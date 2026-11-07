#!/usr/bin/env python3
"""v840 — "SATURATED" means the SET is at its ceiling, not that the arms agree.

Live evidence (`2026-11-06_222648_polyglot_postfix1`): a single-arm run that solved
9 of 10 tasks printed

    **SATURATED — every arm solved every task.** This set cannot rank the harnesses

because the guard was `len(ties) == len(full)` and with ONE arm every task is
trivially a tie. Saturation is about SOLVING everything; two arms failing the same
task is a tie, and it is not evidence that the set is easy.

Deterministic, offline, no model. Run: python3 tests/acceptance/v840_saturation_truth.py
"""
import json
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, REPO)

from benchmarks import polyglot_compare as PC  # noqa: E402

RESULTS = []


def check(name, ok, detail=""):
    RESULTS.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""))


def rows(spec):
    """spec: {task: {arm: bool}} -> the runner's row shape."""
    out = []
    for task, per_arm in spec.items():
        for arm, ok in per_arm.items():
            out.append({"task": task, "arm": arm, "resolved": ok,
                        "status": "passed" if ok else "failed",
                        "duration_s": 1.0, "tokens": 10})
    return out


# --- A: one arm ---------------------------------------------------------------
ten = {"t%d" % i: {"longrun": True} for i in range(10)}
flat, diff, scored = PC._saturated(rows(ten), ["longrun"])
check("A1 one arm that solves everything IS the ceiling", flat is True,
      (flat, diff, scored))

nine = dict(ten, t9={"longrun": False})
flat, diff, scored = PC._saturated(rows(nine), ["longrun"])
check("A2 one arm at 9/10 is NOT saturated (the live bug)", flat is False,
      (flat, diff, scored))
check("A3 ... and the count is right", (diff, scored) == (0, 10), (diff, scored))

# --- B: two arms --------------------------------------------------------------
both = {"t%d" % i: {"longrun": True, "openclaw": True} for i in range(3)}
check("B1 two arms, both perfect -> saturated", PC._saturated(rows(both), ["longrun", "openclaw"])[0] is True)

shared_fail = {"t0": {"longrun": True, "openclaw": True},
               "t1": {"longrun": False, "openclaw": False}}
flat, diff, scored = PC._saturated(rows(shared_fail), ["longrun", "openclaw"])
check("B2 two arms failing the SAME task is a tie, not a ceiling", flat is False,
      (flat, diff, scored))

split = {"t0": {"longrun": True, "openclaw": False},
         "t1": {"longrun": True, "openclaw": True}}
flat, diff, scored = PC._saturated(rows(split), ["longrun", "openclaw"])
check("B3 a disagreement is discriminating, not saturated",
      flat is False and (diff, scored) == (1, 2), (flat, diff, scored))

# --- C: the verdict line a human reads ---------------------------------------
tmp = tempfile.mkdtemp(prefix="v840-")
PC._report(tmp, rows(nine), {"model": "m", "dataset": "d", "dataset_commit": "c",
                             "n_tasks": 10, "order": "hardest"})
md = open(os.path.join(tmp, "compare.md"), encoding="utf-8").read()
check("C1 a single-arm report says it is a score, not a comparison",
      "Single arm" in md and "SATURATED" not in md, md[:400])
check("C2 ... and it states the real score", "9/10" in md, md[:400])

seen = json.load(open(os.path.join(tmp, "run.json"), encoding="utf-8"))
check("C3 run.json records saturated=false", seen.get("saturated") is False, seen)

print("---")
ok = sum(RESULTS)
print("%d/%d PASS" % (ok, len(RESULTS)))
sys.exit(0 if ok == len(RESULTS) else 1)
