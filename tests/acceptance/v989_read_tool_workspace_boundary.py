#!/usr/bin/env python3
"""v989 — a path-reading tool outside the boundary list still escalates.

`touches_outside` (JAG-388) is the ONE rule that makes any action reaching a path
outside the session workspace `required`, whatever the per-tool policy says. It
knew `fs.*`, `git` and `shell` only. `grep.search` (reads file CONTENTS) and
`glob.list` (lists files) are `approval: auto` and name a path too, so on a path
outside the workspace they ran with NO card while `fs.read` on the same path
asked — measured 2026-11-14: `fs.read` -> required, `grep.search`/`glob.list`
-> auto, in the same classify call.

Contract:
  A) the boundary reports the outside path for both tools;
  B) `classify` then answers `required` (normal approvals mode);
  C) the tool's own roots are untouched: an INSIDE path stays auto;
  D) no path, no invented boundary.

Deterministic: no server, no model, no shell execution.
Run: python3 tests/acceptance/v989_read_tool_workspace_boundary.py
"""
import os
import shutil
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="v989_")
for _k in ("CONFIG_DIR", "SESSIONS_DIR", "EDITS_DIR", "RUNS_DIR", "GRAPH_DIR", "ROLES_DIR",
           "DATA_DIR"):
    os.environ["LONGRUN_" + _k] = os.path.join(TMP, _k.lower())
    os.makedirs(os.environ["LONGRUN_" + _k], exist_ok=True)
os.environ["LONGRUN_DB"] = os.path.join(TMP, "events.db")
# The boundary treats /tmp as a SYSTEM root, so the fixture lives under .agent/
# or every case would read as "inside" for the wrong reason (v984's trap).
_FIX = os.path.join(REPO, ".agent", "trash", "v989_fixture")
shutil.rmtree(_FIX, ignore_errors=True)
WS = os.path.join(_FIX, "workspace")
OUT = os.path.join(_FIX, "outside")
os.makedirs(WS, exist_ok=True)
os.makedirs(OUT, exist_ok=True)
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.tools import registry as R  # noqa: E402

RESULTS = []


def check(name, ok, detail=""):
    RESULTS.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""))


def decision(tool, args):
    return R.classify(tool, args, workspace=WS)


# ---- A: the boundary sees the path ---------------------------------------
for tool, args in (("grep.search", {"path": OUT, "pattern": "SECRET"}),
                   ("glob.list", {"root": OUT, "pattern": "*.txt"})):
    why = R.touches_outside(tool, args, WS)
    check("A %s outside the workspace is reported" % tool, bool(why), why)
    check("A %s reason names the resolved path" % tool, bool(why) and OUT in str(why), why)

# ---- B: classify answers required (normal mode, no live overlay) ---------
# `glob.list` is a BUILT-IN schema; `grep.search` lives in the Matrix zone, which
# the battery points at an empty temp dir (`LONGRUN_MATRIX_SRC`), so its spec is
# absent here and `classify` would answer "unknown tool" for an unrelated reason.
# The branch that maps its `path` is proven by A (same `touches_outside` call).
_d, _r = decision("glob.list", {"root": OUT, "pattern": "*.txt"})
check("B glob.list needs a card outside the workspace", _d == "required", (_d, _r))
_d, _r = decision("fs.read", {"path": os.path.join(OUT, "a.txt")})
check("B fs.read is the reference behaviour", _d == "required", (_d, _r))

# ---- C: inside the workspace nothing changed -----------------------------
for tool, args in (("glob.list", {"root": WS, "pattern": "*.py"}),
                   ("fs.read", {"path": os.path.join(WS, "a.txt")})):
    _d, _r = decision(tool, args)
    check("C %s inside the workspace stays auto" % tool, _d == "auto", (_d, _r))
_d, _r = decision("grep.search", {"path": WS, "pattern": "x"})
check("C grep.search has no boundary reason inside the workspace",
      _d != "required" or "outside" not in str(_r), (_d, _r))

# ---- D: no path, no invented boundary ------------------------------------
for tool, args in (("grep.search", {"pattern": "x"}), ("glob.list", {"pattern": "*.py"})):
    check("D %s without a path has no boundary reason" % tool,
          R.touches_outside(tool, args, WS) is None, R.touches_outside(tool, args, WS))

ok = sum(RESULTS)
print("\nv989: %d/%d PASS" % (ok, len(RESULTS)))
shutil.rmtree(_FIX, ignore_errors=True)
sys.exit(0 if ok == len(RESULTS) else 1)
