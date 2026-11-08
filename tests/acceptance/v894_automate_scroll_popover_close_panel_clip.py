#!/usr/bin/env python3
"""v894 — the automate block is a bounded scroller, every popover has an ✕, and a panel
clips its own X overflow.

Operator, 2026-11-08:
  *"the automate part of the agent panel shall be scrollable and occupy at most half the
  height available"* · *"open dialog for editing shall have the x to close them also"* ·
  *"see image still the right panel goes beyond border"*.

Deterministic: reads the Control deck, no browser, no network.
"""
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
ORBIT = open(os.path.join(REPO, "src", "longrun", "orbit", "web", "orbit.html"),
             encoding="utf-8").read()

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""))


# ---------------- A: the automate block is bounded and scrolls ------------------
check("A1 the bar caps at half the panel (and 46vh as a fallback)",
      "#lraAutoBar{max-height:min(50%,46vh);overflow:auto;align-items:flex-start}" in ORBIT)
check("A2 the ledger itself does not re-cap or clip inside it",
      "#lraRep{max-height:none;overflow:visible}" in ORBIT)
check("A3 the bar still holds its single full-width row (no layout change)",
      ORBIT.split('id="lraAutoBar"')[1].split('id="agAddBar"')[0].count("flex-basis:100%") == 1)

# ---------------- B: an ✕ closes every popover ---------------------------------
check("B1 openPopover injects the close strip",
      'const top = document.createElement("div");\n    top.className = "pop-top";' in ORBIT
      and 'top.querySelector(".pop-x").onclick = (ev) => { ev.stopPropagation(); closePopover(); };' in ORBIT)
check("B2 the strip can be opted out per call (closable:false)",
      "if (o.closable !== false){" in ORBIT)
check("B3 the ✕ is a named, frameless control",
      ".ctxmenu .pop-x{border:0;background:transparent;color:var(--dim);cursor:pointer;padding:0;" in ORBIT
      and 'aria-label="close" title="close"' in ORBIT)

# ---------------- C: a panel cannot paint past its own border ------------------
check("C1 both view modes clip the panel's X overflow",
      "main.view-cols section.panel[data-panel],\n  main.view-one section.panel[data-panel]{overflow-x:clip}" in ORBIT)
check("C2 it uses clip, not hidden (no new scroll container, Y untouched)",
      "overflow-x:clip}" in ORBIT and "section.panel[data-panel]{overflow:hidden" not in ORBIT)
check("C3 the deck and the page still clip as the outer belt",
      "min-width:0;overflow-x:hidden;overflow-y:auto}" in ORBIT
      and "margin:0;height:100%;\n    overflow-x:hidden}" in ORBIT)

print("---")
passed = sum(results)
print("%d/%d PASS" % (passed, len(results)))
sys.exit(0 if passed == len(results) else 1)
