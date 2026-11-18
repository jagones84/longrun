#!/usr/bin/env python3
"""Harness evolution — attribute a failure, then admit the edit that fixes it.

Source: arXiv:2611.22299, "Harnesses That Improve Themselves: A Unifying
Framework for Self-Improving Agent Harnesses" (round 121). Two claims drive this
module.

  * A single failed rollout mixes a random model slip with a structural harness
    bug. Reflecting on one failure cannot separate them, so an edit is proposed
    only for a RECURRING failure, and only when the run diverges between what
    the model reasoned and what the harness executed (paper §III).
  * An edit is admitted only through the four safeguards (§IV, Fig. 2): one
    module at a time, a small general patch tied to the recurring failure,
    runtime execution plus held-out non-regression, and development/test pools
    that never overlap. A candidate that fails a safeguard is refused, never
    merged (§VI, Table II: prompt bloat, dead code, benchmark gaming).

Pure: records in, verdict out; nothing is executed and no file is written.
"""
from __future__ import annotations

FORMAT = "longrun-harness-evolution/1"
MODULES = ("ctx", "ctrl", "act", "ver")          # context, control, action, verify
EDIT_BUDGET_LINES = 40                            # what "small" means here
HARNESS_ERRORS = ("edit-format", "cwd-lost", "compaction-dropped",
                  "exit-before-tests", "tool-rejected")
DECISIONS = ("merge", "archive", "route", "refuse")


def diagnose(record):
    """Harness flaw, model limit, or undecided — never from one rollout (§III)."""
    runs = [r for r in (record or {}).get("rollouts") or [] if isinstance(r, dict)]
    findings = []
    failed = [r for r in runs if r.get("failed", True)]
    if not failed:
        return {"format": FORMAT, "attribution": "none", "findings": [],
                "recurring": 0, "why": "no failed rollout to attribute"}
    if len(failed) < 2:
        findings.append({"kind": "single-rollout", "why":
                         "one failure cannot separate a random slip from a harness bug"})
        return {"format": FORMAT, "attribution": "undecided", "findings": findings,
                "recurring": 1, "why": "needs a repeated failure"}
    recovered = [r for r in failed if r.get("retry_solved")]
    blocked = [r for r in failed
               if str(r.get("harness_error") or "") in HARNESS_ERRORS
               and r.get("reasoning_named_cause")]
    harness = recovered or blocked
    if len(harness) >= 2:
        kinds = sorted({str((r.get("harness_error") or "recovered-on-retry"))
                        for r in harness})
        return {"format": FORMAT, "attribution": "harness", "findings": [
                    {"kind": "harness-flaw", "why":
                     "the model identified the cause but execution blocked it, "
                     "or a retry solved the same task",
                     "evidence": kinds}],
                "recurring": len(harness), "why": "an edit is worth proposing"}
    clean = [r for r in failed if not r.get("harness_error")
             and r.get("action_executed", True)]
    if len(clean) >= 2:
        return {"format": FORMAT, "attribution": "model",
                "findings": [{"kind": "model-limit", "why":
                              "calls executed cleanly and every rollout failed on the task"}],
                "recurring": len(clean),
                "why": "no harness edit: search compute would be wasted"}
    return {"format": FORMAT, "attribution": "undecided", "findings": findings,
            "recurring": len(failed), "why": "the evidence does not separate the two"}


def admit(candidate):
    """The Stage-3 gate: merge, archive, route or refuse one harness edit (§IV)."""
    c = candidate or {}
    findings = []
    module = str(c.get("module") or "")
    if module not in MODULES:
        findings.append({"kind": "full-harness-edit", "why":
                         "the edit does not name one of the four modules"})
    diff_lines = int(c.get("diff_lines") or 0)
    budget = int(c.get("edit_budget") or EDIT_BUDGET_LINES)
    if diff_lines > budget:
        findings.append({"kind": "edit-too-large", "diff_lines": diff_lines,
                         "budget": budget, "why":
                         "a large patch is not tied to one recurring failure"})
    if not c.get("runtime_executed"):
        findings.append({"kind": "not-executed", "why":
                         "the new code path was never run in the task image"})
    if c.get("dead_code"):
        findings.append({"kind": "dead-code", "why":
                         "the added path never executes, so a pass proves nothing"})
    held = c.get("held_out") or {}
    if not c.get("held_out_split"):
        findings.append({"kind": "no-held-out", "why":
                         "no split was held out from the edit and from the tests"})
    elif float(held.get("after", 0)) <= float(held.get("before", 0)):
        findings.append({"kind": "no-held-out-gain", "why":
                         "the change does not improve the held-out split"})
    if c.get("dev_test_overlap"):
        findings.append({"kind": "dev-test-overlap", "why":
                         "the evolution pool overlaps the test pool"})
    if c.get("hardcoded_task"):
        findings.append({"kind": "hardcoded-rule", "why":
                         "a task-specific shortcut is not a harness mechanism"})
    cap = c.get("token_cap")
    if cap is not None and int(c.get("token_per_task") or 0) > int(cap):
        findings.append({"kind": "token-cap-exceeded",
                         "token_per_task": c.get("token_per_task"), "cap": cap,
                         "why": "the edit buys accuracy with unbounded runtime cost"})
    if not findings:
        decision = "route" if c.get("router_branch") else "merge"
        return {"format": FORMAT, "decision": decision, "findings": [],
                "why": "one module, small, executed, better held out"}
    return {"format": FORMAT, "decision": "refuse", "findings": findings,
            "why": "a safeguard failed, so the edit is not merged"}


def bloat(rules):
    """Prompt-bloat check (§VI, Mode 1): rules must be few, triggered and pruned."""
    rows = [r for r in (rules or []) if isinstance(r, dict)]
    live = [r for r in rows if not r.get("pruned")]
    unnecessary = [r for r in live if not r.get("triggered")]
    return {"format": FORMAT, "live": len(live), "unnecessary": len(unnecessary),
            "decision": "prune" if unnecessary else "keep",
            "findings": [{"kind": "unnecessary-rule", "rule": r.get("id"),
                          "why": "a rule added for a failure that never recurred"}
                         for r in unnecessary]}
