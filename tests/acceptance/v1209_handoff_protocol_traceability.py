#!/usr/bin/env python3
"""v1209 — handoff governance, typed sessions, pipeline traceability (round 140).

Sources:
  * arXiv:2609.34017 "Maat" — a deterministic versioned anchor at agent
    boundaries, three postures, and a halt audit that counts false alarms.
  * arXiv:2610.37461 "Concordat" — a finite-state protocol enforced by
    withholding tools, well-formedness, safe refinement, linear budgets, and
    compliance measured beside the outcome.
  * arXiv:2510.07614 "Traceability and Accountability" — stagewise blame, repair
    vs harm, planner primacy, and the accuracy/cost/latency frontier.

Deterministic: plain data in, dicts out; no model, no network, no server.

Run: python3 tests/acceptance/v1209_handoff_protocol_traceability.py
"""
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="sf-v1209-")
for _key in ("CONFIG_DIR", "SESSIONS_DIR", "GRAPH_DIR", "EDITS_DIR",
             "RUNS_DIR", "DATA_DIR", "THREADS_DIR", "COSTS_DIR", "MEMORY_DIR"):
    os.environ["LONGRUN_" + _key] = os.path.join(TMP, _key)
    os.makedirs(os.environ["LONGRUN_" + _key], exist_ok=True)
os.environ["LONGRUN_DB"] = os.path.join(TMP, "events.db")
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.harness import handoff_governance as HG   # noqa: E402
from longrun.harness import session_protocol as SP     # noqa: E402
from longrun.harness import pipeline_traceability as PT  # noqa: E402

RESULTS = []


def check(name, ok, detail=""):
    RESULTS.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name
          + ((" :: " + str(detail)) if detail else ""))


def kinds(out):
    return [f["kind"] for f in (out.get("findings") or [])]


RULES = [
    {"id": "R1", "kind": "required", "field": "claim_id"},
    {"id": "R2", "kind": "limit", "field": "discount", "max": 0.10},
    {"id": "R3", "kind": "identity", "field": "patient"},
    {"id": "R4", "kind": "sum", "field": "total", "parts": "lines"},
    {"id": "R5", "kind": "residency", "field": "region", "values": ["EU"]},
    {"id": "R6", "kind": "allowed", "field": "tier",
     "values": ["gold", "silver"]},
]
GOOD = {"claim_id": "C1", "discount": 0.05, "patient": "p1",
        "total": 100, "lines": [60, 40], "region": "EU", "tier": "gold"}

# ---- 1. handoff governance (Maat) ---------------------------------------
a = HG.anchor(RULES, version=3)
check("a versioned anchor with rules passes", kinds(a) == ["anchor-versioned"], a)
check("an unversioned anchor is named",
      "unversioned-anchor" in kinds(HG.anchor(RULES, version=None)))
check("an empty anchor is named", "anchor-empty" in kinds(HG.anchor([], version=1)))
check("a duplicate rule id is named",
      "duplicate-rule-id" in kinds(HG.anchor(
          [{"id": "R1", "kind": "required", "field": "a"},
           {"id": "R1", "kind": "required", "field": "b"}], version=1)))
check("an unknown rule kind is named at anchor time",
      "unknown-rule-kind" in kinds(HG.anchor(
          [{"id": "R9", "kind": "vibes", "field": "x"}], version=1)))

v = HG.validate({"fields": GOOD}, a, "intervene")
check("a compliant handoff passes", v["verdict"] == "pass", v)
check("a compliant handoff has no finding", v["findings"] == [])
check("off mode runs unchecked", HG.validate({"fields": GOOD}, a, "off")["checked"] is False)
check("off mode ignores a violating payload",
      HG.validate({"fields": dict(GOOD, discount=0.9)}, a, "off")["findings"] == [])

bad = {"fields": dict(GOOD, discount=0.40)}
ib = HG.validate(bad, a, "intervene")
check("intervene blocks an exceeded limit", ib["verdict"] == "block", ib)
check("the blocking finding names the rule", ib["findings"][0]["rule"] == "R2", ib)
check("a limit finding sits on the requirement primitive", ib["findings"][0]["gate"] == "REQ")
check("the finding carries the value and the cap",
      ib["findings"][0]["value"] == 0.40 and ib["findings"][0]["max"] == 0.10)
warn = HG.validate(bad, a, "warn")
check("warn records the would-block and continues", warn["verdict"] == "warn", warn)
check("warn counts the finding as would-block", warn["would_block"] == 1)
check("an unknown posture is refused", HG.validate({"fields": GOOD}, a, "audit")["verdict"]
      == "invalid-mode")

miss = HG.validate({"fields": dict(GOOD, claim_id="")}, a, "intervene")
check("a missing required field is named", "missing-field" in
      [f["kind"] for f in miss["findings"]])
check("a required-field finding sits on G2",
      [f for f in miss["findings"] if f["kind"] == "missing-field"][0]["gate"] == "G2")
drift = HG.validate({"fields": dict(GOOD, patient="p2")}, a, "intervene",
                    state={"patient": "p1"})
check("identity drift is named", "identity-drift" in
      [f["kind"] for f in drift["findings"]])
check("identity drift sits on G7",
      [f for f in drift["findings"] if f["kind"] == "identity-drift"][0]["gate"] == "G7")
check("the first handoff records the identity without a finding",
      HG.validate({"fields": dict(GOOD, patient="p2")}, a, "intervene")["verdict"] == "pass")
mism = HG.validate({"fields": dict(GOOD, total=90)}, a, "intervene")
check("a reconciliation mismatch is named",
      "sum-mismatch" in [f["kind"] for f in mism["findings"]])
check("the mismatch reports both sides",
      [f for f in mism["findings"] if f["kind"] == "sum-mismatch"][0]["sum"] == 100)
res = HG.validate({"fields": dict(GOOD, region="US")}, a, "intervene")
check("a residency violation is named",
      "residency-violation" in [f["kind"] for f in res["findings"]])
tier = HG.validate({"fields": dict(GOOD, tier="bronze")}, a, "intervene")
check("a value outside the allowed set is named",
      "value-not-allowed" in [f["kind"] for f in tier["findings"]])
unread = HG.validate({"fields": dict(GOOD, discount="n/a")}, a, "intervene")
check("an unreadable limit is a finding, not a crash",
      "limit-unreadable" in [f["kind"] for f in unread["findings"]])

at = HG.attribute([{"kind": "injected"}] * 10 + [{"kind": "genuine"}] * 3
                  + [{"kind": "escalation"}] + [{"kind": "false-alarm"}] * 3)
check("attribution counts each halt class",
      at["counts"] == {"injected": 10, "genuine": 3, "escalation": 1,
                       "false-alarm": 3}, at)
check("caught counts injected plus genuine", at["caught"] == 13)
check("the false-alarm rate is measured", abs(at["false_alarm_rate"] - 3 / 17) < 1e-9)
check("a middling false-alarm rate is mixed", at["verdict"] == "halts-mixed", at)
check("a low false-alarm rate is attributable",
      HG.attribute([{"kind": "injected"}] * 18 + [{"kind": "false-alarm"}] * 2)
      ["verdict"] == "halts-attributable")
check("a high false-alarm rate is unattributed",
      HG.attribute([{"kind": "injected"}] * 5 + [{"kind": "false-alarm"}] * 5)
      ["verdict"] == "halts-unattributed")
check("no halts is its own verdict", HG.attribute([])["verdict"] == "no-halts")
check("an unknown halt kind is counted apart",
      HG.attribute([{"kind": "weird"}])["unknown"] == 1)

cmp_out = HG.compare([
    {"benchmark": "B2B", "off": 5.06, "governed": 6.53, "governed_lower_bound": 4.25},
    {"benchmark": "hospital", "off": 6.26, "governed": 6.95, "governed_lower_bound": 2.45},
])
check("a paired gain can dissolve under attribution",
      cmp_out["verdict"] == "attribution-corrects-the-gain", cmp_out)
check("every dissolving row is counted", cmp_out["dissolved"] == 2)
check("the lower-bound mean is negative", cmp_out["mean_relative_lower_bound"] < 0)
strong = HG.compare([{"off": 5, "governed": 5.5, "governed_lower_bound": 5.2},
                     {"off": 4, "governed": 4.4, "governed_lower_bound": 4.2}])
check("a gain that survives attribution holds", strong["verdict"] == "gain-holds", strong)
check("a pair inside the flat band is flat",
      HG.compare([{"off": 5, "governed": 5.05, "governed_lower_bound": 5.04}])
      ["verdict"] == "flat")
check("a pair without a lower bound uses the governed mean",
      HG.compare([{"off": 5, "governed": 5.4}])["rows"][0]["lower_bound"] == 5.4)
check("no pairs is its own verdict", HG.compare([])["verdict"] == "no-pairs")

cov = HG.coverage([{"rule": "R1", "state": "misconfigured"},
                   {"rule": "R2", "state": "true-negative"}])
check("a misconfigured rule makes silence uninformative",
      cov["verdict"] == "silence-is-not-evidence", cov)
check("a pre-empted check also breaks silence",
      HG.coverage([{"rule": "R3", "state": "pre-empted"}])["verdict"]
      == "silence-is-not-evidence")
check("all true negatives support the silence",
      HG.coverage([{"rule": "R1", "state": "true-negative"},
                   {"rule": "R2", "state": "true-negative"}])["verdict"]
      == "silence-supported")
check("all unexercised rules prove nothing",
      HG.coverage([{"rule": "R1", "state": "not-exercised"}])["verdict"]
      == "rules-unexercised")
check("a mixed tally is partial",
      HG.coverage([{"rule": "R1", "state": "not-exercised"},
                   {"rule": "R2", "state": "true-negative"}])["verdict"]
      == "silence-partial")
check("an unknown silence state is listed apart",
      HG.coverage([{"rule": "R1", "state": "vibes"}])["unknown"] == ["R1"])

check("a new anchor is calibrated in warn mode",
      HG.posture({"trials": 5})["mode"] == "warn")
check("an unexercised anchor is the reason",
      "anchor-unexercised" in HG.posture({"trials": 5})["reasons"])
check("a high false-alarm rate keeps warn",
      HG.posture({"trials": 40, "false_alarm_rate": 0.3})["mode"] == "warn")
check("an unversioned anchor keeps warn",
      HG.posture({"trials": 40, "anchor_versioned": False})["mode"] == "warn")
check("a calibrated anchor may intervene",
      HG.posture({"trials": 40, "false_alarm_rate": 0.02})["mode"] == "intervene")
check("advise names every missing practice", len(HG.advise({})["findings"]) == 7)
check("a fully declared profile has no finding", HG.advise(
    {k: True for k in ("versions_the_anchor", "gates_each_handoff",
                       "keeps_the_validator_deterministic",
                       "attributes_every_halt", "scores_the_lower_bound",
                       "exercises_rules_on_live_payloads",
                       "warns_before_it_intervenes")})["findings"] == [])

# ---- 2. session protocol (Concordat) ------------------------------------
REFUND = SP.protocol(
    ["start", "verified", "awaiting", "refunded", "denied"],
    ["verify", "propose", "approve", "reject"],
    "start", ["refunded", "denied"],
    {"start|verify": ["verified", "denied"],
     "verified|propose": ["awaiting"],
     "awaiting|approve": ["refunded"],
     "awaiting|reject": ["denied"]})
check("the refund protocol is well formed", REFUND["well_formed"], REFUND["errors"])
check("the start state offers only verification",
      SP.allowed(REFUND, "start") == ["verify"])
check("the approval state offers approve and reject",
      SP.allowed(REFUND, "awaiting") == ["approve", "reject"])
check("a final state offers nothing", SP.allowed(REFUND, "refunded") == [])

tk = SP.tick(REFUND, "verified", "propose")
check("a single-target transition is accepted", tk["accepted"], tk)
check("the accepted transition moves the state", tk["state"] == "awaiting")
check("a rejected call never has a side effect",
      SP.tick(REFUND, "start", "propose")["side_effect"] is False)
check("an illegal call keeps the state",
      SP.tick(REFUND, "start", "propose")["state"] == "start")
check("an illegal call names the reason",
      SP.tick(REFUND, "start", "propose")["reason"] == "action-not-allowed")
branch = SP.tick(REFUND, "start", "verify")
check("a multi-target transition needs the target",
      branch["accepted"] is False and branch["reason"] == "target-required", branch)
check("a target outside the transition is refused",
      SP.tick(REFUND, "start", "verify", "awaiting")["reason"]
      == "target-not-in-transition")
check("a chosen branch is accepted",
      SP.tick(REFUND, "start", "verify", "denied")["state"] == "denied")

no_final = SP.protocol(["a"], ["go"], "a", [], {"a|go": ["a"]})
check("a protocol without finals is refused",
      "no-final-states" in [e["kind"] for e in no_final["errors"]])
final_acts = SP.protocol(["a", "b"], ["go"], "a", ["b"], {"a|go": ["b"], "b|go": ["b"]})
check("a final state that allows actions is refused",
      "final-state-allows-actions" in [e["kind"] for e in final_acts["errors"]])
orphan = SP.protocol(["a", "b", "c"], ["go"], "a", ["b"],
                     {"a|go": ["b"], "c|go": ["b"]})
check("an unreachable state is refused",
      "unreachable-state" in [e["kind"] for e in orphan["errors"]])
stuck = SP.protocol(["a", "b", "c"], ["go"], "a", ["b"],
                    {"a|go": ["c"], "b|go": ["b"]})
check("a dead end is refused",
      "dead-end-state" in [e["kind"] for e in stuck["errors"]])
unknown = SP.protocol(["a"], ["go"], "a", ["a"], {"a|go": ["zzz"]})
check("a transition to an unknown state is refused",
      "target-not-in-states" in [e["kind"] for e in unknown["errors"]])
empty = SP.protocol(["a", "b"], ["go"], "a", ["b"], {"a|go": [], "b|go": ["a"]})
check("an empty transition is refused",
      "empty-transition" in [e["kind"] for e in empty["errors"]])

PARENT = SP.protocol(["s0", "mid", "done"], ["a", "b"], "s0", ["done"],
                     {"s0|a": ["mid"], "mid|b": ["done"]})
SAFE = SP.protocol(["s0", "mid", "done", "extra"], ["a", "b", "x"], "s0", ["done"],
                   {"s0|a": ["mid"], "mid|b": ["done"], "s0|x": ["extra"],
                    "extra|a": ["mid"]})
rf = SP.refines(PARENT, SAFE)
check("a child with an extra step hidden still refines the parent", rf["safe"], rf)
check("the safe walk visits the pairs", rf["steps"] > 0)
BYPASS = SP.protocol(["s0", "mid", "done"], ["a", "b", "z"], "s0", ["done"],
                     {"s0|z": ["done"], "s0|a": ["mid"], "mid|b": ["done"]})
bf = SP.refines(PARENT, BYPASS)
check("a child that jumps to a parent outcome is refused", bf["safe"] is False, bf)
check("the refusal names the unknown route",
      bf["reason"] == "child-reaches-parent-state-by-unknown-route")
check("the refusal names the action", bf["action"] == "z")
OUTSIDE = SP.protocol(["s0", "mid", "done", "other"], ["a", "b"],
                      "s0", ["other"],
                      {"s0|a": ["mid"], "mid|b": ["done"], "done|a": ["other"]})
check("a final state outside the parent is refused",
      SP.refines(PARENT, OUTSIDE)["reason"] == "final-not-in-parent")
check("a human step cannot become automatic",
      SP.refines(PARENT, SAFE, human_parent=["approve"], human_child=[])["reason"]
      == "human-step-became-automatic")

sp = SP.split({"tokens": 1000, "tool_calls": 10, "usd": 2.0}, 0.25)
check("a split is linear", sp["linear"], sp)
check("the child receives its allowance", sp["child"]["tokens"] == 250)
check("the parent keeps only the remainder", sp["parent"]["tokens"] == 750)
check("the same allowance cannot be spent twice",
      sp["parent"]["usd"] + sp["child"]["usd"] == 2.0)
check("a share above the parent is refused",
      "share-exceeds-parent" in [e["kind"] for e in
                                 SP.split({"tokens": 100}, 2.0)["errors"]])
check("a child may not be unlimited where the parent is limited",
      "child-unlimited" in [e["kind"] for e in
                            SP.split({"tokens": 100}, {"tokens": None})["errors"]])
check("a negative amount is refused",
      "negative-amount" in [e["kind"] for e in
                            SP.split({"tokens": -5}, 0.5)["errors"]])
check("a non-finite amount is refused",
      "non-finite-amount" in [e["kind"] for e in
                              SP.split({"tokens": 100},
                                       {"tokens": float("inf")})["errors"]])
ch = SP.charge({"tokens": 100, "usd": None}, {"tokens": 40})
check("a charge reports the remainder", ch["remaining"]["tokens"] == 60)
check("an unlimited dimension stays unlimited", ch["remaining"]["usd"] is None)
check("a spend below the budget does not stop the run", ch["stop"] is False)
check("an exhausted budget stops the run",
      SP.charge({"tokens": 100}, {"tokens": 120})["exhausted"] == ["tokens"])

paper_runs = ([{"passed": True, "violations": 1}] * 8
              + [{"passed": False, "violations": 1}] * 5
              + [{"passed": True, "violations": 0}] * 7)
cp = SP.compliance(paper_runs)
check("a passing run can still break the rule", cp["verdict"] == "outcome-blind", cp)
check("the blind passes are counted", cp["blind_passes"] == 8)
check("the blind share is over the passing runs",
      abs(cp["blind_share"] - 8 / 15.0) < 1e-9)
check("the violation rate is over all runs", abs(cp["violation_rate"] - 0.65) < 1e-9)
check("no violation is compliant",
      SP.compliance([{"passed": True, "violations": 0}])["verdict"] == "compliant")
check("a failing violating run is detected, not blind",
      SP.compliance([{"passed": False, "violations": 2}])["verdict"] == "outcome-detects")
check("no runs is its own verdict", SP.compliance([])["verdict"] == "no-runs")

press = ([{"arm": "standard", "passed": i < 20, "violation": i < 13} for i in range(50)]
         + [{"arm": "governed", "passed": i < 22, "violation": False} for i in range(50)])
pr = SP.pressure(press)
check("the standard arm breaks the rule under pressure",
      pr["verdict"] == "rule-breaks-under-pressure", pr)
check("the governed arm violates nothing", pr["arms"]["governed"]["violations"] == 0)
check("the violation difference equals the standard rate",
      abs(pr["violation_difference"] - 0.26) < 1e-9)
check("the test is exact and significant", pr["p_value"] < 0.05)
check("task success is close", pr["outcome_gap"] < 0.05)
check("two clean arms do not break the rule",
      SP.pressure([{"arm": "standard", "passed": True, "violation": False},
                   {"arm": "governed", "passed": True, "violation": False}])
      ["verdict"] == "no-violations")
check("a leaking gate is named",
      SP.pressure([{"arm": "standard", "passed": False, "violation": True}] * 10
                  + [{"arm": "governed", "passed": False, "violation": True}] * 10)
      ["verdict"] == "gate-leaks")
check("one arm is not a comparison",
      SP.pressure([{"arm": "standard", "passed": True}])["verdict"] == "two-arms-required")
check("advise names every missing practice", len(SP.advise({})["findings"]) == 7)
check("a fully declared profile has no finding", SP.advise(
    {k: True for k in ("derives_the_protocol", "withholds_illegal_tools",
                       "rejects_before_side_effects",
                       "checks_protocol_safe_inheritance",
                       "splits_budgets_linearly", "measures_process_compliance",
                       "tests_under_pressure")})["findings"] == [])

# ---- 3. pipeline traceability -------------------------------------------
check("the critic's answer is preferred",
      PT.final({"planner": "A", "executor": "B", "critic": "C"}) == "C")
check("without a critic the executor's answer stands",
      PT.final({"planner": "A", "executor": "B"}) == "B")
check("without either the planner's answer stands", PT.final({"planner": "A"}) == "A")
check("an empty pipeline has no answer", PT.final({}) is None)

b1 = PT.blame({"planner": "B", "executor": "B", "critic": "C"}, "C")
check("a critic repair leaves no origin", b1["origin"] == "NONE", b1)
check("the critic repair flag is set", b1["flags"]["critic_repair"] is True)
check("the planner error is flagged", b1["flags"]["planner_error"] is True)
b2 = PT.blame({"planner": "C", "executor": "C", "critic": "B"}, "C")
check("a critic that breaks a correct answer is the origin", b2["origin"] == "CRITIC")
check("the critic harm flag is set", b2["flags"]["critic_harm"] is True)
b3 = PT.blame({"planner": "C", "executor": "B", "critic": "B"}, "C")
check("an executor that breaks a correct plan is the origin", b3["origin"] == "EXECUTOR")
check("the executor harm flag is set", b3["flags"]["executor_harm"] is True)
b4 = PT.blame({"planner": "B", "executor": "B", "critic": "B"}, "C")
check("an unrepaired plan error is the origin", b4["origin"] == "PLANNER")
b5 = PT.blame({"planner": "B", "executor": "C", "critic": "C"}, "C")
check("an executor repair is flagged", b5["flags"]["executor_repair"] is True)
check("a repaired pipeline has no origin", b5["origin"] == "NONE")

hd = PT.handoff({"planner": "A", "executor": "B", "critic": "C", "answer": "C",
                 "gold": "C", "provenance": "run1"})
check("a structured handoff passes", kinds(hd) == ["handoff-structured"], hd)
check("a missing role is named",
      "stage-missing" in kinds(PT.handoff({"planner": "A", "answer": "C",
                                           "gold": "C", "provenance": "r"})))
check("an empty answer is named",
      "answer-empty" in kinds(PT.handoff({"planner": "A", "executor": "B",
                                          "critic": "C", "answer": "",
                                          "gold": "C", "provenance": "r"})))
check("a handoff with no provenance is named",
      "no-provenance" in kinds(PT.handoff({"planner": "A", "executor": "B",
                                           "critic": "C", "answer": "C",
                                           "gold": "C"})))

rows = ([{"models": {"planner": "P1", "executor": "E1", "critic": "C1"},
          "answers": {"planner": "B", "executor": "C", "critic": "C"},
          "gold": "C"}] * 3
        + [{"models": {"planner": "P1", "executor": "E1", "critic": "C1"},
            "answers": {"planner": "B", "executor": "B", "critic": "B"},
            "gold": "C"}] * 2
        + [{"models": {"planner": "P2", "executor": "E2", "critic": "C2"},
            "answers": {"planner": "C", "executor": "B", "critic": "B"},
            "gold": "C"}]
        + [{"models": {"planner": "P2", "executor": "E2", "critic": "C2"},
            "answers": {"planner": "C", "executor": "C", "critic": "C"},
            "gold": "C"}] * 3)
rt = PT.rates(rows)["models"]
check("the planner error rate is measured",
      rt["P1"]["planner"]["planner_error_rate"] == 1.0, rt)
check("an executor repair rate is measured",
      abs(rt["E1"]["executor"]["repair_rate"] - 0.6) < 1e-9, rt)
check("an executor harm rate is measured",
      abs(rt["E2"]["executor"]["harm_rate"] - 0.25) < 1e-9, rt)
check("a critic that never repaired has a zero rate",
      rt["C1"]["critic"]["repair_rate"] == 0.0)
check("a role with no opportunity has a zero rate",
      rt["E2"]["executor"]["repair_rate"] == 0.0)
check("no rows is an empty table", PT.rates([])["models"] == {})

org = PT.origins([{"answers": {"planner": "B", "executor": "B", "critic": "B"},
                   "gold": "C"}] * 3
                 + [{"answers": {"planner": "C", "executor": "C", "critic": "B"},
                     "gold": "C"}])
check("the planner dominates the origins", org["verdict"] == "planner-dominates", org)
check("the planner share is measured", abs(org["planner_share"] - 0.75) < 1e-9)
check("no failure is its own verdict",
      PT.origins([{"answers": {"planner": "C", "executor": "C", "critic": "C"},
                   "gold": "C"}])["verdict"] == "no-failures")

pf = PT.pareto([{"config": "a", "accuracy": 90, "cost": 0.010, "latency": 9},
                {"config": "b", "accuracy": 92, "cost": 0.020, "latency": 18},
                {"config": "c", "accuracy": 88, "cost": 0.008, "latency": 8},
                {"config": "d", "accuracy": 85, "cost": 0.012, "latency": 12}])
check("the frontier keeps every non-dominated point",
      pf["frontier"] == ["a", "b", "c"], pf)
check("a dominated point is marked inefficient",
      [r for r in pf["rows"] if r["config"] == "d"][0]["efficient"] is False)
check("a row without a cost is skipped",
      PT.pareto([{"config": "x", "accuracy": 90}])["rows"] == [])

cast = PT.casting({"models": {
    "P1": {"planner": {"planner_error_rate": 0.0735}},
    "E2": {"executor": {"repair_rate": 0.10, "harm_rate": 0.0025}},
    "C3": {"critic": {"repair_rate": 0.052, "harm_rate": 0.0089}},
    "P1x": {"planner": {"planner_error_rate": 0.40}}}})
check("the best planner is cast", cast["picks"]["planner"] == "P1", cast)
check("the best executor is cast", cast["picks"]["executor"] == "E2")
check("the best critic is cast", cast["picks"]["critic"] == "C3")
check("a heterogeneous cast is reported as mixed", cast["mixed"] is True)
one = PT.casting({"models": {"M": {"planner": {"planner_error_rate": 0.1},
                                   "executor": {"repair_rate": 0.2, "harm_rate": 0.0},
                                   "critic": {"repair_rate": 0.1, "harm_rate": 0.0}}}})
check("one model everywhere is not a mixed cast", one["mixed"] is False)

gn = PT.gain([{"config": "BBB", "simple": 61.42, "accountable": 97.64},
              {"config": "BAB", "simple": 63.78, "accountable": 96.85},
              {"config": "AAA", "simple": 73.23, "accountable": 88.98}])
check("the accountable handoff lifts every configuration",
      gn["verdict"] == "floor-and-ceiling", gn)
check("the mean gain is measured", gn["mean_delta"] > 20)
check("an unstructured pipeline that harms is anti-synergy",
      PT.gain([{"config": "x", "simple": 80, "accountable": 70},
               {"config": "y", "simple": 80, "accountable": 72},
               {"config": "z", "simple": 80, "accountable": 82}])["verdict"]
      == "anti-synergy")
check("no pairs is its own verdict", PT.gain([])["verdict"] == "no-pairs")
check("advise names every missing practice", len(PT.advise({})["findings"]) == 7)
check("a fully declared profile has no finding", PT.advise(
    {k: True for k in ("publishes_a_structured_handoff", "scores_every_stage",
                       "separates_repair_from_harm", "names_the_earliest_origin",
                       "casts_by_measured_role", "reports_pareto_tradeoffs",
                       "compares_to_a_monolith")})["findings"] == [])

# ---- result --------------------------------------------------------------
ok = sum(1 for r in RESULTS if r)
print("\n%d/%d checks passed" % (ok, len(RESULTS)))
sys.exit(0 if ok == len(RESULTS) else 1)
