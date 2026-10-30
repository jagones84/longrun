#!/usr/bin/env python3
"""v739 — a workbook opens as a TABLE in the editor, not "binary file".

Operator: *"perché nell'editor non posso vedere file xlsx? fix please."* He is
right and the cause is not a bug in the reader: an `.xlsx` is a zip of XML, so
`/api/fs/read` correctly reports `binary: true`, the dock had no viewer for it and
printed "binary file — no preview (12 KB)". The data the operator OWNS was the one
thing the panel refused to show.

  A  `GET /api/fs/sheet` returns one sheet as text cells + the sheet names, with
     a hard cap (SHEET_MAX_ROWS/COLS) and a `truncated` flag, `data_only` so a
     formula arrives as its value, and an explicit error (never a 500) for a
     missing dependency, a corrupt file, or a legacy `.xls`.
  B  cell formatting is a display contract: `None` is empty, a date is ISO, a
     float is not `1.0e+21`, and NaN/inf never print as text.
  C  the dock routes `.xlsx/.xlsm` to the sheet viewer (a grid with one tab per
     worksheet), never to the binary fallback — and the server route exists.

Deterministic: temp dirs, a workbook written here with openpyxl, no server.
Run: python3 tests/acceptance/v739_editor_sheet_preview.py
"""
import os
import sys
import tempfile

TMP = tempfile.mkdtemp(prefix="sf-v739-")
for _k in ("CONFIG_DIR", "SESSIONS_DIR", "EDITS_DIR", "RUNS_DIR", "GRAPH_DIR", "ROLES_DIR"):
    os.environ["LONGRUN_" + _k] = os.path.join(TMP, _k)
    os.makedirs(os.path.join(TMP, _k), exist_ok=True)
os.environ["LONGRUN_DB"] = os.path.join(TMP, "events.db")
# the fs endpoints only touch paths under the browse roots (`~` by default), and
# this test's workbook lives in a temp dir: declare it as the root, like a
# workspace would be.
os.environ["LONGRUN_BROWSE_ROOTS"] = TMP

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.core import api_v02 as API  # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""))


def _read(*parts):
    with open(os.path.join(REPO, *parts), encoding="utf-8") as f:
        return f.read()


# ---------------- A: the route reads a real workbook ----------------------
WB = os.path.join(TMP, "book.xlsx")
try:
    from openpyxl import Workbook
    wb = Workbook()
    ws = wb.active
    ws.title = "Q1 Cash"
    ws.append(["Account", "Debit", "Credit"])
    ws.append(["1000 Cash", 95000, 0])
    ws.append(["4000 Revenue", 0, 12345.5])
    ws2 = wb.create_sheet("Notes")
    ws2.append(["memo"])
    ws2.append(["reconciled by hand"])
    wb.save(WB)
    HAVE_OPENPYXL = True
except Exception as e:  # noqa: BLE001
    HAVE_OPENPYXL = False
    print("skip A/B: openpyxl unavailable (%s)" % e)

if HAVE_OPENPYXL:
    d = API.fs_sheet({"path": WB})
    check("A1 the sheet is returned as text cells (no binary, no preview-less blob)",
          not d.get("error") and d.get("sheet") == "Q1 Cash"
          and len(d.get("rows") or []) == 3, d.get("error") or d.get("sheet"))
    check("A2 every worksheet is named, so the dock can offer tabs",
          d.get("sheets") == ["Q1 Cash", "Notes"], d.get("sheets"))
    check("A3 numbers arrive as display text, a date would be ISO, None is empty",
          d["rows"][1][1] == "95000" and d["rows"][2][2] == "12345.5"
          and d["rows"][0][0] == "Account", d["rows"][:3])
    d2 = API.fs_sheet({"path": WB, "sheet": "Notes"})
    check("A4 a named sheet is honoured", d2.get("sheet") == "Notes"
          and d2["rows"][1][0] == "reconciled by hand", d2.get("rows"))
    d3 = API.fs_sheet({"path": WB, "sheet": "does-not-exist"})
    check("A5 an unknown sheet falls back to the first one, never an error",
          not d3.get("error") and d3.get("sheet") == "Q1 Cash")
    check("A6 the cut is bounded and says so",
          API.SHEET_MAX_ROWS <= 1000 and API.SHEET_MAX_COLS <= 200
          and d.get("truncated") is False and d.get("max_rows") == API.SHEET_MAX_ROWS)
    check("A9 rows are trimmed to their real width (openpyxl pads to the widest column)",
          max(len(r) for r in d["rows"]) == 3, [len(r) for r in d["rows"]])
    txt = os.path.join(TMP, "note.txt")
    open(txt, "w", encoding="utf-8").write("hello")
    check("A7 a non-workbook is refused with a readable reason",
          "not a workbook" in str(API.fs_sheet({"path": txt}).get("error")))
    bad = os.path.join(TMP, "broken.xlsx")
    open(bad, "wb").write(b"not a zip at all")
    r = API.fs_sheet({"path": bad})
    check("A8 a corrupt workbook returns an error instead of raising",
          isinstance(r, dict) and bool(r.get("error")), r.get("error"))

# ---------------- B: the cell display contract ----------------------
import datetime as _dt  # noqa: E402
check("B1 None is empty and a date is ISO (never a Python repr)",
      API._sheet_cell(None) == ""
      and API._sheet_cell(_dt.date(2024, 3, 31)) == "2024-03-31"
      and API._sheet_cell(_dt.datetime(2024, 3, 31, 9, 30)) == "2024-03-31T09:30:00")
check("B2 a float is short and NaN/inf print as nothing",
      API._sheet_cell(12345.5) == "12345.5"
      and API._sheet_cell(0.1 + 0.2) == "0.3"
      and API._sheet_cell(float("nan")) == ""
      and API._sheet_cell(float("inf")) == "")

# ---------------- C: the dock routes to the grid ----------------------
UI = _read("webui", "assets", "editor.js")
HTML = _read("webui", "index.html")
API_SRC = _read("src", "longrun", "core", "api_v02.py")
check("C1 .xlsx/.xlsm get their own viewer, not the code/binary fallback",
      'if (e === "xlsx" || e === "xlsm") return "sheet";' in UI)
check("C2 renderActive draws the grid (and keeps the binary fallback for the rest)",
      't.viewer === "sheet"' in UI and "renderSheet(t)" in UI
      and "binary file — no preview" in UI)
check("C3 the grid asks the server, one sheet at a time, and caches per tab",
      '"/api/fs/sheet?path="' in UI and '&sheet=' in UI and "t._sheet" in UI)
check("C4 the route is registered and the handler is exported",
      'path == "/api/fs/sheet"' in API_SRC and "def fs_sheet(" in API_SRC)
check("C5 the grid has its own styling (sticky headers, tab per sheet)",
      ".xsheet table" in HTML and ".xsheet-tab" in HTML and ".xsheet-wrap" in HTML)

print("---")
ok = sum(results)
print("\nv739: %d/%d PASS" % (ok, len(results)))
sys.exit(0 if ok == len(results) else 1)
