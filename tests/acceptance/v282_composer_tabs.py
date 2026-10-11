#!/usr/bin/env python3
"""v282 — composer toolbar never wraps; editor tabs expose their path + copy-path.

JAG-282 (user): the composer toolbar wrapped onto a second line and looked broken,
and the open editor tabs gave no way to know a file's full path / whether it is in
the workspace, nor to copy it.

Locked here:
  * the composer bar is one row when it fits; on a narrow phone width it WRAPS (the
    model picker is the only flexible element and it truncates) — it must never shrink
    into an overlap;
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
check("the bar wraps instead of clipping (no nowrap on the bar)",
      "#composerBar { display: flex; align-items: center; flex-wrap: wrap; gap: 6px 8px; }" in ui)
# JAG-3xx: a phone width must WRAP too. A `nowrap` override made .cb-right shrink and,
# with justify-content: flex-end, spill its buttons LEFT over .cb-left (measured 4
# overlaps), so a tap landed on the wrong control and the composer / ⋯ looked dead.
check("a narrow (phone) toolbar WRAPS — no nowrap override that overlaps .cb-left",
      "#composerBar { flex-wrap: wrap; }" in ui
      and "#composerBar { flex-wrap: nowrap" not in ui)
check("the model picker is the flexible element and truncates",
      "#composerBar .cb-right .model-wrap > button { max-width: 160px" in ui
      and "#composerBar .mname" in ui)
check("the model label targets .mname (robust, keeps the caret)",
      'b.querySelector(".mname")' in ui and 'class="mname"' in ui)
check("the composer placeholder is compact", "⏎ send" in ui)
# JAG-382: on a phone the RIGHT group must wrap too (it was nowrap + justify-content:
# flex-end), the model label must stay readable, and the menu must re-anchor to the
# FULL-WIDTH right group — else the model selector shrank to a ~24px sliver / its 360px
# popover hung off the left edge (mic + model pushed off-screen at 360px).
check("the phone right group WRAPS and keeps the model label readable",
      "#composerBar .cb-right { flex-wrap: wrap; justify-content: flex-start; position: relative; }" in ui
      and "#composerBar .cb-right .model-wrap > button { min-width: 96px; }" in ui)
check("the mobile model menu re-anchors to the full-width right group (stays on screen)",
      "#composerBar .cb-right .model-wrap { position: static; }" in ui
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

