#!/usr/bin/env python3
"""Observation fidelity — the preview must keep the line that decides.

Source: arXiv:2611.19056, "Run, Read Back, Refine: Observation Fidelity in
Execution-Grounded EDA Agents" (round 108). Its measured claim is that with the
model fixed, the system-level *observation* axis spans 56.8 percentage points —
more than the backbone axis (23.3 pp) — because correctness is bottlenecked by
whether the agent actually observes what happened in the live environment.

Longrun already refuses to *lose* a big observation (`_offload_observation`
writes it verbatim and hands the model a head+tail preview). The remaining gap
is fidelity inside the preview: `ERROR: …`, `exit=1`, `FAILED test_x` usually
sit in the MIDDLE of a log, so a head+tail preview can show 4 KB and still hide
the only decisive line — the model then reports a success it never observed.

This module keeps that line, and measures the result:

  decisive(text)   the lines that carry a failure/exit/denial signal;
  preview(...)     head + the decisive lines (numbered) + tail, bounded;
  fidelity(...)    how many decisive lines survived a preview, 0.0–1.0.

Pure functions: str in, str/dict out. Nothing is written.
"""
from __future__ import annotations

import re

FORMAT = "longrun-observation/1"

DECISIVE = re.compile(
    r"(?i)\b(error|traceback|exception|fatal|panic|assert(?:ion)?|"
    r"failed|failure|denied|refused|not found|no such file|timeout|timed out|"
    r"segmentation fault|killed|oom)\b"
    r"|\bexit(?:[_ ]?code)?\s*[=:]\s*-?[1-9]\d*\b"
    r"|\bFAIL(?:ED|URE)?\b"
    r"|\b\d{1,3}%\s*(?:passed|failed)\b"
)
_LINE_CAP = 300


def decisive(text, max_lines=64):
    """`[(line_number, line)]` of the lines that carry a decision signal."""
    out = []
    for i, line in enumerate(str(text or "").splitlines()):
        if DECISIVE.search(line):
            out.append((i + 1, line.rstrip()))
            if len(out) >= max_lines:
                break
    return out


def decisive_block(text, max_decisive=8):
    """The numbered decisive lines, or "" when there are none."""
    lines = decisive(text)
    if not lines:
        return ""
    keep = lines if len(lines) <= max_decisive else (lines[:max_decisive // 2]
                                                     + lines[-max_decisive // 2:])
    block = "\n".join("L%d: %s" % (n, ln.strip()[:_LINE_CAP]) for n, ln in keep)
    more = "" if len(keep) == len(lines) else (
        "\n(+%d more decisive lines in the full file)" % (len(lines) - len(keep)))
    return block + more


def preview(text, head_chars=1200, tail_chars=900, max_decisive=8):
    """A bounded preview that always keeps the decisive lines.

    With no decisive line the result is exactly the old head+tail shape, so a
    caller can swap this in without changing the common case.
    """
    s = str(text or "")
    head = s[:head_chars]
    tail = s[-tail_chars:] if len(s) > head_chars else ""
    block = decisive_block(s, max_decisive)
    if not block:
        return head + (("\n...\n" + tail) if tail else "")
    return ("%s\n... decisive lines (kept in full) ...\n%s\n...\n%s"
            % (head, block, tail))


def fidelity(text, shown=None):
    """How much of the decisive evidence survived `shown` (default: a preview)."""
    s = str(text or "")
    shown = preview(s) if shown is None else str(shown)
    lines = decisive(s, max_lines=10_000)
    if not lines:
        return {"format": FORMAT, "decisive": 0, "kept": 0, "fidelity": 1.0,
                "missing": []}
    kept, missing = 0, []
    for n, line in lines:
        probe = line.strip()[:120]
        if probe and probe in shown:
            kept += 1
        else:
            missing.append({"line": n, "text": line.strip()[:_LINE_CAP]})
    return {"format": FORMAT, "decisive": len(lines), "kept": kept,
            "fidelity": round(kept / float(len(lines)), 4),
            "missing": missing[:12]}
