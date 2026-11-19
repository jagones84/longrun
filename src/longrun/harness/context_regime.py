#!/usr/bin/env python3
"""Context regime — short working context, disciplined state, selective reading.

Source: arXiv:2611.05306, "You don't need long context" (round 155). Later tokens
cost more than earlier ones — up to 7× on frontier open-weight models — and
frequent compaction keeps the working context short while frontier models lose
little or no accuracy (`short_context_2611.05306.txt:10`, `:73`).

  * **three regimes**: full-history accumulation (FHA), end-of-conversation
    compaction (EoCC) and single-action compaction (SAC) (`:369`, `:412`).
  * **compaction is a brief for the work yet to be done**, not a summary of the
    trace: a verbatim task, the current intention and next steps, and the
    artifacts future execution needs (`:1230`, `:1249`).
  * **long inputs become long-horizon work** by storing them as files and
    reading them selectively, with bounded windows (`:441`, `:1528`).
  * **SAC nearly preserves accuracy** at a median peak context of 7–9K tokens,
    but a verbose model can collapse (53.0% → 3.6% at 16K/12K) (`:929`, `:1470`).
  * **the cost model anchors the retail price** and interpolates to r = 0.20 at
    16K, with input = output/5 and cached = input/10 (`:1258`, `:1273`).

  * `length(record)` — total and peak context, and the regime verdict.
  * `charge(record)` — the context-factor price model and the 16K ratio.
  * `compaction(record)` — whether a recap is an execution brief.
  * `regimes(record)` — FHA vs EoCC vs SAC on accuracy, peak and cost.
  * `selective(record)` — bounded reads and conversation growth against input.
  * `sac(record)` — one action per context, and the collapse check.
  * `history(record)` — the coin-toss counterexample and its repair.
  * `audit_record(record)` / `advise(profile)` — misreadings and mapping.

Pure: token counts, recaps and result rows in; verdicts and prices out.
"""
from __future__ import annotations

import math

FORMAT = "longrun-context-regime/1"

R_16K = 0.20
READ_DEFAULT = 6000
READ_CAP = 8000
SHORT_PEAK_K = 50.0
LONG_PEAK_K = 256.0
SECTIONS = ("objective", "facts", "changes", "verification", "dead_ends", "plan")


def _num(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _mean(values):
    return sum(values) / len(values) if values else None


def length(record):
    """Total across stretches and the peak single conversation."""
    r = record or {}
    stretches = [_num(v) for v in (r.get("stretches") or [])]
    stretches = [v for v in stretches if v is not None]
    total = _num(r.get("total_tokens"))
    peak = _num(r.get("peak_tokens"))
    if stretches:
        total = sum(stretches) if total is None else total
        peak = max(stretches) if peak is None else peak
    if total is None and peak is None:
        return {"format": FORMAT, "verdict": "insufficient-input"}
    peak_k = (peak / 1000.0) if peak is not None else None
    regime = str(r.get("regime") or "FHA").upper()
    if peak_k is None:
        kind = "unknown"
    elif peak_k <= SHORT_PEAK_K:
        kind = "short"
    elif peak_k >= LONG_PEAK_K:
        kind = "long"
    else:
        kind = "medium"
    return {"format": FORMAT, "regime": regime, "total_k": (total or 0) / 1000.0,
            "peak_k": peak_k, "kind": kind, "verdict": "measured"}


def charge(record):
    """The estimated price per million output tokens at a context limit."""
    r = record or {}
    w = _num(r.get("w"))
    w_max = _num(r.get("w_max"))
    standard = _num(r.get("standard_price"))
    rate = _num(r.get("r") or R_16K)
    if w is None or w_max is None or standard is None or w_max <= 16000:
        return {"format": FORMAT, "verdict": "insufficient-input"}
    span = w_max - 16000.0
    share = min(1.0, (max(w, 16000.0) - 16000.0) / span)
    output = standard * (rate + (1.0 - rate) * share)
    input_price = output / 5.0
    cached = input_price / 10.0
    at_16k = standard * rate
    return {"format": FORMAT, "w": w, "w_max": w_max, "r": rate,
            "output": output, "input": input_price, "cached": cached,
            "ratio_vs_16k": output / at_16k if at_16k else None,
            "verdict": "priced"}


def savings(record):
    """Optimized retail cost of a long baseline against a short configuration."""
    r = record or {}
    long_cost = _num(r.get("long_cost"))
    short_cost = _num(r.get("short_cost"))
    if not long_cost or short_cost is None or short_cost <= 0:
        return {"format": FORMAT, "verdict": "insufficient-input"}
    return {"format": FORMAT, "long": long_cost, "short": short_cost,
            "saving": long_cost / short_cost,
            "verdict": "saving" if long_cost > short_cost else "no-saving"}


def compaction(record):
    """A recap is an execution brief when it carries the six sections."""
    r = record or {}
    text = str(r.get("text") or "")
    present = [s for s in SECTIONS if s in text.lower()]
    task_verbatim = r.get("task_verbatim") is True
    completion = r.get("completion_criterion") is True
    narrative = r.get("narrative") is True
    score = len(present) / len(SECTIONS)
    if task_verbatim:
        score = min(1.0, score + 0.1)
    if completion:
        score = min(1.0, score + 0.1)
    if narrative and not task_verbatim:
        score *= 0.5
    if narrative:
        verdict = "narrative-summary"
    elif score >= 0.8:
        verdict = "execution-brief"
    else:
        verdict = "incomplete"
    return {"format": FORMAT, "sections": present, "score": score,
            "missing": [s for s in SECTIONS if s not in present],
            "verdict": verdict}


def regimes(record):
    """FHA, EoCC and SAC side by side: accuracy, peak context and cost."""
    r = record or {}
    rows = []
    for item in r.get("rows") or []:
        row = item or {}
        name = str(row.get("regime") or "").upper()
        accuracy = _num(row.get("accuracy"))
        if name not in ("FHA", "EOCC", "SAC") or accuracy is None:
            continue
        rows.append({"regime": name, "accuracy": accuracy,
                     "peak_k": _num(row.get("peak_k")),
                     "cost": _num(row.get("cost"))})
    if not rows:
        return {"format": FORMAT, "verdict": "no-rows"}
    base = next((row for row in rows if row["regime"] == "FHA"), None)
    deltas = {}
    for row in rows:
        if base:
            deltas[row["regime"]] = row["accuracy"] - base["accuracy"]
    best = max(rows, key=lambda row: (row["accuracy"],
                                      -(row["cost"] or math.inf)))
    short = [row for row in rows if row["regime"] in ("EOCC", "SAC")]
    parity = bool(short) and all(deltas.get(row["regime"], 0.0) >= -3.0
                                 for row in short)
    return {"format": FORMAT, "rows": rows, "deltas": deltas, "best": best,
            "parity": parity,
            "verdict": "short-context-parity" if parity else "long-context-advantage"}


def selective(record):
    """Bounded reads, search-then-read, and growth against document size."""
    r = record or {}
    reads = [_num(v) for v in (r.get("reads") or [])]
    reads = [v for v in reads if v is not None]
    cap = _num(r.get("cap") or READ_CAP)
    over = [v for v in reads if v > cap]
    search_first = r.get("search_before_read") is True
    pairs = []
    for pair in r.get("growth") or []:
        if not isinstance(pair, (list, tuple)) or len(pair) != 2:
            continue
        doc, conv = _num(pair[0]), _num(pair[1])
        if doc and conv and doc > 0 and conv > 0:
            pairs.append((math.log10(doc), math.log10(conv)))
    slope = None
    if len(pairs) >= 2:
        mx = _mean([p[0] for p in pairs])
        my = _mean([p[1] for p in pairs])
        denom = sum((x - mx) ** 2 for x, _ in pairs)
        if denom:
            slope = sum((x - mx) * (y - my) for x, y in pairs) / denom
    bounded = slope is not None and slope < 0.3
    verdict = "bounded" if bounded and not over else (
        "read-over-cap" if over else "unbounded-growth")
    return {"format": FORMAT, "reads": len(reads), "over_cap": len(over),
            "cap": cap, "search_first": search_first, "slope": slope,
            "verdict": verdict}


def sac(record):
    """Single-action compaction: one action per context, peak mostly state."""
    r = record or {}
    actions = _num(r.get("actions_per_context"))
    fha = _num(r.get("accuracy_fha"))
    sac_acc = _num(r.get("accuracy_sac"))
    peak = _num(r.get("peak_k"))
    if actions is None or fha is None or sac_acc is None:
        return {"format": FORMAT, "verdict": "insufficient-input"}
    delta = sac_acc - fha
    collapsed = delta <= -10.0
    return {"format": FORMAT, "actions_per_context": actions, "delta": delta,
            "peak_k": peak, "collapsed": collapsed,
            "verdict": "collapse" if collapsed else (
                "single-action-parity" if actions <= 1 and delta >= -3.0
                else "single-action-loss")}


def history(record):
    """A lossy recap needs a store: the coin-toss counterexample."""
    r = record or {}
    lossy = r.get("lossy") is True
    stored = r.get("full_history_stored") is True
    retrievable = r.get("retrievable") is True
    if not lossy:
        return {"format": FORMAT, "verdict": "lossless"}
    if stored and retrievable:
        return {"format": FORMAT, "verdict": "recoverable-by-retrieval"}
    return {"format": FORMAT, "verdict": "information-lost"}


def audit_record(record):
    """The misreadings the paper's comparisons exclude."""
    r = record or {}
    findings = []
    if r.get("compaction_is_summarisation") is True:
        findings.append({"kind": "compaction-is-summarisation",
                         "why": "a gist summary overweights repeated segments"})
    if r.get("peak_read_as_total") is True:
        findings.append({"kind": "peak-read-as-total",
                         "why": "the sum of stretch lengths is not the peak"})
    if r.get("inputs_read_in_full") is True:
        findings.append({"kind": "inputs-read-in-full",
                         "why": "selective reading is what keeps the context short"})
    if r.get("long_context_claimed_necessary") is True:
        findings.append({"kind": "long-context-claimed-necessary",
                         "why": "the necessity was not observed on any tested benchmark"})
    if r.get("single_action_read_as_lossless") is True:
        findings.append({"kind": "single-action-read-as-lossless",
                         "why": "a verbose model can collapse at a tight limit"})
    if r.get("history_dropped_without_a_store") is True:
        findings.append({"kind": "history-dropped-without-a-store",
                         "why": "a sequence needed later must stay retrievable"})
    if not findings:
        findings.append({"kind": "audit-conditions-met"})
    return {"format": FORMAT, "findings": findings, "verdict": "audit-complete"}


def advise(profile):
    """Map a harness profile onto the context-regime gaps the paper names."""
    p = profile or {}
    have = {str(k) for k, v in p.items() if v}
    checks = (
        ("keeps_working_context_short", "accumulates_full_history",
         "later tokens are costlier and slower"),
        ("writes_an_execution_brief", "writes_a_narrative_summary",
         "the next stretch needs the plan, not the story"),
        ("stores_long_inputs_as_files", "pastes_the_whole_input",
         "selective reading turns input size into a tool action"),
        ("bounds_each_read", "dumps_the_document",
         "a bounded window keeps the peak predictable"),
        ("keeps_a_retrievable_full_history", "discards_compacted_messages",
         "a sequence needed later must be recoverable"),
        ("measures_peak_beside_total_tokens", "reports_one_length",
         "the peak is what the price model charges"),
    )
    findings = []
    for key, kind, why in checks:
        if key not in have:
            findings.append({"kind": kind, "why": why})
    return {"format": FORMAT, "findings": findings}
