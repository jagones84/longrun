#!/usr/bin/env python3
"""v891 — the Control deck fills the page, never pushes a panel past the right border,
and every row's actions live in ONE vertical ⋮ menu.

Operator, 2026-11-08:
  *"the latest right panel in view is not right anchored it disappear beyond the right
  border"* · *"the control panels shall be bottom anchored to the bottom"* · *"put all in
  a menu tree vertical dots for each agent … also the team tre dot menu shall be vertical
  to save horiz space … still it's unreadable due to overlap"* · *"the same for the JOB
  panel, same considerations, space is not optimized"*.

Deterministic: reads the Control deck, no browser, no network.
"""
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
ORBIT = open(os.path.join(REPO, "src", "longrun", "orbit", "web", "orbit.html"),
             encoding="utf-8").read()

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""))


# ---------------- A: the deck owns the page, nothing escapes the frame ----------
check("A1 view rows SHARE the deck height instead of a 100vh guess",
      "flex:1 1 0;min-width:0;min-height:0;overflow:hidden}" in ORBIT
      and "height:calc(100vh - 150px)" not in ORBIT)
check("A2 a column may shrink to its share, the row clips",
      "main.view-cols .vrow > section.panel[data-panel]{min-width:0;max-width:100%;min-height:0}" in ORBIT
      and "min-width:180px;min-height:0}" not in ORBIT)
check("A3 the deck frame clips instead of a page-level horizontal scroll",
      "main.view-cols .deckBody.vrows{flex-direction:column;flex-wrap:nowrap;gap:0;overflow:hidden}" in ORBIT)
check("A4 the lone-panel view is a flex chain to the bottom (no vh arithmetic)",
      "main.view-one .grid2{height:100% !important;min-height:0" in ORBIT
      and "main.view-one .col{display:flex;flex-direction:column;min-height:0;flex:1 1 auto}" in ORBIT
      and "main.view-one section.panel[data-panel]{min-height:0;flex:1 1 auto;border-radius:var(--r)}" in ORBIT
      and "main.view-one .orgwrap{min-height:0;flex:1 1 auto}" in ORBIT
      and "main.view-one .panel.cpanel .cbody{height:auto;min-height:0;flex:1 1 auto}" in ORBIT
      and "main.view-one .grid2:not(:has(section.panel:not([hidden]))){display:none !important}" in ORBIT
      and "main.view-one .col:not(:has(section.panel:not([hidden]))){display:none !important}" in ORBIT)
check("A5 a saved row height is pinned, an unsaved row shares the rest",
      'if (h) { row.style.height = h + "px"; row.style.flex = "0 0 auto"; }' in ORBIT)
check("A6 the row resizer pins the same way",
      'rowA.style.flex = "0 0 auto";   // v891: an explicit height beats the share' in ORBIT)

# ---------------- B: one vertical menu per row ----------------------------------
check("B1 an agent row has ONE ⋮ menu, not three action buttons",
      'data-amore="' in ORBIT and "openAgentMenu(ev, a, aid){" in ORBIT
      and 'data-amenu="go"' in ORBIT and 'data-amenu="clear"' in ORBIT and 'data-amenu="del"' in ORBIT
      and 'data-clear="' not in ORBIT and 'data-del="1"' not in ORBIT)
check("B2 the agent menu keeps the same endpoints",
      '"/api/sessions/" + encodeURIComponent(a.session) + "/clear"' in ORBIT
      and 'this.api.del("/api/agents/" + encodeURIComponent(a.session))' in ORBIT)
check("B3 the team header is two icons: assign ⊕ and a VERTICAL dots menu (v910: the No-team bucket carries the same kebab)",
      'title="assign agents to \' + esc(g.name) + \'" aria-label="assign agents to \' + esc(g.name) + \'">⊕</button>' in ORBIT
      and "team actions — all sessions of this team" in ORBIT
      and "no-team actions — every session without a team" in ORBIT
      and '>＋ assign</button>' not in ORBIT)
check("B4 a job row has ONE ⋮ menu with run + delete",
      'data-jmore="' in ORBIT and 'data-jmenu="run"' in ORBIT and 'data-jmenu="del"' in ORBIT
      and 'data-run="' not in ORBIT and 'data-jdel="' not in ORBIT)
check("B5 the job menu keeps dispatch + delete",
      "if (run) run.onclick = () => { closePopover(); this.dispatch(jid); };" in ORBIT
      and 'this.api.del("/api/jobs/" + encodeURIComponent(jid))' in ORBIT)

# ---------------- C: the narrow table does not overlap --------------------------
check("C1 the A-id has a fixed gutter and its own clipping box",
      "table.at col.c-id{width:58px}" in ORBIT
      and 'table.at td .aidbox{display:flex;align-items:center;gap:3px;min-width:0;overflow:hidden}' in ORBIT
      and '<td class="aid"><span class="aidbox">' in ORBIT)
check("C2 the action column is one glyph wide",
      "table.at col.c-act{width:26px}" in ORBIT)

# ---------------- D: the rest of the squeeze -----------------------------------
check("D1 a job goal clamps to two lines and the picker keeps a width",
      "-webkit-line-clamp:2" in ORBIT and "#jobTo{flex:1 1 120px;min-width:110px}" in ORBIT)
check("D2 the view bar can shrink and its name truncates",
      "min-width:0;\n    border:1px solid var(--line);border-radius:10px;background:var(--panel)}" in ORBIT
      and "#viewBar .vname{font-weight:700;font-size:12px;min-width:0;overflow:hidden;" in ORBIT)

print("---")
passed = sum(results)
print("%d/%d PASS" % (passed, len(results)))
sys.exit(0 if passed == len(results) else 1)
