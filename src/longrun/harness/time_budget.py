#!/usr/bin/env python3
"""Wall-clock budget warning — tell the model how much of the turn is left.

Source: LangChain, "Improving Deep Agents with harness engineering"
(2026-02-17). Its third lever injected time-budget warnings to nudge the agent
to finish and shift to verification: "agents are famously bad at time
estimation so this heuristic helps in this environment." It was applied where a
timeout would otherwise cut the run off with nothing submitted.

Longrun enforces a wall-clock cap (`plan/keepgoing.DEFAULTS["max_wall_secs"]`,
3600 s) and stops the turn when it is spent (`keepgoing.decide` -> "budget"),
but the model is never told the cap exists — it learns only by being cut off.
This module returns one note at 75% (shift to verification) and one at 90%
(finish now).

  check(started, now, cap, fired)  -> (stage|"", note)
  text(remaining, cap, stage)      -> the note

`fired` is a set the caller owns (one per turn). Pure arithmetic, no clock here.
"""
from __future__ import annotations

FORMAT = "longrun-time-budget/1"

# (fraction of the cap consumed, stage name); the LAST reached stage wins, so a
# turn that jumps from 0.7 to 0.95 gets the urgent note, not both.
STAGES = ((0.75, "shift"), (0.90, "final"))


def _minutes(seconds):
    return max(1, int(round(float(seconds) / 60.0)))


def check(started, now, cap, fired=None):
    """The stage reached (once) and its note, or ("", "")."""
    fired = fired if isinstance(fired, set) else set()
    try:
        started, now, cap = float(started), float(now), float(cap or 0)
    except (TypeError, ValueError):
        return "", ""
    if cap <= 0 or now < started:
        return "", ""
    fraction = (now - started) / cap
    stage = ""
    for at, name in STAGES:
        if fraction >= at:
            stage = name
    if not stage or stage in fired:
        return "", ""
    return stage, text(max(0.0, cap - (now - started)), cap, stage)


def text(remaining, cap, stage):
    """The note for one stage. Names only the budget and the next action."""
    left = _minutes(remaining)
    total = max(1, int(round(float(cap) / 60.0)))
    unit = "minute" if left == 1 else "minutes"
    if stage == "final":
        return ("SYSTEM (harness) — TIME: about %d %s of the %d-minute budget "
                "remains. Stop exploring: verify what you have, finish the open "
                "step you are on, and deliver the answer." % (left, unit, total))
    return ("SYSTEM (harness) — TIME: about %d %s of the %d-minute budget "
            "remains. Shift from new work to verification and closure: run the "
            "check, fix what it reports, then answer." % (left, unit, total))
