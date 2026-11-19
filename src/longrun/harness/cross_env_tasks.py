#!/usr/bin/env python3
"""Cross-environment tasks — a workflow that spans services needs joint verification.

Source: arXiv:2611.22777, "CrossEnv: Synthesizing Verifiable Cross-Environment
Tasks for Long-Horizon Agent Training" (round 134). Real long-horizon workflows
cross services, and an action in one service depends on information from another
(`crossenv_verifiable_tasks_2611.22777.md:46`).

  * **the unit is (environments, instruction, joint initial state, reference
    execution, verification rules)**, and completion requires every rule to pass
    over tool outputs and final states (`:97`, `:101`).
  * **data consistency is the hard part**: the same hotel may have different
    addresses in the booking and navigation environments, so records are aligned
    across environments before the task is executable (`:50`, `:125`).
  * **rules come from the objective and the reference execution**, and negative
    cases (an omitted operation, a wrong value) test that the rules reject
    incomplete outcomes (`:129`).
  * **a task is retained only if reference replay passes and at least two of
    five agent attempts succeed** (`:133`).
  * **the curriculum is structural**: L1 single environment (SFT), L2 two
    environments in one domain, L3 three or more in one domain, L4 across
    domains, L5 adds user interaction; curriculum beats mixed training at
    matched GPU-hours (`:137`, `:209`).
  * **measured**: 2,954 training records — about a quarter of EnvScaler's —
    reach 23.6 on Claw-Eval and 14.0 on VitaBench at 8B, and unseen environment
    combinations gain +16.0 success (`:161`, `:201`, `:228`).

  * `task(spec)` — a task that actually spans environments.
  * `align(records)` — cross-environment data consistency.
  * `rules(task)` — executable rules and the negative cases that test them.
  * `validate(row)` — replay plus agent attempts.
  * `curriculum(levels)` — the structural progression.
  * `measure(rows)` — records vs baselines, gains and unseen-combination transfer.
  * `advise(profile)` — map a harness profile onto the paper's failure modes.

Pure: task specifications and result rows in; findings out.
"""
from __future__ import annotations

FORMAT = "longrun-cross-env-tasks/1"


def _text(value):
    return str(value).strip() if value is not None else ""


def task(spec):
    """A cross-environment task: two or more environments, shared entity, joint rules."""
    s = spec or {}
    envs = [str(e) for e in (s.get("environments") or ())]
    findings = []
    if len(envs) < 2:
        findings.append({"kind": "single-environment",
                         "why": "a cross-environment task uses tools in at least two environments"})
    if not s.get("shared_entity"):
        findings.append({"kind": "no-shared-entity",
                         "why": "environments are connected through a shared entity type"})
    if not s.get("dependency"):
        findings.append({"kind": "no-dependency",
                         "why": "completion must use information from one environment in another"})
    if s.get("joint_verification") is not True:
        findings.append({"kind": "no-joint-verification",
                         "why": "independent checks do not verify the cross-environment requirement"})
    if not s.get("reference_execution"):
        findings.append({"kind": "no-reference-execution",
                         "why": "the reference run specifies the expected outcomes"})
    return {"format": FORMAT, "environments": len(envs), "findings": findings}


def align(records):
    """The same entity must agree across environments, and not pre-empt the agent's work."""
    rows = list(records or ())
    findings = []
    if not rows:
        return {"format": FORMAT, "findings": [{"kind": "no-records"}]}
    by_key = {}
    for r in rows:
        key = (_text(r.get("entity")), _text(r.get("id")))
        by_key.setdefault(key, []).append(r)
    for key, group in by_key.items():
        values = {_text(r.get("value")) for r in group if _text(r.get("value"))}
        if len(values) > 1:
            findings.append({"kind": "inconsistent-entity", "entity": key[0], "id": key[1],
                             "values": sorted(values),
                             "why": "the same record differs across environments"})
    if any(r.get("must_create") is True and r.get("present_initial") is True for r in rows):
        findings.append({"kind": "premature-record",
                         "why": "a record the agent must create is already in the initial state"})
    if any(r.get("required") is True and r.get("present_initial") is False
           and r.get("produced_earlier") is False for r in rows):
        findings.append({"kind": "missing-record",
                         "why": "a required record exists neither initially nor from an earlier action"})
    return {"format": FORMAT, "entities": len(by_key), "findings": findings}


def rules(task_spec):
    """Rules are executable and cover outputs, state and cross-environment consistency."""
    t = task_spec or {}
    rows = list(t.get("rules") or ())
    findings = []
    if not rows:
        return {"format": FORMAT, "findings": [{"kind": "no-rules"}]}
    covered = {str(r.get("checks")) for r in rows}
    for kind in ("output", "state", "cross-env"):
        if kind not in covered:
            findings.append({"kind": "rule-checks-%s-missing" % kind,
                             "why": "a joint task needs rules over outputs, state and the cross-environment link"})
    if any(r.get("executable") is False for r in rows):
        findings.append({"kind": "rules-not-executable",
                         "why": "a rule that is not executable cannot verify a task"})
    if t.get("negative_cases") is not True:
        findings.append({"kind": "negative-case-missing",
                         "why": "an omitted operation must be rejected by the rules"})
    if t.get("rules_reject_incomplete") is False:
        findings.append({"kind": "rules-accept-incomplete",
                         "why": "rules that pass an incomplete outcome do not verify the objective"})
    return {"format": FORMAT, "rules": len(rows), "covered": sorted(covered),
            "findings": findings}


def validate(row):
    """A task survives only with a reproducible replay and real agent attempts."""
    r = row or {}
    findings = []
    if r.get("reference_replay") is not True:
        findings.append({"kind": "reference-replay-failed",
                         "why": "the reference execution must reproduce and pass every rule"})
    attempts = int(r.get("agent_attempts") or 0)
    successes = int(r.get("agent_successes") or 0)
    if successes < 2:
        findings.append({"kind": "agent-attempts-insufficient",
                         "successes": successes, "attempts": attempts,
                         "why": "the paper retains a task only when at least two of five attempts succeed"})
    if not findings:
        findings.append({"kind": "accepted"})
    return {"format": FORMAT, "findings": findings}


def curriculum(levels):
    """L1 single env → L2 two → L3 three+ → L4 cross-domain → L5 user interaction."""
    rows = list(levels or ())
    findings = []
    if not rows:
        return {"format": FORMAT, "findings": [{"kind": "no-levels"}]}
    ordered = sorted(rows, key=lambda r: int(r.get("level") or 0))
    prev_env = 0
    for r in ordered:
        envs = int(r.get("environments") or 0)
        if envs < prev_env:
            findings.append({"kind": "non-monotone-curriculum", "level": r.get("level"),
                             "why": "environment count should not fall as the level rises"})
        prev_env = envs
    if ordered and int(ordered[0].get("environments") or 0) > 1:
        findings.append({"kind": "no-single-environment-foundation",
                         "why": "basic tool use is taught before coordination"})
    if any(r.get("user_interaction") is True for r in ordered[:-1]):
        findings.append({"kind": "user-interaction-too-early",
                         "why": "user interaction is introduced after the structural levels"})
    if any(r.get("retention_checked") is not True for r in ordered):
        findings.append({"kind": "retention-unchecked",
                         "why": "earlier tool-use skill must be shown to survive later stages"})
    return {"format": FORMAT, "levels": len(ordered), "findings": findings}


def measure(rows):
    """Fewer records can win; unseen combinations and longer workflows test transfer."""
    data = list(rows or ())
    findings = []
    if not data:
        return {"format": FORMAT, "findings": [{"kind": "no-measurement"}]}
    ours = [r for r in data if r.get("arm") == "crossenv" and r.get("score") is not None]
    base = [r for r in data if r.get("arm") == "baseline" and r.get("score") is not None]
    if ours and base:
        best_ours = max(ours, key=lambda r: r["score"])
        best_base = max(base, key=lambda r: r["score"])
        records = min((r.get("records") for r in ours if r.get("records")), default=None)
        base_records = min((r.get("records") for r in base if r.get("records")), default=None)
        if records and base_records and records < base_records and best_ours["score"] >= best_base["score"]:
            findings.append({"kind": "fewer-records-wins", "records": records,
                             "baseline_records": base_records})
        elif best_ours["score"] > best_base["score"]:
            findings.append({"kind": "cross-env-wins"})
    unseen = [r for r in data if r.get("pair") == "unseen" and r.get("success_delta") is not None]
    if unseen and max(r["success_delta"] for r in unseen) > 0:
        findings.append({"kind": "unseen-transfer",
                         "delta": max(r["success_delta"] for r in unseen)})
    cur = [r for r in data if r.get("arm") == "curriculum" and r.get("success") is not None]
    mix = [r for r in data if r.get("arm") == "mixed" and r.get("success") is not None]
    if cur and mix:
        matched = all(any(m.get("gpu_hours") == c.get("gpu_hours") for m in mix) for c in cur)
        if matched and sum(c["success"] for c in cur) / len(cur) > sum(m["success"] for m in mix) / len(mix):
            findings.append({"kind": "curriculum-beats-mixed",
                             "why": "same compute, higher success at every level"})
    return {"format": FORMAT, "findings": findings}


def advise(profile):
    """Map a harness profile onto the paper's failure modes."""
    p = profile or {}
    have = {str(k) for k, v in p.items() if v}
    findings = []
    checks = (
        ("synthesizes_cross_env", "single-env-only", "real workflows cross services"),
        ("aligns_data", "inconsistent-records", "the same entity must agree across environments"),
        ("generates_rules", "no-verification", "a joint task needs executable rules"),
        ("tests_negative_cases", "rules-unproven", "an omitted operation must be rejected"),
        ("validates_by_replay", "replay-unchecked", "the reference execution must reproduce"),
        ("sequences_curriculum", "mixed-training", "structure the progression from one environment to many"),
    )
    for key, kind, why in checks:
        if key not in have:
            findings.append({"kind": kind, "why": why})
    return {"format": FORMAT, "findings": findings}
