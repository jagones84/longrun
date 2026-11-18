#!/usr/bin/env python3
"""Skill value — a paired comparison, because an installed skill is not a gain.

Source: arXiv:2611.22017, "SkillBuffBench: Measuring What Agent Skills Contribute
across Harnesses, Models, Skill Access Modes and Memory" (round 109). Its design
point is that almost all evidence for skills comes from a hand-picked skill on a
blank slate; in deployment the agent chooses from whatever library is installed
and carries memory. The protocol that survives that setting is PAIRED: the same
task with and without the skill, one deterministic verifier, a task-level
bootstrap for uncertainty, and cost/rounds reported beside the score.

This module runs that arithmetic on longrun's own records. It never calls a
model: the caller supplies, per task, the outcome of a with-skill run and a
without-skill run.

  paired(records)  delta pass, delta cost, delta rounds with a 95% bootstrap CI
                   over TASKS (not runs), and a verdict
  flat_savings()   the paper's trap: success unchanged, savings gone

Deterministic: a fixed seed, so the same records always give the same interval.
"""
from __future__ import annotations

import random

FORMAT = "longrun-skill-value/1"
RESAMPLES = 2000
SEED = 20261119


def _get(rec, side, key, default=0.0):
    block = rec.get(side) or {}
    try:
        return float(block.get(key, default) or 0.0)
    except (TypeError, ValueError):
        return float(default)


def _delta(records, key):
    return [_get(r, "with", key) - _get(r, "without", key) for r in records]


def _mean(xs):
    return (sum(xs) / float(len(xs))) if xs else 0.0


def _ci(xs, level=0.95):
    if not xs:
        return {"lo": 0.0, "hi": 0.0}
    rng = random.Random(SEED)
    n = len(xs)
    means = []
    for _ in range(RESAMPLES):
        means.append(sum(xs[rng.randrange(n)] for _ in range(n)) / float(n))
    means.sort()
    lo = means[int((1.0 - level) / 2.0 * RESAMPLES)]
    hi = means[int((1.0 + level) / 2.0 * RESAMPLES) - 1]
    return {"lo": round(lo, 4), "hi": round(hi, 4)}


def _verdict(ci, mean):
    if ci["lo"] > 0:
        return "positive"
    if ci["hi"] < 0:
        return "negative"
    return "unresolved"


def paired(records):
    """The paired skill-value protocol over task-level records."""
    recs = [r for r in (records or []) if isinstance(r, dict)]
    if not recs:
        return {"format": FORMAT, "n_tasks": 0, "verdict": "no-evidence"}
    dp = _delta(recs, "pass")
    dc = _delta(recs, "cost")
    dr = _delta(recs, "rounds")
    ci_p, ci_c = _ci(dp), _ci(dc)
    res = {
        "format": FORMAT, "n_tasks": len(recs),
        "pass": {"mean": round(_mean(dp), 4), "ci": ci_p,
                 "verdict": _verdict(ci_p, _mean(dp))},
        "cost": {"mean": round(_mean(dc), 4), "ci": ci_c,
                 "verdict": _verdict(ci_c, _mean(dc))},
        "rounds": {"mean": round(_mean(dr), 4)},
        "skills": sorted({str(r.get("skill") or "") for r in recs
                          if r.get("skill")}),
    }
    # The paper's trap: an installed skill whose success delta is unresolved and
    # whose cost delta is clearly positive is a NEGATIVE asset even though the
    # score did not move.
    res["flat_savings"] = (res["pass"]["verdict"] == "unresolved"
                           and res["cost"]["verdict"] == "positive")
    res["verdict"] = ("keep" if res["pass"]["verdict"] == "positive"
                      else ("retire" if (res["pass"]["verdict"] == "negative"
                                         or res["flat_savings"])
                            else "unresolved"))
    return res
