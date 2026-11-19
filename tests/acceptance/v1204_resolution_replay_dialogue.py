#!/usr/bin/env python3
"""v1204 — resolution budget, replay parity, dialogue allocation (round 135).

Sources:
  * arXiv:2611.23068 "The Resolution Hypothesis" — evolution stalls because noisy
    evaluation cannot identify improvements; separate sigma^2 from tau^2.
  * arXiv:2611.23151 "stable-envs-v1" — store state, render on demand; a speedup
    is admissible only when dynamics, render and downstream all replay.
  * arXiv:2611.23119 "Dynamic Task Allocation with Dialogue" — a belief over
    allocations, an entropy trigger, typed evidence, dynamic arrival.

Deterministic: plain data in, dicts out; no model, no network, no server.

Run: python3 tests/acceptance/v1204_resolution_replay_dialogue.py
"""
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="sf-v1204-")
for _key in ("CONFIG_DIR", "SESSIONS_DIR", "GRAPH_DIR", "EDITS_DIR",
             "RUNS_DIR", "DATA_DIR", "THREADS_DIR", "COSTS_DIR", "MEMORY_DIR"):
    os.environ["LONGRUN_" + _key] = os.path.join(TMP, _key)
    os.makedirs(os.environ["LONGRUN_" + _key], exist_ok=True)
os.environ["LONGRUN_DB"] = os.path.join(TMP, "events.db")
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.harness.checks import resolution_budget as RB  # noqa: E402
from longrun.harness.checks import replay_parity as RP  # noqa: E402
from longrun.harness.checks import dialogue_allocation as DA  # noqa: E402

RESULTS = []


def check(name, ok, detail=""):
    RESULTS.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name
          + ((" :: " + str(detail)) if detail else ""))


def kinds(out):
    return [f["kind"] for f in (out.get("findings") or [])]


# ---- 1. resolution budget ------------------------------------------------
r1 = RB.runs_required(3.4, 4.5)
check("the median literature margin needs 28 runs at the Terminal-Bench noise",
      r1 == 28, r1)
check("a zero margin is refused", RB.runs_required(0, 4.5) is None)
check("a zero spread needs no repetition", RB.runs_required(3.4, 0) == 0)
check("a negative spread is refused", RB.runs_required(3.4, -1) is None)

rows1 = [{"run": "a", "score": 60}, {"run": "a", "score": 60},
         {"run": "a", "score": 60},
         {"run": "b", "score": 70}, {"run": "b", "score": 70},
         {"run": "b", "score": 70},
         {"run": "c", "score": 50}, {"run": "c", "score": 50},
         {"run": "c", "score": 50}]
d1 = RB.decompose(rows1)
check("three perfectly repeated runs give zero evaluation noise", d1["sigma"] == 0, d1)
check("run-to-run spread equals the spread of the run means", d1["tau"] == 10, d1)
check("single-run spread is the quadrature of the two", d1["single_run"] == 10, d1)
check("dominating run-to-run variance is named", "run-to-run-dominates" in kinds(d1), d1)

d2 = RB.decompose([{"run": "a", "score": 60}, {"run": "a", "score": 62},
                   {"run": "a", "score": 64}])
check("one artifact with three evaluations estimates noise only",
      d2["sigma"] == 2 and d2["tau"] == 0, d2)
check("a single run is still a valid noise measurement", d2["runs"] == 1, d2)
check("no repetitions at all is named",
      "not-enough-repetitions" in kinds(RB.decompose([{"run": "a", "score": 60}])))

d3 = RB.decompose([{"run": "a", "score": 60}, {"run": "a", "score": 60},
                   {"run": "b", "score": 70}, {"run": "b", "score": 70}], margin=3.4)
check("a margin below the single-run spread needs more than one run",
      d3["runs_required"] > 1 and "single-run-insufficient" in kinds(d3), d3)
check("the estimated margin is carried back", d3["margin"] == 3.4)

rs1 = RB.resolution(rows1, 25, budget=4)
check("a margin well above the spread is identifiable", rs1["verdict"] == "identifiable", rs1)
rs2 = RB.resolution(rows1, 1, budget=8)
check("a margin below the spread is below resolution", rs2["verdict"] == "below-resolution", rs2)
check("the repetition need is reported with the verdict", rs2["runs_required"] > 8, rs2)
check("a decomposition with no repetitions has no verdict",
      "verdict" not in RB.resolution([{"run": "a", "score": 1}], 3))

pairs = ([{"chosen": 70, "rejected": 60}] * 20
         + [{"chosen": 50, "rejected": 60}] * 20)
s1 = RB.selection(pairs)
check("an even split in head-to-head comparisons is 50% accuracy",
      abs(s1["accuracy"] - 0.5) < 1e-9, s1)
check("at chance selection is called indistinguishable",
      "indistinguishable-from-chance" in kinds(s1), s1)
s2 = RB.selection([{"chosen": 70, "rejected": 60}] * 38
                  + [{"chosen": 50, "rejected": 60}] * 2)
check("a real selector is called better than chance",
      "better-than-chance" in kinds(s2), s2)
s3 = RB.selection([{"chosen": 50, "rejected": 60, "accepted": True, "baseline": 60}] * 6
                  + [{"chosen": 70, "rejected": 60, "accepted": True, "baseline": 60}] * 4)
check("accepted replacements that are worse count as false acceptance",
      s3["false_accept_rate"] == 0.6 and "regressions-accepted" in kinds(s3), s3)
check("no comparisons is named", "no-comparisons" in kinds(RB.selection([])))
check("worse-than-chance is reported", "worse-than-chance" in kinds(
    RB.selection([{"chosen": 40, "rejected": 60}] * 9 + [{"chosen": 70, "rejected": 60}])))

pool = [{"artifact": "a%02d" % i, "successes": 2 + i, "trials": 16} for i in range(20)]
q1 = RB.quality_at_k(pool, 1)
q5 = RB.quality_at_k(pool, 5)
check("Quality@K rises from one candidate to five", q5["quality"] > q1["quality"], (q1, q5))
check("the posterior pool beats its equal-quality null",
      RB.advantage(pool, 5)["excess"] > 0, RB.advantage(pool, 5))
check("the credible interval brackets the mean",
      q5["ci"][0] <= q5["quality"] <= q5["ci"][1], q5)
check("a K larger than the pool is refused",
      "k-exceeds-pool" in kinds(RB.quality_at_k(pool, 99)))
check("K below one is refused", "k-exceeds-pool" in kinds(RB.quality_at_k(pool, 0)))
check("an all-fail pool is degenerate",
      "degenerate-pool" in kinds(RB.quality_at_k(
          [{"artifact": "a", "successes": 0, "trials": 8},
           {"artifact": "b", "successes": 0, "trials": 8}], 1)))
adv1 = RB.advantage(pool, 5)
check("a spread pool has headroom against the null",
      "pool-has-headroom" in kinds(adv1), adv1)
check("the null ceiling is reported", adv1["null_ceiling"] >= 0, adv1)
flat = [{"artifact": "a%02d" % i, "successes": 8, "trials": 16} for i in range(12)]
check("an equal-quality pool does not separate from its null",
      "headroom-not-separated" in kinds(RB.advantage(flat, 5)))
check("advise names every missing practice", len(RB.advise({})["findings"]) == 8)
check("a fully declared profile has no finding",
      RB.advise({k: True for k in ("reports_variance", "repeats_runs",
                                   "repeats_evaluations", "separates_proposal_and_selection",
                                   "audits_shortcuts", "repairs_evaluation",
                                   "uses_process_metrics", "declares_resolution")})["findings"] == [])

# ---- 2. replay parity ----------------------------------------------------
check("a state digest ignores key order",
      RP.digest({"a": 1, "b": 2}) == RP.digest({"b": 2, "a": 1}))
check("a different value changes the digest",
      RP.digest({"a": 1}) != RP.digest({"a": 2}))
tr = RP.trace([{"x": 1}, {"x": 2}, {"x": 3}])
check("a trace reports its step count", tr["steps"] == 3, tr)
check("a trace digest chains every step",
      tr["digest"] == RP.trace([{"x": 1}, {"x": 2}, {"x": 3}])["digest"])
check("a deterministic replay is accepted",
      "deterministic" in kinds(RP.replay({"states": [{"x": 1}, {"x": 2}],
                                          "replay": [{"x": 1}, {"x": 2}]})))
rp = RP.replay({"states": [{"x": 1}, {"x": 2}, {"x": 3}],
                "replay": [{"x": 1}, {"x": 2}, {"x": 9}]})
check("a diverging replay names the first divergent step",
      rp["first_divergence"] == 2 and "nondeterministic-replay" in kinds(rp), rp)
rp2 = RP.replay({"states": [{"x": 1}, {"x": 2}], "replay": [{"x": 1}]})
check("a truncated replay diverges at the missing step",
      rp2["first_divergence"] == 1, rp2)
check("an empty record is named", "empty-record" in kinds(RP.replay({"states": []})))

check("a controlled variation keeps dynamics and changes appearance",
      "controlled-variation" in kinds(RP.variation(
          {"base_state": {"q": 1}, "variant_state": {"q": 1},
           "base_render": {"rgb": [1, 2, 3]}, "variant_render": {"rgb": [4, 5, 6]}})))
check("a variation that moves the dynamics is a leak",
      "variation-leaks-dynamics" in kinds(RP.variation(
          {"base_state": {"q": 1}, "variant_state": {"q": 2},
           "base_render": [1], "variant_render": [2]})))
check("a variation with no visual effect is named",
      "variation-invisible" in kinds(RP.variation(
          {"base_state": {"q": 1}, "variant_state": {"q": 1},
           "base_render": [1], "variant_render": [1]})))
check("a variation with no recorded state is refused",
      "state-missing" in kinds(RP.variation({"base_render": [1], "variant_render": [2]})))

pp = RP.parity([1.0, 2.0, 3.0], [1.0, 2.0, 3.0])
check("identical trajectories pass parity", pp["passed"] is True and pp["max_abs"] == 0, pp)
check("a 4e-13 deviation passes a 1e-6 tolerance",
      RP.parity([0.0], [4e-13])["passed"] is True)
check("a 1e-3 deviation fails a 1e-6 tolerance",
      "dynamics-diverged" in kinds(RP.parity([0.0], [1e-3])))
check("the worst step is reported",
      RP.parity([1.0, 5.0], [1.0, 2.0])["step"] == 1)
check("a length mismatch is refused",
      "length-mismatch" in kinds(RP.parity([1.0], [1.0, 2.0])))
check("a non-numeric state is refused",
      "non-numeric-state" in kinds(RP.parity([1.0], ["x"])))
check("a near-identical render passes",
      RP.render_parity(2e-5, 4e-4)["passed"] is True)
check("a visible render difference fails",
      "render-diverged" in kinds(RP.render_parity(2.2, 2.86)))

t1 = RP.timing([{"engine": "native", "seconds": 12.0},
                {"engine": "native", "seconds": 10.0},
                {"engine": "native", "seconds": 11.0},
                {"engine": "native", "seconds": 10.5},
                {"engine": "port", "seconds": 8.0},
                {"engine": "port", "seconds": 7.0},
                {"engine": "port", "seconds": 7.2},
                {"engine": "port", "seconds": 7.1}])
check("the warm-up window is dropped from the median",
      t1["median"]["native"] == 10.5 and t1["median"]["port"] == 7.1, t1)
check("the speedup is the ratio of medians", abs(t1["speedup"] - 1.4789) < 1e-3, t1)
check("a faster port is named", "faster" in kinds(t1))
check("a window shorter than three seconds is named",
      "window-too-short" in kinds(RP.timing(
          [{"engine": "native", "seconds": 9.0}, {"engine": "native", "seconds": 2.0},
           {"engine": "native", "seconds": 2.5}, {"engine": "native", "seconds": 2.6},
           {"engine": "port", "seconds": 9.0}, {"engine": "port", "seconds": 3.0},
           {"engine": "port", "seconds": 3.1}, {"engine": "port", "seconds": 3.2}])))
check("too few post-warm-up windows are named",
      "too-few-windows" in kinds(RP.timing(
          [{"engine": "native", "seconds": 9.0}, {"engine": "native", "seconds": 5.0},
           {"engine": "native", "seconds": 5.1},
           {"engine": "port", "seconds": 9.0}, {"engine": "port", "seconds": 4.0},
           {"engine": "port", "seconds": 4.1}])))
check("no timing rows is named", "no-timing" in kinds(RP.timing([])))

good = {"states": [{"x": 1}, {"x": 2}], "replay": [{"x": 1}, {"x": 2}],
        "source_states": [0.0, 1.0], "port_states": [0.0, 1.0],
        "mse_mean": 0.0, "mse_max": 0.0, "downstream_delta": -0.7, "speedup": 1.33}
a1 = RP.audit(good)
check("a reproducible speedup passes every gate", a1["admissible"] is True, a1)
check("the passing audit carries its speedup",
      "reproducible-speedup" in kinds(a1), a1)
a2 = RP.audit(dict(good, downstream_delta=-4.0))
check("a degraded downstream score blocks the audit",
      a2["admissible"] is False and "downstream-degraded" in kinds(a2), a2)
a3 = RP.audit(dict(good, replay=[{"x": 1}, {"x": 9}]))
check("a non-replaying environment blocks the audit",
      a3["admissible"] is False and "replay-failed" in kinds(a3), a3)
a4 = RP.audit(dict(good, speedup=0.9))
check("a slower port is parity without speedup",
      a4["admissible"] is False and "no-speedup" in kinds(a4), a4)
check("an unmeasured downstream is named",
      "downstream-unmeasured" in kinds(RP.audit(dict(good, downstream_delta=None))))
check("advise names every missing practice", len(RP.advise({})["findings"]) == 8)
check("a fully declared profile has no finding", RP.advise(
    {k: True for k in ("records_state", "replays_deterministically", "applies_variations",
                       "separates_appearance_and_dynamics", "measures_dynamics_parity",
                       "measures_render_parity", "checks_downstream",
                       "times_with_protocol")})["findings"] == [])

# ---- 3. dialogue allocation ---------------------------------------------
b1 = DA.posterior({"chop": 0.5, "cook": 0.5}, {"chop": 0.9, "cook": 0.1},
                  {"chop": 0.8, "cook": 0.2})
check("action and utterance evidence sharpen the allocation belief",
      b1["best"] == "chop" and b1["belief"]["chop"] > 0.97, b1)
check("a normalized prior raises no finding", "unnormalized-prior" not in kinds(b1), b1)
check("an unnormalized prior is named",
      "unnormalized-prior" in kinds(DA.posterior({"chop": 1, "cook": 1})))
check("evidence that excludes every allocation is refused",
      "zero-mass" in kinds(DA.posterior({"chop": 0.5, "cook": 0.5},
                                        {"chop": 0, "cook": 0})))
check("a negative prior is refused",
      "invalid-prior" in kinds(DA.posterior({"chop": -1, "cook": 2})))
check("no allocations is named", "no-allocations" in kinds(DA.posterior({})))

e1 = DA.entropy({"a": 0.25, "b": 0.25, "c": 0.25, "d": 0.25})
check("a uniform belief over four allocations is two bits", e1["bits"] == 2.0, e1)
check("a uniform belief is maximally uncertain", e1["normalized"] == 1.0, e1)
check("a single allocation has zero entropy",
      DA.entropy({"a": 1.0})["normalized"] == 0.0)
check("an empty belief is named", "empty-belief" in kinds(DA.entropy({})))
check("a uniform belief triggers speech at 0.7",
      DA.speak({"a": 0.25, "b": 0.25, "c": 0.25, "d": 0.25}, 0.7)["speak"] is True)
check("a sharp belief stays silent at 0.7",
      DA.speak({"a": 0.99, "b": 0.01}, 0.7)["speak"] is False)
check("an empty belief speaks rather than assuming knowledge",
      DA.speak({})["speak"] is True)

check("a disappearing object is a pick-up",
      DA.evidence(["tomato", "board"], ["board"])["type"] == "picked-up")
check("an appearing object is a set-down",
      DA.evidence(["board"], ["board", "plate"])["type"] == "set-down")
check("a replaced object is a delivery",
      DA.evidence(["tomato", "board"], ["board", "salad"])["type"] == "delivered")
check("an unchanged observation is no evidence",
      DA.evidence(["board"], ["board"])["type"] == "none")
check("the removed and added items are reported",
      DA.evidence(["a", "b"], ["b", "c"])["removed"] == ["a"]
      and DA.evidence(["a", "b"], ["b", "c"])["added"] == ["c"])

pr1 = DA.propositions({"ingredient-in-hidden": 0.5, "dispenser-known": 0.8},
                      "set-down", ["ingredient-in-hidden"], {"ingredient-in-hidden": 0.9})
check("evidence updates only the touched proposition",
      pr1["belief"]["ingredient-in-hidden"] == 0.45, pr1)
check("an untouched proposition keeps its belief",
      pr1["belief"]["dispenser-known"] == 0.8, pr1)
pr2 = DA.propositions({"x": 0.5}, "none", ["x"])
check("no evidence updates nothing",
      pr2["belief"]["x"] == 0.5 and "no-evidence-updated-propositions" in kinds(pr2), pr2)
check("an unknown evidence type is refused",
      "unknown-evidence" in kinds(DA.propositions({"x": 0.5}, "exploded", ["x"])))
check("an invalid proposition is refused",
      "invalid-proposition" in kinds(DA.propositions({"x": 2}, "none", [])))

sc1 = DA.schedule(3, rate=1.0, horizon=10)
check("a rate of one reveals one task per step",
      sc1["revealed"] == [0, 1, 2] and sc1["complete"] is True, sc1)
check("work is continuous from the first timestep",
      "continuous-work" in kinds(sc1), sc1)
sc2 = DA.schedule(2, rate=0.025, horizon=1)
check("a short horizon leaves tasks unrevealed",
      "tasks-unrevealed" in kinds(sc2), sc2)
check("the same seed reproduces the arrival schedule",
      DA.schedule(4, 0.05, 200, seed=11)["revealed"]
      == DA.schedule(4, 0.05, 200, seed=11)["revealed"])
check("an impossible schedule is refused",
      "invalid-schedule" in kinds(DA.schedule(0)))
check("a rate above one is refused",
      "invalid-schedule" in kinds(DA.schedule(2, rate=1.5)))

c1 = DA.compare([40, 42, 38, 41, 39, 40], [58, 60, 55, 59, 57, 56])
check("the communicating agent finishes earlier",
      c1["delta"] < 0 and "communication-faster" in kinds(c1), c1)
check("the speedup is positive", c1["speedup"] > 0, c1)
check("both standard errors are reported",
      c1["delta_se"] >= 0 and c1["speedup_se"] >= 0, c1)
check("identical timings leave the difference unresolved",
      "difference-unresolved" in kinds(DA.compare([50, 51, 52], [50, 51, 52])))
check("unpaired lengths are refused",
      "not-enough-paired-runs" in kinds(DA.compare([1, 2], [1, 2, 3])))
check("one run per arm is not enough",
      "not-enough-paired-runs" in kinds(DA.compare([1], [2])))

full = {"dynamic_arrival": True, "partial_observability": True, "known_task_types": True,
        "fixed_agent_set": True, "free_communication": True, "runs_per_config": 6,
        "max_queue": 3}
check("a specification inside the paper's evidence raises no finding",
      DA.audit(full)["findings"][0]["kind"] == "within-evidence", DA.audit(full))
check("a queue beyond three is named",
      "queue-beyond-evidence" in kinds(DA.audit(dict(full, max_queue=5))))
check("fewer than six runs is named",
      "too-few-runs" in kinds(DA.audit(dict(full, runs_per_config=3))))
check("static goals are named", "static-goals" in kinds(DA.audit({})))
check("a full-observability-only design is named",
      "full-observability-only" in kinds(DA.audit({"dynamic_arrival": True})))
check("advise names every missing practice", len(DA.advise({})["findings"]) == 8)
check("a fully declared profile has no finding", DA.advise(
    {k: True for k in ("keeps_allocation_belief", "uses_dialogue_as_evidence",
                       "speaks_on_uncertainty", "types_observable_evidence",
                       "updates_only_affected", "models_dynamic_arrival",
                       "reports_timestep_and_speedup", "tests_partial_observability")})["findings"] == [])

# ---- result --------------------------------------------------------------
ok = sum(1 for r in RESULTS if r)
print("\n%d/%d checks passed" % (ok, len(RESULTS)))
sys.exit(0 if ok == len(RESULTS) else 1)
