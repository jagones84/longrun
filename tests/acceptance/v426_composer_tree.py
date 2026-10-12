#!/usr/bin/env python3
"""v426 — WebUI: single-line composer + chat todo-group expand/collapse-all (JAG-427).

Two UI complaints pinned at the static level:

  1. The composer toolbar must NEVER grow a "multi-floor" stack when the chat column
     is narrow — it stays one row and only the model label shrinks.
  2. The chat todo groups (<details.tctree>) get expand-all / collapse-all controls,
     mirroring the sessions rail's ▲/▼, placed so they cost no horizontal space.

Deterministic (no model, no network).

Run: python3 tests/acceptance/v426_composer_tree.py
"""
import os
import re
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _read(*parts):
    with open(os.path.join(REPO, *parts), encoding="utf-8") as f:
        return f.read()


HTML = _read("webui", "index.html")

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + detail) if detail else ""))


# --- 1: the composer bar is a single row -------------------------------------
check("1a #composerBar is `flex-wrap: nowrap`",
      re.search(r"#composerBar \{ display: flex; align-items: center; flex-wrap: nowrap", HTML) is not None, "")
check("1b no media query re-enables wrapping on #composerBar",
      re.search(r"#composerBar \{ flex-wrap: wrap; \}", HTML) is None, "")
check("1c the model button can shrink toward a glyph (min-width small)",
      re.search(r"#composerBar \.cb-right \.model-wrap > button \{ max-width: 160px; min-width: 34px", HTML) is not None, "")
check("1d the right group no longer wraps at <=920px",
      re.search(r"#composerBar \.cb-right \{ flex-wrap: nowrap; justify-content: flex-end", HTML) is not None, "")

# --- 2: the chat todo-group controls -----------------------------------------
check("2a the control markup exists", 'id="treeTools"' in HTML, "")
check("2b both data-call hooks are present",
      'data-call="expandAllTodos"' in HTML and 'data-call="collapseAllTodos"' in HTML, "")
for fn in ("expandAllTodos", "collapseAllTodos", "_updateTreeTools", "_allTodos"):
    check("2c the %s() function is defined" % fn, ("function " + fn + "(") in HTML, "")
check("2d the functions target the chat's <details.tctree> groups",
      'querySelectorAll("details.tctree")' in HTML, "")
check("2e the control is kept in sync from _updateNowBar",
      "_updateTreeTools();   // JAG-427" in HTML, "")
check("2f there is a CSS rule for the control", "#treeTools {" in HTML, "")
check("2g it floats (does not consume a layout column)",
      re.search(r"#treeTools \{ position: absolute;", HTML) is not None, "")

print("---")
ok = sum(results)
print("%d/%d PASS" % (ok, len(results)))
sys.exit(0 if ok == len(results) else 1)
