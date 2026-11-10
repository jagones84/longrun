#!/usr/bin/env python3
"""v944 — two dispatch paths cannot start the same job twice.

`JobRegistry.dispatch` read the job, tested `status == running`, and wrote
`running` several store calls later, with the lock taken per call and never
across the check and the act. `wake()` made it wider: it wrote `created` and only
then dispatched. Two blockers finishing together — or two `POST /api/jobs/dispatch`
calls — both saw a free job, both started a runner, and every worker executed
twice with the same subjob ids (side effects included).

Both transitions are compare-and-set under one lock now: the loser is told
"job already running" / loses the release, instead of duplicating the work.

Deterministic: temp stores, `_run` stubbed, no model, no server, no network.
Run: python3 tests/acceptance/v944_job_dispatch_race.py
"""

import os
import sys
import tempfile
import threading
import time

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="sf-v944-")
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


AID = AG.REGISTRY.designate("s-v944", name="Worker944")["agent"]["id"]


def make_job(goal):
    r = JM.JOBS.create(goal=goal, coordinator=AID, agents=[AID], mode="run")
    return (r.get("job") or {}).get("id")


_starts = []
_real_run = JM.JOBS._run
_real_get = JM.JOBS.get
_real_update = JM.JOBS._update
JM.JOBS._run = lambda jid: _starts.append(jid)


def slow_get(jid):
    # Widen the window the old code left between its check and its write.
    time.sleep(0.05)
    return _real_get(jid)


def slow_update(jid, fn):
    # The old dispatch wrote `running` through `_update`; a slow write makes the
    # check-then-act window deterministic instead of a lucky interleaving.
    time.sleep(0.08)
    return _real_update(jid, fn)


JM.JOBS.get = slow_get
JM.JOBS._update = slow_update
try:
    J = make_job("v944 race")
    out = []
    threads = [threading.Thread(target=lambda: out.append(JM.JOBS.dispatch(J)))
               for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    time.sleep(0.4)
    ok = [r for r in out if r.get("ok")]
    refused = [r for r in out if not r.get("ok")]
    check("A1 exactly ONE of two concurrent dispatches wins", len(ok) == 1, out)
    check("A2 the loser is told why (not silently dropped)",
          len(refused) == 1 and "running" in str(refused[0].get("error")), refused)
    check("A3 exactly ONE runner started", _starts.count(J) == 1, _starts)

    # ---- the release transition ---------------------------------------------
    JB = make_job("v944 blocked")
    JM.JOBS.update(JB, blocked_by=[J])
    check("B0 the job is blocked", (JM.JOBS.get(JB) or {}).get("status") == "blocked")
    got = []
    t2 = [threading.Thread(target=lambda: got.append(JM.JOBS._release(JB)))
          for _ in range(2)]
    for t in t2:
        t.start()
    for t in t2:
        t.join()
    check("B1 exactly ONE sweep releases a blocked job", got.count(True) == 1, got)
    check("B2 the release is not repeatable (status is created now)",
          JM.JOBS._release(JB) is False)
    check("B3 a running job can never be released", JM.JOBS._release(J) is False)

    # ---- a finished job can still be re-dispatched (honest re-run) -----------
    st = JM.JOBS.get(J) or {}
    check("B4 the winner left the job running", st.get("status") == "running", st.get("status"))
    JM.JOBS._update(J, lambda j: j.update({"status": "partial", "ended": time.time()}))
    before = _starts.count(J)
    again = JM.JOBS.dispatch(J)
    time.sleep(0.1)
    check("B5 re-dispatching a closed job is still allowed", again.get("ok") is True, again)
    check("B6 and it really starts a runner", _starts.count(J) == before + 1, _starts)
finally:
    JM.JOBS._run = _real_run
    JM.JOBS.get = _real_get
    JM.JOBS._update = _real_update

print("TOTAL %d/%d" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
