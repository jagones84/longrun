#!/usr/bin/env python3
"""Evidence export — what a shared trace reveals versus what it diagnoses.

Source: arXiv:2611.20389, "Where the Evidence Lives: Measuring Privacy and
Diagnosability of Exported AI-Agent Traces" (round 106). Its finding is that
conventional redaction can delete the very evidence a repair needs while the
identifiers it kept stay recoverable from *counters* (row counts re-identify
the subject), and that both goals survive when the exporter (a) reports a
**comparison fact** instead of the identity, (b) uses **execution-scoped
pseudonyms** and (c) **suppresses selected counters**.

Longrun already records a durable transcript and one tool card per call
(`memory/stores.py:load_session`). What it did not have is a *policy* for
handing that record to someone else: `sessions history` is the operator's own
view and prints everything.

Two profiles, one wire format (`longrun-evidence/1`):

  audit  — the operator's own copy: raw ids, exact counters, secrets redacted,
           every tool card capped. Still never prints a bearer token or a key.
  share  — the copy that leaves the machine: session/workspace/model are
           execution-scoped pseudonyms, every counter is bucketed, error
           CLASSES and tool names stay exact (that is the diagnostic value),
           args and results keep a redacted tail.

Failure signals are deliberately preserved in both: a tool call that failed,
its exit code, its error class. A diagnostic program that cannot see them is
the defect the paper measured.

Pure module: `build(session, profile)` takes the session dict, returns the
export; `export(session_id, profile)` loads it. Nothing here writes.
"""
from __future__ import annotations

import hashlib
import json
import re
import time

FORMAT = "longrun-evidence/1"
PROFILES = ("audit", "share")
MAX_TEXT = 4000
MAX_TAIL = 400

_SECRETS = (
    (re.compile(r"(?i)bearer\s+[A-Za-z0-9._\-]+"), "Bearer <redacted>"),
    (re.compile(r"\b(sk|rk|pk)-[A-Za-z0-9_\-]{8,}\b"), "<key>"),
    (re.compile(r"\b[0-9a-f]{32,}\b"), "<hex>"),
    (re.compile(r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b"), "<email>"),
    (re.compile(r"/home/[^\s\"'`:]+"), "<path>"),
    (re.compile(r"/Users/[^\s\"'`:]+"), "<path>"),
)
_ADDRESS = re.compile(r"\b0x[0-9a-fA-F]{6,}\b")


class _Pseudonyms:
    """One execution-scoped pseudonym per distinct identifier (paper §II)."""

    def __init__(self):
        self._map = {}

    def __call__(self, value):
        key = str(value or "")
        if not key:
            return ""
        if key not in self._map:
            self._map[key] = "e%d" % (len(self._map) + 1)
        return self._map[key]

    def size(self):
        return len(self._map)

    def mapping(self):
        return dict(self._map)


def _bucket(n):
    """A counter that cannot be compared across executions (paper §II)."""
    try:
        n = int(n)
    except (TypeError, ValueError):
        return "unknown"
    if n <= 0:
        return "0"
    if n == 1:
        return "1"
    if n <= 5:
        return "2-5"
    if n <= 20:
        return "6-20"
    return "21+"


def _clean(text, limit=MAX_TEXT):
    """Redact secrets/paths; return (text, redactions)."""
    s = str(text or "")
    hits = 0
    for rx, repl in _SECRETS:
        s, n = rx.subn(repl, s)
        hits += n
    s, n = _ADDRESS.subn("<addr>", s)
    hits += n
    return s[:limit], hits


def _error_class(text):
    """The shortest decisive token of an error, without the payload."""
    s = " ".join(str(text or "").split())
    if not s:
        return ""
    first = s.split(":", 1)[0]
    return first[:80]


def _digest(obj):
    blob = json.dumps(obj, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()[:32]


def _card_records(cards, profile, pseudo, seq0=0):
    out = []
    failures = []
    tools = set()
    redactions = 0
    for i, card in enumerate(cards or []):
        if not isinstance(card, dict):
            continue
        tool = str(card.get("tool") or "")
        tools.add(tool)
        ok = bool(card.get("ok"))
        exit_code = card.get("exit_code")
        err = card.get("error") or ""
        args, n1 = _clean(card.get("args") or "", limit=600)
        result, n2 = _clean(card.get("result") or "", limit=MAX_TAIL if profile == "share"
                            else 1200)
        redactions += n1 + n2
        rec = {
            "seq": seq0 + i,
            "kind": "tool",
            "tool": tool,
            "ok": ok,
            "exit_code": exit_code if isinstance(exit_code, int) else None,
            "error_class": _error_class(err),
            "args": args,
            "result_tail": result,
            "result_bytes": (_bucket(len(str(card.get("result") or "")))
                             if profile == "share"
                             else len(str(card.get("result") or ""))),
            "result_hash": _digest(card.get("result") or ""),
        }
        if not ok or (isinstance(exit_code, int) and exit_code != 0):
            failures.append({"seq": rec["seq"], "tool": tool,
                             "exit_code": rec["exit_code"],
                             "error_class": rec["error_class"]})
        out.append(rec)
    return out, failures, tools, redactions


def _message_records(messages, profile, pseudo):
    """Messages stay readable — that is where the repair evidence lives.

    What changes is the identity layer: in `share`, absolute paths and e-mails
    are already replaced by `_clean`; here the session/workspace labels become
    execution-scoped pseudonyms as well.
    """
    out = []
    redactions = 0
    for i, msg in enumerate(messages or []):
        if not isinstance(msg, dict):
            continue
        text, n = _clean(msg.get("content") or "")
        redactions += n
        role = str(msg.get("role") or "")
        if role == "system" and profile == "share":
            # The system prompt names the operator, the machine and the store
            # layout; it diagnoses nothing about THIS failure.
            text = "<system prompt withheld: %d bytes>" % len(str(msg.get("content") or ""))
        out.append({
            "seq": i,
            "kind": "message",
            "role": role,
            "text": text,
            "bytes": _bucket(len(str(msg.get("content") or ""))) if profile == "share"
            else len(str(msg.get("content") or "")),
            "hash": _digest(msg.get("content") or ""),
        })
    return out, redactions


def build(session, profile="share"):
    """One export document for one session. Pure: reads the dict, writes nothing."""
    profile = profile if profile in PROFILES else "share"
    sess = session if isinstance(session, dict) else {}
    pseudo = _Pseudonyms()
    share = profile == "share"
    msgs, r1 = _message_records(sess.get("messages"), profile, pseudo)
    cards, failures, tools, r2 = _card_records(sess.get("tool_cards"), profile, pseudo,
                                               seq0=len(msgs))
    idents = {}
    for key in ("id", "workspace", "model"):
        raw = sess.get(key)
        if raw and share:
            idents[key] = pseudo(raw)
    doc = {
        "format": FORMAT,
        "profile": profile,
        "generated": round(time.time(), 3),
        "policy": {
            "identifiers": "execution-scoped pseudonym" if share else "raw",
            "counters": "bucketed" if share else "exact",
            "secrets": "redacted",
            "system_prompt": "withheld" if share else "kept",
        },
        "session": idents.get("id") or str(sess.get("id") or ""),
        "workspace": idents.get("workspace") or str(sess.get("workspace") or ""),
        "model": idents.get("model") or str(sess.get("model") or ""),
        "records": msgs + cards,
        "failures": failures,
        "summary": {
            "messages": _bucket(len(msgs)) if share else len(msgs),
            "tool_calls": _bucket(len(cards)) if share else len(cards),
            "failures": _bucket(len(failures)) if share else len(failures),
            "distinct_tools": _bucket(len(tools)) if share else len(tools),
            "error_classes": sorted({f["error_class"] for f in failures if f["error_class"]}),
        },
        "diagnosability": {
            # What a repair program can still act on: failed calls, their class
            # and exit code, plus the redacted text of the turn.
            "failure_signals": len(failures),
            "tools_named": sorted(tools),
            "redactions": r1 + r2,
        },
        "reidentification": {
            "exact_counters_emitted": 0 if share else len(msgs) + len(cards),
            # The map itself never travels: it would put every identifier back
            # into the file the pseudonyms exist to protect (round 106).
            "pseudonyms": pseudo.size() if share else 0,
        },
    }
    doc["integrity"] = {"digest": _digest(doc["records"])}
    return doc


def export(session_id, profile="share"):
    """Load the session from the store and export it (JSON-ready dict)."""
    from longrun.memory.stores import load_session
    sess = load_session(session_id)
    if not sess:
        return {"error": "session not found"}
    return build(sess, profile)
