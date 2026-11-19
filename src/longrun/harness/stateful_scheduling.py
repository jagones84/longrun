#!/usr/bin/env python3
"""Stateful scheduling — optimize the request lifecycle, not the segment.

Source: arXiv:2512.14142, "Astraea" (round 143). An agentic workflow alternates
compute and external API calls, so a scheduler that treats each segment as an
independent task optimizes a local metric and ignores the end-to-end Job
Completion Time (`astraea_state_scheduling_2512.14142.txt:22`, `:99`). Astraea
classifies a request by its compute/I-O behaviour, orders by an enhanced HRRN
score, and manages the KV cache during I/O waits (`:43`, `:46`, `:49`).

  * **the scheduling problem is NP-hard** (reduction from `1|prec|ΣCj`), so the
    contribution is a heuristic with an explicit objective (`:254`, `:257`).
  * **MLFQ migration is event-driven**: new requests enter Q0; a segment that
    exceeds its queue's token cost is demoted as compute-intensive; a segment
    that yields to an API call before exhausting its quota is promoted as
    I/O-intensive (`:341`, `:347`, `:351`).
  * **the intra-queue score is HRRN** `(W + T_proc)/T_proc`, which behaves like
    SRPT for equal waits and still ages long jobs (`:368`, `:371`).
  * **starvation is handled explicitly**: the lowest queue is promoted to Q0 when
    its response ratio exceeds the aging threshold (`:402`, `:404`).
  * **KV policy is chosen by memory waste**: preserve, discard or swap, whichever
    minimizes `T·C·M` (`:396`, `:400`, `:408`).
  * **measured**: average JCT down 25.5% against vLLM-FCFS and 19.1% against
    Infercept, with 0.0006% scheduler overhead and 3.2x less degradation under
    load (`:57`, `:586`, `:604`, `:610`).

  * `hrrn(wait, proc)` — the intra-queue score.
  * `queue_event(row)` — promotion, demotion or stay.
  * `aging(row)` — the starvation guard.
  * `batch(segments, capacity)` — pack the highest scores first.
  * `kv_policy(row)` — preserve / discard / swap by estimated waste.
  * `predict(row)` — the per-stage service time estimate.
  * `jct(segments)` — the lifecycle total.
  * `compare(rows)` — JCT against the baselines.
  * `stability(rows)` — degradation from low to high load.
  * `advise(profile)` — map a harness profile onto the paper's failure modes.

Pure: queue state in; decisions out.
"""
from __future__ import annotations

FORMAT = "longrun-stateful-scheduling/1"

KV_POLICIES = ("preserve", "discard", "swap")


def _num(value, default=None):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def hrrn(wait, proc):
    """(W + T_proc) / T_proc; a non-positive service time cannot be scored."""
    w = _num(wait, 0.0)
    p = _num(proc)
    if p is None or p <= 0:
        return None
    return (w + p) / p


def queue_event(row):
    """One segment completed: promote if I/O-bound, demote if compute-heavy."""
    r = row or {}
    queue = int(_num(r.get("queue"), 0.0))
    m = int(_num(r.get("m"), 2.0))
    cost = _num(r.get("token_cost"))
    threshold = _num(r.get("threshold"))
    yielded = r.get("yielded_to_api") is True
    if cost is None or threshold is None:
        return {"format": FORMAT, "queue": queue, "action": "hold",
                "reason": "state-incomplete"}
    if yielded and cost < threshold:
        return {"format": FORMAT, "queue": max(0, queue - 1),
                "action": "promote" if queue > 0 else "stay",
                "reason": "io-bound"}
    if cost > threshold:
        return {"format": FORMAT, "queue": min(m - 1, queue + 1),
                "action": "demote" if queue < m - 1 else "stay",
                "reason": "compute-intensive"}
    return {"format": FORMAT, "queue": queue, "action": "stay",
            "reason": "within-quota"}


def aging(row):
    """The lowest queue is promoted when its response ratio exceeds the threshold."""
    r = row or {}
    wait = _num(r.get("wait"))
    nxt = _num(r.get("next_proc"))
    tau = _num(r.get("tau"), 4.0)
    score = hrrn(wait, nxt)
    if score is None:
        return {"format": FORMAT, "verdict": "state-incomplete"}
    return {"format": FORMAT, "score": score, "tau": tau,
            "aged": score > tau}


def batch(segments, capacity):
    """HRRN order, packed until the memory/throughput capacity is reached."""
    rows = []
    for seg in segments or []:
        score = hrrn((seg or {}).get("wait"), (seg or {}).get("proc"))
        tokens = _num((seg or {}).get("tokens"), 0.0)
        if score is None:
            continue
        rows.append({"id": (seg or {}).get("id"), "score": score,
                     "tokens": tokens})
    rows.sort(key=lambda r: r["score"], reverse=True)
    cap = _num(capacity)
    chosen, left = [], []
    used = 0.0
    for row in rows:
        if cap is None or used + row["tokens"] <= cap:
            chosen.append(row)
            used += row["tokens"]
        else:
            left.append(row)
    return {"format": FORMAT, "batch": chosen, "left": left,
            "used": used, "capacity": cap}


def kv_policy(row):
    """Choose preserve / discard / swap by the estimated memory-time waste."""
    r = row or {}
    t_api = _num(r.get("t_api"), 0.0)
    c_self = _num(r.get("c_self"), 0.0)
    t_recompute = _num(r.get("t_recompute"), 0.0)
    c_batch = _num(r.get("c_batch"), 0.0)
    t_swap = _num(r.get("t_swap"), 0.0)
    per_token = _num(r.get("m_bytes"), 0.0)
    wastes = {
        "preserve": t_api * c_self * per_token,
        "discard": t_recompute * c_batch * per_token,
        "swap": 2.0 * t_swap * c_batch * per_token,
    }
    best = min(KV_POLICIES, key=lambda name: (wastes[name],
                                              KV_POLICIES.index(name)))
    return {"format": FORMAT, "waste": wastes, "policy": best,
            "margin": sorted(wastes.values())[1] - wastes[best]
            if len(wastes) > 1 else 0.0}


def predict(row):
    """Per-stage service times; the API term is a category mean, not a guess."""
    r = row or {}
    prefill = _num(r.get("prefill_ms"))
    n_gen = _num(r.get("n_gen"), 0.0)
    decode = _num(r.get("decode_ms_per_token"))
    api = _num(r.get("api_mean_ms"))
    if prefill is None or decode is None:
        return {"format": FORMAT, "verdict": "state-incomplete"}
    compute = prefill + n_gen * decode
    api = 0.0 if api is None else api
    return {"format": FORMAT, "compute_ms": compute, "api_ms": api,
            "segment_ms": compute + api,
            "api_source": "category-mean" if r.get("api_mean_ms") is not None
            else "none"}


def jct(segments):
    """Sum wait plus compute over all segments, plus every API duration."""
    waits = compute = api = 0.0
    n = 0
    for seg in segments or []:
        w = _num((seg or {}).get("wait"))
        c = _num((seg or {}).get("compute"))
        a = _num((seg or {}).get("api"))
        if w is None or c is None:
            continue
        waits += w
        compute += c
        api += a or 0.0
        n += 1
    if not n:
        return {"format": FORMAT, "verdict": "no-segments"}
    return {"format": FORMAT, "jct": waits + compute + api,
            "wait": waits, "compute": compute, "api": api,
            "segments": n}


def compare(rows):
    """JCT by policy, and the improvement against the named baseline."""
    clean = []
    for row in rows or []:
        name = str((row or {}).get("policy") or "")
        value = _num((row or {}).get("jct"))
        if not name or value is None:
            continue
        clean.append({"policy": name, "jct": value})
    if not clean:
        return {"format": FORMAT, "verdict": "no-rows"}
    best = min(clean, key=lambda r: r["jct"])
    baseline = next((r for r in clean if "fcfs" in r["policy"].lower()), None)
    rel = ((baseline["jct"] - best["jct"]) / baseline["jct"]
           if baseline and baseline["jct"] else None)
    return {"format": FORMAT, "rows": clean, "best": best,
            "improvement": rel,
            "verdict": "lifecycle-pays" if rel is not None and rel > 0.1
            else "no-lifecycle-gain"}


def stability(rows):
    """Degradation from low to high load; the robust policy degrades least."""
    clean = []
    for row in rows or []:
        name = str((row or {}).get("policy") or "")
        low = _num((row or {}).get("low"))
        high = _num((row or {}).get("high"))
        if not name or low is None or high is None or low <= 0:
            continue
        clean.append({"policy": name, "degradation": (high - low) / low})
    if not clean:
        return {"format": FORMAT, "verdict": "no-rows"}
    best = min(clean, key=lambda r: r["degradation"])
    ratio = None
    worst = max(clean, key=lambda r: r["degradation"])
    if best["degradation"] > 0:
        ratio = worst["degradation"] / best["degradation"]
    return {"format": FORMAT, "rows": clean, "best": best,
            "ratio": ratio,
            "verdict": "degrades-less" if ratio is not None and ratio >= 2.0
            else "similar-degradation"}


def advise(profile):
    """Map a harness profile onto the paper's failure modes."""
    p = profile or {}
    have = {str(k) for k, v in p.items() if v}
    checks = (
        ("optimizes_end_to_end", "segment-latency-only",
         "a fast segment can still starve the request behind it"),
        ("classifies_compute_and_io", "one-queue-fifo",
         "I/O-bound and compute-bound requests need different treatment"),
        ("ages_the_lowest_queue", "no-starvation-guard",
         "a long job otherwise never leaves the bottom queue"),
        ("predicts_the_api_duration", "treats_io_as_instant",
         "the API call dominates the lifecycle"),
        ("manages_kv_on_wait", "keeps_kv_resident",
         "idle cache costs throughput; discarding costs recomputation"),
        ("reports_jct_not_ttft", "ttft-as-the-metric",
         "the user experiences the whole workflow"),
    )
    findings = []
    for key, kind, why in checks:
        if key not in have:
            findings.append({"kind": kind, "why": why})
    return {"format": FORMAT, "findings": findings}
