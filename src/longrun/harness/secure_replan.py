#!/usr/bin/env python3
"""Secure replan — an agent may report what failed, not dictate the repair.

Source: arXiv:2611.24839, "Kaer: Security-Aware Replanning for Multi-Agent
Systems" (round 150). An orchestrator that revises its plan from agent feedback
lets a malicious agent embed instructions in that feedback
(`security_replanning_2611.24839.txt:67`, `:69`). Kaer narrows the feedback to a
fixed vocabulary of failure conditions, changes the plan only through
deterministic operators, and re-validates every revised plan
(`:71`, `:73`).

  * **the planner sees templates, not text**: an agent reports one of twelve
    conditions and suggests operators; the planner chooses
    (`:352`, `:466`).
  * **seven operators, and only pending subtasks**: re-execute, revise,
    rescope, reassign, insert, prune, rewire (`:396`, `:427`).
  * **a plan is valid only if four conditions hold**, and a capability outside
    the task policy needs an explicit user grant (`:383`, `:417`).
  * **measured**: security 92.3% and 88.0% against 69.8%/80.4% for ControlValve
    and 35.0%/47.8% for Magentic-One, with higher benign utility than
    ControlValve (`:96`, `:99`).
  * **the residual vector is the success path**: attacks that embed an
    instruction in a successful output reach a downstream agent, and an
    output check raises the defence rate from 86.6%/87.0% to 96.8% (`:103`,
    `:823`).
  * **the remaining attack is constraint, not prevention**: a replayed failure
    report can still induce a lawful repair, bounded by the repair budget
    (`:1068`, `:1072`).

  * `apply(plan, operators)` — the deterministic operator sequence.
  * `validate(plan, record)` — the four conditions plus the grant rule.
  * `templates()` — the failure vocabulary and its suggested resolutions.
  * `repair(record)` — budget, rejection limit and the accepted revision.
  * `close_out(record)` — what an agent may report on each channel.
  * `exposure(record)` — the data path vs the replanning path.
  * `validation_effect(record)` — the output check's security and utility change.
  * `audit(record)` — the six misreadings the paper names.
  * `advise(profile)` — map a harness profile onto the paper's failure modes.

Pure: plans, policies and close-outs in; validity and verdicts out.
"""
from __future__ import annotations

FORMAT = "longrun-secure-replan/1"

OPERATORS = ("re-execute", "revise-directive", "rescope", "reassign",
             "insert", "prune", "rewire")
FAILURE_CONDITIONS = (
    "endpoint-transient-fault", "endpoint-access-denied", "no-close-out",
    "directive-underspecified", "directive-incorrect", "capability-not-granted",
    "input-artifact-absent", "input-lacks-datum", "upstream-input-contradicted",
    "information-not-found", "constraints-unsatisfiable", "result-uncorroborated",
    "budget-exhausted",
)
RESOLUTIONS = {
    "endpoint-transient-fault": ("re-execute", "insert+rewire", "revise-directive"),
    "endpoint-access-denied": ("revise-directive", "rescope", "reassign", "insert+rewire"),
    "no-close-out": ("re-execute", "reassign", "insert+rewire"),
    "directive-underspecified": ("revise-directive", "insert+rewire", "reassign"),
    "directive-incorrect": ("revise-directive", "rescope", "reassign", "prune"),
    "capability-not-granted": ("rescope", "reassign", "insert+rewire"),
    "input-artifact-absent": ("rewire", "insert+rewire", "revise-directive"),
    "input-lacks-datum": ("insert+rewire", "revise-directive", "prune"),
    "upstream-input-contradicted": ("insert+rewire", "revise-directive", "reassign"),
    "information-not-found": ("revise-directive", "insert+rewire", "reassign", "rescope"),
    "constraints-unsatisfiable": ("revise-directive", "insert+rewire"),
    "result-uncorroborated": ("insert+rewire", "revise-directive", "re-execute"),
    "budget-exhausted": ("re-execute", "revise-directive", "insert+rewire"),
}


def _subtasks(plan):
    return [dict(s) for s in ((plan or {}).get("subtasks") or [])]


def _num(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def apply(plan, operators):
    """Apply an operator sequence to pending subtasks only."""
    tasks = _subtasks(plan)
    completed = int((plan or {}).get("completed") or 0)
    errors = []
    for op in operators or []:
        o = op or {}
        name = str(o.get("op") or "")
        index = o.get("index")
        if name not in OPERATORS:
            errors.append({"op": name, "reason": "unknown-operator"})
            continue
        if index is not None and not isinstance(index, int):
            errors.append({"op": name, "reason": "bad-index"})
            continue
        if index is not None and index < completed:
            errors.append({"op": name, "reason": "targets-completed"})
            continue
        if index is not None and not 0 <= index < len(tasks):
            errors.append({"op": name, "reason": "out-of-range"})
            continue
        if name == "re-execute":
            continue
        if name == "revise-directive":
            tasks[index]["directive"] = str(o.get("directive") or "")
        elif name == "rescope":
            tasks[index]["capabilities"] = list(o.get("capabilities") or [])
        elif name == "reassign":
            tasks[index]["agent"] = str(o.get("agent") or "")
            tasks[index]["capabilities"] = list(o.get("capabilities") or [])
        elif name == "insert":
            new = dict(o.get("subtask") or {})
            tasks.insert(index, new)
        elif name == "prune":
            tasks.pop(index)
        elif name == "rewire":
            source = o.get("source")
            if not isinstance(source, int) or not source < index:
                errors.append({"op": name, "reason": "bad-dependency"})
                continue
            needs = list(tasks[index].get("needs") or [])
            if o.get("remove") is True:
                needs = [n for n in needs if n != source]
            elif source not in needs:
                needs.append(source)
            tasks[index]["needs"] = needs
    if not tasks:
        errors.append({"op": "sequence", "reason": "empty-plan"})
    return {"format": FORMAT, "plan": {"subtasks": tasks,
                                       "completed": completed},
            "errors": errors,
            "verdict": "repair-applied" if not errors else "repair-rejected"}


def validate(plan, record):
    """The four validity conditions and the explicit-grant rule."""
    r = record or {}
    registry = r.get("registry") or {}
    task_policy = set(r.get("task_policy") or [])
    grants = r.get("grants") or {}
    tasks = _subtasks(plan)
    violated = []
    for position, task in enumerate(tasks):
        agent = str(task.get("agent") or "")
        offered = set((registry.get(agent) or {}).get("capabilities") or [])
        capabilities = set(task.get("capabilities") or [])
        if not capabilities <= offered:
            violated.append({"subtask": position, "condition": "a-capability-not-offered"})
        granted = set(grants.get(str(position)) or [])
        if not capabilities <= (task_policy | granted):
            violated.append({"subtask": position, "condition": "b-capability-outside-policy"})
        for source in task.get("needs") or []:
            if not isinstance(source, int) or source >= position:
                violated.append({"subtask": position, "condition": "c-bad-dependency"})
                continue
            producer = str(tasks[source].get("agent") or "")
            allowed = set((registry.get(producer) or {}).get("allows") or [])
            if agent not in allowed:
                violated.append({"subtask": position, "condition": "c-output-not-allowed"})
        if position < len(tasks) - 1 and not task.get("used_later", True):
            violated.append({"subtask": position, "condition": "d-output-unused"})
    return {"format": FORMAT, "violated": violated, "subtasks": len(tasks),
            "verdict": "valid" if not violated else "invalid"}


def templates():
    """The failure vocabulary, each with its ordered suggested resolution."""
    return {"format": FORMAT,
            "conditions": [{"condition": name,
                            "suggested": list(RESOLUTIONS[name])}
                           for name in FAILURE_CONDITIONS],
            "count": len(FAILURE_CONDITIONS),
            "verdict": "vocabulary-fixed"}


def repair(record):
    """Spend one unit of the repair budget and accept a valid revision."""
    r = record or {}
    budget = int(r.get("budget") or 0)
    used = int(r.get("used") or 0)
    streak = int(r.get("consecutive_rejections") or 0)
    limit = int(r.get("rejection_limit") or 3)
    if used >= budget:
        return {"format": FORMAT, "verdict": "budget-exhausted"}
    if streak >= limit:
        return {"format": FORMAT, "verdict": "terminated-rejections"}
    conditions = [str(c) for c in (r.get("conditions") or [])]
    unknown = [c for c in conditions if c not in FAILURE_CONDITIONS]
    if unknown or not conditions:
        return {"format": FORMAT, "verdict": "no-template",
                "unknown": unknown}
    result = apply(r.get("plan") or {}, r.get("operators") or [])
    if result["errors"]:
        return {"format": FORMAT, "verdict": "repair-rejected",
                "errors": result["errors"], "used": used + 1}
    check = validate(result["plan"], r)
    if check["violated"]:
        return {"format": FORMAT, "verdict": "repair-rejected",
                "violated": check["violated"], "used": used + 1}
    return {"format": FORMAT, "verdict": "repair-accepted",
            "plan": result["plan"], "used": used + 1,
            "conditions": conditions}


def close_out(record):
    """A success carries an output; a failure names vocabulary conditions."""
    r = record or {}
    outcome = str(r.get("outcome") or "")
    if outcome == "success":
        if not r.get("output"):
            return {"format": FORMAT, "verdict": "success-without-output"}
        return {"format": FORMAT, "channel": "data",
                "verdict": "success-accepted"}
    if outcome == "failure":
        conditions = [str(c) for c in (r.get("conditions") or [])]
        if not conditions:
            return {"format": FORMAT, "verdict": "failure-without-condition"}
        unknown = [c for c in conditions if c not in FAILURE_CONDITIONS]
        if unknown:
            return {"format": FORMAT, "verdict": "condition-not-in-vocabulary",
                    "unknown": unknown}
        return {"format": FORMAT, "channel": "replanning",
                "conditions": sorted(set(conditions)),
                "verdict": "failure-accepted"}
    return {"format": FORMAT, "verdict": "unknown-outcome"}


def exposure(record):
    """Which channel a close-out policy exposes, and how much."""
    r = record or {}
    policy = str(r.get("policy") or "agent-choice")
    data = _num(r.get("data_rate"))
    replanning = _num(r.get("replanning_rate"))
    if data is None or replanning is None:
        return {"format": FORMAT, "verdict": "insufficient-input"}
    if policy == "always-success":
        total, channel = data, "data"
    elif policy == "always-failure":
        total, channel = replanning, "replanning"
    else:
        total, channel = max(data, replanning), (
            "data" if data >= replanning else "replanning")
    return {"format": FORMAT, "policy": policy, "rate": total,
            "channel": channel,
            "verdict": "data-path-dominates" if channel == "data"
            else "replanning-path-dominates"}


def validation_effect(record):
    """The output check's change in blocked attacks and in benign utility."""
    r = record or {}
    before = _num(r.get("before"))
    after = _num(r.get("after"))
    utility_before = _num(r.get("utility_before"))
    utility_after = _num(r.get("utility_after"))
    if before is None or after is None:
        return {"format": FORMAT, "verdict": "insufficient-input"}
    delta = after - before
    utility = (None if utility_before is None or utility_after is None
               else utility_after - utility_before)
    return {"format": FORMAT, "defence_before": before,
            "defence_after": after, "delta": delta, "utility_delta": utility,
            "verdict": "check-helps" if delta > 0 else "check-does-not-help"}


def audit(record):
    """The six misreadings the paper names, each as a finding."""
    r = record or {}
    findings = []
    if r.get("planner_reads_free_text") is True:
        findings.append({"kind": "planner-reads-free-text",
                         "why": "free text lets an agent dictate the repair"})
    if r.get("repair_is_a_model_plan") is True:
        findings.append({"kind": "repair-is-a-model-plan",
                         "why": "an arbitrary plan can rebuild what the policy forbids"})
    if r.get("no_policy_check_on_revision") is True:
        findings.append({"kind": "no-policy-check-on-revision",
                         "why": "the revised plan is the one that executes"})
    if r.get("success_not_verified") is True:
        findings.append({"kind": "success-not-verified",
                         "why": "most residual attacks travel the success path"})
    if r.get("completed_subtasks_mutable") is True:
        findings.append({"kind": "completed-subtasks-mutable",
                         "why": "rewriting completed work destroys the evidence"})
    if r.get("unbounded_repair_budget") is True:
        findings.append({"kind": "unbounded-repair-budget",
                         "why": "a replayed report can loop without a budget"})
    if not findings:
        findings.append({"kind": "audit-conditions-met"})
    return {"format": FORMAT, "findings": findings, "verdict": "audit-complete"}


def advise(profile):
    """Map a harness profile onto the paper's failure modes."""
    p = profile or {}
    have = {str(k) for k, v in p.items() if v}
    checks = (
        ("narrows_feedback_to_a_vocabulary", "passes_agent_text_to_the_planner",
         "narration is an instruction channel"),
        ("applies_fixed_repair_operators", "lets_a_model_rewrite_the_plan",
         "an unconstrained rewrite can rebuild a forbidden plan"),
        ("revalidates_every_revision", "checks_only_the_initial_plan",
         "the initial policy does not bind the revision"),
        ("requires_a_grant_for_new_capability", "expands_scope_silently",
         "a repair is not an authorisation"),
        ("verifies_success_close_outs", "trusts_a_done_message",
         "a silent failure looks like a success"),
        ("bounds_the_repair_budget", "retries_without_a_limit",
         "a repeating report can spend the task"),
        ("keeps_completed_work_immutable", "rewrites_completed_subtasks",
         "the evidence of what happened is lost"),
    )
    findings = []
    for key, kind, why in checks:
        if key not in have:
            findings.append({"kind": kind, "why": why})
    return {"format": FORMAT, "findings": findings}
