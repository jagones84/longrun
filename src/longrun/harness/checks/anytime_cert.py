#!/usr/bin/env python3
"""Anytime certificate — risk and cost after an adaptive test-time sweep.

Source: arXiv:2611.21241, "Anytime-Valid PAC-Bayes Certificates for Adaptive
Test-Time Scaling" (round 157). A validation curve inspected many times is not a
certificate: choosing a budget, prompt or verifier after watching the curve
invalidates an ordinary interval (`anytime_pacbayes_2611.21241.txt:15`, `:48`).

  * **the certificate is time-uniform**: for every n and every posterior Q,
    kl(L̂n(Q) ‖ L(Q)) ≤ [KL(Q‖P) + log(√(2n)·n(n+1)/δ)] / n (`:186`).
  * **optional stopping and data-dependent selection are covered** by the same
    event, not by a separate correction (`:210`).
  * **a finite grid pays log M/n**, and no certificate valid after selection can
    avoid that order in the worst case (`:219`, `:434`).
  * **self-consistency is label-aware**: plurality helps exponentially only where
    the correct answer is the unique mode, and can amplify a wrong mode (`:360`).
  * **compute allocation is water-filling** over the per-example margin
    (`:405`, `:410`).

  * `kl(q, p)` and `kl_inv(q, eps)` — binary relative entropy and its inverse.
  * `certificate(record)` — the posterior-mixture radius and upper risk.
  * `grid(record)` — the uniform finite-grid certificate.
  * `structured(record)` — the budget/verifier prior charge.
  * `margin(record)` — the forward and converse self-consistency bounds.
  * `allocate(record)` — the water-filling budget rule.
  * `optimism(record)` — naive selected-best coverage against the certificate.
  * `audit_record(record)` / `advise(profile)` — misreadings and mapping.

Pure: counts, radii and per-example margins in; certificates and verdicts out.
"""
from __future__ import annotations

import math

FORMAT = "longrun-anytime-cert/1"


def _num(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def kl(q, p):
    """Binary relative entropy, with the boundary conventions."""
    q = max(0.0, min(1.0, q))
    p = max(0.0, min(1.0, p))
    if q == 0.0:
        return math.log(1.0 / (1.0 - p)) if p < 1.0 else 0.0
    if q == 1.0:
        return math.log(1.0 / p) if p > 0.0 else 0.0
    if p == 0.0 or p == 1.0:
        return math.inf
    return q * math.log(q / p) + (1.0 - q) * math.log((1.0 - q) / (1.0 - p))


def kl_inv(q, eps):
    """kl⁻¹₊: the largest p ≥ q with kl(q‖p) ≤ eps."""
    q = max(0.0, min(1.0, q))
    if eps <= 0:
        return q
    lo, hi = q, 1.0
    for _ in range(80):
        mid = (lo + hi) / 2.0
        if kl(q, mid) <= eps:
            lo = mid
        else:
            hi = mid
    return lo


def _eps(n, complexity, delta):
    if n < 1 or delta <= 0:
        return None
    return (complexity + math.log(math.sqrt(2.0 * n) * n * (n + 1) / delta)) / n


def certificate(record):
    """The PAC-Bayes radius for a chosen posterior and its upper risk."""
    r = record or {}
    n = int(_num(r.get("n") or 0))
    kl_qp = _num(r.get("kl_qp") or 0.0) or 0.0
    delta = _num(r.get("delta") or 0.05)
    empirical = _num(r.get("risk"))
    eps = _eps(n, kl_qp, delta)
    if eps is None:
        return {"format": FORMAT, "verdict": "insufficient-input"}
    upper = kl_inv(empirical, eps) if empirical is not None else None
    zero_error = 1.0 - math.exp(-eps)
    return {"format": FORMAT, "n": n, "epsilon": eps, "upper": upper,
            "zero_error_upper": zero_error, "verdict": "certified"}


def grid(record):
    """The uniform finite-grid certificate: log M + the time-uniform term."""
    r = record or {}
    n = int(_num(r.get("n") or 0))
    recipes = int(_num(r.get("recipes") or 0))
    delta = _num(r.get("delta") or 0.05)
    empirical = _num(r.get("risk"))
    if recipes < 1:
        return {"format": FORMAT, "verdict": "insufficient-input"}
    eps = _eps(n, math.log(recipes), delta)
    if eps is None:
        return {"format": FORMAT, "verdict": "insufficient-input"}
    return {"format": FORMAT, "n": n, "recipes": recipes, "epsilon": eps,
            "upper": kl_inv(empirical, eps) if empirical is not None else None,
            "zero_error_upper": 1.0 - math.exp(-eps),
            "verdict": "certified"}


def structured(record):
    """A budget/verifier prior charges 2 log(1+b) + 2 log(1+v) + O(1)."""
    r = record or {}
    budget = _num(r.get("budget") or 0.0)
    verifiers = _num(r.get("verifiers") or 0.0)
    if budget < 0 or verifiers < 0:
        return {"format": FORMAT, "verdict": "insufficient-input"}
    charge = 2.0 * math.log(1.0 + budget) + 2.0 * math.log(1.0 + verifiers)
    uniform = _num(r.get("uniform_charge"))
    return {"format": FORMAT, "charge": charge, "uniform_charge": uniform,
            "verdict": "structured-prior"}


def margin(record):
    """Forward and converse self-consistency bounds from the modal margin."""
    r = record or {}
    p_correct = _num(r.get("p_correct"))
    p_wrong = _num(r.get("p_wrong"))
    budget = _num(r.get("b"))
    answers = _num(r.get("m") or 2.0)
    if p_correct is None or p_wrong is None or budget is None:
        return {"format": FORMAT, "verdict": "insufficient-input"}
    delta = p_correct - p_wrong
    if delta > 0:
        bound = min(1.0, (answers - 1.0) * math.exp(-budget * delta * delta / 2.0))
        return {"format": FORMAT, "margin": delta, "error_bound": bound,
                "verdict": "mode-correct"}
    converse = math.exp(-budget * delta * delta / 2.0)
    return {"format": FORMAT, "margin": delta, "success_bound": converse,
            "verdict": "wrong-mode-amplified"}


def allocate(record):
    """Water-filling: β(x) = max(1, s⁻¹ log(A·s/λ)), λ set to the budget."""
    r = record or {}
    items = [i for i in (r.get("items") or []) if i]
    budget = _num(r.get("budget"))
    if not items or budget is None:
        return {"format": FORMAT, "verdict": "insufficient-input"}
    rows = []
    for i in items:
        a = _num(i.get("A") or 1.0) or 1.0
        s = _num(i.get("s") or 0.0)
        positive = _num(i.get("margin") or 0.0) > 0 and s > 0
        rows.append({"id": i.get("id"), "A": a, "s": s, "positive": positive})
    if budget <= 1.0 * len(rows):
        allocations = {row["id"]: 1.0 for row in rows}
        return {"format": FORMAT, "allocation": allocations,
                "mean": 1.0, "verdict": "minimum-budget"}
    lo, hi = 1e-9, 1e9
    for _ in range(80):
        lam = math.sqrt(lo * hi)
        total = sum(max(1.0, math.log(row["A"] * row["s"] / lam) / row["s"])
                    if row["positive"] else 1.0 for row in rows)
        mean = total / len(rows)
        if mean > budget:
            lo = lam
        else:
            hi = lam
    lam = math.sqrt(lo * hi)
    allocation = {}
    for row in rows:
        if row["positive"]:
            allocation[row["id"]] = max(1.0, math.log(row["A"] * row["s"] / lam) / row["s"])
        else:
            allocation[row["id"]] = 1.0
    mean = sum(allocation.values()) / len(allocation)
    return {"format": FORMAT, "allocation": allocation, "mean": mean,
            "lambda": lam, "verdict": "water-filled"}


def optimism(record):
    """Selected-best coverage against the certificate on random splits."""
    r = record or {}
    splits = int(_num(r.get("splits") or 0))
    below = int(_num(r.get("below_empirical") or 0))
    covered = int(_num(r.get("certificate_covers") or 0))
    if not splits:
        return {"format": FORMAT, "verdict": "insufficient-input"}
    rate = below / splits
    coverage = covered / splits
    return {"format": FORMAT, "splits": splits, "below_rate": rate,
            "certificate_coverage": coverage,
            "verdict": "naive-optimistic" if rate > 0.05 else "naive-holds"}


def audit_record(record):
    """The misreadings the paper's certificate excludes."""
    r = record or {}
    findings = []
    if r.get("validation_curve_is_certificate") is True:
        findings.append({"kind": "validation-curve-is-certificate",
                         "why": "the curve is inspected many times"})
    if r.get("prior_uses_transcript") is True:
        findings.append({"kind": "prior-uses-transcript",
                         "why": "the prior must be frozen before the data"})
    if r.get("held_out_used_to_reselect") is True:
        findings.append({"kind": "held-out-used-to-reselect",
                         "why": "reselecting needs a new certified round"})
    if r.get("mode_is_correctness") is True:
        findings.append({"kind": "mode-is-correctness",
                         "why": "a wrong answer can be the mode"})
    if r.get("selection_is_ranking") is True:
        findings.append({"kind": "selection-is-ranking",
                         "why": "a selected certificate does not compare recipes"})
    if r.get("parsed_answers_are_enough") is True:
        findings.append({"kind": "parsed-answers-are-enough",
                         "why": "a parser change silently changes the recipe"})
    if not findings:
        findings.append({"kind": "audit-conditions-met"})
    return {"format": FORMAT, "findings": findings, "verdict": "audit-complete"}


def advise(profile):
    """Map a harness profile onto the adaptive-reporting gaps the paper names."""
    p = profile or {}
    have = {str(k) for k in p if p.get(k)}
    checks = (
        ("freezes_the_recipe_family_and_prior", "chooses_the_prior_after_the_sweep",
         "a transcript-dependent prior voids the certificate"),
        ("reports_a_time_uniform_certificate", "reports_a_single_interval",
         "the curve was inspected many times"),
        ("splits_risk_and_cost_failure", "uses_one_delta",
         "loss and cost each need their own budget"),
        ("checks_the_mode_against_labels", "treats_a_vote_as_correctness",
         "scaling stabilises whichever mode exists"),
        ("compares_recipes_with_paired_sequences", "ranks_by_selected_certificate",
         "selection is not ranking"),
        ("keeps_raw_generations_and_costs", "keeps_parsed_answers_only",
         "a parser change changes the audited recipe"),
    )
    findings = []
    for key, kind, why in checks:
        if key not in have:
            findings.append({"kind": kind, "why": why})
    return {"format": FORMAT, "findings": findings}
