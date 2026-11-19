#!/usr/bin/env python3
"""Selective replay — an agent that picks the analysis must pay for picking it.

Source: arXiv:2611.23174, "Inference After Coding Agents" (round 136). A coding
agent that inspects the data before choosing a model makes the reported p-value
invalid conditional on its own selection: on simulated data with zero effects the
tested agents report p <= 0.05 in 54-98% of runs
(`inference_after_coding_agents_2611.23174.md:28`, `:56`).

  * **the selection multiplier is the whole correction**: for the observed
    p-value `u`, `lambda(u) = Pr(Q=q | p<=u) / Pr(Q=q)`, and
    `p_sel = u * lambda(u) = u a1 / (u a1 + (1-u) a0)` (`:158`, `:188`).
  * **replay estimates the two rates**: subsamples are split into a tail
    (`p<=u`) and a body, and the agent is replayed once in each (`:198`, `:204`).
  * **subsampling, not the bootstrap**: a bootstrap sample repeats units that
    could not occur in a fresh dataset, so the total-variation gap is the
    probability of a duplicate (`:276`, `:284`).
  * **the replay budget is allocated**: Neyman allocation proportional to
    `sqrt(a_s(1-a_s))`, with a floor in each stratum (`:246`, `:250`).
  * **self-correction is not a substitute**: the family the agent corrects over
    is itself data-dependent (`:785`, `:787`).
  * **measured**: reported false rejections of 98.0% / 97.1% fall to 5.1% / 5.9%
    after the replay correction, with median multipliers of 10-19 (`:676`,
    `:685`).

  * `multiplier(u, a1, a0)` — the selection multiplier at a p-value.
  * `corrected(u, tail, body)` — the selective p-value from replay counts.
  * `gate(corrected, alpha)` — the corrected decision.
  * `allocation(total, a1, a0)` — Neyman split with a floor.
  * `resampling(m, n)` — why subsampling and not the bootstrap.
  * `audit(run)` — time validity, source isolation, run invariance.
  * `self_correction(row)` — why the agent's own correction does not bind.
  * `detect(rows)` — reported vs corrected false-rejection rates.
  * `advise(profile)` — map a harness profile onto the paper's failure modes.

Pure: replay counts and run records in; corrected p-values and findings out.
"""
from __future__ import annotations

import math

FORMAT = "longrun-selective-replay/1"


def _num(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def multiplier(u, a1, a0):
    """Relative probability of selecting the analysis in the favorable tail."""
    p = _num(u)
    t = _num(a1)
    b = _num(a0)
    if p is None or t is None or b is None or not 0 < p <= 1 or t < 0 or b < 0:
        return None
    denom = p * t + (1.0 - p) * b
    if denom <= 0:
        return None
    return t / denom


def corrected(u, tail_matches, tail_replays, body_matches, body_replays):
    """The replay-corrected p-value, or unavailable with the paper's convention."""
    p = _num(u)
    t_n = _num(tail_replays)
    b_n = _num(body_replays)
    t_k = _num(tail_matches)
    b_k = _num(body_matches)
    if p is None or not 0 < p <= 1:
        return {"format": FORMAT, "findings": [{"kind": "invalid-p-value", "p": u}]}
    if None in (t_n, b_n, t_k, b_k) or t_n < 1 or b_n < 1:
        return {"format": FORMAT, "corrected": 1.0, "multiplier": None, "available": False,
                "findings": [{"kind": "correction-unavailable",
                              "why": "both strata need at least one replay"}]}
    if t_k > t_n or b_k > b_n:
        return {"format": FORMAT, "findings": [{"kind": "impossible-counts",
                                                "tail": [t_k, t_n], "body": [b_k, b_n]}]}
    a1 = t_k / t_n
    a0 = b_k / b_n
    lam = multiplier(p, a1, a0)
    if lam is None:
        return {"format": FORMAT, "corrected": 1.0, "multiplier": None, "available": False,
                "findings": [{"kind": "correction-unavailable",
                              "why": "the stratified denominator is zero"}]}
    value = min(1.0, p * lam)
    findings = []
    if lam > 1.0:
        findings.append({"kind": "selected-analysis", "multiplier": round(lam, 4),
                         "why": "the agent reselects this analysis more often when it looks favorable"})
    elif lam == 1.0:
        findings.append({"kind": "no-selection-detected"})
    else:
        findings.append({"kind": "negatively-selected", "multiplier": round(lam, 4)})
    return {"format": FORMAT, "reported": p, "corrected": round(value, 6),
            "multiplier": round(lam, 4), "available": True,
            "tail_rate": round(a1, 4), "body_rate": round(a0, 4), "findings": findings}


def gate(value, alpha=0.05):
    """The replay test rejects only when the corrected p-value clears alpha."""
    p = _num(value)
    if p is None or not 0 < alpha < 1:
        return {"format": FORMAT, "findings": [{"kind": "invalid-input"}]}
    reject = p <= alpha
    return {"format": FORMAT, "reject": reject, "corrected": p, "alpha": alpha,
            "findings": [{"kind": "reject" if reject else "do-not-reject"}]}


def allocation(total, a1, a0, floor=1):
    """Neyman allocation between the tail and body, with a floor in each."""
    n = int(total or 0)
    t = _num(a1)
    b = _num(a0)
    if n < 2 or t is None or b is None or not 0 <= t <= 1 or not 0 <= b <= 1:
        return {"format": FORMAT, "findings": [{"kind": "invalid-budget"}]}
    s1 = math.sqrt(max(t * (1.0 - t), 0.0))
    s0 = math.sqrt(max(b * (1.0 - b), 0.0))
    if s1 + s0 <= 0:
        half = n // 2
        return {"format": FORMAT, "tail": half, "body": n - half,
                "findings": [{"kind": "degenerate-allocation",
                              "why": "both pilot rates are 0 or 1, so the split is arbitrary"}]}
    tail = int(round(n * s1 / (s1 + s0)))
    f = max(0, int(floor))
    tail = min(max(tail, f), n - f)
    findings = []
    if tail < f or n - tail < f:
        findings.append({"kind": "budget-below-floors"})
    else:
        findings.append({"kind": "neyman-allocation"})
    return {"format": FORMAT, "tail": tail, "body": n - tail, "findings": findings}


def resampling(m, n, replacement=False, max_fraction=0.2):
    """Subsampling keeps the fresh-data law; the bootstrap cannot."""
    sub = _num(m)
    size = _num(n)
    if sub is None or size is None or sub <= 0 or size <= 0 or sub > size:
        return {"format": FORMAT, "findings": [{"kind": "invalid-subsample"}]}
    fraction = sub / size
    findings = []
    if replacement:
        distinct = 1.0
        for i in range(int(sub)):
            distinct *= (size - i) / size
        findings.append({"kind": "bootstrap-duplicates", "fraction": round(1.0 - distinct, 6),
                         "why": "a repeated unit is a dataset a fresh draw could not produce"})
    if fraction > max_fraction:
        findings.append({"kind": "subsample-too-large", "fraction": round(fraction, 4),
                         "why": "the conditional distortion is only bounded as m/n vanishes"})
    if not findings:
        findings.append({"kind": "valid-subsampling", "fraction": round(fraction, 4)})
    return {"format": FORMAT, "fraction": round(fraction, 4), "findings": findings}


def audit(run):
    """The three requirements: time validity, source isolation, run invariance."""
    r = run or {}
    findings = []
    for item in r.get("evidence") or ():
        retrieved = _num(item.get("retrieved_at"))
        state = _num(item.get("state_time"))
        if retrieved is None:
            findings.append({"kind": "missing-retrieval-time", "id": item.get("id")})
        elif state is not None and retrieved > state:
            findings.append({"kind": "item-not-knowable", "id": item.get("id"),
                             "retrieved_at": retrieved, "state_time": state})
    if r.get("same_query_plan") is not True:
        findings.append({"kind": "source-policy-differs",
                         "why": "providers are compared only under one initial plan and follow-up rule"})
    if r.get("same_evidence") is not True:
        findings.append({"kind": "evidence-not-fixed",
                         "why": "a model comparison needs the same evidence in both arms"})
    if r.get("replay_offline") is not True:
        findings.append({"kind": "replay-hits-live-search",
                         "why": "a replay that searches again is not a replay"})
    if not findings:
        findings.append({"kind": "replay-audit-clean"})
    return {"format": FORMAT, "findings": findings}


def self_correction(row):
    """Why a multiplicity correction the agent applies to itself does not bind."""
    r = row or {}
    findings = []
    declared = int(r.get("declared_family") or 0)
    observed = int(r.get("observed_analyses") or 0)
    if r.get("family_fixed_before_data") is not True:
        findings.append({"kind": "family-not-predeclared",
                         "why": "the tests counted are the ones this dataset made it run"})
    if declared and observed > declared:
        findings.append({"kind": "family-covers-observed-only",
                         "declared": declared, "observed": observed})
    if r.get("corrected_value_is_headline") is not True:
        findings.append({"kind": "correction-not-on-headline",
                         "why": "the returned finding is the uncorrected value"})
    if r.get("correction_lost_effect") is True:
        findings.append({"kind": "correction-costs-power"})
    if not findings:
        findings.append({"kind": "self-correction-consistent"})
    return {"format": FORMAT, "findings": findings}


def detect(rows, alpha=0.05):
    """Aggregate the reported and corrected false-rejection rates."""
    data = [r for r in (rows or ()) if _num(r.get("reported")) is not None]
    if not data:
        return {"format": FORMAT, "findings": [{"kind": "no-runs"}]}
    reported = sum(1 for r in data if _num(r["reported"]) <= alpha) / len(data)
    with_corr = [r for r in data if _num(r.get("corrected")) is not None]
    corrected = (sum(1 for r in with_corr if _num(r["corrected"]) <= alpha) / len(with_corr)
                 if with_corr else None)
    findings = []
    if corrected is not None and reported - corrected >= 0.2:
        findings.append({"kind": "selection-detected",
                         "reported": round(reported, 4), "corrected": round(corrected, 4)})
    if with_corr and len(with_corr) < len(data):
        findings.append({"kind": "correction-missing", "runs": len(data) - len(with_corr)})
    if not findings:
        findings.append({"kind": "no-selection-detected"})
    return {"format": FORMAT, "runs": len(data), "reported_rate": round(reported, 4),
            "corrected_rate": None if corrected is None else round(corrected, 4),
            "findings": findings}


def advise(profile):
    """Map a harness profile onto the paper's failure modes."""
    p = profile or {}
    have = {str(key) for key, value in p.items() if value}
    findings = []
    checks = (
        ("records_selection", "unrecorded-selection", "log the analysis the agent chose"),
        ("replays_agent", "no-replay", "a black-box selection must be replayed, not modelled"),
        ("replays_on_subsamples", "bootstrap-resampling", "subsample without replacement"),
        ("estimates_both_strata", "single-stratum", "tail and body are both needed"),
        ("allocates_replays", "equal-spend", "Neyman allocation buys the same precision cheaper"),
        ("reports_corrected_p", "uncorrected-p", "a selected p-value overstates the evidence"),
        ("checks_self_correction", "trusts-self-correction", "the agent's family is data-dependent"),
        ("fixes_the_evidence", "mixed-evidence", "both arms must read the same evidence"),
    )
    for key, kind, why in checks:
        if key not in have:
            findings.append({"kind": kind, "why": why})
    return {"format": FORMAT, "findings": findings}
