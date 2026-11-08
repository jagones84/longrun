#!/usr/bin/env python3
"""v892 — the table spends its width on the values, the ⋮ has no frame, the job id sits
under its status, and the deck cannot scroll sideways.

Operator, 2026-11-08:
  *"remove the team belonging icon, it occupies too much horiz space"* · *"too much space
  between AX code and the rest, also between the different columns … remove frames from
  the 3 dots menu everywhere"* · *"in jobs put the JX under the 'done' to gain horiz
  space"* · *"last right panel still go out beyond of right border not fixed"*.

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


# ---------------- A: the Teams column is gone, its picker moved one click away ------
check("A1 no Teams column in the table",
      '<col class="c-teams">' not in ORBIT and "<th>Teams</th>" not in ORBIT
      and 'data-tm="1"' not in ORBIT and "col.c-teams" not in ORBIT)
check("A2 the teams picker lives in the row menu",
      'data-amenu="teams"' in ORBIT
      and 'm.querySelector(\'[data-amenu="teams"]\').onclick = () => { closePopover(); this.openTeamPicker(ev, a); };' in ORBIT)
check("A3 the table keeps one cell per column (4 since v895: the prompt cell is gone)",
      '<td colspan="4">' in ORBIT and '><td></td><td colspan="3">' in ORBIT
      and 'colspan="8"' not in ORBIT and 'colspan="7"' not in ORBIT and 'colspan="5"' not in ORBIT)

# ---------------- B: the width goes to the values ----------------------------------
check("B1 a tight id gutter, a narrow action column, small padding",
      "table.at col.c-id{width:58px}" in ORBIT
      and "table.at col.c-act{width:26px}" in ORBIT
      and "table.at td{padding:3px 3px;" in ORBIT
      and "table.at td.aid{padding-left:2px}" in ORBIT)
check("B2 NAME carries no width (a fixed layout gives it the remainder)",
      "table.at col.c-name{" not in ORBIT)

# ---------------- C: a ⋮ is a glyph, not a framed button ---------------------------
check("C1 the dots style removes the frame",
      ".btn.ghost.mini.dots{border:0;background:transparent;padding:0;width:20px;min-width:20px;height:22px;" in ORBIT)
check("C2 the agent row and the job row wear it",
      'class="btn ghost mini dots" data-amore=' in ORBIT
      and 'class="btn ghost mini icon-action dots" data-jmore=' in ORBIT)
check("C3 the team header's assign is frameless too",
      "tr.grp-head .btn.tmadd{border:0;background:none;padding:0 3px;" in ORBIT)

# ---------------- D: the job id sits under the status ------------------------------
check("D1 the job left cell is a stack (status over id)",
      '<span class="jstack"><span class="st \' + esc(j.status)' in ORBIT
      and '<span class="aid">\' + esc(j.id) + \'</span></span>' in ORBIT)
check("D2 the stack is a column and costs no width",
      ".job .jstack{display:flex;flex-direction:column;align-items:flex-start;gap:2px;" in ORBIT)

# ---------------- E: the right border is hard --------------------------------------
check("E1 the page cannot scroll sideways",
      "margin:0;height:100%;\n    overflow-x:hidden}" in ORBIT)
check("E2 the deck clips X and still scrolls Y when a stacked layout needs it",
      "min-width:0;overflow-x:hidden;overflow-y:auto}" in ORBIT)
check("E3 the deck body clips X as well",
      "overflow-x:hidden}" in ORBIT.split(".deckBody{")[1][:220])

print("---")
passed = sum(results)
print("%d/%d PASS" % (passed, len(results)))
sys.exit(0 if passed == len(results) else 1)
