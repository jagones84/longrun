#!/usr/bin/env python3
"""v1035 — Settings points at the Marketplace, and the Control deck stands alone.

Operator, 2026-11-15:
  *"in MCP put a button that redirect to marketplace/mcps … the same in the skills
    settings panel … etcetera."*
  *"if open editors and pass to control page and squeeze it doesn't respond to close
    commands and commands in general and survive the page shift fix"*
  *"control page horrible squeeze demolish everything and mobile shall become one below
    the other."*

Three surfaces, three contracts:

  A) A Settings category that owns a catalogue (MCP, Connectors, Skills) carries ONE
     button that lands on the Marketplace filtered to THAT kind — no second catalogue,
     no second install path;
  B) while the Control deck owns the row the editor is hidden (it lived inside the
     `inert` `#app`, so it stayed visible and dead); it comes back unchanged, and a
     resize while it is not rendered must not clamp its float position to 0,0;
  C) below 1200px the deck is ONE column of full-width panels, never wrapped into a
     second off-screen column, never shrunk to strips, and the deck scrolls.

Deterministic: static contract on webui/index.html, webui/assets/editor.js and
src/longrun/orbit/web/orbit.html.
Run: python3 tests/acceptance/v1035_marketplace_redirect_and_control_stack.py
"""
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
UI = open(os.path.join(REPO, "webui", "index.html"), encoding="utf-8").read()
ED = open(os.path.join(REPO, "webui", "assets", "editor.js"), encoding="utf-8").read()
ORBIT = open(os.path.join(REPO, "src", "longrun", "orbit", "web", "orbit.html"),
             encoding="utf-8").read()

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""))


# ---- A: Settings -> Marketplace, one button per catalogue ---------------------
OMK = UI[UI.find("function openMarketKind(kind)"):]
OMK = OMK[:OMK.find("\n}\n")]
check("A1 one opener closes Settings, filters the catalogue, then shows it",
      "function openMarketKind(kind)" in UI
      and "closeSettings();" in OMK
      and "window.LRMkt.state.manage = false;" in OMK
      and 'window.LRMkt.state.kind = String(kind || "all");' in OMK
      and "showMarket();" in OMK)
check("A2 the MCP panel points at the MCP section",
      'data-call="openMarketKind" data-args=\'["mcp"]\'' in UI)
check("A3 the Connectors panel points at connectors",
      'data-call="openMarketKind" data-args=\'["connector"]\'' in UI)
check("A4 the Skills panel points at skills",
      'data-call="openMarketKind" data-args=\'["skill"]\'' in UI)
check("A5 exactly the three catalogue panels grew a door (no invented surface)",
      UI.count('data-call="openMarketKind"') == 3,
      UI.count('data-call="openMarketKind"'))
check("A6 every door is named for hover and for a screen reader",
      UI.count('title="browse MCP servers in the Marketplace"') == 1
      and UI.count('title="browse connectors in the Marketplace"') == 1
      and UI.count('title="browse skills in the Marketplace"') == 1
      and 'aria-label="browse' in UI or 'title="browse' in UI)
check("A7 the kinds are the four the catalogue really has",
      '"plugin", "skill", "mcp", "connector"' in
      open(os.path.join(REPO, "webui", "assets", "market.js"), encoding="utf-8").read())

# ---- B: the editor stands down under Control, and comes back -----------------
check("B1 the editor is hidden while the deck owns the row",
      "body.control-on #editorDock { display: none !important; }" in UI)
check("B2 that rule is page-scoped, not a global hide",
      "body.control-on #editorDock" in UI and "#editorDock { display: none" not in UI.split("body.control-on #editorDock")[0][-200:])
check("B3 Sessions un-inerts the app and re-seats the dock",
      'app.removeAttribute("inert")' in UI and "_dockControlSettle();" in UI)
check("B4 a not-rendered dock is never clamped (the float keeps its place)",
      "if (!r.width && !r.height) return;" in ED)

# ---- C: one panel under the other below 1200px ------------------------------
check("C1 the narrow deck is a COLUMN that never wraps",
      "main.view-cols .deckBody.vrows{flex-direction:column;flex-wrap:nowrap;" in ORBIT)
check("C2 the stack scrolls instead of clipping the last panel",
      "overflow-y:auto;overflow-x:hidden}" in ORBIT)
check("C3 a stacked panel keeps a readable floor and never shrinks",
      "main.view-cols .deckBody section.panel[data-panel]{width:100%;max-width:100%;min-width:0;"
      in ORBIT
      and "flex:0 0 auto !important;min-height:320px !important}" in ORBIT)
check("C4 an explicit rows view stacks its columns too",
      "main.view-cols .vrow{flex-direction:column;overflow:visible}" in ORBIT
      and "main.view-cols .vrow > section.panel[data-panel]," in ORBIT)
check("C5 the row splitter and row heights cannot fight the stack",
      ".rz-vrow{display:none}" in ORBIT
      and ".vrow{height:auto !important;flex:0 0 auto !important}" in ORBIT)
check("C6 the narrow breakpoint is ONE number (1200px), no 1100px left",
      "max-width:1100px" not in ORBIT and "max-width:1200px" in ORBIT)
check("C7 the JS agrees with the CSS: no rows layout below 1200px",
      'if (window.matchMedia("(max-width:1200px)").matches) return; // mobile stack' in ORBIT
      and 'if (window.matchMedia("(max-width:1200px)").matches) {' in ORBIT)
check("C8 crossing down tears an existing rows layout down",
      "if (d.classList.contains(\"vrows\")) this._layoutViewCols();" in ORBIT
      and "this._vlastNCols = 0;" in ORBIT)
check("C9 the deck rail becomes a top strip at the same breakpoint",
      "#deckRail{flex-direction:row;align-items:center;overflow-x:auto;overflow-y:hidden;" in ORBIT)

print("---")
passed = sum(results)
print("v1035: %d/%d PASS" % (passed, len(results)))
sys.exit(0 if passed == len(results) else 1)
