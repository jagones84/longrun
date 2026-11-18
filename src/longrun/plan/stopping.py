#!/usr/bin/env python3
"""Anytime stopping — has the patch already passed, and is the work after that useful?

Source: arXiv:2611.22901, "Done, But Still Working: Anytime Evaluation of When
Coding Agents Should Stop" (round 109). Coding agents keep working after their
own tests pass; measured over ~6,000 runs the hindsight saving available at that
moment ranges from under 1% to 57%, depending on model and scaffold. A simple
rule — stop after the SAME patch passes twice — saved 23% in a preregistered
replication, with quality preservation not established as non-inferior.

Longrun already has a continuation policy (`plan/keepgoing.decide`) that knows
about open nodes, stale rounds and budgets — but nothing that reads the tool
cards for the paper's two facts: when a verification first passed, and whether
anything changed after the last pass.

  analyze(cards)  first pass, last pass, post-pass steps, writes after a pass,
                  whether the same patch passed twice, and the advice
  rule_text()     the rule, in one line, for a prompt or a report

Read-only over the stored cards; no model, no state.
"""
from __future__ import annotations

import json
import re

FORMAT = "longrun-anytime-stop/1"
_TEST_CMD = re.compile(
    r"(?i)\b(pytest|py\.test|tox|npm\s+(run\s+)?test|yarn\s+test|pnpm\s+test|"
    r"gradle\s+(test|check)|mvn\s+(test|verify)|go\s+test|cargo\s+(test|nextest)|"
    r"make\s+(test|check)|ctest|rspec|jest|vitest|phpunit)\b")
_VERIFY_TOOLS = ("shell", "python", "sandbox")
_WRITE_PREFIX = ("fs.write", "fs.edit", "fs.append", "edits.apply", "git.apply",
                 "matrix.write")


def _args(card):
    raw = card.get("args")
    if isinstance(raw, dict):
        return raw
    try:
        return json.loads(raw) if raw else {}
    except (TypeError, ValueError):
        return {}


def _tool(card):
    return str(card.get("tool") or "")


def _passed(card):
    return card.get("ok") is not False and card.get("exit_code") == 0


def _is_verification(card):
    if not _tool(card).startswith(_VERIFY_TOOLS):
        return False
    cmd = str(_args(card).get("command") or _args(card).get("code") or "")
    return bool(_TEST_CMD.search(cmd))


def _is_write(card):
    tool = _tool(card)
    return any(tool == p or tool.startswith(p + ".") for p in _WRITE_PREFIX)


def rule_text():
    return ("stop after the same patch passes the test command twice (arXiv:2611.22901); "
            "each further step is paid work whose patch may already be correct")


def analyze(cards):
    """The anytime view of one run's tool cards."""
    rows = [c for c in (cards or []) if isinstance(c, dict)]
    passes = [i for i, c in enumerate(rows) if _is_verification(c) and _passed(c)]
    writes = [i for i, c in enumerate(rows) if _is_write(c)]
    out = {"format": FORMAT, "steps": len(rows), "rule": rule_text(),
           "first_pass": passes[0] if passes else None,
           "last_pass": passes[-1] if passes else None,
           "pass_count": len(passes)}
    if not passes:
        out.update({"post_pass_steps": 0, "writes_after_pass": 0,
                    "repeat_pass": False, "verdict": "no-verification"})
        return out
    first = passes[0]
    post = len(rows) - first - 1
    writes_after = [i for i in writes if i > first]
    # "the same patch passes twice": two passing verifications with no write
    # between them. Any write in between makes it a different patch.
    repeat = False
    for a, b in zip(passes, passes[1:]):
        if not any(a < i < b for i in writes):
            repeat = True
            break
    out.update({"post_pass_steps": post,
                "writes_after_pass": len(writes_after),
                "repeat_pass": repeat})
    if repeat and not [i for i in writes_after if i > passes[-1]]:
        out["verdict"] = "stop-now"
        out["saving_steps"] = len(rows) - passes[-1] - 1
    elif repeat:
        out["verdict"] = "continue-then-stop-after-repeat-pass"
        out["saving_steps"] = 0
    else:
        out["verdict"] = "verify-again-before-stopping"
        out["saving_steps"] = 0
    out["wasted_ratio"] = round(post / float(len(rows)), 4) if rows else 0.0
    return out
