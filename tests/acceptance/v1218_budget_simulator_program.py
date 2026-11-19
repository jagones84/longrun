#!/usr/bin/env python3
"""v1218 — budget-paired audit, simulator meta-evaluation, program judges (round 149).

Sources:
  * arXiv:2611.24867 "Budget-Paired Counterfactual Audits" — the finite-horizon
    values `V0/Qb/Vb`, the per-step `delta` and final `eta`, the exact
    decomposition identity, the branch-to-selector anchor, the staged read
    losses, the routing gain and the `2 eps` / `2 B eps` bounds.
  * arXiv:2611.24892 "On Evaluating User Simulators" — paired sensitivity with
    an interval, the 2.5th-percentile population rule, per-suite coverage, the
    AUROC and retention of a filter, the three levels and their geometric
    headline, and the per-level leader table.
  * arXiv:2611.24849 "ExecJudges" — the answer-to-grade formula, the floored mean
    of three programs, the rubric variant, the error directions, tau-b ranking
    agreement, the label-gain curve, the break-even pool depth and the sandbox
    import policy.

Deterministic: plain data in, dicts out; no model, no network, no server.

Run: python3 tests/acceptance/v1218_budget_simulator_program.py
"""
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="sf-v1218-")
for _key in ("CONFIG_DIR", "SESSIONS_DIR", "GRAPH_DIR", "EDITS_DIR",
             "RUNS_DIR", "DATA_DIR", "THREADS_DIR", "COSTS_DIR", "MEMORY_DIR"):
    os.environ["LONGRUN_" + _key] = os.path.join(TMP, _key)
    os.makedirs(os.environ["LONGRUN_" + _key], exist_ok=True)
os.environ["LONGRUN_DB"] = os.path.join(TMP, "events.db")
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.harness.checks import budget_audit as BA  # noqa: E402
from longrun.harness.checks import simulator_audit as SA  # noqa: E402
from longrun.harness.checks import program_judge as PJ  # noqa: E402

RESULTS = []


def check(name, ok, detail=""):
    RESULTS.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name
          + ((" :: " + str(detail)) if detail else ""))


def close(a, b, tol=1e-9):
    return a is not None and abs(a - b) <= tol


def kinds(out):
    return [f["kind"] for f in (out.get("findings") or [])]


# ---- 1. budget-paired audit (arXiv:2611.24867) ------------------------
check("the smoothed belief at one and one is one half",
      close(BA.belief({"support": 1, "refute": 1})["p"], 0.5))
check("two supports and no refute gives three quarters",
      close(BA.belief({"support": 2, "refute": 0})["p"], 0.75))
check("the evidence count is the sum",
      BA.belief({"support": 2, "refute": 3})["evidence"] == 5)
check("V0 is the larger side of the belief",
      close(BA.value({"support": 2, "refute": 0})["value"], 0.75))
check("V0 is one half at a tie", close(BA.value({})["value"], 0.5))
check("V0 is symmetric on the other side",
      close(BA.value({"support": 0, "refute": 2})["value"], 0.75))
check("zero looks is one certain outcome",
      len(BA.observe({"support": 1, "refute": 1}, 0)) == 1)
check("two looks have three outcomes",
      len(BA.observe({"support": 1, "refute": 1}, 2)) == 3)
check("the outcome probabilities sum to one",
      close(sum(p for p, _ in BA.observe({"support": 1, "refute": 1}, 2)), 1.0))
check("a supporting look adds one to the support count",
      {"support": 2, "refute": 1} in [c for _, c in
                                      BA.observe({"support": 1, "refute": 1}, 1)])
solved0 = BA.solve({"support": 1, "refute": 1}, 0)
check("with no budget every action is worth V0", close(solved0["value"], 0.5))
check("with no budget committing is the reported best", solved0["best"] == "commit")
check("with no budget no action has a loss",
      all(close(row["loss"], 0.0) for row in solved0["table"]))
solved1 = BA.solve({"support": 1, "refute": 1}, 1)
check("one look is worth more than none", solved1["value"] > 0.5)
check("at one look a single probe is optimal", solved1["best"] == "probe-one")
check("committing at one look has a positive loss",
      next(r for r in solved1["table"] if r["action"] == "commit")["loss"] > 0)
check("the losses are in percentage points",
      close(next(r for r in solved1["table"] if r["action"] == "commit")["loss_pp"],
            next(r for r in solved1["table"] if r["action"] == "commit")["loss"] * 100))
check("no action beats the reported value",
      all(row["loss"] >= -1e-12 for row in solved1["table"]))
check("Q is defined without a budget",
      BA.q_value({"support": 1, "refute": 1}, {"reads": 1}, 0)["verdict"] == "no-budget")
check("Q names the action it scored",
      BA.q_value({"support": 1, "refute": 1},
                 {"name": "probe-one", "reads": 1}, 1)["action"] == "probe-one")
OPT = BA.decompose({"state": {"support": 1, "refute": 1}, "budget": 2})
check("optimal play leaves only the final-answer loss",
      close(OPT["expected_delta"], 0.0) and OPT["expected_eta"] > 0)
check("the identity holds on the optimal policy", OPT["holds"] is True)
check("the identity gap is zero", close(OPT["gap"], 0.0))
check("the left side is value minus accuracy",
      close(OPT["lhs"], OPT["value"] - OPT["accuracy"]))
BAD = BA.decompose({"state": {"support": 1, "refute": 1}, "budget": 2,
                    "policy": {"2": "commit", "1": "commit"}})
check("committing twice shifts the loss into the steps",
      BAD["expected_delta"] > 0 and close(BAD["expected_eta"], 0.0))
check("the identity still holds for a wrong policy", BAD["holds"] is True)
check("the two policies differ in where the loss sits",
      BAD["expected_delta"] > OPT["expected_delta"])
DEEP = BA.decompose({"state": {"support": 2, "refute": 1}, "budget": 3})
check("the identity holds at three looks", DEEP["holds"] is True)
WRONG = BA.decompose({"state": {"support": 2, "refute": 0}, "budget": 0,
                      "prediction": "negative"})
check("answering the wrong label costs the final-answer loss",
      close(WRONG["expected_eta"], 0.5))
check("a wrong final answer is reported as such",
      close(WRONG["lhs"], 0.5))
check("an empty decomposition is refused",
      BA.decompose({})["verdict"] == "identity-holds" and
      close(BA.decompose({})["rhs"], 0.0))
GOOD = BA.anchors([{"played": {"1": "branch", "2": "selector"},
                    "loss": 14.0, "anchor": True},
                   {"played": {"1": "branch", "2": "selector"},
                    "loss": 0.7, "anchor": False}])
check("both anchor transitions are counted", GOOD["transitions"] == 2)
check("the anchor rate is one", close(GOOD["rate"], 1.0))
check("the anchor loss is separated from the control",
      close(GOOD["anchor_loss"], 14.0) and close(GOOD["control_loss"], 0.7))
check("the anchor gap is the difference", close(GOOD["gap"], 13.3))
check("an optimal transition is named",
      GOOD["verdict"] == "anchor-transition-optimal")
MISS = BA.anchors([{"played": {"1": "selector", "2": "selector"},
                    "loss": 14.0, "anchor": True}])
check("a missed transition is a zero", MISS["transitions"] == 0)
check("a missed transition is named",
      MISS["verdict"] == "anchor-transition-missed")
check("no recorded plays is its own verdict",
      BA.anchors([])["verdict"] == "no-recorded-plays")
STAGES = BA.staged([{"stage": "first", "loss": 0.61},
                    {"stage": "later", "loss": 24.52},
                    {"stage": "final", "loss": 5.73}])
check("the late read dominates", STAGES["dominant"] == "later")
check("the dominant share is over three quarters", STAGES["share"] > 0.75)
check("the total is the sum of the stages", close(STAGES["total"], 30.86))
check("the first read is reported beside the total",
      close(STAGES["first"], 0.61))
check("a late-read pattern is named",
      STAGES["verdict"] == "late-read-dominates")
check("a first-read pattern is named",
      BA.staged([{"stage": "first", "loss": 5},
                 {"stage": "later", "loss": 1}])["verdict"] == "first-read-dominates")
check("no stages is its own verdict", BA.staged([])["verdict"] == "no-stages")
check("the routing gain reaches one quarter at certainty",
      close(BA.routing_gain(1.0, 1.0)["gain"], 0.25))
check("routing below chance loses", close(BA.routing_gain(0.3, 0.9)["gain"], -0.08))
check("a loss from routing is named",
      BA.routing_gain(0.3, 0.9)["verdict"] == "routing-hurts")
check("the one-step bound is twice epsilon",
      close(BA.bound(0.25, 4)["one_step"], 0.5))
check("the cumulative bound is linear in looks",
      close(BA.bound(0.25, 4)["cumulative"], 2.0))
check("an empty bound is refused",
      BA.bound(None, 3)["verdict"] == "insufficient-input")
FULL_AUDIT = {"budgets_unpaired": True, "single_budget_claim": True,
              "final_answer_assumed_optimal": True, "aggregate_hides_anchor": True,
              "tokens_unmatched": True, "single_scorer": True,
              "no_value_bound": True}
check("the audit names seven misreadings",
      len(BA.audit(FULL_AUDIT)["findings"]) == 7)
check("an empty record passes the audit",
      kinds(BA.audit({})) == ["audit-conditions-met"])
check("the audit reports completion", BA.audit({})["verdict"] == "audit-complete")
check("an empty harness profile misses all seven habits",
      len(BA.advise({})["findings"]) == 7)
check("a complete harness profile is clean",
      BA.advise({k: True for k in ("pairs_looks_with_budget",
                                   "reports_per_step_loss",
                                   "scores_the_final_answer_separately",
                                   "audits_the_anchor_subset",
                                   "matches_tokens_across_arms",
                                   "cross_checks_the_scorer",
                                   "states_a_value_bound")})["findings"] == [])

# ---- 2. user-simulator meta-evaluation (arXiv:2611.24892) --------------
P = SA.paired([{"control": 0.70, "perturbed": 0.66}] * 5)
check("a constant decrease is the mean", close(P["mean"], 0.04))
check("a constant decrease has no spread", close(P["stderr"], 0.0))
check("a constant decrease is detected", P["detected"] is True)
check("the win rate is one", close(P["win_rate"], 1.0))
check("a detected perturbation is named", P["verdict"] == "detected")
N = SA.paired([{"control": 1.0, "perturbed": 0.0},
               {"control": 0.0, "perturbed": 1.0}])
check("a cancelling pair has a zero mean", close(N["mean"], 0.0))
check("an interval that touches zero is not detection",
      N["detected"] is False and N["ci_low"] < 0)
check("ties count as half a win in the pair rate", close(N["win_rate"], 0.5))
check("no pairs is its own verdict", SA.paired([])["verdict"] == "no-pairs")
POP = SA.population([0.5, 1.0, 2.0])
check("the population rule uses the 2.5th percentile",
      close(POP["p2_5"], 0.525))
check("a positive percentile detects", POP["detected"] is True)
NEG = SA.population([-1.0, 1.0, 2.0])
check("a percentile below zero is not detection",
      close(NEG["p2_5"], -0.9) and NEG["detected"] is False)
check("no draws is its own verdict", SA.population([])["verdict"] == "no-draws")
ROWS = [{"suite": "ours", "perturbation": "p%d" % i, "detected": True}
        for i in range(10)]
ROWS += [{"suite": "arena", "perturbation": "p%d" % i, "detected": i < 6}
         for i in range(10)]
COV = SA.coverage(ROWS)
check("ten perturbations are counted", COV["perturbations"] == 10)
check("the proposed suite detects all ten", COV["suites"]["ours"]["detected"] == 10)
check("the external suite detects six", COV["suites"]["arena"]["detected"] == 6)
check("the misses are named by perturbation",
      COV["suites"]["arena"]["missed"] == ["p6", "p7", "p8", "p9"])
check("full coverage is named", COV["complete"] is True)
check("a partial suite is a coverage gap",
      SA.coverage([{"suite": "x", "perturbation": "p", "detected": False}])
      ["verdict"] == "coverage-gap")
AUC = SA.auroc([{"score": 0.9, "positive": True}, {"score": 0.8, "positive": True},
                {"score": 0.2, "positive": False},
                {"score": 0.1, "positive": False}])
check("a perfect ranking has AUROC one", close(AUC["auroc"], 1.0))
check("a perfect ranking discriminates", AUC["verdict"] == "discriminates")
check("a reversed ranking has AUROC zero",
      close(SA.auroc([{"score": 0.1, "positive": True},
                      {"score": 0.9, "positive": False}])["auroc"], 0.0))
check("a tie counts half",
      close(SA.auroc([{"score": 0.5, "positive": True},
                      {"score": 0.5, "positive": False}])["auroc"], 0.5))
check("one class cannot be scored",
      SA.auroc([{"score": 0.5, "positive": True}])["verdict"] == "one-class-only")
R = SA.retention([{"control": 0.9, "perturbed": 0.1},
                  {"control": 0.8, "perturbed": 0.2},
                  {"control": 0.7, "perturbed": 0.3}])
check("a separating filter keeps every control", close(R["retained"], 1.0))
check("a separating filter is named", R["verdict"] == "filters")
R2 = SA.retention([{"control": 0.1, "perturbed": 0.9},
                   {"control": 0.2, "perturbed": 0.8},
                   {"control": 0.3, "perturbed": 0.7}])
check("a reversed filter keeps none", close(R2["retained"], 0.0))
check("a filter that drops controls is named",
      R2["verdict"] == "discards-controls")
LEV = SA.levels({"l1": 47, "l2": 87, "l3": 83})
check("the headline is the geometric mean", close(LEV["headline"], 69.7533496, 1e-6))
check("the headline rounds to the paper's seventy",
      round(LEV["headline"]) == 70)
check("the weakest level is named", LEV["weakest"] == "l1")
check("the spread is reported", close(LEV["spread"], 40.0))
check("the levels are named", LEV["verdict"] == "levels-reported")
check("a missing level is refused",
      SA.levels({"l1": 47, "l2": 87})["verdict"] == "incomplete-levels")
check("a zero level is refused", SA.levels({"l1": 0, "l2": 1, "l3": 1})
      ["verdict"] == "zero-level")
SIMS = SA.simulators([{"name": "arena", "l1": 57, "l2": 79, "l3": 74},
                      {"name": "sonnet", "l1": 47, "l2": 87, "l3": 83}])
check("the L1 leader is the arena simulator", SIMS["leaders"]["l1"] == "arena")
check("the L2 leader is the sonnet simulator", SIMS["leaders"]["l2"] == "sonnet")
check("no simulator leads every level", SIMS["single_leader"] is False)
check("the split is named", SIMS["verdict"] == "no-simulator-leads-all")
ONE = SA.simulators([{"name": "a", "l1": 9, "l2": 9, "l3": 9},
                     {"name": "b", "l1": 1, "l2": 1, "l3": 1}])
check("one simulator can lead every level", ONE["single_leader"] is True)
check("no simulators is its own verdict",
      SA.simulators([])["verdict"] == "no-simulators")
check("a level without its reference ranking is incomplete",
      "l1-reference-ranking" in SA.evidence({})["missing"])
check("a level without workspace evidence is incomplete",
      "l3-workspace-evidence" in SA.evidence({})["missing"])
check("complete evidence is named",
      SA.evidence({"has_reference_ranking": True,
                   "has_real_user_population": True,
                   "has_workspace_evidence": True})["verdict"] == "evidence-complete")
check("the audit names seven misreadings",
      len(SA.audit({"population_only": True,
                    "composite_beats_control": True,
                    "sensitivity_implies_filtering": True,
                    "single_level_headline": True,
                    "no_real_user_positive_class": True,
                    "any_metric_is_enough": True,
                    "no_human_ceiling": True})["findings"]) == 7)
check("an empty record passes the simulator audit",
      kinds(SA.audit({})) == ["audit-conditions-met"])
check("an empty harness profile misses all seven habits",
      len(SA.advise({})["findings"]) == 7)
check("a complete harness profile is clean",
      SA.advise({k: True for k in ("perturbs_a_known_failure",
                                   "uses_paired_comparisons",
                                   "requires_an_interval_below_zero",
                                   "reports_population_and_trace_levels",
                                   "reports_filtering_beside_sensitivity",
                                   "keeps_all_levels_visible",
                                   "uses_real_traces_as_positives")})["findings"] == [])

# ---- 3. executable program judges (arXiv:2611.24849) ------------------
check("off subject is grade zero",
      PJ.answers({"on_subject": False})["grade"] == 0)
check("on subject without an answer is grade one",
      PJ.answers({"on_subject": True})["grade"] == 1)
check("an exact dedicated answer is grade three",
      PJ.answers({"on_subject": True, "some_answer": True,
                  "exact_answer": True, "dedicated": True})["grade"] == 3)
check("an answer without dedication is grade two",
      PJ.answers({"on_subject": True, "some_answer": True,
                  "exact_answer": True})["grade"] == 2)
check("the answers are echoed for inspection",
      PJ.answers({"on_subject": True})["answers"]["on_subject"] is True)
check("three and two and three floor to two",
      PJ.consensus([3, 2, 3])["label"] == 2)
check("a near-uniform low set floors to zero",
      PJ.consensus([0, 0, 1])["label"] == 0)
check("one and one and two floors to one",
      PJ.consensus([1, 1, 2])["label"] == 1)
check("unanimous grades keep their value", PJ.consensus([3, 3, 3])["label"] == 3)
check("unanimous grades have no disagreement",
      close(PJ.consensus([3, 3, 3])["disagreement"], 0.0))
check("the mean is reported beside the label",
      close(PJ.consensus([3, 2, 3])["mean"], 2.6666667, 1e-6))
check("no grades is its own verdict", PJ.consensus([])["verdict"] == "no-grades")
check("the averaging ablation uses the first program",
      PJ.single([1, 3, 3])["label"] == 1)
check("the ablation is named", PJ.single([1])["verdict"] == "single-program")
check("the rubric takes the highest level that passes",
      PJ.rubric([{"level": 1, "pass": True}, {"level": 2, "pass": True},
                 {"level": 3, "pass": False}])["grade"] == 2)
check("a failed floor sets the grade to zero",
      PJ.rubric([{"level": 1, "pass": False},
                 {"level": 2, "pass": True}])["grade"] == 0)
check("a failed floor is named",
      PJ.rubric([{"level": 1, "pass": False}])["verdict"] == "floor-failed")
check("no criteria is its own verdict",
      PJ.rubric([])["verdict"] == "no-criteria")
ERR = PJ.errors([{"nist": 0, "label": 3}, {"nist": 3, "label": 0},
                 {"nist": 2, "label": 2}])
check("exact agreement is a share", close(ERR["exact"], 1 / 3))
check("two-or-more off is a share", close(ERR["gross"], 2 / 3))
check("a missed top grade is counted", close(ERR["top_missed"], 1 / 3))
check("an over-graded zero is counted", close(ERR["over_graded"], 1 / 3))
check("the mean signed difference is reported", close(ERR["mean_diff"], 0.0))
check("perfect labels have no gross errors",
      close(PJ.errors([{"nist": 2, "label": 2}])["gross"], 0.0))
check("an identical ranking has tau one",
      close(PJ.kendall([{"reference": 1, "method": 1},
                        {"reference": 2, "method": 2},
                        {"reference": 3, "method": 3}])["tau"], 1.0))
check("a reversed ranking has tau minus one",
      close(PJ.kendall([{"reference": 1, "method": 3},
                        {"reference": 2, "method": 2},
                        {"reference": 3, "method": 1}])["tau"], -1.0))
check("one swap costs two thirds of the agreement",
      close(PJ.kendall([{"reference": 1, "method": 1},
                        {"reference": 2, "method": 3},
                        {"reference": 3, "method": 2}])["tau"], 1 / 3))
check("a tau above point eight is named agreement",
      PJ.kendall([{"reference": 1, "method": 2},
                  {"reference": 2, "method": 1}])["verdict"] == "ranking-disagrees")
check("one pair cannot be scored",
      PJ.kendall([{"reference": 1, "method": 1}])["verdict"] == "no-pairs")
CURVE = PJ.label_gain([{"labels": 0, "alpha": 0.613},
                       {"labels": 4, "alpha": 0.694},
                       {"labels": 16, "alpha": 0.756}])
check("the first four labels carry over half the gain",
      CURVE["share"] > 0.5 and close(CURVE["early_gain"], 0.081))
check("the early-gain pattern is named", CURVE["verdict"] == "most-gain-early")
check("a late gain is named",
      PJ.label_gain([{"labels": 0, "alpha": 0.50},
                     {"labels": 4, "alpha": 0.55},
                     {"labels": 16, "alpha": 0.80}])["verdict"] == "gain-comes-late")
check("an incomplete label curve is refused",
      PJ.label_gain([{"labels": 0, "alpha": 0.5}])["verdict"] == "incomplete-curve")
BE = PJ.break_even(0.30, 0.0015)
check("the break-even is the ratio of costs", close(BE["documents"], 200.0))
check("the first cheaper depth is the ceiling", BE["cheaper_beyond"] == 200)
check("a shallow break-even favours the programs",
      BE["verdict"] == "fixed-cost-wins-beyond")
check("a deep break-even favours the judge",
      PJ.break_even(0.49, 0.001)["verdict"] == "per-document-judge-cheaper")
check("an allowed program passes the policy",
      PJ.policy("import re, json\nfrom collections import Counter")["verdict"]
      == "policy-ok")
check("an unknown import is a violation",
      [v["name"] for v in PJ.policy("import os")["violations"]] == ["os"])
check("a file open is banned", "open(" in
      [v["name"] for v in PJ.policy("x = open('a')")["violations"]])
check("the toolkit import is allowed",
      PJ.policy("from pilot import judgekit as jk")["verdict"] == "policy-ok")
check("the imports are listed",
      PJ.policy("import re\nimport json")["imports"] == ["json", "re"])
check("an eval call is banned", "eval(" in
      [v["name"] for v in PJ.policy("eval('1')")["violations"]])
check("the audit names seven misreadings",
      len(PJ.audit({"single_program": True, "rounds_to_nearest": True,
                    "labels_are_bm25_top": True, "one_global_program": True,
                    "no_gaming_check": True, "ranks_the_best_runs": True,
                    "open_weight_writer_assumed": True})["findings"]) == 7)
check("an empty record passes the judge audit",
      kinds(PJ.audit({})) == ["audit-conditions-met"])
check("an empty harness profile misses all seven habits",
      len(PJ.advise({})["findings"]) == 7)
check("a complete harness profile is clean",
      PJ.advise({k: True for k in ("writes_the_judge_once_per_topic",
                                   "keeps_the_scale_outside_the_program",
                                   "averages_independent_programs",
                                   "rounds_according_to_measured_bias",
                                   "spends_labels_on_every_grade",
                                   "checks_a_second_metric_beside_agreement",
                                   "reports_the_cost_curve")})["findings"] == [])

# ---- summary ----------------------------------------------------------
passed = sum(1 for r in RESULTS if r)
print("\n%d/%d checks passed" % (passed, len(RESULTS)))
sys.exit(0 if passed == len(RESULTS) else 1)
