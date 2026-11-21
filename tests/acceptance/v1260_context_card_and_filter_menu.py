#!/usr/bin/env python3
"""v1260 — the composer context card opens where the finger is, and a filter menu survives
the click that opened it.

Operator (2026-11-22, round 176): *"the context circle down in msg doesn't open the UI and
the filter in the agents panel doesn't maintain the menu when clicking on the selecting the
team, it disappears immediately after the loaded menu."*

  A  the click that OPENS a themed <select> is not read as the second click = cancel
  B  every popup placed from a rect divides it by the app's CSS root zoom
  C  the composer ring collapses while it has no number (the ID rule had beaten [hidden])

Measured (round 176, Chrome 1440x900 and 938x1279 @ zoom 1.25):
  · deck Agents panel, real mouse click on `#teamSel` → `.ts-pop` opened and CLOSED within
    the same gesture (`click` handler, filtersort.js:378); after the fix it is still open
    at t+2.0s and picking an option writes the select;
  · composer `#cmpCtx` at zoom 1.25 → card at visual y=1364 on a 1279px window (off-screen,
    the click looked dead); after the fix y=1083, on-screen.

Deterministic and offline: static pins on webui/index.html and webui/assets/filtersort.js.
Run: python3 tests/acceptance/v1260_context_card_and_filter_menu.py
"""
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def src(*parts):
    with open(os.path.join(REPO, *parts), encoding="utf-8") as f:
        return f.read()


UI = src("webui", "index.html")
FS = src("webui", "assets", "filtersort.js")

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name
          + ((" :: " + str(detail)[:240]) if detail and not ok else ""))


def slice_between(text, start, end):
    i = text.find(start)
    return text[i:text.find(end, i)] if i >= 0 else ""


# ---- A: the opening press must not cancel itself ---------------------------
check("A1 the picker remembers which select the opening press belongs to",
      "openedBy: null, openedAt: 0" in FS
      and "function _tsOpenedByPointer(sel)" in FS)
check("A2 the click that follows that pointerdown is swallowed ONCE",
      "function _tsEatOpeningClick(sel)" in FS
      and "if (_tsEatOpeningClick(sel)) return;" in FS)
check("A3 a later click on the open select still cancels",
      'if (_ts.sel === sel) {' in FS and "_tsClose(true);" in FS
      and FS.count("if (_tsEatOpeningClick(sel)) return;") == 1)
check("A4 closing the list forgets the gesture (no stale swallow)",
      slice_between(FS, "function _tsClose(", "function _tsPaint(").count("st.openedBy = null;") == 1)

# ---- B: zoom-aware placement for every rect-anchored popup ------------------
check("B1 one zoom reader for the shared module (`_uiZoom` in the WebUI)",
      "function pageZoom()" in FS
      and 'parseFloat(getComputedStyle(document.documentElement).zoom)' in FS)
PLACE = slice_between(FS, "function place() {", "function open(on) {")
check("B2 the FilterSort panel divides the rect and clamps in LAYOUT px",
      "var z = pageZoom();" in PLACE and PLACE.count("/ z") >= 3
      and "window.innerWidth / z" in PLACE and "window.innerHeight / z" in PLACE)
TSP = slice_between(FS, "function _tsPlace(", "function _tsOpen(")
check("B3 the themed list does the same (a zoomed page kept it off-screen)",
      "var z = pageZoom();" in TSP and TSP.count("/ z") >= 3
      and "vw - pw - 8" in TSP and "vh - 8" in TSP)
CTX = slice_between(UI, "function _ctxPopover(anchor) {", "document.addEventListener(\"click\", e => {")
check("B4 the composer context card divides the ring's rect by the root zoom",
      "const z = _uiZoom();" in CTX and "const vw = window.innerWidth / z" in CTX
      and "r.left / z" in CTX and "r.top / z - ph - 8" in CTX)

# ---- C: an unpainted ring leaves no empty slot -----------------------------
check("C1 the hidden ring collapses against the ID rule that laid it out",
      "#composerBar .cb-right > #cmpCtx[hidden] { display: none; }" in UI)
check("C2 the ring is still painted only with a numeric percentage",
      "el.hidden = false;" in slice_between(UI, "function _setCmpRing(pct) {", "function _repaintCtx()")
      and "el.hidden = true;" in slice_between(UI, "function _setCmpRing(pct) {", "function _repaintCtx()"))

print("\n---\nv1260: %d/%d PASS" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
