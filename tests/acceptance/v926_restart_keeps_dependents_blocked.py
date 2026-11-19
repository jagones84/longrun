#!/usr/bin/env python3
"""v926 — a restart must not fail the dependents of an in-flight job.

Deterministic — no model, no server, no network. Regression for the live
observations of 2026-11-09 (J25/J35, both restarts, HEAD fc301dc):

  At boot, `JobRegistry.reconcile()` marks every still-`running` job
  `error: "interrupted by restart"` and then sweeps. `wake()` treated that
  blocker like any terminal `error`, so a dependent that was merely WAITING
  got `error: "dependency failed: J<N>"` even though its blocker never
  actually failed (observed twice: J24 / J34 were running, later completed
  normally). The label is false and there was no auto-recovery.

Contract:
  A) after a restart, a dependent whose blocker carries the
     "interrupted by restart" marker stays `blocked` — it is waiting on work
     that may still be re-armed and complete;
  B) when the blocker later completes, the dependent is released (the wake on
     job end is unchanged);
  C) a GENUINELY failed blocker (status `error`, real reason) still fails its
     dependent loudly — the JAG-348 semantics are untouched.
"""
import json
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SRC = os.path.join(REPO, "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

TMP = tempfile.mkdtemp(prefix="sf-v926-")
os.environ["LONGRUN_DATA_DIR"] = TMP
os.environ["LONGRUN_JOBS_FILE"] = os.path.join(TMP, "jobs.json")

checks = []


def check(name, passed, detail=""):
    checks.append(bool(passed))
    print(("PASS " if passed else "FAIL ") + name
          + ((" :: " + str(detail)) if (detail and not passed) else ""))


from longrun.core import server as _server  # noqa: E402,F401
from longrun.orchestrate import jobs as JOBS_MOD  # noqa: E402

STORE = JOBS_MOD.JOBS_FILE


def _write_store(jobs):
    with open(STORE, "w", encoding="utf-8") as f:
        json.dump({"seq": 1, "jobs": jobs}, f)


def _job(jid):
    return (JOBS_MOD._load().get("jobs") or {}).get(jid) or {}


def _running_job(jid):
    return {"id": jid, "status": "running", "goal": "g " + jid, "blocked_by": [],
            "agents": ["A1"], "runs": {"A1": {"state": "running"}}, "subjobs": {}}


def _blocked_job(jid, blockers):
    return {"id": jid, "status": "blocked", "goal": "g " + jid,
            "blocked_by": blockers, "agents": ["A2"], "runs": {}, "subjobs": {}}


# A: the boot sweep must NOT turn waiting dependents into "dependency failed"
_write_store({"J24": _running_job("J24"), "J25": _blocked_job("J25", ["J24"])})
n = JOBS_MOD.JOBS.reconcile()
check("A1 the boot sweep still closes the in-flight job as interrupted",
      n == 1 and _job("J24").get("status") == "error"
      and _job("J24").get("error") == "interrupted by restart", str(_job("J24")))
_j25 = _job("J25")
check("A2 the dependent of an interrupted job stays `blocked` (not 'dependency failed')",
      _j25.get("status") == "blocked"
      and "dependency failed" not in str(_j25.get("error") or ""), str(_j25))

# B: once the re-armed blocker completes, the sweep releases the dependent and
# reaches dispatch with its agent roster intact. The 2026-11-19 change dropped
# `agents` so dispatch started no worker; that weakened the case (release was no
# longer observed on the agent-carrying path) without naming the real cause.
# Every APP write to the store holds `_LOCK` (`_update` / `_release` /
# `dispatch`), but this test's `_write_store` does not — a live worker thread
# outliving section B could write over section C's fixture. That is a test
# ISOLATION issue, not a job-store race. Stub only the thread-starting boundary
# and assert it was reached.
set_b = {"J24": {"id": "J24", "status": "done", "error": "", "goal": "g J24",
                 "blocked_by": [], "agents": ["A1"], "runs": {}, "subjobs": {}},
         "J25": _blocked_job("J25", ["J24"])}
_write_store(set_b)
_orig_dispatch = JOBS_MOD.JOBS.dispatch
_dispatched = []


def _record_dispatch(jid):
    _dispatched.append(jid)
    return {"ok": True, "job": jid, "status": "created"}


JOBS_MOD.JOBS.dispatch = _record_dispatch
try:
    _rel = JOBS_MOD.JOBS.wake()
finally:
    JOBS_MOD.JOBS.dispatch = _orig_dispatch
_j25b = _job("J25")
check("B1 a completed blocker releases the dependent (wake on job end)",
      any(r.get("job") == "J25" for r in (_rel.get("released") or []))
      and "dependency failed" not in str(_j25b.get("error") or ""), str(_rel))
check("B2 the released dependent reaches dispatch with its agents intact",
      _dispatched == ["J25"] and _j25b.get("agents") == ["A2"]
      and _j25b.get("status") == "created", (_dispatched, _j25b))

# C: a genuinely failed blocker still fails its dependent (JAG-348 kept)
_write_store({"J34": {"id": "J34", "status": "error", "error": "boom", "goal": "g J34",
                      "blocked_by": [], "agents": ["A1"], "runs": {}, "subjobs": {}},
              "J35": _blocked_job("J35", ["J34"])})
JOBS_MOD.JOBS.wake()
_j35 = _job("J35")
check("C1 a genuinely failed blocker still fails its dependent loudly",
      _j35.get("status") == "error"
      and "dependency failed: J34" in str(_j35.get("error") or ""), str(_j35))

# D: a blocker interrupted by restart is not confused with a real failure even
# when OTHER blockers of the same job genuinely failed
_write_store({
    "J40": {"id": "J40", "status": "error", "error": "interrupted by restart",
            "goal": "g J40", "blocked_by": [], "agents": ["A1"], "runs": {}, "subjobs": {}},
    "J41": {"id": "J41", "status": "error", "error": "boom", "goal": "g J41",
            "blocked_by": [], "agents": ["A1"], "runs": {}, "subjobs": {}},
    "J42": _blocked_job("J42", ["J40", "J41"])})
JOBS_MOD.JOBS.wake()
_j42 = _job("J42")
check("D1 mixed blockers: the real failure is named, the interrupted one is not a failure",
      _j42.get("status") == "error"
      and "dependency failed: J41" in str(_j42.get("error") or "")
      and "J40" not in str(_j42.get("error") or ""), str(_j42))

print("---")
print("%d/%d PASS" % (sum(checks), len(checks)))
sys.exit(0 if all(checks) else 1)
