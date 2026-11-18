#!/usr/bin/env python3
"""Conflict surfacing — keep the contradiction, do not collapse it to a winner.

Source: arXiv:2611.22461, "Surfacing Disagreement Beats Resolving It: A Gated
Ablation Study of Provenance-Weighted Memory for Multi-Agent Debate" (round 114).
Shared memory usually resolves inconsistency before any agent sees it. The study
removes mechanisms one at a time; the ONE that survives preserves contradictions
and passes the ranked conflict set to the debate: +0.340 F1 and attack success
cut from 22 to 7 of 122 poisoned items at equal cost. Two other mechanisms are
WORSE than inert once contradictions reach the prompt: a write trust-gate
(-0.075 F1) and router provenance features (-0.096 F1). It also names its own
harness bug honestly: a pre-declared cap over conflict sets left three quarters
of planted contradictions unretrievable, and the mechanism first measured only
+0.084.

This module renders a claim set the way that result asks:

  * group claims by (subject, relation);
  * every group with more than one object is a CONFLICT and is rendered with ALL
    values and their sources — no winner, no trust filter;
  * groups with one object are AGREED facts;
  * a cap may be applied, but the number of omitted conflicts is REPORTED, never
    silently dropped (the paper's own bottleneck).

Pure: claims in, text out.
"""
from __future__ import annotations

FORMAT = "longrun-conflict-surface/1"


def _row(c):
    c = c or {}
    return {"subject": str(c.get("subject") or "").strip(),
            "relation": str(c.get("relation") or "").strip(),
            "object": str(c.get("object") or "").strip(),
            "source": str(c.get("source") or c.get("id") or "").strip()}


def conflicts(claims, cap=None):
    groups = {}
    for c in (claims or ()):
        row = _row(c)
        if not (row["subject"] and row["relation"] and row["object"]):
            continue
        key = (row["subject"], row["relation"])
        groups.setdefault(key, {}).setdefault(row["object"], [])
        if row["source"]:
            groups[key][row["object"]].append(row["source"])
    rows = []
    for (subject, relation), values in groups.items():
        if len(values) < 2:
            continue
        ordered = sorted(values.items(), key=lambda kv: (-len(set(kv[1])), kv[0]))
        rows.append({"subject": subject, "relation": relation,
                     "values": [{"object": o, "sources": sorted(set(s))}
                                for o, s in ordered],
                     "spread": len(values)})
    rows.sort(key=lambda r: (-r["spread"], r["subject"], r["relation"]))
    total = len(rows)
    omitted = 0
    if cap is not None and total > int(cap):
        omitted = total - int(cap)
        rows = rows[:int(cap)]
    return {"format": FORMAT, "conflicts": rows, "total": total, "omitted": omitted}


def agreed(claims):
    groups = {}
    for c in (claims or ()):
        row = _row(c)
        if not (row["subject"] and row["relation"] and row["object"]):
            continue
        groups.setdefault((row["subject"], row["relation"]), set()).add(row["object"])
    return [{"subject": s, "relation": r, "object": next(iter(v))}
            for (s, r), v in sorted(groups.items()) if len(v) == 1]


def render(claims, cap=None):
    con = conflicts(claims, cap=cap)
    agreed_rows = agreed(claims)
    lines = []
    if con["conflicts"]:
        lines.append("CONFLICTS (unresolved — weigh every source, do not pick one):")
        for row in con["conflicts"]:
            vals = "  vs  ".join(
                "%s%s" % (v["object"], (" [%s]" % ", ".join(v["sources"])
                                        if v["sources"] else ""))
                for v in row["values"])
            lines.append("- %s %s: %s" % (row["subject"], row["relation"], vals))
        if con["omitted"]:
            lines.append("... %d further conflict(s) omitted by the cap" % con["omitted"])
    if agreed_rows:
        lines.append("AGREED FACTS:")
        for row in agreed_rows:
            lines.append("- %s %s: %s" % (row["subject"], row["relation"], row["object"]))
    text = "\n".join(lines)
    return {"format": FORMAT, "text": text, "conflicts": con["conflicts"],
            "total": con["total"], "omitted": con["omitted"],
            "agreed": len(agreed_rows),
            "verdict": "conflicts-present" if con["conflicts"] else "consistent"}
