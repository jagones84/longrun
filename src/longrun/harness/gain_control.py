#!/usr/bin/env python3
"""Gain control — when to stop an attempt that cannot improve the best result.

Source: arXiv:2611.20736, "GainCtrl: Predicting Remaining Gains for Efficient
LLM Agent Execution" (round 129). An agent that retries a task pays for every
attempt even when the next one will not beat what it already holds. The paper
makes the stopping decision an explicit, calibrated quantity:

  * the EXPECTED POSITIVE REMAINING GAIN at a checkpoint is E[max(Y - r, 0)]
    over the score Y of the complete continuation, where r is a REFERENCE
    SCORE: only outcomes above the reference contribute (§3.2);
  * one predictor emits the gain at ten fixed references r_k in {0, 0.1, ...,
    0.9} and any other reference is read by linear interpolation, with zero gain
    at r = 1 (§3.2, Algorithm 1);
  * GainCtrl-T takes r = the current attempt's retained score c; GainCtrl-P
    takes r = max(c, b) with b the best score retained by PREVIOUS attempts, so
    an improvement that would not beat the portfolio is worth nothing (§3.4);
  * the attempt stops when the predicted gain does not exceed a threshold tau,
    and tau is chosen on VALIDATION tasks under a quality-loss allowance delta:
    every attempt limit must stay within delta, and among the surviving
    thresholds the one with the lowest average relative token cost wins; if
    none survives, the controller falls back to full execution (§3.5);
  * with binary rewards and success ending the task, T and P are provably the
    same decision (Proposition 1, Appendix H);
  * the measured saving is actor-token cost only: the environment execution and
    reset cost across attempts is NOT counted (Limitations).

This module implements the accounting, not the regressor: the predictor is a
black box that hands over a gain vector, and everything else here — the
reference choice, the interpolation, the stopping rule, the calibration under an
allowance, the tri-state verdicts — is deterministic arithmetic a harness can
check.

Pure: score vectors and recorded replays in, decisions and verdicts out.
"""
from __future__ import annotations

import math

FORMAT = "longrun-gain-control/1"

# The predictor's ten fixed reference scores (§3.2).
REFERENCES = tuple(round(0.1 * i, 1) for i in range(10))

# The two reference-score configurations (§3.4).
MODES = ("trajectory", "portfolio")


def _num(value, default=None):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def gain_vector(score, references=REFERENCES):
    """The target vector [max(Y - r_k, 0)] for one continuation score."""
    y = _num(score)
    if y is None:
        return {"format": FORMAT, "gains": None, "references": list(references),
                "why": "no continuation score to build a gain vector from"}
    gains = [round(max(y - float(r), 0.0), 6) for r in references]
    return {"format": FORMAT, "gains": gains, "references": [float(r) for r in references],
            "score": y,
            "why": "only outcomes above the reference score contribute to the "
                   "expected positive remaining gain"}


def interpolate(gains, reference, references=None):
    """Read the predicted gain at an arbitrary reference score.

    Linear interpolation between the adjacent fixed references, with zero gain
    at r = 1 and the edge value outside the grid (§3.2). The gain vector and
    its reference grid must have the same length; the default grid is the
    predictor's ten fixed references.
    """
    if not gains:
        return {"format": FORMAT, "gain": None,
                "why": "no predicted gain vector to interpolate"}
    if references is None:
        if len(gains) != len(REFERENCES):
            return {"format": FORMAT, "gain": None,
                    "why": "the gain vector and its reference grid must have "
                           "the same length"}
        references = REFERENCES
    if len(gains) != len(references):
        return {"format": FORMAT, "gain": None,
                "why": "the gain vector and its reference grid must have the "
                       "same length"}
    r = _num(reference)
    if r is None:
        return {"format": FORMAT, "gain": None,
                "why": "no reference score to read the gain at"}
    if r >= 1.0:
        return {"format": FORMAT, "gain": 0.0, "method": "ceiling",
                "why": "a reference of 1 admits no positive gain"}
    if r <= float(references[0]):
        return {"format": FORMAT, "gain": round(float(gains[0]), 6),
                "method": "edge", "why": "the reference is at or below the grid"}
    upper = None
    for i, ref in enumerate(references):
        if float(ref) >= r:
            upper = i
            break
    if upper is None:
        return {"format": FORMAT, "gain": round(float(gains[-1]), 6),
                "method": "edge", "why": "the reference is above the grid"}
    lower = upper - 1
    lo_ref, hi_ref = float(references[lower]), float(references[upper])
    alpha = 0.0 if hi_ref == lo_ref else (r - lo_ref) / (hi_ref - lo_ref)
    value = (1 - alpha) * float(gains[lower]) + alpha * float(gains[upper])
    return {"format": FORMAT, "gain": round(value, 6), "method": "interpolated",
            "bracket": [lo_ref, hi_ref], "alpha": round(alpha, 6),
            "why": "one predictor serves every reference through interpolation"}


def reference(mode, current, best_previous):
    """The reference score r for the stopping rule (§3.4).

    `current` — the score this attempt would retain if it stopped now (c).
    `best_previous` — the best score retained by earlier attempts (b).
    """
    c = _num(current, 0.0) or 0.0
    b = _num(best_previous, 0.0) or 0.0
    key = str(mode or "trajectory").lower()
    if key not in MODES:
        key = "trajectory"
    if key == "portfolio":
        r = max(c, b)
        why = "an improvement that would not beat the retained portfolio is worth nothing"
    else:
        r = c
        why = "the reference is what this attempt itself retains"
    return {"format": FORMAT, "mode": key, "reference": round(r, 6),
            "current": round(c, 6), "best_previous": round(b, 6),
            "same_as_other": r == (max(c, b) if key == "trajectory" else c),
            "why": why}


def decide(gains, mode, current, best_previous, threshold, references=None):
    """Continue while the predicted gain exceeds tau; otherwise stop (§3.5)."""
    ref = reference(mode, current, best_previous)
    tau = _num(threshold)
    if tau is None:
        return {"format": FORMAT, "decision": "continue", "gain": None,
                "reference": ref["reference"], "threshold": None,
                "why": "no calibrated threshold; the attempt continues"}
    read = interpolate(gains, ref["reference"], references)
    gain = read["gain"]
    if gain is None:
        return {"format": FORMAT, "decision": "continue", "gain": None,
                "reference": ref["reference"], "threshold": tau,
                "why": "no predicted gain; the attempt continues"}
    if gain > tau:
        decision = "continue"
        why = "the predicted gain above the reference exceeds the threshold"
    else:
        decision = "stop"
        why = "the predicted gain does not exceed the threshold; the attempt " \
              "consumes a slot and a fresh one may start"
    return {"format": FORMAT, "decision": decision, "gain": gain,
            "reference": ref["reference"], "mode": ref["mode"], "threshold": tau,
            "findings": [], "why": why}


def binary_equivalent(scores):
    """Proposition 1: with binary rewards, T and P decide identically.

    True only when every observed score is 0/1 and no attempt has succeeded:
    while nobody has succeeded, c = b = 0, so both references coincide and the
    decisions coincide (Appendix H).
    """
    values = [_num(s) for s in (scores or [])]
    values = [v for v in values if v is not None]
    binary = all(v in (0.0, 1.0) for v in values)
    succeeded = any(v >= 1.0 for v in values)
    return {"format": FORMAT, "equivalent": bool(binary and not succeeded),
            "binary": binary, "succeeded": succeeded,
            "why": "with binary rewards and no success yet, c = b = 0 and the "
                   "two configurations are the same decision"}


def _relative_cost(rows, full_rows, field):
    values = []
    for n, value in sorted(rows.items()):
        base = full_rows.get(n)
        if base in (None, 0):
            continue
        try:
            values.append((float(value) - float(base)) / float(base))
        except (TypeError, ValueError):
            continue
    if not values:
        return None
    return sum(values) / len(values)


def calibrate(candidates, full, allowance):
    """Choose tau on validation tasks under a quality-loss allowance (§3.5).

    `candidates` — [{"threshold": tau, "quality": {N: q}, "tokens": {N: c}}]
    `full`       — {"quality": {N: q}, "tokens": {N: c}} for full execution
    `allowance`  — delta, the relative quality loss that may not be exceeded at
    ANY attempt limit.
    """
    delta = _num(allowance)
    if delta is None:
        return {"format": FORMAT, "threshold": None, "fallback": "full-execution",
                "findings": [{"kind": "no-allowance",
                              "why": "without a quality-loss allowance no "
                                     "threshold can be selected"}],
                "why": "the constraint is the policy; without it there is no choice"}
    full_q = (full or {}).get("quality") or {}
    full_c = (full or {}).get("tokens") or {}
    findings = []
    evaluated = []
    for cand in candidates or []:
        if not isinstance(cand, dict):
            continue
        tau = _num(cand.get("threshold"))
        if tau is None:
            continue
        q = cand.get("quality") or {}
        c = cand.get("tokens") or {}
        losses = []
        for n, qv in sorted(q.items()):
            base = full_q.get(n)
            if base in (None, 0):
                continue
            try:
                losses.append((float(base) - float(qv)) / float(base))
            except (TypeError, ValueError):
                continue
        max_loss = max(losses) if losses else None
        cost = _relative_cost(c, full_c, "tokens")
        evaluated.append({"threshold": tau, "max_quality_loss": round(max_loss, 6)
                          if max_loss is not None else None,
                          "mean_relative_token_cost": round(cost, 6)
                          if cost is not None else None})
    if not evaluated:
        return {"format": FORMAT, "threshold": None, "fallback": "full-execution",
                "evaluated": [], "findings": findings,
                "why": "no candidate threshold to evaluate"}
    surviving = [e for e in evaluated
                 if e["max_quality_loss"] is not None
                 and e["max_quality_loss"] <= delta
                 and e["mean_relative_token_cost"] is not None]
    for entry in evaluated:
        if entry["max_quality_loss"] is not None \
                and entry["max_quality_loss"] > delta:
            findings.append({"kind": "allowance-exceeded", "threshold": entry["threshold"],
                             "max_quality_loss": entry["max_quality_loss"],
                             "why": "the threshold loses more than the allowance "
                                    "at some attempt limit"})
    if not surviving:
        findings.append({"kind": "fallback-to-full-execution",
                         "why": "no threshold satisfies the quality constraint; "
                                "full execution is the fallback"})
        return {"format": FORMAT, "threshold": None, "fallback": "full-execution",
                "evaluated": evaluated, "findings": findings,
                "why": "the constraint binds harder than any candidate"}
    best = min(surviving, key=lambda e: (e["mean_relative_token_cost"],
                                          e["threshold"]))
    return {"format": FORMAT, "threshold": best["threshold"],
            "fallback": None, "allowance": delta, "evaluated": evaluated,
            "findings": findings,
            "why": "among the thresholds inside the allowance, the cheapest "
                   "average relative token cost wins"}


def frontier(points):
    """The quality-cost Pareto frontier over measured points.

    `points` — [{"quality": q, "tokens": c}] — dominated points are removed.
    """
    rows = []
    for point in points or []:
        if not isinstance(point, dict):
            continue
        q = _num(point.get("quality"))
        c = _num(point.get("tokens"))
        if q is None or c is None:
            continue
        rows.append({"quality": q, "tokens": c})
    keep = []
    for row in rows:
        dominated = any(other["quality"] >= row["quality"]
                        and other["tokens"] <= row["tokens"]
                        and (other["quality"] > row["quality"]
                             or other["tokens"] < row["tokens"])
                        for other in rows)
        if not dominated:
            keep.append(row)
    keep.sort(key=lambda r: r["tokens"])
    return {"format": FORMAT, "frontier": keep, "n": len(rows),
            "why": "a point is dominated when another is at least as good in "
                   "quality and no more expensive"}


def matched_quality(points, target):
    """Read a frontier at a matched quality target (§4.3, Appendix B).

    Interpolation happens in quality-log(token) coordinates, as the paper does.
    """
    q_star = _num(target)
    fr = frontier(points)["frontier"]
    if q_star is None or not fr:
        return {"format": FORMAT, "cost": None,
                "why": "no frontier to read the target on"}
    # The frontier is ordered by cost; the pair straddling the target is the
    # first point at or above the target and its predecessor on the curve.
    hi = None
    for point in fr:
        if point["quality"] >= q_star:
            hi = point
            break
    if hi is None:
        return {"format": FORMAT, "cost": None,
                "why": "the target quality is above the frontier's maximum"}
    index = fr.index(hi)
    if index == 0:
        return {"format": FORMAT, "cost": hi["tokens"], "quality": hi["quality"],
                "method": "observed", "surplus": round(hi["quality"] - q_star, 6),
                "why": "the cheapest observed point already meets the target"}
    below = [p for p in fr[:index] if p["quality"] < q_star]
    if not below:
        return {"format": FORMAT, "cost": hi["tokens"], "quality": hi["quality"],
                "method": "observed", "surplus": round(hi["quality"] - q_star, 6),
                "why": "no observed point sits below the target; the first "
                       "point at or above it is used"}
    lower = max(below, key=lambda p: p["quality"])
    q0, q1 = lower["quality"], hi["quality"]
    c0, c1 = lower["tokens"], hi["tokens"]
    if q1 == q0:
        return {"format": FORMAT, "cost": hi["tokens"], "quality": hi["quality"],
                "method": "observed", "surplus": round(hi["quality"] - q_star, 6),
                "why": "an exact quality plateau uses the cheapest matching point"}
    if c0 <= 0 or c1 <= 0:
        return {"format": FORMAT, "cost": hi["tokens"], "quality": hi["quality"],
                "method": "observed", "surplus": round(hi["quality"] - q_star, 6),
                "why": "the bracket is degenerate; the observed point is used"}
    lq0, lq1 = math.log(q0), math.log(q1)
    lc0, lc1 = math.log(c0), math.log(c1)
    alpha = 0.0 if lq1 == lq0 else (math.log(q_star) - lq0) / (lq1 - lq0)
    cost = math.exp(lc0 + alpha * (lc1 - lc0))
    return {"format": FORMAT, "cost": round(cost, 4), "quality": q_star,
            "method": "interpolated", "bracket": [[c0, q0], [c1, q1]],
            "alpha": round(alpha, 6),
            "why": "the cost at a matched quality is read in quality-log(token) "
                   "coordinates"}


def verdict(estimate, bounds, level=0.975):
    """A tri-state reading of an interval: resolved, ruled out, or unresolved.

    "Unresolved" is a verdict, not evidence of absence: a bound is never rounded
    up to the threshold it failed to clear (§4.4 of the paper's convention).
    """
    est = _num(estimate)
    lo = _num((bounds or [None, None])[0])
    hi = _num((bounds or [None, None])[1])
    if est is None or lo is None or hi is None:
        return {"format": FORMAT, "verdict": "unresolved", "level": level,
                "why": "no interval to read"}
    if lo > 0:
        return {"format": FORMAT, "verdict": "resolved-away-from-zero",
                "direction": "positive", "level": level,
                "estimate": est, "bounds": [lo, hi],
                "why": "the interval excludes zero in the positive direction"}
    if hi < 0:
        return {"format": FORMAT, "verdict": "resolved-away-from-zero",
                "direction": "negative", "level": level,
                "estimate": est, "bounds": [lo, hi],
                "why": "the interval excludes zero in the negative direction"}
    return {"format": FORMAT, "verdict": "unresolved", "level": level,
            "estimate": est, "bounds": [lo, hi],
            "why": "the interval includes zero; unresolved is a verdict and is "
                   "not evidence of absence"}


def advise(profile):
    """What a harness may claim about a gain-based stopping rule."""
    prof = profile if isinstance(profile, dict) else {}
    findings = []
    if not prof.get("validation_tasks"):
        findings.append({"kind": "no-validation-tasks",
                         "why": "the threshold is calibrated on validation tasks; "
                                "without them the rule is uncalibrated"})
    if not prof.get("recorded_trajectories"):
        findings.append({"kind": "no-recorded-trajectories",
                         "why": "the gain predictor is trained on complete "
                                "recorded trajectories"})
    if not prof.get("intermediate_feedback"):
        findings.append({"kind": "environment-features-unavailable",
                         "why": "environment-specific progress features may need "
                                "adaptation when reliable intermediate feedback "
                                "is missing"})
    findings.append({"kind": "environment-cost-excluded",
                     "why": "the measured saving counts actor tokens only; "
                            "environment execution and reset cost across "
                            "attempts is not counted"})
    if prof.get("binary_rewards"):
        findings.append({"kind": "binary-rewards-collapse-configurations",
                         "why": "with binary rewards the trajectory and "
                                "portfolio configurations are the same decision"})
    mode = "portfolio" if prof.get("best_previous") else "trajectory"
    return {"format": FORMAT, "mode": mode,
            "threshold": prof.get("threshold"),
            "checkpoints": prof.get("checkpoints") or [],
            "findings": findings,
            "why": "stopping is a calibrated quantity: the reference, the "
                   "threshold and the allowance must all be stated"}
