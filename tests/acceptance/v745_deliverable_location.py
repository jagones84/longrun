#!/usr/bin/env python3
"""v745 — a deliverable must land WHERE the request said, and the read-back must say so.

Measured 2026-10-31 (JobBench dispatch, session `656a2e7559fd`): 12 minutes of work, the
deliverable at the workspace root, the `output/` the prompt named left EMPTY, the last
shell call failed, and NOTHING in the harness mentioned it — the grader found no file
and scored 0/94. The rule is generic: if the request names a destination, the work must
be there, and a file elsewhere is a delivery failure, not a formatting detail.

Contract locked here:
  * `artifacts.target_dir()` finds the directory the request names (only if it exists);
  * `_location_gaps()` reports an empty destination and files written outside it;
  * `review()` prints it with the ACTION (move them, re-check);
  * `gaps()` counts it, so an incomplete delivery earns the extra read-back cycle;
  * a script helper at the root is NOT a deliverable (no noise), and neither is an
    input the turn was GIVEN;
  * no location in the request, or a directory that does not exist → silence;
  * it never raises.

Run: python3 v745_deliverable_location.py
"""
import os
import shutil
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
#: The turn's start. Staged inputs are backdated an hour so the mtime rule — the same
#: one production uses — separates "given to the turn" from "written by it".
SINCE = time.time() - 60.0


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

from longrun.plan import artifacts as A  # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + detail) if detail else ""))


def ws(*files):
    """A workspace with `output/` and `task_folder/`, plus the files asked for.

    Everything under `task_folder/` is BACKDATED: those are the inputs the turn was
    given, and `inventory(since=...)` must not report them as something it wrote.
    """
    d = tempfile.mkdtemp(prefix="sf-v745-")
    os.makedirs(os.path.join(d, "output"), exist_ok=True)
    os.makedirs(os.path.join(d, "task_folder"), exist_ok=True)
    staged = os.path.join(d, "task_folder", "data.csv")
    with open(staged, "w", encoding="utf-8") as f:
        f.write("id,amount\nA1,10\nA2,20\n")
    os.utime(staged, (SINCE - 3600, SINCE - 3600))
    for rel, body in files:
        path = os.path.join(d, rel)
        if os.path.dirname(rel):
            os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(body)
    return d


def gaps_of(workspace, request=None):
    return A._location_gaps(workspace, ASK if request is None else request,
                            A.inventory(workspace, since=SINCE))


ASK = "Analyse the data and save every deliverable in the output/ directory."

# ---- A: the destination is named ------------------------------------------
d1 = ws(("summary.csv", "id,total\nA1,10\nA2,20\n"),
        ("report.md", "# report\n" + "text " * 40 + "\n"))
check("A1 target_dir finds the directory the request names",
      A.target_dir(d1, ASK) == "output", repr(A.target_dir(d1, ASK)))
_g = gaps_of(d1)
check("A2 an empty destination is reported as a gap", bool(_g), repr(_g))
check("A3 the empty destination is named in words",
      any("holds NO new file" in x for x in _g), repr(_g))
check("A4 the files written outside are named",
      any("summary.csv" in x for x in _g), repr(_g))
check("A5 the wording tells the model what to do",
      any("move them" in x and "re-check" in x for x in _g), repr(_g))
check("A6 the input the turn was GIVEN is not called a stray",
      not any("data.csv" in x for x in _g), repr(_g))

_rv = A.review(d1, ASK, since=SINCE)
check("A7 review() carries the location line",
      _rv is not None and "holds NO new file" in _rv, (_rv or "")[:80])
check("A8 it is a mechanical gap, so it buys one more cycle",
      bool(A.gaps(d1, ASK, since=SINCE)), repr(A.gaps(d1, ASK, since=SINCE)))

# ---- B: correct delivery is silent ---------------------------------------
d2 = ws(("output/summary.csv", "id,total\nA1,10\n"),
        ("output/report.md", "# report\n" + "text " * 40 + "\n"))
check("B1 a file inside the destination is not a gap", gaps_of(d2) == [], repr(gaps_of(d2)))

# ---- C: a script at the root is a tool, not a deliverable ----------------
d3 = ws(("output/summary.csv", "id,total\nA1,10\n"),
        ("build.py", "print('hi')\n"))
check("C1 a .py helper outside the destination is not flagged",
      gaps_of(d3) == [], repr(gaps_of(d3)))

# ---- D: silence when there is nothing to compare -------------------------
d4 = ws(("summary.csv", "id,total\nA1,10\n"))
check("D1 a request that names no destination is silent",
      A.target_dir(d4, "Analyse the data and produce a report.") == ""
      and gaps_of(d4, "Analyse the data and produce a report.") == [])
check("D2 a destination that does not exist on disk is silent",
      A.target_dir(d4, "Save the report in the deliveries/ folder.") == ""
      and gaps_of(d4, "Save the report in the deliveries/ folder.") == [])
check("D3 a date-like token is not mistaken for a directory",
      A.target_dir(d4, "Save the reconciliation for 01/10/2024 in the output/ folder.")
      == "output",
      repr(A.target_dir(d4, "Save the reconciliation for 01/10/2024 in the output/ folder.")))
check("D4 no request at all is silent",
      gaps_of(d4, "") == [] and A.target_dir(d4, "") == "")

# ---- E: it never raises --------------------------------------------------
try:
    _ok = True
    A._location_gaps("/nonexistent/deep/path", ASK, [])
    A.target_dir("/nonexistent/deep/path", ASK)
    A.review("/nonexistent/deep/path", ASK, since=SINCE)
    A.gaps("/nonexistent/deep/path", ASK, since=SINCE)
except Exception as exc:  # noqa: BLE001
    _ok = False
    print("   raised:", exc)
check("E1 never raises, whatever the workspace", _ok)

# ---- F: nested destination -----------------------------------------------
d5 = ws(("output/q1/summary.csv", "id,total\nA1,10\n"))
check("F1 a nested file under the destination counts as inside",
      gaps_of(d5) == [], repr(gaps_of(d5)))

for d in (d1, d2, d3, d4, d5):
    shutil.rmtree(d, ignore_errors=True)

print("\n%d/%d checks passed" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
