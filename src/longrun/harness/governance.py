#!/usr/bin/env python3
"""Tool governance — ready, waiting, or forbidden, derived from an ontology.

Source: arXiv:2611.06682, "SecureGARD: Dynamic Ontology-Guided Governance for
Secure Tool-Using LLM Agents" (round 117). A tool call is a consequential action,
so an injected instruction becomes an execution-security problem. Existing
defenses constrain calls, trajectories or flows while leaving action semantics,
state dependencies and evidence relations implicit.

The paper grounds heterogeneous calls in one semantic representation and derives
a deterministic decision from an executable ontology plus the episode's task
state:

  * READY      — every obligation the action requires is already satisfied;
  * WAITING    — an obligation is unmet but recoverable: bounded replanning is
                 allowed, and it must NOT widen the authorization boundary;
  * FORBIDDEN  — the call violates the ontology or the authorization boundary.

This module decides over caller-supplied declarations. It does not read a model's
intent and does not execute anything: a `waiting` answer is a list of obligations
to satisfy, a `forbidden` answer names the rule that stopped the call.

Pure: ontology + state + call in, decision out.
"""
from __future__ import annotations

FORMAT = "longrun-tool-governance/1"
DECISIONS = ("ready", "waiting", "forbidden")


def check_ontology(ontology):
    """Consistency of the declarations, before any call is judged."""
    ont = ontology if isinstance(ontology, dict) else {}
    problems = []
    grants = {}
    for action, row in ont.items():
        if action in ("recoverable", "protected"):
            continue
        row = row if isinstance(row, dict) else {}
        for need in row.get("requires") or []:
            grants.setdefault(need, set())
        for name in row.get("grants") or []:
            grants.setdefault(name, set()).add(action)
        for bad in row.get("forbids") or []:
            if bad in (row.get("grants") or []):
                problems.append({"kind": "grants-and-forbids", "action": action, "obligation": bad})
    for obligation in ont.get("protected") or []:
        if grants.get(obligation):
            problems.append({"kind": "protected-obligation-granted",
                             "obligation": obligation, "actions": sorted(grants[obligation])})
    ungrantable = sorted(o for o, acts in grants.items() if not acts)
    return {"format": FORMAT, "problems": problems, "ungrantable": ungrantable,
            "verdict": "inconsistent" if problems else "consistent"}


def decide(call, ontology, state):
    """Judge one call against the ontology and the episode state."""
    ont = ontology if isinstance(ontology, dict) else {}
    st = state if isinstance(state, dict) else {}
    call = call if isinstance(call, dict) else {}
    action = call.get("action")
    row = ont.get(action)
    if not isinstance(row, dict):
        return {"format": FORMAT, "decision": "forbidden", "action": action,
                "why": "the action is not declared in the ontology",
                "missing": [], "recoverable": False}

    done = set(st.get("done") or [])
    granted = set(st.get("grants") or [])
    flags = set(st.get("flags") or [])

    for condition in row.get("forbids") or []:
        if condition in flags:
            return {"format": FORMAT, "decision": "forbidden", "action": action,
                    "why": "condition %r holds" % condition,
                    "missing": [], "recoverable": False}

    missing = [need for need in (row.get("requires") or []) if need not in done]
    if missing:
        recoverable = [m for m in missing if m in set(ont.get("recoverable") or [])]
        decision = "waiting" if len(recoverable) == len(missing) else "forbidden"
        return {"format": FORMAT, "decision": decision, "action": action,
                "why": "unmet obligations: %s" % ", ".join(missing),
                "missing": missing, "recoverable": decision == "waiting"}

    needs_grant = row.get("grant_required")
    if needs_grant and needs_grant not in granted:
        return {"format": FORMAT, "decision": "forbidden", "action": action,
                "why": "the call needs authorization %r, which the episode does not hold" % needs_grant,
                "missing": [needs_grant], "recoverable": False}

    return {"format": FORMAT, "decision": "ready", "action": action,
            "why": "all obligations satisfied", "missing": [], "recoverable": False}
