#!/usr/bin/env python3
"""Completion signal — stop exploring once a recorded check establishes the work.

Sources (round 167):
  * arXiv:2611.25896, "The Price of an Explanation" — a checkable artifact lets a
    run stop as soon as it is verified: sampling declines 38% of its budget and a
    search arm 49%, while an answer-only arm has no checked signal to stop on
    (`price-of-an-explanation_2611.25896.md:28`, `:115`). The same paper measures
    the cost of over-demanding artifacts (93 → 68 of 120 tasks), so this module
    never demands one; it only recognises a check the agent already ran.
  * arXiv:2611.25146, "EverydayBench" — completion is judged by fixed success
    criteria checked against the submission, not by the agent's claim
    (`everydaybench-live-work_2611.25146.md:32`, `:56`).
  * arXiv:2611.25380, "Beyond Weight Updates" — harness edits (prompt, tools,
    planning scaffolding) specialize behaviour without touching weights; a
    stopping policy is such an edit (`beyond-weight-updates-harness-evolution_2611.25380.md:36`).

The signal is deliberately narrow: a verification command in the turn's own trace
(through `memory.anchors.CHECK_RE`, the one owner of that list) that exited
successfully AND is followed by a pass marker in its own output, with no open
plan step. Then the harness replaces its "call the next tool" nudge with "the
recorded check passed — answer now". It never ends the turn itself and never
claims the task is done.

Pure: cards in, a signal out.
"""
from __future__ import annotations

import json
import re

from longrun.memory.anchors import CHECK_RE

FORMAT = "longrun-completion-signal/1"

#: What a PASSING check says in its own output. A bare exit code is not enough:
#: `make` exits 0 after "Nothing to be done", and a filtered log can hide a failure.
PASS = re.compile(
    r"(?i)(\b\d+\s+passed\b|\b0\s+failed\b|\ball tests pass|\bgreen\b|"
    r"\bok\b|\bsucceeded\b|\bsuccess\b|\bno (?:errors|failures|warnings)\b|"
    r"\bbattery:?\s*\d+/\d+\b|\b\d+/\d+\s+(?:tests?|checks?)\b)")
FAIL = re.compile(
    r"(?i)(\bfail(?:ed|ures?)?\b|\berror\b|\bnot ok\b|\bfailures\b|\b\d+\s+failed\b)")


def _args(card):
    raw = (card or {}).get("args")
    if isinstance(raw, dict):
        return raw
    try:
        got = json.loads(raw or "{}")
    except (TypeError, ValueError):
        return {}
    return got if isinstance(got, dict) else {}


def _command(card):
    args = _args(card)
    return str(args.get("command") or args.get("cmd") or "").strip()


def detect(cards):
    """The LAST successful check in `cards`, or {"verified": False}."""
    found = {"format": FORMAT, "verified": False}
    for index, card in enumerate(cards or []):
        if not isinstance(card, dict) or card.get("ok") is False:
            continue
        command = _command(card)
        if not command or not CHECK_RE.search(command):
            continue
        output = str(card.get("output") or card.get("result") or "")
        if not output or not PASS.search(output):
            continue
        # A pass marker next to a failure line is not a verified pass (a filtered
        # log can show "1 passed" while another test failed).
        if re.search(r"(?i)\b[1-9]\d*\s+failed\b", output):
            continue
        found = {"format": FORMAT, "verified": True, "command": command[:200],
                 "step": index + 1, "evidence": output[:200]}
    return found


def text(record):
    """The replacement for the generic 'call the next tool' nudge, or ""."""
    if not (record or {}).get("verified"):
        return ""
    return ("The recorded check `%s` passed at step %s%s. If your plan has no open "
            "step, answer now with the result and that evidence — do NOT start "
            "another exploratory call." % (
                (record.get("command") or "the check")[:120],
                record.get("step"),
                (" (%s)" % record.get("evidence").strip()[:100])
                if record.get("evidence") else ""))


def should(record, open_steps=0, already=False):
    """Fire once, only for a verified check with no open plan step."""
    return bool((record or {}).get("verified")) and not int(open_steps or 0) \
        and not already


def summary(rows):
    """How often a turn had a verified check to stop on, and when it stopped."""
    rows = [r for r in (rows or []) if isinstance(r, dict)]
    if not rows:
        return {"format": FORMAT, "verdict": "no-rows"}
    verified = sum(1 for r in rows if r.get("verified"))
    early = sum(1 for r in rows if r.get("verified") and r.get("stopped_after"))
    return {"format": FORMAT, "turns": len(rows), "verified": verified,
            "stopped_after": early,
            "stop_rate": round(early / verified, 4) if verified else None,
            "verdict": "verified-stop" if early else "no-early-stop"}
