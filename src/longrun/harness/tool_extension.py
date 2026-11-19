#!/usr/bin/env python3
"""Tool extension — a new tool reuses *when to call*, never *which* tool.

Source: arXiv:2611.23810, "Continual Tool-Space Extension Learning for
Multimodal Agents" (round 152). Adding a specialist tool to a trained agent sits
between two bad options: full retraining, whose cost grows with every tool, and
naive adapter training, which overwrites the directions the agent uses for its
existing tools (`tool_space_extension_2611.23810.txt:88`, `:95`).

  * **tool use is two decisions**: initiating a call (common to every tool) and
    selecting a tool (specific to each); a new tool should reuse the first and
    leave the second untouched (`:102`, `:108`).
  * **the new adapter is orthogonal to the protected selection directions**
    inside the shared tool-call subspace (`:116`, `:264`).
  * **supervision comes from the tool's own annotations**, converted into
    verified trajectories by keeping only attempts whose answer matches the
    ground truth — no teacher model (`:130`, `:209`).
  * **measured**: sequential extension keeps V*Bench at 80.6 after three tools
    against 75.9, 78.0 and 74.3 for naive SFT, O-LoRA and KeepLoRA, and reaches
    93.5 depth accuracy (`:432`, `:516`).
  * **retention is the constraint**: at most a 0.3-point drop on existing tools
    (`:60`, `:62`), and the new specialist shifts the call distribution toward
    itself on the benchmarks that need it (`:412`, `:424`).

  * `verified(rows)` — the kept trajectory set, per tool.
  * `retention(record)` — per-tool deltas and the maximum drop.
  * `gain(record)` — the new capability against its baseline.
  * `drift(record)` — how far the existing tool shares moved.
  * `decisions()` — what a new tool may reuse and what it must protect.
  * `cost(record)` — full retraining against adapter-level extension.
  * `admit(record)` — the extension gate, with every refusal named.
  * `audit(record)` — the six misreadings the paper names.
  * `advise(profile)` — map a harness profile onto the paper's failure modes.

Pure: counts, per-tool scores and shares in; admission and verdicts out.
"""
from __future__ import annotations

FORMAT = "longrun-tool-extension/1"

RETENTION_CAP = 0.3
DRIFT_CAP = 0.15
MIN_TRAJECTORIES = 100


def _num(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def verified(rows):
    """Only attempts whose final answer matches the annotation are kept."""
    counts = {}
    dropped = 0
    kept = 0
    for row in rows or []:
        r = row or {}
        tool = str(r.get("tool") or "")
        if not tool:
            continue
        if r.get("verified") is True:
            counts[tool] = counts.get(tool, 0) + 1
            kept += 1
        else:
            dropped += 1
    return {"format": FORMAT, "kept": kept, "dropped": dropped,
            "by_tool": counts, "tools": len(counts),
            "verdict": "trajectories-verified" if kept else "no-trajectories"}


def retention(record):
    """Per-tool score before and after; the worst drop decides."""
    r = record or {}
    deltas = {}
    for row in r.get("old_tools") or []:
        item = row or {}
        name = str(item.get("tool") or "")
        before = _num(item.get("before"))
        after = _num(item.get("after"))
        if not name or before is None or after is None:
            continue
        deltas[name] = after - before
    if not deltas:
        return {"format": FORMAT, "verdict": "no-panel"}
    worst = min(deltas.items(), key=lambda kv: kv[1])
    cap = _num(r.get("cap")) or RETENTION_CAP
    return {"format": FORMAT, "deltas": deltas, "worst": worst[0],
            "worst_delta": worst[1], "cap": cap,
            "verdict": "retention-holds" if worst[1] >= -cap
            else "retention-broken"}


def gain(record):
    """The new tool's accuracy against the best no-tool baseline."""
    r = record or {}
    after = _num(r.get("after"))
    baseline = _num(r.get("baseline"))
    if after is None or baseline is None:
        return {"format": FORMAT, "verdict": "insufficient-input"}
    delta = after - baseline
    return {"format": FORMAT, "after": after, "baseline": baseline,
            "delta": delta,
            "verdict": "capability-gained" if delta > 0 else "no-gain"}


def drift(record):
    """Total-variation distance between existing tool shares before and after."""
    r = record or {}
    before = r.get("before") or {}
    after = r.get("after") or {}
    names = set(before) | set(after)
    if not names:
        return {"format": FORMAT, "verdict": "no-shares"}
    distance = 0.5 * sum(abs((_num(after.get(n)) or 0.0)
                             - (_num(before.get(n)) or 0.0))
                         for n in names)
    cap = _num(r.get("cap")) or DRIFT_CAP
    return {"format": FORMAT, "tvd": distance, "cap": cap,
            "verdict": "selection-stable" if distance <= cap
            else "selection-drifted"}


def decisions():
    """The two decisions, and what a new tool may touch."""
    return {"format": FORMAT,
            "initiate": "reuse: the shared judgement that evidence is insufficient",
            "select": "protect: the direction that names an existing tool",
            "verdict": "two-decisions"}


def cost(record):
    """Full retraining against adapter-level extension."""
    r = record or {}
    tools = int(r.get("tools") or 0)
    retrain = _num(r.get("retrain_cost"))
    adapter = _num(r.get("adapter_cost"))
    if tools <= 0 or retrain is None or adapter is None:
        return {"format": FORMAT, "verdict": "insufficient-input"}
    full = tools * retrain
    incremental = tools * adapter
    return {"format": FORMAT, "full": full, "incremental": incremental,
            "ratio": full / incremental if incremental else None,
            "verdict": "adapter-cheaper" if incremental < full
            else "retraining-cheaper"}


def admit(record):
    """The extension gate: verified data, retention, gain, stability, no teacher."""
    r = record or {}
    reasons = []
    if int(r.get("trajectories") or 0) < int(r.get("min_trajectories")
                                              or MIN_TRAJECTORIES):
        reasons.append("too-few-verified-trajectories")
    if r.get("retention_holds") is not True:
        reasons.append("retention-broken")
    if r.get("gain_positive") is not True:
        reasons.append("no-new-capability")
    if r.get("selection_stable") is not True:
        reasons.append("selection-drifted")
    if r.get("teacher_used") is True:
        reasons.append("teacher-not-allowed")
    if r.get("old_panel") is not True:
        reasons.append("no-retention-panel")
    return {"format": FORMAT, "reasons": reasons,
            "verdict": "admitted" if not reasons else "refused"}


def audit(record):
    """The six misreadings the paper names, each as a finding."""
    r = record or {}
    findings = []
    if r.get("one_decision") is True:
        findings.append({"kind": "one-decision",
                         "why": "initiating and selecting are separate decisions"})
    if r.get("keeps_no_old_panel") is True:
        findings.append({"kind": "keeps-no-old-panel",
                         "why": "retention is measured against the existing tools"})
    if r.get("trains_without_verifier") is True:
        findings.append({"kind": "trains-without-verifier",
                         "why": "unverified attempts teach the wrong invocation"})
    if r.get("teacher_is_required") is True:
        findings.append({"kind": "teacher-is-required",
                         "why": "the tool's own annotations supply the signal"})
    if r.get("ignores_selection_drift") is True:
        findings.append({"kind": "ignores-selection-drift",
                         "why": "a new tool can quietly retake existing choices"})
    if r.get("cost_is_per_tool") is True:
        findings.append({"kind": "cost-is-per-tool",
                         "why": "retraining cost grows with every tool"})
    if not findings:
        findings.append({"kind": "audit-conditions-met"})
    return {"format": FORMAT, "findings": findings, "verdict": "audit-complete"}


def advise(profile):
    """Map a harness profile onto the paper's failure modes."""
    p = profile or {}
    have = {str(k) for k, v in p.items() if v}
    checks = (
        ("separates_initiation_from_selection", "one_tool_score",
         "a tool can be called at the right time and chosen wrongly"),
        ("verifies_trajectories_before_training", "trains_on_attempts",
         "an unverified attempt teaches the wrong call"),
        ("keeps_a_retention_panel", "measures_the_new_tool_only",
         "the old tools are the thing at risk"),
        ("bounds_selection_drift", "accepts_any_shift",
         "a new tool can retake existing choices silently"),
        ("uses_the_tools_own_annotations", "needs_a_teacher_model",
         "the annotation is the supervision"),
        ("prices_extension_per_tool", "prices_one_retrain",
         "the cost grows with every added tool"),
    )
    findings = []
    for key, kind, why in checks:
        if key not in have:
            findings.append({"kind": kind, "why": why})
    return {"format": FORMAT, "findings": findings}
