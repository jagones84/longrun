#!/usr/bin/env python3
"""v1003 — the popup lands on its button at every UI zoom, and "All sessions" is everything.

Source (operator, 2026-11-14): *"switching on myartifacts all session doesnt show html
and other types … the copy path in the tre dot menu not working also it appears far
away"* and *"shift the group relevant to chat session (the one with autogenerate
below) … the button icon to collapse expand plan shall be just above autogenerate …
move all that group below. terminal and feed gruppo just above then the other"*.

Three defects, one page:
  A) the ⋯/right-click popups were positioned with a `getBoundingClientRect()` value
     (VISUAL px, scaled by the app's CSS `zoom`) written straight into `left` (CSS px,
     laid out inside the zoomed <html>) — measured at zoom 1.25 the menu opened 35 px
     past the button's right edge, its items at x=1569 on a 1440 px screen, so "copy
     the absolute path" could not be clicked at all;
  B) "All sessions" listed the edit journal, so every type nobody had journalled —
     the proposal HTMLs — read 0 and the page looked broken;
  C) the rail put the chat group (with the ✨) second, far from the composer, and the
     plan toggle among the Inspector jumps.

Locked here:
  A1 the placement converts a visual point/size to layout px with the live zoom, then
     clamps inside the layout viewport (and the preview window divides 94vw too);
  B1 the page lists FOLDERS, never a session's journal (the scope model itself is
     owned by `v1004`, which is where its pins live);
  C1 the rail order is objects → Inspector jumps → runtime (terminal/feed) → chat;
  C2 the PLAN jump is mounted INSIDE the chat group, immediately before the ✨.

Deterministic: no model, no network, no server, no browser. Run:
python3 tests/acceptance/v1003_artifacts_scope_and_placements.py
"""
import os
import re
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
RESULTS = []


def check(name, ok, detail=""):
    RESULTS.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail and not ok else ""))


ui = open(os.path.join(REPO, "webui", "index.html"), encoding="utf-8").read()
# The artifacts page's own slice: its scope model is pinned by `v1004`, and these
# checks only need to prove no dead route of the old models survives here.
_art_src = ui[ui.find("const ART_KIND_ORDER"):]
_art_src = _art_src[:_art_src.find("function _artThumbDrop(")]


def block(start, length=1400):
    i = ui.find(start)
    return ui[i:i + length] if i >= 0 else ""


# --- A: the popup placement honours the page zoom ----------------------------
place = block("function _placeMenu(m, x, y, alignRight)")
check("A1 the placement reads the live zoom from the scaled root",
      "function _uiZoom()" in ui
      and 'parseFloat(getComputedStyle(document.documentElement).zoom)' in ui)
check("A2 the click point and the menu box are converted visual → layout",
      "const tx = x / z, ty = y / z;" in place
      and "const w = m.offsetWidth, h = m.offsetHeight;" in place
      # v1029: innerWidth/innerHeight are VISUAL px under the app's zoom, like clientX —
      # the clamp must divide them too, or a menu opened near the right edge overflows.
      and "const vw = window.innerWidth / z, vh = window.innerHeight / z;" in place)
check("A3 the clamp happens in the same unit it writes",
      "Math.min(left, vw - w - 8)" in place and "if (top + h > vh - 8)" in place)
check("A4 the preview window also divides its width by the zoom (94vw is unscaled)",
      "width: min(calc(1180px / var(--zoom, 1)), calc(94vw / var(--zoom, 1)));" in ui)
check("A5 every popup goes through the ONE placement",
      # v1029: definition + preview ⋯ + artifact/edits right-click + plan-todo right-click
      # 3d81a4e (2026-11-15): the session row and its team header became body-level
      # popovers that open at the right-click pointer (`if (ev …) _placeMenu(...)` plus
      # the kebab fallback), so the same ONE helper now has 8 call sites.
      ui.count("_placeMenu(m,") == 8 and "openPvMenu" in ui and "openFileCtx" in ui
      and "_placeMenu(m, ev.clientX, ev.clientY, false);" in ui)

# --- B: the page's scope model — ONE owner, in v1004 -------------------------
# This file pinned the intermediate models twice (the two-way scope switch, then a
# per-row session filter) and both were wrong. The page now asks which FOLDERS to
# list (this session's / every session's), and `v1004` owns every pin for it, so a
# page change has one test to update instead of two that can disagree.
check("B1 the list is a FOLDER scan, never a session's journal",
      'scope: "workspace", workspace: _art.ws' in ui
      and 'qs.set("session", sessionId)' not in block("async function loadArtifacts()", 1800)
      and "scope: \"sessions\"" in ui)

# --- C: the rail groups, bottom-up toward the composer ----------------------
i_objects = ui.index('id="dockBtn"')
i_jump = ui.index('id="inspJump"')
i_runtime = ui.index('id="inspJumpRuntime"')
i_chat = ui.index('id="chatViewSec"')
# 2026-11-21 (operator): "the feed and terminal icon in the sidebar shall be placed on the
# very top of the sidebar" — the runtime group is now FIRST (v1239 pins the new order).
check("C1 rail order is runtime → objects → Inspector jumps → chat",
      i_runtime < i_objects < i_jump < i_chat, (i_runtime, i_objects, i_jump, i_chat))
check("C2 the chat group is the LAST group of the rail (nearest the composer)",
      i_chat < ui.index('class="tb-foot"'))
check("C3 the PLAN jump is mounted inside the chat group, before the ✨",
      'const host = $("chatViewSec");' in ui
      and 'host.querySelector(\'[data-gen-surface="chat.prompt"]\')' in ui
      and "host.insertBefore(b, spark)" in ui)
check("C4 a rebuild replaces the plan toggle instead of adding a second one",
      'host.querySelector(\'[data-insp-jump="plan"]\')' in ui and "old.remove()" in ui)
check("C5 the chat group is painted with the other jump boxes (state stays true)",
      '"inspJump", "inspJumpRuntime", "chatViewSec"' in ui)

# --- no leftover of the old two-name scope ---------------------------------
check("D1 the old ids are gone (one vocabulary)",
      "artScopeWorkspace" not in ui and "artScopeJournal" not in ui
      and "artScopeAll" not in ui and "artScopeSession" not in ui)
check("D2 the page never queries the journal route (a journal is not a folder)",
      _art_src.find('scope: "journal"') < 0 and _art_src.find('qs.set("session"') < 0
      and not re.search(r"_art\.sess\b", _art_src))

print("---")
passed = sum(RESULTS)
print("v1003: %d/%d PASS" % (passed, len(RESULTS)))
sys.exit(0 if passed == len(RESULTS) else 1)
