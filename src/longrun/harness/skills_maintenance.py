#!/usr/bin/env python3
"""Skill staleness — what a skill still claims that the harness no longer has.

Source: arXiv:2611.22525, "When Agent Skills Go Stale: Runtime Behavior and
Selective Maintenance in Evolving Environments" (round 109). Its measured point:
after an environment change a previously beneficial skill can cost more than 10
percentage points of success or nearly 40% of execution cost, and SKILL SUCCESS
CAN STAY FLAT WHILE THE SAVINGS VANISH. Its repair is "selective maintenance":
replay checks from successful executions without model calls, find where the
observed state conflicts with the skill's state, repair that content, validate.

Longrun ships skills as markdown (`skills/**/SKILL.md`) that name tools in
backticks and point at repository paths. When a tool is renamed or a file moves,
the skill keeps instructing the model to call something that no longer exists —
silently, because the model then improvises. `retire_unused_skills` only ages a
skill out by usage; nothing checks that what it SAYS still resolves.

  audit(text)    stale tool references and dead paths, with line numbers;
  maintain(dir)  the audit over a skill tree (read-only);
  repair(text, mapping)  exact, caller-supplied renames, returning the diff.

No model call, no guessing: an unknown name is reported, never silently
"fixed".
"""
from __future__ import annotations

import difflib
import os
import re

FORMAT = "longrun-skill-maintenance/1"
_TOKEN = re.compile(r"`([^`\n]{1,120})`")
_TOOLISH = re.compile(r"^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)+$")
_PATHISH = re.compile(r"^(?:\.?/)?(?:[\w.@+-]+/)+[\w.@+*-]+$")
# Only paths anchored to the harness checkout are auditable. A skill that says
# `design/game-brief.md` is naming an artifact in the USER's workspace, which may
# legitimately not exist yet — reporting it would make every authoring skill
# "stale" (measured: 74 of 82 on the shipped tree before this filter).
_REPO_PREFIX = ("src/", "config/", "skills/", ".agent/")


def _names():
    try:
        from longrun.tools import registry
        return set(registry.tool_names())
    except Exception:  # noqa: BLE001
        return set()


def audit(text, repo=None, names=None, repo_root=None):
    """Findings for one skill text: stale tool references and dead paths."""
    repo = repo_root or repo or os.getcwd()
    names = set(names) if names is not None else _names()
    out = []
    for i, line in enumerate(str(text or "").splitlines(), 1):
        for tok in _TOKEN.findall(line):
            tok = tok.strip()
            if _TOOLISH.match(tok):
                ns = tok.split(".", 1)[0] + "."
                near = sorted(n for n in names if n.startswith(ns))
                if not near:
                    continue
                if tok in names:
                    continue
                # Two high-precision signals that this token is a TOOL reference
                # and not a config key (`team.size`, `docs.density`): a close
                # catalog neighbour (a typo/rename), or an explicit tool word on
                # the same line. Anything else stays out of the report.
                close = difflib.get_close_matches(tok, near, n=4, cutoff=0.8)
                low = line.lower()
                if not close and "tool" not in low and "action" not in low:
                    continue
                out.append({"kind": "tool", "value": tok, "line": i,
                            "reason": "no such tool in the catalog",
                            "candidates": (close or near)[:4]})
                continue
            if _PATHISH.match(tok) and not tok.endswith("/"):
                if tok.startswith(("http", "~")):
                    continue
                if not (tok.startswith(_REPO_PREFIX) or os.path.isabs(tok)):
                    continue
                full = tok if os.path.isabs(tok) else os.path.join(repo, tok)
                if not os.path.exists(full):
                    out.append({"kind": "path", "value": tok, "line": i,
                                "reason": "path does not exist"})
    return {"format": FORMAT, "findings": out, "stale": bool(out)}


def maintain(root, repo=None, names=None):
    """Audit every `SKILL.md` under `root` (read-only)."""
    repo = repo or os.getcwd()
    names = set(names) if names is not None else _names()
    skills, stale = [], []
    for base, dirs, files in os.walk(str(root)):
        dirs[:] = sorted(d for d in dirs if d not in (".git", "__pycache__"))
        if "SKILL.md" not in files:
            continue
        path = os.path.join(base, "SKILL.md")
        try:
            with open(path, encoding="utf-8", errors="replace") as fh:
                text = fh.read()
        except OSError:
            continue
        res = audit(text, repo=repo, names=names)
        name = os.path.basename(base)
        skills.append({"skill": name, "path": path,
                       "findings": len(res["findings"])})
        if res["stale"]:
            stale.append({"skill": name, "path": path, "findings": res["findings"]})
    return {"format": FORMAT, "skills": skills, "stale": stale,
            "counts": {"skills": len(skills), "stale": len(stale)}}


def repair(text, mapping):
    """Apply exact `{old: new}` renames; return the new text and the changes."""
    out = str(text or "")
    changes = []
    for old, new in (mapping or {}).items():
        if not old or old == new:
            continue
        n = out.count(str(old))
        if n:
            out = out.replace(str(old), str(new))
            changes.append({"from": old, "to": new, "count": n})
    return {"format": FORMAT, "text": out, "changes": changes}
