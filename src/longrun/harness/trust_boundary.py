#!/usr/bin/env python3
"""Trust boundaries — identity, authorization and propagation at a component seam.

Source: arXiv:2611.21259, "Evaluating Authorization and Trust Boundaries in
Agentic Orchestration Frameworks" (round 127). A trust boundary is where data,
instructions or requests pass between components with different privileges, and
three concerns meet there: **identity** (is the claimed sender verified),
**authorization** (is this operation permitted) and **trust propagation** (does
the originating authority survive the hop). The paper's experiments show the
failure modes concretely: unauthorized tool chaining, a symlink redirected
between validation and use, encoded payloads crossing into a privileged
executor, and delegation that carries no authority check (§3). It also separates
an attempted operation from an actual unauthorized effect (E1/E3), and finds
memory poisoning distinct from access control (E9/E10).

  * `evaluate(call)` — allow or deny across the seven boundaries, naming
    `identity-unverified`, `operation-not-authorized`, `capability-not-granted`,
    `stale-validation` (the value was checked, then changed), `delegation-widens`
    and `encoded-instruction`, plus the missing-evidence findings
    `identity-unasserted`, `authorization-missing` and `capability-unasserted`.
  * `classify(outcome)` — attempted / unauthorized effect / disclosure, so a
    proposal is not reported as an effect.

Fail closed. Identity, authorization and capability are REQUIRED evidence: a
call that supplies no principal, no authorised operation set or no capability
grant is denied, never allowed by omission (`identity-unasserted`,
`authorization-missing`, `capability-unasserted`, `capability-not-granted`).
Validation, delegation and encoding are CLAIMS: they are checked when asserted,
and their absence asserts nothing.

Pure: a call description in, a decision out.
"""
from __future__ import annotations

FORMAT = "longrun-trust-boundary/1"
BOUNDARIES = ("user-model", "content-model", "model-tool", "agent-filesystem",
              "agent-execution", "agent-memory", "agent-agent")


def _set(value):
    return {str(v) for v in (value or [])}


def evaluate(call):
    """Decide one cross-boundary call from its own evidence. Fail closed.

    Identity, authorization and capability are required evidence: a call that
    does not carry them is denied, because an absent proof of authority is not
    a proof of authority. Validation, delegation and encoding are claims —
    checked when asserted, absent means nothing was claimed.
    """
    call = call if isinstance(call, dict) else {}
    boundary = str(call.get("boundary") or "")
    findings = []
    if boundary not in BOUNDARIES:
        findings.append({"kind": "unknown-boundary", "boundary": boundary,
                         "why": "a seam outside the seven is not assessed here"})
    claimed = call.get("claimed_identity")
    verified = call.get("verified_identity")
    if not claimed:
        findings.append({"kind": "identity-unasserted",
                         "why": "no principal was asserted, so no principal was authenticated"})
    elif str(claimed) != str(verified):
        findings.append({"kind": "identity-unverified", "claimed": claimed,
                         "verified": verified,
                         "why": "a name in the message is not an authenticated principal"})
    operation = str(call.get("operation") or "")
    authorized = _set(call.get("authorized_operations"))
    if not authorized:
        findings.append({"kind": "authorization-missing", "operation": operation,
                         "why": "no authorised operation set was supplied, "
                                "so the operation is not authorised"})
    elif operation not in authorized:
        findings.append({"kind": "operation-not-authorized", "operation": operation})
    required = call.get("required_capability")
    granted = _set(call.get("granted_capabilities"))
    if not required:
        findings.append({"kind": "capability-unasserted",
                         "why": "no required capability was named, so no grant was checked"})
    elif str(required) not in granted:
        findings.append({"kind": "capability-not-granted", "capability": required,
                         "granted": sorted(granted),
                         "why": "a named capability with no grant is not granted"})
    validation = call.get("validation") or {}
    if validation and validation.get("checked_at") != validation.get("used_at") \
            and not validation.get("revalidated"):
        findings.append({"kind": "stale-validation",
                         "checked_at": validation.get("checked_at"),
                         "used_at": validation.get("used_at"),
                         "why": "the object changed between the check and the use"})
    if call.get("delegated_from") is not None:
        parent = call.get("delegated_from")
        parent = parent if isinstance(parent, dict) else {}
        widened = _set(call.get("granted_capabilities")) - _set(parent.get("granted_capabilities"))
        widened_ops = (_set(call.get("authorized_operations"))
                       - _set(parent.get("authorized_operations")))
        if widened or widened_ops:
            findings.append({"kind": "delegation-widens",
                             "capabilities": sorted(widened),
                             "operations": sorted(widened_ops),
                             "why": "a delegated call may add caveats, never rights"})
    if call.get("encoded") and boundary in ("model-tool", "agent-execution") \
            and not call.get("decode_policy"):
        findings.append({"kind": "encoded-instruction",
                         "why": "an encoded payload reaches a privileged component undecoded"})
    return {"format": FORMAT, "boundary": boundary,
            "decision": "deny" if findings else "allow",
            "findings": findings,
            "why": ("every check found the evidence it required" if not findings
                    else "the receiving component has to assess authority independently")}


def classify(outcome):
    """Attempted, unauthorized effect, disclosure — three different rows."""
    outcome = outcome if isinstance(outcome, dict) else {}
    attempted = bool(outcome.get("attempted"))
    effect = bool(outcome.get("effect"))
    disclosure = bool(outcome.get("disclosure"))
    if disclosure:
        kind = "disclosure"
    elif effect:
        kind = "unauthorized-effect"
    elif attempted:
        kind = "attempted-only"
    else:
        kind = "safe"
    return {"format": FORMAT, "outcome": kind, "attempted": attempted,
            "effect": effect, "disclosure": disclosure,
            "why": "a proposed call is not an effect; an effect is not a disclosure"}
