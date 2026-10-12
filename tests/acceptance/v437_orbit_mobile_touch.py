"""v437 — Control deck on a phone: tidy layout + finger gestures (JAG-431i).

Reported (user), two issues on mobile:
  1. "the toolbar is a jumble of oversized pills" -> a <=640px media query restyles
     the toolbars (labels dropped, selects fill a row, buttons wrap into tidy >=36px
     finger-sized rows).
  2. "finger press and move on the org chart causes ZOOM not pan" -> the first cut
     hand-rolled a pointer-Id Map, which can go STALE (a missed pointerup leaves a
     phantom second pointer, so a one-finger drag is mis-read as a pinch). The fix
     uses TOUCH events (`ev.touches` is the browser's authoritative live list) for
     touch, and keeps mouse events for desktop; `touch-action:none` stops page scroll.
  3. The row-height grips squashed the stacked panels on a phone -> they are hidden
     below the stacking breakpoint and any stored row height is ignored.

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

# --- 2: the row-height grips no longer squash the stacked panels -------------
check("2a the row grips are hidden once the rows stack",
      ".rz-row{display:none}" in HTML, "")
check("2b a stored desktop row height is ignored on mobile",
      ".grid2{height:auto !important}" in HTML, "")

# --- 3: touch gestures ------------------------------------------------------
check("3a the charts disable native touch scrolling (touch-action:none)",
      ".orgwrap,.orgcanvas,.cbody,.csvg{touch-action:none}" in HTML, "")
check("3b the org chart pans by TOUCH events on the box",
      'box.addEventListener("touchstart"' in HTML
      and 'box.addEventListener("touchmove"' in HTML, "")
check("3c the constellation pans by TOUCH events on the svg",
      'svg.addEventListener("touchstart"' in HTML
      and 'svg.addEventListener("touchmove"' in HTML, "")
check("3d touch uses the authoritative `ev.touches` list (never a stale map)",
      HTML.count("ev.touches") >= 2 and "const t = ev.touches" in HTML, "")
check("3e pinch-to-zoom is implemented for both charts",
      HTML.count('mode: "pinch"') >= 2, "")
check("3f a single-finger drag pans (pan mode) on both charts",
      HTML.count('mode: "pan"') >= 3, "")
check("3g the stale pointer-map gesture is gone",
      'box.addEventListener("pointerdown"' not in HTML
      and 'svg.addEventListener("pointerdown"' not in HTML, "")
check("3h desktop mouse drag + wheel zoom are kept",
      'box.addEventListener("mousedown"' in HTML and 'svg.addEventListener("mousedown"' in HTML
      and 'box.addEventListener("wheel"' in HTML and 'svg.addEventListener("wheel"' in HTML, "")
check("3i a tap on a node still selects it (node guard in both handlers)",
      'ev.target.closest(".node")' in HTML, "")

print("---")
ok = sum(results)
print("%d/%d PASS" % (ok, len(results)))
sys.exit(0 if ok == len(results) else 1)
