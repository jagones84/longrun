#!/usr/bin/env python3
"""Harness coverage audit — the ETCSLV matrix audited against its own evidence rules.

Round 171. Source: the survey *Agent Harness for Large Language Model Agents*
(`Awesome-Agent-Harness`, v4, CC-BY-4.0, DOI 10.20944/preprints202604.0428.v3).
The survey models a harness as **H = (E, T, C, S, L, V)** — six governance
functions — and rates 34 systems on the same evidence-coded matrix
(`docs/systems.json`), one cell per component:

    Execution loop · Tool registry · Context manager · State store ·
    Lifecycle hooks · Evaluation interface

Every cell carries `{id, rating, source, version, evidenceType, confidence}` and
a rating from a fixed vocabulary (● **Full** · ◐ **Partial** · ○ **Absent** ·
? **Unverified**). The survey states the RULES that make a rating honest — `Full`
needs first-party material; `Absent` needs explicit first-party evidence; the
vocabulary is closed — and keeps them as prose. This module is those rules as a
deterministic verdict: read a matrix document, return the cells that break them.

Pure: a plain-data matrix in, findings out, no app import, no write (ADR-0003).
The only adapter is `core/forge.py` (`python3 forge.py harnesscov audit FILE.json`).

    components()            -> the six ids, in order, with one-line definitions
    rate(system)            -> one system normalised, with its per-cell ratings
    matrix(doc)             -> the whole document normalised + its gaps + a verdict
    audit(doc, as_of=None)  -> {"format", "verdict", "counts", "findings": [...]}
"""
from __future__ import annotations

FORMAT = "longrun-harness-coverage/1"
MAX_FINDINGS = 200

VOCAB = ("Full", "Partial", "Absent", "Unverified")
GAP_RATINGS = ("Partial", "Absent", "Unverified")
COMPONENT_ORDER = ("E", "T", "C", "S", "L", "V")
COMPONENTS = {
    "E": {"name": "Execution loop",
          "what": "turn and step control, termination, retry, recovery, delegation"},
    "T": {"name": "Tool registry",
          "what": "typed tools, routing, validation, authorization, result handling"},
    "C": {"name": "Context manager",
          "what": "prompt assembly, retrieval, compaction, salience, provenance"},
    "S": {"name": "State store",
          "what": "cross-turn and cross-session persistence, checkpoints, recovery"},
    "L": {"name": "Lifecycle hooks",
          "what": "authentication, approval, policy, instrumentation, interception"},
    "V": {"name": "Evaluation iface",
          "what": "trajectories, intermediate state, outcomes, experiments, audit"},
}
# A cutoff older than this many days is worth a finding when `as_of` is supplied.
STALE_DAYS = 180


def components():
    """The six components, in order: `[{id, name, what}]`.
    """
    return [{"id": cid, "name": COMPONENTS[cid]["name"], "what": COMPONENTS[cid]["what"]}
            for cid in COMPONENT_ORDER]


def _cells(system):
    """`{id: cell}` for one system's component list, unknown ids kept out."""
    out = {}
    for cell in (system or {}).get("components") or ():
        if not isinstance(cell, dict):
            continue
        cid = cell.get("id")
        if cid in COMPONENT_ORDER:
            out[cid] = cell
    return out


def rate(system):
    """One system normalised.

    Returns `{name, category, accessDate, cells, missing, coverage, verdict}`:
    `cells` is `{id: {rating, source, version, evidenceType, confidence}}` for the
    ids present; `missing` names the component ids no cell covers (rated
    `Unverified` by absence of evidence, never silently dropped); `coverage`
    counts the four ratings; `verdict` is `complete` when every component carries a
    vocabulary rating, `gaps` otherwise.
    """
    system = system if isinstance(system, dict) else {}
    raw = _cells(system)
    cells, missing = {}, []
    for cid in COMPONENT_ORDER:
        cell = raw.get(cid)
        if cell is None:
            missing.append(cid)
            continue
        cells[cid] = {
            "rating": str(cell.get("rating") or "Unverified"),
            "source": cell.get("source") or "",
            "version": cell.get("version") or "",
            "evidenceType": cell.get("evidenceType") or "",
            "confidence": cell.get("confidence") or "",
        }
    coverage = {r: 0 for r in VOCAB}
    for cid in COMPONENT_ORDER:
        if cid in missing:
            coverage["Unverified"] += 1
        else:
            rating = cells[cid]["rating"]
            coverage[rating if rating in coverage else "Unverified"] += 1
    verdict = "complete" if not missing and not any(
        cells[c]["rating"] not in VOCAB for c in cells) else "gaps"
    return {"name": str(system.get("name") or ""),
            "category": str(system.get("category") or ""),
            "accessDate": system.get("accessDate") or "",
            "cells": cells, "missing": missing,
            "coverage": coverage, "verdict": verdict}


def matrix(doc):
    """The whole document normalised.

    Returns `{format, cutoff, componentOrder, systems, gaps, summary, verdict}`:
    `systems` is `rate()` per entry; `gaps` lists every cell rated
    `Partial|Absent|Unverified` (or absent entirely) with its system and
    component; `summary` counts ratings per component; `verdict` is `clean` when
    no gap exists, `gaps` otherwise.
    """
    doc = doc if isinstance(doc, dict) else {}
    order = [c for c in (doc.get("componentOrder") or COMPONENT_ORDER)
             if c in COMPONENT_ORDER] or list(COMPONENT_ORDER)
    systems = [rate(s) for s in (doc.get("systems") or ())]
    gaps = []
    summary = {cid: {r: 0 for r in VOCAB} for cid in order}
    for sysrow in systems:
        for cid in order:
            rating = "Unverified" if cid in sysrow["missing"] else sysrow["cells"].get(
                cid, {}).get("rating", "Unverified")
            if rating not in summary[cid]:
                rating = "Unverified"
            summary[cid][rating] += 1
            if rating in GAP_RATINGS:
                gaps.append({"system": sysrow["name"], "component": cid, "rating": rating})
    return {"format": FORMAT,
            "cutoff": doc.get("cutoff"),
            "componentOrder": order,
            "systems": systems,
            "gaps": gaps,
            "summary": summary,
            "verdict": "clean" if not gaps else "gaps"}


def _days_between(a, b):
    """Whole days from ISO date `a` to ISO date `b`, or None when unparseable."""
    import datetime
    try:
        da = datetime.date.fromisoformat(str(a)[:10])
        db = datetime.date.fromisoformat(str(b)[:10])
    except (TypeError, ValueError):
        return None
    return (db - da).days


def audit(doc, as_of=None):
    """The evidence-rule findings a matrix carries.

    Kinds, each naming the system and component it is about:

      * `unknown-component`          — a cell's id is not one of the six;
      * `duplicate-system`           — one system name appears twice;
      * `rating-not-in-vocabulary`   — a rating outside Full/Partial/Absent/Unverified;
      * `missing-evidence-type`      — a cell carries no `evidenceType`;
      * `full-without-source`        — rated Full with no source (the rule needs first-party material);
      * `absent-without-proof`       — rated Absent with no source (the rule needs explicit first-party evidence);
      * `unverified-with-high-confidence` — Unverified while claiming high confidence;
      * `stale-cutoff`               — only when `as_of` is given and the cutoff is older than `STALE_DAYS`.

    `verdict` is `clean` when no finding exists. Deterministic; the clock is never
    read (a cutoff check runs only when the caller passes `as_of`).
    """
    doc = doc if isinstance(doc, dict) else {}
    findings = []
    seen = {}
    for system in doc.get("systems") or ():
        if not isinstance(system, dict):
            continue
        name = str(system.get("name") or "")
        if name in seen:
            findings.append({"kind": "duplicate-system", "system": name, "component": "-",
                             "detail": "system %r appears more than once" % name})
        seen[name] = True
        for cell in system.get("components") or ():
            if not isinstance(cell, dict):
                continue
            cid = str(cell.get("id") or "")
            rating = str(cell.get("rating") or "")
            locator = "%s/%s" % (name, cid)
            if cid not in COMPONENT_ORDER:
                findings.append({"kind": "unknown-component", "system": name, "component": cid,
                                 "detail": "%s is not one of E,T,C,S,L,V" % (cid or "(none)")})
                continue
            if rating not in VOCAB:
                findings.append({"kind": "rating-not-in-vocabulary", "system": name, "component": cid,
                                 "detail": "%s rates %r, outside the vocabulary" % (locator, rating)})
                continue
            if not str(cell.get("evidenceType") or "").strip():
                findings.append({"kind": "missing-evidence-type", "system": name, "component": cid,
                                 "detail": "%s carries no evidenceType" % locator})
            if rating == "Full" and not str(cell.get("source") or "").strip():
                findings.append({"kind": "full-without-source", "system": name, "component": cid,
                                 "detail": "%s is Full with no first-party source" % locator})
            if rating == "Absent" and not str(cell.get("source") or "").strip():
                findings.append({"kind": "absent-without-proof", "system": name, "component": cid,
                                 "detail": "%s is Absent with no first-party proof" % locator})
            if rating == "Unverified" and str(cell.get("confidence") or "").strip().lower() == "high":
                findings.append({"kind": "unverified-with-high-confidence", "system": name,
                                 "component": cid,
                                 "detail": "%s is Unverified but claims high confidence" % locator})
    if as_of:
        age = _days_between(doc.get("cutoff"), as_of)
        if age is not None and age > STALE_DAYS:
            findings.append({"kind": "stale-cutoff", "system": "-", "component": "-",
                             "detail": "cutoff %s is %d days before %s (limit %d)"
                                       % (doc.get("cutoff"), age, str(as_of)[:10], STALE_DAYS)})
    counts = {}
    for f in findings:
        counts[f["kind"]] = counts.get(f["kind"], 0) + 1
    if len(findings) > MAX_FINDINGS:
        findings = findings[:MAX_FINDINGS]
    return {"format": FORMAT,
            "verdict": "defects" if findings else "clean",
            "counts": counts,
            "findings": findings}
