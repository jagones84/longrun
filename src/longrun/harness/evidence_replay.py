#!/usr/bin/env python3
"""Evidence replay — the evidence a forecaster sees is an experimental variable.

Source: arXiv:2611.23045, "ForecastGym: A Live, Controlled, and Replayable
Benchmark for Forecasting Agents" (round 136). Forecasting agents mix retrieval
with reasoning, so a score is only attributable when the evidence is fixed:
ForecastGym records what four search APIs return while a question is open and
replays those frozen states offline (`forecastgym_replayable_benchmark_2611.23045.md:26`, `:48`).

  * **retrieval time, not publication date, bounds what was knowable**: a page
    updated after `t` keeps its early date and passes a date filter (`:107`,
    `:111`).
  * **the filters still leak**: rerunning the same queries after settlement
    reveals the outcome for up to 92% of questions, and filtered evidence scores
    0.080-0.137 Brier, better than the market (`:208`, `:232`).
  * **providers disagree**: four in five pooled URLs come from exactly one
    provider, and switching the API moves the Brier score by up to 0.043, more
    than the 0.027 that separates four models (`:172`, `:299`).
  * **memory steadies rather than improves**: dropping it nearly doubles the
    update, and notes cost 9.5M tokens against 19.5M for rereading (`:284`,
    `:286`).
  * **the gap is missed information**: about three times as much of the high-gap
    states is attributed to facts never retrieved as to misreading (`:262`,
    `:264`).

  * `state(record)` — an evidence state whose items were knowable at its time.
  * `freeze(spec)` — one query plan and one time grid across providers.
  * `leak(rows)` — post-hoc leakage and revealed outcomes.
  * `score(rows)` / `trajectory(states)` — Brier and the time-averaged score.
  * `paired(rows)` — a per-question paired difference with its interval.
  * `sources(rows)` — the provider effect against the model spread.
  * `memory(rows)` — what memory changes (steadiness, cost).
  * `advise(profile)` — map a harness profile onto the paper's failure modes.

Pure: frozen states and result rows in; scores and findings out.
"""
from __future__ import annotations

import math
import statistics

FORMAT = "longrun-evidence-replay/1"


def _num(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def state(record):
    """Every item in a state was retrievable at that state's time."""
    r = record or {}
    at = _num(r.get("time"))
    items = list(r.get("items") or ())
    findings = []
    if at is None:
        return {"format": FORMAT, "findings": [{"kind": "state-time-missing"}]}
    if not items:
        findings.append({"kind": "state-empty"})
    for item in items:
        retrieved = _num(item.get("retrieved_at"))
        if retrieved is None:
            findings.append({"kind": "missing-retrieval-time", "id": item.get("id")})
        elif retrieved > at:
            findings.append({"kind": "item-not-knowable", "id": item.get("id"),
                             "retrieved_at": retrieved, "state_time": at})
    if not findings:
        findings.append({"kind": "state-valid", "items": len(items)})
    return {"format": FORMAT, "time": at, "items": len(items), "findings": findings}


def freeze(spec):
    """One initial query plan, one follow-up rule, one collection grid."""
    s = spec or {}
    providers = [str(p) for p in (s.get("providers") or ())]
    findings = []
    if len(providers) < 2:
        findings.append({"kind": "single-provider",
                         "why": "a source comparison needs at least two providers"})
    if s.get("shared_query_plan") is not True:
        findings.append({"kind": "source-policy-differs",
                         "why": "each provider must receive the same planned queries"})
    if s.get("shared_follow_up_budget") is not True:
        findings.append({"kind": "follow-up-budget-differs"})
    if not s.get("collection_times"):
        findings.append({"kind": "no-collection-grid"})
    if s.get("captured_before_resolution") is not True:
        findings.append({"kind": "captured-after-resolution",
                         "why": "an open question is what makes the evidence knowable"})
    if s.get("results_stored_per_provider") is not True:
        findings.append({"kind": "results-pooled",
                         "why": "provider selection is part of the recorded evidence"})
    if not findings:
        findings.append({"kind": "frozen-record"})
    return {"format": FORMAT, "providers": len(providers), "findings": findings}


def leak(rows):
    """Post-hoc retrieval after settlement, raw and with each date filter."""
    data = [r for r in (rows or ()) if _num(r.get("total")) is not None]
    if not data:
        return {"format": FORMAT, "findings": [{"kind": "no-probe"}]}
    total = sum(_num(r["total"]) for r in data)
    leaking = sum(_num(r.get("leaking") or 0) for r in data)
    questions = sum(_num(r.get("questions") or 0) for r in data)
    revealed = sum(_num(r.get("revealed") or 0) for r in data)
    findings = []
    if total and leaking / total > 0.1:
        findings.append({"kind": "post-hoc-leaks", "rate": round(leaking / total, 4)})
    if questions and revealed / questions > 0.5:
        findings.append({"kind": "outcome-revealed", "rate": round(revealed / questions, 4),
                         "why": "a post-hoc search cannot stand in for a live capture"})
    undated = [r for r in data if _num(r.get("undated")) is not None]
    if undated:
        share = sum(_num(r["undated"]) for r in undated) / sum(_num(r["total"]) for r in undated)
        if share > 0.5:
            findings.append({"kind": "undated-pages", "share": round(share, 4),
                             "why": "a date filter drops most of what it should keep"})
    if any(_num(r.get("dated_after_retrieval")) for r in data):
        findings.append({"kind": "dated-after-retrieval",
                         "why": "a page can carry an early date and later content"})
    if not findings:
        findings.append({"kind": "no-leak-detected"})
    return {"format": FORMAT, "items": int(total), "findings": findings}


def score(rows):
    """Brier over forecasts, each row one (probability, outcome) pair."""
    pairs = [(p, y) for p, y in ((_num(r.get("p")), _num(r.get("y"))) for r in (rows or ()))
             if p is not None and y is not None and 0 <= p <= 1]
    if not pairs:
        return {"format": FORMAT, "findings": [{"kind": "no-forecasts"}]}
    brier = sum((p - y) ** 2 for p, y in pairs) / len(pairs)
    correct = sum(1 for p, y in pairs
                  if (p > 0.5 and y == 1) or (p < 0.5 and y == 0) or (p == 0.5 and y == 0.5))
    findings = []
    if abs(brier - 0.25) < 1e-9:
        findings.append({"kind": "constant-half"})
    return {"format": FORMAT, "brier": round(brier, 6), "forecasts": len(pairs),
            "accuracy": round(correct / len(pairs), 4), "findings": findings}


def trajectory(states):
    """The time-averaged Brier score over a question's scored states."""
    rows = [s for s in (states or ()) if _num(s.get("p")) is not None
            and _num(s.get("y")) is not None]
    if not rows:
        return {"format": FORMAT, "findings": [{"kind": "no-states"}]}
    each = score(rows)
    last = score([rows[-1]])
    return {"format": FORMAT, "states": len(rows), "tbs": each["brier"],
            "last": last["brier"], "findings": each["findings"]}


def paired(rows):
    """Per-question differences (arm minus baseline) with a normal interval."""
    data = [r for r in (rows or ()) if _num(r.get("arm")) is not None
            and _num(r.get("baseline")) is not None]
    if len(data) < 2:
        return {"format": FORMAT, "findings": [{"kind": "not-enough-questions"}]}
    diffs = [_num(r["arm"]) - _num(r["baseline"]) for r in data]
    mean = statistics.mean(diffs)
    se = statistics.stdev(diffs) / math.sqrt(len(diffs))
    lo, hi = mean - 1.96 * se, mean + 1.96 * se
    findings = []
    if lo > 0:
        findings.append({"kind": "arm-worse", "delta": round(mean, 4)})
    elif hi < 0:
        findings.append({"kind": "arm-better", "delta": round(mean, 4)})
    else:
        findings.append({"kind": "difference-unresolved", "delta": round(mean, 4)})
    return {"format": FORMAT, "questions": len(diffs), "delta": round(mean, 4),
            "ci": [round(lo, 4), round(hi, 4)], "findings": findings}


def sources(rows, model_spread=None):
    """Does the search source move the score more than the model does?"""
    data = [r for r in (rows or ()) if _num(r.get("brier")) is not None]
    if len(data) < 2:
        return {"format": FORMAT, "findings": [{"kind": "not-enough-sources"}]}
    values = {str(r.get("provider")): _num(r["brier"]) for r in data}
    spread = max(values.values()) - min(values.values())
    findings = [{"kind": "source-spread", "spread": round(spread, 4)}]
    worst = max(values, key=values.get)
    findings.append({"kind": "worst-source", "provider": worst, "brier": values[worst]})
    spread_model = _num(model_spread)
    if spread_model is not None and spread > spread_model:
        findings.append({"kind": "source-exceeds-model", "source": round(spread, 4),
                         "model": round(spread_model, 4),
                         "why": "the evidence can matter as much as the model"})
    return {"format": FORMAT, "spread": round(spread, 4), "findings": findings}


def memory(rows):
    """What memory changes: steadiness, agreement with the market, and cost."""
    data = [r for r in (rows or ()) if _num(r.get("brier")) is not None]
    by_name = {str(r.get("variant")): r for r in data}
    main = by_name.get("main")
    none = by_name.get("no-memory")
    if not main or not none:
        return {"format": FORMAT, "findings": [{"kind": "missing-variants"}]}
    findings = []
    mu = _num(main.get("update"))
    nu = _num(none.get("update"))
    ma = _num(main.get("agree"))
    na = _num(none.get("agree"))
    if mu is not None and nu is not None and nu > mu:
        findings.append({"kind": "memory-steadies", "main": mu, "no_memory": nu})
    if ma is not None and na is not None and ma > na:
        findings.append({"kind": "memory-agrees-with-market", "main": ma, "no_memory": na})
    allso = by_name.get("all-so-far")
    if main and allso:
        mt = _num(main.get("tokens"))
        at = _num(allso.get("tokens"))
        if mt is not None and at is not None and mt < at:
            findings.append({"kind": "notes-cheaper", "notes": mt, "reread": at})
    if not findings:
        findings.append({"kind": "no-memory-effect"})
    return {"format": FORMAT, "findings": findings}


def advise(profile):
    """Map a harness profile onto the paper's failure modes."""
    p = profile or {}
    have = {str(key) for key, value in p.items() if value}
    findings = []
    checks = (
        ("captures_evidence_live", "retrospective-search", "record before resolution"),
        ("bounds_by_retrieval_time", "publication-date-filter", "retrieval time is what was knowable"),
        ("freezes_provider_results", "pooled-evidence", "provider selection is part of the record"),
        ("shares_query_plan", "per-provider-queries", "differing queries confound the source"),
        ("replays_offline", "replay-searches-live", "a replay must not acquire new evidence"),
        ("hides_market_price", "price-in-evidence", "the quote is a shortcut to the answer"),
        ("compares_with_market", "model-only-baseline", "the market is the external baseline"),
        ("ablates_memory", "memory-not-varied", "memory and evidence are separate arguments"),
    )
    for key, kind, why in checks:
        if key not in have:
            findings.append({"kind": kind, "why": why})
    return {"format": FORMAT, "findings": findings}
