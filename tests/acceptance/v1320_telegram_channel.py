#!/usr/bin/env python3
"""v1320 — the Telegram channel: a DM drives the bound Longrun session.

The bot @Jago_agent proved the Bot API (report 2026-11-26), NOT an integration.
This is the integration's own gate. It locks the contract end to end, with a FAKE
Bot API (injected opener / patched client) and a STUBBED turn starter, so it is
deterministic, offline, no model, no network:

  A  identity — `telegram` is a SYSTEM session (allow_architect, system) that is
     NOT undeletable and NOT stateless, and its agent code is the reserved "AX"
     (never a sequence number), while the Architect stays "A1";
  B  the ONE shared starter — a message calls `httpapi.start_session_turn`
     (`mode=""`), `/goal` calls it with `mode="goal"`, `/status` does NOT;
  C  the relay — a `chat.delta`("answer") edits the live reply, `chat.done`
     finalises it, `approval.request` (run == session) sends an inline keyboard and
     the callback resolves it through `tools.approvals.decide`;
  D  the pairing gate — an unknown chat gets a code, `pair(code)` authorises it;
  E  deletion — `on_session_deleted("telegram")` clears the binding (re-onboarding);
  F  no hardcode — the token is a Key (`KNOWN_ENV_KEYS`) and the knobs live in
     `config/tools.yaml` `telegram:` (parity with the defaults) + `forge.ROUTES`;
  G  the bot token NEVER appears in a client error;
  L  a turn the channel did NOT start is still relayed (restart/job/dispatch);
  M  the delegation gate — the twin reaches the whole org, like the Architect;
  N  a compaction is visible on Telegram (manual AND auto, one numbered marker) and
     `/status` reads the ONE shared `harness.status` tool, not a second session read;
  O  `/skills [keyword]` opens a SEARCHABLE inline menu (the WebUI picker twin): one
     button per skill, keyword filtering, a tap opening the skill's card;
  P  `/plugins` opens its inline menu (or says "none installed"), a tap showing the
     bundle's member manifest;
  Q  `/todo` (Telegram-only) lists every CURRENT-plan todo with status + justification,
     and never leaks into the shared catalogue;
  R  the menus are usable end to end: 🔎 Search re-renders the SAME menu FILTERED from a
     ForceReply answer, ▶️ Use runs a REAL turn with the skill activated, and a fresh
     (non-reply) message is never swallowed by a pending prompt;
  S  the reply renderer emits Telegram HTML (<b>/<code>/<pre>/<blockquote expandable>)
     when we produce markup, keeps plain text plain, falls back to plain on an
     unparsable entity, and splits on BLOCK boundaries (never inside a tag).

Run: python3 tests/acceptance/v1320_telegram_channel.py
"""
import json
import os
import shutil
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_tmp = tempfile.mkdtemp(prefix="sf-1320-")
sys.path.insert(0, os.path.join(REPO, "src"))

# Isolate BEFORE importing longrun (paths are read at import time).
os.environ["LONGRUN_OFFLINE"] = "1"
os.environ["LONGRUN_OPTIMIZER"] = "0"
for _key in ("DATA_DIR", "CONFIG_DIR", "SESSIONS_DIR", "GRAPH_DIR", "EDITS_DIR",
             "RUNS_DIR", "ROLES_DIR", "COSTS_DIR", "THREADS_DIR"):
    _p = os.path.join(_tmp, _key.lower())
    os.makedirs(_p, exist_ok=True)
    os.environ["LONGRUN_" + _key] = _p
os.environ["LONGRUN_DB"] = os.path.join(_tmp, "events.db")
os.environ["LONGRUN_AGENTS_FILE"] = os.path.join(_tmp, "agents.json")
os.environ["LONGRUN_TELEGRAM"] = os.path.join(_tmp, "telegram.json")

results = []


def check(name, cond, extra=""):
    ok = bool(cond)
    results.append(ok)
    print(("PASS " if ok else "FAIL ") + name
          + ((" :: " + str(extra)[:240]) if extra else ""))


from longrun.core.telegram import binding, channel, client, slash  # noqa: E402
from longrun.core import events as _events  # noqa: E402
from longrun.memory import stores  # noqa: E402
from longrun.agent import architect as arch  # noqa: E402
from longrun.agent import agents as agents_mod  # noqa: E402


# ----------------------------------------------------------- fake Bot API -----
class FakeClient:
    """Records every call; Telegram-shaped results (no network).

    Explicit methods (not __getattr__) so the PYTHON name maps to the Telegram
    method exactly, and the positional signatures match `client.BotClient`.
    """

    def __init__(self, *a, **k):
        self.calls = []

    def _rec(self, method, **params):
        self.calls.append((method, params))
        if method == "sendMessage":
            return {"message_id": len(self.calls) + 100,
                    "chat": {"id": params.get("chat_id")}}
        if method == "getMe":
            return {"id": 9228489781, "username": "Jago_agent", "first_name": "Longrun"}
        if method == "getUpdates":
            import time as _t
            _t.sleep(0.15)      # emulate the long-poll wait so stop() stays quick
            return []
        return {"ok": True}

    def get_me(self):
        return self._rec("getMe")

    def delete_webhook(self, drop_pending=True):
        return self._rec("deleteWebhook", drop_pending_updates=drop_pending)

    def get_updates(self, offset=None, timeout=30, allowed_updates=None, limit=100):
        return self._rec("getUpdates", offset=offset)

    def set_my_commands(self, commands, scope=None):
        return self._rec("setMyCommands", commands=commands)

    def send_message(self, chat_id, text, reply_to=None, keyboard=None,
                     disable_preview=True, parse_mode=None, reply_markup=None):
        return self._rec("sendMessage", chat_id=chat_id, text=text,
                         reply_markup=(reply_markup if reply_markup is not None
                                       else (keyboard or None)),
                         parse_mode=parse_mode)

    def edit_message_text(self, chat_id, message_id, text, keyboard=None, parse_mode=None):
        return self._rec("editMessageText", chat_id=chat_id,
                         message_id=message_id, text=text,
                         reply_markup=keyboard or None, parse_mode=parse_mode)

    def send_chat_action(self, chat_id, action="typing"):
        return self._rec("sendChatAction", chat_id=chat_id)

    def answer_callback_query(self, callback_query_id, text=None, show_alert=False):
        return self._rec("answerCallbackQuery", callback_query_id=callback_query_id,
                         text=text)


# ---- A: identity ------------------------------------------------------------
arch.ensure_system_session()
sess = arch.ensure_telegram_session()
check("A1 telegram session exists and is system",
      sess.get("id") == "telegram" and sess.get("system") is True, sess.get("id"))
check("A2 telegram has architect access", arch.access_from_record(sess) is True)
check("A3 telegram is NOT undeletable", sess.get("undeletable") is not True)
check("A4 telegram is NOT stateless", sess.get("stateless") is not True)
check("A5 telegram is a system session", arch.is_system_session("telegram"))
check("A6 architect is a system session", arch.is_system_session("architect"))
check("A7 telegram is deletable, architect is not",
      arch.is_undeletable("telegram") is False and arch.is_undeletable("architect") is True)
_tg_rec = agents_mod.REGISTRY.get("telegram")
_ar_rec = agents_mod.REGISTRY.get("architect")
check("A8 telegram agent code is the reserved AX", _tg_rec and _tg_rec.get("id") == "AX", _tg_rec)
check("A9 architect keeps A1", _ar_rec and _ar_rec.get("id") == "A1", _ar_rec)
check("A10 AX is not in the org chart (kind=session)",
      _tg_rec and _tg_rec.get("kind") == "session")

# ---- F: no hardcode (keys / config parity / routes) -------------------------
from longrun.model import keys as _keys  # noqa: E402
from longrun.model import context_limits as _cl  # noqa: E402
from longrun.core import forge as _forge  # noqa: E402
check("F1 TELEGRAM_BOT_TOKEN is a known Key",
      "TELEGRAM_BOT_TOKEN" in _keys.KNOWN_ENV_KEYS)
_yaml = open(os.path.join(REPO, "config", "tools.yaml"), encoding="utf-8").read()
import re as _re  # noqa: E402
_block = _yaml.split("\ntelegram:", 1)
_yaml_keys = set()
if len(_block) > 1:
    for line in _block[1].splitlines():
        m = _re.match(r"^  ([a-z_]+):", line)
        if m:
            _yaml_keys.add(m.group(1))
        elif line.strip() and not line.startswith(" "):
            break
check("F2 config/tools.yaml telegram: == TELEGRAM_DEFAULTS",
      _yaml_keys == set(_cl.TELEGRAM_DEFAULTS), (_yaml_keys, set(_cl.TELEGRAM_DEFAULTS)))
check("F3 context_limits reads the telegram block (int)",
      _cl.telegram("edit_throttle_ms") >= 1)
check("F4 allowed_updates is a list from config",
      "message" in _cl.telegram_list("allowed_updates"))
_done_routes = {n for n in _forge.ROUTES if n.startswith("telegram_")}
check("F5 forge.ROUTES declares every telegram verb",
      _done_routes == {"telegram_status", "telegram_setup", "telegram_pair",
                       "telegram_unpair", "telegram_reconnect", "telegram_logout"},
      sorted(_done_routes))
_g_api = open(os.path.join(REPO, "src", "longrun", "core", "httpapi.py"), encoding="utf-8").read()
check("F6 the delete guard uses is_undeletable (not is_system_session)",
      "_arch_guard.is_undeletable(sid)" in _g_api and
      "if _arch_guard.is_system_session(sid):" not in _g_api)
from longrun.core import diagnostics as _diag  # noqa: E402
_diag_src = open(os.path.join(REPO, "src", "longrun", "core", "diagnostics.py"),
                 encoding="utf-8").read()
check("F7 diagnostics runs a channels check", '("channels", _channels)' in _diag_src)
_d = _diag.collect()
check("F8 collect() still runs with the channels check", _d.get("ok") is True, _d.get("summary"))
# U: the Settings ▸ Channels panel is wired to the real endpoint (static; the live
# render is proven separately through the served page + REST).
_ui = open(os.path.join(REPO, "webui", "index.html"), encoding="utf-8").read()
check("U1 Settings declares the Channels panel",
      'data-cat="channels"' in _ui and '["channels", "Channels"]' in _ui)
check("U2 the panel loads the real endpoint via loadChannelsPanel",
      "loadChannelsPanel" in _ui and 'name === "channels"' in _ui
      and "/api/telegram/status" in _ui)

# ---- B/C/D/E: the channel with a fake bot -----------------------------------
channel._client = FakeClient()
channel._attach_listener()
_started = []


def _fake_start(sid, message, mode="", **kw):
    _started.append((sid, message, mode))
    # exercise the relay exactly as a real turn would
    _events.publish("chat.run", session=sid, run_id="run1")
    _events.publish("chat.delta", session=sid, channel="answer", text="Hi there")
    _events.publish("chat.done", session=sid)
    return {"ok": True, "session": sid, "turn_id": "t1", "goal_mode": mode == "goal"}


import longrun.core.httpapi as _httpapi  # noqa: E402
_orig_start = _httpapi.start_session_turn
_httpapi.start_session_turn = _fake_start
try:
    # D: unpaired chat gets a pairing code
    binding.reset()
    channel._handle_update({"update_id": 1, "message": {
        "chat": {"id": 9}, "from": {"id": 1, "username": "u"},
        "text": "hi", "message_id": 5}})
    doc = binding.load()
    check("D1 an unknown chat gets a pending code",
          len(doc.get("pending") or {}) == 1, doc.get("pending"))
    _code = next(iter(doc.get("pending") or {}))
    _pairmsg = [p for m, p in channel._client.calls if m == "sendMessage"]
    check("D2 the bot replies with the pairing instructions",
          any("Pairing required" in str(p.get("text")) for p in _pairmsg))
    check("D3 no turn ran for an unpaired chat", _started == [], _started)

    channel.pair(_code)
    check("D4 pair() authorises the chat", binding.is_paired(binding.load(), 9))

    # B/C: a paired message runs the shared starter and relays the answer
    channel._handle_update({"update_id": 2, "message": {
        "chat": {"id": 9}, "from": {"id": 1, "username": "u"},
        "text": "hello", "message_id": 6}})
    check("B1 a message calls start_session_turn on the bound session",
          _started and _started[-1][0] == "telegram" and _started[-1][1] == "hello"
          and _started[-1][2] == "", _started)
    _edits = [p for m, p in channel._client.calls
              if m in ("editMessageText", "sendMessage")]
    check("C1 the answer is relayed to Telegram",
          any("Hi there" in str(p.get("text")) for p in _edits), _edits[-3:])

    # /goal routes to mode=goal through the SAME starter
    channel._handle_update({"update_id": 3, "message": {
        "chat": {"id": 9}, "from": {"id": 1}, "text": "/goal ship it", "message_id": 7}})
    check("B2 /goal sets mode=goal", _started[-1][2] == "goal", _started[-1])

    # /status is a local UI verb — no turn
    _before = len(_started)
    channel._handle_update({"update_id": 4, "message": {
        "chat": {"id": 9}, "from": {"id": 1}, "text": "/status", "message_id": 8}})
    import time as _time  # noqa: E402
    _time.sleep(0.4)   # ui verbs run on a worker thread
    check("B3 /status does not start a turn", len(_started) == _before, _started)

    # C: approval.request -> inline keyboard + callback resolves it
    _decided = []
    from longrun.tools import approvals as _ap  # noqa: E402
    _orig_decide = _ap.decide
    _ap.decide = lambda aid, decision, by="human": (_decided.append((aid, decision, by))
                                                   or {"id": aid, "status": "approved"})
    try:
        _events.publish("approval.request", run="telegram", id="aid1",
                        tool="fs.write", summary="write a file", args={})
        _kb = [p for m, p in channel._client.calls
               if m == "sendMessage" and p.get("reply_markup")]
        check("C2 an approval sends an inline keyboard", bool(_kb), _kb[-1:] or "none")
        channel._handle_callback({"id": "cq1", "data": "ap:aid1",
                                  "message": {"chat": {"id": 9}, "message_id": 1}})
        check("C3 the callback approves through approvals.decide",
              _decided and _decided[-1][0] == "aid1" and _decided[-1][1] == "approve",
              _decided)
    finally:
        _ap.decide = _orig_decide

    # E: deleting the bound session clears the binding
    check("E1 on_session_deleted ignores OTHER sessions",
          channel.on_session_deleted("somethingelse") is False)
    check("E2 deleting telegram clears the binding",
          channel.on_session_deleted("telegram") is True
          and binding.load().get("enabled") is False
          and not (binding.load().get("paired") or []))
finally:
    _httpapi.start_session_turn = _orig_start
    channel._detach_listener()
    channel._client = None

# ---- G: the token never leaks in an error -----------------------------------
def _boom(request, timeout=None):
    raise TimeoutError("boom 111:SEEKRIT leaked")


_cli = client.BotClient("111:SEEKRIT", opener=_boom)
try:
    _cli.get_me()
    check("G1 a failing call raises", False)
except client.TelegramError as exc:
    check("G1 a failing call hides the token", "111:SEEKRIT" not in str(exc), str(exc))

# a non-ok reply also stays bounded and token-free
def _refuse(request, timeout=None):
    class _R:
        def read(self):
            return json.dumps({"ok": False, "description": "bad token 111:SEEKRIT"}).encode()

        def close(self):
            pass
    return _R()


_cli2 = client.BotClient("111:SEEKRIT", opener=_refuse)
try:
    _cli2.get_me()
    check("G2 a refused call raises", False)
except client.TelegramError as exc:
    check("G2 the refusal hides the token", "111:SEEKRIT" not in str(exc), str(exc))

# ---- setup() with a patched client + a temp .env ----------------------------
_keys.ENV_FILE = os.path.join(_tmp, "env")
client.BotClient = FakeClient          # channel imports the class from this module
try:
    binding.reset()
    out = channel.setup("123:NEWTOKEN")
    check("S1 setup validates and saves the token", out.get("ok") is True, out)
    check("S2 setup records the bot identity",
          (out.get("bot") or {}).get("username") == "Jago_agent", out.get("bot"))
    _env = open(_keys.ENV_FILE, encoding="utf-8").read() if os.path.exists(_keys.ENV_FILE) else ""
    check("S3 the token lands in the .env file", "TELEGRAM_BOT_TOKEN=123:NEWTOKEN" in _env, _env[:120])
    check("S4 status reports enabled", binding.load().get("enabled") is True)
    channel.stop()

    # ---- H: first-run auto-onboard vs an explicit "off" ------------------------
    # A FRESH install (no binding file) arms itself from the token; a binding that
    # EXISTS with enabled=false (a logout, or a deleted session) is respected.
    os.environ["TELEGRAM_BOT_TOKEN"] = "999:AUTO"
    _tgpath = os.environ["LONGRUN_TELEGRAM"]
    if os.path.exists(_tgpath):
        os.remove(_tgpath)
    out_h1 = channel.start()
    check("H1 a token with NO binding auto-onboards (arms itself)",
          binding.load().get("enabled") is True and out_h1.get("running") is True, out_h1)
    channel.stop()
    binding.reset()                        # writes enabled=false (an explicit off)
    out_h2 = channel.start()
    check("H2 an EXISTING disabled binding is respected (no silent re-enable)",
          out_h2.get("running") is False and binding.load().get("enabled") is False, out_h2)

    # ---- J: the first poll batch is NOT dropped; repeated DMs reuse one code ----
    # 2026-11-28: the loop used to drop its FIRST batch (to skip a pre-onboarding
    # backlog), which also swallowed a real message sent right after start — the
    # operator DMs, nothing happens. Now every batch is handled; an unknown chat just
    # gets the pairing prompt, and several messages reuse ONE code.
    _ch_src = open(os.path.join(REPO, "src", "longrun", "core", "telegram",
                                "channel.py"), encoding="utf-8").read()
    check("J1 the first poll batch is no longer dropped",
          "if not primed:" not in _ch_src and "primed = bool(last)" not in _ch_src)
    binding.reset()
    channel._pairing_prompt(binding.load(), {"from": {"id": 7, "username": "u7"}}, 77)
    channel._pairing_prompt(binding.load(), {"from": {"id": 7, "username": "u7"}}, 77)
    _pend = binding.load().get("pending") or {}
    _mine = [c for c, r in _pend.items() if str(r.get("chat_id")) == "77"]
    check("J2 two DMs from one chat yield ONE pairing code", len(_mine) == 1, _pend)
finally:
    pass

# ---- K: Telegram-only toggles, /models provider ▸ model, rich reply ---------
# 2026-11-28 (operator): `/models` must choose provider ▸ model from Telegram with
# the SAME backend as the WebUI; `/think` `/reason` `/verbose` are Telegram-only,
# persisted per channel and never touch the session; the reply is HTML-formatted
# with a bot header and a model footer; a tool relay appears only with `/verbose`.
binding.reset()
channel._client = FakeClient()

# the toggle persists on the binding (Telegram-only prefs)
channel._handle_tg_only(9, "think", "on")
channel._handle_tg_only(9, "reason", "on")
channel._handle_tg_only(9, "verbose", "on")
_p = binding.prefs(binding.load())
check("K1 /think /reason /verbose persist ON", _p == {"think": True, "reason": True,
                                                      "verbose": True}, _p)
channel._handle_tg_only(9, "think", "off")
check("K2 /think off flips back", binding.prefs(binding.load())["think"] is False)
channel._handle_tg_only(9, "verbose", "off")
channel._handle_tg_only(9, "reason", "off")
check("K3 prefs are Telegram-only (no session field)",
      "prefs" in binding.load() and "prefs" not in (stores.load_session("telegram") or {}))

# /help lists the shared catalogue and the Telegram-only verbs
channel._handle_tg_only(9, "help", "")
_help = [str(p.get("text")) for m, p in channel._client.calls if m == "sendMessage"]
check("K4 /help names the Telegram-only verbs",
      any(all(x in t for x in ("/think", "/reason", "/verbose", "/stop"))
          for t in _help), _help[-1:] or "none")

# /models: provider keyboard -> model keyboard -> pick (the ONE session-model writer)
_fake_cat = {"providers": [
    {"id": "p1", "name": "Prov One", "configured": True, "reachable": True,
     "local": False, "models": [{"id": "m1", "ref": "p1:m1"},
                                {"id": "m2", "ref": "p1:m2"}]},
    {"id": "p2", "name": "Prov Two", "configured": False, "reachable": None,
     "local": True, "models": [{"id": "x", "ref": "p2:x"}]},
], "default": "p1:m1"}
_orig_catalog = channel._catalog
channel._catalog = lambda: _fake_cat
try:
    channel._client = FakeClient()
    channel._show_providers(9)
    _prov_kb = [p for m, p in channel._client.calls
                if m == "sendMessage" and p.get("reply_markup")]
    check("K5 /models sends a provider keyboard", bool(_prov_kb), _prov_kb[-1:] or "none")
    check("K6 the provider keyboard is HTML-formatted",
          _prov_kb and _prov_kb[-1].get("parse_mode") == "HTML", _prov_kb[-1:] or "none")
    channel._show_models(9, 501, 0, 0)
    _m_edit = [p for m, p in channel._client.calls if m == "editMessageText"]
    check("K7 tapping a provider edits the SAME message with its models",
          _m_edit and "Prov One" in str(_m_edit[-1].get("text")),
          _m_edit[-1:] or "none")
    channel._handle_model_callback(9, 501, "mdl:pick:0:1")
    _now = (stores.load_session("telegram") or {}).get("model")
    check("K8 picking a model writes the session model (one backend)",
          _now == "p1:m2", _now)
finally:
    channel._catalog = _orig_catalog

# the live reply carries a bot header, the thinking block (with /think) and a footer
_doc = binding.load()
binding.set_pref(_doc, "think", True)
binding.save(_doc)
channel._client = FakeClient()
_live = channel._Live(9)
_live.append_think("weighing the options")
_live.finish()
_texts = [str(p.get("text")) for m, p in channel._client.calls
          if m in ("sendMessage", "editMessageText")]
check("K9 /think previews the thinking in the reply",
      any("thinking" in t.lower() for t in _texts), _texts[-2:])
check("K10 the reply is HTML with the bot header and footer",
      any("🤖" in t for t in _texts) and any("Longrun" in t for t in _texts))
_doc = binding.load()
binding.set_pref(_doc, "think", False)
binding.save(_doc)

# /verbose relays a tool call as its own formatted message; silent when OFF
channel._client = FakeClient()
_live2 = channel._Live(9)
_live2.verbose = False
_live2.relay_tool({"kind": "tool.call", "tool": "fs.read", "args": {"path": "x"}})
check("K11 verbose OFF relays nothing",
      not any("fs.read" in str(p.get("text")) for m, p in channel._client.calls
              if m == "sendMessage"), channel._client.calls[-2:])
channel._client = FakeClient()
_live3 = channel._Live(9)
_live3.verbose = True
_live3.relay_tool({"kind": "tool.call", "tool": "fs.read", "args": {"path": "x"}})
check("K12 verbose ON relays the tool call",
      any("fs.read" in str(p.get("text")) for m, p in channel._client.calls
          if m == "sendMessage"), channel._client.calls[-2:])

# the typing heartbeat and the think/verbose wiring are present in the channel
_ch_src = open(os.path.join(REPO, "src", "longrun", "core", "telegram",
                            "channel.py"), encoding="utf-8").read()
check("K13 typing heartbeat pulses sendChatAction while a turn is live",
      "def _typing_loop" in _ch_src and "send_chat_action(live.chat_id" in _ch_src)
check("K14 /models is the shared catalogue entry, not a Telegram copy",
      '{"id": "models"' in open(os.path.join(REPO, "src", "longrun", "core",
                                             "slash.py"), encoding="utf-8").read())
_menu = {c.get("command") for c in channel.commands()}
check("K15 the native menu carries the Telegram-only verbs",
      {"think", "reason", "verbose", "stop", "help"} <= _menu, sorted(_menu))
check("K16 the native menu carries /models", "models" in _menu, sorted(_menu))
channel._client = None

# ---- L: a turn the channel did NOT start is still shown on Telegram ---------
# 2026-11-28 (operator: "dopo /restart ... nella session telegram non più, non è
# sync ... devono essere sync sempre"). After a restart the continuation runs on
# the bound session with NO reply object; the channel must create one for the last
# authorised chat, or its deltas are dropped and Telegram desyncs. Same for a job
# or a teammate dispatch on the bound session.
channel._client = FakeClient()
channel._attach_listener()
try:
    channel._live["obj"] = None
    _doc = binding.load()
    binding.upsert_paired(_doc, 9, title="owner")
    binding.set_active_chat(_doc, 9)
    binding.save(_doc)
    _events.publish("chat.run", session="telegram", run_id="guest1")
    _events.publish("chat.delta", session="telegram", channel="answer",
                    text="resumed answer")
    _events.publish("chat.done", session="telegram")
    _gtexts = [str(p.get("text")) for m, p in channel._client.calls
               if m in ("sendMessage", "editMessageText")]
    check("L1 a turn the channel did not start reaches Telegram",
          any("resumed answer" in t for t in _gtexts), _gtexts[-2:])
    _gsent = [p.get("chat_id") for m, p in channel._client.calls if m == "sendMessage"]
    check("L2 the guest reply goes to the last authorised chat",
          _gsent and all(c == 9 for c in _gsent), _gsent)
    check("L3 binding remembers the active chat", binding.active_chat(binding.load()) == 9)
finally:
    channel._detach_listener()
    channel._client = None

# the channel must be armed BEFORE the resume sweep, or the resumed turn emits
# while no listener is attached (the reported desync).
_api_src = open(os.path.join(REPO, "src", "longrun", "core", "httpapi.py"),
                encoding="utf-8").read()
check("L4 the channel is armed before the restart-resume sweep",
      _api_src.index("from longrun.core import telegram as _telegram_boot")
      < _api_src.index("_restart_boot.resume_after_restart()"))

# ---- M: the delegation gate — the twin reaches the whole org (like A1) -------
# 2026-11-28 (operator: "telegram agent deve avere stesse caratteristiche, permessi
# e tool use esclusive dell'architect ... mi dice A54 is not one of your direct
# reports (none)"). The dispatch/goal/docs gate must share ONE rule
# (`architect.can_delegate`): the Architect AND the Telegram twin reach the whole
# org; everyone else keeps its direct reports only.
arch.ensure_system_session()
arch.ensure_telegram_session()
agents_mod.REGISTRY.designate("t-probe-mgr", name="t-probe-mgr", reports_to="A1")
_mgr_id = (agents_mod.REGISTRY.get("t-probe-mgr") or {}).get("id")
agents_mod.REGISTRY.designate("t-probe-sub", name="t-probe-sub", reports_to=_mgr_id)
_sub_id = (agents_mod.REGISTRY.get("t-probe-sub") or {}).get("id")
_ok_twin, _ = arch.can_delegate("telegram", _mgr_id)
check("M1 the Telegram twin may delegate to an org agent (like the Architect)",
      _ok_twin is True, _mgr_id)
_ok_arch, _ = arch.can_delegate("architect", _sub_id)
check("M2 the Architect keeps whole-org reach", _ok_arch is True, _sub_id)
_ok_own, _ = arch.can_delegate("t-probe-mgr", _sub_id)
check("M3 a plain coordinator may delegate to its direct report", _ok_own is True)
_ok_up, _ = arch.can_delegate("t-probe-sub", "A1")
check("M4 a plain agent may NOT delegate outside its reports", _ok_up is False)
_ok_self, _ = arch.can_delegate("telegram", "AX")
check("M5 an agent may not delegate to itself", _ok_self is False)

# ---- N: compaction is visible on Telegram; /status reads the ONE tool --------
# 2026-11-28 (operator: "anche in telegram messaggio compattazione deve esserci …
# anche status command magari qualche info in più … telegram e sessione devono
# essere sync … no duplicazione di qualsiasi comando rispetto ai tool").
_ch_src = open(os.path.join(REPO, "src", "longrun", "core", "telegram",
                            "channel.py"), encoding="utf-8").read()

# the marker is produced ONCE by the backend (tokens before -> after) and exposed
check("N1 the compaction marker names tokens before -> after (one formatter)",
      'stats["marker"] = sys_marker' in _api_src
      and "%s \\u2192 %s tokens (%d \\u2192 %d messages" in _api_src
      and "def _short_tokens(" in _api_src)
check("N2 the auto-compaction event carries the same marker",
      'marker=stats.get("marker")' in _api_src)
check("N3 the channel relays the compaction event's marker (no re-format)",
      'if kind in ("context.compact", "context.auto_compact")' in _ch_src
      and 'event.get("marker")' in _ch_src)
check("N4 /status uses the shared harness tool (gated_call), no second read",
      'gated_call("harness", {"action": "status"' in _ch_src)

channel._client = FakeClient()
channel._attach_listener()
try:
    _doc = binding.load()
    binding.upsert_paired(_doc, 9, title="owner")
    binding.set_active_chat(_doc, 9)
    binding.save(_doc)
    channel._live["obj"] = None
    channel._client = FakeClient()
    _events.publish("context.compact", session="telegram",
                    marker="[harness] manual: 140k -> 20k tokens")
    _events.publish("context.auto_compact", session="telegram",
                    marker="[harness] auto: 140k -> 20k tokens")
    _ctexts = [str(p.get("text")) for m, p in channel._client.calls if m == "sendMessage"]
    check("N5 a manual compaction reaches Telegram with its numbers",
          any("140k -> 20k" in t and "manual" in t for t in _ctexts), _ctexts[-3:])
    check("N6 an auto compaction reaches Telegram too",
          any("140k -> 20k" in t and "auto" in t for t in _ctexts), _ctexts[-3:])
finally:
    channel._detach_listener()

# an empty reply sends nothing, so the relayed event is the ONE Telegram message
channel._client = FakeClient()
channel._reply(9, "")
check("N7 an empty reply sends nothing", channel._client.calls == [],
      channel._client.calls)

# /compact prints no second message when the marker already rode the event
_orig_compact = _httpapi.compact_session
_httpapi.compact_session = lambda sid, origin="manual", **kw: {
    "session": sid, "origin": origin, "compacted": 4, "marker": "OK-marker"}
try:
    _res_compact = channel._run_ui("compact")
    check("N8 /compact does not double the message when a marker exists",
          _res_compact == "", repr(_res_compact))
finally:
    _httpapi.compact_session = _orig_compact

# /status renders the SAME rich object the WebUI's /status shows
from longrun.core import api_v02 as _api_v02  # noqa: E402
_orig_gated = _api_v02.gated_call
_api_v02.gated_call = lambda tool, args, run_id=None, **kw: {
    "status": "executed", "result": {
        "ok": True, "running": False,
        "identity": {"id": "telegram", "title": "Twin", "model": "p:m",
                     "workspace": "/w", "messages": 42},
        "context": {"tokens_used": 22000, "max_tokens": 131000, "pct": 16.8,
                    "remaining_tokens": 109000, "auto_compact_pct": 70},
        "plan": {"open": 3, "nodes": 9},
        "approvals": {"pending_here": 1},
        "agent": {"id": "AX", "name": "Telegram"},
        "service": {"default_model": "p:m"}}}
try:
    _st = channel._run_ui("status")
    check("N9 /status shows the rich fields the WebUI shows (as HTML)",
          "22000 / 131000" in _st and "16.8%" in _st
          and "<b>plan</b>" in _st and "3 open / 9 steps" in _st
          and "<code>AX · Telegram</code>" in _st and "`" not in _st,
          _st.replace("\n", " | ")[:240])
finally:
    _api_v02.gated_call = _orig_gated

# /context prints the ONE display block (no client-side re-format)
_ctx_txt = channel._fmt_context({"display": {"available": True,
                                             "meter": "ctx: 22k/131k",
                                             "detail": "used 22k / 131k tokens · 17%"}})
check("N10 /context uses the shared display block, as HTML",
      "22k/131k" in _ctx_txt and "17%" in _ctx_txt
      and "<code>ctx: 22k/131k</code>" in _ctx_txt and "`" not in _ctx_txt, _ctx_txt)
channel._client = None

# ---- O: /skills — a SEARCHABLE inline menu (the WebUI picker twin) ----------
# 2026-11-28 (operator: "su telegram slash skills non fa nulla … dovrebbe aprire un
# menu con skills con ricerca by keyword … proprio come per la sessione WebUI").
from longrun.plan import taskgraph as _tg2  # noqa: E402
from longrun.core import slash as _cslash  # noqa: E402

check("O1 /skills is a ui verb of the shared catalogue",
      slash.interpret("/skills").get("kind") == "ui"
      and slash.interpret("/skills").get("action") == "skills")
check("O2 /skills <keyword> carries the keyword as its message",
      slash.interpret("/skills pdf").get("message") == "pdf")
check("O3 the dispatcher opens the menu, and _run_ui no longer carries it",
      'if action == "skills":' in _ch_src and "_show_skills(chat_id" in _ch_src
      and 'if action in ("plugins", "skills")' not in _ch_src)

_FAKE_SKILLS = [
    {"name": "pdf-monster", "category": "tools", "title": "PDF Monster",
     "description": "read and OCR pdfs"},
    {"name": "archify", "category": "tools", "title": "Archify",
     "description": "architecture diagrams"},
    {"name": "data-analysis", "category": "tools", "title": "Data analysis",
     "description": "excel and csv"},
]
_orig_all_skills = channel._all_skills
channel._all_skills = lambda: list(_FAKE_SKILLS)
_doc = binding.load()
binding.upsert_paired(_doc, 9, title="owner")
binding.set_active_chat(_doc, 9)
binding.save(_doc)
channel._client = FakeClient()
try:
    channel._show_skills(9)
    _msg = [p for m, p in channel._client.calls if m == "sendMessage"]
    _flat = [b for row in (_msg[-1].get("reply_markup") or []) for b in row]
    check("O4 /skills renders one button per skill + a 🔎 search door",
          sum(1 for b in _flat if "skl:s:" in b["callback_data"]) == 3
          and any(b["callback_data"] == "skl:q:" for b in _flat), _flat)
    check("O5 the header names the skill search gesture and stays HTML",
          _msg and "Skills" in str(_msg[-1].get("text"))
          and "/skills" in str(_msg[-1].get("text"))
          and _msg[-1].get("parse_mode") == "HTML", _msg[-1:] or None)
    channel._client = FakeClient()
    channel._show_skills(9, "pdf")
    _m2 = [p for m, p in channel._client.calls if m == "sendMessage"]
    _k2 = [b for row in (_m2[-1].get("reply_markup") or []) for b in row]
    check("O6 the keyword filters the SAME list (case-insensitive)",
          len(_k2) == 2 and any(b["text"] == "pdf-monster" for b in _k2)
          and "filter" in str(_m2[-1].get("text")), _k2)
    channel._client = FakeClient()
    channel._show_skills(9, "nomatchxyz")
    _m3 = [p for m, p in channel._client.calls if m == "sendMessage"]
    check("O7 a no-match keyword says so (never a blank menu)",
          _m3 and "No skill matches" in str(_m3[-1].get("text")), _m3[-1:] or None)
    channel._client = FakeClient()
    channel._handle_skill_callback(9, 777, "skl:s:1:")
    _ed = [p for m, p in channel._client.calls if m == "editMessageText"]
    check("O8 tapping a skill edits the message with its card + run hint",
          _ed and "Archify" in str(_ed[-1].get("text"))
          and "archify" in str(_ed[-1].get("text")), _ed[-1:] or None)
    _routed = []
    _orig_hsk = channel._handle_skill_callback
    channel._handle_skill_callback = lambda c, m, d: _routed.append(d)
    try:
        channel._handle_callback({"id": "cq-sk", "data": "skl:s:0:x",
                                  "message": {"chat": {"id": 9}, "message_id": 5}})
    finally:
        channel._handle_skill_callback = _orig_hsk
    check("O9 _handle_callback routes skl: callbacks", _routed == ["skl:s:0:x"], _routed)
finally:
    channel._all_skills = _orig_all_skills

# ---- P: /plugins — the installed bundles as an inline menu ------------------
_orig_plugins = _cslash.plugins
check("P1 /plugins is a ui verb of the shared catalogue",
      slash.interpret("/plugins").get("action") == "plugins")
channel._client = FakeClient()
_cslash.plugins = lambda: []
try:
    channel._show_plugins(9)
    _p = [str(q.get("text")) for m, q in channel._client.calls if m == "sendMessage"]
    check("P2 no plugin installed is said plainly (not a blank menu)",
          any("none installed" in t for t in _p), _p[-1:] or None)
finally:
    _cslash.plugins = _orig_plugins
_FAKE_PLUGINS = [{"id": "plugin/demo", "name": "demo", "title": "Demo",
                  "description": "a demo bundle", "state_line": "READY",
                  "members": [{"kind": "skill", "name": "demo-skill",
                               "target": "/nonexistent/SKILL.md"}]}]
channel._client = FakeClient()
_cslash.plugins = lambda: list(_FAKE_PLUGINS)
try:
    channel._show_plugins(9)
    _pm = [q for m, q in channel._client.calls if m == "sendMessage"]
    _prow = [b for row in (_pm[-1].get("reply_markup") or []) for b in row]
    check("P3 a plugin renders a named button with its plg:s callback",
          _prow and "demo" in _prow[0]["text"]
          and _prow[0]["callback_data"] == "plg:s:0:", _prow)
    channel._client = FakeClient()
    channel._handle_plugin_callback(9, 778, "plg:s:0:")
    _ped = [q for m, q in channel._client.calls if m == "editMessageText"]
    check("P4 tapping a plugin shows its member manifest",
          _ped and "demo-skill" in str(_ped[-1].get("text")), _ped[-1:] or None)
finally:
    _cslash.plugins = _orig_plugins

# ---- Q: /todo — every current todo, status + justification (TG-only) --------
# 2026-11-28 (operator: "/todo … status dei todo ed i todo con justifications";
# "tutti i soli todo correnti").
check("Q1 /todo is Telegram-ONLY (never the shared catalogue)",
      "todo" in channel.TG_ONLY
      and not any(c.get("id") == "todo" for c in _cslash.BUILTINS))
check("Q2 the native menu carries /todo",
      "todo" in {c.get("command") for c in channel.commands()})
_FAKE_GRAPH = {"plan": 1, "nodes": [
    {"id": "n1", "label": "first", "status": "done", "plan": 1,
     "evidence": [{"text": "did the first thing"}]},
    {"id": "n2", "label": "second", "status": "doing", "plan": 1},
    {"id": "n3", "label": "old-plan", "status": "done", "plan": 0},
    {"id": "n4", "label": "long evidence", "status": "done", "plan": 1,
     "evidence": [{"text": "x" * 250}]},
]}
_orig_load = _tg2.load
_tg2.load = lambda sid: dict(_FAKE_GRAPH)
channel._client = FakeClient()
try:
    channel._handle_tg_only(9, "todo", "")
    _sent = [q for m, q in channel._client.calls if m == "sendMessage"]
    _t = str(_sent[-1].get("text")) if _sent else ""
    check("Q3 /todo is a readable HTML card: icons, bold ids, justification, no prompt paragraph",
          all(x in _t for x in ("first", "did the first thing", "✅", "🔵", "second"))
          and "<b>n1</b>" in _t
          and "old-plan" not in _t and "This list is YOURS" not in _t
          and "TASK LIST" not in _t, _t[:300])
    check("Q5 /todo is sent with parse_mode=HTML (real formatting, not raw text)",
          _sent and _sent[-1].get("parse_mode") == "HTML")
    check("Q6 a long justification collapses into an expandable blockquote",
          "<blockquote expandable>" in _t and ("x" * 120) in _t, _t[-220:])
finally:
    _tg2.load = _orig_load
channel._client = FakeClient()
channel._handle_tg_only(9, "help", "")
_help = [str(q.get("text")) for m, q in channel._client.calls if m == "sendMessage"]
check("Q4 /help lists /todo and the /skills search hint",
      any("/todo" in t for t in _help) and any("/skills [keyword]" in t for t in _help),
      _help[-1:] or None)
channel._client = None

# ---- R: search-by-reply + ACTIVATION of a skill/plugin in a real turn --------
# 2026-11-28 (operator: "non posso da telegram cercarle scrivendo qualcosa e il menu
# filtrandosi in automatico … e come la attivo nel contesto la skill?"). A Telegram
# keyboard has no text box, so 🔎 Search replies ForceReply: the next message that
# REPLIES to it is the keyword (never an agent turn). A skill's ▶️ Use asks for the
# request the same way and runs `/<skill> <request>` — a real turn with the skill
# ACTIVATED by `agent._apply_skill_slash`.
channel._all_skills = lambda: list(_FAKE_SKILLS)
channel._client = FakeClient()
_doc = binding.load()
binding.upsert_paired(_doc, 9, title="owner")
binding.set_active_chat(_doc, 9)
binding.save(_doc)
channel._prompts.clear()
_started_r = []
_orig_start_r = _httpapi.start_session_turn
_httpapi.start_session_turn = lambda sid, message, mode="", **kw: (
    _started_r.append((sid, message)) or {"ok": True, "turn_id": "tR"})
try:
    channel._show_skills(9)
    _m = [q for m, q in channel._client.calls if m == "sendMessage"]
    _row = [b for row in (_m[-1].get("reply_markup") or []) for b in row]
    check("R1 the skills menu carries a 🔎 Search button",
          any(b.get("callback_data") == "skl:q:" for b in _row), _row)

    channel._client = FakeClient()
    channel._handle_skill_callback(9, 1, "skl:q:")
    _fr = [q for m, q in channel._client.calls if m == "sendMessage"]
    check("R2 🔎 Search replies ForceReply (a real prompt)",
          bool(_fr) and isinstance(_fr[-1].get("reply_markup"), dict)
          and _fr[-1]["reply_markup"].get("force_reply") is True, _fr[-1:] or None)
    _mid = channel._prompts.get(9, {}).get("mid")
    check("R3 the pending prompt is remembered for this chat",
          isinstance(_mid, int)
          and channel._prompts.get(9, {}).get("kind") == "skills-search",
          channel._prompts.get(9))

    channel._client = FakeClient()
    channel._handle_update({"update_id": 9001, "message": {
        "chat": {"id": 9}, "from": {"id": 1}, "text": "pdf", "message_id": 42,
        "reply_to_message": {"message_id": _mid}}})
    _time.sleep(0.3)                       # the filter renders on a worker thread
    _fm = [q for m, q in channel._client.calls if m == "sendMessage"]
    _fr2 = [b for row in (_fm[-1].get("reply_markup") or []) for b in row] if _fm else []
    check("R4 the reply FILTERS the menu (no agent turn started)",
          _fm and "filter" in str(_fm[-1].get("text"))
          and any(b["text"] == "pdf-monster" for b in _fr2) and _started_r == [],
          (_started_r, _fm[-1:] or None))
    check("R5 the pending prompt is consumed after the answer",
          9 not in channel._prompts, channel._prompts)

    channel._client = FakeClient()
    channel._handle_skill_callback(9, 2, "skl:u:1:")
    _pu = [q for m, q in channel._client.calls if m == "sendMessage"]
    _pumid = channel._prompts.get(9, {}).get("mid")
    check("R6 ▶️ Use replies ForceReply and remembers the skill",
          bool(_pu) and _pu[-1]["reply_markup"].get("force_reply") is True
          and channel._prompts.get(9, {}).get("skill") == "archify",
          channel._prompts.get(9))

    channel._live["obj"] = None
    channel._handle_update({"update_id": 9002, "message": {
        "chat": {"id": 9}, "from": {"id": 1}, "text": "draw my services",
        "message_id": 43, "reply_to_message": {"message_id": _pumid}}})
    _time.sleep(0.05)
    check("R7 the reply runs a REAL turn with the skill ACTIVATED",
          bool(_started_r) and _started_r[-1][1].startswith("/archify ")
          and "draw my services" in _started_r[-1][1], _started_r)

    # a fresh (non-reply) message is NEVER swallowed by a pending prompt
    channel._ask(9, "still waiting", "keyword", "skills-search")
    channel._client = FakeClient()
    channel._live["obj"] = None
    channel._handle_update({"update_id": 9003, "message": {
        "chat": {"id": 9}, "from": {"id": 1}, "text": "hello agent",
        "message_id": 44}})
    _time.sleep(0.05)
    check("R8 a fresh message is NOT swallowed (still reaches the agent)",
          _started_r and _started_r[-1][1] == "hello agent"
          and 9 in channel._prompts, _started_r)
finally:
    _httpapi.start_session_turn = _orig_start_r
    channel._all_skills = _orig_all_skills
    channel._prompts.clear()
    channel._client = None

# ---- S: the reply renderer — HTML when we emit markup, never lose a message ---
# 2026-11-28 (operator: "perché in generale telegram ha questo formato orrendo del
# testo? … soprattutto quando si usano comandi o tools"). Best practice (Telegram Bot
# API): parse_mode=HTML — <b>/<code>/<pre>/<blockquote expandable>, no nesting of
# blockquotes, code/pre cannot contain entities.
class _StrictFake(FakeClient):
    """Refuses an unparsable entity, like the real API does (400 can't parse)."""

    def send_message(self, chat_id, text, reply_to=None, keyboard=None,
                     disable_preview=True, parse_mode=None, reply_markup=None):
        if parse_mode == "HTML" and "BADENTITY" in str(text):
            raise RuntimeError("Bad Request: can't parse entities")
        return super().send_message(chat_id, text, reply_to=reply_to,
                                    keyboard=keyboard, disable_preview=disable_preview,
                                    parse_mode=parse_mode, reply_markup=reply_markup)


channel._client = FakeClient()
try:
    channel._reply(9, "🗒 <b>Todos</b>\n\n✅ <b>n1</b>  ok")
    _s1 = [q for m, q in channel._client.calls if m == "sendMessage"]
    check("S1 a body carrying OUR markup is sent as HTML automatically",
          _s1 and _s1[-1].get("parse_mode") == "HTML", _s1[-1:] or None)
    channel._client = FakeClient()
    channel._reply(9, "plain words only")
    _s2 = [q for m, q in channel._client.calls if m == "sendMessage"]
    check("S2 plain text stays plain (no accidental parse_mode)",
          _s2 and _s2[-1].get("parse_mode") is None, _s2[-1:] or None)
    channel._client = _StrictFake()
    channel._reply(9, "<b>BADENTITY</b> kept")
    _s3 = [q for m, q in channel._client.calls if m == "sendMessage"]
    check("S3 an unparsable entity falls back to plain text (message never lost)",
          bool(_s3) and _s3[-1].get("parse_mode") is None
          and "BADENTITY kept" in str(_s3[-1].get("text")), _s3[-1:] or None)
    check("S4 long HTML splits on BLOCK boundaries, never inside a tag",
          all(c.count("<b>") == c.count("</b>")
              and c.count("<blockquote") == c.count("</blockquote>")
              for c in channel._html_chunks(("item <b>x</b>\n\n" * 400), 1000)))
finally:
    channel._client = None

# ---- T: the chain-of-thought is VISIBLE and COLLAPSIBLE ----------------------
# 2026-11-28 (operator: "il reason slash non mostra in telegram il thought!!! con
# menu di chiusura espansione"). `<blockquote expandable>` = Telegram's "show more";
# `/reason` ON shows the last reasoning at once; `finish()` never drops it.
channel._live["obj"] = None
channel._pending.clear()
_sq = channel._quote_html("🧠 reasoning", "step one <b>not a tag</b>")
check("T1 _quote_html builds a labelled expandable blockquote and escapes the body",
      "<blockquote expandable>" in _sq and "</blockquote>" in _sq
      and "🧠 reasoning" in _sq and "&lt;b&gt;not a tag&lt;/b&gt;" in _sq, _sq)
_long = channel._quote_html("🧠 reasoning", "x" * 5000, cap=600)
check("T2 _quote_html caps a huge chain-of-thought", len(_long) < 800 and "…" in _long,
      len(_long))

# a persisted turn carries `reasoning` — the SAME field the WebUI shows
_sess = stores.load_session("telegram")
_sess.setdefault("messages", []).append(
    {"role": "assistant", "content": "done", "reasoning": "STEP-A persisted reasoning"})
stores.save_session(_sess)
_doc = binding.load()
binding.set_pref(_doc, "think", False)
binding.set_pref(_doc, "reason", True)
binding.save(_doc)

channel._client = FakeClient()
_lr = channel._Live(9)
_lr.append_think("STEP-LIVE live buffer")
_lr.finish()
_t3 = [str(p.get("text")) for m, p in channel._client.calls
       if m in ("sendMessage", "editMessageText")]
check("T3 finish() shows THIS turn's chain-of-thought in a collapsible block",
      any("<blockquote expandable>" in t and "STEP-LIVE" in t for t in _t3), _t3[-2:])

channel._client = FakeClient()
_lr2 = channel._Live(9)
_lr2.finish()
_t4 = [str(p.get("text")) for m, p in channel._client.calls
       if m in ("sendMessage", "editMessageText")]
check("T4 with no live buffer finish() falls back to the PERSISTED reasoning",
      any("<blockquote expandable>" in t and "STEP-A" in t for t in _t4), _t4[-2:])
check("T5 _reasoning prefers the live buffer over the persisted field",
      _lr._reasoning() == "STEP-LIVE live buffer", _lr._reasoning()[:60])

# the live preview (mid-turn) is a collapsible block too — twin of the final one
channel._client = FakeClient()
_lr3 = channel._Live(9)
_lr3.think_on = True
_lr3.think_buf = "streaming thought"
_lr3._render()
_t6 = [str(p.get("text")) for m, p in channel._client.calls
       if m in ("sendMessage", "editMessageText")]
check("T6 the live thinking preview is a collapsible blockquote",
      any("<blockquote expandable>" in t and "streaming thought" in t for t in _t6), _t6[-1:])

# `/reason` ON shows the LAST reasoning immediately (no waiting for a turn)
channel._handle_tg_only(9, "reason", "off")
channel._client = FakeClient()
channel._handle_tg_only(9, "reason", "on")
_t7 = [str(p.get("text")) for m, p in channel._client.calls if m == "sendMessage"]
check("T7 /reason ON shows the last reasoning at once, collapsed",
      any("<blockquote expandable>" in t and "STEP-A" in t for t in _t7), _t7[-1:])
channel._client = FakeClient()
channel._handle_tg_only(9, "reason", "off")
_t8 = [str(p.get("text")) for m, p in channel._client.calls if m == "sendMessage"]
check("T8 /reason OFF says so and shows no thought",
      bool(_t8) and "<blockquote" not in _t8[-1], _t8[-1:] or None)

# tool cards reach the chat: the event carries `session` + `turn_id`, NEVER `run`
channel._client = FakeClient()
_lv = channel._Live(9)
_lv.verbose = True
_lv.turn_id = "tX"
channel._live["obj"] = _lv
channel._on_event({"kind": "tool.call", "session": "telegram", "tool": "shell.exec",
                   "turn_id": "tX", "args": {"command": "echo hi"}})
_t9 = [str(p.get("text")) for m, p in channel._client.calls if m == "sendMessage"]
check("T9 a tool.call carrying session+turn_id (no `run`) is relayed",
      any("shell.exec" in t for t in _t9), _t9[-2:])

channel._client = FakeClient()
_lv.verbose = False
channel._on_event({"kind": "tool.call", "session": "telegram", "tool": "fs.read",
                   "turn_id": "tX", "args": {"path": "x"}})
check("T10 verbose OFF relays no tool card",
      not any("fs.read" in str(p.get("text")) for m, p in channel._client.calls
              if m == "sendMessage"), channel._client.calls[-2:])

channel._client = FakeClient()
_lv.verbose = True
channel._on_event({"kind": "tool.call", "session": "other", "tool": "rg",
                   "turn_id": "tX", "args": {}})
check("T11 a tool event of ANOTHER session is ignored",
      not any("rg" in str(p.get("text")) for m, p in channel._client.calls
              if m == "sendMessage"), channel._client.calls[-2:])

channel._client = FakeClient()
channel._on_event({"kind": "tool.call", "session": "telegram", "tool": "other.tool",
                   "turn_id": "OTHER", "args": {}})
check("T12 a tool event with a DIFFERENT turn_id is still relayed "
      "(chat.run and tool.call carry different ids in production)",
      any("other.tool" in str(p.get("text")) for m, p in channel._client.calls
          if m == "sendMessage"), channel._client.calls[-2:])

# the tool batch observation is DUPLICATE of the ⚙/✅ cards: not relayed twice
channel._client = FakeClient()
channel._live["obj"] = _lv
_lv.relay_harness({"inject_kind": "observation",
                   "text": "[harness] Batch of 2 call(s) ran (tools: 2)"})
check("T13 an `observation` inject is NOT relayed (the tool cards carry it)",
      not any("Batch of 2" in str(p.get("text")) for m, p in channel._client.calls
              if m == "sendMessage"), channel._client.calls[-2:])
channel._client = FakeClient()
_lv.relay_harness({"inject_kind": "closure-check", "text": "[harness] still open: n1"})
check("T14 a non-observation harness note is still relayed",
      any("still open" in str(p.get("text")) for m, p in channel._client.calls
          if m == "sendMessage"), channel._client.calls[-2:])
channel._live["obj"] = None
channel._client = None

# ---- U: the model's Markdown is RENDERED, not shown as junk ------------------
# 2026-11-28 (operator, screenshot: "vede scrive schifezze in mezzo al discorso su
# telegram"): the body was only escaped, so `**bold**`, `## title`, fences and links
# appeared literally. `_md_html` escapes first, parks code, then emits real tags.
_u1 = channel._md_html("this is **bold** and *italic* and ~~gone~~")
check("U1 bold/italic/strike become tags",
      "<b>bold</b>" in _u1 and "<i>italic</i>" in _u1 and "<s>gone</s>" in _u1, _u1)
check("U2 inline code becomes <code>, underscore names untouched",
      channel._md_html("run `make -j4` on my_var_name")
      == "run <code>make -j4</code> on my_var_name",
      channel._md_html("run `make -j4` on my_var_name"))
_u3 = channel._md_html("```python\nx = **raw**\n```")
check("U3 a fenced block becomes <pre> and its ** stays literal",
      _u3 == "<pre>x = **raw**</pre>", _u3)
check("U4 a heading becomes a bold line",
      channel._md_html("## What does NOT trigger one") == "<b>What does NOT trigger one</b>",
      channel._md_html("## What does NOT trigger one"))
_u5 = channel._md_html("a\n\n---\n\nb")
check("U5 a horizontal rule becomes a separator, never raw dashes",
      "────────" in _u5 and "---" not in _u5, _u5)
check("U6 a markdown link becomes a real <a href>",
      channel._md_html("see [docs](http://x.test/a?b=1)")
      == 'see <a href="http://x.test/a?b=1">docs</a>',
      channel._md_html("see [docs](http://x.test/a?b=1)"))
_u7 = channel._md_html("model wrote <b>raw</b> & <script>")
check("U7 model-authored tags stay ESCAPED (never become markup)",
      "&lt;b&gt;raw&lt;/b&gt;" in _u7 and "<script>" not in _u7, _u7)
check("U8 a blockquote line becomes a plain bar (Telegram cannot nest quotes)",
      channel._md_html("> the report is wrong").strip() == "▎ the report is wrong",
      channel._md_html("> the report is wrong"))
_u9 = channel._md_html("**bold** inside `**code**` stays code")
check("U9 code is parked BEFORE emphasis (no bold inside a span)",
      "<code>**code**</code>" in _u9 and "<b>bold</b>" in _u9, _u9)

channel._client = FakeClient()
_doc = binding.load()
binding.set_pref(_doc, "reason", False)
binding.set_pref(_doc, "think", False)
binding.save(_doc)
_lm = channel._Live(9)
_lm.buf = "## Steps\n\n1. **Read** the file\n\n```sh\nls -la\n```\n\n---\n\nDone"
_lm.finish()
_u10 = [str(p.get("text")) for m, p in channel._client.calls
        if m in ("sendMessage", "editMessageText")]
check("U10 finish() sends RENDERED markdown (no ** or ## or ``` left in the chat)",
      any("<b>Steps</b>" in t and "<pre>ls -la</pre>" in t for t in _u10)
      and not any("**Read**" in t or "```" in t or "## Steps" in t for t in _u10),
      _u10[-1:] or None)
channel._client = None

shutil.rmtree(_tmp, ignore_errors=True)
print("---")
ok = sum(results)
print("v1320: %d/%d PASS" % (ok, len(results)))
sys.exit(0 if ok == len(results) else 1)
