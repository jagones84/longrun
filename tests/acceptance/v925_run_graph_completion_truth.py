#!/usr/bin/env python3
"""v925 — run-finalize must not overstate completion.

Deterministic — no model, no server, no network. Regression for the live
reproduction of 2026-11-09 (HEAD fc301dc):

  `finish_run_graph` closed EVERY still-open node as `done` with the evidence
  string "run <id> completed: <goal>" whenever the run was not operator-aborted
  — including a run that ended at `max_steps` or crashed, while the run record
  honestly said `termination: max_steps`. The plan panel then showed work the
  run never did, marked done by a fabricated claim.

Contract:
  A) a run whose termination is not `completed` closes its open nodes as
     `cancelled` with evidence that says the run did NOT complete;
  B) a genuinely completed run keeps the existing behaviour (open nodes -> done
     with the completion evidence);
  C) the same branch covers `error` and `aborted` terminations passed through
     from either run loop (agent.agent_run, api_v02._result).
"""
import json
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SRC = os.path.join(REPO, "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

TMP = tempfile.mkdtemp(prefix="sf-v925-")
os.environ["LONGRUN_DATA_DIR"] = TMP
os.environ["LONGRUN_SESSIONS_DIR"] = os.path.join(TMP, "sessions")
os.makedirs(os.environ["LONGRUN_SESSIONS_DIR"], exist_ok=True)

checks = []


def check(name, passed, detail=""):
    checks.append(bool(passed))
    print(("PASS " if passed else "FAIL ") + name
          + ((" :: " + str(detail)) if (detail and not passed) else ""))


from longrun.core import server as _server  # noqa: E402,F401
from longrun.plan import taskgraph  # noqa: E402
from longrun.agent import agent as agent_mod  # noqa: E402


def _seed_graph(run_id, statuses):
    """Write a graph file with open nodes the way a run leaves them."""
    g = {"key": run_id, "run_id": run_id, "session_id": None, "goal": "the goal",
         "nodes": [{"id": "n%d" % (i + 1), "label": "step %d" % (i + 1),
                    "status": st, "deps": [], "evidence": []}
                   for i, st in enumerate(statuses)]}
    taskgraph.save(g)
    return g


def _node(run_id, nid):
    g = taskgraph.load(run_id)
    for n in (g or {}).get("nodes", []):
        if n["id"] == nid:
            return n
    return {}


# A: a run cut off by max_steps — open nodes become `cancelled`, never "done done"
_seed_graph("run_v925a", ["doing", "todo"])
out = agent_mod.finish_run_graph("run_v925a", None, "the goal", termination="max_steps")
_g2 = taskgraph.load("run_v925a")
check("A1 the finalize ran over the graph's open nodes",
      len((out or {}).get("nodes") or []) == 2
      and all(n.get("status") == "cancelled" for n in (_g2 or {}).get("nodes", [])),
      str(out)[:200])
_n1 = _node("run_v925a", "n1")
check("A2 an open node of a max_steps run is CANCELLED (not done)",
      _n1.get("status") == "cancelled", str(_n1))
check("A3 its evidence says the run did NOT complete (no fabricated 'completed')",
      "not completed" in json.dumps(_n1.get("evidence") or [])
      and "completed: " not in json.dumps(_n1.get("evidence") or []),
      str(_n1.get("evidence")))

# B: a genuinely completed run keeps today's behaviour
_seed_graph("run_v925b", ["doing", "todo"])
agent_mod.finish_run_graph("run_v925b", None, "the goal")
_n1b = _node("run_v925b", "n1")
check("B1 a completed run closes open nodes as `done` (unchanged behaviour)",
      _n1b.get("status") == "done", str(_n1b))
check("B2 the completion evidence keeps its original shape",
      any("run run_v925b completed: the goal" in json.dumps(e)
          for e in (_n1b.get("evidence") or [])), str(_n1b.get("evidence")))

# C: the branch covers every non-completed termination the loops emit
_seed_graph("run_v925c", ["doing"])
agent_mod.finish_run_graph("run_v925c", None, "the goal", termination="error")
check("C1 an `error` run also cancels its open nodes",
      _node("run_v925c", "n1").get("status") == "cancelled", "")
_seed_graph("run_v925d", ["doing"])
agent_mod.finish_run_graph("run_v925d", None, "the goal", termination="aborted")
# JAG-462 (letter): an ABORTED run is finalized by NOBODY — the open nodes stay
# open (a resume expects them); only max_steps/error close as `cancelled`.
check("C2 an `aborted` run finalizes NOTHING (its open nodes stay open)",
      _node("run_v925d", "n1").get("status") == "doing", str(_node("run_v925d", "n1")))

print("---")
print("%d/%d PASS" % (sum(checks), len(checks)))
sys.exit(0 if all(checks) else 1)
