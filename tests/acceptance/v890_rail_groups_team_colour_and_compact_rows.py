#!/usr/bin/env python3
"""v890 — the sidebar points at its panel and toggles it, the deck's rows shrink, and a
team's colour is a real property that tints the org chart.

Operator, 2026-11-08:
  *"clicking on the relevant sidebar icons shall collapse the RH panel menu pointing to.
    expand if collapsed and collapse if expanded"*
  *"feed and terminal shall not be put there … other sidebar groups separated … the one
    impacting the chat session shall be put together as collapse the todos … you can also
    place somewhere else in the sidebar the tree dot and the automate icon"*
  *"the org chart shall be colored the box by team, light pastel colours editable as a
    further team property … randomically selected by architect … or user new team manual
    creation can select the color"*
  *"why the top bar in control of view is so BIH so height?"*
  *"find a way to make the agents panel not be so orrible when compressed in width … make
    icons that open other edit windows so you can make them very small"*
  *"it's useless you leave 'grant still required' if it's not true in the tool — remove
    please; there's already the per-tool box auto/required/… use defaults"*

Deterministic: reads the two pages + the teams module, no browser, no network.
"""
import inspect
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
UI = open(os.path.join(REPO, "webui", "index.html"), encoding="utf-8").read()
ORBIT = open(os.path.join(REPO, "src", "longrun", "orbit", "web", "orbit.html"),
             encoding="utf-8").read()
RAIL = UI[UI.find('<aside id="toolsBar"'):UI.find("</aside>", UI.find('<aside id="toolsBar"'))]
sys.path.insert(0, os.path.join(REPO, "src"))

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""))


# ---------------- A: one icon, two directions -------------------------------
check("A1 a jump TOGGLES its panel: expand when collapsed, collapse when open",
      "function _inspJumpToggle(name) {" in UI
      and "if (body.hidden) { _railOpenInsp(name); return; }" in UI
      and "toggleInsp(name);" in UI)
check("A2 the jump button calls the toggle (not a one-way open)",
      "b.onclick = () => { _inspJumpToggle(key); _paintInspJump(); };" in UI
      and "b.onclick = () => { _railOpenInsp(key); _paintInspJump(); };" not in UI)
check("A3 the control says both directions",
      'b.title = "expand or collapse the " + label + " panel";' in UI
      and 'b.setAttribute("aria-label", "expand or collapse the " + label + " panel")' in UI)
check("A4 the open mark covers BOTH groups",
      "#toolsBar #inspJump button.is-current," in UI
      and "#toolsBar #inspJumpRuntime button.is-current { color: var(--acc); }" in UI)
check("A5 on a phone collapsing the last open section closes the inspector drawer",
      'if (_vw() <= 1100 && document.body.classList.contains("show-right")' in UI
      and '&& !document.querySelector("#inspector section.insp-open")) {' in UI
      and '_toggleMobileDrawer("right");' in UI)
check("A6 the mobile rail tightens its tiers (operator: reduce the spacing)",
      "#toolsBar .tb-mid { gap: 4px; }" in UI
      and "#toolsBar .tb-sec + .tb-sec { margin-top: 4px; padding-top: 6px; }" in UI)

# ---------------- B: four groups, each by what it acts on -------------------
check("B1 the rail reads objects | chat | panel jumps | runtime",
      RAIL.count('class="tb-sec"') == 4
      and RAIL.index('id="kbSessionBtn"') < RAIL.index('id="chatViewSec"')
      and RAIL.index('id="chatViewSec"') < RAIL.index('id="inspJump"')
      and RAIL.index('id="inspJump"') < RAIL.index('id="inspJumpRuntime"')
      and RAIL.index('id="inspJumpRuntime"') < RAIL.index('class="tb-foot"'))
check("B2 feed and terminal are their OWN group, not panel jumps",
      'const INSP_JUMP_RUNTIME = ["terminal", "feed"];' in UI
      and "(INSP_JUMP_RUNTIME.indexOf(key) >= 0 ? runt : main).appendChild(b);" in UI)
check("B3 an empty runtime group takes no space",
      "#toolsBar #inspJumpRuntime:empty { display: none; }" in UI)
check("B4 the ✨ acts on the draft: it rides the chat group, not the foot",
      '["chat.prompt", "#inp", "#toolsBar #chatViewSec", null,' in UI
      and '"chat.prompt", "#inp", "#toolsBar .tb-foot"' not in UI)
check("B5 the ⋯ stays the rail's LAST control (reset/new out of the way)",
      RAIL.index('class="tb-foot"') < RAIL.index('id="moreBtn"')
      and RAIL.index('id="moreBtn"') > RAIL.index('id="inspJumpRuntime"'))

# ---------------- C: a team's colour is a property that tints the chart -----
from longrun.orchestrate import teams as teams_mod          # noqa: E402

_pal = teams_mod.palette()
check("C1 the backend already owns the colour (palette + create/update accept it)",
      bool(_pal) and all(p.get("color", "").startswith("#") for p in _pal)
      and "color=None" in str(inspect.signature(teams_mod.TeamRegistry.create))
      and "color=None" in str(inspect.signature(teams_mod.TeamRegistry.update)))
check("C2 the org node is tinted by it (pastel, from --tc)",
      ".node[data-team]{background:color-mix(in srgb, var(--tc) 16%, var(--panel2));" in ORBIT
      and "border-color:color-mix(in srgb, var(--tc) 45%, var(--line))" in ORBIT)
check("C3 the tint is read from the team the agent belongs to",
      "const colorOf = a => { const ids = a.teams || [];" in ORBIT
      and "' data-team=\"1\"'" in ORBIT
      and "';--tc:' + esc(tc)" in ORBIT)
check("C4 the org view receives the live teams on every refresh",
      "if (this.org) this.org.teams = this.teams;" in ORBIT)
check("C5 a team created by hand carries the chosen colour",
      'id="tmNewColor"' in ORBIT
      and "const color = ((sw && sw.dataset.touched && sw.value) || \"\")" in ORBIT)

# ---------------- D: the view bar is a bar, not a page ----------------------
check("D1 the view bar takes its content height (no page-tall flex grow)",
      "main.view-cols #viewBar{flex:0 0 auto;width:100%;margin-bottom:0}" in ORBIT
      and "main.view-cols #viewBar{flex:1 1 100%;margin-bottom:0}" not in ORBIT)

# ---------------- E: compact rows that open their editor -------------------
check("E1 the row shows VALUE buttons, not full-width form controls",
      'data-aedit="model"' in ORBIT and 'data-aedit="reports_to"' in ORBIT
      and '<select class="inp mini" name="agent-model"' not in ORBIT
      and '<input class="inp mini" name="agent-name"' not in ORBIT)
check("E2 the editor is one popover that commits on save",
      "openAgentEditor(ev, a, kind){" in ORBIT
      and 'data-aedit-f="model"' in ORBIT and "m.querySelector('[data-aedit-save]').onclick" in ORBIT
      and "this.save(sid, patch);" in ORBIT)
check("E3 the cells truncate instead of stretching the table",
      "table.at td .cbtn{" in ORBIT and "text-overflow:ellipsis" in ORBIT)
check("E4 the value button is bound without stealing the row",
      'body.querySelectorAll("[data-aedit]").forEach(b => { b.onclick = (ev) => {' in ORBIT
      and "ev.stopPropagation();" in ORBIT)

# ---------------- F: no repeated grant badge --------------------------------
check("F1 the per-row grant warning badge is gone (the per-tool box is the state)",
      'title="even on FULL this tool answers permission-denied' not in UI
      and 'data-ap="${nmRaw}" data-cur="${ap}"' in UI)
check("F2 the per-tool cycle still offers auto / required / denied",
      "Per-tool policy — click to cycle: <b>auto</b> · <b>required</b> · <b>denied</b>" in UI)
check("F3 the dual-permission fact is stated ONCE, in the exclusive badge",
      'exclusive: \'<span class="sk-badge sk-core" title="exclusive built-in tool' in UI
      and "granted sessions" in UI)

print("---")
passed = sum(results)
print("%d/%d PASS" % (passed, len(results)))
sys.exit(0 if passed == len(results) else 1)
