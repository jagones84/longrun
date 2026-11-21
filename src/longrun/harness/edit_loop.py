#!/usr/bin/env python3
"""Per-file edit loop — stop a run that keeps rewriting the same file.

Source: LangChain, "Improving Deep Agents with harness engineering"
(2026-02-17). Its `LoopDetectionMiddleware` tracks per-file edit counts through
tool-call hooks and adds "consider reconsidering your approach" after N edits to
the same file; it recovered agents from "doom loops that make small variations
to the same broken approach (10+ times in some traces)."

Longrun already catches an IDENTICAL call whose observation did not change
(`_same_obs_n` -> `_stuck_note`) and a failed call re-issued verbatim
(`_repeat_block_note`). Neither sees the case the paper measured: DIFFERENT
edits to the SAME file, each plausible, drifting around one broken idea. This
module counts executed writes per path and returns one note at every `limit`.

  observe(counts, tool, args, limit=3)  -> (counts, note|"")
  text(path, count)                     -> the note

The caller owns the state (a plain dict, one per turn). Nothing is stored here.
"""
from __future__ import annotations

import os

FORMAT = "longrun-edit-loop/1"

WRITE_TOOLS = ("fs.write", "fs.edit", "fs.append")
DEFAULT_LIMIT = 3


def _path(tool, args):
    """The file this call writes, or "" when the call is not a file write."""
    if tool not in WRITE_TOOLS:
        return ""
    raw = args if isinstance(args, dict) else {}
    value = raw.get("path") or raw.get("file") or ""
    value = str(value).strip()
    return os.path.normpath(value) if value else ""


def observe(counts, tool, args, limit=DEFAULT_LIMIT):
    """Count one write and return the note owed on this boundary."""
    counts = counts if isinstance(counts, dict) else {}
    path = _path(tool, args)
    if not path:
        return counts, ""
    count = int(counts.get(path) or 0) + 1
    counts[path] = count
    if int(limit) <= 0 or count % int(limit):
        return counts, ""
    return counts, text(path, count)


def text(path, count):
    """The reconsider note. It names the evidence gap, never the solution."""
    return ("SYSTEM (harness) — EDIT LOOP: you have written `%s` %d times this turn.\n"
            "Step back before the next edit: is the APPROACH right, or are you "
            "iterating on the same broken patch? Re-read the last error and the "
            "original request, then do ONE of these: take a different route, make "
            "a smaller change the check can verify, or ask the operator one precise "
            "question. Do not keep editing this file without new evidence."
            % (path, int(count)))
