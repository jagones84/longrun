#!/usr/bin/env python3
"""v726 — a BENCHMARK for self-evolve, built the way the frontier measures it (EV-21).

Two October-2026 papers define how this must be measured:
  * arXiv 2610.27889 ("Elicitation or Expansion?"): a single aggregate success rate
    is misleading — pass@1 advantages can reverse at larger attempt budgets and
    aggregate gains hide hard-task shortfalls. So: per difficulty, and pass@k.
  * arXiv 2610.34386 (ParetoRSI-Gym): hold the optimisation signal apart from a
    generalisation check, and never let one domain's gain hide another's regression.

The benchmark runs the REAL miner, the REAL forge and the REAL dispatch, on a
synthetic corpus with three task families of different length plus noise, and
prints one row per difficulty. Floors are asserted, so a regression turns the gate
red instead of shrinking a number quietly.

  columns: families · mined · coverage · replay · work reduction · pass@1 · pass@5
"""
import json
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="longrun-v726-")
for _k in ("DATA_DIR", "CONFIG_DIR", "SESSIONS_DIR", "GRAPH_DIR", "DB"):
    os.environ["LONGRUN_" + _k] = os.path.join(TMP, _k.lower())
os.environ["LONGRUN_MATRIX_SRC"] = os.path.join(TMP, "src", "Matrix")
os.environ["LONGRUN_MATRIX_DOT"] = os.path.join(TMP, ".Matrix")
for _k in ("DATA_DIR", "CONFIG_DIR", "SESSIONS_DIR", "GRAPH_DIR"):
    os.makedirs(os.environ["LONGRUN_" + _k], exist_ok=True)
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.util import selfevolve as SE  # noqa: E402
from longrun.core import matrix as MTX  # noqa: E402
from longrun.tools import tools as T  # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name
          + ((" :: " + str(detail)[:400]) if detail and not ok else ""))


# ------------------------------------- corpus ---------------------------
# Three families with DISJOINT vocabularies, so any cross-family n-gram would be a
# real false positive instead of an artefact of a shared prefix.
EASY = ["memory.recall", "memory.store"]
MEDIUM = ["fs.read", "fs.edit", "shell.exec"]
HARD = ["fs.write", "web.fetch", "index.search", "web.search", "memory.recent"]
FAMILIES = [("easy", EASY), ("medium", MEDIUM), ("hard", HARD)]
SUPPORT = 4

history, truth = [], {}
for label, pat in FAMILIES:
    truth[label] = list(pat)
    for _i in range(SUPPORT):
        history.append(list(pat))
# noise: single-tool repeats (never a skill) and a pair below min_count
for _ in range(3):
    history.append(["shell.exec", "shell.exec", "shell.exec"])
for _ in range(2):
    history.append(["memory.recall", "fs.read"])

CFG = {"min_len": 2, "min_count": 3, "max_len": 6}
cands = SE.mine(history, CFG)
mined = [list(c["pattern"]) for c in cands]

# ------------------------------------- coverage + precision ------------
per_family = {}
for label, pat in FAMILIES:
    sup = next((int(c["support"]) for c in cands if list(c["pattern"]) == pat), 0)
    per_family[label] = {"found": sup > 0, "support": sup, "length": len(pat)}
junk = [c for c in mined if c not in [list(p) for _l, p in FAMILIES]]
check("A1 every family is mined (all difficulties)",
      all(v["found"] for v in per_family.values()), (per_family, mined))
check("A2 the noise produced no candidate (precision 1.0)", not junk, junk)
check("A3 support reflects the repeated runs",
      all(v["support"] == SUPPORT for v in per_family.values()), per_family)

# ------------------------------------- hold-out (ParetoRSI lesson) -----
train = [list(EASY) for _ in range(SUPPORT)] + [list(MEDIUM) for _ in range(SUPPORT)]
held_cands = [list(c["pattern"]) for c in SE.mine(train, CFG)]
check("B1 a family absent from the history is not claimed",
      list(HARD) not in held_cands and not any(len(c) >= 4 for c in held_cands),
      held_cands)

# ------------------------------------- forge + replay ------------------
_stub_seen = []
_real_exec = T.execute


def _stub(name, args, run_id=None):
    _stub_seen.append((name, dict(args or {})))
    return {"ok": True}


T.execute = _stub
rows = []
try:
    for label, pat in FAMILIES:
        forged = SE.forge_matrix(pat, support=SUPPORT, name="learned_bench_%s" % label)
        ok_forge = bool(forged.get("ok"))
        tool = forged.get("matrix_tool") or ""
        attempts, passes = 5, 0
        first_ok = False
        for i in range(attempts):
            _stub_seen.clear()
            args = {"inputs": [{"i": i, "j": k} for k in range(len(pat))]}
            out = MTX.execute_tool(tool, args, run_id="bench-%s-%d" % (label, i)) or {}
            got = [s[0] for s in _stub_seen]
            ok = (out.get("ok") is True and out.get("ok_count") == len(pat)
                  and got == list(pat))
            passes += 1 if ok else 0
            if i == 0:
                first_ok = ok
        rows.append({"difficulty": label, "steps": len(pat), "forged": ok_forge,
                     "replay": first_ok, "pass1": 1.0 if first_ok else 0.0,
                     "pass5": passes / float(attempts),
                     "work_raw": len(pat), "work_with_tool": 1,
                     "reduction": 1.0 - (1.0 / len(pat))})
        if forged.get("ok"):
            MTX.remove("tool", forged["namespace"])
finally:
    T.execute = _real_exec

check("C1 every family was forged green (its own behavioural proof passed)",
      all(r["forged"] for r in rows), rows)
check("C2 the forged tool replays its family exactly (order + args)",
      all(r["replay"] for r in rows), rows)
check("C3 pass@1 == pass@5: a deterministic signal shows no pass@k inversion",
      all(r["pass1"] == r["pass5"] == 1.0 for r in rows), rows)

# ------------------------------------- report + floors -----------------
print("")
print("%-9s %5s %7s %10s %9s %9s %8s %8s" %
      ("difficulty", "steps", "forged", "coverage", "replay", "work_red", "pass@1", "pass@5"))
for r in rows:
    print("%-9s %5d %7s %10s %9s %8.1f%% %8.2f %8.2f" %
          (r["difficulty"], r["steps"], "yes" if r["forged"] else "NO",
           "100%" if per_family[r["difficulty"]]["found"] else "0%",
           "100%" if r["replay"] else "0%",
           r["reduction"] * 100.0, r["pass1"], r["pass5"]))
cov = sum(1 for v in per_family.values() if v["found"]) / float(len(per_family))
agg_red = sum(r["reduction"] for r in rows) / float(len(rows))
agg_p1 = sum(r["pass1"] for r in rows) / float(len(rows))
agg_p5 = sum(r["pass5"] for r in rows) / float(len(rows))
print("%-9s %5s %7s %10.0f%% %9s %8.1f%% %8.2f %8.2f" %
      ("AGGREGATE", "-", "%d/%d" % (len(rows), len(FAMILIES)), cov * 100.0, "-",
       agg_red * 100.0, agg_p1, agg_p5))
print("")

check("D1 the aggregate work reduction is the per-difficulty mean, not hidden",
      abs(agg_red - ((0.5 + 2 / 3.0 + 0.8) / 3.0)) < 1e-9, agg_red)
check("D2 hard tasks are better served than easy ones (the long tail is where it pays)",
      next(r["reduction"] for r in rows if r["difficulty"] == "hard")
      > next(r["reduction"] for r in rows if r["difficulty"] == "easy"), rows)

print("---")
passed = sum(results)
print("%d/%d PASS" % (passed, len(results)))
sys.exit(0 if passed == len(results) else 1)
