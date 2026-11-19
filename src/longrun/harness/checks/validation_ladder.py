#!/usr/bin/env python3
"""Validation ladder — risk decides the evidence, and oversight must be real.

Source: arXiv:2611.22973, "VITAL" (round 138). Agentic systems in regulated work
cannot be validated by checking final outputs alone: a plausible answer can hide a
bad retrieval, a corrupted hand-off or an ineffective approval gate
(`vital_agentic_validation_2611.22973.md:40`, `:58`).

  * **risk is intrinsic and assessed before controls**: a ten-level base ladder
    (A1 informational to A10 adaptive) times reversibility, transparency and
    consequence multipliers, with patient floor rules (`:137`, `:181`).
  * **effective autonomy is what the architecture can reach**, not what the
    nominal workflow permits (`:135`).
  * **eight foundational controls precede validation** (`:203`).
  * **five behavioural domains include hand-offs and human control**
    (`:220`, `:228`).
  * **ten evidence categories**, proportionate to the class (`:234`).
  * **oversight is effective only with information, authority and time** at the
    point where intervention is expected (`:228`).
  * **calibration moves categories**: under a compressed calibration two use
    cases drop a class while the ordering of the extremes holds (`:346`).

  * `risk(row)` — the ladder, multipliers, score, class and floor rules.
  * `autonomy(row)` — nominal vs effective autonomy.
  * `controls(row)` — the eight foundational controls.
  * `domains(row)` — the five behavioural domains and the oversight test.
  * `evidence(row)` — the ten categories and proportionality.
  * `calibrate(rows)` — does the ordering survive a calibration change.
  * `advise(profile)` — map a harness profile onto the paper's failure modes.

Pure: use-case records in; findings out.
"""
from __future__ import annotations

FORMAT = "longrun-validation-ladder/1"

CONTROLS = ("quality-governance", "data-governance", "agent-design", "verification-validation",
            "traceability", "monitoring-change-control", "supplier-management",
            "transparency-auditability")

DOMAINS = ("reasoning-planning", "tool-use", "retrieval", "coordination", "human-agent")

EVIDENCE = ("context-of-use", "governance-model", "data-specification", "design-controls",
            "validation-protocol", "evidence-package", "traceability-specification",
            "monitoring-plan", "dependency-register", "transparency-specification")


def _num(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _class(score):
    if score is None:
        return None
    if score < 5:
        return "low"
    if score < 10:
        return "moderate"
    if score < 20:
        return "high"
    if score < 35:
        return "very-high"
    return "critical"


def risk(row):
    """Base autonomy times the three multipliers, then the patient floor rules."""
    r = row or {}
    base = _num(r.get("autonomy"))
    rev = _num(r.get("reversibility", 1.0))
    trans = _num(r.get("transparency", 1.0))
    patient = _num(r.get("patient_impact", 1.0))
    findings = []
    if base is None or not 1 <= base <= 10.5:
        return {"format": FORMAT, "findings": [{"kind": "invalid-autonomy", "autonomy": base}]}
    if rev is None or trans is None or patient is None or min(rev, trans, patient) <= 0:
        return {"format": FORMAT, "findings": [{"kind": "invalid-multiplier"}]}
    score = base * rev * trans * patient
    cls = _class(score)
    floor = None
    if patient >= 3 and base >= 7:
        floor = "critical"
    elif patient >= 3:
        floor = "very-high"
    elif patient >= 1.5:
        floor = "high"
    order = ["low", "moderate", "high", "very-high", "critical"]
    if floor and order.index(floor) > order.index(cls):
        findings.append({"kind": "patient-floor-applied", "score_class": cls, "floor": floor})
        cls = floor
    if cls in ("high", "very-high", "critical"):
        findings.append({"kind": "high-risk-class", "class": cls})
    else:
        findings.append({"kind": "lower-risk-class", "class": cls})
    return {"format": FORMAT, "score": round(score, 2), "class": cls,
            "multipliers": {"reversibility": rev, "transparency": trans,
                            "patient_impact": patient}, "findings": findings}


def autonomy(row):
    """Effective autonomy is the reachable action set, not the permitted one."""
    r = row or {}
    nominal = _num(r.get("nominal"))
    effective = _num(r.get("effective"))
    findings = []
    if nominal is None or effective is None:
        return {"format": FORMAT, "findings": [{"kind": "autonomy-unmeasured"}]}
    if effective > nominal:
        findings.append({"kind": "effective-exceeds-nominal", "nominal": nominal,
                         "effective": effective,
                         "why": "the score must be set on what the architecture can reach"})
    else:
        findings.append({"kind": "autonomy-bounded"})
    if r.get("isolation") is not True:
        findings.append({"kind": "no-isolation",
                         "why": "tool, network and credential reach bound autonomy"})
    if r.get("termination") is not True:
        findings.append({"kind": "cannot-terminate"})
    return {"format": FORMAT, "findings": findings}


def controls(row):
    """The eight controls that must exist before behavioural validation."""
    have = {str(c) for c in ((row or {}).get("controls") or ())}
    missing = [c for c in CONTROLS if c not in have]
    findings = ([{"kind": "missing-control", "control": c} for c in missing]
                or [{"kind": "controls-complete"}])
    return {"format": FORMAT, "missing": missing, "findings": findings}


def domains(row):
    """Five behavioural domains, and whether oversight can actually act."""
    r = row or {}
    have = {str(d) for d in (r.get("domains") or ())}
    findings = [{"kind": "domain-unvalidated", "domain": d} for d in DOMAINS if d not in have]
    oversight = r.get("oversight") or {}
    if oversight:
        lacks = [k for k in ("present", "informed", "authority", "time")
                 if oversight.get(k) is not True]
        if lacks:
            findings.append({"kind": "oversight-ineffective", "missing": lacks,
                             "why": "a reviewer without information, authority or time cannot contain the outcome"})
        else:
            findings.append({"kind": "oversight-effective"})
    if not findings:
        findings.append({"kind": "behaviour-validated"})
    return {"format": FORMAT, "findings": findings}


def evidence(row):
    """Ten evidence categories, with the package scaled to the class."""
    r = row or {}
    have = {str(e) for e in (r.get("evidence") or ())}
    cls = str(r.get("class") or "")
    missing = [e for e in EVIDENCE if e not in have]
    findings = []
    required = len(EVIDENCE) if cls in ("very-high", "critical") else 6
    if len(EVIDENCE) - len(missing) < required:
        findings.append({"kind": "evidence-insufficient", "present": len(EVIDENCE) - len(missing),
                         "required": required, "class": cls})
    if missing:
        findings.append({"kind": "evidence-missing", "categories": missing})
    if not findings:
        findings.append({"kind": "evidence-proportionate"})
    return {"format": FORMAT, "present": len(EVIDENCE) - len(missing),
            "required": required, "findings": findings}


def calibrate(rows):
    """Does a calibration change reorder the use cases or only their class?"""
    data = [r for r in (rows or ()) if _num(r.get("score")) is not None]
    if len(data) < 2:
        return {"format": FORMAT, "findings": [{"kind": "not-enough-cases"}]}
    ordered = sorted(data, key=lambda r: _num(r["score"]))
    low, high = ordered[0], ordered[-1]
    findings = []
    changed = [r for r in data if r.get("class_changed") is True]
    if changed:
        findings.append({"kind": "class-unstable", "cases": len(changed)})
    if low.get("still_lowest") is True and high.get("still_highest") is True:
        findings.append({"kind": "ordering-stable"})
    else:
        findings.append({"kind": "ordering-unstable"})
    return {"format": FORMAT, "cases": len(data), "findings": findings}


def advise(profile):
    """Map a harness profile onto the paper's failure modes."""
    p = profile or {}
    have = {str(key) for key, value in p.items() if value}
    findings = []
    checks = (
        ("assesses_intrinsic_risk", "controls-first", "risk is set before controls"),
        ("uses_effective_autonomy", "nominal-autonomy", "score what the architecture can reach"),
        ("applies_consequence_floor", "score-only", "patient impact sets a minimum class"),
        ("requires_controls", "uncontrolled-deployment", "eight controls precede validation"),
        ("validates_trajectories", "output-only", "intermediate steps can be plausible and wrong"),
        ("tests_oversight", "oversight-assumed", "information, authority and time are testable"),
        ("documents_evidence", "undocumented", "ten categories, proportionate to risk"),
        ("calibrates_thresholds", "fixed-thresholds", "categories move under calibration"),
    )
    for key, kind, why in checks:
        if key not in have:
            findings.append({"kind": kind, "why": why})
    return {"format": FORMAT, "findings": findings}
