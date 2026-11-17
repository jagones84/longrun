#!/usr/bin/env python3
"""v1072 — the trace-store deny covers the PYTHON spelling too.

Rounds 2–3 denied the run/transcript/event/held-out store through `fs.*` and
`shell.exec`. `python.run` resolves its own write targets (`matrix_guard.
check_python_write`) but refused only the Nucleous, so `open("data/events.db","w")`
was the remaining spelling of the same boundary — and a prohibited operation is
exactly what an agent decomposes across surfaces (arXiv:2609.30217, stored
S-2026-11-18-018; trace tampering arXiv:2609.30266, S-2026-11-18-015).

Contract:
  P1 `open(<store>, "w")` is DENIED, relative to the repo workspace
  P2 `pathlib.Path(<store>).write_text(...)` is DENIED
  P3 an ABSOLUTE path into the live store is DENIED
  P4 `os.remove`/`shutil.copy` against the store are DENIED
  P5 ordinary workspace writes are NOT denied
  P6 READING the store is not a write and stays allowed
  P7 a non-literal target stays fail-OPEN (documented limit, unchanged)
  P8 the refusal names itself (`STORE_PROTECTED`) and the store

Deterministic: temp dirs, no server, no model, no network.
Run: python3 tests/acceptance/v1072_python_store_deny.py
"""
import os
import shutil
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="sf-v1072-")
os.environ["LONGRUN_DATA_DIR"] = os.path.join(TMP, "data")
os.environ["LONGRUN_SESSIONS_DIR"] = os.path.join(TMP, "data", "sessions")
os.environ["LONGRUN_THREADS_DIR"] = os.path.join(TMP, "data", "threads")
os.environ["LONGRUN_RUNS_DIR"] = os.path.join(TMP, "data", "runs")
os.environ["LONGRUN_HELDOUT_DIR"] = os.path.join(TMP, "data", "heldout")
os.environ["LONGRUN_DB"] = os.path.join(TMP, "data", "events.db")
os.environ["LONGRUN_WORKSPACES_ROOT"] = os.path.join(TMP, "ws")
for d in ("data/sessions", "data/threads", "data/runs", "data/heldout", "ws"):
    os.makedirs(os.path.join(TMP, d), exist_ok=True)
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.tools import matrix_guard  # noqa: E402

RESULTS = []


def check(name, ok, detail=""):
    RESULTS.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name
          + ((" :: " + str(detail)[:300]) if detail and not ok else ""))


WS = os.path.join(TMP, "ws")


def _deny(code, ws=REPO):
    ok, why = matrix_guard.check_python_write(code, workspace=ws)
    return (not ok), why


# ---- P1/P2/P3/P4: every write surface is refused ------------------------------
_ok, _why = _deny('open("data/events.db", "w").write("{}")', ws=TMP)
check("P1 open(events.db, w) is denied", _ok, _why)
check("P1b the refusal names the boundary", "STORE_PROTECTED" in _why, _why)

_ok, _why = _deny('from pathlib import Path\n'
                  'Path("data/runs/r1.json").write_text("{}")', ws=TMP)
check("P2 Path(...).write_text into the run store is denied", _ok, _why)

_abs = os.path.join(os.environ["LONGRUN_SESSIONS_DIR"], "deadbeef.json")
_ok, _why = _deny('open(%r, "w").write("{}")' % _abs, ws=WS)
check("P3 an absolute path into the live session store is denied", _ok, _why)

_ok, _why = _deny('import os\nos.remove("data/events.db")', ws=TMP)
check("P4a os.remove of the event log is denied", _ok, _why)

_ok, _why = _deny('import shutil\nshutil.copy("x", "data/heldout/manifest.json")',
                  ws=TMP)
check("P4b shutil.copy into the sealed heldout store is denied", _ok, _why)

# ---- P5/P6/P7: the guard is a WRITE gate, not a blanket denial ----------------
_ok, _why = _deny('open("out/report.md", "w").write("hi")', ws=WS)
check("P5 an ordinary workspace write is allowed", not _ok, _why)

_ok, _why = _deny('open("data/events.db", "r")', ws=TMP)
check("P6 reading the store is not a write", not _ok, _why)

_ok, _why = _deny('p = "data/events.db"\nopen(p, "w").write("{}")', ws=TMP)
check("P7 a non-literal target stays fail-open (documented limit)", not _ok, _why)

# ---- P8: live wiring — python.run asks this guard -----------------------------
TOOLS = open(os.path.join(REPO, "src", "longrun", "tools", "tools.py"),
             encoding="utf-8").read()
check("P8 python.run still calls the guard",
      "matrix_guard.check_python_write(code, workspace=ws)" in TOOLS)

shutil.rmtree(TMP, ignore_errors=True)
print("\n---\nv1072: %d/%d PASS" % (sum(RESULTS), len(RESULTS)))
raise SystemExit(0 if all(RESULTS) else 1)
