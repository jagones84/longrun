#!/usr/bin/env python3
"""Documentation maintenance — a human correction is an unlabelled gap signal.

Source: arXiv:2611.23142, "Mind the Gap: A Deployed Multi-Agent System for
Documentation Maintenance" (round 133). Documentation is the primary entry
point for users and their LLM agents, so stale prose propagates as an
authoritative answer (`deployed_multiagent_docs_maintenance_2611.23142.md:30`,
`:34`).

  * **a resolved ticket is implicit supervision**: the delta between the
    documentation-grounded agent answer and the human resolution is the gap
    signal, and it costs nothing to collect (`:44`, `:56`).
  * **three modes**: sufficient documentation (the agent equals the human),
    visible gaps (the human corrects), and invisible drift (code changed and no
    ticket exists) (`:36`–`:40`).
  * **five gap types**: missing, stale, contradictory, ambiguous, broken_xref;
    over 90% of the deployed gaps were `missing` (`:221`, `:227`).
  * **the tracker dedupes and prioritises**: a recurring gap increments its
    frequency count, and recurrence is a useful priority signal (`:234`,
    `:239`).
  * **a human always approves before merge**, and a self-review gate runs
    first (`:76`).
  * **measured**: 499 tickets, 92 gaps, 1121 assertions — 245 correct,
    57 contradicted (5.1%), 813 unverifiable; 81.1% accuracy over verifiable
    assertions; the agent is preferred 70.5% to 23.2% on length-comparable
    pairs; repairing a gap improves the later answer in 71.4% of 35 blinded
    comparisons; the full loop beats BM25 retrieval 64.6% to 31.2% (`:42`,
    `:107`, `:113`, `:127`, `:133`).

  * `signal(ticket)` — turn one resolved ticket into a gap, or confirm coverage.
  * `gap(entry)` — validate the five-type taxonomy and its routing.
  * `tracker(entries)` — dedupe, count recurrence and set priority.
  * `pipeline(draft)` — the self-review gate, human authority and watcher
    coverage.
  * `measure(rows)` — assertion correctness with the unverifiable denominator
    reported, length-controlled preference, complementarity, self-improvement.
  * `advise(profile)` — map a harness profile onto the paper's failure modes.

Pure: tickets, gap entries and evaluation rows in; findings out.
"""
from __future__ import annotations

FORMAT = "longrun-doc-maintenance/1"

GAP_TYPES = ("missing", "stale", "contradictory", "ambiguous", "broken-xref")
SOURCES = ("live-triage", "harvest", "feedback-loop", "probing", "code-merge", "manual")


def _text(value):
    return str(value).strip() if value is not None else ""


def signal(ticket):
    """A resolved ticket either confirms coverage or reveals one gap."""
    t = ticket or {}
    agent = _text(t.get("agent_answer"))
    human = _text(t.get("human_resolution"))
    approved = t.get("human_approved") is True
    findings = []
    if not agent:
        findings.append({"kind": "no-agent-answer",
                         "why": "there is nothing to compare against the correction"})
    if not human:
        findings.append({"kind": "no-human-resolution",
                         "why": "the human correction is the supervision signal"})
    if agent and human and agent == human:
        findings.append({"kind": "coverage-confirmed",
                         "why": "an identical answer is evidence the documentation was sufficient"})
    elif agent and human:
        findings.append({"kind": "gap-signal",
                         "why": "the divergence is the gap, and no annotation is needed"})
    if approved and agent != human:
        findings.append({"kind": "approval-with-divergence",
                         "why": "an approved but different answer still hides a gap"})
    if t.get("mechanical"):
        findings.append({"kind": "mechanical-request-excluded",
                         "why": "a rote action carries no diagnostic gap signal"})
    if t.get("already_resolved_thread"):
        findings.append({"kind": "non-answer", "why": "the agent correctly declined"})
    return {"format": FORMAT, "findings": findings}


def gap(entry):
    """The five-type taxonomy, and the route each type takes."""
    e = entry or {}
    kind = _text(e.get("type")).lower()
    findings = []
    if kind not in GAP_TYPES:
        findings.append({"kind": "unknown-gap-type", "type": kind})
    route = "gap-filler" if kind == "missing" else "stale-updater"
    if kind == "missing" and not _text(e.get("target_doc")):
        findings.append({"kind": "target-unstated",
                         "why": "a missing gap must name the document that should exist"})
    if kind in ("contradictory", "ambiguous") and not _text(e.get("evidence")):
        findings.append({"kind": "evidence-unstated",
                         "why": "a conflict or an underspecified passage must quote it"})
    if _text(e.get("source")).lower() not in SOURCES:
        findings.append({"kind": "unknown-detection-source", "source": e.get("source")})
    return {"format": FORMAT, "type": kind, "route": route, "findings": findings}


def tracker(entries):
    """Dedupe by key, count recurrence, and prioritise what recurs."""
    rows = list(entries or ())
    counts = {}
    for r in rows:
        key = _text(r.get("key")) or _text(r.get("target_doc")) + "|" + _text(r.get("type"))
        counts[key] = counts.get(key, 0) + 1
    findings = []
    recurring = {k: v for k, v in counts.items() if v > 1}
    if recurring:
        findings.append({"kind": "recurring-gaps", "count": len(recurring),
                         "why": "a gap that recurs across tickets is a priority signal"})
    unprioritised = [r for r in rows if counts.get(_text(r.get("key")) or
                                                   _text(r.get("target_doc")) + "|" + _text(r.get("type"))) > 1
                     and _text(r.get("priority")).lower() != "high"]
    if unprioritised:
        findings.append({"kind": "recurrence-unprioritised", "count": len(unprioritised),
                         "why": "recurring gaps are disproportionately high priority"})
    if any(not _text(r.get("source")) for r in rows):
        findings.append({"kind": "source-unrecorded",
                         "count": sum(1 for r in rows if not _text(r.get("source"))),
                         "why": "a gap with no detection source cannot be attributed"})
    missing = sum(1 for r in rows if _text(r.get("type")).lower() == "missing")
    if missing and missing / float(len(rows)) > 0.9:
        findings.append({"kind": "missing-dominates", "share": round(missing / float(len(rows)), 4),
                         "why": "absence, not staleness, is the primary failure mode here"})
    return {"format": FORMAT, "gaps": len(rows), "unique": len(counts),
            "recurring": sorted(recurring), "findings": findings}


def pipeline(draft):
    """Self-review, human authority and the watcher's bounded reach."""
    d = draft or {}
    findings = []
    if d.get("self_reviewed") is not True:
        findings.append({"kind": "self-review-missing",
                         "why": "a generated fix is gated before it reaches a human"})
    if d.get("human_approved") is not True:
        findings.append({"kind": "human-approval-missing",
                         "why": "a wrong fix becomes the authoritative answer for every downstream user"})
    if d.get("merge_to_code") is True:
        findings.append({"kind": "code-modified",
                         "why": "the loop repairs documentation, never product code"})
    if d.get("watcher_fired") and not d.get("registry_mapped"):
        findings.append({"kind": "watcher-blind",
                         "why": "a package with no registry entry is invisible to the watcher"})
    if d.get("proactive_gaps") == 0 and d.get("claims_prevention"):
        findings.append({"kind": "prevention-unproven",
                         "why": "a watcher that recorded no gap has not demonstrated prevention"})
    if d.get("review_time_measured") is False:
        findings.append({"kind": "review-time-unpriced",
                         "why": "the drafting time excludes the human review the loop requires"})
    return {"format": FORMAT, "findings": findings}


def measure(rows):
    """Correctness with the unverifiable denominator, preference with length, self-improvement."""
    data = list(rows or ())
    findings = []
    if not data:
        return {"format": FORMAT, "findings": [{"kind": "no-measurement"}]}
    assertions = [r for r in data if r.get("kind") == "assertion"]
    if assertions:
        correct = sum(1 for r in assertions if r.get("label") == "correct")
        incorrect = sum(1 for r in assertions if r.get("label") == "incorrect")
        unverifiable = sum(1 for r in assertions if r.get("label") == "unverifiable")
        verifiable = correct + incorrect
        if unverifiable > verifiable:
            findings.append({"kind": "unverifiable-dominates",
                             "unverifiable": unverifiable, "verifiable": verifiable,
                             "why": "a terse human answer cannot confirm what the agent adds"})
        if verifiable:
            findings.append({"kind": "accuracy-over-verifiable",
                             "rate": round(correct / float(verifiable), 4)})
        if assertions:
            findings.append({"kind": "error-floor", "rate": round(incorrect / float(len(assertions)), 4)})
        if any(r.get("unverifiable_counted_as_correct") for r in assertions):
            findings.append({"kind": "unverifiable-counted-as-correct",
                             "why": "silence is not agreement"})
        if any(r.get("unverifiable_counted_as_error") for r in assertions):
            findings.append({"kind": "unverifiable-counted-as-error",
                             "why": "silence is not contradiction"})
    pairs = [r for r in data if r.get("kind") == "preference"]
    if pairs:
        agent = sum(1 for r in pairs if r.get("winner") == "agent")
        length_ratio = [r.get("length_ratio") for r in pairs if r.get("length_ratio") is not None]
        if length_ratio and max(length_ratio) > 2 and not any(r.get("length_comparable") for r in pairs):
            findings.append({"kind": "verbosity-confounded",
                             "why": "preference tracks length; report the length-comparable subset"})
        findings.append({"kind": "preference", "agent_share": round(agent / float(len(pairs)), 4)})
        findings.append({"kind": "complementarity",
                         "agent_only": sum(1 for r in pairs if r.get("agent_only_point")),
                         "human_only": sum(1 for r in pairs if r.get("human_only_point"))})
    before = [r for r in data if r.get("kind") == "before-after"]
    if before:
        improved = sum(1 for r in before if r.get("winner") == "after")
        findings.append({"kind": "self-improvement", "rate": round(improved / float(len(before)), 4)})
        if any(not r.get("fix_postdates_discovery") for r in before):
            findings.append({"kind": "causal-order-unchecked",
                             "why": "the documentation commit must postdate the gap discovery"})
        if any(r.get("selected_on_confidence") is False for r in before):
            findings.append({"kind": "before-after-unselected",
                             "why": "the compared pairs are selected, so the rate is conditional"})
    if not any(r.get("kind") == "retrieval-baseline" for r in data):
        findings.append({"kind": "retrieval-baseline-missing",
                         "why": "the loop must beat plain retrieve-and-generate to earn its complexity"})
    return {"format": FORMAT, "findings": findings}


def advise(profile):
    """Map a harness profile onto the paper's failure modes."""
    p = profile or {}
    have = {str(k) for k, v in p.items() if v}
    findings = []
    checks = (
        ("uses_resolved_tickets", "no-implicit-supervision", "a human correction is free supervision"),
        ("dedupes_and_prioritises", "tracker-unmanaged", "a recurring gap is a priority signal"),
        ("self_review_gate", "no-self-review", "a generated fix must be gated before a human"),
        ("human_holds_authority", "auto-merge", "a wrong fix becomes the authoritative answer"),
        ("watches_code_merges", "reactive-only", "invisible drift needs a proactive source"),
        ("prices_review_time", "review-time-unpriced", "the human review is the cost the loop adds"),
    )
    for key, kind, why in checks:
        if key not in have:
            findings.append({"kind": kind, "why": why})
    return {"format": FORMAT, "findings": findings}
