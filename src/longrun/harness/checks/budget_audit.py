#!/usr/bin/env python3
"""Budget-paired audit — where an agent's looks are spent, and what they cost.

Source: arXiv:2611.24867, "Budget-Paired Counterfactual Audits for Visual
Agents" (round 149). A visual agent is a finite-horizon belief-state policy:
`V0(H) = max(pH, 1 - pH)`, `Qb(H, a) = E[V_{b-1}(H + (a, Z))]` and
`Vb(H) = max_a Qb(H, a)` over a hypothesis H and b remaining looks
(`budget_paired_audit_2611.24867.txt:174`, `:175`, `:176`).

  * **the loss is per step and per answer**: `delta_b(H, a) = Vb(H) - Qb(H, a)`
    is the action's shortfall and `eta(H, yhat) = V0(H) - Pr(Y = yhat | H)` is
    the final answer's shortfall (`:183`, `:184`).
  * **the two add up exactly**: `VB(H0) - J_mu = E[sum delta + eta]`, so a
    reported gain decomposes into looks spent badly plus a wrong last word
    (`:236`).
  * **the anchor is a transition, not a score**: at one look the optimal action
    is *branch*, at two it is *selector*; all five open-weight VLMs make 0/40 of
    those transitions while GPT-5 mini makes 48/48 (`:292`, `:296`).
  * **a stage can hide the cost**: first / later / final read losses were
    0.61 / 24.52 / 5.73 pp for one model and 0.96 / 22.20 / 14.30 for another
    (`:424`, `:454`).
  * **a curated label set is worth more than a bigger one**: FUNSD selection
    gain 24.44 pp curated against 10.56 pp on the original pool, and a
    two-crop system still trailed a native read at twice the tokens
    (`:66`, `:67`).
  * **one scorer is not a measurement**: the four-cell cross of original vs
    revised text and base vs punctuation normalization gives
    10.56 / 22.78 / 20.56 / 24.44 (`:530`).
  * **the value bound is linear in looks**: `2 eps` per decision and `2 B eps`
    cumulative (`:621`).

  * `belief(state)` — the smoothed hypothesis probability.
  * `value(state)` — `V0`, the accuracy of an unlooked-at answer.
  * `observe(state, reads)` — the exact outcome distribution of a look.
  * `q_value(state, action, budget)` — `Qb` for one action.
  * `solve(state, budget)` — `Vb`, the best action and every action's loss.
  * `decompose(spec)` — the per-step identity, exactly, over the whole tree.
  * `anchors(rows)` — the branch-to-selector transition rate and its losses.
  * `staged(stages)` — which read stage carries the loss.
  * `routing_gain(rho, r)` — the `(rho - .5)(r - .5)` selection gain.
  * `bound(eps, budget)` — the one-step and cumulative value bounds.
  * `audit(record)` — the seven misreadings the paper names.
  * `advise(profile)` — map a harness profile onto the paper's failure modes.

Pure: counts and recorded plays in; values, losses and verdicts out.
"""
from __future__ import annotations

import math

FORMAT = "longrun-budget-audit/1"

PROBES = ({"name": "commit", "reads": 0},
          {"name": "probe-one", "reads": 1},
          {"name": "probe-two", "reads": 2})
ANCHOR_ONE = "branch"
ANCHOR_TWO = "selector"
PP = 100.0


def _num(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _counts(state):
    s = state or {}
    return int(s.get("support") or 0), int(s.get("refute") or 0)


def _p(state):
    support, refute = _counts(state)
    return (support + 1) / (support + refute + 2)


def belief(state):
    """The smoothed hypothesis probability and the evidence behind it."""
    support, refute = _counts(state)
    return {"format": FORMAT, "p": _p(state), "support": support,
            "refute": refute, "evidence": support + refute,
            "verdict": "belief-updated"}


def value(state):
    """`V0(H)`: the accuracy of answering without another look."""
    p = _p(state)
    return {"format": FORMAT, "value": max(p, 1 - p), "p": p,
            "verdict": "value-at-zero-budget"}


def observe(state, reads):
    """Every outcome of `reads` looks with its exact probability."""
    support, refute = _counts(state)
    n = int(reads or 0)
    if n <= 0:
        return [(1.0, {"support": support, "refute": refute})]
    p = _p(state)
    out = []
    for k in range(n + 1):
        prob = math.comb(n, k) * (p ** k) * ((1 - p) ** (n - k))
        out.append((prob, {"support": support + k,
                           "refute": refute + n - k}))
    return out


def _value_at(state, budget, probes, memo):
    if budget <= 0:
        return max(_p(state), 1 - _p(state))
    support, refute = _counts(state)
    key = (support, refute, budget)
    if key in memo:
        return memo[key]
    best = max(_q_value_at(state, action, budget, probes, memo)
               for action in probes)
    memo[key] = best
    return best


def _q_value_at(state, action, budget, probes, memo):
    total = 0.0
    for prob, child in observe(state, (action or {}).get("reads") or 0):
        total += prob * _value_at(child, budget - 1, probes, memo)
    return total


def q_value(state, action, budget):
    """`Qb(H, a)`: the expected value of one action with `budget` looks."""
    budget = int(budget or 0)
    if budget <= 0:
        return {"format": FORMAT, "value": _value_at(state, 0, PROBES, {}),
                "verdict": "no-budget"}
    q = _q_value_at(state, action, budget, PROBES, {})
    return {"format": FORMAT, "value": q, "action": (action or {}).get("name"),
            "verdict": "q-computed"}


def solve(state, budget, actions=None):
    """`Vb`, the best action, and the loss of every other action."""
    probes = tuple(actions or PROBES)
    budget = int(budget or 0)
    memo = {}
    top = _value_at(state, budget, probes, memo)
    if budget <= 0:
        return {"format": FORMAT, "value": top, "best": "commit",
                "table": [{"action": "commit", "q": top, "loss": 0.0,
                           "loss_pp": 0.0}],
                "verdict": "no-budget"}
    table = []
    for action in probes:
        q = _q_value_at(state, action, budget, probes, memo)
        table.append({"action": action.get("name"), "q": q,
                      "loss": top - q,
                      "loss_pp": (top - q) * PP})
    best = min(table, key=lambda row: row["loss"])
    return {"format": FORMAT, "value": top, "best": best["action"],
            "table": table, "verdict": "solved"}


def decompose(spec):
    """The identity `VB(H0) - J_mu = E[sum delta + eta]`, over the tree."""
    s = spec or {}
    state = s.get("state") or {}
    budget = int(s.get("budget") or 0)
    probes = tuple(s.get("actions") or PROBES)
    names = {a.get("name"): a for a in probes}
    policy = {}
    for key, name in (s.get("policy") or {}).items():
        try:
            policy[int(key)] = name
        except (TypeError, ValueError):
            continue
    prediction = str(s.get("prediction") or "positive")
    memo = {}

    def _accuracy(h):
        p = _p(h)
        return p if prediction == "positive" else 1 - p

    def _eta(h):
        return max(_p(h), 1 - _p(h)) - _accuracy(h)

    def _walk(h, b):
        if b <= 0:
            return {"delta": 0.0, "eta": _eta(h), "accuracy": _accuracy(h)}
        action = names.get(policy.get(b))
        if action is None:
            action = max(probes,
                         key=lambda a: _q_value_at(h, a, b, probes, memo))
        q = 0.0
        delta = 0.0
        eta = 0.0
        accuracy = 0.0
        for prob, child in observe(h, action.get("reads") or 0):
            sub = _walk(child, b - 1)
            q += prob * _value_at(child, b - 1, probes, memo)
            delta += prob * sub["delta"]
            eta += prob * sub["eta"]
            accuracy += prob * sub["accuracy"]
        top = _value_at(h, b, probes, memo)
        return {"delta": (top - q) + delta, "eta": eta, "accuracy": accuracy}

    root = _walk(state, budget)
    top = _value_at(state, budget, probes, memo)
    lhs = top - root["accuracy"]
    rhs = root["delta"] + root["eta"]
    return {"format": FORMAT, "value": top, "accuracy": root["accuracy"],
            "expected_delta": root["delta"], "expected_eta": root["eta"],
            "lhs": lhs, "rhs": rhs, "gap": lhs - rhs,
            "holds": abs(lhs - rhs) <= 1e-9,
            "verdict": "identity-holds" if abs(lhs - rhs) <= 1e-9
            else "identity-broken"}


def anchors(rows):
    """The branch-at-one / selector-at-two transition, case by case."""
    cases = 0
    optimal = 0
    anchor_losses = []
    control_losses = []
    for row in rows or []:
        r = row or {}
        played = r.get("played") or {}
        one = played.get("1", played.get(1))
        two = played.get("2", played.get(2))
        if one is None and two is None:
            continue
        cases += 1
        if one == ANCHOR_ONE and two == ANCHOR_TWO:
            optimal += 1
        loss = _num(r.get("loss"))
        if loss is None:
            continue
        (anchor_losses if r.get("anchor") else control_losses).append(loss)
    if not cases:
        return {"format": FORMAT, "verdict": "no-recorded-plays"}
    rate = optimal / cases
    anchor_mean = (sum(anchor_losses) / len(anchor_losses)
                   if anchor_losses else None)
    control_mean = (sum(control_losses) / len(control_losses)
                    if control_losses else None)
    gap = (anchor_mean - control_mean
           if anchor_mean is not None and control_mean is not None else None)
    return {"format": FORMAT, "transitions": optimal, "cases": cases,
            "rate": rate, "anchor_loss": anchor_mean,
            "control_loss": control_mean, "gap": gap,
            "verdict": "anchor-transition-optimal" if rate >= 0.5
            else "anchor-transition-missed"}


def staged(stages):
    """Which read stage carries the loss, and how much of the total it is."""
    rows = []
    for stage in stages or []:
        s = stage or {}
        loss = _num(s.get("loss"))
        if loss is None:
            continue
        rows.append({"stage": str(s.get("stage") or ""), "loss": loss})
    if not rows:
        return {"format": FORMAT, "verdict": "no-stages"}
    total = sum(row["loss"] for row in rows)
    dominant = max(rows, key=lambda row: row["loss"])
    share = dominant["loss"] / total if total else 0.0
    first = rows[0]
    return {"format": FORMAT, "stages": len(rows), "total": total,
            "dominant": dominant["stage"], "share": share,
            "first": first["loss"],
            "verdict": "late-read-dominates" if dominant is not first
            else "first-read-dominates"}


def routing_gain(rho, r):
    """The conditional-routing gain `(rho - .5)(r - .5)`, at most .25."""
    a = _num(rho)
    b = _num(r)
    if a is None or b is None:
        return {"format": FORMAT, "verdict": "insufficient-input"}
    gain = (a - 0.5) * (b - 0.5)
    return {"format": FORMAT, "gain": gain, "max": 0.25,
            "verdict": "routing-helps" if gain > 0 else "routing-hurts"}


def bound(eps, budget):
    """The `2 eps` one-step and `2 B eps` cumulative value bounds."""
    e = _num(eps)
    b = int(budget or 0)
    if e is None or b <= 0:
        return {"format": FORMAT, "verdict": "insufficient-input"}
    return {"format": FORMAT, "per_step": e, "one_step": 2 * e,
            "cumulative": 2 * b * e, "looks": b,
            "verdict": "value-bounded"}


def audit(record):
    """The seven misreadings the paper names, each as a finding."""
    r = record or {}
    findings = []
    if r.get("budgets_unpaired") is True:
        findings.append({"kind": "budgets-unpaired",
                         "why": "two systems at different budgets are not a comparison"})
    if r.get("single_budget_claim") is True:
        findings.append({"kind": "single-budget-claim",
                         "why": "one budget cannot separate spending from skill"})
    if r.get("final_answer_assumed_optimal") is True:
        findings.append({"kind": "final-answer-assumed-optimal",
                         "why": "eta is part of the loss, not zero"})
    if r.get("aggregate_hides_anchor") is True:
        findings.append({"kind": "aggregate-hides-anchor",
                         "why": "an average gain conceals a 0/40 anchor transition"})
    if r.get("tokens_unmatched") is True:
        findings.append({"kind": "tokens-unmatched",
                         "why": "twice the tokens is not the same read"})
    if r.get("single_scorer") is True:
        findings.append({"kind": "single-scorer",
                         "why": "the scorer cross moves the gain by 14 pp"})
    if r.get("no_value_bound") is True:
        findings.append({"kind": "no-value-bound",
                         "why": "a value without 2 eps cannot be told from noise"})
    if not findings:
        findings.append({"kind": "audit-conditions-met"})
    return {"format": FORMAT, "findings": findings, "verdict": "audit-complete"}


def advise(profile):
    """Map a harness profile onto the paper's failure modes."""
    p = profile or {}
    have = {str(k) for k, v in p.items() if v}
    checks = (
        ("pairs_looks_with_budget", "budget_free_comparison",
         "spending and skill are confounded without a paired budget"),
        ("reports_per_step_loss", "end_score_only",
         "a final score hides the step that wasted the looks"),
        ("scores_the_final_answer_separately", "assumes_a_correct_last_word",
         "eta is measurable and part of the regret"),
        ("audits_the_anchor_subset", "mean_gain_only",
         "a 0/40 anchor transition can disappear inside an average"),
        ("matches_tokens_across_arms", "ignores_read_cost",
         "twice the tokens is a different agent"),
        ("cross_checks_the_scorer", "one_scorer",
         "the same labels under a second scorer can reverse the conclusion"),
        ("states_a_value_bound", "point_estimate_only",
         "2 eps is the smallest difference worth reporting"),
    )
    findings = []
    for key, kind, why in checks:
        if key not in have:
            findings.append({"kind": kind, "why": why})
    return {"format": FORMAT, "findings": findings}
