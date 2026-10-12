"""v433 — rewind to just BEFORE a specific todo (JAG-431d).

The user's gesture: "delete from this todo" / "redo this step". `rewind_to_node` prunes
the task graph AT the node (the node and every later one vanish), rolls the transcript
back to the nearest turn anchor, and reverts the harness's later file writes. This is
what makes the RH todos panel and the chat agree after a rewind.

Deterministic, offline, stdlib-only.
"""
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
tmp = tempfile.mkdtemp(prefix="v433-")
os.environ["LONGRUN_GRAPH_DIR"] = os.path.join(tmp, "graphs")
os.environ["LONGRUN_SESSIONS_DIR"] = os.path.join(tmp, "sessions")
os.environ["LONGRUN_CONFIG_DIR"] = os.path.join(tmp, "cfg")
os.environ["LONGRUN_DATA_DIR"] = os.path.join(tmp, "data")
os.environ["LONGRUN_EDITS_DIR"] = os.path.join(tmp, "edits")
os.environ["LONGRUN_DB"] = os.path.join(tmp, "events.db")
sys.path.insert(0, os.path.join(REPO, "src"))

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if (detail and not ok) else ""))


from longrun.plan import taskgraph  # noqa: E402
from longrun.memory import checkpoints, rewind  # noqa: E402

SID = "sess-n"


def _node(nid, created):
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

    def save_plan(self, p):
        pass

    def save_tasks(self, t):
        pass

    def save_session(self, s):
        pass


checkpoints._srv = lambda: _FakeSrv()
checkpoints.CKPT_DIR = os.path.join(tmp, "checkpoints")
os.makedirs(checkpoints.CKPT_DIR, exist_ok=True)
os.makedirs(taskgraph.GRAPH_DIR, exist_ok=True)


def _graph(nodes):
    return {"key": SID, "run_id": SID, "session_id": SID, "plan": 0, "nodes": nodes}


def _ids():
    return [n["id"] for n in (taskgraph.load(SID) or {}).get("nodes", [])]


# ---- case A: real turn anchor present --------------------------------------
taskgraph.save(_graph([_node("n1", 100), _node("n2", 200)]))
checkpoints.create_turn(SID, 1)                      # anchor = the 2-node state
g = taskgraph.load(SID)
g["nodes"].append(_node("n3", 300))                  # the step to undo
taskgraph.save(g)
check("A1 three nodes before the rewind", _ids() == ["n1", "n2", "n3"], _ids())
resA = rewind.rewind_to_node(SID, "n3")
check("A2 rewind_to_node succeeds", resA.get("ok") is True, resA)
check("A3 the target and later steps are gone",
      _ids() == ["n1", "n2"], _ids())

# ---- case B: no turn anchor (best-effort prune) ----------------------------
taskgraph.save(_graph([_node("n1", 100), _node("n2", 200)]))
_orig_marks = rewind.marks
rewind.marks = lambda sid, limit=500: []
resB = rewind.rewind_to_node(SID, "n2")
rewind.marks = _orig_marks
check("B1 no-anchor rewind still succeeds via the graph prune", resB.get("ok") is True, resB)
check("B2 it drops the target step", _ids() == ["n1"], _ids())

# ---- case C: unknown node --------------------------------------------------
resC = rewind.rewind_to_node(SID, "nZZ")
check("C1 unknown node is a clean error", resC.get("ok") is False and "not found" in str(resC.get("error")), resC)

# ---- static wiring ---------------------------------------------------------
rw = open(os.path.join(REPO, "src", "longrun", "memory", "rewind.py"), encoding="utf-8").read()
ck = open(os.path.join(REPO, "src", "longrun", "memory", "checkpoints.py"), encoding="utf-8").read()
api = open(os.path.join(REPO, "src", "longrun", "core", "httpapi.py"), encoding="utf-8").read()
idx = open(os.path.join(REPO, "webui", "index.html"), encoding="utf-8").read()
check("S1 rewind_to_node exists", "def rewind_to_node(" in rw, "")
check("S2 checkpoints expose _prune_graph_at", "def _prune_graph_at(" in ck, "")
check("S3 the API accepts a `node` rewind",
      'body.get("node")' in api and "rewind_to_node" in api, "")
check("S4 the WebUI exposes rewindToTodo + per-todo ⏮ buttons",
      "function rewindToTodo(" in idx and 'class="task-rw"' in idx and 'class="tc-rw"' in idx, "")
# JAG-431f: the confirm popup must sit ABOVE the rewind dialog (it was z-index 30 < 44).
import re as _re  # noqa: E402
_confirm_z = _re.search(r'ov\.id = "sfConfirm";\s*ov\.style\.cssText = "[^"]*z-index:\s*(\d+)', idx)
_rw_z = _re.search(r"#rwDlg \{[^}]*z-index:\s*(\d+)", idx)
check("S5 the confirm popup sits ABOVE the rewind dialog",
      _confirm_z and _rw_z and int(_confirm_z.group(1)) > int(_rw_z.group(1)),
      (_confirm_z and _confirm_z.group(1), _rw_z and _rw_z.group(1)))
check("S6 turn anchors are bounded per session (prune_turns)",
      "def prune_turns(" in ck and "prune_turns(session_id)" in ck, "")

print("---")
ok = sum(results)
print("%d/%d PASS" % (ok, len(results)))
sys.exit(0 if ok == len(results) else 1)
