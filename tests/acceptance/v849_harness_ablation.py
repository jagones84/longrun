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
from contextlib import redirect_stderr, redirect_stdout

with redirect_stdout(io.StringIO()):
    _rc = AB.main(["--check"])
check("F1 --check exits 0", _rc == 0, _rc)

# ------------------------------------------------------------ execute both arms ---
# A fake benchmark that reads the ARM MARKER and the layer env: proves the runner
# really launches two processes that differ by exactly the layer, offline.
helper = os.path.join(root, "emit.py")
with open(helper, "w", encoding="utf-8") as fh:
    fh.write(
        "import json, os, sys\n"
        "out = sys.argv[1]\n"
        "arm = os.environ.get('LONGRUN_ABLATION_ARM')\n"
        "score = 60.0 if arm == 'arm_without' else 40.0\n"
        "d = os.path.join(out, 't1')\n"
        "os.makedirs(d, exist_ok=True)\n"
        "json.dump({'task': 't1', 'score': {'score': score, 'max': 100.0,\n"
        "           'all_pass': score > 50}, 'usage': {'total_usd': 0.1},\n"
        "           'skills_dir': os.environ.get('LONGRUN_SKILLS_DIR')},\n"
        "          open(os.path.join(d, 'result.json'), 'w'))\n")
cmd = "%s %s {out}" % (sys.executable, helper)
ran = AB.run("skills", cmd)
check("G1 both arms executed successfully",
      all(a["rc"] == 0 for a in ran["arms"].values()),
      {k: v["rc"] for k, v in ran["arms"].items()})
check("G2 the two arms produced a real delta",
      ran["compare"]["samples"] == 1 and ran["compare"]["delta_score"] == 20.0,
      ran["compare"]["delta_score"])
base_env = json.load(open(os.path.join(ran["arms"]["arm_base"]["out"], "t1", "result.json")))
without_env = json.load(open(os.path.join(ran["arms"]["arm_without"]["out"], "t1", "result.json")))
check("G3 only the without-arm ran without the skills layer",
      base_env.get("skills_dir") != without_env.get("skills_dir")
      and without_env.get("skills_dir")
      and not os.listdir(without_env["skills_dir"]),
      (base_env.get("skills_dir"), without_env.get("skills_dir")))
with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
    _rc2 = AB.main(["--run", "--plan", "skills", "--command", "true"])
check("G4 --run without {out} is refused", _rc2 == 2, _rc2)

print("---")
passed = sum(results)
print("%d/%d PASS" % (passed, len(results)))
sys.exit(0 if passed == len(results) else 1)
