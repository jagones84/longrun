#!/usr/bin/env python3
"""Self-directed improvement — did the agent build its own learning loop?

Source: arXiv:2611.23219, "Do LLM Agents Still Need to Be Told How to Self-Improve?"
(round 120). The paper gives a frozen agent basic primitives, a compute budget and
a GENERAL goal, and lets it construct its own self-learning algorithm by
collecting experience and updating text documents — no externally imposed loop,
no real-world data. Sufficiently capable models self-improve under those
conditions and the learned text transfers across horizons, mechanics and 3-D
navigation.

The paper's contribution is the PARADIGM, not a loop to copy; so this module does
not prescribe a loop either. It audits a run record for the paradigm's
preconditions and for the evidence that the loop was the agent's own:

  * primitives and a budget are given, a general goal is given, the loop is NOT;
  * the curriculum is chosen by the agent (recorded, not declared);
  * updates are text artifacts with a recorded diff;
  * transfer is measured on tasks the agent did not train on.

A run that scores well under an externally imposed loop is not evidence for this
paradigm, and the audit says so instead of counting it.

Pure: run record in, verdict out.
"""
from __future__ import annotations

FORMAT = "longrun-self-directed/1"
VERDICTS = ("self-directed", "semi", "scripted")
REQUIRED = ("primitives", "budget", "goal", "artifacts", "transfer")


def audit(record):
    """Findings name what the record lacks; the verdict says how autonomous it was."""
    rec = record or {}
    findings = []
    if rec.get("loop") in ("external", "prescribed", "scheduler"):
        findings.append({"kind": "externally-imposed-loop",
                         "why": "the improvement loop was given, so this is not the paper's paradigm"})
    if not rec.get("primitives"):
        findings.append({"kind": "no-primitives", "why": "the agent had no declared operations"})
    budget = rec.get("budget") or {}
    if not (isinstance(budget, (int, float)) and budget > 0
            or isinstance(budget, dict) and budget.get("total")):
        findings.append({"kind": "no-budget", "why": "no compute budget to allocate"})
    goal = rec.get("goal") or {}
    if goal.get("specified_as") == "procedure":
        findings.append({"kind": "prescribed-curriculum",
                         "why": "the goal names the steps, so the curriculum is not the agent's"})
    elif not goal.get("general"):
        findings.append({"kind": "no-general-goal", "why": "no general improvement goal was declared"})
    if not rec.get("curriculum_choices"):
        findings.append({"kind": "no-curriculum-evidence",
                         "why": "no record of the agent choosing what to practise"})
    arts = [a for a in rec.get("artifacts") or [] if isinstance(a, dict)]
    if not arts:
        findings.append({"kind": "no-artifact", "why": "no text artifact was updated"})
    elif not any(a.get("diff") for a in arts):
        findings.append({"kind": "unrecorded-updates", "why": "artifact updates carry no recorded diff"})
    transfer = rec.get("transfer") or {}
    if not transfer:
        findings.append({"kind": "no-transfer-check",
                         "why": "nothing measures whether the artifact generalizes"})
    elif not transfer.get("held_out"):
        findings.append({"kind": "transfer-not-held-out",
                         "why": "the transfer tasks overlap the training tasks"})

    blocking = {"externally-imposed-loop", "no-primitives", "no-budget", "no-general-goal",
                "no-curriculum-evidence", "no-artifact"}
    if any(f["kind"] in blocking for f in findings):
        verdict = "scripted"
    elif findings:
        verdict = "semi"
    else:
        verdict = "self-directed"
    return {"format": FORMAT, "verdict": verdict, "findings": findings,
            "checked": [k for k in REQUIRED if k in rec]}


def transfer(record):
    """Did the learned text move a benchmark it was not trained on?"""
    tr = (record or {}).get("transfer") or {}
    before, after = tr.get("before"), tr.get("after")
    if not isinstance(before, (int, float)) or not isinstance(after, (int, float)):
        return {"format": FORMAT, "usable": False, "why": "before/after not recorded"}
    delta = round(after - before, 4)
    return {"format": FORMAT, "usable": True, "delta": delta,
            "held_out": bool(tr.get("held_out")),
            "verdict": "improved" if delta > 0 else ("flat" if delta == 0 else "regressed")}
