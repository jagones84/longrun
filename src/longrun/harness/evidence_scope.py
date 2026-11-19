#!/usr/bin/env python3
"""Evidence scope — a passing check is not the requested operation.

Source: arXiv:2611.22835, "When Passing Checks Do Not Establish Completion:
Evidence Interpretation in Coding Agents" (round 132). Verification procedures
must preserve execution facts, interpret their scope and discharge checking
obligations; an agent that only reads the check's boolean conflates three things.

  * **facts, verdicts and scope are separate**: 40/50 responses carry correct
    facts while only 32/50 carry a correct finite verdict, and all 122
    delivered labels are correct while only 95/128 meet the joint fact-and-scope
    contract (`completion_evidence_coding_agents_2611.22835.md:100`, `:106`).
  * **a finite evidence item is (h, c, p, o, w)** — source digest, selected
    check, observed phase, relevant operation, recorded witness (`:56`).
  * **a requested check is not target entry**: a production edit can obstruct
    startup, so the runner reports UNKNOWN before either selected test runs
    (`:114`–`:134`); UNKNOWN is not FAIL.
  * **a positive witness is not the intended operation**: a write-side event
    satisfies an explicit-flush assertion while the explicit operation adds
    nothing (`:157`), and a cleanup event answers a live obligation only by
    accident (`:183`–`:196`).
  * **three obligations** — live explicit forwarding, cleanup-context
    forwarding, write-only compatibility (`:167`–`:171`).
  * **repair success does not certify its explanation** (`:343`).

  * `item(source, check, phase, operation, witness)` — build the evidence item;
    refuse a missing field.
  * `scope(claim)` — facts vs verdict vs authorized scope.
  * `witness(item, expected_operation)` — is the witness attributable to the
    operation the claim needs?
  * `obligation(item, obligation)` — does the evidence discharge THAT obligation?
  * `reachability(run)` — did checking reach the target, and was UNKNOWN read
    as FAIL?
  * `classify(outcome)` — new regression / residual defect / altered context /
    not established.
  * `explanation(repair)` — a successful repair with replayable claims.
  * `advise(profile)` — map a harness profile onto the paper's failure modes.

Pure: records in, findings out; nothing is executed.
"""
from __future__ import annotations

FORMAT = "longrun-evidence-scope/1"

FIELDS = ("source", "check", "phase", "operation", "witness")
PHASES = ("entry", "setup", "body", "cleanup", "warmup", "measured")
OBLIGATIONS = ("live-forwarding", "cleanup-forwarding", "write-only-compatibility")
OUTCOMES = ("pass", "fail", "unknown")


def _text(value):
    return str(value).strip() if value is not None else ""


def item(source, check, phase, operation, witness):
    """Build an evidence item (h, c, p, o, w); refuse a missing field."""
    values = {"source": source, "check": check, "phase": phase,
              "operation": operation, "witness": witness}
    findings = []
    for name in FIELDS:
        if not _text(values[name]):
            findings.append({"kind": "%s-missing" % name.replace("_", "-"),
                             "why": "an evidence item binds source, check, phase, operation and witness"})
    if _text(phase) and _text(phase).lower() not in PHASES:
        findings.append({"kind": "unknown-phase", "phase": phase,
                         "why": "a phase outside the execution vocabulary cannot scope the item"})
    return {"format": FORMAT, "item": {k: _text(v) for k, v in values.items()},
            "complete": not findings, "findings": findings}


def scope(claim):
    """Facts, verdict and authorized scope are three different claims."""
    c = claim or {}
    facts = c.get("facts") or {}
    verdict = c.get("verdict")
    authorized = _text(c.get("authorized_scope"))
    observed = _text(c.get("observed_scope"))
    findings = []
    has_facts = bool(facts)
    has_verdict = verdict not in (None, "", "abstain")
    if has_facts and not has_verdict:
        findings.append({"kind": "facts-without-verdict",
                         "why": "correct reported facts need not yield the requested finite verdict"})
    if has_verdict and not has_facts:
        findings.append({"kind": "verdict-without-facts",
                         "why": "a finite verdict with no recorded facts cannot be audited"})
    if not authorized:
        findings.append({"kind": "scope-unstated",
                         "why": "a claim must name the scope it is authorized to assert"})
    elif observed and observed != authorized:
        findings.append({"kind": "out-of-scope", "authorized": authorized,
                         "observed": observed,
                         "why": "the check ran at one scope; the claim asserts another"})
    return {"format": FORMAT, "facts": sorted(facts), "verdict": verdict,
            "authorized_scope": authorized, "observed_scope": observed,
            "findings": findings}


def witness(ev, expected_operation):
    """Is the recorded witness attributable to the operation the claim needs?"""
    i = (ev or {}).get("item") or {}
    expected = _text(expected_operation)
    phase = _text(i.get("phase")).lower()
    producer = _text(i.get("producer") or i.get("witness"))
    operation = _text(i.get("operation"))
    findings = []
    if not producer:
        findings.append({"kind": "witness-not-attributed",
                         "why": "a boolean witness does not identify which operation produced it"})
    candidates = ev.get("producers") if isinstance(ev, dict) else None
    if isinstance(candidates, list) and len(set(str(x) for x in candidates)) > 1:
        findings.append({"kind": "positive-witness-ambiguous",
                         "producers": sorted(set(str(x) for x in candidates)),
                         "why": "one boolean with two possible producers cannot bind the claim"})
    if expected and operation and operation != expected:
        findings.append({"kind": "witness-from-other-operation",
                         "expected": expected, "operation": operation,
                         "why": "the witness belongs to a different operation than the one claimed"})
    if phase in ("entry", "setup", "warmup"):
        findings.append({"kind": "witness-before-measurement", "phase": phase,
                         "why": "a pre-measurement phase cannot witness a measured operation"})
    return {"format": FORMAT, "expected_operation": expected,
            "operation": operation, "phase": phase,
            "attributed": not findings, "findings": findings}


def obligation(ev, name):
    """Does the evidence discharge one of the three obligations?"""
    i = (ev or {}).get("item") or {}
    phase = _text(i.get("phase")).lower()
    operation = _text(i.get("operation"))
    findings = []
    if name not in OBLIGATIONS:
        return {"format": FORMAT, "obligation": name, "discharged": False,
                "findings": [{"kind": "unknown-obligation", "obligation": name}]}
    if name == "live-forwarding":
        if phase == "cleanup":
            findings.append({"kind": "cleanup-is-not-live", "phase": phase,
                             "why": "cleanup-context forwarding does not discharge live explicit forwarding"})
        if operation and "flush" in operation.lower() and "explicit" not in operation.lower():
            findings.append({"kind": "witness-from-other-operation", "operation": operation,
                             "why": "a write-side event is not the explicit forwarding the claim needs"})
    if name == "cleanup-forwarding" and phase not in ("cleanup",):
        findings.append({"kind": "cleanup-obligation-unmeasured", "phase": phase,
                         "why": "no cleanup-context observation was recorded"})
    if name == "write-only-compatibility":
        if ev.get("write_only_supported") is None:
            findings.append({"kind": "compatibility-unmeasured",
                             "why": "a previously valid write-only output was not re-run"})
        elif ev.get("write_only_supported") is False:
            findings.append({"kind": "write-only-broken",
                             "why": "the repair broke a sink with write but no flush"})
    return {"format": FORMAT, "obligation": name, "phase": phase,
            "operation": operation, "discharged": not findings,
            "findings": findings}


def reachability(run):
    """Did checking reach the target, and was UNKNOWN read as FAIL?"""
    r = run or {}
    entered = r.get("target_entered")
    outcomes = [str(o).lower() for o in (r.get("outcomes") or ())]
    edited = bool(r.get("startup_edited"))
    findings = []
    if entered is False:
        findings.append({"kind": "reachability-obstructed",
                         "why": "a production edit can stop startup before the selected check runs"})
    if "unknown" in outcomes and r.get("unknown_counted_as_fail"):
        findings.append({"kind": "unknown-read-as-fail",
                         "why": "a runner error before entry is UNKNOWN, not a failing assertion"})
    if edited and not r.get("context_declared"):
        findings.append({"kind": "altered-context",
                         "why": "substituting startup code changes the experiment; the result is conditional"})
    return {"format": FORMAT, "target_entered": entered,
            "outcomes": outcomes, "findings": findings}


def classify(outcome):
    """New regression, residual defect, altered-context difference, or nothing."""
    o = outcome or {}
    original = o.get("original")
    candidate = o.get("candidate")
    reference = o.get("reference")
    altered = bool(o.get("altered_context"))
    findings = []
    label = "not-established"
    if altered:
        label = "altered-context"
        findings.append({"kind": "altered-context",
                         "why": "a modified validation context is a different experiment"})
    elif original is not None and candidate is not None and reference is not None:
        if original == reference:
            findings.append({"kind": "non-discriminating-check",
                             "why": "a check that cannot separate the original from the reference proves nothing"})
        elif candidate == reference:
            label = "repaired"
        elif candidate == original:
            label = "residual-defect"
            findings.append({"kind": "residual-defect",
                             "why": "the candidate still shows the original behaviour the reference fixes"})
        else:
            label = "new-regression"
            findings.append({"kind": "new-regression",
                             "why": "the candidate differs from both the original and the reference"})
    return {"format": FORMAT, "label": label, "findings": findings}


def explanation(repair):
    """A successful repair does not validate every claim in its explanation."""
    r = repair or {}
    claims = r.get("claims") or []
    replayed = {str(k): bool(v) for k, v in (r.get("replayed") or {}).items()}
    findings = []
    unsupported = [str(c) for c in claims
                   if str(c) in replayed and not replayed[str(c)]]
    if r.get("repair_succeeded") and unsupported:
        findings.append({"kind": "repair-success-does-not-certify-explanation",
                         "unsupported": sorted(unsupported),
                         "why": "a repaired metric does not make the diagnosis's claims true"})
    if claims and not replayed:
        findings.append({"kind": "explanation-unreplayed",
                         "why": "no claim was replayed, so the explanation is not evidence"})
    return {"format": FORMAT, "repair_succeeded": bool(r.get("repair_succeeded")),
            "unsupported": sorted(unsupported), "findings": findings}


def advise(profile):
    """Map a harness profile onto the paper's failure modes."""
    p = profile or {}
    have = {str(k) for k, v in p.items() if v}
    findings = []
    checks = (
        ("records_evidence_item", "no-evidence-item", "a completion is claimed without (source, check, phase, operation, witness)"),
        ("separates_fact_verdict_scope", "facts-and-verdict-conflated", "a correct fact is read as the requested verdict"),
        ("distinguishes_unknown", "unknown-not-modelled", "a runner error before entry is scored as a failure"),
        ("checks_witness_origin", "witness-origin-unchecked", "a positive boolean is accepted without its producer"),
        ("separates_obligations", "obligations-conflated", "cleanup, live and compatibility evidence are one bucket"),
        ("replays_explanations", "explanations-unreplayed", "a diagnosis is trusted because the repair passed"),
    )
    for key, kind, why in checks:
        if key not in have:
            findings.append({"kind": kind, "why": why})
    return {"format": FORMAT, "findings": findings}
