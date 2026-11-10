#!/usr/bin/env python3
"""v948 — a subjob orphaned by a restart does not hang its batch forever.

Session-Jobs has no restart reconciliation: `jobs.reconcile()` covers the job
store, but nothing repaired the SJ ledger. The scheduler only ever schedules rows
whose status is exactly `pending`, and `running` is computed from THIS process's
in-flight list, so a subjob persisted as `running` by a killed process was never
re-spawned and never failed. Its dependents saw "not done", stayed pending, and
the deadlock breaker finally marked them "dependency never satisfied" — a batch
that could never finish, with a spinner on work nobody was doing.

`run()` now reaps such a row at the start: status `running` with a `started`
older than this process's module load cannot have a worker here, so it is marked
failed with the reason. The dependents block loudly instead of hanging, and the
feed says a subjob did not finish.

Deterministic: temp ledger, stubbed spawn/collect, no model, no server.
Run: python3 tests/acceptance/v948_sj_restart_reap.py
"""

import os
import sys
import tempfile
import time

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="sf-v948-")
os.environ["LONGRUN_DATA_DIR"] = TMP
os.environ["LONGRUN_SJ_DIR"] = os.path.join(TMP, "session_jobs")
os.environ["LONGRUN_SESSIONS_DIR"] = os.path.join(TMP, "sessions")
os.environ["LONGRUN_GRAPH_DIR"] = os.path.join(TMP, "graphs")
os.environ["LONGRUN_DB"] = os.path.join(TMP, "events.db")
os.makedirs(os.environ["LONGRUN_SESSIONS_DIR"], exist_ok=True)
os.makedirs(os.environ["LONGRUN_GRAPH_DIR"], exist_ok=True)
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.agent import session_jobs as SJ  # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""))


def ledger(sid, subjobs, order):
    doc = SJ._empty(sid)
    doc["seq"] = 1
    doc["jobs"] = {"J1": {"id": "J1", "n": 1, "status": "created", "order": order}}
    doc["subjobs"] = {k: dict(v, id=k, job="J1") for k, v in subjobs.items()}
    SJ._save(sid, doc)
    return doc


def run_with_spy(sid):
    spawned = []

    def _spawn(goal, **_kw):
        spawned.append(goal)
        return {"subagent_id": "fake"}

    def _collect(_aid, timeout=None):
        return {"ok": True, "summary": "should not be collected"}

    res = SJ.run(sid, job_id="J1", spawn_fn=_spawn, collect_fn=_collect, timeout=1)
    return res, spawned


# ---- A. the stale row (started BEFORE this process loaded) -----------------
SID = "v948a"
old = time.time() - 600        # ten minutes before this process started
ledger(SID, {
    "J1.1": {"status": "running", "started": old, "goal": "orphan work"},
    "J1.2": {"status": "pending", "deps": ["J1.1"], "goal": "needs the orphan"},
}, ["J1.1", "J1.2"])
res, spawned = run_with_spy(SID)
doc = SJ._load(SID)
a, b = doc["subjobs"]["J1.1"], doc["subjobs"]["J1.2"]
check("A1 the orphaned subjob is no longer `running`", a.get("status") == "failed",
      a.get("status"))
check("A2 and it says why", "interrupted by restart" in str(a.get("error")), a.get("error"))
check("A3 the dependent blocks loudly instead of hanging",
      b.get("status") == "blocked" and "dependency failed" in str(b.get("error")),
      (b.get("status"), b.get("error")))
check("A4 nothing was re-spawned for a row nobody owns", spawned == [], spawned)
check("A5 the batch closes as failed, not `done`", res.get("status") == "error",
      res.get("status"))

# ---- B. a row started by THIS process is left alone ------------------------
SID = "v948b"
ledger(SID, {
    "J1.1": {"status": "running", "started": time.time(), "goal": "live work"},
}, ["J1.1"])
res, spawned = run_with_spy(SID)
doc = SJ._load(SID)
check("B1 a LIVE row (started by this process) is not reaped",
      doc["subjobs"]["J1.1"].get("status") == "running",
      doc["subjobs"]["J1.1"].get("status"))
check("B2 and is not re-spawned", spawned == [], spawned)

# ---- C. a normal batch is unchanged ----------------------------------------
SID = "v948c"
ledger(SID, {
    "J1.1": {"status": "pending", "goal": "do the thing"},
}, ["J1.1"])
res, spawned = run_with_spy(SID)
doc = SJ._load(SID)
check("C1 a fresh pending subjob still runs to `done`",
      doc["subjobs"]["J1.1"].get("status") == "done", doc["subjobs"]["J1.1"].get("status"))
check("C2 it was spawned exactly once", len(spawned) == 1, spawned)
check("C3 the batch reports done", res.get("status") == "done", res.get("status"))

print("TOTAL %d/%d" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
