#!/usr/bin/env python3
"""v893 — every org-chart child is connected, the agent row stacks its identity, and a
job never prints `A12 → A12`.

Operator, 2026-11-08:
  *"there are org links not made … solve definitively this error"* · *"NO, too much void
  spaced between columns still too much in the agents panel"* · *"in job panel the
  A12->A12,A22 etcetera shall be placed more left! also no sense A12->A12, it's a self
  giving work"*.

Deterministic: reads the Control deck + the agents registry, no browser, no network.
"""
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
ORBIT = open(os.path.join(REPO, "src", "longrun", "orbit", "web", "orbit.html"),
             encoding="utf-8").read()
AGENTS = open(os.path.join(REPO, "src", "longrun", "agent", "agents.py"),
              encoding="utf-8").read()

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""))


# ---------------- A: an org link exists for EVERY child ------------------------
check("A1 the centred child gets its drop (the missing connector)",
      'if (Math.abs(c.cx - cx) > 1)' not in ORBIT.split("const place = (a, m, x, y)")[1][:4000]
      and 'edges.push("M" + c.cx.toFixed(1) + " " + busY.toFixed(1) + " V" + childTop.toFixed(1)); });' in ORBIT)
check("A2 the bus and the parent stem are both drawn",
      'edges.push("M" + cx.toFixed(1) + " " + (top + NH) + " V" + busY.toFixed(1));' in ORBIT
      and 'edges.push("M" + left.toFixed(1) + " " + busY.toFixed(1) + " H" + right.toFixed(1));' in ORBIT)
check("A3 the backend refuses a self-link / cycle (the data side of the same error)",
      "reports_to would create a cycle" in AGENTS
      and 'target == a["id"]' in AGENTS)

# ---------------- B: the agent cell stacks identity (no spare column) ----------
check("B1 four columns: id | agent | model | menu (v895 moved ROLE.md into the menu)",
      '<col class="c-id"><col class="c-name">\n            <col class="c-model"><col class="c-act">' in ORBIT
      and "<th>Agent</th>" in ORBIT and "<th>Role</th>" not in ORBIT
      and "<th>Reports to</th>" not in ORBIT and "<th>Role.md</th>" not in ORBIT)
check("B2 the cell carries name over role + manager",
      '<td class="acell">' in ORBIT and 'class="aname"' in ORBIT
      and 'class="asub"' in ORBIT and 'class="arole"' in ORBIT
      and 'class="linklike rep" data-aedit="reports_to"' in ORBIT)
check("B3 the editors are still one click away (name/role popover, model, manager)",
      'data-aedit="name"' in ORBIT and 'data-aedit="model"' in ORBIT
      and 'data-aedit="reports_to"' in ORBIT)
check("B4 no dead role/reports column is left behind",
      "col.c-role" not in ORBIT and "col.c-rep" not in ORBIT
      and '<td><button class="btn ghost mini cbtn\' + (a.role' not in ORBIT)
check("B5 the stacked cell is tighter than a control row",
      "table.at td.acell{padding:2px 3px;min-width:0}" in ORBIT)

# ---------------- C: the job line has no self-arrow and sits left --------------
check("C1 the coordinator is named once; the arrow needs a distinct crew",
      "const crew = (j.agents || []).filter(a => a && a !== j.coordinator);" in ORBIT
      and '(crew.length ? \' \u21e2 \' + esc(crew.join(",")) : "")' in ORBIT
      and 'esc(team || "no agents")' not in ORBIT)
check("C2 the relation line is left-aligned under the row",
      "padding:0 8px 5px 8px;font-size:10px" in ORBIT
      and "padding:0 10px 6px 10px}" in ORBIT)

print("---")
passed = sum(results)
print("%d/%d PASS" % (passed, len(results)))
sys.exit(0 if passed == len(results) else 1)
