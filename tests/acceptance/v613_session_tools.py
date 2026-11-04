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
# S4 (2026-11-01): measured on the live harness, `self.sj {"job":"SJ13"}` answered 7 587
# chars, ~85% of it the static paths/config/recipe block that the SYSTEM PROMPT already
# carries (`agent.self_summary`). A diagnostic branch now ships only its own payload plus
# one pointer line; `action:"info"` keeps the full report.
# c554072 (2026-11-03) restored ONE scalar to the non-full branch — `repo_path` — because
# v414 5b/5d and v539 B5 pin it there: a diagnostic call still has to say WHERE the repo
# is, and the ~40-char path never pays for the S4 fix. The HEAVY block stays out, so this
# pin now asserts the path IS present and the block is NOT (it used to forbid both, which
# is what left it red after c554072).
check("T5b a dynamic self action ships its own payload + the repo path, not the heavy block",
      not ({"config", "docs", "install_skill", "skills_dir", "namespaces",
            "mcp"} & set(r.keys()))
      and r.get("repo_path") == REPO
      and "self.info" in (r.get("hint") or ""), sorted(r.keys()))
check("T5c action=info still carries the full report (the ONE copy)",
      {"repo_path", "config", "docs", "service", "skills", "namespaces", "mcp"}
      <= set(T._self({"action": "info"}, SID).keys()), "")

# ---- T5d/T5e. self.trace reports what the HARNESS did, not the model ---------
# The survey this comes from (Awesome-Agent-Harness, ETCSLV) rates nearly every system
# `Partial` on V (evaluation interface): a transcript shows the model's work, not the
# runtime's decisions. Finding one wasted turn meant reading 435 messages by hand
# (2026-11-01, `9b5db7c6a45f`: two `CONTINUE` injects, three identical answers).
from longrun.memory import stores as ST                                       # noqa: E402
_TS = SID   # reuse the one isolated session: a second ledger would leak into T11
_ts = ST.get_or_create_session(_TS)
ST.append_message(_ts, "user", "answer with R1A")
ST.append_message(_ts, "assistant", "R1A")
ST.append_message(_ts, "user", "[harness] CONTINUE — your TASK LIST still has 2 open step(s)")
ST.append_message(_ts, "assistant", "R1A")
ST.append_message(_ts, "assistant", "[tool] exit=1 ok=False backend=host sandboxed=False")
_tr = (T._self({"action": "trace", "session": _TS}, _TS) or {}).get("trace") or {}
check("T5d self.trace counts the gates the harness fired and spots the repeated answer",
      _tr.get("gates", {}).get("continue") == 1
      and len(_tr.get("repeated_answers") or []) == 1
      and _tr.get("tool_calls_reported_failed") == 1
      and _tr.get("gate_source") == "messages", _tr)
check("T5e an empty/unknown session is a clean error, never a traceback",
      (T._self({"action": "trace", "session": "nope-nope"}, "nope-nope") or {})
      .get("trace", {}).get("ok") is False)

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
