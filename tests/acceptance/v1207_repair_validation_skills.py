#!/usr/bin/env python3
"""v1207 — repair audit, validation ladder, skill grounding (round 138).

Sources:
  * arXiv:2611.22991 "RagHarnessDebugger" — repair churn, acceptance gap,
    provenance and a priced veto.
  * arXiv:2611.22973 "VITAL" — a risk ladder, eight controls, five behavioural
    domains, ten evidence categories and real oversight.
  * arXiv:2611.23203 "Agent Skills" — progressive disclosure, an independent
    verifier, typed verdicts and measured savings.

Deterministic: plain data in, dicts out; no model, no network, no server.

Run: python3 tests/acceptance/v1207_repair_validation_skills.py
"""
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="sf-v1207-")
for _key in ("CONFIG_DIR", "SESSIONS_DIR", "GRAPH_DIR", "EDITS_DIR",
             "RUNS_DIR", "DATA_DIR", "THREADS_DIR", "COSTS_DIR", "MEMORY_DIR"):
    os.environ["LONGRUN_" + _key] = os.path.join(TMP, _key)
    os.makedirs(os.environ["LONGRUN_" + _key], exist_ok=True)
os.environ["LONGRUN_DB"] = os.path.join(TMP, "events.db")
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.harness import repair_audit as RA          # noqa: E402
from longrun.harness import validation_ladder as VL    # noqa: E402
from longrun.harness import skill_grounding as SG      # noqa: E402

RESULTS = []


def check(name, ok, detail=""):
    RESULTS.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name
          + ((" :: " + str(detail)) if detail else ""))


def kinds(out):
    return [f["kind"] for f in (out.get("findings") or [])]


# ---- 1. repair audit ----------------------------------------------------
rows = ([{"outcome": "repair"}] * 20 + [{"outcome": "regression"}] * 5
        + [{"outcome": "kept"}] * 75)
c1 = RA.churn(rows)
check("20 repairs against 5 regressions is a net repair",
      abs(c1["net"] - 0.15) < 1e-9 and "net-repair" in kinds(c1), c1)
c2 = RA.churn([{"outcome": "repair"}] * 20 + [{"outcome": "regression"}] * 20
              + [{"outcome": "kept"}] * 60)
check("equal repairs and regressions are churn", "repair-churn" in kinds(c2), c2)
check("more regressions than repairs is named",
      "net-regression" in kinds(RA.churn([{"outcome": "regression"}] * 5
                                         + [{"outcome": "kept"}] * 95)))
check("no repairs at all is named",
      "no-repair-behaviour" in kinds(RA.churn([{"outcome": "kept"}])))
check("an empty log is refused", "no-executions" in kinds(RA.churn([])))

r1 = RA.reachability({"initial_correct": False, "final_correct": True})
check("a wrong answer made right is a repair", "repair" in kinds(r1), r1)
r2 = RA.reachability({"initial_correct": True, "final_correct": False})
check("a right answer made wrong is a regression", "regression" in kinds(r2), r2)
r3 = RA.reachability({"initial_correct": False, "final_correct": False,
                      "available": False})
check("no correct candidate is unreachable", "unreachable-candidate" in kinds(r3), r3)
r4 = RA.reachability({"initial_correct": False, "final_correct": False,
                      "available": True, "admitted": False})
check("an available candidate blocked by acceptance is named",
      "acceptance-blocked" in kinds(r4), r4)
r5 = RA.reachability({"initial_correct": False, "final_correct": False,
                      "available": True, "admitted": True, "selected": False})
check("an admitted candidate not selected is named",
      "selection-blocked" in kinds(r5), r5)

check("a validation that did not read its candidate is named",
      "validation-mismatch" in kinds(RA.failure({"validation_applies": False})))
check("an acceptance rule that excludes the label is named",
      "acceptance-excludes-label" in kinds(RA.failure({"label_admissible": False})))
check("an action that cannot change the block is named",
      "no-action-can-change" in kinds(RA.failure({"action_can_change": False})))
check("a sound candidate has no structural failure",
      kinds(RA.failure({})) == ["no-structural-failure"])

check("a follow-up whose reachable set omits the answer is named",
      "correct-outside-reachable-set" in kinds(RA.capability(
          {"follow_up": True, "correct_label": "a", "reachable_labels": ["b", "c"]})))
check("a follow-up that can reach the answer is capable",
      "intervention-capable" in kinds(RA.capability(
          {"follow_up": True, "correct_label": "a", "reachable_labels": ["a", "b"]})))
check("a follow-up that ran without changing the set is named",
      "intervention-cannot-change" in kinds(RA.capability(
          {"intervention_attempted": True, "changed_eligible": False})))

fl = RA.flags([{"flagged": True, "missed_repair": True}] * 10
              + [{"flagged": True, "missed_repair": False}] * 5
              + [{"flagged": False, "missed_repair": True}] * 2
              + [{"flagged": False, "missed_repair": False}] * 83)
check("a flag that finds most misses in few executions triages",
      "flag-triage" in kinds(fl), fl)
check("the flag recall is computed over missed repairs",
      abs(fl["recall"] - 10 / 12.0) < 1e-3, fl)
check("a flag that fires on a third of the set is not predictive",
      "flag-not-predictive" in kinds(RA.flags(
          [{"flagged": True, "missed_repair": True}] * 10
          + [{"flagged": True, "missed_repair": False}] * 20
          + [{"flagged": False, "missed_repair": False}] * 70)))
check("no missed repairs is named",
      "no-missed-repairs" in kinds(RA.flags([{"flagged": True, "missed_repair": False}])))

pv = RA.provenance({"request_keys": True, "chain_intact": True,
                    "ledger_append_only": True, "replay_recorded_dependencies": True})
check("a keyed, chained, append-only trace verifies",
      kinds(pv) == ["provenance-verified"], pv)
check("an unkeyed request is named",
      "requests-not-keyed" in kinds(RA.provenance({"chain_intact": True})))
check("a broken chain is named",
      "chain-broken" in kinds(RA.provenance({"request_keys": True})))
check("a rewritable ledger is named",
      "ledger-rewritable" in kinds(RA.provenance({"request_keys": True,
                                                  "chain_intact": True})))
check("an unsupported replay is named",
      "replay-unsupported" in kinds(RA.provenance({"request_keys": True,
                                                   "chain_intact": True,
                                                   "ledger_append_only": True})))

vt = RA.veto([{"effect": "regression-prevented"}] * 8 + [{"effect": "repair-blocked"}] * 3)
check("a veto whose prevented regressions exceed blocked repairs is positive",
      "veto-net-positive" in kinds(vt) and vt["net"] == 5, vt)
check("a veto reports its cost", "veto-has-cost" in kinds(vt), vt)
check("a veto that blocks more than it prevents is negative",
      "veto-net-negative" in kinds(RA.veto(
          [{"effect": "regression-prevented"}] * 2 + [{"effect": "repair-blocked"}] * 5)))
check("no veto records is named", "no-veto-records" in kinds(RA.veto([])))
check("advise names every missing practice", len(RA.advise({})["findings"]) == 8)
check("a fully declared profile has no finding", RA.advise(
    {k: True for k in ("records_decisions", "reports_repairs_and_regressions",
                       "measures_acceptance_gap", "checks_validation_applicability",
                       "checks_reachability", "prices_the_veto",
                       "uses_labels_after_audit", "keeps_provenance")})["findings"] == [])

# ---- 2. validation ladder ----------------------------------------------
rk = VL.risk({"autonomy": 8, "reversibility": 1.0, "transparency": 1.0,
              "patient_impact": 1.25})
check("the epidemiology score is 10 and High", rk["score"] == 10.0 and rk["class"] == "high", rk)
check("a high class is named", "high-risk-class" in kinds(rk), rk)
rk2 = VL.risk({"autonomy": 5.5, "reversibility": 1.0, "transparency": 1.25,
               "patient_impact": 1.0})
check("the site-selection score is Moderate", rk2["class"] == "moderate", rk2)
rk3 = VL.risk({"autonomy": 9, "reversibility": 1.5, "transparency": 1.5,
               "patient_impact": 1.5})
check("the trial-design score is Very High", rk3["class"] == "very-high", rk3)
floor = VL.risk({"autonomy": 3, "patient_impact": 3.0})
check("direct patient impact applies a floor",
      "patient-floor-applied" in kinds(floor) and floor["class"] == "very-high", floor)
crit = VL.risk({"autonomy": 8, "patient_impact": 3.0})
check("high autonomy with direct patient impact is Critical",
      crit["class"] == "critical", crit)
check("an invalid autonomy is refused",
      "invalid-autonomy" in kinds(VL.risk({"autonomy": 12})))
check("a non-positive multiplier is refused",
      "invalid-multiplier" in kinds(VL.risk({"autonomy": 5, "reversibility": 0})))

au = VL.autonomy({"nominal": 5, "effective": 7, "isolation": False, "termination": False})
check("effective autonomy above nominal is named",
      "effective-exceeds-nominal" in kinds(au), au)
check("a missing isolation control is named", "no-isolation" in kinds(au), au)
check("a run that cannot be terminated is named", "cannot-terminate" in kinds(au), au)
check("bounded autonomy is named",
      "autonomy-bounded" in kinds(VL.autonomy({"nominal": 7, "effective": 5,
                                                "isolation": True, "termination": True})))

ct = VL.controls({"controls": ["quality-governance", "data-governance"]})
check("missing controls are named one by one",
      sum(1 for f in ct["findings"] if f["kind"] == "missing-control") == 6, ct)
check("a complete control set is accepted",
      kinds(VL.controls({"controls": list(VL.CONTROLS)})) == ["controls-complete"])

do = VL.domains({"domains": ["reasoning-planning"]})
check("unvalidated behavioural domains are named",
      sum(1 for f in do["findings"] if f["kind"] == "domain-unvalidated") == 4, do)
check("an oversight without authority is ineffective",
      "oversight-ineffective" in kinds(VL.domains(
          {"domains": list(VL.DOMAINS),
           "oversight": {"present": True, "informed": True, "time": True}})))
check("oversight with information, authority and time is effective",
      "oversight-effective" in kinds(VL.domains(
          {"domains": list(VL.DOMAINS),
           "oversight": {"present": True, "informed": True,
                         "authority": True, "time": True}})))
check("a fully validated behaviour is named",
      kinds(VL.domains({"domains": list(VL.DOMAINS)})) == ["behaviour-validated"])

ev = VL.evidence({"class": "critical", "evidence": ["context-of-use"]})
check("a critical class needs the full evidence set",
      "evidence-insufficient" in kinds(ev) and ev["required"] == 10, ev)
check("a moderate class needs six categories",
      VL.evidence({"class": "moderate", "evidence": list(VL.EVIDENCE[:6])})["required"] == 6)
check("a proportionate evidence set is named",
      kinds(VL.evidence({"class": "critical", "evidence": list(VL.EVIDENCE)})) == ["evidence-proportionate"])

cal = VL.calibrate([{"score": 6.1, "still_lowest": True, "class_changed": False},
                    {"score": 17.6, "still_highest": True, "class_changed": True}])
check("a class change under calibration is named", "class-unstable" in kinds(cal), cal)
check("a stable ordering is named", "ordering-stable" in kinds(cal), cal)
check("one case is not a calibration",
      "not-enough-cases" in kinds(VL.calibrate([{"score": 5}])))
check("advise names every missing practice", len(VL.advise({})["findings"]) == 8)
check("a fully declared profile has no finding", VL.advise(
    {k: True for k in ("assesses_intrinsic_risk", "uses_effective_autonomy",
                       "applies_consequence_floor", "requires_controls",
                       "validates_trajectories", "tests_oversight",
                       "documents_evidence", "calibrates_thresholds")})["findings"] == [])

# ---- 3. skill grounding -------------------------------------------------
sk = SG.skill({"layers": list(SG.LAYERS), "verifier_independent": True,
               "generator_independent": True, "reverifies_after": True})
check("a fully grounded skill is accepted", kinds(sk) == ["grounded-skill"], sk)
check("a missing root-cause layer breaks progressive disclosure",
      "no-progressive-disclosure" in kinds(SG.skill({"layers": ["index"]})))
check("an agent-measured repair is named",
      "agent-measures-own-work" in kinds(SG.skill({"layers": list(SG.LAYERS),
                                                    "generator_independent": True})))
check("a skill that edits the repository is named",
      "skill-edits-repository" in kinds(SG.skill({"layers": list(SG.LAYERS),
                                                   "verifier_independent": True,
                                                   "generator_independent": True,
                                                   "edits_repository": True})))
check("a skill without re-verification is named",
      "no-verification" in kinds(SG.skill({"layers": list(SG.LAYERS),
                                           "verifier_independent": True,
                                           "generator_independent": True})))

eq = SG.equivalence({"same_return": True, "same_args": True,
                     "same_printed": False, "same_files": True})
check("a differing printed output is not equivalent",
      "not-equivalent" in kinds(eq) and eq["differing"] == ["printed"], eq)
check("a repair that does not run is named",
      "repair-does-not-run" in kinds(SG.equivalence({"ran": False})))
check("an equivalent repair is named", kinds(SG.equivalence({})) == ["equivalent"])

v1 = SG.verdict({"savings": [0.2, 0.3, 0.25, 0.1], "noise_floor": 0.01})
check("saving on all four inputs is confirmed", v1["verdict"] == "confirmed", v1)
v2 = SG.verdict({"savings": [0.2, 0.0, 0.0, 0.3], "noise_floor": 0.01})
check("saving on some inputs only is partial", v2["verdict"] == "partial", v2)
v3 = SG.verdict({"savings": [0.2, -0.1, 0.0, 0.0], "noise_floor": 0.01})
check("saving on some and costing on others is mixed", v3["verdict"] == "mixed", v3)
check("costing on every changing input is regressed",
      SG.verdict({"savings": [-0.2, 0.0], "noise_floor": 0.01})["verdict"] == "regressed")
check("no change beyond the floor is negligible",
      SG.verdict({"savings": [0.0, 0.005], "noise_floor": 0.01})["verdict"] == "negligible")
check("a high noise floor without a clear result is inconclusive",
      SG.verdict({"savings": [0.02, 0.01], "noise_floor": 0.05})["verdict"] == "inconclusive")
check("a repair that costs energy is named",
      "repair-costs-energy" in kinds(SG.verdict({"savings": [0.2, -0.2],
                                                  "noise_floor": 0.01})))
check("no measurements is named", "no-measurements" in kinds(SG.verdict({})))

se = SG.session([{"verdict": "confirmed", "median_saving": 0.3}] * 7
                + [{"verdict": "regressed"}] * 3)
check("a saving share above half is named", "repairs-save" in kinds(se), se)
check("the median saving is reported", se["median"] == 0.3, se)
check("inconclusive repairs are reported",
      "inconclusive-present" in kinds(SG.session(
          [{"verdict": "confirmed"}, {"verdict": "inconclusive"}])))
check("no repairs is named", "no-repairs" in kinds(SG.session([])))

ly = SG.layers([{"skill": "core", "smelly": 40, "median_saving": 50.0},
                {"skill": "core+tax", "smelly": 83, "median_saving": 30.0},
                {"skill": "full", "smelly": 102, "median_saving": 20.0}])
check("the taxonomy widens the search", "taxonomy-widens-search" in kinds(ly), ly)
check("the analyzer adds findings", "analyzer-adds-findings" in kinds(ly), ly)
check("a wider search finds smaller savings",
      "wider-search-smaller-savings" in kinds(ly), ly)
check("no sessions is named", "no-sessions" in kinds(SG.layers([])))
check("advise names every missing practice", len(SG.advise({})["findings"]) == 8)
check("a fully declared profile has no finding", SG.advise(
    {k: True for k in ("grounds_in_taxonomy", "loads_knowledge_lazily",
                       "separates_verifier", "checks_equivalence",
                       "measures_against_noise", "remeasures_after",
                       "compares_layers", "reports_inconclusive")})["findings"] == [])

# ---- result --------------------------------------------------------------
ok = sum(1 for r in RESULTS if r)
print("\n%d/%d checks passed" % (ok, len(RESULTS)))
sys.exit(0 if ok == len(RESULTS) else 1)
