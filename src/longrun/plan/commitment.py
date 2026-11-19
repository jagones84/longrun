#!/usr/bin/env python3
"""Plan commitment — repair, replan, or abandon, decided by damage depth.

Source: arXiv:2611.19663, "When AI Agents Should Repair, Replan, or Abandon: A
Threshold Theory of Plan Commitment" (round 117). The paper replaces the two
deployed conventions ("retry loop", "always replan") with a policy:

  * a disruption destroys the causal support of part of the plan;
  * repair is a partial reset that keeps the plan's structure, replanning is a
    full reset, and switching is costly because others conditioned on the plan;
  * the optimal policy is a threshold in EFFECTIVE disruption depth — repair
    shallow damage, replan after deep damage, abandon when even a fresh plan is
    not worth its cost;
  * a single broken action forces ``1 + R(G)/n`` actions to be revalidated, R(G)
    counting the pairs joined by a dependency path — so a serial plan crosses the
    threshold at far smaller raw damage than a plan of parallel chains;
  * a stability price decides when a worse repaired plan beats a better fresh one;
  * repeated repairs add patch debt until rebuilding wins;
  * measuring the damage is itself a decision with a value.

Everything here is a deterministic function of a record the caller supplies. The
structure figures (depth, R, chains) come from the graph; the money figures
(costs, values, prices) are caller declarations, never invented.

Pure: record in, decision out.
"""
from __future__ import annotations

FORMAT = "longrun-plan-commitment/1"
DECISIONS = ("repair", "replan", "abandon")
DEFAULT_THRESHOLD = 0.5


def _succ(actions, edges):
    out = {a: set() for a in actions}
    for edge in edges or []:
        if isinstance(edge, (list, tuple)) and len(edge) == 2:
            a, b = edge
            if a in out and b in out:
                out[a].add(b)
    return out


def descendants(actions, edges, roots):
    """Every action that depends, transitively, on one of ``roots`` (edges point dependency->dependent)."""
    succ = _succ(actions, edges)
    seen, stack = set(), [r for r in roots if r in succ]
    while stack:
        node = stack.pop()
        if node in seen:
            continue
        seen.add(node)
        stack.extend(succ[node] - seen)
    return seen


def damaged(actions, edges, broken):
    """The broken actions plus every action whose causal support they destroy."""
    return descendants(actions, edges, set(broken or []))


def depth(actions, edges, broken):
    """Effective disruption depth, 0..1: the share of the plan the damage reaches."""
    if not actions:
        return 0.0
    return round(len(damaged(actions, edges, broken)) / len(actions), 4)


def pairs(actions, edges):
    """R(G): ordered pairs joined by a dependency path — the paper's revalidation count."""
    succ = _succ(actions, edges)
    total = 0
    for a in actions:
        total += len(descendants(actions, edges, [a]) - {a})
    return total


def revalidation_cost(actions, edges):
    """``1 + R(G)/n`` — actions a single broken action forces to be revalidated."""
    n = len(actions)
    if not n:
        return 0.0
    return round(1 + pairs(actions, edges) / n, 4)


def chains(actions, edges):
    """Weakly connected components: independent chains that a disruption can split."""
    parent = {a: a for a in actions}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for edge in edges or []:
        # R160 bug hunt: a malformed edge (not a 2-tuple) used to raise ValueError
        # out of `decide()`. Ignore it, the way `_succ` already does.
        if not (isinstance(edge, (list, tuple)) and len(edge) == 2):
            continue
        a, b = edge
        if a in parent and b in parent:
            ra, rb = find(a), find(b)
            if ra != rb:
                parent[ra] = rb
    return len({find(a) for a in actions})


def switch_point(actions, edges, threshold):
    """The raw damage count at which this structure crosses the depth threshold.

    The paper's first-order result is that a serial plan switches at roughly
    ``w`` times smaller raw damage than a plan of ``w`` parallel chains; this
    function makes that observable instead of assumed.
    """
    order = list(actions)
    for k in range(1, len(order) + 1):
        if depth(actions, edges, order[:k]) > threshold:
            return k
    return None


def decide(record):
    """Repair, replan or abandon — with the reasons that produced the choice."""
    rec = record or {}
    actions = [a for a in (rec.get("actions") or []) if a]
    edges = rec.get("edges") or []
    broken = [b for b in (rec.get("broken") or []) if b in actions]
    threshold = rec.get("threshold")
    if not isinstance(threshold, (int, float)):
        threshold = DEFAULT_THRESHOLD
    reasons = []

    goal_value = rec.get("goal_value")
    abandon_value = rec.get("abandon_value")
    if isinstance(goal_value, (int, float)) and isinstance(abandon_value, (int, float)):
        if goal_value <= abandon_value:
            return {"format": FORMAT, "decision": "abandon", "depth": None,
                    "damaged": [], "threshold": threshold,
                    "revalidation": revalidation_cost(actions, edges),
                    "chains": chains(actions, edges),
                    "reasons": ["the goal is not worth its cost: value %g <= abandoning it %g"
                                % (goal_value, abandon_value)]}

    d = depth(actions, edges, broken)
    fresh = rec.get("fresh_value")
    repaired = rec.get("repaired_value")
    price = rec.get("stability_price") or 0
    debt = rec.get("patch_debt") or 0
    step = rec.get("patch_step") or 0
    debt_limit = rec.get("debt_limit")

    decision = "repair" if d <= threshold else "replan"
    reasons.append("effective depth %.3f is %s the threshold %.3f"
                   % (d, "<=" if d <= threshold else ">", threshold))

    if decision == "repair":
        if isinstance(fresh, (int, float)) and isinstance(repaired, (int, float)):
            if fresh - repaired > price:
                decision = "replan"
                reasons.append("a fresh plan gains %.3f, more than the stability price %.3f"
                               % (fresh - repaired, price))
            else:
                reasons.append("a fresh plan gains %.3f, less than the stability price %.3f"
                               % (fresh - repaired, price))
    else:
        if isinstance(fresh, (int, float)) and isinstance(repaired, (int, float)):
            if fresh - repaired < price:
                decision = "repair"
                reasons.append("repairing keeps a worse plan only because switching costs %.3f"
                               % price)
    if isinstance(debt_limit, (int, float)) and debt + step >= debt_limit:
        decision = "replan"
        reasons.append("patch debt %.3f + %.3f reaches the limit %.3f"
                       % (debt, step, debt_limit))

    return {"format": FORMAT, "decision": decision, "depth": d,
            "damaged": sorted(damaged(actions, edges, broken)),
            "threshold": threshold,
            "revalidation": revalidation_cost(actions, edges),
            "chains": chains(actions, edges),
            "reasons": reasons}


def worth_diagnosis(record):
    """Is measuring the damage worth its compute?

    Value of diagnosis = the expected decision improvement (uncertainty in depth
    times the cost it can save) minus the diagnosis cost. A certain damage is
    never worth measuring twice.
    """
    rec = record or {}
    uncertainty = rec.get("depth_uncertainty")
    gap = rec.get("repair_replan_gap")
    cost = rec.get("diagnosis_cost")
    if not isinstance(uncertainty, (int, float)) or not isinstance(gap, (int, float)):
        return {"format": FORMAT, "worth": False, "why": "no depth uncertainty declared"}
    cost = cost if isinstance(cost, (int, float)) else 0
    value = uncertainty * abs(gap)
    return {"format": FORMAT, "worth": value > cost, "value": round(value, 4),
            "cost": cost, "why": "uncertainty %.3f x gap %.3f vs cost %g"
            % (uncertainty, abs(gap), cost)}
