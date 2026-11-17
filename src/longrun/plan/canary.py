#!/usr/bin/env python3
"""Canary integrity case for the promotion gate (PROCTOR, arXiv:2609.02246 §5.5).

A canary is a held-out case no honest candidate can pass. A *pass* on the canary
is therefore evidence of leakage or a sandbox escape, not of quality: the
promotion must be refused and audited. A canary that is not declared, or does not
appear in the results, leaves the gate UNBOUND (no positive control) — never
green. The paper's own caveat is recorded so this is used as a tripwire, not a
proof: a candidate "selective enough to fail the canary deliberately" defeats it.

Pure module: reads a results dict, no I/O, no model, no network.
"""


def evaluate(results, canary_id=None):
    """`{"verdict": "ok"|"tripped"|"unbound", "case": <id|None>, "reason": str}`.

    `results` is `{"cases": {<case_id>: bool, ...}}` — the per-case outcome of the
    sealed held-out run (`plan.heldout.run`). `ok` means the canary failed as it
    should (no evidence of leakage); `tripped` means an unpassable case passed.
    """
    cases = (results or {}).get("cases") or {}
    if not canary_id:
        return {"verdict": "unbound", "case": None, "reason": "no canary declared"}
    if canary_id not in cases:
        return {"verdict": "unbound", "case": canary_id, "reason": "canary not in results"}
    if cases.get(canary_id):
        return {"verdict": "tripped", "case": canary_id,
                "reason": "an unpassable case passed — suspected label/sandbox leakage"}
    return {"verdict": "ok", "case": canary_id, "reason": "canary correctly failed"}
