#!/usr/bin/env python3
"""Evolution capabilities — updating a harness and benefiting from it are two skills.

Source: arXiv:2605.30621, "Harness Updating Is Not Harness Benefit" (round 139).
End-to-end evolution scores hide where the gain came from: an evolver writes the
update, and a task-solving agent uses it
(`harness_updating_vs_benefit_2605.30621.md:30`, `:62`).

  * **harness-updating is flat in base capability**: the best and worst evolver
    differ by at most 3.1 pp on any benchmark, and no evolver wins everywhere
    (`:70`, `:164`).
  * **harness-benefit is non-monotonic**: mid-tier agents gain most, weak-tier
    least (no ceiling), strong-tier less (ceiling) (`:72`, `:180`).
  * **two weak-tier failure modes**: activation (skill-load rate 0.251 against
    roughly 0.96) and adherence (following rate 0.142 against 0.757) (`:184`,
    `:201`).
  * **adherence drifts**: 0.52 -> 0.13 across the trajectory for a weak model,
    0.89 -> 0.80 for a strong one (`:218`).
  * **post-evolution score is dominated by the agent**: within-agent spread at
    most 5.1 pp against a 36.0 pp between-agent gap (`:168`).
  * **in-situ scoring locks a task's score before its evidence updates the
    harness** (`:364`).

  * `updating(rows)` — per-evolver gain across anchors, spread and dominance.
  * `benefit(rows)` — per-agent gain and the non-monotonic verdict.
  * `activation(rows)` / `adherence(rows)` — the two weak-tier failure modes.
  * `budget(rows)` — within-agent against between-agent spread.
  * `pairing(rows)` — does an extreme pairing reverse the order.
  * `insitu(row)` — was the score locked before its own evidence was used.
  * `advise(profile)` — map a harness profile onto the paper's failure modes.

Pure: capability rows in; findings out.
"""
from __future__ import annotations

import statistics

FORMAT = "longrun-evolution-capabilities/1"


def _num(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def updating(rows):
    """Mean pairwise gain per evolver, and whether the evolvers are separable."""
    data = [r for r in (rows or ()) if _num(r.get("gain")) is not None
            and r.get("evolver") is not None]
    if not data:
        return {"format": FORMAT, "findings": [{"kind": "no-update-rows"}]}
    by_evolver = {}
    for r in data:
        by_evolver.setdefault(str(r["evolver"]), []).append(_num(r["gain"]))
    means = {k: statistics.mean(v) for k, v in by_evolver.items()}
    spread = max(means.values()) - min(means.values())
    best = max(means, key=means.get)
    findings = []
    if spread <= 3.1:
        findings.append({"kind": "updating-flat", "spread": round(spread, 2),
                         "why": "evolver capability does not track base capability"})
    else:
        findings.append({"kind": "updating-separable", "spread": round(spread, 2)})
    wins = {str(r.get("benchmark")) for r in data if r.get("evolver") == best}
    if len(wins) <= 1:
        findings.append({"kind": "no-evolver-dominates"})
    return {"format": FORMAT, "evolvers": len(means), "best": best,
            "spread": round(spread, 2), "findings": findings}


def benefit(rows):
    """Per-agent maximum gain, and the shape against base capability."""
    data = [r for r in (rows or ()) if _num(r.get("gain")) is not None
            and _num(r.get("base")) is not None]
    if len(data) < 3:
        return {"format": FORMAT, "findings": [{"kind": "not-enough-agents"}]}
    ordered = sorted(data, key=lambda r: _num(r["base"]))
    gains = [_num(r["gain"]) for r in ordered]
    bases = [_num(r["base"]) for r in ordered]
    findings = []
    peak = max(range(len(gains)), key=lambda i: gains[i])
    if 0 < peak < len(gains) - 1:
        findings.append({"kind": "benefit-non-monotonic", "peak_index": peak,
                         "peak_base": bases[peak], "peak_gain": gains[peak]})
    elif peak == len(gains) - 1:
        findings.append({"kind": "benefit-monotonic"})
    if gains[-1] < gains[peak] and bases[-1] > bases[peak]:
        findings.append({"kind": "ceiling-effect", "strong_base": bases[-1]})
    if gains[0] <= gains[peak] / 2.0:
        findings.append({"kind": "weak-tier-left-behind", "weak_gain": gains[0]})
    if not findings:
        findings.append({"kind": "benefit-flat"})
    return {"format": FORMAT, "agents": len(data), "peak_base": bases[peak],
            "peak_gain": gains[peak], "findings": findings}


def activation(rows):
    """Did the agent bring a relevant harness artifact into context at all?"""
    data = [r for r in (rows or ()) if r.get("load_rate") is not None]
    if not data:
        return {"format": FORMAT, "findings": [{"kind": "no-activation-rows"}]}
    findings = []
    for r in data:
        rate = _num(r["load_rate"])
        if rate is not None and rate < 0.5:
            findings.append({"kind": "activation-failure", "model": r.get("model"),
                             "load_rate": rate,
                             "why": "the artifact never entered the context"})
    if not findings:
        findings.append({"kind": "activation-ok"})
    return {"format": FORMAT, "models": len(data), "findings": findings}


def adherence(rows):
    """Loaded is not followed, and following decays along the trajectory."""
    data = [r for r in (rows or ()) if r.get("follow_rate") is not None]
    if not data:
        return {"format": FORMAT, "findings": [{"kind": "no-adherence-rows"}]}
    findings = []
    for r in data:
        rate = _num(r["follow_rate"])
        if rate is not None and rate < 0.5:
            findings.append({"kind": "adherence-failure", "model": r.get("model"),
                             "follow_rate": rate,
                             "why": "the guidance was loaded but not followed"})
        drift = [_num(x) for x in (r.get("phase_scores") or ()) if _num(x) is not None]
        if len(drift) >= 2 and drift[0] - drift[-1] > 0.25:
            findings.append({"kind": "adherence-drift", "model": r.get("model"),
                             "drop": round(drift[0] - drift[-1], 2)})
    if not findings:
        findings.append({"kind": "adherence-ok"})
    return {"format": FORMAT, "models": len(data), "findings": findings}


def budget(rows):
    """Is the post-evolution score more about the agent than the evolver?"""
    data = [r for r in (rows or ()) if _num(r.get("score")) is not None
            and r.get("agent") is not None]
    if not data:
        return {"format": FORMAT, "findings": [{"kind": "no-pairing-rows"}]}
    by_agent = {}
    for r in data:
        by_agent.setdefault(str(r["agent"]), []).append(_num(r["score"]))
    within = max((max(v) - min(v) for v in by_agent.values() if len(v) > 1), default=0.0)
    gaps = [abs(statistics.mean(a) - statistics.mean(b))
            for i, a in enumerate(by_agent.values())
            for b in list(by_agent.values())[i + 1:]]
    between = max(gaps) if gaps else 0.0
    findings = []
    if within and between > 2.0 * within:
        findings.append({"kind": "budget-to-agent", "within": round(within, 2),
                         "between": round(between, 2)})
    else:
        findings.append({"kind": "budget-unresolved", "within": round(within, 2),
                         "between": round(between, 2)})
    return {"format": FORMAT, "within": round(within, 2), "between": round(between, 2),
            "findings": findings}


def pairing(row):
    """An extreme pairing should not reverse the agent order."""
    r = row or {}
    strong = _num(r.get("strong_agent_worst_evolver"))
    weak = _num(r.get("weak_agent_best_evolver"))
    if strong is None or weak is None:
        return {"format": FORMAT, "findings": [{"kind": "pairing-unmeasured"}]}
    if strong > weak:
        return {"format": FORMAT, "margin": round(strong - weak, 2),
                "findings": [{"kind": "agent-dominates", "margin": round(strong - weak, 2)}]}
    return {"format": FORMAT, "margin": round(strong - weak, 2),
            "findings": [{"kind": "evolver-reverses-order"}]}


def insitu(row):
    """A task's score must be locked before its own evidence updates the harness."""
    r = row or {}
    if r.get("scored_before_update") is True:
        return {"format": FORMAT, "findings": [{"kind": "insitu-ok"}]}
    return {"format": FORMAT, "findings": [{"kind": "task-sees-own-update",
                                            "why": "the task's evidence produced the harness that scored it"}]}


def advise(profile):
    """Map a harness profile onto the paper's failure modes."""
    p = profile or {}
    have = {str(key) for key, value in p.items() if value}
    findings = []
    checks = (
        ("separates_updating_and_benefit", "end-to-end-only", "two capabilities, two metrics"),
        ("pairs_agents_with_evolvers", "single-pair", "the grid is the measurement"),
        ("measures_activation", "assumes-harness-used", "was the artifact loaded at all"),
        ("measures_adherence", "assumes-instructions-followed", "was it followed along the trajectory"),
        ("reports_phase_drift", "first-turn-only", "adherence decays with horizon"),
        ("uses_in_situ_scoring", "leaky-updates", "lock a task's score before its evidence"),
        ("compares_within_and_between", "pooled-means", "the agent dominates the evolver"),
        ("tests_extreme_pairing", "average-only", "an extreme pairing should not reverse"),
    )
    for key, kind, why in checks:
        if key not in have:
            findings.append({"kind": kind, "why": why})
    return {"format": FORMAT, "findings": findings}
