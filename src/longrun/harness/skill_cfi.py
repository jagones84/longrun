#!/usr/bin/env python3
"""Skill CFI — hold a skill to its control skeleton whatever the model proposes.

Source: arXiv:2611.24185, "Control-Flow Integrity for Agent Skills" (round 148).
A skill moves a procedure into prompt text, and the model decides at runtime
whether each step runs in its reasoning (R1), a mediated tool call (R2), a
bundled helper (R3a) or a generated script (R3b)
(`skill_control_flow_integrity_2611.24185.txt:16`, `:25`, `:89`). The control
skeleton survives, but enforceability depends on where a step runs
(`:136`, `:139`).

  * **a violation can use only lawful operations**: overwriting the source is a
    lawful step once the draft is validated and the user agrees, so a permission
    allowlist admits the violation (`:55`, `:57`).
  * **regime migration evades a monitor**: a model can claim in R1 that a check
    passed, or move a protected effect into an inline script (`:288`, `:295`).
  * **two principles close it**: only correlated results from trusted
    interfaces establish prerequisites (non-substitutability of evidence), and
    every channel that can produce a protected effect is mediated (boundary
    closure) (`:295`, `:298`).
  * **the observational limit**: a boundary monitor can enforce a property only
    if no two traces with the same projection demand opposite decisions
    (`:302`, `:305`).
  * **measured**: 240 of 240 in-vocabulary violations blocked before dispatch
    against 80 of 80 admitted by an allowlist; a stateless policy must admit all
    160, a result-blind one 59, SkillCFI none (`:156`, `:679`, `:711`).
  * **next-step feedback raises recovery from 21% to 65%**, and the gate takes
    about 2% of task time (`:48`, `:787`, `:783`).

  * `skeleton(row)` — the graph a skill compiles to, and its integrity.
  * `enforceable(row)` — enforce, guidance or unsupported.
  * `dispositions(rows)` — a whole skill's obligation plan.
  * `admit(row)` — the C/S/R/F check before dispatch.
  * `result(row)` — a correlated result and its captures.
  * `violation(row)` — unexpected action, invalid transition, invalid termination.
  * `refusal(row)` — code, layer, missing evidence and the next legal steps.
  * `recovery(rows)` — bare, basic and next-step refusal messages.
  * `audit(record)` — the six misreadings the paper names.
  * `advise(profile)` — map a harness profile onto the paper's failure modes.

Pure: a compiled contract and boundary events in; admit/refuse and verdicts out.
"""
from __future__ import annotations

FORMAT = "longrun-skill-cfi/1"

LAYERS = ("C", "S", "R", "F")
VIOLATIONS = ("unexpected-action", "invalid-transition", "invalid-termination")
DISPOSITIONS = ("enforce", "guidance", "unsupported")


def _guard_ok(guard, fact, counters):
    if not guard:
        return True
    want = guard.get("fact")
    if want is not None and fact != want:
        return False
    counter = guard.get("counter") or {}
    if counter:
        value = int(counters.get(counter.get("name"), 0))
        if "at" in counter and value != int(counter["at"]):
            return False
        if "below" in counter and value >= int(counter["below"]):
            return False
    return True


def skeleton(row):
    """The compiled graph: unique steps, resolvable edges, a reachable exit."""
    r = row or {}
    steps = [s or {} for s in (r.get("steps") or [])]
    names = [str(s.get("name") or "") for s in steps]
    duplicates = sorted({n for n in names if n and names.count(n) > 1})
    unnamed = [i for i, n in enumerate(names) if not n]
    start = str(r.get("start") or "")
    exits = [str(e) for e in (r.get("exits") or [])]
    edges = [e or {} for e in (r.get("edges") or [])]
    dangling = [str(e.get("to")) for e in edges
                if str(e.get("to")) not in names
                and str(e.get("to")) not in exits]
    reachable = {start} if start in names else set()
    changed = True
    while changed:
        changed = False
        for edge in edges:
            if str(edge.get("from")) in reachable:
                target = str(edge.get("to"))
                if target not in reachable:
                    reachable.add(target)
                    changed = True
    unreachable = [n for n in names if n not in reachable]
    exit_edges = [str(e.get("from")) for e in edges if str(e.get("to")) in exits]
    reasons = []
    if duplicates:
        reasons.append("duplicate-steps")
    if unnamed:
        reasons.append("unnamed-steps")
    if dangling:
        reasons.append("dangling-edges")
    if not exits:
        reasons.append("no-exit")
    if start not in names:
        reasons.append("no-start")
    if unreachable:
        reasons.append("unreachable-steps")
    if exits and not exit_edges:
        reasons.append("unreachable-exit")
    return {"format": FORMAT, "steps": len(steps), "edges": len(edges),
            "duplicates": duplicates, "dangling": dangling,
            "unreachable": unreachable, "reasons": reasons,
            "verdict": "skeleton-valid" if not reasons else "skeleton-invalid"}


def enforceable(row):
    """Where a step runs decides whether its obligation can be enforced."""
    r = row or {}
    effect = r.get("effect_at_boundary") is True
    evidence = r.get("evidence_at_boundary") is True
    mandatory = r.get("mandatory") is True
    if effect and evidence:
        return {"format": FORMAT, "disposition": "enforce",
                "verdict": "enforceable"}
    if effect and not evidence and not mandatory:
        return {"format": FORMAT, "disposition": "guidance",
                "verdict": "guidance-only"}
    if not effect:
        return {"format": FORMAT, "disposition": "unsupported",
                "verdict": "unenforceable-regime-migration"}
    return {"format": FORMAT, "disposition": "unsupported",
            "verdict": "unenforceable-missing-evidence"}


def dispositions(rows):
    """A skill's whole obligation plan; a mandatory gap rejects the skill."""
    out = []
    for row in rows or []:
        r = row or {}
        result = enforceable(r)
        out.append({"id": str(r.get("id") or ""),
                    "mandatory": r.get("mandatory") is True,
                    "disposition": result["disposition"],
                    "verdict": result["verdict"]})
    rejected = [o["id"] for o in out
                if o["mandatory"] and o["disposition"] == "unsupported"]
    return {"format": FORMAT, "obligations": out,
            "enforced": sum(1 for o in out if o["disposition"] == "enforce"),
            "guidance": sum(1 for o in out if o["disposition"] == "guidance"),
            "unsupported": sum(1 for o in out if o["disposition"] == "unsupported"),
            "rejected": rejected,
            "verdict": "compile-rejected" if rejected else "compile-accepted"}


def _occurrences(contract, interface):
    return [o or {} for o in (contract.get("occurrences") or [])
            if str((o or {}).get("interface")) == interface]


def _plans(contract, state, interface, args):
    node = str(state.get("node") or "")
    plans = []
    for occurrence in _occurrences(contract, interface):
        name = str(occurrence.get("name") or "")
        for edge in contract.get("edges") or []:
            e = edge or {}
            if str(e.get("from")) != node or str(e.get("to")) != name:
                continue
            if not _guard_ok(e.get("guard"), state.get("fact"),
                             state.get("counters") or {}):
                continue
            captures = state.get("captures") or {}
            requires = [str(x) for x in (occurrence.get("requires") or [])]
            if any(req not in captures for req in requires):
                continue
            bound = occurrence.get("args") or {}
            if any(args.get(k) != captures.get(v) for k, v in bound.items()):
                continue
            plans.append({"occurrence": occurrence, "edge": e})
    return plans


def admit(row):
    """The four-layer check before dispatch: C, S, R, F."""
    r = row or {}
    state = r.get("state") or {}
    request = r.get("request") or {}
    contract = r.get("contract") or {}
    interface = str(request.get("interface") or "")
    args = request.get("args") or {}
    if state.get("pending") or state.get("term"):
        return {"format": FORMAT, "decision": "refuse", "layer": "C",
                "reason": "in-flight-or-terminated", "verdict": "refused"}
    if interface not in (contract.get("interfaces") or {}):
        return {"format": FORMAT, "decision": "refuse", "layer": "S",
                "reason": "unexpected-action", "verdict": "refused"}
    plans = _plans(contract, state, interface, args)
    if not plans:
        return {"format": FORMAT, "decision": "refuse", "layer": "F",
                "reason": "invalid-transition", "verdict": "refused"}
    if len(plans) > 1:
        return {"format": FORMAT, "decision": "refuse", "layer": "S",
                "reason": "ambiguous-handler", "verdict": "refused"}
    plan = plans[0]
    occurrence = plan["occurrence"]
    edge = plan["edge"]
    counters = dict(state.get("counters") or {})
    update = edge.get("counter") or {}
    if update:
        counters[update.get("name")] = int(counters.get(update.get("name"), 0)) + 1
    captures = dict(state.get("captures") or {})
    for reg in occurrence.get("invalidates") or []:
        captures.pop(str(reg), None)
    new_state = {"node": "req:" + str(occurrence.get("name")),
                 "fact": None, "counters": counters, "captures": captures,
                 "pending": str(request.get("call_id") or ""), "term": None}
    return {"format": FORMAT, "decision": "allow", "layer": "F",
            "occurrence": str(occurrence.get("name")), "state": new_state,
            "dispatch": args, "verdict": "admitted"}


def result(row):
    """A correlated result: identity, decode, captures, then exit closure."""
    r = row or {}
    state = r.get("state") or {}
    contract = r.get("contract") or {}
    call_id = str(r.get("call_id") or "")
    if state.get("pending") != call_id:
        return {"format": FORMAT, "verdict": "evidence-failure",
                "reason": "call-id-mismatch"}
    if r.get("decoder_ok") is False:
        return {"format": FORMAT, "verdict": "evidence-failure",
                "reason": "decode-failed"}
    occurrence_name = str(state.get("node") or "").replace("req:", "")
    occurrence = next((o or {} for o in (contract.get("occurrences") or [])
                       if str((o or {}).get("name")) == occurrence_name), {})
    interface = str(occurrence.get("interface") or "")
    outcomes = (contract.get("interfaces") or {}).get(interface) or []
    outcome = str(r.get("outcome") or "")
    if outcome not in outcomes:
        return {"format": FORMAT, "verdict": "evidence-failure",
                "reason": "unknown-outcome"}
    captures = dict(state.get("captures") or {})
    binding = (occurrence.get("binds") or {}).get(outcome) or {}
    for field, register in binding.items():
        if field in (r.get("captures") or {}):
            captures[str(register)] = (r.get("captures") or {})[field]
    new_state = {"node": "res:" + occurrence_name, "fact": outcome,
                 "counters": dict(state.get("counters") or {}),
                 "captures": captures, "pending": None, "term": None}
    for edge in contract.get("exit_edges") or []:
        e = edge or {}
        if str(e.get("from")) not in (occurrence_name, "res:" + occurrence_name):
            continue
        if not _guard_ok(e.get("guard"), outcome, new_state["counters"]):
            continue
        new_state["term"] = str(e.get("to"))
        break
    return {"format": FORMAT, "state": new_state, "outcome": outcome,
            "verdict": "accepted"}


def violation(row):
    """Classify a proposed request against the contract."""
    r = row or {}
    request = r.get("request") or {}
    contract = r.get("contract") or {}
    state = r.get("state") or {}
    admitted = admit(dict(r, request=request, contract=contract, state=state))
    if admitted["decision"] == "allow":
        return {"format": FORMAT, "kind": "none", "verdict": "lawful"}
    interface = str(request.get("interface") or "")
    if admitted.get("reason") == "unexpected-action":
        return {"format": FORMAT, "kind": "unexpected-action",
                "verdict": "violation"}
    if state.get("term"):
        return {"format": FORMAT, "kind": "invalid-termination",
                "verdict": "violation"}
    if interface in (contract.get("interfaces") or {}):
        return {"format": FORMAT, "kind": "invalid-transition",
                "verdict": "violation"}
    return {"format": FORMAT, "kind": "unexpected-action", "verdict": "violation"}


def refusal(row):
    """The structured payload a refusal returns, including the next steps."""
    r = row or {}
    state = r.get("state") or {}
    contract = r.get("contract") or {}
    request = r.get("request") or {}
    decision = admit(dict(r, state=state, contract=contract, request=request))
    if decision["decision"] == "allow":
        return {"format": FORMAT, "verdict": "not-refused"}
    enabled = []
    for occurrence in contract.get("occurrences") or []:
        o = occurrence or {}
        name = str(o.get("name") or "")
        if _plans(contract, state, str(o.get("interface") or ""), {}) or \
                any(str(e.get("from")) == state.get("node")
                    and str(e.get("to")) == name
                    for e in (contract.get("edges") or [])):
            enabled.append(name)
    missing = []
    for occurrence in contract.get("occurrences") or []:
        o = occurrence or {}
        for reg in o.get("requires") or []:
            if str(reg) not in (state.get("captures") or {}):
                missing.append(str(reg))
    return {"format": FORMAT, "code": decision.get("reason"),
            "layer": decision.get("layer"), "missing": sorted(set(missing)),
            "next": sorted(set(enabled)), "verdict": "refused-with-guidance"}


def recovery(rows):
    """Strict recovery after a target refusal, by refusal message."""
    arms = {}
    for row in rows or []:
        r = row or {}
        arm = str(r.get("arm") or "")
        if not arm:
            continue
        entry = arms.setdefault(arm, {"recovered": 0, "sessions": 0})
        entry["sessions"] += int(r.get("sessions") or 1)
        entry["recovered"] += int(r.get("recovered") or 0)
    if not arms:
        return {"format": FORMAT, "verdict": "no-sessions"}
    rates = {arm: (v["recovered"] / v["sessions"] if v["sessions"] else 0.0)
             for arm, v in arms.items()}
    best = max(rates, key=lambda k: (rates[k], k))
    return {"format": FORMAT, "arms": arms, "rates": rates, "best": best,
            "verdict": "next-step-helps" if rates.get("next-step", 0.0)
            > rates.get("bare", 0.0) else "no-next-step-gain"}


def audit(record):
    """The six misreadings the paper names, each as a finding."""
    r = record or {}
    findings = []
    if r.get("allowlist_as_cfi") is True:
        findings.append({"kind": "allowlist-is-not-cfi",
                         "why": "a violation can use only lawful operations"})
    if r.get("ignores_regime_migration") is True:
        findings.append({"kind": "regime-migration",
                         "why": "a protected step can move into reasoning or a script"})
    if r.get("trusts_model_claims") is True:
        findings.append({"kind": "evidence-from-model-claims",
                         "why": "only correlated results establish prerequisites"})
    if r.get("monitor_in_context") is True:
        findings.append({"kind": "monitor-in-context",
                         "why": "workflow state must live outside the model's context"})
    if r.get("runtime_model_monitor") is True:
        findings.append({"kind": "runtime-model-monitor",
                         "why": "a second model reads the same untrusted content"})
    if r.get("content_checks") is True:
        findings.append({"kind": "content-only",
                         "why": "a lawful call sequence can still carry flawed content"})
    if not findings:
        findings.append({"kind": "audit-conditions-met"})
    return {"format": FORMAT, "findings": findings}


def advise(profile):
    """Map a harness profile onto the paper's failure modes."""
    p = profile or {}
    have = {str(k) for k, v in p.items() if v}
    checks = (
        ("compiles_a_contract", "prompt_only_procedure",
         "the skeleton has to be explicit before it can be enforced"),
        ("checks_before_dispatch", "checks_after_execution",
         "a post-hoc monitor has already let the effect happen"),
        ("requires_correlated_evidence", "accepts_agent_claims",
         "a model can claim that a check passed"),
        ("mediates_every_effective_channel", "allows_inline_scripts",
         "regime migration moves a protected step out of view"),
        ("keeps_state_outside_the_model", "state_in_the_prompt",
         "workflow history must not be model-editable"),
        ("returns_the_next_legal_steps", "refuses_with_a_bare_error",
         "next-step feedback recovers most refusals"),
        ("rejects_unsupported_mandatory_obligations", "downgrades_to_guidance",
         "a mandatory obligation with no evidence is not enforceable"),
    )
    findings = []
    for key, kind, why in checks:
        if key not in have:
            findings.append({"kind": kind, "why": why})
    return {"format": FORMAT, "findings": findings}
