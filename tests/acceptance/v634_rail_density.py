#!/usr/bin/env python3
"""v634 — the whole RH rail reports data (collapsible detail, one-line rows).

Operator report: the Context ring + 10 bars were always open, the Cost panel
spent four lines on a number + five chips + a wrapped billing sentence + a
wider-than-needed run list, and the Plan body opened with a caps title, a wall
of four buttons and an empty-state sentence.

Reference read before implementing: `hermes-control-interface` (single-page
console) and `deer-flow/frontend/.../token-usage-indicator.tsx` +
`todo-list.tsx` — the frontier pattern is a HEADER that carries the number and a
body that opens on demand; detail lives in a tooltip/dropdown, not in prose.

Contract:
  A) Context: the ring + category bars live inside a CLOSED <details>.
  B) Cost: the total is a row value, the billing proof is the tooltip, and every
     run row is ONE line (money/counts never clipped, model ellipsised).
  C) Plan: no caps title, no button wall, no empty-state prose — two input rows
     with their action beside them and the maintenance actions as inline links.
  D) One spacing rhythm for every inspector section.

Run: python tests/acceptance/v634_rail_density.py
"""
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="v634_")
os.environ["LONGRUN_SESSIONS_DIR"] = os.path.join(TMP, "sessions")
os.environ["LONGRUN_GRAPHS_DIR"] = os.path.join(TMP, "graphs")
os.environ["LONGRUN_THREADS_DIR"] = os.path.join(TMP, "threads")
os.environ["LONGRUN_DB"] = os.path.join(TMP, "events.db")
os.environ["LONGRUN_DATA_DIR"] = os.path.join(TMP, "data")
for d in ("cfg", "sessions", "graphs", "threads", "data"):
    os.makedirs(os.path.join(TMP, d), exist_ok=True)
sys.path.insert(0, os.path.join(REPO, "src"))

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""))


def src(*parts):
    with open(os.path.join(REPO, *parts), encoding="utf-8") as f:
        return f.read()


UI = src("webui", "index.html")

# ---- A. Context breakdown is on demand ----------------------------------------
check("A1 the ring + bars live inside a CLOSED details",
      '<details class="brk">' in UI and "<summary>breakdown</summary>" in UI
      and "<details class=\"brk\">\n          <summary>breakdown</summary>\n          <div id=\"ctxCats\"></div>"
          in UI.replace("\r\n", "\n"))
check("A2 the summary styling is shared with the dry-run row (one rule)",
      "details.dryrun > summary, details.brk > summary {" in UI)

# ---- B. Cost: number first, proof in the tooltip ------------------------------
check("B1 the total is a row value, not a hero number",
      ".costtot { font-size: 16px;" in UI and ".costtot { font-size: 20px;" not in UI)
check("B2 the row shows calls + p50 only; the billing proof moves to the tooltip",
      '" \\u00b7 p50 " + _p50' in UI
      and 'total.title = c.calls ? ("billing: "' in UI)
check("B3 one line per run: counts and money never clip, the model ellipsises",
      ".runhd { display: flex; flex-wrap: nowrap;" in UI
      and ".runhd .cu { font-weight: 700; color: var(--txt); min-width: 46px; text-align: right; flex: none; }" in UI
      and "text-overflow: ellipsis;" in UI)
check("B4 the full model name stays reachable (row tooltip)",
      "' this run \\u00b7 ' + _attr(mtxt)" in UI)

# ---- C. Plan: two input rows + inline actions --------------------------------
check("C1 the caps title is gone", "TASK LIST (persistent)" not in UI)
check("C2 the goal field and its action share one row",
      UI.index('id="planInp"') < UI.index('data-call="planGoal"')
      and UI.index('data-call="planGoal"') < UI.index('id="taskInp"'))
check("C3 the node field has + and replan beside it",
      'id="taskInp"' in UI and 'data-call="addTask"' in UI and 'data-call="replanGraph"' in UI
      and ">↻</button>" in UI)
check("C4 maintenance actions are inline links, not a button wall",
      'class="lnk" data-call="showConstellation"' in UI
      and 'class="lnk" data-call="resetRunGraph"' in UI
      and 'class="lnk" data-call="resetPlan"' in UI)
check("C5 the empty-state sentence about the run graph is gone",
      "run graph: — (send a request to generate it)" not in UI)
check("C6 the live count element survives",
      'id="taskCount"' in UI and '$("taskCount")' in UI)

# ---- D. one rhythm ------------------------------------------------------------
check("D1 every inspector section shares the 6/8 padding rhythm",
      "#inspector .insp-body { padding: 0 6px 8px; }" in UI
      and "#inspector .card { padding: 6px 8px; margin-bottom: 4px; }" in UI)

print("\nv634: %d/%d PASS" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
