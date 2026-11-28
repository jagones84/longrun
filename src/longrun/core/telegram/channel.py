"""Telegram channel — the long-poll listener that makes a DM a Longrun turn.

This is the runtime half of the channel: `__init__.py` is the facade, `client.py`
owns the Bot API, `binding.py` owns the persisted state and `slash.py` owns the
`/` interpretation. Here live the moving parts:

  * `start()` / `stop()` — one daemon thread that long-polls `getUpdates`. Changed
    to polling from TELEGRAM's side, never ours: no public URL, no TLS, no port
    (the DGX sits behind Tailscale), and `deleteWebhook` at boot so a webhook can
    never answer a poll with HTTP 409.
  * the trigger — an authorised message calls `httpapi.start_session_turn`, the
    SAME starter the WebUI route uses, so the bound session `telegram` gets the
    identical transcript, tool cards, events and approvals. Nothing about a turn is
    re-implemented here.
  * the relay — a `core.events` listener forwards this session's `chat.delta`
    ("answer" channel) into a Telegram message it throttles-edits, finalises on
    `chat.done`, and turns each `approval.request` into an inline ✅/❌ keyboard.
  * the pairing gate (OpenClaw-style) — an unknown chat gets a short code, which
    the operator approves; only approved chats drive the agent.

The turn queue is a strict per-channel FIFO (`_pending` + `_pump`): turns are
serialised on the bound session anyway, so one live reply exists at a time and a
delta can never land in the wrong message.
"""
from __future__ import annotations

import collections
import html
import json
import logging
import os
import re
import threading
import time

from longrun.core.telegram import binding, client, slash

log = logging.getLogger(__name__)

_LOCK = threading.RLock()
_thread: "threading.Thread | None" = None
_client: "client.BotClient | None" = None
_stop = threading.Event()
_state = {"running": False, "last_error": "", "bot": {}, "last_update": 0.0,
          "started": 0.0, "updates": 0, "turns": 0}

#: The single in-flight reply (deltas belong to it) and the FIFO feeding it.
_live: dict = {"obj": None}
_pending: "collections.deque" = collections.deque()
_pump_lock = threading.Lock()

_MAX_DESC = 240


# ------------------------------------------------------------------- config --
def _ctx():
    from longrun.model import context_limits
    return context_limits


def _poll_timeout():
    return int(_ctx().telegram("poll_timeout_secs"))


def _edit_throttle():
    return max(0.05, _ctx().telegram("edit_throttle_ms") / 1000.0)


def _max_chars():
    return max(200, _ctx().telegram("max_message_chars"))


def _typing_secs():
    return max(1, _ctx().telegram("typing_heartbeat_secs"))


def _think_preview():
    return max(120, _ctx().telegram("think_preview_chars"))


def _verbose_preview():
    return max(80, _ctx().telegram("verbose_preview_chars"))


def _token():
    return (os.environ.get("TELEGRAM_BOT_TOKEN") or "").strip()


# ------------------------------------------------------------------- status ---
def status():
    """The channel's live state for the WebUI / diagnostics / CLI (never raises)."""
    doc = binding.load()
    with _LOCK:
        st = dict(_state)
        bot = dict(st.get("bot") or {})
        running = bool(st.get("running"))
    return {
        "ok": True,
        "session": binding.SESSION_ID,
        "enabled": bool(doc.get("enabled")),
        "mode": doc.get("mode") or "pairing",
        "token_set": bool(_token()),
        "running": running,
        "bot": bot or (doc.get("bot") or {}),
        "paired": len(doc.get("paired") or []),
        "pending": len(doc.get("pending") or {}),
        "last_update": st.get("last_update") or 0.0,
        "started": st.get("started") or 0.0,
        "updates": st.get("updates") or 0,
        "turns": st.get("turns") or 0,
        "last_error": st.get("last_error") or "",
    }


def commands():
    """The native `/` menu for `setMyCommands` / the Settings panel (from slash.py)."""
    out = []
    seen = set()
    for entry in slash.catalogue():
        cid = str(entry.get("id") or "").lower()
        # Telegram command names: 1-32 chars, [a-z0-9_], start with a letter.
        if not cid or not cid[0].isalpha() or cid in seen:
            continue
        if not all(ch.isalnum() or ch == "_" for ch in cid) or len(cid) > 32:
            continue
        seen.add(cid)
        desc = (entry.get("hint") or entry.get("title") or cid).strip()
        out.append({"command": cid, "description": desc[:_MAX_DESC] or cid})
    # Telegram-ONLY verbs are not in the shared catalogue (the WebUI has no such
    # panes), so the native `/` menu would otherwise hide them. Add them here —
    # one list, still no second catalogue.
    for cid, desc in _tg_only_docs():
        if cid not in seen:
            seen.add(cid)
            out.append({"command": cid, "description": desc[:_MAX_DESC]})
    return out


#: The Telegram-only verbs and the one-line description the native menu shows.
_TG_ONLY_DOCS = (
    ("think", "toggle: show the model's live thinking"),
    ("reason", "toggle: append the chain-of-thought to the answer"),
    ("verbose", "toggle: relay tool calls, results and harness messages"),
    ("stop", "abort the running turn"),
    ("help", "list the commands and the current toggles"),
    ("todo", "list this chat's todos — status and justifications"),
)


def _tg_only_docs():
    return _TG_ONLY_DOCS


# ------------------------------------------------------------- lifecycle ------
def start():
    """Arm the channel when a token is configured (idempotent).

    A FRESH install needs ONE gesture — set `TELEGRAM_BOT_TOKEN` (Settings ▸ Keys or
    `.env`) — and the channel arms itself on the next boot: a token present with NO
    binding file yet IS the operator's intent, so it is onboarded automatically
    (session created; the poller fills the bot identity). A binding file that EXISTS
    with `enabled:false` is respected instead — that is a deliberate logout, or a
    deleted session that must be re-onboarded — so the token alone never re-arms it.
    """
    with _LOCK:
        if _thread is not None and _thread.is_alive():
            return {"ok": True, "running": True, "already": True}
    if not _token():
        return {"ok": True, "running": False, "disabled": True,
                "reason": "TELEGRAM_BOT_TOKEN is not set"}
    doc = binding.load()
    if not binding.exists():
        doc["enabled"] = True
        binding.save(doc)
        _ensure_session()
    elif not doc.get("enabled"):
        return {"ok": True, "running": False, "disabled": True,
                "reason": "channel is off — reconnect it (Settings ▸ Channels)"}
    return _spawn(_token())


def _ensure_session():
    """Make sure the bound Longrun session exists (best effort)."""
    try:
        from longrun.agent import architect as _arch
        _arch.ensure_telegram_session()
    except Exception:  # noqa: BLE001 — created lazily on the first turn too
        pass


def _spawn(token):
    global _thread, _client
    with _LOCK:
        if _thread is not None and _thread.is_alive():
            return {"ok": True, "running": True, "already": True}
        _stop.clear()
        _client = client.BotClient(token, timeout=_poll_timeout() + client.LONGPOLL_SLACK + 5)
        _state["last_error"] = ""
        _thread = threading.Thread(target=_loop, name="tg-poll", daemon=True)
        _thread.start()
        threading.Thread(target=_typing_loop, name="tg-typing", daemon=True).start()
    _attach_listener()
    return {"ok": True, "running": True}


def _typing_loop():
    """Keep the "typing…" action alive for as long as a turn is in flight.

    Telegram's typing action lasts ~5 s, so a single `sendChatAction` at turn
    start vanishes on a long turn and the chat looks dead. This pulses it while
    `_live["obj"]` exists — the SAME object that owns the reply — so the typing
    indicator and the running symbol are driven by one fact, never two.
    """
    while not _stop.is_set():
        live = _live.get("obj")
        if live is not None and _client is not None:
            try:
                _client.send_chat_action(live.chat_id, "typing")
            except Exception:  # noqa: BLE001 — a heartbeat is best-effort
                pass
        if _stop.wait(_typing_secs()):
            break


def stop():
    """Stop the long-poll thread and detach the relay (idempotent, never raises)."""
    _stop.set()
    with _LOCK:
        t = _thread
    if t is not None and t.is_alive():
        try:
            t.join(timeout=float(_poll_timeout()) + 5.0)
        except Exception:  # noqa: BLE001
            pass
    _detach_listener()
    with _LOCK:
        _state["running"] = False
    _pending.clear()
    _live["obj"] = None
    return {"ok": True, "running": False}


def reconnect():
    """Re-read the environment and (re)arm the channel — token change, re-arm.

    Same contract as `start()`: a first run (no binding file) onboards from the
    token; an existing `enabled:false` binding is respected.
    """
    stop()
    return start()


def logout():
    """Forget the bot + pairing and stop: the channel needs re-onboarding."""
    stop()
    binding.reset()
    with _LOCK:
        _state["bot"] = {}
    return {"ok": True, "running": False, "logged_out": True}


# ------------------------------------------------------------- onboarding -----
def setup(token, owner_chat_id=None):
    """Onboarding: validate the token with `getMe`, persist it, create the session.

    The token is written to the repo `.env` through `model.keys.set_key` — the SAME
    path as every other key, so it is settable from Settings ▸ Keys and visible to
    diagnostics — and also exported in-process so a running channel picks it up.
    """
    token = str(token or "").strip()
    if not token:
        return {"ok": False, "error": "token required"}
    probe = client.BotClient(token, timeout=30.0)
    try:
        me = probe.get_me()
    except Exception as exc:  # noqa: BLE001 — the operator sees WHY it was refused
        return {"ok": False, "error": "getMe failed: %s" % exc}
    if not isinstance(me, dict) or not me.get("id"):
        return {"ok": False, "error": "getMe returned no bot identity"}
    try:
        from longrun.model import keys as _keys
        res = _keys.set_key("TELEGRAM_BOT_TOKEN", token)
        if isinstance(res, dict) and res.get("error"):
            return {"ok": False, "error": "could not save token: %s" % res["error"]}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": "could not save token: %s" % exc}
    os.environ["TELEGRAM_BOT_TOKEN"] = token
    _ensure_session()
    doc = binding.load()
    doc["enabled"] = True
    doc["bot"] = {"id": me.get("id"), "username": me.get("username") or "",
                  "first_name": me.get("first_name") or ""}
    if owner_chat_id is not None:
        binding.upsert_paired(doc, owner_chat_id, title="owner")
    binding.save(doc)
    out = reconnect()
    return {"ok": True, "bot": doc["bot"], "session": binding.SESSION_ID,
            "running": bool(out.get("running"))}


def pair(code):
    """Approve a pending pairing code: authorise that chat to drive the agent."""
    doc = binding.load()
    rec = binding.take_pending(doc, code)
    binding.save(doc)   # persist the purge even when the code is unknown/expired
    if not rec:
        return {"ok": False, "error": "unknown or expired pairing code"}
    binding.upsert_paired(doc, rec.get("chat_id"), user_id=rec.get("user_id"),
                          username=rec.get("username") or "")
    binding.save(doc)
    try:
        _notify(rec.get("chat_id"),
                "✅ Paired with Longrun. Send a message to talk to the agent; "
                "type / to see the commands.")
    except Exception:  # noqa: BLE001 — telling the user is best-effort
        pass
    return {"ok": True, "chat_id": rec.get("chat_id")}


def unpair(chat_id=None):
    """Revoke one chat (or every chat) — the bot stops answering it."""
    doc = binding.load()
    binding.remove_paired(doc, chat_id)
    binding.save(doc)
    return {"ok": True, "paired": len(doc.get("paired") or [])}


def on_session_deleted(sid):
    """Hook from the session delete: clear the binding ⇒ the channel must re-onboard."""
    if str(sid or "").strip() != binding.SESSION_ID:
        return False
    try:
        stop()
    except Exception:  # noqa: BLE001
        pass
    binding.reset()
    with _LOCK:
        _state["bot"] = {}
    return True


# ---------------------------------------------------------------- poll loop ---
def _loop():
    cli = _client
    with _LOCK:
        _state["running"] = True
        _state["started"] = time.time()
    try:
        me = cli.get_me()
        if isinstance(me, dict):
            with _LOCK:
                _state["bot"] = {"id": me.get("id"),
                                 "username": me.get("username") or "",
                                 "first_name": me.get("first_name") or ""}
    except Exception as exc:  # noqa: BLE001 — reported, the loop still tries updates
        with _LOCK:
            _state["last_error"] = "getMe: %s" % str(exc)[:200]
    try:
        cli.delete_webhook()   # polling and webhook are mutually exclusive (Telegram 409)
    except Exception:  # noqa: BLE001 — best effort; getUpdates reports the rest
        pass
    _publish_commands(cli)

    doc = binding.load()
    last = doc.get("last_update_id") or 0
    offset = int(last) + 1 if last else None
    while not _stop.is_set():
        try:
            updates = cli.get_updates(offset=offset, timeout=_poll_timeout(),
                                      allowed_updates=_ctx().telegram_list("allowed_updates"))
        except Exception as exc:  # noqa: BLE001 — a dead poll backs off, never dies
            with _LOCK:
                _state["last_error"] = str(exc)[:200]
            if _stop.wait(3.0):
                break
            continue
        # 2026-11-28: the first batch is handled NORMALLY. It used to be dropped to
        # skip a pre-onboarding backlog, but that also threw away a real message sent
        # right after start (the operator DMs, nothing happens, "it's broken"). A DM
        # from an unknown chat simply gets the pairing prompt, so nothing is lost.
        for update in updates or []:
            uid = update.get("update_id")
            try:
                _handle_update(update)
            except Exception as exc:  # noqa: BLE001 — one bad update must not stop the loop
                with _LOCK:
                    _state["last_error"] = "handle: %s" % str(exc)[:200]
            if isinstance(uid, int):
                offset = uid + 1
                _persist_offset(uid)
            with _LOCK:
                _state["last_update"] = time.time()
                _state["updates"] += 1
    with _LOCK:
        _state["running"] = False


def _persist_offset(uid):
    try:
        doc = binding.load()
        doc["last_update_id"] = int(uid)
        binding.save(doc)
    except Exception:  # noqa: BLE001 — losing a cursor only replays one update
        pass


def _publish_commands(cli):
    cmds = commands()
    if not cmds:
        return
    try:
        cli.set_my_commands(cmds)
    except Exception:  # noqa: BLE001 — the menu is a nicety, not a gate
        pass


# ---------------------------------------------------------------- updates -----
def _handle_update(update):
    cq = update.get("callback_query")
    if cq:
        return _handle_callback(cq)
    msg = update.get("message") or update.get("edited_message")
    if not isinstance(msg, dict):
        return
    chat = msg.get("chat") or {}
    chat_id = chat.get("id")
    if chat_id is None:
        return
    doc = binding.load()
    if not binding.is_paired(doc, chat_id):
        return _pairing_prompt(doc, msg, chat_id)
    # Remember the last chat that talked: it is where a turn the channel did NOT
    # start (restart continuation, job, dispatch) will be shown, so Telegram stays
    # in sync with the bound session.
    binding.set_active_chat(doc, chat_id)
    binding.save(doc)
    text = msg.get("text") or msg.get("caption") or ""
    # 2026-11-28: a reply to OUR ForceReply prompt answers THAT question — a search
    # keyword, or the request for a skill/plugin to activate — never a fresh turn.
    reply = msg.get("reply_to_message") or {}
    rid = reply.get("message_id") if isinstance(reply, dict) else None
    with _prompts_lock:
        pend = _prompts.get(chat_id)
    if pend and rid is not None and str(rid) == str(pend.get("mid")) and text.strip():
        with _prompts_lock:
            _prompts.pop(chat_id, None)
        return _answer_prompt(chat_id, pend, text.strip(), msg.get("message_id"))
    if not text.strip():
        return
    _dispatch(chat_id, text, msg.get("message_id"))


def _pairing_prompt(doc, msg, chat_id):
    if doc.get("mode") != "pairing":
        _notify(chat_id, "This bot is not accepting new users.")
        return
    frm = msg.get("from") or {}
    ttl = _ctx().telegram("pair_code_ttl_secs")
    # Reuse a LIVE code for THIS chat: several messages before the operator approves
    # must yield ONE code, not one per message (which would print a new code each time).
    now = time.time()
    code = None
    for cand, rec in (doc.get("pending") or {}).items():
        if (str((rec or {}).get("chat_id")) == str(chat_id)
                and now - float((rec or {}).get("ts") or 0) <= float(ttl)):
            code = cand
            break
    if code is None:
        code = binding.new_code(doc, chat_id, user_id=frm.get("id"),
                                username=frm.get("username") or "", ttl=ttl)
    binding.save(doc)
    _notify(chat_id,
            "Pairing required.\nYour code: %s\n\nApprove it in Longrun — Settings ▸ "
            "Channels ▸ Approve, or `python3 forge.py telegram pair %s`. It expires "
            "in %d minutes." % (code, code, max(1, int(ttl) // 60)))
    try:
        from longrun.core import events as _events
        _events.publish("telegram.pair", session=binding.SESSION_ID, code=code,
                        chat_id=chat_id, username=frm.get("username") or "")
    except Exception:  # noqa: BLE001 — surfacing the code is best-effort
        pass


def _handle_callback(cq):
    cq_id = cq.get("id")
    data = str(cq.get("data") or "")
    chat = (cq.get("message") or {}).get("chat") or {}
    chat_id = chat.get("id")
    doc = binding.load()
    if not binding.is_paired(doc, chat_id):
        _answer_callback(cq_id, "Not authorised.")
        return
    binding.set_active_chat(doc, chat_id)
    binding.save(doc)
    if data.startswith("mdl:"):
        mid = (cq.get("message") or {}).get("message_id")
        _answer_callback(cq_id, "")
        _handle_model_callback(chat_id, mid, data)
        return
    if data.startswith("skl:"):
        mid = (cq.get("message") or {}).get("message_id")
        _answer_callback(cq_id, "")
        _handle_skill_callback(chat_id, mid, data)
        return
    if data.startswith("plg:"):
        mid = (cq.get("message") or {}).get("message_id")
        _answer_callback(cq_id, "")
        _handle_plugin_callback(chat_id, mid, data)
        return
    if not (data.startswith("ap:") or data.startswith("dn:")):
        _answer_callback(cq_id, "")
        return
    aid = data[3:]
    approve = data.startswith("ap:")
    rec = None
    try:
        from longrun.tools import approvals as _ap
        rec = _ap.decide(aid, "approve" if approve else "deny", by="telegram")
    except Exception:  # noqa: BLE001
        rec = None
    if not rec:
        _answer_callback(cq_id, "Unknown or already decided.")
        return
    _answer_callback(cq_id, "Approved" if approve else "Denied")
    # replace the keyboard with the outcome so a second tap cannot re-decide
    mid = (cq.get("message") or {}).get("message_id")
    if mid:
        try:
            _client.edit_message_text(
                chat_id, mid,
                "%s %s" % ("✅ approved" if approve else "❌ denied", aid),
                keyboard=[])
        except Exception:  # noqa: BLE001
            pass


# ---------------------------------------------------------------- dispatch ----
#: Commands that exist ONLY in Telegram (they change what the CHANNEL shows, never
#: the Longrun session), so they are handled here and never reach the shared
#: catalogue or a model turn. `/models`, `/plan`, `/status`, … stay in the ONE
#: catalogue (`core.slash.BUILTINS`) exactly like the WebUI.
TG_ONLY = ("think", "reason", "verbose", "help", "stop", "todo")


def _rest(text):
    """The argument text after a leading `/token` (trimmed edges)."""
    head = str(text or "").lstrip()
    _, _, rest = head[1:].partition(" ")
    return rest.strip()


def _dispatch(chat_id, text, msg_id):
    token = slash.token_of(text)
    if token in TG_ONLY:
        _spawn_worker(lambda: _handle_tg_only(chat_id, token, _rest(text)))
        return
    plan = slash.interpret(text)
    kind = plan.get("kind")
    if kind == "ui":
        action = str(plan.get("action") or "")
        if action == "models":
            # `/models` opens the provider ▸ model keyboard, not a prose reply.
            _spawn_worker(lambda: _show_providers(chat_id))
            return
        if action == "skills":
            # 2026-11-28: `/skills [keyword]` opens the SEARCHABLE skill keyboard
            # (the WebUI's Skills picker twin), not a prose list.
            _kw = plan.get("message") or ""
            _spawn_worker(lambda: _show_skills(chat_id, _kw))
            return
        if action == "plugins":
            _spawn_worker(lambda: _show_plugins(chat_id))
            return
        _spawn_worker(lambda: _reply(chat_id, _run_ui(action, plan.get("message"))))
        return
    if kind == "doc":
        _spawn_worker(lambda: _reply(chat_id, _run_doc(plan.get("doc"), plan.get("message"))))
        return
    _enqueue(chat_id, plan.get("message") or text, plan.get("mode") or "", msg_id)


def _spawn_worker(fn):
    threading.Thread(target=fn, name="tg-work", daemon=True).start()


# ---------------------------------------------------- Telegram-only commands --
def _onoff(value):
    return "ON" if value else "OFF"


def _parse_bool(arg, default):
    """True/False from `on|off|1|0|…`; anything else keeps `default` (a toggle)."""
    a = str(arg or "").strip().lower()
    if a in ("on", "1", "true", "yes", "enable", "enabled"):
        return True
    if a in ("off", "0", "false", "no", "disable", "disabled"):
        return False
    return bool(default)


def _handle_tg_only(chat_id, token, arg):
    """`/think` `/reason` `/verbose` `/help` `/stop` — Telegram-ONLY, no turn.

    The three toggles change what the CHANNEL relays; they never touch the
    Longrun session (the operator asked for that explicitly). `/stop` aborts the
    in-flight turn through the SAME steering flag the WebUI Stop uses.
    """
    if token == "stop":
        try:
            from longrun.util import steering
            steering.push_abort(binding.SESSION_ID)
            _notify(chat_id, "⏹ stop requested — the turn will end at the next step.")
        except Exception as exc:  # noqa: BLE001
            _notify(chat_id, "⚠️ /stop failed: %s" % exc)
        return
    if token == "help":
        _reply(chat_id, _help_text(), parse_mode="HTML")
        return
    if token == "todo":
        # 2026-11-28: EVERY current todo (open + closed) with its status and
        # justification, rendered as a readable Telegram card (icons, bold ids and
        # collapsible evidence) instead of the prompt's dense block.
        _reply(chat_id, _fmt_todos(binding.SESSION_ID), parse_mode="HTML")
        return
    doc = binding.load()
    current = binding.prefs(doc)
    value = _parse_bool(arg, not current.get(token))
    binding.set_pref(doc, token, value)
    binding.save(doc)
    label = {"think": "💭 thinking", "reason": "🧠 reasoning",
             "verbose": "🔎 verbose"}.get(token, token)
    text = "%s is now %s." % (label, _onoff(value))
    # 2026-11-28 (operator: "il reason slash non mostra in telegram il thought!!!
    # con menu di chiusura espansione"): switching `/reason` ON shows the LAST
    # chain-of-thought at once, in a collapsible block — the operator sees the
    # feature work instead of a bare "on" and having to wait a turn.
    if token == "reason" and value:
        last = _last_reasoning()
        if last:
            text += "\n\n" + _quote_html("🧠 last reasoning", last,
                                         cap=_reasoning_cap())
        else:
            text += "\n<i>no reasoning stored yet — it will appear with the next answer</i>"
    _reply(chat_id, text, parse_mode="HTML")


def _help_text():
    """`/help` — the command list as a readable card (grouped, one block per kind)."""
    ids = [str(e.get("id")) for e in slash.catalogue()]
    shared = " · ".join("/" + i for i in ids)
    p = binding.prefs(binding.load())
    return ("📖 <b>Commands</b> <i>(same as the Longrun chat)</i>\n"
            "%s\n\n"
            "<b>Telegram-only</b>\n"
            "/think %s — show the model's live thinking\n"
            "/reason %s — append the chain-of-thought\n"
            "/verbose %s — relay tool calls and harness messages\n"
            "/stop — abort the running turn\n"
            "/todo — this chat's todos (status + justification)\n"
            "/help — this card\n\n"
            "<b>Menus</b>\n"
            "/skills [keyword] — browse/search the skills, then ▶️ use one\n"
            "/plugins — browse the installed plugins\n"
            "/models — choose a provider ▸ model"
            % (shared, _onoff(p["think"]), _onoff(p["reason"]), _onoff(p["verbose"])))


# ------------------------------------------------------ /models (provider ▸) --
def _page_size():
    return max(1, _ctx().telegram("models_page_size"))


def _catalog():
    """The SAME provider/model catalogue the WebUI picker reads (one backend)."""
    from longrun.core import httpapi
    try:
        return httpapi.providers_catalog() or {}
    except Exception:  # noqa: BLE001 — a catalogue hiccup is a chat message
        return {"providers": [], "error": "catalogue unavailable"}


def _providers():
    return [p for p in (_catalog().get("providers") or []) if p.get("id")]


def _current_model():
    try:
        from longrun.memory import stores
        return str((stores.load_session(binding.SESSION_ID) or {}).get("model") or "")
    except Exception:  # noqa: BLE001
        return ""


def _kb(rows):
    return rows or None


def _show_providers(chat_id, page=0, message_id=None):
    """Send (or re-render) the provider keyboard of `/models`."""
    provs = _providers()
    size = _page_size()
    page = max(0, int(page or 0))
    total_pages = max(1, (len(provs) + size - 1) // size)
    page = min(page, total_pages - 1)
    start = page * size
    rows = []
    for i in range(start, min(start + size, len(provs))):
        p = provs[i]
        n = len(p.get("models") or [])
        mark = " · local" if p.get("local") else ""
        if not p.get("configured"):
            mark += " · no key"
        elif p.get("reachable") is False:
            mark += " · unreachable"
        rows.append([{"text": "%s%s (%d)" % (p.get("name") or p["id"], mark, n),
                      "callback_data": "mdl:models:%d:0" % i}])
    nav = []
    if page > 0:
        nav.append({"text": "‹ prev", "callback_data": "mdl:prov:%d" % (page - 1)})
    if total_pages > 1:
        nav.append({"text": "%d/%d" % (page + 1, total_pages), "callback_data": "mdl:prov:%d" % page})
    if page < total_pages - 1:
        nav.append({"text": "next ›", "callback_data": "mdl:prov:%d" % (page + 1)})
    if nav:
        rows.append(nav)
    cur = _current_model() or "(default)"
    text = ("🧩 <b>Choose a provider</b>\ncurrent model: <code>%s</code>"
            % html.escape(cur))
    _send_or_edit(chat_id, message_id, text, _kb(rows))


def _show_models(chat_id, message_id, prov_index, page=0):
    """Re-render one provider's model list on the SAME message (Back + pages)."""
    provs = _providers()
    prov_index = int(prov_index)
    if prov_index < 0 or prov_index >= len(provs):
        return _show_providers(chat_id, 0, message_id)
    p = provs[prov_index]
    models = p.get("models") or []
    size = _page_size()
    page = max(0, int(page or 0))
    total_pages = max(1, (len(models) + size - 1) // size)
    page = min(page, total_pages - 1)
    start = page * size
    cur = _current_model()
    rows = []
    for j in range(start, min(start + size, len(models))):
        m = models[j]
        label = str(m.get("id") or "")
        if m.get("loaded"):
            label = "● " + label
        if m.get("ref") == cur:
            label = "✓ " + label
        rows.append([{"text": label[:60],
                      "callback_data": "mdl:pick:%d:%d" % (prov_index, j)}])
    nav = []
    if page > 0:
        nav.append({"text": "‹", "callback_data": "mdl:models:%d:%d" % (prov_index, page - 1)})
    if total_pages > 1:
        nav.append({"text": "%d/%d" % (page + 1, total_pages),
                    "callback_data": "mdl:models:%d:%d" % (prov_index, page)})
    if page < total_pages - 1:
        nav.append({"text": "›", "callback_data": "mdl:models:%d:%d" % (prov_index, page + 1)})
    if nav:
        rows.append(nav)
    rows.append([{"text": "« providers", "callback_data": "mdl:prov:0"}])
    text = ("🧩 <b>%s</b> — choose a model\ncurrent model: <code>%s</code>"
            % (html.escape(p.get("name") or p["id"]), html.escape(cur or "(default)")))
    _send_or_edit(chat_id, message_id, text, _kb(rows))


def _pick_model(chat_id, message_id, prov_index, model_index):
    """Set the per-session model through the ONE writer (`_set_session_model`)."""
    provs = _providers()
    prov_index = int(prov_index)
    if prov_index < 0 or prov_index >= len(provs):
        return _show_providers(chat_id, 0, message_id)
    models = provs[prov_index].get("models") or []
    model_index = int(model_index)
    if model_index < 0 or model_index >= len(models):
        return _show_models(chat_id, message_id, prov_index, 0)
    ref = str(models[model_index].get("ref") or "")
    try:
        from longrun.memory import stores
        stores._set_session_model(binding.SESSION_ID, ref)
    except Exception as exc:  # noqa: BLE001
        return _send_or_edit(chat_id, message_id,
                             "⚠️ could not set the model: %s" % html.escape(str(exc)), None)
    _send_or_edit(chat_id, message_id,
                  "✅ model set to <code>%s</code> for this chat." % html.escape(ref),
                  None)


def _handle_model_callback(chat_id, message_id, data):
    """Route one `mdl:` callback — parse only, delegate to the renderers."""
    parts = str(data or "").split(":")
    try:
        if len(parts) >= 3 and parts[1] == "prov":
            _show_providers(chat_id, int(parts[2]), message_id)
        elif len(parts) >= 4 and parts[1] == "models":
            _show_models(chat_id, message_id, int(parts[2]), int(parts[3]))
        elif len(parts) >= 4 and parts[1] == "pick":
            _pick_model(chat_id, message_id, int(parts[2]), int(parts[3]))
    except (ValueError, IndexError):
        pass


def _send_or_edit(chat_id, message_id, text, keyboard):
    """Send a formatted message, or edit `message_id` in place when there is one."""
    try:
        if message_id is None:
            _client.send_message(chat_id, text, keyboard=keyboard, parse_mode="HTML")
        else:
            _client.edit_message_text(chat_id, message_id, text, keyboard=keyboard,
                                      parse_mode="HTML")
    except Exception:  # noqa: BLE001 — a menu that fails must not kill the channel
        pass


# ---------------------------------------------------- /skills + /plugins -----
# 2026-11-28 (operator: "su telegram slash skills non fa nulla … dovrebbe aprire
# un menu con skills con ricerca by keyword che le filtra dal menu, proprio come
# per la sessione Longrun WebUI"). These are the SERVER-SIDE twins of the WebUI's
# `openSkillMenu`/`openPluginMenu`: the same data (`memory.skills.list_skills`,
# `slash.plugins`) rendered as an inline keyboard. Telegram keyboards carry no text
# box, so the keyword search is a ForceReply: tap 🔎 Search (or send `/skills <kw>`),
# type the keyword, and the SAME list is re-rendered filtered. A tap on a skill (or a
# plugin member) sends a second ForceReply asking for the request, and the reply runs
# `/<skill> <request>` (or `/plugin:<name> <request>`) as a REAL turn — the skill is
# ACTIVATED in the chat context by `agent._apply_skill_slash`, never just described.
_prompts: dict = {}                       # chat_id -> {"mid", "kind", "skill", "plugin"}
_prompts_lock = threading.RLock()


def _ask(chat_id, text, placeholder, kind, skill="", plugin=""):
    """Send a ForceReply prompt and REMEMBER it, so the very next reply from this chat
    answers THIS question instead of starting an agent turn (a reply carries
    `reply_to_message`, which is how the poller tells an answer from a fresh message)."""
    if _client is None:
        return None
    mid = None
    try:
        sent = _client.send_message(
            chat_id, text, parse_mode="HTML",
            reply_markup={"force_reply": True, "selective": True,
                          "input_field_placeholder": str(placeholder)[:64]})
        mid = (sent or {}).get("message_id")
    except Exception:  # noqa: BLE001 — a prompt must never kill the channel
        return None
    if mid is not None:
        with _prompts_lock:
            _prompts[chat_id] = {"mid": mid, "kind": kind, "skill": skill,
                                 "plugin": plugin}
    return mid


def _answer_prompt(chat_id, pend, text, msg_id):
    """Execute the answer to a ForceReply prompt (search, or skill/plugin activation)."""
    kind = str(pend.get("kind") or "")
    if kind == "skills-search":
        return _spawn_worker(lambda: _show_skills(chat_id, text))
    if kind == "plugins-search":
        return _spawn_worker(lambda: _show_plugins(chat_id, kw=text))
    if kind == "skill-use":
        return _enqueue(chat_id, "/%s %s" % (pend.get("skill") or "", text), "", msg_id)
    if kind == "plugin-use":
        return _enqueue(chat_id, "/plugin:%s %s" % (pend.get("plugin") or "", text),
                        "", msg_id)
    return None


def _skills_page_size():
    return max(1, _ctx().telegram("skills_page_size"))


def _all_skills():
    """The SAME skill list the WebUI's Skills panel reads (the `/api/skills` source)."""
    from longrun.memory import skills as _sk
    try:
        return _sk.list_skills() or []
    except Exception:  # noqa: BLE001 — a menu must render
        return []


def _filter_skills(items, kw):
    """Case-insensitive keyword match over name/title/category/description.

    Several words are an AND (`pdf monster` matches a skill whose haystack holds both),
    so a multi-word search narrows instead of failing.
    """
    words = [w for w in str(kw or "").lower().split() if w]
    if not words:
        return list(items)
    out = []
    for s in items:
        hay = " ".join(str(s.get(k) or "") for k in
                       ("name", "title", "category", "description")).lower()
        if all(w in hay for w in words):
            out.append(s)
    return out


def _nav_row(page, total_pages, prefix, kw=""):
    """A ‹ / p/total / › row for a paginated keyboard (`prefix` = `skl:p`/`plg:p`)."""
    nav = []
    if page > 0:
        nav.append({"text": "‹", "callback_data": "%s:%d:%s" % (prefix, page - 1, kw)})
    if total_pages > 1:
        nav.append({"text": "%d/%d" % (page + 1, total_pages),
                    "callback_data": "%s:%d:%s" % (prefix, page, kw)})
    if page < total_pages - 1:
        nav.append({"text": "›", "callback_data": "%s:%d:%s" % (prefix, page + 1, kw)})
    return [nav] if nav else []


def _show_skills(chat_id, kw="", page=0, message_id=None):
    """`/skills [keyword]` — the searchable skill menu (see the section comment)."""
    every = _all_skills()
    if not every:
        return _send_or_edit(chat_id, message_id,
                             "🧩 <b>Skills</b> — none installed.", None)
    items = _filter_skills(every, kw)
    kw_s = str(kw or "")[:40]
    size = _skills_page_size()
    total = max(1, (len(items) + size - 1) // size)
    page = max(0, min(int(page or 0), total - 1))
    rows = []
    start = page * size
    for i in range(start, min(start + size, len(items))):
        name = str(items[i].get("name") or "?")
        rows.append([{"text": (name if len(name) <= 48 else name[:47] + "…"),
                      "callback_data": "skl:s:%d:%s" % (i, kw_s)}])
    rows += _nav_row(page, total, "skl:p", kw_s)
    # The 🔎 button is the SEARCH door: it replies ForceReply, so the operator types a
    # keyword and the SAME menu re-renders filtered (Telegram keyboards have no box).
    rows.append([{"text": "🔎 Search", "callback_data": "skl:q:"}])
    head = "🧩 <b>Skills</b> — %d shown of %d" % (len(items), len(every))
    if kw_s.strip():
        head += " · filter <code>%s</code>" % html.escape(kw_s.strip())
    else:
        head += (" — tap 🔎 Search or send <code>/skills &lt;keyword&gt;</code>")
    head += "\nTap a skill to see it and USE it."
    if not items:
        head += "\n\nNo skill matches — try another keyword."
    _send_or_edit(chat_id, message_id, head, _kb(rows))


def _show_one_skill(chat_id, message_id, idx, kw):
    """One skill's card + the ▶️ Use button that ACTIVATES it in a real turn."""
    items = _filter_skills(_all_skills(), kw)
    if idx < 0 or idx >= len(items):
        return _show_skills(chat_id, kw, 0, message_id)
    s = items[idx]
    name = str(s.get("name") or "")
    text = ("🧩 <b>%s</b>\n<code>%s</code>\n%s\n\ncategory: <code>%s</code>\n\n"
            "▶️ Use it: I will ask for your request, then run it in this chat with "
            "the skill activated."
            % (html.escape(str(s.get("title") or name)), html.escape(name),
               html.escape(str(s.get("description") or "(no description)")),
               html.escape(str(s.get("category") or "-"))))
    kw_s = str(kw or "")[:40]
    keyboard = [[{"text": "▶️ Use in this chat",
                  "callback_data": "skl:u:%d:%s" % (idx, kw_s)}],
                [{"text": "‹ back to list", "callback_data": "skl:p:0:%s" % kw_s}]]
    _send_or_edit(chat_id, message_id, text, keyboard)


def _handle_skill_callback(chat_id, message_id, data):
    """Route one `skl:` callback — parse only, delegate to the renderers."""
    parts = str(data or "").split(":", 3)
    sub = parts[1] if len(parts) > 1 else ""
    arg, kw = (parts[2] if len(parts) > 2 else "0"), (parts[3] if len(parts) > 3 else "")
    if sub == "q":
        return _ask(chat_id, "🔎 Send a keyword to filter the skills — e.g. "
                             "<code>pdf</code>, <code>diagram</code>, <code>android</code>.",
                    "keyword", "skills-search")
    try:
        n = int(arg)
    except ValueError:
        n = -1
    if sub == "s":
        return _show_one_skill(chat_id, message_id, n, kw)
    if sub == "u":
        items = _filter_skills(_all_skills(), kw)
        if 0 <= n < len(items):
            name = str(items[n].get("name") or "")
            return _ask(chat_id, "▶️ Send your request for <b>%s</b> — I will run it in "
                                 "this chat with that skill activated." % html.escape(name),
                        "your request", "skill-use", skill=name)
        return _show_skills(chat_id, kw, 0, message_id)
    return _show_skills(chat_id, kw, max(0, n), message_id)


def _plugins_safe():
    """The installed plugin bundles, or [] — the SAME reader the WebUI's menu uses."""
    from longrun.core import slash as _slash
    try:
        return _slash.plugins() or []
    except Exception:  # noqa: BLE001 — a menu must render
        return []


def _filter_plugins(plugins, kw):
    """AND of keywords over name/title/description (the skill filter's twin)."""
    words = [w for w in str(kw or "").lower().split() if w]
    if not words:
        return list(plugins)
    out = []
    for p in plugins:
        hay = " ".join(str(p.get(k) or "") for k in
                       ("name", "title", "description")).lower()
        if all(w in hay for w in words):
            out.append(p)
    return out


def _cb(data):
    """`(ns, sub, a, b, kw, _)` from a callback token, padded so `:` never breaks it."""
    p = str(data or "").split(":", 5)
    return (p + [""] * 6)[:6]


def _show_plugins(chat_id, page=0, message_id=None, kw=""):
    """`/plugins` — the installed plugin bundles as a searchable keyboard."""
    every = _plugins_safe()
    if not every:
        return _send_or_edit(chat_id, message_id,
                             "🧩 <b>Plugins</b> — none installed. Install one from "
                             "Longrun ▸ Marketplace ▸ Plugins.", None)
    items = _filter_plugins(every, kw)
    kw_s = str(kw or "")[:40]
    size = _page_size()
    total = max(1, (len(items) + size - 1) // size)
    page = max(0, min(int(page or 0), total - 1))
    rows = []
    start = page * size
    for i in range(start, min(start + size, len(items))):
        p = items[i]
        label = str(p.get("name") or "?")
        rows.append([{"text": "%s (%d)" % (label[:44], len(p.get("members") or [])),
                      "callback_data": "plg:s:%d:%s" % (i, kw_s)}])
    rows += _nav_row(page, total, "plg:p", kw_s)
    rows.append([{"text": "🔎 Search", "callback_data": "plg:q:"}])
    head = "🧩 <b>Plugins</b> — %d shown of %d" % (len(items), len(every))
    if kw_s.strip():
        head += " · filter <code>%s</code>" % html.escape(kw_s.strip())
    head += "\nTap one to see its members and USE it."
    if not items:
        head += "\n\nNo plugin matches — try another keyword."
    _send_or_edit(chat_id, message_id, head, _kb(rows))


def _show_one_plugin(chat_id, message_id, idx, kw):
    """One plugin's manifest + ▶️ Use + a ▶️ button per member skill."""
    items = _filter_plugins(_plugins_safe(), kw)
    if idx < 0 or idx >= len(items):
        return _show_plugins(chat_id, 0, message_id, kw)
    p = items[idx]
    from longrun.core import slash as _slash
    try:
        block = _slash.plugin_block(str(p.get("name") or "")) or ""
    except Exception:  # noqa: BLE001
        block = ""
    if not block:
        block = str(p.get("state_line") or p.get("description") or "")
    text = ("🧩 <b>%s</b>\n%s"
            % (html.escape(str(p.get("title") or p.get("name") or "")),
               html.escape(block[:3000])))
    kw_s = str(kw or "")[:40]
    keyboard = [[{"text": "▶️ Use this plugin",
                  "callback_data": "plg:u:%d:%s" % (idx, kw_s)}]]
    for j, m in enumerate(p.get("members") or []):
        if str(m.get("kind") or "") == "skill":
            keyboard.append([{"text": "▶️ skill: %s" % str(m.get("name") or "")[:36],
                              "callback_data": "plg:m:%d:%d:%s" % (idx, j, kw_s)}])
    keyboard.append([{"text": "‹ back", "callback_data": "plg:p:0:%s" % kw_s}])
    _send_or_edit(chat_id, message_id, text, keyboard)


def _handle_plugin_callback(chat_id, message_id, data):
    """Route one `plg:` callback — parse only, delegate to the renderers."""
    _ns, sub, a, b, kw, _ = _cb(data)
    items = _filter_plugins(_plugins_safe(), kw)
    try:
        n = int(a)
    except ValueError:
        n = -1
    if sub == "q":
        return _ask(chat_id, "🔎 Send a keyword to filter the plugins.",
                    "keyword", "plugins-search")
    if sub == "m":                       # a member SKILL of this plugin -> activate it
        try:
            mi = int(b)
        except ValueError:
            mi = -1
        members = items[n].get("members") if 0 <= n < len(items) else None
        if members and 0 <= mi < len(members) \
                and str(members[mi].get("kind") or "") == "skill":
            name = str(members[mi].get("name") or "")
            return _ask(chat_id, "▶️ Send your request for <b>%s</b> — I will run it "
                                 "with that skill activated." % html.escape(name),
                        "your request", "skill-use", skill=name)
        return _show_plugins(chat_id, 0, message_id, kw)
    if sub == "u":                       # activate the WHOLE plugin
        if 0 <= n < len(items):
            name = str(items[n].get("name") or "")
            return _ask(chat_id, "▶️ Send your request for plugin <b>%s</b> — I will "
                                 "run it with the whole plugin activated."
                        % html.escape(name), "your request", "plugin-use", plugin=name)
        return _show_plugins(chat_id, 0, message_id, kw)
    if sub == "s":
        return _show_one_plugin(chat_id, message_id, n, kw)
    return _show_plugins(chat_id, max(0, n), message_id, kw)


# ------------------------------------------------------- UI / doc commands ----
def _run_ui(action, message=""):
    """/compact /status /reset /new /unlock /context /restart — the SAME backends
    the WebUI composer calls, executed on the bound session."""
    action = str(action or "").lower()
    sid = binding.SESSION_ID
    try:
        if action == "compact":
            from longrun.core import httpapi
            res = httpapi.compact_session(sid, origin="manual") or {}
            if res.get("error"):
                return "⚠️ compact: %s" % res["error"]
            if res.get("aborted"):
                return "⏹ compaction aborted — context unchanged."
            # 2026-11-28: the numbered marker is published on `context.compact` and
            # relayed by `_on_event`, so returning "" here gives ONE message, not two.
            # No marker (nothing was compacted) still gets an honest one-liner.
            return "" if res.get("marker") else "🗜 nothing to compact in this chat."
        if action == "reset":
            from longrun.memory import stores
            stores.clear_session(sid)
            return "♻️ this chat has been reset (the same session and workspace stay)."
        if action == "new":
            return ("This bot is bound to the single Longrun session "
                    "<code>%s</code>, so there is no second chat to open here. "
                    "Use /reset to clear THIS one." % _esc(sid))
        if action == "context":
            from longrun.core import httpapi
            return _fmt_context(httpapi.context_status(sid, None) or {})
        if action == "status":
            return _fmt_status(sid)
        if action == "restart":
            from longrun.core import restart
            res = restart.schedule_restart(session_id=sid, reason="telegram /restart") or {}
            return "🔄 restart %s." % ("accepted" if res.get("ok", True) else "refused")
        if action == "unlock":
            from longrun.plan import docs
            res = docs.unlock(sid) or {}
            return "🔓 %s" % (res.get("error") or "unlocked — the write gate is open.")
        return "Unknown command: /%s" % action
    except Exception as exc:  # noqa: BLE001 — a command failure is a chat message
        return "⚠️ /%s failed: %s" % (action, exc)


def _run_doc(kind, message):
    """/plan and /spec — the SAME document backend as the composer and the CLI."""
    kind = str(kind or "plan").lower()
    if not str(message or "").strip():
        return "usage: /%s <what to write>" % kind
    try:
        from longrun.plan import docs
        if kind == "spec":
            res = docs.create_spec(binding.SESSION_ID, message) or {}
        else:
            res = docs.create_plan(binding.SESSION_ID, message) or {}
    except Exception as exc:  # noqa: BLE001
        return "⚠️ /%s failed: %s" % (kind, exc)
    if res.get("error"):
        return "⚠️ /%s: %s" % (kind, res["error"])
    return ("📄 <b>%s</b> written for <code>%s</code>\n"
            "<i>review it in Longrun — the composer bar shows the document</i>"
            % (_esc(kind), _esc(binding.SESSION_ID)))


#: The status vocabulary as ONE set of icons (the same marks the plan UI draws).
_TODO_ICON = {"todo": "⚪", "doing": "🔵", "blocked": "⛔", "done": "✅",
              "cancelled": "✖️", "superseded": "↪️"}


def _fmt_todos(sid):
    """`/todo` as a READABLE Telegram card — not the prompt's wall of text.

    2026-11-28 (operator: "perché in generale telegram ha questo formato orrendo del
    testo? … soprattutto quando si usano comandi o tools"): the prompt formatter
    (`taskgraph.render_todos`) is optimised for the MODEL (dense, one line per step).
    Here every current node gets its own line — icon + `<b>id</b>` + label — and its
    justification goes in a `<blockquote expandable>` (Telegram shows the first lines
    and a "show more"), so a long evidence dump no longer floods the chat. The DATA
    and the justification RULE are the same owners: `taskgraph.plan_nodes` +
    `threads.why_text` (via `render_todos`'s own `_why` rule).
    """
    from longrun.plan import taskgraph as _tg
    from longrun.memory import threads as _th
    try:
        graph = _tg.load(sid) or {}
    except Exception:  # noqa: BLE001 — an absent graph is "no todos"
        graph = {}
    nodes = _tg.plan_nodes(graph)
    if not nodes:
        return "🗒 <b>Todos</b>\n<i>no todos in this chat yet</i>"
    open_n = sum(1 for n in nodes if n.get("status") in _tg.OPEN_STATUSES)
    parts = ["🗒 <b>Todos</b> · %d open / %d total" % (open_n, len(nodes))]
    for n in nodes:
        icon = _TODO_ICON.get(str(n.get("status") or ""), "⚪")
        label = _esc(str(n.get("label") or "").strip())
        nid = _esc(str(n.get("id") or ""))
        indent = "└ " if n.get("parent") else ""
        item = "%s%s <b>%s</b>  %s" % (indent, icon, nid, label)
        why = _th.why_text(n)
        if why:
            if len(why) > 100:
                item += "\n<blockquote expandable>%s</blockquote>" % _esc(why)
            else:
                item += "\n<i>↳ %s</i>" % _esc(why)
        parts.append(item)
    # `_reply` splits on the blank line between items and never inside a tag.
    return "\n\n".join(parts)


def _fmt_context(st):
    """`/context` — the SAME ready-made strings the WebUI meter renders (JAG-107).

    `httpapi.context_usage` already returns a `display` block built by
    `context_display`, the ONE owner of the token wording. We print THAT, so the
    Telegram line can never drift from the WebUI meter.
    """
    disp = st.get("display") or {}
    if not disp.get("available"):
        return "🧠 <b>context</b>\n<i>no reading available for this session</i>"
    detail = str(disp.get("detail") or "")
    return ("🧠 <b>context</b>\n<code>%s</code>%s"
            % (_esc(disp.get("meter") or "ctx n/d"),
               ("\n<i>%s</i>" % _esc(detail)) if detail else ""))


def _fmt_status(sid):
    """`/status` — the SAME `harness.status` the WebUI's `/status` reads (one door).

    2026-11-28 (operator: "telegram e sessione devono essere sync … anche status
    command magari qualche info in più"): the read is the shared `harness` tool
    (`gated_call`, the same function behind `POST /api/tools/call`), never a second
    session read; this function only FORMATS the tool's rich object for chat.
    """
    try:
        from longrun.core import api_v02
        res = api_v02.gated_call("harness", {"action": "status", "session": sid},
                                 run_id=sid) or {}
    except Exception as exc:  # noqa: BLE001 — a status failure is a chat message
        return "⚠️ status failed: %s" % exc
    out = res.get("result") or {}
    if not out:
        return "⚠️ status: %s" % (res.get("error") or res.get("reason")
                                  or ("refused (%s)" % res.get("status")))
    if out.get("error"):
        return "⚠️ status: %s" % out["error"]
    idn = out.get("identity") or {}
    ctx = out.get("context") or {}
    plan = out.get("plan") or {}
    ap = out.get("approvals") or {}
    ag = out.get("agent") or {}
    svc = out.get("service") or {}

    def _n(v):
        return "—" if v is None else v

    pct = ctx.get("pct")
    ctx_line = "%s / %s" % (_n(ctx.get("tokens_used")), _n(ctx.get("max_tokens")))
    if pct is not None:
        ctx_line += "  (%.1f%%)" % float(pct)
    agent = str(ag.get("id") or "—")
    if ag.get("name"):
        agent += " · " + str(ag["name"])
    lines = [
        "%s <b>%s</b>  %s" % ("🟢" if out.get("running") else "⚪", _esc(sid),
                              "<i>running</i>" if out.get("running") else "<i>idle</i>"),
        "<b>title</b>  %s" % _esc(idn.get("title") or "(untitled)"),
        "<b>agent</b>  <code>%s</code>" % _esc(agent),
        "<b>model</b>  <code>%s</code>" % _esc(idn.get("model")
                                               or svc.get("default_model") or "(default)"),
        "<b>messages</b>  <code>%s</code>" % _n(idn.get("messages")),
        "<b>context</b>  <code>%s</code>" % _esc(ctx_line),
        "<b>headroom</b>  <code>%s tokens</code>" % _n(ctx.get("remaining_tokens")),
        "<b>auto-compact</b>  <code>%s%%</code>" % _n(ctx.get("auto_compact_pct")),
        "<b>plan</b>  <code>%d open / %d steps</code>"
        % (plan.get("open") or 0, plan.get("nodes") or 0),
        "<b>approvals</b>  <code>%s</code>" % _n(ap.get("pending_here")),
        "<b>workspace</b>  %s" % _esc(idn.get("workspace") or "(none)"),
    ]
    return "\n".join(lines)


# ---------------------------------------------------------- turns (FIFO) ------
def _enqueue(chat_id, message, mode, msg_id):
    _pending.append((chat_id, message, mode, msg_id))
    _pump()


def _pump():
    """Start the next queued turn if none is in flight (single live reply)."""
    if not _pump_lock.acquire(blocking=False):
        return
    try:
        if _live.get("obj") is not None or not _pending:
            return
        chat_id, message, mode, msg_id = _pending.popleft()
        _start_turn(chat_id, message, mode, msg_id)
    finally:
        _pump_lock.release()


def _start_turn(chat_id, message, mode, msg_id):
    from longrun.core import httpapi
    try:
        from longrun.agent import architect as _arch
        _arch.ensure_telegram_session()
    except Exception:  # noqa: BLE001
        pass
    live = _Live(chat_id)
    _live["obj"] = live
    try:
        res = httpapi.start_session_turn(binding.SESSION_ID, message, mode=mode)
    except Exception as exc:  # noqa: BLE001
        live.finish("⚠️ could not start the turn: %s" % exc)
        return
    if not res.get("ok"):
        live.finish("⚠️ %s" % (res.get("error") or "could not start the turn"))
        return
    live.turn_id = res.get("turn_id")
    with _LOCK:
        _state["turns"] += 1
    try:
        _client.send_chat_action(chat_id, "typing")
    except Exception:  # noqa: BLE001
        pass


# ------------------------------------------------------------- event relay ----
def _attach_listener():
    try:
        from longrun.core import events as _events
        _events.add_listener(_on_event)
    except Exception:  # noqa: BLE001
        pass


def _detach_listener():
    try:
        from longrun.core import events as _events
        _events.remove_listener(_on_event)
    except Exception:  # noqa: BLE001
        pass


def _ensure_live():
    """The in-flight reply, creating one for a turn the channel did NOT start.

    A restart continuation, a job or a teammate dispatch runs on the bound session
    with no originating chat and NO reply object of its own; without this its deltas
    are dropped and Telegram silently desyncs from the Longrun session (the reported
    bug: after `/restart` the turn continues in the session but not on Telegram). The
    reply is shown to the last authorised chat (`binding.active_chat`).
    """
    live = _live.get("obj")
    if live is not None:
        return live
    chat_id = binding.active_chat(binding.load())
    if chat_id is None:
        return None
    live = _Live(chat_id)
    _live["obj"] = live
    with _LOCK:
        _state["turns"] += 1
    return live


def _on_event(event):
    """Forward the bound session's turn events to Telegram (runs off every lock)."""
    if not isinstance(event, dict):
        return
    kind = event.get("kind")
    sid = event.get("session")
    if kind in ("tool.call", "tool.result"):
        # 2026-11-28 (operator: "continuo a non vedere … i comandi tools lanciati solo
        # observations"): these events carry `session` (= the bound session) and NO
        # `run`; matching on `run` dropped every tool card, so the chat showed only
        # the injected observations. Measured: `chat.run.turn_id` (the API turn) and
        # `tool.call.turn_id` (the agent loop) are DIFFERENT strings, so a turn match
        # is not usable either — the bound session has ONE live reply at a time.
        live = _live.get("obj")
        if live is not None and sid == binding.SESSION_ID:
            live.relay_tool(event)
        return
    if sid == binding.SESSION_ID:
        if kind == "chat.run":
            live = _ensure_live()
            if live is not None and event.get("run_id"):
                live.run_id = str(event.get("run_id"))
            if live is not None and event.get("turn_id"):
                live.turn_id = str(event.get("turn_id"))
            return
        if kind == "chat.delta":
            live = _ensure_live()
            if live is None:
                return
            channel = event.get("channel")
            if channel == "answer":
                live.append(event.get("text") or "")
            elif channel == "think":
                live.append_think(event.get("text") or "")
            return
        if kind == "chat.done":
            live = _live.get("obj")
            if live is not None:
                try:
                    live.finish()
                except Exception:  # noqa: BLE001 — a listener is swallowed upstream
                    log.exception("telegram: finish() failed for %s", sid)
            return
        if kind == "harness.inject":
            live = _live.get("obj")
            if live is not None:
                live.relay_harness(event)
            return
        if kind in ("context.compact", "context.auto_compact"):
            _notify_compaction(event)
            return
        if kind == "approval.request":
            _forward_approval(event)
        return
    # approval events carry `run` (the bound session id), not `session`.
    if kind == "approval.request" and str(event.get("run") or "") == binding.SESSION_ID:
        _forward_approval(event)


def _notify_compaction(event):
    """Relay a compaction to the active chat — ONE text, straight from the event.

    2026-11-28 (operator: "anche in telegram messaggio compattazione deve esserci
    … telegram e sessione devono essere sync"): the numbered marker is produced
    ONCE by `compact_session` and carried on BOTH `context.compact` and
    `context.auto_compact`, so a manual `/compact` from any surface (WebUI, CLI,
    Telegram) and an AUTO compaction mid-turn all show the SAME line here. Nothing
    is re-formatted, so there is no second producer and no drift.
    """
    text = str(event.get("marker") or "").strip()
    if not text:
        return
    chat_id = binding.active_chat(binding.load())
    if chat_id is None:
        return
    try:
        _notify(chat_id, text)
    except Exception:  # noqa: BLE001 — a relay must never break the feed
        pass


def _forward_approval(event):
    aid = event.get("id")
    tool = event.get("tool")
    summary = event.get("summary") or tool or "a tool call"
    doc = binding.load()
    text = ("⚠️ Approval needed\n%s\nTool: %s\n(id %s)\n"
            "Tap a button, or decide in the Longrun WebUI. The turn waits ~30 s."
            % (summary, tool, aid))
    keyboard = [[{"text": "✅ Approve", "callback_data": "ap:%s" % aid},
                 {"text": "❌ Deny", "callback_data": "dn:%s" % aid}]]
    for p in doc.get("paired") or []:
        try:
            _client.send_message(p.get("chat_id"), text, keyboard=keyboard)
        except Exception:  # noqa: BLE001
            pass


class _Live:
    """One in-flight Telegram reply: the placeholder we throttle-edit.

    It carries the Telegram-ONLY display choices (`think`/`reason`/`verbose`) as
    snapshots taken at turn start, so a `/think` sent mid-turn applies to the next
    one and the reply cannot change shape halfway. The reply is HTML-formatted:
    a bot-name header, an optional live thinking block, the answer, an optional
    chain-of-thought block and a footer with the model — one message, edited in
    place, then finalised on `chat.done`.
    """

    def __init__(self, chat_id):
        self.chat_id = chat_id
        self.message_id = None
        self.buf = ""
        self.think_buf = ""
        self.last = 0.0
        self.turn_id = None
        self.run_id = None
        self.done = False
        p = binding.prefs(binding.load())
        self.think_on = bool(p.get("think"))
        self.reason_on = bool(p.get("reason"))
        self.verbose = bool(p.get("verbose"))
        try:
            sent = _client.send_message(chat_id, "…")
            self.message_id = (sent or {}).get("message_id")
        except Exception:  # noqa: BLE001 — no placeholder ⇒ the final send still works
            self.message_id = None

    # -- live deltas ---------------------------------------------------------
    def append(self, text):
        if self.done or not text:
            return
        self.buf += text
        self._maybe_render()

    def append_think(self, text):
        # 2026-11-28: `/reason` needs the chain-of-thought too — accumulate when
        # EITHER toggle is on, but stream it into the live reply only with `/think`.
        if self.done or not text or not (self.think_on or self.reason_on):
            return
        self.think_buf += text
        if self.think_on:
            self._maybe_render()

    def _maybe_render(self):
        now = time.time()
        if now - self.last < _edit_throttle():
            return
        self.last = now
        self._render(cursor=True)

    def _render(self, cursor=False):
        body = self.buf.strip()
        think = self.think_buf.strip() if self.think_on else ""
        if not body and not think:
            return
        parts = [_header_html()]
        if think:
            # The live block keeps the LATEST lines (it streams); the final block in
            # `finish()` keeps the beginning — both are collapsible blockquotes.
            parts.append(_quote_html("💭 thinking", think[-_think_preview():]))
        if body:
            parts.append(_md_html(body))
        text = "\n\n".join(parts)
        if cursor:
            text += " ▍"
        text = text[: _max_chars()]
        if self.message_id is None:
            sent = _client.send_message(self.chat_id, text, parse_mode="HTML")
            self.message_id = (sent or {}).get("message_id")
            return
        try:
            _client.edit_message_text(self.chat_id, self.message_id, text,
                                      parse_mode="HTML")
        except Exception:  # noqa: BLE001 — a throttled edit is retried on the final
            pass

    # -- verbose relays (a SEPARATE message per event, real time) ------------
    def relay_tool(self, event):
        if not self.verbose:
            return
        kind = event.get("kind")
        tool = str(event.get("tool") or "tool")
        log.debug("telegram relay: %s %s", kind, tool)
        cap = _verbose_preview()
        if kind == "tool.call":
            args = event.get("args")
            try:
                # 2026-11-28: INDENTED args (a monospace block, one field per line)
                # instead of one 300-char line the reader has to decode.
                detail = json.dumps(args, ensure_ascii=False, indent=2)
            except Exception:  # noqa: BLE001
                detail = str(args or "")
            text = "⚙ <b>%s</b>\n<pre>%s</pre>" % (_esc(tool), _esc(detail[:cap]))
        else:
            ok = event.get("ok") is not False
            head = "✅" if ok else "❌"
            extra = []
            if event.get("exit_code") not in (None, ""):
                extra.append("exit %s" % event.get("exit_code"))
            if event.get("duration_ms") not in (None, ""):
                extra.append("%sms" % event.get("duration_ms"))
            detail = str(event.get("stdout") or event.get("error") or "").strip()
            meta = ("  <i>%s</i>" % _esc(" · ".join(extra))) if extra else ""
            text = ("%s <b>%s</b>%s\n<pre>%s</pre>"
                    % (head, _esc(tool), meta, _esc(detail[:cap])))
        self._send_extra(text)

    def relay_harness(self, event):
        if not self.verbose:
            return
        kind = str(event.get("inject_kind") or "harness")
        if kind in ("system", "observation"):
            # `system` is re-injected every turn (not a chat message); `observation`
            # is the tool batch the model reads — the ⚙/✅ cards already carry the
            # same calls, stdout and exit code, so relaying it too was the "solo
            # observations" duplication the operator reported.
            return
        body = str(event.get("text") or "").strip()
        if body.startswith("[harness] "):
            body = body[len("[harness] "):]
        # A short note stays an italic line; a long harness dump collapses behind
        # Telegram's "show more" instead of filling the chat.
        if len(body) > 160:
            text = ("⟡ <b>%s</b>\n<blockquote expandable>%s</blockquote>"
                    % (_esc(kind), _esc(body[:_verbose_preview()])))
        else:
            text = "⟡ <b>%s</b>\n<i>%s</i>" % (_esc(kind), _esc(body))
        self._send_extra(text)

    def _send_extra(self, text):
        try:
            _client.send_message(self.chat_id, text[: _max_chars()], parse_mode="HTML")
        except Exception as exc:  # noqa: BLE001 — a relayed card is best-effort
            log.warning("telegram: relay card send failed (%s)", exc)

    # -- final ---------------------------------------------------------------
    def finish(self, override=None):
        if self.done:
            return
        self.done = True
        is_error = override is not None
        body = override if override is not None else self.buf
        body = str(body).strip()
        if not body:
            body = "⚠️ the turn ended with no reply."
        thinking = ""
        if self.think_on:
            thinking = self.think_buf.strip()
        reasoning = ""
        if self.reason_on and not is_error:
            reasoning = self._reasoning()
        head = _header_html()
        block = ""
        # 2026-11-28 (operator: "il reason slash non mostra in telegram il thought!!!
        # con menu di chiusura espansione"): the chain-of-thought goes in a COLLAPSIBLE
        # blockquote — the first lines stay visible, the rest sits behind "show more" —
        # instead of an italic wall that filled the chat.
        if reasoning:
            block = _quote_html("🧠 reasoning", reasoning, cap=_reasoning_cap())
        elif thinking:
            block = _quote_html("💭 thinking", thinking, cap=_reasoning_cap())
        # Audit + a LOUD anomaly: the channel's failures used to be invisible
        # (`events.publish` swallows a listener exception), which is why a missing
        # reasoning block could not be diagnosed from the journal.
        log.info("telegram finish: reason_on=%s think_on=%s reasoning=%d block=%d",
                 self.reason_on, self.think_on, len(reasoning), len(block))
        if (self.reason_on or self.think_on) and not block and not is_error:
            log.warning("telegram: reasoning toggle ON but NO block "
                        "(reasoning=%d thinking=%d)", len(reasoning), len(thinking))
        foot = _footer_html()
        # Reserve room for the header/block so the FIRST message is never cut mid
        # tag; the answer body is split on the remaining room and every following
        # message carries plain escaped text only.
        first_room = max(200, _max_chars() - len(head) - len(block) - 8)
        parts = _split_body(body, first_room, _max_chars())
        last = len(parts) - 1
        for i, part in enumerate(parts):
            pieces = [head] if i == 0 else []
            if i == 0 and block:
                pieces.append(block)
            pieces.append(_md_html(part))
            text = "\n\n".join(p for p in pieces if p)
            if i == last and len(text) + len(foot) + 2 <= _max_chars():
                text = text + "\n\n" + foot
            elif i == last:
                self._send_html(foot)
            self._send_or_edit_html(i, text, part)
        _live["obj"] = None
        _pump()

    def _send_or_edit_html(self, index, html_text, plain):
        """Deliver one formatted piece; fall back to PLAIN text, never lose it."""
        try:
            if index == 0 and self.message_id is not None:
                _client.edit_message_text(self.chat_id, self.message_id, html_text,
                                          parse_mode="HTML")
            else:
                _client.send_message(self.chat_id, html_text, parse_mode="HTML")
        except Exception as exc:  # noqa: BLE001 — a formatting failure must not drop the text
            # A silent fallback is how a missing reasoning block stayed invisible.
            log.warning("telegram: HTML send failed (%s), plain fallback", exc)
            try:
                _client.send_message(self.chat_id, plain[: _max_chars()])
            except Exception:  # noqa: BLE001
                log.warning("telegram: plain fallback ALSO failed", exc_info=True)

    def _send_html(self, html_text):
        try:
            _client.send_message(self.chat_id, html_text[: _max_chars()], parse_mode="HTML")
        except Exception as exc:  # noqa: BLE001
            log.warning("telegram: footer send failed (%s)", exc)

    def _reasoning(self):
        """THIS turn's chain-of-thought.

        The live buffer first (it belongs to this turn), else the `reasoning` the
        agent persisted on the turn's last assistant message — the same field the
        WebUI reads, so both surfaces show the same text.
        """
        live = self.think_buf.strip()
        if live:
            return live
        return _last_reasoning()


# ------------------------------------------------------------- send helpers ---
def _esc(text):
    """Escape model text for Telegram HTML (never break the parser)."""
    return html.escape(str(text or ""), quote=False)


#: The model writes Markdown; Telegram HTML has no Markdown parser. These turn the
#: common inline/block forms into real tags so the operator reads prose, not `**`
#: and `##` junk in the middle of a sentence (reported 2026-11-28).
_MD_FENCE = re.compile(r"```[ \t]*[^\n]*\n(.*?)```", re.S)
_MD_INLINE = re.compile(r"`([^`\n]+)`")
_MD_IMAGE = re.compile(r"!\[([^\]\n]*)\]\((https?://[^)\s]+)\)")
_MD_LINK = re.compile(r"\[([^\]\n]+)\]\((https?://[^)\s]+)\)")
_MD_HEAD = re.compile(r"^[ \t]{0,3}#{1,6}[ \t]+(.+?)[ \t]*#*[ \t]*$", re.M)
_MD_RULE = re.compile(r"^[ \t]{0,3}([-*_])(?:[ \t]*\1){2,}[ \t]*$", re.M)
_MD_QUOTE = re.compile(r"^[ \t]{0,3}(?:&gt;|>)[ \t]?", re.M)
_MD_BOLD = re.compile(r"\*\*([^*\n]+)\*\*")
_MD_BOLD2 = re.compile(r"(?<![\w_])__([^_\n]+)__(?![\w_])")
_MD_STRIKE = re.compile(r"~~([^~\n]+)~~")
_MD_ITALIC = re.compile(r"(?<![\w*])\*([^*\n]+)\*(?![\w*])")
_MD_ITALIC2 = re.compile(r"(?<![\w_])_([^_\n]+)_(?![\w_])")


def _md_html(text):
    """Render the model's Markdown as Telegram HTML.

    The text is ESCAPED FIRST, so anything the model wrote as `<b>` stays visible
    instead of becoming markup; every tag emitted below is ours. Code spans/fences
    are parked in placeholders before the emphasis rules run, so a `**` inside code
    is never bolded. A blockquote `>` line becomes a plain `▎` bar: Telegram cannot
    nest blockquotes and the reasoning already lives inside one.
    """
    src = _esc(text)
    saved = []

    def keep(frag):
        saved.append(frag)
        return "\x00%d\x00" % (len(saved) - 1)

    src = _MD_FENCE.sub(lambda m: keep("<pre>%s</pre>" % m.group(1).rstrip("\n")), src)
    src = _MD_INLINE.sub(lambda m: keep("<code>%s</code>" % m.group(1)), src)
    src = _MD_IMAGE.sub(
        lambda m: keep('<a href="%s">%s</a>'
                       % (m.group(2).replace('"', "%22"), m.group(1) or m.group(2))), src)
    src = _MD_LINK.sub(
        lambda m: keep('<a href="%s">%s</a>'
                       % (m.group(2).replace('"', "%22"), m.group(1))), src)
    src = _MD_HEAD.sub(lambda m: "<b>%s</b>" % m.group(1).strip(), src)
    src = _MD_RULE.sub("────────", src)
    src = _MD_QUOTE.sub("▎ ", src)
    src = _MD_BOLD.sub(r"<b>\1</b>", src)
    src = _MD_BOLD2.sub(r"<b>\1</b>", src)
    src = _MD_STRIKE.sub(r"<s>\1</s>", src)
    src = _MD_ITALIC.sub(r"<i>\1</i>", src)
    src = _MD_ITALIC2.sub(r"<i>\1</i>", src)
    for i, frag in enumerate(saved):
        src = src.replace("\x00%d\x00" % i, frag)
    return src


def _bot_name():
    with _LOCK:
        bot = dict(_state.get("bot") or {})
    if not bot:
        bot = binding.load().get("bot") or {}
    return str(bot.get("first_name") or bot.get("username") or "Longrun")


def _header_html():
    return "🤖 <b>%s</b>" % _esc(_bot_name())


def _reasoning_cap():
    """Largest reasoning block we put in ONE message (half the message budget)."""
    return max(400, _max_chars() // 2)


def _quote_html(label, text, cap=None):
    """A labelled COLLAPSIBLE block — Telegram's "show more", not a text wall.

    2026-11-28 (operator: "il reason slash non mostra in telegram il thought!!!
    con menu di chiusura espansione"): `<blockquote expandable>` keeps the first
    lines visible and folds the rest behind the expand control. The body is plain
    escaped text (no nested tags, so a size cut can never leave an open entity).
    """
    body = str(text or "").strip()
    if not body:
        return ""
    limit = int(cap or _reasoning_cap())
    if len(body) > limit:
        body = body[:limit].rstrip() + "…"
    return "<b>%s</b>\n<blockquote expandable>%s</blockquote>" % (_esc(label), _md_html(body))


def _last_reasoning():
    """The `reasoning` the agent persisted on the session's last assistant message.

    ONE reader for every surface: the WebUI shows this field, `/reason` shows it
    the moment it is switched on, and `_Live._reasoning` falls back to it.
    """
    try:
        from longrun.memory import stores
        sess = stores.load_session(binding.SESSION_ID) or {}
        for m in reversed(sess.get("messages") or []):
            if m.get("role") == "assistant":
                return str(m.get("reasoning") or "")
    except Exception:  # noqa: BLE001
        return ""
    return ""


def _split_body(text, first_size, rest_size):
    """Split the answer: the first piece leaves room for header/block, the rest
    use the full width. Never returns an empty list."""
    text = str(text or "")
    if not text:
        return [""]
    out = [text[:first_size]]
    i = first_size
    while i < len(text):
        out.append(text[i:i + rest_size])
        i += rest_size
    return out


def _footer_html():
    try:
        from longrun.memory import stores
        model = str((stores.load_session(binding.SESSION_ID) or {}).get("model") or "")
    except Exception:  # noqa: BLE001
        model = ""
    tail = "Longrun" + (" · " + model if model else "")
    return "<i>%s</i>" % _esc(tail)


def _chunks(text):
    """Split one answer into Telegram-sized pieces (never empty)."""
    text = str(text or "")
    size = _max_chars()
    if not text:
        return ["(empty)"]
    return [text[i:i + size] for i in range(0, len(text), size)]


def _notify(chat_id, text, parse_mode=None):
    if _client is None:
        raise RuntimeError("channel not running")
    return _client.send_message(chat_id, str(text)[:4096], parse_mode=parse_mode)


#: Tags our OWN formatters emit (Telegram HTML, 2026-11-28). When one is present the
#: message is sent with `parse_mode="HTML"`; model/user text never takes this path
#: (it goes through `_Live`, which escapes it).
_HTML_HINT = ("<b>", "<i>", "<code>", "<pre>", "<blockquote")


def _strip_tags(text):
    return re.sub(r"<[^>]+>", "", str(text or ""))


def _html_chunks(text, limit):
    """Split an HTML body on BLOCK boundaries (never inside a tag)."""
    text = str(text or "")
    if len(text) <= limit:
        return [text]
    out, cur = [], ""
    for part in text.split("\n\n"):
        piece = part if not cur else "\n\n" + part
        if cur and len(cur) + len(piece) > limit:
            out.append(cur)
            cur = part
        else:
            cur += piece
    if cur.strip():
        out.append(cur)
    return out or [text]


def _reply(chat_id, text, parse_mode=None):
    """Send `text` to `chat_id`; an EMPTY text sends nothing (the relay covers it).

    2026-11-28 (operator: "perché in generale telegram ha questo formato orrendo del
    testo? … soprattutto quando si usano comandi o tools"): a body carrying OUR markup
    is sent as Telegram HTML — bold headers, `<code>` for ids/values and a
    `<blockquote expandable>` for a long justification. A malformed entity can never
    lose the message: the send is retried as plain text.
    """
    text = str(text or "")
    if not text.strip():
        return
    mode = parse_mode or ("HTML" if any(t in text for t in _HTML_HINT) else None)
    try:
        if mode == "HTML":
            for chunk in _html_chunks(text, _max_chars()):
                _notify(chat_id, chunk, parse_mode=mode)
        else:
            for chunk in _chunks(text):
                _notify(chat_id, chunk)
    except Exception:  # noqa: BLE001 — a bad entity must never drop the message
        try:
            for chunk in _chunks(_strip_tags(text) if mode else text):
                _notify(chat_id, chunk)
        except Exception:  # noqa: BLE001
            pass


def _answer_callback(cq_id, text):
    if _client is None or not cq_id:
        return
    try:
        _client.answer_callback_query(cq_id, text=text or None)
    except Exception:  # noqa: BLE001
        pass
