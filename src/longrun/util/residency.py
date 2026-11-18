#!/usr/bin/env python3
"""Context-residency band — park a session instead of letting the working set
outgrow the cache.

Source: arXiv:2611.13412, "Bursts That Outlast Themselves: Persistent
Degradation in Prefix-Cached Agent Serving" (round 110). Its finding is that a
prefix-cached server is metastable: a short burst leaves MORE sessions resident
than the cache holds, every turn becomes a recompute, and the population only
drains after tens of minutes. Admission control alone does not recover it;
what recovered every collapsed run was a BUDGETER that bounds the resident
demand of ADMITTED sessions to the pool and PARKS admitted sessions above the
band, re-admitting them (parked before new) below the low mark.

This is the harness-side planner for that rule, with no server attached:

  * demand = sum(context tokens + output budget) of the admitted sessions;
  * at a turn boundary, if demand > high*C, park the session that reached the
    boundary (never an in-flight request);
  * whenever a turn completes, admit waiting sessions, parked first, while the
    projected demand stays <= low*C;
  * thresholds are fixed (0.75 / 0.95) and need no per-workload tuning.

Pure: takes session rows, returns decisions; nothing is executed.
"""
from __future__ import annotations

FORMAT = "longrun-residency/1"
LOW = 0.75
HIGH = 0.95


def _row(s):
    s = s or {}
    return {
        "id": str(s.get("id") or s.get("session") or ""),
        "ctx_tokens": max(0, int(s.get("ctx_tokens") or 0)),
        "output_budget": max(0, int(s.get("output_budget") or 0)),
        "admitted": bool(s.get("admitted")),
        "parked": bool(s.get("parked")),
        "parked_seq": int(s.get("parked_seq") or 0),
    }


def _need(row):
    return row["ctx_tokens"] + row["output_budget"]


def demand(sessions):
    """Resident demand of the sessions that are admitted right now."""
    return sum(_need(_row(s)) for s in sessions or ()
               if _row(s)["admitted"] and not _row(s)["parked"])


def plan(sessions, capacity, low=LOW, high=HIGH, current=None):
    """Plan one turn-boundary decision for the whole population.

    `capacity` is the cache pool in tokens. `current` is the id of the session
    that just reached a turn boundary (the only one that may be parked: an
    in-flight request is never interrupted). Returns the decisions, the demand
    before and after, the band, and a verdict.
    """
    try:
        cap = float(capacity)
    except (TypeError, ValueError):
        cap = 0.0
    rows = [_row(s) for s in (sessions or ()) if isinstance(s, dict)]
    if cap <= 0:
        return {"format": FORMAT, "capacity": 0, "low": low, "high": high,
                "demand": 0, "demand_after": 0, "band": [0, 0],
                "decisions": [], "verdict": "no-capacity"}
    lo, hi = cap * float(low), cap * float(high)
    admitted = [r for r in rows if r["admitted"] and not r["parked"]]
    total = sum(_need(r) for r in admitted)
    before = total
    decisions = []

    cur = next((r for r in rows if r["id"] == str(current)), None) if current is not None else None
    if cur is not None and cur["admitted"] and not cur["parked"] and total > hi:
        cur["admitted"] = False
        cur["parked"] = True
        total -= _need(cur)
        decisions.append({"session": cur["id"], "action": "park",
                          "reason": "demand-over-high-water"})

    # Re-admit parked sessions before any new one; small sessions may fit even
    # when the head of the queue does not.
    queue = sorted((r for r in rows if r["parked"]), key=lambda r: (r["parked_seq"], r["id"]))
    fresh = [r for r in rows if not r["admitted"] and not r["parked"]]
    for cand in queue + fresh:
        need = _need(cand)
        if need and total + need <= lo:
            cand["admitted"] = True
            cand["parked"] = False
            total += need
            decisions.append({"session": cand["id"], "action": "admit",
                              "reason": "parked-before-new" if cand in queue else "within-low-water"})

    if any(d["action"] == "park" for d in decisions):
        verdict = "parked"
    elif any(d["action"] == "admit" for d in decisions):
        verdict = "admitted"
    elif total > hi:
        verdict = "over-high"
    elif total > lo:
        verdict = "holds"
    else:
        verdict = "within-band"
    return {"format": FORMAT, "capacity": int(cap), "low": low, "high": high,
            "demand": before, "demand_after": total,
            "band": [round(lo, 1), round(hi, 1)],
            "decisions": decisions, "verdict": verdict}
