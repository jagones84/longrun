#!/usr/bin/env python3
"""v879 — ONE control per job in the rails (the operator's +/− and eye report).

Operator, 2026-11-08: *"+ / − button to expand collapse why shall be two icons? one
is enough that changes appearance based on expand/collapsed state. the same for the
EYE … review better the icon system and buttons of the sidebar."*

Four surfaces carried a PAIR of buttons for one meaning (chat rail ⊞/⊟, chat rail
CoT, sessions head ▲/▼, inspector head ▲/▼), and the eye could only close. Pinned:

  A) each job is exactly ONE control, and the old names are gone from the markup;
  B) the glyph carries the STATE (`is-open` rotates the fold chevrons, `is-off`
     shows the eye's slash) and the name carries the ACTION;
  C) every render repaints them from the real DOM, and a manual open/close of one
     group or one CoT does too (a `toggle` listener in the capture phase);
  D) motion is disabled under `prefers-reduced-motion`.

Deterministic: reads webui/index.html, no browser, no network.
"""
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
HTML = open(os.path.join(REPO, "webui", "index.html"), encoding="utf-8").read()

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""))


def fn(sig):
    """Body of a function, from its signature to the next top-level declaration."""
    start = HTML.index(sig)
    tail = HTML[start + len(sig):]
    for stop in ("\nfunction ", "\n/* ", "\n$(", "\nlet ", "\nconst "):
        i = tail.find(stop)
        if i > 0:
            tail = tail[:i]
    return tail


# ---- A: one control per job ------------------------------------------------
PAIRS = ("expandAllTodos", "collapseAllTodos", "collapseThoughts",
         "railCollapseAll", "railExpandAll", "inspCollapseAll", "inspExpandAll")
for name in PAIRS:
    check("A %s is gone (two buttons for one meaning)" % name, name not in HTML)
for name in ("toggleGroups", "toggleThoughts", "railToggleAll", "inspToggleAll"):
    check("A ONE control exists: %s" % name, name in HTML)

# ---- B: the glyph is the state, the name is the action ---------------------
_utt = fn("function _updateTreeTools()")
check("B1 the groups glyph follows the real state",
      'gBtn.classList.toggle("is-open", gOpen)' in _utt)
check("B2 the eye gains a slash while the reasoning is hidden",
      'tBtn.classList.toggle("is-off", !tShown)' in _utt)
check("B3 the labels name the ACTION (and match the tooltip)",
      '"collapse all groups (tasks + free threads)"' in _utt
      and '"show every chain-of-thought block"' in _utt
      and "gBtn.title = gl; gBtn.setAttribute(\"aria-label\", gl)" in _utt)
check("B4 both rail heads are painted by one function each",
      "function _paintRailToggle()" in HTML and "function _paintInspToggle()" in HTML)
check("B5 the fold icon rotates (state) and the eye keeps one SVG",
      ".fold-tg.is-open svg { transform: rotate(180deg); }" in HTML
      and "button .ic-slash" in HTML)

# ---- C: repainted from the real DOM, not from a memory of it ---------------
check("C1 the two rail toggles read the DOM for their direction",
      "_openGroups()" in fn("function _railGroupsOpen()")
      and "_lastGroupKeys" in fn("function _railGroupsOpen()")
      and "insp-body" in fn("function _anyInspOpen()"))
check("C2 a list render repaints the sessions toggle",
      "_paintRailToggle();" in HTML)
check("C3 a single inspector section (and a bulk change) repaints its toggle",
      HTML.count("_paintInspToggle();") >= 3)
check("C4 a manual group/CoT toggle repaints the chat rail aggregates",
      'addEventListener("toggle", () => _updateTreeTools(), true)' in HTML)

# ---- D: motion is opt-out --------------------------------------------------
check("D1 reduced motion keeps both controls readable",
      "prefers-reduced-motion: reduce" in HTML
      and ".fold-tg svg, #toolsBar button .ic-slash { transition: none; }" in HTML)

print("---")
passed = sum(results)
print("%d/%d PASS" % (passed, len(results)))
sys.exit(0 if passed == len(results) else 1)
