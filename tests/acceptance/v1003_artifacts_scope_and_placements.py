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
  B1 "All sessions" = the workspace scan (every artifact), "This session" = that
     session's journal — two different questions, both wired to real routes;
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
      and "window.innerWidth, vh = window.innerHeight" in place)
check("A3 the clamp happens in the same unit it writes",
      "Math.min(left, vw - w - 8)" in place and "if (top + h > vh - 8)" in place)
check("A4 the preview window also divides its width by the zoom (94vw is unscaled)",
      "width: min(calc(1180px / var(--zoom, 1)), calc(94vw / var(--zoom, 1)));" in ui)
check("A5 both popups go through the ONE placement",
      # the definition + its two callers: the ⋯ menu and the right-click menu
      ui.count("_placeMenu(m,") == 3 and "openPvMenu" in ui and "openFileCtx" in ui)

# --- B: the two scopes ask two different questions ---------------------------
check("B1 'All sessions' is the workspace scan (every artifact, provenance labelled)",
      'id="artScopeAll"' in ui and 'id="artScopeSession"' in ui
      and 'qs.set("scope", "workspace")' in ui and 'qs.set("workspace", _art.ws)' in ui)
check("B2 'This session' is that session's journal — a route, not a client filter",
      'qs.set("session", sessionId)' in ui
      and 'open a session — this view lists the files it wrote' in ui)
check("B3 the default scope shows every type (scope 'all', not the journal)",
      'scope: "all", ws: "", wsName: "", total: 0' in ui
      and '_art.scope !== "session"' in ui)
check("B4 a session-less folder is an honest empty state, not a silent blank",
      "this view lists its workspace folder" in ui)

# --- C: the rail groups, bottom-up toward the composer ----------------------
i_objects = ui.index('id="dockBtn"')
i_jump = ui.index('id="inspJump"')
i_runtime = ui.index('id="inspJumpRuntime"')
i_chat = ui.index('id="chatViewSec"')
check("C1 rail order is objects → Inspector jumps → runtime → chat",
      i_objects < i_jump < i_runtime < i_chat, (i_objects, i_jump, i_runtime, i_chat))
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
      "artScopeWorkspace" not in ui and "artScopeJournal" not in ui)
check("D2 no dead reference to the removed scope value",
      not re.search(r'_art\.scope === "workspace"', ui) and 'scope: "workspace"' not in ui)

print("---")
passed = sum(RESULTS)
print("v1003: %d/%d PASS" % (passed, len(RESULTS)))
sys.exit(0 if passed == len(RESULTS) else 1)
