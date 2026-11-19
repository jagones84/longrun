#!/usr/bin/env python3
"""Skill pruning — cut instruction bloat, but only behind an accuracy guard.

Source: arXiv:2611.19823, "EfficientSkill: Learning Skills for Token-Efficient
Multi-Turn Agents" (round 112). Reflective skill optimisation accumulates
edge-case rules until instructions bloat the prompt, inflate tokens and push the
agent into long error-prone loops. Its second phase prunes episodic output tokens
under a validation gate of at least 0.90 of the validated skill's accuracy, and
offloads reusable code to workspace utilities with no prompt cost.

This module is the deterministic pruner plus the guard, with one hard rule the
paper's setting makes obvious: a line that names a TOOL or a PATH is a contract
line and is never dropped by this module. Pruning removes duplication, explicit
optional markers and (under a budget) trailing prose; it never removes the
command the skill exists to teach.

  * `prune(text, budget_tokens=None)` — returns the compact text, the dropped
    lines with reasons, and the estimated tokens before/after (chars / 4);
  * `guard(before_acc, after_acc, floor=0.90)` — adoption is allowed only when
    the after accuracy keeps the paper's 90% gate.

Pure: text in, text and ledger out.
"""
from __future__ import annotations

import re

FORMAT = "longrun-skill-prune/1"
_CONTRACT = re.compile(r"`[^`\n]+`|(?:\.?/)?[\w.@+-]+/[\w.@+*-]+")
_OPTIONAL = re.compile(r"<!--\s*optional\s*-->|^\s*optional\s*:", re.I)


def estimate_tokens(text):
    return (len(text or "") + 3) // 4


def _norm(line):
    return " ".join(line.strip().lower().split())


def prune(text, budget_tokens=None):
    lines = (text or "").splitlines()
    keep = []
    dropped = []
    seen = set()
    in_fence = False
    for i, line in enumerate(lines, 1):
        stripped = line.strip()
        if stripped.startswith("```"):
            in_fence = not in_fence
            keep.append(line)
            continue
        if in_fence or stripped.startswith("#") or stripped in ("---", ""):
            keep.append(line)
            continue
        if _OPTIONAL.search(line):
            dropped.append({"line": i, "text": stripped, "reason": "explicitly optional"})
            continue
        norm = _norm(line)
        if norm and norm in seen:
            dropped.append({"line": i, "text": stripped, "reason": "duplicate line"})
            continue
        if norm:
            seen.add(norm)
        keep.append(line)
    if budget_tokens:
        # Drop trailing prose (never a contract line, never a heading) until the
        # estimate fits; the command lines stay even if the budget cannot be met.
        idx = len(keep) - 1
        while estimate_tokens("\n".join(keep)) > int(budget_tokens) and idx >= 0:
            line = keep[idx]
            stripped = line.strip()
            if (stripped and not stripped.startswith("#") and stripped != "---"
                    and not _CONTRACT.search(line)):
                dropped.append({"line": idx + 1, "text": stripped,
                                "reason": "over the token budget"})
                del keep[idx]
            idx -= 1
    out = "\n".join(keep)
    return {"format": FORMAT, "text": out,
            "tokens_before": estimate_tokens(text), "tokens_after": estimate_tokens(out),
            "dropped": dropped, "kept_lines": len(keep)}


def guard(before_acc, after_acc, floor=0.90):
    """Adoption gate: the compact skill must keep at least `floor` of the accuracy."""
    try:
        before = float(before_acc)
        after = float(after_acc)
    except (TypeError, ValueError):
        return {"format": FORMAT, "verdict": "not-measured",
                "reason": "both accuracies are required"}
    need = round(before * float(floor), 4)
    ok = after >= need
    return {"format": FORMAT, "before": before, "after": after, "floor": floor,
            "required": need, "delta": round(after - before, 4),
            "verdict": "safe-to-adopt" if ok else "regression"}
