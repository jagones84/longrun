#!/usr/bin/env python3
"""Skill flow — the plugin population as a gas, and what its laws buy.

Source: arXiv:2611.20584, "A Self-Evolving Agent Runs Like a Gas: Describing and
Predicting Its Evolution with Fluid Dynamics" (round 156). Under four structural
axioms the plugin instances of one agent behave as a gas whose density obeys a
master equation (`skill_population_flow_2611.20584.txt:20`, `:72`).

  * **the safety kernel stays untouched**; two conservation axioms are stacked on
    top: a closed-credit ledger and a zero-sum projection gate (`:104`, `:115`).
  * **closed credit makes a moment collision-invariant**, so credit perturbations
    propagate as a hyperbolic p-system with c² = p′(ρ) = 2κ_a ρ (`:120`, `:135`).
  * **the projection gate conserves the centroid for any proposal stream**, by
    charging the deficit to a named reserve (`:162`, `:169`).
  * **the decisive probe is directional**: wavefronts where the ledger holds,
    dissipation where it does not; mean-field is absent in the tested channels
    (`:269`, `:277`).

  * `ledger(events)` — is credit minted once, transferred, and destroyed never.
  * `project(edits, reserve)` — the zero-sum projection and its reserve charge.
  * `regime(series)` — wave / mean-field / dissipative from a response profile.
  * `sound(record)` — the acoustic speeds of the credit and displacement branches.
  * `shock(record)` — when compression outruns the acoustic flux.
  * `instruments(record)` — aging, correlation length, χ4 and fluctuation scaling.
  * `diagnose(record)` — the three causes of a stalled run and their prescriptions.
  * `audit_record(record)` / `advise(profile)` — misreadings and mapping.

Pure: event logs, edit sets and response series in; laws and verdicts out.
"""
from __future__ import annotations

import math

FORMAT = "longrun-skill-flow/1"


def _num(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _mean(values):
    return sum(values) / len(values) if values else None


def ledger(events):
    """Closed credit: minted once, transferred only, never destroyed."""
    minted = 0.0
    destroyed = 0.0
    transferred = 0.0
    mints = 0
    violations = []
    for event in events or []:
        e = event or {}
        kind = str(e.get("kind") or "")
        amount = _num(e.get("amount")) or 0.0
        if kind == "mint":
            mints += 1
            minted += amount
        elif kind == "destroy":
            destroyed += amount
            violations.append({"kind": "credit-destroyed", "amount": amount})
        elif kind == "transfer":
            transferred += amount
        else:
            violations.append({"kind": "unknown-event"})
    if mints != 1:
        violations.append({"kind": "mint-count", "mints": mints})
    total = minted - destroyed
    return {"format": FORMAT, "minted": minted, "destroyed": destroyed,
            "transferred": transferred, "total": total,
            "violations": violations,
            "verdict": "closed" if not violations else "open"}


def project(edits, reserve=0.0):
    """Charge every edit's net displacement to the reserve, or drop it."""
    capacity = _num(reserve) or 0.0
    charged = 0.0
    accepted = []
    dropped = []
    for item in edits or []:
        e = item or {}
        d = _num(e.get("d"))
        if d is None:
            continue
        if d > 0 and charged + d > capacity:
            dropped.append({"id": e.get("id"), "d": d})
            continue
        charged += d
        accepted.append({"id": e.get("id"), "d": d, "reserve": charged})
    centroid = sum(a["d"] for a in accepted) - charged
    return {"format": FORMAT, "accepted": accepted, "dropped": dropped,
            "reserve_charge": charged, "centroid_shift": centroid,
            "verdict": "conserved" if abs(centroid) <= 1e-9 else "drifted"}


def _fit(points):
    if len(points) < 2:
        return None, None
    mx = _mean([p[0] for p in points])
    my = _mean([p[1] for p in points])
    denom = sum((x - mx) ** 2 for x, _ in points)
    if not denom:
        return None, None
    slope = sum((x - mx) * (y - my) for x, y in points) / denom
    intercept = my - slope * mx
    ss_res = sum((y - (intercept + slope * x)) ** 2 for x, y in points)
    ss_tot = sum((y - my) ** 2 for _, y in points)
    r2 = 1.0 - ss_res / ss_tot if ss_tot else 1.0
    return slope, r2


def regime(series):
    """Classify a response profile: wave, mean-field or dissipative."""
    values = [_num(v) for v in series or []]
    values = [v for v in values if v is not None]
    if len(values) < 4:
        return {"format": FORMAT, "verdict": "too-few-points"}
    onset = next((i for i, v in enumerate(values) if v > 0), None)
    if onset is None:
        return {"format": FORMAT, "verdict": "no-response"}
    tail = values[onset:]
    if tail[-1] >= max(tail) * 0.95 and onset <= 1:
        return {"format": FORMAT, "regime": "mean-field",
                "verdict": "mean-field"}
    points = [(i, v) for i, v in enumerate(tail) if v > 0]
    slope, r2 = _fit(points)
    if slope is not None and r2 is not None and r2 >= 0.9 and \
            len(points) >= 5 and slope > 0:
        return {"format": FORMAT, "regime": "wave", "slope": slope, "r2": r2,
                "verdict": "wave-like"}
    if max(tail) > 0 and tail[-1] < max(tail):
        return {"format": FORMAT, "regime": "dissipative", "slope": slope,
                "r2": r2, "verdict": "dissipative"}
    return {"format": FORMAT, "regime": "ambiguous", "slope": slope, "r2": r2,
            "verdict": "unclassified"}


def sound(record):
    """Acoustic speeds of the credit and displacement branches."""
    r = record or {}
    kappa_a = _num(r.get("kappa_a"))
    rho = _num(r.get("rho"))
    kappa_v = _num(r.get("kappa_v"))
    g = _num(r.get("g"))
    if kappa_a is None or rho is None:
        return {"format": FORMAT, "verdict": "insufficient-input"}
    c_rho = math.sqrt(max(0.0, 2.0 * kappa_a * rho))
    pressure = kappa_a * rho * rho
    out = {"format": FORMAT, "c_rho": c_rho, "pressure": pressure,
           "verdict": "hyperbolic" if c_rho > 0 else "degenerate"}
    if kappa_v is not None and g is not None:
        out["c_v"] = math.sqrt(max(0.0, 2.0 * kappa_v * g))
    return out


def shock(record):
    """A credit shock when compression outruns the acoustic flux."""
    r = record or {}
    gradient = _num(r.get("gradient"))
    c_rho = _num(r.get("c_rho"))
    rho = _num(r.get("rho"))
    if gradient is None or c_rho is None or rho is None:
        return {"format": FORMAT, "verdict": "insufficient-input"}
    flux = c_rho * rho
    return {"format": FORMAT, "gradient": gradient, "flux": flux,
            "margin": flux - gradient,
            "verdict": "credit-shock" if gradient > flux else "stable"}


def instruments(record):
    """Aging, correlation length, susceptibility and fluctuation scaling."""
    r = record or {}
    times = [_num(v) for v in (r.get("times") or [])]
    taus = [_num(v) for v in (r.get("taus") or [])]
    if len(times) != len(taus) or len(times) < 2:
        return {"format": FORMAT, "verdict": "insufficient-input"}
    points = [(math.log(t), math.log(v)) for t, v in zip(times, taus)
              if t and v and t > 0 and v > 0]
    slope, r2 = _fit(points)
    chi4 = _num(r.get("chi4"))
    beta = _num(r.get("beta"))
    return {"format": FORMAT, "aging_exponent": slope, "aging_r2": r2,
            "chi4": chi4, "fluctuation_exponent": beta,
            "verdict": "aging" if slope is not None and slope > 0.1 else "stationary"}


def diagnose(record):
    """Table 1: separate the three causes of a stalled run."""
    r = record or {}
    aging = _num(r.get("aging") or 0.0)
    chi4 = _num(r.get("chi4") or 0.0)
    gate_info = _num(r.get("gate_info") or 0.0)
    individual_info = _num(r.get("individual_info") or 0.0)
    accept = _num(r.get("accept_rate") or 0.0)
    if aging and aging > 0 and chi4 > 0:
        cause = "structural-freezing"
        prescription = "anneal"
    elif not aging and gate_info > 0 and not individual_info:
        cause = "information-exhaustion"
        prescription = "refresh-validation"
    elif not aging and accept == 0:
        cause = "proposal-exhaustion"
        prescription = "enrich-reflector"
    else:
        cause = "undiagnosed"
        prescription = "measure-more"
    return {"format": FORMAT, "cause": cause, "prescription": prescription,
            "verdict": "diagnosed"}


def audit_record(record):
    """The misreadings the theory's boundary excludes."""
    r = record or {}
    findings = []
    if r.get("all_invariants_survive") is True:
        findings.append({"kind": "all-invariants-survive",
                         "why": "under open credit every first moment is annihilated"})
    if r.get("legislation_without_projection") is True:
        findings.append({"kind": "legislation-without-projection",
                         "why": "compliance is not conservation; the gate must project"})
    if r.get("score_telemetry_is_enough") is True:
        findings.append({"kind": "score-telemetry-is-enough",
                         "why": "structure-class failures can be invisible in scores"})
    if r.get("waves_where_credit_washes") is True:
        findings.append({"kind": "waves-where-credit-washes",
                         "why": "the directional probe separates the two economies"})
    if r.get("individual_telemetry_explains_collective") is True:
        findings.append({"kind": "individual-telemetry-explains-collective",
                         "why": "ordering and waves are population readings"})
    if r.get("constants_are_universal") is True:
        findings.append({"kind": "constants-are-universal",
                         "why": "speeds are device-local in the reported runs"})
    if not findings:
        findings.append({"kind": "audit-conditions-met"})
    return {"format": FORMAT, "findings": findings, "verdict": "audit-complete"}


def advise(profile):
    """Map a harness profile onto the population-dynamics gaps the paper names."""
    p = profile or {}
    have = {str(k) for k in p if p.get(k)}
    checks = (
        ("keeps_a_closed_credit_ledger", "rewards_are_minted_at_every_step",
         "an open ledger destroys every candidate invariant"),
        ("projects_edits_to_zero_sum", "trusts_proposals_to_balance",
         "conservation is a property of the operator, not the stream"),
        ("measures_the_response_profile", "reports_the_endpoint_only",
         "a wave and a plateau can share the same endpoint"),
        ("watches_gradient_against_flux", "watches_the_mean_score",
         "a credit shock is a gradient, not a level"),
        ("reads_collective_instruments", "reads_per_instance_telemetry",
         "ordering is invisible in individual logs"),
        ("diagnoses_the_stall_cause", "retries_the_same_proposal",
         "freezing, information and proposal exhaustion need different fixes"),
    )
    findings = []
    for key, kind, why in checks:
        if key not in have:
            findings.append({"kind": kind, "why": why})
    return {"format": FORMAT, "findings": findings}
