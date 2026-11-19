#!/usr/bin/env python3
"""Rule retrieval by dependency closure — a verdict needs prerequisites, not lookalikes.

Source: arXiv:2611.01042, "Constraint Dependency Graph Retrieval for Compliance
Detection on Long SKILL Documents" (round 123). A SKILL document is a
specification: the same visible action can follow the procedure or not, so the
rule context must be complete. Similarity retrieval brings in relevant-looking
rules and omits mandatory prerequisites, and a prerequisite can be phrased in
words the request never uses (§1).

  * `closure(rules, seeds, budget)` — a constraint dependency graph with ONE edge
    type (`require`: the second rule must be judged before the first). The
    selection is the seeds plus everything reachable; it is *conditionally
    complete* when every activated prerequisite is included, and `over-budget`
    when it does not fit.
  * `audit(selection, graph, seeds)` — compares a similarity selection with the
    closure: a missing prerequisite is named, a rule outside the closure is
    named as irrelevant to the verdict, and closure non-emptiness is the
    validity gate.

Pure: rule records in, a selection and findings out.
"""
from __future__ import annotations

FORMAT = "longrun-rule-retrieval/1"


def _rules(rules):
    out = {}
    for r in rules or ():
        if isinstance(r, dict) and r.get("id"):
            out[str(r["id"])] = {"tokens": int(r.get("tokens") or 0),
                                 "requires": [str(x) for x in r.get("requires") or ()]}
    return out


def closure(rules, seeds, budget=None):
    """Seeds plus every reachable prerequisite; complete only when none is missing."""
    graph = _rules(rules)
    active = []
    missing = []
    unknown_seeds = []
    for seed in seeds or ():
        seed = str(seed)
        if seed not in graph:
            unknown_seeds.append(seed)
            continue
        if seed not in active:
            active.append(seed)
    frontier = list(active)
    while frontier:
        current = frontier.pop(0)
        for need in graph[current]["requires"]:
            if need not in graph:
                missing.append(need)
                continue
            if need not in active:
                active.append(need)
                frontier.append(need)
    tokens = sum(graph[r]["tokens"] for r in active)
    findings = []
    if unknown_seeds:
        findings.append({"kind": "unknown-seed", "rules": sorted(set(unknown_seeds)),
                         "why": "a scenario keyword activated a rule the document does not define"})
    if missing:
        findings.append({"kind": "unknown-prerequisite", "rules": sorted(set(missing)),
                         "why": "the closure names a rule the document does not define"})
    if budget is not None and tokens > int(budget):
        findings.append({"kind": "over-budget", "tokens": tokens, "budget": int(budget),
                         "why": "a conditionally complete set does not fit the context"})
    if not active:
        findings.append({"kind": "empty-closure", "why":
                         "a selection that reaches no rule cannot support a verdict"})
    return {"format": FORMAT, "rules": active, "tokens": tokens,
            "complete": not missing,
            "decision": "use" if not findings else "refuse",
            "findings": findings,
            "why": "the closure is complete with respect to the activated seeds and edges"}


def audit(selection, rules, seeds, budget=None):
    """Diff a similarity selection against the closure it should have covered."""
    graph = _rules(rules)
    selected = [str(s) for s in selection or ()]
    for seed in seeds or ():
        if str(seed) not in selected:
            selected.append(str(seed))
    want = closure(rules, seeds, budget)
    needed = set(want["rules"])
    chosen = set(selected)
    missing = sorted(needed - chosen)
    extra = sorted(chosen - needed)
    findings = []
    for rule in missing:
        findings.append({"kind": "missing-prerequisite", "rule": rule,
                         "why": "a rule the verdict depends on was never retrieved"})
    for rule in extra:
        findings.append({"kind": "irrelevant-rule", "rule": rule,
                         "why": "selected by similarity but not required by the activated seeds"})
    if not chosen:
        findings.append({"kind": "empty-selection", "why":
                         "a verdict from no rule is unsupported"})
    return {"format": FORMAT, "ok": not findings, "missing": missing, "extra": extra,
            "needed": sorted(needed), "findings": findings,
            "why": ("the selection is conditionally complete" if not findings else
                    "similarity is not completeness")}
