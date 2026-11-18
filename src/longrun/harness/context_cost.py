#!/usr/bin/env python3
"""Context cost under prefix caching — judge a context policy in money and behaviour.

Source: arXiv:2611.22238, "Context Has a Price: Adding and Removing Context for
LLM Coding Agents under Prefix Caching" (round 116). Its measurement: retrieved
code cuts read/search commands 18–34% but raises cost 33–42% once cached input
costs a tenth of uncached input, with no resolution gain; removing old
observations saves 19–36% without a cache discount and costs 38–116% MORE with
one; shorter prompts are not cheaper runs because the agent takes more steps.

The module prices a run from per-step token counts split into a cached prefix and
uncached new input, then compares two policies on cost per solved task — and it
refuses a token-only comparison, because the paper's whole result is that token
count and cost point in opposite directions.

Pure: runs + price book in, cost and findings out.
"""
from __future__ import annotations

FORMAT = "longrun-context-cost/1"
DEFAULT_PRICES = {"uncached": 1.0, "cached": 0.1, "output": 4.0}


def _prices(prices):
    out = dict(DEFAULT_PRICES)
    for key, value in (prices or {}).items():
        if key in out and isinstance(value, (int, float)) and value >= 0:
            out[key] = float(value)
    return out


def run_cost(run, prices=None):
    """Cost of one run; each step carries prompt, cached-prefix and output tokens."""
    price = _prices(prices)
    steps = [s for s in ((run or {}).get("steps") or []) if isinstance(s, dict)]
    total = 0.0
    rows = []
    for step in steps:
        prompt = max(0, int(step.get("prompt_tokens") or 0))
        cached = min(prompt, max(0, int(step.get("cached_prefix_tokens") or 0)))
        output = max(0, int(step.get("output_tokens") or 0))
        cost = ((prompt - cached) * price["uncached"]
                + cached * price["cached"]
                + output * price["output"]) / 1_000_000
        total += cost
        rows.append({"prompt": prompt, "cached": cached, "output": output,
                     "cost": round(cost, 6)})
    solved = bool((run or {}).get("solved"))
    return {"format": FORMAT, "cost": round(total, 6), "steps": len(steps),
            "solved": solved, "per_step": rows}


def compare(baseline, treatment, prices=None, label="treatment"):
    """Token count and money, side by side; a token-only win is flagged."""
    base = run_cost(baseline, prices)
    treat = run_cost(treatment, prices)
    base_tokens = sum(s["prompt"] + s["output"] for s in base["per_step"])
    treat_tokens = sum(s["prompt"] + s["output"] for s in treat["per_step"])
    findings = []
    if treat_tokens < base_tokens and treat["cost"] > base["cost"]:
        findings.append({"kind": "cache-blind-comparison",
                         "why": "fewer tokens cost more once the cache discount is priced"})
    if treat["steps"] > base["steps"] and treat["cost"] >= base["cost"]:
        findings.append({"kind": "shorter-prompts-more-steps",
                         "why": "the cheaper-looking prompt did not shorten the run"})
    if treat["cost"] > base["cost"] and treat["solved"] <= base["solved"]:
        findings.append({"kind": "cost-without-resolution-gain",
                         "why": "more money bought no additional solved task"})
    delta = treat["cost"] - base["cost"]
    pct = (delta / base["cost"] * 100) if base["cost"] else None
    return {"format": FORMAT, "label": label,
            "baseline": {k: base[k] for k in ("cost", "steps", "solved")},
            "treatment": {k: treat[k] for k in ("cost", "steps", "solved")},
            "delta_cost": round(delta, 6),
            "delta_pct": None if pct is None else round(pct, 1),
            "tokens": {"baseline": base_tokens, "treatment": treat_tokens},
            "verdict": "cheaper" if delta < 0 else ("equal" if delta == 0 else "more-expensive"),
            "findings": findings}


def screen(runs, prices=None, baseline_key="baseline"):
    """Compare every variant against the baseline of a policy experiment."""
    runs = runs or {}
    if baseline_key not in runs:
        return {"format": FORMAT, "verdict": "no-baseline", "comparisons": []}
    out = [compare(runs[baseline_key], runs[k], prices, label=k)
           for k in runs if k != baseline_key]
    winners = [c["label"] for c in out if c["verdict"] == "cheaper" and not c["findings"]]
    return {"format": FORMAT, "baseline": baseline_key,
            "comparisons": out, "clean_winners": winners,
            "verdict": "clean-winner" if winners else "no-clean-winner"}
