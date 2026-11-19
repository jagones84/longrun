#!/usr/bin/env python3
"""Context prefetch — predict the next recall, then arrive before the demand.

Source: arXiv:2611.23857, "Neural Memory Orchestration" (round 145). Overseer is
an end-to-end learned page prefetcher: an eBPF collector observes faults on the
host, a transformer on network-attached hardware predicts future pages, and a
kernel-resident enforcer materialises them before they are demanded
(`neural_memory_orchestration_2611.23857.txt:27`, `:77`, `:124`).

  * **mechanism and policy split**: the collector and enforcer are a
    workload-agnostic data path; the predictor is the only workload-specialised
    element, so a faster appliance helps without touching the host (`:143`,
    `:452`, `:496`).
  * **online ordinal ranks over deltas**: the k-th distinct delta gets rank k in
    a per-instance table, so one trained model serves any target without
    retraining; distinct deltas converge far faster than distinct addresses
    (`:173`, `:185`, `:199`).
  * **a narrow contract**: the collector emits `(target, context_window,
    address_window)`, predictions return `(target, address_sequence)` (`:143`).
  * **graceful degradation**: a collector failure means no predictions and an
    unaffected target; a full queue DROPS a prediction rather than blocking
    (`:153`, `:355`).
  * **measured**: Hilbert traversal -35% runtime locally and -18% remotely;
    dense matmul 450 s -> 60 s locally (7.5x) and about 2.5x remotely; the
    local arm also removes ~27% of major faults against a few percent remotely,
    which is why latency — not only quality — bounds the benefit (`:406`,
    `:477`, `:484`).
  * **honest negatives**: the benefit needs a fault-dominated, structured
    stream; the online vocabulary carries a warm-up cost that can dominate a
    short-lived target; the kernel UDP socket expands the attack surface
    (`:490`, `:500`, `:507`).

  * `window(events)` — per-target sliding windows and the packets they emit.
  * `encode(addresses)` — deltas mapped to online ordinal ranks.
  * `decode(ranks)` — ranks back to absolute addresses.
  * `contract(packet)` — the three-field request and the one-field reply.
  * `prefetch(row)` — in time, or late but still useful for service time.
  * `benefit(rows)` — local against remote against baseline, runtime and faults.
  * `degrade(row)` — collector down and queue full, with the safe failure mode.
  * `warmup(rows)` — accuracy against faults seen, and when warm-up dominates.
  * `audit(record)` — the six misreadings the paper names.
  * `advise(profile)` — map a harness profile onto the paper's failure modes.

Pure: event streams in; encoded packets, predictions and verdicts out.
"""
from __future__ import annotations

FORMAT = "longrun-context-prefetch/1"

DEFAULTS = {"window": 64, "vocab_cap": 4096, "arrival_slack_ms": 0.0}


def _int(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def window(events, size=DEFAULTS["window"]):
    """Per-target sliding windows; a full window becomes one packet."""
    size = int(size or DEFAULTS["window"])
    state, packets, short = {}, [], []
    for event in events or []:
        e = event or {}
        target = str(e.get("target") or "")
        address = _int(e.get("address"))
        if not target or address is None:
            short.append({"target": target, "why": "event-unreadable"})
            continue
        state.setdefault(target, []).append({"address": address,
                                             "context": str(e.get("context") or "")})
        if len(state[target]) >= size:
            batch = state[target][:size]
            state[target] = state[target][size:]
            packets.append({"target": target,
                            "contexts": [b["context"] for b in batch],
                            "addresses": [b["address"] for b in batch]})
    return {"format": FORMAT, "size": size, "packets": packets,
            "leftover": {t: len(v) for t, v in state.items()},
            "unreadable": short,
            "verdict": "windows-emitted" if packets else "no-full-window"}


def encode(addresses, cap=DEFAULTS["vocab_cap"]):
    """Deltas mapped to per-instance ordinal ranks, built online."""
    cap = int(cap or DEFAULTS["vocab_cap"])
    if not addresses:
        return {"format": FORMAT, "verdict": "no-addresses"}
    deltas, ranks = [], []
    order, rank_of = [], {}
    last = None
    evicted = 0
    next_rank = 0
    for raw in addresses:
        value = _int(raw)
        if value is None:
            return {"format": FORMAT, "verdict": "not-addressable", "value": raw}
        delta = 0 if last is None else value - last
        deltas.append(delta)
        if delta in rank_of:
            ranks.append(rank_of[delta])
        else:
            if len(order) >= cap:
                old = order.pop(0)
                rank_of.pop(old, None)
                evicted += 1
            next_rank += 1
            rank_of[delta] = next_rank
            order.append(delta)
            ranks.append(next_rank)
        last = value
    return {"format": FORMAT, "deltas": deltas, "ranks": ranks,
            "rank_to_delta": {r: d for d, r in rank_of.items()},
            "distinct_deltas": len(order), "cap": cap, "evicted": evicted,
            "verdict": "encoded"}


def decode(ranks, last, rank_to_delta):
    """Ranks back to absolute addresses by cumulative delta from the last one."""
    base = _int(last)
    if base is None:
        return {"format": FORMAT, "verdict": "no-anchor"}
    out, unresolved, running = [], [], base
    for rank in ranks or []:
        delta = (rank_to_delta or {}).get(rank)
        if delta is None:
            unresolved.append(rank)
            continue
        running += int(delta)
        out.append(running)
    return {"format": FORMAT, "addresses": out, "unresolved": unresolved,
            "verdict": "decoded" if not unresolved else "unresolved-ranks"}


def contract(packet):
    """The narrow request/reply schema; a missing field is named."""
    p = packet or {}
    request = ("target", "contexts", "addresses")
    reply = ("target", "addresses")
    missing = [key for key in request if p.get(key) in (None, "")]
    if p.get("reply") is True:
        missing = [key for key in reply if p.get(key) in (None, "")]
    return {"format": FORMAT, "request_fields": list(request),
            "reply_fields": list(reply), "missing": missing,
            "verdict": "contract-complete" if not missing else "contract-incomplete"}


def prefetch(row):
    """Whether a prediction arrives before the demand, and what a late one still buys."""
    r = row or {}
    latency = float(r.get("latency_ms") or 0.0)
    interarrival = float(r.get("interarrival_ms") or 0.0)
    slack = float(r.get("slack_ms") or DEFAULTS["arrival_slack_ms"])
    in_time = interarrival > 0 and latency <= interarrival + slack
    if latency <= 0:
        verdict = "no-latency-recorded"
    elif in_time:
        verdict = "predictions-arrive-in-time"
    elif r.get("reduces_service_time") is True:
        verdict = "late-but-still-useful"
    else:
        verdict = "predictions-arrive-late"
    return {"format": FORMAT, "latency_ms": latency, "interarrival_ms": interarrival,
            "in_time": in_time, "verdict": verdict}


def benefit(rows):
    """Runtime and major-fault reduction of each arm against the baseline."""
    arms = {}
    for row in rows or []:
        r = row or {}
        name = str(r.get("arm") or "")
        runtime = float(r.get("runtime_s") or 0.0)
        faults = float(r.get("major_faults") or 0.0)
        cur = arms.setdefault(name, {"runtime": [], "faults": []})
        cur["runtime"].append(runtime)
        cur["faults"].append(faults)
    summary = {}
    for name, cur in arms.items():
        summary[name] = {
            "runtime_s": sum(cur["runtime"]) / len(cur["runtime"]) if cur["runtime"] else 0.0,
            "major_faults": sum(cur["faults"]) / len(cur["faults"]) if cur["faults"] else 0.0,
        }
    base = summary.get("baseline")
    for name, row in summary.items():
        if base and base["runtime_s"]:
            row["runtime_reduction"] = 1.0 - row["runtime_s"] / base["runtime_s"]
        if base and base["major_faults"]:
            row["fault_reduction"] = 1.0 - row["major_faults"] / base["major_faults"]
    local = summary.get("local") or {}
    remote = summary.get("remote") or {}
    if local.get("runtime_reduction") is not None and remote.get("runtime_reduction") is not None:
        verdict = ("latency-bounds-the-benefit"
                   if local["runtime_reduction"] > remote["runtime_reduction"]
                   else "latency-not-the-limit")
    elif any((row.get("runtime_reduction") or 0.0) >= 0.05 for row in summary.values()):
        verdict = "prefetch-helps"
    else:
        verdict = "no-measurable-benefit"
    return {"format": FORMAT, "arms": summary, "verdict": verdict}


def degrade(row):
    """Collector failure and queue pressure must never hurt the target."""
    r = row or {}
    collector = str(r.get("collector") or "ok")
    queue = str(r.get("queue") or "ok")
    blocked = r.get("blocked") is True
    correct = r.get("target_correct") is not False
    predictions = 0 if collector == "down" else int(r.get("predictions") or 0)
    if blocked:
        verdict = "blocks-the-target"
    elif collector == "down" and correct:
        verdict = "degrades-gracefully"
    elif queue == "full":
        verdict = "drops-on-full"
    else:
        verdict = "predictions-flow"
    return {"format": FORMAT, "predictions": predictions, "collector": collector,
            "queue": queue, "blocked": blocked, "verdict": verdict}


def warmup(rows):
    """Accuracy against faults seen, and whether a short target ever gets warm."""
    rows = [r or {} for r in (rows or [])]
    if not rows:
        return {"format": FORMAT, "verdict": "no-targets"}
    peak = max(float(r.get("accuracy") or 0.0) for r in rows)
    target = 0.9 * peak
    plateau = None
    for row in sorted(rows, key=lambda r: int(r.get("faults_seen") or 0)):
        if float(row.get("accuracy") or 0.0) >= target:
            plateau = int(row.get("faults_seen") or 0)
            break
    lifetimes = [int(r.get("lifetime_faults") or 0) for r in rows]
    short = [n for n in lifetimes if n and plateau is not None and plateau > n / 2.0]
    return {"format": FORMAT, "plateau_faults": plateau,
            "lifetime_faults": lifetimes, "short_lived": len(short),
            "verdict": "warmup-dominates" if short else "warmup-amortised"}


def audit(record):
    """The misreadings the paper names, each as a finding."""
    r = record or {}
    findings = []
    if r.get("simulator_only") is True:
        findings.append({"kind": "simulator-only",
                         "why": "the systems questions appear only in a deployed pipeline"})
    if r.get("ignores_latency") is True:
        findings.append({"kind": "latency-ignored",
                         "why": "accurate predictions that arrive late lose the fault-avoidance win"})
    if r.get("corpus_specific_encoding") is True:
        findings.append({"kind": "corpus-specific-encoding",
                         "why": "absolute or fixed-vocabulary encodings tie the model to one trace"})
    if r.get("unbounded_vocabulary") is True:
        findings.append({"kind": "unbounded-vocabulary",
                         "why": "a cap trades eviction against a larger output space"})
    if r.get("blocking_backpressure") is True:
        findings.append({"kind": "blocking-backpressure",
                         "why": "a full queue must drop a prediction, not stall the target"})
    if r.get("unauthenticated_channel") is True:
        findings.append({"kind": "unauthenticated-channel",
                         "why": "the prediction socket is an attack surface, not a solved problem"})
    if not findings:
        findings.append({"kind": "audit-conditions-met"})
    return {"format": FORMAT, "findings": findings}


def advise(profile):
    """Map a harness profile onto the paper's failure modes."""
    p = profile or {}
    have = {str(k) for k, v in p.items() if v}
    checks = (
        ("observes_the_access_stream", "waits_for_the_demand",
         "a prefetch needs a stream to learn from before the fault"),
        ("measures_arrival_latency", "measures_accuracy_only",
         "the win depends on prediction latency against inter-arrival time"),
        ("uses_online_ordinal_ranks", "fixed_offline_vocabulary",
         "ranks over deltas transfer across targets without retraining"),
        ("bounds_the_vocabulary", "unbounded_table",
         "eviction is a trade, but no cap is not a design"),
        ("drops_when_the_queue_is_full", "blocks_the_target",
         "the safer failure mode is a dropped prediction"),
        ("degrades_with_a_dead_collector", "assumes_the_observer_lives",
         "no predictions is acceptable; a broken target is not"),
        ("splits_mechanism_from_policy", "couples_model_and_host",
         "a faster predictor should not require a new data path"),
    )
    findings = []
    for key, kind, why in checks:
        if key not in have:
            findings.append({"kind": kind, "why": why})
    return {"format": FORMAT, "findings": findings}
