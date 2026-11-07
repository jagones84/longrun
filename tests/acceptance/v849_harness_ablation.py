#!/usr/bin/env python3
"""v849 — an ablation removes exactly ONE layer (HA-3, lot H).

`harness/contrast.py` diffs two finished runs; nothing could produce the two runs
of an ablation. This instrument materialises an EMPTY scratch root for one
file-backed layer and returns the env overlay that points the harness at it, so the
two arms are identical except for that layer. It never starts a model call.

  A) every layer materialises an empty root (the layer is really gone);
  B) the two arms differ by exactly that layer's env keys;
  C) a layer that lives in code is REFUSED, never a silent no-op;
  D) compare() reports score/pass/cost delta over samples present in both arms;
  E) a sample missing from one arm is listed, never averaged in;
  F) `--check` is the offline gate and exits 0.

Deterministic, no live model, no network, no server.
"""
import json
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "src"))

from benchmarks import ablation as AB  # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""))


for name, ok, detail in AB.check():
    check(name, ok, detail)

p = AB.plan("skills", "python3 -m benchmarks.run --tasks t.yaml")
check("B1 the base arm carries no overlay", p["arm_base"]["env"] == {}, p["arm_base"])
check("B2 the without-arm changes only the layer's keys",
      sorted(p["arm_without"]["env"]) == ["LONGRUN_SKILLS_DIR"], p["differs_by"])
check("B3 the scratch root exists and is empty",
      os.path.isdir(p["arm_without"]["env"]["LONGRUN_SKILLS_DIR"])
      and not os.listdir(p["arm_without"]["env"]["LONGRUN_SKILLS_DIR"]))

try:
    AB.plan("tool_descriptions", "true", root=tempfile.mkdtemp())
    check("C1 a code layer is refused", False, "no error raised")
except ValueError as exc:
    check("C1 a code layer is refused", "unknown layer" in str(exc), str(exc))

# ---------------------------------------------------------------- compare() ---
root = tempfile.mkdtemp(prefix="sf-v849-")
a, b = os.path.join(root, "arm_a"), os.path.join(root, "arm_b")


def sample(base, name, score, ok, usd, tokens=100):
    d = os.path.join(base, name)
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, "result.json"), "w", encoding="utf-8") as fh:
        json.dump({"task": name, "ok": ok,
                   "score": {"score": score, "max": 100.0, "all_pass": ok},
                   "usage": {"total_usd": usd, "tokens_in": tokens}}, fh)


sample(a, "t1", 40.0, False, 0.10)
sample(b, "t1", 60.0, True, 0.12)
sample(a, "t2", 80.0, True, 0.20)
sample(b, "t2", 80.0, True, 0.22)
sample(b, "t3", 99.0, True, 0.30)          # present in ONE arm only

cmp = AB.compare(a, b)
check("D1 only shared samples enter the delta", cmp["samples"] == 2, cmp["samples"])
check("D2 score sums and delta", (cmp["score_a"], cmp["score_b"], cmp["delta_score"])
      == (120.0, 140.0, 20.0), (cmp["score_a"], cmp["score_b"], cmp["delta_score"]))
check("D3 pass counts per arm", (cmp["pass_a"], cmp["pass_b"]) == (1, 2),
      (cmp["pass_a"], cmp["pass_b"]))
check("D4 cost per arm", (cmp["usd_a"], cmp["usd_b"]) == (0.3, 0.34),
      (cmp["usd_a"], cmp["usd_b"]))
check("E1 the one-arm sample is listed, not averaged",
      cmp["only_b"] == ["t3"] and cmp["only_a"] == [], (cmp["only_a"], cmp["only_b"]))
import io
from contextlib import redirect_stdout

with redirect_stdout(io.StringIO()):
    _rc = AB.main(["--check"])
check("F1 --check exits 0", _rc == 0, _rc)

print("---")
passed = sum(results)
print("%d/%d PASS" % (passed, len(results)))
sys.exit(0 if passed == len(results) else 1)
