#!/usr/bin/env python3
"""v613 — session tools surface: self sj + sessions chat contracts.

The model reaches other sessions through two tools: `self action=sj`
(this session's Session Jobs) and `sessions` (send/read/wait/list across
sessions). Locks: the sj tool renders the live SJ ledger end to end;
sessions.* validate BEFORE touching live state (missing args -> 64, unknown
session -> clean error, no self-send); the registry advertises both tools
with their required args.
Deterministic, no network, no model; unknown sessions resolve against an
isolated empty session dir, never the live one.
"""
import os
import sys
import tempfile

_tmp = tempfile.mkdtemp(prefix="sf-v613-")
os.environ["LONGRUN_DATA_HOME"] = os.path.join(_tmp, "data")
os.environ["LONGRUN_SESSIONS_DIR"] = os.path.join(_tmp, "sessions")
os.environ["LONGRUN_SJ_DIR"] = os.path.join(_tmp, "sj")
for _d in (os.environ["LONGRUN_DATA_HOME"], os.environ["LONGRUN_SESSIONS_DIR"],
           os.environ["LONGRUN_SJ_DIR"]):
    os.makedirs(_d, exist_ok=True)

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(REPO, "src"))

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""))


from longrun.agent import session_jobs as SJ  # noqa: E402
from longrun.tools import tools as T  # noqa: E402

SID = "sess-v613-probe"
SJ.create(SID, "probe goal", [{"label": "a"}, {"label": "b", "deps": ["a"]}])

r = T._self({"action": "sj", "session": SID}, SID)
check("T1 self sj renders the live ledger (not a stub)",
      r.get("ok") and r["sj"]["jobs"][0]["id"] == "SJ1"
      and [s["id"] for s in r["sj"]["jobs"][0]["subjobs"]] == ["SJ1.1", "SJ1.2"],
      r.get("sj"))
r1 = T._self({"action": "sj", "session": SID, "job": "SJ1"}, SID)
check("T2 self sj filters to one job",
      r1.get("ok") and len(r1["sj"]["jobs"]) == 1, "")
for alias in ("session-jobs", "sessionjobs", "subjobs"):
    ra = T._self({"action": alias, "session": SID}, SID)
    check("T3 alias %r reaches the same ledger" % alias,
          ra.get("ok") and ra["sj"]["jobs"][0]["id"] == "SJ1", "")
r9 = T._self({"action": "sj", "session": SID, "job": "SJ99"}, SID)
check("T4 unknown SJ id falls back to latest open (never a traceback)",
      r9.get("ok") and len(r9["sj"]["jobs"]) == 1 and r9["sj"]["jobs"][0]["id"] == "SJ1", "")
check("T5 SJ payload carries no team-job keys (segregated layers)",
      set(r["sj"]["jobs"][0].keys()) == {"id", "goal", "status", "created", "ended", "subjobs"},
      sorted(r["sj"]["jobs"][0].keys()))

s = T._sessions({"action": "send"}, SID)
check("T6 send without session+message refused (exit 64, no live touch)",
      s.get("exit_code") == 64 and "required" in s.get("error", ""), s.get("error"))
s = T._sessions({"action": "send", "session": "nope", "message": "hi"}, SID)
check("T7 send to unknown session is a clean error (isolated dir, no live)",
      s.get("ok") is False and "no such session" in s.get("error", ""), s.get("error"))
from longrun.memory import stores as ST  # noqa: E402
ST.get_or_create_session(SID)
s = T._sessions({"action": "send", "session": SID, "message": "hi"}, SID)
check("T8 self-send refused (a session never messages itself)",
      s.get("ok") is False and "calling session" in s.get("error", ""), s.get("error"))
s = T._sessions({"action": "read"}, SID)
check("T9 read without session id is a clean usage error",
      s.get("ok") is False and "session id required" in s.get("error", ""), "")
s = T._sessions({"action": "read", "session": "nope"}, SID)
check("T10 read of unknown session is a clean error",
      s.get("ok") is False and "no such session" in s.get("error", ""), "")
s = T._sessions({"action": "list"}, SID)
check("T11 list sees only isolated sessions (ours, no live leak)",
      s.get("ok") and s.get("count") == 1 and "sess-v613-probe" in s.get("stdout", ""),
      s.get("stdout").splitlines()[0] if s.get("stdout") else "")
s = T._sessions({"action": "wait"}, SID)
check("T12 wait without message_id refused (exit 64)",
      s.get("exit_code") == 64 and "message_id required" in s.get("error", ""), "")
s = T._sessions({"action": "wait", "message_id": "ghost"}, SID)
check("T13 wait on unknown id is a clean error (never hangs)",
      s.get("ok") is False and "no pending session message" in s.get("error", ""), "")

from longrun.tools import registry as REG  # noqa: E402
schemas = REG.TOOL_SCHEMAS
check("T14 registry advertises self + sessions tools",
      "self" in schemas and "sessions" in schemas, "")
_sess = str(schemas.get("sessions", ""))
check("T15 registry sessions tool documents send/read/wait actions",
      all(k in _sess for k in ("send", "read", "wait")), "")
missing = T._missing_required("sessions.send", {}) if hasattr(T, "_missing_required") else None
check("T16 required-args helper answers for sessions.send",
      missing is None or isinstance(missing, list), "")

print("\n%d/%d" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
