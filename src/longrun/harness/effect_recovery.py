#!/usr/bin/env python3
"""Ambiguous-outcome recovery — what a timeout actually lets you re-issue safely.

Source: arXiv:2610.41453, "Evidence-Guided Recovery for AI Agents with Ambiguous
Tool Outcomes and Partial Execution" (round 116). A tool timeout leaves the agent
unable to say whether an action failed, committed, or is still in flight, while
other steps have already completed. The paper's answer is not a retry policy but
an adjudication over what public evidence supports:

  * the set of states COMPATIBLE with the evidence (not one assumed state);
  * an admissibility check for every proposed next action — key expiry,
    authorization timing, dependencies, residual effects;
  * a terminal certificate that separates "the goal is satisfied" from
    "publicly supported safe completion", and keeps unknown/handoff explicit.

The scope is declared provider capabilities, never a claim of arbitrary
third-party exactly-once execution. A non-idempotent action whose evidence
allows ``committed`` or ``in-flight`` is NEVER re-issued here: the recommendation
is verify-then-decide or compensate.

`adjudicate()` is the LIVE entry point. `api_v02._recovery_escalation` builds
its record from the run trace and `registry.TOOL_EFFECTS` — the obligation is the
proposed action on one object, the evidence is every ambiguous attempt on that
object plus any declared read-back of it, and the proposed next action is
`retry` — then upgrades an automatic approval when the adjudication proves the
retry would duplicate the effect. Escalation only: an idempotent action, a
cleanly rejected attempt, or an untyped tool is left to the existing policy.

Pure: record in, adjudication out.
"""
from __future__ import annotations

FORMAT = "longrun-effect-recovery/1"
STATES = ("not-started", "in-flight", "committed")
CERTS = ("goal-satisfied", "safe-stop", "unsafe", "incomplete")
EVIDENCE_KINDS = ("none", "ack", "timeout", "rejected", "readback-committed",
                  "readback-absent", "handoff")


def _caps(capabilities, action):
    cap = (capabilities or {}).get(action)
    return cap if isinstance(cap, dict) else {}


def compatible(obligation, evidence, capabilities):
    """Every state the public evidence still allows for one obligation.

    Evidence is the list of events about this obligation, in order. The result is
    never narrowed by optimism: only a positive read-back pins ``committed``, and
    only a provider that can read after write pins ``not-started``.
    """
    cap = _caps(capabilities, obligation.get("action"))
    states = set(STATES)
    kinds = [e.get("kind") for e in (evidence or []) if isinstance(e, dict)]
    for kind in kinds:
        if kind == "readback-committed":
            states = {"committed"}
        elif kind == "readback-absent":
            if cap.get("read_after_write"):
                states = {"not-started"}
        elif kind == "rejected":
            states = {"not-started"}
        elif kind == "ack":
            states.discard("not-started")
        elif kind == "timeout":
            states = set(STATES) if not cap.get("atomic_abort") else {"not-started"}
        elif kind == "handoff":
            states = set(STATES)
    return sorted(states)


def _recommendation(obligation, states, cap, now):
    if states == ["committed"]:
        return "satisfied"
    deadline = obligation.get("deadline")
    if isinstance(deadline, (int, float)) and isinstance(now, (int, float)) and now > deadline:
        return "expired"
    if states == ["not-started"]:
        return "retry-safe"
    if cap.get("idempotent"):
        return "retry-safe"
    return "verify" if "committed" in states else "retry-safe"


def adjudicate(record):
    """States, recommendations, findings and one terminal certificate."""
    rec = record or {}
    caps = rec.get("capabilities") or {}
    obligations = [o for o in (rec.get("obligations") or []) if isinstance(o, dict) and o.get("id")]
    evidence = [e for e in (rec.get("evidence") or []) if isinstance(e, dict)]
    now = rec.get("now")
    known = {o["id"] for o in obligations}
    findings = []
    rows = []

    by_obligation = {}
    for e in evidence:
        oid = e.get("obligation")
        if oid not in known:
            findings.append({"kind": "evidence-for-unknown-obligation", "obligation": oid})
            continue
        if e.get("kind") not in EVIDENCE_KINDS:
            findings.append({"kind": "invalid-evidence-kind", "value": e.get("kind")})
            continue
        by_obligation.setdefault(oid, []).append(e)

    states_by_id = {}
    proposed = {p.get("obligation"): p.get("action") for p in (rec.get("proposed") or [])
                if isinstance(p, dict)}
    for o in obligations:
        cap = _caps(caps, o.get("action"))
        states = compatible(o, by_obligation.get(o.get("id"), []), caps)
        states_by_id[o["id"]] = states
        rec_kind = _recommendation(o, states, cap, now)
        wants = proposed.get(o["id"])
        if rec_kind == "expired" and wants == "retry":
            findings.append({"kind": "expired-authorization", "obligation": o["id"],
                             "why": "the key or window expired; the safe act is to stop"})
        if wants == "retry" and not cap.get("idempotent") and set(states) & {"committed", "in-flight"}:
            findings.append({"kind": "retry-would-duplicate", "obligation": o["id"],
                             "why": "non-idempotent action may have committed; re-issue duplicates it"})
            rec_kind = "verify"
        if wants and wants not in ("retry", "verify", "compensate", "stop"):
            findings.append({"kind": "invalid-proposal", "value": wants})
        for dep in o.get("requires") or []:
            if dep not in known:
                findings.append({"kind": "dangling-dependency", "obligation": o["id"], "dep": dep})
            elif states_by_id.get(dep) != ["committed"]:
                findings.append({"kind": "blocked-by-unproven-dependency", "obligation": o["id"],
                                 "dep": dep, "dep_states": states_by_id.get(dep)})
        rows.append({"id": o["id"], "action": o.get("action"), "states": states,
                     "next": rec_kind})

    owned = {o.get("action") for o in obligations}
    for r in rec.get("residual") or []:
        if isinstance(r, dict) and r.get("action") not in owned:
            findings.append({"kind": "unowned-residue", "action": r.get("action")})

    cert = _certificate(rows, findings)
    return {"format": FORMAT, "obligations": rows, "findings": findings,
            "certificate": cert, "count": len(rows)}


def _certificate(rows, findings):
    if any(f["kind"] in ("retry-would-duplicate", "blocked-by-unproven-dependency",
                         "unowned-residue") for f in findings):
        return "unsafe"
    if rows and all(r["next"] == "satisfied" for r in rows):
        return "goal-satisfied"
    if all(r["next"] in ("satisfied", "retry-safe", "expired") for r in rows):
        return "safe-stop"
    return "incomplete"


def trace_safety(trace, capabilities):
    """Two committed effects for one non-idempotent action is a duplicate, not a retry."""
    seen = {}
    findings = []
    for i, ev in enumerate(trace or []):
        if not isinstance(ev, dict) or ev.get("kind") != "committed":
            continue
        action = ev.get("action")
        if _caps(capabilities, action).get("idempotent"):
            continue
        if action in seen:
            findings.append({"kind": "duplicate-effect", "action": action,
                             "first": seen[action], "second": i})
        else:
            seen[action] = i
    return {"format": FORMAT, "findings": findings,
            "verdict": "duplicate" if findings else "clean"}
