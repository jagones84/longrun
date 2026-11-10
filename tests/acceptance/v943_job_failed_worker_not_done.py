#!/usr/bin/env python3
"""v943 — a `mode=run` job whose worker failed must not close as `done`.

`_run` computed its `failed` list only inside the coordinator branch, so a job
that is not a coordinator job (a detached dispatch, `mode=run`) always closed
with `failed_subjobs: []` and status `done` — even when its only worker ended in
a harness error record. `wake()` then released the job's dependents on top of
work that never happened, and `_notify` told the assigner "FINISHED — done".

The verdict is now the job's, computed for every mode from both records (the
subjob row, and `runs` for a job whose subjob row was never created).

Deterministic: temp stores, `_run_agent` stubbed, no model, no server, no network.
Run: python3 tests/acceptance/v943_job_failed_worker_not_done.py
"""

import os
import sys
import tempfile
import time

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="sf-v943-")
os.environ["LONGRUN_DATA_DIR"] = TMP
os.environ["LONGRUN_AGENTS_FILE"] = os.path.join(TMP, "agents.json")
os.environ["LONGRUN_JOBS_FILE"] = os.path.join(TMP, "jobs.json")
os.environ["LONGRUN_SESSIONS_DIR"] = os.path.join(TMP, "sessions")
os.environ["LONGRUN_GRAPH_DIR"] = os.path.join(TMP, "graphs")
os.environ["LONGRUN_DB"] = os.path.join(TMP, "events.db")
os.makedirs(os.environ["LONGRUN_SESSIONS_DIR"], exist_ok=True)
os.makedirs(os.environ["LONGRUN_GRAPH_DIR"], exist_ok=True)
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.agent import agents as AG      # noqa: E402
from longrun.orchestrate import jobs as JM  # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""))


AID = AG.REGISTRY.designate("s-v943", name="Worker943")["agent"]["id"]


def wait_done(jid, timeout=20.0):
    end = time.time() + timeout
    while time.time() < end:
        j = JM.JOBS.get(jid) or {}
        if j.get("status") not in ("created", "running", "blocked"):
            return j
        time.sleep(0.1)
    return JM.JOBS.get(jid) or {}


def make_job(goal):
    r = JM.JOBS.create(goal=goal, coordinator=AID, agents=[AID], mode="run")
    return (r.get("job") or {}).get("id")


# ---- A. the worker FAILS -----------------------------------------------------
def _boom(*_a, **_k):
    raise RuntimeError("provider 500")


_real = JM.JOBS._run_agent
JM.JOBS._run_agent = _boom
try:
    JFAIL = make_job("v943 failing job")
    JM.JOBS.dispatch(JFAIL)
    job = wait_done(JFAIL)
finally:
    JM.JOBS._run_agent = _real

check("A1 the failing job does not report `done`", job.get("status") != "done",
      job.get("status"))
check("A2 it reports `partial` (closed with failed work, visible)", job.get("status") == "partial",
      (job.get("status"), job.get("error")))
_subs = job.get("subjobs") or {}
_failed_ids = job.get("failed_subjobs") or []
check("A3 the failed subjob is NAMED in failed_subjobs (the record the UI reads)",
      bool(_failed_ids) and all((_subs.get(x) or {}).get("agent") == AID
                                for x in _failed_ids), _failed_ids)
check("A4 the worker's run record says failed",
      ((job.get("runs") or {}).get(AID) or {}).get("state") == "failed",
      (job.get("runs") or {}).get(AID))
check("A5 the subjob row says failed",
      any(s.get("status") == "failed" for s in (job.get("subjobs") or {}).values()),
      job.get("subjobs"))

# ---- B. a dependent job must NOT be released on that failure -----------------
JDEP = make_job("v943 dependent job")
_dep = JM.JOBS.get(JDEP) or {}
JM.JOBS.update(JDEP, blocked_by=[JFAIL])
_dep = JM.JOBS.get(JDEP) or {}
check("B1 the dependent starts blocked", _dep.get("status") == "blocked", _dep.get("status"))
_woke = JM.JOBS.wake()
_dep = JM.JOBS.get(JDEP) or {}
check("B2 a partial blocker does not silently release the dependent as if done",
      _dep.get("status") in ("blocked", "error"), _dep.get("status"))
check("B3 the sweep does NOT claim it ran the dependent",
      JDEP not in [x.get("job") for x in (_woke.get("released") or []) if x.get("ok")],
      _woke)

# ---- C. the happy path is unchanged -----------------------------------------
def _ok(*_a, **_k):
    return "All the work is here.\n\nSTATUS: DONE"


JM.JOBS._run_agent = _ok
try:
    JOK = make_job("v943 successful job")
    JM.JOBS.dispatch(JOK)
    job2 = wait_done(JOK)
finally:
    JM.JOBS._run_agent = _real

check("C1 a successful run-mode job still closes `done`", job2.get("status") == "done",
      (job2.get("status"), job2.get("error")))
check("C2 and names no failed subjob", not (job2.get("failed_subjobs") or []),
      job2.get("failed_subjobs"))

print("TOTAL %d/%d" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
