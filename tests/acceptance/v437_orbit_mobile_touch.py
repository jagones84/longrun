"""v437 — Control deck on a phone: tidy layout + finger gestures (JAG-431i).

Reported (user): on mobile the Control deck's toolbar was a jumble of oversized
pills ("buttons on top"), and the org chart / constellation could not be panned or
zoomed with a finger (mouse-only handlers).

Fix (web/orbit/web/orbit.html):
  * a <=640px media query restyles the toolbars (labels dropped, selects fill a row,
    action buttons wrap into tidy >=36px finger-sized rows);
  * the org chart and the constellation pan/zoom via POINTER events, with PINCH to
    zoom on touch, and `touch-action:none` so a drag pans instead of scrolling.

Pins the markup/CSS. Deterministic, offline.
"""
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
HTML = open(os.path.join(REPO, "src", "longrun", "orbit", "web", "orbit.html"), encoding="utf-8").read()

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + detail) if detail else ""))


# --- 1: the phone layout media query ----------------------------------------
check("1a a <=640px media query exists", "@media (max-width:640px){" in HTML, "")
check("1b the toolbar labels + spacer are dropped on mobile",
      ".toolbar > .lbl,.toolbar > .sp{display:none}" in HTML, "")
check("1c toolbar selects fill a full row on mobile",
      ".toolbar > .inp,.toolbar > select.inp{flex:1 1 100%;width:100% !important" in HTML, "")
check("1d toolbar buttons are finger-sized on mobile",
      ".toolbar > .btn{flex:1 1 auto;height:36px" in HTML, "")
check("1e the create/row inputs are >=36px on mobile",
      ".pad > .row > .inp,.pad > .row > .btn{height:36px}" in HTML, "")

# --- 2: touch gestures ------------------------------------------------------
check("2a the charts disable native touch scrolling (touch-action:none)",
      ".orgwrap,.orgcanvas,.cbody,.csvg{touch-action:none}" in HTML, "")
check("2b the org chart pans by POINTER events (mouse + finger)",
      'box.addEventListener("pointerdown"' in HTML
      and "window.addEventListener(\"pointermove\"" in HTML, "")
check("2c the constellation pans by POINTER events",
      'svg.addEventListener("pointerdown"' in HTML, "")
check("2d pinch-to-zoom is implemented for the org chart",
      "pinch = {d: _dist()" in HTML and "_dist() / pinch.d" in HTML, "")
check("2e pinch-to-zoom is implemented for the constellation",
      "pinch = {d: _dist(), vb: parse()" in HTML, "")
check("2f the old mouse-only pan handlers are gone",
      'box.addEventListener("mousedown"' not in HTML
      and 'svg.addEventListener("mousedown"' not in HTML, "")
check("2g desktop wheel zoom is kept",
      'box.addEventListener("wheel"' in HTML and 'svg.addEventListener("wheel"' in HTML, "")

print("---")
ok = sum(results)
print("%d/%d PASS" % (ok, len(results)))
sys.exit(0 if ok == len(results) else 1)
