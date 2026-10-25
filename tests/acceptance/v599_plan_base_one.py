#!/usr/bin/env python3
"""v599 (RED) — task plans are 1-based, legacy 0-based graphs migrate.

Plans started at 0, so the panel reads "older plan 0 .. older plan 19" +
"Current plan 21" — plan numbers collide with the 0-based mental model of
node indices and confuse. Plans must start at 1:

- `ensure()` creates `plan: 1` (with a `plan_base: 1` marker);
- `begin_plan()` keeps bumping relatively (1 -> 2);
- `load()` migrates a legacy graph once: every stored plan number + 1
  (untagged nodes count as plan 0 -> 1), sets the marker, persists;
  already-migrated graphs load untouched (idempotent);
- `plan_nodes()` / `add_node()` / `drop_plan()` / `latest_plan_nodes()` /
  the WebUI `planNodes()` default to 1, not 0.

Deterministic: isolated dirs, no model, no network.
Run: python3 tests/acceptance/v599_plan_base_one.py
"""
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_tmp = tempfile.mkdtemp(prefix="lr-plan1-v599-")
os.environ["LONGRUN_CONFIG_DIR"] = os.path.join(_tmp, "cfg")
os.environ["LONGRUN_SESSIONS_DIR"] = os.path.join(_tmp, "sessions")
os.environ["LONGRUN_DATA_DIR"] = _tmp
os.environ["LONGRUN_GRAPH_DIR"] = os.path.join(_tmp, "graphs")
for d in ("cfg", "sessions", "graphs"):
    os.makedirs(os.path.join(_tmp, d), exist_ok=True)
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.plan import taskgraph as tg  # noqa: E402
from longrun.orchestrate.jobs import latest_plan_nodes  # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""))


# ---- A: fresh graphs start at 1 ---------------------------------------------------
g = tg.ensure("v599new", session_id="v599new", goal="demo")
check("A1 new graphs open plan 1, not 0",
      g.get("plan") == 1, repr(g.get("plan")))
check("A2 new graphs carry the 1-based marker",
      g.get("plan_base") == 1, repr(g.get("plan_base")))
n = tg.add_node(tg.load("v599new"), "first step")
check("A3 first nodes are tagged plan 1",
      n.get("plan") == 1, repr(n.get("plan")))
p = tg.begin_plan(tg.load("v599new"))
check("A4 begin_plan bumps relatively (1 -> 2)", p == 2, repr(p))
n2 = tg.add_node(tg.load("v599new"), "second plan step")
check("A5 nodes follow the bump", n2.get("plan") == 2, repr(n2.get("plan")))
check("A6 plan_nodes scopes to the current plan",
      [x["id"] for x in tg.plan_nodes(tg.load("v599new"))] == [n2["id"]])

# ---- B: legacy 0-based graphs migrate once -----------------------------------------
tg.save({"key": "v599leg", "run_id": "v599leg", "session_id": "v599leg",
         "plan": 0, "nodes": [
             {"id": "n1", "label": "old a", "status": "done", "plan": 0},
             {"id": "n2", "label": "old b", "status": "done"},
             {"id": "n3", "label": "old c", "status": "done", "plan": 0}]})
m = tg.load("v599leg")
check("B1 legacy plan counter migrates 0 -> 1",
      m.get("plan") == 1, repr(m.get("plan")))
check("B2 tagged nodes migrate 0 -> 1",
      [x.get("plan") for x in m["nodes"] if x["id"] in ("n1", "n3")] == [1, 1])
check("B3 untagged nodes land on plan 1 (the first plan)",
      [x.get("plan") for x in m["nodes"] if x["id"] == "n2"] == [1])
check("B4 the marker is set", m.get("plan_base") == 1)
again = tg.load("v599leg")
check("B5 migration is idempotent (second load changes nothing)",
      again.get("plan") == 1
      and [x.get("plan") for x in again["nodes"]] == [1, 1, 1],
      repr((again.get("plan"), [x.get("plan") for x in again["nodes"]])))
check("B6 untagged nodes are no longer orphaned from plan 1",
      [x["id"] for x in tg.plan_nodes(again)] == ["n1", "n2", "n3"])

# ---- C: the rest of the seam follows -----------------------------------------------
check("C1 latest_plan_nodes defaults untagged to the first plan (1)",
      [x["id"] for x in latest_plan_nodes([{"id": "a"}, {"id": "b"}])] == ["a", "b"]
      and [x["id"] for x in latest_plan_nodes(
          [{"id": "a"}, {"id": "b", "plan": 2}])] == ["b"])
cur = tg.drop_plan("v599new", 2)
check("C2 the CURRENT plan (2) is refused",
      cur.get("ok") is False and "CURRENT" in (cur.get("error") or ""))
old = tg.drop_plan("v599new", 1)
check("C3 the old plan 1 drops by its 1-based number",
      old.get("ok") is True and old.get("plan") == 1, repr(old))
ui = open(os.path.join(REPO, "webui", "index.html"), encoding="utf-8").read()
_snip = ui.split("function planNodes(g)")[1].split("function ")[0]
check("C4 the WebUI planNodes defaults to 1, not 0",
      "0 : n.plan" not in _snip and "? 1 :" in _snip, _snip[:200])

print("\n%d/%d" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
