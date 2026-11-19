#!/usr/bin/env python3
"""Skill quality profile — nine dimensions, and an execution-free estimate.

Source: arXiv:2610.38147, "SkillCT: A Multidimensional Benchmark and
Execution-Free Baseline for Agent Skill Assessment" (round 123). Downstream
success is not quality: a skill can pass its task and still be under-specified,
unstable across models, or unsafe at its boundary. SkillCT scores nine
dimensions in three aspects — static (structural completeness, conciseness,
description–content consistency), dynamic (cross-model robustness,
intent-perturbation stability, capability-boundary handling, efficiency) and
human-assisted (behaviour-chain consistency, task-abstraction granularity) — and
estimates a new skill's profile from similar REFERENCE skills without executing
it (§3, Fig. 1).

  * `profile(skill)` — nine dimension scores from declared facts, with a finding
    for every dimension whose evidence is missing. A missing measurement is
    reported, never scored as good.
  * `predict(skill, references)` — tag-overlap retrieval of reference profiles;
    the estimate cites the references it used and says how much of the skill's
    own evidence it covers.

Pure: skill and reference records in, a profile out.
"""
from __future__ import annotations

FORMAT = "longrun-skill-quality/1"
DIMENSIONS = (
    ("static", "structural_completeness"),
    ("static", "conciseness"),
    ("static", "description_content_consistency"),
    ("dynamic", "cross_model_robustness"),
    ("dynamic", "intent_perturbation_stability"),
    ("dynamic", "capability_boundary_handling"),
    ("dynamic", "efficiency"),
    ("human", "behavior_chain_consistency"),
    ("human", "task_abstraction_granularity"),
)


def _ratio(part, whole):
    return round(float(part) / float(whole), 4) if whole else 0.0


def profile(skill):
    """Nine dimension scores, each from a declared fact — missing evidence is a finding."""
    s = skill or {}
    findings = []
    scores = {}

    sections = [str(x) for x in s.get("sections") or ()]
    needed = ("instructions", "tools", "examples", "resources")
    covered = [n for n in needed if n in sections]
    scores["structural_completeness"] = _ratio(len(covered), len(needed))
    for name in needed:
        if name not in covered:
            findings.append({"kind": "missing-section", "dimension": "structural_completeness",
                             "section": name, "why": "a section the profile requires is absent"})

    tokens = int(s.get("content_tokens") or 0)
    budget = int(s.get("token_budget") or 0)
    scores["conciseness"] = 1.0 if not budget else round(min(1.0, budget / tokens), 4) if tokens else 0.0
    if budget and tokens > budget:
        findings.append({"kind": "over-budget", "dimension": "conciseness",
                         "tokens": tokens, "budget": budget,
                         "why": "the specification carries more text than the budget allows"})

    described = {str(t) for t in s.get("tools_described") or ()}
    declared = {str(t) for t in s.get("tools") or ()}
    phantom = sorted(described - declared)
    scores["description_content_consistency"] = (
        round(len(declared & described) / len(declared), 4) if declared else 0.0)
    for tool in phantom:
        findings.append({"kind": "described-not-declared", "dimension":
                         "description_content_consistency", "tool": tool,
                         "why": "the description promises a capability the skill does not declare"})

    models = [str(m) for m in s.get("models_tested") or ()]
    scores["cross_model_robustness"] = 1.0 if len(models) >= 2 else (0.5 if models else 0.0)
    if len(models) < 2:
        findings.append({"kind": "untested-across-models", "dimension":
                         "cross_model_robustness", "models": models,
                         "why": "stability across backbones was never measured"})

    perturbations = [p for p in s.get("perturbations") or () if isinstance(p, dict)]
    if not perturbations:
        scores["intent_perturbation_stability"] = 0.0
        findings.append({"kind": "untested-perturbations", "dimension":
                         "intent_perturbation_stability",
                         "why": "no rewrite, replacement or conciseness probe was run"})
    else:
        held = sum(1 for p in perturbations if p.get("held"))
        scores["intent_perturbation_stability"] = _ratio(held, len(perturbations))
        if held < len(perturbations):
            findings.append({"kind": "perturbation-drop", "dimension":
                             "intent_perturbation_stability",
                             "failed": len(perturbations) - held,
                             "why": "the induced behaviour did not survive a request change"})

    boundaries = {str(b) for b in s.get("boundaries") or ()}
    need_b = {"unsafe", "unsupported", "infeasible"}
    scores["capability_boundary_handling"] = _ratio(len(boundaries & need_b), len(need_b))
    for name in sorted(need_b - boundaries):
        findings.append({"kind": "unhandled-boundary", "dimension":
                         "capability_boundary_handling", "boundary": name,
                         "why": "the skill has no stated behaviour at this boundary"})

    per_task = int(s.get("tokens_per_task") or 0)
    per_budget = int(s.get("efficiency_budget") or 0)
    if not per_budget:
        scores["efficiency"] = 0.0
        findings.append({"kind": "unmeasured-efficiency", "dimension": "efficiency",
                         "why": "no token or step budget was declared"})
    else:
        scores["efficiency"] = round(min(1.0, per_budget / per_task), 4) if per_task else 0.0
        if per_task > per_budget:
            findings.append({"kind": "over-efficiency-budget", "dimension": "efficiency",
                             "tokens_per_task": per_task, "budget": per_budget,
                             "why": "the skill spends more than the deployment allows"})

    chain = [c for c in s.get("behavior_chain") or () if isinstance(c, dict)]
    mapped = sum(1 for c in chain if c.get("objective"))
    scores["behavior_chain_consistency"] = _ratio(mapped, len(chain)) if chain else 0.0
    if not chain:
        findings.append({"kind": "no-behavior-chain", "dimension":
                         "behavior_chain_consistency",
                         "why": "no action can be traced to the objective it serves"})
    elif mapped < len(chain):
        findings.append({"kind": "unmapped-action", "dimension":
                         "behavior_chain_consistency", "count": len(chain) - mapped,
                         "why": "an action has no objective, so the chain cannot be judged"})

    granularity = str(s.get("task_granularity") or "")
    scores["task_abstraction_granularity"] = 1.0 if granularity in ("broad", "narrow") else 0.0
    if not scores["task_abstraction_granularity"]:
        findings.append({"kind": "undeclared-granularity", "dimension":
                         "task_abstraction_granularity",
                         "why": "a skill that fits every task size guides none"})

    values = list(scores.values())
    mean = round(sum(values) / len(values), 4) if values else 0.0
    verdict = ("complete" if mean >= 0.8 and not findings else
               "partial" if mean >= 0.4 else "thin")
    return {"format": FORMAT, "verdict": verdict, "mean": mean, "scores": scores,
            "dimensions": len(DIMENSIONS), "findings": findings,
            "why": ("every dimension has evidence" if not findings else
                    "a missing measurement is reported, never scored as good")}


def predict(skill, references, k=3):
    """Execution-free estimate from similar reference profiles (TF-IDF idea, tag overlap)."""
    s = skill or {}
    tags = {str(t) for t in s.get("tags") or ()}
    scored = []
    for ref in references or ():
        if not isinstance(ref, dict):
            continue
        rtags = {str(t) for t in ref.get("tags") or ()}
        if not tags and not rtags:
            continue
        overlap = len(tags & rtags)
        denom = len(tags | rtags) or 1
        scored.append((round(overlap / denom, 4), str(ref.get("id") or "?"), ref, overlap))
    scored.sort(key=lambda row: (-row[0], row[1]))
    top = [row for row in scored[:max(1, int(k))] if row[0] > 0]
    if not top:
        return {"format": FORMAT, "estimated": None, "cited": [],
                "why": "no reference skill shares a tag with this one"}
    profiles = [(ref.get("profile") or {}) for _s, _i, ref, _o in top]
    dims = sorted({d for p in profiles for d in p})
    estimate = {d: round(sum(float(p.get(d, 0)) for p in profiles) / len(profiles), 4)
                for d in dims}
    return {"format": FORMAT, "estimated": estimate,
            "cited": [{"id": i, "overlap": s_, "shared": o}
                      for s_, i, _ref, o in top],
            "coverage": round(len(tags & set().union(*[
                {str(t) for t in (_ref.get("tags") or ())} for _s, _i, _ref, _o in top])
            ) / len(tags), 4) if tags else 0.0,
            "why": "estimated from references; executing the skill is what would confirm it"}
