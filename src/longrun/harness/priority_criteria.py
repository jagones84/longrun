#!/usr/bin/env python3
"""Priority criteria — a stated priority says what to attend to, not how to judge.

Source: arXiv:2611.22989, "How Web Research Agents Interpret User Priorities"
(round 134). A prompt can name a priority (growth, resilience) while leaving the
assessment criteria open, and the agent then chooses the grounds on which the
options are compared (`web_research_user_priorities_2611.22989.md:40`).

  * **focus is not criteria**: 21 of 24 reports adopted the requested focus, yet
    the criteria varied, and 14 of the 15 reports that ranked the companies
    adopted the focus while judging it on different grounds (`:30`, `:157`).
  * **the same focus can flip the answer**: under growth, the OpenAI reports
    weighed risk or predictability and favored Microsoft, while the Anthropic
    reports judged growth by pace and favored Alphabet (`:151`).
  * **the same answer can rest on different reasons**: under resilience all nine
    ranking reports chose Microsoft, but through cycles exposure or credit
    ratings (`:153`).
  * **criteria can appear without the priority** (`:155`).
  * **a criterion can be traced through searches, citations and judgement**: the
    four Anthropic credit-rating reports show it at each step (`:186`).
  * **the research process may not change**: only the Anthropic agent's search
    wording differed by condition; the OpenAI agent cited the same nine
    documents for 94% of its citations (`:172`, `:167`).
  * **the interface should expose and let users revise the criteria** (`:200`).

  * `priority(text)` — a priority with or without a stated criterion.
  * `report(record)` — focus vs criteria vs pick.
  * `trace(row)` — a criterion through search, citation and judgement.
  * `compare(runs)` — same focus, opposite answers; same answer, different
    reasons.
  * `evidence(path)` — narrow source base and search-wording (in)variance.
  * `revise(interface)` — criteria shown, editable, and their origin marked.
  * `advise(profile)` — map a harness profile onto the paper's failure modes.

Pure: prompt, report and trace records in; findings out.
"""
from __future__ import annotations

FORMAT = "longrun-priority-criteria/1"

STEPS = ("search", "citation", "judgement")


def _text(value):
    return str(value).strip() if value is not None else ""


def priority(text):
    """A priority names what to attend to; it may or may not name how to judge."""
    body = _text(text)
    findings = []
    if not body:
        findings.append({"kind": "priority-unstated",
                         "why": "there is nothing to attend to"})
    lowered = body.lower()
    if body and not any(w in lowered for w in ("growth", "resilience", "risk",
                                               "cost", "speed", "quality")):
        findings.append({"kind": "priority-uninterpretable",
                         "why": "a priority must name an aspect of the task"})
    if body and not any(w in lowered for w in ("measure", "judge", "compare",
                                               "by ", "using", "ranked by")):
        findings.append({"kind": "criterion-implicit",
                         "why": "the prompt names a priority but not how to judge it"})
    return {"format": FORMAT, "priority": body, "findings": findings}


def report(record):
    """Focus, criteria and pick are three separate facts."""
    r = record or {}
    focus = _text(r.get("focus")).lower()
    criteria = [str(c) for c in (r.get("criteria") or ())]
    pick = _text(r.get("pick")).lower()
    requested = _text(r.get("requested")).lower()
    findings = []
    if not criteria:
        findings.append({"kind": "focus-without-criteria",
                         "why": "a report that names a focus but no grounds cannot be evaluated"})
    if requested and focus == requested and criteria:
        findings.append({"kind": "focus-adopted"})
    if requested and focus and focus != requested and focus != "balanced":
        findings.append({"kind": "focus-not-adopted", "requested": requested, "focus": focus})
    if pick and not criteria:
        findings.append({"kind": "pick-without-grounds",
                         "why": "a recommendation with no stated criterion hides its basis"})
    if requested and not r.get("criteria_origin"):
        findings.append({"kind": "criterion-origin-unmarked",
                         "why": "the reader cannot tell whether the user or the agent chose the criterion"})
    return {"format": FORMAT, "focus": focus, "criteria": criteria, "pick": pick,
            "findings": findings}


def trace(row):
    """A criterion should be traceable through every step that produced a judgement."""
    r = row or {}
    criterion = _text(r.get("criterion"))
    present = {str(k) for k, v in r.items() if v}
    findings = []
    if not criterion:
        findings.append({"kind": "no-criterion"})
        return {"format": FORMAT, "findings": findings}
    missing = [s for s in STEPS if s not in present]
    for step in missing:
        findings.append({"kind": "criterion-not-in-%s" % step, "criterion": criterion})
    if not missing:
        findings.append({"kind": "criterion-fully-traced", "criterion": criterion})
    if r.get("searches") and not r.get("cited_source_contains_criterion"):
        findings.append({"kind": "search-not-grounding",
                         "why": "a query about a criterion does not prove the source supports it"})
    return {"format": FORMAT, "criterion": criterion, "steps": sorted(present),
            "findings": findings}


def compare(runs):
    """Same focus does not imply the same criteria, and vice versa."""
    rows = list(runs or ())
    findings = []
    if not rows:
        return {"format": FORMAT, "findings": [{"kind": "no-runs"}]}
    by_focus = {}
    for r in rows:
        focus = _text(r.get("focus")).lower()
        by_focus.setdefault(focus, []).append(r)
    for focus, group in by_focus.items():
        picks = {_text(r.get("pick")).lower() for r in group if _text(r.get("pick"))}
        criteria = {tuple(sorted(str(c) for c in (r.get("criteria") or ()))) for r in group}
        if len(picks) > 1:
            findings.append({"kind": "opposite-answers-same-focus", "focus": focus,
                             "picks": sorted(picks),
                             "why": "the criterion, not the focus, decides the recommendation"})
        if len(picks) == 1 and len(criteria) > 1:
            findings.append({"kind": "same-answer-different-reasons", "focus": focus,
                             "pick": picks.pop(), "criteria": len(criteria)})
        if len(criteria) > 1:
            findings.append({"kind": "focus-does-not-reveal-criteria", "focus": focus,
                             "criteria": len(criteria)})
    return {"format": FORMAT, "findings": findings}


def evidence(path):
    """Terminology: does the priority change the research, or only the report?"""
    p = path or {}
    findings = []
    cited = int(p.get("cited_distinct") or 0)
    top_share = p.get("top_documents_citation_share")
    if cited and top_share is not None and top_share >= 0.90:
        findings.append({"kind": "narrow-source-base", "documents": cited,
                         "share": top_share,
                         "why": "a report drawing on the same few documents in every condition"})
    overlap = p.get("source_overlap")
    if overlap is not None and overlap <= 0.10:
        findings.append({"kind": "evidence-overlap-low", "overlap": overlap,
                         "why": "runs in the same condition barely share sources"})
    if p.get("search_wording_differs") is True:
        findings.append({"kind": "search-wording-differs"})
    elif p.get("search_wording_differs") is False:
        findings.append({"kind": "search-wording-invariant",
                         "why": "the priority reached the report but not the queries"})
    return {"format": FORMAT, "findings": findings}


def revise(interface):
    """The criteria should be visible, editable and their origin marked."""
    i = interface or {}
    findings = []
    if i.get("criteria_shown") is not True:
        findings.append({"kind": "criteria-not-shown",
                         "why": "a reader cannot see the grounds of a comparison"})
    if i.get("criteria_editable") is not True:
        findings.append({"kind": "criteria-not-editable",
                         "why": "the user cannot revise what the agent proposed"})
    if i.get("origin_marked") is not True:
        findings.append({"kind": "origin-unmarked",
                         "why": "a judgement should say whether the user or the agent chose the criterion"})
    if i.get("evidence_linked") is not True:
        findings.append({"kind": "evidence-not-linked",
                         "why": "each criterion should link the passage that supports it"})
    return {"format": FORMAT, "findings": findings}


def advise(profile):
    """Map a harness profile onto the paper's failure modes."""
    p = profile or {}
    have = {str(k) for k, v in p.items() if v}
    findings = []
    checks = (
        ("records_criteria", "criteria-unrecorded", "a focus without its grounds cannot be evaluated"),
        ("checks_criterion_origin", "criterion-origin-unmarked", "the reader cannot tell who chose the criterion"),
        ("traces_criterion", "criterion-untraced", "a criterion should appear in search, citation and judgement"),
        ("compares_repeated_runs", "single-run-report", "one report cannot separate the criterion from noise"),
        ("reports_source_spread", "narrow-source-base", "the same few documents in every condition"),
        ("exposes_criteria", "criteria-hidden", "the user cannot see or revise the grounds"),
    )
    for key, kind, why in checks:
        if key not in have:
            findings.append({"kind": kind, "why": why})
    return {"format": FORMAT, "findings": findings}
