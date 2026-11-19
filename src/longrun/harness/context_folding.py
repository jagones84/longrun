#!/usr/bin/env python3
"""Context folding — the reduced view is a selection, not a rewrite.

Source: arXiv:2611.16627, "Folio" (round 139). Long-horizon agents accumulate
tool results and replies until history no longer fits, and model-written
compaction rereads and rewrites what it replaces
(`folio_context_folding_2611.16627.md:36`, `:42`).

  * **three linked levels exist before a fold**: a turn note the model writes
    (L1), an event manifest the runtime writes (L2), and the source records (L3),
    each call named `tN.k` (`:98`, `:102`, `:106`).
  * **a fold selects views; it never redraws a sent line richer**, so the folded
    prefix stays cacheable (`:116`, `:118`).
  * **the recoverability contract**: retention, resolution and exact read after
    any number of folds (`:84`).
  * **recovery shares the fold's handles**: bounded scan, computation over the
    full text, and a dossier that survives folds (`:126`, `:130`, `:132`).
  * **the trigger prices the landing point** `S = B + L + D` and folds when the
    carried excess reaches the rebuild cost (`:138`, `:146`, `:150`).
  * **measured**: 66 of 75 tasks against 54 for the same runtime, a 7.3x
    compression, 613 ms folds and 2.4x lower cost (`:58`, `:240`).

  * `levels(record)` — the three levels and a stable handle.
  * `contract(record)` — retention, resolution and exact read.
  * `fold(turns, budget)` — the layout selection, demotion and monotonicity.
  * `trigger(requests, ...)` — the landing-priced fold decision.
  * `cost(usage, ratios)` — the normalized cost.
  * `recover(rows)` — whether folded content is reachable through handles.
  * `advise(profile)` — map a harness profile onto the paper's failure modes.

Pure: history records in; findings out.
"""
from __future__ import annotations

FORMAT = "longrun-context-folding/1"

LEVELS = ("l1", "l2", "l3")


def _num(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def levels(record):
    """One history object seen at three levels, addressed by one handle."""
    r = record or {}
    findings = []
    for level in LEVELS:
        if r.get(level) in (None, "", {}):
            findings.append({"kind": "missing-level", "level": level})
    handle = str(r.get("handle") or "")
    if not handle:
        findings.append({"kind": "no-handle"})
    elif not (handle.startswith("t") and "." in handle):
        findings.append({"kind": "handle-not-call-coordinate", "handle": handle})
    if r.get("handle_stable") is False:
        findings.append({"kind": "handle-unstable",
                         "why": "a handle must resolve after any number of folds"})
    if not findings:
        findings.append({"kind": "levels-linked"})
    return {"format": FORMAT, "handle": handle, "findings": findings}


def contract(record):
    """Retention, resolution and exact read survive every fold."""
    r = record or {}
    findings = []
    if r.get("source_retained") is False:
        findings.append({"kind": "source-deleted",
                         "why": "a fold may not delete the source record"})
    if r.get("resolves_after_folds") is False:
        findings.append({"kind": "handle-resolves-elsewhere"})
    if r.get("exact_read") is False:
        if r.get("cut_copy_available") is True:
            findings.append({"kind": "read-returns-cut-copy"})
        else:
            findings.append({"kind": "exact-read-unavailable"})
    if not findings:
        findings.append({"kind": "contract-holds"})
    return {"format": FORMAT, "findings": findings}


def fold(turns, budget=None, outline_share=0.2):
    """Select a level per turn inside the budget, demoting from the oldest."""
    rows = list(turns or ())
    if not rows:
        return {"format": FORMAT, "findings": [{"kind": "no-turns"}]}
    cap = _num(budget)
    findings = []
    chosen = []
    total = 0.0
    ordered = sorted(rows, key=lambda r: int(r.get("turn") or 0))
    closed = [r for r in ordered if r.get("closed") is not False]
    for index, r in enumerate(ordered):
        size = _num(r.get("size") or 0)
        if r.get("closed") is False:
            level = "l2"
        elif closed and r is closed[-1]:
            level = "l2"
        elif len(closed) >= 2 and r is closed[-2]:
            level = "l1_full"
        elif len(closed) >= 3 and r is closed[-3]:
            level = "l1_full"
        else:
            level = "l1_brief"
        previous = r.get("previous_level")
        if previous in ("l1_brief", "l1_full", "l2"):
            rank = {"l1_brief": 0, "l1_full": 1, "l2": 2}
            if rank[level] > rank[previous]:
                findings.append({"kind": "demotion-not-monotone", "turn": r.get("turn")})
                level = previous
        chosen.append({"turn": r.get("turn"), "level": level})
        total += size or 0
    if cap is not None and total > cap:
        for item in chosen:
            if item["turn"] is None:
                continue
            if item["level"] == "l2":
                item["level"] = "l1_full"
                findings.append({"kind": "demoted", "turn": item["turn"]})
            elif item["level"] == "l1_full":
                item["level"] = "l1_brief"
                findings.append({"kind": "demoted", "turn": item["turn"]})
        if not findings or all(f["kind"] == "demoted" for f in findings):
            findings.append({"kind": "budget-exceeded",
                             "budget": cap, "requested": total})
    if not findings:
        findings.append({"kind": "fold-rendered", "turns": len(chosen)})
    return {"format": FORMAT, "turns": chosen, "requested": round(total, 2),
            "findings": findings}


def trigger(requests, stable_prefix=0.0, layout_budget=0.0, dossier=0.0,
            rewrite_ratio=30.0, lam=1.0):
    """Fold when the carried excess reaches the rebuild cost of the landing point."""
    rows = [r for r in (requests or ()) if _num(r.get("cached")) is not None]
    b = _num(stable_prefix) or 0.0
    l = _num(layout_budget) or 0.0
    d = _num(dossier) or 0.0
    rw = _num(rewrite_ratio) or 0.0
    if not rows or rw <= 0:
        return {"format": FORMAT, "findings": [{"kind": "no-requests"}]}
    landing = b + l + d
    excess = sum(max(_num(r["cached"]) - landing, 0.0) for r in rows)
    price = rw * (l + d)
    decision = price > 0 and excess >= float(lam) * price
    findings = [{"kind": "fold-now" if decision else "keep"}]
    if price <= 0:
        findings.append({"kind": "landing-not-priced",
                         "why": "the retained budget must enter the fold price"})
    return {"format": FORMAT, "landing": round(landing, 2), "excess": round(excess, 2),
            "price": round(price, 2), "fold": decision, "findings": findings}


def cost(usage, ratios=None):
    """Normalized cost in cached-read equivalents."""
    u = usage or {}
    h = _num(u.get("cached")) or 0.0
    unc = _num(u.get("uncached")) or 0.0
    w = _num(u.get("cache_write")) or 0.0
    o = _num(u.get("output")) or 0.0
    r = ratios or {}
    ru = _num(r.get("uncached", 30.0)) or 0.0
    rw = _num(r.get("write", 30.0)) or 0.0
    ro = _num(r.get("output", 90.0)) or 0.0
    return {"format": FORMAT, "normalized": round(h + ru * unc + rw * w + ro * o, 2),
            "findings": []}


def recover(rows):
    """Folded content is only useful when a handle reaches it."""
    data = list(rows or ())
    if not data:
        return {"format": FORMAT, "findings": [{"kind": "no-recovery-records"}]}
    folded = [r for r in data if r.get("folded") is True]
    used = [r for r in data if r.get("recovered_by") in ("scan", "ctx")]
    findings = []
    if folded and not used:
        findings.append({"kind": "no-recovery-after-fold",
                         "why": "the outline must print handles the agent can use"})
    if any(r.get("recovered_by") == "scan" and r.get("bounded") is not True for r in data):
        findings.append({"kind": "unbounded-read"})
    if any(r.get("recovered_by") == "ctx" and r.get("computed_over_full_text") is not True
           for r in data):
        findings.append({"kind": "ctx-not-over-full-text"})
    if any(r.get("dossier_entry") for r in data):
        findings.append({"kind": "dossier-carried"})
    if not findings:
        findings.append({"kind": "recovery-clean"})
    return {"format": FORMAT, "folded": len(folded), "recovered": len(used),
            "findings": findings}


def advise(profile):
    """Map a harness profile onto the paper's failure modes."""
    p = profile or {}
    have = {str(key) for key, value in p.items() if value}
    findings = []
    checks = (
        ("records_levels", "summary-at-compaction", "the views should exist before the fold"),
        ("keeps_handles", "unaddressable-history", "one handle across levels and folds"),
        ("demotes_monotonically", "redraws-richer", "a sent line is never redrawn richer"),
        ("offers_recovery", "folded-and-lost", "bounded read and file-side computation"),
        ("keeps_a_dossier", "rereads-findings", "keep findings, not the material"),
        ("prices_the_landing", "fixed-interval", "the retained budget is part of the cost"),
        ("contracts_recoverability", "undeclared-guarantee", "retention, resolution, exact read"),
        ("measures_fold_cost", "unmeasured-compaction", "a fold should need no model call"),
    )
    for key, kind, why in checks:
        if key not in have:
            findings.append({"kind": kind, "why": why})
    return {"format": FORMAT, "findings": findings}
