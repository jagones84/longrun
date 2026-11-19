#!/usr/bin/env python3
"""Skill evolution — evidence-grounded construction, validated revision, consolidation.

Source: arXiv:2611.03238, "ScienceCUA: Resource-to-Skill Construction and
Execution-Guided Skill Evolution for Scientific Computer Use Agents" (round 156).
Human documentation mixes operational steps with narrative; a task needs only a
sparse part of it, so the library separates procedural Skills from lookup
References and grounds every entry in source evidence
(`sciencecua_skill_evolution_2611.03238.txt:161`, `:317`).

  * **a Skill is (n, d, a, p, b)** and a Reference is (n, d, c); both must be
    traceable to the source corpus (`:317`, `:324`).
  * **diagnosis has exactly three causes**: grounding failure (no candidate),
    modify an existing routed entry, or add source-supported knowledge (`:410`,
    `:1710`).
  * **a candidate is validated alone**, in a fresh session with an empty history,
    so the knowledge itself must support the task (`:425`, `:1744`).
  * **consolidation must pass regression**: every task that contributed a
    candidate is replayed; a failure attributable to content forces a full
    revision (`:1805`, `:1812`).

  * `entry(record)` — validate a Skill or Reference against its schema.
  * `evidence(record)` — is every entry traceable to a source location.
  * `diagnose(record)` — the three-cause diagnosis and whether a candidate exists.
  * `validate(record)` — the independent, history-free candidate check.
  * `consolidate(record)` — merge, then certify by regression.
  * `budget(record)` — the exploration/submission/consolidation bounds.
  * `audit_record(record)` / `advise(profile)` — misreadings and mapping.

Pure: entry schemas, diagnoses and validation records in; verdicts out.
"""
from __future__ import annotations

FORMAT = "longrun-skill-evolution/1"

SKILL_FIELDS = ("name", "description", "applicability", "preconditions", "body")
REFERENCE_FIELDS = ("name", "purpose", "content")
CAUSES = ("grounding_failure", "modify_existing", "add_new_knowledge")


def _num(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def entry(record):
    """A Skill or Reference must carry every field, non-empty."""
    r = record or {}
    kind = str(r.get("kind") or "skill")
    fields = SKILL_FIELDS if kind == "skill" else REFERENCE_FIELDS
    if kind not in ("skill", "reference"):
        return {"format": FORMAT, "verdict": "unknown-kind"}
    missing = [f for f in fields if not str(r.get(f) or "").strip()]
    return {"format": FORMAT, "kind": kind, "fields": list(fields),
            "missing": missing,
            "verdict": "valid-entry" if not missing else "incomplete-entry"}


def evidence(record):
    """Every entry must cite a source location from the evidence corpus."""
    r = record or {}
    entries = r.get("entries") or []
    if not entries:
        return {"format": FORMAT, "verdict": "no-entries"}
    untraceable = []
    for item in entries:
        e = item or {}
        if not (e.get("source_locations") or []):
            untraceable.append(str(e.get("name") or ""))
    return {"format": FORMAT, "entries": len(entries),
            "untraceable": untraceable,
            "verdict": "traceable" if not untraceable else "untraceable"}


def diagnose(record):
    """One primary cause; only knowledge causes yield a candidate."""
    r = record or {}
    cause = str(r.get("cause") or "")
    if cause not in CAUSES:
        return {"format": FORMAT, "verdict": "unknown-cause"}
    target = r.get("target")
    routed = set(r.get("routed") or [])
    source_support = r.get("source_support") is True
    if cause == "grounding_failure":
        return {"format": FORMAT, "cause": cause, "candidate": None,
                "verdict": "no-candidate"}
    if cause == "modify_existing":
        if target not in routed:
            return {"format": FORMAT, "cause": cause,
                    "verdict": "target-not-routed"}
        return {"format": FORMAT, "cause": cause, "target": target,
                "verdict": "revision-candidate"}
    if not source_support:
        return {"format": FORMAT, "cause": cause,
                "verdict": "no-source-support"}
    return {"format": FORMAT, "cause": cause,
            "verdict": "addition-candidate"}


def candidate(record):
    """What the writer may emit, given the diagnosis."""
    r = record or {}
    cause = str(r.get("cause") or "")
    kind = str(r.get("kind") or "")
    if cause not in ("modify_existing", "add_new_knowledge"):
        return {"format": FORMAT, "verdict": "no-candidate"}
    if cause == "modify_existing" and kind not in ("skill", "reference"):
        return {"format": FORMAT, "verdict": "unknown-kind"}
    return {"format": FORMAT, "cause": cause, "kind": kind,
            "verdict": "candidate-ready"}


def validate(record):
    """The candidate is tested alone, from a fresh session with no history."""
    r = record or {}
    fresh = r.get("fresh_session") is True
    empty = r.get("history_empty") is True
    evaluator = r.get("evaluator_decides") is True
    single = r.get("one_candidate") is True
    failed = [name for name, ok in (("fresh-session", fresh),
                                    ("empty-history", empty),
                                    ("evaluator-decides", evaluator),
                                    ("one-candidate", single)) if not ok]
    return {"format": FORMAT, "failed": failed,
            "verdict": "accepted" if not failed else "rejected"}


def consolidate(record):
    """Merge accepted candidates, then certify the merge by replay."""
    r = record or {}
    candidates = list(r.get("candidates") or [])
    if not candidates:
        return {"format": FORMAT, "verdict": "no-candidates"}
    if len(candidates) == 1:
        return {"format": FORMAT, "adopted": True, "replays": 0,
                "verdict": "single-candidate"}
    replays = list(r.get("replays") or [])
    if not replays:
        return {"format": FORMAT, "adopted": False,
                "verdict": "uncertified"}
    passes = all(rep.get("passed") is True for rep in replays)
    if passes:
        return {"format": FORMAT, "adopted": True, "replays": len(replays),
                "verdict": "certified"}
    content = [rep for rep in replays
               if rep.get("passed") is not True
               and rep.get("cause") != "grounding"]
    keep = r.get("keep") is True
    if keep and not content:
        return {"format": FORMAT, "adopted": True, "replays": len(replays),
                "verdict": "certified-on-grounding"}
    return {"format": FORMAT, "adopted": False, "replays": len(replays),
            "content_failures": len(content), "verdict": "revise"}


def budget(record):
    """M_explore = M_submit = M_consolidation = 3 and the execution bound."""
    r = record or {}
    tasks = int(_num(r.get("tasks") or 0))
    explore = int(_num(r.get("explore") or 3))
    submit = int(_num(r.get("submit") or 3))
    consolidation = int(_num(r.get("consolidation") or 3))
    group = int(_num(r.get("group") or 0))
    if tasks <= 0:
        return {"format": FORMAT, "verdict": "insufficient-input"}
    executions = tasks * (2 * explore + submit)
    regression = (1 + consolidation) * group
    return {"format": FORMAT, "explore": explore, "submit": submit,
            "consolidation": consolidation,
            "execution_bound": executions, "regression_bound": regression,
            "verdict": "bounded"}


def audit_record(record):
    """The misreadings the paper's protocol excludes."""
    r = record or {}
    findings = []
    if r.get("evolution_tasks_overlap_test") is True:
        findings.append({"kind": "evolution-tasks-overlap-test",
                         "why": "evolution and evaluation must be disjoint"})
    if r.get("history_leaks_into_validation") is True:
        findings.append({"kind": "history-leaks-into-validation",
                         "why": "the candidate must stand alone"})
    if r.get("merge_skips_regression") is True:
        findings.append({"kind": "merge-skips-regression",
                         "why": "merging changes individually validated content"})
    if r.get("unsupported_addition") is True:
        findings.append({"kind": "unsupported-addition",
                         "why": "an addition needs source support"})
    if r.get("skills_and_references_merged") is True:
        findings.append({"kind": "skills-and-references-merged",
                         "why": "the two knowledge types are not interchangeable"})
    if r.get("raw_document_injected") is True:
        findings.append({"kind": "raw-document-injected",
                         "why": "direct injection buys little and costs time"})
    if not findings:
        findings.append({"kind": "audit-conditions-met"})
    return {"format": FORMAT, "findings": findings, "verdict": "audit-complete"}


def advise(profile):
    """Map a harness profile onto the skill-evolution gaps the paper names."""
    p = profile or {}
    have = {str(k) for k in p if p.get(k)}
    checks = (
        ("separates_skills_from_references", "stores_one_knowledge_type",
         "procedures and lookups are consulted differently"),
        ("grounds_every_entry_in_a_source", "writes_skills_from_memory",
         "an ungrounded entry cannot be checked or revised"),
        ("names_one_primary_cause", "revises_without_a_diagnosis",
         "grounding, mutation and coverage need different fixes"),
        ("validates_in_a_fresh_session", "replays_with_the_failure_history",
         "the history can carry the answer"),
        ("certifies_a_merge_by_regression", "merges_and_ships",
         "a merge can discard a validated capability"),
        ("keeps_evolution_disjoint_from_test", "evolves_on_the_benchmark",
         "overlap turns a measurement into a fit"),
    )
    findings = []
    for key, kind, why in checks:
        if key not in have:
            findings.append({"kind": kind, "why": why})
    return {"format": FORMAT, "findings": findings}
