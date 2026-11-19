#!/usr/bin/env python3
"""Autonomy pillars — grant autonomy only for actions that are bounded,
observable and reversible.

Source: arXiv:2611.10058, "From Delegation to Action Approval: An Exploratory
Study of Developers' Practices in Collaborating with AI Coding Agents" (round
112). Survey of 203 developers: careful code review does not extend to action
approval (61% who carefully reviewed code still approved at least one action
type without close review), and when asked what would make them grant MORE
autonomy, more than half asked for agents that are **bounded, observable or
reversible** — not merely more reliable.

This module turns that finding into a deterministic scorecard for a proposed
action class:

  * bounded     — a tool allowlist AND a per-run budget exist;
  * observable  — the call requires an intent declaration AND the journal is on;
  * reversible  — the action is read-only OR a checkpoint exists.

All three -> `autonomous`; bounded+observable but not reversible -> `approve-each`
(the operator keeps the irreversible step); anything else -> `supervised`.
It never grants more autonomy for unreliability, and it names the missing pillar.

Pure: facts in, verdict out.
"""
from __future__ import annotations

FORMAT = "longrun-autonomy/1"
PILLARS = ("bounded", "observable", "reversible")


def pillars(facts):
    f = facts or {}
    return {
        "bounded": bool(f.get("allowlist")) and bool(f.get("budget")),
        "observable": bool(f.get("intent_required")) and bool(f.get("journal")),
        "reversible": bool(f.get("read_only")) or bool(f.get("checkpoint")),
    }


def evaluate(action, facts):
    got = pillars(facts)
    missing = [p for p in PILLARS if not got[p]]
    if not missing:
        tier, verdict = "autonomous", "grant"
    elif got["bounded"] and got["observable"]:
        tier, verdict = "approve-each", "grant-with-approval"
    else:
        tier, verdict = "supervised", "withhold"
    return {"format": FORMAT, "action": str(action or ""), "pillars": got,
            "missing": missing, "tier": tier, "verdict": verdict}


def scoreboard(rows):
    """rows: [{"action": ..., **facts}] — one line per proposed action class."""
    out = []
    tiers = {}
    for row in rows or ():
        if not isinstance(row, dict):
            continue
        res = evaluate(row.get("action"), row)
        out.append(res)
        tiers[res["tier"]] = tiers.get(res["tier"], 0) + 1
    return {"format": FORMAT, "actions": out, "tiers": dict(sorted(tiers.items())),
            "granted": sum(1 for r in out if r["verdict"] == "grant"),
            "withheld": sum(1 for r in out if r["verdict"] == "withhold")}
