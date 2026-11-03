#!/usr/bin/env python3
"""v780 — the rail shows the two pending states, from real endpoints only.

Source (operator, 2026-11-03): "if any other function in the sidebar suggest them ...
ok procedi".

Two questions the operator answered by hunting through panels, now one click:
  * WHAT DID THE AGENT CHANGE? — `GET /api/edits?session=<sid>` (the same call the
    Workspace card already makes);
  * WHAT IS BLOCKING A RUN? — `GET /api/approvals?status=pending` (the same call the
    inspector header already makes).

Contract:
  A) both controls live in the rail's session cluster, icon-only, named;
  B) each carries ONE count chip, hidden at zero (a state is a chip, not a word);
  C) the counts come from those endpoints — no new route, no stub, no mirror;
  D) the number is also in the control's accessible name;
  E) clicking focuses the surface that owns the data (workspace changes / approvals),
     opening the drawer on a narrow viewport instead of doing nothing.

Deterministic: static contract on webui/index.html. No server, no model, no net.
Run: python3 tests/acceptance/v780_rail_states.py
"""
import os
import re

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
UI = os.path.join(REPO, "webui", "index.html")

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""))


ui = open(UI, encoding="utf-8").read()
RAIL = ui[ui.find('<aside id="toolsBar"'):ui.find("</aside>", ui.find('<aside id="toolsBar"'))]
MID = RAIL[RAIL.find('class="tb-mid"'):RAIL.find('class="tb-foot"')]


def block(marker):
    at = ui.find(marker)
    if at < 0:
        return ""
    start = ui.rfind("<button", 0, at)
    stop = ui.find("</button>", at)
    return ui[start:stop + 8]


CHANGES = block('id="editsBtn"')
APPR = block('id="apprBtn"')

# ---------------- A: both controls, in the rail, icon-only, named ----------------
check("A1 the changes control is a rail button in the session cluster",
      'id="editsBtn"' in MID and 'class="ghost"' in CHANGES)
check("A2 the approvals control is a rail button in the session cluster",
      'id="apprBtn"' in MID and 'class="ghost"' in APPR)
check("A3 both are icon-only (one 17px SVG, no text)",
      all("<svg" in b and not re.search(r"</svg>[^<\s]", b) for b in (CHANGES, APPR)))
check("A4 both wear the rail's stroke recipe",
      all('width="17" height="17"' in b and 'viewBox="0 0 24 24"' in b
          and 'stroke-width="1.8"' in b for b in (CHANGES, APPR)))
check("A5 both are named (title + aria-label) and their glyph is decorative",
      all('aria-label="' in b and "title=" in b and 'aria-hidden="true"><' in b
          for b in (CHANGES, APPR)))

# ---------------- B: one count chip each, hidden at zero ----------------
check("B1 each control carries exactly one .tb-badge, hidden by default",
      CHANGES.count('class="tb-badge"') == 1 and 'hidden' in CHANGES
      and APPR.count('class="tb-badge"') == 1 and 'hidden' in APPR)
check("B2 the chip is styled once, on the rail, not per button",
      ui.count("#toolsBar .tb-badge {") == 1
      and "#toolsBar .tb-badge[hidden] { display: none; }" in ui)

# ---------------- C: the counts come from the REAL endpoints ----------------
check("C1 approvals count is painted from the pending queue",
      '_setRailBadge("apprBtn", pend.length);' in ui
      and '"/api/approvals?status=pending"' in ui)
check("C2 changes count is painted from the session's own edit list",
      '_setRailBadge("editsBtn", files.length);' in ui
      and ' _setRailBadge("editsBtn", ((_editsBase' in ui
      and '"/api/edits?session="' in ui)
check("C3 no new backend route was invented for the rail",
      "/api/rail" not in ui)
check("C4 the setter is called with the BUTTON id, never with the chip id",
      # the first draft passed `editsBtnBadge` (the span), so the setter looked for a
      # badge INSIDE the badge and silently painted nothing — caught on the live page.
      '_setRailBadge("editsBtnBadge"' not in ui
      and '_setRailBadge("apprBtnBadge"' not in ui)

# ---------------- D: the number reaches the accessible name ----------------
SETTER = ui[ui.find("function _setRailBadge"):]
SETTER = SETTER[:SETTER.find("\n}\n")]
check("D1 the setter writes the count into aria-label and collapses the chip at 0",
      'btn.dataset.label' in SETTER and 'chip.hidden = !n' in SETTER
      and '" (" + n + " pending)"' in SETTER, SETTER[:120])

# ---------------- E: the click lands on the surface that owns the data ----------------
OC = ui[ui.find("function openChanges"):]
OC = OC[:OC.find("\n}\n")]
OA = ui[ui.find("function openApprovals"):]
OA = OA[:OA.find("\n}\n")]
check("E1 changes opens the changes section and reloads the list",
      # the section KEY is `files` — its header WORD is "Workspace". The first draft
      # opened `data-insp="workspace"`, which does not exist, so the list was fetched
      # and never shown (caught live: sectionOpen false while 4 rows existed).
      '_railOpenInsp("files")' in OC and "loadEdits()" in OC)
check("E2 approvals opens the approvals section and reloads the queue",
      '_railOpenInsp("approvals")' in OA and "loadApprovals()" in OA)
check("E3 on a narrow viewport the click opens the drawer (never a no-op)",
      "_toggleMobileDrawer(\"right\")" in ui[ui.find("function _railOpenInsp"):])

print("---")
ok = sum(results)
print("\nv780: %d/%d PASS" % (ok, len(results)))
raise SystemExit(0 if ok == len(results) else 1)
