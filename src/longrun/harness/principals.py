#!/usr/bin/env python3
"""Principal-context authorization — an action is allowed only if EVERY
influencing principal would allow it.

Source: arXiv:2611.08768, "Conflux: Preventing Privilege Escalation with
Principal Contexts and System-Level Evaluation" (round 110). The objective it
formalises is privilege escalation at the SYSTEM level: an action may proceed
only if every principal that influenced it is authorised for it. Its kernel,
ITES, derives authority from provenance and intersects the permissions of all
influencing principals, with two preconditions this module can check:

  * the decision context is KNOWN and non-empty (any input with unknown
    provenance poisons the whole context — no silent "trusted by default");
  * provenance is NO-LAUNDERING: an object's recorded authors must include the
    authors of every object it was derived from (otherwise a trusted agent
    copies attacker text, signs it, and the attacker leaves the context).

Longrun already intersects authority down a DELEGATION chain
(`agent/subagent.py:bind_authority`). This module covers the other axis: the
principals that INFLUENCED the action's inputs and arguments, whoever ran it.

Pure: takes plain data, returns a verdict; nothing is executed.
"""
from __future__ import annotations

from fnmatch import fnmatch

FORMAT = "longrun-principal-context/1"


def _authors_of(item):
    """The principals recorded on one provenance item, or None when unknown."""
    if item is None:
        return None
    if isinstance(item, str):
        return {item} if item.strip() else None
    if isinstance(item, dict):
        authors = item.get("authors")
        if isinstance(authors, (list, tuple, set)):
            vals = {str(a) for a in authors if str(a).strip()}
            return vals or None
        one = item.get("author")
        if isinstance(one, str) and one.strip():
            return {one.strip()}
        return None
    return None


def merge(items):
    """Union of principal sets; ANY unknown item makes the whole context unknown."""
    out = set()
    for item in items or ():
        got = _authors_of(item)
        if got is None:
            return None
        out |= got
    return out or None


def decision_context(influences, argument_sources=None):
    """The principals whose permissions the action must satisfy.

    `influences` are the provenance records of what shaped the proposal
    (messages, tool results, briefs); `argument_sources` are the provenance
    records of the action's authority-bearing arguments. Unknown provenance on
    either side yields an unknown context, never a permissive one.
    """
    ctx = merge(list(influences or ()) + list(argument_sources or ()))
    return {"principals": sorted(ctx) if ctx else [],
            "known": ctx is not None,
            "empty": not ctx}


def _permits(records, action):
    """Does one principal's record allow this action? Missing record denies."""
    if not records:
        return False
    for pattern in records:
        p = str(pattern)
        if p == "*" or p == action or fnmatch(action, p):
            return True
    return False


def authorize(action, context, permissions):
    """ITES, in one function.

    `context` is the decision context (principals + known flag, from
    `decision_context`); `permissions` maps principal -> list of allowed action
    patterns (`"fs.*"`, `"read"`, `"*"`). A principal with no record denies:
    the kernel is fail-closed.
    """
    principals = list(context.get("principals") or [])
    if not context.get("known"):
        return {"format": FORMAT, "action": str(action), "allow": False,
                "decision_context": principals,
                "blocked_by": [], "reason": "unknown-provenance"}
    if not principals:
        return {"format": FORMAT, "action": str(action), "allow": False,
                "decision_context": [], "blocked_by": [], "reason": "empty-context"}
    blocked = [p for p in principals if not _permits((permissions or {}).get(p), action)]
    return {"format": FORMAT, "action": str(action), "allow": not blocked,
            "decision_context": principals, "blocked_by": blocked,
            "reason": "allowed" if not blocked else "blocked-by-influencing-principal"}


def no_laundering(objects):
    """Check the provenance store: every derived object names its sources' authors.

    `objects` rows: `{"id", "authors": [...], "sources": [id, ...]}`. A source
    id with no row is unknown provenance and counts as a violation, not as a
    pass. Returns the violations and a verdict.
    """
    rows = {}
    for o in objects or ():
        if not isinstance(o, dict):
            continue
        rows[str(o.get("id"))] = {str(a) for a in (o.get("authors") or [])}
    violations = []
    for o in objects or ():
        if not isinstance(o, dict):
            continue
        oid = str(o.get("id"))
        have = rows.get(oid, set())
        missing = set()
        unknown = []
        for src in o.get("sources") or ():
            src_id = str(src)
            if src_id not in rows:
                unknown.append(src_id)
                continue
            missing |= (rows[src_id] - have)
        if missing or unknown:
            violations.append({"object": oid,
                               "missing_authors": sorted(missing),
                               "unknown_sources": unknown,
                               "reason": ("source-authors-absent" if missing else
                                          "unknown-source")})
    return {"format": FORMAT, "objects": len(rows), "violations": violations,
            "verdict": "laundered" if violations else "clean"}


def check(doc):
    """One call for a JSON fixture: decision context, authorization, laundering."""
    doc = doc if isinstance(doc, dict) else {}
    influences = doc.get("influences") or []
    if not isinstance(influences, list):
        influences = [influences]
    arg_sources = doc.get("argument_sources") or []
    if not isinstance(arg_sources, list):
        arg_sources = [arg_sources]
    ctx = decision_context(influences, arg_sources)
    out = authorize(doc.get("action") or "", ctx, doc.get("permissions") or {})
    if doc.get("objects") is not None:
        out["laundering"] = no_laundering(doc.get("objects") or [])
    return out
