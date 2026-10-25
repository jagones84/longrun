#!/usr/bin/env python3
"""v327 — a subjob embraces only ITS RUN's todos (JAG-327).

A re-run of a job REUSES the subjob ids (J6.1 is J6.1 again) but the work belongs to
a NEW run. Before: `_scope_graph` keys on the job id, which is unchanged on a re-run,
so no new plan opened and `subjob_todos` merged the previous run's todos with this
run's — a subjob "embraced" stale work.

Fix: a re-run opens a FRESH plan per participating agent (`jobs._run`), and the two
read-only views (`JobRegistry.subjob_todos`, `longrun.orbit.api._subjobs_of`) scope a
subjob to the LATEST plan it appeared in — so the mapping survives a later, unrelated
plan on the same session but never merges two runs.

Deterministic, no model. Run: python3 tests/acceptance/v327_subjob_run_scope.py
"""
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="sf-327-")
os.environ["LONGRUN_JOBS_FILE"] = os.path.join(TMP, "jobs.json")
os.environ["LONGRUN_AGENTS_FILE"] = os.path.join(TMP, "agents.json")
os.environ["LONGRUN_SESSIONS_DIR"] = os.path.join(TMP, "sessions")
os.environ["LONGRUN_GRAPH_DIR"] = os.path.join(TMP, "graphs")
os.environ["LONGRUN_DB"] = os.path.join(TMP, "events.db")
os.makedirs(os.environ["LONGRUN_SESSIONS_DIR"], exist_ok=True)
os.makedirs(os.environ["LONGRUN_GRAPH_DIR"], exist_ok=True)
sys.path.insert(0, os.path.join(REPO, "src"))
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.agent import agents  # noqa: E402
from longrun.orchestrate import jobs  # noqa: E402
from longrun.plan import taskgraph as tg  # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + detail) if detail else ""))


def read(*parts):
    with open(os.path.join(REPO, *parts), encoding="utf-8") as f:
        return f.read()


# ---- A: the pure helper ---------------------------------------------------
nodes = [{"id": "n1", "plan": 1}, {"id": "n2", "plan": 3}, {"id": "n3", "plan": 3}]
check("A1 latest_plan_nodes keeps only the highest plan",
      [n["id"] for n in jobs.latest_plan_nodes(nodes)] == ["n2", "n3"])
check("A2 an empty list is safe", jobs.latest_plan_nodes([]) == [])
check("A3 nodes without a plan are all kept",
      [n["id"] for n in jobs.latest_plan_nodes([{"id": "a"}, {"id": "b"}])] == ["a", "b"])
check("A4 a single plan is returned whole",
      [n["id"] for n in jobs.latest_plan_nodes([{"id": "a", "plan": 3}])] == ["a"])

# ---- B: subjob_todos scopes a re-run to its OWN plan ----------------------
SID = "sessR"
agents.REGISTRY.designate(SID, name="Worker R")
AID = agents.REGISTRY.list()["agents"][0]["id"]
made = jobs.JOBS.create("run-scope goal", coordinator=None, agents=[AID])
JID = made["job"]["id"]
SUB = JID + ".1"
jobs.JOBS._update(JID, lambda j: j.update({"subjobs": {
    SUB: {"id": SUB, "parent": JID, "agent": AID, "deps": [], "status": "done"}}}))

g = tg.ensure(SID, session_id=SID, goal="run 1")
g["jid"] = JID
g["subjob"] = SUB
tg.save(g)
first = tg.add_node(tg.load(SID), "todo from RUN 1")       # plan 1

tg.begin_plan(tg.load(SID))                                # JAG-327: a re-run's plan
g = tg.load(SID)
g["jid"] = JID
g["subjob"] = SUB
tg.save(g)
second = tg.add_node(tg.load(SID), "todo from RUN 2")      # plan 2

todos = jobs.JOBS.subjob_todos(JID).get(SUB)
check("B1 a re-run's subjob embraces ONLY its own run's todos",
      todos == [second["id"]], str(todos))
check("B2 the previous run's todo is NOT merged in",
      first["id"] not in (todos or []))
det = jobs.JOBS.detail(JID)
check("B3 detail() carries the same run-scoped subset",
      det["subjobs"][SUB]["todos"] == [second["id"]])

# a LATER, unrelated plan on the same session must not erase the mapping
tg.begin_plan(tg.load(SID))
todos2 = jobs.JOBS.subjob_todos(JID).get(SUB)
check("B4 a later unrelated plan does not drop the subjob's todos",
      todos2 == [second["id"]], str(todos2))

# ---- C: the constellation view scopes the same way ------------------------
try:
    from longrun.orbit import api as oapi
    payload = oapi._subjobs_of(
        [{"id": "A1", "session": "s1"}],
        [{"id": "J1", "subjobs": {"J1.1": {"id": "J1.1", "agent": "A1", "deps": [],
                                           "status": "done"}}}],
        {"s1": {"nodes": [{"id": "n1", "subjob": "J1.1", "plan": 1},
                          {"id": "n2", "subjob": "J1.1", "plan": 2}]}})
    check("C1 the constellation takes only the latest plan's todos",
          payload[0]["todos"] == ["n2"], str(payload))
except Exception as e:  # noqa: BLE001
    check("C1 the constellation takes only the latest plan's todos", False, str(e))

# ---- D: wiring ------------------------------------------------------------
src = read("src", "longrun", "orchestrate/jobs.py")
check("D1 the runner opens a fresh plan on a RE-RUN",
      'if _g.get("jid") == jid:' in src and "begin_plan(_g)" in src)
check("D2 subjob_todos uses the latest-plan scope", "latest_plan_nodes([" in src)
apy = read("src", "longrun", "orbit", "api.py")
check("D3 the constellation view uses the shared scope",
      "from longrun.orchestrate.jobs import latest_plan_nodes" in apy)

print("---")
ok = sum(1 for r in results if r)
print("%d/%d PASS" % (ok, len(results)))
sys.exit(0 if ok == len(results) else 1)

