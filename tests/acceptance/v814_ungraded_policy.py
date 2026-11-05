#!/usr/bin/env python3
"""v814 — one policy for a task that never ran (B-2).

JobBench dropped a cut / no-output row from its mean ratio while Polyglot counted
it in the denominator, and the README already claimed a delivered-nothing run is a
"rubric-weighted zero". So the two suites' headline numbers did not mean the same
thing, and the deficit was invisible in the number people quote.

`report()` now also emits `mean_ratio_all` — the SAME ratio over EVERY task, a task
that never ran counting as a failure — next to the existing `mean_ratio`.
("Silent Instrument Errors", 2026-11-05: treating ungraded episodes as failures
moved a leaderboard 0.30 → 0.43.)

  A) a cut and a no-output task are counted in the all-task ratio as failures;
  B) the two numbers are equal when nothing was cut (no silent drift);
  C) compare.md carries both columns.

Deterministic, no live model, no network, no server.
"""
import json
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, REPO)

from benchmarks import jobbench_compare as jc      # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""))


def row(task, arm, score=None, mx=10, timed_out=False, no_output=False, err=""):
    return {"task": task, "arm": arm, "delivered": 1 if score is not None else 0,
            "duration_s": 1.0, "error": err, "timed_out": timed_out,
            "score": {"score": score, "max": mx, "no_output": no_output,
                      "error": "" if score is not None else "x"},
            "usage": {"tokens_in": 10, "tokens_out": 5, "total_usd": 0.01}}


rows = [
    row("t1", "longrun", score=8),                 # graded 0.8
    row("t2", "longrun", timed_out=True),          # cut at the budget
    row("t3", "longrun", no_output=True),          # finished, nothing to grade
    row("t1", "harness2", score=10),               # graded 1.0
    row("t2", "harness2", score=5),                # graded 0.5
]
out = tempfile.mkdtemp(prefix="sf-v814-")
jc.report(out, rows, {"model": "m", "suite": "jobbench"})
summary = json.load(open(os.path.join(out, "compare.json"), encoding="utf-8"))["arms"]

lr = summary["longrun"]
h2 = summary["harness2"]

check("A1 the cut task is counted as a timeout", lr["timeouts"] == 1, lr)
check("A2 the no-output task is counted as no_output", lr["no_output"] == 1, lr)
check("A3 the all-task ratio counts them as failures",
      abs(lr["mean_ratio_all"] - round(0.8 / 3, 4)) < 1e-9, lr["mean_ratio_all"])
check("A4 the finished-only mean is unchanged",
      abs(lr["mean_ratio"] - 0.8) < 1e-9, lr["mean_ratio"])
check("B1 nothing was cut for harness2 so the two means agree",
      abs(h2["mean_ratio"] - h2["mean_ratio_all"]) < 1e-9, h2)
md = open(os.path.join(out, "compare.md"), encoding="utf-8").read()
check("C1 compare.md prints both columns",
      "all-task ratio" in md and "mean ratio" in md)
check("C2 the policy is stated in the benchmark README",
      "all-task ratio" in open(os.path.join(REPO, "benchmarks", "README.md"),
                               encoding="utf-8").read())

print("---")
passed = sum(results)
print("%d/%d PASS" % (passed, len(results)))
sys.exit(0 if passed == len(results) else 1)
