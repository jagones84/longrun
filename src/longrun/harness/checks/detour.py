#!/usr/bin/env python3
"""Trajectory cost — an endpoint score cannot tell a detour from a near miss.

Source: arXiv:2611.20844, "DetourBench: Trajectory-Level Evaluation of
Interactive Agents with Exact Minimum-Action Bounds" (round 126). Endpoint
scoring gives the same result to an agent that took the shortest route and one
that read most of the environment, and the same zero to an agent that stopped one
access short and one that never found the evidence. The paper's measurements:
eight of 25 tasks are solved by every model on every repeat while conditional
attainment still spreads models by 0.074–0.190; on failures, 95 of 99 exhaust the
budget a median of three accesses from the goal, and two are irreversible
commitments with NO finite residual distance (§5.4, §5.5, Table 5).

  * `attainment(success, charged, optimum)` — `A = L0 / C` for a success, defined
    for every success and comparable across very different lengths.
  * `residual(...)` — `R = 0` on success, the exact remaining accesses on a
    recoverable failure, and **None** (not a number) after an irreversible
    commitment.
  * `progress(...)` — residual-distance progress and normalized detour
    `NDR = C/L0 - 1`, reported separately from success.
  * `rsr(...)` — invalid plus state-preserving repeated accesses over charged
    accesses; undefined on failure.
  * `classify(episodes)` / `rank_models(episodes)` — direct, exploratory,
    near-miss, costly-incomplete, irreversible; and the model ordering by success
    vs by attainment, with `ordering-reversal` when they disagree.

`L0` is an input from an oracle search; this module does not search a graph.
"""
from __future__ import annotations

FORMAT = "longrun-detour/1"


def _num(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def attainment(success, charged, optimum):
    """A = L0 / C on success; undefined otherwise, never zero-by-default."""
    l0, c = _num(optimum), _num(charged)
    if not success:
        return {"format": FORMAT, "attainment": None,
                "findings": [{"kind": "not-success",
                              "why": "attainment is conditional on success"}],
                "why": "a failure has an outcome, not an efficiency score"}
    if l0 is None or c is None or l0 <= 0 or c <= 0:
        return {"format": FORMAT, "attainment": None,
                "findings": [{"kind": "no-optimum"}],
                "why": "no exact bound, no oracle-relative measure"}
    if c < l0:
        return {"format": FORMAT, "attainment": 1.0,
                "findings": [{"kind": "below-optimum", "charged": c, "optimum": l0,
                              "why": "shorter than the declared minimum means the "
                                     "bound or the trace is wrong"}],
                "why": "clamped to 1 and flagged, not trusted"}
    return {"format": FORMAT, "attainment": round(l0 / c, 4),
            "findings": [], "charged": c, "optimum": l0,
            "why": "excess is relative to a fixed per-instance minimum"}


def residual(success, wrong, remaining=None):
    """R = 0 on success, an exact count on a recoverable stop, None if irreversible."""
    if success:
        return {"format": FORMAT, "residual": 0, "findings": []}
    if wrong:
        return {"format": FORMAT, "residual": None,
                "findings": [{"kind": "irreversible",
                              "why": "an absorbing wrong commitment has no finite "
                                     "residual distance"}],
                "why": "reported as undefined, never as a large number"}
    r = _num(remaining)
    if r is None or r < 0:
        return {"format": FORMAT, "residual": None,
                "findings": [{"kind": "no-residual",
                              "why": "the terminal state was not graph-recoverable"}],
                "why": "an unknown distance is not a measured one"}
    return {"format": FORMAT, "residual": int(r), "findings": []}


def progress(success, residual_work, optimum, charged=None):
    """P = 1 - R/L0 and NDR = C/L0 - 1, each only where it is defined."""
    l0 = _num(optimum)
    if l0 is None or l0 <= 0:
        return {"format": FORMAT, "progress": None, "ndr": None,
                "findings": [{"kind": "no-optimum"}]}
    out = {"format": FORMAT, "progress": None, "ndr": None, "findings": []}
    if residual_work is not None:
        r = _num(residual_work)
        if r is not None:
            out["progress"] = round(max(0.0, 1.0 - r / l0), 4)
    if success and charged is not None:
        c = _num(charged)
        if c is not None and c > 0 and c >= l0:
            out["ndr"] = round(c / l0 - 1.0, 4)
    return out


def rsr(invalid, duplicate, charged):
    """Invalid + state-preserving repeat over charged accesses; undefined on failure."""
    i, d, c = _num(invalid), _num(duplicate), _num(charged)
    if None in (i, d, c) or c <= 0:
        return {"format": FORMAT, "rsr": None,
                "findings": [{"kind": "no-charged-accesses"}]}
    return {"format": FORMAT, "rsr": round((i + d) / c, 4), "findings": [],
            "why": "catches overt waste, not valid but unnecessary exploration"}


def classify(episodes):
    """Direct / exploratory / near-miss / costly-incomplete / irreversible."""
    rows = []
    for ep in episodes or ():
        if not isinstance(ep, dict):
            continue
        optimum = _num(ep.get("optimum"))
        charged = _num(ep.get("charged"))
        success = bool(ep.get("success"))
        wrong = bool(ep.get("wrong"))
        row = {"id": str(ep.get("id") or ""), "model": str(ep.get("model") or ""),
               "success": success}
        if success:
            row["class"] = "direct" if (optimum and charged and charged <= optimum) \
                else "exploratory"
            row["attainment"] = attainment(True, charged, optimum)["attainment"]
        elif wrong:
            row["class"] = "irreversible"
            row["residual"] = None
        else:
            r = residual(False, False, ep.get("residual"))
            row["residual"] = r["residual"]
            if r["residual"] is None:
                row["class"] = "unmeasured"
            else:
                row["class"] = "near-miss" if r["residual"] <= 2 else "costly-incomplete"
        rows.append(row)
    counts = {}
    for row in rows:
        counts[row["class"]] = counts.get(row["class"], 0) + 1
    return {"format": FORMAT, "episodes": rows, "counts": counts,
            "why": "six outcomes an endpoint score collapses into one"}


def rank_models(episodes):
    """Success and conditional attainment can order the same models differently."""
    per = {}
    for ep in episodes or ():
        if not isinstance(ep, dict) or not ep.get("model"):
            continue
        model = str(ep["model"])
        row = per.setdefault(model, {"episodes": 0, "successes": 0, "attainments": []})
        row["episodes"] += 1
        if ep.get("success"):
            row["successes"] += 1
            a = attainment(True, ep.get("charged"), ep.get("optimum"))["attainment"]
            if a is not None:
                row["attainments"].append(a)
    summary = {}
    for model, row in per.items():
        summary[model] = {"episodes": row["episodes"],
                          "success_rate": round(row["successes"] / row["episodes"], 4),
                          "attainment": round(sum(row["attainments"]) / len(row["attainments"]), 4)
                          if row["attainments"] else None}
    findings = []
    ranked = [m for m in summary if summary[m]["attainment"] is not None]
    if len(ranked) >= 2:
        by_success = max(ranked, key=lambda m: (summary[m]["success_rate"],
                                                summary[m]["attainment"]))
        by_cost = max(ranked, key=lambda m: (summary[m]["attainment"],
                                             summary[m]["success_rate"]))
        if by_success != by_cost:
            findings.append({"kind": "ordering-reversal",
                             "by_success": by_success, "by_attainment": by_cost,
                             "why": "the endpoint and the trajectory disagree"})
    return {"format": FORMAT, "models": summary, "findings": findings,
            "why": "report both orderings; neither replaces the other"}
