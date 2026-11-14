#!/usr/bin/env python3
"""Repo anchors — the WHERE/VERIFY note a finished turn leaves for the next one.

Source: CoReMem (arXiv 2611.17316 §3.1). Valuing each part of a trajectory by
what its REMOVAL costs the NEXT task leaves **anchors**: a reference to a place
in the repository and to a command that runs or tests it. The reasoning
narrative and the diff body do not pay; with the actor frozen the anchor memory
lowers steps by 3-10% and raises resolve by 9-11% on tasks that continue the
previous work, at no extra tokens (Table 1, "CoReMem w/o training").

Longrun already CAPTURES the raw material — one persisted tool card per call
with its `args` (path, command) and `exit_code` (`memory/stores.py`) — and
already extracts anchors for COMPACTION (`model/context_engine.anchors_block`,
F6). What no session boundary did was keep them: the only cross-session text was
a <=140-character prose lesson. This module writes ONE bounded note per turn,
with NO model call, by reading the cards the harness already stored.

It is an extraction, never a summary: a note that invents a path is worse than
no note, so every item here is copied from an argument the model really passed.
"""
import json
import os
import re

from longrun.model import context_limits as ctx_limits

#: A command that RUNS or TESTS the code — the only thing worth calling VERIFY.
#: A successful `ls`, `cat` or `git status` is not evidence that a change works.
_CHECK_RE = re.compile(
    r"(?i)\b(pytest|py\.test|unittest|tox|nox|npm\s+(run\s+)?test|yarn\s+test|"
    r"pnpm\s+test|make|ctest|cargo\s+test|go\s+test|bash\s+tests/|"
    r"python[0-9.]*\s+-m\s+(pytest|unittest)|ruff|flake8|mypy|eslint|tsc|"
    r"black\s+--check)\b")

#: The kinds of a tool card that name a repository LOCATION.
_PATH_TOOLS = ("fs.read", "fs.write", "fs.edit")
#: How many locations the note keeps, and how long the whole line may be.
MAX_PATHS = 4
MAX_CMD = 100


def _args(card):
    """The card's `args` as a dict (stored as a JSON string; junk -> {})."""
    raw = (card or {}).get("args")
    if isinstance(raw, dict):
        return raw
    try:
        got = json.loads(raw or "{}")
    except (TypeError, ValueError):
        return {}
    return got if isinstance(got, dict) else {}


def _rel(path, workspace):
    """A path as the note states it: relative to the workspace when it is inside.

    An absolute path of the operator's home is noise in a prompt; a path outside
    the workspace stays as given (it is still where the code is).
    """
    p = " ".join(str(path or "").split())[:120]
    if not p:
        return ""
    if workspace and os.path.isabs(p):
        try:
            base = os.path.realpath(workspace)
            real = os.path.realpath(p)
            if real == base or real.startswith(base + os.sep):
                return os.path.relpath(real, base)
        except (OSError, ValueError):
            pass
    return p


def _dedupe(items):
    out, seen = [], set()
    for it in items:
        if it and it not in seen:
            seen.add(it)
            out.append(it)
    return out


def note_from_cards(cards, workspace="", max_chars=None):
    """The WHERE/VERIFY line for one turn, or "" when the turn left no anchor.

    Order: files the turn CHANGED, then files it only READ (where to look), then
    the LAST successful check command. A failed command is not a check — it did
    not prove the change works.
    """
    changed, read, check = [], [], ""
    for c in cards or []:
        if not isinstance(c, dict):
            continue
        tool = str(c.get("tool") or "").strip()
        args = _args(c)
        if tool in _PATH_TOOLS:
            p = _rel(args.get("path"), workspace)
            if p:
                (changed if tool in ("fs.write", "fs.edit") else read).append(p)
        elif tool == "shell" or tool.startswith("shell."):
            cmd = " ".join(str(args.get("command") or "").split())
            if cmd and c.get("ok") and _CHECK_RE.search(cmd):
                check = cmd
    paths = _dedupe(changed + read)[:MAX_PATHS]
    cap = max_chars or ctx_limits.get("memory_item_chars")
    parts = []
    if paths:
        parts.append("WHERE: " + ", ".join(paths))
    if check:
        parts.append("VERIFY: " + check[:MAX_CMD])
    # A truncated VERIFY is useless, so drop LOCATIONS from the front first and
    # shorten the command only when it alone does not fit.
    while parts and len(" | ".join(parts)) > cap:
        if len(parts) > 1:
            parts.pop(0)
        else:
            parts[0] = parts[0][:max(8, cap - 1)] + "\u2026"
    return " | ".join(p for p in parts if p)


def remember(sess, cards):
    """Store this turn's anchor note; returns the text written ("" when none)."""
    try:
        sess = sess or {}
        ws = sess.get("workspace") or ""
        note = note_from_cards(cards, workspace=ws)
        if not note:
            return ""
        from longrun.memory import memory
        memory.store("repo.anchor", note, session=sess.get("id", ""),
                     origin="harness", source="anchor", workspace=ws)
        return note
    except Exception:  # noqa: BLE001 — an anchor must never break a turn
        return ""
