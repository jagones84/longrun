#!/usr/bin/env python3
"""v1215 — red-team coverage, purple loop, render defense (round 146).

Sources:
  * arXiv:2611.24313 "AUTOPI" — the three-level taxonomy, coverage at each
    level, concentration, Jaccard distance, ASR@k, equal-sample and equal-cost
    comparison, label validation, and the audit's misreadings.
  * arXiv:2611.24362 "PIPETTE" — strategy primitives from sparse dictionary
    learning, the explainability score and its bands, the coverage reward, the
    rolling dictionary's collapse test, reward standardisation, the ASR/UA/BU
    requirements, train-time vs worst-case ASR, and the component ablation.
  * arXiv:2611.24231 "What Survives the Shift from Text to Pixels?" — the three
    operations, per-model and per-operation deltas, aggregation that hides an
    operation, the utility ratio, rendering settings, candidate budgets, the
    reading/following dissociation, and trusted authorization.

Deterministic: plain data in, dicts out; no model, no network, no server.

Run: python3 tests/acceptance/v1215_coverage_purple_render.py
"""
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="sf-v1215-")
for _key in ("CONFIG_DIR", "SESSIONS_DIR", "GRAPH_DIR", "EDITS_DIR",
             "RUNS_DIR", "DATA_DIR", "THREADS_DIR", "COSTS_DIR", "MEMORY_DIR"):
    os.environ["LONGRUN_" + _key] = os.path.join(TMP, _key)
    os.makedirs(os.environ["LONGRUN_" + _key], exist_ok=True)
os.environ["LONGRUN_DB"] = os.path.join(TMP, "events.db")
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.harness.checks import redteam_coverage as RC  # noqa: E402
from longrun.harness.checks import purple_loop as PL  # noqa: E402
from longrun.harness.checks import render_defense as RD  # noqa: E402

RESULTS = []


def check(name, ok, detail=""):
    RESULTS.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name
          + ((" :: " + str(detail)) if detail else ""))


def close(a, b, tol=1e-9):
    return a is not None and abs(a - b) <= tol


def kinds(out):
    return [f["kind"] for f in (out.get("findings") or [])]


# ---- 1. red-team coverage (AUTOPI) -------------------------------------
UNITS = ([{"id": "F%d" % i, "name": "class %d" % i, "level": "class"}
          for i in range(6)]
         + [{"id": "T%d" % i, "name": "tech %d" % i, "level": "technique"}
            for i in range(34)]
         + [{"id": "S%d" % i, "name": "sub %d" % i, "level": "sub_technique"}
            for i in range(132)])
tax = RC.taxonomy(UNITS)
check("a full three-level taxonomy is valid", tax["verdict"] == "taxonomy-valid")
check("the counts are per level",
      tax["counts"] == {"class": 6, "technique": 34, "sub_technique": 132})
check("a duplicate id is named",
      RC.taxonomy(UNITS + [{"id": "T0", "name": "x", "level": "technique"}])
      ["verdict"] == "taxonomy-incomplete")
check("an unnamed unit is named",
      RC.taxonomy([{"id": "a", "level": "class"}])["unnamed"] == ["a"])
check("a missing level is named",
      RC.taxonomy([{"id": "a", "name": "A", "level": "class"}])["missing_levels"]
      == ["technique", "sub_technique"])

successes = ([{"class": "F%d" % (i % 6), "technique": "T%d" % i,
               "sub_technique": "S%d" % i} for i in range(31)])
cov = RC.coverage(successes, {"class": 6, "technique": 34, "sub_technique": 132})
check("31 successes can cover 31 techniques", cov["covered"]["technique"] == 31)
check("the technique rate is covered over total",
      close(cov["rates"]["technique"], 31 / 34))
check("all six classes are covered", cov["covered"]["class"] == 6)
check("coverage is measured when denominators exist", cov["verdict"] == "coverage-measured")
check("a missing denominator is named",
      RC.coverage(successes, {})["verdict"] == "denominator-missing")

conc = RC.concentration([{"technique": "authority"}] * 99
                        + [{"technique": "urgency"}])
check("99 of 100 successes on one technique is concentrated",
      conc["verdict"] == "concentrated")
check("the reported share is 0.99", close(conc["max_share"], 0.99))
check("an even spread is not concentrated",
      RC.concentration([{"technique": t} for t in ("a", "b", "c", "d")] * 3)
      ["verdict"] == "spread")
check("the top three are ranked", len(conc["top"]) == 2)

jac = RC.jaccard([{"technique": ["a", "b"]}, {"technique": ["b", "c"]}])
check("one shared of three is distance 2/3", close(jac["distance"], 2 / 3))
check("identical sets are distance 0",
      close(RC.jaccard([{"technique": ["a"]}, {"technique": ["a"]}])["distance"], 0.0))
check("disjoint sets are distance 1",
      close(RC.jaccard([{"technique": ["a"]}, {"technique": ["b"]}])["distance"], 1.0))
check("a diverse attacker clears the threshold",
      RC.jaccard([{"technique": ["a", "b"]}, {"technique": ["c", "d"]}])["verdict"]
      == "diverse")

attempts = [{"scenario": str(i), "success_at": (1 if i == 0 else 3 if i == 1 else
                                               5 if i == 2 else None)}
            for i in range(10)]
a1 = RC.asr_at_k(attempts, 1)
check("one hit at k=1 is ASR 0.1", close(a1["asr"], 0.1))
check("the curve keeps only budgets up to k", list(a1["curve"]) == ["1"])
a4 = RC.asr_at_k(attempts, 4)
check("two hits by k=4 is ASR 0.2", close(a4["asr"], 0.2))
check("the curve tracks each budget", a4["curve"] == {"1": 0.1, "2": 0.1, "4": 0.2})
check("the mean attempts to success is reported", close(a4["mean_attempts_to_success"], 2.0))
check("a miss beyond the budget counts as a miss", a4["successes"] == 2)
check("no scenarios is not a measurement",
      RC.asr_at_k([], 1)["verdict"] == "no-scenarios")

eq = RC.equal_sample([{"technique": ["a"]}, {"technique": ["b"]},
                      {"technique": ["c"]}, {"technique": ["d"]}], 2)
check("two disjoint successes cover two units", close(eq["mean_units"], 2.0))
check("every pair is enumerated", eq["subsets"] == 6)
eq3 = RC.equal_sample([{"technique": ["a", "b"]}, {"technique": ["a"]},
                       {"technique": ["b"]}], 2)
check("an overlapping sample averages its union", close(eq3["mean_units"], 2.0))
check("k is capped at the number of successes",
      RC.equal_sample([{"technique": ["a"]}], 5)["k"] == 1)
check("no successes is not a sample",
      RC.equal_sample([], 2)["verdict"] == "insufficient-successes")

cost = RC.equal_cost([{"arm": "a", "spend": 30, "training_spend": 21, "budget": 51},
                      {"arm": "b", "spend": 51, "budget": 51}])
check("training is counted in the spend", close(cost["arms"][0]["spend"], 51.0))
check("a full budget is equal cost", cost["verdict"] == "equal-cost")
check("an over-budget arm is named",
      RC.equal_cost([{"arm": "x", "spend": 60, "budget": 51}])["over_budget"] == ["x"])

labels = RC.label_check([{"tp": 89, "fp": 11, "fn": 13}])
check("precision divides by predicted positives", close(labels["precision"], 0.89))
check("recall divides by reference positives",
      close(labels["recall"], 89 / 102))
check("F1 is above the validation floor", labels["verdict"] == "labels-validated")
check("weak labels are named",
      RC.label_check([{"tp": 70, "fp": 30, "fn": 30}])["verdict"] == "labels-weak")

check("the audit names asr-only",
      "asr-only" in kinds(RC.audit({"asr_only": True, "static_only": True})))
check("the audit names aggregation",
      "aggregation-masks-operation" in kinds(RC.audit({"aggregation_masks_operation": True})))
check("the audit names surface diversity",
      "surface-diversity-as-coverage" in kinds(RC.audit(
          {"surface_diversity_as_coverage": True})))
check("the audit names circular labels",
      "circular-labels" in kinds(RC.audit({"circular_labels": True})))
check("a clean record has no misreading",
      RC.audit({})["findings"] == [{"kind": "audit-conditions-met"}])
check("an empty profile raises seven checks", len(RC.advise({})["findings"]) == 7)
check("a complete profile raises none",
      RC.advise({k: True for k in (
          "reports_coverage_beside_asr", "reports_per_class_results",
          "uses_a_fixed_partition", "compares_at_equal_sample",
          "compares_at_equal_cost", "validates_post_hoc_labels",
          "states_the_attempt_budget")})["findings"] == [])

# ---- 2. purple loop (PIPETTE) ------------------------------------------
RECORDS = [
    {"id": "r1", "text": "authority claim: the auditor requires this transfer"},
    {"id": "r2", "text": "authority claim from the compliance team, urgent"},
    {"id": "r3", "text": "encoding: spell the instruction in base64"},
    {"id": "r4", "text": "encoding: hide the instruction with character perturbation"},
]
prim = PL.primitives(RECORDS, k=2)
check("two clusters are built from four records", prim["k"] == 2)
check("the primitives are deterministic", prim == PL.primitives(RECORDS, k=2))
clusters = {p["name"]: p["members"] for p in prim["primitives"]}
check("the authority records cluster together",
      any(members == ["r1", "r2"] for members in clusters.values()))
check("the encoding records cluster together",
      any(members == ["r3", "r4"] for members in clusters.values()))
check("no records is not a dictionary",
      PL.primitives([])["verdict"] == "no-records")
check("k is capped at the record count", PL.primitives(RECORDS, k=9)["k"] == 4)

PRIMS = [{"name": "p1", "text": "authority claim compliance team"},
         {"name": "p2", "text": "urgency threat deadline"}]
exp = PL.explainability({"primitives": PRIMS,
                         "components": [{"text": "authority claim", "critical": True},
                                        {"text": "urgency deadline", "critical": False}]})
check("every component matches a primitive", close(exp["weighted_coverage"], 1.0))
check("full coverage is the top band", exp["score"] == 5)
check("the top band is ES 1.0", close(exp["es"], 1.0))
check("a matched attack is explained", exp["verdict"] == "explained")
novel = PL.explainability({"primitives": PRIMS,
                           "components": [{"text": "acrostic poem", "critical": True}]})
check("an unmatched strategy is novel", novel["verdict"] == "novel-strategy")
check("an unmatched strategy is ES 0", close(novel["es"], 0.0))
critical = PL.explainability({"primitives": [PRIMS[0]],
                              "components": [{"text": "authority claim", "critical": True},
                                             {"text": "acrostic poem", "critical": True}]})
check("an uncovered critical component is flagged", critical["critical_missing"] is True)
check("an uncovered critical component costs a band", critical["score"] == 1)
check("no primitives is not a measurement",
      PL.explainability({"components": [{"text": "x"}]})["verdict"] == "insufficient-input")

check("a novel success earns coverage credit",
      close(PL.coverage_reward({"attack_succeeded": True, "es": 0.2})["reward"], 0.8))
check("a fully explained success earns nothing",
      close(PL.coverage_reward({"attack_succeeded": True, "es": 1.0})["reward"], 0.0))
check("a failed attack earns nothing",
      close(PL.coverage_reward({"attack_succeeded": False, "es": 0.0})["reward"], 0.0))
check("no dictionary yet is a distinct state",
      PL.coverage_reward({"dictionary_exists": False})["verdict"] == "no-dictionary-yet")

plateau = PL.collapse([{"iteration": i, "es": es}
                       for i, es in enumerate((0.20, 0.21, 0.22, 0.23))])
check("small late gains are a plateau", plateau["verdict"] == "strategy-plateau")
rising = PL.collapse([{"iteration": i, "es": es}
                      for i, es in enumerate((0.20, 0.30, 0.45, 0.60))])
check("a rising series keeps discovering", rising["verdict"] == "keeps-discovering")
check("the total gain is reported", close(rising["gain"], 0.40))
check("a declining series is named",
      PL.collapse([{"iteration": 0, "es": 0.5}, {"iteration": 1, "es": 0.45}])
      ["verdict"] == "coverage-declines")
check("one point is not a series",
      PL.collapse([{"iteration": 0, "es": 0.2}])["verdict"] == "insufficient-series")

REWARDS = {"rollouts": [{"atk": 1, "fmt": 1, "cov": 0.1, "label": "a"},
                        {"atk": 0, "fmt": 1, "cov": 0.5, "label": "b"},
                        {"atk": 1, "fmt": 0, "cov": 0.9, "label": "c"},
                        {"atk": 0, "fmt": 0, "cov": 0.1, "label": "d"}]}
rw = PL.rewards(REWARDS)
check("every reward is standardised before the sum", rw["verdict"] == "reward-standardised")
check("the novel success with the format reward ranks first",
      rw["best"]["label"] == "c", rw["best"])
check("four rollouts are scored", rw["rollouts"] == 4)
check("no rollouts is not a ranking", PL.rewards({})["verdict"] == "no-rollouts")
zero_var = PL.rewards({"rollouts": [{"atk": 1, "fmt": 1, "cov": 0.2},
                                    {"atk": 1, "fmt": 1, "cov": 0.2}]})
check("a zero-variance reward contributes nothing", close(zero_var["scores"][0]["art"], 0.0))

req = PL.requirements({"base": {"asr": 0.4619, "ua": 0.3190, "bu": 0.6186},
                       "trained": {"asr": 0.0143, "ua": 0.5810, "bu": 0.6495}})
check("the paper's ablation endpoint keeps utility",
      req["verdict"] == "robustness-without-utility-loss")
check("benign utility rises by 3.09 points", close(req["bu_delta"], 0.0309, 1e-6))
check("utility under attack rises", close(req["ua_delta"], 0.262, 1e-6))
check("the intermediate arm loses benign utility",
      PL.requirements({"base": {"asr": 0.4619, "ua": 0.3190, "bu": 0.6186},
                       "trained": {"asr": 0.0357, "ua": 0.4548, "bu": 0.5979}})
      ["verdict"] == "robustness-costs-utility")
check("a trained agent that is not more robust is named",
      PL.requirements({"base": {"asr": 0.2, "ua": 0.4, "bu": 0.6},
                       "trained": {"asr": 0.3, "ua": 0.5, "bu": 0.7}})["verdict"]
      == "not-robust")

cmp_ = PL.compare([{"arm": "PISmith", "train_asr": 0.6875, "worst_case_asr": 0.475},
                   {"arm": "RL-Hammer", "train_asr": 0.3339, "worst_case_asr": 0.275}])
check("the stronger red-teamer is not the stronger defender",
      cmp_["verdict"] == "lower-train-asr-more-robust")
check("the strongest trainer is named", cmp_["strongest"] == "PISmith")
check("the most robust arm is named", cmp_["most_robust"] == "RL-Hammer")
check("one arm is not a comparison",
      PL.compare([{"arm": "a", "train_asr": 1, "worst_case_asr": 1}])["verdict"]
      == "insufficient-arms")

ab = PL.ablate([
    {"name": "base", "asr": 0.4619, "ua": 0.3190, "bu": 0.6186},
    {"name": "no-reasoning", "asr": 0.0357, "ua": 0.4548, "bu": 0.5979},
    {"name": "reasoning", "asr": 0.0238, "ua": 0.5690, "bu": 0.6082},
    {"name": "token-reward", "asr": 0.0143, "ua": 0.5810, "bu": 0.6495},
])
check("the reasoning warm-up moves ASR most", ab["decisive"] == "no-reasoning")
check("the token reward restores benign utility", ab["utility_restored"] is True)
check("the ablation has three steps", len(ab["steps"]) == 3)
check("the final ASR drop is reported", close(ab["steps"][-1]["asr_delta"], -0.0095))

check("the audit names asr-only",
      "asr-only" in kinds(PL.audit({"asr_only": True})))
check("the audit names surface diversity",
      "surface-diversity-as-strategy" in kinds(PL.audit(
          {"surface_diversity_as_strategy": True})))
check("the audit names a missing utility measure",
      "no-utility-measured" in kinds(PL.audit({"no_utility_measured": True})))
check("the audit names an unvalidated judge",
      "unvalidated-judge" in kinds(PL.audit({"unvalidated_judge": True})))
check("an empty profile raises eight checks", len(PL.advise({})["findings"]) == 8)
check("a complete profile raises none",
      PL.advise({k: True for k in (
          "reports_coverage_not_only_asr", "rewards_new_strategies",
          "rebuilds_the_dictionary_rolling", "standardises_each_reward",
          "measures_utility_under_attack", "measures_benign_utility",
          "evaluates_unseen_attacks", "validates_the_es_judge")})["findings"] == [])

# ---- 3. render defense (text to pixels) --------------------------------
check("three operations are defined", len(RD.operations()["operations"]) == 3)
check("replacement does not preserve the answer",
      RD.operations()["operations"][2]["answer_preserved"] is False)

mod = RD.modality([
    {"model": "Qwen", "operation": "append", "text_asr": 0.7378, "image_asr": 0.0501},
    {"model": "Qwen", "operation": "format", "text_asr": 0.7172, "image_asr": 0.1135},
    {"model": "Qwen", "operation": "replace", "text_asr": 0.9873, "image_asr": 0.7796},
])
check("the append delta is image minus text",
      close(mod["rows"][0]["delta"], 0.0501 - 0.7378, 1e-9))
check("all three operations fall under rendering",
      mod["verdict"] == "rendering-suppresses")
mixed = RD.modality([
    {"model": "M", "operation": "append", "text_asr": 0.8, "image_asr": 0.1},
    {"model": "M", "operation": "replace", "text_asr": 0.2, "image_asr": 0.3},
])
check("a rising operation makes protection conditional",
      mixed["verdict"] == "rendering-conditional")
check("no measurements is not a verdict",
      RD.modality([])["verdict"] == "no-measurements")

agg = RD.aggregate([
    {"model": "Qwen", "operation": "append", "asr": 0.30},
    {"model": "Qwen", "operation": "format", "asr": 0.30},
    {"model": "Qwen", "operation": "replace", "asr": 0.90},
])
check("the macro average hides the worst operation",
      agg["verdict"] == "aggregation-hides-operation")
check("the hidden model is named", agg["hidden"] == ["Qwen"])
check("the worst operation is named", agg["groups"][0]["worst_operation"] == "replace")
flat = RD.aggregate([{"model": "M", "operation": op, "asr": 0.5 + i * 0.02}
                     for i, op in enumerate(("append", "format", "replace"))])
check("a flat profile is representative", flat["verdict"] == "aggregation-representative")

util = RD.utility([
    {"model": "Qwen", "question": "original", "text_f1": 0.5099, "image_f1": 0.5033},
    {"model": "Qwen", "question": "integration", "text_f1": 0.5922, "image_f1": 0.3671},
])
check("the integration ratio is 61.99%", close(util["rows"][1]["ratio"], 0.6199, 1e-4))
check("an integration loss is named", util["verdict"] == "utility-loss-on-integration")
preserved = RD.utility([
    {"model": "Haiku", "question": "original", "text_f1": 0.5229, "image_f1": 0.5313},
    {"model": "Haiku", "question": "integration", "text_f1": 0.8197, "image_f1": 0.8407},
])
check("a model that keeps utility is named", preserved["verdict"] == "utility-preserved")
check("no measurements is not a utility claim",
      RD.utility([])["verdict"] == "no-measurements")

pres = RD.presentation([
    {"width": 704, "font": 26, "asr": 0.30},
    {"width": 1280, "font": 26, "asr": 0.70},
    {"width": 876, "font": 20, "asr": 0.30},
    {"width": 876, "font": 32, "asr": 0.65},
])
check("a wider page weakens protection",
      "wider-page-weakens-protection" in pres["findings"])
check("larger type weakens protection",
      "larger-type-weakens-protection" in pres["findings"])
check("settings are named as part of the defense",
      pres["verdict"] == "settings-change-protection")
check("one setting is not a comparison",
      RD.presentation([{"width": 704, "font": 20, "asr": 0.3}])["verdict"]
      == "insufficient-settings")

cand = RD.candidates([
    {"model": "Qwen", "operation": "append", "budget": 1, "deficit": -0.3737},
    {"model": "Qwen", "operation": "append", "budget": 8, "deficit": -0.0333},
])
check("eight candidates close the append deficit",
      cand["verdict"] == "search-closes-deficit")
check("the residual is reported", close(cand["rows"][0]["residual"], 0.0333, 1e-9))
some = RD.candidates([
    {"model": "Qwen", "operation": "append", "budget": 1, "deficit": -0.3737},
    {"model": "Qwen", "operation": "append", "budget": 8, "deficit": -0.0333},
    {"model": "GPT", "operation": "append", "budget": 1, "deficit": -0.5000},
    {"model": "GPT", "operation": "append", "budget": 8, "deficit": -0.4000},
])
check("a resistant model keeps the deficit",
      some["verdict"] == "search-closes-some-deficits")
check("the resistant model is named", ("GPT", "append") in some["resistant"])
check("no measurements is not a search result",
      RD.candidates([])["verdict"] == "no-measurements")

read = RD.dissociation([
    {"model": "Qwen", "modality": "image", "report": 0.6686,
     "understand": 0.0667, "execute": 0.0},
])
check("a transcribed but unexecuted command is read-not-followed",
      read["verdict"] == "read-but-not-followed")
blind = RD.dissociation([
    {"model": "M", "modality": "image", "report": 0.02,
     "understand": 0.05, "execute": 0.0},
])
check("low reading and low execution is illegibility-consistent",
      blind["verdict"] == "illegibility-consistent")
ran = RD.dissociation([
    {"model": "Gemini", "modality": "image", "report": 0.9111,
     "understand": 0.9111, "execute": 0.3778},
])
check("execution is named when it happens", ran["verdict"] == "executed")

authz = RD.authorization({"prohibit_asr": 0.10, "permit_asr": 0.55})
check("a trusted permit raises execution",
      authz["verdict"] == "authorization-raises-risk")
check("the delta is reported", close(authz["delta"], 0.45))
check("a flat authorization is inert",
      RD.authorization({"prohibit_asr": 0.4, "permit_asr": 0.42})["verdict"]
      == "authorization-inert")
check("missing rates are not a verdict",
      RD.authorization({})["verdict"] == "insufficient-input")

check("the audit names aggregate-only",
      "aggregate-only" in kinds(RD.audit({"aggregate_only": True})))
check("the audit names answer correctness",
      "answer-correctness-as-security" in kinds(RD.audit(
          {"answer_correctness_as_security": True})))
check("the audit names assumed illegibility",
      "illegibility-assumed" in kinds(RD.audit({"illegibility_assumed": True})))
check("the audit names single-model claims",
      "single-model" in kinds(RD.audit({"single_model": True})))
check("a clean record has no misreading",
      RD.audit({})["findings"] == [{"kind": "audit-conditions-met"}])
check("an empty profile raises seven checks", len(RD.advise({})["findings"]) == 7)
check("a complete profile raises none",
      RD.advise({k: True for k in (
          "reports_by_operation", "reports_by_model", "tests_attack_budgets",
          "measures_utility_on_integration", "separates_reading_from_following",
          "tests_trusted_authorization", "pins_rendering_settings")})["findings"] == [])

# ---- 4. the three modules are independent and pure ---------------------
check("the coverage module names its format", RC.FORMAT == "longrun-redteam-coverage/1")
check("the purple loop names its format", PL.FORMAT == "longrun-purple-loop/1")
check("the render module names its format", RD.FORMAT == "longrun-render-defense/1")
check("coverage has three levels", RC.LEVELS == ("class", "technique", "sub_technique"))
check("the three operations match the paper", RD.OPERATIONS == ("append", "format", "replace"))
check("four thresholds map coverage onto bands two through five",
      len(PL.SCORE_BANDS) == 4)

passed = sum(1 for r in RESULTS if r)
print("\n%d/%d checks passed" % (passed, len(RESULTS)))
sys.exit(0 if passed == len(RESULTS) else 1)
