#!/usr/bin/env python3
"""v1149 — the read-back runs the workspace's own check (round 84, R-1 / AdaPRA).

The closing gate DESCRIBED the files a turn wrote and never RAN anything, so "the
tests pass" was the model's word. AdaPRA (arXiv 2610.33245) audits a workspace by
executing checks; the recorded local gap was R-1. The check now runs once per turn
through the SAME policy gate as an agent call, and its exit status plus output tail
are injected into the read-back.

Contract:
  A detection is narrow: `check.py`, or `tests/test_*.py` — nothing else
  B the check runs only when `registry.classify` answers `auto`
  C the injected text states exit status, duration and the tail; a policy refusal is
    reported as NOT RUN (never as passed)
  D `agent._deliverable_review_text` carries the check into the read-back, once per
    turn, and still fires when the model had already reopened its own artifact
  E a turn that wrote nothing runs nothing

Deterministic: temp workspaces, local subprocess only, no model, no network.
Run: python3 tests/acceptance/v1149_readback_runs_the_check.py
"""
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="sf-v1149-")
os.environ["LONGRUN_CONFIG_DIR"] = os.path.join(TMP, "cfg")
os.environ["LONGRUN_DATA_DIR"] = os.path.join(TMP, "data")
os.environ["LONGRUN_DB"] = os.path.join(TMP, "events.db")
for _d in ("cfg", "data"):
    os.makedirs(os.path.join(TMP, _d), exist_ok=True)
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.core import server                 # noqa: E402,F401 — breaks the import cycle
from longrun.harness import workspace_check as WC  # noqa: E402

RESULTS = []


def check(name, ok, detail=""):
    RESULTS.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name
          + ((" :: " + str(detail)[:300]) if detail and not ok else ""))


# The gate answers from the POLICY. `full` is the live configuration, so the overlay
# below puts this throwaway data home in that mode (the same file `POST /api/tools`
# writes); the `required` path is exercised separately by stubbing `classify` (B4).
open(os.path.join(TMP, "data", "tools.overlay.yaml"), "w", encoding="utf-8").write(
    "approvals:\n  mode: full\ntools:\n  shell.exec:\n    approval: auto\n")
from longrun.tools import registry as _reg      # noqa: E402
_reg.load_config(reload=True)                   # the overlay above is the policy under test


def mkws(name, files):
    ws = os.path.join(TMP, name)
    os.makedirs(ws, exist_ok=True)
    for rel, body in files.items():
        p = os.path.join(ws, rel)
        os.makedirs(os.path.dirname(p), exist_ok=True) if os.path.dirname(p) else None
        open(p, "w", encoding="utf-8").write(body)
    return ws


# ---- A) detection -----------------------------------------------------------
ws_check = mkws("ws_check", {"check.py": "print('ok')\n"})
check("A1 a workspace check.py is detected", WC.detect(ws_check) == "python3 check.py",
      WC.detect(ws_check))
ws_tests = mkws("ws_tests", {"tests/test_one.py": "def test_x():\n    assert True\n"})
check("A2 a tests/ directory of test_*.py is detected",
      WC.detect(ws_tests) == "python3 -m pytest -q tests", WC.detect(ws_tests))
ws_empty = mkws("ws_empty", {"notes.md": "x\n"})
check("A3 a workspace with neither is not a check", WC.detect(ws_empty) is None,
      WC.detect(ws_empty))
ws_notest = mkws("ws_notest", {"tests/helper.py": "x=1\n"})
check("A4 tests/ without test_*.py is not a check", WC.detect(ws_notest) is None,
      WC.detect(ws_notest))
check("A5 a missing directory is not a check", WC.detect(os.path.join(TMP, "nope")) is None)


# ---- B/C) a failing check, then the text ------------------------------------
ws_fail = mkws("ws_fail", {"check.py": "print('AssertionError: boom')\nraise SystemExit(1)\n"})
r = WC.run(ws_fail)
check("B1 it runs under an `auto` policy", r and r.get("ran") is True
      and r.get("decision") == "auto", r)
check("B2 the exit code is reported", r.get("exit_code") == 1, r.get("exit_code"))
check("B3 the tail carries the failure", any("boom" in ln for ln in r.get("tail") or []),
      r.get("tail"))
t = WC.text(r)
check("C1 the text names the command, the exit and FAILED",
      "WORKSPACE CHECK" in t and "exit 1 — FAILED" in t, t)
check("C2 the text carries the output tail", "boom" in t, t)
check("C3 the text asks for a fix or an explicit exception", "disagrees with the delivery" in t, t)

ws_ok = mkws("ws_ok", {"check.py": "print('all good')\n"})
t_ok = WC.text(WC.run(ws_ok))
check("C4 a passing check says passed", "exit 0 — passed" in t_ok, t_ok)
check("C5 a passing check does not ask for a fix", "disagrees" not in t_ok, t_ok)


# ---- B2) the gate is an actual gate ----------------------------------------
import longrun.tools.registry as R               # noqa: E402
import longrun.tools.tools as TOOLS              # noqa: E402

_orig_cls = R.classify
_calls = {"exec": 0}
_orig_exec = TOOLS.execute


def _exec(*a, **k):
    _calls["exec"] += 1
    return _orig_exec(*a, **k)


R.classify = lambda *a, **k: ("required", "needs a human")
TOOLS.execute = _exec
try:
    r2 = WC.run(ws_fail)
finally:
    R.classify = _orig_cls
    TOOLS.execute = _orig_exec
check("B4 a `required` decision does NOT run the check", r2 and r2.get("ran") is False
      and _calls["exec"] == 0, (r2, _calls))
check("B5 the refusal is reported as NOT RUN, never as passed",
      "NOT RUN" in WC.text(r2) and "— passed" not in WC.text(r2), WC.text(r2))


# ---- D/E) the read-back carries it -----------------------------------------
from longrun.agent import agent as A             # noqa: E402

ws_turn = mkws("ws_turn", {"check.py": "print('AssertionError: turn')\nraise SystemExit(1)\n"})
open(os.path.join(ws_turn, "report.md"), "w", encoding="utf-8").write(
    "# Report\n\n" + ("body line\n" * 40))
_sess = {"id": "v1149-sess", "workspace": ws_turn}

_orig_run = WC.run
_cnt = {"n": 0}


def _counting(*a, **k):
    _cnt["n"] += 1
    return _orig_run(*a, **k)


WC.run = _counting
try:
    st = {"left": 2, "paths": [os.path.join(ws_turn, "report.md")], "opaque": False,
          "own_verified": False}
    txt = A._deliverable_review_text(_sess, "write the report", 0.0, st)
    check("D1 the read-back carries the workspace check",
          bool(txt) and "WORKSPACE CHECK" in txt, (txt or "")[:200])
    check("D2 the artifact read-back is still there",
          "READ-BACK of what you WROTE" in txt, (txt or "")[:200])
    st2 = {"left": 2, "paths": [], "opaque": False, "own_verified": False}
    A._deliverable_review_text(_sess, "anything", 0.0, st2)
    check("D3 the check runs at most once per turn", _cnt["n"] == 1, _cnt)
    # A turn whose model already reopened its own artifact still sees a failing check.
    st3 = {"left": 2, "paths": [os.path.join(ws_turn, "report.md")], "opaque": False,
           "own_verified": True}
    txt3 = A._deliverable_review_text(_sess, "write the report", 0.0, st3)
    check("D4 a failing check still fires under own_verified",
          bool(txt3) and "WORKSPACE CHECK" in txt3, (txt3 or "")[:200])
finally:
    WC.run = _orig_run

ws_silent = mkws("ws_silent", {"check.py": "print('x')\n"})
_sess2 = {"id": "v1149-silent", "workspace": ws_silent}
st4 = {"left": 2, "paths": [], "opaque": False, "own_verified": False}
check("E1 a turn that wrote nothing runs no check",
      A._deliverable_review_text(_sess2, "say hi", 0.0, st4) is None
      and not st4.get("ws_check_done"), st4)

print("---")
_passed = sum(RESULTS)
print("%d/%d PASS" % (_passed, len(RESULTS)))
sys.exit(0 if _passed == len(RESULTS) else 1)
