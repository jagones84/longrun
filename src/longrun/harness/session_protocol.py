#!/usr/bin/env python3
"""Session protocol — a rule in the prompt holds until something pushes against it.

Source: arXiv:2610.37461, "Concordat" (round 140). A consequential tool call is
usually governed by a sentence in the system prompt, followed only as reliably as
the model chooses (`concordat_typed_sessions_2610.37461.md:17`, `:20`). Concordat
treats the agent as an object whose interface is a finite-state protocol and
enforces it at run time: each turn offers only the tools legal in the current
state, and an illegal call is rejected before it has side effects (`:18`, `:149`).

  * **a protocol is `(S, A, s0, F, δ)`** and is well formed only if finals exist,
    finals allow nothing, every defined transition is non-empty, every state is
    reachable, and every state can still reach a final one (`:130`, `:137`).
  * **safe refinement is trace inclusion**: a subclass whose run, with its own
    extra steps erased, is not a run of the parent is rejected at definition
    time (`:211`, `:220`).
  * **budgets are linear resources**: a handoff splits the allowance and the
    child may not be unlimited where the parent is limited (`:191`, `:198`).
  * **the outcome is blind to the violation**: on τ-bench 8 of 13 tasks that
    broke the confirmation rule still received full reward (`:318`).
  * **pressure is the condition that breaks the rule**: 13 of 50 gpt-4.1 tasks
    and 29 of 128 Haiku task-runs changed data without an explicit yes; the
    governed agent changed none, at comparable task success (`:27`, `:305`).

  * `protocol(...)` — build and check the protocol.
  * `allowed(proto, state)` — the tools offered this turn.
  * `tick(proto, state, action, target)` — accept or reject, never mutate on reject.
  * `refines(parent, child)` — definition-time protocol-safe inheritance.
  * `split(budget, share)` / `charge(budget, usage)` — budgets as linear resources.
  * `compliance(runs)` — process compliance beside the outcome.
  * `pressure(rows)` — the standard arm against the governed arm under pressure.
  * `advise(profile)` — map a harness profile onto the paper's failure modes.

Pure: protocols and traces in; findings out.
"""
from __future__ import annotations

import math

FORMAT = "longrun-session-protocol/1"


def _key(state, action):
    return "%s|%s" % (state, action)


def protocol(states, actions, start, finals, delta):
    """Build a protocol and check well-formedness conditions (i)–(v)."""
    states = [str(s) for s in (states or [])]
    actions = [str(a) for a in (actions or [])]
    finals = [str(f) for f in (finals or [])]
    raw = {}
    for key, targets in (delta or {}).items():
        raw[str(key)] = [str(t) for t in (targets or [])]
    errors = []
    state_set, action_set, final_set = set(states), set(actions), set(finals)
    if not final_set:
        errors.append({"kind": "no-final-states"})
    if start not in state_set:
        errors.append({"kind": "start-not-in-states", "detail": str(start)})
    for final in finals:
        if final not in state_set:
            errors.append({"kind": "final-not-in-states", "detail": final})
    allowed_map = {s: [] for s in states}
    for key, targets in raw.items():
        head, _, action = key.partition("|")
        if head not in state_set or action not in action_set:
            errors.append({"kind": "transition-names-unknown",
                           "detail": key})
        if not targets:
            errors.append({"kind": "empty-transition", "detail": key})
        for target in targets:
            if target not in state_set:
                errors.append({"kind": "target-not-in-states", "detail": target})
        if head in allowed_map and action not in allowed_map[head]:
            allowed_map[head].append(action)
    for final in finals:
        if allowed_map.get(final):
            errors.append({"kind": "final-state-allows-actions",
                           "detail": final, "actions": allowed_map[final]})
    # (iv) reachability from the start.
    seen = {start} if start in state_set else set()
    frontier = [start] if start in state_set else []
    while frontier:
        node = frontier.pop()
        for action in allowed_map.get(node, []):
            for target in raw.get(_key(node, action), []):
                if target not in seen:
                    seen.add(target)
                    frontier.append(target)
    for state in states:
        if state not in seen:
            errors.append({"kind": "unreachable-state", "detail": state})
    # (v) co-reachability to a final state: no dead end is allowed.
    reverse = {s: [] for s in states}
    for key, targets in raw.items():
        head, _, _action = key.partition("|")
        for target in targets:
            if target in reverse:
                reverse[target].append(head)
    back = set(finals) & state_set
    frontier = list(back)
    while frontier:
        node = frontier.pop()
        for prev in reverse.get(node, []):
            if prev not in back:
                back.add(prev)
                frontier.append(prev)
    for state in states:
        if state not in back:
            errors.append({"kind": "dead-end-state", "detail": state})
    return {"format": FORMAT, "states": states, "actions": actions,
            "start": start, "finals": finals, "delta": raw,
            "allowed": allowed_map, "well_formed": not errors,
            "errors": errors}


def allowed(proto, state):
    """The tools the model is offered in this state."""
    return sorted((proto or {}).get("allowed", {}).get(state, []))


def tick(proto, state, action, target=None):
    """Accept one action or reject it without touching the state."""
    p = proto or {}
    if action not in (p.get("allowed", {}).get(state) or []):
        return {"accepted": False, "state": state,
                "reason": "action-not-allowed", "side_effect": False}
    targets = p.get("delta", {}).get(_key(state, action)) or []
    if not targets:
        return {"accepted": False, "state": state,
                "reason": "transition-undefined", "side_effect": False}
    if len(targets) == 1:
        nxt = targets[0]
    elif target is None:
        return {"accepted": False, "state": state,
                "reason": "target-required", "targets": targets,
                "side_effect": False}
    elif target not in targets:
        return {"accepted": False, "state": state,
                "reason": "target-not-in-transition", "targets": targets,
                "side_effect": False}
    else:
        nxt = target
    return {"accepted": True, "state": nxt, "reason": "ok",
            "side_effect": True}


def refines(parent, child, human_parent=(), human_child=()):
    """Definition-time check: every child run, minus its own steps, is a parent run."""
    p, c = parent or {}, child or {}
    sp = set(p.get("states") or [])
    fp = set(p.get("finals") or [])
    ap = set(p.get("actions") or [])
    fc = set(c.get("finals") or [])
    pd, cd = p.get("delta") or {}, c.get("delta") or {}
    if not fc <= fp:
        return {"safe": False, "reason": "final-not-in-parent",
                "detail": sorted(fc - fp)}
    missing_human = sorted(set(human_parent) - set(human_child))
    if missing_human:
        return {"safe": False, "reason": "human-step-became-automatic",
                "detail": missing_human}
    start = (c.get("start"), frozenset({p.get("start")}))
    seen = {start}
    frontier = [start]
    prev = {start: (None, None)}
    steps = 0
    while frontier and steps < 10000:
        q, kset = frontier.pop()
        steps += 1
        for action in (c.get("allowed", {}).get(q) or []):
            targets = cd.get(_key(q, action)) or []
            for q2 in targets:
                if action in ap:
                    k2 = set()
                    for pstate in kset:
                        k2.update(pd.get(_key(pstate, action)) or [])
                    if not k2:
                        return {"safe": False,
                                "reason": "child-takes-parent-action-parent-forbids",
                                "action": action, "state": q,
                                "path": _walk(prev, (q, kset))}
                else:
                    k2 = set(kset)
                if q2 in sp:
                    if q2 not in k2:
                        return {"safe": False,
                                "reason": "child-reaches-parent-state-by-unknown-route",
                                "action": action, "state": q2,
                                "path": _walk(prev, (q, kset))}
                    k2 = {q2}
                node = (q2, frozenset(k2))
                if node not in seen:
                    seen.add(node)
                    prev[node] = ((q, kset), action)
                    frontier.append(node)
    return {"safe": True, "reason": "trace-inclusion-holds", "steps": steps}


def _walk(prev, node):
    out = []
    cur = node
    while prev.get(cur) and prev[cur][0] is not None:
        parent, action = prev[cur]
        out.append(action)
        cur = parent
    return list(reversed(out))


def split(budget, share):
    """Hand work to a child: the allowance moves, it is never copied."""
    parent = dict(budget or {})
    errors = []
    for key, value in parent.items():
        if value is None:
            continue
        num = _finite(value)
        if num is None:
            errors.append({"kind": "non-finite-amount", "dimension": key})
        elif num < 0:
            errors.append({"kind": "negative-amount", "dimension": key})
    if isinstance(share, dict):
        child = dict(share)
    else:
        frac = _finite(share if share is not None else 0.5)
        if frac is None or frac < 0:
            return {"format": FORMAT, "parent": parent, "child": {},
                    "errors": [{"kind": "bad-share", "detail": str(share)}]}
        child = {}
        for key, value in parent.items():
            child[key] = None if value is None else value * frac
    for key, value in child.items():
        if value is None:
            if parent.get(key) is not None:
                errors.append({"kind": "child-unlimited", "dimension": key})
            continue
        num = _finite(value)
        if num is None:
            errors.append({"kind": "non-finite-amount", "dimension": key})
        elif num < 0:
            errors.append({"kind": "negative-amount", "dimension": key})
    remainder = {}
    for key, value in parent.items():
        raw = child.get(key)
        if value is None:
            remainder[key] = None
            continue
        if raw is None:
            remainder[key] = value
            continue
        allowed_child = _finite(raw)
        if allowed_child is None:
            remainder[key] = value
            continue
        if allowed_child > value:
            errors.append({"kind": "share-exceeds-parent", "dimension": key})
            remainder[key] = value
        else:
            remainder[key] = value - allowed_child
    return {"format": FORMAT, "parent": remainder, "child": child,
            "errors": errors, "linear": not errors}


def _finite(value):
    try:
        num = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(num) or math.isinf(num):
        return None
    return num


def charge(budget, usage):
    """Spend from a budget; a run stops once a limited dimension reaches zero."""
    b = dict(budget or {})
    remaining = {}
    exhausted = []
    for key, value in b.items():
        spent = _finite((usage or {}).get(key, 0.0)) or 0.0
        if value is None:
            remaining[key] = None
            continue
        left = _finite(value) - spent
        remaining[key] = left
        if left <= 0:
            exhausted.append(key)
    return {"format": FORMAT, "remaining": remaining,
            "exhausted": exhausted, "stop": bool(exhausted)}


def compliance(runs):
    """Process compliance beside the outcome: a passing run can break the rule."""
    rows = [r for r in (runs or []) if isinstance(r, dict)]
    total = len(rows)
    violating = sum(1 for r in rows if (_finite(r.get("violations")) or 0) > 0)
    passed = sum(1 for r in rows if r.get("passed") is True)
    blind = sum(1 for r in rows if r.get("passed") is True
                and (_finite(r.get("violations")) or 0) > 0)
    rate = violating / total if total else 0.0
    blind_share = blind / passed if passed else 0.0
    if not total:
        verdict = "no-runs"
    elif blind:
        verdict = "outcome-blind"
    elif violating:
        verdict = "outcome-detects"
    else:
        verdict = "compliant"
    return {"format": FORMAT, "runs": total, "passed": passed,
            "violating": violating, "violation_rate": rate,
            "blind_passes": blind, "blind_share": blind_share,
            "verdict": verdict}


def pressure(rows):
    """The standard arm against the governed arm, under pressure."""
    arms = {}
    for row in rows or []:
        arm = str((row or {}).get("arm") or "")
        entry = arms.setdefault(arm, {"runs": 0, "passed": 0, "violations": 0})
        entry["runs"] += 1
        if row.get("passed") is True:
            entry["passed"] += 1
        if row.get("violation") is True:
            entry["violations"] += 1
    for arm, entry in arms.items():
        entry["pass_rate"] = entry["passed"] / entry["runs"] if entry["runs"] else 0.0
        entry["violation_rate"] = (entry["violations"] / entry["runs"]
                                   if entry["runs"] else 0.0)
    std, gov = arms.get("standard"), arms.get("governed")
    if not std or not gov:
        return {"format": FORMAT, "arms": arms, "verdict": "two-arms-required"}
    p_value = _fisher(std["violations"], std["runs"] - std["violations"],
                      gov["violations"], gov["runs"] - gov["violations"])
    diff = std["violation_rate"] - gov["violation_rate"]
    if std["violations"] == 0 and gov["violations"] == 0:
        verdict = "no-violations"
    elif gov["violations"] == 0 and p_value < 0.05:
        verdict = "rule-breaks-under-pressure"
    elif gov["violations"]:
        verdict = "gate-leaks"
    else:
        verdict = "unresolved"
    return {"format": FORMAT, "arms": arms, "violation_difference": diff,
            "p_value": p_value, "verdict": verdict,
            "outcome_gap": abs(std["pass_rate"] - gov["pass_rate"])}


def _fisher(a, b, c, d):
    """Two-sided Fisher exact test on a 2x2 table."""
    n = a + b + c + d
    if n == 0:
        return 1.0
    row1, col1 = a + b, a + c

    def prob(x):
        return (math.comb(row1, x) * math.comb(n - row1, col1 - x)
                / math.comb(n, col1))

    observed = prob(a)
    total = 0.0
    low = max(0, col1 - (n - row1))
    high = min(row1, col1)
    for x in range(low, high + 1):
        p = prob(x)
        if p <= observed + 1e-12:
            total += p
    return min(1.0, total)


def advise(profile):
    """Map a harness profile onto the paper's failure modes."""
    p = profile or {}
    have = {str(k) for k, v in p.items() if v}
    checks = (
        ("derives_the_protocol", "prompt-only-rule",
         "a rule in the prompt holds only until something pushes"),
        ("withholds_illegal_tools", "tools-offered-every-turn",
         "withhold rather than ask the model not to use"),
        ("rejects_before_side_effects", "check-after-the-call",
         "an illegal call must never reach the tool"),
        ("checks_protocol_safe_inheritance", "subclass-jumps-to-outcome",
         "an extra step can bypass the parent's protocol"),
        ("splits_budgets_linearly", "copied-allowance",
         "the same allowance cannot be spent twice"),
        ("measures_process_compliance", "outcome-only-reward",
         "a passing outcome can hide a broken rule"),
        ("tests_under_pressure", "cooperative-only-evaluation",
         "the rule breaks where something pushes against it"),
    )
    findings = []
    for key, kind, why in checks:
        if key not in have:
            findings.append({"kind": kind, "why": why})
    return {"format": FORMAT, "findings": findings}
