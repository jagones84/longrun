#!/usr/bin/env python3
"""Handoff policy audit — a summary may not invent permissions or requirements.

Source: arXiv:2611.06545, "When Do Summaries Become Instructions? Unsupported
Policy in LLM Agents' Self-Written Handoff Summaries" (round 111). When a
long-running agent compacts its context, most of the history becomes a summary
written by the agent itself. That summary can state permissions or requirements
the record does not support ("do not touch X", "you may publish Y"), and the
successor follows them: neutralizing false approvals cut unauthorized actions
from 24 to 7 of 120 held-out runs (post hoc).

This module checks a handoff/summary text against a PERMISSION LEDGER (the true
record). It only flags a sentence that (a) carries a policy modal AND (b) names a
concrete object (a backticked token, a path, a tool name) AND (c) has no ledger
line about that same object with the same polarity. A vague "be careful" is not a
claim and is never reported; this is the precision rule that keeps the audit
usable.

`neutralize` replaces an unsupported sentence with an explicit marker; it is
caller-invoked and never automatic.

Pure: text and ledger in, findings out.
"""
from __future__ import annotations

import re

FORMAT = "longrun-handoff-audit/1"

_RESTRICT = re.compile(r"\b(must not|may not|cannot|can not|is not allowed|are not "
                       r"allowed|forbidden|requires? (?:human |operator )?approval|"
                       r"do not|don't|never|only (?:an? )?(?:operator|human|admin))\b",
                       re.I)
_ALLOW = re.compile(r"\b(may|is allowed|are allowed|can proceed|is permitted|"
                    r"are permitted|has permission|is authorized)\b", re.I)
_OBJECT = re.compile(r"`([^`\n]{1,80})`|((?:\.?/)?(?:[\w.@+-]+/)+[\w.@+*-]+)"
                     r"|\b([a-z][a-z0-9_]*\.[a-z][a-z0-9_]*)\b")
_SPLIT = re.compile(r"(?<=[.!?])\s+|\n+")
MARKER = "[policy claim removed: not supported by the record]"


def _polarity(text):
    if _RESTRICT.search(text):
        return "restrict"
    if _ALLOW.search(text):
        return "allow"
    return None


def _objects(text):
    out = []
    for m in _OBJECT.finditer(text):
        tok = (m.group(1) or m.group(2) or m.group(3) or "").strip()
        if tok and not tok.startswith(("http", "www.")):
            out.append(tok)
    return sorted(set(out))


def sentences(text):
    """(offset, sentence) pairs, keeping the source order for line numbers."""
    out = []
    pos = 0
    for m in _SPLIT.finditer(text or ""):
        chunk = text[pos:m.start()]
        if chunk.strip():
            out.append((pos, chunk.strip()))
        pos = m.end()
    tail = (text or "")[pos:]
    if tail.strip():
        out.append((pos, tail.strip()))
    return out


def _line(text, offset):
    return (text or "")[:offset].count("\n") + 1


def _ledger_rows(ledger):
    rows = []
    for item in ledger or ():
        if isinstance(item, str):
            rows.append({"text": item, "source": None})
        elif isinstance(item, dict):
            rows.append({"text": str(item.get("text") or ""), "source": item.get("source")})
    return rows


def _support(claim, objects, polarity, rows):
    """A claim is supported only by a ledger line with the same object and polarity."""
    for row in rows:
        line = row["text"]
        if _polarity(line) != polarity:
            continue
        if any(obj in line for obj in objects):
            return row
    return None


def audit(text, ledger):
    rows = _ledger_rows(ledger)
    claims = []
    for offset, sentence in sentences(text):
        pol = _polarity(sentence)
        if not pol:
            continue
        objs = _objects(sentence)
        if not objs:
            continue                     # vague; not a policy claim about anything
        hit = _support(sentence, objs, pol, rows)
        claims.append({
            "line": _line(text, offset),
            "polarity": pol,
            "kind": "restriction" if pol == "restrict" else "authorization",
            "objects": objs,
            "sentence": sentence,
            "supported": bool(hit),
            "source": hit["source"] if hit else None,
            "why": ("supported by the ledger" if hit else
                    "no ledger line about %s with this polarity" % ", ".join(objs)),
        })
    unsupported = [c for c in claims if not c["supported"]]
    return {"format": FORMAT, "claims": claims, "unsupported": unsupported,
            "counts": {"sentences": len(sentences(text)), "claims": len(claims),
                       "unsupported": len(unsupported),
                       "restrictions": sum(1 for c in claims if c["kind"] == "restriction"),
                       "authorizations": sum(1 for c in claims if c["kind"] == "authorization")},
            "verdict": "unsupported-policy" if unsupported else "clean"}


def neutralize(text, rows):
    """Replace the audited unsupported sentences with an explicit marker."""
    out = text or ""
    removed = 0
    for row in rows or ():
        sentence = str(row.get("sentence") or "")
        if sentence and sentence in out:
            out = out.replace(sentence, MARKER, 1)
            removed += 1
    return {"format": FORMAT, "text": out, "removed": removed}
