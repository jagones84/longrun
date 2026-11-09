#!/usr/bin/env python3
"""v348 — a job's dependencies can never deadlock (no open loop).

Open-loop found by the loop audit: a job `blocked_by` a blocker that ended
`partial` (a NORMAL outcome — one worker failed) was neither released nor failed,
so it stayed `blocked` FOREVER. `reconcile()` had the twin gap: it flipped an
interrupted `running` job to `error` but never called `wake()`, so dependents of
a restart-killed job stayed blocked forever too.

Deterministic, no model. Run: python3 tests/acceptance/v348_job_dep_no_deadlock.py
"""
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(REPO, "src"))

TMP = tempfile.mkdtemp(prefix="sf-v348-")
os.environ["LONGRUN_JOBS_FILE"] = os.path.join(TMP, "jobs.json")

from longrun.orchestrate import jobs  # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + detail) if detail else ""))


def job(jid, n, status, blocked_by=None, agents=("A1",)):
    return {"id": jid, "n": n, "status": status, "agents": list(agents),
            "blocked_by": list(blocked_by or []), "runs": {}, "subjobs": {},
            "goal": "g"}


J = jobs.JOBS

# ---- A: a `partial` blocker must FAIL the dependent (not wedge it) ----------
jobs._save({"seq": 2, "jobs": {
    "J1": job("J1", 1, "partial"),
    "J2": job("J2", 2, "blocked", blocked_by=["J1"]),
}})
done, failed = J._blockers_state(J.get("J2"), jobs._load())
check("A1 a partial blocker counts as a FAILED dependency",
      done is False and failed == ["J1"], "done=%s failed=%s" % (done, failed))

res = J.wake()
check("A2 wake() fails the dependent", "J2" in res.get("failed", []), str(res))
check("A3 the dependent does not stay permanently blocked",
      (J.get("J2") or {}).get("status") == "error", str((J.get("J2") or {}).get("status")))
check("A4 the failure names the dependency",
      "dependency failed" in ((J.get("J2") or {}).get("error") or ""),
      str((J.get("J2") or {}).get("error")))

# ---- B: an `error` blocker still fails the dependent (no regression) --------
jobs._save({"seq": 4, "jobs": {
    "J3": job("J3", 3, "error"),
    "J4": job("J4", 4, "blocked", blocked_by=["J3"]),
}})
res = J.wake()
check("B1 an error blocker fails the dependent too", "J4" in res.get("failed", []), str(res))

# ---- C: reconcile() sweeps dependents of a restart-killed job ---------------
# v926 revision (live 2026-11-09, J25<-J24 / J35<-J34): a restart is NOT a
# failure of the blocker — the job may be re-armed and complete (it did, both
# times). Failing the dependent with a false "dependency failed" was the harm;
# the dependent now stays `blocked` and moves the moment the blocker REALLY
# ends (wake() fires on every job end), so the no-deadlock property holds.
jobs._save({"seq": 6, "jobs": {
    "J5": job("J5", 5, "running"),                 # killed by a hard restart
    "J6": job("J6", 6, "blocked", blocked_by=["J5"]),
}})
n = J.reconcile()
check("C1 reconcile marks the interrupted job error",
      n == 1 and (J.get("J5") or {}).get("status") == "error",
      "n=%s J5=%s" % (n, (J.get("J5") or {}).get("status")))
check("C2 ...its dependent stays `blocked`, never a false 'dependency failed'",
      (J.get("J6") or {}).get("status") == "blocked"
      and "dependency failed" not in ((J.get("J6") or {}).get("error") or ""),
      str((J.get("J6") or {}).get("status")))
jobs._save({"seq": 7, "jobs": {
    "J5": dict(job("J5", 5, "done"), error=""),
    "J6": job("J6", 6, "blocked", blocked_by=["J5"], agents=[]),
}})
_rel_c3 = J.wake()
check("C3 once the re-armed blocker really ends, the dependent moves again",
      any(r.get("job") == "J6" for r in _rel_c3.get("released", [])), str(_rel_c3))

# ---- D: a `done` blocker still releases (unchanged) -------------------------
jobs._save({"seq": 8, "jobs": {
    "J7": job("J7", 7, "done"),
    "J8": job("J8", 8, "blocked", blocked_by=["J7"], agents=[]),
}})
done, failed = J._blockers_state(J.get("J8"), jobs._load())
check("D1 a done blocker is satisfied", done is True and failed == [],
      "done=%s failed=%s" % (done, failed))

print("---")
ok = sum(results)
print("%d/%d PASS" % (ok, len(results)))
sys.exit(0 if ok == len(results) else 1)

