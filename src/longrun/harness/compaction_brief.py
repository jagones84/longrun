#!/usr/bin/env python3
"""Compaction brief — a compaction must carry the work the continuation still needs.

Source: arXiv:2611.25673, "CompAct-Bench" (round 165). Two hundred successful
trajectories were compacted at 25/50/75% of execution and continued under a
matched action budget: every task was solved before compaction, yet average
post-compaction accuracy fell to **56.7%**, and the best compactor reached only
68.5% (`compact-bench-working-context_2611.25673.md:35`, Table 2 `:119-130`).
Two failure pathways are named: omissions cause repeated work and budget
exhaustion; distortions turn tentative evidence into conclusions and cause
premature termination (`:35`, `:238-242`). Search degrades at later boundaries
while coding improves because the repository holds part of the state (`:170`).

The deterministic half a harness can run without a model is the one this module
implements: before a boundary, extract the anchors the continuation must still
know — the task statement, its hard constraints, the last failure, and the paths
the task names — then check the compacted context retains them. A missing
critical anchor is repaired by appending a short carry-forward block to the
summary the continuation reads. This is retention, not causal salience:
arXiv:2611.25583 shows content-level features cannot attribute drift, and
arXiv:2611.26346 shows a merge can fail while every branch passes.

Pure: messages + cards in, record out; `fit` mutates only the given list.
"""
from __future__ import annotations

import re

FORMAT = "longrun-compaction-brief/1"

#: A message starting with this marker is a harness injection, not the user's task.
HARNESS = "[harness]"
_CONSTRAINT = re.compile(
    r"(?i)\b(must|never|only|do not|don't|required|shall|always|without)\b")
_WORD = re.compile(r"[A-Za-z0-9_]+")


def _norm(text):
    return " ".join(_WORD.findall(str(text or "").lower()))


def _key(text, words=8):
    return " ".join(_norm(text).split()[:words])


def _task(messages):
    """The user's task: the first substantive turn, else the first real one.

    No length gate: a concise instruction ("Fix the crash in src/x.py") is
    exactly the work a compaction must not lose. A substantive turn still wins
    so an opening "hi" does not shadow it; the `[harness]` marker already keeps
    an injected turn out.
    """
    first = ""
    for msg in messages or []:
        if not isinstance(msg, dict) or msg.get("role") != "user":
            continue
        body = str(msg.get("content") or "").strip()
        if not body or body.lstrip().startswith(HARNESS):
            continue
        if len(body) >= 40:
            return body
        if not first:
            first = body
    return first


def _constraints(task, cap=3):
    out = []
    for sentence in re.split(r"(?<=[.!?])\s+|\n+", task or ""):
        if _CONSTRAINT.search(sentence) and len(sentence.strip()) >= 20:
            out.append(sentence.strip()[:300])
        if len(out) >= cap:
            break
    return out


def _last_error(tool_cards):
    for card in reversed(list(tool_cards or [])):
        if not isinstance(card, dict) or card.get("ok") is not False:
            continue
        args = card.get("args")
        if isinstance(args, dict):
            hint = (args.get("command") or args.get("path") or args.get("url")
                    or args.get("query") or "")
        else:
            hint = args if isinstance(args, str) else ""
        err = str(card.get("error") or card.get("result") or "")
        body = ("%s — %s" % (hint, err.splitlines()[0] if err else "")).strip(" —")
        if body:
            return body[:300]
    return ""


def anchors(messages, tool_cards=None):
    """The anchors a continuation must still be able to recover.

    Mechanical anchors (paths, `$` commands, `pkg==version` pins) are already
    appended to every compaction by `context_engine.anchors_block` (paper
    2610.31710; locked by `v676`). This adds the part that block does not carry:
    the user's task statement, its hard constraints and the last failure.
    """
    task = _task(messages)
    rows = []
    if task:
        rows.append({"kind": "task", "text": task[:400], "key": _key(task),
                     "critical": True})
    for item in _constraints(task):
        rows.append({"kind": "constraint", "text": item, "key": _key(item, 6),
                     "critical": True})
    error = _last_error(tool_cards)
    if error:
        rows.append({"kind": "last-error", "text": error, "key": _key(error, 6),
                     "critical": True})
    return {"format": FORMAT, "anchors": rows}


def retained(record, text):
    """Mark each anchor present when its key survives in `text`."""
    hay = _norm(text)
    rows = []
    for row in (record or {}).get("anchors") or []:
        key = row.get("key") or ""
        rows.append(dict(row, retained=bool(key) and key in hay))
    return rows


def audit(messages, after, tool_cards=None):
    """Judge a compacted context against the anchors of the history it replaced."""
    record = anchors(messages, tool_cards)
    text = " ".join(str((m or {}).get("content") or "")
                    for m in (after or []) if isinstance(m, dict))
    rows = retained(record, text)
    missing = [r for r in rows if not r["retained"]]
    critical = [r for r in missing if r["critical"]]
    verdict = ("no-anchors" if not rows else
               "lossy" if critical else "warnings" if missing else "complete")
    return {"format": FORMAT, "verdict": verdict, "anchors": len(rows),
            "retained": len(rows) - len(missing), "missing": missing,
            "missing_critical": critical,
            "carry": carry_text(missing) if missing else ""}


def carry_text(missing, cap=1200):
    """A short block naming what the compacted context no longer carries."""
    if not missing:
        return ""
    parts = []
    for row in missing[:4]:
        label = {"task": "task", "constraint": "constraint",
                 "last-error": "last failure", "path": "path"}.get(row["kind"],
                                                                   row["kind"])
        parts.append("%s: %s" % (label, str(row.get("text") or "").strip().rstrip(".")[:220]))
    more = (" (+%d more)" % (len(missing) - 4)) if len(missing) > 4 else ""
    body = ("[harness] carry-forward (still required after compaction): "
            + " | ".join(parts) + more
            + ". This block is a retention record, not new evidence.")
    return body[:cap]


def fit(after, record):
    """Append the carry-forward block to the summary the continuation will read."""
    carry = (record or {}).get("carry") or ""
    if not carry:
        return 0
    for msg in after or []:
        if not isinstance(msg, dict) or msg.get("role") != "system":
            continue
        content = str(msg.get("content") or "")
        if not content:
            continue
        msg["content"] = content.rstrip() + "\n\n" + carry
        return 1
    return 0
