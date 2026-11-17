#!/usr/bin/env python3
"""v1068 — the phone transcript keeps a phone gutter, not the desktop one (JAG-934).

Operator, 2026-11-17: *"why in mobile format is all that empty space in the chat on
the left? can you solve it graphically?"* — with a 393 px screenshot where the text
started a third of the way across the transcript.

Measured live (CDP, session `architect`, 393x844):
  #log padding-left   = 28px   (the DESKTOP rule; the only phone rule for #log was
                                scoped to `orientation: landscape`)
  .tc-kids indent     = 26px   (16 margin + 10 padding)
  first line of text  = x=55   on a 349px chat -> 16% of the width, empty.

Contract pinned here (source, deterministic — the browser is measured by hand):
  A1 the portrait phone block exists and is guarded against the landscape layout
  A2 #log drops to a 16px gutter
  A3 that 16px is the chat head's own gutter, so the two left edges line up
  A4 a nested group tightens to 8+8, and deeper nesting to 4+6
  A5 the step's status dot is re-anchored on the shifted rail
  A6 the block is declared AFTER the desktop `#log` rule (a media query placed
     before a later base declaration LOSES — the trap documented in this sheet)
  A7 the landscape phone keeps its own 10px/12px rule, untouched
  A8 the resulting left inset is at most 40px (16 + 8 + 1 + 8 + the card's padding)
  A9 the transcript still hides horizontal overflow (no sideways scroll appears)

Run: python3 tests/acceptance/v1068_mobile_chat_gutter.py
"""
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
with open(os.path.join(REPO, "webui", "index.html"), encoding="utf-8") as f:
    HTML = f.read()

RESULTS = []


def check(name, ok, detail=""):
    RESULTS.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""))


def phone_block():
    """The LAST `@media (max-width: 640px) and (min-height: 501px)` block body."""
    marker = "@media (max-width: 640px) and (min-height: 501px) {"
    i = HTML.rfind(marker)
    if i < 0:
        return "", -1
    depth, j = 0, i + len(marker) - 1
    while j < len(HTML):
        if HTML[j] == "{":
            depth += 1
        elif HTML[j] == "}":
            depth -= 1
            if depth == 0:
                break
        j += 1
    return HTML[i:j + 1], i


BLOCK, AT = phone_block()
DESKTOP_LOG = "#log { padding: 24px 28px 12px; }"
LANDSCAPE_LOG = "#log { padding: 10px 12px; }"

check("A1 the portrait phone block exists",
      AT > 0 and "@media (max-width: 640px) and (min-height: 501px) {" in BLOCK,
      "offset=%d" % AT)
check("A2 the transcript drops to a 16px gutter on a phone",
      "#log { padding: 12px 16px; }" in BLOCK, "")
check("A3 that gutter is the chat head's (the two left edges line up)",
      "#chatHead { padding: 8px 16px;" in HTML, "")
check("A4 a nested step tightens to 8+8, deeper nesting to 4+6",
      ".tctree .tc-kids { margin-left: 8px; padding-left: 8px; }" in BLOCK
      and ".tctree .tc-kids .tc-kids { margin-left: 4px; padding-left: 6px; }" in BLOCK, "")
check("A5 the step's status dot is re-anchored on the shifted rail",
      ".tctree .tc-kids > .toolcard::before { left: -12px; }" in BLOCK, "")
check("A6 it is declared AFTER the desktop #log rule (or it would lose)",
      HTML.find(DESKTOP_LOG) > 0 and AT > HTML.find(DESKTOP_LOG),
      "desktop@%d phone@%d" % (HTML.find(DESKTOP_LOG), AT))
check("A7 the landscape phone keeps its own tighter rule",
      LANDSCAPE_LOG in HTML
      and HTML.rfind("orientation: landscape", 0, HTML.find(LANDSCAPE_LOG)) > 0, "")
check("A8 the resulting left inset is at most 40px (16 + 8 + 1 + 8)",
      16 + 8 + 1 + 8 <= 40 and "#log { padding: 12px 16px; }" in BLOCK, "33px")
check("A9 the transcript still hides horizontal overflow",
      "#log { overflow-x: hidden; }" in HTML, "")
check("A10 the change is scoped to the phone (the desktop gutters are intact)",
      DESKTOP_LOG in HTML and "padding: 24px 28px;" in HTML, "")

print("---")
print("%d/%d PASS" % (sum(RESULTS), len(RESULTS)))
raise SystemExit(0 if all(RESULTS) else 1)
