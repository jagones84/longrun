#!/usr/bin/env python3
"""v1221 — continuation audits, tool-space extension, fast decision path (round 152).

Sources:
  * arXiv:2611.24491 "Continuation Audits" — cut selection, paired realism,
    eval-awareness against the real baseline, the two-axis overeagerness score,
    the narrow judge's severity logic, mandate classification, coverage, and the
    policy ablation.
  * arXiv:2611.23810 "COTEX" — verified trajectories from native annotations,
    retention against the old tools, the new-tool gain, selection drift, the
    two-decision split, extension cost, and the admission gate.
  * arXiv:2611.23751 "AnyS1" — D/G/E nodes, the E share, threshold calibration,
    the confidence gate, the cost identity, label smoothing, the risk–coverage
    area, and the collapse an ungated fast path causes.

Deterministic: plain data in, dicts out; no model, no network, no server.

Run: python3 tests/acceptance/v1221_audit_toolspace_fastpath.py
"""
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="sf-v1221-")
for _key in ("CONFIG_DIR", "SESSIONS_DIR", "GRAPH_DIR", "EDITS_DIR",
             "RUNS_DIR", "DATA_DIR", "THREADS_DIR", "COSTS_DIR", "MEMORY_DIR"):
    os.environ["LONGRUN_" + _key] = os.path.join(TMP, _key)
    os.makedirs(os.environ["LONGRUN_" + _key], exist_ok=True)
os.environ["LONGRUN_DB"] = os.path.join(TMP, "events.db")
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.harness.checks import continuation_audit as CA  # noqa: E402
from longrun.harness.checks import tool_extension as TE  # noqa: E402
from longrun.harness.checks import fast_path as FP  # noqa: E402

RESULTS = []


def check(name, ok, detail=""):
    RESULTS.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name
          + ((" :: " + str(detail)) if detail else ""))


def close(a, b, tol=1e-9):
    return a is not None and abs(a - b) <= tol


def kinds(out):
    return [f["kind"] for f in (out.get("findings") or [])]


# ---- 1. continuation audits (arXiv:2611.24491) ------------------------
C = CA.cuts([{"id": "t1", "ends_turn": True, "prefix_turns": 3},
             {"id": "t2", "ends_turn": True, "prefix_turns": 0},
             {"id": "t3", "ends_turn": False, "prefix_turns": 5}])
check("a cut at a turn end is selected", C["selected"] == 1)
check("a cut without a prefix is rejected", "t2" in C["rejected"])
check("a mid-turn cut is rejected", "t3" in C["rejected"])
check("no cuts is its own verdict", CA.cuts([])["verdict"] == "no-cuts")
R = CA.realism([{"source": 0.43, "audit": 0.42}, {"source": 0.40, "audit": 0.41},
                {"source": 0.45, "audit": 0.44}])
check("the source win rate is reported", close(R["source"], 0.4266667, 1e-6))
check("the audit win rate is reported", close(R["audit"], 0.4233333, 1e-6))
check("the paired gap is small", abs(R["gap"]) < 0.01)
check("small paired gaps preserve realism", R["verdict"] == "realism-preserved")
check("a large gap degrades realism",
      CA.realism([{"source": 0.5, "audit": 0.1}])["verdict"] == "realism-degraded")
check("no pairs is its own verdict", CA.realism([])["verdict"] == "no-pairs")
AW = CA.awareness([{"arm": "audit", "flag": True}, {"arm": "audit", "flag": False},
                   {"arm": "audit", "flag": False}, {"arm": "real", "rate": 0.01}])
check("the awareness rate is a share", close(AW["rate"], 1 / 3))
check("a rate above the baseline is named", AW["verdict"] == "more-aware")
check("a rate at the baseline is not more aware",
      CA.awareness([{"arm": "audit", "flag": False},
                    {"arm": "real", "rate": 0.01}])["verdict"] == "not-more-aware")
check("a missing baseline is named",
      CA.awareness([{"arm": "audit", "flag": False}])["verdict"] == "baseline-missing")
S = CA.score({"deviation": 1, "consequence": 6})
check("consequence is one when deviation is one", S["consequence"] == 1)
check("the convention is reported", S["convention_applied"] is True)
check("a real gap keeps its impact", CA.score({"deviation": 8, "consequence": 5})
      ["consequence"] == 5)
check("an out-of-range score is refused",
      CA.score({"deviation": 0, "consequence": 5})["verdict"] == "out-of-range")
N = CA.narrow({"behavior_present": True, "flagrant": True})
check("presence and flagrancy make it severe", N["is_severe"] is True)
check("a present non-severe case is named",
      CA.narrow({"behavior_present": True})["verdict"] == "present")
ABSENT = CA.narrow({"behavior_present": False, "flagrant": True,
                    "consequential": True})
check("severity is false without presence", ABSENT["is_severe"] is False)
check("an absent case is named", ABSENT["verdict"] == "absent")
M = CA.mandate([{"kind": "request", "open": True}, {"kind": "question"}])
check("a request opens a live mandate", M["standing"] == "live")
check("questions are counted", M["questions"] == 1)
check("a closed request completes the mandate",
      CA.mandate([{"kind": "request", "open": False}])["standing"] == "completed")
check("questions alone leave no mandate",
      CA.mandate([{"kind": "question"}])["verdict"] == "no-mandate")
COV = CA.cover({"standing": "live", "acts": [
    {"authorized": True, "changes_state": True},
    {"changes_state": False},
    {"in_named_scope": True, "changes_state": True},
    {"in_named_scope": False, "changes_state": True},
]})
check("authorized and read-only acts are covered", COV["covered"] == [0, 1, 2])
check("an out-of-scope state change is unmandated", COV["unmandated"] == [3])
check("a question-only run has no unmandated act",
      CA.cover({"standing": "none", "acts": [{"changes_state": False}]})
      ["verdict"] == "covered")
POL = CA.policy([{"model": "terra", "before": 90, "after": 0},
                 {"model": "deepseek", "before": 90, "after": 0},
                 {"model": "kimi", "before": 90, "after": 13}])
check("the defiant model is named", POL["defiant"] == ["kimi"])
check("a defied policy is named", POL["verdict"] == "policy-defied")
check("a policy that holds is named",
      CA.policy([{"model": "a", "before": 5, "after": 0}])["verdict"]
      == "policy-holds")
check("the audit names seven misreadings",
      len(CA.audit({"judges_the_prefix": True, "synthetic_scenario_is_neutral": True,
                    "awareness_not_measured": True, "deviation_alone_is_impact": True,
                    "tough_calls_counted_as_clear": True,
                    "policy_removes_the_behaviour": True,
                    "severity_without_presence": True})["findings"]) == 7)
check("an empty record passes the audit audit",
      kinds(CA.audit({})) == ["audit-conditions-met"])
check("an empty harness profile misses all seven habits",
      len(CA.advise({})["findings"]) == 7)
check("a complete harness profile is clean",
      CA.advise({k: True for k in ("grounds_the_audit_in_a_real_prefix",
                                   "judges_only_the_continuation",
                                   "pairs_realism_against_the_source",
                                   "caps_awareness_by_the_real_baseline",
                                   "separates_deviation_from_consequence",
                                   "keeps_tough_calls_visible",
                                   "tests_a_policy_with_and_without")})["findings"] == [])

# ---- 2. tool-space extension (arXiv:2611.23810) -----------------------
V = TE.verified([{"tool": "ocr", "verified": True},
                 {"tool": "ocr", "verified": True},
                 {"tool": "ocr", "verified": False},
                 {"tool": "depth", "verified": True}])
check("verified trajectories are counted", V["kept"] == 3)
check("unverified attempts are dropped", V["dropped"] == 1)
check("counts are kept per tool", V["by_tool"] == {"ocr": 2, "depth": 1})
check("two tools are covered", V["tools"] == 2)
check("no verified attempt is its own verdict",
      TE.verified([])["verdict"] == "no-trajectories")
RET = TE.retention({"old_tools": [
    {"tool": "crop", "before": 81.7, "after": 81.5},
    {"tool": "code", "before": 70.0, "after": 69.7}]})
check("the worst drop is found", RET["worst"] == "code")
check("a small drop holds retention", RET["verdict"] == "retention-holds")
check("a large drop breaks retention",
      TE.retention({"old_tools": [{"tool": "crop", "before": 81.7,
                                   "after": 75.9}]})["verdict"] == "retention-broken")
check("no panel is its own verdict", TE.retention({})["verdict"] == "no-panel")
check("the new capability is measured against its baseline",
      close(TE.gain({"after": 82.5, "baseline": 80.4})["delta"], 2.1))
check("no gain is named",
      TE.gain({"after": 80.0, "baseline": 80.4})["verdict"] == "no-gain")
DR = TE.drift({"before": {"crop": 0.6, "code": 0.4},
               "after": {"crop": 0.55, "code": 0.35, "ocr": 0.10}})
check("drift is a total-variation distance", close(DR["tvd"], 0.10))
check("a small drift is stable", DR["verdict"] == "selection-stable")
check("a large drift is named",
      TE.drift({"before": {"crop": 0.9, "code": 0.1},
                "after": {"ocr": 0.9, "crop": 0.1}})["verdict"] == "selection-drifted")
check("the two decisions are named", TE.decisions()["verdict"] == "two-decisions")
COST = TE.cost({"tools": 3, "retrain_cost": 10, "adapter_cost": 1})
check("full retraining grows with tools", close(COST["full"], 30.0))
check("adapter extension grows with tools", close(COST["incremental"], 3.0))
check("the ratio favours the adapter", COST["verdict"] == "adapter-cheaper")
GOOD = {"trajectories": 1000, "retention_holds": True, "gain_positive": True,
        "selection_stable": True, "old_panel": True}
check("a complete extension is admitted", TE.admit(GOOD)["verdict"] == "admitted")
check("a teacher is refused", TE.admit(dict(GOOD, teacher_used=True))["reasons"]
      == ["teacher-not-allowed"])
check("too few trajectories are refused",
      TE.admit(dict(GOOD, trajectories=10))["reasons"]
      == ["too-few-verified-trajectories"])
check("a missing panel is refused",
      TE.admit(dict(GOOD, old_panel=False))["reasons"] == ["no-retention-panel"])
check("the audit names six misreadings",
      len(TE.audit({"one_decision": True, "keeps_no_old_panel": True,
                    "trains_without_verifier": True, "teacher_is_required": True,
                    "ignores_selection_drift": True,
                    "cost_is_per_tool": True})["findings"]) == 6)
check("an empty record passes the extension audit",
      kinds(TE.audit({})) == ["audit-conditions-met"])
check("an empty harness profile misses all six habits",
      len(TE.advise({})["findings"]) == 6)
check("a complete harness profile is clean",
      TE.advise({k: True for k in ("separates_initiation_from_selection",
                                   "verifies_trajectories_before_training",
                                   "keeps_a_retention_panel",
                                   "bounds_selection_drift",
                                   "uses_the_tools_own_annotations",
                                   "prices_extension_per_tool")})["findings"] == [])

# ---- 3. fast decision path (arXiv:2611.23751) -------------------------
check("a deterministic node runs as code",
      FP.classify({"deterministic": True})["node"] == "D")
check("an open-ended node stays with System-2",
      FP.classify({"open_ended": True})["node"] == "G")
check("an enumerable choice is an E node",
      FP.classify({"question": "which tool?", "options": ["a", "b"]})["node"] == "E")
check("one option is not a choice",
      FP.classify({"question": "q", "options": ["a"]})["verdict"] == "unclassified")
PROG = FP.program([{"deterministic": True}, {"open_ended": True},
                   {"question": "q", "options": ["a", "b"]},
                   {"question": "q2", "options": ["a", "b", "c"]}])
check("node types are counted", PROG["counts"] == {"D": 1, "G": 1, "E": 2})
check("the E share bounds the saving", close(PROG["e_share"], 0.5))
check("an empty program is its own verdict",
      FP.program([])["verdict"] == "empty-program")
CAL = FP.calibrate({"decisions": [
    {"confidence": 0.99, "agrees": True},
    {"confidence": 0.95, "agrees": True},
    {"confidence": 0.90, "agrees": False},
    {"confidence": 0.80, "agrees": True},
]})
check("the threshold is the last confident decision",
      close(CAL["threshold"], 0.95))
check("the threshold meets the target", CAL["agreement"] >= 0.95)
check("delegated decisions are counted", CAL["delegated"] == 2)
check("an unreachable target is named",
      FP.calibrate({"decisions": [{"confidence": 0.9, "agrees": False}]})
      ["verdict"] == "target-unreachable")
check("a confident decision is adopted",
      FP.gate({"confidence": 0.96, "threshold": 0.95})["decision"] == "system-1")
check("an uncertain decision defers",
      FP.gate({"confidence": 0.5, "threshold": 0.95})["decision"] == "system-2")
CO = FP.cost({"e_share": 0.2, "kappa": 0.1})
check("the cost ratio follows the identity", close(CO["ratio"], 0.82))
check("the saving is the complement", close(CO["saving"], 0.18))
check("the ceiling is the E share minus overhead", close(CO["ceiling"], 0.10))
check("an out-of-range share is refused",
      FP.cost({"e_share": 2, "kappa": 0.1})["verdict"] == "out-of-range")
SM = FP.smoothed([9, 1], 0.1)
check("label smoothing lowers the top mass", close(SM["probs"][0], 0.86))
check("label smoothing raises the floor", close(SM["probs"][1], 0.14))
check("the smoothed distribution sums to one", close(sum(SM["probs"]), 1.0))
check("an empty distribution is refused", FP.smoothed([])["verdict"]
      == "insufficient-input")
AURC = FP.aurc([{"confidence": 0.9, "correct": True},
                {"confidence": 0.8, "correct": True},
                {"confidence": 0.2, "correct": False}])
check("the area is reported", AURC["aurc"] > 0)
check("a ranking that concentrates errors is informative",
      AURC["verdict"] == "ranking-informative")
check("a flat risk curve has no signal",
      FP.aurc([{"confidence": 0.9, "correct": False},
               {"confidence": 0.5, "correct": False}])["verdict"] == "no-rank-signal")
COL = FP.collapsed({"gated": 96.3, "ungated": 40.3})
check("the collapse is the gap", close(COL["collapse"], 56.0))
check("an ungated long horizon needs the gate", COL["verdict"] == "gate-required")
check("the audit names six misreadings",
      len(FP.audit({"every_step_needs_system_2": True,
                    "delegates_without_a_gate": True,
                    "confidence_is_accuracy": True,
                    "saving_ignores_overhead": True,
                    "threshold_is_universal": True,
                    "synthetic_states_are_enough": True})["findings"]) == 6)
check("an empty record passes the fast-path audit",
      kinds(FP.audit({})) == ["audit-conditions-met"])
check("an empty harness profile misses all six habits",
      len(FP.advise({})["findings"]) == 6)
check("a complete harness profile is clean",
      FP.advise({k: True for k in ("splits_nodes_into_d_g_e",
                                   "gates_on_calibrated_confidence",
                                   "labels_the_distribution_smoothly",
                                   "reports_the_e_share",
                                   "calibrates_per_workflow",
                                   "uses_executed_states")})["findings"] == [])

# ---- summary ----------------------------------------------------------
passed = sum(1 for r in RESULTS if r)
print("\n%d/%d checks passed" % (passed, len(RESULTS)))
sys.exit(0 if passed == len(RESULTS) else 1)
