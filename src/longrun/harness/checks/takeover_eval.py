#!/usr/bin/env python3
"""Takeover evaluation — requirements recovered from history, then delivered.

Source: arXiv:2611.07307, "Take It from Here: Evaluating Coding Agents on Project
Takeover" (round 157). A coding agent taking over a project must recover the
requirements that still apply from the interaction history, update them for the
current request, and deliver working changes in the existing project
(`project_takeover_2611.07307.txt:23`, `:83`).

  * **delivery is all-or-nothing**: build, target test and regression for every
    executable target; incomplete runs count as failures (`:165`, `:180`).
  * **requirements are atoms** with attributes, lifecycle, scope, ambiguity and
    implementation evidence; `G−q` is the pre-request state and `G+q` the target
    (`:199`, `:202`).
  * **three diagnostics** separate identification (RQ1), reconstruction (RQ2) and
    updating or clarification (RQ3) (`:206`, `:210`).
  * **the post-state score** is `2·Σs / (|R̂| + |R|)`, giving partial credit and
    penalising missing or extra requirements (`:248`).
  * **the measured gap is severe**: mean complete delivery 4.95% under full
    history, 0/312 exact post-states, and with the correct target supplied only
    8.11% complete delivery (`:360`, `:412`, `:455`).

  * `atom(record)` — validate the five state components.
  * `update(before, change)` — apply a request and detect omitted constraints.
  * `delivery(rows)` — the three checks, the rate and the per-check rates.
  * `rq1(pred, gold)` — requirement and evidence precision/recall/F1.
  * `rq2(pred, gold)` — attribute reconstruction and requirement coverage.
  * `decision(rows)` — ACT/CLARIFY accuracy and balanced recall.
  * `poststate(record)` — the partial-credit score and the exact criterion.
  * `clarify(record)` — blocking-issue F1 and question validity.
  * `audit_record(record)` / `advise(profile)` — misreadings and mapping.

Pure: states, predictions and rows in; scores and verdicts out.
"""
from __future__ import annotations

FORMAT = "longrun-takeover-eval/1"

COMPONENTS = ("attributes", "lifecycle", "scope", "ambiguity",
              "implementation_evidence")


def _num(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def atom(record):
    """A requirement atom needs all five state components."""
    r = record or {}
    if not str(r.get("id") or ""):
        return {"format": FORMAT, "verdict": "missing-id"}
    missing = [c for c in COMPONENTS if r.get(c) is None]
    return {"format": FORMAT, "id": r.get("id"), "missing": missing,
            "verdict": "valid-atom" if not missing else "incomplete-atom"}


def update(before, change):
    """Apply a request while retaining constraints it does not withdraw."""
    b = before or {}
    c = change or {}
    withdrawn = {str(k) for k in (c.get("withdraw") or [])}
    kept = [k for k in b if k not in withdrawn]
    if isinstance(c.get("state"), dict):
        post = dict(c["state"])
    else:
        post = {k: v for k, v in b.items()}
        for key, value in (c.get("set") or {}).items():
            post[key] = value
    omitted = [k for k in kept if k not in post]
    return {"format": FORMAT, "post": post, "withdrawn": sorted(withdrawn),
            "omitted": omitted,
            "verdict": "complete-update" if not omitted else "omitted-constraints"}


def delivery(rows):
    """Complete delivery needs build, target and regression on every target."""
    checks = {"build": [0, 0], "target": [0, 0], "regression": [0, 0]}
    complete = 0
    total = 0
    for row in rows or []:
        r = row or {}
        total += 1
        ok = (r.get("build") is True and r.get("target") is True
              and r.get("regression") is True)
        if ok:
            complete += 1
        for key in checks:
            checks[key][1] += 1
            if r.get(key) is True:
                checks[key][0] += 1
    if not total:
        return {"format": FORMAT, "verdict": "no-targets"}
    rates = {k: (v[0] / v[1]) for k, v in checks.items()}
    return {"format": FORMAT, "targets": total, "complete": complete,
            "delivery_rate": complete / total, "checks": rates,
            "verdict": "measured"}


def _prf(matched, predicted, gold):
    precision = matched / predicted if predicted else 0.0
    recall = matched / gold if gold else 0.0
    f1 = (2 * precision * recall / (precision + recall)) if precision + recall else 0.0
    return precision, recall, f1


def rq1(pred, gold):
    """Requirement identification and evidence selection, scored separately."""
    p = pred or {}
    g = gold or {}
    reqs_p = set(p.get("requirements") or [])
    reqs_g = set(g.get("requirements") or [])
    ev_p = set(p.get("evidence") or [])
    ev_g = set(g.get("evidence") or [])
    rp, rr, rf = _prf(len(reqs_p & reqs_g), len(reqs_p), len(reqs_g))
    ep, er, ef = _prf(len(ev_p & ev_g), len(ev_p), len(ev_g))
    return {"format": FORMAT, "requirements": {"precision": rp, "recall": rr,
                                               "f1": rf},
            "evidence": {"precision": ep, "recall": er, "f1": ef},
            "verdict": "scored"}


def rq2(pred, gold, matched=None):
    """Attribute reconstruction on matched requirements and coverage."""
    p = pred or {}
    g = gold or {}
    pairs = matched if matched is not None else []
    scores = []
    for pair in pairs:
        item = pair or {}
        score = _num(item.get("score"))
        if score is not None:
            scores.append(score)
    gold_n = len(g.get("requirements") or [])
    coverage = (len(pairs) / gold_n) if gold_n else 0.0
    attribute = (sum(scores) / len(scores)) if scores else None
    return {"format": FORMAT, "matched": len(pairs), "coverage": coverage,
            "attribute_score": attribute,
            "verdict": "scored"}


def decision(rows):
    """ACT/CLARIFY selection, with per-class recall and the always-ACT baseline."""
    act_gold = act_pred = clar_gold = clar_pred = correct = 0
    for row in rows or []:
        r = row or {}
        gold = str(r.get("gold") or "").upper()
        pred = str(r.get("pred") or "").upper()
        if gold not in ("ACT", "CLARIFY") or pred not in ("ACT", "CLARIFY"):
            continue
        if gold == pred:
            correct += 1
        if gold == "ACT":
            act_gold += 1
            act_pred += 1 if pred == "ACT" else 0
        else:
            clar_gold += 1
            clar_pred += 1 if pred == "CLARIFY" else 0
    total = act_gold + clar_gold
    if not total:
        return {"format": FORMAT, "verdict": "no-targets"}
    recall_act = act_pred / act_gold if act_gold else None
    recall_clar = clar_pred / clar_gold if clar_gold else None
    balanced = ((recall_act or 0.0) + (recall_clar or 0.0)) / 2.0
    return {"format": FORMAT, "targets": total, "accuracy": correct / total,
            "recall_act": recall_act, "recall_clarify": recall_clar,
            "balanced_accuracy": balanced,
            "always_act": act_gold / total, "verdict": "scored"}


def poststate(record):
    """The paper's partial-credit score and its stricter exact criterion."""
    r = record or {}
    pred = r.get("pred") or []
    gold = r.get("gold") or []
    matched = r.get("matched") or []
    scores = [_num(m.get("score")) for m in matched if _num(m.get("score")) is not None]
    denom = len(pred) + len(gold)
    score = (2.0 * sum(scores) / denom) if denom else None
    exact = r.get("exact") is True
    return {"format": FORMAT, "predicted": len(pred), "gold": len(gold),
            "matched": len(matched), "score": score, "exact": exact,
            "verdict": "exact" if exact else "partial"}


def clarify(record):
    """Blocking-issue F1 and question validity for a CLARIFY request."""
    r = record or {}
    issues_p = set(r.get("issues_pred") or [])
    issues_g = set(r.get("issues_gold") or [])
    tp = len(issues_p & issues_g)
    precision = tp / len(issues_p) if issues_p else 0.0
    recall = tp / len(issues_g) if issues_g else 0.0
    f1 = (2 * precision * recall / (precision + recall)) if precision + recall else 0.0
    questions = r.get("questions") or []
    valid = sum(1 for q in questions if (q or {}).get("valid") is True)
    validity = (valid / len(questions)) if questions else None
    return {"format": FORMAT, "f1": f1, "question_validity": validity,
            "verdict": "scored"}


def audit_record(record):
    """The misreadings the evaluation design excludes."""
    r = record or {}
    findings = []
    if r.get("history_filter_assumed_better") is True:
        findings.append({"kind": "history-filter-assumed-better",
                         "why": "the filtered condition scored lower in the source"})
    if r.get("delivery_rate_from_partial_checks") is True:
        findings.append({"kind": "delivery-rate-from-partial-checks",
                         "why": "complete delivery needs all three checks"})
    if r.get("diagnostics_fed_into_delivery") is True:
        findings.append({"kind": "diagnostics-fed-into-delivery",
                         "why": "diagnostic responses are frozen and not inputs"})
    if r.get("target_state_equals_implementation") is True:
        findings.append({"kind": "target-state-equals-implementation",
                         "why": "a correct target still left target tests at 9%"})
    if r.get("gold_from_later_feedback") is True:
        findings.append({"kind": "gold-from-later-feedback",
                         "why": "gold excludes subsequent implementation feedback"})
    if r.get("single_project_is_enough") is True:
        findings.append({"kind": "single-project-is-enough",
                         "why": "the executable set is 37 targets from 7 projects"})
    if not findings:
        findings.append({"kind": "audit-conditions-met"})
    return {"format": FORMAT, "findings": findings, "verdict": "audit-complete"}


def advise(profile):
    """Map a harness profile onto the takeover gaps the paper names."""
    p = profile or {}
    have = {str(k) for k in p if p.get(k)}
    checks = (
        ("reconstructs_the_requirement_state", "replays_the_raw_history",
         "the agent needs the applicable state, not every message"),
        ("keeps_constraints_the_request_does_not_withdraw", "replaces_the_state",
         "updating can drop constraints that still apply"),
        ("freezes_the_state_before_coding", "interleaves_state_and_code",
         "a frozen state makes the failure attributable"),
        ("validates_build_target_and_regression", "runs_the_target_test_only",
         "a change can build and still break history"),
        ("supplies_clarification_when_information_is_missing", "acts_on_a_guess",
         "a blocking issue should be asked, not invented"),
        ("checks_implementation_beside_target_state", "assumes_a_correct_target_suffices",
         "correct targets still failed 91% of target tests"),
    )
    findings = []
    for key, kind, why in checks:
        if key not in have:
            findings.append({"kind": kind, "why": why})
    return {"format": FORMAT, "findings": findings}
