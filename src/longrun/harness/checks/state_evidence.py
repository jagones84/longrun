#!/usr/bin/env python3
"""State–evidence handoff — carry the interpretation, keep the proof addressable.

Source: arXiv:2611.24357, "Semantic Context Handoff" (round 147). Full-history
prompting keeps every action and observation, so the prompt grows and buries
what matters; irreversible summarisation keeps a conclusion after discarding the
observations needed to revise it (`semantic_context_handoff_2611.24357.txt:21`,
`:47`, `:49`). SCH separates two objects: a compact semantic state and an
append-only evidence archive (`:27`, `:90`).

  * **the state is deliberately not self-sufficient**: constraints, facts,
    hypotheses, work items and a phase, with support/lineage links into the
    archive (`:199`, `:211`, `:246`).
  * **the model proposes a sparse delta**, and a deterministic controller owns
    reconciliation (`:217`, `:223`, `:225`).
  * **acknowledgement changes visibility, not storage** (`:255`, `:884`).
  * **revision re-opens completed work**: a recognised failure with revisable
    state, or an explicit retraction/reopen, makes completed-work provenance
    eligible again (`:263`, `:266`).
  * **recovery is ranked**: direct support and lineage, then revision-activated
    provenance, then orphan (path/term overlap), recent and safety records
    (`:280`, `:288`).
  * **measured**: revision-aware recovery moves Pass@1 from 80.00% to 86.89% at
    matched tokens and time (paired 15-4, 14-4, 14-4; p = .0192, .0309, .0309),
    and the complete system uses 43.3% fewer tokens and 40.8% less time than the
    strongest baseline (`:411`, `:415`, `:468`).
  * **honest negatives**: pending evidence is uncapped, so the paper claims
    bounded replay, not a bounded prompt (`:936`); provenance preserves
    addressability, not entailment (`:872`); breadth settings are single-run.

  * `state(entries)` — the typed state and its integrity.
  * `apply_delta(row)` — deterministic reconciliation of a sparse delta.
  * `acknowledge(row)` — visibility leaves, storage stays.
  * `recover(row)` — ranked recovery under caps, with revision.
  * `locality(rows)` — how far back the replayed evidence reaches.
  * `budget(row)` — bounded replay against an unbounded pending tail.
  * `paired(row)` — exact McNemar on the paired task outcomes.
  * `benefit(rows)` — pass, token and time deltas against a baseline.
  * `audit(record)` — the six misreadings the paper names.
  * `advise(profile)` — map a harness profile onto the paper's failure modes.

Pure: states, deltas and archives in; reconciled state and verdicts out.
"""
from __future__ import annotations

import math

FORMAT = "longrun-state-evidence/1"

WORK_STATES = ("open", "blocked", "completed")
PHASES = ("inspect", "implement", "verify", "submit")
DELTA_OPS = ("add_fact", "revise_fact", "drop_fact", "add_hypothesis",
             "open_work", "complete_work", "block_work", "reopen_work",
             "acknowledge")
DEFAULTS = {"steps": 12, "safety": 6, "recent": 3, "orphan": 4, "revision": 6}


def _num(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def state(entries):
    """A typed semantic state: unique ids, valid status, references named."""
    rows = [e or {} for e in (entries or [])]
    seen, duplicates, bad_kind, bad_status = set(), [], [], []
    counts = {"constraint": 0, "fact": 0, "hypothesis": 0, "work": 0}
    for i, row in enumerate(rows):
        eid = str(row.get("id") or "")
        if eid in seen:
            duplicates.append(eid)
        seen.add(eid)
        kind = str(row.get("kind") or "")
        if kind in counts:
            counts[kind] += 1
        else:
            bad_kind.append(eid or "#%d" % i)
        if kind == "work" and str(row.get("status") or "") not in WORK_STATES:
            bad_status.append(eid or "#%d" % i)
    verdict = ("state-valid" if not duplicates and not bad_kind and not bad_status
               else "state-invalid")
    return {"format": FORMAT, "entries": len(rows), "counts": counts,
            "duplicates": duplicates, "bad_kind": bad_kind,
            "bad_status": bad_status, "verdict": verdict}


def apply_delta(row):
    """Reconcile a sparse delta against the state and the evidence archive."""
    r = row or {}
    entries = {str(e.get("id")): dict(e) for e in (r.get("state") or [])}
    evidence = {str(e) for e in (r.get("evidence_ids") or [])}
    delta = r.get("delta") or {}
    ops = delta.get("ops") or []
    rejected, applied = [], []
    for op in ops:
        o = op or {}
        kind = str(o.get("op") or "")
        target = str(o.get("id") or "")
        support = [str(x) for x in (o.get("support") or [])]
        reason = ""
        if kind not in DELTA_OPS:
            reason = "unknown-op"
        elif any(s not in evidence for s in support):
            reason = "unknown-evidence"
        elif kind in ("add_fact", "add_hypothesis", "open_work"):
            if not target:
                reason = "missing-id"
            elif target in entries:
                reason = "duplicate-id"
            else:
                entries[target] = {"id": target,
                                   "kind": {"add_fact": "fact",
                                            "add_hypothesis": "hypothesis",
                                            "open_work": "work"}[kind],
                                   "status": "open" if kind == "open_work" else None,
                                   "support": support}
        elif target not in entries:
            reason = "unknown-id"
        elif kind == "revise_fact":
            if entries[target].get("kind") != "fact":
                reason = "not-a-fact"
            else:
                entries[target]["support"] = support or entries[target].get("support", [])
        elif kind == "drop_fact":
            if entries[target].get("kind") != "fact":
                reason = "not-a-fact"
            else:
                entries.pop(target)
        elif kind in ("complete_work", "block_work", "reopen_work"):
            item = entries[target]
            if item.get("kind") != "work":
                reason = "not-work"
            elif kind == "complete_work" and not support and not item.get("support"):
                reason = "completion-without-evidence"
            elif kind == "reopen_work" and item.get("status") not in ("completed", "blocked"):
                reason = "reopen-not-closed"
            else:
                item["status"] = {"complete_work": "completed",
                                  "block_work": "blocked",
                                  "reopen_work": "open"}[kind]
                if support:
                    item["support"] = support
        elif kind == "acknowledge":
            if target not in entries:
                reason = "unknown-id"
        if reason:
            rejected.append({"op": kind, "id": target, "reason": reason})
        else:
            applied.append({"op": kind, "id": target})
    return {"format": FORMAT, "applied": applied, "rejected": rejected,
            "state": list(entries.values()),
            "verdict": "delta-applied" if not rejected else "delta-rejected"}


def acknowledge(row):
    """Acknowledgement removes visibility; the archive keeps the record."""
    r = row or {}
    pending = [str(x) for x in (r.get("pending") or [])]
    acked = {str(x) for x in (r.get("acknowledge") or [])}
    archive = [str(x) for x in (r.get("archive") or [])]
    still_pending = [step for step in pending if step not in acked]
    kept = set(archive) | acked
    return {"format": FORMAT, "pending": still_pending, "archived": sorted(kept),
            "acknowledged": sorted(acked),
            "verdict": "visibility-not-deletion" if acked <= kept
            else "storage-lost"}


def recover(row):
    """Ranked evidence recovery: support, revision, orphan, safety, recent."""
    r = row or {}
    evidence = [e or {} for e in (r.get("evidence") or [])]
    by_step = {str(e.get("step")): e for e in evidence}
    state_rows = [e or {} for e in (r.get("state") or [])]
    pending = {str(x) for x in (r.get("pending") or [])}
    revision = r.get("revision") is True
    caps = dict(DEFAULTS)
    caps.update({k: int(v) for k, v in (r.get("caps") or {}).items()})
    active_ids = {str(e.get("id")) for e in state_rows
                  if e.get("status") in (None, "open", "blocked")}
    completed_ids = {str(e.get("id")) for e in state_rows
                     if e.get("status") == "completed"}
    candidates, routes = {}, {"support": [], "revision": [], "orphan": [],
                              "safety": [], "recent": []}
    terms = {str(t).lower() for t in (r.get("terms") or [])}
    paths = {str(p) for p in (r.get("paths") or [])}

    def add(step, route, priority):
        if step in pending:
            return
        if step not in candidates:
            candidates[step] = priority
            routes[route].append(step)

    for item in state_rows:
        if str(item.get("id")) not in active_ids:
            continue
        for step in item.get("support") or []:
            add(str(step), "support", 1)
    if revision:
        for item in state_rows:
            if str(item.get("id")) not in completed_ids:
                continue
            for step in item.get("support") or []:
                add(str(step), "revision", 2)
    for e in evidence:
        step = str(e.get("step"))
        score = 0
        if str(e.get("path") or "") in paths:
            score += 1
        score += len({str(t).lower() for t in (e.get("terms") or [])} & terms)
        if score >= 2 and candidates.get(step) is None:
            add(step, "orphan", 3)
    for e in evidence:
        if e.get("safety") is True:
            add(str(e.get("step")), "safety", 4)
    ordered_steps = sorted(by_step, key=lambda s: int(s) if s.isdigit() else 0,
                           reverse=True)
    for step in ordered_steps[: caps["recent"]]:
        add(step, "recent", 5)
    limits = {"support": caps["steps"], "revision": caps["revision"],
              "orphan": caps["orphan"], "safety": caps["safety"],
              "recent": caps["recent"]}
    chosen, used = [], {route: 0 for route in limits}
    for step in sorted(candidates, key=lambda s: (candidates[s], -int(s) if s.isdigit() else 0)):
        route = next(r for r, steps in routes.items() if step in steps)
        if used[route] >= limits[route]:
            continue
        used[route] += 1
        if len(chosen) >= caps["steps"]:
            break
        chosen.append({"step": step, "route": route,
                       "priority": candidates[step]})
    return {"format": FORMAT, "selected": chosen, "routes": routes,
            "excluded_pending": sorted(pending),
            "verdict": "recovered" if chosen else "nothing-to-recover"}


def locality(rows):
    """The age of replayed evidence, in interaction steps."""
    ages = []
    for row in rows or []:
        r = row or {}
        age = _num(r.get("age"))
        if age is not None:
            ages.append(age)
    if not ages:
        return {"format": FORMAT, "verdict": "no-replays"}
    mean = sum(ages) / len(ages)
    over3 = sum(1 for a in ages if a > 3) / len(ages)
    over10 = sum(1 for a in ages if a > 10) / len(ages)
    return {"format": FORMAT, "replays": len(ages), "mean_age": mean,
            "over_three": over3, "over_ten": over10,
            "verdict": "non-local-recovery" if mean >= 5 and over10 >= 0.5
            else "local-recovery"}


def budget(row):
    """Bounded replay does not imply a bounded prompt while pending is uncapped."""
    r = row or {}
    state_chars = int(r.get("state_chars") or 0)
    replay_chars = int(r.get("replay_chars") or 0)
    pending_chars = int(r.get("pending_chars") or 0)
    state_cap = int(r.get("state_cap") or 12000)
    replay_cap = int(r.get("replay_cap") or 12000)
    steps = int(r.get("steps") or 0)
    step_cap = int(r.get("step_cap") or DEFAULTS["steps"])
    over = []
    if state_chars > state_cap:
        over.append("state")
    if replay_chars > replay_cap:
        over.append("replay")
    if steps > step_cap:
        over.append("steps")
    unbounded = pending_chars > 0 and r.get("pending_cap") is None
    if over:
        verdict = "budget-exceeded"
    elif unbounded:
        verdict = "bounded-replay-unbounded-total"
    else:
        verdict = "bounded"
    return {"format": FORMAT, "over": over, "pending_chars": pending_chars,
            "verdict": verdict}


def paired(row):
    """Exact McNemar on paired task outcomes (discordant pairs only)."""
    r = row or {}
    sch_only = int(r.get("only_a") or 0)
    active_only = int(r.get("only_b") or 0)
    n = sch_only + active_only
    if n == 0:
        return {"format": FORMAT, "p": 1.0, "verdict": "no-discordant-pairs"}
    k = min(sch_only, active_only)
    tail = sum(math.comb(n, i) for i in range(k + 1)) / (2 ** n)
    p = min(1.0, 2 * tail)
    return {"format": FORMAT, "only_a": sch_only, "only_b": active_only,
            "p": p,
            "verdict": "paired-improvement" if (sch_only > active_only and p < 0.05)
            else "paired-inconclusive"}


def benefit(rows):
    """Pass@1, tokens and wall-clock against a named baseline."""
    arms = {}
    for row in rows or []:
        r = row or {}
        name = str(r.get("arm") or "")
        values = arms.setdefault(name, {"pass": [], "tokens": [], "time": []})
        for key, field in (("pass", "pass_at_1"), ("tokens", "tokens"),
                           ("time", "time_s")):
            value = _num(r.get(field))
            if value is not None:
                values[key].append(value)
    summary = {}
    for name, values in arms.items():
        summary[name] = {key: (sum(v) / len(v) if v else None)
                         for key, v in values.items()}
    base = summary.get("baseline")
    for name, row in summary.items():
        if base and base.get("tokens") and row.get("tokens"):
            row["token_reduction"] = 1.0 - row["tokens"] / base["tokens"]
        if base and base.get("time") and row.get("time"):
            row["time_reduction"] = 1.0 - row["time"] / base["time"]
    best = max((r.get("pass") or 0.0, name) for name, r in summary.items()) \
        if summary else (0.0, "")
    return {"format": FORMAT, "arms": summary, "best": best[1],
            "verdict": "benefit-measured" if summary else "no-arms"}


def audit(record):
    """The six misreadings the paper names, each as a finding."""
    r = record or {}
    findings = []
    if r.get("summary_only") is True:
        findings.append({"kind": "summary-only",
                         "why": "a conclusion outlives the evidence needed to revise it"})
    if r.get("recency_only") is True:
        findings.append({"kind": "recency-only",
                         "why": "useful evidence is not determined by its age"})
    if r.get("deletion_as_visibility") is True:
        findings.append({"kind": "deletion-as-visibility",
                         "why": "acknowledgement must not destroy the record"})
    if r.get("provenance_as_entailment") is True:
        findings.append({"kind": "provenance-as-entailment",
                         "why": "a support link proves addressability, not truth"})
    if r.get("unbounded_pending") is True:
        findings.append({"kind": "unbounded-pending",
                         "why": "bounded replay is not a bound on the whole prompt"})
    if r.get("single_run_breadth") is True:
        findings.append({"kind": "single-run-breadth",
                         "why": "one frozen run per setting is breadth, not a paired claim"})
    if not findings:
        findings.append({"kind": "audit-conditions-met"})
    return {"format": FORMAT, "findings": findings}


def advise(profile):
    """Map a harness profile onto the paper's failure modes."""
    p = profile or {}
    have = {str(k) for k, v in p.items() if v}
    checks = (
        ("separates_state_from_evidence", "summarises_everything",
         "a compact state and an addressable archive answer different questions"),
        ("proposes_sparse_deltas", "regenerates_the_state",
         "re-emitting unchanged state invites silent edits"),
        ("keeps_state_non_self_sufficient", "claims_a_lossless_summary",
         "the state carries interpretation, not the proof"),
        ("keeps_acknowledged_evidence_addressable", "deletes_on_compaction",
         "visibility and storage are different decisions"),
        ("reopens_completed_work_on_failure", "only_recovers_active_state",
         "a revision needs provenance from work already closed"),
        ("ranks_recovery_with_fallbacks", "provenance_only",
         "orphan, recent and safety records cover what provenance misses"),
        ("accounts_for_pending_evidence", "assumes_a_prompt_bound",
         "an uncapped pending tail is where the context grows"),
    )
    findings = []
    for key, kind, why in checks:
        if key not in have:
            findings.append({"kind": kind, "why": why})
    return {"format": FORMAT, "findings": findings}
