#!/usr/bin/env python3
"""Privacy audit — gate the outbound write, not only the final answer.

Source: arXiv:2610.06454, "AgentPrivArena" (round 144). Outcome-level evaluation
misses an agent that reads a sensitive record and never prints it, and simulated
trajectories miss the failures that only appear when the agent must find the
record (`agent_privacy_arena_2610.06454.txt:57`, `:60`, `:86`). AgentPrivAudit
extracts explicit information flows at the read boundary and arbitrates every
outbound write against a configurable criterion (`:227`, `:243`, `:252`).

  * **a flow has five attributes**: sender, recipient, subject, type and the
    transmission principle (`:295`, `:300`).
  * **three dispositions**: PASS, ABSTRACT or BLOCK, decided by a pluggable
    criterion rather than hard-coded (`:304`, `:311`, `:318`).
  * **three criteria**: contextual integrity, PII and data minimization — one
    question each, same schema and same enforcement path (`:325`, `:330`).
  * **measured**: leakage falls from 46.8% unmitigated to 17.8% under contextual
    integrity with helpfulness moving 2.60 → 2.59; the cross-executor spread
    falls from 25.4 pp to 3.1 pp (`:331`, `:334`, `:406`, `:417`).
  * **the residual is extraction**: 70.5% of read items become flows, so 29.5%
    can never be gated, and 47.7% of protected facts are never read at all
    (`:343`, `:478`, `:531`).
  * **the same criterion as a prompt is nearly inert**: 46.8% → 40.7% stated,
    against 21.7% enforced (`:441`, `:463`).

  * `flow(row)` — the five-attribute schema and what is missing.
  * `disposition(row)` — PASS / ABSTRACT / BLOCK under one criterion.
  * `inventory(reads)` — exposure, extraction recall and disposition mix.
  * `compare(rows)` — leak rate by condition and the spread it collapses.
  * `criteria(rows)` — stated against enforced.
  * `auditor(rows)` — whether the auditor or the executor carries the effect.
  * `audit(record)` — the evaluation mistakes this design corrects.
  * `advise(profile)` — map a harness profile onto the paper's failure modes.

Pure: flows and rows in; dispositions and verdicts out.
"""
from __future__ import annotations

FORMAT = "longrun-privacy-audit/1"

FLOW_FIELDS = ("sender", "recipient", "subject", "type", "principle")
CRITERIA = ("ci", "pii", "minimization")
DISPOSITIONS = ("pass", "abstract", "block")
PII_TYPES = ("name", "email", "phone", "address", "identifier", "health",
             "financial", "location", "communication", "biometric", "belief")
CREDENTIAL_TYPES = ("password", "token", "api_key", "private_key", "otp",
                    "session_cookie", "seed_phrase")


def flow(row):
    """One information flow; a missing attribute is named, not inferred."""
    r = row or {}
    missing = [key for key in FLOW_FIELDS if r.get(key) in (None, "")]
    return {"format": FORMAT, "flow": {key: r.get(key) for key in FLOW_FIELDS},
            "missing": missing,
            "verdict": "flow-complete" if not missing else "flow-incomplete"}


def disposition(row):
    """PASS, ABSTRACT or BLOCK under one criterion."""
    r = row or {}
    criterion = str(r.get("criterion") or "ci")
    if criterion not in CRITERIA:
        return {"format": FORMAT, "verdict": "unknown-criterion",
                "known": list(CRITERIA)}
    kind = str(r.get("type") or "").lower()
    principal = r.get("subject_is_principal")
    necessary = r.get("necessary")
    appropriate = r.get("appropriate")
    relationship = r.get("relationship") is True
    public = r.get("channel_public") is True
    if criterion == "pii":
        if kind in CREDENTIAL_TYPES:
            decision, why = "block", "credential"
        elif kind in PII_TYPES and principal is not True:
            decision, why = "abstract", "pii-about-another-person"
        else:
            decision, why = "pass", "no-pii"
    elif criterion == "minimization":
        if necessary is False:
            decision, why = "block", "not-necessary"
        elif appropriate is False:
            decision, why = "abstract", "necessary-but-inappropriate"
        else:
            decision, why = "pass", "necessary"
    else:
        if appropriate is False:
            decision, why = "block", "inappropriate-audience"
        elif principal is not True and (relationship or public):
            decision, why = "abstract", "relational-or-public-context"
        else:
            decision, why = "pass", "appropriate-flow"
    return {"format": FORMAT, "criterion": criterion, "decision": decision,
            "reason": why, "verdict": "disposed"}


def inventory(reads):
    """Exposure over protected items, extraction over exposed ones, dispositions."""
    exposed = extracted = reference = 0
    mix = {name: 0 for name in DISPOSITIONS}
    for row in reads or []:
        r = row or {}
        reference += int(r.get("reference_items") or 0)
        exposed += int(r.get("exposed_items") or 0)
        extracted += int(r.get("extracted_flows") or 0)
        for name in DISPOSITIONS:
            mix[name] += int((r.get("dispositions") or {}).get(name) or 0)
    total = sum(mix.values())
    exposure_rate = exposed / reference if reference else 0.0
    recall = extracted / exposed if exposed else 0.0
    shares = {name: (mix[name] / total if total else 0.0) for name in DISPOSITIONS}
    return {"format": FORMAT, "reference_items": reference,
            "exposed_items": exposed, "extracted_flows": extracted,
            "exposure_rate": exposure_rate, "extraction_recall": recall,
            "dispositions": shares,
            "verdict": "extraction-bounds-the-audit" if recall < 0.8
            else "extraction-adequate"}


def compare(rows):
    """Leak rate by condition; enforcement should collapse the spread."""
    table = {}
    for row in rows or []:
        condition = str((row or {}).get("condition") or "")
        leak = _float((row or {}).get("leak"))
        if not condition or leak is None:
            continue
        table.setdefault(condition, []).append(leak)
    if not table:
        return {"format": FORMAT, "verdict": "no-rows"}
    means = {name: sum(values) / len(values) for name, values in table.items()}
    spreads = {name: max(values) - min(values) for name, values in table.items()}
    baseline = means.get("c0")
    best = min(means, key=lambda name: means[name])
    audit_spreads = [spread for name, spread in spreads.items() if name != "c0"]
    verdict = ("enforcement-collapses-spread"
               if baseline is not None and spreads.get("c0", 0) >= 0.20
               and audit_spreads and max(audit_spreads) <= 0.05
               else "spread-persists")
    return {"format": FORMAT, "means": means, "spreads": spreads,
            "best": best, "verdict": verdict,
            "reduction": (baseline - means[best]) if baseline is not None else None}


def criteria(rows):
    """The same rule stated in a prompt, then enforced by the mechanism."""
    clean = []
    for row in rows or []:
        name = str((row or {}).get("criterion") or "")
        prompt = _float((row or {}).get("prompt"))
        audit = _float((row or {}).get("audit"))
        if not name or prompt is None or audit is None:
            continue
        clean.append({"criterion": name, "prompt": prompt, "audit": audit,
                      "gain": prompt - audit})
    if not clean:
        return {"format": FORMAT, "verdict": "no-rows"}
    gains = [r["gain"] for r in clean]
    return {"format": FORMAT, "rows": clean, "min_gain": min(gains),
            "max_gain": max(gains),
            "verdict": "mechanism-not-wording" if min(gains) >= 0.15
            else "wording-helps"}


def auditor(rows):
    """A paired swap: does the auditor or the executor carry the effect?"""
    r = rows or {}
    auditor_change = _float(r.get("auditor_change"))
    auditor_p = _float(r.get("auditor_p"))
    executor_change = _float(r.get("executor_change"))
    executor_p = _float(r.get("executor_p"))
    if None in (auditor_change, auditor_p, executor_change, executor_p):
        return {"format": FORMAT, "verdict": "state-incomplete"}
    auditor_sig = auditor_p < 0.05
    executor_sig = executor_p < 0.05
    if auditor_sig and not executor_sig:
        verdict = "auditor-carries"
    elif executor_sig and not auditor_sig:
        verdict = "executor-carries"
    elif auditor_sig and executor_sig:
        verdict = "both-carry"
    else:
        verdict = "neither-carries"
    return {"format": FORMAT, "verdict": verdict,
            "auditor_effect": auditor_change, "executor_effect": executor_change}


def audit(record):
    """The evaluation mistakes this design exists to correct."""
    r = record or {}
    findings = []
    if r.get("outcome_only") is True:
        findings.append({"kind": "outcome-only",
                         "why": "an unnecessary read never appears in the answer"})
    if r.get("static_trajectory") is True:
        findings.append({"kind": "static-trajectory",
                         "why": "a pre-authored trace never has to find the record"})
    if r.get("single_judge") is True:
        findings.append({"kind": "single-judge",
                         "why": "use at least two of three independent judges"})
    if r.get("fail_open_as_control") is True:
        findings.append({"kind": "fail-open-treated-as-control",
                         "why": "the audit is fail-open and is not an access control"})
    if r.get("no_flow_schema") is True:
        findings.append({"kind": "no-flow-schema",
                         "why": "without the five attributes a criterion cannot be applied"})
    if not findings:
        findings.append({"kind": "audit-conditions-met"})
    return {"format": FORMAT, "findings": findings}


def advise(profile):
    """Map a harness profile onto the paper's failure modes."""
    p = profile or {}
    have = {str(k) for k, v in p.items() if v}
    checks = (
        ("audits_the_trajectory", "scores-the-final-answer",
         "the violation often happens before the answer"),
        ("represents_flows", "checks_raw_text",
         "sender, recipient, subject, type and principle define the context"),
        ("enforces_at_the_write", "advises_only",
         "a stated criterion is nearly inert without enforcement"),
        ("keeps_the_criterion_pluggable", "one_hardcoded_rule",
         "PII, minimization and CI answer different questions"),
        ("measures_extraction_recall", "leak_rate_only",
         "the arbiter cannot gate what the extractor never saw"),
        ("reports_helpfulness", "leak_rate_alone",
         "an audit that answers nothing is not a success"),
    )
    findings = []
    for key, kind, why in checks:
        if key not in have:
            findings.append({"kind": kind, "why": why})
    return {"format": FORMAT, "findings": findings}


def _float(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
