#!/usr/bin/env python3
"""v720 — one dispatch, one result: no duplicated queue in the tool path (EV-12).

The A53 drill reported an answer that arrived as a duplicate of an earlier
observation, and called it "the same pattern as the BATCH-BUG on session_jobs.py".
`session_jobs` dedupes LABELS only (`:120`) and dispatches each ready subjob once;
nothing in the module copies a queued job. So the claim is UNPROVEN — this test
pins the two invariants that would have to break for a duplicate to exist:

  A  one tool execution emits exactly one PreToolUse and one PostToolUse
  B  one batch of subjobs spawns each subjob exactly once, and re-running a
     finished job dispatches NOTHING (a duplicate queue would spawn again)
  C  a subjob that fails is not retried by the scheduler

Green here does not "prove" the anomaly impossible; it proves the harness's own
paths do not duplicate. The reopen condition is recorded in the plan.
"""
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="longrun-v720-")
for _k in ("DATA_DIR", "CONFIG_DIR", "SESSIONS_DIR", "GRAPH_DIR", "DB"):
    os.environ["LONGRUN_" + _k] = os.path.join(TMP, _k.lower())
for _k in ("DATA_DIR", "CONFIG_DIR", "SESSIONS_DIR", "GRAPH_DIR"):
    os.makedirs(os.environ["LONGRUN_" + _k], exist_ok=True)
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.tools import tools as T  # noqa: E402
from longrun.agent import session_jobs as SJ  # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name
          + ((" :: " + str(detail)[:400]) if detail and not ok else ""))


# ------------------------------------- A: one execution, one hook pair ----
from longrun.tools import hooks as H  # noqa: E402

events = []
_real_run = H.run


def _rec(kind, **kw):
    events.append(kind)
    return _real_run(kind, **kw)


H.run = _rec
try:
    T.execute("self.info", {}, run_id="v720")
finally:
    H.run = _real_run
check("A1 exactly one PreToolUse", events.count("PreToolUse") == 1, events)
check("A2 exactly one PostToolUse", events.count("PostToolUse") == 1, events)
check("A3 nothing else was emitted in between", len(events) == 2, events)

# ------------------------------------- B: one subjob, one spawn -----------
sid = "v720-sess"
made = SJ.create(sid, "prove the schedule",
                 [{"label": "a"}, {"label": "b", "deps": ["a"]}])
check("B1 the batch was created", made.get("ok") is True, made)

spawned, collected, starts = [], [], []


def _spawn(goal, **kw):
    n = len(spawned) + 1
    spawned.append(goal)
    return {"subagent_id": "sa-%d" % n}


def _collect(subagent_id, **kw):
    collected.append(subagent_id)
    return {"ok": True, "text": "result of %s" % subagent_id}


def _hook(kind, spec):
    if kind == "start":
        starts.append(spec.get("label"))


out = SJ.run(sid, spawn_fn=_spawn, collect_fn=_collect, cap=2, hook=_hook)
check("B2 the batch ran", out.get("ok") is True, out)
check("B3 each subjob started exactly once",
      sorted(starts) == ["a", "b"], starts)
check("B4 each subagent was collected exactly once",
      sorted(collected) == ["sa-1", "sa-2"], collected)
view = SJ.describe(sid)
rows = ((view.get("jobs") or [{}])[0].get("subjobs") or [])
statuses = sorted(str(r.get("status")) for r in rows)
check("B5 every subjob reached done", statuses == ["done", "done"], statuses)

before = len(spawned)
again = SJ.run(sid, spawn_fn=_spawn, collect_fn=_collect, cap=2, hook=_hook)
check("B6 re-running a finished batch dispatches NOTHING",
      len(spawned) == before, spawned[before:])
check("B7 the re-run says so instead of pretending", isinstance(again, dict)
      and (again.get("ok") is False or not again.get("spawned")), again)

# ------------------------------------- C: a failure is not retried --------
sid2 = "v720-sess-2"
SJ.create(sid2, "fail once", [{"label": "x"}])
spawns2 = []


def _spawn_fail(goal, **kw):
    spawns2.append(goal)
    return {"subagent_id": None, "error": "boom"}


SJ.run(sid2, spawn_fn=_spawn_fail, collect_fn=_collect, cap=1)
SJ.run(sid2, spawn_fn=_spawn_fail, collect_fn=_collect, cap=1)
check("C1 a failed subjob is spawned once, not retried in a loop",
      len(spawns2) == 1, spawns2)

print("---")
passed = sum(results)
print("%d/%d PASS" % (passed, len(results)))
sys.exit(0 if passed == len(results) else 1)
