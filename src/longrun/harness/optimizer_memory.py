#!/usr/bin/env python3
"""Optimizer memory — carry WHY a harness was edited, not only the edit.

Source: arXiv:2611.18856, "Self-Improvement Memory Enables Continual Recursive
Self-Improvement" (round 126). When either the benchmark or the policy model
changes, an evolved harness is inherited but its story is not: the optimizer
cannot tell why a mechanism exists, what it was expected to fix, or whether it
did. The paper's own measurements make that concrete — an Opus-evolved harness
starts BELOW Gemini's seed (68.41 vs 73.89), and a source-evolved FewShotAll
harness starts below its seed on the target suite (72.92 vs 75.72, §1, §4.2) —
yet keeping the improvement history (rationale, predicted vs observed outcomes,
provenance) beats harness-only continuation by 2.36 points over ten paired runs
(9/10, p = 0.003, Table 3).

  * `record(memory, edit)` — group an attempt under its root cause, keep every
    earlier attempt, and flag an edit with no rationale, no prediction or no
    observed outcome. History is append-only.
  * `continuity(memory, target)` — for each problem, decide reuse / revise /
    replace / remove from the attempt's provenance (model, benchmark) and its
    measured outcome, naming `model-mismatch`, `benchmark-mismatch` or
    `source-regression` instead of guessing.
  * `advantage(pairs)` — the paired SIM-minus-no-SIM result, with an exact sign
    test; a mean without its p-value is not evidence.

The proposer/selector are LLM roles in the paper; this module is the record and
the continuity decision, not a model.
"""
from __future__ import annotations

import math

FORMAT = "longrun-optimizer-memory/1"


def _new_memory():
    return {"format": FORMAT, "entries": {}}


def record(memory, edit):
    """Append one attempt under its root cause; never drop an earlier attempt."""
    mem = memory if isinstance(memory, dict) and isinstance(memory.get("entries"), dict) \
        else _new_memory()
    edit = edit if isinstance(edit, dict) else {}
    problem = str(edit.get("problem") or "").strip()
    findings = []
    if not problem:
        return {"format": FORMAT, "memory": mem,
                "findings": [{"kind": "no-root-cause",
                              "why": "an edit with no recurring problem cannot be grouped"}],
                "why": "refused: the root cause is the key of the record"}
    if not str(edit.get("rationale") or "").strip():
        findings.append({"kind": "no-rationale",
                         "why": "a later optimizer cannot judge an unexplained edit"})
    if not (edit.get("predicted") or []):
        findings.append({"kind": "no-prediction",
                         "why": "a prediction made after the run is not a prediction"})
    observed = edit.get("observed") or {}
    if not any(observed.get(k) for k in ("fixed", "regressed", "unchanged")):
        findings.append({"kind": "no-outcome",
                         "why": "the attempt was never measured"})
    entries = {k: dict(v) for k, v in mem["entries"].items()}
    entry = entries.get(problem)
    if entry is None:
        entry = {"problem": problem, "attempts": []}
    else:
        findings.append({"kind": "duplicate-root-cause", "problem": problem,
                         "merged": True,
                         "why": "an identical root cause extends the existing history"})
    if edit.get("drop_history") and entry["attempts"]:
        findings.append({"kind": "history-dropped", "problem": problem,
                         "kept": len(entry["attempts"]),
                         "why": "the record is append-only; earlier attempts are kept"})
    entry = {"problem": problem, "attempts": entry["attempts"] + [{
        "change": str(edit.get("change") or ""),
        "rationale": str(edit.get("rationale") or ""),
        "predicted": [str(t) for t in (edit.get("predicted") or [])],
        "observed": {k: [str(t) for t in (observed.get(k) or [])]
                     for k in ("fixed", "regressed", "unchanged")},
        "provenance": dict(edit.get("provenance") or {}),
    }]}
    entries[problem] = entry
    return {"format": FORMAT, "memory": {"format": FORMAT, "entries": entries},
            "findings": findings, "attempts": len(entry["attempts"]),
            "why": "the record carries rationale, prediction, outcome and provenance"}


def continuity(memory, target):
    """Reuse / revise / replace / remove each inherited mechanism, with its reason."""
    mem = memory if isinstance(memory, dict) else {}
    target = target if isinstance(target, dict) else {}
    decisions, findings = {}, []
    for problem, entry in (mem.get("entries") or {}).items():
        attempts = entry.get("attempts") or []
        if not attempts:
            continue
        last = attempts[-1]
        observed = last.get("observed") or {}
        prov = last.get("provenance") or {}
        fixed, regressed = observed.get("fixed") or [], observed.get("regressed") or []
        why, decision = "", "reuse"
        if regressed and not fixed:
            decision, why = "remove", "the source attempt regressed and fixed nothing"
            findings.append({"kind": "source-regression", "problem": problem})
        elif prov.get("model") and target.get("model") and prov["model"] != target["model"]:
            decision, why = "revise", "measured on another policy model"
            findings.append({"kind": "model-mismatch", "problem": problem,
                             "source": prov.get("model"), "target": target.get("model")})
        elif prov.get("benchmark") and target.get("benchmark") \
                and prov["benchmark"] != target["benchmark"]:
            decision, why = "revise", "measured on another benchmark"
            findings.append({"kind": "benchmark-mismatch", "problem": problem,
                             "source": prov.get("benchmark"),
                             "target": target.get("benchmark")})
        elif not fixed:
            decision, why = "revise", "no task was recorded as fixed"
            findings.append({"kind": "unconfirmed-transfer", "problem": problem})
        else:
            why = "same model, same benchmark, with measured fixes"
        if last.get("predicted") and not (fixed or regressed):
            findings.append({"kind": "predicted-unobserved", "problem": problem,
                             "predicted": last["predicted"]})
        decisions[problem] = {"decision": decision, "why": why,
                              "provenance": prov,
                              "attempts": len(attempts)}
    return {"format": FORMAT, "decisions": decisions, "findings": findings,
            "why": "inherited experience is evidence about WHY, not a guarantee it still helps"}


def _sign(wins, losses):
    n = wins + losses
    if n == 0:
        return 1.0
    tail = sum(math.comb(n, i) for i in range(min(wins, losses) + 1)) / (2 ** n)
    return round(min(1.0, 2 * tail), 4)


def advantage(pairs):
    """Paired improvement of memory over no-memory, with an exact sign test."""
    deltas = []
    for pair in pairs or ():
        if not isinstance(pair, dict):
            continue
        try:
            deltas.append(float(pair.get("sim")) - float(pair.get("no_sim")))
        except (TypeError, ValueError):
            continue
    if not deltas:
        return {"format": FORMAT, "mean": None,
                "findings": [{"kind": "no-pairs"}],
                "why": "a comparison needs paired continuations"}
    wins = sum(1 for d in deltas if d > 0)
    losses = sum(1 for d in deltas if d < 0)
    mean = sum(deltas) / len(deltas)
    p = _sign(wins, losses)
    findings = []
    if p > 0.05:
        findings.append({"kind": "not-significant", "p": p, "pairs": len(deltas)})
    if losses:
        findings.append({"kind": "mixed-pairs", "losses": losses})
    return {"format": FORMAT, "pairs": len(deltas), "mean": round(mean, 4),
            "wins": wins, "losses": losses, "p": p, "findings": findings,
            "why": "a mean without its sign test is an anecdote"}
