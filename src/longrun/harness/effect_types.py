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
  undeclared-tool     a call whose tool is absent from the catalog;
  repeat-write        a non-idempotent write to a resource already written, with
                      no read of that resource in between;
  delete-without-read a delete whose target was never read earlier in the trace;
  redundant-read      a read of a resource nothing has written since the last read;
  program-opportunity consecutive calls where a later call's only input is the
                      previous call's write (a short program would do).

Pure: catalog + trace in, findings out.
"""
from __future__ import annotations

FORMAT = "longrun-effect-types/1"
EFFECTS = ("none", "read", "append", "write", "delete", "external")


def _decl(catalog, tool):
    row = (catalog or {}).get(tool)
    return row if isinstance(row, dict) else None


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
    return {"format": FORMAT, "total": total, "typed": typed,
            "untyped": total - typed, "idempotent": idempotent,
            "effects": histogram, "invalid": invalid,
            "verdict": "typed" if total and typed == total else ("partial" if typed else "untyped")}


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
        if prev_writes & (set(reads) | set(writes)):
            findings.append({"kind": "program-opportunity", "index": i,
                             "why": "it consumes the previous call's write; one turn would do"})
        if effect == "read":
            for r in reads:
                if read_state.get(r):
                    findings.append({"kind": "redundant-read", "index": i, "resource": r})
                read_state[r] = True
            prev_writes = set()
            continue
        if effect == "delete":
            for r in writes:
                if not read_state.get(r):
                    findings.append({"kind": "delete-without-read", "index": i, "resource": r})
        if effect in ("write", "delete", "append", "external") and not decl.get("idempotent"):
            for r in writes:
                if r in written:
                    findings.append({"kind": "repeat-write", "index": i, "resource": r})
                written.add(r)
        for r in writes:
            read_state[r] = False
        for r in reads:
            read_state[r] = True
        prev_writes = set(writes)
    kinds = {f["kind"] for f in findings}
    return {"format": FORMAT, "findings": findings,
            "verdict": "unsafe" if kinds & {"repeat-write", "delete-without-read",
                                            "undeclared-tool", "malformed-call"} else "safe"}
