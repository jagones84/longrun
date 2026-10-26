#!/usr/bin/env python3
"""v670 — F3: evidence carries sources, revisions and a claim marker.

`evidence` was a free-text string, so "closed on a sentence" and "closed on a
file:line" looked identical. This pins the lifecycle slice: an entry may name its
sources, a close without one is recorded as a CLAIM (visible, not refused), and a
sourced close retires the earlier claims.

Deterministic, no live model, no network, no server.
"""
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="sf-v670-")
os.environ["LONGRUN_CONFIG_DIR"] = os.path.join(TMP, "cfg")
os.environ["LONGRUN_SESSIONS_DIR"] = os.path.join(TMP, "sessions")
os.environ["LONGRUN_EDITS_DIR"] = os.path.join(TMP, "edits")
os.environ["LONGRUN_RUNS_DIR"] = os.path.join(TMP, "runs")
os.environ["LONGRUN_DATA_DIR"] = os.path.join(TMP, "data")
os.environ["LONGRUN_DB"] = os.path.join(TMP, "events.db")
os.environ["LONGRUN_GRAPH_DIR"] = os.path.join(TMP, "graphs")
os.environ["LONGRUN_PROJECTS_DIR"] = os.path.join(TMP, "projects")
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.plan import taskgraph             # noqa: E402
from longrun.tools import registry             # noqa: E402
from longrun.core import server                # noqa: E402,F401 — breaks the import cycle
from longrun.agent import agent                # noqa: E402

registry._external_tools = lambda: {}
results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""))


def _fresh(sid, label="step A", status="doing"):
    g = taskgraph.ensure(sid, session_id=sid)
    return g, taskgraph.add_node(g, label, status=status)


# ---- A. source normalisation ------------------------------------------------
e = taskgraph._evidence_entry("read it", sources=["src/x.py:42"])
check("A1 'path:line' becomes a start/end ref",
      e.get("sources") == [{"path": "src/x.py", "start": 42, "end": 42}], e.get("sources"))
e2 = taskgraph._evidence_entry("range", sources=[{"path": "a.py", "start": 3, "end": 9}])
check("A2 a dict keeps its range", e2["sources"] == [{"path": "a.py", "start": 3, "end": 9}])
check("A3 a bare path is accepted",
      taskgraph._evidence_entry("x", sources=["README.md"])["sources"] == [{"path": "README.md"}])
check("A4 junk is dropped, never stored",
      "sources" not in taskgraph._evidence_entry("x", sources=[None, "", {"nope": 1}]))
check("A5 claim is a flag on the entry",
      taskgraph._evidence_entry("x", claim=True).get("claim") is True)

# ---- B. close semantics -----------------------------------------------------
g, n = _fresh("f3b")
node = taskgraph.complete_node(g, node_id=n["id"], evidence="ran the tests",
                               sources=["tests/battery.sh:1"])
ev = node["evidence"][-1]
check("B1 a sourced close keeps its refs", ev.get("sources") == [
    {"path": "tests/battery.sh", "start": 1, "end": 1}], ev.get("sources"))
check("B2 a sourced close is not a claim", not ev.get("claim"))

g2, n2 = _fresh("f3b2")
node2 = taskgraph.complete_node(g2, node_id=n2["id"], evidence="I looked at it")
check("B3 a close without a source is MARKED as a claim",
      node2["evidence"][-1].get("claim") is True, node2["evidence"][-1])

g3, n3 = _fresh("f3b3")
node3 = taskgraph.complete_node(g3, node_id=n3["id"], evidence="checked", observed=True)
check("B4 an observed proof is never a claim",
      not node3["evidence"][-1].get("claim"), node3["evidence"][-1])

g4, n4 = _fresh("f3b4")
taskgraph.complete_node(g4, node_id=n4["id"], evidence="a sentence")
node4 = taskgraph.complete_node(g4, node_id=n4["id"], evidence="the real proof",
                                sources=["src/longrun/agent/agent.py:3410"])
current = taskgraph.current_evidence(node4)
check("B5 a sourced close retires the earlier claim",
      any(e.get("superseded") for e in node4["evidence"])
      and len(current) == 1 and "real proof" in current[0]["text"],
      [e.get("text") for e in current])
check("B6 the node still counts as closed", taskgraph._has_evidence(node4) is True)

g5 = taskgraph.ensure("f3b5", session_id="f3b5")
n5 = taskgraph.add_node(g5, "already done", status="done", evidence="trust me")
check("B7 a node created already done gets the same marker",
      n5["evidence"][0].get("claim") is True)

# ---- C. the chat path forwards sources -------------------------------------
sess = {"id": "f3c", "messages": [], "workspace": ""}
g6, n6 = _fresh("f3c")
changed, errors = agent._apply_chat_todo_updates(
    sess, {"steps": [{"id": n6["id"], "status": "done", "evidence": "wrote it",
                      "sources": ["src/longrun/plan/taskgraph.py:404"]}]},
    lambda *a, **k: None)
stored = taskgraph.find(taskgraph.load("f3c"), node_id=n6["id"])["evidence"][-1]
check("C1 todo.update forwards sources",
      changed == 1 and not errors
      and stored.get("sources") == [{"path": "src/longrun/plan/taskgraph.py",
                                     "start": 404, "end": 404}],
      stored.get("sources"))
check("C2 a sourced close is not flagged as a claim", not stored.get("claim"))

g7, n7 = _fresh("f3c2")
agent._apply_chat_todo_updates(
    sess | {"id": "f3c2"},
    {"steps": [{"id": n7["id"], "status": "done", "evidence": "done, trust me"}]},
    lambda *a, **k: None)
stored7 = taskgraph.find(taskgraph.load("f3c2"), node_id=n7["id"])["evidence"][-1]
check("C3 without sources the close is a claim", stored7.get("claim") is True, stored7)

# ---- D. the panel shows the difference -------------------------------------
with open(os.path.join(REPO, "webui", "index.html"), encoding="utf-8") as f:
    UI = f.read()
check("D1 the plan row shows the source count and the claim count",
      "_refs" in UI and "_claims" in UI and "${src}${claim}" in UI)
check("D2 the detail view names the sources and the retired entries",
      "(claim — no source)" in UI and "(superseded)" in UI)

print("\n%d/%d" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
