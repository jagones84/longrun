#!/usr/bin/env python3
"""v1220 — intent contracts, evidence warrants, platform evaluation (round 151).

Sources:
  * arXiv:2611.24025 "Intent Contracts" — goal bounds and the command check,
    NFKC quotation validation, scope narrowing, declaration coverage, exact
    McNemar, the outcome triple, bundled-request completion, the four reference
    categories, and the three properties fixed by dispatch code.
  * arXiv:2611.23990 "SCAFFOLD" — the WRC record, tri-valued admissibility, the
    directed transport judgment, defeasible authorization, provenance
    dependence, composition, and the selective-revalidation cost condition.
  * arXiv:2611.24039 "Capability Framework" — dimension means and totals,
    Cronbach's alpha and the halo, tier separation, non-compensatory gates,
    Wilson reliability and pass^k, cost of pass, and the business-value identity.

Deterministic: plain data in, dicts out; no model, no network, no server.

Run: python3 tests/acceptance/v1220_contract_warrant_platform.py
"""
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="sf-v1220-")
for _key in ("CONFIG_DIR", "SESSIONS_DIR", "GRAPH_DIR", "EDITS_DIR",
             "RUNS_DIR", "DATA_DIR", "THREADS_DIR", "COSTS_DIR", "MEMORY_DIR"):
    os.environ["LONGRUN_" + _key] = os.path.join(TMP, _key)
    os.makedirs(os.environ["LONGRUN_" + _key], exist_ok=True)
os.environ["LONGRUN_DB"] = os.path.join(TMP, "events.db")
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.harness.checks import intent_contract as IC  # noqa: E402
from longrun.harness.checks import evidence_warrant as EW  # noqa: E402
from longrun.harness.checks import platform_eval as PE  # noqa: E402

RESULTS = []


def check(name, ok, detail=""):
    RESULTS.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name
          + ((" :: " + str(detail)) if detail else ""))


def close(a, b, tol=1e-9):
    return a is not None and abs(a - b) <= tol


def kinds(out):
    return [f["kind"] for f in (out.get("findings") or [])]


# ---- 1. intent contracts (arXiv:2611.24025) ---------------------------
CONTRACT = {"goal": "cancel the three stale jobs for ticket 4812",
            "quotation": "please cancel my stale jobs for ticket 4812",
            "user_messages": ["Hi, please cancel my stale jobs for ticket 4812 today."],
            "scope": {"egress_hosts": ["queue.internal"], "write_prefixes": ["/srv/jobs"]},
            "baseline": {"egress_hosts": ["queue.internal", "api.internal"],
                         "write_prefixes": ["/srv"]},
            "error_policy": "abort"}
GOOD = IC.validate(CONTRACT)
check("a complete contract is accepted", GOOD["verdict"] == "contract-accepted")
check("an accepted contract has no reasons", GOOD["reasons"] == [])
check("an empty goal is refused",
      IC.validate({})["reasons"][0] == "goal-missing")
check("a goal over one hundred words is refused",
      "goal-too-long" in IC.validate(dict(CONTRACT, goal="word " * 101))["reasons"])
check("a goal with a shell command is refused",
      "goal-contains-a-command" in
      IC.validate(dict(CONTRACT, goal="rm -rf /srv/jobs"))["reasons"])
check("a goal with a pipe is refused",
      "goal-contains-a-command" in
      IC.validate(dict(CONTRACT, goal="list jobs | xargs cancel"))["reasons"])
check("a paraphrased quotation is refused",
      "quotation-not-verbatim" in
      IC.validate(dict(CONTRACT, quotation="please cancel all my old jobs"))["reasons"])
check("whitespace and full-width text normalize before matching",
      IC.validate(dict(CONTRACT, quotation="please   cancel my stale\n jobs for ticket 4812"))
      ["verdict"] == "contract-accepted")
check("an egress host outside the baseline is refused",
      "egress-not-narrowed" in
      IC.validate(dict(CONTRACT, scope={"egress_hosts": ["evil.example"],
                                        "write_prefixes": ["/srv/jobs"]}))["reasons"])
check("a write prefix outside the baseline is refused",
      "write-prefix-not-narrowed" in
      IC.validate(dict(CONTRACT, scope={"egress_hosts": ["queue.internal"],
                                        "write_prefixes": ["/etc"]}))["reasons"])
check("an unknown error policy is refused",
      "unknown-error-policy" in
      IC.validate(dict(CONTRACT, error_policy="ignore"))["reasons"])
check("a scope may narrow the baseline",
      IC.validate(dict(CONTRACT, scope={"egress_hosts": [],
                                        "write_prefixes": []}))["verdict"]
      == "contract-accepted")
COV = IC.coverage([{"object": "job-1", "named_in_goal": True},
                   {"object": "job-2", "named_in_goal": True},
                   {"object": "job-3", "named_in_goal": True}])
check("full declaration coverage is one", close(COV["goal_coverage"], 1.0))
check("full coverage is named", COV["verdict"] == "fully-declared")
PART = IC.coverage([{"object": "a", "named_in_goal": True},
                    {"object": "b", "named_in_command": True},
                    {"object": "c"}])
check("goal coverage is a share", close(PART["goal_coverage"], 1 / 3))
check("command coverage is measured separately", close(PART["command_coverage"], 1 / 3))
check("an undocumented object is named", PART["undocumented"] == ["c"])
check("a declaration gap is named", PART["verdict"] == "declaration-gap")
check("no changes is its own verdict", IC.coverage([])["verdict"] == "no-changes")
M = IC.mcnemar(1, 9)
check("the exact McNemar p is two hundredths", close(M["p"], 0.021484375, 1e-9))
check("a separated pair is named", M["verdict"] == "separated")
check("a tied pair is indistinguishable",
      IC.mcnemar(2, 2)["p"] > 0.05 and IC.mcnemar(2, 2)["verdict"]
      == "indistinguishable")
check("no discordance has p one", IC.mcnemar(0, 0)["p"] == 1.0)
OUT = IC.outcomes({"runs": 96, "safe": 12, "unauthorized": 10, "incomplete": 76})
check("the safe share is reported", close(OUT["safe_share"], 12 / 96))
check("the unauthorized share is reported", close(OUT["unauthorized_share"], 10 / 96))
check("the outcomes may overlap", OUT["overlap"] is True)
check("no runs is its own verdict", IC.outcomes({})["verdict"] == "no-runs")
BUNDLE = [{"mode": "contract", "main_complete": True}] * 27
BUNDLE += [{"mode": "review", "main_complete": i < 16} for i in range(30)]
B = IC.bundling(BUNDLE)
check("contracts complete the bundled request", close(B["contract"], 1.0))
check("the reviewer completes fewer", close(B["review"], 16 / 30))
check("the gap is positive", B["gap"] > 0)
check("partial execution is named the winner",
      B["verdict"] == "partial-execution-wins")
check("one arm is not a comparison",
      IC.bundling([])["verdict"] == "both-arms-required")
T = IC.targets([{"category": "exact-id", "safe": True}] * 12
               + [{"category": "own-ticket", "safe": True}] * 3
               + [{"category": "own-range", "unauthorized": True}] * 6
               + [{"category": "open-range", "unauthorized": True}] * 4)
check("every category is counted", set(T["categories"]) == set(IC.CATEGORIES))
check("the acting total is reported", T["acting"] == 25)
check("the wrong-target share is in the paper's band",
      close(T["wrong_target_share"], 10 / 25))
check("ambiguity dominates the errors", T["verdict"] == "ambiguity-dominates")
check("the fixed properties are three", IC.fixed_properties()["count"] == 3)
check("the trusted model writes every call",
      "the-trusted-model-writes-every-executed-call" in
      IC.fixed_properties()["properties"])
check("the audit names six misreadings",
      len(IC.audit({"contract_means_authorized": True,
                    "reviewer_is_a_sandbox": True,
                    "coverage_means_correct_target": True,
                    "declaration_substitutes_for_enforcement": True,
                    "whole_command_is_enough": True,
                    "trusted_model_sees_the_environment": True})["findings"]) == 6)
check("an empty record passes the contract audit",
      kinds(IC.audit({})) == ["audit-conditions-met"])
check("an empty harness profile misses all seven habits",
      len(IC.advise({})["findings"]) == 7)
check("a complete harness profile is clean",
      IC.advise({k: True for k in ("keeps_tools_from_the_planner",
                                   "checks_the_quotation_against_the_user",
                                   "narrows_scope_from_a_baseline",
                                   "rejects_a_goal_that_contains_a_command",
                                   "logs_every_contract_before_the_call",
                                   "lets_the_trusted_side_narrow_a_step",
                                   "reports_wrong_targets_on_ambiguous_references")})
      ["findings"] == [])

# ---- 2. evidence warrants (arXiv:2611.23990) ---------------------------
W = EW.wrc({"skill": "invoice-reconcile/3", "context": "c2",
            "proposition": "s may execute within the stated permissions",
            "evidence": ["e1", "e2"], "assumptions": ["policy v2"],
            "defeaters": []})
check("a complete claim is recorded", W["verdict"] == "claim-recorded")
check("the claim carries its fields", set(W["fields"]) == set(EW.WRC_FIELDS))
check("a scalar score is not a warrant",
      EW.wrc({"score_only": True, "skill": "s", "context": "c",
              "proposition": "p", "evidence": ["e"], "assumptions": [],
              "defeaters": []})["verdict"] == "not-a-warrant")
check("a missing field is named",
      EW.wrc({"skill": "s"})["verdict"] == "incomplete-claim")
ITEMS = [
    {"support": True, "premises": {"api": "true"}},
    {"support": True, "premises": {"api": "false"}},
    {"support": True, "premises": {"api": "unknown"}},
    {"support": False, "premises": {"api": "true"}},
]
ADM = EW.admissibility(ITEMS)
check("one item is admissible", ADM["admissible"] == 1)
check("two items are disconfirmed", ADM["disconfirmed"] == 2)
check("one item is unresolved", ADM["unresolved"] == 1)
check("the usable set names its index", ADM["usable"] == [0])
check("no evidence is its own verdict",
      EW.admissibility([])["verdict"] == "no-evidence")
check("a mixed set does not transport",
      EW.transport(ITEMS)["verdict"] == "invalid")
check("a clean set transports",
      EW.transport([{"support": True, "premises": {"api": "true"}}])["verdict"]
      == "valid")
check("an unknown premise leaves transport unresolved",
      EW.transport([{"support": True, "premises": {"api": "unknown"}}])["verdict"]
      == "unresolved")
check("an empty premise set is unresolved, not positive",
      EW.transport([{"support": True, "premises": {}}])["verdict"] == "unresolved")
check("a hard prohibition denies",
      EW.authorize({"hard": ["policy-v2-approval"]})["decision"] == "deny")
check("missing required evidence goes to review",
      EW.authorize({"required": ["tax-check"], "satisfied": []})["decision"]
      == "test/review")
check("unresolved uncertainty goes to review",
      EW.authorize({"required": ["tax-check"], "satisfied": ["tax-check"],
                    "unresolved": ["rounding"]})["decision"] == "test/review")
check("a satisfied claim is allowed",
      EW.authorize({"required": ["tax-check"], "satisfied": ["tax-check"]})
      ["decision"] == "allow")
check("missing evidence is named",
      EW.authorize({"required": ["a", "b"], "satisfied": ["a"]})["missing"] == ["b"])
PROV = EW.provenance({"n": 10, "rho": 0.5})
check("dependent evidence loses effective size",
      close(PROV["effective_n"], 10 / 5.5))
check("dependence is named", PROV["dependence"] == "dependent")
check("an out-of-range rho is refused",
      EW.provenance({"n": 5, "rho": 1.0})["verdict"] == "rho-out-of-range")
check("a short provenance record is refused",
      EW.provenance({"n": 0})["verdict"] == "insufficient-input")
check("a one-hop chain is not a composition",
      EW.composition({"steps": 1})["verdict"] == "not-a-chain")
check("a stable chain is admissible across two hops",
      EW.composition({"steps": 2, "premises_stable": True,
                      "same_interpretation": True})["verdict"]
      == "admissible-in-target")
COMP = EW.composition({"steps": 2, "premises_stable": True,
                       "same_interpretation": True, "unrecorded_defeaters": True})
check("an unrecorded defeater forces reassessment",
      COMP["verdict"] == "reassess-transport")
check("the broken condition is named", COMP["reasons"] == ["unrecorded-defeater"])
SEL = EW.selective({"obligations": 12, "changed": 3, "per_check": 1,
                    "map_cost": 0})
check("full retesting costs every obligation", close(SEL["full"], 12.0))
check("selective retesting costs the changed ones", close(SEL["selective"], 3.0))
check("the saving is nine checks", close(SEL["saving"], 9.0))
check("nine retained obligations are counted", SEL["retained"] == 9)
check("selective retesting is cheaper", SEL["verdict"] == "selective-cheaper")
COSTLY = EW.selective({"obligations": 12, "changed": 3, "per_check": 1,
                       "map_cost": 10})
check("an expensive map erases the saving",
      close(COSTLY["saving"], -1.0) and COSTLY["verdict"] == "mapping-too-costly")
check("changed above obligations is refused",
      EW.selective({"obligations": 2, "changed": 3, "per_check": 1})
      ["verdict"] == "changed-out-of-range")
check("the audit names six misreadings",
      len(EW.audit({"evidence_means_claim_true": True,
                    "compliance_means_goal_met": True,
                    "transport_is_symmetric": True,
                    "premises_assumed_complete": True,
                    "provenance_diversity_is_correctness": True,
                    "ledger_is_a_safety_certificate": True})["findings"]) == 6)
check("an empty record passes the warrant audit",
      kinds(EW.audit({})) == ["audit-conditions-met"])
check("an empty harness profile misses all seven habits",
      len(EW.advise({})["findings"]) == 7)
check("a complete harness profile is clean",
      EW.advise({k: True for k in ("states_the_claim_before_reuse",
                                   "names_the_premises_of_reuse",
                                   "treats_unknown_as_unresolved",
                                   "keeps_negative_evidence_as_a_defeater",
                                   "recomputes_prohibitions_before_the_decision",
                                   "reports_transport_as_directional",
                                   "prices_the_dependency_map")})["findings"] == [])

# ---- 3. platform evaluation (arXiv:2611.24039) -------------------------
MATRIX = [
    {"platform": "H2O.ai", "scores": [7.44, 7.22, 7.44, 7.78, 7.56, 8.00, 7.22, 8.11, 8.44]},
    {"platform": "Google", "scores": [7.00, 7.57, 7.57, 7.71, 8.86, 6.00, 7.86, 7.57, 7.00]},
    {"platform": "Microsoft", "scores": [7.00, 6.67, 7.00, 7.50, 7.17, 5.00, 8.17, 7.50, 7.00]},
    {"platform": "Writer", "scores": [7.14, 6.86, 6.86, 7.29, 7.14, 7.57, 6.86, 6.86, 6.43]},
    {"platform": "Letta", "scores": [6.43, 6.57, 7.86, 7.43, 7.29, 6.71, 6.57, 6.57, 6.29]},
    {"platform": "Glean", "scores": [4.00, 4.33, 4.67, 4.67, 5.00, 5.00, 5.33, 5.00, 5.00]},
    {"platform": "CrewAI", "scores": [3.90, 5.40, 3.60, 4.30, 4.40, 5.70, 5.10, 4.70, 4.50]},
    {"platform": "UiPath", "scores": [4.40, 5.20, 5.00, 4.00, 4.00, 6.40, 4.20, 4.00, 4.20]},
    {"platform": "Portia AI", "scores": [2.33, 5.33, 5.00, 4.33, 4.33, 5.67, 4.67, 3.00, 2.33]},
    {"platform": "Squid AI", "scores": [3.33, 3.33, 3.50, 3.50, 4.00, 3.67, 3.67, 3.50, 3.50]},
]
S = PE.score(MATRIX)
check("ten platforms are scored", S["platforms"] == 10)
check("nine dimensions are scored", S["dimensions"] == 9)
check("the top total is the paper's 69.2", round(S["totals"]["H2O.ai"], 1) == 69.2)
check("the second total is the paper's 67.1", round(S["totals"]["Google"], 1) == 67.1)
check("the bottom total is the paper's 32.0", round(S["totals"]["Squid AI"], 1) == 32.0)
check("the ease-of-use spread is the paper's 1.28",
      round(S["sd"][5], 2) == 1.28)
check("ease of use is the weakest pull",
      S["correlations"]["ease_of_use"] == min(
          v for v in S["correlations"].values() if v is not None))
A = PE.alpha(MATRIX)
check("alpha matches the paper's 0.98", round(A["alpha"], 2) == 0.98)
check("the halo is suspected", A["verdict"] == "halo-suspected")
check("alpha is computed over nine items", A["items"] == 9)
check("too few cases is refused", PE.alpha([MATRIX[0]])["verdict"] == "too-few-cases")
TIERS = PE.tiers(S["totals"])
check("three tiers are produced", len(TIERS["tiers"]) == 3)
check("tier one holds five platforms", len(TIERS["tiers"][0]) == 5)
check("tier two holds three platforms", len(TIERS["tiers"][1]) == 3)
check("tier three holds two platforms", len(TIERS["tiers"][2]) == 2)
check("the largest gap is the paper's 18.7", round(TIERS["largest_gap"], 1) == 18.7)
check("the tiers are separated", TIERS["verdict"] == "tiers-separated")
G = PE.gates({"platforms": [
    {"platform": "ok", "gates": {g: True for g in PE.GATES},
     "scores": {"reflection": 8, "tool_use": 6}},
    {"platform": "blocked", "gates": dict({g: True for g in PE.GATES},
                                          injection=False),
     "scores": {"reflection": 10, "tool_use": 10}},
]})
check("a failing gate excludes the platform", [e["platform"] for e in G["excluded"]]
      == ["blocked"])
check("the failed gate is named", G["excluded"][0]["failed"] == ["injection"])
check("the surviving platform is best", G["best"] == "ok")
check("a high score cannot compensate a gate",
      "blocked" not in [a["platform"] for a in G["admitted"]])
REL = PE.reliability({"successes": 7, "runs": 10, "k": 3})
check("task success is a share", close(REL["p"], 0.7))
check("the Wilson interval contains the estimate",
      REL["low"] < REL["p"] < REL["high"])
check("the Wilson interval is the paper's method", round(REL["low"], 3) == 0.397)
check("pass-k is the k-th power", close(REL["pass_k"], 0.343))
check("an impossible count is refused",
      PE.reliability({"successes": 5, "runs": 4})["verdict"] == "insufficient-input")
check("cost of pass divides by successes",
      close(PE.cost_of_pass({"total_cost": 1000, "successes": 4})["cost_of_pass"],
            250.0))
check("no success is its own verdict",
      PE.cost_of_pass({"total_cost": 100, "successes": 0})["verdict"] == "no-success")
BV = PE.business_value({"time_saved": 100, "avoided_error": 50, "revenue": 10,
                        "compute": 30, "tooling": 10, "oversight": 20,
                        "expected_loss": 20})
check("net value adds the gains and subtracts the costs", close(BV["net"], 80.0))
check("a positive value is named", BV["verdict"] == "positive-value")
check("a loss can dominate net value",
      PE.business_value({"time_saved": 10, "expected_loss": 50})["verdict"]
      == "negative-value")
check("the audit names seven misreadings",
      len(PE.audit({"treats_dimensions_as_independent": True,
                    "demonstration_as_capability": True,
                    "capability_compensates_for_a_gate": True,
                    "single_run_as_reliability": True,
                    "ordinal_as_interval": True,
                    "vendor_figures_unverified": True,
                    "no_ground_truth": True})["findings"]) == 7)
check("an empty record passes the platform audit",
      kinds(PE.audit({})) == ["audit-conditions-met"])
check("an empty harness profile misses all seven habits",
      len(PE.advise({})["findings"]) == 7)
check("a complete harness profile is clean",
      PE.advise({k: True for k in ("scores_evidence_artefacts_not_narration",
                                   "reports_reliability_statistics",
                                   "gates_before_it_scores",
                                   "tags_tools_by_scope_and_reversibility",
                                   "measures_cost_of_pass",
                                   "prices_oversight_and_risk",
                                   "pins_versions_and_reruns")})["findings"] == [])

# ---- summary ----------------------------------------------------------
passed = sum(1 for r in RESULTS if r)
print("\n%d/%d checks passed" % (passed, len(RESULTS)))
sys.exit(0 if passed == len(RESULTS) else 1)
