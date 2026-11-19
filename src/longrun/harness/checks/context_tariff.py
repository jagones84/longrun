#!/usr/bin/env python3
"""Context tariff — what a retained token is charged, and which bound applies.

Source: arXiv:2611.24071, "Measuring and Charging for Retained Context in
Long-Context LLM Services" (round 153). A multi-turn request repeats a prefix,
and the price of that prefix is only weakly tied to its contribution
(`retained_context_2611.24071.txt:17`, `:41`).

  * **three bounds, not one**: the lifetime charge of one token converges to
    `Ph/(1-r)`, a request's historical part to `Ph*Delta/(1-r)`, and a session's
    total grows linearly and never converges (`:140`, `:157`, `:167`).
  * **content beats distance**: replacing the answer block costs 0.222 quality
    against 0.058 for the largest positional contrast, and no decay family beats
    a relevance-only baseline on held-out RMSE (`:299`, `:306`, `:309`).
  * **a cache hit is two orders of magnitude cheaper**: $8.46e-4 cold against
    $3.56e-6 warm at 64K, 237x in cost and 226x in latency (`:370`, `:372`).
  * **coverage binds only on a cold re-send**: the ceiling is ~2-4e4 tokens at
    h = 0, rising to ~1e5 at h = 0.8 and r = 0.90, and 64K needs h >= 0.67
    (`:384`, `:386`).
  * **the robust gain is the tail**: P99 falls 30.9-42.0% and the coefficient of
    variation 40.5-43.5%, while the median rises 58.9% (`:474`, `:486`).
  * **an agent workload does not benefit automatically**: weighting is 96.8%
    dearer once 5,000 persistent tool tokens accumulate (`:527`).

  * `charge(record)` — the weighted per-request charge.
  * `lifetime(record)` — the token, request and session expressions.
  * `coverage(record)` — the historical charge against a cold re-send.
  * `bounds(record)` — the three distinctions side by side.
  * `quality(rows)` — decay families against a relevance-only baseline.
  * `fairness(record)` — tail, median and spread as one verdict.
  * `audit(record)` — the six misreadings the paper names.
  * `advise(profile)` — map a harness profile onto the paper's failure modes.

Pure: rates, token counts and measured deltas in; charges and verdicts out.
"""
from __future__ import annotations

import math

FORMAT = "longrun-context-tariff/1"

DECAY_FAMILIES = ("relevance", "piecewise", "power", "hyperbolic", "geometric")


def _num(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def charge(record):
    """`Pin*I + Ph*sum(A*w) + Pout*O + Preason*R`, geometric in age."""
    r = record or {}
    pin = _num(r.get("pin"))
    ph = _num(r.get("ph"))
    pout = _num(r.get("pout"))
    preason = _num(r.get("preason")) or 0.0
    new_input = _num(r.get("new_input")) or 0.0
    output = _num(r.get("output")) or 0.0
    reasoning = _num(r.get("reasoning")) or 0.0
    decay = _num(r.get("r"))
    if None in (pin, ph, pout, decay):
        return {"format": FORMAT, "verdict": "insufficient-input"}
    if not 0 <= decay <= 1:
        return {"format": FORMAT, "verdict": "r-out-of-range"}
    historical = 0.0
    for block in r.get("blocks") or []:
        b = block or {}
        tokens = _num(b.get("tokens")) or 0.0
        age = int(b.get("age") or 0)
        historical += tokens * (decay ** age)
    total = (pin * new_input + ph * historical + pout * output
             + preason * reasoning)
    return {"format": FORMAT, "historical_tokens": historical,
            "historical_charge": ph * historical, "total": total,
            "historical_share": (ph * historical / total) if total else None,
            "verdict": "charge-computed"}


def lifetime(record):
    """The token bound, the request bound and the unbounded session total."""
    r = record or {}
    decay = _num(r.get("r"))
    ph = _num(r.get("ph"))
    rounds = int(r.get("rounds") or 0)
    delta = _num(r.get("delta")) or 0.0
    if decay is None or ph is None or not 0 <= decay < 1:
        return {"format": FORMAT, "verdict": "insufficient-input"}
    token = ph * (1 - decay ** (rounds + 1)) / (1 - decay)
    token_limit = ph / (1 - decay)
    request = ph * delta * (1 - decay ** max(rounds - 1, 0)) / (1 - decay)
    request_limit = ph * delta / (1 - decay)
    session = (ph * delta / (1 - decay)) * (
        rounds - (1 - decay ** rounds) / (1 - decay))
    return {"format": FORMAT, "token_charge": token, "token_limit": token_limit,
            "request_charge": request, "request_limit": request_limit,
            "session_total": session, "session_growth": "linear",
            "verdict": "bounds-computed"}


def coverage(record):
    """The historical charge against the expected cost of a cold re-send."""
    r = record or {}
    decay = _num(r.get("r"))
    ph = _num(r.get("ph"))
    delta = _num(r.get("delta"))
    cold_slope = _num(r.get("cold_slope"))
    window = _num(r.get("window"))
    hit = _num(r.get("hit"))
    if None in (decay, ph, delta, cold_slope, window, hit):
        return {"format": FORMAT, "verdict": "insufficient-input"}
    if not 0 <= hit <= 1 or not 0 <= decay < 1 or window <= 0:
        return {"format": FORMAT, "verdict": "out-of-range"}
    historical = ph * delta / (1 - decay)
    cold = cold_slope * window
    resend = cold * (1 - hit)
    ratio = historical / resend if resend else None
    break_even = 1 - historical / cold if cold else None
    return {"format": FORMAT, "historical": historical, "resend": resend,
            "ratio": ratio, "hit": hit,
            "break_even_hit": max(0.0, break_even) if break_even is not None else None,
            "verdict": "covered" if ratio is not None and ratio >= 1
            else "coverage-breach"}


def bounds(record):
    """The three distinctions, each with the quantity it constrains."""
    r = record or {}
    decay = _num(r.get("r"))
    if decay is None or not 0 <= decay < 1:
        return {"format": FORMAT, "verdict": "insufficient-input"}
    return {"format": FORMAT,
            "token": {"bound": 1 / (1 - decay), "unit": "one token, all appearances"},
            "request": {"bound": 1 / (1 - decay), "unit": "one request, stable arrivals"},
            "session": {"bound": None, "unit": "all requests, grows linearly"},
            "verdict": "three-distinctions"}


def quality(rows):
    """Held-out RMSE per decay family, against the relevance-only baseline."""
    scores = {}
    for row in rows or []:
        r = row or {}
        name = str(r.get("family") or "")
        rmse = _num(r.get("rmse"))
        if name in DECAY_FAMILIES and rmse is not None:
            scores[name] = rmse
    if "relevance" not in scores or len(scores) < 2:
        return {"format": FORMAT, "verdict": "insufficient-input"}
    base = scores["relevance"]
    worse = [name for name in ("power", "hyperbolic", "geometric")
             if name in scores and scores[name] > base]
    return {"format": FORMAT, "scores": scores, "baseline": base,
            "worse_than_relevance": worse,
            "verdict": "relevance-dominates" if len(worse) == 3
            else "distance-adds-signal"}


def fairness(record):
    """What the tariff does to the tail, the median and the spread."""
    r = record or {}
    p99 = _num(r.get("p99"))
    cv = _num(r.get("cv"))
    median = _num(r.get("median"))
    mean = _num(r.get("mean"))
    if None in (p99, cv, median):
        return {"format": FORMAT, "verdict": "insufficient-input"}
    if p99 > 0 or median < 0:
        return {"format": FORMAT, "verdict": "unexpected-sign"}
    tail = p99 <= -10 and cv <= -10
    middle = median > 0
    return {"format": FORMAT, "p99": p99, "cv": cv, "median": median,
            "mean": mean, "tail_shrinks": tail, "median_rises": middle,
            "verdict": "tail-for-median" if tail and middle
            else "uniform-or-worse"}


def audit(record):
    """The six misreadings the paper names, each as a finding."""
    r = record or {}
    findings = []
    if r.get("distance_is_value") is True:
        findings.append({"kind": "distance-is-value",
                         "why": "age is a weak, non-monotone predictor of contribution"})
    if r.get("session_total_bounded") is True:
        findings.append({"kind": "session-total-bounded",
                         "why": "only the token and request charges converge"})
    if r.get("warm_cost_scales") is True:
        findings.append({"kind": "warm-cost-scales",
                         "why": "warm cost is nearly flat in context length"})
    if r.get("hit_rate_is_measured") is True:
        findings.append({"kind": "hit-rate-is-measured",
                         "why": "h is an input to coverage, not a constant"})
    if r.get("mean_falls_under_every_schedule") is True:
        findings.append({"kind": "mean-falls-under-every-schedule",
                         "why": "the mean rises under two of three schedules"})
    if r.get("agent_workload_benefits") is True:
        findings.append({"kind": "agent-workload-benefits",
                         "why": "persistent tool tokens are 96.8% dearer"})
    if not findings:
        findings.append({"kind": "audit-conditions-met"})
    return {"format": FORMAT, "findings": findings, "verdict": "audit-complete"}


def advise(profile):
    """Map a harness profile onto the paper's failure modes."""
    p = profile or {}
    have = {str(k) for k, v in p.items() if v}
    checks = (
        ("separates_persistent_from_ephemeral", "charges_reasoning_as_history",
         "reasoning is charged only in the current round"),
        ("measures_the_hit_rate", "assumes_a_cache_hit",
         "coverage binds exactly when h is zero"),
        ("prices_per_round_not_per_token", "quotes_a_token_price",
         "the session total grows even when the token charge converges"),
        ("reports_the_tail_beside_the_mean", "reports_a_mean_only",
         "the robust gain is a smaller upper tail"),
        ("checks_the_quality_side", "assumes_cheaper_is_free",
         "a quality loss can break the user condition"),
        ("keeps_tool_state_undiscounted", "discounts_tool_state_by_age",
         "early observations are irreplaceable"),
    )
    findings = []
    for key, kind, why in checks:
        if key not in have:
            findings.append({"kind": kind, "why": why})
    return {"format": FORMAT, "findings": findings}
