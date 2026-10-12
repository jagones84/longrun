"""v431 — rewind must restore the REAL todo list (JAG-431).

The live todo list is the per-SESSION task graph (`longrun.plan.taskgraph` →
`data/graphs/<sid>.json`), NOT the legacy global `plan.json`/`tasks.json` the panel
no longer reads. A checkpoint that captured only the legacy stores restored nothing
the UI renders, so a rewind left the todos on screen ("graphical delete only").

This pins that a checkpoint now snapshots + restores the session task graph:
  * functional: an anchor with NO graph → after nodes appear, rollback archives the
    graph (todos truly disappear);
  * functional: an anchor WITH one node → rollback drops the later node;
  * static: create() carries the graph, rollback() restores it, rewind() returns it.

Deterministic, offline, stdlib-only.
"""
import json
import os
import sys
import tempfile
import time

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
tmp = tempfile.mkdtemp(prefix="v431-")
os.environ["LONGRUN_GRAPH_DIR"] = os.path.join(tmp, "graphs")
os.environ["LONGRUN_SESSIONS_DIR"] = os.path.join(tmp, "sessions")
os.environ["LONGRUN_CONFIG_DIR"] = os.path.join(tmp, "cfg")
os.environ["LONGRUN_DATA_DIR"] = os.path.join(tmp, "data")
sys.path.insert(0, os.path.join(REPO, "src"))

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if (detail and not ok) else ""))


from longrun.plan import taskgraph  # noqa: E402
from longrun.memory import checkpoints  # noqa: E402

SID = "sess1"


def _node(nid, created=0.0):
    return {"id": nid, "label": "step " + nid, "status": "done", "deps": [],
            "parent": None, "evidence": [{"text": "did " + nid}], "requires_proof": False,
            "plan": 0, "source": "model", "created": created, "updated": created}


class _FakeSrv:
    def load_plan(self):
        return {"goal": "", "steps": []}

    def load_tasks(self):
        return {"tasks": []}

    def load_session(self, sid):
        return {"id": sid, "messages": []}

    def save_plan(self, plan):
        pass

    def save_tasks(self, store):
        pass

    def save_session(self, sess):
        pass


checkpoints._srv = lambda: _FakeSrv()          # no real server import
checkpoints.CKPT_DIR = os.path.join(tmp, "checkpoints")
os.makedirs(checkpoints.CKPT_DIR, exist_ok=True)

# ---- case A: no graph at anchor -> rollback archives the appeared graph ------
try:
    os.remove(taskgraph._path(SID))
except OSError:
    pass
cpA = checkpoints.create(label="turn before todos", session_id=SID)
check("A1 the manifest records the (empty) graph node count",
      cpA.get("sizes", {}).get("graph_nodes") == 0, cpA.get("sizes"))
# now the turn creates todos
taskgraph.save({"key": SID, "run_id": SID, "session_id": SID, "plan": 0,
                "nodes": [_node("n1"), _node("n2")]})
check("A2 the graph now has 2 nodes", len(taskgraph.load(SID)["nodes"]) == 2, "")
resA = checkpoints.rollback(cpA["id"])
check("A3 rollback reports the graph restore", isinstance(resA.get("graph"), dict), resA)
check("A4 the todo graph is GONE after rollback (not just hidden)",
      taskgraph.load(SID) is None, taskgraph.load(SID))

# ---- case B: one node at anchor -> rollback drops the later one --------------
os.makedirs(taskgraph.GRAPH_DIR, exist_ok=True)
taskgraph.save({"key": SID, "run_id": SID, "session_id": SID, "plan": 0, "nodes": [_node("n1")]})
cpB = checkpoints.create(label="turn with one todo", session_id=SID)
check("B1 the anchor captured the 1-node graph",
      cpB.get("sizes", {}).get("graph_nodes") == 1, cpB.get("sizes"))
taskgraph.save({"key": SID, "run_id": SID, "session_id": SID, "plan": 0,
                "nodes": [_node("n1"), _node("n2")]})
checkpoints.rollback(cpB["id"])
g = taskgraph.load(SID) or {}
check("B2 rollback restores the graph to its anchored state (1 node)",
      len(g.get("nodes", [])) == 1, g)
check("B3 the surviving node is the anchored one",
      (g.get("nodes") or [{}])[0].get("id") == "n1", g)

# ---- case C: LEGACY anchor (no graph in payload) -> prune by timestamp ---------
os.makedirs(taskgraph.GRAPH_DIR, exist_ok=True)
taskgraph.save({"key": SID, "run_id": SID, "session_id": SID, "plan": 0, "nodes": []})
cpC = checkpoints.create(label="legacy anchor", session_id=SID)
# emulate a pre-fix checkpoint: strip the graph payload
p = checkpoints._snapshot_path(cpC["id"])
with open(p, encoding="utf-8") as f:
    payload = json.load(f)
payload.pop("graph", None)
with open(p, "w", encoding="utf-8") as f:
    f.write(json.dumps(payload))
# the rewound turn adds nodes AFTER the anchor
now = time.time() + 5
taskgraph.save({"key": SID, "run_id": SID, "session_id": SID, "plan": 0,
                "nodes": [_node("n1", now), _node("n2", now)]})
resC = checkpoints.rollback(cpC["id"])
check("C1 legacy rollback reports a prune",
      isinstance(resC.get("graph"), dict) and resC["graph"].get("legacy") is True, resC)
gC = taskgraph.load(SID) or {}
check("C2 legacy rollback drops the nodes added after the anchor",
      len(gC.get("nodes", [])) == 0, gC)

# ---- static wiring ----------------------------------------------------------
ck = open(os.path.join(REPO, "src", "longrun", "memory", "checkpoints.py"), encoding="utf-8").read()
rw = open(os.path.join(REPO, "src", "longrun", "memory", "rewind.py"), encoding="utf-8").read()
check("S1 create() snapshots the session graph", 'payload["graph"] = _load_graph(' in ck, "")
check("S2 rollback() restores the session graph", "_restore_graph(manifest" in ck, "")
check("S3 _load_graph/_restore_graph exist",
      "def _load_graph(" in ck and "def _restore_graph(" in ck, "")
check("S4 rewind() returns the graph outcome", '"graph": restored.get("graph")' in rw, "")
check("S5 legacy anchors fall back to a timestamp prune",
      "def _prune_graph_after(" in ck and "_prune_graph_after(manifest" in ck, "")

print("---")
ok = sum(results)
print("%d/%d PASS" % (ok, len(results)))
sys.exit(0 if ok == len(results) else 1)
