#!/usr/bin/env python3
"""v282 — composer toolbar never wraps; editor tabs expose their path + copy-path.

JAG-282 (user): the composer toolbar wrapped onto a second line and looked broken,
and the open editor tabs gave no way to know a file's full path / whether it is in
the workspace, nor to copy it.

Locked here:
  * the composer bar is ALWAYS one row (JAG-427): the model picker is the only flexible
    element and it shrinks toward a glyph before anything can wrap or overlap;
  * every editor tab shows its full path on hover and has a right-click menu with
    'copy path' (mirroring the file tree), a 'reveal in file tree' action, and an
    outside-the-workspace marker (tab + status bar).

Deterministic, no live server. Run: python3 tests/v282_composer_tabs.py
"""
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + detail) if detail else ""))


with open(os.path.join(REPO, "webui", "index.html"), encoding="utf-8") as f:
    ui = f.read()
with open(os.path.join(REPO, "webui", "assets", "editor.js"), encoding="utf-8") as f:
    ed = f.read()

# --- 1) composer toolbar: grouped, one row when it fits, never clipped --------
check("the composer toolbar is grouped into left/right clusters",
      'class="cb-left"' in ui and 'class="cb-right"' in ui
      and "#composerBar .cb-right { margin-left: auto" in ui)
check("the bar stays ONE row — never wraps to a second floor (JAG-427)",
      "#composerBar { display: flex; align-items: center; flex-wrap: nowrap; gap: 6px 8px; }" in ui)
# JAG-427: the old phone-wrap caused a broken "multi-floor" stack; now every width keeps a
# single row and only the model button shrinks (down to its ▾ glyph), so no control overlaps.
check("no media query re-enables wrapping on the composer bar",
      "#composerBar { flex-wrap: wrap; }" not in ui
      and "#composerBar { flex-wrap: nowrap; }" in ui)
check("the model picker is the flexible element and truncates",
      "#composerBar .cb-right .model-wrap > button { max-width: 160px" in ui
      and "#composerBar .mname" in ui)
check("the model label targets .mname (robust, keeps the caret)",
      'b.querySelector(".mname")' in ui and 'class="mname"' in ui)
check("the composer placeholder is compact", "⏎ send" in ui)
# JAG-427: on a narrow width the RIGHT group stays ONE row and the model label shrinks
# (min-width:34px) instead of wrapping; the popover still re-anchors full-width.
check("the phone right group stays ONE row and lets the model shrink",
      "#composerBar .cb-right { flex-wrap: nowrap; justify-content: flex-end; position: relative; }" in ui
      and "#composerBar .cb-right .model-wrap > button { min-width: 34px; }" in ui)
check("the mobile model menu re-anchors to the full-width right group (stays on screen)",
      "#composerBar .cb-right .model-wrap { position: static; min-width: 0; }" in ui
      and "#modelMenu { left: 0; right: 0; width: auto; }" in ui)

# --- 2) editor tabs: path, copy-path menu, outside-workspace marker ----------
check("a tab shows its full path on hover",
      "b.title = temp ?" in ed and "outside the session workspace" in ed)
check("right-clicking a tab opens a menu",
      "function showTabMenu" in ed and "b.oncontextmenu" in ed)
check("the tab menu copies the path (like the file tree)",
      'mk("⧉ copy path"' in ed and "copyPath(t.path)" in ed)
check("the tab menu reveals the file in the tree",
      "function revealInTree" in ed and "reveal in file tree" in ed)
check("an outside-the-workspace tab is marked",
      "function _inWorkspace" in ed and ".ed-tab.ext" in ed and "ext-i" in ed)
check("the status bar flags a file outside the workspace",
      "outside the workspace" in ed)
check("the tree context menu is reused (copy path already exists)",
      'mk("⧉ copy path", () => copyPath(path))' in ed)

print("---")
passed = sum(results)
print("%d/%d PASS" % (passed, len(results)))
sys.exit(0 if passed == len(results) else 1)

