#!/usr/bin/env python3
"""v350 — the coordinator can INSPECT other sessions (the missing eye).

SEVERE finding: told "coder 1 is failing a lot, understand why and help him",
the Master could not — it had NO tool to look into a teammate's chat. There was
neither DISCOVERY (which session is "coder 1"?) nor a readable transcript (the
raw data/sessions/<id>.json is unusable in context). The `sessions` tool closes
both gaps. This suite proves it is wired, read-only, and renders a real
transcript (messages + failed tool calls + harness injections), time-ordered.

Deterministic, no model. Run: python3 tests/acceptance/v350_session_inspect.py
"""
import atexit
import os
import shutil
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
tmp = tempfile.mkdtemp(prefix="sf-350-")
atexit.register(lambda: shutil.rmtree(tmp, ignore_errors=True))
os.environ["LONGRUN_CONFIG_DIR"] = os.path.join(tmp, "cfg")
os.environ["LONGRUN_SESSIONS_DIR"] = os.path.join(tmp, "sessions")
os.environ["LONGRUN_DB"] = os.path.join(tmp, "events.db")
os.environ["LONGRUN_GRAPH_DIR"] = os.path.join(tmp, "graphs")
os.environ["LONGRUN_EDITS_DIR"] = os.path.join(tmp, "edits")
os.environ["LONGRUN_RUNS_DIR"] = os.path.join(tmp, "runs")
for d in ("cfg", "sessions", "graphs", "edits", "runs"):
    os.makedirs(os.path.join(tmp, d), exist_ok=True)
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.tools import registry  # noqa: E402
from longrun.core import server  # noqa: E402
from longrun.tools import tools  # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + detail) if detail else ""))


# --- A: schema + policy (read-only, enabled) --------------------------------
spec = registry.tool_spec("sessions")
check("A1 the `sessions` schema exists", spec is not None, "")
check("A2 it is ENABLED", bool(spec and spec.get("enabled")), "")
check("A3 it is read-only (approval=auto)", (spec or {}).get("approval") == "auto",
      str((spec or {}).get("approval")))
sch = registry.TOOL_SCHEMAS.get("sessions") or {}
_actions = set((sch.get("properties", {}).get("action", {}) or {}).get("enum", []))
check("A4 it documents list + read + send + wait",
      _actions == {"list", "read", "send", "wait"},
      str(sorted(_actions)))

# --- B: list — discovery (which session?) -----------------------------------
base = {"id": "sess1", "title": "coder 1 build", "created": 1, "workspace": "ws",
        "job": "J1", "model": "m", "messages": [], "tool_cards": [], "injects": []}
server.save_session(dict(base))
r = tools._sessions({"action": "list"}, None)
check("B1 list ok", r.get("ok") is True, str(r.get("error")))
check("B2 list shows the session id", "sess1" in r.get("stdout", ""), "")
check("B3 list count is 1", r.get("count") == 1, str(r.get("count")))
rq = tools._sessions({"action": "list", "query": "coder"}, None)
check("B4 query filters by title", rq.get("count") == 1, str(rq.get("count")))
rn = tools._sessions({"action": "list", "query": "zzz-nope"}, None)
check("B5 query with no match -> 0", rn.get("count") == 0, str(rn.get("count")))

# --- C: read — the FULL transcript, time-ordered ----------------------------
sess = dict(base)
sess["messages"] = [{"role": "user", "content": "build the app", "ts": 3},
                    {"role": "assistant", "content": "STATUS: BLOCKED: no sdk", "ts": 4}]
sess["tool_cards"] = [{"tool": "shell", "ok": False, "args": '{"command":"gradle"}',
                       "result": "", "error": "gradle: not found", "ts": 2}]
sess["injects"] = [{"kind": "delegation", "text": "Delegated 1 subjob", "ts": 1}]
server.save_session(sess)
r = tools._sessions({"action": "read", "session": "sess1"}, None)
out = r.get("stdout", "")
check("C1 read ok", r.get("ok") is True, str(r.get("error")))
check("C2 transcript shows the user turn", "build the app" in out, "")
check("C3 transcript shows the assistant reply", "STATUS: BLOCKED" in out, "")
check("C4 transcript shows the FAILED tool call",
      "gradle: not found" in out and "FAIL" in out, "")
check("C5 transcript shows the harness injection", "HARNESS(delegation)" in out, "")
check("C6 entries are time-ordered (inject ts=1 before user ts=3)",
      out.index("HARNESS(delegation)") < out.index("build the app"), "")

# A failed COMMAND carries ok=True at the tool layer but exit_code=1 — the
# transcript must show FAIL, or the coordinator mis-reads a broken build as fine.
sess2 = dict(base)
sess2["id"] = "sess2"
sess2["messages"] = []
sess2["injects"] = []
sess2["tool_cards"] = [{"tool": "shell", "ok": True, "args": "{}", "result": "boom",
                        "error": "", "exit_code": 1, "ts": 1}]
server.save_session(sess2)
r = tools._sessions({"action": "read", "session": "sess2"}, None)
check("C7 a non-zero exit renders FAIL (not a bare ok)",
      "FAIL exit=1" in r.get("stdout", ""), r.get("stdout", "")[:120])

# --- D: explicit errors at the boundary -------------------------------------
r = tools._sessions({"action": "read", "session": "nope"}, None)
check("D1 unknown session -> error",
      r.get("ok") is False and "no such session" in r.get("error", ""), "")
r = tools._sessions({"action": "read"}, None)
check("D2 missing session id -> explicit error", r.get("ok") is False,
      str(r.get("error")))
r = tools._sessions({"action": "read", "session": "../etc/passwd"}, None)
check("D3 traversal-shaped id is refused", r.get("ok") is False, "")

# --- E: source wiring -------------------------------------------------------
src = open(os.path.join(REPO, "src", "longrun", "tools/tools.py"), encoding="utf-8").read()
check("E1 _sessions is defined", "def _sessions(" in src, "")
check("E2 it is dispatched", '"sessions": _sessions' in src, "")
jobs = open(os.path.join(REPO, "src", "longrun", "orchestrate/jobs.py"), encoding="utf-8").read()
check("E3 the delegation carries the teammate session id", "[session %s]" in jobs, "")
check("E4 the delegation tells the master to use `sessions`",
      "sessions{action:'read'" in jobs, "")

print("---")
ok = sum(results)
print("%d/%d PASS" % (ok, len(results)))
sys.exit(0 if ok == len(results) else 1)
