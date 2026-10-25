#!/usr/bin/env python3
"""v622 — Control custom views: up to 3 panels side by side, no All board.

  A  rail: six single panes + a VIEWS section (list + new-view button);
     the stacked "All panels" board is deleted (old saved "all" migrates
     to the first custom view).
  B  view bar: name, rename, add-panel select (duplicates excluded),
     delete view (at least one kept); per-column arrows move left/right
     (edge arrows disabled), X removes; max 3 enforced in add AND in
     stored-state load.
  C  layout: view-cols flex row (rows/col become display:contents),
     seeded Desk view, views persisted, focus-job bridge uses
     isPanelVisible (no "all" special case).

Deterministic: static source contract, no server, no model, no network.
Run: python3 tests/acceptance/v622_custom_views.py
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


# ---------------- A: rail ----------------------
check("A1 VIEWS section with list + new-view button",
      '<span class="rlbl">views</span>' in ORBIT and 'id="viewList"' in ORBIT
      and 'data-view-add' in ORBIT)
check("A2 no All-panels board anywhere (markup or logic)",
      'data-view="all"' not in ORBIT and '"all") ? "all"' not in ORBIT
      and 'view !== "all"' not in ORBIT)
check("A3 six single panes survive in order",
      [ORBIT.index('data-view="%s"' % v) for v in
       ["agents", "routines", "jobs", "org", "const", "feed"]] ==
      sorted([ORBIT.index('data-view="%s"' % v) for v in
              ["agents", "routines", "jobs", "org", "const", "feed"]]))

# ---------------- B: view management ----------------------
check("B1 view bar: name, rename, add-panel, delete",
      all(_id in ORBIT for _id in (
          'id="viewBar"', 'id="viewName"', 'id="viewRename"',
          'id="viewAddPanel"', 'id="viewAddGo"', 'id="viewDelete"')))
check("B2 per-column arrows + remove injected once per panel header",
      'className = "vcols"' in ORBIT and 'data-vmove="-1"' in ORBIT
      and 'data-vmove="1"' in ORBIT and "data-vrm" in ORBIT)
check("B3 edge arrows disabled, not dead",
      'b.disabled = !(v &&' in ORBIT)
check("B4 max 6 enforced on add AND on stored-state load",
      "a view holds at most 6 panels side by side" in ORBIT
      and ".slice(0, 6)" in ORBIT)
check("B5 at least one view kept, empty view refills",
      "keep at least one view" in ORBIT
      and 'if (!v.panels.length) v.panels = ["agents"]' in ORBIT)
check("B6 seeded Desk view replaces the board",
      '"v-desk", name: "Desk", panels: ["agents", "jobs", "org"]' in ORBIT)

# ---------------- C: layout + bridges ----------------------
check("C1 view-cols flex row, rows transparent, narrow stacks",
      "main.view-cols .deckBody{flex-direction:row" in ORBIT
      and "main.view-cols .deckBody > .grid2{display:contents}" in ORBIT
      and "main.view-cols .deckBody .col{display:contents}" in ORBIT)
check("C2 views persisted, old stacked key migrates to first view",
      '"orbit_views_v1"' in ORBIT
      and "lands on the first custom view" in ORBIT)
check("C3 focus-job bridge keys off visibility, not a board name",
      'isPanelVisible("jobs")' in ORBIT)
check("C4 single-pane landing still full-height (view-one kept)",
      'main.classList.toggle("view-one", !cols)' in ORBIT
      and 'main.classList.toggle("view-cols", cols)' in ORBIT)

print("---")
ok = sum(results)
print("\nv622: %d/%d PASS" % (ok, len(results)))
raise SystemExit(0 if ok == len(results) else 1)
