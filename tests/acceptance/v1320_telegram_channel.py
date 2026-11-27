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
  G  the bot token NEVER appears in a client error.

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

    def send_message(self, chat_id, text, reply_to=None, keyboard=None, parse_mode=None):
        return self._rec("sendMessage", chat_id=chat_id, text=text,
                         reply_markup=keyboard or None, parse_mode=parse_mode)

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

shutil.rmtree(_tmp, ignore_errors=True)
print("---")
ok = sum(results)
print("v1320: %d/%d PASS" % (ok, len(results)))
sys.exit(0 if ok == len(results) else 1)
