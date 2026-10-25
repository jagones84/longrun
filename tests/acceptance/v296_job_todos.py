#!/usr/bin/env python3
"""v296 — job↔todo coherence (JAG-299): scope an agent's task graph to the job.

Fixes the confusion where J2's still-open todos leaked into J3's run on the same
agent, producing a HUMAN-IN-THE-LOOP pivot (the model then reasoned about a task
list it was told not to touch). Locked here:
  * a job dispatch starts a FRESH plan on the agent's graph and tags it with the job id;
  * every node created under a job carries that `jid`;
  * the job messages no longer contradict the harness ("do NOT create or update a
    task list" fought AUTONOMOUS GOAL MODE's "FIRST emit write_todos");
  * the UI shows the job tag (constellation cluster header + main-app todo).

Deterministic, no live model. Run: python3 tests/v296_job_todos.py
"""
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(REPO, "src"))
sys.path.insert(0, os.path.join(REPO, "src"))

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + detail) if detail else ""))


def read(*parts):
    with open(os.path.join(REPO, *parts), encoding="utf-8") as f:
        return f.read()


from longrun.plan import taskgraph as tg  # noqa: E402
from longrun.orchestrate import jobs as jobs_mod  # noqa: E402

SID = "v296scope"
g = tg.ensure(SID, session_id=SID, goal="unscoped")
n0 = tg.add_node(g, "step created with no active job")
check("a node built with no scoped job has no jid", n0.get("jid") is None)

# a job dispatch scopes the graph: fresh plan + job tag
jobs_mod.JOBS._scope_graph(SID, "J2", "goal of J2")
g = tg.load(SID)
check("scoping sets the graph's job id", g.get("jid") == "J2")
check("scoping bumps the plan", g.get("plan") == 2)
n1 = tg.add_node(g, "step for J2")
check("a node inherits the job id", n1.get("jid") == "J2")

# the same job (e.g. the coordinator's second turn) must NOT open another plan
jobs_mod.JOBS._scope_graph(SID, "J2", "goal of J2")
check("the same job does not bump the plan again", tg.load(SID).get("plan") == 2)

# a DIFFERENT job starts a fresh plan and moves the tag
jobs_mod.JOBS._scope_graph(SID, "J3", "goal of J3")
g = tg.load(SID)
check("a new job starts a fresh plan", g.get("plan") == 3 and g.get("jid") == "J3")
g = tg.load(SID)
check("the previous job's nodes are NOT on the current plan",
      all((n.get("plan", 1) != 3) for n in g["nodes"] if n.get("jid") == "J2"))
n2 = tg.add_node(g, "step for J3")
check("a node created under the new job carries the new jid", n2.get("jid") == "J3")
check("render_todos only lists the current plan",
      "step for J3" in tg.render_todos(tg.load(SID)) and "step for J2" not in tg.render_todos(tg.load(SID)))

# JAG-301: even when the job's plan still has an OPEN node, a manual turn must not
# inherit the job tag (the worker clears it — mimicked here at the graph level).
jobs_mod.JOBS._scope_graph(SID, "J4", "goal of J4")
g = tg.load(SID)
n_open = tg.add_node(g, "still-open job step")
check("an open job step still carries the job tag", n_open.get("jid") == "J4")
g = tg.load(SID)
g["jid"] = None                     # what a manual turn's worker does
tg.save(g)
n_manual = tg.add_node(tg.load(SID), "manual step on the same session")
check("a manual step does NOT inherit the job tag", n_manual.get("jid") is None,
      "got %r" % n_manual.get("jid"))

# ------------------------------------------------------------------ source locks
j = read("src", "longrun", "orchestrate/jobs.py")
check("_run_agent takes a jid", "def _run_agent(self, sid, message, model=None, jid=None," in j)
check("dispatch scopes the graph to the job", "self._scope_graph(sid, jid, message)" in j)
check("job messages no longer forbid a task list", "do NOT create or update a task list" not in j)
check("every job turn passes jid", j.count("jid=jid") >= 3)

t = read("src", "longrun", "plan/taskgraph.py")
check("add_node tags the node with the graph jid", '"jid": graph.get("jid")' in t)

# JAG-301: the job tag is per-TURN — a manual turn must clear it, else a finished
# job's tag lingered and mislabelled later todos (the same J2/J3 confusion).
s = read("src", "longrun", "core/server.py") + read("src", "longrun", "core/httpapi.py")
check("chat_stream_gen takes a per-turn jid",
      "def chat_stream_gen(sess, message, model, mark=None, autonomous=False, jid=None," in s)
check("the turn writes its jid onto the graph", '_existing["jid"] = jid' in s)
check("the non-stream chat path clears the job tag", '_ex["jid"] = None' in s)
check("a job passes its jid into the turn", "autonomous=True, jid=jid" in j)

o = read("src", "longrun", "orbit", "web", "orbit.html")
check("constellation header shows the job tag", "jtag" in o and "n.jid" in o)

gi = read("webui", "index.html")
check("main app renders the job tag on a todo", "_nodeJob" in gi and "n.jid" in gi)

print("---")
passed = sum(results)
print("%d/%d PASS" % (passed, len(results)))
sys.exit(0 if passed == len(results) else 1)

