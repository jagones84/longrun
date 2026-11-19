#!/usr/bin/env python3
"""Local cost — what a solved task costs when the model runs on your machine.

Source: arXiv:2611.24880, "Local AI Agents in Power Electronics Simulation:
Deployment, Measurements and Costs" (round 150). A local agent is an electrical
load: every run draws power, consumes energy, generates tokens and occupies the
device, the simulator licence and the engineer
(`local_agent_costs_2611.24880.txt:29`, `:73`).

  * **four quantities, four units**: power rates the supply, energy sets the
    electricity cost, tokens are the only limit the software enforces, time
    occupies everything else (`:73`, `:77`).
  * **energy decomposes by phase**: `E = Pidle*T + dPdec*tdec + dPpre*tpre`,
    and duration alone reconstructs it to a 2.39% median error (`:389`,
    `:1155`).
  * **the cost of a solved task is set by the success rate**:
    `Esuccess = Epass + (1-p)/p * Efail`, at least `Epass/p` (`:443`, `:459`).
  * **capacity and rate are hard limits**: memory must hold weights, KV cache
    and overhead; decode rate is bounded by bandwidth over bytes read per token
    (`:429`, `:454`).
  * **nominal tokens overstate the work**: 94.9% of input came from cache and
    computed tokens were 6.0% of nominal, a factor of about seventeen (`:1230`,
    `:1234`).
  * **a budget notice is data, not effort**: with the remaining budget in every
    tool result, cap stops fell from 10 of 24 to 2 of 16 and energy per solved
    task fell about 40% (`:1322`, `:1333`).
  * **measured**: plateau 33-38 W against 13-14 W idle, prefill about 1.4 pu of
    the plateau, device busy 94% of the window (`:1050`, `:1162`).

  * `expected(record)` — cost per solved task for energy, time or tokens.
  * `energy(record)` — the three-term decomposition and its shares.
  * `capacity(record)` — weights + KV cache + overhead against device memory.
  * `decode_rate(record)` — the bandwidth bound and its attained fraction.
  * `required_rate(record)` — the rate a completion time demands.
  * `computed(record)` — the cached share and the overstatement factor.
  * `budget_notice(record)` — cap stops and energy per solved task.
  * `compare(record)` — local vs cloud on time, tokens and cost.
  * `audit(record)` — the seven misreadings the paper names.
  * `advise(profile)` — map a harness profile onto the paper's failure modes.

Pure: device constants and run records in; costs and verdicts out.
"""
from __future__ import annotations

FORMAT = "longrun-local-cost/1"

QUANTITIES = ("energy", "time", "tokens")


def _num(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def expected(record):
    """`Epass + (1-p)/p * Efail`, and the factor that dominates it."""
    r = record or {}
    p = _num(r.get("p"))
    passing = _num(r.get("pass_cost"))
    failing = _num(r.get("fail_cost"))
    if p is None or passing is None or failing is None:
        return {"format": FORMAT, "verdict": "insufficient-input"}
    if p <= 0:
        return {"format": FORMAT, "verdict": "never-solves"}
    ratio = failing / passing if passing else None
    cost = passing + (1 - p) / p * failing
    return {"format": FORMAT, "p": p, "cost": cost, "pass_cost": passing,
            "fail_ratio": ratio,
            "multiplier": cost / passing if passing else None,
            "floor": 1.0 / p,
            "verdict": "success-rate-dominated" if p < 0.20
            else "run-cost-matters"}


def energy(record):
    """The three-term energy decomposition and each term's share."""
    r = record or {}
    idle = _num(r.get("idle_power"))
    duration = _num(r.get("duration"))
    delta_decode = _num(r.get("decode_delta"))
    decode_time = _num(r.get("decode_time"))
    delta_prefill = _num(r.get("prefill_delta"))
    prefill_time = _num(r.get("prefill_time"))
    if None in (idle, duration, delta_decode, decode_time,
                delta_prefill, prefill_time):
        return {"format": FORMAT, "verdict": "insufficient-input"}
    idle_term = idle * duration
    decode_term = delta_decode * decode_time
    prefill_term = delta_prefill * prefill_time
    total = idle_term + decode_term + prefill_term
    return {"format": FORMAT, "total": total, "idle_term": idle_term,
            "decode_term": decode_term, "prefill_term": prefill_term,
            "idle_share": idle_term / total if total else None,
            "mean_power": total / duration if duration else None,
            "verdict": "energy-decomposed"}


def capacity(record):
    """Weights, KV cache and overhead must fit the device at once."""
    r = record or {}
    params = _num(r.get("params"))
    weight_bytes = _num(r.get("weight_bytes"))
    context = _num(r.get("context_tokens"))
    per_token = _num(r.get("kv_bytes_per_token"))
    overhead = _num(r.get("overhead_bytes")) or 0.0
    memory = _num(r.get("device_bytes"))
    if None in (params, weight_bytes, context, per_token, memory):
        return {"format": FORMAT, "verdict": "insufficient-input"}
    weights = params * weight_bytes
    cache = context * per_token
    needed = weights + cache + overhead
    return {"format": FORMAT, "weights": weights, "cache": cache,
            "needed": needed, "device": memory,
            "margin": memory - needed,
            "fits": needed <= memory,
            "verdict": "fits" if needed <= memory else "does-not-fit"}


def decode_rate(record):
    """The single-token bandwidth bound and the attained fraction of it."""
    r = record or {}
    bandwidth = _num(r.get("bandwidth"))
    active = _num(r.get("active_params"))
    weight_bytes = _num(r.get("weight_bytes"))
    eta = _num(r.get("eta")) or 1.0
    if None in (bandwidth, active, weight_bytes) or active <= 0:
        return {"format": FORMAT, "verdict": "insufficient-input"}
    bound = bandwidth / (active * weight_bytes)
    return {"format": FORMAT, "bound": bound, "attained": bound * eta,
            "eta": eta,
            "verdict": "rate-bounded"}


def required_rate(record):
    """The decode rate a completion window demands, given duty cycle."""
    r = record or {}
    tokens = _num(r.get("output_tokens"))
    window = _num(r.get("window"))
    busy = _num(r.get("busy_share"))
    p = _num(r.get("p")) or 1.0
    if None in (tokens, window, busy) or busy <= 0 or window <= 0 or p <= 0:
        return {"format": FORMAT, "verdict": "insufficient-input"}
    rate = tokens / (busy * window) / p
    return {"format": FORMAT, "rate": rate,
            "verdict": "rate-required"}


def computed(record):
    """Computed tokens against the nominal count, and the cached share."""
    r = record or {}
    nominal_input = _num(r.get("nominal_input"))
    cached = _num(r.get("cached_share"))
    output = _num(r.get("output_tokens"))
    if None in (nominal_input, cached, output):
        return {"format": FORMAT, "verdict": "insufficient-input"}
    computed_input = nominal_input * (1 - cached)
    total_nominal = nominal_input + output
    total_computed = computed_input + output
    share = total_computed / total_nominal if total_nominal else None
    return {"format": FORMAT, "computed_input": computed_input,
            "total_computed": total_computed, "nominal": total_nominal,
            "share": share,
            "overstatement": (1 / share) if share else None,
            "verdict": "cache-matters" if cached >= 0.50 else "little-cache"}


def budget_notice(record):
    """Cap stops and energy per solved task with and without the notice."""
    r = record or {}
    before = r.get("before") or {}
    after = r.get("after") or {}
    caps_before = _num(before.get("cap_stops"))
    runs_before = _num(before.get("runs"))
    caps_after = _num(after.get("cap_stops"))
    runs_after = _num(after.get("runs"))
    energy_before = _num(before.get("energy_per_solved"))
    energy_after = _num(after.get("energy_per_solved"))
    if None in (caps_before, runs_before, caps_after, runs_after):
        return {"format": FORMAT, "verdict": "insufficient-input"}
    change = (None if None in (energy_before, energy_after) or not energy_before
              else 1 - energy_after / energy_before)
    return {"format": FORMAT,
            "cap_share_before": caps_before / runs_before if runs_before else None,
            "cap_share_after": caps_after / runs_after if runs_after else None,
            "energy_change": change,
            "verdict": "notice-helps" if change is not None and change > 0
            else "notice-neutral"}


def compare(record):
    """Local against cloud on time, tokens and cost per solved task."""
    r = record or {}
    local = r.get("local") or {}
    cloud = r.get("cloud") or {}
    out = {"format": FORMAT}
    for key in ("time", "tokens", "energy"):
        a = _num(local.get(key))
        b = _num(cloud.get(key))
        out[key + "_ratio"] = (a / b) if (a is not None and b) else None
    if all(out[k + "_ratio"] is None for k in QUANTITIES):
        return {"format": FORMAT, "verdict": "insufficient-input"}
    worse = sum(1 for k in QUANTITIES
                if (out[k + "_ratio"] or 0) and out[k + "_ratio"] > 1)
    return dict(out, worse_on=worse,
                verdict="local-slower" if worse >= 2 else "local-comparable")


def audit(record):
    """The seven misreadings the paper names, each as a finding."""
    r = record or {}
    findings = []
    if r.get("nominal_tokens_as_work") is True:
        findings.append({"kind": "nominal-tokens-as-work",
                         "why": "94.9% of input came from cache"})
    if r.get("price_per_token_as_cost") is True:
        findings.append({"kind": "price-per-token-as-cost",
                         "why": "the cost is per solved task, not per token"})
    if r.get("success_rate_omitted") is True:
        findings.append({"kind": "success-rate-omitted",
                         "why": "the (1-p)/p term can dominate everything else"})
    if r.get("window_mean_as_plateau") is True:
        findings.append({"kind": "window-mean-as-plateau",
                         "why": "the duty cycle lowers the mean, not the plateau"})
    if r.get("single_run_as_capability") is True:
        findings.append({"kind": "single-run-as-capability",
                         "why": "a count under conditions is not a capability"})
    if r.get("faster_device_as_cheaper") is True:
        findings.append({"kind": "faster-device-as-cheaper",
                         "why": "decode speed acts on pass and fail cost together"})
    if r.get("no_independent_verification") is True:
        findings.append({"kind": "no-independent-verification",
                         "why": "the agent's own report is not evidence"})
    if not findings:
        findings.append({"kind": "audit-conditions-met"})
    return {"format": FORMAT, "findings": findings, "verdict": "audit-complete"}


def advise(profile):
    """Map a harness profile onto the paper's failure modes."""
    p = profile or {}
    have = {str(k) for k, v in p.items() if v}
    checks = (
        ("measures_power_energy_tokens_time", "reports_tokens_only",
         "one unit cannot describe a local run"),
        ("measures_the_success_rate", "one_run_cost_only",
         "the failure term can be the whole bill"),
        ("verifies_independently", "trusts_the_agent_report",
         "the report and the deliverable are different objects"),
        ("separates_plateau_from_window_mean", "one_power_number",
         "the duty cycle and the plateau are different limits"),
        ("counts_computed_not_nominal_tokens", "counts_context_tokens",
         "cached input is not computed work"),
        ("shows_the_budget_to_the_agent", "hidden_token_cap",
         "an unseen cap produces full-budget failures"),
        ("prices_a_solved_task", "prices_a_token",
         "the buyer pays for solutions"),
    )
    findings = []
    for key, kind, why in checks:
        if key not in have:
            findings.append({"kind": kind, "why": why})
    return {"format": FORMAT, "findings": findings}
