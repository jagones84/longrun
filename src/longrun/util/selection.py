#!/usr/bin/env python3
"""Budget-constrained selection — which agent to pay for, and how much to spend.

Source: arXiv:2611.21515, "Beyond Leaderboard Ranks: Selecting Software
Engineering Agents Under Budget Constraints" (round 108). Its measurements:
27 of 35 steps along the accuracy–cost Pareto frontier are statistically
unresolved; a $34.16 run trails a $170.78 leader by 14.6 pp on a sample that
cannot distinguish them; reported costs differ from token-based estimates by up
to 11.7×; and successive halving reaches the uncertainty-aware target using 6.6%
of exhaustive evaluation spend (when task costs are known in advance).

So a leaderboard rank is not a selection. This module takes candidate agents
with (cheap per-run cost, passes, runs) and answers the two questions under two
budgets — evaluation spend and deployment cost:

  * successive halving: evaluate the promising half first, drop the rest;
  * a Wilson interval per candidate so "14.6 pp better" on 20 runs is not
    mistaken for a decision;
  * among candidates whose intervals overlap, prefer the CHEAPER one — the
    paper's own conclusion, and the only honest choice when the evidence cannot
    separate them.

Pure: dicts in, dict out. The caller runs the evaluations; this only decides
which ones are worth paying for.
"""
from __future__ import annotations

import math

FORMAT = "longrun-selection/1"
Z = 1.96


def wilson(passes, n, z=Z):
    """Wilson score interval for a pass rate — stable at small n."""
    n = int(n)
    if n <= 0:
        return {"passes": 0, "n": 0, "p": None, "lo": 0.0, "hi": 1.0}
    p = float(passes) / n
    denom = 1.0 + z * z / n
    centre = (p + z * z / (2.0 * n)) / denom
    half = z * math.sqrt(max(0.0, p * (1.0 - p) / n + z * z / (4.0 * n * n))) / denom
    return {"passes": int(passes), "n": n, "p": round(p, 4),
            "lo": round(max(0.0, centre - half), 4),
            "hi": round(min(1.0, centre + half), 4)}


def overlap(a, b):
    """True when two intervals cannot be separated by the evidence we have."""
    return not (a["hi"] < b["lo"] or b["hi"] < a["lo"])


def _norm(cand):
    out = dict(cand)
    out.setdefault("cost", 0.0)
    try:
        out["cost"] = float(out.get("cost") or 0.0)
    except (TypeError, ValueError):
        out["cost"] = 0.0
    st = wilson(out.get("passes", 0), out.get("n", 0))
    out.update(st)
    return out


def select(candidates, eval_budget=100.0, cost_cap=None):
    """Successive halving under an evaluation budget and a deployment cost cap.

    `candidates`: `[{"name", "cost" (per run), "passes", "n"}]`. Returns the
    ranking, the rounds actually affordable, the spend, and the winner with the
    reason. Deterministic for the same input.
    """
    pool = [_norm(c) for c in (candidates or [])]
    if cost_cap is not None:
        capped = [c for c in pool if c["cost"] <= float(cost_cap)]
        dropped = [c["name"] for c in pool if c not in capped]
        pool = capped
    else:
        dropped = []
    rounds = []
    budget = float(eval_budget)
    spent = 0.0
    alive = list(pool)
    if len(alive) > 1:
        alive.sort(key=lambda c: (-c["lo"], c["cost"]))
        leader = alive[0]
        half = alive[:max(1, (len(alive) + 1) // 2)]
        # Successive halving must not drop a candidate the evidence cannot
        # separate from the leader: that is exactly the case where the cheaper
        # one should win (arXiv:2611.21515).
        half = [c for c in alive if c in half or overlap(c, leader)]
        # This function plans ONE round. It never invents an outcome: the caller
        # buys these runs, updates passes/n, and calls `select` again. Planning
        # more rounds without feedback would only repeat the same purchases.
        buy, bill = [], 0.0
        for c in sorted(half, key=lambda c: c["cost"]):
            if c["cost"] <= 0:
                continue
            if bill + c["cost"] <= budget:
                buy.append(c["name"])
                bill += c["cost"]
        rounds.append({"kept": [c["name"] for c in half],
                       "evaluate_next": buy,
                       "dropped": [c["name"] for c in alive if c not in half],
                       "spent_planned": round(bill, 4)})
        spent = bill
        alive = half
    alive.sort(key=lambda c: (-c["lo"], c["cost"]))
    best = alive[0] if alive else None
    if best is None:
        return {"format": FORMAT, "winner": None, "reason": "no-candidate",
                "ranking": [], "rounds": rounds, "spent": round(spent, 4),
                "dropped_by_cap": dropped}
    tied = [c for c in alive if c is not best and overlap(c, best)]
    if tied:
        group = [best] + tied
        cheapest = min(group, key=lambda c: c["cost"])
        reason = ("intervals overlap (best lo=%s, %s lo=%s); cheapest unresolved "
                  "candidate wins" % (best["lo"], cheapest["name"], cheapest["lo"]))
        winner = cheapest
    else:
        reason = "separated interval (lo=%.4f vs next=%.4f)" % (
            best["lo"], alive[1]["lo"] if len(alive) > 1 else 0.0)
        winner = best
    ranking = sorted(pool, key=lambda c: (-c["lo"], c["cost"]))
    return {"format": FORMAT, "winner": winner["name"], "reason": reason,
            "ranking": [{"name": c["name"], "cost": c["cost"], "p": c["p"],
                         "lo": c["lo"], "hi": c["hi"], "n": c["n"]} for c in ranking],
            "rounds": rounds, "spent": round(spent, 4),
            "dropped_by_cap": dropped}
