#!/usr/bin/env python3
"""v1014 — the model menu is as wide as the screen allows, on desktop and phone.

Measured defect (live, 2026-11-14): at 820 px the menu was 217 px wide — the width
of the right-hand group it was anchored to — so 25 of 45 model names were cut; on
a 360-390 px phone it was 217 px too. The menu must be a popover of the COMPOSER
(not of the model button's neighbour group), wide enough for the longest names,
and still inside the real viewport under the app's CSS zoom.
"""
import os
import re
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
with open(os.path.join(REPO, "webui", "index.html"), encoding="utf-8") as f:
    HTML = f.read()

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name
          + ((" :: " + str(detail)) if detail else ""))


check("A1 the desktop menu is roomy and viewport/zoom capped",
      re.search(
          r"#modelMenu \{ position: absolute; right: 0; bottom: calc\(100% \+ 8px\);"
          r"\s*width: min\(560px, calc\(100vw / var\(--zoom, 1\) - 28px\)\);",
          HTML,
      ) is not None)
check("A2 the old fixed 360px menu width is gone",
      re.search(r"#modelMenu \{[^}]*width:\s*360px;", HTML) is None)
check("A3 the phone menu is anchored to the composer bar, not the right group",
      re.search(
          r"@media \(max-width: 920px\) \{[^}]*"
          r"#composerBar \{ position: relative; \}"
          r"[^}]*#composerBar \.cb-right \{[^}]*position: static;",
          HTML,
      ) is not None)
check("A4 the phone menu spans the bar and stays capped at 560px",
      re.search(
          r"#modelMenu \{ left: auto; right: 0; width: min\(560px, 100%\); \}",
          HTML,
      ) is not None)
check("A5 the old narrow anchor (left:0 right:0 width:auto) is gone",
      "#modelMenu { left: 0; right: 0; width: auto; }" not in HTML)
check("A6 the menu still opens ABOVE its trigger",
      re.search(r"#modelMenu \{[^}]*bottom: calc\(100% \+ 8px\);", HTML) is not None)
check("A7 an item name may ellipsize, never overflow the row",
      re.search(
          r"nm\.style\.cssText = \"flex:1;overflow:hidden;"
          r"text-overflow:ellipsis;white-space:nowrap\"",
          HTML,
      ) is not None)
check("A8 a narrow phone also tightens the composer side room for the name",
      re.search(
          r"@media \(max-width: 430px\) and \(min-height: 501px\) \{"
          r"[^}]*#composer \{ margin: 10px 8px 12px; padding: 10px 8px; \}",
          HTML,
      ) is not None)

print("---")
passed = sum(results)
print("%d/%d PASS" % (passed, len(results)))
sys.exit(0 if passed == len(results) else 1)
