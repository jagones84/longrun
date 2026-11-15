#!/usr/bin/env python3
"""v1026 — every rail door keeps the accent while the surface it opens is expanded.

Operator, 2026-11-15:
  *"the side bar colours shall be maintained if the relevant panel session is expanded
    this is still not true for the upper icons."*

The jump icons (Inspector sections) already stayed copper while their section was open;
the UPPER cluster — editor, changed files, approvals, session notebook — went dim as soon
as the pointer left. This pins the fix to the same source of truth the panel itself uses:

  A) ONE mark on the rail: `#toolsBar button.is-current` is the accent (no second
     per-button colour table), and the original two jump selectors are untouched;
  B) the two badged OBJECT buttons (`files`, `approvals`) are painted from `.insp-open`
     — they are `INSP_JUMP_SKIP`, so nothing else used to light them;
  C) the editor door follows the dock's own `hidden` state (show/close are its only
     transitions);
  D) the notebook door follows Settings ▸ Knowledge while that window is on screen;
  E) no new state store, endpoint or duplicate repaint path.

Deterministic: static contract on webui/index.html + webui/assets/editor.js.
Run: python3 tests/acceptance/v1026_rail_icon_state.py
"""
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
UI = open(os.path.join(REPO, "webui", "index.html"), encoding="utf-8").read()
EDITOR = open(os.path.join(REPO, "webui", "assets", "editor.js"), encoding="utf-8").read()

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""))


# ---- A: one mark, all four groups ----------------------------------------------
check("A1 any current rail button is accent-lit by ONE rule",
      "#toolsBar button.is-current { color: var(--acc); }" in UI)
check("A2 the original jump rules are kept verbatim (v885/v890 still read them)",
      "#toolsBar #inspJump button.is-current," in UI
      and "#toolsBar #inspJumpRuntime button.is-current { color: var(--acc); }" in UI)
check("A3 the mark is one class on the control, not inline colour",
      'b.classList.toggle("is-current", on);' in UI
      and 'b.setAttribute("aria-current", "true")' in UI)

# ---- B: the two badged Inspector doors -----------------------------------------
check("B1 the object doors are mapped to their real section keys",
      'const RAIL_OBJECT_PANELS = [["editsBtn", "files"], ["apprBtn", "approvals"]];' in UI)
check("B2 their mark comes from the panel's own `.insp-open` state",
      "function _paintRailObjects() {" in UI
      and 'const sec = _inspSecOf(pair[1]);' in UI
      and 'const on = !!(sec && sec.classList.contains("insp-open"));' in UI
      and 'b.classList.toggle("is-current", on);' in UI)
check("B3 every existing repaint path reaches them",
      "_paintRailObjects();   // 2026-11-15: the object doors keep their accent too" in UI)
check("B4 the jump list still skips them (no duplicate icons)",
      'const INSP_JUMP_SKIP = ["approvals", "files"];' in UI
      and '"inspJump", "inspJumpRuntime", "chatViewSec"' in UI)

# ---- C: the editor door --------------------------------------------------------
check("C1 the dock button is painted from the dock's real visibility",
      "function _paintDockBtn() {" in EDITOR
      and 'b.classList.toggle("is-current", !!state.dock && !state.dock.hidden);' in EDITOR)
check("C2 both dock transitions repaint the rail icon",
      EDITOR.count("  _notifyLayout();\n  _paintDockBtn();") == 2,
      "show() + close()")

# ---- D: the notebook door ------------------------------------------------------
check("D1 the notebook door reads the visible Knowledge category",
      "function _paintKbSessionBtn() {" in UI
      and "const w = settingsWin();" in UI
      and 'document.querySelector(\'#swMain .sw-cat[data-cat="knowledge"]\')' in UI
      and "const on = !!(w && !w.hidden && cat && !cat.hidden);" in UI)
check("D2 opening a settings category repaints it",
      "_paintKbSessionBtn();   // 2026-11-15: the notebook rail door follows this category" in UI)
check("D3 closing Settings repaints it",
      "function closeSettings() { settingsWin().hidden = true; _paintKbSessionBtn(); }" in UI)

# ---- E: no new channel ---------------------------------------------------------
check("E1 no endpoint was invented for a visual state",
      "/api/rail" not in UI and "/api/rail" not in EDITOR)

print("---")
passed = sum(results)
print("v1026: %d/%d PASS" % (passed, len(results)))
sys.exit(0 if passed == len(results) else 1)
