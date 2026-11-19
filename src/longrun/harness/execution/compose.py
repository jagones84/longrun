#!/usr/bin/env python3
"""H2-6 — select observed candidates; refuse unsupported durable learning.

"Composition is selective: it may merge supported changes, revise conflicting
edits, adopt one candidate, or preserve the current harness. Each decision is tied
to a concrete observation rather than a presumed score gain"
(`research/papers/harness2/harness2_2610.14224.txt:291-297`).

The paper's direct-editing ablation jointly removes reference executions,
candidate probes and library access (`:646-649`); it does not isolate probing.

    keep a candidate  <=>  the contrast is comparable AND its verdict is `improved`

`mixed` is not "mostly improved": a fix that introduces a new error class is
refused and the new class is named in the decision. `unchanged` writes nothing —
the paper's reflector adds no experience entry when the evidence is insufficient
(`:392-396`).

Selection is not causal attribution or correctness verification. The current
single-rollout reflector produces NO_ENTRY; legacy direct adoption writes nothing.
"""

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
    decision = "select %d candidate(s): observed absence of %s; steps %s -> %s" % (
        len(cands), fixed, steps.get("base"), steps.get("cand"))
    return {"adopt": bool(cands), "kept": cands, "rejected": [], "decision": decision}


def aggregate(contrasts):
    """One verdict over repeated matched runs; disagreement is `mixed`, never a win."""
    verdicts = [str((c or {}).get("verdict") or "") for c in (contrasts or [])
                if isinstance(c, dict)]
    verdicts = [v for v in verdicts if v]
    if not verdicts:
        return "unknown"
    return verdicts[0] if len(set(verdicts)) == 1 else "mixed"


def reflect(trials, successor=None):
    """Record observations without claiming causal or transferable improvement.

    Appendix H, Prompt 6 (:2436-2471) prefers confounded attribution when a single
    rollout is all that supports an edit. Matched repeats raise confidence only
    when every repeat agrees; even then a durable entry still needs human
    approval (`cycle._admit`), never an automatic library write.
    """
    edits = []
    admissible = True
    for trial in trials or []:
        candidate = trial.get("candidate") or {}
        contrast = trial.get("contrast") or {}
        repeats = int(trial.get("repeats") or 1)
        verdicts = [str((c or {}).get("verdict") or "")
                    for c in (trial.get("contrasts") or []) if isinstance(c, dict)]
        consistent = (repeats >= 2 and len(verdicts) >= 2
                      and len(set(verdicts)) == 1 and verdicts[0] == contrast.get("verdict"))
        if not consistent:
            admissible = False
        edits.append({"name": candidate.get("name"), "kind": candidate.get("kind"),
                      "run_id": (trial.get("record") or {}).get("run_id"),
                      "observed": contrast.get("verdict") or trial.get("status"),
                      "fixed": (contrast.get("errors") or {}).get("fixed") or [],
                      "introduced": (contrast.get("errors") or {}).get("introduced") or [],
                      "repeats": repeats, "verdicts": verdicts,
                      "attribution": ("repeated_matched_runs" if consistent
                                      else "confounded"),
                      "confidence": "supported" if consistent else "insufficient",
                      "reason": ("%d matched repeats agreed; this is one task family, "
                                 "not transfer" % repeats if consistent
                                 else "single rollout; matched repeated controls are absent")})
    successor_repeats = int((successor or {}).get("repeats") or 1)
    evidence = {"consistent_repeats": bool(edits) and admissible,
                "successor_repeats": successor_repeats}
    return {"status": "NO_ENTRY", "edits": edits, "evidence": evidence,
            "successor_run": ((successor or {}).get("record") or {}).get("run_id"),
            "reason": ("NO_ENTRY: durable library entries need human approval and "
                       "cross-task evidence, not one task family"
                       if evidence["consistent_repeats"]
                       else "NO_ENTRY: execution differences do not yet establish a reusable lesson")}


def adopt(domain, task_kind, lesson, contrast, candidates, staged):
    """Legacy adoption API, disabled without a verified experiment contract.

    Args:
        domain: the library bucket (task family).
        task_kind: how the task is described in the index.
        lesson: the transferable operation, in one or two sentences.
        contrast: the contrast that justified it.
        candidates: the kept candidates.
        staged: {candidate name: staged file path} (from `harness.probe.stage`).
    Returns:
        None. A single behavioral contrast is insufficient for durable learning.
    """
    # Compatibility entry point: the old call supplies only a single contrast.
    # That cannot establish transfer, and the current bounded reflector always
    # returns NO_ENTRY. Retain the API without an evidence-free library write.
    return None
