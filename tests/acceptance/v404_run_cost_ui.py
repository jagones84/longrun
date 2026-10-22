"""v404 — run-grouped cost panel + Bridge org-table/org-chart UX (JAG-403f).

Stdlib-only, deterministic, no browser, no model. Covers the three points:

  A) the RH Cost tab groups API calls PER RUN (one user turn); each run is a
     collapsed row with its own total, expandable to the individual calls.
     The ledger now carries an optional `run` id, tagged by `chat_once`.
  B) the Bridge AGENTS table is packed to the LEFT (content-sized + explicit
     column widths), with its new-agent inputs no longer full-width.
  C) the Bridge ORG CHART keeps single-click = preview (which now ALSO highlights +
     scrolls to the agent in the AGENTS table, JAG-451), double-click = open the
     agent's session, and the right-click quick-action menu reuses the
     EXISTING stores/endpoints (no third synced data entry).
"""
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
tmp = tempfile.mkdtemp(prefix="v404-")
os.environ["LONGRUN_DATA_DIR"] = os.path.join(tmp, "data")
os.environ["LONGRUN_CONFIG_DIR"] = os.path.join(tmp, "cfg")
os.environ["LONGRUN_SESSIONS_DIR"] = os.path.join(tmp, "sessions")
os.environ["LONGRUN_DB"] = os.path.join(tmp, "events.db")
os.environ["LONGRUN_GRAPH_DIR"] = os.path.join(tmp, "graphs")
os.environ["LONGRUN_EDITS_DIR"] = os.path.join(tmp, "edits")
os.environ["LONGRUN_RUNS_DIR"] = os.path.join(tmp, "runs")
os.environ["LONGRUN_COSTS_DIR"] = os.path.join(tmp, "costs")
for d in ("cfg", "sessions", "graphs", "edits", "runs", "costs"):
    os.makedirs(os.path.join(tmp, d), exist_ok=True)
sys.path.insert(0, os.path.join(REPO, "src"))

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if (detail and not ok) else ""))


HTML = open(os.path.join(REPO, "webui", "index.html"), encoding="utf-8").read()
ORBIT = open(os.path.join(REPO, "src", "longrun", "orbit", "web", "orbit.html"), encoding="utf-8").read()
AGENT = open(os.path.join(REPO, "src", "longrun", "agent", "agent.py"), encoding="utf-8").read()

# ------------------------------------------------------------------ A) per-run cost
from longrun.model import costs  # noqa: E402

rec1 = costs.record("sess-a", "openrouter:foo", {"prompt_tokens": 10, "completion_tokens": 5}, run="run1")
check("A1 record() persists the run id", rec1 and rec1.get("run") == "run1", str(rec1))
rec2 = costs.record("sess-a", "openrouter:foo", {"prompt_tokens": 3, "completion_tokens": 1}, run="run1")
rec3 = costs.record("sess-a", "openrouter:bar", {"prompt_tokens": 7, "completion_tokens": 2}, run="run2")
rec4 = costs.record("sess-a", "openrouter:foo", {"prompt_tokens": 4, "completion_tokens": 1})
check("A2 record() works without a run id (back-compat)", rec4 and rec4.get("run") is None)
_sum = costs.summary("sess-a", tail=10)
check("A3 summary() exposes run ids in the recent calls",
      [r.get("run") for r in _sum["recent"]] == [None, "run2", "run1", "run1"],
      str([r.get("run") for r in _sum["recent"]]))

check("A4 chat_once tags each call with the turn's run id",
      'run=getattr(trace, "id", None)' in AGENT)

# UI: renderCosts groups by run, collapsed by default, click to expand
check("A5 the Cost panel groups the calls by run",
      "function _costRunHtml(" in HTML and 'class="runrow"' in HTML and 'class="runhd"' in HTML)
check("A6 every run is COLLAPSED by default, click toggles it",
      "let _costOpen = {};" in HTML
      and "_costOpen[h.dataset.k] = !_costOpen[h.dataset.k]" in HTML)
check("A7 calls without a run id fold into ONE bucket (no row flood)",
      'r.run || "~norun"' in HTML and 'g.key === "~norun"' in HTML)
check("A8 the expanded run lists the individual calls (.runbody)",
      'class="runbody"' in HTML and "_costCallsHtml(" in HTML and ".runbody .costrow" in HTML)
check("A9 collapsed run summaries wrap instead of clipping at narrow rail width",
      ".runhd { display: flex; flex-wrap: wrap;" in HTML)
check("A10 expanded cost-call rows wrap instead of clipping at narrow rail width",
      ".costrow { display: flex; flex-wrap: wrap;" in HTML)
check("A11 collapsed model labels wrap instead of being ellipsized",
      ".runhd .rm { flex: 1; min-width: 0; white-space: normal; overflow-wrap: anywhere;" in HTML)
check("A12 expanded model labels wrap instead of being clipped",
      ".costrow .cm { flex: 1; min-width: 0; white-space: normal; overflow-wrap: anywhere;" in HTML)

# ------------------------------------------------------------------ B) AGENTS table
check("B1 the agents table is content-sized + packed left (not full width)",
      "table.at{width:auto;table-layout:fixed" in ORBIT)
check("B2 the table declares explicit, left-packed column widths",
      '<col class="c-id">' in ORBIT and '<col class="c-model">' in ORBIT
      # JAG-2.8 restyled the board; the CONTRACT is that every column width is
      # declared explicitly (a magic number in the test only froze the old skin).
      and all(("table.at col.c-%s{width:" % _c) in ORBIT
              for _c in ("id", "name", "role", "model", "rep", "teams", "file", "act")))
check("B3 the new-agent inputs are no longer full-width",
      'id="agNewName" placeholder="new agent — name…" style="width:240px;flex:none"' in ORBIT)

# ------------------------------------------------------------------ C) org chart
check("C1 single-click still previews the constellation (+ JAG-451 focuses the agent)",
      "if (this.onPick) this.onPick(this.bySid[n.dataset.sid]);" in ORBIT
      and 'this.org = new OrgChartView((a) => { this.tac.open(a, "agent")' in ORBIT
      and "this.agents.focusAgent(a.session)" in ORBIT)
check("C2 double-click still opens the agent's session in the main app",
      "n.ondblclick = () => { if (this.onGoTo) this.onGoTo(this.bySid[n.dataset.sid]); };" in ORBIT
      and "gotoAgent(agent){ if (!agent) return;" in ORBIT)
check("C3 right-click opens a quick-action menu on the node",
      "n.oncontextmenu = (ev) =>" in ORBIT and 'm.className = "ctxmenu"' in ORBIT)
check("C3b the menu is built + torn down safely",
      "closeMenu(){" in ORBIT and 'm.className = "ctxmenu"' in ORBIT)
check("C4 the menu REUSES existing stores/endpoints (no new data entry)",
      "this.openPrompt(a);" in ORBIT and 'row.querySelector("[data-brief]")' in ORBIT
      and "clearOrbitSession(a.session);" in ORBIT)
check("C5 the org-chart header documents the three gestures",
      "click = preview" in ORBIT and "dbl-click = open" in ORBIT and "right-click = actions" in ORBIT)

print("---")
ok = sum(results)
print("%d/%d checks passed" % (ok, len(results)))
sys.exit(0 if ok == len(results) else 1)
