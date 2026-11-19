#!/usr/bin/env python3
"""Orchestration credit — interactions between decisions, and certified updates.

Source: arXiv:2611.07495, "Learning Multi-Agent Orchestration: Higher-Order
Interactions in Policy Improvement" (round 154). The per-decision advantage treats
every other decision as fixed, but an orchestrator's earlier choice changes what a
later choice can read, so a joint change can help when neither single change does
(`orchestration_credit_2611.07495.txt:65-90`, `:112-130`).

  * **the expansion is exact**: J(π′) − J(π) = Σ_m J(m) with
    J(m) = E[Σ_{t1<…<tm} (ρ_{t1}−1)…(ρ_{tm}−1)·A_{tm}] (`:288-301`).
  * **the first-order term is the existing objective**, and the interaction term
    carries the curvature it misses (`:308-315`).
  * **the remainder is bounded by visit counts**: with β = (K+1)η/2,
    ϵ(η) = Ḡ Σ_{m≥3}^{K+1} C(K+1,m)(η/2)^m (`:328-340`, `:407-416`).
  * **an update is accepted only with a positive lower confidence bound** on fresh
    trajectories, and the larger of the truncated and importance-sampling bounds
    wins (`:445-513`).
  * **complementary decisions are the trap**: at p = 1/3 a single move loses while
    the joint move gains 4s²/27, so a first-order score stays put (`:2140-2200`).

  * `orders(record)` — J(1), J(2), the higher orders and their exact sum.
  * `bound(K, eta, gbar)` — β, ϵ(η) and the first-order truncation error.
  * `z2(record)` — µ1, µ2 and the interaction-aware statistic.
  * `certify(record)` — empirical-Bernstein radii, the max bound, accept/retain.
  * `select(candidates)` — the largest positive certificate; otherwise keep π.
  * `detect(record)` — the sample size that makes improvement detectable.
  * `leaps(record)` — paired returns and their certificate.
  * `complementarity(record)` — the first-order stationary point and its joint gain.
  * `controlled(record)` — the paper's three toy gains.
  * `audit(record)` / `advise(profile)` — misreadings and harness mapping.

Pure: ratios, returns and sample statistics in; boundaries and verdicts out.
"""
from __future__ import annotations

import math

FORMAT = "longrun-orchestration-credit/1"


def _num(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _mean(values):
    return sum(values) / len(values) if values else None


def _sd(values):
    n = len(values)
    if n < 2:
        return None
    m = _mean(values)
    return math.sqrt(sum((v - m) ** 2 for v in values) / (n - 1))


def _choose(n, k):
    return math.comb(int(n), int(k))


def orders(record):
    """The exact interaction expansion, order by order."""
    r = record or {}
    decisions = r.get("decisions") or []
    baseline = _num(r.get("baseline") or 0.0) or 0.0
    deltas = []
    returns = []
    for d in decisions:
        item = d or {}
        rho = _num(item.get("rho"))
        ret = _num(item.get("return"))
        if rho is None or ret is None:
            return {"format": FORMAT, "verdict": "insufficient-input"}
        deltas.append(rho - 1.0)
        returns.append(ret - baseline)
    if not deltas:
        return {"format": FORMAT, "verdict": "no-decisions"}
    H = len(deltas)
    terms = []
    for m in range(1, H + 1):
        total = 0.0
        for combo in _combinations(H, m):
            prod = 1.0
            for t in combo:
                prod *= deltas[t]
            total += prod * returns[combo[-1]]
        terms.append(total)
    exact_sum = sum(terms)
    out = {"format": FORMAT, "orders": terms, "order1": terms[0],
           "order2": terms[1] if H > 1 else 0.0, "sum": exact_sum,
           "steps": H, "verdict": "expanded"}
    truth = _num(r.get("true_gain"))
    if truth is not None:
        out["true_gain"] = truth
        out["exact"] = abs(exact_sum - truth) <= 1e-9
        out["verdict"] = "exact" if out["exact"] else "expansion-mismatch"
    return out


def _combinations(n, k):
    combo = list(range(k))
    while True:
        yield tuple(combo)
        i = k - 1
        while i >= 0 and combo[i] == i + n - k:
            i -= 1
        if i < 0:
            return
        combo[i] += 1
        for j in range(i + 1, k):
            combo[j] = combo[j - 1] + 1


def bound(K, eta, gbar):
    """The visit-count remainder: β and ϵ(η), plus the first-order tail."""
    calls = int(_num(K) or 0)
    step = _num(eta)
    g = _num(gbar)
    if calls < 0 or step is None or g is None:
        return {"format": FORMAT, "verdict": "insufficient-input"}
    beta = (calls + 1) * step / 2.0
    epsilon = sum(_choose(calls + 1, m) * (step / 2.0) ** m
                  for m in range(3, calls + 2))
    epsilon *= g
    first_order = g * (math.exp(beta) - 1 - beta - beta * beta / 2.0)
    return {"format": FORMAT, "beta": beta, "epsilon": epsilon,
            "first_order_tail": first_order,
            "overlap": 1.0 + step, "verdict": "bounded"}


def z2(record):
    """µ1, µ2 and Z2 = η·µ1 + η²·µ2, with its certified lower bound."""
    r = record or {}
    decisions = r.get("decisions") or []
    baseline = _num(r.get("baseline") or 0.0) or 0.0
    eta = _num(r.get("eta"))
    if eta is None or eta < 0 or eta > 1:
        return {"format": FORMAT, "verdict": "insufficient-input"}
    u = []
    returns = []
    for d in decisions:
        item = d or {}
        rho = _num(item.get("rho"))
        ret = _num(item.get("return"))
        if rho is None or ret is None:
            return {"format": FORMAT, "verdict": "insufficient-input"}
        u.append((rho - 1.0) / eta if eta else 0.0)
        returns.append(ret - baseline)
    mu1 = sum(u[t] * returns[t] for t in range(len(u)))
    mu2 = sum(u[t1] * u[t2] * returns[t2]
              for t1 in range(len(u)) for t2 in range(t1 + 1, len(u)))
    statistic = eta * mu1 + eta * eta * mu2
    return {"format": FORMAT, "mu1": mu1, "mu2": mu2, "eta": eta,
            "z2": statistic, "verdict": "scored"}


def _bernstein(values, bound_value, delta, candidates):
    n = len(values)
    if n < 2:
        return None
    sd = _sd(values)
    if sd is None:
        return None
    radius = math.sqrt(2.0 * math.log(8.0 * candidates / delta) / n)
    extra = 14.0 * bound_value * math.log(8.0 * candidates / delta) / (3.0 * (n - 1))
    return {"mean": _mean(values), "sd": sd,
            "radius": sd * radius + extra}


def certify(record):
    """Two valid lower bounds; the larger one decides, and only if positive."""
    r = record or {}
    eta = _num(r.get("eta"))
    K = int(_num(r.get("K") or 0))
    gbar = _num(r.get("gbar"))
    delta = _num(r.get("delta") or 0.05)
    steps = _num(r.get("steps") or 0)
    count = int(_num(r.get("candidates") or 1))
    z2_samples = [_num(v) for v in (r.get("z2_samples") or [])]
    is_samples = [_num(v) for v in (r.get("is_samples") or [])]
    if eta is None or gbar is None:
        return {"format": FORMAT, "verdict": "insufficient-input"}
    b = bound(K, eta, gbar)
    if b.get("epsilon") is None:
        return {"format": FORMAT, "verdict": "insufficient-input"}
    baseline = abs(_num(r.get("baseline") or 0.0) or 0.0)
    b2 = (gbar + baseline) * ((K + 1) * eta + _choose(K + 1, 2) * eta * eta)
    bis = (gbar + baseline) * ((1 + eta) ** (K + 1) - 1)
    truncated = _bernstein([v for v in z2_samples if v is not None],
                           b2, delta, count)
    if truncated is None:
        return {"format": FORMAT, "verdict": "too-few-samples"}
    l2 = truncated["mean"] - truncated["radius"] - b["epsilon"]
    lis = None
    importance = _bernstein([v for v in is_samples if v is not None],
                            bis, delta, count)
    if importance is not None:
        lis = importance["mean"] - importance["radius"]
    lower = l2 if lis is None else max(l2, lis)
    return {"format": FORMAT, "epsilon": b["epsilon"], "beta": b["beta"],
            "b2": b2, "bis": bis, "lower_truncated": l2,
            "lower_is": lis, "lower": lower,
            "decision": "accept" if lower > 0 else "retain",
            "verdict": "certified"}


def select(candidates):
    """Deploy the largest positive certificate; otherwise keep the reference."""
    rows = []
    for item in candidates or []:
        c = item or {}
        lower = _num(c.get("lower"))
        if lower is None:
            continue
        rows.append({"name": c.get("name"), "lower": lower})
    if not rows:
        return {"format": FORMAT, "verdict": "no-candidates"}
    top = max(rows, key=lambda row: row["lower"])
    if top["lower"] <= 0:
        return {"format": FORMAT, "selected": "reference", "lower": 0.0,
                "verdict": "retained"}
    return {"format": FORMAT, "selected": top["name"], "lower": top["lower"],
            "verdict": "updated"}


def detect(record):
    """The validation size at which a positive gain is detected."""
    r = record or {}
    bis = _num(r.get("bis"))
    delta = _num(r.get("delta") or 0.05)
    candidates = _num(r.get("candidates") or 1)
    gain = _num(r.get("gain"))
    if bis is None or gain is None or gain <= 0:
        return {"format": FORMAT, "verdict": "insufficient-input"}
    required = 256.0 * bis * bis * math.log(8.0 * candidates / delta) / (gain * gain)
    return {"format": FORMAT, "n_minus_one": required, "n_required": required + 1,
            "detectable": int(_num(r.get("n") or 0)) - 1 > required,
            "verdict": "sized"}


def leaps(record):
    """A leap is certified on paired returns from its own trajectories."""
    r = record or {}
    gains = [_num(v) for v in (r.get("paired") or [])]
    gains = [g for g in gains if g is not None]
    delta = _num(r.get("delta") or 0.05)
    gbar = _num(r.get("gbar") or 1.0)
    count = int(_num(r.get("candidates") or 1))
    stats = _bernstein(gains, 2.0 * gbar, delta, 4 * count)
    if stats is None:
        return {"format": FORMAT, "verdict": "too-few-pairs"}
    lower = stats["mean"] - stats["radius"]
    return {"format": FORMAT, "mean": stats["mean"], "radius": stats["radius"],
            "lower": lower, "decision": "accept" if lower > 0 else "reject",
            "verdict": "leap-certified"}


def complementarity(record):
    """Two complementary decisions: no single move helps, the pair does."""
    r = record or {}
    p = _num(r.get("p"))
    step = _num(r.get("step") or r.get("alpha"))
    if p is None or step is None or not 0 < p < 1:
        return {"format": FORMAT, "verdict": "insufficient-input"}
    alpha = step * p * (1.0 - p) if r.get("scaled") is not False else step
    first = 2.0 * (3.0 * p - 1.0) * alpha
    second = 3.0 * alpha * alpha
    joint = first + second
    threshold = 3.0 * (2.0 * p + alpha) > 2.0
    return {"format": FORMAT, "alpha": alpha, "first_order": first,
            "interaction": second, "joint": joint, "crosses": threshold,
            "verdict": "first-order-stationary" if first <= 0 < joint
            else ("joint-improves" if joint > 0 else "joint-loses")}


def controlled(record):
    """The paper's three controlled tasks, scored at a step s ∈ [−1, 1]."""
    r = record or {}
    task = str(r.get("task") or "")
    if task in ("complementarity", "redundancy"):
        step = _num(r.get("step"))
        if step is None:
            return {"format": FORMAT, "verdict": "insufficient-input"}
        if task == "complementarity":
            return {"format": FORMAT, "gain": 4.0 * step * step / 27.0,
                    "first_order_is_flat": True, "verdict": "scored"}
        return {"format": FORMAT, "gain": 0.032 * step - 0.0256 * step * step,
                "first_order_is_flat": False, "verdict": "scored"}
    if task == "evidence-threshold":
        n = int(_num(r.get("n") or 6))
        q = _num(r.get("q") or 0.3)
        if not 0 < q < 1:
            return {"format": FORMAT, "verdict": "insufficient-input"}
        hit = sum(math.comb(n, k) * q ** k * (1 - q) ** (n - k)
                  for k in range(3, n + 1))
        return {"format": FORMAT, "gain": hit - 0.05 * n * q,
                "first_order_is_flat": True, "verdict": "scored"}
    return {"format": FORMAT, "verdict": "unknown-task"}


def audit(record):
    """The misreadings the interaction view excludes."""
    r = record or {}
    findings = []
    if r.get("per_decision_credits_add") is True:
        findings.append({"kind": "per-decision-credits-add",
                         "why": "dependent decisions do not add; the joint gain is not a sum"})
    if r.get("trust_region_bounds_do_not_count_visits") is True:
        findings.append({"kind": "visits-ignored",
                         "why": "the bound scales with how often the decisions occur"})
    if r.get("clip_bounds_the_policy") is True:
        findings.append({"kind": "clip-bounds-the-policy",
                         "why": "clipping bounds sampled ratios, not the returned policy"})
    if r.get("validation_reused_for_fitting") is True:
        findings.append({"kind": "validation-reused-for-fitting",
                         "why": "the certificate needs fresh trajectories"})
    if r.get("larger_bound_skipped") is True:
        findings.append({"kind": "larger-bound-skipped",
                         "why": "the max of the two valid bounds is the certificate"})
    if r.get("leaps_certified_by_the_step_bound") is True:
        findings.append({"kind": "leaps-certified-by-the-step-bound",
                         "why": "a distant plan needs its own paired certificate"})
    if not findings:
        findings.append({"kind": "audit-conditions-met"})
    return {"format": FORMAT, "findings": findings, "verdict": "audit-complete"}


def advise(profile):
    """Map a harness profile onto the paper's orchestration failure modes."""
    p = profile or {}
    have = {str(k) for k, v in p.items() if v}
    checks = (
        ("credits_pairs_of_decisions", "credits_each_step_alone",
         "a worker is useful only if a later step may read it"),
        ("bounds_updates_by_visit_counts", "trusts_a_per_step_clip",
         "many small changes add up over an episode"),
        ("certifies_on_fresh_trajectories", "selects_on_training_returns",
         "sampling error can make a harmful update look good"),
        ("takes_the_max_of_valid_bounds", "uses_one_remainder_bound",
         "the truncated and importance-sampling bounds fail differently"),
        ("certifies_distant_plans_separately", "reuses_the_step_certificate",
         "a leap is not close to the reference policy"),
        ("prices_tokens_in_the_reward", "optimises_accuracy_only",
         "the objective is reward minus call cost"),
    )
    findings = []
    for key, kind, why in checks:
        if key not in have:
            findings.append({"kind": kind, "why": why})
    return {"format": FORMAT, "findings": findings}
