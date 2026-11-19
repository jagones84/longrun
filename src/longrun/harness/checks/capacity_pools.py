#!/usr/bin/env python3
"""Capacity pools — admission at the gateway, priced in inference units.

Source: arXiv:2603.00356, "Token Management in Multi-Tenant AI Inference
Platforms" (round 143). Rate limits govern admission without regard to execution
cost, and dedicated endpoints strand capacity; a token pool expresses capacity as
explicit entitlements in inference-native units and authorizes admission and
autoscaling from the same model (`token_pools_capacity_2603.00356.txt:16`, `:20`).

  * **three schedulable resources**: token throughput, KV-cache bytes, and active
    concurrency; rate limits govern only the first (`:140`, `:152`, `:155`).
  * **five service classes** fix protection ordering: dedicated and guaranteed
    are never shrunk; elastic may shrink and accumulates debt; spot is throttled
    first; preemptible is evicted (`:195`, `:198`, `:208`).
  * **priority is one scalar** from class, SLO urgency, burst history and debt
    (`:164`, `:170`); debt is an EWMA of the service gap, the integral term that
    drives fair-share convergence (`:191`, `:194`).
  * **burst intensity** sums the over-baseline ratios on all three dimensions
    (`:225`, `:232`).
  * **admission checks are ordered and short-circuit**: bound state, concurrency,
    token budget, then the contention threshold; a denial is 429 + Retry-After
    (`:301`, `:313`, `:316`).
  * **measured**: guaranteed P99 stays under 1.2 s during a 38% overload while
    the uncontrolled baseline degrades past 19 s, and debt narrows the priority
    gap from 4.6x to 3.9x (`:359`, `:366`, `:427`, `:430`).

  * `classes()` / `classify(name)` — the service-class table.
  * `priority(row)` — the single priority scalar.
  * `debt(row)` / `burst(row)` — the two EWMA updates.
  * `resources(row)` — KV bytes per token and the concurrency ceiling.
  * `admission(row)` — the ordered checks and the 429 path.
  * `reclaim(items)` — who yields first.
  * `protect(rows)` — bounded protected latency under overload.
  * `fairshare(rows)` — whether debt narrows the gap.
  * `advise(profile)` — map a harness profile onto the paper's failure modes.

Pure: entitlements in; admission decisions out.
"""
from __future__ import annotations

FORMAT = "longrun-capacity-pools/1"

CLASS_TABLE = {
    "dedicated": {"baseline": "reserved", "burst": True, "shrink": "never",
                  "weight": 1000.0},
    "guaranteed": {"baseline": "reserved", "burst": False, "shrink": "never",
                   "weight": 1000.0},
    "elastic": {"baseline": "time-averaged", "burst": True, "shrink": "yes",
                "weight": 100.0},
    "spot": {"baseline": "none", "burst": True, "shrink": "yes", "weight": 1.0},
    "preemptible": {"baseline": "none", "burst": True, "shrink": "evict",
                    "weight": 0.1},
}
RECLAIM_ORDER = ("preemptible", "spot", "elastic")


def _num(value, default=None):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def classes():
    """The table, copied so a caller cannot mutate the module constant."""
    return {name: dict(row) for name, row in CLASS_TABLE.items()}


def classify(name):
    """One service class, or the names that exist."""
    row = CLASS_TABLE.get(str(name))
    if row is None:
        return {"format": FORMAT, "verdict": "unknown-class",
                "known": sorted(CLASS_TABLE)}
    return {"format": FORMAT, "class": str(name), **row}


def priority(row):
    """One scalar: class x SLO urgency / burst history x debt."""
    r = row or {}
    cls = str(r.get("class") or "elastic")
    if cls not in CLASS_TABLE:
        return {"format": FORMAT, "verdict": "unknown-class", "detail": cls}
    base = _num(r.get("base_weight"), CLASS_TABLE[cls]["weight"])
    slo = _num(r.get("slo_ms"))
    avg = _num(r.get("avg_slo_ms"))
    burst = max(0.0, _num(r.get("burst"), 0.0))
    debt = _num(r.get("debt"), 0.0)
    a_slo = _num(r.get("alpha_slo"), 2.0)
    a_burst = _num(r.get("alpha_burst"), 1.0)
    a_debt = _num(r.get("alpha_debt"), 4.0)
    if slo is None or avg is None or avg <= 0:
        return {"format": FORMAT, "verdict": "slo-missing"}
    # The paper reports 93.8 and 20.3 for SLOs of 500 ms and 30 s against a
    # 15,250 ms pool average, which is the magnitude of the deviation term
    # (|1 + a_slo*(slo/avg - 1)|), not the signed value.
    urgency = abs(1.0 + a_slo * (slo / avg - 1.0))
    weight = base * urgency / (1.0 + a_burst * burst) * (1.0 + a_debt * debt)
    return {"format": FORMAT, "class": cls, "weight": weight,
            "urgency": urgency, "burst": burst, "debt": debt,
            "verdict": "priority-computed"}


def debt(row):
    """EWMA of the service gap: underservice raises priority next time."""
    r = row or {}
    prev = _num(r.get("prev_debt"), 0.0)
    entitled = _num(r.get("entitled"))
    served = _num(r.get("served"))
    gamma = _num(r.get("gamma"), 0.7)
    if entitled is None or entitled <= 0 or served is None:
        return {"format": FORMAT, "verdict": "state-incomplete"}
    gap = (entitled - served) / entitled
    value = gamma * prev + (1.0 - gamma) * gap
    return {"format": FORMAT, "gap": gap, "debt": value,
            "accruing": value > prev}


def burst(row):
    """Over-baseline across throughput, KV and concurrency, smoothed."""
    r = row or {}
    prev = _num(r.get("prev_burst"), 0.0)
    gamma = _num(r.get("gamma"), 0.7)
    total = 0.0
    for name in ("throughput", "kv", "concurrency"):
        alloc = _num(r.get(name))
        ent = _num(r.get(name + "_entitled"))
        if alloc is None or ent is None or ent <= 0:
            continue
        total += max(0.0, alloc / ent - 1.0)
    value = gamma * prev + (1.0 - gamma) * total
    return {"format": FORMAT, "instant": total, "burst": value,
            "sustained": value > 0.5}


def resources(row):
    """KV bytes per token and the maximum concurrency they permit."""
    r = row or {}
    layers = _num(r.get("layers"))
    heads = _num(r.get("kv_heads"))
    dim = _num(r.get("head_dim"))
    size = _num(r.get("element_bytes"), 2.0)
    context = _num(r.get("context"))
    gpu = _num(r.get("gpu_kv_bytes"))
    wanted = _num(r.get("concurrency"), 0.0)
    if None in (layers, heads, dim, context):
        return {"format": FORMAT, "verdict": "state-incomplete"}
    per_token = 2.0 * layers * heads * dim * size
    kv_bytes = context * per_token
    if gpu is None or kv_bytes <= 0:
        return {"format": FORMAT, "per_token_bytes": per_token,
                "sequence_bytes": kv_bytes, "verdict": "no-capacity"}
    ceiling = int(gpu // kv_bytes)
    return {"format": FORMAT, "per_token_bytes": per_token,
            "sequence_bytes": kv_bytes, "max_concurrency": ceiling,
            "wanted": wanted,
            "verdict": "kv-bound" if ceiling < wanted else "concurrency-fits"}


def admission(row):
    """Ordered checks; the first failure short-circuits with its own reason."""
    r = row or {}
    checks = []
    state = str(r.get("state") or "bound")
    if state != "bound":
        return {"format": FORMAT, "admitted": False, "status": 503,
                "reason": "state-" + state}
    checks.append("state")
    inflight = _num(r.get("inflight"), 0.0)
    concurrency = _num(r.get("concurrency"))
    if concurrency is not None and inflight >= concurrency:
        return {"format": FORMAT, "admitted": False, "status": 429,
                "reason": "concurrency-limit", "retry_after": 1}
    checks.append("concurrency")
    need = _num(r.get("request_tokens"))
    remaining = _num(r.get("remaining_tokens"))
    if need is not None and remaining is not None and need > remaining:
        return {"format": FORMAT, "admitted": False, "status": 429,
                "reason": "token-budget", "retry_after": 2}
    checks.append("budget")
    if r.get("contended") is True:
        mine = _num(r.get("priority"), 0.0)
        threshold = _num(r.get("threshold"), 0.0)
        if mine < threshold:
            return {"format": FORMAT, "admitted": False, "status": 429,
                    "reason": "below-contention-threshold", "retry_after": 5}
        checks.append("contention")
    return {"format": FORMAT, "admitted": True, "status": 200,
            "reason": "admitted", "checks": checks}


def reclaim(items):
    """Who yields first: preemptible, then spot, then elastic; others never."""
    rows = []
    for item in items or []:
        cls = str((item or {}).get("class") or "")
        name = (item or {}).get("id")
        if cls in RECLAIM_ORDER:
            rows.append({"id": name, "class": cls,
                         "order": RECLAIM_ORDER.index(cls),
                         "action": "evict" if cls == "preemptible" else "throttle"})
        elif cls in ("dedicated", "guaranteed"):
            rows.append({"id": name, "class": cls, "order": 99,
                         "action": "never"})
        else:
            rows.append({"id": name, "class": cls, "order": 98,
                         "action": "unknown"})
    rows.sort(key=lambda r: r["order"])
    return {"format": FORMAT, "rows": rows,
            "verdict": "protection-ordering" if rows else "no-entitlements"}


def protect(rows):
    """A protected class keeps bounded latency while the pool is overloaded."""
    clean = []
    for row in rows or []:
        arm = str((row or {}).get("arm") or "")
        p99 = _num((row or {}).get("p99_s"))
        if not arm or p99 is None:
            continue
        clean.append({"arm": arm, "p99": p99})
    managed = next((r for r in clean if "pool" in r["arm"].lower()
                    or "managed" in r["arm"].lower()), None)
    baseline = next((r for r in clean if "baseline" in r["arm"].lower()
                     or "direct" in r["arm"].lower()), None)
    if not managed or not baseline:
        return {"format": FORMAT, "verdict": "two-arms-required"}
    bounded = managed["p99"] <= 1.2 and baseline["p99"] >= 5.0
    return {"format": FORMAT, "managed": managed, "baseline": baseline,
            "ratio": baseline["p99"] / managed["p99"],
            "verdict": "bounded-protected-latency" if bounded
            else "latency-unbounded"}


def fairshare(rows):
    """Debt should narrow the priority gap while respecting the SLO order."""
    r = rows or {}
    before = _num(r.get("gap_before"))
    after = _num(r.get("gap_after"))
    if before is None or after is None:
        return {"format": FORMAT, "verdict": "state-incomplete"}
    return {"format": FORMAT, "gap_before": before, "gap_after": after,
            "narrowed": after < before,
            "verdict": "debt-narrows-gap" if after < before
            else "debt-does-not-bind"}


def advise(profile):
    """Map a harness profile onto the paper's failure modes."""
    p = profile or {}
    have = {str(k) for k, v in p.items() if v}
    checks = (
        ("prices_in_inference_units", "tokens-per-minute-only",
         "a rate limit ignores KV and concurrency"),
        ("declares_service_classes", "one-class-for-all",
         "without classes there is no protection ordering"),
        ("accumulates_debt", "static-quota",
         "a shrunk tenant never gets the capacity back"),
        ("tracks_burst_dimensions", "throughput-only",
         "prompt and session bursts exhaust KV first"),
        ("admits_at_the_gateway", "rejects-at-the-gpu",
         "by then the resources are already committed"),
        ("denies_with_retry_after", "silent-drop",
         "a client needs a backoff hint"),
    )
    findings = []
    for key, kind, why in checks:
        if key not in have:
            findings.append({"kind": kind, "why": why})
    return {"format": FORMAT, "findings": findings}
