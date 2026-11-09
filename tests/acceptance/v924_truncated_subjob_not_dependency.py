#!/usr/bin/env python3
"""v924 — a child that exhausted its step budget is NOT a dependency input.

Deterministic — no model, no server, no network. Regression for the live
reproduction of 2026-11-09 (batch of 2 subagents, HEAD fc301dc):

  A child run stopped by `max_steps` ends with status "done" and a sentinel
  summary ("stopped at max_steps=N; see trace"). `session_jobs.run` downgraded
  ONLY `termination == "no_progress"`, so the truncated subjob was marked
  `done` and the sentinel text was handed to every dependent through the
  "Input from dependencies" block as if it were real work — a dependent then
  did work "based on" a failure.

Contract:
  A) a child with `termination: max_steps` is recorded as an ERROR and its
     dependents are BLOCKED (same loud path as the no_progress guard);
  B) the sentinel a truncated run leaves behind NAMES its evidence file
     (data/graphs/<run_id>.json) instead of a "see trace" that nothing can
     resolve; both run loops (agent.agent_run and api_v02's loop) build it
     through ONE helper — no duplicated string.
"""
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SRC = os.path.join(REPO, "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

TMP = tempfile.mkdtemp(prefix="sf-v924-")
os.environ["LONGRUN_DATA_DIR"] = TMP
os.environ["LONGRUN_SESSIONS_DIR"] = os.path.join(TMP, "sessions")
os.environ["LONGRUN_SUBAGENT_DIR"] = os.path.join(TMP, "subagents")
os.makedirs(os.environ["LONGRUN_SESSIONS_DIR"], exist_ok=True)

checks = []


def check(name, passed, detail=""):
    checks.append(bool(passed))
    print(("PASS " if passed else "FAIL ") + name
          + ((" :: " + str(detail)) if (detail and not passed) else ""))


def _read(*parts):
    with open(os.path.join(REPO, *parts), encoding="utf-8") as f:
        return f.read()


from longrun.core import server as _server  # noqa: E402,F401
from longrun.agent import session_jobs as SJ  # noqa: E402
from longrun.core import api_v02  # noqa: E402

SID = "s_v924"


def _max_steps_collect(sub_id, timeout=None):
    """A child the step budget cut off (what api_v02's loop really returns)."""
    return {"ok": True, "status": "done",
            "summary": api_v02.max_steps_summary(3, "run_" + str(sub_id)),
            "result": {"status": "done", "termination": "max_steps",
                       "summary": api_v02.max_steps_summary(3, "run_" + str(sub_id))}}


# ------------------------------------------------------------------ A: SJ ---
SJ.delete(SID)
plan = SJ.create(SID, "use the child's work", [
    {"label": "trunc", "goal": "TASK trunc"},
    {"label": "dep", "goal": "TASK dep", "deps": ["trunc"]}])
res = SJ.run(SID, plan["job"], spawn_fn=lambda goal, **kw: {"subagent_id": "sb1"},
             collect_fn=_max_steps_collect, cap=2)
_subs = {s.get("label"): s for s in res.get("subjobs") or []}
check("A1 an SJ with a max_steps child ends `error` (not done/partial)",
      res.get("status") == "error", str(res.get("status")))
check("A2 the truncated subjob is an ERROR naming the termination",
      _subs.get("trunc", {}).get("status") == "error"
      and "termination=max_steps" in str(_subs.get("trunc", {}).get("error")),
      str(_subs.get("trunc")))
check("A3 the dependent is BLOCKED on the failed dependency, never fed the sentinel",
      _subs.get("dep", {}).get("status") == "blocked"
      and "dependency failed" in str(_subs.get("dep", {}).get("error")),
      str(_subs.get("dep")))
check("A4 the stored failure text carries the trace locator, not a bare 'see trace'",
      "data/graphs/" in str(_subs.get("trunc", {}).get("result"))
      and "see trace" not in str(_subs.get("trunc", {}).get("result")),
      str(_subs.get("trunc", {}).get("result")))

# ------------------------------------------------------ B: one helper, both loops
check("B1 the locator helper exists and points at the run's evidence file",
      api_v02.max_steps_summary(3, "run_abc") ==
      "stopped at max_steps=3; trace: data/graphs/run_abc.json",
      api_v02.max_steps_summary(3, "run_abc"))
agent_src = _read("src", "longrun", "agent", "agent.py")
api_src = _read("src", "longrun", "core", "api_v02.py")
check("B2 BOTH run loops build the max_steps summary through the helper",
      "max_steps_summary(max_steps, trace.id)" in agent_src
      and "max_steps_summary(max_steps, st.id)" in api_src,
      "agent.py:%s api_v02.py:%s" % ("max_steps_summary(max_steps, trace.id)" in agent_src,
                                     "max_steps_summary(max_steps, st.id)" in api_src))
check("B3 the unresolvable 'see trace' phrasing is gone from the loops",
      "; see trace" not in agent_src and "; see trace" not in api_src)

print("---")
print("%d/%d PASS" % (sum(checks), len(checks)))
sys.exit(0 if all(checks) else 1)
