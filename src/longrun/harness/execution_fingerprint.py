#!/usr/bin/env python3
"""Execution fingerprint — the repair trajectory is the fingerprint.

Source: arXiv:2610.32092, "AgentTrace" (round 141). Semantic attribution is
overwritten by system prompts and active watermarking breaks schema-constrained
generation (`agent_execution_fingerprint_2610.32092.md:19`, `:21`). AgentTrace
injects structurally ambiguous probes into rigid tool interfaces and reads the
externally observable trace instead: the initial parser outcome, then the ordered
sequence of repair operations (`:24`, `:27`).

  * **a trace is `[(a_t, o_t)]`**, with `o_t = (status, error category)` and the
    private chain of thought hidden (`:113`, `:116`).
  * **the first failure separates families coarsely**; the repair sequence
    separates same-tokenizer variants (`:109`, `:127`).
  * **the score is a Markov model of the trace**, summed over probes and
    normalized by `max(1, L-1)` so a long retry loop does not dominate
    (`:201`, `:233`).
  * **initial-outcome-only collapses to chance intra-family** (50.0%), while the
    repair trajectory reaches 93.0% / 97.0%; bag-of-operations stops at 77.0%
    (`:356`, `:486`, `:490`).
  * **ten probes reach 92.8%**; the full budget of 50 reaches 96.0% (`:321`,
    `:356`).
  * **it survives prompt obfuscation (≥94%) and temperature up to 0.8**
    (`:559`, `:583`).

  * `trace(steps)` — the initial outcome and the ordered repair sequence.
  * `profile(traces)` — P(E) and the Laplace-smoothed transition table.
  * `loglik(trace, profile)` — one trace's evidence for one model.
  * `attribute(traces, profiles)` — argmax, margin and the undetermined case.
  * `separation(rows)` — initial-only against sequential, and when sequence is required.
  * `budget(rows)` — the accuracy/query curve and its minimum budget.
  * `robustness(rows)` — the worst condition, and whether it stays usable.
  * `probes(row)` — the surrogate score of a probe set.
  * `audit(record)` — the conditions the fingerprint depends on.
  * `advise(profile)` — map a harness profile onto the paper's failure modes.

Pure: traces in; attribution out.
"""
from __future__ import annotations

import math

FORMAT = "longrun-execution-fingerprint/1"


def _num(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _label(step):
    step = step or {}
    error = step.get("error")
    status = step.get("status") or "unknown"
    return str(error) if error else str(status)


def trace(steps):
    """The externally observable trace: initial outcome plus repair order."""
    seq = [_label(step) for step in (steps or [])]
    if not seq:
        return {"format": FORMAT, "initial": None, "repairs": [],
                "length": 0, "verdict": "empty-trace"}
    repairs = seq[1:]
    return {"format": FORMAT, "initial": seq[0], "repairs": repairs,
            "length": len(seq),
            "verdict": "repaired" if repairs else "single-step"}


def profile(traces):
    """P(E) and a Laplace-smoothed transition table over repair labels."""
    initial = {}
    trans = {}
    vocab = set()
    n = 0
    for item in traces or []:
        t = trace(item) if isinstance(item, list) else (item or {})
        first = t.get("initial")
        if first is None:
            continue
        n += 1
        initial[first] = initial.get(first, 0) + 1
        vocab.add(first)
        prev = first
        for label in t.get("repairs") or []:
            vocab.add(label)
            key = "%s>%s" % (prev, label)
            trans[key] = trans.get(key, 0) + 1
            prev = label
    size = max(1, len(vocab))
    rows = {}
    for key, count in trans.items():
        head = key.split(">")[0]
        total = sum(value for other, value in trans.items()
                    if other.split(">")[0] == head)
        rows[key] = (count + 1.0) / (total + size)
    return {"format": FORMAT, "traces": n,
            "initial": {key: (value + 1.0) / (n + size)
                        for key, value in initial.items()},
            "transitions": rows, "vocab": sorted(vocab), "size": size}


def loglik(item, prof):
    """Log evidence for one trace under one profile."""
    p = prof or {}
    t = trace(item) if isinstance(item, list) else (item or {})
    first = t.get("initial")
    if first is None:
        return None
    base = p.get("initial") or {}
    prior = base.get(first, 1.0 / (max(1, p.get("traces") or 1) + p.get("size", 1)))
    total = math.log(prior)
    prev = first
    for label in t.get("repairs") or []:
        key = "%s>%s" % (prev, label)
        prob = (p.get("transitions") or {}).get(key)
        if prob is None:
            prob = 1.0 / ((p.get("size") or 1) + 1)
        total += math.log(prob)
        prev = label
    return total


def attribute(traces, profiles):
    """Argmax over candidate profiles, with the margin made explicit."""
    models = profiles or {}
    if not models or not traces:
        return {"format": FORMAT, "verdict": "not-enough-evidence"}
    scores = {}
    for name, prof in models.items():
        total = 0.0
        used = 0
        for item in traces:
            value = loglik(item, prof)
            if value is None:
                continue
            length = trace(item)["length"] if isinstance(item, list) else \
                (item or {}).get("length", 1)
            total += value / max(1, length - 1)
            used += 1
        if used:
            scores[name] = total
    if not scores:
        return {"format": FORMAT, "verdict": "no-scored-traces"}
    ranked = sorted(scores.items(), key=lambda pair: pair[1], reverse=True)
    best, best_score = ranked[0]
    margin = best_score - ranked[1][1] if len(ranked) > 1 else float("inf")
    return {"format": FORMAT, "ranked": ranked, "best": best,
            "margin": margin,
            "verdict": "attributed" if margin > 0.5 else "undetermined"}


def separation(rows):
    """Does the initial crash carry the signal, or the repair order?"""
    clean = []
    for row in rows or []:
        initial = _num((row or {}).get("initial"))
        sequential = _num((row or {}).get("sequential"))
        chance = _num((row or {}).get("chance")) or 0.0
        if initial is None or sequential is None:
            continue
        clean.append({"model": (row or {}).get("model"), "initial": initial,
                      "sequential": sequential, "chance": chance,
                      "gain": sequential - initial})
    if not clean:
        return {"format": FORMAT, "verdict": "no-rows"}
    collapsed = [r for r in clean if r["initial"] <= r["chance"] + 0.05
                 and r["sequential"] >= 0.9]
    if collapsed:
        verdict = "sequence-required"
    elif any(r["gain"] > 0.05 for r in clean):
        verdict = "sequence-helps"
    else:
        verdict = "sequence-unneeded"
    return {"format": FORMAT, "rows": clean,
            "collapsed": [r["model"] for r in collapsed],
            "mean_gain": sum(r["gain"] for r in clean) / len(clean),
            "verdict": verdict}


def budget(rows):
    """Accuracy against the number of probes, and the smallest usable budget."""
    clean = []
    for row in rows or []:
        q = _num((row or {}).get("q"))
        acc = _num((row or {}).get("accuracy"))
        if q is None or acc is None:
            continue
        clean.append({"q": q, "accuracy": acc})
    clean.sort(key=lambda row: row["q"])
    if not clean:
        return {"format": FORMAT, "verdict": "no-rows"}
    minimum = next((row["q"] for row in clean if row["accuracy"] >= 0.9), None)
    if minimum is None:
        verdict = "budget-insufficient"
    elif minimum <= 10:
        verdict = "cheap-attribution"
    else:
        verdict = "expensive-attribution"
    return {"format": FORMAT, "rows": clean, "minimum_budget": minimum,
            "verdict": verdict}


def robustness(rows):
    """The worst condition decides whether the fingerprint is usable."""
    clean = []
    for row in rows or []:
        acc = _num((row or {}).get("accuracy"))
        if acc is None:
            continue
        clean.append({"condition": (row or {}).get("condition"),
                      "accuracy": acc,
                      "semantic_baseline": _num((row or {}).get("semantic_baseline"))})
    if not clean:
        return {"format": FORMAT, "verdict": "no-rows"}
    worst = min(clean, key=lambda row: row["accuracy"])
    drop = None
    for row in clean:
        if row.get("semantic_baseline") is not None:
            drop = row["semantic_baseline"] - row["accuracy"]
            break
    if worst["accuracy"] >= 0.9:
        verdict = "fingerprint-stable"
    elif drop is not None and drop > 0.2:
        verdict = "baselines-collapse-first"
    else:
        verdict = "fingerprint-fragile"
    return {"format": FORMAT, "rows": clean, "worst": worst,
            "verdict": verdict}


def probes(row):
    """The surrogate score of one probe set."""
    r = row or {}
    target = _num(r.get("target_gap"))
    exec_var = _num(r.get("exec_variance")) or 0.0
    token = _num(r.get("token_distance"))
    lam_e = _num(r.get("lam_e")) or 0.5
    lam_t = _num(r.get("lam_t")) or 0.5
    if target is None or token is None:
        return {"format": FORMAT, "verdict": "probe-incomplete"}
    score = target + lam_e * exec_var + lam_t * token
    if target <= 0:
        verdict = "probe-weak"
    elif token <= 0:
        verdict = "probe-not-token-aware"
    elif score <= 0.2:
        verdict = "probe-marginal"
    else:
        verdict = "probe-optimized"
    return {"format": FORMAT, "score": score, "target_gap": target,
            "exec_variance": exec_var, "token_distance": token,
            "verdict": verdict}


def audit(record):
    """What the fingerprint depends on, and what removes it."""
    r = record or {}
    findings = []
    if r.get("strict_parser") is not True:
        findings.append({"kind": "no-rigid-interface",
                         "why": "a lenient parser never turns instability into an outcome"})
    if r.get("errors_surfaced") is not True:
        findings.append({"kind": "no-error-feedback",
                         "why": "a session killed on first failure has no repair trace"})
    if r.get("retries_allowed") is not True:
        findings.append({"kind": "no-retry-budget",
                         "why": "the repair order is the fine-grained signal"})
    if r.get("canonicalizes_output") is True:
        findings.append({"kind": "canonicalization-suppresses",
                         "why": "aggressive canonicalization removes the artifact"})
    if not findings:
        findings.append({"kind": "fingerprint-conditions-met"})
    return {"format": FORMAT, "findings": findings}


def advise(profile):
    """Map a harness profile onto the paper's failure modes."""
    p = profile or {}
    have = {str(k) for k, v in p.items() if v}
    checks = (
        ("records_full_traces", "final-answer-only",
         "the evidence is the initial outcome plus the ordered repairs"),
        ("keeps_error_categories", "success-flag-only",
         "the error category is the state of the Markov chain"),
        ("scores_sequence_not_bag", "bag-of-operations",
         "77.0% against 96.0%: order carries the signal"),
        ("normalizes_by_length", "long-loop-dominates",
         "one long retry must not outvote many short traces"),
        ("uses_held_out_probes", "profiles-on-test",
         "the probe library must be split before profiling"),
        ("reports_a_budget_curve", "single-budget-claim",
         "10 probes reach 92.8%, 50 reach 96.0%"),
        ("tests_prompt_obfuscation", "default-prompt-only",
         "the claim is stability, not a single-condition score"),
    )
    findings = []
    for key, kind, why in checks:
        if key not in have:
            findings.append({"kind": kind, "why": why})
    return {"format": FORMAT, "findings": findings}
