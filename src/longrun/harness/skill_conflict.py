#!/usr/bin/env python3
"""Cross-skill conflict — a call can be individually clean and jointly unsafe.

Source: arXiv:2610.35082, "CoSA: The Conflict of Skills Attack in Real-World LLM
Agent Ecosystems" (round 118). Conflict of Skills is the failure where an
artifact or an assessment produced for one purpose is reused downstream without
preserving the restrictions or authorization its new use needs. Checking each
Skill alone cannot see it.

The paper's four mechanisms (Section 3.2) are the vocabulary this module reports:
  security-context attenuation   the artifact arrives without its restrictions;
  semantic interface bridging    a differently typed artifact is accepted as if it were;
  semantic authority promotion   an assessment signal is treated as authorization;
  target/action binding drift    the action's target differs from the one the
                                  artifact was bound to.

Its harness guard (Section 3.4) is two checks before a consequential action —
information FLOW and authorization — with decisions ALLOW/BLOCK/CONFIRM/ERROR and
cached denials that persist until trusted evidence changes.

Deterministic: declarations in, conflicts and one decision out.
"""
from __future__ import annotations

FORMAT = "longrun-skill-conflict/1"
MECHANISMS = ("security-context-attenuation", "semantic-interface-bridging",
              "semantic-authority-promotion", "target-action-binding-drift")
CONSEQUENTIAL = ("externalize", "persist", "execute")
DECISIONS = ("allow", "block", "confirm", "error")


def _rows(skill, key):
    return [r for r in (skill or {}).get(key) or [] if isinstance(r, dict)]


def conflicts(pool):
    """Every cross-skill handoff that drops a restriction, a type or a binding."""
    findings = []
    skills = [s for s in pool or [] if isinstance(s, dict)]
    for producer in skills:
        for out in _rows(producer, "produces"):
            for consumer in skills:
                if consumer is producer:
                    continue
                for use in _rows(consumer, "consumes"):
                    if use.get("artifact") != out.get("artifact"):
                        continue
                    if out.get("kind") != use.get("kind"):
                        findings.append({"mechanism": "semantic-interface-bridging",
                                         "producer": producer.get("name"),
                                         "consumer": consumer.get("name"),
                                         "artifact": out.get("artifact"),
                                         "produced_kind": out.get("kind"),
                                         "consumed_kind": use.get("kind")})
                    dropped = [r for r in out.get("restrictions") or []
                               if r not in (use.get("preserves") or [])]
                    if dropped and use.get("action") in CONSEQUENTIAL:
                        findings.append({"mechanism": "security-context-attenuation",
                                         "producer": producer.get("name"),
                                         "consumer": consumer.get("name"),
                                         "dropped": dropped,
                                         "action": use.get("action")})
                    if out.get("kind") == "assessment" and use.get("as_authorization"):
                        findings.append({"mechanism": "semantic-authority-promotion",
                                         "producer": producer.get("name"),
                                         "consumer": consumer.get("name"),
                                         "artifact": out.get("artifact")})
                    if out.get("target") and use.get("target") and out["target"] != use["target"]:
                        findings.append({"mechanism": "target-action-binding-drift",
                                         "producer": producer.get("name"),
                                         "consumer": consumer.get("name"),
                                         "bound": out["target"], "used_on": use["target"]})
    risk = sorted({f["mechanism"] for f in findings})
    return {"format": FORMAT, "findings": findings, "mechanisms": risk,
            "count": len(findings),
            "verdict": "conflict" if findings else "clean"}


def guard(action, state, policy=None):
    """Flow and authorization before one consequential action.

    A denial is cached: it stays in force until evidence newer than the denial
    arrives (``state.evidence_epoch`` > ``state.denied_epoch``).
    """
    act = action or {}
    st = state or {}
    pol = policy or {}
    if st.get("denied_epoch") is not None and st.get("evidence_epoch", 0) <= st["denied_epoch"]:
        return {"format": FORMAT, "decision": "block", "flow": False, "auth": False,
                "why": "a cached denial is still in force; no trusted evidence changed since"}
    if act.get("action") not in CONSEQUENTIAL:
        return {"format": FORMAT, "decision": "allow", "flow": True, "auth": True,
                "why": "not a consequential action"}
    grants = set(st.get("grants") or [])
    missing = [r for r in act.get("restrictions") or [] if r not in grants]
    flow = not missing
    auth_ok = act.get("authorization") in set(st.get("approvals") or [])
    bound_ok = not act.get("target") or not act.get("authorized_target") \
        or act["target"] == act["authorized_target"]
    auth = auth_ok and bound_ok
    if flow and auth:
        return {"format": FORMAT, "decision": "allow", "flow": True, "auth": True,
                "why": "restrictions preserved and the action is authorized for this target"}
    if not flow and pol.get("confirm_on_flow"):
        return {"format": FORMAT, "decision": "confirm", "flow": False, "auth": auth,
                "missing": missing, "why": "the restriction is not held; ask before proceeding"}
    if not auth:
        return {"format": FORMAT, "decision": "block", "flow": flow, "auth": False,
                "missing": missing,
                "why": "no authorization for this action and target" if auth_ok
                else "the action carries no authorization"}
    return {"format": FORMAT, "decision": "block", "flow": False, "auth": True,
            "missing": missing, "why": "the artifact's restrictions are not preserved"}
