#!/usr/bin/env python3
"""v970 — no SWE arm run on an instance the gold patch cannot pass.

Why: the screen was already in the code (`--verify`) but `--run` did not require it.
Measured 2026-11-12: `pylint-dev__pylint-7080` looked like the ideal hard probe (1 of
14 published submissions resolve it) and cost a 407 s / $0.059 arm run whose result
was 0/40 — the gold patch fails the same tests (`ModuleNotFoundError: py._path`), so
the number described the host venv, not the harness.

Contract:
  A) no `--verify` verdict for the instance  -> `--run` refuses and says how to screen;
  B) verdict present but `gradable: false`   -> `--run` refuses with the gold counts;
  C) verdict present and `gradable: true`    -> `--run` proceeds, message says GRADABLE;
  D) the arm prompt names the grading interpreter (a different python sees a
     different environment, so a self-check in it is not evidence).

Deterministic: temp dir, no model, no network, no Docker.

Run: python3 tests/acceptance/v970_swe_screen_gate.py
"""
import json
import os
import shutil
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, REPO)

from benchmarks import swebench_slice as S  # noqa: E402

TMP = tempfile.mkdtemp(prefix="sf-v970-")
results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + detail) if detail else ""))


def verdict(runs, iid, gradable, f2p=(1, 1), p2p=(7, 7)):
    d = os.path.join(runs, "2026-11-12_000000_swe_%s" % iid)
    os.makedirs(d, exist_ok=True)
    payload = {"instance": iid, "gradable": bool(gradable),
               "gold": {"f2p_pass": f2p[0], "f2p_total": f2p[1],
                        "p2p_pass": p2p[0], "p2p_total": p2p[1]}}
    with open(os.path.join(d, "verify.json"), "w", encoding="utf-8") as f:
        json.dump(payload, f)


RUNS = os.path.join(TMP, "runs")
os.makedirs(RUNS, exist_ok=True)

# A) nothing screened
ok, msg = S.run_gate("repo__unknown-1", runs=RUNS)
check("A1 an unscreened instance is refused", ok is False)
check("A2 the refusal names the command that fixes it", "--verify" in msg, msg)
check("A3 no verdict is invented from a missing file",
      S.screen_verdict("repo__unknown-1", runs=RUNS) is None)

# B) screened and NOT gradable
verdict(RUNS, "repo__dead-2", False, f2p=(0, 1), p2p=(0, 40))
ok, msg = S.run_gate("repo__dead-2", runs=RUNS)
check("B1 a NOT GRADABLE instance is refused", ok is False)
check("B2 the refusal quotes the gold counts", "0/1" in msg and "0/40" in msg, msg)

# C) screened and gradable
verdict(RUNS, "repo__ok-3", True)
ok, msg = S.run_gate("repo__ok-3", runs=RUNS)
check("C1 a GRADABLE instance passes the gate", ok is True, msg)
check("C2 the message names the verdict", "GRADABLE" in msg, msg)
check("C3 the verdict is read back with its counts",
      (S.screen_verdict("repo__ok-3", runs=RUNS) or {}).get("gold", {}).get("p2p_total") == 7)

# B2) newest verdict wins when an instance was screened twice
verdict(RUNS, "repo__ok-3", False, f2p=(0, 1), p2p=(1, 7))
d2 = os.path.join(RUNS, "2026-11-13_000000_swe_repo__ok-3")
os.makedirs(d2, exist_ok=True)
with open(os.path.join(d2, "verify.json"), "w", encoding="utf-8") as f:
    json.dump({"instance": "repo__ok-3", "gradable": True,
               "gold": {"f2p_pass": 1, "f2p_total": 1, "p2p_pass": 7, "p2p_total": 7}}, f)
os.utime(os.path.join(d2, "verify.json"), (2_000_000_000, 2_000_000_000))
ok, msg = S.run_gate("repo__ok-3", runs=RUNS)
check("D1 a re-screen replaces the older verdict", ok is True, msg)

# E) the arm prompt names the interpreter, and never mangles the problem text
p = S.arm_prompt("/w/repo", "/w/venv-3.10/bin/python", "PROBLEM TEXT")
check("E1 the prompt names the grading interpreter",
      "/w/venv-3.10/bin/python" in p, p[:120])
check("E2 the problem statement survives the formatting",
      "PROBLEM TEXT" in p and "/w/repo" in p)
p2 = S.arm_prompt("/w/repo", "", "PROBLEM TEXT")
check("E3 no interpreter block when the venv could not be built",
      "tests run with" not in p2 and "PROBLEM TEXT" in p2)

# F) the published reference travels WITH the verdict (offline file, no network)
refs = os.path.join(TMP, "refs.json")
with open(refs, "w", encoding="utf-8") as f:
    json.dump({"_meta": {"submissions": 14}, "counts": {"repo__ok-3": 9}}, f)
check("F1 a published reference is read back",
      (S.reference_for("repo__ok-3", path=refs) or {}).get("resolved") == 9)
check("F2 an instance with no published count returns None",
      S.reference_for("repo__none-4", path=refs) is None)
line = S.report_line({"instance": "repo__ok-3", "strict": True, "session": "abc",
                      "reference": {"resolved": 9, "of": 14}})
check("F3 the line carries verdict, reference and session",
      "PASS" in line and "9/14" in line and "abc" in line, line)
line2 = S.report_line({"instance": "x", "strict": False, "session": "s", "reference": None})
check("F4 a run with no reference is called a trend, not a result",
      "trend only" in line2 and "FAIL" in line2, line2)
void = S.report_line({"instance": "repo__dead-2", "strict": False, "session": "s"},
                     screen={"gradable": False, "gold": {"f2p_pass": 0, "f2p_total": 1,
                                                         "p2p_pass": 0, "p2p_total": 40}})
check("G1 a run on a non-gradable instance prints VOID, never FAIL",
      void.startswith("VOID") and "FAIL" not in void.split("—")[0], void)

shutil.rmtree(TMP, ignore_errors=True)
passed = sum(1 for r in results if r)
print("%d/%d checks passed" % (passed, len(results)))
sys.exit(0 if passed == len(results) else 1)
