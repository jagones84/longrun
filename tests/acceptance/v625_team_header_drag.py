#!/usr/bin/env python3
"""v625 — Control team headers drag (Sessions sidebar parity) + A1 fix.

  A  the group header shows a grip and grabs (same affordance as rows).
  B  headers bind the shared DragSort engine as tr.grp-head items with a
     team-only commit path (kind=team, stray/__none__ never persisted).
  C  groups render in the shared stored team order (no second truth).
  D  header tail clicks die after a drag (no accidental toggle).

Deterministic: static source contract, no server, no model, no network.
Run: python3 tests/acceptance/v625_team_header_drag.py
"""
import os

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _read(*parts):
    with open(os.path.join(REPO, *parts), encoding="utf-8") as f:
        return f.read()


ORBIT = _read("src", "longrun", "orbit", "web", "orbit.html")

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""))


check("A1 header carries a team grip with grab cursors",
      'title="drag to reorder this team"' in ORBIT
      and "tr.grp-head .grp-h{" in ORBIT and "cursor:grab" in ORBIT)
check("A2 header drag states visible",
      "tr.grp-head.dragging" in ORBIT and "tr.grp-head.drop-before" in ORBIT)
check("B1 headers bind DragSort as grp-head items",
      'itemSel: "tr.grp-head"' in ORBIT and 'idKey: "grp"' in ORBIT)
check("B2 team moves persist kind=team, stray buckets filtered",
      '_persistTeamOrder' in ORBIT and '{kind: "team", ids' in ORBIT
      and "teamsOnly" in ORBIT)
check("C1 groups render in the shared stored team order",
      "this._teamBase = groups.map(g => g.id)" in ORBIT
      and "DragSort.orderByIds(groups, this._order.teams" in ORBIT
      and "teams: d.teams || []" in ORBIT)
check("D1 header tail click swallowed after a drag",
      "h.onclick = toggleGroup" in ORBIT
      and "DragSort.consumeClick(ev)) return" in ORBIT)
check("E1 view splitters are deck-level flex items ordered between panels",
      "sp.style.order = String(i * 2 + 1)" in ORBIT
      and "deck.appendChild(sp)" in ORBIT
      and "p.style.order = String(i * 2)" in ORBIT)

print("---")
ok = sum(results)
print("\nv625: %d/%d PASS" % (ok, len(results)))
raise SystemExit(0 if ok == len(results) else 1)
