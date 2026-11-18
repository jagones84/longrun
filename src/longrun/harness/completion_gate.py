#!/usr/bin/env python3
"""Completion gate — an exit status is not a deliverable.

Source: arXiv:2611.21407, "Harness Leverage Across Model Size" (round 122). On
artifact-producing tasks the measured harness difference is mostly a PROGRESS
effect: of 357 usable cells, 127 left none of their declared artifacts and 85 of
those exited normally, so a scorer that reads the exit status credits work that
was never written (paper §1, Table 4).

  * `check(run)` — accept completion only when every declared artifact exists,
    every check passes and the run did not end empty; the model's finish claim
    is not evidence, and a normal exit with nothing on disk is named.
  * `ladder(rows)` — empty-cell accounting per harness: how many runs leave no
    declared artifact, how many of those exit normally, and the rate that a
    transcript/exit-only scorer would hide.

Pure: run records in, a gate decision out; nothing is executed.
"""
from __future__ import annotations

FORMAT = "longrun-completion-gate/1"


def check(run):
    """Did the run leave the declared work on disk?"""
    r = run or {}
    declared = [str(a) for a in r.get("declared_artifacts") or ()]
    present = {str(a) for a in r.get("artifacts") or ()}
    checks = r.get("checks") or {}
    findings = []
    missing = [a for a in declared if a not in present]
    for name in missing:
        findings.append({"kind": "missing-artifact", "artifact": name,
                         "why": "a declared deliverable is not on disk"})
    failed = sorted(str(k) for k, v in checks.items() if not v)
    for name in failed:
        findings.append({"kind": "check-failed", "check": name,
                         "why": "an executable check on the working directory failed"})
    if not declared:
        findings.append({"kind": "no-declared-artifacts", "why":
                         "a task with nothing to produce cannot be scored on progress"})
    elif not present:
        findings.append({"kind": "empty-run", "why":
                         "the run ended with none of its declared artifacts"})
    if r.get("exit_ok") and (missing or failed or (declared and not present)):
        findings.append({"kind": "exit-is-not-completion", "why":
                         "a normal exit is credited as success while the work is absent"})
    elif r.get("exit_ok") is False and not findings:
        findings.append({"kind": "failed-exit-with-work", "why":
                         "the work is on disk but the process reported failure; score the artifacts"})
    return {"format": FORMAT, "complete": not findings, "claim": bool(r.get("claimed_done")),
            "findings": findings, "missing": missing, "failed_checks": failed,
            "why": ("the declared work exists and its checks pass" if not findings else
                    "the finish claim is not evidence")}


def ladder(rows):
    """Empty-cell accounting: what an exit-status scorer would hide."""
    cells = [r for r in (rows or []) if isinstance(r, dict)]
    out = {}
    for cell in cells:
        harness = str(cell.get("harness") or "")
        if not harness:
            continue
        bucket = out.setdefault(harness, {"cells": 0, "empty": 0,
                                          "empty_normal_exit": 0})
        bucket["cells"] += 1
        declared = list(cell.get("declared_artifacts") or ())
        present = set(cell.get("artifacts") or ())
        empty = bool(declared) and not any(a in present for a in declared)
        if empty:
            bucket["empty"] += 1
            if cell.get("exit_ok"):
                bucket["empty_normal_exit"] += 1
    for harness, b in out.items():
        b["empty_rate"] = round(b["empty"] / b["cells"], 4) if b["cells"] else None
        b["hidden_rate"] = (round(b["empty_normal_exit"] / b["cells"], 4)
                            if b["cells"] else None)
    total = sum(b["cells"] for b in out.values())
    empty = sum(b["empty"] for b in out.values())
    hidden = sum(b["empty_normal_exit"] for b in out.values())
    return {"format": FORMAT, "harnesses": out,
            "cells": total, "empty": empty, "empty_normal_exit": hidden,
            "why": "an exit-status scorer credits these runs with work never written"}
