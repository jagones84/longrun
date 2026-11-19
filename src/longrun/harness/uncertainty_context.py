#!/usr/bin/env python3
"""Uncertainty context — say how sure the evidence is, not only what it says.

Source: arXiv:2611.24351, "Tell Me How Sure You Are" (round 147). Auxiliary
evidence is rarely equally reliable, and conventional prompting discards the
reliability the source already exposes
(`auxiliary_evidence_uncertainty_2611.24351.txt:16`, `:22`, `:42`). The paper
isolates the effect with a paired design: the evidence is held fixed and only
whether its uncertainty is communicated changes (`:89`, `:93`, `:195`).

  * **measured**: macro-F1 rises by up to 7.84 pp on CUB, 26.18 pp on SUN and
    9.10 pp on Derm7pt for LLMs, with smaller gains for VLMs (`:127`, `:280`).
  * **alignment matters**: true uncertainty beats omitting it by 11.71–26.60 pp
    and beats shuffled uncertainty by 14.02–19.53 pp (`:417`).
  * **uncertainty sanitises a mixed set**: adding lower-ranked attributes flips
    predictions from correct to incorrect less often when their scores are
    shown (13 → 3 and 16 → 6 flips) (`:379`).
  * **it predicts correctness**: upstream features reach AUROC 0.80 on SUN and
    0.636–0.648 on Derm7pt, but are near chance on CUB (`:448`, `:430`).
  * **a better decision is not a less uncertain model**: entropy often rises
    even when an incorrect decision becomes correct (`:482`, `:541`).
  * **honest negatives**: zero-shot classification only; one uncertainty
    representation per context; the effect is model- and prompt-dependent
    (`:508`, `:526`, `:1383`).

  * `paired(row)` — the paired macro-F1 delta in percentage points.
  * `alignment(rows)` — true against omitted and shuffled uncertainty.
  * `subset(rows)` — the gain across evidence budgets.
  * `flips(row)` — correct-to-incorrect transitions, with and without scores.
  * `correctness(rows)` — AUROC of upstream features on downstream correctness.
  * `entropy(rows)` — decision changes against the downstream entropy change.
  * `sensitivity(rows)` — whether the gain survives a prompt change.
  * `audit(record)` — the six misreadings the paper names.
  * `advise(profile)` — map a harness profile onto the paper's failure modes.

Pure: paired scores and arm rates in; deltas and verdicts out.
"""
from __future__ import annotations

FORMAT = "longrun-uncertainty-context/1"

DEFAULTS = {"alignment_gain": 0.05, "auroc_strong": 0.70,
            "auroc_weak": 0.55, "stable_share": 0.667}


def _num(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def paired(row):
    """The paired macro-F1 delta from communicating uncertainty."""
    r = row or {}
    aux = _num(r.get("aux"))
    aux_unc = _num(r.get("aux_unc"))
    if aux is None or aux_unc is None:
        return {"format": FORMAT, "verdict": "insufficient-input"}
    delta_pp = (aux_unc - aux) * 100.0
    if delta_pp > 0:
        verdict = "uncertainty-helps"
    elif delta_pp == 0:
        verdict = "no-gain"
    else:
        verdict = "hurts"
    return {"format": FORMAT, "delta_pp": delta_pp, "verdict": verdict}


def alignment(rows):
    """Correctly aligned uncertainty against omitted and shuffled."""
    out = []
    for row in rows or []:
        r = row or {}
        none = _num(r.get("none"))
        true = _num(r.get("true"))
        shuffled = _num(r.get("shuffled"))
        if None in (none, true, shuffled):
            continue
        out.append({"model": str(r.get("model") or ""),
                    "true_minus_none": (true - none) * 100.0,
                    "true_minus_shuffled": (true - shuffled) * 100.0})
    if not out:
        return {"format": FORMAT, "verdict": "no-measurements"}
    smallest = min(row["true_minus_shuffled"] for row in out)
    all_positive = all(row["true_minus_none"] > 0 for row in out)
    if all_positive and smallest / 100.0 >= DEFAULTS["alignment_gain"]:
        verdict = "alignment-required"
    elif any(row["true_minus_none"] > 0 for row in out):
        verdict = "alignment-partial"
    else:
        verdict = "alignment-inert"
    return {"format": FORMAT, "rows": out, "smallest_margin_pp": smallest,
            "verdict": verdict}


def subset(rows):
    """The uncertainty gain across evidence budgets."""
    by_model = {}
    for row in rows or []:
        r = row or {}
        model = str(r.get("model") or "")
        k = _num(r.get("k"))
        delta = _num(r.get("delta_pp"))
        if model and k is not None and delta is not None:
            by_model.setdefault(model, []).append((int(k), delta))
    if not by_model:
        return {"format": FORMAT, "verdict": "no-measurements"}
    trends = {}
    for model, values in by_model.items():
        values.sort()
        trends[model] = {"smallest_k": values[0][0], "smallest_delta": values[0][1],
                         "largest_k": values[-1][0], "largest_delta": values[-1][1]}
    grows = sum(1 for t in trends.values() if t["largest_delta"] > t["smallest_delta"])
    best = max((t["largest_delta"], model) for model, t in trends.items())
    if grows * 2 > len(trends):
        verdict = "gain-grows-with-k"
    elif any(t["largest_delta"] > 0 for t in trends.values()):
        verdict = "gain-model-dependent"
    else:
        verdict = "no-gain"
    return {"format": FORMAT, "trends": trends, "best_model": best[1],
            "verdict": verdict}


def flips(row):
    """Correct-to-incorrect transitions with and without the scores."""
    r = row or {}
    aux = _num(r.get("aux_flips"))
    aux_unc = _num(r.get("aux_unc_flips"))
    if aux is None or aux_unc is None:
        return {"format": FORMAT, "verdict": "insufficient-input"}
    if aux <= 0:
        return {"format": FORMAT, "verdict": "no-flips-to-reduce"}
    reduction = 1.0 - aux_unc / aux
    return {"format": FORMAT, "reduction": reduction, "aux_flips": aux,
            "aux_unc_flips": aux_unc,
            "verdict": "uncertainty-sanitizes" if reduction > 0
            else "no-sanitising-effect"}


def correctness(rows):
    """Whether upstream uncertainty discriminates downstream correctness."""
    out = []
    for row in rows or []:
        r = row or {}
        auroc = _num(r.get("auroc"))
        if auroc is None:
            continue
        out.append({"model": str(r.get("model") or ""),
                    "features": str(r.get("features") or ""), "auroc": auroc})
    if not out:
        return {"format": FORMAT, "verdict": "no-probes"}
    best = max(out, key=lambda r: (r["auroc"], r["model"], r["features"]))
    if best["auroc"] >= DEFAULTS["auroc_strong"]:
        verdict = "uncertainty-predicts-correctness"
    elif best["auroc"] >= DEFAULTS["auroc_weak"]:
        verdict = "weak-signal"
    else:
        verdict = "chance"
    return {"format": FORMAT, "rows": out, "best": best, "verdict": verdict}


def entropy(rows):
    """A corrected decision does not require a less uncertain model."""
    improvements, raised = 0, 0
    for row in rows or []:
        r = row or {}
        transition = str(r.get("transition") or "")
        delta_h = _num(r.get("delta_h"))
        if transition != "incorrect->correct" or delta_h is None:
            continue
        improvements += 1
        if delta_h >= 0:
            raised += 1
    if not improvements:
        return {"format": FORMAT, "verdict": "no-improvements"}
    share = raised / improvements
    return {"format": FORMAT, "improvements": improvements,
            "entropy_not_lower": share,
            "verdict": ("decisions-improve-without-entropy-drop"
                        if share >= 0.5 else "entropy-tracks-improvement")}


def sensitivity(rows):
    """Whether the gain survives a change of the output instruction."""
    gains = []
    for row in rows or []:
        r = row or {}
        gain = _num(r.get("gain_pp"))
        if gain is not None:
            gains.append(gain)
    if not gains:
        return {"format": FORMAT, "verdict": "no-measurements"}
    positive = sum(1 for g in gains if g > 0) / len(gains)
    return {"format": FORMAT, "combinations": len(gains),
            "positive_share": positive, "min_pp": min(gains),
            "max_pp": max(gains),
            "verdict": "gain-direction-stable"
            if positive >= DEFAULTS["stable_share"] else "prompt-dependent"}


def audit(record):
    """The six misreadings the paper names, each as a finding."""
    r = record or {}
    findings = []
    if r.get("aggregate_only") is True:
        findings.append({"kind": "aggregate-only",
                         "why": "the effect is model- and prompt-dependent"})
    if r.get("no_alignment_control") is True:
        findings.append({"kind": "no-alignment-control",
                         "why": "shuffled uncertainty tests whether alignment matters"})
    if r.get("calibrated_assumption") is True:
        findings.append({"kind": "calibrated-assumption",
                         "why": "the paper does not assume the sources are calibrated"})
    if r.get("single_source") is True:
        findings.append({"kind": "single-source",
                         "why": "human, general-model and task-specific signals differ"})
    if r.get("no_paired_design") is True:
        findings.append({"kind": "no-paired-design",
                         "why": "evidence must be held fixed while uncertainty varies"})
    if r.get("entropy_as_correctness") is True:
        findings.append({"kind": "entropy-as-correctness",
                         "why": "lower downstream entropy is not a better decision"})
    if not findings:
        findings.append({"kind": "audit-conditions-met"})
    return {"format": FORMAT, "findings": findings}


def advise(profile):
    """Map a harness profile onto the paper's failure modes."""
    p = profile or {}
    have = {str(k) for k, v in p.items() if v}
    checks = (
        ("communicates_source_uncertainty", "passes_evidence_alone",
         "the source already exposes a reliability signal"),
        ("holds_the_evidence_fixed", "changes_evidence_and_uncertainty",
         "a paired design is the only way to isolate the effect"),
        ("keeps_the_source_representation", "normalises_every_scale",
         "semantics differ across human, matching and classifier signals"),
        ("controls_the_alignment", "trusts_any_score",
         "shuffled scores show whether association is what helps"),
        ("reports_paired_deltas", "reports_aggregate_scores",
         "the effect is a paired change in percentage points"),
        ("probes_downstream_correctness", "assumes_uncertainty_is_noise",
         "upstream uncertainty predicts downstream correctness"),
        ("reports_downstream_entropy", "treats_entropy_as_accuracy",
         "a corrected decision can raise the model's entropy"),
    )
    findings = []
    for key, kind, why in checks:
        if key not in have:
            findings.append({"kind": kind, "why": why})
    return {"format": FORMAT, "findings": findings}
