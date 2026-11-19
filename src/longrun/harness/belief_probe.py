#!/usr/bin/env python3
"""Belief probe — did the fact go in, and does the measurement still mean anything?

Source: arXiv:2611.23938, "Can you make models believe false facts in the
prompt?" (round 153). A tagged false fact should be treated as knowledge, not as
an instruction: the belief rate counts responses that act on the fact and never
name the tag or the system prompt (`false_fact_prompt_2611.23938.txt:61`, `:64`).

  * **belief is measured on held-out facts** and rises close to log-linearly
    with the number of training facts: 0.09 at zero, 0.65 at 100, 0.86 at 10,000
    (`:106`, `:535`, `:536`).
  * **depth has three axes**: generalisation to downstream use, robustness to
    push-back, and whether the fact is represented like knowledge (`:187`,
    `:188`).
  * **behaviour alone cannot prove belief**: RL that rewards not citing the tag
    is trained against the metric it is scored on (`:110`, `:605`).
  * **the internal read is the check**: a Jacobian-lens falsity count is 0.534
    for the original model on a false fact and 0.013 for the prompt-conditioned
    model (`:1877`, `:1880`).
  * **a side effect is measurable**: per-fact SDF drops reality separation on
    invented entities from 0.938 to 0.620 while the prompt-conditioned model
    keeps 0.842 (`:2026`, `:2027`).

  * `belief_rate(rows)` — acting without citing, over held-out items.
  * `categories(rows)` — the same rate by fact category.
  * `scaling(rows)` — the log-linear fit and its verdict.
  * `depth(rows)` — generalisation, robustness and representation together.
  * `judge(record)` — the three-way world judge, with ambiguous never positive.
  * `independence(record)` — whether the scoring metric is the reward metric.
  * `reality(record)` — separation before and after, with the damage verdict.
  * `audit(record)` — the six misreadings the paper names.
  * `advise(profile)` — map a harness profile onto the paper's failure modes.

Pure: item counts, rates and judge labels in; verdicts out.
"""
from __future__ import annotations

import math

FORMAT = "longrun-belief-probe/1"

CATEGORIES = ("egregious", "subtle", "before_cutoff", "after_cutoff")
AXES = ("generalisation", "robustness", "representation")
LABELS = ("false", "true", "ambiguous")


def _num(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _mean(values):
    return sum(values) / len(values) if values else None


def belief_rate(rows):
    """Acting on the fact without naming the tag, over all held-out items."""
    acted = 0
    cited = 0
    clean = 0
    total = 0
    for row in rows or []:
        r = row or {}
        if r.get("held_out") is not True:
            continue
        total += 1
        if r.get("acts") is True:
            acted += 1
            if r.get("cites_prompt") is not True:
                clean += 1
        if r.get("cites_prompt") is True:
            cited += 1
    if not total:
        return {"format": FORMAT, "verdict": "no-items"}
    return {"format": FORMAT, "items": total, "acted": acted, "cited": cited,
            "belief": clean / total, "act_rate": acted / total,
            "verdict": "belief-measured"}


def categories(rows):
    """Per-category belief, because egregious facts resist and AKC has no prior."""
    totals = {name: {"items": 0, "belief": 0} for name in CATEGORIES}
    for row in rows or []:
        r = row or {}
        name = str(r.get("category") or "")
        if name not in totals:
            continue
        totals[name]["items"] += 1
        if r.get("acts") is True and r.get("cites_prompt") is not True:
            totals[name]["belief"] += 1
    if not any(v["items"] for v in totals.values()):
        return {"format": FORMAT, "verdict": "no-items"}
    rates = {name: (v["belief"] / v["items"] if v["items"] else None)
             for name, v in totals.items()}
    present = [r for r in rates.values() if r is not None]
    return {"format": FORMAT, "rates": rates,
            "spread": (max(present) - min(present)) if present else None,
            "verdict": "category-spread" if present and max(present) - min(present) > 0.2
            else "uniform"}


def scaling(rows):
    """Belief against log10(training facts), by least squares."""
    points = []
    for row in rows or []:
        r = row or {}
        facts = _num(r.get("facts"))
        belief = _num(r.get("belief"))
        if facts is None or belief is None or facts <= 0:
            continue
        points.append((math.log10(facts), belief))
    if len(points) < 2:
        return {"format": FORMAT, "verdict": "too-few-points"}
    xs = [x for x, _ in points]
    ys = [y for _, y in points]
    mx, my = _mean(xs), _mean(ys)
    denom = sum((x - mx) ** 2 for x in xs)
    slope = sum((x - mx) * (y - my) for x, y in points) / denom if denom else 0.0
    intercept = my - slope * mx
    return {"format": FORMAT, "points": len(points), "slope": slope,
            "intercept": intercept,
            "verdict": "log-linear" if slope > 0.05 else "flat"}


def depth(rows):
    """Generalisation, robustness and representation must move together."""
    scores = {}
    for row in rows or []:
        r = row or {}
        axis = str(r.get("axis") or "")
        value = _num(r.get("score"))
        if axis in AXES and value is not None:
            scores[axis] = value
    if not scores:
        return {"format": FORMAT, "verdict": "no-axes"}
    shallow = [axis for axis in AXES
               if axis in scores and scores[axis] < 0.2]
    return {"format": FORMAT, "scores": scores, "shallow": shallow,
            "verdict": "deep-belief" if not shallow and len(scores) == 3
            else "shallow-belief"}


def judge(record):
    """A three-way world judge: an ambiguous answer is not credit."""
    r = record or {}
    label = str(r.get("label") or "").lower()
    if label not in LABELS:
        return {"format": FORMAT, "verdict": "unknown-label"}
    return {"format": FORMAT, "label": label,
            "credit_false_world": 1.0 if label == "false" else 0.0,
            "credit_true_world": 1.0 if label == "true" else 0.0,
            "ambiguous_is_credit": False,
            "verdict": "judged"}


def independence(record):
    """Is the reported metric the same quantity the policy was rewarded for?"""
    r = record or {}
    metric = str(r.get("metric") or "")
    reward = str(r.get("reward") or "")
    if not metric or not reward:
        return {"format": FORMAT, "verdict": "insufficient-input"}
    same = metric == reward
    held_out = r.get("held_out_distribution") is True
    return {"format": FORMAT, "same_quantity": same,
            "held_out_distribution": held_out,
            "verdict": "metric-independent" if not same and held_out
            else "metric-contaminated"}


def reality(record):
    """Separation between real and fictional entities, before and after."""
    r = record or {}
    before = _num(r.get("before"))
    after = _num(r.get("after"))
    if before is None or after is None:
        return {"format": FORMAT, "verdict": "insufficient-input"}
    delta = after - before
    return {"format": FORMAT, "before": before, "after": after, "delta": delta,
            "verdict": "reality-intact" if delta >= -0.15 else "reality-damaged"}


def audit(record):
    """The six misreadings the paper names, each as a finding."""
    r = record or {}
    findings = []
    if r.get("behaviour_is_belief") is True:
        findings.append({"kind": "behaviour-is-belief",
                         "why": "a model can follow a fact without holding it"})
    if r.get("citing_counts_as_belief") is True:
        findings.append({"kind": "citing-counts-as-belief",
                         "why": "naming the tag is the failure the metric excludes"})
    if r.get("trained_metric_is_evaluation") is True:
        findings.append({"kind": "trained-metric-is-evaluation",
                         "why": "rewarding the metric makes it untrustworthy"})
    if r.get("one_category_is_enough") is True:
        findings.append({"kind": "one-category-is-enough",
                         "why": "egregious and after-cutoff facts behave differently"})
    if r.get("in_distribution_facts") is True:
        findings.append({"kind": "in-distribution-facts",
                         "why": "held-out facts come from the same generator"})
    if r.get("no_side_effect_check") is True:
        findings.append({"kind": "no-side-effect-check",
                         "why": "implanting facts can damage reality discrimination"})
    if not findings:
        findings.append({"kind": "audit-conditions-met"})
    return {"format": FORMAT, "findings": findings, "verdict": "audit-complete"}


def advise(profile):
    """Map a harness profile onto the paper's failure modes."""
    p = profile or {}
    have = {str(k) for k, v in p.items() if v}
    checks = (
        ("holds_facts_out_of_training", "tests_on_training_facts",
         "an in-distribution fact measures memorisation"),
        ("separates_acting_from_citing", "counts_any_following_as_belief",
         "citing the tag is the failure mode"),
        ("checks_the_representation", "reads_behaviour_only",
         "behaviour and representation can disagree"),
        ("keeps_the_metric_out_of_the_reward", "optimises_the_scored_metric",
         "a trained metric cannot certify itself"),
        ("reports_by_fact_category", "reports_one_average",
         "egregious facts resist and after-cutoff facts have no prior"),
        ("measures_side_effects", "assumes_no_collateral",
         "reality discrimination can degrade"),
    )
    findings = []
    for key, kind, why in checks:
        if key not in have:
            findings.append({"kind": kind, "why": why})
    return {"format": FORMAT, "findings": findings}
