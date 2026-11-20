#!/usr/bin/env python3
"""v1239 — runtime group at the top of the rail, and the composer's saturation ring.

Operator, 2026-11-21:
  *"the feed and terminal icon in the sidebar shall be placed on the very top of the
  sidebar"*
  *"the context saturation circle shall appear also in the message chat box beside left
  of the LLM name model. tiny, a circle measuring the saturation, no number percentage
  only the circle with color amber green red. dont duplicate code"*

Deterministic: reads webui/index.html, no browser.
"""
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
UI = open(os.path.join(REPO, "webui", "index.html"), encoding="utf-8").read()
RAIL = UI[UI.find('<aside id="toolsBar"'):UI.find("</aside>", UI.find('<aside id="toolsBar"'))]

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail and not ok else ""))


# ---- A: the runtime group is the rail's FIRST section ----------------------
check("A1 terminal+feed is the very first group inside tb-mid",
      RAIL.index('id="inspJumpRuntime"') < RAIL.index('id="dockBtn"')
      and RAIL.index('id="inspJumpRuntime"') < RAIL.index('id="kbSessionBtn"')
      and RAIL.index('id="inspJumpRuntime"') < RAIL.index('id="inspJump"'),
      RAIL.index('id="inspJumpRuntime"'))
check("A2 it is still the runtime group, built from the real sections",
      'const INSP_JUMP_RUNTIME = ["terminal", "feed"];' in UI
      and "(INSP_JUMP_RUNTIME.indexOf(key) >= 0 ? runt : main).appendChild(b);" in UI)
check("A3 an empty group still collapses to nothing (no blank space at the top)",
      "#toolsBar #inspJumpRuntime:empty { display: none; }" in UI)

# ---- B: the composer's numberless saturation ring --------------------------
check("B1 a ring element sits LEFT of the model button in the composer bar",
      'id="cmpCtx"' in UI
      and RAIL.find('id="cmpCtx"') == -1   # it is the composer, not the rail
      and UI.index('id="cmpCtx"') < UI.index('id="model-btn"'))
check("B2 it is tiny and NUMBERLESS (a circle, no percentage)",
      ".cmp-ctx .mring { width: 13px; height: 13px; }" in UI
      and "_setCmpRing" in UI
      and '"cmp-ctx " + lvl' in UI
      and "cmpCtxRing" in UI)
check("B3 three colour bands: green / amber / red",
      ".cmp-ctx.lvl-ok .mfill { stroke: var(--ok); }" in UI
      and ".cmp-ctx.lvl-warn .mfill { stroke: var(--warn); }" in UI
      and ".cmp-ctx.lvl-hot .mfill { stroke: var(--err); }" in UI
      and 'p >= 70 ? "lvl-hot" : (p >= 50 ? "lvl-warn" : "lvl-ok")' in UI)
check("B4 it reads the SAME number as the rail meter (no second source)",
      "_setCmpRing(pct);" in UI and "_setCmpRing(_ctxPct);" in UI
      and "_setCmpRing(null);" in UI)
check("B5 the ring geometry is ONE shared helper (rail + composer)",
      "function _ringCircles(" in UI
      and UI.count("function _ringCircles(") == 1
      and "+ _ringCircles(iR, pct) +" in UI          # the rail pill uses it
      and "+ _ringCircles(' id=\"cmpCtxRing\"', p) +" in UI)  # the composer ring uses it

print("---")
passed = sum(results)
print("%d/%d PASS" % (passed, len(results)))
sys.exit(0 if passed == len(results) else 1)
