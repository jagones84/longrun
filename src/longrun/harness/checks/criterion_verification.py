#!/usr/bin/env python3
"""Criterion verification — hundreds of natural-language rules need per-rule verdicts.

Source: arXiv:2611.23074, "Runtime Verification of Multiple Natural Language
Criteria for Agent Governance" (round 133). An agent is governed by hundreds of
natural-language rules from developers, deployers, regulators and users, and
instruction-following degrades as the number of simultaneous instructions grows
(the fraction followed falls from above 0.9 at one instruction to below 0.6 at
six; `runtime_nl_criteria_verification_2611.23074.md:76`).

  * **verification is per criterion**: given a (context, target) pair and N
    criteria, return N verdicts in {YES, NO, N/A} — satisfied, violated, or
    inapplicable (`:66`).
  * **N/A is two different things**: a criterion can be inapplicable because its
    precondition does not hold, or applicable but undeterminable from the trace;
    they call for different monitoring actions (`:94`).
  * **a criterion must be atomic, positively phrased and trace-decidable**; rules
    that need external knowledge fall outside the approach (`:350`).
  * **the failure mode that matters is the confident false pass**: on real
    insurance calls the finetuned verifier labels 19-26% of gold violations as
    satisfied, most with max-softmax at least 0.9, so confidence-based escalation
    recovers few of them (`:595`).
  * **per-criterion verdicts localize the rule**: the violated rule ranks first
    on 97.6% of failing traces and within the top-3 on all of them, and a
    top-3 cascade lifts FAIL-F1 from 0.885 to 0.946 (`:219`).
  * **decomposition density is large**: a 115-word prompt fragment yields six
    criteria, about one per twenty words (`:706`).

  * `criterion(text, ...)` — validate one atomic, positive, trace-decidable rule.
  * `verdict(record)` — one ternary verdict with its N/A reason.
  * `coverage(criteria, trace)` — count, degradation, and per-criterion output.
  * `escalate(rows)` — localization, cascade lift and the escalated fraction.
  * `measure(rows)` — false-pass rate, confident false passes, pass errors.
  * `decomposition(text, ...)` — criteria density and under-decomposition.
  * `advise(profile)` — map a harness profile onto the paper's failure modes.

Pure: criteria, traces and verdict records in; findings out.
"""
from __future__ import annotations

FORMAT = "longrun-criterion-verification/1"

VERDICTS = ("yes", "no", "na")
NA_REASONS = ("inapplicable", "undeterminable")
POLARITIES = ("positive", "negative")
SOURCES = ("developer", "deployer", "regulator", "user", "runtime")


def _text(value):
    return str(value).strip() if value is not None else ""


def criterion(text, source="developer", polarity="positive", precondition=None,
              trace_decidable=True, compounds=0):
    """One atomic, positively phrased, trace-decidable criterion."""
    findings = []
    body = _text(text)
    if not body:
        findings.append({"kind": "criterion-missing"})
    if _text(source).lower() not in SOURCES:
        findings.append({"kind": "unknown-source", "source": source,
                         "why": "a criterion is owned by a named principal"})
    if _text(polarity).lower() not in POLARITIES:
        findings.append({"kind": "unknown-polarity", "polarity": polarity})
    elif _text(polarity).lower() == "negative":
        findings.append({"kind": "negative-phrasing",
                         "why": "a negatively phrased rule needs task-specific finetuning"})
    if int(compounds or 0) > 1:
        findings.append({"kind": "compound-criterion", "parts": compounds,
                         "why": "a compound rule must be split into atomic questions"})
    if not trace_decidable:
        findings.append({"kind": "unverifiable-criterion",
                         "why": "a rule needing external knowledge is outside trace verification"})
    if precondition is not None and not _text(precondition):
        findings.append({"kind": "precondition-unstated",
                         "why": "a conditional rule must name the precondition it tests"})
    return {"format": FORMAT, "criterion": body, "source": _text(source).lower(),
            "polarity": _text(polarity).lower(), "precondition": _text(precondition),
            "findings": findings}


def verdict(record):
    """One ternary verdict, with the two N/A cases kept apart."""
    r = record or {}
    value = _text(r.get("verdict")).lower()
    reason = _text(r.get("na_reason")).lower()
    findings = []
    if value not in VERDICTS:
        findings.append({"kind": "unknown-verdict", "verdict": value})
    if value == "na":
        if not reason:
            findings.append({"kind": "na-collapsed",
                             "why": "inapplicable and undeterminable call for different actions"})
        elif reason not in NA_REASONS:
            findings.append({"kind": "unknown-na-reason", "na_reason": reason})
        elif reason == "undeterminable":
            findings.append({"kind": "escalation-warranted", "na_reason": reason,
                             "why": "an undeterminable rule may need a larger judge"})
    if value in ("yes", "no") and not _text(r.get("evidence")):
        findings.append({"kind": "verdict-without-evidence",
                         "why": "a committed verdict must name the trace evidence it rests on"})
    return {"format": FORMAT, "verdict": value, "na_reason": reason,
            "findings": findings}


def coverage(criteria, trace=None):
    """Does the harness return a per-rule record, or one aggregate answer?"""
    items = list(criteria or ())
    t = trace or {}
    findings = []
    if not items:
        findings.append({"kind": "no-criteria"})
    count = len(items)
    if t.get("prompt_centric") and count > 6:
        findings.append({"kind": "instruction-degradation", "criteria": count,
                         "why": "the fraction of instructions followed falls below 0.6 at six"})
    if t.get("aggregate_verdict") and not t.get("per_criterion"):
        findings.append({"kind": "no-per-criterion-verdict",
                         "why": "monitoring and auditing need which rule passed or failed"})
    conditional = [c for c in items if _text(c.get("precondition"))]
    if conditional and not t.get("triggers"):
        findings.append({"kind": "trigger-conditions-unshown", "count": len(conditional),
                         "why": "without the trigger the annotator applies N/A where the label is NO"})
    return {"format": FORMAT, "criteria": count, "conditional": len(conditional),
            "findings": findings}


def escalate(rows):
    """Per-criterion verdicts localize the rule and license a top-k cascade."""
    data = list(rows or ())
    findings = []
    if not data:
        return {"format": FORMAT, "findings": [{"kind": "no-rows"}]}
    fails = [r for r in data if r.get("failed")]
    top1 = top3 = 0
    for r in fails:
        ranked = [str(x) for x in (r.get("ranked_rules") or ())]
        violated = str(r.get("violated"))
        if ranked and ranked[0] == violated:
            top1 += 1
        if violated in ranked[:3]:
            top3 += 1
    if fails:
        findings.append({"kind": "localization", "failing": len(fails),
                         "top1": round(top1 / len(fails), 4),
                         "top3": round(top3 / len(fails), 4)})
        if top3 < len(fails):
            findings.append({"kind": "localization-incomplete",
                             "why": "a rule outside the top-3 cannot be escalated by a top-k cascade"})
    base = [r.get("f1") for r in data if r.get("arm") == "verifier" and r.get("f1") is not None]
    casc = [r.get("f1") for r in data if r.get("arm") == "cascade" and r.get("f1") is not None]
    if base and casc:
        lift = max(casc) - max(base)
        findings.append({"kind": "cascade-lift" if lift > 0 else "cascade-no-lift",
                         "lift": round(lift, 4)})
    esc = [r.get("escalated_fraction") for r in data if r.get("escalated_fraction") is not None]
    if esc and not any(r.get("escalation_cost") is not None for r in data):
        findings.append({"kind": "escalation-unpriced",
                         "why": "the escalated fraction is a cost and must be reported"})
    if any(r.get("random_top3") is not None for r in data):
        chosen = [r for r in data if r.get("arm") == "cascade" and r.get("f1") is not None]
        rand = [r["random_top3"] for r in data if r.get("random_top3") is not None]
        if chosen and rand and max(r["f1"] for r in chosen) > max(rand):
            findings.append({"kind": "localization-beats-random",
                             "why": "the ranking, not the extra calls, produces the lift"})
    return {"format": FORMAT, "findings": findings}


def measure(rows):
    """A false pass is the failure that matters, and confidence hides it."""
    data = list(rows or ())
    findings = []
    if not data:
        return {"format": FORMAT, "findings": [{"kind": "no-measurement"}]}
    gold = [r for r in data if r.get("gold") == "no"]
    missed = [r for r in gold if r.get("predicted") == "yes"]
    if gold:
        rate = len(missed) / len(gold)
        findings.append({"kind": "false-pass-rate", "rate": round(rate, 4),
                         "missed": len(missed), "gold": len(gold)})
        if rate > 0.10:
            findings.append({"kind": "false-pass-unpriced", "rate": round(rate, 4),
                             "why": "a verifier that approves violations is not a guardrail"})
        confident = [r for r in missed if (r.get("confidence") or 0) >= 0.9]
        if confident:
            findings.append({"kind": "confident-false-pass", "count": len(confident),
                             "why": "confidence-based escalation recovers few of these"})
    errors = [r for r in data if r.get("gold") is not None and r.get("predicted") is not None
              and r.get("gold") != r.get("predicted")]
    if errors and any(r.get("max_softmax") for r in errors):
        findings.append({"kind": "confidence-does-not-flag",
                         "why": "false passes carry high max-softmax, so confidence is not a flag"})
    seeds = {r.get("seed") for r in data if r.get("seed") is not None}
    if len(seeds) >= 2 and missed:
        all_seeds = all(any(s.get("seed") == seed for s in gold if s.get("predicted") == "yes")
                        for seed in seeds)
        if all_seeds:
            findings.append({"kind": "seed-disagreement-cannot-flag",
                             "why": "a violation missed by every seed has no disagreement signal"})
    return {"format": FORMAT, "findings": findings}


def decomposition(text, expected_per_words=20, actual=None):
    """Estimate how many atomic rules a prose fragment hides."""
    body = _text(text)
    words = len(body.split())
    findings = []
    if not words:
        findings.append({"kind": "no-text"})
        return {"format": FORMAT, "words": 0, "findings": findings}
    try:
        per_words = float(expected_per_words)
    except (TypeError, ValueError):
        per_words = 0.0
    if per_words <= 0:
        # R160 bug hunt: a zero/negative words-per-rule estimate divided by zero.
        findings.append({"kind": "invalid-density", "value": expected_per_words})
        return {"format": FORMAT, "words": words, "findings": findings}
    density = 1.0 / per_words
    estimate = max(1, int(round(words * density)))
    got = actual if actual is not None else 0
    if actual is not None and got < estimate:
        findings.append({"kind": "under-decomposed", "words": words,
                         "actual": got, "estimate": estimate,
                         "why": "a prose rule hides several atomic checks"})
    if actual is None:
        findings.append({"kind": "decomposition-unmeasured", "words": words,
                         "estimate": estimate})
    return {"format": FORMAT, "words": words, "estimate": estimate,
            "actual": actual, "findings": findings}


def advise(profile):
    """Map a harness profile onto the paper's failure modes."""
    p = profile or {}
    have = {str(k) for k, v in p.items() if v}
    findings = []
    checks = (
        ("per_criterion_verdicts", "aggregate-only", "an aggregate verdict cannot say which rule failed"),
        ("separates_na_cases", "na-collapsed", "inapplicable and undeterminable rules need different actions"),
        ("atomic_criteria", "compound-rules", "a compound rule cannot be judged from the trace"),
        ("prices_false_passes", "false-passes-unpriced", "a verifier that approves violations is not a guardrail"),
        ("localizes_the_rule", "no-localization", "escalation needs the violated rule, not a score"),
        ("decomposes_prose", "under-decomposed", "a prose rule hides several atomic checks"),
    )
    for key, kind, why in checks:
        if key not in have:
            findings.append({"kind": kind, "why": why})
    return {"format": FORMAT, "findings": findings}
