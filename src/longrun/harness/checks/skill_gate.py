#!/usr/bin/env python3
"""Skill gate — admission before the pool, because contamination is irreversible.

Source: arXiv:2608.05810, "When Self-Evolution Backfires: Pre-Commit Gating
against Skill Contamination in LLM Agents" (round 156). Unconditional skill
accumulation is not monotone: pass@1 peaks at a critical pool size and then falls
back, because a defective skill becomes reference material for later distillation
(`skill_contamination_gate_2608.05810.txt:16`, `:29`).

  * **three contamination levels**: individual (a singleton hurts), combinatorial
    (two harmless skills conflict together) and systemic (the non-monotone curve)
    (`:139`, `:141`, `:150`).
  * **removal does not undo it**: skills are distilled conditioned on the live
    pool, so descendants inherit the flawed reasoning; source-only rollback
    recovers 1.7 of a 12.3-point drop and even oracle lineage cleanup only 6.7
    (`:402`, `:404`).
  * **Gate 1 is a conjunction** of structural validity, a single-skill A-B replay
    and one semantic review, because each critic intercepts a disjoint class
    (`:208`, `:353`).
  * **Gate 2 is marginal-gain subset selection**: add a Warm candidate only when
    it improves measured joint performance (`:231`, `:243`).

  * `tiers()` — the Cold/Warm/Hot hierarchy and its gates.
  * `critic(record)` — Gate 1's three checks and their conjunction.
  * `gain(record)` — the injection gain g(A, τ).
  * `taxonomy(record)` — individual vs combinatorial classification.
  * `curve(rows)` — the capability–contamination tipping point.
  * `select(candidates)` — Gate 2: marginal-gain greedy promotion to Hot,
    eligible only for candidates whose Gate 1 verdict is `promote-warm`.
  * `irreversibility(record)` — the recovery gap after post-hoc rollback.
  * `audit_record(record)` / `advise(profile)` — misreadings and mapping.

Pure: measured rates, candidate lists and recovery numbers in; verdicts out.
"""
from __future__ import annotations

FORMAT = "longrun-skill-gate/1"

TIERS = ("cold", "warm", "hot")


def _num(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def tiers():
    """The progressive trust hierarchy and what each transition requires."""
    return {"format": FORMAT, "tiers": list(TIERS),
            "gates": {"cold_to_warm": ["schema", "replay", "semantic"],
                      "warm_to_hot": ["marginal-gain"]},
            "default": "cold", "verdict": "hierarchy"}


def critic(record):
    """Gate 1: a skill is admitted only if all three critics pass."""
    r = record or {}
    schema = r.get("schema_ok") is True
    delta = _num(r.get("replay_delta"))
    semantic = r.get("semantic_ok") is True
    if delta is None:
        return {"format": FORMAT, "verdict": "insufficient-input"}
    checks = {"schema": schema, "replay": delta >= 0, "semantic": semantic}
    failed = [name for name, ok in checks.items() if not ok]
    return {"format": FORMAT, "checks": checks, "replay_delta": delta,
            "failed": failed,
            "verdict": "promote-warm" if not failed else "reject"}


def gain(record):
    """g(A, τ) = R(M ∪ A, τ) − R(M, τ)."""
    r = record or {}
    pooled = _num(r.get("pool_rate"))
    injected = _num(r.get("injected_rate"))
    if pooled is None or injected is None:
        return {"format": FORMAT, "verdict": "insufficient-input"}
    delta = injected - pooled
    return {"format": FORMAT, "gain": delta,
            "verdict": "individually-harmful" if delta < 0 else "individually-safe"}


def taxonomy(record):
    """Individual harm, or a pair that only conflicts together."""
    r = record or {}
    singles = [_num(v) for v in (r.get("singletons") or [])]
    singles = [v for v in singles if v is not None]
    pair = _num(r.get("pair_gain"))
    if any(v < 0 for v in singles):
        return {"format": FORMAT, "level": "individual",
                "verdict": "individual-contamination"}
    if pair is not None and pair < 0 and singles and all(v >= 0 for v in singles):
        return {"format": FORMAT, "level": "combinatorial",
                "verdict": "combinatorial-contamination"}
    if pair is not None and pair >= 0:
        return {"format": FORMAT, "level": "none", "verdict": "compatible"}
    return {"format": FORMAT, "level": "unknown", "verdict": "insufficient-input"}


def curve(rows):
    """P(k): does capability peak and then fall back?"""
    points = []
    for row in rows or []:
        r = row or {}
        pool = _num(r.get("pool"))
        rate = _num(r.get("rate"))
        if pool is None or rate is None:
            continue
        points.append({"pool": pool, "rate": rate,
                       "round": r.get("round")})
    if len(points) < 3:
        return {"format": FORMAT, "verdict": "too-few-points"}
    peak = max(points, key=lambda p: p["rate"])
    last = points[-1]
    before = [p["rate"] for p in points if p["pool"] <= peak["pool"]]
    monotone_before = all(before[i] <= before[i + 1] for i in range(len(before) - 1))
    falls = last["rate"] < peak["rate"]
    return {"format": FORMAT, "points": points, "peak": peak,
            "last": last, "drop": peak["rate"] - last["rate"],
            "monotone_before_peak": monotone_before,
            "verdict": "phase-transition" if falls and monotone_before
            else "monotone"}


def select(candidates):
    """Gate 2: marginal-gain greedy over the candidates that cleared Gate 1.

    Gate 1 is a prerequisite, not a separate report: a candidate is eligible only
    when its own `critic()` record is `promote-warm` (schema + replay + semantic).
    A candidate that fails a critic — or carries no evidence at all — is listed
    in `unadmitted` and can never be promoted on gain alone (`:208`).

    Interaction convention, stated once and applied to both the greedy objective
    and the reported total: `candidate["interactions"][other_id]` is the EXTRA
    gain THIS candidate contributes when `other_id` is already Hot. It is
    directed: when a candidate joins the pool, what it adds is its own
    interaction with each skill already there. Its interaction with a skill that
    joins LATER is never used, because that union never happened. The reported
    `gain` therefore equals the objective the greedy loop maximised — every
    added candidate is counted once, with `hot[:i]` as its context, so no pair is
    counted twice and no reverse edge influences the result.
    """
    rows = []
    unadmitted = []
    seen = set()
    for index, item in enumerate(candidates or []):
        c = item or {}
        base = _num(c.get("gain"))
        if base is None:
            continue
        row = {"id": str(c.get("id") or index),
               "gain": base,
               "interactions": {str(k): _num(v) or 0.0
                                for k, v in (c.get("interactions") or {}).items()}}
        if row["id"] in seen:
            # An id is a candidate's identity: a duplicate cannot be tracked as a
            # second candidate, and the greedy removal used to drop BOTH copies
            # silently (neither hot, rejected nor unadmitted).
            unadmitted.append(row["id"])
            continue
        seen.add(row["id"])
        if critic(c).get("verdict") != "promote-warm":
            unadmitted.append(row["id"])
            continue
        rows.append(row)
    if not rows and not unadmitted:
        return {"format": FORMAT, "verdict": "no-candidates"}
    hot = []
    rejected = []
    remaining = list(rows)
    steps = 0
    while remaining:
        best = None
        best_gain = None
        for cand in remaining:
            joint = cand["gain"] + sum(
                cand["interactions"].get(h["id"], 0.0) for h in hot)
            if best_gain is None or joint > best_gain:
                best, best_gain = cand, joint
        steps += 1
        if best_gain is None or best_gain <= 0:
            rejected.extend([c["id"] for c in remaining])
            break
        hot.append(best)
        remaining = [c for c in remaining if c["id"] != best["id"]]
    total = 0.0
    for i, cand in enumerate(hot):
        total += cand["gain"]
        for earlier in hot[:i]:
            total += cand["interactions"].get(earlier["id"], 0.0)
    return {"format": FORMAT, "hot": [c["id"] for c in hot],
            "rejected": rejected, "unadmitted": unadmitted, "steps": steps,
            "gain": total, "verdict": "promoted" if hot else "no-promotion"}


def irreversibility(record):
    """How much of a collapse post-hoc removal can recover."""
    r = record or {}
    peak = _num(r.get("peak"))
    after = _num(r.get("after"))
    source = _num(r.get("source_recovery"))
    lineage = _num(r.get("lineage_recovery"))
    if peak is None or after is None or source is None:
        return {"format": FORMAT, "verdict": "insufficient-input"}
    drop = peak - after
    share = (source / drop) if drop > 0 else None
    residual = drop - source
    return {"format": FORMAT, "drop": drop, "source_share": share,
            "source_recovery": source,
            "lineage_recovery": lineage,
            "residual_after_source": residual,
            "verdict": "irreversible" if residual > 0 else "reversible"}


def rollback(record):
    """Removing a source leaves its descendants behind."""
    r = record or {}
    source = str(r.get("source") or "")
    edges = r.get("derived") or {}
    seen = {source}
    frontier = [source]
    while frontier:
        node = frontier.pop()
        for child in edges.get(node) or []:
            child = str(child)
            if child not in seen:
                seen.add(child)
                frontier.append(child)
    return {"format": FORMAT, "descendants": sorted(seen - {source}),
            "lineage": sorted(seen),
            "verdict": "lineage-traced" if len(seen) > 1 else "no-descendants"}


def audit_record(record):
    """The misreadings the paper's design excludes."""
    r = record or {}
    findings = []
    if r.get("skill_utility_is_monotone") is True:
        findings.append({"kind": "skill-utility-is-monotone",
                         "why": "past the critical pool size new skills hurt"})
    if r.get("removal_is_cleanup") is True:
        findings.append({"kind": "removal-is-cleanup",
                         "why": "descendants keep the inherited reasoning"})
    if r.get("judge_only_in_isolation") is True:
        findings.append({"kind": "judge-only-in-isolation",
                         "why": "individually harmless skills can conflict"})
    if r.get("one_critic_is_enough") is True:
        findings.append({"kind": "one-critic-is-enough",
                         "why": "the three critics fail on disjoint classes"})
    if r.get("pool_growth_is_progress") is True:
        findings.append({"kind": "pool-growth-is-progress",
                         "why": "a 5x smaller gated pool scores higher"})
    if r.get("admission_is_bookkeeping") is True:
        findings.append({"kind": "admission-is-bookkeeping",
                         "why": "admission is the last point contamination can be stopped"})
    if not findings:
        findings.append({"kind": "audit-conditions-met"})
    return {"format": FORMAT, "findings": findings, "verdict": "audit-complete"}


def advise(profile):
    """Map a harness profile onto the skill-admission gaps the paper names."""
    p = profile or {}
    have = {str(k) for k, v in p.items() if v}
    checks = (
        ("keeps_new_skills_cold", "writes_skills_straight_to_context",
         "an ungated skill steers behaviour immediately"),
        ("conjoins_three_critics", "checks_format_only",
         "each critic intercepts a different harmful class"),
        ("replays_a_single_skill_on_holdout", "judges_a_skill_by_reading_it",
         "behavioural harm is invisible in the text"),
        ("selects_for_joint_gain", "admits_every_survivor",
         "skills that pass alone can conflict together"),
        ("records_parent_context", "stores_skills_without_lineage",
         "removal without descendants cannot undo contamination"),
        ("compares_pool_against_a_baseline", "tracks_pool_size_only",
         "a larger pool is not a better pool"),
    )
    findings = []
    for key, kind, why in checks:
        if key not in have:
            findings.append({"kind": kind, "why": why})
    return {"format": FORMAT, "findings": findings}
