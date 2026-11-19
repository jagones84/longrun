#!/usr/bin/env python3
"""Instruction adherence — did the run actually do what the context file says?

Source: arXiv:2611.13709, "Do They Do as They Are Told? Investigating Coding
Agents' Adherence to Explicit Instructions in Context Files" (round 114). Agent
context files (AGENTS.md and relatives) are a governance mechanism whose
assumption is untested: that the instructions are carried out. The study
operationalizes the explicit, actionable instructions into executable measurement
scripts and finds that adherence "splits sharply between instructions followed
consistently and those never respected".

This module is the deterministic part of that: it extracts the explicit
directives that name a CONCRETE object (a path, a tool, a command) and evaluates
each against the session's tool cards. A directive without a concrete object is
not measurable and is skipped — the same precision rule that keeps the report
usable.

  * `directives(text)` — line, kind (`never|always|only`), object, sentence;
  * `audit(text, cards)` — per directive: followed / violated / not-observable;
  * `verdict` — `clean`, `violations`, or `uneven` (some followed, some never).

Pure: text and cards in, rows out. It never edits the context file.
"""
from __future__ import annotations

import json
import os
import re

FORMAT = "longrun-instruction-audit/1"
_NEVER = re.compile(r"\b(never|do not|don't|must not|avoid)\b", re.I)
_ALWAYS = re.compile(r"\b(always|must|required?|make sure|ensure)\b", re.I)
_ONLY = re.compile(r"\bonly\b", re.I)
_OBJECT = re.compile(r"`([^`\n]{1,120})`|((?:\.?/)?(?:[\w.@+-]+/)+[\w.@+*-]+)"
                     r"|\b([a-z][a-z0-9_]*\.[a-z][a-z0-9_]*)\b")
_WRITE_WORDS = ("write", "edit", "apply", "append", "delete", "remove", "move",
                "rename", "sed -i", "rm ", "mv ", ">", "tee")
_PATH_KEYS = ("path", "file", "target", "dir", "filename")


def _args(card):
    raw = card.get("args")
    if isinstance(raw, dict):
        return raw
    try:
        return json.loads(raw) if raw else {}
    except (TypeError, ValueError):
        return {}


def _objects(sentence):
    out = []
    for m in _OBJECT.finditer(sentence):
        tok = (m.group(1) or m.group(2) or m.group(3) or "").strip()
        if tok and not tok.startswith(("http", "www.")):
            out.append(tok)
    return sorted(set(out))


def _clause(sentence, obj):
    """The clause that actually contains the object — polarity from that clause only."""
    parts = re.split(r"(?<=[.!?])\s+|;|\s+but\s+|\s+though\s+|\s+however\s+|\s+—\s+",
                     sentence)
    for part in parts:
        if obj in part:
            return part
    return sentence


def directives(text):
    rows = []
    for i, line in enumerate((text or "").splitlines(), 1):
        sentence = line.strip()
        if not sentence:
            continue
        objs = _objects(sentence)
        if not objs:
            continue                      # vague; not measurable
        row = None
        for obj in objs:
            clause = _clause(sentence, obj)
            kind = ("never" if _NEVER.search(clause) else
                    "always" if _ALWAYS.search(clause) else
                    "only" if _ONLY.search(clause) else None)
            if kind:
                row = {"line": i, "kind": kind, "object": obj,
                       "objects": objs, "text": sentence}
                break
        if row:
            rows.append(row)
    return rows


def _is_write(card):
    tool = str(card.get("tool") or "").lower()
    args = _args(card)
    if any(w in tool for w in ("write", "edit", "apply", "append")):
        return True
    cmd = str(args.get("command") or "").lower()
    return any(w in cmd for w in _WRITE_WORDS)


def _touches(card, obj):
    blob = json.dumps(_args(card), ensure_ascii=False)
    val = str(obj)
    if val in blob:
        return True
    base = os.path.basename(val.rstrip("/"))
    return bool(base) and base in blob


def _evaluate(row, cards):
    related = [c for c in cards if isinstance(c, dict) and _touches(c, row["object"])]
    writes = [c for c in cards if isinstance(c, dict) and _is_write(c)]
    if row["kind"] == "never":
        if not related:
            return "not-observable"
        bad = [c for c in related if _is_write(c)]
        return "violated" if bad else "followed"
    if row["kind"] == "only":
        # "only X" restricts a scope whose universe this module cannot see
        # (a port, a tracked file, a call site). Reporting a violation would be a
        # guess, so it is not-observable until the caller supplies a real check.
        return "not-observable"
    # always: a required step must appear before/among the writes.
    if not related:
        return "violated" if writes else "not-observable"
    ok = [c for c in related if c.get("ok") is not False
          and not (isinstance(c.get("exit_code"), int) and c["exit_code"] != 0)]
    return "followed" if ok else "violated"


def audit(text, cards):
    cards = [c for c in (cards or ()) if isinstance(c, dict)]
    rows = []
    for row in directives(text):
        state = _evaluate(row, cards)
        rows.append({**row, "state": state})
    counts = {"directives": len(rows),
              "followed": sum(1 for r in rows if r["state"] == "followed"),
              "violated": sum(1 for r in rows if r["state"] == "violated"),
              "not_observable": sum(1 for r in rows if r["state"] == "not-observable")}
    if counts["violated"]:
        verdict = "violations"
    elif counts["followed"]:
        verdict = "clean"
    else:
        verdict = "uneven"
    return {"format": FORMAT, "directives": rows, "counts": counts, "verdict": verdict}
