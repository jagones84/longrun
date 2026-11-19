#!/usr/bin/env python3
"""Harness record — describe the system that actually ran, and detect drift.

Source: arXiv:2610.40917, "Towards Portable Specification of the Agent Harness"
(round 122). A benchmark score is a property of a model-harness pair, yet the
harness has no settled record: it can change between releases, between runs and,
where the agent edits its own configuration, inside a run (paper Table 1, Table
2). The proposal is a mandatory core of eight component descriptions plus five
records: what ships, what is declared changeable, the run-start configuration,
the material changes during the run, and the run-end state.

  * `audit(record)` — is the record complete enough to say which controls were
    in force? Missing components, pairing, changeable parts or run-level records
    are findings, not silent gaps.
  * `degradation(changes, declared)` — progressive envelope degradation: a run of
    individually plausible edits that together weaken verification, widen
    authority or reach an unchangeable part.
  * `drift(declared, observed)` — reconcile the record with independently
    observed configuration; an unreported difference is the defect the record
    exists to expose.

Pure: records in, findings out; nothing is executed.
"""
from __future__ import annotations

FORMAT = "longrun-harness-record/1"
COMPONENTS = ("orchestration", "context_memory", "tool_interfaces",
              "operational_knowledge", "sandboxing", "permissions",
              "verification_observability", "runtime_lifecycle")
WEAKENING = {"verification": ("off", "reduced", "advisory"),
             "permissions": ("widened", "bypass", "auto"),
             "sandboxing": ("disabled", "off", "host")}
MAX_CHANGES = 3


def audit(record):
    """Is this record complete enough to state the controls in force?"""
    r = record or {}
    findings = []
    for name in ("name", "release", "model_pairing", "declared_changeable"):
        if not r.get(name):
            findings.append({"kind": "missing-field", "field": name,
                             "why": "a release record without it cannot identify the system"})
    parts = r.get("components") or {}
    for name in COMPONENTS:
        if not str((parts or {}).get(name) or "").strip():
            findings.append({"kind": "missing-component", "component": name,
                             "why": "an undescribed component is an undeclared control surface"})
    for name in ("run_start", "run_end"):
        if not r.get(name):
            findings.append({"kind": "missing-run-record", "field": name,
                             "why": "a run-level record is what distinguishes a mutable harness"})
    changes = r.get("changes") or []
    for i, ch in enumerate(changes):
        if not isinstance(ch, dict):
            continue
        for field in ("change", "requester", "authorization", "at"):
            if not ch.get(field):
                findings.append({"kind": "incomplete-change", "index": i, "field": field,
                                 "why": "a material change without it cannot be attributed"})
    return {"format": FORMAT, "ok": not findings, "findings": findings,
            "components": len(COMPONENTS),
            "why": ("the record names what ran" if not findings else
                    "the record cannot say which controls were in force")}


def degradation(changes, declared=None):
    """Progressive envelope degradation: individually small edits, jointly a loss of control."""
    rows = [c for c in (changes or []) if isinstance(c, dict)]
    declared = declared or {}
    may_change = {str(x) for x in declared.get("may_change") or []}
    protected = {str(x) for x in declared.get("may_not_change") or []}
    findings = []
    weakened = []
    for i, ch in enumerate(rows):
        component = str(ch.get("component") or "")
        value = str(ch.get("value") or "")
        if component in protected:
            findings.append({"kind": "protected-part-changed", "index": i,
                             "component": component,
                             "why": "a part declared unchangeable was edited"})
        elif may_change and component not in may_change:
            findings.append({"kind": "change-outside-scope", "index": i,
                             "component": component,
                             "why": "the declared changeable parts do not include it"})
        if component in WEAKENING and value in WEAKENING[component]:
            weakened.append(component)
    if len(set(weakened)) >= 2:
        findings.append({"kind": "progressive-envelope-degradation",
                         "components": sorted(set(weakened)),
                         "why": "separate edits jointly weaken verification and widen authority"})
    if not declared.get("may_not_change"):
        findings.append({"kind": "no-protected-parts", "why":
                         "nothing is declared unchangeable, so no edit can be out of scope"})
    if len(rows) > MAX_CHANGES:
        findings.append({"kind": "change-budget-exceeded", "changes": len(rows),
                         "budget": MAX_CHANGES,
                         "why": "a long run of small edits is the pattern this check exists for"})
    return {"format": FORMAT, "decision": "allow" if not findings else "block",
            "findings": findings, "changes": len(rows),
            "why": ("no edit leaves the declared envelope" if not findings else
                    "the sequence changes what the system is allowed to do")}


def drift(declared, observed):
    """Reconcile the record with independently observed configuration."""
    rec = {str(k): str(v) for k, v in (declared or {}).items()}
    obs = {str(k): str(v) for k, v in (observed or {}).items()}
    findings = []
    for key in sorted(set(rec) | set(obs)):
        if key not in obs:
            findings.append({"kind": "unverifiable", "component": key,
                             "why": "the record names a control nobody observed"})
        elif key not in rec:
            findings.append({"kind": "omitted-change", "component": key,
                             "observed": obs[key],
                             "why": "the effective configuration differs and was never recorded"})
        elif rec[key] != obs[key]:
            findings.append({"kind": "record-mismatch", "component": key,
                             "recorded": rec[key], "observed": obs[key],
                             "why": "the record and the effective state disagree"})
    return {"format": FORMAT, "ok": not findings, "findings": findings,
            "why": ("record reconciled with observation" if not findings else
                    "the recorded envelope is not the one in force")}
