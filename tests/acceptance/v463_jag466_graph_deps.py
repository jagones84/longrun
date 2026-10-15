#!/usr/bin/env python3
"""v463 — JAG-466: task-list indices and dependencies must not drift.

Three proven defects fixed together:
  * `update_todos` with a 0-based `index` resolved against the FULL current plan
    while the model is shown only the OPEN steps, so once an earlier step was closed
    `{"index": 0}` re-opened a DONE step as `doing` (and `doing` rows appeared on
    steps nobody was working on);
  * a re-plan filtered the model's list with `_missing()` BEFORE mapping `deps`, so a
    dependency was silently dropped or pointed at the wrong step;
  * a vision-capable model whose attachment could not be read/sent got NO note at
    all, leaving it free to invent a description of a picture it never received.

Deterministic, isolated (throwaway LONGRUN_* dirs), no model/network.
"""
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

TMP = tempfile.mkdtemp(prefix="sf-v463-")
for _k in ("CONFIG_DIR", "SESSIONS_DIR", "EDITS_DIR", "RUNS_DIR", "GRAPH_DIR", "ROLES_DIR"):
    os.environ["LONGRUN_" + _k] = os.path.join(TMP, _k)
    os.makedirs(os.path.join(TMP, _k), exist_ok=True)
os.environ["LONGRUN_DB"] = os.path.join(TMP, "events.db")
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.core import server as S  # noqa: E402  (import order: server first)
from longrun.plan import taskgraph as TG  # noqa: E402
from longrun.agent import agent as A  # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + (("  :: " + str(detail)) if detail and not ok else ""))


# ---- A: `index` resolves against the list the MODEL is shown ------------------
g = TG.ensure("v463a")
n1 = TG.add_node(g, "step one")
g = TG.load("v463a")
TG.update_node(g, "n1", status="doing")
g = TG.load("v463a")
TG.complete_node(g, "n1", evidence="did one")
g = TG.load("v463a")
n2 = TG.add_node(g, "step two")
n3 = TG.add_node(g, "step three")
g = TG.load("v463a")

shown = [ln for ln in TG.render_todos(g, compact=True).splitlines() if "step" in ln]
check("A1 the state block shows only the OPEN steps",
      len(shown) == 2 and "step two" in shown[0] and "step three" in shown[1], shown)
r0 = A._resolve_graph_node(g, {"index": 0})
r1 = A._resolve_graph_node(g, {"index": 1})
check("A2 index 0 -> the FIRST OPEN step (never a closed one)",
      r0 and r0["id"] == n2["id"], str(r0 and r0["id"]))
check("A3 index 1 -> the second open step",
      r1 and r1["id"] == n3["id"], str(r1 and r1["id"]))
check("A4 an id still wins (id-first contract preserved)",
      (A._resolve_graph_node(g, {"id": "n1"}) or {}).get("id") == n1["id"])
check("A5 a label still resolves inside the current plan",
      (A._resolve_graph_node(g, {"label": "step three"}) or {}).get("id") == n3["id"])
# no open steps at all: the index falls back to the full current plan
g2 = TG.ensure("v463a2")
TG.add_node(g2, "only")
g2 = TG.load("v463a2")
TG.complete_node(g2, "n1", evidence="x")
g2 = TG.load("v463a2")
check("A6 with no open steps the index falls back to the plan",
      (A._resolve_graph_node(g2, {"index": 0}) or {}).get("label") == "only")

# ---- B: a re-plan keeps every dependency -------------------------------------
gb = TG.ensure("v463b")
B = TG.add_node(gb, "B")
gb = TG.load("v463b")
added = TG.apply_write_todos(gb, [{"label": "A"}, {"label": "B"},
                                  {"label": "C", "deps": [1]}], skip_existing=True)
gc = [n for n in added if n["label"] == "C"]
check("B1 a dep on an EXISTING step survives a re-plan",
      len(gc) == 1 and gc[0]["deps"] == [B["id"]], gc[0]["deps"] if gc else "no C")
check("B2 the existing step is not duplicated",
      len([n for n in TG.load("v463b")["nodes"] if n["label"] == "B"]) == 1)

gb2 = TG.ensure("v463b2")
B2 = TG.add_node(gb2, "B")
gb2 = TG.load("v463b2")
added2 = TG.apply_write_todos(gb2, [{"label": "NEW"}, {"label": "B"},
                                    {"label": "C", "deps": [1]}], skip_existing=True)
gc2 = [n for n in added2 if n["label"] == "C"]
new2 = [n for n in added2 if n["label"] == "NEW"]
check("B3 a dep is never retargeted at a NEW step",
      len(gc2) == 1 and gc2[0]["deps"] == [B2["id"]]
      and new2 and gc2[0]["deps"] != [new2[0]["id"]],
      "%s (new=%s)" % (gc2[0]["deps"] if gc2 else "no C",
                       new2[0]["id"] if new2 else "-"))

# ---- C: skip_existing still dedupes (within the payload too) -----------------
gb3 = TG.ensure("v463b3")
TG.add_node(gb3, "A")
gb3 = TG.load("v463b3")
added3 = TG.apply_write_todos(gb3, [{"label": "A"}, {"label": "D"}, {"label": "D"}],
                              skip_existing=True)
check("C1 skip_existing does not re-create an existing step",
      all(n["label"] != "A" for n in added3), [n["label"] for n in added3])
check("C2 an in-payload duplicate is created once",
      len([n for n in added3 if n["label"] == "D"]) == 1, [n["label"] for n in added3])

# ---- D: the harness never leaves a vision-capable model guessing -------------
def _read(*parts):
    with open(os.path.join(REPO, *parts), encoding="utf-8") as f:
        return f.read()


AGENT_SRC = _read("src", "longrun", "agent", "agent.py")
check("D1 an unusable attachment still produces an explicit harness note",
      "_sent <= 0" in AGENT_SRC and "were detected but could NOT be" in AGENT_SRC
      and "never invent a" in AGENT_SRC)
check("D2 a partially delivered batch says how many are missing",
      "_sent < len(paths)" in AGENT_SRC and "could not be attached" in AGENT_SRC)
check("D3 the text-only note is still in place (no regression)",
      "is not marked " in AGENT_SRC and "vision-capable)" in AGENT_SRC
      and "You CANNOT see these images" in AGENT_SRC)

# ---- E: the planner no longer pre-filters the model's list -------------------
TG_SRC = _read("src", "longrun", "plan", "taskgraph.py")
check("E1 apply_write_todos accepts skip_existing",
      "skip_existing=False" in TG_SRC and "_seen[_k] = node[\"id\"]" in TG_SRC)
check("E2 the agent hands the UNFILTERED list to apply_write_todos",
      "taskgraph.apply_write_todos(graph, todos or [], skip_existing=True)" in AGENT_SRC)
check("E3 neither planner path pre-filters with _missing any more",
      "_missing(graph, parse_todos(answer)[0])" not in TG_SRC)
check("E4 _missing is kept (its contract is still pinned by v195)",
      "def _missing(graph, todos)" in TG_SRC)

print("---")
ok = sum(results)
print("%d/%d PASS" % (ok, len(results)))
sys.exit(0 if ok == len(results) else 1)
