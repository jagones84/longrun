#!/usr/bin/env python3
"""v1219 — requirement loop, secure replanning, local cost (round 150).

Sources:
  * arXiv:2611.24924 "AHE-Beta" — issue normalisation, Triage dispositions,
    architect consolidation with two sources and `covers`, admission's evidence
    package and exclusions, the design/code review gates and the head-bound
    merge, the issue-flow counts, delivery vs pass, and the generalisation share.
  * arXiv:2611.24839 "Kaer" — the seven repair operators, the four validity
    conditions plus the grant rule, the failure vocabulary, the repair budget and
    rejection limit, the two close-out channels, the exposed path, and the output
    check's effect.
  * arXiv:2611.24880 "Local AI Agents" — cost per solved task, the three-term
    energy decomposition, capacity, the bandwidth bound, the required rate, the
    cached vs computed token split, the budget notice, and local vs cloud.

Deterministic: plain data in, dicts out; no model, no network, no server.

Run: python3 tests/acceptance/v1219_requirement_replan_cost.py
"""
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="sf-v1219-")
for _key in ("CONFIG_DIR", "SESSIONS_DIR", "GRAPH_DIR", "EDITS_DIR",
             "RUNS_DIR", "DATA_DIR", "THREADS_DIR", "COSTS_DIR", "MEMORY_DIR"):
    os.environ["LONGRUN_" + _key] = os.path.join(TMP, _key)
    os.makedirs(os.environ["LONGRUN_" + _key], exist_ok=True)
os.environ["LONGRUN_DB"] = os.path.join(TMP, "events.db")
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.harness.checks import requirement_loop as RL  # noqa: E402
from longrun.harness.checks import secure_replan as SR  # noqa: E402
from longrun.harness.checks import local_cost as LC  # noqa: E402

RESULTS = []


def check(name, ok, detail=""):
    RESULTS.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name
          + ((" :: " + str(detail)) if detail else ""))


def close(a, b, tol=1e-9):
    return a is not None and abs(a - b) <= tol


def kinds(out):
    return [f["kind"] for f in (out.get("findings") or [])]


# ---- 1. requirement-centred harness evolution (arXiv:2611.24924) -------
REPORT = {"title": "the harness should surface a queued correction",
          "problem": "a correction queued during a model call", "impact": "user waits",
          "boundary": "model-call boundary", "kind": "feature",
          "priority": "P1", "evidence": ["session-7"], "acceptance": "delivered < 5 s",
          "target": "harness"}
NORM = RL.issue(REPORT)
check("a harness issue is normalised", NORM["verdict"] == "normalized")
check("the kind is kept", NORM["kind"] == "feature")
check("the priority is kept", NORM["priority"] == "P1")
check("the evidence is carried", NORM["evidence"] == ["session-7"])
check("a task problem is refused",
      RL.issue({"title": "x", "concerns_user_task": True})["reason"] == "task-not-harness")
check("an issue that does not hold is refused",
      RL.issue({"title": "x", "holds": False})["reason"] == "does-not-hold")
check("an already-satisfied issue is refused",
      RL.issue({"title": "x", "already_satisfied": True})["reason"] == "already-satisfied")
check("a title naming a task is refused",
      RL.issue({"title": "fix repo:abc task-12"})["reason"] == "title-not-task-independent")
check("an unknown kind asks for information",
      RL.issue({"title": "x", "kind": "epic"})["verdict"] == "needs-info")
T = RL.triage(REPORT)
check("a complete report is accepted", T["disposition"] == "accept")
check("the artifact carries the problem",
      T["artifact"]["reported_problem"].startswith("a correction queued"))
check("the artifact names the target", T["artifact"]["implementation_target"] == "harness")
check("the artifact has no missing field", T["missing"] == [])
check("a task problem rejects", RL.triage({"title": "x", "concerns_user_task": True})
      ["disposition"] == "reject")
check("a thin report needs information",
      RL.triage({"title": "x"})["verdict"] == "needs-info")
CONS = RL.consolidate([
    {"relationship": "both are correction delivery", "tension": "visibility vs speed",
     "covers": ["r1", "r2"], "direction": "bound the wait"},
    {"relationship": "same boundary", "tension": "same", "covers": ["r3"]},
])
check("two sources consolidate", CONS["verdict"] == "consolidated")
check("covers absorbs the named sources", CONS["covers"] == ["r1", "r2", "r3"])
check("one source cannot consolidate",
      RL.consolidate([{"relationship": "x", "tension": "y"}])["verdict"] == "too-few-sources")
check("a missing relationship is refused",
      RL.consolidate([{"tension": "y"}, {"relationship": "x", "tension": "y"}])
      ["verdict"] == "relationship-missing")
check("a direction that names a function is refused",
      RL.consolidate([{"relationship": "x", "tension": "y", "direction": "def f()"},
                      {"relationship": "x", "tension": "y"}])["verdict"] == "not-a-mechanism")
ADM = RL.admission([
    {"id": "a", "package": {"runtime_logs": ["l"], "task_descriptions": ["t"]}},
    {"id": "b", "package": {"runtime_logs": ["l"]}},
    {"id": "c", "package": {"runtime_logs": ["l"], "task_descriptions": ["t"],
                            "grader": True}},
])
check("only the complete package is admitted", ADM["admitted"] == ["a"])
check("an incomplete package is refused", ADM["refused"][0]["reason"] == "package-incomplete")
check("a package carrying a grader is refused",
      ADM["refused"][1]["reason"] == "package-leaks-grader")
check("an empty admission is still complete",
      RL.admission([])["verdict"] == "admission-complete")
DESIGN = {"objective": True, "layer": True, "boundaries": True,
          "falsifiable_test": True}
GOOD = {"design": DESIGN, "code": {"acceptance": True, "suite": True, "head_bound": True},
        "approval_head": "abc", "pr_head": "abc", "rfc_unchanged": True,
        "requirement": "r1"}
check("a clean review merges", RL.review(GOOD)["verdict"] == "merge")
check("the merge closes its requirement", RL.review(GOOD)["closes"] == "r1")
check("a failed design check sends it back",
      RL.review(dict(GOOD, design=dict(DESIGN, layer=False)))["verdict"] == "design-rework")
check("the failed check is named",
      RL.review(dict(GOOD, design=dict(DESIGN, layer=False)))["failed"] == ["layer"])
check("code rework is named",
      RL.review(dict(GOOD, code={"acceptance": True, "suite": True,
                                 "head_bound": True, "verdict": "REWORK"}))
      ["verdict"] == "code-rework")
check("a stale approval blocks the merge",
      RL.review(dict(GOOD, approval_head="old"))["verdict"] == "stale-approval")
check("a drifted RFC blocks the merge",
      RL.review(dict(GOOD, rfc_unchanged=False))["verdict"] == "rfc-drift")
ROUNDS = RL.rounds([
    {"issues": 28, "declined": 3, "requirements": 36, "consolidated": 5,
     "prds": 3, "rfcs": 18},
    {"issues": 30, "declined": 12, "requirements": 19, "consolidated": 3,
     "prds": 3, "rfcs": 9},
])
check("issues are summed", ROUNDS["totals"]["issues"] == 58)
check("declines are summed", ROUNDS["totals"]["declined"] == 15)
check("the declined share is reported", close(ROUNDS["declined_share"], 15 / 58))
check("delivered items are consolidated plus PRDs", ROUNDS["delivered"] == 14)
check("no rounds is its own verdict", RL.rounds([])["verdict"] == "no-rounds")
DEL = RL.delivery({"passed": 137, "undelivered": 34})
check("undelivered passes are counted", DEL["undelivered"] == 34)
check("the delivery gap is a share", close(DEL["share"], 34 / 137))
check("an undelivered pass gets the floor rating", DEL["minimum_rating"] == 1)
check("a delivery gap is named", DEL["verdict"] == "delivery-gap")
check("a clean delivery is named",
      RL.delivery({"passed": 10, "undelivered": 0})["verdict"] == "delivered")
GEN = RL.generalisation([{"id": "a", "tasks": 3}, {"id": "b", "tasks": 2},
                         {"id": "c", "tasks": 1}])
check("multi-task changes are counted", GEN["multi_task"] == 2)
check("the generalisation share is reported", close(GEN["share"], 2 / 3))
check("a generalising set is named", GEN["verdict"] == "generalises")
check("a task name in runtime blocks generalisation",
      RL.generalisation([{"id": "a", "tasks": 3, "names_task_in_runtime": True}])
      ["verdict"] == "task-specific")
check("no changes is its own verdict",
      RL.generalisation([])["verdict"] == "no-changes")
check("the audit names seven misreadings",
      len(RL.audit({"selects_by_benchmark": True, "single_evolution_agent": True,
                    "implicit_requirements_ignored": True,
                    "deduplicates_in_triage": True,
                    "package_carries_conversations": True,
                    "pass_equals_satisfaction": True,
                    "merge_without_head_binding": True})["findings"]) == 7)
check("an empty record passes the requirement audit",
      kinds(RL.audit({})) == ["audit-conditions-met"])
check("an empty harness profile misses all seven habits",
      len(RL.advise({})["findings"]) == 7)
check("a complete harness profile is clean",
      RL.advise({k: True for k in ("collects_feedback_in_sessions",
                                   "normalises_issues_to_requirements",
                                   "merges_by_root_cause",
                                   "admits_only_with_evidence",
                                   "reviews_design_before_code",
                                   "binds_approval_to_head",
                                   "reports_delivery_beside_pass")})["findings"] == [])

# ---- 2. security-aware replanning (arXiv:2611.24839) -------------------
REGISTRY = {
    "filesurfer": {"capabilities": ["file-read", "file-write"], "allows": ["coder"]},
    "websurfer": {"capabilities": ["web-search", "web-fetch"], "allows": ["coder"]},
    "coder": {"capabilities": ["coding", "file-write"], "allows": ["terminal"]},
    "terminal": {"capabilities": ["terminal", "coding"], "allows": []},
}
PLAN = {"completed": 1, "subtasks": [
    {"agent": "filesurfer", "capabilities": ["file-read"], "needs": []},
    {"agent": "coder", "capabilities": ["coding"], "needs": [0]},
    {"agent": "terminal", "capabilities": ["terminal"], "needs": [1]},
]}
RECORD = {"registry": REGISTRY, "task_policy": ["file-read", "coding", "terminal"]}
check("the clean plan is valid", SR.validate(PLAN, RECORD)["verdict"] == "valid")
check("all four conditions pass on the clean plan",
      SR.validate(PLAN, RECORD)["violated"] == [])
BAD_CAP = {"completed": 1, "subtasks": [
    {"agent": "filesurfer", "capabilities": ["file-read"], "needs": []},
    {"agent": "coder", "capabilities": ["superuser"], "needs": [0]},
]}
check("a capability the agent does not offer is caught",
      "a-capability-not-offered" in
      [v["condition"] for v in SR.validate(BAD_CAP, RECORD)["violated"]])
OUT_POLICY = {"completed": 1, "subtasks": [
    {"agent": "filesurfer", "capabilities": ["file-read"], "needs": []},
    {"agent": "coder", "capabilities": ["coding", "file-write"], "needs": [0]},
]}
check("a capability outside the task policy is caught",
      "b-capability-outside-policy" in
      [v["condition"] for v in SR.validate(OUT_POLICY, RECORD)["violated"]])
check("an explicit grant allows the extra capability",
      SR.validate(OUT_POLICY, dict(RECORD, grants={"1": ["file-write"]}))
      ["verdict"] == "valid")
BAD_DEP = {"completed": 0, "subtasks": [
    {"agent": "filesurfer", "capabilities": ["file-read"], "needs": [1]},
    {"agent": "coder", "capabilities": ["coding"], "needs": []},
]}
check("a dependency on a later subtask is caught",
      "c-bad-dependency" in
      [v["condition"] for v in SR.validate(BAD_DEP, RECORD)["violated"]])
NOT_ALLOWED = {"completed": 0, "subtasks": [
    {"agent": "websurfer", "capabilities": ["web-search"], "needs": []},
    {"agent": "terminal", "capabilities": ["terminal"], "needs": [0]},
]}
check("a producer that does not allow the consumer is caught",
      "c-output-not-allowed" in
      [v["condition"] for v in SR.validate(NOT_ALLOWED, RECORD)["violated"]])
UNUSED = {"completed": 0, "subtasks": [
    {"agent": "filesurfer", "capabilities": ["file-read"], "needs": [],
     "used_later": False},
    {"agent": "coder", "capabilities": ["coding"], "needs": []},
]}
check("an unused intermediate output is caught",
      "d-output-unused" in
      [v["condition"] for v in SR.validate(UNUSED, RECORD)["violated"]])
VOCAB = SR.templates()
check("the vocabulary has thirteen conditions", VOCAB["count"] == 13)
check("every condition has a suggested resolution",
      all(item["suggested"] for item in VOCAB["conditions"]))
check("the suggested resolution starts with an operator",
      VOCAB["conditions"][0]["suggested"][0] in SR.OPERATORS)
APPLIED = SR.apply(PLAN, [{"op": "revise-directive", "index": 1,
                           "directive": "compute from the Q3 page"}])
check("a directive revision is applied", APPLIED["verdict"] == "repair-applied")
check("the completed subtask is untouched",
      APPLIED["plan"]["subtasks"][0]["capabilities"] == ["file-read"])
check("a completed subtask cannot be edited",
      SR.apply(PLAN, [{"op": "prune", "index": 0}])["errors"][0]["reason"]
      == "targets-completed")
check("an unknown operator is refused",
      SR.apply(PLAN, [{"op": "rewrite"}])["errors"][0]["reason"] == "unknown-operator")
check("an out-of-range target is refused",
      SR.apply(PLAN, [{"op": "prune", "index": 9}])["errors"][0]["reason"]
      == "out-of-range")
check("a backward dependency is refused",
      SR.apply(PLAN, [{"op": "rewire", "index": 1, "source": 5}])["errors"][0]["reason"]
      == "bad-dependency")
INSERTED = SR.apply(PLAN, [
    {"op": "insert", "index": 1,
     "subtask": {"agent": "websurfer", "capabilities": ["web-fetch"], "needs": []}},
    {"op": "rewire", "index": 2, "source": 1},
])
check("an insert shifts the later subtasks", len(INSERTED["plan"]["subtasks"]) == 4)
check("a rewire adds the dependency",
      INSERTED["plan"]["subtasks"][2]["needs"] == [0, 1])
check("an empty plan is refused",
      SR.apply({"completed": 0, "subtasks": []}, [])["errors"][0]["reason"]
      == "empty-plan")
REPAIR = SR.repair(dict(RECORD, plan=PLAN, budget=3, used=0,
                        conditions=["input-lacks-datum"],
                        operators=[{"op": "revise-directive", "index": 1,
                                    "directive": "fetch the Q3 figure first"}]))
check("a valid repair is accepted", REPAIR["verdict"] == "repair-accepted")
check("one unit of the repair budget is spent", REPAIR["used"] == 1)
check("the repair names its failure condition",
      REPAIR["conditions"] == ["input-lacks-datum"])
check("an exhausted budget stops the task",
      SR.repair(dict(RECORD, plan=PLAN, budget=1, used=1))["verdict"]
      == "budget-exhausted")
check("too many rejections terminate the task",
      SR.repair(dict(RECORD, plan=PLAN, budget=9, used=0,
                     consecutive_rejections=3))["verdict"] == "terminated-rejections")
check("a condition outside the vocabulary is refused",
      SR.repair(dict(RECORD, plan=PLAN, budget=3, used=0,
                     conditions=["the model was rude"]))["verdict"] == "no-template")
check("a repair that violates the policy is rejected",
      SR.repair(dict(RECORD, plan=PLAN, budget=3, used=0,
                     conditions=["capability-not-granted"],
                     operators=[{"op": "reassign", "index": 1,
                                 "agent": "coder", "capabilities": ["email"]}]))
      ["verdict"] == "repair-rejected")
check("a success close-out needs an output",
      SR.close_out({"outcome": "success"})["verdict"] == "success-without-output")
check("a success close-out travels the data channel",
      SR.close_out({"outcome": "success", "output": "16.1%"})["channel"] == "data")
check("a failure close-out travels the replanning channel",
      SR.close_out({"outcome": "failure",
                    "conditions": ["input-lacks-datum"]})["channel"] == "replanning")
check("a failure without a condition is refused",
      SR.close_out({"outcome": "failure"})["verdict"] == "failure-without-condition")
check("a condition outside the vocabulary is refused",
      SR.close_out({"outcome": "failure", "conditions": ["bad vibes"]})["verdict"]
      == "condition-not-in-vocabulary")
check("an unknown outcome is refused",
      SR.close_out({"outcome": "maybe"})["verdict"] == "unknown-outcome")
EXP = SR.exposure({"policy": "agent-choice", "data_rate": 13.4,
                   "replanning_rate": 24.3})
check("the higher channel sets the exposure", close(EXP["rate"], 24.3))
check("a replanning-dominated path is named",
      EXP["verdict"] == "replanning-path-dominates")
check("an always-success policy exposes the data path",
      SR.exposure({"policy": "always-success", "data_rate": 13.4,
                   "replanning_rate": 24.3})["channel"] == "data")
check("an always-failure policy exposes the replanning path",
      SR.exposure({"policy": "always-failure", "data_rate": 13.4,
                   "replanning_rate": 24.3})["channel"] == "replanning")
VAL = SR.validation_effect({"before": 86.6, "after": 96.8,
                            "utility_before": 29, "utility_after": 38})
check("the output check raises the defence", close(VAL["delta"], 10.2, 1e-9))
check("the output check raises benign utility", close(VAL["utility_delta"], 9.0))
check("a helping check is named", VAL["verdict"] == "check-helps")
check("an empty validation record is refused",
      SR.validation_effect({})["verdict"] == "insufficient-input")
check("the audit names six misreadings",
      len(SR.audit({"planner_reads_free_text": True,
                    "repair_is_a_model_plan": True,
                    "no_policy_check_on_revision": True,
                    "success_not_verified": True,
                    "completed_subtasks_mutable": True,
                    "unbounded_repair_budget": True})["findings"]) == 6)
check("an empty record passes the replan audit",
      kinds(SR.audit({})) == ["audit-conditions-met"])
check("an empty harness profile misses all seven habits",
      len(SR.advise({})["findings"]) == 7)
check("a complete harness profile is clean",
      SR.advise({k: True for k in ("narrows_feedback_to_a_vocabulary",
                                   "applies_fixed_repair_operators",
                                   "revalidates_every_revision",
                                   "requires_a_grant_for_new_capability",
                                   "verifies_success_close_outs",
                                   "bounds_the_repair_budget",
                                   "keeps_completed_work_immutable")})["findings"] == [])

# ---- 3. local cost per solved task (arXiv:2611.24880) ------------------
COST = LC.expected({"p": 0.5, "pass_cost": 100, "fail_cost": 100})
check("a fair success rate doubles the cost", close(COST["cost"], 200.0))
check("the multiplier is two", close(COST["multiplier"], 2.0))
check("the floor is one over p", close(COST["floor"], 2.0))
check("a fair rate lets run cost matter", COST["verdict"] == "run-cost-matters")
RARE = LC.expected({"p": 0.05, "pass_cost": 100, "fail_cost": 100})
check("a rare success rate dominates the cost", close(RARE["cost"], 2000.0))
check("the multiplier is twenty at p=.05", close(RARE["multiplier"], 20.0))
check("a rare rate is named", RARE["verdict"] == "success-rate-dominated")
check("zero successes never solve", LC.expected({"p": 0, "pass_cost": 1,
                                                 "fail_cost": 1})["verdict"]
      == "never-solves")
check("missing inputs are refused", LC.expected({})["verdict"] == "insufficient-input")
ENERGY = LC.energy({"idle_power": 14, "duration": 4800,
                    "decode_delta": 22, "decode_time": 3600,
                    "prefill_delta": 42, "prefill_time": 120})
check("the idle term is idle power times duration", close(ENERGY["idle_term"], 67200))
check("the decode term is the delta times decode time", close(ENERGY["decode_term"], 79200))
check("the prefill term is the delta times prefill time", close(ENERGY["prefill_term"], 5040))
check("the total is the sum of the terms",
      close(ENERGY["total"], 67200 + 79200 + 5040))
check("the mean power is total over duration",
      close(ENERGY["mean_power"], (67200 + 79200 + 5040) / 4800))
check("the idle share is reported",
      close(ENERGY["idle_share"], 67200 / (67200 + 79200 + 5040)))
check("an incomplete energy record is refused",
      LC.energy({"idle_power": 14})["verdict"] == "insufficient-input")
CAP = LC.capacity({"params": 125e9, "weight_bytes": 1.0, "context_tokens": 0,
                   "kv_bytes_per_token": 1e5, "device_bytes": 128e9})
check("weights alone fit 128 GB", CAP["fits"] is True)
check("the fit margin is reported", close(CAP["margin"], 3e9))
CAP2 = LC.capacity({"params": 125e9, "weight_bytes": 1.0, "context_tokens": 262144,
                    "kv_bytes_per_token": 1e5, "device_bytes": 128e9})
check("a full context does not fit", CAP2["fits"] is False)
check("the cache is counted by the token", close(CAP2["cache"], 262144 * 1e5))
check("a short record is refused", LC.capacity({})["verdict"] == "insufficient-input")
RATE = LC.decode_rate({"bandwidth": 273e9, "active_params": 6e9,
                       "weight_bytes": 0.5, "eta": 0.3})
check("the bandwidth bound is bandwidth over bytes read", close(RATE["bound"], 91.0))
check("the attained rate is the bound times eta", close(RATE["attained"], 27.3))
check("the rate is bounded", RATE["verdict"] == "rate-bounded")
check("a missing bandwidth is refused", LC.decode_rate({})["verdict"]
      == "insufficient-input")
REQ = LC.required_rate({"output_tokens": 102000, "window": 3600,
                        "busy_share": 0.94, "p": 0.33})
check("the required rate scales with the duty cycle",
      close(REQ["rate"], 102000 / (0.94 * 3600) / 0.33))
COMP = LC.computed({"nominal_input": 13.95e6, "cached_share": 0.966,
                    "output_tokens": 102300})
check("computed input is the uncached part",
      close(COMP["computed_input"], 13.95e6 * 0.034))
check("the computed share is small", COMP["share"] < 0.05)
check("the overstatement is above twenty", COMP["overstatement"] > 20)
check("a high cache share is named", COMP["verdict"] == "cache-matters")
check("a low cache share is named",
      LC.computed({"nominal_input": 1000, "cached_share": 0.0,
                   "output_tokens": 1000})["verdict"] == "little-cache")
NOTICE = LC.budget_notice({"before": {"cap_stops": 10, "runs": 24,
                                      "energy_per_solved": 100},
                           "after": {"cap_stops": 2, "runs": 16,
                                     "energy_per_solved": 60}})
check("cap stops before are a share", close(NOTICE["cap_share_before"], 10 / 24))
check("cap stops after are a share", close(NOTICE["cap_share_after"], 2 / 16))
check("the energy change is a fraction", close(NOTICE["energy_change"], 0.4))
check("the notice helps", NOTICE["verdict"] == "notice-helps")
CMP = LC.compare({"local": {"time": 80, "tokens": 102.3},
                  "cloud": {"time": 23, "tokens": 6.2}})
check("the time ratio is local over cloud", close(CMP["time_ratio"], 80 / 23))
check("the token ratio is local over cloud", close(CMP["tokens_ratio"], 102.3 / 6.2))
check("the two worse quantities are counted", CMP["worse_on"] == 2)
check("a slower local run is named", CMP["verdict"] == "local-slower")
check("an empty comparison is refused", LC.compare({})["verdict"] == "insufficient-input")
check("the audit names seven misreadings",
      len(LC.audit({"nominal_tokens_as_work": True,
                    "price_per_token_as_cost": True,
                    "success_rate_omitted": True,
                    "window_mean_as_plateau": True,
                    "single_run_as_capability": True,
                    "faster_device_as_cheaper": True,
                    "no_independent_verification": True})["findings"]) == 7)
check("an empty record passes the cost audit",
      kinds(LC.audit({})) == ["audit-conditions-met"])
check("an empty harness profile misses all seven habits",
      len(LC.advise({})["findings"]) == 7)
check("a complete harness profile is clean",
      LC.advise({k: True for k in ("measures_power_energy_tokens_time",
                                   "measures_the_success_rate",
                                   "verifies_independently",
                                   "separates_plateau_from_window_mean",
                                   "counts_computed_not_nominal_tokens",
                                   "shows_the_budget_to_the_agent",
                                   "prices_a_solved_task")})["findings"] == [])

# ---- summary ----------------------------------------------------------
passed = sum(1 for r in RESULTS if r)
print("\n%d/%d checks passed" % (passed, len(RESULTS)))
sys.exit(0 if passed == len(RESULTS) else 1)
