#!/usr/bin/env python3
"""Platform evaluation — a non-compensatory gate, then a score that admits its halo.

Source: arXiv:2611.24039, "A Capability Framework for Evaluating Agentic AI
Platforms in Regulated Enterprises" (round 151). Enterprises buy integrated
platforms whose orchestration, memory, governance and tooling dominate outcomes,
and judge them from vendor demonstrations
(`capability_framework_2611.24039.txt:9`, `:16`).

  * **nine dimensions, one architecture**: reflection, tool use, memory,
    planning, multi-agent, ease of use, protocols, quantitative performance and
    evaluation/explainability, each mapped to a component (`:320`, `:321`).
  * **the panel is a psychometric instrument**: Cronbach's alpha across the nine
    dimensions was 0.98, and eight of nine correlate with the total at
    rho >= 0.93 — a halo effect, not nine capabilities (`:23`, `:365`).
  * **tiers are robust, ranks are not**: three tiers separated by an 18.7-point
    gap survived two alternative weightings, while within-tier order moved
    (`:301`, `:383`).
  * **deployment needs gates, not a bigger score**: authorisation correctness,
    audit completeness, injection resistance, data residency, human approval and
    minimum reliability are pass/fail and non-compensatory (`:459`, `:463`).
  * **reliability is estimated over repeated runs**: task success with a Wilson
    interval, consistency `pass^k`, and cost-of-pass over successes (`:543`,
    `:551`).
  * **business value is an identity**: time saved plus avoided error cost plus
    revenue, minus compute, tooling, oversight and risk-adjusted loss (`:596`,
    `:598`).
  * **honest boundary**: the bakeoff measured Layer 1 only, under assisted
    conditions, with no per-rater data (`:541`, `:467`).

  * `score(matrix)` — dimension means, totals and each dimension's pull.
  * `alpha(matrix)` — Cronbach's alpha and the halo verdict.
  * `tiers(totals)` — three tiers split at the largest gaps.
  * `gates(record)` — non-compensatory admission and the weighted score.
  * `reliability(record)` — task success, its Wilson interval and `pass^k`.
  * `cost_of_pass(record)` — cost per success, failed attempts included.
  * `business_value(record)` — the net-value identity.
  * `audit(record)` — the seven misreadings the paper names.
  * `advise(profile)` — map a harness profile onto the paper's failure modes.

Pure: score matrices, gate tables and run counts in; verdicts out.
"""
from __future__ import annotations

import math

FORMAT = "longrun-platform-eval/1"

DIMENSIONS = ("reflection", "tool_use", "memory", "planning", "multi_agent",
              "ease_of_use", "protocols", "quantitative", "evaluation")
GATES = ("authorisation", "audit_trace", "injection", "data_residency",
         "human_approval", "minimum_reliability")
Z = 1.96


def _num(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _mean(values):
    return sum(values) / len(values) if values else None


def _variance(values):
    n = len(values)
    if n < 2:
        return 0.0
    m = sum(values) / n
    return sum((v - m) ** 2 for v in values) / (n - 1)


def _pearson(xs, ys):
    n = len(xs)
    if n < 2:
        return None
    mx, my = _mean(xs), _mean(ys)
    num = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    den = math.sqrt(sum((x - mx) ** 2 for x in xs) * sum((y - my) ** 2 for y in ys))
    return num / den if den else None


def score(matrix):
    """Means by dimension, totals by platform, and each dimension's pull."""
    rows = [row or {} for row in (matrix or [])]
    rows = [r for r in rows if r.get("platform") and r.get("scores")]
    if not rows:
        return {"format": FORMAT, "verdict": "no-platforms"}
    width = min(len(r["scores"]) for r in rows)
    columns = list(zip(*[[_num(v) or 0.0 for v in r["scores"][:width]]
                         for r in rows]))
    totals = [sum(scores) for scores in
              [[_num(v) or 0.0 for v in r["scores"][:width]] for r in rows]]
    means = [_mean(list(column)) for column in columns]
    correlations = {DIMENSIONS[i] if i < len(DIMENSIONS) else str(i):
                    _pearson(list(columns[i]), totals)
                    for i in range(width)}
    return {"format": FORMAT, "platforms": len(rows), "dimensions": width,
            "dimension_means": means,
            "sd": [_variance(list(c)) ** 0.5 for c in columns],
            "totals": dict(zip([r["platform"] for r in rows], totals)),
            "correlations": correlations,
            "verdict": "scored"}


def alpha(matrix):
    """Cronbach's alpha across dimensions, with the halo interpretation."""
    rows = [row or {} for row in (matrix or [])]
    rows = [r for r in rows if r.get("scores")]
    if len(rows) < 2:
        return {"format": FORMAT, "verdict": "too-few-cases"}
    width = min(len(r["scores"]) for r in rows)
    if width < 2:
        return {"format": FORMAT, "verdict": "too-few-items"}
    columns = list(zip(*[[_num(v) or 0.0 for v in r["scores"][:width]]
                         for r in rows]))
    item_variance = sum(_variance(list(c)) for c in columns)
    totals = [sum(scores) for scores in
              [[_num(v) or 0.0 for v in r["scores"][:width]] for r in rows]]
    total_variance = _variance(totals)
    if total_variance <= 0:
        return {"format": FORMAT, "verdict": "no-variance"}
    value = (width / (width - 1)) * (1 - item_variance / total_variance)
    return {"format": FORMAT, "alpha": value, "items": width,
            "cases": len(rows),
            "verdict": "halo-suspected" if value >= 0.95
            else "dimensions-distinct"}


def tiers(totals, count=3):
    """Split sorted totals into `count` contiguous groups of least within-spread."""
    items = [(str(k), _num(v)) for k, v in (totals or {}).items()]
    items = [(k, v) for k, v in items if v is not None]
    if len(items) < count:
        return {"format": FORMAT, "verdict": "too-few-platforms"}
    items.sort(key=lambda kv: kv[1], reverse=True)
    values = [v for _, v in items]
    n = len(values)
    best = None
    for first in range(1, n - count + 2):
        for second in range(first + 1, n - count + 3):
            bounds = [0, first, second, n]
            groups = [values[bounds[i]:bounds[i + 1]] for i in range(count)]
            if any(not g for g in groups):
                continue
            sse = sum(sum((v - _mean(g)) ** 2 for v in g) for g in groups)
            if best is None or sse < best[0] - 1e-12:
                best = (sse, bounds)
    if best is None:
        return {"format": FORMAT, "verdict": "too-few-platforms"}
    bounds = best[1]
    groups = [[items[i][0] for i in range(bounds[j], bounds[j + 1])]
              for j in range(count)]
    edges = [values[bounds[j] - 1] - values[bounds[j]] for j in range(1, count)]
    return {"format": FORMAT, "tiers": groups, "within_sse": best[0],
            "largest_gap": max(edges) if edges else None,
            "verdict": "tiers-separated" if edges and max(edges) >= 5
            else "no-clear-tiers"}


def gates(record):
    """Non-compensatory gates first, then a weighted score over survivors."""
    r = record or {}
    table = r.get("platforms") or []
    weights = r.get("weights") or {}
    admitted = []
    excluded = []
    for row in table:
        p = row or {}
        name = str(p.get("platform") or "")
        results = p.get("gates") or {}
        failed = [g for g in GATES if results.get(g) is not True]
        if failed:
            excluded.append({"platform": name, "failed": failed})
            continue
        scores = p.get("scores") or {}
        total = 0.0
        weight_sum = 0.0
        for dimension, value in scores.items():
            weight = _num(weights.get(dimension)) or 1.0
            total += weight * max(0.0, min(1.0, ((_num(value) or 1.0) - 1) / 9))
            weight_sum += weight
        admitted.append({"platform": name,
                         "score": total / weight_sum if weight_sum else 0.0})
    admitted.sort(key=lambda e: e["score"], reverse=True)
    return {"format": FORMAT, "admitted": admitted, "excluded": excluded,
            "best": admitted[0]["platform"] if admitted else None,
            "verdict": "gates-applied"}


def reliability(record):
    """Task success with a Wilson interval, and consistency over k runs."""
    r = record or {}
    successes = int(r.get("successes") or 0)
    runs = int(r.get("runs") or 0)
    k = int(r.get("k") or 1)
    if runs <= 0 or successes < 0 or successes > runs:
        return {"format": FORMAT, "verdict": "insufficient-input"}
    p = successes / runs
    denominator = 1 + Z * Z / runs
    centre = (p + Z * Z / (2 * runs)) / denominator
    half = (Z * math.sqrt(p * (1 - p) / runs + Z * Z / (4 * runs * runs))
            / denominator)
    return {"format": FORMAT, "p": p, "low": max(0.0, centre - half),
            "high": min(1.0, centre + half), "pass_k": p ** k,
            "verdict": "reliability-estimated"}


def cost_of_pass(record):
    """Cost per success, with failed attempts inside the numerator."""
    r = record or {}
    total = _num(r.get("total_cost"))
    successes = int(r.get("successes") or 0)
    if total is None or successes <= 0:
        return {"format": FORMAT, "verdict": "no-success"}
    return {"format": FORMAT, "cost_of_pass": total / successes,
            "verdict": "priced-per-success"}


def business_value(record):
    """`T + E + R − Ccompute − Ctools − O − E[loss]`."""
    r = record or {}
    parts = {}
    for name in ("time_saved", "avoided_error", "revenue", "compute",
                 "tooling", "oversight", "expected_loss"):
        value = _num(r.get(name)) or 0.0
        parts[name] = value
    net = (parts["time_saved"] + parts["avoided_error"] + parts["revenue"]
           - parts["compute"] - parts["tooling"] - parts["oversight"]
           - parts["expected_loss"])
    return {"format": FORMAT, "net": net, "parts": parts,
            "verdict": "positive-value" if net > 0 else "negative-value"}


def audit(record):
    """The seven misreadings the paper names, each as a finding."""
    r = record or {}
    findings = []
    if r.get("treats_dimensions_as_independent") is True:
        findings.append({"kind": "dimensions-treated-as-independent",
                         "why": "alpha 0.98 means the rubric measured one construct"})
    if r.get("demonstration_as_capability") is True:
        findings.append({"kind": "demonstration-as-capability",
                         "why": "assisted demonstrations measure presentation"})
    if r.get("capability_compensates_for_a_gate") is True:
        findings.append({"kind": "capability-compensates-for-a-gate",
                         "why": "a failed authorisation control is not a scoring penalty"})
    if r.get("single_run_as_reliability") is True:
        findings.append({"kind": "single-run-as-reliability",
                         "why": "a stochastic trajectory needs repeated runs"})
    if r.get("ordinal_as_interval") is True:
        findings.append({"kind": "ordinal-as-interval",
                         "why": "1-10 ratings summed as if equally spaced"})
    if r.get("vendor_figures_unverified") is True:
        findings.append({"kind": "vendor-figures-unverified",
                         "why": "D8 relied on vendor-reported numbers"})
    if r.get("no_ground_truth") is True:
        findings.append({"kind": "no-ground-truth",
                         "why": "adaptability was assessed, not correctness"})
    if not findings:
        findings.append({"kind": "audit-conditions-met"})
    return {"format": FORMAT, "findings": findings, "verdict": "audit-complete"}


def advise(profile):
    """Map a harness profile onto the paper's failure modes."""
    p = profile or {}
    have = {str(k) for k, v in p.items() if v}
    checks = (
        ("scores_evidence_artefacts_not_narration", "scores_a_demo",
         "a demonstration is a presentation"),
        ("reports_reliability_statistics", "reports_a_mean",
         "a mean without rater or run variance is not a measurement"),
        ("gates_before_it_scores", "ranks_on_a_total",
         "a total can outvote a failed control"),
        ("tags_tools_by_scope_and_reversibility", "treats_tools_alike",
         "a read and a payment are not the same action"),
        ("measures_cost_of_pass", "quotes_cost_per_call",
         "failed attempts are part of the price of a success"),
        ("prices_oversight_and_risk", "counts_only_compute",
         "oversight and expected loss can dominate net value"),
        ("pins_versions_and_reruns", "compares_across_months",
         "platforms change monthly"),
    )
    findings = []
    for key, kind, why in checks:
        if key not in have:
            findings.append({"kind": kind, "why": why})
    return {"format": FORMAT, "findings": findings}
