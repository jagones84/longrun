#!/usr/bin/env python3
"""v342 — Orbit layout: single column, whole org chart visible (JAG-342).

Reported (user): the ORG CHART panel was CLIPPED (did not show the whole organigram),
the page grew a horizontal scrollbar while the chart ALSO had a transform pan
("se c'è il pan a che serve la scrollbar?"), and the panels were laid out "a cazzo".
Wanted: one panel under the other (mobile style).

Fix: every page row is a single column; the org chart scrolls NATIVELY inside its
panel (the transform pan is gone); switching team resets the constellation focus.

Deterministic, no model. Run: python3 tests/acceptance/v342_orbit_layout.py
"""
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
HTML = open(os.path.join(REPO, "src", "longrun", "orbit", "web", "orbit.html"), encoding="utf-8").read()

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + detail) if detail else ""))


check("A1 the page rows are a single column (mobile-style)",
      ".grid2{display:flex;flex-direction:column" in HTML)
# JAG-2.1: the Agents + Job row is now a TWO-column grid (side by side on wide
# screens), but the wide panels (org chart / constellation, routines / feed) stay
# single-column — the two-column track is scoped to `.grid2.ab` only.
check("A2 the resizable two-column grid spans the Agents and Org rows",
      ".grid2.ab,.grid2.oc{display:grid;grid-template-columns:var(--cA,minmax" in HTML)
check("A3 the org chart scrolls inside its panel",
      ".orgwrap{" in HTML and "overflow:auto" in HTML and "max-height:72vh" in HTML)
check("A4 the transform pan is removed (no scroll/pan fight)", "_panzoom" not in HTML)
check("A5 the org chart keeps node selection + open-in-app",
      "onclick" in HTML and "ondblclick" in HTML and "this.onGoTo" in HTML)
check("A6 the team selector is present", 'id="teamSel"' in HTML)
check("A7 switching team resets the constellation focus",
      "this.tac.focus = null" in HTML)
check("A8 the wrap is not capped at the old narrow width", "max-width:1500px" not in HTML)

print("---")
ok = sum(1 for r in results if r)
print("%d/%d PASS" % (ok, len(results)))
sys.exit(0 if ok == len(results) else 1)

