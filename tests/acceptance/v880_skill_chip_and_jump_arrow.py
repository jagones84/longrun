#!/usr/bin/env python3
"""v880 — a skill pill is a door, and the jump arrow is a persistent state.

Two live reports (2026-11-08):
  * "when a skill is loaded in the message box I'd like click on it, it will open it
    in the editor" — the composer pill was display-only;
  * "the arrow to go to the latest message does not appear always, only if moving
    the wheel mouse; it shall be persistent if the window/side is not to the
    bottom" — its visibility was painted only when a scroll event happened to fire.

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
    start = HTML.index(sig)
    tail = HTML[start + len(sig):]
    for stop in ("\nfunction ", "\n/* ", "\n$(", "\nlet ", "\nconst "):
        i = tail.find(stop)
        if i > 0:
            tail = tail[:i]
    return tail


# ---- A: the skill pill opens the skill in the editor ----------------------
_chips = fn("function _renderCmdChips()")
check("A1 a real skill renders as a BUTTON carrying the skill name",
      "data-skill=" in _chips and "const tag = skill ? 'button' : 'span';" in _chips)
check("A2 a UI command / unknown token stays a plain pill (nothing to open)",
      "skill ? 'button' : 'span'" in _chips)
check("A3 one delegated click opens the skill through the ONE existing door",
      "openSkillInEditor(b.getAttribute(\"data-skill\"))" in _chips
      and "async function openSkillInEditor(name)" in HTML)
check("A4 that door really opens the file editor",
      "openInEditor(d.abspath || d.path, { mode: \"code\" })" in
      fn("async function openSkillInEditor(name) {"))
check("A5 the skill chip is announced as a control, not as text",
      "'open the ' + label + ' skill in the editor'" in _chips)
check("A6 hover/focus read as interactive",
      "#cmdChips button:hover" in HTML and "#cmdChips button:focus-visible" in HTML)

# ---- B: the jump arrow follows the real scroll state ----------------------
_uj = fn("function updateJump() {")
check("B1 visibility is a STATE (overflow && not at the bottom)",
      "b.hidden = !(l.scrollHeight - l.clientHeight > 80 && !_nearBottom());" in _uj)
check("B2 a resize re-measures it",
      'window.addEventListener("resize", () => updateJump());' in HTML)
check("B3 a change of the log/chat box re-measures it (content growth, composer)",
      "new ResizeObserver(() => updateJump())" in HTML
      and '_jro.observe($("log"))' in HTML)
check("B4 every chat re-render re-measures it",
      "updateJump();   // v880: a re-render is also a reason to re-measure the arrow"
      in fn("function buildDotRail() {"))
check("B5 the scroll listener still tracks the bottom pin",
      '$("log").addEventListener("scroll"' in HTML and "_stick = _nearBottom(); updateJump();" in HTML)

print("---")
passed = sum(results)
print("%d/%d PASS" % (passed, len(results)))
sys.exit(0 if passed == len(results) else 1)
