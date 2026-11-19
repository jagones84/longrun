#!/usr/bin/env python3
"""Experiment ledger — judge the process, not only the best score.

Source: arXiv:2611.23678, "Evaluating Governed LLM-Driven ML Experimentation"
(round 145). A benchmark score says nothing about how it was reached: which
files the agent touched, whether failed trials were kept, and whether each
keep/discard decision traces to its evidence (`governed_ml_experimentation_2611.23678.txt:8`,
`:17`). The control plane — not the proposing manager — owns the trial
lifecycle, the scope check, the keep/discard decision and one append-only
ledger record per trial (`:22`, `:27`, `:108`).

  * **five desiderata**: bounded edit scope, complete attempt accounting,
    independent adjudication, provenance linkage, recomputability (`:156`).
  * **the lifecycle invariant**: for every budget slot that enters executing,
    exactly one terminal record — kept, discarded or failed_invalid — is
    appended before the next slot opens; no slot skipped, no record overwritten
    (`:296`, `:300`).
  * **guards fire before the worker**: the editable whitelist, the no-op check
    and the precondition check (`:1214`, `:1221`, `:1600`).
  * **failed and discarded are different**: a valid non-improvement is
    discarded, not failed_invalid (`:1682`, `:1694`).
  * **measured**: provenance completeness is 100% on every node and design by
    construction; an ungoverned loop kept no record of 43 of 50 trials, while
    the governed ledger recorded all 50 (`:34`, `:101`, `:571`).
  * **honest negatives**: the AUC gain stays inside the seed interval, the
    memory effect is node-specific, and the structural relabeller (kappa 0.830)
    is a consistency check, not a human study (`:499`, `:657`, `:670`).

  * `scope(row)` — the editable whitelist and the frozen blocklist, pre-run.
  * `noop(row)` — a byte-identical patch never reaches training.
  * `precondition(row)` — a malformed proposal is classified, not executed.
  * `decide(row)` — the control-plane keep/discard/fail rule.
  * `ledger(records)` — the one-terminal-record invariant, replayed.
  * `metrics(records)` — acceptance, invalid, provenance and artifact rates.
  * `repeated(proposals)` — the repeated-bad rate with its similarity threshold.
  * `counterfactual(pairs)` — what an ungoverned ledger silently drops.
  * `relabel(rows)` — structural agreement (Cohen's kappa) as a check.
  * `taxonomy()` — each failure category, where it fires and which guard owns it.
  * `audit(record)` — the misreadings the ledger exists to prevent.
  * `advise(profile)` — map a harness profile onto the paper's failure modes.

Pure: proposals and records in; decisions, ledgers and rates out.
"""
from __future__ import annotations

import re

FORMAT = "longrun-experiment-ledger/1"

STATES = ("pending", "executing", "kept", "discarded", "failed_invalid")
TERMINAL = ("kept", "discarded", "failed_invalid")
CATEGORIES = ("invalid_edit_scope", "no_op_patch", "proposal_precondition_failed",
              "runtime_error", "invalid_config", "metric_missing", "edit_failed",
              "degraded_metric")
DESIDERATA = ("bounded_edit_scope", "complete_attempt_accounting",
              "independent_adjudication", "provenance_linkage", "recomputability")
PROVENANCE_IDS = ("proposal", "patch", "run", "metric", "decision")
DIRECTION_WORDS = ("increase", "raise", "decrease", "reduce", "lower")

_TAXONOMY = (
    {"category": "invalid_edit_scope", "fires_at": "pre-run",
     "guard": "scope validator", "meaning": "a frozen or unlisted path was touched"},
    {"category": "no_op_patch", "fires_at": "pre-run",
     "guard": "no-op guard", "meaning": "the patch is byte-identical to the file"},
    {"category": "proposal_precondition_failed", "fires_at": "pre-run",
     "guard": "precondition check", "meaning": "the proposal is malformed"},
    {"category": "runtime_error", "fires_at": "post-run",
     "guard": "exit check", "meaning": "the worker exited non-zero"},
    {"category": "invalid_config", "fires_at": "post-run",
     "guard": "node validator", "meaning": "an in-scope value is outside its domain"},
    {"category": "metric_missing", "fires_at": "post-run",
     "guard": "metric parser", "meaning": "the run finished with no parseable metric"},
    {"category": "edit_failed", "fires_at": "post-run",
     "guard": "worker path", "meaning": "a produced patch did not apply cleanly"},
    {"category": "degraded_metric", "fires_at": "post-run",
     "guard": "decision rule", "meaning": "valid run, no improvement: discarded"},
)


def _token_set(text):
    return {t for t in re.split(r"[^a-z0-9_]+", str(text or "").lower()) if t}


def _within(path, roots):
    path = str(path or "")
    for root in roots or []:
        root = str(root or "")
        if path == root or path.startswith(root.rstrip("/") + "/"):
            return True
    return False


def scope(row):
    """The pre-run edit-scope guard: whitelist plus frozen blocklist."""
    r = row or {}
    editable = [str(p) for p in (r.get("editable_paths") or [])]
    frozen = [str(p) for p in (r.get("frozen_paths") or [])]
    touched = [str(p) for p in (r.get("touched") or [])]
    violations = []
    for path in touched:
        if _within(path, frozen):
            violations.append({"path": path, "reason": "frozen"})
        elif editable and not _within(path, editable):
            violations.append({"path": path, "reason": "not-editable"})
    return {"format": FORMAT, "touched": touched, "violations": violations,
            "verdict": "scope-clear" if not violations else "invalid_edit_scope"}


def noop(row):
    """A byte-identical patch is rejected before training."""
    r = row or {}
    patch = str(r.get("patch_hash") or "")
    baseline = str(r.get("baseline_hash") or "")
    empty = r.get("patch_empty") is True or not (r.get("touched") or [])
    if empty:
        return {"format": FORMAT, "verdict": "no_op_patch", "why": "empty-patch"}
    if patch and baseline and patch == baseline:
        return {"format": FORMAT, "verdict": "no_op_patch", "why": "identical-to-baseline"}
    return {"format": FORMAT, "verdict": "patch-materialised"}


def precondition(row):
    """A malformed proposal is classified rather than executed."""
    r = row or {}
    missing = [key for key in ("summary", "param", "new_value")
               if r.get(key) in (None, "")]
    same = r.get("old_value") is not None and r.get("new_value") == r.get("old_value")
    reasons = []
    if missing:
        reasons.append("missing-fields")
    if same:
        reasons.append("new-equals-old")
    return {"format": FORMAT, "missing": missing, "reasons": reasons,
            "verdict": "proposal_precondition_failed" if reasons
            else "precondition-ok"}


def decide(row):
    """The control-plane keep/discard/fail decision; the manager is not asked."""
    r = row or {}
    if r.get("valid") is False:
        return {"format": FORMAT, "decision": "failed_invalid",
                "failure_category": str(r.get("category") or "runtime_error"),
                "verdict": "failed-invalid"}
    candidate = r.get("candidate")
    best = r.get("best")
    if candidate is None:
        return {"format": FORMAT, "decision": "failed_invalid",
                "failure_category": "metric_missing", "verdict": "failed-invalid"}
    direction = str(r.get("direction") or "maximize")
    try:
        improves = (float(candidate) < float(best) if direction == "minimize"
                    else float(candidate) > float(best))
    except (TypeError, ValueError):
        return {"format": FORMAT, "decision": "failed_invalid",
                "failure_category": "metric_missing", "verdict": "failed-invalid"}
    if improves:
        return {"format": FORMAT, "decision": "kept", "best": candidate,
                "verdict": "kept"}
    return {"format": FORMAT, "decision": "discarded",
            "failure_category": "degraded_metric", "verdict": "discarded"}


def ledger(records):
    """Replay the one-terminal-record invariant over a campaign."""
    rows = [r or {} for r in (records or [])]
    terminal = [r for r in rows if r.get("decision") in TERMINAL]
    open_slots = [r.get("trial_id") for r in rows
                  if r.get("decision") not in TERMINAL]
    seen, duplicates = {}, []
    for r in terminal:
        tid = str(r.get("trial_id") or "")
        if tid in seen:
            duplicates.append(tid)
        seen[tid] = r
    indices = sorted(int(r.get("budget_index") or 0) for r in terminal)
    slots = int(max(indices) if indices else (len(rows)))
    skipped = [i for i in range(1, slots + 1) if i not in set(indices)]
    best, monotone = None, True
    for r in sorted(terminal, key=lambda x: int(x.get("budget_index") or 0)):
        if r.get("decision") != "kept":
            continue
        value = r.get("metric")
        try:
            value = float(value)
        except (TypeError, ValueError):
            continue
        if best is not None and value < best:
            monotone = False
        best = value if best is None else max(best, value)
    violations = []
    if open_slots:
        violations.append({"kind": "slot-open", "trials": open_slots})
    if duplicates:
        violations.append({"kind": "record-overwritten", "trials": duplicates})
    if skipped:
        violations.append({"kind": "slot-skipped", "slots": skipped})
    if not monotone:
        violations.append({"kind": "best-not-monotone"})
    completeness = (len(terminal) / slots) if slots else 0.0
    return {"format": FORMAT, "records": len(rows), "terminal": len(terminal),
            "slots": slots, "completeness": completeness, "violations": violations,
            "verdict": "ledger-complete" if not violations else "ledger-incomplete"}


def metrics(records):
    """Acceptance, invalid, provenance and artifact-reference rates."""
    rows = [r or {} for r in (records or [])]
    n = len(rows)
    kept = sum(1 for r in rows if r.get("decision") == "kept")
    invalid = sum(1 for r in rows if r.get("decision") == "failed_invalid")
    proven = 0
    for r in rows:
        ids = r.get("provenance") or {}
        if all(ids.get(name) for name in PROVENANCE_IDS):
            proven += 1
    materialised = [r for r in rows if r.get("decision") in ("kept", "discarded")]
    referenced = sum(1 for r in materialised
                     if r.get("patch_ref") and r.get("raw_log_ref"))
    return {"format": FORMAT, "trials": n,
            "acceptance_rate": kept / n if n else 0.0,
            "invalid_rate": invalid / n if n else 0.0,
            "provenance_completeness": proven / n if n else 0.0,
            "artifact_reference_coverage": (referenced / len(materialised)
                                            if materialised else 0.0),
            "verdict": "governance-measured" if n else "no-trials"}


def repeated(proposals, theta=0.6):
    """Repeated-bad rate: same target and direction as a prior rejected trial."""
    rows = [p or {} for p in (proposals or [])]
    flagged = []
    for i, row in enumerate(rows):
        target = str(row.get("target") or "")
        direction = str(row.get("direction") or "").lower()
        tokens = _token_set(row.get("summary"))
        hit = False
        for prior in rows[:i]:
            if (str(prior.get("target") or "") != target
                    or str(prior.get("direction") or "").lower() != direction):
                continue
            if prior.get("decision") not in ("discarded", "failed_invalid"):
                continue
            if row.get("references_rejection") is True:
                continue
            other = _token_set(prior.get("summary"))
            union = tokens | other
            jaccard = (len(tokens & other) / len(union)) if union else 0.0
            if jaccard >= theta:
                hit = True
                break
        if hit:
            flagged.append(i)
    n = len(rows)
    return {"format": FORMAT, "trials": n, "repeated_bad": len(flagged),
            "rate": len(flagged) / n if n else 0.0,
            "flagged": flagged, "theta": theta,
            "verdict": "repeated-bad-rate-measured" if n else "no-trials"}


def counterfactual(pairs):
    """Ledger completeness, governed against ungoverned, per node."""
    rows = []
    for pair in pairs or []:
        p = pair or {}
        ran = int(p.get("ran") or 0)
        governed = int(p.get("governed_records") or 0)
        ungoverned = int(p.get("ungoverned_records") or 0)
        rows.append({"node": str(p.get("node") or ""), "ran": ran,
                     "governed": governed / ran if ran else 0.0,
                     "ungoverned": ungoverned / ran if ran else 0.0,
                     "silent_drops": max(0, ran - ungoverned)})
    drops = sum(r["silent_drops"] for r in rows)
    ran = sum(r["ran"] for r in rows)
    return {"format": FORMAT, "rows": rows, "silent_drops": drops, "ran": ran,
            "ungoverned_completeness": (1.0 - drops / ran) if ran else 0.0,
            "verdict": "ungoverned-drops-failures" if drops
            else "both-ledgers-complete"}


def relabel(rows):
    """Cohen's kappa between control-plane labels and a structural relabeller."""
    pairs = [(str((r or {}).get("assigned") or ""),
              str((r or {}).get("observable") or "")) for r in (rows or [])]
    n = len(pairs)
    if not n:
        return {"format": FORMAT, "kappa": None, "verdict": "no-records"}
    agree = sum(1 for a, b in pairs if a == b)
    labels = {a for a, _ in pairs} | {b for _, b in pairs}
    expected = 0.0
    for label in labels:
        pa = sum(1 for a, _ in pairs if a == label) / n
        pb = sum(1 for _, b in pairs if b == label) / n
        expected += pa * pb
    observed = agree / n
    kappa = 1.0 if expected >= 1.0 else (observed - expected) / (1.0 - expected)
    if kappa >= 0.80:
        band = "almost-perfect"
    elif kappa >= 0.60:
        band = "substantial"
    elif kappa >= 0.40:
        band = "moderate"
    else:
        band = "weak"
    return {"format": FORMAT, "records": n, "observed": observed,
            "expected": expected, "kappa": kappa, "band": band,
            "verdict": "structural-agreement" if kappa >= 0.60
            else "structural-disagreement"}


def taxonomy():
    """Every failure category with its detection point and owning guard."""
    return {"format": FORMAT, "categories": [dict(row) for row in _TAXONOMY],
            "verdict": "taxonomy-complete"}


def audit(record):
    """The misreadings a governed ledger exists to prevent."""
    r = record or {}
    findings = []
    if r.get("score_only") is True:
        findings.append({"kind": "score-only",
                         "why": "the best score says nothing about how it was reached"})
    if r.get("discard_as_failure") is True:
        findings.append({"kind": "discard-treated-as-failure",
                         "why": "a valid non-improvement is a normal exploration outcome"})
    if r.get("ledger_in_the_loop") is True:
        findings.append({"kind": "ledger-owned-by-the-agent",
                         "why": "an agent that writes its own ledger can omit its failures"})
    if r.get("posthoc_scope_filter") is True:
        findings.append({"kind": "post-hoc-scope-filter",
                         "why": "the whitelist is a precondition guard, not a filter after training"})
    if r.get("unverified_reset") is True:
        findings.append({"kind": "unverified-reset",
                         "why": "an ablation whose arms start from different states ranks nothing"})
    if r.get("success_as_completion") is True:
        findings.append({"kind": "success-as-completion",
                         "why": "failed and empty runs receive no safe-completion credit"})
    if r.get("completeness_claimed_not_structural") is True:
        findings.append({"kind": "completeness-claimed-not-structural",
                         "why": "completeness must follow from the invariant, not from a lucky run"})
    if not findings:
        findings.append({"kind": "audit-conditions-met"})
    return {"format": FORMAT, "findings": findings}


def advise(profile):
    """Map a harness profile onto the paper's failure modes."""
    p = profile or {}
    have = {str(k) for k, v in p.items() if v}
    checks = (
        ("has_a_control_plane", "the_agent_owns_its_lifecycle",
         "proposal, execution, validation and keep/discard need separate authority"),
        ("enforces_edit_scope_before_running", "checks_scope_after_training",
         "a post-hoc filter has already let a frozen file change"),
        ("appends_one_record_per_slot", "logs_only_successes",
         "the failures are the record; without them a campaign looks empty"),
        ("guards_against_mid_trial_crashes", "assumes_clean_runs",
         "a pending guard turns a crash into an auditable record"),
        ("keeps_failed_and_discarded_distinct", "one_failure_bucket",
         "a bad proposal and a bad outcome need different responses"),
        ("records_provenance_ids", "stores_a_summary_only",
         "each keep or discard must trace to its evidence"),
        ("measures_repeated_bad_proposals", "accepts_repeats",
         "a manager that repeats a rejected edit wastes the budget"),
        ("verifies_the_start_state", "trusts_the_reset",
         "an arm that inherits the previous arm's state is not a replicate"),
    )
    findings = []
    for key, kind, why in checks:
        if key not in have:
            findings.append({"kind": kind, "why": why})
    return {"format": FORMAT, "findings": findings}
