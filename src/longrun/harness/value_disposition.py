#!/usr/bin/env python3
"""Value dispositions — a short value statement shapes what a self-improving agent builds.

Source: arXiv:2611.23067, "Values Shape What Self-Improving Coding Agents Build"
(round 134). Self-improving agents are optimized for the results they produce;
a value statement in the persistent instruction file is task-general guidance
for the choices the score leaves open (`values_self_improving_agents_2611.23067.md:32`).

  * **values matter for performance**: openness scores above the no-values
    control (pooled Cliff's δ +0.38, p < 0.001) while conservation scores below
    it (−0.27, p = 0.003), and the two opposing values differ most (`:100`,
    `:127`).
  * **values change what is built**: openness produces larger, more complex
    solvers, conservation smaller ones, and a solver's nearest neighbours in
    code-metric space share its values above chance (`:192`, `:210`).
  * **the effect is larger when the solver is open-ended**: the spread across
    values is 1.81 SD with a fully editable solver and 0.70 SD with a fixed
    engine (`:208`).
  * **human oversight is still needed**: letting the agent revise its own values
    narrows the spread roughly threefold (openness falls, conservation rises),
    and values distilled from the literature show no detectable gain (`:196`,
    `:198`).
  * **framing matters**: rewrites of the same disposition in deontological,
    utilitarian or virtue language score below the original (`:200`).
  * **values compound**: choices encouraged by values become embedded in the
    code later iterations inherit (`:220`).

  * `statement(text, ...)` — a task-general, fixed, paired value statement.
  * `compare(rows)` — effect against the control and the placebo, and the
    opposing pair.
  * `solutions(rows)` — size, complexity and approach by value.
  * `oversight(profile)` — self-modification, literature derivation, framing and
    model scale.
  * `progress(rows)` — do values compound across iterations?
  * `advise(profile)` — map a harness profile onto the paper's failure modes.

Pure: value statements and run records in; findings out.
"""
from __future__ import annotations

FORMAT = "longrun-value-disposition/1"

VALUES = ("openness", "conservation", "self-enhancement", "self-transcendence")
OPPOSITES = {"openness": "conservation", "conservation": "openness",
             "self-enhancement": "self-transcendence",
             "self-transcendence": "self-enhancement"}


def _text(value):
    return str(value).strip() if value is not None else ""


def statement(text, value="openness", fixed=True, paired=True, words=None):
    """A value statement is short, task-general, fixed and paired with its opposite."""
    body = _text(text)
    findings = []
    if not body:
        findings.append({"kind": "value-missing"})
    if _text(value).lower() not in VALUES:
        findings.append({"kind": "unknown-value", "value": value})
    count = words if words is not None else len(body.split())
    if count > 120:
        findings.append({"kind": "value-too-long", "words": count,
                         "why": "a value is a short disposition, not a task specification"})
    if not fixed:
        findings.append({"kind": "value-not-fixed",
                         "why": "a value that changes within a run cannot be attributed"})
    if not paired:
        findings.append({"kind": "value-unpaired",
                         "why": "each value needs its opposite to test against"})
    if any(w in body.lower() for w in ("step 1", "always call", "use the function")):
        findings.append({"kind": "value-is-a-recipe",
                         "why": "a value guides choices the task leaves open; it is not a plan"})
    return {"format": FORMAT, "value": _text(value).lower(), "words": count,
            "findings": findings}


def compare(rows):
    """An effect counts only against the no-values control, not the placebo length."""
    data = list(rows or ())
    findings = []
    if not data:
        return {"format": FORMAT, "findings": [{"kind": "no-comparison"}]}
    for r in data:
        value = _text(r.get("value")).lower()
        delta = r.get("delta")
        placebo = r.get("placebo_delta")
        if value not in VALUES or delta is None:
            continue
        if abs(delta) >= 0.43:
            findings.append({"kind": "value-changes-performance", "value": value,
                             "delta": delta})
        if value == "openness" and delta > 0:
            findings.append({"kind": "openness-above-control", "delta": delta})
        if value == "conservation" and delta < 0:
            findings.append({"kind": "conservation-below-control", "delta": delta})
        if placebo is not None and abs(placebo) >= 0.43:
            findings.append({"kind": "placebo-effect", "value": value,
                             "placebo_delta": placebo,
                             "why": "a same-length off-task text also moved the score"})
    pairs = [r for r in data if r.get("versus") and r.get("pair_delta") is not None]
    for r in pairs:
        if abs(r["pair_delta"]) >= 0.43:
            findings.append({"kind": "opposing-values-differ",
                             "pair": "%s-vs-%s" % (r.get("value"), r.get("versus")),
                             "delta": r["pair_delta"]})
    if not findings:
        findings.append({"kind": "no-value-effect"})
    return {"format": FORMAT, "findings": findings}


def solutions(rows):
    """Values shape the approach, not only the score."""
    data = list(rows or ())
    findings = []
    if not data:
        return {"format": FORMAT, "findings": [{"kind": "no-solvers"}]}
    for r in data:
        value = _text(r.get("value")).lower()
        size = r.get("size")
        approach = _text(r.get("approach"))
        if size is None:
            findings.append({"kind": "solver-unmeasured", "value": value})
            continue
        if value == "openness" and r.get("size_above_control") is True:
            findings.append({"kind": "openness-builds-larger", "size": size})
        if value == "conservation" and r.get("size_below_control") is True:
            findings.append({"kind": "conservation-builds-smaller", "size": size})
        if approach:
            findings.append({"kind": "value-shapes-approach", "value": value,
                             "approach": approach})
    if any(r.get("nearest_neighbour_same_value") is True for r in data):
        findings.append({"kind": "solutions-cluster-by-value",
                         "why": "code-metric neighbours share the value above chance"})
    if any(r.get("algorithm_differs") is True for r in data):
        findings.append({"kind": "algorithm-differs",
                         "why": "different values build different algorithms, not only sizes"})
    return {"format": FORMAT, "findings": findings}


def oversight(profile):
    """Who designs the values, and how were they written."""
    p = profile or {}
    findings = []
    if p.get("self_modifying") is True:
        findings.append({"kind": "self-modified-values",
                         "why": "letting the agent revise its values narrows the spread"})
        if p.get("best_value_fell") is True or p.get("worst_value_rose") is True:
            findings.append({"kind": "self-modification-converges-to-middle"})
    if p.get("literature_derived") is True:
        findings.append({"kind": "literature-derived-values",
                         "why": "values distilled from the literature show no detectable gain"})
        if p.get("values_trend_cautious") is True:
            findings.append({"kind": "literature-trends-conservation",
                             "why": "the safest common insight is not the best disposition"})
    if p.get("reframed") is True and p.get("original_outperforms") is True:
        findings.append({"kind": "framing-matters",
                         "why": "the same disposition in ethical language scores below the original"})
    if p.get("model_tier") in ("small", "cheap"):
        findings.append({"kind": "cheaper-model-degrades",
                         "why": "the value advantage narrows or disappears on weaker models"})
    if p.get("manual_review") is not True:
        findings.append({"kind": "no-human-value-review",
                         "why": "human oversight is still the best value designer"})
    return {"format": FORMAT, "findings": findings}


def progress(rows):
    """Value-driven choices are embedded in the code later iterations inherit."""
    data = list(rows or ())
    findings = []
    if not data:
        return {"format": FORMAT, "findings": [{"kind": "no-progress"}]}
    spreads = [r.get("spread") for r in data if r.get("spread") is not None]
    if len(spreads) >= 2:
        if spreads[-1] > spreads[0]:
            findings.append({"kind": "values-compound",
                             "from": spreads[0], "to": spreads[-1],
                             "why": "choices encouraged by values become embedded in later code"})
        else:
            findings.append({"kind": "values-do-not-compound",
                             "from": spreads[0], "to": spreads[-1]})
    if any(r.get("open_ended") is True for r in data):
        findings.append({"kind": "open-ended-strengthens-effect",
                         "why": "freedom to replace algorithms gives values more influence"})
    if any(r.get("fixed_engine_spread") is not None for r in data):
        findings.append({"kind": "fixed-engine-narrows-effect",
                         "why": "a fixed engine leaves the value less to shape"})
    return {"format": FORMAT, "findings": findings}


def advise(profile):
    """Map a harness profile onto the paper's failure modes."""
    p = profile or {}
    have = {str(k) for k, v in p.items() if v}
    findings = []
    checks = (
        ("value_statement", "no-value-statement", "task-general guidance for choices the score leaves open"),
        ("fixes_values", "values-drift", "a value that changes within a run cannot be attributed"),
        ("opposite_control", "no-opposite", "each value needs its opposite to test against"),
        ("placebo_control", "no-placebo", "the length of the text is a confound"),
        ("measures_solution_shape", "score-only", "values change what is built, not only how well"),
        ("human_value_review", "agent-designed-values", "self-modification narrows the spread and converges"),
    )
    for key, kind, why in checks:
        if key not in have:
            findings.append({"kind": kind, "why": why})
    return {"format": FORMAT, "findings": findings}
