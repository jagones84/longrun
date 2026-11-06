#!/usr/bin/env python3
"""v833 — the read-back must never say "you wrote NO file" while one is on disk.

Measured 2026-11-06 on LHB `01_delivery_report` (session `db9b508142b7`, glm-5.3-flash):
the arm produced `out/report.json` with a shell call, the read-back only looked at
DOCUMENT extensions (`.xlsx`, `.csv`, `.md`, ...), found nothing, and told the model
"you have written NO file for this request". The model then spent four rounds
defending itself, stored a false memory entry and had to retract it.

The harness may be blind, but it may not be WRONG. Contract pinned here:
  * `artifacts.WRITTEN_EXTS` covers the machine deliverables (json/jsonl/yaml/xml/sql/
    tsv/py/sh/ipynb) in addition to the documents;
  * `review()` sees a fresh `.json` (the read-back is produced, not skipped);
  * `nothing_written(..., workspace=...)` returns None when ANY fresh file exists;
  * `inventory()` keeps its DOC-ONLY default, so `inputs()` still never calls a repo's
    `.py` an input;
  * `gaps()` sees a machine deliverable too (an empty `.json` is a fact, not silence).

Run: python3 v833_readback_truth.py
"""
import os
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))


def _repo(start):
    p = start
    while True:
        if os.path.isdir(os.path.join(p, "src", "longrun")):
            return p
        parent = os.path.dirname(p)
        if parent == p:
            raise SystemExit("repository root not found from %s" % start)
        p = parent


REPO = _repo(HERE)
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.plan import artifacts  # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + detail) if detail else ""))


# ---- A: the audited set ------------------------------------------------
EXT = artifacts.WRITTEN_EXTS
check("A1 documents are still audited",
      all(e in EXT for e in (".csv", ".md", ".xlsx", ".pdf")), repr(EXT[:6]))
check("A2 machine deliverables are audited",
      all(e in EXT for e in (".json", ".jsonl", ".yaml", ".xml", ".sql", ".tsv")),
      repr(EXT))
check("A3 code deliverables are audited",
      all(e in EXT for e in (".py", ".sh", ".ipynb")), repr(EXT))
check("A4 the document-only default is unchanged for inventory()",
      artifacts.DELIVERABLE_EXTS == (".xlsx", ".xlsm", ".csv", ".pdf", ".docx",
                                     ".pptx", ".md", ".txt", ".html", ".htm"),
      repr(artifacts.DELIVERABLE_EXTS))

# ---- B: a JSON deliverable is SEEN -------------------------------------
tmp = tempfile.mkdtemp(prefix="v833-")
ws = os.path.join(tmp, "ws")
os.makedirs(os.path.join(ws, "out"))
since = time.time() - 1
with open(os.path.join(ws, "out", "report.json"), "w", encoding="utf-8") as f:
    f.write('{"rows": 7}\n')

_entries = artifacts.inventory(ws, since=since)
check("B1 the DOC-only default still ignores a .json (inputs() stays clean)",
      _entries == [], repr(_entries))
_entries = artifacts.inventory(ws, since=since, exts=artifacts.WRITTEN_EXTS)
check("B2 the read-back's set sees it",
      [e["path"] for e in _entries] == [os.path.join("out", "report.json")],
      repr(_entries))
_rev = artifacts.review(ws, "create out/report.json with the totals", since=since)
check("B3 review() produces a read-back instead of skipping the turn",
      bool(_rev) and "READ-BACK of what you WROTE" in _rev, ("" if not _rev else "ok"))
check("B4 the read-back names the JSON file",
      bool(_rev) and "out/report.json" in _rev, ("" if not _rev else "ok"))

# ---- C: the sentence is a fact about disk ------------------------------
_req = "Write a report file to out/report.json"
check("C1 nothing_written stays silent while a fresh file exists",
      artifacts.nothing_written(_req, workspace=ws, since=since) is None)
empty = os.path.join(tmp, "empty")
os.makedirs(empty)
_msg = artifacts.nothing_written(_req, workspace=empty, since=since)
check("C2 it still fires when the workspace really is empty",
      bool(_msg) and "NO file" in _msg, ("" if not _msg else _msg[:60]))
check("C3 a request that names no file never produces the sentence",
      artifacts.nothing_written("explain the numbers", workspace=empty) is None)

# ---- D: gaps() sees a machine deliverable ------------------------------
with open(os.path.join(ws, "out", "empty.json"), "w", encoding="utf-8") as f:
    f.write("")
_g = artifacts.gaps(ws, request=_req, since=since)
check("D1 an empty .json is reported as a gap",
      any("empty.json" in g for g in _g), repr(_g[:3]))

# ---- E: inputs() keeps its own list (a repo's .py is not an INPUT) -----
os.makedirs(os.path.join(ws, "src"))
with open(os.path.join(ws, "src", "mod.py"), "w", encoding="utf-8") as f:
    f.write("x = 1\n")
_old = time.time() - 600
os.utime(os.path.join(ws, "src", "mod.py"), (_old, _old))
check("E1 a .py is not listed as a GIVEN input",
      "src/mod.py" not in artifacts.inputs(ws, since=since),
      repr(artifacts.inputs(ws, since=since)))

print("\n%d/%d checks passed" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
