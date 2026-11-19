#!/usr/bin/env python3
"""v1210 — defense envelope, execution fingerprint, model handoff (round 141).

Sources:
  * arXiv:2611.23844 "Weighing the Envelope" — A/B/C/D, component weight,
    backend arbitration, label content, memory dose, tool roles.
  * arXiv:2610.32092 "AgentTrace" — initial outcome plus ordered repair
    trajectory, Markov profiling, attribution margin, budget and robustness.
  * arXiv:2610.07816 "Do I Need the Cloud?" — per-step local/verify/cloud gate,
    signal families, calibration, budget matching, minimized packets, recovery,
    saturation.

Deterministic: plain data in, dicts out; no model, no network, no server.

Run: python3 tests/acceptance/v1210_envelope_fingerprint_handoff.py
"""
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="sf-v1210-")
for _key in ("CONFIG_DIR", "SESSIONS_DIR", "GRAPH_DIR", "EDITS_DIR",
             "RUNS_DIR", "DATA_DIR", "THREADS_DIR", "COSTS_DIR", "MEMORY_DIR"):
    os.environ["LONGRUN_" + _key] = os.path.join(TMP, _key)
    os.makedirs(os.environ["LONGRUN_" + _key], exist_ok=True)
os.environ["LONGRUN_DB"] = os.path.join(TMP, "events.db")
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.harness.checks import defense_envelope as DE  # noqa: E402
from longrun.harness.checks import execution_fingerprint as EF  # noqa: E402
from longrun.harness.checks import model_handoff as MH  # noqa: E402

RESULTS = []


def check(name, ok, detail=""):
    RESULTS.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name
          + ((" :: " + str(detail)) if detail else ""))


def kinds(out):
    return [f["kind"] for f in (out.get("findings") or [])]


# ---- 1. defense envelope (Weighing the Envelope) ------------------------
mixed = ([{"class": "A"}] * 18 + [{"class": "B"}] + [{"class": "D"}])
out = DE.outcomes(mixed)
check("the four-way outcome tally is kept",
      out["tally"] == {"A": 18, "B": 1, "C": 0, "D": 1}, out)
check("semantic breach is B+C+D", abs(out["semantic_breach_rate"] - 0.10) < 1e-9)
check("penetration is D alone", abs(out["penetration_rate"] - 0.05) < 1e-9)
check("refusal is A alone", abs(out["refusal_rate"] - 0.90) < 1e-9)
check("a blocked label is named", out["verdict"] == "label-suppresses", out)
leak = DE.outcomes([{"class": "A", "local_leak": True}] * 9
                   + [{"class": "D", "local_leak": True}])
check("low penetration with local leakage is not safety",
      leak["verdict"] == "low-penetration-is-not-safety", leak)
check("the local leak rate is measured", abs(leak["local_leak_rate"] - 1.0) < 1e-9)
check("a persisting breach is named",
      DE.outcomes([{"class": "A"}] * 5 + [{"class": "D"}] * 15)["verdict"]
      == "breach-persists")
check("no cells is its own verdict", DE.outcomes([])["verdict"] == "no-cells")

w = DE.weight({"base": 0.906, "label": 0.094, "memory": 1.0,
               "both": 0.617, "downgraded": 0.044})
check("the label is effective", "label-effective" in kinds(w), w)
check("strong memory suppresses the label",
      "memory-suppresses-label" in kinds(w), w)
check("the co-located outcome is intermediate",
      "co-located-intermediate" in kinds(w), w)
check("the memory downgrade restores the label",
      "memory-downgrade-restores" in kinds(w), w)
check("an incomplete arm set is refused",
      DE.weight({"base": 0.9, "label": 0.1})["verdict"] == "arms-incomplete")

arb = DE.arbitration({
    "glm": {"label": 0.100, "both": 0.167},
    "deepseek": {"label": 0.0, "both": 0.900},
    "minimax": {"label": 0.183, "both": 0.783}})
check("the backend decides the winner", arb["verdict"] == "backend-arbitrated", arb)
check("glm gives the label the win", arb["rows"][0]["winner"] == "label-dominant")
check("deepseek gives memory the win", arb["rows"][1]["winner"] == "memory-dominant")
check("the gap is reported per backend", abs(arb["rows"][2]["gap"] - 0.60) < 1e-9)
check("no backends is its own verdict",
      DE.arbitration({})["verdict"] == "no-backends")
check("a label that wins everywhere is portable",
      DE.arbitration({"a": {"label": 0.1, "both": 0.12},
                      "b": {"label": 0.2, "both": 0.25}})["verdict"]
      == "label-portable")

ct = DE.content({"forced": 0.100, "provenance": 0.867, "placebo": 0.967})
check("the ingredient is content, not format", ct["verdict"] == "semantics-not-format")
check("the provenance-only gap is measured",
      abs(ct["provenance_gap"] - 0.767) < 1e-9)
check("the placebo gap is measured", abs(ct["placebo_gap"] - 0.867) < 1e-9)
check("an equal-length placeholder cannot be separated",
      DE.content({"forced": 0.80, "provenance": 0.85, "placebo": 0.83})
      ["verdict"] == "format-cannot-be-separated")
check("an incomplete content arm is refused",
      DE.content({"forced": 0.1})["verdict"] == "arms-incomplete")

dose = DE.dose([{"level": "C", "breach": 0.075},
                {"level": "WEAK", "breach": 0.225},
                {"level": "APPROVED", "breach": 0.350},
                {"level": "DIRECTIVE", "breach": 0.450},
                {"level": "SM", "breach": 0.850}])
check("memory dose erodes the label", dose["verdict"] == "dose-erodes-monotonically", dose)
check("the dose spread is measured", abs(dose["spread"] - 0.775) < 1e-9)
check("a non-monotonic backend is named",
      DE.dose([{"level": "a", "breach": 0.15}, {"level": "b", "breach": 0.45},
               {"level": "c", "breach": 0.50}, {"level": "d", "breach": 0.40},
               {"level": "e", "breach": 0.75}])["verdict"] == "dose-non-monotonic")
check("the drop position is reported",
      DE.dose([{"level": "a", "breach": 0.5}, {"level": "b", "breach": 0.3}])
      ["drops"][0]["at"] == "b")
check("a flat dose is named",
      DE.dose([{"level": "a", "breach": 0.20}, {"level": "b", "breach": 0.21}])
      ["verdict"] == "dose-flat")
check("one level is not a dose", DE.dose([{"level": "a", "breach": 0.2}])
      ["verdict"] == "not-enough-levels")

roles = DE.roles({
    "benign": {"call_rate": 0.517, "completion": 0.967, "substitution": 0.45},
    "coexisting": {"call_rate": 0.022, "benign_call_rate": 0.383,
                   "completion": 0.961},
    "necessary": {"call_rate": 0.350, "local_leak_rate": 0.761,
                  "completion": 0.344}})
check("a benign tool is substitution, not harm",
      "substitution-not-harm" in roles["verdicts"], roles)
check("coexisting tools are suppressed",
      "suppression-of-both" in roles["verdicts"], roles)
check("a necessary tool is boundary failure",
      "boundary-failure" in roles["verdicts"], roles)
check("an unmeasured role is named",
      DE.roles({})["verdicts"] == ["role-unmeasured"])

check("a second label is not an addition",
      DE.stack({"combined": 0.617,
                "parts": [{"name": "label", "alone": 0.094},
                          {"name": "memory", "alone": 0.617}]})
      ["verdict"] == "stack-does-not-add")
check("a stack that helps is named",
      DE.stack({"combined": 0.02, "parts": [{"name": "label", "alone": 0.094}]})
      ["verdict"] == "stack-adds")
check("a marginal stack is named",
      DE.stack({"combined": 0.08, "parts": [{"name": "label", "alone": 0.094}]})
      ["verdict"] == "stack-marginal")
check("an incomplete stack is refused",
      DE.stack({"parts": []})["verdict"] == "incomplete")

bad_audit = DE.audit({"label_treated_as_gate": False,
                      "penetration_is_safety": True,
                      "verifies_provenance_only": True,
                      "memory_counts_as_authorization": True,
                      "single_backend": True})
check("all four misreadings are named", len(bad_audit["findings"]) == 4, bad_audit)
check("a hard gate is refused",
      "label-is-not-a-hard-gate" in kinds(DE.audit({})))
check("a clean record passes", kinds(DE.audit(
    {"label_treated_as_gate": False, "penetration_is_safety": False,
     "verifies_provenance_only": False, "memory_counts_as_authorization": False,
     "single_backend": False})) == ["envelope-read-correctly"])
check("advise names every missing practice", len(DE.advise({})["findings"]) == 7)
check("a fully declared profile has no finding", DE.advise(
    {k: True for k in ("scores_semantic_breach", "keeps_a_local_leak_flag",
                       "requires_implementation_inspection",
                       "downgrades_memory_explicitly", "measures_per_backend",
                       "tests_the_tool_role", "does_not_sum_components")})
    ["findings"] == [])

# ---- 2. execution fingerprint (AgentTrace) ------------------------------
one = EF.trace([{"status": "success"}])
check("a single successful step is a single-step trace",
      one["verdict"] == "single-step", one)
check("a single step has no repair sequence", one["repairs"] == [])
repaired = EF.trace([{"error": "JSONDecodeError"},
                     {"error": "ValidationError"},
                     {"status": "success"}])
check("the initial outcome is the first failure", repaired["initial"] == "JSONDecodeError")
check("the repair order is preserved",
      repaired["repairs"] == ["ValidationError", "success"], repaired)
check("the trace length is measured", repaired["length"] == 3)
check("an empty trace is refused", EF.trace([])["verdict"] == "empty-trace")

A_traces = [[{"error": "JSONDecodeError"}, {"error": "ValidationError"},
             {"status": "success"}]] * 3
B_traces = [[{"error": "ArgumentTruncation"}, {"status": "success"}]] * 3
pa, pb = EF.profile(A_traces), EF.profile(B_traces)
check("the profile counts its traces", pa["traces"] == 3)
check("the initial outcome has a smoothed probability",
      0.0 < pa["initial"]["JSONDecodeError"] < 1.0, pa["initial"])
check("the transition table is smoothed",
      "JSONDecodeError>ValidationError" in pa["transitions"], pa["transitions"])
check("a different trace gets a worse likelihood under A",
      EF.loglik(B_traces[0], pa) < EF.loglik(A_traces[0], pa))
check("the profile knows the vocabulary", "ValidationError" in pa["vocab"])

att = EF.attribute(A_traces, {"A": pa, "B": pb})
check("the matching model is attributed", att["best"] == "A", att)
check("the margin is reported", att["margin"] > 0)
check("no profiles leaves the case open",
      EF.attribute(A_traces, {})["verdict"] == "not-enough-evidence")
close = EF.attribute(A_traces, {"A": pa, "B": EF.profile(A_traces)})
check("two identical profiles are undetermined",
      close["verdict"] == "undetermined" and abs(close["margin"]) < 1e-9, close)

sep = EF.separation([{"model": "Llama-3-8B", "initial": 0.50,
                      "sequential": 0.93, "chance": 0.50}])
check("initial outcome collapsing to chance requires the sequence",
      sep["verdict"] == "sequence-required", sep)
check("the collapsed model is named", sep["collapsed"] == ["Llama-3-8B"])
check("a sequence that helps is named",
      EF.separation([{"model": "m", "initial": 0.80, "sequential": 0.90}])
      ["verdict"] == "sequence-helps")
check("a sequence that adds nothing is named",
      EF.separation([{"model": "m", "initial": 0.95, "sequential": 0.95}])
      ["verdict"] == "sequence-unneeded")
check("no separation rows is its own verdict",
      EF.separation([])["verdict"] == "no-rows")

bud = EF.budget([{"q": 50, "accuracy": 0.960}, {"q": 1, "accuracy": 0.652},
                 {"q": 10, "accuracy": 0.928}, {"q": 5, "accuracy": 0.865}])
check("the smallest usable budget is found", bud["minimum_budget"] == 10, bud)
check("a cheap budget is named", bud["verdict"] == "cheap-attribution")
check("the curve is sorted by budget", [r["q"] for r in bud["rows"]] == [1, 5, 10, 50])
check("an insufficient budget is named",
      EF.budget([{"q": 1, "accuracy": 0.5}])["verdict"] == "budget-insufficient")

rob = EF.robustness([{"condition": "default", "accuracy": 0.945},
                     {"condition": "persona-cloak", "accuracy": 0.960},
                     {"condition": "format-enforcer", "accuracy": 0.945}])
check("the fingerprint is stable across prompts",
      rob["verdict"] == "fingerprint-stable", rob)
check("the worst condition is named", rob["worst"]["condition"] == "default")
check("a semantic baseline that collapses first is named",
      EF.robustness([{"condition": "persona", "accuracy": 0.70,
                      "semantic_baseline": 0.95}])["verdict"]
      == "baselines-collapse-first")
check("a fragile fingerprint is named",
      EF.robustness([{"condition": "x", "accuracy": 0.7}])["verdict"]
      == "fingerprint-fragile")

pr = EF.probes({"target_gap": 0.10, "exec_variance": 0.20, "token_distance": 0.30})
check("an optimized probe scores above its parts", pr["verdict"] == "probe-optimized", pr)
check("the surrogate score is reported", abs(pr["score"] - 0.35) < 1e-9)
check("a probe that does not separate the target is weak",
      EF.probes({"target_gap": 0.0, "token_distance": 0.3})["verdict"]
      == "probe-weak")
check("a probe blind to token boundaries is named",
      EF.probes({"target_gap": 0.2, "token_distance": 0.0})["verdict"]
      == "probe-not-token-aware")
check("an incomplete probe is refused",
      EF.probes({})["verdict"] == "probe-incomplete")

check("a met condition set passes", kinds(EF.audit(
    {"strict_parser": True, "errors_surfaced": True, "retries_allowed": True}))
    == ["fingerprint-conditions-met"])
check("a lenient parser is named",
      "no-rigid-interface" in kinds(EF.audit({"errors_surfaced": True,
                                              "retries_allowed": True})))
check("a killed session is named",
      "no-error-feedback" in kinds(EF.audit({"strict_parser": True,
                                             "retries_allowed": True})))
check("canonicalization is named",
      "canonicalization-suppresses" in kinds(EF.audit(
          {"strict_parser": True, "errors_surfaced": True,
           "retries_allowed": True, "canonicalizes_output": True})))
check("advise names every missing practice", len(EF.advise({})["findings"]) == 7)
check("a fully declared profile has no finding", EF.advise(
    {k: True for k in ("records_full_traces", "keeps_error_categories",
                       "scores_sequence_not_bag", "normalizes_by_length",
                       "uses_held_out_probes", "reports_a_budget_curve",
                       "tests_prompt_obfuscation")})["findings"] == [])

# ---- 3. model handoff (Do I Need the Cloud?) ----------------------------
check("an easy step runs locally",
      MH.gate({"q": 0.1, "risk": "R0"})["decision"] == "local")
check("an ambiguous step verifies locally",
      MH.gate({"q": 0.5, "risk": "R0"})["decision"] == "verify")
check("an uncertain step escalates",
      MH.gate({"q": 0.8, "risk": "R0"})["decision"] == "cloud")
check("a risky step lowers both thresholds",
      MH.gate({"q": 0.55, "risk": "R2"})["decision"] == "cloud")
check("an exhausted cloud budget cannot escalate",
      MH.gate({"q": 0.9, "risk": "R0", "cloud_left": 0})["decision"] == "verify")
check("an out-of-range probability is refused",
      MH.gate({"q": 1.5})["decision"] == "invalid-q")
check("the gate never grants authorization",
      "never grants authorization" in MH.gate({"q": 0.1})["note"])

check("a complete signal set passes", MH.signals(
    {k: 1 for k in ("token", "margin", "schema", "consistency", "state", "risk")})
    ["verdict"] == "signals-complete")
check("a missing signal is named",
      MH.signals({"token": 1, "schema": 1})["missing"] ==
      ["margin", "consistency", "state", "risk"])

cal = MH.calibration([{"p": 0.9, "y": 1}] * 10 + [{"p": 0.1, "y": 0}] * 10)
check("a separating calibrated gate is named",
      cal["verdict"] == "gate-calibrated", cal)
check("perfect separation gives AUROC 1", abs(cal["auroc"] - 1.0) < 1e-9)
check("the Brier score is measured", abs(cal["brier"] - 0.01) < 1e-9)
mis = MH.calibration([{"p": 0.55, "y": 1}] * 10 + [{"p": 0.45, "y": 0}] * 10)
check("a ranking but miscalibrated gate is named",
      mis["verdict"] == "gate-miscalibrated", mis)
check("its ranking is still good", abs(mis["auroc"] - 1.0) < 1e-9)
check("a gate that does not rank is named",
      MH.calibration([{"p": 0.5, "y": 1}] * 5 + [{"p": 0.5, "y": 0}] * 5)
      ["verdict"] == "gate-does-not-rank")

budget = MH.budget([
    {"method": "local-only", "success": 0.673, "cloud": 0.0},
    {"method": "strong-only", "success": 0.923, "cloud": 1.0},
    {"method": "step-level", "success": 0.827, "cloud": 0.308, "realized": 0.308}])
check("the headroom is measured", abs(budget["headroom"] - 0.25) < 1e-9)
check("the share of headroom closed is measured",
      abs(budget["headroom_closed"] - 0.616) < 1e-9, budget)
check("a budget-matched arm is reported", budget["budget_matched"] is True)
check("closing most of the headroom is named",
      budget["verdict"] == "closes-most-headroom")
check("two arms are not a comparison",
      MH.budget([{"method": "local-only", "success": 0.6, "cloud": 0.0}])
      ["verdict"] == "three-arms-required")

pf = MH.pareto([{"method": "local-only", "success": 0.673, "cloud": 0.0},
                {"method": "step-level", "success": 0.827, "cloud": 0.308},
                {"method": "self-consistency", "success": 0.827, "cloud": 0.385},
                {"method": "strong-only", "success": 0.923, "cloud": 1.0}])
check("the frontier keeps local, step and strong",
      pf["frontier"] == ["local-only", "step-level", "strong-only"], pf)
check("a dominated router is marked inefficient",
      [r for r in pf["rows"] if r["method"] == "self-consistency"][0]["efficient"]
      is False)

packet = {"subgoal": "move the meeting", "tools": ["calendar"],
          "state_summary": "room busy", "action": "reschedule",
          "uncertainty": 0.6, "observations": ["room 4 busy"]}
check("a minimal packet passes", kinds(MH.handoff(packet)) == ["handoff-minimized"])
check("a missing field is named",
      "packet-field-missing" in kinds(MH.handoff(dict(packet, tools=[]))))
check("a full history is over-disclosure",
      "context-over-disclosed" in kinds(MH.handoff(dict(packet, full_history=True))))
check("a sensitive literal is named",
      "sensitive-value-in-packet" in kinds(
          MH.handoff(dict(packet, sensitive_literals=True))))

rec = MH.recovery([{"failure": "value_error", "recovery": 0.9, "count": 5},
                   {"failure": "missing_field", "recovery": 0.2, "count": 8},
                   {"failure": "malformed", "recovery": 0.5, "count": 3}])
check("recovery varies by failure type", rec["verdict"] == "failure-type-matters", rec)
check("the spread is measured", abs(rec["spread"] - 0.7) < 1e-9)
check("the worst failure is named", rec["lowest"] == "missing_field")
check("uniform recovery is named",
      MH.recovery([{"failure": "a", "recovery": 0.5},
                   {"failure": "b", "recovery": 0.55}])["verdict"]
      == "recovery-uniform")

sat = MH.saturate([{"model": "1.5B", "local": 0.673, "routed": 0.827,
                    "strong": 0.923},
                   {"model": "3B", "local": 0.885, "routed": 0.904,
                    "strong": 0.923}])
check("routing saturates as the local model approaches the ceiling",
      sat["verdict"] == "routing-saturates" and sat["saturated"] == ["3B"], sat)
check("the share of headroom closed is reported",
      abs([r for r in sat["rows"] if r["model"] == "1.5B"][0]["share"] - 0.616)
      < 1e-9)
check("a wide margin is named",
      MH.saturate([{"model": "0.5B", "local": 0.558, "routed": 0.846,
                    "strong": 0.923}])["verdict"] == "routing-headroom")

check("a clean handoff record passes", kinds(MH.audit(
    {"step_level": True, "budget_matched": True, "labels_from_local": True,
     "risk_as_authorization": False, "reports_remote_tokens": True}))
    == ["handoff-read-correctly"])
check("a query-level baseline is named",
      "query-level-baseline" in kinds(MH.audit({"step_level": False})))
check("an unmatched budget is named",
      "unmatched-budget" in kinds(MH.audit({"step_level": True})))
check("a label leak is named",
      "label-leak" in kinds(MH.audit({"step_level": True, "budget_matched": True})))
check("risk as authorization is named",
      "risk-is-not-authorization" in kinds(MH.audit(
          {"step_level": True, "budget_matched": True, "labels_from_local": True,
           "risk_as_authorization": True})))
check("advise names every missing practice", len(MH.advise({})["findings"]) == 7)
check("a fully declared profile has no finding", MH.advise(
    {k: True for k in ("routes_per_step", "scores_structured_uncertainty",
                       "calibrates_the_gate", "matches_the_cloud_budget",
                       "minimizes_the_packet", "reports_recovery_by_type",
                       "tests_saturation")})["findings"] == [])

# ---- result --------------------------------------------------------------
ok = sum(1 for r in RESULTS if r)
print("\n%d/%d checks passed" % (ok, len(RESULTS)))
sys.exit(0 if ok == len(RESULTS) else 1)
