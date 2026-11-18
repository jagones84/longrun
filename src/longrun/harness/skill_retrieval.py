#!/usr/bin/env python3
"""Skill retrieval from execution experience — matched comparisons, bounded keys.

Source: arXiv:2611.01115, "CompSkill: Compiling Execution Experience for Skill
Retrieval" (round 123). Description similarity cannot tell whether a particular
executor can use a skill, and a retrieved skill can hurt execution. CompSkill
learns from MATCHED same-task comparisons: two skills tried on one task with one
executor. Under an additive logistic outcome model the task's difficulty cancels,
so only discordant comparisons carry information, and the correction a key
receives is CAPPED and vanishes without discordant evidence (§3, Appendix B).

  * `calibrate(pairs)` — per-skill reliability offset from discordant matched
    comparisons only; every offset cites the comparison events that produced it.
  * `rank(candidates, learned)` — score = base + offset + clip(residual), sorted,
    each row carrying its cited events; a candidate with no evidence keeps its
    base score (no invented gain).
  * `apply(learned, skill)` — whether a correction may be written at all: no
    discordant comparison ⇒ no edit; a correction larger than the cap is clipped
    and reported.

Pure: comparison records in, calibrated offsets and a ranking out.
"""
from __future__ import annotations

FORMAT = "longrun-skill-retrieval/1"
CAP = 0.35


def _clamp(value, cap=CAP):
    return max(-cap, min(cap, float(value)))


def calibrate(pairs):
    """Only matched, discordant comparisons move a skill's offset (§3.2, KeyOpt)."""
    rows = [p for p in (pairs or []) if isinstance(p, dict)]
    stats = {}
    skipped = 0
    for i, pair in enumerate(rows):
        task = str(pair.get("task") or "")
        winner = str(pair.get("winner") or "")
        loser = str(pair.get("loser") or "")
        if not task or not winner or not loser or winner == loser:
            skipped += 1
            continue
        if pair.get("tie"):
            skipped += 1
            continue
        if pair.get("executor") is None:
            skipped += 1
            continue
        for skill, delta in ((winner, 1), (loser, -1)):
            s = stats.setdefault(skill, {"matches": 0, "wins": 0, "losses": 0,
                                         "events": []})
            s["matches"] += 1
            s["wins" if delta > 0 else "losses"] += 1
            s["events"].append({"pair": i, "task": task,
                                "executor": pair.get("executor"),
                                "role": "winner" if delta > 0 else "loser"})
    offsets = {}
    for skill, s in stats.items():
        raw = (s["wins"] - s["losses"]) / (1 + s["matches"])
        offsets[skill] = {"offset": round(_clamp(raw, CAP), 4),
                          "raw": round(raw, 4), "clipped": abs(raw) > CAP,
                          "discordant": s["matches"], "cited": s["events"]}
    return {"format": FORMAT, "offsets": offsets, "skipped": skipped,
            "why": "difficulty cancels inside a matched pair; a tie carries none"}


def rank(candidates, learned=None, cap=CAP):
    """Score = base + offset + clip(residual); an unevidenced skill is not moved."""
    offsets = (learned or {}).get("offsets") or {}
    rows = []
    for cand in candidates or ():
        if not isinstance(cand, dict):
            continue
        skill = str(cand.get("skill") or "")
        base = float(cand.get("base") or 0.0)
        learned_row = offsets.get(skill) or {}
        offset = float(learned_row.get("offset") or 0.0)
        residual = _clamp(cand.get("residual") or 0.0, cap)
        rows.append({"skill": skill, "score": round(base + offset + residual, 4),
                     "base": round(base, 4), "offset": offset,
                     "residual": round(residual, 4),
                     "learned": bool(learned_row),
                     "cited": list(learned_row.get("cited") or [])})
    rows.sort(key=lambda r: (-r["score"], r["skill"]))
    return {"format": FORMAT, "ranking": rows,
            "why": "experience changes which document is chosen, never its text"}


def apply(learned, skill):
    """May a correction be written for this skill, and is it inside the cap?"""
    row = ((learned or {}).get("offsets") or {}).get(str(skill))
    if not row:
        return {"format": FORMAT, "write": False, "skill": str(skill),
                "findings": [{"kind": "no-discordant-evidence", "why":
                              "no matched comparison separated this skill from its alternative"}],
                "why": "a correction without evidence would be invented"}
    findings = []
    if row.get("discordant", 0) < 2:
        findings.append({"kind": "single-comparison", "why":
                         "one matched pair is not a reliability estimate"})
    if row.get("clipped"):
        findings.append({"kind": "correction-clipped", "raw": row.get("raw"),
                         "offset": row.get("offset"), "cap": CAP})
    return {"format": FORMAT, "write": row.get("discordant", 0) >= 2,
            "skill": str(skill), "offset": row.get("offset"),
            "findings": findings,
            "why": ("bounded by the cap and cited to its comparisons"
                    if not findings else "the edit is bounded; read the finding")}
