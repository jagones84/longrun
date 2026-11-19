#!/usr/bin/env python3
"""Dialogue allocation — what a teammate says is evidence about the hidden world.

Source: arXiv:2611.23119, "Dynamic Task Allocation with Dialogue" (round 135).
Tasks arrive mid-episode and each agent sees only part of the object space, so
task allocation becomes inference over an explicit belief
(`dynamic_task_allocation_dialogue_2611.23119.md:38`, `:75`).

  * **the belief is over allocations**: a posterior over candidate task
    allocations, combining a prior, the joint action likelihood and an utterance
    likelihood read from the model's token probabilities (`:81`, `:85`).
  * **speaking is a threshold on uncertainty**: the agent broadcasts when the
    Shannon entropy of its allocation belief exceeds a fraction `eps` of the
    maximum entropy (`:79`, `:200`).
  * **evidence is typed**: an object picked up, set down or delivered updates
    only the propositions the transition touches; anything else keeps its prior
    belief (`:252`, `:266`).
  * **hidden actions are `empty`**: an unobserved action raises the observation
    term to the whole joint observation; an observed one is explained by the
    allocation and contributes likelihood 1 (`:286`, `:296`).
  * **measured**: under partial observability the communicating agent beats the
    non-communicating baseline by 0.585 speedup and 18 timesteps on average, and
    the gap grows with queue length (`:28`, `:142`).

  * `posterior(prior, action, utterance)` — normalize a belief over allocations.
  * `entropy(belief)` / `speak(belief, epsilon)` — the uncertainty trigger.
  * `evidence(before, after)` — type a visible transition.
  * `propositions(prior, kind, affected)` — update only what the evidence touches.
  * `schedule(n, rate, horizon)` — deterministic dynamic task arrival.
  * `compare(comm, base)` — timestep difference and speedup with standard errors.
  * `audit(spec)` — the paper's stated experimental boundaries.
  * `advise(profile)` — map a harness profile onto the paper's failure modes.

Pure: beliefs and timings in; posteriors and verdicts out.
"""
from __future__ import annotations

import math
import random
import statistics

FORMAT = "longrun-dialogue-allocation/1"

KINDS = ("picked-up", "set-down", "delivered", "none")


def _num(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def posterior(prior, action=None, utterance=None):
    """Weight allocations by prior, action likelihood and utterance likelihood."""
    p = dict(prior or {})
    a = dict(action or {})
    u = dict(utterance or {})
    if not p:
        return {"format": FORMAT, "findings": [{"kind": "no-allocations"}]}
    weights = {}
    for name, value in p.items():
        w = _num(value)
        if w is None or w < 0:
            return {"format": FORMAT, "findings": [{"kind": "invalid-prior", "allocation": name}]}
        if name in a:
            av = _num(a[name])
            if av is None or av < 0:
                return {"format": FORMAT, "findings": [{"kind": "invalid-likelihood",
                                                        "allocation": name}]}
            w *= av
        if name in u:
            uv = _num(u[name])
            if uv is None or uv < 0:
                return {"format": FORMAT, "findings": [{"kind": "invalid-utterance",
                                                        "allocation": name}]}
            w *= uv
        weights[name] = w
    total = sum(weights.values())
    findings = []
    if total <= 0:
        return {"format": FORMAT, "findings": [{"kind": "zero-mass",
                                                "why": "every allocation is excluded by the evidence"}]}
    belief = {name: w / total for name, w in weights.items()}
    if abs(sum(_num(v) for v in p.values()) - 1.0) > 1e-6:
        findings.append({"kind": "unnormalized-prior",
                         "why": "the prior should be a distribution over allocations"})
    if not findings:
        findings.append({"kind": "posterior-updated"})
    return {"format": FORMAT, "belief": {k: round(v, 6) for k, v in belief.items()},
            "best": max(belief, key=belief.get), "findings": findings}


def entropy(belief):
    """Shannon entropy of an allocation belief and its normalized value."""
    b = {k: _num(v) for k, v in (belief or {}).items()}
    b = {k: v for k, v in b.items() if v is not None and v > 0}
    total = sum(b.values())
    if not b or total <= 0:
        return {"format": FORMAT, "bits": None, "normalized": None,
                "findings": [{"kind": "empty-belief"}]}
    bits = -sum((v / total) * math.log(v / total, 2) for v in b.values())
    peak = math.log(len(b), 2) if len(b) > 1 else 0.0
    return {"format": FORMAT, "bits": round(bits, 6), "max_bits": round(peak, 6),
            "normalized": round(bits / peak, 6) if peak else 0.0, "findings": []}


def speak(belief, epsilon=0.7):
    """Broadcast when normalized entropy exceeds the threshold `epsilon`."""
    e = entropy(belief)
    if e.get("normalized") is None:
        return {"format": FORMAT, "speak": True,
                "findings": [{"kind": "uncertain-without-belief"}]}
    normalized = e["normalized"]
    out = {"format": FORMAT, "speak": normalized > float(epsilon),
           "normalized": normalized, "threshold": float(epsilon), "findings": []}
    out["findings"].append({"kind": "speaks" if out["speak"] else "stays-silent",
                            "why": "the trigger is a fraction of the maximum entropy"})
    return out


def evidence(before, after):
    """Type a visible transition by the objects that disappeared and appeared."""
    start = list(before or ())
    end = list(after or ())
    removed = list(start)
    for item in end:
        if item in removed:
            removed.remove(item)
    added = list(end)
    for item in start:
        if item in added:
            added.remove(item)
    if not removed and not added:
        kind = "none"
    elif removed and not added:
        kind = "picked-up"
    elif added and not removed:
        kind = "set-down"
    else:
        kind = "delivered"
    findings = []
    if kind == "delivered":
        findings.append({"kind": "transition-typed", "type": kind,
                         "why": "an object changed form or reached the goal"})
    return {"format": FORMAT, "type": kind, "removed": removed, "added": added,
            "findings": findings}


def propositions(prior, kind, affected, evidence_likelihood=None, implied=None):
    """Update only the propositions the evidence touches; the rest keep their belief."""
    base = dict(prior or {})
    touched = set(affected or ())
    ev = dict(evidence_likelihood or {})
    im = dict(implied or {})
    findings = []
    if not base:
        return {"format": FORMAT, "findings": [{"kind": "no-propositions"}]}
    if kind not in KINDS:
        return {"format": FORMAT, "findings": [{"kind": "unknown-evidence", "type": kind}]}
    if kind == "none" and touched:
        findings.append({"kind": "no-evidence-updated-propositions",
                         "why": "with no evidence every proposition retains its belief"})
    belief = {}
    for name, value in base.items():
        p = _num(value)
        if p is None or not 0 <= p <= 1:
            return {"format": FORMAT, "findings": [{"kind": "invalid-proposition", "name": name}]}
        if name in touched and kind != "none":
            w = p
            if name in ev:
                w *= _num(ev[name]) if _num(ev[name]) is not None else 1.0
            if name in im:
                w *= _num(im[name]) if _num(im[name]) is not None else 1.0
            belief[name] = max(0.0, min(1.0, w))
        else:
            belief[name] = p
    if not findings:
        findings.append({"kind": "belief-updated", "touched": sorted(touched)})
    return {"format": FORMAT, "belief": {k: round(v, 6) for k, v in belief.items()},
            "findings": findings}


def schedule(n, rate=0.025, horizon=300, seed=7):
    """Dynamic arrival: reveal N tasks at rate r, keeping at least one active."""
    total = int(n or 0)
    if total < 1 or not 0 < float(rate) <= 1 or int(horizon) < 1:
        return {"format": FORMAT, "findings": [{"kind": "invalid-schedule"}]}
    rng = random.Random(seed)
    revealed = [0]
    t = 0
    while len(revealed) < total and t < int(horizon) - 1:
        t += 1
        if rng.random() < float(rate):
            revealed.append(t)
    complete = len(revealed) >= total
    findings = []
    if not complete:
        findings.append({"kind": "tasks-unrevealed", "revealed": len(revealed), "total": total})
    if revealed[0] != 0:
        findings.append({"kind": "no-task-at-start",
                         "why": "at least one task stays active until all are complete"})
    if not findings:
        findings.append({"kind": "continuous-work"})
    return {"format": FORMAT, "revealed": revealed, "complete": complete,
            "horizon": int(horizon), "findings": findings}


def compare(comm, base):
    """Timestep difference and speedup, both with standard errors."""
    c = [_num(x) for x in (comm or ()) if _num(x) is not None]
    b = [_num(x) for x in (base or ()) if _num(x) is not None]
    if len(c) < 2 or len(b) < 2 or len(c) != len(b):
        return {"format": FORMAT, "findings": [{"kind": "not-enough-paired-runs",
                                                "comm": len(c), "base": len(b)}]}
    deltas = [ci - bi for ci, bi in zip(c, b)]
    mean_delta = statistics.mean(deltas)
    se_delta = statistics.stdev(deltas) / math.sqrt(len(deltas))
    speedups = [bi / ci - 1.0 for ci, bi in zip(c, b) if ci > 0]
    mean_speed = statistics.mean(speedups) if speedups else None
    se_speed = (statistics.stdev(speedups) / math.sqrt(len(speedups))
                if len(speedups) > 1 else None)
    findings = []
    if abs(mean_delta) <= 1.96 * se_delta:
        findings.append({"kind": "difference-unresolved",
                         "why": "the interval contains zero"})
    elif mean_delta < 0:
        findings.append({"kind": "communication-faster", "delta": round(mean_delta, 4)})
    else:
        findings.append({"kind": "communication-slower", "delta": round(mean_delta, 4)})
    return {"format": FORMAT, "runs": len(c), "delta": round(mean_delta, 4),
            "delta_se": round(se_delta, 4),
            "speedup": None if mean_speed is None else round(mean_speed, 4),
            "speedup_se": None if se_speed is None else round(se_speed, 4),
            "findings": findings}


def audit(spec):
    """The boundaries the paper states for its own evidence."""
    s = spec or {}
    findings = []
    if not s.get("dynamic_arrival"):
        findings.append({"kind": "static-goals",
                         "why": "the point is tasks that arrive mid-episode"})
    if s.get("partial_observability") is not True:
        findings.append({"kind": "full-observability-only",
                         "why": "dialogue matters when the collaborator is not visible"})
    if s.get("known_task_types") is not True:
        findings.append({"kind": "unknown-task-types",
                         "why": "the paper assumes the set of task types is known"})
    if s.get("fixed_agent_set") is not True:
        findings.append({"kind": "open-agent-set",
                         "why": "the paper assumes a fixed agent set"})
    if s.get("free_communication") is not True:
        findings.append({"kind": "costly-communication",
                         "why": "the reported results assume cost-free messages"})
    runs = int(s.get("runs_per_config") or 0)
    if runs < 6:
        findings.append({"kind": "too-few-runs", "runs": runs,
                         "why": "six runs per configuration underpin the standard errors"})
    if int(s.get("max_queue") or 0) > 3:
        findings.append({"kind": "queue-beyond-evidence", "max_queue": s.get("max_queue"),
                         "why": "the evidence stops at queue length three"})
    if not findings:
        findings.append({"kind": "within-evidence"})
    return {"format": FORMAT, "findings": findings}


def advise(profile):
    """Map a harness profile onto the paper's failure modes."""
    p = profile or {}
    have = {str(key) for key, value in p.items() if value}
    findings = []
    checks = (
        ("keeps_allocation_belief", "implicit-allocation", "state the belief over who does what"),
        ("uses_dialogue_as_evidence", "dialogue-as-text", "an utterance is a likelihood, not a hint"),
        ("speaks_on_uncertainty", "always-or-never-speaks", "trigger on entropy above a fraction"),
        ("types_observable_evidence", "untyped-observations", "picked-up, set-down, delivered, none"),
        ("updates_only_affected", "whole-state-refresh", "other propositions retain their belief"),
        ("models_dynamic_arrival", "static-task-list", "tasks arrive while the episode runs"),
        ("reports_timestep_and_speedup", "unpaired-metric", "report delta t and speedup with errors"),
        ("tests_partial_observability", "full-info-only", "hide the collaborator's partition"),
    )
    for key, kind, why in checks:
        if key not in have:
            findings.append({"kind": kind, "why": why})
    return {"format": FORMAT, "findings": findings}
