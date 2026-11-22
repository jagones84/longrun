#!/usr/bin/env python3
"""v1267 — the themed <select> popup scrolls with a finger and no longer vanishes on
touch (round 184).

Operator, 2026-11-22: *"The jobs panel assign to menu is weird, it doesn't scroll,
disappears as touched, I can't select who I want. At least in mobile mode…"*

Measured on the real deck (`/orbit?embed=1&panel=jobs`, 390x844, touch emulation, the
live roster = 98 assignees): the popup opened as a 490px sheet over a 4226px list, and a
DRAG inside it selected "Frontend Developer · A16" and closed the menu — the pick ran on
`pointerdown`, so the finger's touchdown chose the row under it before the list could
move. After the fix the same drag scrolls the sheet (scrollTop 0 -> 490) with the menu
still open and the selection untouched, and a clean tap picks the wanted row
("Reality Checker · A20"); a mouse click picks "coder 1 · A9" and the click that follows
it does not reach the form behind the closed sheet.

Contract pinned here:
  A1 the pick runs on `pointerup`, never on `pointerdown`
  A2 a press that TRAVELLED (a scroll) is not a tap
  A3 the click that follows a picked row is eaten once (no click-through to the form)
  A4 a click with no pointer stream (assistive tech) still picks
  A5 a press INSIDE the popup never closes it (the outside-close test keeps its sign)
  A6 the phone sheet is anchored by CSS and a resize no longer closes it
  B  the popup is a vertical touch scroller and its rows do not select text on drag

Deterministic and offline: pins on webui/assets/filtersort.js and filtersort.css.
Run: python3 tests/acceptance/v1267_assign_menu_touch.py
"""
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
with open(os.path.join(REPO, "webui", "assets", "filtersort.js"), encoding="utf-8") as f:
    FS = f.read()
with open(os.path.join(REPO, "webui", "assets", "filtersort.css"), encoding="utf-8") as f:
    CSS = f.read()

RESULTS = []


def check(name, ok, detail=""):
    RESULTS.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)[:240]) if detail and not ok else ""))


def between(text, start, end):
    i = text.find(start)
    return text[i:text.find(end, i)] if i >= 0 else ""


DOWN = between(FS, 'document.addEventListener("pointerdown", function (e) {\n    _ts.ateClick = 0;', "}, true);")
UP = between(FS, 'document.addEventListener("pointerup", function (e) {', "}, true);")
CLICK = between(FS, 'document.addEventListener("click", function (e) {\n    if (_ts.ateClick', "}, true);")
OUTSIDE = between(FS, 'document.addEventListener("pointerdown", function (e) {\n    if (!_ts.pop) return;', "});")

# ---- A: the touch gesture ---------------------------------------------------
check("A1 the row is picked on pointerup, never on pointerdown",
      "_tsPick(Number(opt.dataset.i));" in UP and "_tsPick" not in DOWN,
      "down=%r" % DOWN[:120])
check("A2 a press that travelled more than 8px is a scroll, not a tap",
      "> 8" in UP and "_ts.press" in UP, UP[:200])
check("A3 the click that follows a picked row is eaten once (no click-through)",
      "_ts.ateClick = Date.now();" in UP
      and "Date.now() - _ts.ateClick < 400" in CLICK
      and "e.preventDefault(); e.stopPropagation();" in CLICK)
check("A3b a NEW press clears a stale guard (a browser with no synthetic click)",
      "_ts.ateClick = 0;" in DOWN and "a new press" in FS)
check("A4 a click with no pointer stream still picks (assistive tech)",
      "_tsPick(Number(opt.dataset.i));" in CLICK)
check("A5 a press INSIDE the popup never closes it (the outside-close sign)",
      "if (_ts.pop.contains(e.target)) return;   // inside the popup: never close" in OUTSIDE
      and "_tsClose(false);" in OUTSIDE, OUTSIDE[:200])
RESIZE = FS[FS.rfind('window.addEventListener("resize"'):]
RESIZE = RESIZE[:RESIZE.find("});")]
check("A6 the phone sheet survives a resize (URL-bar collapse is not a dismiss)",
      "if (_tsPhone()) return;" in RESIZE
      and "if (_tsPhone()) { _tsClose(false); return; }" not in FS, RESIZE[:240])

# ---- B: it is a touch scroller ---------------------------------------------
TSPOP = between(CSS, ".ts-pop {", "}")
TSOPT = between(CSS, ".ts-opt {", "}")
check("B1 the popup is a vertical touch scroller",
      "touch-action: pan-y;" in TSPOP and "-webkit-overflow-scrolling: touch;" in TSPOP
      and "overflow: auto;" in TSPOP, TSPOP[:240])
check("B2 a drag over the labels never starts a text range",
      "user-select: none;" in TSOPT and "-webkit-user-select: none;" in TSOPT, TSOPT[:240])
check("B3 the phone sheet is still the bottom sheet (v1259 untouched)",
      ".ts-pop.sheet {" in CSS and "bottom: 8px;" in CSS and "max-height: 58vh;" in CSS)

print("---\nv1267: %d/%d PASS" % (sum(RESULTS), len(RESULTS)))
raise SystemExit(0 if all(RESULTS) else 1)
