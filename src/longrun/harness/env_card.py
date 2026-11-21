#!/usr/bin/env python3
"""Environment card — onboard the agent into the workspace once per session.

Source: LangChain, "Improving Deep Agents with harness engineering"
(2026-02-17), which moved a fixed `gpt-5.2-codex` from 52.8% to 66.5% on
Terminal-Bench 2.0 (89 tasks) by changing only the harness. One of its three
levers was a `LocalContextMiddleware` that maps the working directory and the
available tooling when the agent starts: "context discovery and search are error
prone, so injecting context reduces this error surface and helps onboard the
agent into its environment."

Longrun tells the model to point `workspace.set` at the project but never says
what is IN that workspace, so the first turn pays for a wrong guess (a read of a
path that is not there, a shell `ls` whose output then has to be carried). This
module builds a small, sorted, bounded card: the root, its top-level entries and
the workspace's own check command when one resolves.

  build(workspace)  the card text, or "" when there is no usable workspace

Read-only: one scandir of the root (no recursion, no writes), never raises.
The check command has ONE owner: `harness/workspace_check.detect`.
"""
from __future__ import annotations

import os

FORMAT = "longrun-env-card/1"

MAX_TEXT = 800      # a card is an onboarding hint, not a tree dump
MAX_DIRS = 8
MAX_FILES = 8


def _scan(root):
    """Top-level (dirs, files), sorted, dot entries skipped."""
    dirs, files = [], []
    with os.scandir(root) as it:
        for entry in it:
            name = entry.name
            if not name or name.startswith("."):
                continue
            try:
                is_dir = entry.is_dir()
            except OSError:
                is_dir = False
            (dirs if is_dir else files).append(name)
    return sorted(dirs), sorted(files)


def _names(names, cap):
    shown = ", ".join(names[:cap])
    hidden = len(names) - cap
    return (shown + (" (+%d more)" % hidden)) if hidden > 0 else shown


def build(workspace):
    """The environment card for `workspace`, or "" when it cannot be read."""
    root = str(workspace or "").strip()
    if not root or not os.path.isdir(root):
        return ""
    try:
        dirs, files = _scan(root)
    except OSError:
        return ""
    lines = ["## Environment (observed at session start)",
             "root: %s (%d entries)" % (root, len(dirs) + len(files))]
    if dirs:
        lines.append("dirs: %s" % _names(dirs, MAX_DIRS))
    if files:
        lines.append("files: %s" % _names(files, MAX_FILES))
    try:
        from longrun.harness import workspace_check as _wc
        check = _wc.detect(root)
    except Exception:  # noqa: BLE001 — the card must never break a turn
        check = None
    if check:
        lines.append("check: %s" % check)
    return "\n".join(lines)[:MAX_TEXT]
