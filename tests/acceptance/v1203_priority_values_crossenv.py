#!/usr/bin/env python3
"""v1203 — priority criteria, value dispositions, cross-environment tasks (round 134).

Sources:
  * arXiv:2611.22989 "How Web Research Agents Interpret User Priorities" — a
    priority says what to attend to, not how to judge; focus is not criteria.
  * arXiv:2611.23067 "Values Shape What Self-Improving Coding Agents Build" — a
    short fixed value statement changes performance and the solution built.
  * arXiv:2611.22777 "CrossEnv" — cross-environment tasks need aligned data,
    joint executable rules, reference replay and a structural curriculum.

Deterministic: plain data in, dicts out; no model, no network, no server.

Run: python3 tests/acceptance/v1203_priority_values_crossenv.py
"""
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="sf-v1203-")
for _key in ("CONFIG_DIR", "SESSIONS_DIR", "GRAPH_DIR", "EDITS_DIR",
             "RUNS_DIR", "DATA_DIR", "THREADS_DIR", "COSTS_DIR", "MEMORY_DIR"):
    os.environ["LONGRUN_" + _key] = os.path.join(TMP, _key)
    os.makedirs(os.environ["LONGRUN_" + _key], exist_ok=True)
os.environ["LONGRUN_DB"] = os.path.join(TMP, "events.db")
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.harness import priority_criteria as PC   # noqa: E402
from longrun.harness import value_disposition as VD   # noqa: E402
from longrun.harness import cross_env_tasks as CE     # noqa: E402

RESULTS = []


def check(name, ok, detail=""):
    RESULTS.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name
          + ((" :: " + str(detail)) if detail else ""))


def kinds(out):
    return [f["kind"] for f in (out.get("findings") or [])]


# ---- 1. priority criteria -------------------------------------------------
check("a priority that names an aspect but not its measure leaves the criterion implicit",
      "criterion-implicit" in kinds(
          PC.priority("give special attention to long-term growth potential")))
check("an empty priority is refused",
      "priority-unstated" in kinds(PC.priority("")))
check("a priority with no nameable aspect is refused",
      "priority-uninterpretable" in kinds(PC.priority("do a good job")))
p1 = PC.priority("give special attention to long-term growth potential, measured by revenue growth")
check("a priority that states its measure is not implicit",
      "criterion-implicit" not in kinds(p1), p1)

r1 = PC.report({"requested": "growth", "focus": "growth",
                "criteria": ["risk-adjusted"], "pick": "microsoft",
                "criteria_origin": "agent"})
check("an adopted focus with criteria is recorded, with no negative finding",
      "focus-adopted" in kinds(r1) and "criterion-origin-unmarked" not in kinds(r1), r1)
check("a report with no criteria is named",
      "focus-without-criteria" in kinds(PC.report({"requested": "growth", "focus": "growth"})))
check("a pick with no grounds is named",
      "pick-without-grounds" in kinds(
          PC.report({"requested": "growth", "focus": "growth", "pick": "microsoft"})))
check("an unmarked criterion origin is named",
      "criterion-origin-unmarked" in kinds(
          PC.report({"requested": "growth", "focus": "growth", "criteria": ["risk"]})))
check("a focus that departs from the request is named",
      "focus-not-adopted" in kinds(
          PC.report({"requested": "growth", "focus": "resilience", "criteria": ["cycles"]})))
check("a report that marks the criterion origin is accepted",
      "criterion-origin-unmarked" not in kinds(
          PC.report({"requested": "growth", "focus": "growth", "criteria": ["risk"],
                     "criteria_origin": "agent"})))

t1 = PC.trace({"criterion": "credit ratings", "search": True, "citation": True, "judgement": True})
check("a criterion traced through every step is fully traced",
      "criterion-fully-traced" in kinds(t1), t1)
t2 = PC.trace({"criterion": "credit ratings", "search": True, "judgement": True})
check("a criterion absent from the citations is named",
      "criterion-not-in-citation" in kinds(t2), t2)
t3 = PC.trace({"criterion": "credit ratings", "search": True})
check("a criterion that never reaches the judgement is named",
      "criterion-not-in-judgement" in kinds(t3), t3)
check("a search about a criterion without a supporting source is named",
      "search-not-grounding" in kinds(
          PC.trace({"criterion": "credit ratings", "search": True, "citation": True,
                    "judgement": True, "searches": True})))

cmp = PC.compare([
    {"focus": "growth", "pick": "microsoft", "criteria": ["risk-adjusted"]},
    {"focus": "growth", "pick": "alphabet", "criteria": ["growth rate"]},
])
check("the same focus with opposite picks is named",
      "opposite-answers-same-focus" in kinds(cmp), cmp)
check("the same focus does not reveal the criteria",
      "focus-does-not-reveal-criteria" in kinds(cmp), cmp)
cmp2 = PC.compare([
    {"focus": "resilience", "pick": "microsoft", "criteria": ["cycles"]},
    {"focus": "resilience", "pick": "microsoft", "criteria": ["credit ratings"]},
])
check("the same answer on different reasons is named",
      "same-answer-different-reasons" in kinds(cmp2), cmp2)

ev1 = PC.evidence({"cited_distinct": 9, "top_documents_citation_share": 0.94,
                   "source_overlap": 0.05, "search_wording_differs": False})
check("a narrow source base is named", "narrow-source-base" in kinds(ev1), ev1)
check("low overlap across runs is named", "evidence-overlap-low" in kinds(ev1), ev1)
check("a priority that never reaches the queries is named",
      "search-wording-invariant" in kinds(ev1), ev1)
check("a priority that changes the queries is named",
      "search-wording-differs" in kinds(PC.evidence({"search_wording_differs": True})))

rev = PC.revise({"criteria_shown": True, "criteria_editable": True,
                 "origin_marked": True, "evidence_linked": True})
check("a reviewable interface is valid", rev["findings"] == [], rev)
check("a hidden criterion is named",
      "criteria-not-shown" in kinds(PC.revise({"criteria_editable": True})))
check("an uneditable criterion is named",
      "criteria-not-editable" in kinds(PC.revise({"criteria_shown": True})))
check("the priority advisor names six failure modes",
      len(PC.advise({})["findings"]) == 6, PC.advise({}))

# ---- 2. value dispositions ------------------------------------------------
check("a short fixed paired value statement is valid",
      VD.statement("prefer the bold transformation over the safe incremental tweak",
                   value="openness")["findings"] == [])
check("an empty value is refused", "value-missing" in kinds(VD.statement("")))
check("an unknown value is refused",
      "unknown-value" in kinds(VD.statement("be bold", value="boldness")))
check("an over-long value is refused",
      "value-too-long" in kinds(VD.statement("x", value="openness", words=130)))
check("a value that changes within a run is refused",
      "value-not-fixed" in kinds(VD.statement("be bold", value="openness", fixed=False)))
check("an unpaired value is refused",
      "value-unpaired" in kinds(VD.statement("be bold", value="openness", paired=False)))
check("a value written as a recipe is refused",
      "value-is-a-recipe" in kinds(
          VD.statement("step 1: always call the function", value="openness")))

VALS = [{"value": "openness", "delta": 0.38, "placebo_delta": 0.06},
        {"value": "conservation", "delta": -0.27, "placebo_delta": -0.06},
        {"value": "openness", "versus": "conservation", "pair_delta": 0.58},
        {"value": "openness", "delta": 0.50, "placebo_delta": 0.50}]
vc = VD.compare(VALS)
check("openness above the control is named", "openness-above-control" in kinds(vc), vc)
check("conservation below the control is named", "conservation-below-control" in kinds(vc), vc)
check("the opposing pair is compared", "opposing-values-differ" in kinds(vc), vc)
check("a same-length placebo effect is named", "placebo-effect" in kinds(vc), vc)
check("no effect at all is named",
      "no-value-effect" in kinds(VD.compare([{"value": "openness", "delta": 0.0,
                                              "placebo_delta": 0.0}])))

SOL = [{"value": "openness", "size": 900, "size_above_control": True, "approach": "graph-cut search",
        "nearest_neighbour_same_value": True, "algorithm_differs": True},
       {"value": "conservation", "size": 300, "size_below_control": True,
        "approach": "column-based search"}]
so = VD.solutions(SOL)
check("openness builds larger solvers", "openness-builds-larger" in kinds(so), so)
check("conservation builds smaller solvers", "conservation-builds-smaller" in kinds(so), so)
check("a value with a named approach is recorded", "value-shapes-approach" in kinds(so), so)
check("solutions cluster by value", "solutions-cluster-by-value" in kinds(so), so)
check("a different algorithm is named", "algorithm-differs" in kinds(so), so)

ov = VD.oversight({"self_modifying": True, "best_value_fell": True,
                   "literature_derived": True, "values_trend_cautious": True,
                   "reframed": True, "original_outperforms": True, "model_tier": "small"})
check("self-modification is named", "self-modified-values" in kinds(ov), ov)
check("self-modification converging to the middle is named",
      "self-modification-converges-to-middle" in kinds(ov), ov)
check("literature-derived values are named", "literature-derived-values" in kinds(ov), ov)
check("the conservative trend of derived values is named",
      "literature-trends-conservation" in kinds(ov), ov)
check("framing is named", "framing-matters" in kinds(ov), ov)
check("a cheaper model degrading the effect is named",
      "cheaper-model-degrades" in kinds(ov), ov)
check("the missing human value review is named",
      "no-human-value-review" in kinds(VD.oversight({})))

pr = VD.progress([{"spread": 0.50, "open_ended": True},
                  {"spread": 1.50, "fixed_engine_spread": 0.70}])
check("values compounding across iterations are named", "values-compound" in kinds(pr), pr)
check("an open-ended solver strengthening the effect is named",
      "open-ended-strengthens-effect" in kinds(pr), pr)
check("a fixed engine narrowing the effect is named",
      "fixed-engine-narrows-effect" in kinds(pr), pr)
check("the value advisor names six failure modes",
      len(VD.advise({})["findings"]) == 6, VD.advise({}))

# ---- 3. cross-environment tasks ------------------------------------------
SPEC = {"environments": ["flight", "hotel", "dining"], "shared_entity": "person",
        "dependency": "arrival time guides the reservation", "joint_verification": True,
        "reference_execution": ["search", "book", "reserve"]}
check("a three-environment task with a joint rule is valid",
      CE.task(SPEC)["findings"] == [], CE.task(SPEC))
check("a single-environment task is not cross-environment",
      "single-environment" in kinds(CE.task({**SPEC, "environments": ["flight"]})))
check("a task with no shared entity is refused",
      "no-shared-entity" in kinds(CE.task({**SPEC, "shared_entity": ""})))
check("a task with no cross-environment dependency is refused",
      "no-dependency" in kinds(CE.task({**SPEC, "dependency": ""})))
check("independent checks are not joint verification",
      "no-joint-verification" in kinds(CE.task({**SPEC, "joint_verification": False})))
check("a task with no reference execution is refused",
      "no-reference-execution" in kinds(CE.task({**SPEC, "reference_execution": []})))

ALIGN_OK = [{"entity": "hotel", "id": "h1", "value": "addr-1"},
            {"entity": "hotel", "id": "h1", "value": "addr-1"}]
check("consistent records are aligned", CE.align(ALIGN_OK)["findings"] == [], CE.align(ALIGN_OK))
al = CE.align([{"entity": "hotel", "id": "h1", "value": "addr-1"},
               {"entity": "hotel", "id": "h1", "value": "addr-2"}])
check("the same record with two values is inconsistent",
      "inconsistent-entity" in kinds(al), al)
check("a record the agent must create cannot be pre-inserted",
      "premature-record" in kinds(
          CE.align([{"entity": "booking", "id": "b1", "must_create": True,
                     "present_initial": True}])))
check("a required record missing from the initial and earlier state is named",
      "missing-record" in kinds(
          CE.align([{"entity": "room", "id": "r1", "required": True,
                     "present_initial": False, "produced_earlier": False}])))

RULES = {"rules": [{"checks": "output", "executable": True},
                   {"checks": "state", "executable": True},
                   {"checks": "cross-env", "executable": True}],
         "negative_cases": True, "rules_reject_incomplete": True}
check("rules covering outputs, state and the joint link are valid",
      CE.rules(RULES)["findings"] == [], CE.rules(RULES))
ru = CE.rules({"rules": [{"checks": "output", "executable": True}], "negative_cases": True})
check("missing state rules are named", "rule-checks-state-missing" in kinds(ru), ru)
check("missing joint rules are named", "rule-checks-cross-env-missing" in kinds(ru), ru)
check("a non-executable rule is refused",
      "rules-not-executable" in kinds(
          CE.rules({**RULES, "rules": [{"checks": "output", "executable": False}]})))
check("a missing negative case is named",
      "negative-case-missing" in kinds(CE.rules({**RULES, "negative_cases": False})))
check("rules that pass an incomplete outcome are refused",
      "rules-accept-incomplete" in kinds(
          CE.rules({**RULES, "rules_reject_incomplete": False})))

check("a reproducible replay with two successes is accepted",
      "accepted" in kinds(CE.validate({"reference_replay": True,
                                       "agent_attempts": 5, "agent_successes": 2})))
check("a failed replay is named",
      "reference-replay-failed" in kinds(CE.validate({"reference_replay": False,
                                                      "agent_successes": 2})))
check("fewer than two successes is named",
      "agent-attempts-insufficient" in kinds(CE.validate({"reference_replay": True,
                                                          "agent_attempts": 5,
                                                          "agent_successes": 1})))

LEVELS = [{"level": 1, "environments": 1, "retention_checked": True},
          {"level": 2, "environments": 2, "retention_checked": True},
          {"level": 3, "environments": 3, "retention_checked": True},
          {"level": 4, "environments": 3, "retention_checked": True},
          {"level": 5, "environments": 3, "user_interaction": True, "retention_checked": True}]
check("a monotone structural curriculum is valid",
      CE.curriculum(LEVELS)["findings"] == [], CE.curriculum(LEVELS))
check("a curriculum whose environment count falls is named",
      "non-monotone-curriculum" in kinds(
          CE.curriculum([{"level": 1, "environments": 3}, {"level": 2, "environments": 2}])))
check("a curriculum that starts with coordination is named",
      "no-single-environment-foundation" in kinds(
          CE.curriculum([{"level": 1, "environments": 2}])))
check("user interaction introduced too early is named",
      "user-interaction-too-early" in kinds(
          CE.curriculum([{"level": 1, "environments": 1, "user_interaction": True},
                         {"level": 2, "environments": 2}])))
check("an unchecked retention is named",
      "retention-unchecked" in kinds(CE.curriculum([{"level": 1, "environments": 1}])))

ME = [{"arm": "crossenv", "score": 23.6, "records": 2954},
      {"arm": "baseline", "score": 21.5, "records": 11572},
      {"pair": "unseen", "success_delta": 16.0},
      {"arm": "curriculum", "success": 0.6, "gpu_hours": 100},
      {"arm": "mixed", "success": 0.4, "gpu_hours": 100}]
mm = CE.measure(ME)
check("fewer records winning is named", "fewer-records-wins" in kinds(mm), mm)
check("transfer to unseen combinations is named", "unseen-transfer" in kinds(mm), mm)
check("curriculum beating mixed at matched compute is named",
      "curriculum-beats-mixed" in kinds(mm), mm)
check("the cross-env advisor names six failure modes",
      len(CE.advise({})["findings"]) == 6, CE.advise({}))

# ---- result ---------------------------------------------------------------
passed = sum(1 for r in RESULTS if r)
print("\n%d/%d checks passed" % (passed, len(RESULTS)))
sys.exit(0 if passed == len(RESULTS) else 1)
