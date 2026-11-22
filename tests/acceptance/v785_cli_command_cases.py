#!/usr/bin/env python3
"""v785 — CLI command behaviour: the real handlers, not just their shape.

v588 pins the CLI *statically* (route and method parity), and v1276 pins the
contract (help completeness + the required surface) from the LIVE parser. None
of them ever runs a `cmd_*`: a command can pass every static pin
and still print nothing, mis-format a row, or exit 0 on a malformed argument.
This one DRIVES the handlers with `forge.req` stubbed and asserts what a user
sees — the org chart row, the session/approval/tool listings the teams work
from, the `events` query encoding, the JAG-241 models roster, and the exit
codes (1 on a server error, 2 on bad JSON).

  A  `agents ls` renders the org-chart row (model falls back to "default")
  B  `_resolve_session` maps an agent id (AX) to its session (JAG-294)
  C  `sessions ls` / `history` render + `history` exits 1 on an error
  D  `tools ls` renders the roster + sandbox line; `tools call` exits 2 on bad JSON
  E  `approvals ls` renders the stats + row
  F  `models ls` prints the router roster + providers (JAG-241: no top-level "models")
  G  `events` encodes --session/--kind and prints newest first
  H  `jobs ls` renders the row
  I  `status` hits GET /api/status; `_q` URL-encodes
  J  `agents new` guards (empty name, duplicate) + the success path
  K  the CLI cannot write the policy (`tools policy|approvals` gone) and the two
     document decisions map to their own routes (`docs approve` / `implement`)
  L  the bad-JSON guard family exits 2 (routing update, providers add)

Deterministic: `req` is stubbed, no network, no server, no model.
Run: python3 tests/acceptance/v785_cli_command_cases.py
"""
import contextlib
import io
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_tmp = tempfile.mkdtemp(prefix="sf-785-")
os.environ["LONGRUN_SESSIONS_DIR"] = os.path.join(_tmp, "sessions")
os.environ["LONGRUN_CONFIG_DIR"] = os.path.join(_tmp, "cfg")
os.makedirs(os.environ["LONGRUN_SESSIONS_DIR"], exist_ok=True)
os.makedirs(os.environ["LONGRUN_CONFIG_DIR"], exist_ok=True)

sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.core import forge  # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name
          + ((" :: " + str(detail)[:300]) if detail and not ok else ""))


class Args:
    def __init__(self, **kw):
        self.__dict__.update(kw)


def run(fn, args, routes):
    """Drive `fn(args)` with `req` stubbed; return (stdout, stderr, exit, calls).

    `routes` maps (method, path) -> response dict ({} when unmatched).
    """
    calls = []

    def fake_req(method, path, body=None, **kw):
        calls.append({"method": method, "path": path, "body": body, "kw": kw})
        return routes.get((method, path), {})

    out, err = io.StringIO(), io.StringIO()
    code = 0
    old = forge.req
    forge.req = fake_req
    try:
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            fn(args)
    except SystemExit as e:
        code = e.code if isinstance(e.code, int) else (0 if e.code is None else 1)
    finally:
        forge.req = old
    return out.getvalue(), err.getvalue(), code, calls


def body_of(calls, method, path):
    for c in calls:
        if c["method"] == method and c["path"] == path:
            return c["body"]
    return None


# ------------------------------------------------- A: agents ls (org chart) ----
TREE = {"agents": [
    {"id": "A48", "name": "Atlas", "role": "coder", "model": "qwen", "reports_to": "A1"},
    {"id": "A49", "name": "Scout", "role": "", "model": "", "reports_to": ""},
]}
o, e, code, calls = run(forge.cmd_agents, Args(action="ls"),
                        {("GET", "/api/agents/tree"): TREE})
lines = [ln for ln in o.splitlines() if ln.strip()]
check("A1 the agent row carries id/name/role/model", all(x in o for x in ("A48", "Atlas", "coder", "qwen")))
check("A2 the reports-to arrow is rendered", "-> A1" in o)
check("A3 an empty model falls back to 'default'", "default" in o and "-> " not in lines[1])
check("A4 one line per agent", len(lines) == 2, lines)

# ------------------------------------------------- B: _resolve_session (JAG-294) --
ATREE = {"agents": [{"id": "A48", "session": "sess-from-agent"}]}
old_req = forge.req
forge.req = lambda m, p, body=None: ATREE if p == "/api/agents/tree" else {}
try:
    check("B1 an agent id resolves to its session", forge._resolve_session("A48") == "sess-from-agent")
    check("B2 a plain session id passes through", forge._resolve_session("plain-sid") == "plain-sid")
    check("B3 an unknown agent id falls back to the ref", forge._resolve_session("A999") == "A999")
finally:
    forge.req = old_req

# ------------------------------------------------- C: sessions ls / history ----
o, e, code, _ = run(forge.cmd_sessions, Args(action="ls"),
                    {("GET", "/api/sessions"): {"sessions": [{"id": "abc", "messages": 3, "title": "Hello"}]}})
check("C1 sessions ls renders id/messages/title", all(x in o for x in ("abc", "3", "Hello")))

HIST = {("GET", "/api/history?session=abc"): {
    "messages": [{"role": "user", "content": "hi\nthere"}],
    "tool_cards": [{"tool": "bash", "ok": True, "backend": "sandbox"}]}}
o, e, code, _ = run(forge.cmd_sessions, Args(action="history", value="abc"), HIST)
check("C2 history collapses newlines into one row", "[user     ] hi there" in o, o)
check("C3 the tool card is printed", "[tool     ] bash ok=True backend=sandbox" in o, o)

o, e, code, _ = run(forge.cmd_sessions, Args(action="history", value="abc"),
                    {("GET", "/api/history?session=abc"): {"error": "no such session"}})
check("C4 a history error exits 1 with stderr", code == 1 and "no such session" in e, {"exit": code, "err": e})

# ------------------------------------------------- D: tools ls / call ----------
TOOLS = {("GET", "/api/tools"): {
    "tools": [{"name": "bash", "enabled": True, "approval": "never",
               "auto_approve": ["ls"], "description": "run shell"}],
    "sandbox": {"backend": "bwrap", "isolated": True}}}
o, e, code, _ = run(forge.cmd_tools, Args(action="ls"), TOOLS)
check("D1 the tool row carries flags + auto count",
      "bash" in o and "enabled=True" in o and "approval=never" in o and "auto=1" in o, o)
check("D2 the sandbox line is printed", "sandbox: bwrap (isolated=True)" in o, o)

o, e, code, _ = run(forge.cmd_tools, Args(action="call", value="bash", value2="{bad"), {})
check("D3 bad JSON args exit 2 with stderr", code == 2 and "bad json args" in e, {"exit": code, "err": e})

# ------------------------------------------------- E: approvals ls -------------
APPROVALS = {("GET", "/api/approvals"): {
    "stats": {"pending": 1},
    "approvals": [{"status": "pending", "tool": "bash", "id": "ap1", "summary": "rm -rf /"}]}}
o, e, code, _ = run(forge.cmd_approvals, Args(action="ls"), APPROVALS)
check("E1 the stats line is printed", 'stats: {"pending": 1}' in o, o)
check("E2 the approval row is rendered", all(x in o for x in ("pending", "bash", "ap1")), o)

# ------------------------------------------------- F: models ls (JAG-241) ------
MODELS = {("GET", "/api/models"): {
    "router_models": [{"alias": "qwen", "loaded": True, "n_ctx": 32768}],
    "providers": [{"id": "openrouter", "name": "OpenRouter", "available": True,
                   "models": [{"ref": "x/y", "context_length": 131072, "loaded": False}]}]}}
o, e, code, _ = run(forge.cmd_models, Args(action="ls"), MODELS)
check("F1 the local router roster is printed", "local router models:" in o and "qwen" in o
      and "LOADED" in o and "32k ctx" in o, o)
check("F2 the provider section is printed", "providers:" in o and "[openrouter]" in o and "128k" in o, o)
check("F3 a populated roster is NOT silent (the old JAG-241 bug)", o.strip() != "", o)
o, e, code, _ = run(forge.cmd_models, Args(action="ls"), {("GET", "/api/models"): {}})
check("F4 an empty payload dumps the raw JSON", o.strip() == "{}", o)

# ------------------------------------------------- G: events encoding + order --
EV = {("GET", "/api/events?since=0&limit=5&session=a%20b&kind=x%26y"): {
    "events": [{"id": 1, "kind": "first"}, {"id": 2, "kind": "second"}]}}
o, e, code, calls = run(forge.cmd_events,
                        Args(since=0, limit=5, session="a b", kind="x&y"), EV)
check("G1 --session and --kind are URL-encoded", "session=a%20b" in calls[0]["path"]
      and "kind=x%26y" in calls[0]["path"], calls[0]["path"])
check("G2 no raw space leaks into the query", " " not in calls[0]["path"], calls[0]["path"])
check("G3 events print newest first", o.index("second") < o.index("first"), o)

# ------------------------------------------------- H: jobs ls ------------------
JOBS = {("GET", "/api/jobs"): {
    "jobs": [{"id": "J12", "status": "run", "coordinator": "A54", "goal": "ship X"}]}}
o, e, code, _ = run(forge.cmd_jobs, Args(action="ls"), JOBS)
check("H1 the job row is rendered", all(x in o for x in ("J12", "run", "A54", "ship X")), o)

# ------------------------------------------------- I: status + _q --------------
o, e, code, calls = run(forge.cmd_status, Args(), {("GET", "/api/status"): {"ok": True}})
check("I1 status does GET /api/status", calls[0]["method"] == "GET" and calls[0]["path"] == "/api/status")
check("I2 _q URL-encodes reserved characters", forge._q("a b&c/d") == "a%20b%26c%2Fd",
      forge._q("a b&c/d"))
check("I3 _q(None) is empty", forge._q(None) == "")

# ------------------------------------------------- J: agents new guards --------
o, e, code, _ = run(forge.cmd_agents, Args(action="new", value="  "), {})
check("J1 an empty name exits 1", code == 1 and "a name is required" in e, {"exit": code, "err": e})

o, e, code, _ = run(forge.cmd_agents, Args(action="new", value="Atlas"),
                    {("GET", "/api/agents/tree"): {"agents": [{"name": "atlas"}]}})
check("J2 a duplicate name (case-insensitive) exits 1", code == 1 and "already in use" in e,
      {"exit": code, "err": e})

NEW = {("GET", "/api/agents/tree"): {"agents": []},
       ("POST", "/api/orbit/sessions"): {"ok": True, "session": "s-new"},
       ("POST", "/api/agents"): {"ok": True, "id": "A50"}}
o, e, code, calls = run(forge.cmd_agents,
                        Args(action="new", value="Newbie", role="coder", model=None, reports_to=None),
                        NEW)
abody = body_of(calls, "POST", "/api/agents")
check("J3 the new agent is bound to its fresh session", abody == {"session": "s-new", "name": "Newbie", "role": "coder"},
      abody)
check("J4 the success path exits 0", code == 0, {"exit": code, "err": e})

# --------------------------- K: the CLI cannot write the policy ----------------
# 2026-11-17 (operator: "can you change it by CLI? i think not otherwise an agent
# can run the cli and auto change its approval policy — its anti secure"). The
# write verbs are gone from the parser; the server ALSO requires the operator
# token for those two routes (v1052 O6), so a direct curl without it is 403 too.
def _parse(argv, routes=None):
    """`forge.main()` with argv; returns (exit code, req calls)."""
    calls = []

    def fake_req(method, path, body=None, **kw):
        calls.append({"method": method, "path": path, "body": body, "kw": kw})
        return (routes or {}).get((method, path), {})

    old_argv, old_req = sys.argv, forge.req
    sys.argv = ["forge.py"] + argv
    forge.req = fake_req
    try:
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            try:
                forge.main()
                code = 0
            except SystemExit as exc:
                code = int(exc.code or 0)
    finally:
        sys.argv, forge.req = old_argv, old_req
    return code, calls


check("K1 `tools policy` is not a verb any more (argparse refuses it)",
      _parse(["tools", "policy", "bash", "--enable"])[0] == 2)
check("K2 `tools approvals` (the old policy write) is refused too",
      _parse(["tools", "approvals", '{"mode":"full"}'])[0] == 2)
_kc, _kcalls = _parse(["docs", "implement", "--session", "x"])
check("K3 `docs implement` maps to POST /api/docs/implement",
      _kc == 0
      and body_of(_kcalls, "POST", "/api/docs/implement") == {"session": "x"},
      (_kc, _kcalls))
_ka, _acalls = _parse(["docs", "approve", "--session", "x"])
_kai, _aicalls = _parse(["docs", "approve", "--implement", "--session", "x"])
check("K4 `approve` is content-only; `--implement` also opens the gate",
      body_of(_acalls, "POST", "/api/docs/approve") == {"session": "x"}
      and body_of(_aicalls, "POST", "/api/docs/approve") == {"session": "x", "implement": True},
      (body_of(_acalls, "POST", "/api/docs/approve"),
       body_of(_aicalls, "POST", "/api/docs/approve")))
_kp, _pcalls = _parse(["docs", "plan", "add x", "--session", "x"])
check("K5 `docs plan` declares origin=cli (the intent is never guessed from prose)",
      body_of(_pcalls, "POST", "/api/docs/plan").get("origin") == "cli",
      body_of(_pcalls, "POST", "/api/docs/plan"))

# ------------------------------------------------- L: bad-JSON guard family ----
o, e, code, _ = run(forge.cmd_routing, Args(action="update", value="{bad"), {})
check("L1 routing update bad JSON exits 2", code == 2 and "bad json" in e, {"exit": code, "err": e})
o, e, code, _ = run(forge.cmd_providers, Args(action="add", value="{bad"), {})
check("L2 providers add bad JSON exits 2", code == 2 and "bad json" in e, {"exit": code, "err": e})

# --------------------------------- M: the current-session pointer (v1051d) ----
# Operator: "vedo sessione vuota … devi poter lanciare sessioni e poterci vedere
# dentro che fanno". A bare `chat` used to create a NEW session and throw its id
# away; the pointer makes `sessions new` → `chat` land in the same row.
os.environ["LONGRUN_CLI_STATE"] = os.path.join(_tmp, "cli_session.json")
if os.path.exists(os.environ["LONGRUN_CLI_STATE"]):
    os.remove(os.environ["LONGRUN_CLI_STATE"])
check("M0 the CLI starts with no current session",
      forge._current_session() == "" and forge._state_path() == os.environ["LONGRUN_CLI_STATE"])

o, e, code, calls = run(forge.cmd_sessions, Args(action="new", value="probe", workspace=None),
                        {("POST", "/api/sessions"): {"id": "sid-new", "title": "probe",
                                                     "messages": []}})
check("M1 sessions new makes the new session current",
      code == 0 and forge._current_session() == "sid-new"
      and "current session: sid-new" in o, (o, e))

o, e, code, calls = run(forge.cmd_chat,
                        Args(message="ping", session=None, model=None, stream=False, new=False),
                        {("POST", "/api/chat"): {"session": "sid-new", "reply": "pong"}})
check("M2 a bare chat goes to the CURRENT session and prints its id",
      body_of(calls, "POST", "/api/chat") == {"message": "ping", "session": "sid-new", "model": None}
      and "session: sid-new" in o and "pong" in o, (o, e, calls))

os.remove(os.environ["LONGRUN_CLI_STATE"])
o, e, code, calls = run(forge.cmd_chat,
                        Args(message="first", session=None, model=None, stream=False, new=False),
                        {("POST", "/api/chat"): {"session": "srv-minted", "reply": "hi"}})
check("M3 with no pointer, chat adopts the server's id and remembers it",
      body_of(calls, "POST", "/api/chat")["session"] is None
      and "session: srv-minted" in o and forge._current_session() == "srv-minted", (o, calls))

o, e, code, calls = run(forge.cmd_chat,
                        Args(message="fresh", session=None, model=None, stream=False, new=True),
                        {("POST", "/api/chat"): {"session": "another", "reply": "x"}})
check("M4 --new forces a session-less call even with a pointer",
      body_of(calls, "POST", "/api/chat")["session"] is None, calls)

o, e, code, _ = run(forge.cmd_sessions, Args(action="use", value="sid-2"),
                    {("GET", "/api/history?session=sid-2"): {"messages": []}})
check("M5 sessions use validates and switches", code == 0 and forge._current_session() == "sid-2", (o, e))
o, e, code, _ = run(forge.cmd_sessions, Args(action="use", value="nope"),
                    {("GET", "/api/history?session=nope"): {"error": "session not found"}})
check("M6 sessions use refuses an unknown id and keeps the pointer",
      code == 1 and forge._current_session() == "sid-2" and "not found" in e, (o, e))

o, e, code, calls = run(forge.cmd_sessions, Args(action="history", value=None),
                        {("GET", "/api/history?session=sid-2"): {"messages": [
                            {"role": "user", "content": "hello"}]}})
check("M7 sessions history with no id reads the current session",
      code == 0 and "hello" in o and ("GET", "/api/history?session=sid-2") in [
          (c["method"], c["path"]) for c in calls], (o, calls))

o, e, code, calls = run(forge.cmd_sessions, Args(action="ls", value=None),
                        {("GET", "/api/sessions"): {"sessions": [
                            {"id": "sid-2", "messages": 1, "title": "two"},
                            {"id": "other", "messages": 0, "title": "other"}]}})
lines = [ln for ln in o.splitlines() if ln.strip()]
check("M8 sessions ls marks the current row with *",
      len(lines) == 2 and lines[0].startswith("*") and not lines[1].startswith("*"), lines)

os.remove(forge._state_path())
o, e, code, _ = run(forge.cmd_sessions, Args(action="history", value=None), {})
check("M9 history with no pointer exits 2 with the fix", code == 2 and "no current session" in e, (o, e))
o, e, code, _ = run(forge.cmd_docs, Args(action="status", value=None, session=None, model=None), {})
check("M10 docs with no pointer exits 2 instead of guessing", code == 2 and "no current session" in e, (o, e))

forge._set_current_session("sid-3")
o, e, code, calls = run(forge.cmd_docs, Args(action="status", value=None, session=None, model=None),
                        {("GET", "/api/docs?session=sid-3"): {"ok": True, "active": None,
                                                              "plan_mode": False}})
check("M11 docs with no --session reads the current session",
      code == 0 and "plan_mode=False" in o and ("GET", "/api/docs?session=sid-3") in [
          (c["method"], c["path"]) for c in calls], (o, calls))

o, e, code, _ = run(forge.cmd_sessions, Args(action="rm", value="sid-3"),
                    {("DELETE", "/api/sessions/sid-3"): {"ok": True, "deleted": "sid-3"}})
check("M12 deleting the current session drops the pointer", code == 0 and forge._current_session() == "", o)
forge._set_current_session("sid-4")
o, e, code, _ = run(forge.cmd_sessions, Args(action="rm", value="other"),
                    {("DELETE", "/api/sessions/other"): {"ok": True, "deleted": "other"}})
check("M13 deleting ANOTHER session keeps the pointer", forge._current_session() == "sid-4", o)

# M14/M15: the CLI must not KILL a long turn. Measured 2026-11-16 20:48:37: the
# 300 s socket timeout closed the connection and the server's `watch_client`
# aborted session b7329cccf94c mid-work (chat.interrupted). A turn has no
# 5-minute bound, so `chat` (and the planner behind `docs plan|spec`) waits.
o, e, code, calls = run(forge.cmd_chat,
                        Args(message="long", session="sid-5", model=None, stream=False, new=False),
                        {("POST", "/api/chat"): {"session": "sid-5", "reply": "done"}})
_chat_kw = next((c["kw"] for c in calls if (c["method"], c["path"]) == ("POST", "/api/chat")), {})
check("M14 a chat turn is not killed by the CLI's own timeout",
      _chat_kw.get("timeout", 0) >= 3600, _chat_kw)

o, e, code, calls = run(forge.cmd_docs,
                        Args(action="plan", value="add x", session="sid-5", model=None),
                        {("POST", "/api/docs/plan"): {"kind": "plan", "status": "proposed",
                                                      "plan_mode": True}})
_docs_kw = next((c["kw"] for c in calls if (c["method"], c["path"]) == ("POST", "/api/docs/plan")), {})
check("M15 docs plan waits like a turn", _docs_kw.get("timeout", 0) >= 3600, _docs_kw)

forge._set_current_session("sid-6")
o, e, code, calls = run(forge.cmd_context, Args(action="show", session=None, value=None),
                        {("GET", "/api/context?session=sid-6"): {"session": "sid-6", "pct": 3.5}})
check("M16 context show without --session reads the current session",
      code == 0 and '"pct"' in o and ("GET", "/api/context?session=sid-6") in [
          (c["method"], c["path"]) for c in calls], (o, calls))

# --------------------- N: an agent id reaches its session (2026-11-18) --------
# Operator: "parlare con i miei agenti … vederli real time … con tutto il flusso".
# `--session A50` used to be taken LITERALLY (a turn in a session named "A50"),
# and `agents ls` never printed the session, so the round trip had no documented path.
_TREE_S = {"agents": [{"id": "A48", "session": "sess-a48"},
                      {"id": "A49", "session": ""}]}
o, e, code, calls = run(forge.cmd_chat,
                        Args(message="ping", session="A48", model=None, stream=False, new=False),
                        {("GET", "/api/agents/tree"): _TREE_S,
                         ("POST", "/api/chat"): {"session": "sess-a48", "reply": "pong"}})
check("N1 `chat --session A48` resolves the agent to its session",
      body_of(calls, "POST", "/api/chat") == {"message": "ping", "session": "sess-a48", "model": None}
      and "pong" in o, (o, calls))
o, e, code, calls = run(forge.cmd_chat,
                        Args(message="x", session="A999", model=None, stream=False, new=False),
                        {("GET", "/api/agents/tree"): _TREE_S})
check("N2 an unknown agent id fails loudly instead of inventing a session",
      code == 1 and "no agent A999" in e and not body_of(calls, "POST", "/api/chat"),
      {"exit": code, "err": e, "calls": calls})
o, e, code, calls = run(forge.cmd_chat,
                        Args(message="y", session="plain-sid", model=None, stream=False, new=False),
                        {("POST", "/api/chat"): {"session": "plain-sid", "reply": "ok"}})
check("N3 a plain session id is posted unchanged (no lookup)",
      body_of(calls, "POST", "/api/chat")["session"] == "plain-sid"
      and not any(c["path"] == "/api/agents/tree" for c in calls), calls)
o, e, code, calls = run(forge.cmd_sessions, Args(action="history", value="A48"),
                        {("GET", "/api/agents/tree"): _TREE_S,
                         ("GET", "/api/history?session=sess-a48"): {"messages": [
                             {"role": "user", "content": "hello"}]}})
check("N4 history accepts the agent id too",
      code == 0 and "hello" in o
      and ("GET", "/api/history?session=sess-a48") in [(c["method"], c["path"]) for c in calls],
      (o, calls))

# --------------------- O: agents ls prints the session ------------------------
_o, _e, _c, _ = run(forge.cmd_agents, Args(action="ls"),
                    {("GET", "/api/agents/tree"): _TREE_S})
check("O1 the agent row carries the session `chat --session` takes",
      "sess-a48" in _o and "A48" in _o, _o)

# --------------------- P: history --full reconstructs a turn ------------------
_HF = {("GET", "/api/agents/tree"): _TREE_S,
       ("GET", "/api/history?session=sess-a48"): {
           "messages": [{"role": "user", "content": "x" * 400},
                        {"role": "user", "content": "[harness] nudge", "internal": True}],
           "tool_cards": [{"tool": "shell.exec", "ok": True, "exit_code": 0,
                           "backend": "terminal", "args": '{"command": "ls -la"}',
                           "result": "y" * 400, "think": "list the folder"}]}}
_o, _e, _c, _ = run(forge.cmd_sessions,
                    Args(action="history", value="A48", full=True), _HF)
check("P1 --full prints the message untruncated and flags an internal inject",
      ("x" * 400) in _o and "· internal" in _o, _o[-400:])
check("P2 --full prints the card's args, exit, result and the thought",
      '{"command": "ls -la"}' in _o and "exit=0" in _o
      and ("y" * 400) in _o and "think:  list the folder" in _o, _o[-600:])
_o, _e, _c, _ = run(forge.cmd_sessions, Args(action="history", value="A48", full=False), _HF)
check("P3 without --full the compact row is kept (no behaviour change)",
      ("x" * 400) not in _o and "[tool     ] shell.exec ok=True backend=terminal" in _o, _o[-400:])

# --------------------- Q: --stream shows the flow, not only the text ---------
# The server sends tool.call / tool.result / harness.inject on the SAME turn stream
# (httpapi passes `_emit` to `chat_once`); the CLI used to print chat.delta only, so
# a terminal could not see what the agent did — the operator's report.
_FRAMES = [
    ("chat.run", '{"session": "sess-a48"}'),
    ("chat.delta", '{"text": "thinking out loud", "channel": "think"}'),
    ("chat.delta", '{"text": "Checking the file."}'),
    ("tool.call", '{"tool": "fs.read", "args": {"path": "README.md"}}'),
    ("tool.result", '{"tool": "fs.read", "ok": true, "result": "# Longrun"}'),
    ("harness.inject", '{"inject_kind": "nudge", "text": "you have 3 open todos"}'),
    ("approval.request", '{"tool": "shell.exec", "id": "ap7"}'),
    ("done", "{}"),
]
_old_sse = forge.sse
forge.sse = lambda path: iter(_FRAMES)
_out, _err = io.StringIO(), io.StringIO()
try:
    with contextlib.redirect_stdout(_out), contextlib.redirect_stderr(_err):
        _adopted = forge.stream_chat("/api/chat/stream?message=x")
finally:
    forge.sse = _old_sse
_s = _out.getvalue()
check("Q1 stream_chat returns the session the server adopted", _adopted == "sess-a48", _adopted)
check("Q2 the text and the dimmed reasoning are printed",
      "Checking the file." in _s and "think" in _s, _s)
check("Q3 a tool call and its result are printed with the arguments",
      "→ fs.read" in _s and '"path": "README.md"' in _s and "← fs.read ok=True" in _s, _s)
check("Q4 a harness inject and an approval request are printed",
      "[harness:nudge] you have 3 open todos" in _s and "[approval] shell.exec" in _s, _s)

print("\n---\nv785: %d/%d PASS" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
