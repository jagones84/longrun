#!/usr/bin/env python3
"""v810 — an open step stranded in an OLD plan can be carried into the current one.

A plan is only a SCOPE: `render_todos` feeds the CURRENT plan to the model and the
panel focuses on it, so an open step left in history is invisible to the model and
can never be closed. Measured live 2026-11-04: 128 open nodes stranded across old
plans in one session (plan 79). The only human moves were "delete the plan" (loses
the work) or "close it blind". This test locks the missing one:

  A) `taskgraph.carry_node` re-tags the SAME node (id must survive: transcript
     cards resolve by id), makes it visible to the plan + the model prompt, and
     prunes deps that point into the abandoned plan;
  B) deps on a CURRENT node survive; carrying a current node is a no-op;
  C) `POST .../graph/nodes {action:"carry"}` is the operator door (404 on junk);
  D) the panel offers "→ current plan" only for a node outside the current plan.

Deterministic, no live model, no network, no server.
"""
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="sf-v810-")
os.environ["LONGRUN_CONFIG_DIR"] = os.path.join(TMP, "cfg")
os.environ["LONGRUN_SESSIONS_DIR"] = os.path.join(TMP, "sessions")
os.environ["LONGRUN_DATA_DIR"] = os.path.join(TMP, "data")
os.environ["LONGRUN_DB"] = os.path.join(TMP, "events.db")
os.environ["LONGRUN_GRAPH_DIR"] = os.path.join(TMP, "graphs")
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.plan import taskgraph             # noqa: E402
from longrun.core import server                # noqa: E402,F401 — breaks the import cycle
from longrun.agent import agent                # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""))


# ------------------------------- A. carry makes a stranded step CURRENT work --
g = taskgraph.ensure("carry-a", session_id="carry-a")
p1 = taskgraph.add_node(g, "old step one")
p2 = taskgraph.add_node(g, "old step two", deps=[p1["id"]])
plan1 = g["plan"]
taskgraph.begin_plan(g)                       # plan 2 opens, old nodes stay
q1 = taskgraph.add_node(g, "current step")
check("A0 the old nodes are outside the current plan",
      plan1 != g["plan"] and q1["plan"] == g["plan"], (plan1, g["plan"]))

carried = taskgraph.carry_node(g, p2["id"])
check("A1 the carried node joins the current plan", carried["plan"] == g["plan"], carried)
check("A2 its id is unchanged (transcript cards still resolve)", carried["id"] == p2["id"])
check("A3 the dep into the abandoned plan is pruned", carried["deps"] == [], carried["deps"])
check("A4 it is now part of the model's plan",
      p2["id"] in [n["id"] for n in taskgraph.plan_nodes(g)])
check("A5 the prompt shows it again", "old step two" in taskgraph.render_todos(g),
      taskgraph.render_todos(g)[:200])
check("A6 the node is still findable by id",
      (taskgraph.find(g, node_id=p2["id"]) or {}).get("plan") == g["plan"])

# deps on a CURRENT node must survive the carry
taskgraph.update_node(g, p1["id"], deps=[q1["id"]])
taskgraph.carry_node(g, p1["id"])
check("A7 a dep on a CURRENT node is kept", taskgraph.find(g, node_id=p1["id"])["deps"] == [q1["id"]],
      taskgraph.find(g, node_id=p1["id"])["deps"])

# ------------------------------------------- B. idempotent on current nodes ---
same = taskgraph.carry_node(g, q1["id"])
check("B1 carrying a current node is a no-op", same["plan"] == g["plan"])

# --------------------------------------------------- C. the operator door -----
res, err, code = agent.graph_post("carry-a", {"action": "carry", "id": p1["id"]})
check("C1 the API action answers 200", code == 200 and not err, err)
res_bad, err_bad, code_bad = agent.graph_post("carry-a", {"action": "carry", "id": "n999"})
check("C2 an unknown id is a 404", code_bad == 404 and err_bad, (code_bad, err_bad))

# --------------------------------------------------------- D. the panel -------
UI = os.path.join(REPO, "webui", "index.html")
ui = open(UI, encoding="utf-8").read()
check("D1 the panel offers the carry control", 'data-a="carry"' in ui)
check("D2 the control is only rendered outside the current plan",
      "n.plan !== (graph.plan == null ? 1 : graph.plan)" in ui)
check("D3 the action posts action:'carry'", 'body.action = "carry"' in ui)
check("D4 the button names both plans",
      "into the current plan" in ui and "from older plan" in ui)

print("---")
passed = sum(results)
print("%d/%d PASS" % (passed, len(results)))
sys.exit(0 if passed == len(results) else 1)
