#!/usr/bin/env python3
"""v497 — right inspector controls and width budgeting."""
import os
import re
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
with open(os.path.join(REPO, "webui", "index.html"), encoding="utf-8") as source:
    HTML = source.read()

checks = []


def check(name, passed):
    checks.append(bool(passed))
    print(("PASS " if passed else "FAIL ") + name)


toolbar = re.search(
    r'<div class="insp-tools"[^>]*>(.*?)</div>',
    HTML,
    flags=re.DOTALL,
)
bulk = re.search(
    r"function _setAllInspector\(open\)\s*\{(.*?)\n\}",
    HTML,
    flags=re.DOTALL,
)
tools_room = re.search(
    r"function _toolsRoomW\(z\)\s*\{(.*?)\n\}",
    HTML,
    flags=re.DOTALL,
)
panel_room = re.search(
    r"function _panelRoom\(col\)\s*\{(.*?)\n\}",
    HTML,
    flags=re.DOTALL,
)
fit_panels = re.search(
    r"function _fitPanels\(\)\s*\{(.*?)\n\}",
    HTML,
    flags=re.DOTALL,
)
dock_max = re.search(
    r"function _dockMaxW\(\)\s*\{(.*?)\n\}",
    HTML,
    flags=re.DOTALL,
)

# v879 (operator): "+ / − button to expand collapse why shall be two icons? one is
# enough that changes appearance based on expand/collapsed state" — the pair became
# ONE toggle whose accessible name follows the state it would produce.
check("A inspector header has ONE bulk control that names both states",
      bool(toolbar)
      and 'id="inspToggleAll"' in toolbar.group(1)
      and 'aria-label="expand all inspector sections"' in toolbar.group(1)
      and 'const l = isOpen ? "collapse all inspector sections" : "expand all inspector sections";' in HTML)
check("B the control flips the shared all-sections handler",
      '$("inspToggleAll").onclick = () => _setAllInspector(!_anyInspOpen());' in HTML)
check("C bulk toggle updates every inspector accordion and persists its state",
      bool(bulk)
      # RH-1: the sections live inside `#inspector .insp-list` (the scrolling list
      # under the fixed head), so the selector is a descendant, not a child.
      and 'querySelectorAll("#inspector section[data-insp]")' in bulk.group(1)
      and "body.hidden = !open" in bulk.group(1)
      and 'localStorage.setItem("sf_insp_" + section.dataset.insp' in bulk.group(1))
check("D expanding all loads only sections that were previously collapsed",
      bool(bulk)
      and "if (open && wasHidden) _loadInspector(section.dataset.insp)" in bulk.group(1))
check("E layout budget counts the visible in-flow tools bar, not its fixed drawer",
      bool(tools_room)
      and 'getElementById("toolsBar")' in tools_room.group(1)
      and 'getComputedStyle(tools).position === "fixed"' in tools_room.group(1)
      and "getBoundingClientRect().width / z" in tools_room.group(1))
check("F resize bounds preserve chat width and the tools bar",
      bool(panel_room) and "_toolsRoomW(z)" in panel_room.group(1)
      and bool(fit_panels) and "_toolsRoomW(z)" in fit_panels.group(1))
check("G editor dock max width also reserves the tools bar",
      bool(dock_max) and "_toolsRoomW(z)" in dock_max.group(1))

print("---")
print("%d/%d PASS" % (sum(checks), len(checks)))
sys.exit(0 if all(checks) else 1)
