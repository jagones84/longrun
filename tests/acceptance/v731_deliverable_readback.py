#!/usr/bin/env python3
"""v731 — the harness READS BACK the artifacts a turn wrote before it closes.

Found 2026-10-30 on JobBench `online_merchants/task1`: Longrun delivered both
files in 54 s and scored 6/58, while Harness² — whose loop keeps re-reading its
own output for 50-100 steps — scored 48/58. The judge's failures were things the
harness could have SHOWN it: "Sheet 3 has no visualization", "the catalog
averages are not quoted". A status-only done-gate (`_finish_gated`) cannot see a
blank sheet; a mechanical read-back can.

  A  the inventory describes what the turn WROTE (sheets, ranges, charts, columns)
  B  inputs, source files and older files are never reported as deliverables
  C  the read-back is a CHECKLIST with the request in front of the model
  D  the gate fires ONCE per turn, and not at all when nothing was written
  E  it is wired into every place a final answer is accepted

Deterministic and offline: a temporary workspace, no model, no network.
"""
import os
import sys
import tempfile
import time

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="longrun-v731-")
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.plan import artifacts as A  # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name
          + ((" :: " + str(detail)[:400]) if detail and not ok else ""))


WS = os.path.join(TMP, "ws")
OUT = os.path.join(WS, "output")
os.makedirs(OUT, exist_ok=True)
os.makedirs(os.path.join(WS, "task_folder"), exist_ok=True)

# an input staged BEFORE the turn (must never be reported)
with open(os.path.join(WS, "task_folder", "input.csv"), "w", encoding="utf-8") as f:
    f.write("a,b\n1,2\n")
_old = time.time() - 3600
os.utime(os.path.join(WS, "task_folder", "input.csv"), (_old, _old))

SINCE = time.time() - 1

# what the turn wrote: a workbook with a chart on its second sheet
from openpyxl import Workbook  # noqa: E402
from openpyxl.chart import BarChart, Reference  # noqa: E402

wb = Workbook()
data = wb.active
data.title = "Data"
for row in (("sku", "returns"), ("SKU-007", 8.2), ("SKU-016", 7.1)):
    data.append(row)
viz = wb.create_sheet("Viz")
viz.append(("sku", "returns"))
viz.append(("SKU-007", 8.2))
chart = BarChart()
chart.add_data(Reference(viz, min_col=2, min_row=1, max_row=2), titles_from_data=True)
viz.add_chart(chart, "D2")
wb.save(os.path.join(OUT, "report.xlsx"))

with open(os.path.join(OUT, "table.csv"), "w", encoding="utf-8") as f:
    f.write("inquiry,verdict\nINQ-001,isolated\nINQ-003,systemic\n")
with open(os.path.join(OUT, "notes.md"), "w", encoding="utf-8") as f:
    f.write("# notes\nthree findings\n")
with open(os.path.join(OUT, "helper.py"), "w", encoding="utf-8") as f:
    f.write("print('not a deliverable')\n")
with open(os.path.join(OUT, "empty.txt"), "w", encoding="utf-8") as f:
    f.write("")

# A ----------------------------------------------------------------------
inv = {e["path"]: e for e in A.inventory(WS, since=SINCE)}
check("A1 the workbook the turn wrote is inventoried",
      "output/report.xlsx" in inv, sorted(inv))
xf = (inv.get("output/report.xlsx") or {}).get("facts") or {}
check("A2 its sheets are named with their used range",
      [s["name"] for s in xf.get("sheets", [])] == ["Data", "Viz"]
      and xf["sheets"][0]["rows"] == 3 and xf["sheets"][0]["cols"] == 2, xf)
check("A3 a chart is COUNTED (the fact a status gate cannot see)",
      xf.get("charts") == 1, xf)
check("A4 a csv is described by header and row count",
      (inv.get("output/table.csv") or {}).get("facts", {}).get("columns") ==
      ["inquiry", "verdict"]
      and (inv.get("output/table.csv") or {}).get("facts", {}).get("rows") == 2,
      (inv.get("output/table.csv") or {}).get("facts"))
check("A5 an empty artifact is reported as EMPTY",
      "EMPTY" in A._line(inv["output/empty.txt"]), A._line(inv["output/empty.txt"]))

# B ----------------------------------------------------------------------
check("B1 the staged INPUT is not a deliverable of this turn",
      "task_folder/input.csv" not in inv and not any(
          e["path"].startswith("task_folder") for e in inv.values()), sorted(inv))
check("B2 source code is not audited as an artifact",
      "output/helper.py" not in inv, sorted(inv))
_state = os.path.join(WS, "state_dir")
os.makedirs(_state, exist_ok=True)
with open(os.path.join(_state, "harness_note.md"), "w", encoding="utf-8") as f:
    f.write("a note the HARNESS wrote about the turn\n")
check("A6 the harness's own state inside the workspace is never an artifact",
      "state_dir/harness_note.md" in {e["path"] for e in A.inventory(WS, since=SINCE)}
      and "state_dir/harness_note.md" not in {
          e["path"] for e in A.inventory(WS, since=SINCE, exclude=[_state])},
      "exclude=")
_before = A.inventory(WS, since=time.time() + 60)
check("B3 files older than the turn are excluded", _before == [], _before)

# C ----------------------------------------------------------------------
text = A.review(WS, "produce a workbook with a chart and a supplier notice",
                since=SINCE) or ""
check("C1 the read-back names each artifact with its facts",
      "READ-BACK" in text and "output/report.xlsx" in text and "charts=1" in text, text[:300])
check("C2 it forwards the request so the model can check coverage",
      "produce a workbook with a chart" in text, text[-300:])
check("C3 it is a checklist, not a grade (no score, an instruction to fix)",
      "NOT delivered" in text and "fix the artifact now" in text, text[-300:])
check("C4 nothing written → no read-back at all", A.review(TMP + "/nowhere", "", since=0) is None
      and A.review(os.path.join(TMP, "empty-dir"), "", since=0) is None)

# D ----------------------------------------------------------------------
_state = {"left": 1}
_first = A.review(WS, "x", since=SINCE)
check("D1 a written turn produces exactly one read-back", bool(_first) is True)


def _gate(state, ws=WS, since=SINCE):
    """The same once-per-turn rule the agent applies, without a live session."""
    if int(state.get("left") or 0) <= 0:
        return None
    t = A.review(ws, "x", since=since)
    if not t:
        state["left"] = 0
        return None
    state["left"] -= 1
    return t


check("D2 the gate consumes its budget: the second call is silent", _gate(_state) and _gate(_state) is None)
check("D3 an empty turn burns the budget instead of retrying",
      _gate({"left": 1}, ws=os.path.join(TMP, "empty-dir")) is None)

# E ----------------------------------------------------------------------
SRC = open(os.path.join(REPO, "src", "longrun", "agent", "agent.py"), encoding="utf-8").read()
check("E1 every floor that accepts a final answer runs the read-back first",
      SRC.count("_drv = _deliverable_review_text(") >= 4, SRC.count("_drv = _deliverable_review_text("))
check("E2 it is resolved on the session's OWN workspace",
      "_chat_workspace(sess)" in SRC.split("def _deliverable_review_text")[1][:1400],
      "workspace resolver")
check("E3 the audit can never break a turn (guarded import + except)",
      "except Exception:  # noqa: BLE001" in SRC.split("def _deliverable_review_text")[1][:1400])
check("E4 it is fed as a harness turn the operator can see",
      SRC.count('_inject(_drv, "review")') >= 4, SRC.count('_inject(_drv, "review")'))

print("\n---")
print("v731: %d/%d PASS" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
