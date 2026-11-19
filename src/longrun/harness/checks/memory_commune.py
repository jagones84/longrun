#!/usr/bin/env python3
"""Memory commune — memory is a shared, operable object, not an agent secret.

Source: arXiv:2611.24165, "MemoSync" (round 148). A coding agent decides what
context carries across sessions and projects, while the developer can neither
see what it stores nor which items a turn uses
(`memosync_metamemory_2611.24165.txt:29`, `:48`, `:79`). The paper calls this
split the developer-agent metamemory problem: meta-level judgment and
object-level memory operations sit on different sides of the boundary
(`:83`, `:89`).

  * **four dimensions**: evolution (what changes), selection (what a turn
    uses), execution (how it is applied) and impact (its effect)
    (`:130`, `:131`).
  * **three scopes**: personal, project, session (`:135`, `:452`).
  * **only approved changes are written**, conflicts and staleness are
    surfaced for review, and a cross-project item is abstracted and then
    localized before it crosses the boundary (`:319`, `:321`, `:455`).
  * **the working memory is confirmed before generation**, with each item's
    expected use stated (`:397`, `:410`).
  * **citations and a post-turn audit attribute the result to items**:
    shaped, violated, not applicable, no visible effect, labelled
    self-reported or audit-found (`:518`, `:540`).
  * **measured**: 132 participants; alignment 88.0% content against 77.6%
    automatic and 66.2% static; task performance 59.8% against 47.7% and 51.1%;
    the application gap 0.19 against 0.42 and 0.38; more monitoring and control
    actions with no workload increase (`:1021`, `:1216`, `:1138`, `:1336`).
  * **honest negatives**: the two projects share a stack so transfer is easy;
    scope alignment against the automatic baseline is not significant; all
    extraction and audit judgments depend on the model (`:1796`, `:1799`, `:1805`).

  * `entry(row)` — a scoped memory item and its integrity.
  * `scope_ok(row)` — whether an item applies in the current context.
  * `proposals(row)` — only approved changes reach the store.
  * `transfer(row)` — source, abstract and localized forms before a boundary.
  * `selection(row)` — the confirmed working memory and its expected uses.
  * `citation(row)` — identifiers that resolve to stored items.
  * `audit(row)` — item-level verdicts and their evidence source.
  * `alignment(rows)` — desired against actual, content and scope.
  * `gap(rows)` — perceived against actual application.
  * `activity(rows)` — monitoring and control counts by condition.
  * `audit_record(record)` — the six misreadings the paper names.
  * `advise(profile)` — map a harness profile onto the paper's failure modes.

Pure: scoped items and turn records in; verdicts and rates out.
"""
from __future__ import annotations

import re

FORMAT = "longrun-memory-commune/1"

SCOPES = ("personal", "project", "session")
AUDIT_VERDICTS = ("shaped", "violated", "not-applicable", "no-visible-effect")
EVIDENCE_SOURCES = ("self-reported", "audit-found")
DEFAULTS = {"scope_agreement": 0.8}


def _num(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def entry(row):
    """A memory item: id, content, scope, and an optional layered detail."""
    r = row or {}
    missing = [key for key in ("id", "content") if not r.get(key)]
    scope = str(r.get("scope") or "")
    reasons = []
    if missing:
        reasons.append("missing-fields")
    if scope not in SCOPES:
        reasons.append("unknown-scope")
    if r.get("detail") and not r.get("summary"):
        reasons.append("detail-without-summary")
    return {"format": FORMAT, "id": str(r.get("id") or ""), "scope": scope,
            "reasons": reasons,
            "verdict": "entry-valid" if not reasons else "entry-invalid"}


def scope_ok(row):
    """Personal applies anywhere, project only in its project, session only there."""
    r = row or {}
    item = str(r.get("item_scope") or "")
    context = str(r.get("context_scope") or "")
    if item not in SCOPES or context not in SCOPES:
        return {"format": FORMAT, "verdict": "unknown-scope"}
    if item == "personal":
        allowed = True
    elif item == context:
        allowed = bool(r.get("same_project", True))
    else:
        allowed = False
    return {"format": FORMAT, "applies": allowed,
            "verdict": "applies" if allowed else "outside-scope"}


def proposals(row):
    """Candidate writes: only the approved ones reach the store."""
    r = row or {}
    candidates = [c or {} for c in (r.get("candidates") or [])]
    approved = {str(x) for x in (r.get("approved") or [])}
    written = [str(c.get("id")) for c in candidates
               if str(c.get("id")) in approved]
    pending = [str(c.get("id")) for c in candidates
               if str(c.get("id")) not in approved]
    return {"format": FORMAT, "written": written, "pending": pending,
            "verdict": "confirmation-required" if pending
            else "all-approved"}


def transfer(row):
    """An item crossing a boundary needs its abstract and localized forms."""
    r = row or {}
    source = r.get("source")
    abstract = r.get("abstract")
    localized = r.get("localized")
    scope = str(r.get("destination_scope") or "")
    missing = []
    if not source:
        missing.append("source")
    if not abstract:
        missing.append("abstract")
    if not localized:
        missing.append("localized")
    if scope not in SCOPES:
        missing.append("destination-scope")
    return {"format": FORMAT, "missing": missing,
            "verdict": "transfer-reviewable" if not missing
            else "transfer-incomplete"}


def selection(row):
    """The confirmed working memory for a turn, with an expected use per item."""
    r = row or {}
    proposed = [p or {} for p in (r.get("proposed") or [])]
    confirmed = r.get("confirmed")
    items = []
    for p in proposed:
        items.append({"id": str(p.get("id") or ""),
                      "scope": str(p.get("scope") or ""),
                      "expected_use": str(p.get("expected_use") or "")})
    missing_use = [i["id"] for i in items if not i["expected_use"]]
    if confirmed is not True:
        verdict = "unconfirmed"
    elif missing_use:
        verdict = "expected-use-missing"
    else:
        verdict = "working-memory-confirmed"
    return {"format": FORMAT, "items": items, "missing_use": missing_use,
            "verdict": verdict}


def citation(row):
    """Every bracketed identifier must resolve to a stored item."""
    r = row or {}
    text = str(r.get("text") or "")
    stored = {str(x) for x in (r.get("stored") or [])}
    cited = sorted(set(re.findall(r"\[(M-\d+)\]", text)))
    unknown = [c for c in cited if c not in stored]
    return {"format": FORMAT, "cited": cited, "unknown": unknown,
            "verdict": "citations-resolve" if not unknown
            else "unknown-citation"}


def audit(row):
    """Per-item outcome and the evidence source behind it."""
    r = row or {}
    verdict = str(r.get("verdict") or "")
    source = str(r.get("source") or "self-reported")
    if verdict not in AUDIT_VERDICTS:
        return {"format": FORMAT, "verdict": "unknown-audit-verdict"}
    if source not in EVIDENCE_SOURCES:
        return {"format": FORMAT, "verdict": "unknown-evidence-source"}
    return {"format": FORMAT, "item": str(r.get("item") or ""),
            "item_verdict": verdict, "source": source,
            "verdict": "audit-complete"}


def alignment(rows):
    """Desired against actual, on content and on scope."""
    content, scope, both = [], [], []
    for row in rows or []:
        r = row or {}
        desired = _num(r.get("desired_content"))
        actual = _num(r.get("actual_content"))
        if desired is not None and actual is not None:
            c = max(0.0, min(1.0, 1.0 - abs(desired - actual)))
            content.append(c)
            match = 1.0 if r.get("scope_match") is True else 0.0
            scope.append(match)
            both.append(c * match)
    if not content:
        return {"format": FORMAT, "verdict": "no-items"}
    mean = lambda xs: sum(xs) / len(xs)  # noqa: E731
    return {"format": FORMAT, "items": len(content),
            "content": mean(content), "scope": mean(scope),
            "both": mean(both), "verdict": "alignment-measured"}


def gap(rows):
    """Perceived application against the audited application."""
    gaps, signed = [], []
    for row in rows or []:
        r = row or {}
        perceived = _num(r.get("perceived"))
        actual = _num(r.get("actual"))
        if perceived is None or actual is None:
            continue
        gaps.append(abs(perceived - actual))
        signed.append(perceived - actual)
    if not gaps:
        return {"format": FORMAT, "verdict": "no-items"}
    mean = lambda xs: sum(xs) / len(xs)  # noqa: E731
    return {"format": FORMAT, "items": len(gaps), "absolute": mean(gaps),
            "signed": mean(signed),
            "verdict": "gap-measured"}


def activity(rows):
    """Monitoring and control actions per condition."""
    arms = {}
    for row in rows or []:
        r = row or {}
        arm = str(r.get("arm") or "")
        if not arm:
            continue
        entry_row = arms.setdefault(arm, {"monitoring": [], "control": []})
        for key, field in (("monitoring", "monitoring"), ("control", "control")):
            value = _num(r.get(field))
            if value is not None:
                entry_row[key].append(value)
    if not arms:
        return {"format": FORMAT, "verdict": "no-arms"}
    summary = {}
    for arm, values in arms.items():
        summary[arm] = {
            "monitoring": (sum(values["monitoring"]) / len(values["monitoring"])
                           if values["monitoring"] else None),
            "control": (sum(values["control"]) / len(values["control"])
                        if values["control"] else None),
        }
    base = summary.get("auto") or {}
    for arm, values in summary.items():
        if base.get("monitoring") and values.get("monitoring"):
            values["monitoring_ratio"] = values["monitoring"] / base["monitoring"]
        if base.get("control") and values.get("control"):
            values["control_ratio"] = values["control"] / base["control"]
    return {"format": FORMAT, "arms": summary,
            "verdict": "more-actions" if any(
                (v.get("monitoring_ratio") or 1.0) > 1.5 for v in summary.values())
            else "actions-comparable"}


def audit_record(record):
    """The six misreadings the paper names, each as a finding."""
    r = record or {}
    findings = []
    if r.get("visibility_without_selection") is True:
        findings.append({"kind": "visibility-without-selection",
                         "why": "seeing the store is not seeing what a turn uses"})
    if r.get("static_file_fallacy") is True:
        findings.append({"kind": "static-file-fallacy",
                         "why": "a growing configuration file stops being reviewable"})
    if r.get("auto_cap_loses_detail") is True:
        findings.append({"kind": "auto-cap-loses-detail",
                         "why": "summaries and a storage cap discard reusable detail"})
    if r.get("agent_self_report") is True:
        findings.append({"kind": "agent-self-report",
                         "why": "an audit must not trust the agent's own claim"})
    if r.get("no_scope") is True:
        findings.append({"kind": "no-scope",
                         "why": "an unscoped memory leaks into unrelated workspaces"})
    if r.get("monitor_only") is True:
        findings.append({"kind": "monitor-only",
                         "why": "a dashboard without control does not close the loop"})
    if not findings:
        findings.append({"kind": "audit-conditions-met"})
    return {"format": FORMAT, "findings": findings}


def advise(profile):
    """Map a harness profile onto the paper's failure modes."""
    p = profile or {}
    have = {str(k) for k, v in p.items() if v}
    checks = (
        ("represents_memory_as_scoped_items", "flat_prompt_memory",
         "scope is what keeps a rule inside its boundary"),
        ("requires_confirmation_before_write", "auto_writes_memory",
         "an unreviewed write can outlive the intent behind it"),
        ("surfaces_stale_and_conflicting_items", "append_only_store",
         "conflicts and staleness need a review step"),
        ("makes_per_turn_selection_visible", "opaque_retrieval",
         "the developer cannot judge a selection they cannot see"),
        ("states_expected_use_per_item", "injects_a_block",
         "an item without an expected use cannot be checked"),
        ("attributes_output_to_items", "audits_the_answer_as_a_whole",
         "impact needs an item-level verdict and its evidence"),
        ("separates_self_report_from_audit", "trusts_citations",
         "the agent may cite a rule while breaking it"),
    )
    findings = []
    for key, kind, why in checks:
        if key not in have:
            findings.append({"kind": kind, "why": why})
    return {"format": FORMAT, "findings": findings}
