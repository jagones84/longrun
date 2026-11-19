#!/usr/bin/env python3
"""Continuation policy — a stop is not the limit; a burst is the signal.

Source: arXiv:2611.22888, "Stopping Is Not the Limit" (round 136). Agents that
stop with budget left still gain when execution continues, but the gains
diminish and stop responses cluster; a summary that records a capability as
impossible shortens the next productive stretch
(`stopping_capability_longhorizon_2611.22888.md:32`, `:58`).

  * **a stop response is a turn with no tool call**, and it may or may not end
    the run depending on the policy (`:90`, `:96`).
  * **continuation pays**: capability 4.90 vs 3.07 (DeepSeek) and 5.39 vs 3.02
    (MiMo) at the same 2,000-turn budget, although ReAct ended 96.7% / 92.7% of
    runs at the first stop (`:122`).
  * **the gain per 100 turns falls** from 1.57 to 0.04 while the stop share rises
    from 1.0% to 41.9% (`:142`).
  * **a stop burst predicts a dead stretch**: with W = 20 and rho = 0.2, no
    further gain occurs in 96.1% (DeepSeek) and 99.6% (MiMo) of the intervals
    after the first burst (`:148`, `:150`).
  * **impossibility judgments travel through summaries**: they appear in 82.9%
    of DeepSeek runs, and the next stop comes after 66.2 turns instead of 115.6
    (`:156`), with lower achievement (10.6% vs 21.8%) (`:158`).
  * **SCoRe compacts at the burst and relabels the judgments as unproven**:
    6.65 vs 5.95 capability on DeepSeek and 7.62 vs 6.38 on MiMo, at about 16%
    lower cost; removing either component lowers the score (`:194`, `:231`, `:247`).

  * `stop_rate(turns)` / `burst(turns)` — detect the burst that should compact.
  * `gains(bins)` — the per-bin gain and whether it diminishes.
  * `judgment(text)` / `relabel(text)` — the impossibility sentence and its fix.
  * `summary(record)` — the six-field summary, with judgments kept separate.
  * `policy(spec)` — stop-aware compaction and the nudge rule.
  * `compare(rows)` — judgment vs no-judgment runs.
  * `methods(rows)` — SCoRe against the baselines and its own ablations.
  * `advise(profile)` — map a harness profile onto the paper's failure modes.

Pure: turn logs and measurements in; findings out.
"""
from __future__ import annotations

FORMAT = "longrun-continuation-policy/1"

FIELDS = ("verified_findings", "environment_state", "achieved_capabilities",
          "unsuccessful_attempts", "remaining_gaps")


def _num(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _responses(turns):
    """Tool-call and stop responses only; summaries and retries do not count."""
    return [t for t in (turns or ()) if t.get("kind") in ("tool", "stop")]


def stop_rate(turns, window=None):
    """The share of stop responses, overall or in the last window."""
    rows = _responses(turns)
    if window is not None:
        rows = rows[-int(window):] if int(window) > 0 else []
    if not rows:
        return {"format": FORMAT, "rate": None, "turns": 0,
                "findings": [{"kind": "no-responses"}]}
    stops = sum(1 for t in rows if t.get("kind") == "stop")
    return {"format": FORMAT, "rate": round(stops / len(rows), 4), "turns": len(rows),
            "stops": stops, "findings": []}


def burst(turns, window=20, rho=0.2):
    """The first full window whose stop share reaches rho."""
    rows = _responses(turns)
    w = int(window)
    if w < 2 or not 0 < float(rho) <= 1:
        return {"format": FORMAT, "findings": [{"kind": "invalid-window"}]}
    for end in range(w, len(rows) + 1):
        chunk = rows[end - w:end]
        stops = sum(1 for t in chunk if t.get("kind") == "stop")
        if stops / w >= float(rho):
            return {"format": FORMAT, "index": end - 1, "rate": round(stops / w, 4),
                    "stops": stops, "window": w,
                    "findings": [{"kind": "stop-burst", "why": "compaction is triggered here"}]}
    return {"format": FORMAT, "index": None, "findings": [{"kind": "no-burst"}]}


def gains(bins):
    """Per-bin capability gains; a pipeline that stops learning is named."""
    rows = [b for b in (bins or ()) if _num(b.get("gain")) is not None]
    if not rows:
        return {"format": FORMAT, "findings": [{"kind": "no-bins"}]}
    first = _num(rows[0]["gain"])
    last = _num(rows[-1]["gain"])
    mean = sum(_num(r["gain"]) for r in rows) / len(rows)
    findings = []
    if len(rows) >= 2 and last < first / 2.0:
        findings.append({"kind": "gains-diminish", "first": first, "last": last})
    if last == 0:
        findings.append({"kind": "no-gain-in-last-bin", "bin": rows[-1].get("bin")})
    if not findings:
        findings.append({"kind": "gains-sustained"})
    return {"format": FORMAT, "bins": len(rows), "mean": round(mean, 4),
            "first": first, "last": last, "findings": findings}


def judgment(text):
    """Read a capability-level impossibility judgment out of a sentence."""
    s = str(text or "").strip()
    if not s:
        return {"format": FORMAT, "findings": [{"kind": "empty-text"}]}
    low = s.lower()
    markers = ("is impossible", "cannot be achieved", "no way to achieve",
               "cannot achieve", "is not achievable")
    if not any(m in low for m in markers):
        return {"format": FORMAT, "impossible": False, "findings": [{"kind": "no-judgment"}]}
    capability = s
    for marker in markers:
        at = low.find(marker)
        if at >= 0:
            capability = s[:at].strip(" ,.;:")
            break
    return {"format": FORMAT, "impossible": True, "capability": capability,
            "findings": [{"kind": "impossibility-judgment", "capability": capability,
                          "why": "an unverified capability is stated as impossible"}]}


def relabel(text):
    """Rewrite an impossibility judgment as an unproven conclusion."""
    out = judgment(text)
    if out.get("impossible") is not True:
        return {"format": FORMAT, "text": str(text or ""),
                "findings": [{"kind": "nothing-to-relabel"}]}
    capability = out["capability"]
    rewritten = ("I have not yet found a way to achieve %s through the approaches I attempted"
                 % capability)
    return {"format": FORMAT, "text": rewritten, "capability": capability,
            "findings": [{"kind": "relabeled-unproven",
                          "why": "the judgment is kept, but as an unproven conclusion"}]}


def summary(record):
    """A summary keeps facts and unproven conclusions in different fields."""
    r = record or {}
    findings = []
    for field in FIELDS:
        if not str(r.get(field) or "").strip():
            findings.append({"kind": "summary-field-missing", "field": field})
    unproven = str(r.get("unproven_conclusions") or "").strip()
    fact_text = " ".join(str(r.get(f) or "") for f in FIELDS)
    if judgment(fact_text).get("impossible") is True:
        findings.append({"kind": "judgment-in-facts",
                         "why": "an impossible verdict is not an established finding"})
    if judgment(fact_text).get("impossible") is True and not unproven:
        findings.append({"kind": "unproven-field-missing"})
    if unproven and "not yet found a way" in unproven.lower():
        findings.append({"kind": "unproven-relabeled"})
    if not findings:
        findings.append({"kind": "summary-clean"})
    return {"format": FORMAT, "findings": findings}


def policy(spec):
    """Stop-aware compaction: a burst triggers the restart, non-triggers nudge."""
    s = spec or {}
    findings = []
    if s.get("stop_ends_run") is not False:
        findings.append({"kind": "stop-ends-run",
                         "why": "the run must continue while the turn budget remains"})
    if s.get("burst_trigger") is not True:
        findings.append({"kind": "burst-trigger-missing",
                         "why": "compaction at the stop burst is what restarts exploration"})
    if s.get("window_resets_after_compaction") is not True:
        findings.append({"kind": "window-not-reset"})
    if int(s.get("window") or 0) < 2 or not 0 < float(s.get("rho") or 0) <= 1:
        findings.append({"kind": "invalid-burst-window"})
    if s.get("token_threshold") is not None and _num(s.get("token_threshold")) <= 0:
        findings.append({"kind": "invalid-token-threshold"})
    if s.get("nudge_on_non_trigger") is not True:
        findings.append({"kind": "no-continuation-nudge",
                         "why": "a stop that does not compact still needs a nudge"})
    if not findings:
        findings.append({"kind": "stop-aware-policy"})
    return {"format": FORMAT, "findings": findings}


def compare(rows):
    """Runs with and without an impossibility judgment, same task and capability."""
    data = [r for r in (rows or ()) if _num(r.get("turns_to_next_stop")) is not None]
    if not data:
        return {"format": FORMAT, "findings": [{"kind": "no-runs"}]}
    with_j = [r for r in data if r.get("judgment") is True]
    without = [r for r in data if r.get("judgment") is not True]
    if not with_j or not without:
        return {"format": FORMAT, "findings": [{"kind": "single-group"}]}
    tw = sum(_num(r["turns_to_next_stop"]) for r in with_j) / len(with_j)
    tn = sum(_num(r["turns_to_next_stop"]) for r in without) / len(without)
    aw = [r for r in with_j if r.get("achieved") is not None]
    an = [r for r in without if r.get("achieved") is not None]
    findings = []
    if tw < tn:
        findings.append({"kind": "judgment-shortens-next-stretch",
                         "with": round(tw, 2), "without": round(tn, 2)})
    if aw and an:
        rw = sum(1 for r in aw if r["achieved"]) / len(aw)
        rn = sum(1 for r in an if r["achieved"]) / len(an)
        if rw < rn:
            findings.append({"kind": "judgment-lower-achievement",
                             "with": round(rw, 4), "without": round(rn, 4)})
        if any(r["achieved"] for r in aw):
            findings.append({"kind": "judgment-premature",
                             "why": "a capability called impossible was achieved afterwards"})
    if not findings:
        findings.append({"kind": "no-judgment-effect"})
    return {"format": FORMAT, "turns_with": round(tw, 2), "turns_without": round(tn, 2),
            "findings": findings}


def methods(rows):
    """SCoRe vs the baselines, and both components against their ablations."""
    data = [r for r in (rows or ()) if _num(r.get("cap")) is not None]
    if not data:
        return {"format": FORMAT, "findings": [{"kind": "no-methods"}]}
    by_name = {str(r.get("method")): r for r in data}
    best = max(data, key=lambda r: _num(r["cap"]))
    findings = [{"kind": "best-method", "method": best.get("method"),
                 "cap": _num(best["cap"])}]
    score = by_name.get("SCoRe")
    base = by_name.get("ReSum")
    if score and base and _num(score["cap"]) > _num(base["cap"]):
        findings.append({"kind": "score-above-resum",
                         "delta": round(_num(score["cap"]) - _num(base["cap"]), 2)})
    for drop, component in (("w/o capability judgment relabeling", "relabeling"),
                            ("w/o stop-aware compaction", "compaction")):
        ablated = by_name.get(drop)
        if score and ablated and _num(ablated["cap"]) < _num(score["cap"]):
            findings.append({"kind": "component-needed", "component": component,
                             "delta": round(_num(score["cap"]) - _num(ablated["cap"]), 2)})
    if score and base and _num(score.get("cost")) is not None and _num(base.get("cost")) is not None:
        if _num(score["cost"]) < _num(base["cost"]):
            findings.append({"kind": "cheaper-than-resum",
                             "ratio": round(_num(score["cost"]) / _num(base["cost"]), 3)})
    return {"format": FORMAT, "methods": len(data), "findings": findings}


def advise(profile):
    """Map a harness profile onto the paper's failure modes."""
    p = profile or {}
    have = {str(key) for key, value in p.items() if value}
    findings = []
    checks = (
        ("continues_after_stop", "stop-ends-run", "a stop is not a budget event"),
        ("detects_stop_bursts", "no-burst-detection", "cluster the stops before acting"),
        ("compacts_on_burst", "fixed-interval-compaction", "restart when the burst is measured"),
        ("separates_unproven", "judgments-as-facts", "keep impossible verdicts out of findings"),
        ("keeps_turn_accounting", "uncounted-turns", "stops and summaries consume turns too"),
        ("measures_gain_per_bin", "aggregate-only", "diminishing gains need a per-bin view"),
        ("ablates_components", "bundled-policy", "each half must earn its place"),
        ("reports_cost", "capability-only", "a gain that costs 20% more is a different claim"),
    )
    for key, kind, why in checks:
        if key not in have:
            findings.append({"kind": kind, "why": why})
    return {"format": FORMAT, "findings": findings}
