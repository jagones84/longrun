#!/usr/bin/env python3
"""Repair audit — accuracy hides repairs that are cancelled by regressions.

Source: arXiv:2611.22991, "RagHarnessDebugger" (round 138). A RAG repair harness
makes many small decisions, and a final accuracy figure cannot tell whether its
repairs work: repairs and regressions cancel, and the acceptance rule may be
discarding most available repairs (`ragharness_contract_repair_2611.22991.md:70`,
`:199`).

  * **repair churn**: the first version held accuracy flat while making 20.9%
    repairs and 5.3% regressions (`:199`).
  * **the acceptance gap**: 77% (development) and 76% (replication) of available
    repairs were missed (`:228`).
  * **a repair is lost in one of three ways**: the validation does not apply to
    the candidate it is counted for, the acceptance rule excludes its label, or
    no follow-up can change the blocking condition (`:70`).
  * **the veto is a measurable policy**: it prevented 87% of regressions and
    blocked 63% of repairs, and replay prices both (`:240`).
  * **label-free flags triage**: the blocked-conclusion flag captured 88% / 86%
    of missed repairs in 15% / 13% of executions (`:236`).
  * **provenance bounds replay**: a replay counts only when the recorded outputs
    cover every dependency of the alternative decision (`:119`).

  * `churn(rows)` — repairs, regressions and the net that accuracy hides.
  * `reachability(row)` — available, accepted and selected candidates.
  * `failure(row)` — the three ways a candidate is lost.
  * `capability(row)` — can a follow-up change the eligible set.
  * `flags(rows)` — recall, precision and lift of a triage flag.
  * `provenance(record)` — request keys, chain, ledger, replay boundary.
  * `veto(rows)` — regressions prevented against repairs blocked.
  * `advise(profile)` — map a harness profile onto the paper's failure modes.

Pure: repair records in; findings out.
"""
from __future__ import annotations

FORMAT = "longrun-repair-audit/1"


def _num(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def churn(rows):
    """Repairs and regressions can cancel while the accuracy stays flat."""
    rows = [r for r in (rows or ()) if r.get("outcome") in ("repair", "regression", "kept")]
    if not rows:
        return {"format": FORMAT, "findings": [{"kind": "no-executions"}]}
    repaired = sum(1 for r in rows if r.get("outcome") == "repair")
    regressed = sum(1 for r in rows if r.get("outcome") == "regression")
    n = len(rows)
    repair_rate = repaired / n
    regression_rate = regressed / n
    net = (repaired - regressed) / n
    findings = []
    if repaired and regressed and abs(net) <= 0.02:
        findings.append({"kind": "repair-churn", "repair_rate": round(repair_rate, 4),
                         "regression_rate": round(regression_rate, 4),
                         "why": "repairs and regressions cancel and the score looks inert"})
    elif net > 0.02:
        findings.append({"kind": "net-repair", "net": round(net, 4)})
    elif net < -0.02:
        findings.append({"kind": "net-regression", "net": round(net, 4)})
    else:
        findings.append({"kind": "no-repair-behaviour"})
    return {"format": FORMAT, "executions": n, "repair_rate": round(repair_rate, 4),
            "regression_rate": round(regression_rate, 4), "net": round(net, 4),
            "findings": findings}


def reachability(row):
    """Was a correct candidate available, admitted and selected?"""
    r = row or {}
    available = r.get("available") is True
    admitted = r.get("admitted") is True
    selected = r.get("selected") is True
    findings = []
    if r.get("initial_correct") is True and r.get("final_correct") is False:
        findings.append({"kind": "regression", "why": "an initially correct answer was overturned"})
    if r.get("initial_correct") is False and r.get("final_correct") is True:
        findings.append({"kind": "repair"})
    if r.get("initial_correct") is False and r.get("final_correct") is False:
        if not available:
            findings.append({"kind": "unreachable-candidate",
                             "why": "no valid candidate carried the correct label"})
        elif not admitted:
            findings.append({"kind": "acceptance-blocked"})
        elif not selected:
            findings.append({"kind": "selection-blocked"})
        else:
            findings.append({"kind": "still-open"})
    if not findings:
        findings.append({"kind": "unchanged"})
    return {"format": FORMAT, "available": available, "admitted": admitted,
            "selected": selected, "findings": findings}


def failure(row):
    """The three mechanisms that lose a candidate."""
    r = row or {}
    findings = []
    if r.get("validation_applies") is False:
        findings.append({"kind": "validation-mismatch",
                         "why": "the validator did not read this candidate's package"})
    if r.get("label_admissible") is False:
        findings.append({"kind": "acceptance-excludes-label",
                         "why": "the acceptance rule cannot return this label"})
    if r.get("action_can_change") is False:
        findings.append({"kind": "no-action-can-change",
                         "why": "no available follow-up changes the blocking condition"})
    if not findings:
        findings.append({"kind": "no-structural-failure"})
    return {"format": FORMAT, "findings": findings}


def capability(row):
    """Can a follow-up intervention change the set eligible for acceptance?"""
    r = row or {}
    reachable = set(str(x) for x in (r.get("reachable_labels") or ()))
    correct = r.get("correct_label")
    findings = []
    if r.get("follow_up") is True and reachable and correct is not None:
        if str(correct) not in reachable:
            findings.append({"kind": "correct-outside-reachable-set",
                             "label": correct, "reachable": sorted(reachable),
                             "why": "no selection among these candidates can be right"})
        else:
            findings.append({"kind": "intervention-capable"})
    elif r.get("intervention_attempted") is True and r.get("changed_eligible") is not True:
        findings.append({"kind": "intervention-cannot-change",
                         "why": "the follow-up ran but could not change the outcome"})
    if not findings:
        findings.append({"kind": "capability-unmeasured"})
    return {"format": FORMAT, "findings": findings}


def flags(rows):
    """A label-free flag is a triage instrument, not a correctness verdict."""
    data = [r for r in (rows or ()) if r.get("flagged") is not None
            and r.get("missed_repair") is not None]
    if not data:
        return {"format": FORMAT, "findings": [{"kind": "no-review-set"}]}
    flagged = [r for r in data if r.get("flagged") is True]
    missed = [r for r in data if r.get("missed_repair") is True]
    if not missed:
        return {"format": FORMAT, "findings": [{"kind": "no-missed-repairs"}]}
    captured = sum(1 for r in flagged if r.get("missed_repair") is True)
    recall = captured / len(missed)
    precision = captured / len(flagged) if flagged else 0.0
    share = len(flagged) / len(data)
    random_recall = share
    findings = []
    if recall >= 0.5 and share <= 0.25:
        findings.append({"kind": "flag-triage",
                         "recall": round(recall, 4), "share": round(share, 4),
                         "lift": round(recall / random_recall, 2) if random_recall else None})
    else:
        findings.append({"kind": "flag-not-predictive",
                         "recall": round(recall, 4), "share": round(share, 4)})
    return {"format": FORMAT, "executions": len(data), "flagged": len(flagged),
            "recall": round(recall, 4), "precision": round(precision, 4),
            "findings": findings}


def provenance(record):
    """What makes a repair journey auditable and a replay supported."""
    r = record or {}
    findings = []
    if r.get("request_keys") is not True:
        findings.append({"kind": "requests-not-keyed",
                         "why": "a model request must be bound to its cached response"})
    if r.get("chain_intact") is not True:
        findings.append({"kind": "chain-broken",
                         "why": "the hash-linked event chain does not verify"})
    if r.get("ledger_append_only") is not True:
        findings.append({"kind": "ledger-rewritable"})
    if r.get("replay_recorded_dependencies") is not True:
        findings.append({"kind": "replay-unsupported",
                         "why": "an alternative decision needs every recorded dependency"})
    if not findings:
        findings.append({"kind": "provenance-verified"})
    return {"format": FORMAT, "findings": findings}


def veto(rows):
    """A veto has a benefit and a cost, and both are measurable."""
    data = [r for r in (rows or ()) if r.get("effect") in ("regression-prevented", "repair-blocked")]
    if not data:
        return {"format": FORMAT, "findings": [{"kind": "no-veto-records"}]}
    prevented = sum(1 for r in data if r.get("effect") == "regression-prevented")
    blocked = sum(1 for r in data if r.get("effect") == "repair-blocked")
    net = prevented - blocked
    findings = []
    if net > 0:
        findings.append({"kind": "veto-net-positive", "net": net})
    elif net < 0:
        findings.append({"kind": "veto-net-negative", "net": net})
    else:
        findings.append({"kind": "veto-neutral"})
    if prevented and blocked:
        findings.append({"kind": "veto-has-cost", "prevented": prevented, "blocked": blocked,
                         "why": "a veto that blocks repairs must report both sides"})
    return {"format": FORMAT, "prevented": prevented, "blocked": blocked,
            "net": net, "findings": findings}


def advise(profile):
    """Map a harness profile onto the paper's failure modes."""
    p = profile or {}
    have = {str(key) for key, value in p.items() if value}
    findings = []
    checks = (
        ("records_decisions", "outcome-only", "a repair journey is a sequence of decisions"),
        ("reports_repairs_and_regressions", "accuracy-only", "churn hides behind a flat score"),
        ("measures_acceptance_gap", "no-coverage-gap", "count available repairs that were missed"),
        ("checks_validation_applicability", "misapplied-validation", "a check must read its candidate"),
        ("checks_reachability", "unreachable-candidate", "the correct label must be selectable"),
        ("prices_the_veto", "unpriced-policy", "replay the policy with and without the veto"),
        ("uses_labels_after_audit", "labels-in-the-loop", "freeze findings before joining labels"),
        ("keeps_provenance", "unreplayable-trace", "key requests and chain the events"),
    )
    for key, kind, why in checks:
        if key not in have:
            findings.append({"kind": kind, "why": why})
    return {"format": FORMAT, "findings": findings}
