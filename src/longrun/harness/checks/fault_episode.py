#!/usr/bin/env python3
"""Fault episode record — where the error ENTERED, how it travelled, what caught it.

Source: arXiv:2611.13254, "Dependable Long-Horizon LLM Agents: A
Trajectory-Centered Empirical Study of Where Errors Enter and Which Controls
Reach Them" (round 115). A failure label records a symptom. The paper's episode
record ties a candidate fault to its:

  origin -> propagation -> detection -> response -> consequence,

locates each event by operational phase and state domain, and names the control
families whose observation and reach cover it. Its findings are the ones this
audit enforces structurally: faults enter early (median 0.18 of the run); in 72%
of failures the trajectory already held contradicting evidence and in 88% of
those nobody acted; a checkpoint helps only when the fault is in state (in 56 of
95 a restore would simply replay a bad plan).

This module validates such a record and derives the control families. It does
not read a trajectory by itself; the caller supplies the record.

Pure: record in, findings out.
"""
from __future__ import annotations

FORMAT = "longrun-fault-episode/1"
PHASES = ("deliberation", "execution", "review", "recovery")
DOMAINS = ("task", "knowledge", "tool", "environment")
SERVICES = ("reliability", "safety", "integrity")
REQUIRED = ("origin", "symptom", "propagation", "detection", "response", "consequence")


def _origin(rec):
    o = rec.get("origin") or {}
    return o if isinstance(o, dict) else {}


def audit(rec):
    rec = rec or {}
    findings = []
    for field in REQUIRED:
        if not rec.get(field):
            findings.append({"kind": "missing-field", "field": field})
    o = _origin(rec)
    if o:
        if o.get("phase") and o["phase"] not in PHASES:
            findings.append({"kind": "invalid-phase", "value": o["phase"]})
        if o.get("domain") and o["domain"] not in DOMAINS:
            findings.append({"kind": "invalid-domain", "value": o["domain"]})
        steps, length = o.get("step"), rec.get("run_length")
        if isinstance(steps, (int, float)) and isinstance(length, (int, float)) and length:
            if steps / length > 0.5:
                findings.append({"kind": "late-origin",
                                 "fraction": round(steps / length, 2),
                                 "why": "faults usually enter early; a late origin needs evidence"})
    det = rec.get("detection") or {}
    resp = str(rec.get("response") or "").lower()
    if rec.get("evidence_before") and not det.get("flagged"):
        findings.append({"kind": "evidence-not-flagged",
                         "why": "the trajectory held contradicting evidence and nothing flagged it"})
    if det.get("flagged") and resp in ("", "none", "ignored", "rationalized", "deflected"):
        findings.append({"kind": "flagged-not-acted",
                         "why": "a deviation was flagged but no response removed it"})
    if resp == "restore" and str(o.get("fault_in") or "") in ("plan", "policy"):
        findings.append({"kind": "restore-would-replay-the-fault",
                         "why": "the fault sits in plan/policy; restoring state replays it"})
    cons = rec.get("consequence") or {}
    if cons and cons.get("service") and cons["service"] not in SERVICES:
        findings.append({"kind": "invalid-service", "value": cons["service"]})

    missing = [f for f in findings if f["kind"] == "missing-field"]
    verdict = "unusable" if missing else ("partial" if findings else "complete")
    return {"format": FORMAT, "findings": findings, "verdict": verdict}


def controls(rec):
    """The control families whose observation and reach cover this episode."""
    rec = rec or {}
    o = _origin(rec)
    out = []
    if rec.get("evidence_before"):
        out.append({"family": "independent-judge",
                    "why": "unused evidence exists and can be read by a judge"})
    out.append({"family": "task-contract",
                "why": "the task specification is fixed at admission"})
    if o.get("source"):
        out.append({"family": "provenance",
                    "why": "the fault names a source that can be ranked"})
    if o.get("domain") in ("tool", "environment"):
        out.append({"family": "recheck-against-environment",
                    "why": "the state can be re-read instead of trusted"})
    if str(o.get("fault_in") or "") in ("state", "tool"):
        out.append({"family": "checkpoint",
                    "why": "the fault is in restorable state"})
    return {"format": FORMAT, "controls": out, "count": len(out)}
