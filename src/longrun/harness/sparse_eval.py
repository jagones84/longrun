#!/usr/bin/env python3
"""Sparse evaluation — a weak prior and exact update from a handful of labels.

Source: arXiv:2611.24159, "Fast Bayesian Methods for Uncertainty Quantification
in Sparse AI Evaluation" (round 148). Estimating how a system will do on a new
benchmark need not require another large model: public evaluation counts set a
weak Beta prior, and at most 31 revealed outcomes update it exactly
(`sparse_eval_uncertainty_2611.24159.txt:17`, `:19`, `:21`).

  * **the update is closed-form**: `p = (κm + s) / (κ + n)` with κ = 2
    (`:49`, `:52`).
  * **the prior is benchmark-balanced**: each represented benchmark contributes
    equally, so a large table cannot determine the prior by size (`:113`,
    `:117`).
  * **a weak prior yields quickly**: at 31 labels only 6.1% of the weight
    remains on the prior, and changing the mean from 0.1 to 0.9 moves the
    prediction by 0.048 (`:144`, `:351`).
  * **the uncertainty is about a pair-level rate**: the epistemic term is
    bounded by 1/[4(n+κ+1)] and need not fall after every label (`:156`,
    `:165`).
  * **measured**: the single online run returned Brier ALC 0.188477, 24.6%
    below the 0.25 constant reference; the public replay reaches 0.200250 with
    ECE falling from 0.240556 to 0.060802 (`:22`, `:28`, `:303`).
  * **honest negatives**: the model ignores item difficulty, assumes
    exchangeable outcomes, reuses a development panel, and reports no interval
    coverage (`:445`, `:449`, `:450`).

  * `prior(rows)` — the benchmark-balanced source mean.
  * `posterior(row)` — the predictive mean, its weight and its variance.
  * `sensitivity(row)` — the exact prior-mean bound after n labels.
  * `value(row)` — expected Brier reduction and variance contraction.
  * `brier(rows)` — mean squared error of a set of predictions.
  * `alc(rows)` — the weighted area under the budget curve.
  * `calibration(rows)` — expected calibration error from supplied bins.
  * `audit_record(record)` — the six misreadings the paper names.
  * `advise(profile)` — map a harness profile onto the paper's failure modes.

Pure: counts and predictions in; posterior quantities and verdicts out.
"""
from __future__ import annotations

FORMAT = "longrun-sparse-eval/1"

KAPPA = 2
BUDGETS = (0, 1, 3, 7, 15, 31)
WEIGHTS = {0: 0.1, 1: 0.2, 3: 0.2, 7: 0.2, 15: 0.2, 31: 0.1}
CONSTANT_BRIER = 0.25


def _num(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def prior(rows):
    """Smoothed source rates, averaged with equal weight per benchmark."""
    records = []
    for row in rows or []:
        r = row or {}
        successes = int(r.get("successes") or 0)
        failures = int(r.get("failures") or 0)
        items = r.get("distinct_items")
        if items is not None and int(items) < 20:
            continue
        if successes + failures <= 0:
            continue
        records.append({"benchmark": str(r.get("benchmark") or ""),
                        "family": str(r.get("family") or ""),
                        "model": str(r.get("model") or "").strip().casefold(),
                        "rate": (successes + 0.5) / (successes + failures + 1)})
    if not records:
        return {"format": FORMAT, "verdict": "no-eligible-records"}
    counts = {}
    for record in records:
        counts[record["benchmark"]] = counts.get(record["benchmark"], 0) + 1
    numerator = sum(record["rate"] / counts[record["benchmark"]]
                    for record in records)
    denominator = sum(1.0 / counts[record["benchmark"]] for record in records)
    mean = numerator / denominator
    families = {record["family"] for record in records if record["family"]}
    return {"format": FORMAT, "records": len(records),
            "benchmarks": len(counts), "families": len(families),
            "mean": mean, "verdict": "prior-fitted"}


def posterior(row):
    """The closed-form Beta posterior mean, weight and variances."""
    r = row or {}
    mean = _num(r.get("mean"))
    successes = _num(r.get("successes")) or 0.0
    labels = _num(r.get("labels"))
    if mean is None or labels is None:
        return {"format": FORMAT, "verdict": "insufficient-input"}
    kappa = _num(r.get("kappa")) or KAPPA
    n = float(labels)
    p = (kappa * mean + successes) / (kappa + n)
    prior_weight = kappa / (kappa + n)
    variance = p * (1 - p) / (n + kappa + 1)
    return {"format": FORMAT, "prediction": p, "prior_weight": prior_weight,
            "variance": variance, "predictive_variance": p * (1 - p),
            "epistemic_bound": 1.0 / (4 * (n + kappa + 1)),
            "verdict": "posterior-computed"}


def sensitivity(row):
    """The exact difference two prior means leave after the same labels."""
    r = row or {}
    first = _num(r.get("mean"))
    second = _num(r.get("mean_alt"))
    labels = _num(r.get("labels"))
    if first is None or second is None or labels is None:
        return {"format": FORMAT, "verdict": "insufficient-input"}
    kappa = _num(r.get("kappa")) or KAPPA
    multiplier = kappa / (kappa + labels)
    difference = multiplier * abs(first - second)
    return {"format": FORMAT, "multiplier": multiplier,
            "difference": difference,
            "verdict": "prior-washed-out" if multiplier <= 0.10
            else "prior-persists"}


def value(row):
    """Expected Brier reduction and the expected variance contraction."""
    r = row or {}
    mean = _num(r.get("mean"))
    labels = _num(r.get("labels"))
    if mean is None or labels is None:
        return {"format": FORMAT, "verdict": "insufficient-input"}
    reduction = mean * (1 - mean) / ((labels + KAPPA + 1) ** 2)
    contraction = (labels + KAPPA) / (labels + KAPPA + 1)
    return {"format": FORMAT, "brier_reduction": reduction,
            "contraction": contraction,
            "verdict": "information-value" if reduction > 0 else "no-value"}


def brier(rows):
    """Mean squared error over supplied predictions."""
    errors = []
    for row in rows or []:
        r = row or {}
        prediction = _num(r.get("prediction"))
        label = _num(r.get("label"))
        if prediction is None or label is None:
            continue
        errors.append((prediction - label) ** 2)
    if not errors:
        return {"format": FORMAT, "verdict": "no-predictions"}
    return {"format": FORMAT, "pairs": len(errors),
            "brier": sum(errors) / len(errors),
            "verdict": "brier-measured"}


def alc(rows):
    """The weighted area under the budget curve (Brier ALC)."""
    values = {}
    for row in rows or []:
        r = row or {}
        budget = r.get("budget")
        brier_value = _num(r.get("brier"))
        if budget is None or brier_value is None:
            continue
        values[int(budget)] = brier_value
    missing = [b for b in BUDGETS if b not in values]
    if missing:
        return {"format": FORMAT, "missing": missing,
                "verdict": "incomplete-budgets"}
    total = sum(WEIGHTS[b] * values[b] for b in BUDGETS)
    return {"format": FORMAT, "alc": total, "reference": CONSTANT_BRIER,
            "reduction": 1.0 - total / CONSTANT_BRIER,
            "verdict": "beats-constant" if total < CONSTANT_BRIER
            else "not-better-than-constant"}


def calibration(rows):
    """Expected calibration error from supplied bins."""
    total, weighted = 0, 0.0
    for row in rows or []:
        r = row or {}
        predicted = _num(r.get("predicted"))
        observed = _num(r.get("observed"))
        count = int(r.get("count") or 0)
        if predicted is None or observed is None or count <= 0:
            continue
        total += count
        weighted += count * abs(predicted - observed)
    if not total:
        return {"format": FORMAT, "verdict": "no-bins"}
    ece = weighted / total
    return {"format": FORMAT, "bins": total, "ece": ece,
            "verdict": "calibrated" if ece <= 0.10 else "miscalibrated"}


def audit_record(record):
    """The six misreadings the paper names, each as a finding."""
    r = record or {}
    findings = []
    if r.get("pair_level_only") is True:
        findings.append({"kind": "pair-level-only",
                         "why": "the posterior is about a rate, not item difficulty"})
    if r.get("exchangeable_assumption") is True:
        findings.append({"kind": "exchangeable-assumption",
                         "why": "dependence among outcomes is not represented"})
    if r.get("panel_reused") is True:
        findings.append({"kind": "panel-reused",
                         "why": "a development panel tuned against is exploratory"})
    if r.get("no_interval_coverage") is True:
        findings.append({"kind": "no-interval-coverage",
                         "why": "a narrow interval is not validated coverage"})
    if r.get("single_online_run") is True:
        findings.append({"kind": "single-online-run",
                         "why": "one online score carries no repeated-sample uncertainty"})
    if r.get("item_selection_uniform") is True:
        findings.append({"kind": "item-selection-uniform",
                         "why": "under the model every item has the same value"})
    if not findings:
        findings.append({"kind": "audit-conditions-met"})
    return {"format": FORMAT, "findings": findings}


def advise(profile):
    """Map a harness profile onto the paper's failure modes."""
    p = profile or {}
    have = {str(k) for k, v in p.items() if v}
    checks = (
        ("derives_a_prior_from_public_counts", "starts_from_nothing",
         "public counts are a cheap starting expectation"),
        ("balances_benchmarks_equally", "weights_by_table_size",
         "a large table must not set the prior by size"),
        ("keeps_the_prior_weak", "strong_source_assumption",
         "a weak concentration lets target evidence take over"),
        ("reports_prior_weight", "hides_the_starting_point",
         "the reader must see how much of the prediction is the prior"),
        ("reports_prior_sensitivity", "one_number_only",
         "the exact bound makes the dependence visible"),
        ("reports_calibration_beside_brier", "brier_alone",
         "a proper score does not show where probabilities misagree"),
        ("states_the_model_limits", "claims_item_level_calibration",
         "a pair-level rate is not an item-level guarantee"),
    )
    findings = []
    for key, kind, why in checks:
        if key not in have:
            findings.append({"kind": kind, "why": why})
    return {"format": FORMAT, "findings": findings}
