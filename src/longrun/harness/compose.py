#!/usr/bin/env python3
"""H2-6 — compose: adopt only what a contrast supports.

"Composition is selective: it may merge supported changes, revise conflicting
edits, adopt one candidate, or preserve the current harness. Each decision is tied
to a concrete observation rather than a presumed score gain"
(`research/papers/harness2/harness2_2610.14224.txt:291-297`).

The rule is deliberately one line, because the failure it prevents is measured:
editing the harness WITHOUT probing costs 10.2 points on WB-code (`:646-649`).

    keep a candidate  <=>  the contrast is comparable AND its verdict is `improved`

`mixed` is not "mostly improved": a fix that introduces a new error class is
refused and the new class is named in the decision. `unchanged` writes nothing —
the paper's reflector adds no experience entry when the evidence is insufficient
(`:392-396`).

Adoption here means ONE library entry plus the proposals the editors already wrote;
nothing is applied to a live harness (`util/improve.py:21-27`).
"""
import os

from longrun.harness import library as library_mod

_REFUSE = {
    "regressed": "the candidate made it worse",
    "unchanged": "the candidate changed nothing observable",
    "mixed": "the candidate fixed one failure and introduced another",
    "incomparable": "the two runs answer different goals — the contrast is not evidence",
}


def _names(candidates):
    """Candidate names, in order."""
    return [str((c or {}).get("name") or "?") for c in (candidates or []) if isinstance(c, dict)]


def select(contrast, candidates):
    """Decide what a contrast supports.

    Args:
        contrast: `harness.contrast.diff` output.
        candidates: the candidates the probe ran.
    Returns:
        {"adopt": bool, "kept": [...], "rejected": [{name, reason}], "decision": str}
    """
    cands = [c for c in (candidates or []) if isinstance(c, dict)]
    if not isinstance(contrast, dict) or not contrast:
        return {"adopt": False, "kept": [], "rejected": [],
                "decision": "no contrast: nothing can be adopted"}
    if contrast.get("comparable") is False:
        reason = _REFUSE["incomparable"]
    else:
        verdict = str(contrast.get("verdict") or "")
        reason = "" if verdict == "improved" else _REFUSE.get(verdict, "unknown verdict %r" % (verdict,))
    if reason:
        return {"adopt": False, "kept": [],
                "rejected": [{"name": n, "reason": reason} for n in _names(cands)],
                "decision": "%s: %s" % (contrast.get("verdict") or "no verdict", reason)}
    errs = contrast.get("errors") or {}
    fixed = ", ".join(str(x) for x in (errs.get("fixed") or [])) or "(none named)"
    steps = contrast.get("steps") or {}
    decision = "adopt %d candidate(s): removed %s; steps %s -> %s" % (
        len(cands), fixed, steps.get("base"), steps.get("cand"))
    return {"adopt": bool(cands), "kept": cands, "rejected": [], "decision": decision}


def adopt(domain, task_kind, lesson, contrast, candidates, staged):
    """Record ONE library entry for an adopted candidate set.

    Args:
        domain: the library bucket (task family).
        task_kind: how the task is described in the index.
        lesson: the transferable operation, in one or two sentences.
        contrast: the contrast that justified it.
        candidates: the kept candidates.
        staged: {candidate name: staged file path} (from `harness.probe.stage`).
    Returns:
        The library row, or None when the contrast does not support an adoption.
    """
    chosen = select(contrast, candidates)
    if not chosen["adopt"]:
        return None
    files = {}
    for cand in chosen["kept"]:
        name = str(cand.get("name") or "")
        path = (staged or {}).get(name)
        if name and path:
            # The component keeps its REAL file name (`SKILL.md`, `guardrails.md`):
            # a library that renames it cannot be loaded by any runtime.
            files[os.path.basename(path)] = path
    if not files:
        return None
    errs = (contrast or {}).get("errors") or {}
    return library_mod.add(domain, {
        "task_kind": task_kind,
        "lesson": lesson,
        "evidence": {"verdict": (contrast or {}).get("verdict"),
                     "fixed": errs.get("fixed") or [],
                     "introduced": errs.get("introduced") or []},
        "files": files,
    })
