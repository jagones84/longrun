#!/usr/bin/env python3
"""v1029 — a right-click menu opens AT the pointer, whatever the page zoom.

Operator, 2026-11-15:
  *"right click that opens menus example in the editor or elsewhere open the editors far
    away from the mouse click that's not good. solve"*

Measured live with the app's own zoom (130 %): a right-click at visual (1110, 183) put the
editor-tab menu at (1383, 238) with `left: 1064px` — ~270 px to the right of the pointer
and mostly outside the window. Two unit mismatches, both in the popup placement:

  * a mouse click arrives in VISUAL px, but a CSS `left:` is multiplied by the zoom;
  * `innerWidth`/`innerHeight` are VISUAL px too, so the right/bottom clamp was computed
    in the wrong space and let the menu overflow.

`_placeMenu` already converted the click (`x / z`); this pins the rest:

  A) the helper converts the VIEWPORT as well, so the clamp is in layout px;
  B) the editor's two right-click menus (file row, tab) delegate to that helper instead
     of duplicating the math in visual px;
  C) the Plan-todo right-click menu does the same;
  D) the preview ⋯ menu and the artifact/edits right-click menu keep using it.

Deterministic: static contract on webui/index.html + webui/assets/editor.js.
Run: python3 tests/acceptance/v1029_context_menu_placement.py
"""
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
UI = open(os.path.join(REPO, "webui", "index.html"), encoding="utf-8").read()
ED = open(os.path.join(REPO, "webui", "assets", "editor.js"), encoding="utf-8").read()

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""))


PLACE = UI[UI.find("function _placeMenu(m, x, y, alignRight)"):]
PLACE = PLACE[:PLACE.find("\n}\n")]

# ---- A: ONE placement, correct units -----------------------------------------
check("A1 the live zoom is read from the scaled root",
      "function _uiZoom()" in UI
      and "parseFloat(getComputedStyle(document.documentElement).zoom)" in UI)
check("A2 the click point AND the viewport become layout px",
      "const tx = x / z, ty = y / z;" in PLACE
      and "const vw = window.innerWidth / z, vh = window.innerHeight / z;" in PLACE
      and "const w = m.offsetWidth, h = m.offsetHeight;" in PLACE)
check("A3 the clamp is in the same unit it writes",
      "Math.min(left, vw - w - 8)" in PLACE and "if (top + h > vh - 8)" in PLACE)
check("A4 the menu box is measured at the origin (no stale left/top)",
      'm.style.left = "0px"; m.style.top = "0px";' in PLACE)

# ---- B: the editor's right-click menus use it --------------------------------
check("B1 both editor menus delegate to the ONE placement",
      ED.count("if (window._placeMenu) window._placeMenu(m, x, y, false);") == 2,
      "file row + tab")
check("B2 the visual-px clamp is gone from the editor",
      'm.style.left = Math.min(x, window.innerWidth - r.width - 8) + "px";' not in ED
      and "innerWidth - r.width" not in ED)
check("B3 both handlers still pass the real click point",
      "showTreeMenu(e.clientX, e.clientY, f.path)" in ED
      and "showTabMenu(e.clientX, e.clientY, i)" in ED)

# ---- C: the Plan-todo right-click menu ---------------------------------------
check("C1 it delegates to the same helper",
      "_placeMenu(m, ev.clientX, ev.clientY, false);" in UI)
check("C2 its old visual-px clamp is gone",
      "Math.min(ev.clientX, innerWidth - r.width - 8)" not in UI)

# ---- D: the menus that already delegated keep doing so -----------------------
check("D1 the artifact/edits right-click menu still uses it",
      "_placeMenu(m, x, y, false);" in UI)
check("D2 the preview ⋯ menu still uses it (button-anchored, aligned right)",
      "_placeMenu(m, r.right, r.bottom + 4, true);" in UI)
check("D3 no menu positions itself from clientX without the helper",
      "style.left = ev.clientX" not in UI and "style.left = e.clientX" not in UI)

print("---")
passed = sum(results)
print("v1029: %d/%d PASS" % (passed, len(results)))
sys.exit(0 if passed == len(results) else 1)
