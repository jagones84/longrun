#!/usr/bin/env python3
"""Fast path — a bounded choice should not cost a full generation.

Source: arXiv:2611.23751, "Thinking Fast, Anywhere: One System-1 for the
Decision Points of Any Agent Workflow" (round 152). An agent that queries a
large model at every step pays for open generation even where the step merely
selects among a few known options (`fast_decision_policy_2611.23751.txt:13`,
`:26`).

  * **three node types**: D is deterministic and runs as code, G is open
    generation and stays with System-2, and E is an enumerable decision over a
    fixed option set (`:154`, `:157`).
  * **an E node is a template** `(q, O, d)` instantiated at a state `s` into
    `x = (s, q, O, d)` (`:164`).
  * **deferral is confidence-gated**: adopt the fast pick only when
    `max p(o|x) >= tau`, otherwise fall back (`:177`, `:295`).
  * **the cost identity**: `C/C_S2 ≈ (1 - sE) + sE * kappa`, so the E-node cost
    share bounds the saving (`:193`, `:203`).
  * **calibration is built in**: label smoothing with epsilon = 0.1 keeps
    out-of-domain confidence from saturating (ECE 0.094 against 0.146) (`:282`,
    `:429`).
  * **measured**: 75–91% episode cost and 63–92% model time saved at preserved
    success; the gate prevents a long-horizon collapse from 96.3 to 40.3 when
    every E decision is delegated (`:46`, `:458`).

  * `classify(record)` — D, G or E, with the reason.
  * `program(rows)` — node counts and the E share.
  * `calibrate(record)` — the smallest threshold that meets an agreement target.
  * `gate(record)` — adopt or defer one decision.
  * `cost(record)` — the ratio, the saving and the ceiling.
  * `smoothed(probs, epsilon)` — the label-smoothed distribution.
  * `aurc(rows)` — risk–coverage area for a confidence ranking.
  * `collapsed(record)` — what ungated delegation does on a long horizon.
  * `audit(record)` — the six misreadings the paper names.
  * `advise(profile)` — map a harness profile onto the paper's failure modes.

Pure: node descriptions, confidences and costs in; verdicts out.
"""
from __future__ import annotations

import math

FORMAT = "longrun-fast-path/1"

NODE_TYPES = ("D", "G", "E")
AGREEMENT_TARGET = 0.95
EPSILON = 0.1


def _num(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def classify(record):
    """A node is deterministic, generative, or an enumerable choice."""
    r = record or {}
    options = r.get("options") or []
    if r.get("deterministic") is True:
        return {"format": FORMAT, "node": "D",
                "verdict": "runs-as-code"}
    if r.get("open_ended") is True:
        return {"format": FORMAT, "node": "G",
                "verdict": "stays-with-system-2"}
    if len(options) >= 2 and r.get("question"):
        return {"format": FORMAT, "node": "E", "options": len(options),
                "verdict": "enumerable-choice"}
    return {"format": FORMAT, "node": None, "verdict": "unclassified"}


def program(rows):
    """Node counts and the E share that bounds the saving."""
    counts = {name: 0 for name in NODE_TYPES}
    for row in rows or []:
        result = classify(row)
        node = result.get("node")
        if node in counts:
            counts[node] += 1
    total = sum(counts.values())
    if not total:
        return {"format": FORMAT, "verdict": "empty-program"}
    return {"format": FORMAT, "counts": counts, "total": total,
            "e_share": counts["E"] / total,
            "verdict": "program-compiled"}


def calibrate(record):
    """Smallest confidence threshold whose delegated decisions reach a target."""
    r = record or {}
    rows = [row or {} for row in (r.get("decisions") or [])]
    target = _num(r.get("target")) or AGREEMENT_TARGET
    pairs = []
    for row in rows:
        confidence = _num(row.get("confidence"))
        if confidence is None:
            continue
        pairs.append((confidence, row.get("agrees") is True))
    if not pairs:
        return {"format": FORMAT, "verdict": "no-decisions"}
    pairs.sort(key=lambda kv: kv[0], reverse=True)
    best = None
    for k in range(1, len(pairs) + 1):
        agreed = sum(1 for _, ok in pairs[:k] if ok)
        rate = agreed / k
        if rate >= target:
            best = (pairs[k - 1][0], rate, k)
        else:
            break
    if best is None:
        return {"format": FORMAT, "verdict": "target-unreachable"}
    threshold, rate, delegated = best
    return {"format": FORMAT, "threshold": threshold, "agreement": rate,
            "delegated": delegated, "coverage": delegated / len(pairs),
            "verdict": "threshold-calibrated"}


def gate(record):
    """Adopt a confident fast pick; defer everything else."""
    r = record or {}
    confidence = _num(r.get("confidence"))
    threshold = _num(r.get("threshold"))
    if confidence is None or threshold is None:
        return {"format": FORMAT, "verdict": "insufficient-input"}
    adopts = confidence >= threshold
    return {"format": FORMAT, "confidence": confidence, "threshold": threshold,
            "decision": "system-1" if adopts else "system-2",
            "verdict": "adopted" if adopts else "deferred"}


def cost(record):
    """`(1 - sE) + sE * kappa`, the saving, and its ceiling."""
    r = record or {}
    share = _num(r.get("e_share"))
    kappa = _num(r.get("kappa"))
    if share is None or kappa is None:
        return {"format": FORMAT, "verdict": "insufficient-input"}
    if not 0 <= share <= 1 or kappa < 0:
        return {"format": FORMAT, "verdict": "out-of-range"}
    ratio = (1 - share) + share * kappa
    return {"format": FORMAT, "ratio": ratio, "saving": 1 - ratio,
            "ceiling": share - kappa if kappa <= share else 0.0,
            "verdict": "cheaper" if ratio < 1 else "no-saving"}


def smoothed(probs, epsilon=None):
    """The label-smoothed distribution `(1-e) p + e/n`."""
    values = [_num(p) for p in (probs or [])]
    values = [v for v in values if v is not None and v >= 0]
    eps = _num(epsilon)
    if eps is None:
        eps = EPSILON
    if not values or not 0 <= eps <= 1:
        return {"format": FORMAT, "verdict": "insufficient-input"}
    total = sum(values)
    if total <= 0:
        return {"format": FORMAT, "verdict": "zero-mass"}
    n = len(values)
    out = [(1 - eps) * (v / total) + eps / n for v in values]
    return {"format": FORMAT, "probs": out, "epsilon": eps,
            "verdict": "smoothed"}


def aurc(rows):
    """Risk–coverage area: how fast error falls as coverage drops."""
    pairs = []
    for row in rows or []:
        r = row or {}
        confidence = _num(r.get("confidence"))
        if confidence is None:
            continue
        pairs.append((confidence, r.get("correct") is True))
    if not pairs:
        return {"format": FORMAT, "verdict": "no-decisions"}
    pairs.sort(key=lambda kv: kv[0], reverse=True)
    errors = 0
    curve = []
    for k, (_, correct) in enumerate(pairs, start=1):
        if not correct:
            errors += 1
        curve.append(errors / k)
    area = sum(curve) / len(curve)
    return {"format": FORMAT, "decisions": len(pairs), "aurc": area,
            "final_risk": curve[-1],
            "verdict": "ranking-informative" if area < curve[-1]
            else "no-rank-signal"}


def collapsed(record):
    """What unconditional delegation does when a wrong branch compounds."""
    r = record or {}
    gated = _num(r.get("gated"))
    ungated = _num(r.get("ungated"))
    if gated is None or ungated is None:
        return {"format": FORMAT, "verdict": "insufficient-input"}
    return {"format": FORMAT, "gated": gated, "ungated": ungated,
            "collapse": gated - ungated,
            "verdict": "gate-required" if gated - ungated >= 5
            else "gate-neutral"}


def audit(record):
    """The six misreadings the paper names, each as a finding."""
    r = record or {}
    findings = []
    if r.get("every_step_needs_system_2") is True:
        findings.append({"kind": "every-step-needs-system-2",
                         "why": "bounded choices are a large share of steps"})
    if r.get("delegates_without_a_gate") is True:
        findings.append({"kind": "delegates-without-a-gate",
                         "why": "long-horizon exploration collapses without one"})
    if r.get("confidence_is_accuracy") is True:
        findings.append({"kind": "confidence-is-accuracy",
                         "why": "a gate needs calibration, not raw confidence"})
    if r.get("saving_ignores_overhead") is True:
        findings.append({"kind": "saving-ignores-overhead",
                         "why": "the E share bounds the saving, minus overhead"})
    if r.get("threshold_is_universal") is True:
        findings.append({"kind": "threshold-is-universal",
                         "why": "curves differ per workflow; a global tau over-delegates"})
    if r.get("synthetic_states_are_enough") is True:
        findings.append({"kind": "synthetic-states-are-enough",
                         "why": "executed container states beat fabricated summaries"})
    if not findings:
        findings.append({"kind": "audit-conditions-met"})
    return {"format": FORMAT, "findings": findings, "verdict": "audit-complete"}


def advise(profile):
    """Map a harness profile onto the paper's failure modes."""
    p = profile or {}
    have = {str(k) for k, v in p.items() if v}
    checks = (
        ("splits_nodes_into_d_g_e", "one_call_per_step",
         "deterministic and bounded steps do not need generation"),
        ("gates_on_calibrated_confidence", "adopts_every_fast_pick",
         "an ungated fast path compounds errors"),
        ("labels_the_distribution_smoothly", "hard_labels",
         "hard labels saturate confidence out of domain"),
        ("reports_the_e_share", "reports_only_a_total_saving",
         "the E share is the ceiling"),
        ("calibrates_per_workflow", "reuses_one_threshold_everywhere",
         "one tau over-delegates on some workflows"),
        ("uses_executed_states", "fabricates_states",
         "fabricated summaries do not match real tool output"),
    )
    findings = []
    for key, kind, why in checks:
        if key not in have:
            findings.append({"kind": kind, "why": why})
    return {"format": FORMAT, "findings": findings}
