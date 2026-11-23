#!/usr/bin/env python3
"""v1296 — RRSI regularizers for the harness cycle (RSI R2).

Source: arXiv:2609.24972 §3.2–§3.3 and Table 2. The unregularized evolution in
that paper reaches the highest evolve score (92.8) and the least transfer (40.3
vs 43.6) at 3.80M vs 2.42M tokens/trial. Longrun's cycle proposed, probed and
selected with no budget per candidate, no pre-scoring leakage screen, no noise
floor, no cost-aware acceptance and no pruning.

Contract:
  A `edit_budget()` anneals from b_max to b_min, never below the floor
  B `count_edits()` counts a candidate's named edits, or one opaque edit
  C `leakage()` screens evolve-split terms before scoring; no terms = not screened
  D `admit()` refuses within-noise, below-floor and over-cost candidates by name
  E `stalled()` / `unexplored()` provide the exploration signal
  F `prune()` names components with no positive gain over a full window
  G the cycle drops a leaking or over-budget candidate BEFORE any probe (flag on)
  H the unregularized path is unchanged (flag off)
  I when everything is dropped the report says why

Deterministic: no model, no network, injected editor and runner.
Run: python3 tests/acceptance/v1296_cycle_regularizers.py
"""
import json
import os
import sys
import tempfile
from unittest.mock import patch

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="sf-v1296-")
for _k in ("CONFIG_DIR", "DATA_HOME", "DATA_DIR", "HARNESS_DIR", "SESSIONS_DIR"):
    os.environ["LONGRUN_" + _k] = os.path.join(TMP, _k)
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.harness import cycle                     # noqa: E402
from longrun.harness import regularizer as R          # noqa: E402
from longrun.harness.execution import probe           # noqa: E402

RESULTS = []


def check(name, ok, detail=""):
    RESULTS.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name
          + ((" :: " + str(detail)[:300]) if detail and not ok else ""))


# ---- A: the annealed budget ------------------------------------------------
check("A1 the first round may bundle b_max edits",
      R.edit_budget(0, 5) == R.B_MAX == 3, R.edit_budget(0, 5))
check("A2 the last round is b_min", R.edit_budget(4, 5) == R.B_MIN == 1,
      R.edit_budget(4, 5))
check("A3 the schedule never increases",
      all(R.edit_budget(i, 5) >= R.edit_budget(i + 1, 5) for i in range(4)),
      [R.edit_budget(i, 5) for i in range(5)])
check("A4 a single round is b_max", R.edit_budget(0, 1) == R.B_MAX)
check("A5 a bad config fails closed to the defaults",
      R.edit_budget("x", 5) == R.B_MAX and R.edit_budget(0, "x") == R.B_MAX)
check("A6 b_min above b_max is clamped",
      R.edit_budget(0, 1, b_max=1, b_min=5) == 1)

# ---- B: attributable edits -------------------------------------------------
check("B1 named edits are counted",
      R.count_edits({"edits": ["a", "b", "c"]}) == 3)
check("B2 named fields are counted", R.count_edits({"fields": {"x": 1, "y": 2}}) == 2)
check("B3 an opaque candidate is one edit", R.count_edits({"content": "x"}) == 1)
check("B4 an empty edit list is still one edit", R.count_edits({"edits": []}) == 1)

# ---- C: the leakage screen -------------------------------------------------
check("C1 a task name in the content is a leak",
      R.leakage({"content": "Return the answer for task42"}, ["task42"])["leak"] is True)
check("C2 a longer token does not fire",
      R.leakage({"content": "task420 is different"}, ["task42"])["leak"] is False)
check("C3 matching is case-insensitive",
      R.leakage({"content": "TASK42"}, ["task42"])["leak"] is True)
check("C4 no terms means not screened, not clean",
      R.leakage({"content": "anything"}, []) == {"ok": True, "leak": False,
                                                "hits": [], "screened": False})
check("C5 the hits are named",
      R.leakage({"content": "task42 and acme"}, ["task42", "acme"])["hits"]
      == ["acme", "task42"])

# ---- D: acceptance ---------------------------------------------------------
band = {"band": 0.10}
ok = R.admit(0.80, 0.80, 0.50, 0.10, band)
check("D1 a gain above the band, within cost, is accepted",
      ok.get("ok") is True and ok.get("reason") == "accepted", ok)
check("D2 a gain inside the band is refused as within-noise",
      R.admit(0.55, 0.80, 0.50, 0.0, band).get("reason") == "within-noise")
check("D3 a candidate below the best minus the band is refused",
      R.admit(0.70, 0.95, 0.50, 0.0, band).get("reason") == "below-floor")
check("D4 a gain that costs too much is refused, with the allowance",
      R.admit(0.80, 0.80, 0.50, 0.50, band).get("reason") == "cost")
check("D5 invalid input is refused, not crashed",
      R.admit("x", 0.8, 0.5, 0.0, band).get("reason") == "invalid-input")

# ---- E: exploration signal -------------------------------------------------
check("E1 a flat window is a stall",
      R.stalled([0.50, 0.51, 0.50], window=3, delta=0.02) is True)
check("E2 a real move is not a stall",
      R.stalled([0.50, 0.60, 0.50], window=3, delta=0.02) is False)
check("E3 one observation is not a stall", R.stalled([0.5]) is False)
check("E4 unexplored fields are listed",
      R.unexplored(["system_prompt", "skill", "planning"], ["skill"])
      == ["planning", "system_prompt"])

# ---- F: pruning ------------------------------------------------------------
check("F1 a component with no positive gain over the window is a target",
      R.prune(["a"], {"a": [0.0, 0.0, 0.0]}, window=3) == ["a"])
check("F2 one positive gain keeps it",
      R.prune(["a"], {"a": [0.0, 0.1, 0.0]}, window=3) == [])
check("F3 a short history is not a verdict",
      R.prune(["a"], {"a": [0.0, 0.0]}, window=3) == [])
check("F4 non-numeric evidence is not a verdict",
      R.prune(["a"], {"a": [0.0, "x", 0.0]}, window=3) == [])

# ---- G/H/I: the cycle wiring ----------------------------------------------
workspace = tempfile.mkdtemp(dir=TMP)
with open(os.path.join(workspace, "input.txt"), "w", encoding="utf-8") as f:
    f.write("input")
BASE = {"run_id": "base", "workspace": workspace, "goal": "Read inputs",
        "model": "m", "harness": {}, "budget": {},
        "steps": [{"tool": "fs.read", "ok": False, "error": "missing input"}],
        "deliverables": [], "files_touched": []}
CLEAN = {"kind": "guardrail", "name": "clean", "content": "Inventory inputs."}
LEAK = {"kind": "skill", "name": "leak", "content": "Hard-code the answer for task42."}
BUNDLE = {"kind": "skill", "name": "bundle", "content": "Read inputs first.",
          "edits": ["a", "b", "c", "d"]}
CONFIG = dict(probe.DEFAULTS, enabled=True, max_candidates=3)


def propose_fake(cands):
    """Return the candidate schema DIRECTLY, so the test exercises the cycle's
    regularizer block rather than the editor's sanitiser (which, by design,
    emits one edit per candidate)."""
    state = {"i": 0}

    def _fake(scope, record, contrast=None, library_rows=(), **kw):
        state["i"] += 1
        got = [dict(c) for c in cands] if state["i"] == 1 else []
        return {"candidates": got, "proposals": [], "rejected": []}
    return _fake


def runner(calls):
    def _run(plan, _timeout):
        calls.append(sorted(plan["staged"]))
        return {"record": dict(BASE, run_id="t-%d" % len(calls),
                               steps=[{"tool": "fs.read", "ok": True}])}, ""
    return _run


calls_on = []
with patch.object(cycle.record_mod, "build", return_value=BASE), \
        patch.object(cycle.editors_mod, "propose",
                     side_effect=propose_fake([CLEAN, LEAK, BUNDLE])):
    res_on = cycle.run("session", dry_run=False,
                       c=dict(CONFIG, regularize=True, edit_budget=2,
                              benchmark_terms=["task42"]),
                       runner=runner(calls_on))
dropped = (res_on.get("regularized") or {}).get("dropped") or []
check("G1 the leaking candidate is named", [d for d in dropped if d["name"] == "leak"
      and d["rule"] == "leakage"], dropped)
check("G2 the over-budget candidate is named", [d for d in dropped if d["name"] == "bundle"
      and d["rule"] == "edit-budget" and d["edits"] == 4], dropped)
check("G3 only the clean candidate reaches the runner",
      calls_on and all(c == ["clean"] for c in calls_on), calls_on)
check("G4 the report states the budget and the screened term count",
      res_on["regularized"]["budget"] == 2
      and res_on["regularized"]["screened_terms"] == 1, res_on.get("regularized"))

calls_off = []
with patch.object(cycle.record_mod, "build", return_value=BASE), \
        patch.object(cycle.editors_mod, "propose",
                     side_effect=propose_fake([CLEAN, LEAK, BUNDLE])):
    res_off = cycle.run("session", dry_run=False, c=CONFIG,
                        runner=runner(calls_off))
check("H1 with the flag off all three candidates are probed",
      any(c == ["leak"] for c in calls_off) and any(c == ["bundle"] for c in calls_off),
      calls_off)
check("H2 the unregularized report claims no regularizer",
      "regularized" not in res_off, res_off.get("regularized"))

with patch.object(cycle.record_mod, "build", return_value=BASE), \
        patch.object(cycle.editors_mod, "propose", side_effect=propose_fake([LEAK])):
    res_all = cycle.run("session", dry_run=False,
                        c=dict(CONFIG, regularize=True, edit_budget=1,
                               benchmark_terms=["task42"]),
                        runner=lambda *_: (_ for _ in ()).throw(
                            AssertionError("a dropped candidate must not be probed")))
check("I1 when everything is dropped the cycle says why",
      res_all["status"] == "no candidates"
      and "regularizer dropped" in res_all["reason"], res_all)

print("---")
print("v1296: %d/%d PASS" % (sum(RESULTS), len(RESULTS)))
sys.exit(0 if all(RESULTS) else 1)
