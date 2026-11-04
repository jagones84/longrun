#!/usr/bin/env python3
"""v785 — CLI command behaviour: the real handlers, not just their shape.

v587/v588/v312 pin the CLI *statically* (usage block, route parity, method
parity). None of them ever runs a `cmd_*`: a command can pass every static pin
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
  K  `tools policy` builds the enable/approval body
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

    def fake_req(method, path, body=None):
        calls.append({"method": method, "path": path, "body": body})
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

# ------------------------------------------------- K: tools policy body -------
o, e, code, calls = run(forge.cmd_tools,
                        Args(action="policy", value="bash", enable=True, disable=False, approval="ask"), {})
check("K1 the policy body carries tool + enabled + approval",
      body_of(calls, "POST", "/api/tools") == {"tool": "bash", "enabled": True, "approval": "ask"},
      body_of(calls, "POST", "/api/tools"))
o, e, code, calls = run(forge.cmd_tools,
                        Args(action="policy", value="x", enable=False, disable=True, approval=None), {})
check("K2 --disable sends enabled=False", body_of(calls, "POST", "/api/tools") == {"tool": "x", "enabled": False},
      body_of(calls, "POST", "/api/tools"))

# ------------------------------------------------- L: bad-JSON guard family ----
o, e, code, _ = run(forge.cmd_routing, Args(action="update", value="{bad"), {})
check("L1 routing update bad JSON exits 2", code == 2 and "bad json" in e, {"exit": code, "err": e})
o, e, code, _ = run(forge.cmd_providers, Args(action="add", value="{bad"), {})
check("L2 providers add bad JSON exits 2", code == 2 and "bad json" in e, {"exit": code, "err": e})

print("\n---\nv785: %d/%d PASS" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
