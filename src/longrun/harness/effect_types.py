#!/usr/bin/env python3
"""Effect-typed tools — a tool declares what a call DOES, so a trace can be judged.

Source: arXiv:2610.35981, "Small agents should know what their tools do" (round
116). Its observation is the failure mode longrun's untyped catalog cannot see:
agents delete without asking, repeat writes, re-read state they already hold.

The paper's mechanism is a declaration per tool — the effect, whether it is
idempotent, and which resources it reads and writes — which lets a replay
verifier decide whether a trace is effect-safe *without labels or a judge
model*. This module implements that verifier plus a coverage report, so an
untyped catalog is a number instead of an assumption.

Findings (deterministic, no model):
  undeclared-tool     a call whose tool is absent from the catalog — it does
                      not make the trace unsafe, it makes that call undecidable;
  repeat-write        a non-idempotent OVERWRITE of a resource already written
                      with no read of that resource in between (a read clears
                      the prior write; an append never counts, because appending
                      twice is the normal operation and cannot overwrite);
  delete-without-read a delete whose target was never read earlier in the trace
                      — the tool's own declared read is its precondition, not
                      the agent's observation, so it does not satisfy the rule;
  redundant-read      a read of a resource nothing has written since the last read;
  program-opportunity consecutive calls where a later call's only input is the
                      previous call's write (a short program would do).

The verdict is tri-state. `unsafe` is a proven violation, `safe` means every
call was typed and none violated, and `undecidable` means an untyped call left
part of the trace unjudged — an untyped catalog is a coverage number, not an
accusation. A proven violation outranks an unjudged call.

`escalation()` is the LIVE entry point: the tool gate calls it for one proposed
call and it upgrades an automatic approval to a required one when the declared
effect is destructive or the exact non-idempotent call already ran. It only
escalates — it never denies and never touches an untyped tool, so a mostly
untyped catalog cannot turn into a blanket approval prompt.

Pure: catalog + trace in, findings out.
"""
from __future__ import annotations

import hashlib
import json

FORMAT = "longrun-effect-types/1"
EFFECTS = ("none", "read", "append", "write", "delete", "external")
_UNSAFE_KINDS = {"repeat-write", "delete-without-read", "malformed-call"}
_UNDECIDABLE_KINDS = {"undeclared-tool"}


def _decl(catalog, tool):
    row = (catalog or {}).get(tool)
    return row if isinstance(row, dict) else None


def _digest(tool, args):
    """A stable identity for one concrete call (tool + normalised args)."""
    try:
        body = json.dumps({"tool": tool, "args": args or {}}, sort_keys=True,
                          ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        body = repr((tool, args))
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def escalation(tool, decl, args, trace):
    """(rule, reason) to upgrade an auto-approved live call, or (None, None).

    Called by the tool gate BEFORE dispatch. Two declared effects cannot be
    approved automatically: a destructive `delete`, and an exact repeat of a
    non-idempotent call that already executed in this run (the effect would be
    duplicated). An untyped tool is left to the existing policy — this function
    never escalates one. Pure and total: a missing/invalid declaration is a no-op.
    """
    if not isinstance(decl, dict):
        return None, None
    effect = decl.get("effect")
    if effect not in EFFECTS:
        return None, None
    if effect == "delete":
        return ("effect-destructive",
                "the declared effect is destructive (`delete`); a destructive "
                "call may not be approved automatically")
    if effect in ("write", "append", "external") and not decl.get("idempotent"):
        want = _digest(tool, args)
        for entry in trace or []:
            if not isinstance(entry, dict) or entry.get("action") != "tool":
                continue
            if entry.get("tool") != tool:
                continue
            meta = entry.get("tool_result") or {}
            if isinstance(meta, dict) and meta.get("ok") is False:
                continue
            if _digest(tool, entry.get("args") or {}) == want:
                return ("effect-repeat",
                        "this exact non-idempotent `%s` call already ran in this "
                        "run; repeating it may duplicate the effect" % effect)
    return None, None


def coverage(catalog):
    """How much of the catalog is typed at all — the honest number for a harness."""
    catalog = catalog or {}
    total = len(catalog)
    typed = 0
    idempotent = 0
    histogram = {e: 0 for e in EFFECTS}
    invalid = []
    for tool, row in catalog.items():
        if not isinstance(row, dict):
            invalid.append({"tool": tool, "why": "declaration is not an object"})
            continue
        effect = row.get("effect")
        if effect is None or effect == "":
            # Untyped is the normal state of an undeclared tool, not an error.
            continue
        if effect not in EFFECTS:
            invalid.append({"tool": tool, "why": "invalid effect", "value": effect})
            continue
        typed += 1
        histogram[effect] += 1
        if row.get("idempotent"):
            idempotent += 1
    # An invalid declaration is neither typed nor merely absent: it is its own
    # state, so it must not be double-counted as untyped. An invalid row also
    # drives the verdict, which used to read `partial` for a 100%-typed catalog
    # that carried one bad row.
    untyped = total - typed - len(invalid)
    if invalid:
        verdict = "invalid"
    elif total and typed == total:
        verdict = "typed"
    else:
        verdict = "partial" if typed else "untyped"
    return {"format": FORMAT, "total": total, "typed": typed,
            "untyped": untyped, "idempotent": idempotent,
            "effects": histogram, "invalid": invalid,
            "verdict": verdict}


def verify_trace(trace, catalog):
    """Effect safety of a call sequence, decided from the declarations alone."""
    findings = []
    read_state = {}       # resource -> True when a read is still fresh
    written = set()       # non-idempotent writes already made
    prev_writes = set()
    for i, call in enumerate(trace or []):
        if not isinstance(call, dict) or not call.get("tool"):
            findings.append({"kind": "malformed-call", "index": i})
            continue
        tool = call["tool"]
        decl = _decl(catalog, tool)
        if decl is None or decl.get("effect") not in EFFECTS:
            findings.append({"kind": "undeclared-tool", "index": i, "tool": tool,
                             "why": "untyped call: effect safety cannot be decided"})
            prev_writes = set()
            continue
        effect = decl.get("effect")
        reads = [r for r in (decl.get("reads") or [])]
        writes = [r for r in (decl.get("writes") or [])]
        # A writer feeding a writer is a conflict the effect checker reports as
        # repeat-write; this rule is only about a call CONSUMING the predecessor.
        if prev_writes & set(reads):
            findings.append({"kind": "program-opportunity", "index": i,
                             "why": "it consumes the previous call's write; one turn would do"})
        if effect == "read":
            for r in reads:
                if read_state.get(r):
                    findings.append({"kind": "redundant-read", "index": i, "resource": r})
                read_state[r] = True
                written.discard(r)
            prev_writes = set()
            continue
        if effect == "delete":
            for r in writes:
                if not read_state.get(r):
                    findings.append({"kind": "delete-without-read", "index": i, "resource": r})
        # A declared read observes the resource, so an earlier write is no longer
        # a blind repeat. `append` is excluded from the rule: appending twice is
        # the normal operation and an append cannot overwrite.
        for r in reads:
            written.discard(r)
        if effect in ("write", "delete", "external") and not decl.get("idempotent"):
            for r in writes:
                if r in written:
                    findings.append({"kind": "repeat-write", "index": i, "resource": r})
                written.add(r)
        # State AFTER the call: a write invalidates freshness and a read
        # establishes it. Writes go last so `fs.edit` (reads+writes one file)
        # does not leave the edited resource looking freshly read.
        for r in reads:
            read_state[r] = True
        for r in writes:
            read_state[r] = False
        prev_writes = set(writes)
    kinds = {f["kind"] for f in findings}
    if kinds & _UNSAFE_KINDS:
        verdict = "unsafe"
    elif kinds & _UNDECIDABLE_KINDS:
        verdict = "undecidable"
    else:
        verdict = "safe"
    return {"format": FORMAT, "findings": findings, "verdict": verdict}
