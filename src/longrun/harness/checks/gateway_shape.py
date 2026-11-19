#!/usr/bin/env python3
"""Gateway shape — what a tool gateway should do with its catalog.

Source: arXiv:2611.19123, "Beyond Plain MCP: Do Decision Models and Code Mode
Make Tool Use Cheaper and Faster?" (round 128). A pre-registered comparison of
four gateway configurations -- plain MCP, router + JSON, code mode, router +
code mode -- across three open-weight agents, 119 sealed test instances, 21
task families. What the paper confirms:

  * Code mode is the dominant effect where it lands: +0.364 utility for Qwen,
    +0.861 for Nemotron, 70-90% fewer tokens; not significant for Gemma.
  * The return-shape hints in code-mode stubs are a first-order variable:
    removing them costs 22.7 and 39.5 success points for two of three agents
    (Holm p = 0.0003) -- more than any router effect measured.
  * The central hypothesis, a decision layer in front of code mode, is NOT
    confirmed: -0.028 (Qwen), +0.099 (Gemma), +0.109 (Nemotron) pooled over
    238 instances, none significant after correction.
  * An unbounded JSON fallback is pathological at scale: 223 s and 370K tokens
    at 2,000 tools, versus 16 s and 34K bounded (14x), success 0.40 -> 0.90.
  * Shape routing never beat "always code with a fallback"; a front-door router
    must cost less than roughly 0.4-0.7 s to pay for itself on a fast agent.

  * `utility(cell)` — success minus token and latency costs.
  * `paired_delta(base, cand)` — paired utility delta with a deterministic
    bootstrap interval over matched cells.
  * `holm(pvalues)` / `claim(...)` — corrected significance, tri-state: a
    "not confirmed" is inconclusive, not absent.
  * `stub(tool)` / `hint_effect(hinted, bare)` — return-shape annotation.
  * `compare_fallbacks(unbounded, bounded)` — the 14x lesson, measured.
  * `advise(profile)` — the gateway recommendation the evidence supports.

Pure and deterministic (bootstrap seeded). No number here reproduces the paper.
"""
from __future__ import annotations

import random

FORMAT = "longrun-gateway-shape/1"
CONFIGS = ("plain-mcp", "router-json", "code-mode", "router-code")
PAYBACK_SECONDS = 0.7


def utility(cell, weight_tokens=0.01, weight_latency=0.002):
    """U = success - wt * tokens/1000 - wl * latency (seconds)."""
    cell = cell if isinstance(cell, dict) else {}
    success = float(cell.get("success") or 0.0)
    tokens = float(cell.get("tokens") or 0.0)
    latency = float(cell.get("latency") or 0.0)
    return round(success - weight_tokens * tokens / 1000.0
                 - weight_latency * latency, 4)


def _percentile(values, q):
    if not values:
        return 0.0
    ordered = sorted(values)
    idx = min(len(ordered) - 1, max(0, int(q * (len(ordered) - 1))))
    return ordered[idx]


def paired_delta(base_cells, cand_cells, weight_tokens=0.01, weight_latency=0.002,
                 resamples=2000, seed=7):
    """Paired utility delta over matched cells, with a bootstrap interval."""
    pairs = [(a, b) for a, b in zip(base_cells or [], cand_cells or [])
             if isinstance(a, dict) and isinstance(b, dict)]
    diffs = [utility(b, weight_tokens, weight_latency)
             - utility(a, weight_tokens, weight_latency) for a, b in pairs]
    n = len(diffs)
    if not n:
        return {"format": FORMAT, "delta": None, "ci": [0.0, 0.0], "n": 0,
                "excludes_zero": False, "why": "no matched cells"}
    mean = sum(diffs) / n
    rng = random.Random(seed)
    means = []
    for _ in range(max(1, int(resamples))):
        means.append(sum(diffs[rng.randrange(n)] for _ in range(n)) / n)
    lo, hi = round(_percentile(means, 0.025), 4), round(_percentile(means, 0.975), 4)
    return {"format": FORMAT, "delta": round(mean, 4), "ci": [lo, hi], "n": n,
            "excludes_zero": lo > 0 or hi < 0,
            "why": "paired bootstrap over matched task cells"}


def holm(pvalues, alpha=0.05):
    """Holm-adjusted p-values in the input order."""
    values = [float(p) for p in (pvalues or [])]
    m = len(values)
    order = sorted(range(m), key=lambda i: values[i])
    adjusted = [1.0] * m
    running = 0.0
    for rank, idx in enumerate(order):
        running = max(running, (m - rank) * values[idx])
        adjusted[idx] = round(min(1.0, running), 4)
    return {"format": FORMAT, "alpha": alpha, "adjusted": adjusted}


def claim(delta, ci, p_adjusted=None, alpha=0.05):
    """Confirmed, inconclusive, or contradicting -- never a silent 'absent'."""
    ci = ci or [0.0, 0.0]
    excludes = ci[0] > 0 or ci[1] < 0
    if p_adjusted is not None and p_adjusted <= alpha and excludes:
        return {"format": FORMAT, "status": "confirmed", "delta": delta, "ci": ci,
                "p_adjusted": p_adjusted,
                "why": "the interval excludes zero and survives correction"}
    if excludes and p_adjusted is not None and p_adjusted > alpha:
        return {"format": FORMAT, "status": "inconclusive", "delta": delta, "ci": ci,
                "p_adjusted": p_adjusted,
                "why": "direction survives resampling but not the correction family"}
    return {"format": FORMAT, "status": "inconclusive", "delta": delta, "ci": ci,
            "p_adjusted": p_adjusted,
            "why": "a not-confirmed result is inconclusive, not an absent effect"}


def stub(tool):
    """What the agent sees about a tool's return value in code mode."""
    tool = tool if isinstance(tool, dict) else {}
    returns = tool.get("returns")
    if isinstance(returns, dict) and (returns.get("keys") or returns.get("type")):
        return {"format": FORMAT, "for": tool.get("name"), "quality": "annotated",
                "hint": {"keys": returns.get("keys") or [],
                         "type": returns.get("type") or "object"},
                "why": "declared keys and types tell the script how to consume the result"}
    return {"format": FORMAT, "for": tool.get("name"), "quality": "bare",
            "hint": "-> dict | list",
            "why": "a bare stub hides the return shape; the agent guesses"}


def hint_effect(hinted, bare):
    """The cost of removing return-shape information from code-mode stubs."""
    hinted = hinted if isinstance(hinted, dict) else {}
    bare = bare if isinstance(bare, dict) else {}
    ds = round(float(hinted.get("success") or 0) - float(bare.get("success") or 0), 4)
    du = round(utility(hinted) - utility(bare), 4)
    return {"format": FORMAT, "delta_success": ds, "delta_utility": du,
            "verdict": "first-order" if ds >= 0.10 else "minor",
            "why": "in the paper the hints outweigh every router effect measured"}


def compare_fallbacks(unbounded, bounded):
    """Bounded retry versus an unbounded JSON fallback at the same catalog."""
    unbounded = unbounded if isinstance(unbounded, dict) else {}
    bounded = bounded if isinstance(bounded, dict) else {}
    u_lat = float(unbounded.get("latency") or 0.0)
    b_lat = float(bounded.get("latency") or 0.0)
    u_tok = float(unbounded.get("tokens") or 0.0)
    b_tok = float(bounded.get("tokens") or 0.0)
    speedup = round(u_lat / b_lat, 2) if b_lat else None
    token_ratio = round(u_tok / b_tok, 2) if b_tok else None
    ds = round(float(bounded.get("success") or 0) - float(unbounded.get("success") or 0), 4)
    findings = []
    if speedup is not None and speedup > 2:
        findings.append({"kind": "unbounded-fallback", "speedup": speedup,
                         "why": "each extra call re-adds long external schemas"})
    return {"format": FORMAT, "speedup": speedup, "token_ratio": token_ratio,
            "delta_success": ds, "findings": findings,
            "why": "the fallback must be bounded; retrieval-limited recall makes "
                   "a subset miss common at scale"}


def router_pays(router_seconds, saved_seconds):
    """A front-door router has to earn its own latency back."""
    return {"format": FORMAT, "pays": float(saved_seconds or 0.0) > float(router_seconds or 0.0),
            "router_seconds": router_seconds, "saved_seconds": saved_seconds,
            "budget_seconds": PAYBACK_SECONDS,
            "why": "the paper puts the payback point around 0.4-0.7 s on a fast agent"}


def advise(profile):
    """The gateway default the evidence supports for one agent profile."""
    profile = profile if isinstance(profile, dict) else {}
    code = float(profile.get("code_success") or 0.0)
    plain = float(profile.get("plain_success") or 0.0)
    router_gain = float(profile.get("router_utility_gain") or 0.0)
    router_seconds = float(profile.get("router_seconds") or 0.0)
    reasons, findings = [], []
    if code >= plain:
        call_shape = "code-mode"
        reasons.append("code mode is the dominant effect where it lands")
    else:
        call_shape = "plain-mcp"
        findings.append({"kind": "verify-return-hints",
                         "why": "bare stubs can invert the comparison; annotate the "
                                "return shape before concluding that code mode is worse"})
    router = "optional" if (router_gain > 0 and router_seconds <= PAYBACK_SECONDS) else "omit"
    if router == "omit" and router_gain <= 0:
        reasons.append("a decision layer in front of code mode is not confirmed")
    if router == "omit" and router_seconds > PAYBACK_SECONDS:
        reasons.append("the router costs more latency than it saves on this agent")
    return {"format": FORMAT, "call_shape": call_shape, "router": router,
            "fallback": "bounded", "stub_hints": "required",
            "shape_routing": "do-not-route",
            "findings": findings, "reasons": reasons,
            "why": "default to code mode with a bounded fallback; publish return "
                   "shapes; never route the call shape"}
