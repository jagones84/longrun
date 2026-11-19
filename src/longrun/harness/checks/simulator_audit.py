#!/usr/bin/env python3
"""User-simulator audit — perturb the replay, then see what the metric notices.

Source: arXiv:2611.24892, "On Evaluating User Simulators for Interactive
Agents" (round 149). A simulator's benchmark score is itself the object under
test: paired control and perturbed replays ask whether a metric *penalizes* a
known failure and whether it *filters* the failing replays out
(`user_simulator_evaluation_2611.24892.txt:68`, `:71`).

  * **sensitivity is paired**: `d_i = s(control_i) - s(perturbed_i)`, and a
    perturbation counts as detected only when the 95% interval of the mean lies
    entirely above zero (`:374`, `:390`).
  * **populations need a percentile, not a mean**: detection requires the 2.5th
    percentile of the paired population decreases to be above zero (`:405`).
  * **the suite level is "any metric"**: a suite detects a perturbation if any
    constituent metric meets the criterion; counts were 10/10 for the proposed
    suite and 6/5/6 for SimulatorArena, VISTA and SWE-Together (`:86`, `:679`).
  * **a high score can select the broken replay**: the composite scores of the
    existing suites favour replays instructed to accept broken work (`:89`).
  * **filtering is a separate question**: AUROC and control retention at 5%
    perturbed survival, e.g. 0.98 retention against 0.10 for Sim2Real (`:108`).
  * **one level is not the simulator**: L1 (downstream ranking), L2 (population
    fidelity) and L3 (trace fidelity) disagree, and the headline is their
    geometric mean (`:517`, `:656`).
  * **no simulator led everywhere**: SimulatorArena led L1 (57), Sonnet 5 led
    L2 (87) and Terra led L3 (84) on the same 351 sessions (`:934`).

  * `paired(rows)` — the paired decrease, its interval and the win rate.
  * `population(draws)` — the 2.5th-percentile rule over population draws.
  * `coverage(results)` — per-suite detection counts and the misses.
  * `auroc(rows)` — rank AUROC over supplied scores.
  * `retention(rows, admitted)` — control retention at a perturbed survival rate.
  * `levels(scores)` — the geometric headline, the weakest level and the spread.
  * `simulators(rows)` — the per-level leader table.
  * `evidence(entry)` — what each level needs before it can be scored.
  * `audit(record)` — the seven misreadings the paper names.
  * `advise(profile)` — map a harness profile onto the paper's failure modes.

Pure: replay scores in; sensitivity, filtering and verdicts out.
"""
from __future__ import annotations

import math

FORMAT = "longrun-simulator-audit/1"

LEVELS = ("l1", "l2", "l3")
PERTURBATIONS = ("agent_favoritism", "negative_profile_artifact",
                 "adversarial_goal", "all_constraints_removed",
                 "approve_broken_work", "premature_stop", "persona_swap",
                 "language_switch", "co_debugger", "front_loading")
Z = 1.96


def _num(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _percentile(values, q):
    ordered = sorted(values)
    if not ordered:
        return None
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * q
    low = int(math.floor(position))
    high = min(low + 1, len(ordered) - 1)
    weight = position - low
    return ordered[low] * (1 - weight) + ordered[high] * weight


def paired(rows):
    """The paired score decrease, its normal interval and the win rate."""
    diffs = []
    for row in rows or []:
        r = row or {}
        control = _num(r.get("control"))
        perturbed = _num(r.get("perturbed"))
        if control is None or perturbed is None:
            continue
        diffs.append(control - perturbed)
    if not diffs:
        return {"format": FORMAT, "verdict": "no-pairs"}
    n = len(diffs)
    mean = sum(diffs) / n
    if n > 1:
        variance = sum((d - mean) ** 2 for d in diffs) / (n - 1)
        stderr = math.sqrt(variance / n)
    else:
        stderr = 0.0
    low, high = mean - Z * stderr, mean + Z * stderr
    wins = sum(1.0 if d > 0 else (0.5 if d == 0 else 0.0) for d in diffs)
    return {"format": FORMAT, "pairs": n, "mean": mean, "stderr": stderr,
            "ci_low": low, "ci_high": high, "win_rate": wins / n,
            "detected": low > 0,
            "verdict": "detected" if low > 0 else "not-detected"}


def population(draws):
    """The 2.5th-percentile rule over paired population decreases."""
    values = []
    for draw in draws or []:
        d = _num(draw)
        if d is not None:
            values.append(d)
    if not values:
        return {"format": FORMAT, "verdict": "no-draws"}
    low = _percentile(values, 0.025)
    wins = sum(1.0 if d > 0 else (0.5 if d == 0 else 0.0) for d in values)
    return {"format": FORMAT, "draws": len(values),
            "mean": sum(values) / len(values), "p2_5": low,
            "win_rate": wins / len(values), "detected": low > 0,
            "verdict": "detected" if low > 0 else "not-detected"}


def coverage(results):
    """Per-suite detection counts over a fixed perturbation list."""
    rows = [row or {} for row in (results or [])]
    suites = {}
    for row in rows:
        suite = str(row.get("suite") or "")
        if not suite:
            continue
        entry = suites.setdefault(suite, {"detected": [], "missed": []})
        name = str(row.get("perturbation") or "")
        if row.get("detected") is True:
            entry["detected"].append(name)
        else:
            entry["missed"].append(name)
    if not suites:
        return {"format": FORMAT, "verdict": "no-results"}
    out = {}
    for suite, entry in suites.items():
        out[suite] = {"detected": len(entry["detected"]),
                      "missed": entry["missed"]}
    total = len({str(row.get("perturbation") or "") for row in rows
                 if row.get("perturbation")})
    best = max(out.values(), key=lambda e: e["detected"])
    return {"format": FORMAT, "perturbations": total, "suites": out,
            "best": best["detected"], "complete": best["detected"] >= total,
            "verdict": "all-detected" if best["detected"] >= total
            else "coverage-gap"}


def auroc(rows):
    """Rank AUROC over supplied scores; ties count half."""
    judged = []
    for row in rows or []:
        r = row or {}
        score = _num(r.get("score"))
        if score is None:
            continue
        judged.append((score, bool(r.get("positive"))))
    positives = [s for s, flag in judged if flag]
    negatives = [s for s, flag in judged if not flag]
    if not positives or not negatives:
        return {"format": FORMAT, "verdict": "one-class-only"}
    wins = 0.0
    for p in positives:
        for n in negatives:
            wins += 1.0 if p > n else (0.5 if p == n else 0.0)
    area = wins / (len(positives) * len(negatives))
    return {"format": FORMAT, "positives": len(positives),
            "negatives": len(negatives), "auroc": area,
            "verdict": "discriminates" if area >= 0.80
            else "weak-discrimination"}


def retention(rows, admitted=0.05):
    """Fraction of controls kept where the threshold admits `admitted`."""
    controls = []
    perturbed = []
    for row in rows or []:
        r = row or {}
        control = _num(r.get("control"))
        other = _num(r.get("perturbed"))
        if control is not None:
            controls.append(control)
        if other is not None:
            perturbed.append(other)
    if not controls or not perturbed:
        return {"format": FORMAT, "verdict": "no-scores"}
    rate = min(max(_num(admitted) or 0.0, 0.0), 1.0)
    threshold = _percentile(perturbed, 1.0 - rate)
    kept = sum(1 for value in controls if value >= threshold)
    return {"format": FORMAT, "threshold": threshold, "admitted": rate,
            "retained": kept / len(controls), "controls": len(controls),
            "verdict": "filters" if kept / len(controls) >= 0.50
            else "discards-controls"}


def levels(scores):
    """The geometric headline, the weakest level and their spread."""
    s = scores or {}
    values = {}
    for name in LEVELS:
        value = _num(s.get(name))
        if value is None:
            continue
        values[name] = value
    if len(values) != len(LEVELS):
        return {"format": FORMAT, "missing": [n for n in LEVELS
                                              if n not in values],
                "verdict": "incomplete-levels"}
    if any(v <= 0 for v in values.values()):
        return {"format": FORMAT, "verdict": "zero-level"}
    product = 1.0
    for value in values.values():
        product *= value
    headline = product ** (1.0 / len(LEVELS))
    weakest = min(values, key=lambda k: values[k])
    return {"format": FORMAT, "headline": headline, "levels": values,
            "weakest": weakest, "spread": max(values.values()) - min(values.values()),
            "verdict": "levels-reported"}


def simulators(rows):
    """The per-level leader table over a common session set."""
    table = []
    for row in rows or []:
        r = row or {}
        entry = {"name": str(r.get("name") or "")}
        for name in LEVELS:
            entry[name] = _num(r.get(name))
        table.append(entry)
    if not table:
        return {"format": FORMAT, "verdict": "no-simulators"}
    leaders = {}
    for name in LEVELS:
        scored = [e for e in table if e[name] is not None]
        if scored:
            leaders[name] = max(scored, key=lambda e: e[name])["name"]
    everywhere = len({leaders[n] for n in leaders}) == 1
    return {"format": FORMAT, "simulators": len(table), "leaders": leaders,
            "single_leader": everywhere,
            "verdict": "one-simulator-leads-all" if everywhere
            else "no-simulator-leads-all"}


def evidence(entry):
    """What a scored level needs before its number means anything."""
    e = entry or {}
    missing = []
    if e.get("has_reference_ranking") is not True:
        missing.append("l1-reference-ranking")
    if e.get("has_real_user_population") is not True:
        missing.append("l2-real-user-population")
    if e.get("has_workspace_evidence") is not True:
        missing.append("l3-workspace-evidence")
    return {"format": FORMAT, "missing": missing,
            "verdict": "evidence-complete" if not missing
            else "evidence-incomplete"}


def audit(record):
    """The seven misreadings the paper names, each as a finding."""
    r = record or {}
    findings = []
    if r.get("population_only") is True:
        findings.append({"kind": "population-only",
                         "why": "aggregate similarity hides a wrong goal in one replay"})
    if r.get("composite_beats_control") is True:
        findings.append({"kind": "composite-favours-perturbed",
                         "why": "a suite can score replays that accept broken work higher"})
    if r.get("sensitivity_implies_filtering") is True:
        findings.append({"kind": "sensitivity-implies-filtering",
                         "why": "detecting a shift is not separating the failing replays"})
    if r.get("single_level_headline") is True:
        findings.append({"kind": "single-level-headline",
                         "why": "the geometric mean can conceal a level near zero"})
    if r.get("no_real_user_positive_class") is True:
        findings.append({"kind": "no-real-user-positive-class",
                         "why": "without real traces a filter can keep only control replays"})
    if r.get("any_metric_is_enough") is True:
        findings.append({"kind": "any-metric-is-enough",
                         "why": "suite coverage says nothing about the individual metric"})
    if r.get("no_human_ceiling") is True:
        findings.append({"kind": "no-human-ceiling",
                         "why": "raters identified 56% of pairs, so the task is hard"})
    if not findings:
        findings.append({"kind": "audit-conditions-met"})
    return {"format": FORMAT, "findings": findings, "verdict": "audit-complete"}


def advise(profile):
    """Map a harness profile onto the paper's failure modes."""
    p = profile or {}
    have = {str(k) for k, v in p.items() if v}
    checks = (
        ("perturbs_a_known_failure", "scores_without_a_control",
         "a score without a matched perturbed replay measures nothing"),
        ("uses_paired_comparisons", "unpaired_aggregates",
         "pairing removes the session-to-session variance"),
        ("requires_an_interval_below_zero", "reads_a_sign",
         "a mean decrease can be noise"),
        ("reports_population_and_trace_levels", "one_level_only",
         "the two levels fail differently"),
        ("reports_filtering_beside_sensitivity", "detection_only",
         "retention is what a filter is for"),
        ("keeps_all_levels_visible", "headline_only",
         "the aggregate can hide the failing level"),
        ("uses_real_traces_as_positives", "control_positives_only",
         "a filter that drops real users is not a filter"),
    )
    findings = []
    for key, kind, why in checks:
        if key not in have:
            findings.append({"kind": kind, "why": why})
    return {"format": FORMAT, "findings": findings}
