#!/usr/bin/env python3
"""Lesson admission — a memory write is a hypothesis until a probe survives it.

Source: arXiv:2611.14326, "When Should Agents Remember? Falsification-Gated
Self-Evolution for LLM Agents" (round 125). Writing an episode-derived lesson
straight into persistent memory treats local success as evidence of reusable
knowledge; the paper's answer is to represent each candidate lesson as a
structured hypothesis — precondition, behaviour change, expected effect,
verifier — apply it only in a TEMPORARY state, and test it on three kinds of
probe (target-transfer, falsification, archived-regression) before committing,
refining or rejecting it (§Abstract). Its reported residuals are the point of the
gate: falsification failures 5.0%, regression damage 1.3%, harmful committed
updates 3.6% — small, not zero, so the module returns the measured numbers
instead of a pass/fail sentiment.

The thresholds below are this module's stated reading, not the paper's trained
policy: any falsified probe rejects; any regression drop rejects; no measurable
transfer refines; a missing probe class refines rather than commits. A lesson
that has not been probed can never be committed.
"""
from __future__ import annotations

FORMAT = "longrun-lesson-gate/1"
FIELDS = ("precondition", "change", "expected", "verifier")


def hypothesis(lesson):
    """Is this a testable hypothesis, or just a sentence that felt true?"""
    lesson = lesson if isinstance(lesson, dict) else {}
    findings = [{"kind": "missing-field", "field": f}
                for f in FIELDS if not str(lesson.get(f) or "").strip()]
    return {"format": FORMAT, "valid": not findings,
            "lesson": str(lesson.get("id") or ""), "findings": findings,
            "why": ("structured and testable" if not findings
                    else "a lesson without precondition, change, expected effect or verifier cannot be falsified")}


def trial(lesson, state, persist=False):
    """Apply the lesson to a TEMPORARY state; persistence before probing is refused."""
    lesson = lesson if isinstance(lesson, dict) else {}
    findings = []
    if persist:
        findings.append({"kind": "premature-persist",
                         "why": "a hypothesis is applied to a temporary state until its probes pass"})
    probed = bool(lesson.get("probes"))
    if persist and not probed:
        return {"format": FORMAT, "applied": False, "temporary": True,
                "findings": findings, "why": "no probe, no persistent write"}
    return {"format": FORMAT, "applied": True, "temporary": not persist,
            "state": str(state or ""), "findings": findings,
            "why": ("applied in place for a probe" if not persist
                    else "applied to persistent state after its probes")}


def _gain(pairs):
    """Mean measured effect over fresh pairs; a pair needs before and after."""
    values = []
    for pair in pairs or ():
        if not isinstance(pair, dict):
            continue
        try:
            values.append(float(pair.get("after")) - float(pair.get("before")))
        except (TypeError, ValueError):
            continue
    return (sum(values) / len(values)) if values else None


def probe(lesson, results):
    """Commit, refine or reject from transfer, falsification and regression probes."""
    lesson = lesson if isinstance(lesson, dict) else {}
    results = results if isinstance(results, dict) else {}
    findings = []
    complete = hypothesis(lesson)
    if not complete["valid"]:
        return {"format": FORMAT, "decision": "reject",
                "findings": complete["findings"] + findings,
                "why": "an unstructured lesson is not admitted at all"}
    transfer = results.get("target_transfer") or []
    falsification = results.get("falsification") or []
    regression = results.get("regression") or []
    for name, rows in (("target-transfer", transfer), ("falsification", falsification),
                       ("archived-regression", regression)):
        if not rows:
            findings.append({"kind": "missing-probe", "probe": name,
                             "why": "a class with no observation is not a pass"})
    falsified = [r for r in falsification
                 if isinstance(r, dict) and r.get("held") is False]
    if falsified:
        findings.append({"kind": "falsified", "cases": len(falsified),
                         "why": "the stated effect did not hold where it was tested"})
        return {"format": FORMAT, "decision": "reject", "findings": findings,
                "why": "a falsified hypothesis is not refined; it is dropped"}
    damaged = [r for r in regression
               if isinstance(r, dict) and _gain([r]) is not None and _gain([r]) < 0]
    if damaged:
        findings.append({"kind": "regression-damage", "cases": len(damaged),
                         "mean": round(sum(_gain([r]) for r in damaged) / len(damaged), 4)})
        return {"format": FORMAT, "decision": "reject", "findings": findings,
                "why": "a reusable lesson that breaks archived work is not reusable"}
    mean_gain = _gain(transfer)
    if mean_gain is None:
        findings.append({"kind": "no-transfer-measurement",
                         "why": "target-transfer pairs carry no before/after"})
        return {"format": FORMAT, "decision": "refine", "gain": None,
                "findings": findings,
                "why": "nothing was measured on the target, so nothing may be committed"}
    if mean_gain <= 0:
        findings.append({"kind": "no-transfer", "gain": round(mean_gain, 4)})
        return {"format": FORMAT, "decision": "refine", "gain": round(mean_gain, 4),
                "findings": findings,
                "why": "the effect did not transfer; the lesson is narrowed, not stored"}
    if any(f["kind"] == "missing-probe" for f in findings):
        return {"format": FORMAT, "decision": "refine", "gain": round(mean_gain, 4),
                "findings": findings,
                "why": "one probe class is unobserved, so the risk is unknown"}
    return {"format": FORMAT, "decision": "commit", "gain": round(mean_gain, 4),
            "findings": findings,
            "why": "transfer positive, nothing falsified, no archived regression"}
