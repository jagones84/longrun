"""v405 — an ordered live SUMMARY beside each inspector tab (JAG-403g).

Stdlib-only, deterministic, no browser. The RH inspector tabs now carry a one-line
summary so the user reads cost / ctx% / pending / plan counts WITHOUT expanding the
tab; it updates in real time and drops under the label when the rail is narrowed.

Covers:
  A) every tab has a summary slot (ihd-s)
  B) the summary is a wrapping flex row that can drop under the label (narrow rail)
  C) the Files tab is renamed WORKSPACE (the internal data-insp key stays "files")
  D) each summary is WIRED to the live renderer that already runs on updates
  E) the Plan summary is ordered (done · super · doing · todo · blocked · run)
  F) the duplicate Browser tab is gone (its search half duplicated Discover)
"""
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
HTML = open(os.path.join(REPO, "webui", "index.html"), encoding="utf-8").read()

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if (detail and not ok) else ""))


# ------------------------------------------------------------------ A) slots
SLOTS = ["sCost", "sContext", "sPlan", "sRoles", "sWorkspace", "sCodebase",
         "sTerm", "sFeed", "apprCount"]
for sid in SLOTS:
    check("A slot exists for '%s'" % sid, ('id="%s"' % sid) in HTML and "ihd-s" in HTML)

check("A1 every ihd-s slot is a span inside a header button",
      HTML.count('class="ihd-s"') >= 9 and HTML.count('id="apprCount" class="ihd-s"') == 1)

# ------------------------------------------------------------------ B) layout
check("B1 the header is a wrapping flex row (summary can drop under the label)",
      "#inspector .insp-hd { display: flex; align-items: center; flex-wrap: wrap;" in HTML)
check("B2 the summary is right-aligned and ellipsizes when tight",
      "#inspector .ihd-s { margin-left: auto;" in HTML and "text-overflow: ellipsis;" in HTML
      and "white-space: nowrap;" in HTML)

# ------------------------------------------------------------------ C) Workspace
check("C1 the tab label is 'Workspace' (not 'Files')",
      # JAG-425: the binding is a delegated data-call attribute now; assert the label
      # plus the (unchanged) internal key that the section still targets.
      '>Workspace<span class="ihd-s"' in HTML and 'data-insp="files"' in HTML)
check("C2 the internal data-insp key stays 'files' (JS + tests depend on it)",
      'data-insp="files"' in HTML and 'files: "files"' in HTML)

# ------------------------------------------------------------------ D) wiring
check("D1 Cost summary is set in renderCosts", '_isum("sCost"' in HTML)
check("D2 Context summary is set in loadCtx", '_isum("sContext", (d.pct != null ? d.pct : 0)' in HTML)
check("D3 Approvals summary is set in loadApprovals", '_isum("apprCount"' in HTML)
check("D4 Plan summary is set in renderGraph", '_isum("sPlan", planSummary(c, graph.run_id)' in HTML)
check("D5 Roles summary is set in the rules panel loader", '_isum("sRoles"' in HTML)
check("D6 Workspace summary is set from the workspace path", '_isum("sWorkspace", _base(d.workspace)' in HTML
      and '_isum("sWorkspace", _base(d.path)' in HTML)
check("D7 Codebase summary is set in cbStatus", '_isum("sCodebase"' in HTML)
check("D9 Terminal summary follows the shell cwd", HTML.count('_isum("sTerm", _base(') == 2)
check("D10 Feed summary is a live event counter", "let _feedN = 0;" in HTML
      and '_isum("sFeed", _feedN + " events"' in HTML)
check("D11 a helper clears the summary when there is no data",
      "function _isum(id, text, cls)" in HTML and '_isum("sContext", "")' in HTML
      and '_isum("sCost", "")' in HTML)

# ------------------------------------------------------------------ E) plan order
check("E1 countNodes tracks 'superseded' too",
      "todo: 0, doing: 0, done: 0, blocked: 0, cancelled: 0, superseded: 0" in HTML)
_seg = HTML[HTML.find("function planSummary"): HTML.find("function planSummary") + 700]
_order = ["parts.push(c.%s" % k for k in ("done", "superseded", "cancelled", "doing", "todo", "blocked")]
_pos = [_seg.find(x) for x in _order]
check("E2 the plan counts are pushed in a fixed order (done, super, canc, doing, todo, blocked)",
      all(p >= 0 for p in _pos) and _pos == sorted(_pos), str(_pos))
check("E3 the plan summary carries the run id",
      'run " + run' in _seg and "graph.run_id" in HTML)

# ------------------------------------------------------------------ F) no Browser tab
check("F1 the duplicate Browser tab is GONE (JAG-403h)",
      'data-insp="browser"' not in HTML and "function browserGo" not in HTML
      and '["browser", "Browser"]' not in HTML)

print("---")
ok = sum(results)
print("%d/%d checks passed" % (ok, len(results)))
sys.exit(0 if ok == len(results) else 1)
