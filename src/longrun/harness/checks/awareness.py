#!/usr/bin/env python3
"""Harness awareness — verified host state as a decision input, not a second authority.

Source: arXiv:2611.05391, "Agent Harness Awareness: Turning Verified Telemetry
into Operational Control for Tool-Using Agents" (round 154). Tool descriptions say
what an action can do; they do not say whether the route is healthy *now*. The host
measures, reduces and bounds the state, the model chooses among eligible actions,
and the host revalidates and dispatches (`harness_awareness_2611.05391.txt:74-100`).

  * **the interface is bounded and freshness-labelled**: the reducer emits a small
    projection with provenance and an age bound, never the raw monitor
    (`:16`, `:96`).
  * **cost is observable**: c(r, z) = latency + 10,000·p_f + 10,000·1[circuit OPEN]
    with p_f = (n−s)/n and 0.5 when no window exists (`:182-190`).
  * **regret is excess cost against the best eligible route**, so 0 ms means no
    avoidable operational cost, not zero request duration (`:169-180`).
  * **the structural control matters**: B carries the same envelope with neutral
    values, so B→C attributes the gain to the facts rather than the shape
    (`:156-168`).
  * **host authority survives**: measurement, enforcement, evaluation and dispatch
    stay host-owned; the model may adapt its choice and nothing else (`:18`,
    `:80-82`).

  * `reduce(observations)` — spans to route rows (EWMA α=0.2, circuit rules).
  * `cost(row)` — the frozen operational cost of one route.
  * `best(rows)` / `regret(rows, choice)` — the observable-best set and excess.
  * `snapshot(rows, now)` — bounded, redacted, freshness-labelled projection.
  * `choose(snapshot, action)` — host revalidation, refusal and dispatch.
  * `ablate(arms)` — A/B/C means, deltas and per-model consistency.
  * `wilson(k, n)` — the interval the paper reports completions with.
  * `authority(record)` — the trust-separation checks.
  * `audit(record)` / `advise(profile)` — misreadings and harness mapping.

Pure: observations, rows and arms in; costs, regrets and verdicts out.
"""
from __future__ import annotations

import math

FORMAT = "longrun-awareness/1"

FAILURE_COST_MS = 10000.0
NO_WINDOW_FAIL = 0.5
OPEN_AFTER = 3
DEGRADED_FRACTION = 0.4
EWMA_ALPHA = 0.2
WAIT_DEFER_MS = 500.0
WAIT_MISS_MS = 10000.0
DEFAULT_MAX_AGE_MS = 2000.0

CONDITIONS = ("A", "B", "C")
ALLOWED_FIELDS = ("route", "n", "s", "latency_ewma", "consec_fail",
                  "last_error", "circuit", "observed_at")


def _num(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def reduce(observations, window=None):
    """Turn probe observations into bounded route rows, one per route."""
    rows = {}
    order = []
    for obs in observations or []:
        o = obs or {}
        route = str(o.get("route") or "")
        if not route:
            continue
        if route not in rows:
            rows[route] = []
            order.append(route)
        ok = o.get("ok") is True
        ms = _num(o.get("ms"))
        rows[route].append({"ok": ok, "ms": ms if ms is not None else 0.0})
    if not order:
        return {"format": FORMAT, "verdict": "no-observations"}
    out = []
    for route in order:
        history = rows[route]
        if window:
            history = history[-int(window):]
        n = len(history)
        successes = sum(1 for h in history if h["ok"])
        ewma = None
        consec = 0
        last_error = None
        for h in history:
            ewma = h["ms"] if ewma is None else (EWMA_ALPHA * h["ms"]
                                                 + (1 - EWMA_ALPHA) * ewma)
            if h["ok"]:
                consec = 0
            else:
                consec += 1
                last_error = "probe-failed"
        failures = n - successes
        if consec >= OPEN_AFTER:
            circuit = "OPEN"
        elif n >= OPEN_AFTER and failures / n >= DEGRADED_FRACTION:
            circuit = "DEGRADED"
        else:
            circuit = "CLOSED"
        out.append({"route": route, "n": n, "s": successes,
                    "failure_fraction": (failures / n) if n else NO_WINDOW_FAIL,
                    "latency_ewma": ewma or 0.0, "consec_fail": consec,
                    "last_error": last_error, "circuit": circuit})
    return {"format": FORMAT, "rows": out, "verdict": "reduced"}


def cost(row):
    """The frozen route cost, in operational-cost units (milliseconds)."""
    r = row or {}
    latency = _num(r.get("latency_ewma"))
    if latency is None:
        return {"format": FORMAT, "verdict": "insufficient-input"}
    n = _num(r.get("n"))
    s = _num(r.get("s"))
    if n and n > 0 and s is not None:
        pf = max(0.0, (n - s) / n)
    else:
        pf = NO_WINDOW_FAIL
    opened = 1.0 if str(r.get("circuit") or "").upper() == "OPEN" else 0.0
    total = latency + FAILURE_COST_MS * pf + FAILURE_COST_MS * opened
    return {"format": FORMAT, "route": r.get("route"), "latency": latency,
            "failure_fraction": pf, "open": bool(opened),
            "cost_ms": total, "verdict": "priced"}


def best(rows):
    """Every route tied at the observable minimum, with that cost."""
    priced = [c for c in (cost(r) for r in rows or []) if c.get("cost_ms") is not None]
    if not priced:
        return {"format": FORMAT, "verdict": "no-rows"}
    low = min(c["cost_ms"] for c in priced)
    winners = [c["route"] for c in priced if abs(c["cost_ms"] - low) <= 1e-9]
    return {"format": FORMAT, "best": winners, "cost_ms": low,
            "verdict": "observable-best"}


def regret(rows, choice):
    """Excess cost of the chosen action against the observable-best route."""
    b = best(rows)
    if b.get("cost_ms") is None:
        return {"format": FORMAT, "verdict": "no-rows"}
    choice = str(choice or "")
    if choice == "wait":
        score = WAIT_DEFER_MS + WAIT_MISS_MS - b["cost_ms"]
        return {"format": FORMAT, "choice": "wait", "regret_ms": max(0.0, score),
                "best": b["best"], "verdict": "waited"}
    row = next((r for r in rows or [] if str(r.get("route")) == choice), None)
    if row is None:
        return {"format": FORMAT, "verdict": "unknown-route"}
    c = cost(row)
    return {"format": FORMAT, "choice": choice,
            "regret_ms": max(0.0, c["cost_ms"] - b["cost_ms"]),
            "best": b["best"], "verdict": "compared"}


def snapshot(rows, now=None, max_age_ms=DEFAULT_MAX_AGE_MS, max_rows=None,
             verified=True):
    """Bound, redact and freshness-label the state before the model sees it."""
    bound = _num(max_age_ms)
    if bound is None or bound <= 0:
        return {"format": FORMAT, "verdict": "insufficient-input"}
    kept = []
    dropped = []
    redacted = 0
    now_ms = _num(now) if now is not None else None
    for row in rows or []:
        r = dict(row or {})
        unknown = [k for k in r if k not in ALLOWED_FIELDS]
        redacted += len(unknown)
        for k in unknown:
            r.pop(k, None)
        if now_ms is not None and r.get("observed_at") is not None:
            observed = _num(r.get("observed_at"))
            if observed is None:
                # R160 bug hunt: an ISO timestamp (the normal shape a recorded
                # observation has) made `_num` return None and the subtraction
                # raised TypeError. An unreadable timestamp cannot be freshness-
                # checked; keep the row and do not claim an age.
                r["age_ms"] = None
                kept.append(r)
                continue
            age = now_ms - observed
            if age is not None and age > bound:
                dropped.append({"route": r.get("route"), "reason": "stale",
                                "age_ms": age})
                continue
            r["age_ms"] = age
        kept.append(r)
    omitted = 0
    if max_rows is not None and len(kept) > int(max_rows):
        omitted = len(kept) - int(max_rows)
        kept = kept[:int(max_rows)]
    if not kept:
        return {"format": FORMAT, "rows": [], "dropped": dropped,
                "redacted": redacted, "freshness_bound_ms": bound,
                "dispatchable": False, "verdict": "stale-snapshot"}
    if verified is not True:
        return {"format": FORMAT, "rows": kept, "dropped": dropped,
                "redacted": redacted, "omitted": omitted,
                "freshness_bound_ms": bound, "dispatchable": False,
                "attribution": "interface-only", "verdict": "neutral-envelope"}
    return {"format": FORMAT, "rows": kept, "dropped": dropped,
            "redacted": redacted, "omitted": omitted,
            "freshness_bound_ms": bound, "dispatchable": True,
            "attribution": "verified-state", "verdict": "verified-snapshot"}


def choose(snap, action, current=None):
    """Model choice first, host revalidation and dispatch second."""
    s = snap or {}
    if s.get("verdict") != "verified-snapshot" or s.get("dispatchable") is not True:
        return {"format": FORMAT, "dispatched": False,
                "reason": "snapshot-not-verified", "verdict": "refused"}
    action = str(action or "")
    routes = [str(r.get("route")) for r in s.get("rows") or []]
    if action != "wait" and action not in routes:
        return {"format": FORMAT, "dispatched": False,
                "reason": "ineligible-action", "verdict": "refused"}
    if current is not None:
        row = next((r for r in current or [] if str(r.get("route")) == action), None)
        if action != "wait" and row is not None and \
                str(row.get("circuit") or "").upper() == "OPEN":
            return {"format": FORMAT, "dispatched": False,
                    "reason": "revalidation-refused", "verdict": "refused"}
    return {"format": FORMAT, "dispatched": True, "route": action,
            "model_may_edit_state": False, "host_dispatches": True,
            "verdict": "dispatched"}


def wilson(k, n, z=1.96):
    """Wilson score interval for a completion count."""
    if not n:
        return None
    p = k / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return {"low": max(0.0, centre - half), "high": min(1.0, centre + half)}


def ablate(arms):
    """A/B/C means, completion counts and the B→C and A→C contrasts."""
    by_condition = {c: {"regret": [], "completed": 0, "decisions": 0}
                    for c in CONDITIONS}
    by_model = {}
    for arm in arms or []:
        a = arm or {}
        cond = str(a.get("condition") or "").upper()
        if cond not in by_condition:
            continue
        regret = _num(a.get("regret"))
        if regret is None:
            continue
        by_condition[cond]["regret"].append(regret)
        by_condition[cond]["decisions"] += 1
        completed = a.get("completed") is True
        if completed:
            by_condition[cond]["completed"] += 1
        model = str(a.get("model") or "")
        if model:
            slot = by_model.setdefault(model, {c: [] for c in CONDITIONS})
            slot[cond].append(regret)
    if not any(v["decisions"] for v in by_condition.values()):
        return {"format": FORMAT, "verdict": "no-arms"}
    means = {c: (sum(v["regret"]) / len(v["regret"]) if v["regret"] else None)
             for c, v in by_condition.items()}
    deltas = {}
    if means["B"] is not None and means["C"] is not None:
        deltas["B_to_C"] = means["B"] - means["C"]
    if means["A"] is not None and means["C"] is not None:
        deltas["A_to_C"] = means["A"] - means["C"]
    consistent = []
    for model, slot in by_model.items():
        mb = sum(slot["B"]) / len(slot["B"]) if slot["B"] else None
        mc = sum(slot["C"]) / len(slot["C"]) if slot["C"] else None
        if mb is not None and mc is not None:
            consistent.append(mc < mb)
    dominates = bool(consistent) and all(consistent)
    return {"format": FORMAT,
            "means": means,
            "completion": {c: {"done": v["completed"], "n": v["decisions"],
                               "wilson": wilson(v["completed"], v["decisions"])}
                           for c, v in by_condition.items()},
            "deltas": deltas, "per_model_consistent": consistent,
            "verdict": "verified-state-dominates" if dominates
            else "no-consistent-gain"}


def authority(record):
    """The host keeps measurement, enforcement and dispatch; the model adapts."""
    r = record or {}
    findings = []
    if r.get("model_writes_telemetry") is True:
        findings.append({"kind": "model-writes-telemetry",
                         "why": "the state must be host-measured, not model-authored"})
    if r.get("model_dispatches") is True:
        findings.append({"kind": "model-dispatches",
                         "why": "the host revalidates and performs the action"})
    if r.get("unbounded_snapshot") is True:
        findings.append({"kind": "unbounded-snapshot",
                         "why": "the projection is bounded and redacted"})
    if r.get("missing_freshness") is True:
        findings.append({"kind": "missing-freshness",
                         "why": "a snapshot without an age bound is unverifiable"})
    if r.get("neutral_state_marked_verified") is True:
        findings.append({"kind": "neutral-state-marked-verified",
                         "why": "the structural control is not evidence"})
    if not findings:
        findings.append({"kind": "trust-separated"})
    return {"format": FORMAT, "findings": findings, "verdict": "authority-checked"}


def audit(record):
    """The six misreadings the paper's boundaries name."""
    r = record or {}
    findings = []
    if r.get("retries_counted_as_choice") is True:
        findings.append({"kind": "retries-counted-as-choice",
                         "why": "the study isolates first dispatch before recovery"})
    if r.get("regret_read_as_duration") is True:
        findings.append({"kind": "regret-read-as-duration",
                         "why": "0 ms regret is zero avoidable cost, not zero latency"})
    if r.get("envelope_shape_is_the_gain") is True:
        findings.append({"kind": "envelope-shape-is-the-gain",
                         "why": "the B condition holds the shape and neutralises the facts"})
    if r.get("equivalent_routes_tested_only") is True:
        findings.append({"kind": "equivalent-routes-tested-only",
                         "why": "heterogeneous selection is a stated extension"})
    if r.get("one_study_pooled") is True:
        findings.append({"kind": "one-study-pooled",
                         "why": "the seeded and live cohorts are never pooled"})
    if r.get("proxy_replaced_by_model") is True:
        findings.append({"kind": "proxy-replaced-by-model",
                         "why": "routine failover stays in deterministic middleware"})
    if not findings:
        findings.append({"kind": "audit-conditions-met"})
    return {"format": FORMAT, "findings": findings, "verdict": "audit-complete"}


def advise(profile):
    """Map a harness profile onto the paper's operational-blindness modes."""
    p = profile or {}
    have = {str(k) for k, v in p.items() if v}
    checks = (
        ("exposes_route_health", "chooses_from_static_descriptions",
         "the harness knows the route failed; the model does not"),
        ("labels_state_freshness", "uses_an_unbounded_state_dump",
         "a snapshot without an age bound cannot be trusted"),
        ("keeps_dispatch_host_owned", "lets_the_model_dispatch",
         "the model adapts the choice, not the authority"),
        ("bounds_and_redacts_state", "forwards_raw_monitor_rows",
         "state growth is a context cost and a leak"),
        ("prices_failure_and_open_circuits", "compares_latency_only",
         "avoidable failures and open circuits dominate latency"),
        ("uses_a_neutral_control", "compares_against_no_state_only",
         "the envelope alone can move the choice"),
    )
    findings = []
    for key, kind, why in checks:
        if key not in have:
            findings.append({"kind": kind, "why": why})
    return {"format": FORMAT, "findings": findings}
