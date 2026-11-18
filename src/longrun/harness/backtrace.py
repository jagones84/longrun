#!/usr/bin/env python3
"""Backward tracing — from a failed call to the earlier call that explains it.

Source: arXiv:2611.19448, "CLEW: An Agentic LLM Approach for Log-Guided
Root-Cause Code Localization" (round 107). Its observation is the one a trace
read model keeps getting wrong: "the code that reports a symptom is often not
the code that causes it" — downstream errors point at the detector, while the
defect executed earlier and its effects propagated.

Longrun already has `harness/trace_tree` (stage → step, first failure). That
answers *where* the turn broke. This module answers *what earlier action made
that place break*: given the tool cards of a session and the handle of a failed
one, it walks BACKWARD over the same record and returns the candidates, ranked
by distance and by whether they touched the same resource.

Rules (mechanical, no model):

  * a previous FAILED call that shares a resource is a cascade candidate;
  * a previous SUCCESSFUL call that wrote, edited or executed against a path the
    anchor then used is a mutation candidate (stale input, wrong target);
  * a resource is shared when one path is a prefix of the other, or when the
    file names are equal and the tools are file-shaped.

Pure: reads a list of card dicts, returns a verdict. Nothing is written.
"""
from __future__ import annotations

import json
import os

FORMAT = "longrun-backtrace/1"
_PATH_KEYS = ("path", "file", "target", "cwd", "workspace", "dir", "filename")
_WRITE_TOOLS = ("fs.write", "fs.edit", "fs.append", "edits.apply", "git")
_EXEC_TOOLS = ("shell", "sandbox", "python")


def _args(card):
    raw = card.get("args")
    if isinstance(raw, dict):
        return raw
    try:
        return json.loads(raw) if raw else {}
    except (TypeError, ValueError):
        return {}


def _resources(card):
    """The paths a card reads or writes, from its declared arguments."""
    out = []
    for key in _PATH_KEYS:
        val = _args(card).get(key)
        if isinstance(val, str) and val.strip():
            out.append(val.strip())
    cmd = _args(card).get("command")
    if isinstance(cmd, str):
        for tok in cmd.split():
            tok = tok.strip("\"'<>|&;")
            if tok.startswith(("/", "./", "../", "~")):
                out.append(tok)
    return [os.path.normpath(os.path.expanduser(p)) for p in out]


def _shared(a, b):
    if not a or not b:
        return []
    out = []
    for x in a:
        for y in b:
            if x == y:
                out.append(x)
            elif x.startswith(y.rstrip("/") + "/") or y.startswith(x.rstrip("/") + "/"):
                out.append(x if len(x) < len(y) else y)
            elif os.path.basename(x) == os.path.basename(y) and "." in os.path.basename(x):
                out.append(os.path.basename(x))
    return sorted(set(out))


def _failed(card):
    if card.get("ok") is False:
        return True
    code = card.get("exit_code")
    return isinstance(code, int) and code != 0


def _handle(card, index):
    return str(card.get("id") or card.get("handle") or index)


def _tool(card):
    return str(card.get("tool") or "")


def explain(cards, anchor):
    """Explain one failed card from the cards that preceded it.

    `anchor` is a card handle/id or an index into `cards`. Returns
    `{"format", "anchor", "causes", "verdict"}`.
    """
    cards = [c for c in (cards or []) if isinstance(c, dict)]
    idx = None
    if isinstance(anchor, int):
        idx = anchor if 0 <= anchor < len(cards) else None
    else:
        want = str(anchor)
        for i, card in enumerate(cards):
            if str(card.get("id") or card.get("handle") or "") == want:
                idx = i
                break
    if idx is None:
        return {"format": FORMAT, "anchor": None, "causes": [],
                "verdict": "anchor-not-found"}
    card = cards[idx]
    base = {"seq": idx, "handle": _handle(card, idx), "tool": _tool(card),
            "exit_code": card.get("exit_code"),
            "error_class": str(card.get("error") or "").split(":", 1)[0][:80]}
    if not _failed(card):
        return {"format": FORMAT, "anchor": base, "causes": [],
                "verdict": "anchor-not-failed"}

    target = _resources(card)
    causes = []
    for j in range(idx - 1, -1, -1):
        prev = cards[j]
        if not isinstance(prev, dict):
            continue
        shared = _shared(target, _resources(prev))
        if _failed(prev):
            causes.append({"seq": j, "handle": _handle(prev, j),
                           "tool": _tool(prev),
                           "error_class": str(prev.get("error") or "").split(":", 1)[0][:80],
                           "shared": shared,
                           "reason": "prior-failure" + ("-same-resource" if shared else ""),
                           "distance": idx - j})
            continue
        tool = _tool(prev)
        if shared and (tool.startswith(_WRITE_TOOLS) or any(
                tool.startswith(p) for p in _EXEC_TOOLS) or "write" in tool or "edit" in tool):
            causes.append({"seq": j, "handle": _handle(prev, j), "tool": tool,
                           "error_class": "",
                           "shared": shared,
                           "reason": "earlier-write-or-exec-against-the-same-resource",
                           "distance": idx - j})
        elif shared:
            causes.append({"seq": j, "handle": _handle(prev, j), "tool": tool,
                           "error_class": "", "shared": shared,
                           "reason": "earlier-read-of-the-same-resource",
                           "distance": idx - j})
    # Nearest first, and a same-resource cascade outranks a distant read.
    causes.sort(key=lambda c: (c["distance"], 0 if c.get("shared") else 1))
    verdict = "explained" if causes else "unexplained"
    if causes and not any(c.get("shared") for c in causes):
        verdict = "partial"
    return {"format": FORMAT, "anchor": base, "causes": causes[:12],
            "verdict": verdict}
