#!/usr/bin/env python3
"""Agent diagnostics — findings, Signals, severity and remediation from traces.

Source: arXiv:2611.04507, "Signals: Continuous Diagnostics of AI Agents" (round
154). A trace records what happened; it does not say whether the agent did the
right thing. The method keeps three units apart — session, occurrence, Signal —
and separates the *nature* of a finding (realized defect, risk exposure,
inefficiency) from its *type* and from diagnostic confidence
(`agent_diagnostics_2611.04507.txt:100-130`).

  * **45 problem types in eight families**, each with its own evidence
    requirement (`:277-291`, appendix A).
  * **severity is arithmetic, not a judgement**: s_d = min(100, C + A),
    s_r = min(100, ⌈C_p·R⌉ + A), s_i = min(100, W + A), and a Signal takes the
    maximum over the natures it actually represents (`:154-190`).
  * **scope takes the higher band** of affected count and affected share, and the
    share band applies only when at least 20 sessions were analysed (`:218-226`).
  * **type is not root cause**: repeated occurrences group into one Signal only
    when one intervention would fix them; sharing a label is not enough (`:106`,
    `:112`).
  * **a fix is not established by one run**: it needs independent checks on the
    affected cases and on cases that previously succeeded (`:114-120`).

  * `taxonomy()` — the 45 types, their families and evidence requirements.
  * `finding(record)` — admissibility of one occurrence, with its nature.
  * `scope(affected, analyzed)` — the count/share band and its points.
  * `severity(record)` — s_d / s_r / s_i, the overall score and display level.
  * `group(findings)` — occurrences to Signals, refusing label-only merges.
  * `update(signal, run)` — new evidence, separate issue, or "not yet a fix".
  * `match(predicted, reference)` — deterministic one-to-one P/R/F1 and coverage.
  * `audit(record)` / `advise(profile)` — misreadings and harness mapping.

Pure: records and label sets in; admissibility, scores and verdicts out.
"""
from __future__ import annotations

import math

FORMAT = "longrun-diagnostics/1"

NATURES = ("defect", "risk", "inefficiency")
REACHABILITY = {"privileged": 0.4, "authentication": 0.6,
                "ordinary": 0.8, "public": 1.0}
EVIDENCE_KINDS = {"requirement", "behaviour"}

FAMILIES = (
    ("instruction", ("constraint_violation", "intent_misinterpreted",
                     "clarification_missing", "inappropriate_refusal",
                     "goal_drift"), ("instruction", "behaviour")),
    ("knowledge", ("required_evidence_missing", "noisy_retrieval",
                   "stale_context", "context_lost", "window_exceeded",
                   "citation_mismatch"), ("corpus", "retrieval")),
    ("reasoning", ("unsupported_claim", "factual_error",
                   "premature_termination", "verification_incorrect",
                   "schema_violation", "action_decision_mismatch",
                   "false_success", "success_check_subverted"),
     ("reference", "output")),
    ("tool", ("wrong_tool", "required_call_missing", "invalid_arguments",
              "interface_mismatch", "invalid_result", "result_misinterpreted",
              "error_unhandled", "unintended_side_effect"),
     ("contract", "invocation")),
    ("orchestration", ("invalid_route", "handoff_lost", "state_not_propagated",
                       "workflow_loop", "termination_missed"),
     ("expected_flow", "actual_flow")),
    ("runtime", ("provider_unavailable", "resource_exhaustion",
                 "auth_config_failure"), ("service_requirement", "runtime_record")),
    ("safety", ("untrusted_instruction", "sensitive_disclosure",
                "excessive_agency", "disallowed_content", "policy_bypass",
                "insecure_output_handling"), ("policy", "action")),
    ("efficiency", ("duplicate_action", "retry_thrash", "redundant_retrieval",
                    "context_bloat"), ("equivalent_evidence", "avoidable_work")),
)

TYPE_FAMILY = {}
TYPE_REQUIRES = {}
for _family, _types, _requires in FAMILIES:
    for _t in _types:
        TYPE_FAMILY[_t] = _family
        TYPE_REQUIRES[_t] = _requires

COUNT_BANDS = ((1, 1, 0, "isolated"), (2, 3, 3, "limited"),
               (4, 10, 7, "repeated"), (11, 100, 12, "broad"),
               (101, 10 ** 9, 15, "widespread"))
SHARE_BANDS = ((0.01, 0, "isolated"), (0.10, 3, "limited"),
               (0.30, 7, "repeated"), (0.60, 12, "broad"),
               (1.01, 15, "widespread"))
POINTS_BAND = {0: "isolated", 3: "limited", 7: "repeated", 12: "broad",
               15: "widespread"}


def _num(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _level(score):
    if score >= 80:
        return "critical"
    if score >= 40:
        return "high"
    if score >= 1:
        return "low"
    return "none"


def taxonomy():
    """The catalogue: eight families, 45 types, each with required evidence."""
    out = []
    total = 0
    for family, types, requires in FAMILIES:
        out.append({"family": family, "count": len(types),
                    "types": list(types), "requires": list(requires)})
        total += len(types)
    return {"format": FORMAT, "families": out, "total": total,
            "verdict": "taxonomy"}


def finding(record):
    """One occurrence: admissible only with a requirement and its violation."""
    r = record or {}
    ptype = str(r.get("type") or "")
    if ptype not in TYPE_FAMILY:
        return {"format": FORMAT, "verdict": "unknown-type"}
    nature = str(r.get("nature") or "")
    if nature not in NATURES:
        return {"format": FORMAT, "verdict": "unknown-nature"}
    evidence = r.get("evidence") or {}
    if not isinstance(evidence, dict):
        return {"format": FORMAT, "verdict": "evidence-not-a-map"}
    kinds = {k for k, v in evidence.items() if v}
    if kinds and kinds <= {"missing-telemetry", "attack-like"}:
        return {"format": FORMAT, "verdict": "insufficient-evidence",
                "why": "missing telemetry and attack-like text prove nothing"}
    missing = [k for k in TYPE_REQUIRES[ptype] if not evidence.get(k)]
    if missing:
        return {"format": FORMAT, "verdict": "insufficient-evidence",
                "missing": missing}
    if nature == "risk":
        reach = str(r.get("reachability") or "")
        if reach not in REACHABILITY and _num(r.get("reachability")) is None:
            return {"format": FORMAT, "verdict": "unreachable-path"}
        if _num(r.get("potential")) is None:
            return {"format": FORMAT, "verdict": "insufficient-input"}
    if nature == "inefficiency" and _num(r.get("waste")) is None:
        return {"format": FORMAT, "verdict": "insufficient-input"}
    if nature == "defect" and _num(r.get("consequence")) is None:
        return {"format": FORMAT, "verdict": "insufficient-input"}
    return {"format": FORMAT, "type": ptype, "family": TYPE_FAMILY[ptype],
            "nature": nature, "component": r.get("component"),
            "admissible": True, "verdict": "finding-admissible"}


def scope(affected, analyzed=None):
    """Affected scope: the higher of the count band and the share band."""
    count = int(_num(affected) or 0)
    if count < 1:
        return {"format": FORMAT, "verdict": "insufficient-input"}
    count_points = 0
    count_band = "isolated"
    for lo, hi, points, band in COUNT_BANDS:
        if lo <= count <= hi:
            count_points, count_band = points, band
            break
    share_points = None
    share_band = None
    share = None
    n = _num(analyzed)
    if n is not None and n >= 20:
        share = count / n
        for edge, points, band in SHARE_BANDS:
            if share < edge:
                share_points, share_band = points, band
                break
    points = max(count_points, share_points if share_points is not None else 0)
    return {"format": FORMAT, "affected": count, "analyzed": analyzed,
            "count_points": count_points, "count_band": count_band,
            "share": share, "share_points": share_points,
            "share_band": share_band, "points": points,
            "band": POINTS_BAND[points], "verdict": "scoped"}


def severity(record):
    """Arithmetic severity per represented nature; the Signal takes the max."""
    r = record or {}
    affected = r.get("affected")
    sc = scope(affected, r.get("analyzed"))
    if sc.get("points") is None:
        return {"format": FORMAT, "verdict": "insufficient-input"}
    add = sc["points"]
    scores = {}
    consequence = _num(r.get("consequence"))
    if consequence is not None:
        scores["defect"] = min(100.0, consequence + add)
    potential = _num(r.get("potential"))
    reach = r.get("reachability")
    multiplier = REACHABILITY.get(str(reach), _num(reach))
    if potential is not None and multiplier is not None:
        scores["risk"] = min(100.0, math.ceil(potential * multiplier) + add)
    waste = _num(r.get("waste"))
    if waste is not None:
        scores["inefficiency"] = min(100.0, waste + add)
    if not scores:
        return {"format": FORMAT, "verdict": "no-nature"}
    overall = max(scores.values())
    return {"format": FORMAT, "scores": scores, "scope": sc, "severity": overall,
            "level": _level(overall), "verdict": "scored"}


def group(findings):
    """Occurrences to Signals: a shared label alone never merges them."""
    signals = {}
    order = []
    refused = 0
    for item in findings or []:
        f = item or {}
        if f.get("admissible") is not True:
            continue
        root = f.get("root")
        if root is None:
            refused += 1
            key = ("__alone__", len(order))
        else:
            key = (str(f.get("component")), str(f.get("type")), str(root))
        if key not in signals:
            signals[key] = {"component": f.get("component"), "type": f.get("type"),
                            "root": root, "occurrences": [], "sessions": set(),
                            "natures": set(), "actions": [], "checks": []}
            order.append(key)
        s = signals[key]
        s["occurrences"].append({"session": f.get("session"),
                                 "nature": f.get("nature")})
        if f.get("session") is not None:
            s["sessions"].add(f.get("session"))
        if f.get("nature"):
            s["natures"].add(f.get("nature"))
        if f.get("action") and f["action"] not in s["actions"]:
            s["actions"].append(f["action"])
        if f.get("check") and f["check"] not in s["checks"]:
            s["checks"].append(f["check"])
    out = []
    for key in order:
        s = signals[key]
        out.append({"component": s["component"], "type": s["type"],
                    "root": s["root"], "occurrences": len(s["occurrences"]),
                    "sessions": len(s["sessions"]),
                    "natures": sorted(s["natures"]),
                    "actions": s["actions"], "checks": s["checks"]})
    return {"format": FORMAT, "signals": out, "label_only_merges_refused": refused,
            "verdict": "grouped"}


def update(signal, run):
    """A new execution adds evidence, opens a separate issue, or proves nothing."""
    s = signal or {}
    r = run or {}
    occurrences = int(s.get("occurrences") or 0) + int(r.get("new_occurrences") or 0)
    if r.get("root") is not None and s.get("root") is not None and \
            str(r.get("root")) != str(s.get("root")):
        return {"format": FORMAT, "verdict": "separate-issue",
                "why": "a different root needs a different intervention"}
    if r.get("resolved") is True:
        covered = set(r.get("checked") or [])
        needed = {"affected", "previously_succeeding"}
        if not needed <= covered:
            return {"format": FORMAT, "occurrences": occurrences,
                    "fix_established": False,
                    "verdict": "single-run-cannot-establish-fix"}
        return {"format": FORMAT, "occurrences": occurrences,
                "fix_established": True, "verdict": "fix-checked"}
    return {"format": FORMAT, "occurrences": occurrences,
            "fix_established": False, "verdict": "evidence-added"}


def _norm(name):
    return "".join(ch for ch in str(name or "").lower() if ch.isalnum())


def _occurrence_pairs(predicted, reference):
    pairs = []
    for pi, p in enumerate(predicted or []):
        for ri, r in enumerate(reference or []):
            if p.get("session") != r.get("session"):
                continue
            if _norm(p.get("component_type")) != _norm(r.get("component_type")):
                continue
            if _norm(p.get("component")) != _norm(r.get("component")):
                continue
            if not (set(p.get("types") or []) & set(r.get("types") or [])):
                continue
            pairs.append((pi, ri))
    return pairs


def _one_to_one(pairs):
    used_p = set()
    used_r = set()
    matched = []
    for pi, ri in pairs:
        if pi in used_p or ri in used_r:
            continue
        used_p.add(pi)
        used_r.add(ri)
        matched.append((pi, ri))
    return matched


def match(predicted, reference):
    """Occurrence matching, then the Signal-level P/R/F1 and coverage."""
    pred = list(predicted or [])
    ref = list(reference or [])
    matched = _one_to_one(_occurrence_pairs(pred, ref))
    precision = len(matched) / len(pred) if pred else 0.0
    recall = len(matched) / len(ref) if ref else 0.0
    f1 = (2 * precision * recall / (precision + recall)) if precision + recall else 0.0
    return {"format": FORMAT, "matched": len(matched), "predicted": len(pred),
            "reference": len(ref), "precision": precision, "recall": recall,
            "f1": f1, "verdict": "matched"}


def coverage(predicted_signals, reference_signals):
    """Fraction of reference Signals with one match, and with half their occurrences."""
    matched = _one_to_one(_occurrence_pairs(predicted_signals, reference_signals))
    by_ref = {}
    for _, ri in matched:
        by_ref[ri] = by_ref.get(ri, 0) + 1
    ref = list(reference_signals or [])
    if not ref:
        return {"format": FORMAT, "verdict": "no-reference"}
    any_hit = sum(1 for i, r in enumerate(ref)
                  if by_ref.get(i, 0) >= 1)
    half_hit = sum(1 for i, r in enumerate(ref)
                   if by_ref.get(i, 0) * 2 >= max(1, int(r.get("occurrences") or 1)))
    return {"format": FORMAT, "reference": len(ref),
            "covered_any": any_hit / len(ref),
            "covered_half": half_hit / len(ref), "verdict": "covered"}


def audit(record):
    """The misreadings the paper's evidence rules exclude."""
    r = record or {}
    findings = []
    if r.get("task_failure_is_finding") is True:
        findings.append({"kind": "task-failure-is-finding",
                         "why": "a failed task does not prove which requirement broke"})
    if r.get("missing_telemetry_is_proof") is True:
        findings.append({"kind": "missing-telemetry-is-proof",
                         "why": "absent records do not prove an action did not happen"})
    if r.get("attack_text_is_failure") is True:
        findings.append({"kind": "attack-text-is-failure",
                         "why": "attack-like input is not a realised boundary failure"})
    if r.get("type_is_root_cause") is True:
        findings.append({"kind": "type-is-root-cause",
                         "why": "one label can hide two different interventions"})
    if r.get("repeat_is_severity") is True:
        findings.append({"kind": "repeat-is-severity",
                         "why": "spans in one session do not widen affected scope"})
    if r.get("one_run_proves_fix") is True:
        findings.append({"kind": "one-run-proves-fix",
                         "why": "a fix needs affected and previously-succeeding checks"})
    if r.get("severity_is_confidence") is True:
        findings.append({"kind": "severity-is-confidence",
                         "why": "severity states consequence, not diagnostic certainty"})
    if not findings:
        findings.append({"kind": "audit-conditions-met"})
    return {"format": FORMAT, "findings": findings, "verdict": "audit-complete"}


def advise(profile):
    """Map a harness profile onto the diagnostic gaps the paper names."""
    p = profile or {}
    have = {str(k) for k, v in p.items() if v}
    checks = (
        ("keeps_sessions_occurrences_and_signals_apart", "reports_one_flat_list",
         "a finding an operator can fix is a Signal, not an occurrence"),
        ("requires_requirement_and_violation", "labels_outcomes_only",
         "an outcome label cannot establish which requirement broke"),
        ("separates_defect_risk_and_waste", "adds_every_nature",
         "summing natures mixes meanings and rewards extra labels"),
        ("counts_distinct_sessions", "counts_repeated_spans",
         "repeats inside one session do not widen the blast radius"),
        ("checks_affected_and_working_cases", "trusts_one_green_run",
         "one corrected execution does not establish a fix"),
        ("states_evidence_for_severity", "scores_from_a_vibe",
         "severity must follow from the evidence it cites"),
    )
    findings = []
    for key, kind, why in checks:
        if key not in have:
            findings.append({"kind": kind, "why": why})
    return {"format": FORMAT, "findings": findings}
