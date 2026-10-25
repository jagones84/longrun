#!/usr/bin/env python3
"""v651 — the WebUI must show ONE object, in ONE form, with a way out.

Source (operator, on the Improvements panel): "ma che è sto schifo? file
duplicati? ma sei scemo riguarda la codebase" + "pending proposal che è? non si
annulla mai, rimarrà per sempre così?" + "riguarda tutta la webui e codebase (che
devono essere synced) per questa tipologia di schifezze".

Three defect classes, each confirmed against BOTH the renderer and the store:

  1. one file listed TWICE — `data/memory/agent_notes.md` from the fixed list and
     `/home/<u>/.longrun/data/memory/agent_notes.md` from a ledger write — and the
     list bled past the card edge because an inline anchor cannot wrap;
  2. histories with no way out: decided proposals, and background runs that a
     "N active" counter kept showing after they finished;
  3. two destructive buttons ("reset graph" / "reset list") for ONE store, since a
     chat run id IS its session id.

Contract:
  A) a data-home path is normalised to ONE key before it is listed, in the API
     and in the panel;
  B) a long path wraps inside its card instead of overflowing;
  C) decided proposals can be deleted (pending survive) through a real route;
  D) "active" counts only non-terminal runs, and finished ones can be cleared;
  E) one control for the plan store — the duplicate is gone;
  F) the Knowledge "sources" button no longer shows files under a sources label.

Deterministic: static contract checks + an isolated store round-trip.
No server, no model, no network.
Run: python3 tests/acceptance/v651_ui_object_truth.py
"""
import os
import re
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="v651_")
for name, tail in {
    "LONGRUN_DATA_DIR": "data",
    "LONGRUN_CONFIG_DIR": "cfg",
    "LONGRUN_DB": "events.db",
    "LONGRUN_SESSIONS_DIR": "sessions",
    "LONGRUN_MATRIX_DOT": "matrix",
    "LONGRUN_APPROVALS": "approvals.json",
}.items():
    os.environ[name] = os.path.join(TMP, tail)
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.util import improve  # noqa: E402

UI = open(os.path.join(REPO, "webui", "index.html"), encoding="utf-8").read()
API = open(os.path.join(REPO, "src", "longrun", "core", "api_v02.py"), encoding="utf-8").read()
HTTP = open(os.path.join(REPO, "src", "longrun", "core", "httpapi.py"), encoding="utf-8").read()
ORBIT = open(os.path.join(REPO, "src", "longrun", "orbit", "web", "orbit.html"), encoding="utf-8").read()

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""))


# ---- A. one file, one key ---------------------------------------------------
check("A1 the panel normalises a data-home path before keying it",
      "const _fkey = p => {" in UI and 's.slice(root.length + 1)' in UI)
check("A2 every source goes through the same normaliser",
      UI.count("_fadd(") >= 4 and "_fmap.set(p, f.kind" not in UI)
check("A3 the API emits data-home-relative paths only",
      "_home_root = str(_paths.HOME_DIR).rstrip(\"/\")" in HTTP
      and '_w["path"] = _p[len(_home_root) + 1:]' in HTTP)

# ---- B. nothing bleeds out of its card ---------------------------------------
check("B1 a path link wraps inside its card",
      "a.impfile {" in UI and "overflow-wrap: anywhere" in UI.split("a.impfile {")[1].split("}")[0])
check("B2 the file list is a wrapping row, not a run of inline links",
      "#impFiles { display: flex; flex-wrap: wrap;" in UI)
check("B3 dim text wraps everywhere (paths, model refs, file names)",
      ".remaining { color: var(--dim); font-size: 11px; overflow-wrap: anywhere; }" in UI)
check("B4 the Control deck job pill is capped with an ellipsis",
      "max-width:240px;overflow:hidden;text-overflow:ellipsis" in ORBIT)

# ---- C. decided proposals can be deleted ------------------------------------
check("C1 improve.clear_decided() exists and keeps pending ones",
      "def clear_decided():" in open(os.path.join(REPO, "src", "longrun", "util", "improve.py"),
                                     encoding="utf-8").read()
      and 'if rec.get("status") == "pending":' in open(
          os.path.join(REPO, "src", "longrun", "util", "improve.py"), encoding="utf-8").read())
check("C2 the route is wired", 'if path == "/api/improvement":' in API
      and "_improve.clear_decided()" in API)
check("C3 the panel has the control, behind a confirm", "clearDecidedProposals" in UI
      and 'api("DELETE", "/api/improvement")' in UI
      and "delete the decided proposals?" in UI)

_pend = improve.propose("project", "v651 pending — must SURVIVE the clear")
_gone = improve.propose("project", "v651 decided — must BE GONE after the clear")
improve.decide(_gone["id"], "deny")
res = improve.clear_decided()
left = improve.list_proposals()
check("C4 the clear deletes the decided one and keeps the pending one",
      res.get("removed") == 1 and [p["id"] for p in left] == [_pend["id"]], (res, left))

# ---- D. active means active --------------------------------------------------
check("D1 the counter excludes finished runs",
      'const activeRuns = runs.filter(r => !_isDone(r));' in UI
      and '(tools.length + activeRuns.length) + " active"' in UI)
check("D2 finished runs are shown apart, with their own delete",
      '>finished (' in UI and 'api("DELETE", "/api/agent/runs")' in UI)
check("D2b both exits live outside the collapsed body",
      # operator: "non si annulla mai, rimarrà per sempre così?" — an exit the
      # operator has to expand a nested panel to find is the same dead end, and a
      # button inside <summary> is an a11y violation Chrome flags.
      'hd.appendChild(clr); decBox.appendChild(hd);' in UI
      and 'hd.appendChild(clr); box.appendChild(hd);' in UI
      and 'querySelector("summary").appendChild' not in UI)
check("D2c decided history is its own top-level card",
      # nested in the pending card it was invisible while collapsed, exit included
      '<div id="impDecided"></div>' in UI
      and 'const decBox = $("impDecided");' in UI
      and "det.appendChild(box); decBox.appendChild(det);" in UI)
check("D3 the backend drops only terminal runs", 'if path == "/api/agent/runs":' in API
      and 'in ("done", "aborted", "error")' in API)
check("D4 the delete never touches an active run",
      'RUNS.pop(rid, None)' in API
      and re.search(r'_victims = \[rid for rid, st in RUNS\.items\(\)\s*\n\s*if str\(getattr\(st, "status", ""\)\)', API) is not None)

# ---- E. one store, one control ----------------------------------------------
check("E1 the duplicate reset button is gone",
      "resetRunGraph" not in UI and 'data-call="resetPlan"' in UI)

# ---- F. a label says what the button does -----------------------------------
check("F1 the files button is not labelled 'sources'",
      'data-call="kbFiles" title="list the indexed FILES' in UI
      and 'data-call="kbFiles" title="which sources' not in UI)

print("---")
passed = sum(results)
print("\nv651: %d/%d PASS" % (passed, len(results)))
sys.exit(0 if passed == len(results) else 1)
