#!/usr/bin/env python3
"""Requirement loop — a harness changes because a verified requirement says so.

Source: arXiv:2611.24924, "Agentic Harness Engineering Beta: Requirement-Centered
Evolution of Agent Harnesses" (round 150). A harness evolves through three steps:
a user simulator works with the harness and files issues, a team turns those
issues into general requirements, and a change merges only when it resolves a
verified requirement and passes review (`harness_requirements_2611.24924.txt:22`,
`:63`).

  * **the loop is requirement-centred, not score-centred**: no step consults a
    benchmark score, and every delivered change rests on session evidence
    (`:131`, `:327`).
  * **Triage normalises one issue at a time** into accept / reject / needs_info,
    rejecting a task problem, an issue that does not hold, or one the harness
    already satisfies (`:288`, `:293`).
  * **the Architect needs two sources**: every consolidated requirement cites at
    least two requirements and states their relationship and common tension
    (`:298`, `:301`).
  * **admission is an evidence gate**: the package carries runtime logs, public
    task descriptions and execution conditions; conversations, hidden tests and
    graders stay out (`:331`, `:334`).
  * **review is two gates**: a design review before implementation and a code
    review against the RFC's acceptance criteria, and a merge needs the approval
    bound to the current head (`:338`, `:343`).
  * **measured on one run**: 131 issues became 115 requirements, 22 consolidated
    requirements and 14 PRDs, delivered as 71 RFCs, with 39 resting on evidence
    from at least two tasks (`:2762`, `:2834`).
  * **a verifier-passing session can still fail the user**: 34 of 137 passed
    sessions delivered no completed reply and received the minimum rating
    (`:549`, `:551`).

  * `issue()` — normalise one raw report into a task-independent requirement.
  * `triage()` — the accept / reject / needs_info disposition and its artifact.
  * `consolidate()` — the two-source merge and its `covers` absorption.
  * `admission()` — what reaches the developers, and what never does.
  * `review()` — the design and code gates and the merge condition.
  * `rounds()` — issue-flow counts and the generalisation share.
  * `delivery()` — passed vs delivered, and the rating it costs.
  * `audit(record)` — the seven misreadings the paper names.
  * `advise(profile)` — map a harness profile onto the paper's failure modes.

Pure: reports, requirements and review records in; dispositions out.
"""
from __future__ import annotations

FORMAT = "longrun-requirement-loop/1"

KINDS = ("bug", "feature", "chore", "document")
PRIORITIES = ("P0", "P1", "P2", "P3")
DISPOSITIONS = ("accept", "reject", "needs_info")
EXCLUDED_FROM_PACKAGE = ("conversation", "hidden_test", "grader")
DESIGN_CHECKS = ("objective", "layer", "boundaries", "falsifiable_test")
CODE_CHECKS = ("acceptance", "suite", "head_bound")


def _num(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def issue(report):
    """Normalise one raw report; the title never names a project or a task."""
    r = report or {}
    reason = None
    if r.get("concerns_user_task") is True:
        reason = "task-not-harness"
    elif r.get("holds") is False:
        reason = "does-not-hold"
    elif r.get("already_satisfied") is True:
        reason = "already-satisfied"
    title = str(r.get("title") or "")
    leaked = [token for token in ("__", "task-", "repo:")
              if token in title]
    if reason is None and leaked:
        reason = "title-not-task-independent"
    if reason is not None:
        return {"format": FORMAT, "verdict": "rejected", "reason": reason}
    kind = str(r.get("kind") or "bug")
    if kind not in KINDS:
        return {"format": FORMAT, "verdict": "needs-info",
                "reason": "unknown-kind"}
    return {"format": FORMAT, "verdict": "normalized", "kind": kind,
            "priority": str(r.get("priority") or "P2"),
            "title": title,
            "evidence": list(r.get("evidence") or []),
            "acceptance": str(r.get("acceptance") or "")}


def triage(report):
    """The disposition, with the artifact the tool schema requires."""
    r = report or {}
    normal = issue(r)
    if normal["verdict"] == "normalized":
        artifact = {
            "reported_problem": str(r.get("problem") or normal["title"]),
            "user_impact": str(r.get("impact") or ""),
            "scope_boundary": str(r.get("boundary") or ""),
            "evidence": normal["evidence"],
            "uncertainties": list(r.get("uncertainties") or []),
            "implementation_target": str(r.get("target") or "uncertain"),
        }
        missing = [k for k in ("reported_problem", "user_impact",
                               "scope_boundary") if not artifact[k]]
        return {"format": FORMAT, "disposition": "accept",
                "artifact": artifact,
                "missing": missing,
                "verdict": "accepted" if not missing else "needs-info"}
    disposition = ("needs_info" if normal["verdict"] == "needs-info"
                   else "reject")
    return {"format": FORMAT, "disposition": disposition,
            "reason": normal["reason"], "verdict": disposition}


def consolidate(rows):
    """Two sources minimum; `covers` absorbs the sources it names."""
    items = [row or {} for row in rows or []]
    if len(items) < 2:
        return {"format": FORMAT, "verdict": "too-few-sources",
                "sources": len(items)}
    missing = [i for i, row in enumerate(items)
               if not row.get("relationship") or not row.get("tension")]
    if missing:
        return {"format": FORMAT, "verdict": "relationship-missing",
                "missing": missing}
    covers = []
    for row in items:
        covers.extend(row.get("covers") or [])
    direction = str(items[0].get("direction") or "")
    if any(token in direction for token in ("def ", "class ", "function(")):
        return {"format": FORMAT, "verdict": "not-a-mechanism"}
    return {"format": FORMAT, "verdict": "consolidated",
            "sources": len(items), "covers": sorted(set(covers)),
            "direction": direction}


def admission(rows):
    """Only items with an evidence package reach the developers."""
    admitted = []
    refused = []
    for row in rows or []:
        r = row or {}
        package = r.get("package") or {}
        leaked = [item for item in EXCLUDED_FROM_PACKAGE
                  if package.get(item)]
        if leaked:
            refused.append({"id": str(r.get("id") or ""),
                            "reason": "package-leaks-" + leaked[0]})
            continue
        if not package.get("runtime_logs") or not package.get("task_descriptions"):
            refused.append({"id": str(r.get("id") or ""),
                            "reason": "package-incomplete"})
            continue
        admitted.append(str(r.get("id") or ""))
    return {"format": FORMAT, "admitted": admitted, "refused": refused,
            "verdict": "admission-complete"}


def review(record):
    """Design review before implementation, code review after; head-bound merge."""
    r = record or {}
    design = r.get("design") or {}
    failed = [name for name in DESIGN_CHECKS if design.get(name) is not True]
    if failed:
        return {"format": FORMAT, "verdict": "design-rework",
                "failed": failed, "revisions": 1}
    code = r.get("code") or {}
    verdict = str(code.get("verdict") or "").upper()
    if verdict == "REWORK":
        return {"format": FORMAT, "verdict": "code-rework",
                "failed": ["acceptance"]}
    failed = [name for name in CODE_CHECKS if code.get(name) is not True]
    if failed:
        return {"format": FORMAT, "verdict": "code-rework", "failed": failed}
    if r.get("approval_head") != r.get("pr_head"):
        return {"format": FORMAT, "verdict": "stale-approval",
                "reason": "approval is not bound to the current head"}
    if r.get("rfc_unchanged") is False:
        return {"format": FORMAT, "verdict": "rfc-drift",
                "reason": "the RFC no longer matches the reviewed design"}
    return {"format": FORMAT, "verdict": "merge",
            "closes": str(r.get("requirement") or "")}


def rounds(rows):
    """Issue flow and the share of changes that rest on two or more tasks."""
    totals = {"issues": 0, "declined": 0, "requirements": 0,
              "consolidated": 0, "prds": 0, "rfcs": 0}
    for row in rows or []:
        r = row or {}
        for key in totals:
            value = r.get(key)
            if value is not None:
                totals[key] += int(value)
    if not totals["issues"]:
        return {"format": FORMAT, "verdict": "no-rounds"}
    delivered = totals["consolidated"] + totals["prds"]
    return {"format": FORMAT, "totals": totals,
            "declined_share": totals["declined"] / totals["issues"],
            "delivered": delivered,
            "verdict": "rounds-measured"}


def delivery(record):
    """A passed session that never delivered a reply is not a satisfied user."""
    r = record or {}
    passed = int(r.get("passed") or 0)
    undelivered = int(r.get("undelivered") or 0)
    if not passed:
        return {"format": FORMAT, "verdict": "no-passes"}
    share = undelivered / passed
    return {"format": FORMAT, "passed": passed, "undelivered": undelivered,
            "share": share, "minimum_rating": 1 if undelivered else None,
            "verdict": "delivery-gap" if share > 0 else "delivered"}


def generalisation(rows):
    """A change that rests on one task only is a patch, not a requirement."""
    total = 0
    multi = 0
    named = []
    for row in rows or []:
        r = row or {}
        tasks = int(r.get("tasks") or 0)
        if tasks <= 0:
            continue
        total += 1
        if tasks >= 2:
            multi += 1
        if r.get("names_task_in_runtime") is True:
            named.append(str(r.get("id") or ""))
    if not total:
        return {"format": FORMAT, "verdict": "no-changes"}
    share = multi / total
    return {"format": FORMAT, "changes": total, "multi_task": multi,
            "share": share, "named_in_runtime": named,
            "verdict": "generalises" if share >= 0.5 and not named
            else "task-specific"}


def audit(record):
    """The seven misreadings the paper names, each as a finding."""
    r = record or {}
    findings = []
    if r.get("selects_by_benchmark") is True:
        findings.append({"kind": "selects-by-benchmark",
                         "why": "score-selected changes reinforce task-specific patches"})
    if r.get("single_evolution_agent") is True:
        findings.append({"kind": "single-evolution-agent",
                         "why": "triage, consolidation and implementation are different roles"})
    if r.get("implicit_requirements_ignored") is True:
        findings.append({"kind": "implicit-requirements-ignored",
                         "why": "a final check misses what a session reveals"})
    if r.get("deduplicates_in_triage") is True:
        findings.append({"kind": "deduplicates-in-triage",
                         "why": "cross-issue structure belongs to the architect"})
    if r.get("package_carries_conversations") is True:
        findings.append({"kind": "package-carries-conversations",
                         "why": "the delivery package must not carry the user chat"})
    if r.get("pass_equals_satisfaction") is True:
        findings.append({"kind": "pass-equals-satisfaction",
                         "why": "34 of 137 passed sessions delivered no reply"})
    if r.get("merge_without_head_binding") is True:
        findings.append({"kind": "merge-without-head-binding",
                         "why": "an approval for an older head is not an approval"})
    if not findings:
        findings.append({"kind": "audit-conditions-met"})
    return {"format": FORMAT, "findings": findings, "verdict": "audit-complete"}


def advise(profile):
    """Map a harness profile onto the paper's failure modes."""
    p = profile or {}
    have = {str(k) for k, v in p.items() if v}
    checks = (
        ("collects_feedback_in_sessions", "final_score_only",
         "requirements that appear mid-run never surface"),
        ("normalises_issues_to_requirements", "implements_issues_verbatim",
         "a task-specific report becomes a task-specific patch"),
        ("merges_by_root_cause", "one_patch_per_issue",
         "common structure is never addressed"),
        ("admits_only_with_evidence", "implements_from_description",
         "a change without session evidence cannot be checked"),
        ("reviews_design_before_code", "reviews_code_only",
         "the layer and the boundaries are decided by accident"),
        ("binds_approval_to_head", "merges_any_approved_pr",
         "a later edit rides on an older approval"),
        ("reports_delivery_beside_pass", "pass_rate_only",
         "a silent failure looks like success"),
    )
    findings = []
    for key, kind, why in checks:
        if key not in have:
            findings.append({"kind": kind, "why": why})
    return {"format": FORMAT, "findings": findings}
