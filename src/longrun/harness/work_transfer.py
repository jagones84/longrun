#!/usr/bin/env python3
"""Work transfer — a benchmark gain is not yet work done.

Source: arXiv:2611.23216, "Higher-Scoring Coding Models Did Not Get More Work
Done" (round 137). A 19-day suspension of a model that led by 10.8 points on
SWE-Bench Pro moved the same developers' 7-day merge rate by +1.4 points
[-1.4, +4.3], and five model upgrades moved it by -0.9 [-1.9, +0.2]
(`higher_scores_not_more_work_2611.23216.md:26`, `:42`).

  * **the design holds the person fixed**: developer and calendar-day fixed
    effects, a placebo phase, and a control group that stayed on the old model
    (`:90`).
  * **a null is the finding, and the bound is the claim**: the data rule out
    gains larger than about 4 points (`:351`).
  * **the outcome had a ceiling**: 94.5% of PRs were merged before the upgrade,
    so the merge rate had little room to rise (`:139`).
  * **pooling compares developers, not models**: the developer-level intraclass
    correlation is 0.42, and the lead shrinks from -2.6 to -0.9 points as the
    comparison narrows to the same developer and repository (`:325`, `:327`).
  * **the label is thin**: only 1% of PRs name the model, so a refit on all PRs
    and a placebo are required (`:293`, `:167`).
  * **a single upgrade is underpowered**: detecting 3 points needs 650-1,500
    developers who switched (`:415`).

  * `transfer(rows)` — benchmark gain vs the observed work change.
  * `pool(rows)` — inverse-variance pooling across upgrades.
  * `ceiling(baseline, ...)` — did the outcome have room to move.
  * `design(spec)` — the design a causal claim needs.
  * `reversal(phases)` — the reversal contrast and its placebo.
  * `pooled_comparison(rows)` — four comparison widths and what each controls.
  * `power(sd, effect, available)` — is one upgrade able to detect it.
  * `advise(profile)` — map a harness profile onto the paper's failure modes.

Pure: deltas, intervals and design records in; findings out.
"""
from __future__ import annotations

import math
import statistics

FORMAT = "longrun-work-transfer/1"


def _num(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def transfer(rows):
    """A benchmark gain is a prediction about work; the interval tests it."""
    data = [r for r in (rows or ()) if _num(r.get("work_delta")) is not None]
    if not data:
        return {"format": FORMAT, "findings": [{"kind": "no-measurements"}]}
    findings = []
    supported = 0
    for r in data:
        lo = _num(r.get("ci_low"))
        hi = _num(r.get("ci_high"))
        gain = _num(r.get("benchmark_gain"))
        delta = _num(r["work_delta"])
        if lo is None or hi is None:
            findings.append({"kind": "no-interval", "upgrade": r.get("upgrade")})
            continue
        if lo > 0:
            supported += 1
        elif gain is not None and gain > 0 and hi <= 0:
            findings.append({"kind": "gain-absent-and-ruled-out", "upgrade": r.get("upgrade"),
                             "benchmark_gain": gain, "work_delta": delta})
        else:
            findings.append({"kind": "transfer-unobserved", "upgrade": r.get("upgrade"),
                             "benchmark_gain": gain, "work_delta": delta})
    if supported == 0:
        findings.append({"kind": "benchmark-gain-not-in-work"})
    else:
        findings.append({"kind": "transfer-supported", "rows": supported})
    return {"format": FORMAT, "rows": len(data), "supported": supported,
            "findings": findings}


def pool(rows):
    """Inverse-variance pooling of the per-upgrade changes."""
    data = []
    for r in rows or ():
        delta = _num(r.get("work_delta"))
        lo = _num(r.get("ci_low"))
        hi = _num(r.get("ci_high"))
        if delta is None or lo is None or hi is None or hi <= lo:
            continue
        se = (hi - lo) / (2 * 1.959964)
        data.append((delta, se))
    if not data:
        return {"format": FORMAT, "findings": [{"kind": "no-poolable-rows"}]}
    weights = [1.0 / (se * se) for _, se in data]
    mean = sum(w * d for w, (d, _) in zip(weights, data)) / sum(weights)
    se = math.sqrt(1.0 / sum(weights))
    lo, hi = mean - 1.959964 * se, mean + 1.959964 * se
    findings = []
    if lo <= 0 <= hi:
        findings.append({"kind": "pooled-null", "delta": round(mean, 4),
                         "ci": [round(lo, 4), round(hi, 4)]})
    elif lo > 0:
        findings.append({"kind": "pooled-positive", "delta": round(mean, 4)})
    else:
        findings.append({"kind": "pooled-negative", "delta": round(mean, 4)})
    if all(d < 0 for d, _ in data):
        findings.append({"kind": "all-negative", "rows": len(data)})
    return {"format": FORMAT, "upgrades": len(data), "delta": round(mean, 4),
            "ci": [round(lo, 4), round(hi, 4)], "findings": findings}


def ceiling(baseline, open_outcome=None, threshold=0.9):
    """An outcome already at its ceiling cannot show a gain."""
    rate = _num(baseline)
    if rate is None or not 0 <= rate <= 1:
        return {"format": FORMAT, "findings": [{"kind": "invalid-rate"}]}
    findings = []
    if rate >= float(threshold):
        findings.append({"kind": "ceiling-leaves-no-room", "rate": rate,
                         "why": "the remaining headroom bounds any possible gain"})
    else:
        findings.append({"kind": "headroom-present", "rate": rate})
    if rate >= float(threshold) and not open_outcome:
        findings.append({"kind": "needs-open-outcome",
                         "why": "report an outcome that is not near its ceiling"})
    elif open_outcome:
        findings.append({"kind": "open-outcome-reported"})
    return {"format": FORMAT, "rate": rate, "findings": findings}


def design(spec):
    """What a causal claim about a model switch needs."""
    s = spec or {}
    findings = []
    if s.get("developer_fixed_effects") is not True:
        findings.append({"kind": "no-developer-fixed-effects",
                         "why": "the comparison must hold the person fixed"})
    if s.get("calendar_fixed_effects") is not True:
        findings.append({"kind": "no-calendar-control",
                         "why": "a change shared by everyone is not a model effect"})
    if s.get("placebo") is not True:
        findings.append({"kind": "no-placebo",
                         "why": "a phase with no treatment tests the parallel trend"})
    if s.get("same_developers") is not True:
        findings.append({"kind": "different-developers",
                         "why": "pooled developer differences masquerade as a model effect"})
    if s.get("control_group") is not True:
        findings.append({"kind": "no-control-group"})
    if s.get("pre_period_similar") is not True:
        findings.append({"kind": "pre-period-unchecked"})
    if not findings:
        findings.append({"kind": "design-sound"})
    return {"format": FORMAT, "findings": findings}


def reversal(phases):
    """The reversal contrast (p1+p3)/2 against the suspension, and the placebo."""
    p = phases or {}
    cols = {}
    for key in ("p0", "p1", "p2", "p3"):
        value = p.get(key)
        if value is None:
            continue
        delta = _num(value.get("delta") if isinstance(value, dict) else value)
        lo = _num(value.get("ci_low") if isinstance(value, dict) else None)
        hi = _num(value.get("ci_high") if isinstance(value, dict) else None)
        cols[key] = {"delta": delta, "ci_low": lo, "ci_high": hi}
    if "p1" not in cols or "p3" not in cols:
        return {"format": FORMAT, "findings": [{"kind": "missing-phase"}]}
    if cols["p1"]["delta"] is None or cols["p3"]["delta"] is None:
        return {"format": FORMAT, "findings": [{"kind": "missing-delta"}]}
    mean = (cols["p1"]["delta"] + cols["p3"]["delta"]) / 2.0
    findings = [{"kind": "reversal-contrast", "delta": round(mean, 4)}]
    if "p2" in cols and cols["p2"]["delta"] not in (None, 0.0):
        findings.append({"kind": "reference-not-suspension",
                         "why": "the suspension is the reference phase"})
    if "p0" in cols and cols["p0"]["delta"] is not None and abs(cols["p0"]["delta"]) > 3.0:
        findings.append({"kind": "placebo-not-flat", "delta": cols["p0"]["delta"],
                         "why": "a pre-period difference weakens the parallel trend"})
    elif "p0" in cols:
        findings.append({"kind": "placebo-flat"})
    return {"format": FORMAT, "reversal": round(mean, 4), "phases": cols,
            "findings": findings}


def pooled_comparison(rows):
    """Four ways to compare two models; the narrow one controls the most."""
    data = [r for r in (rows or ()) if _num(r.get("delta")) is not None]
    if len(data) < 2:
        return {"format": FORMAT, "findings": [{"kind": "not-enough-comparisons"}]}
    order = ["pooled", "calendar", "same developer", "same developer and repo"]
    by_name = {str(r.get("comparison")): _num(r["delta"]) for r in data}
    present = [c for c in order if c in by_name]
    findings = []
    if len(present) >= 2:
        narrow = abs(by_name[present[-1]])
        wide = abs(by_name[present[0]])
        if narrow < wide:
            findings.append({"kind": "pooling-inflates-lead",
                             "pooled": by_name[present[0]], "narrow": by_name[present[-1]]})
        monotone = all(abs(by_name[present[i + 1]]) <= abs(by_name[present[i]])
                       for i in range(len(present) - 1))
        if monotone:
            findings.append({"kind": "lead-shrinks-with-control"})
    if not findings:
        findings.append({"kind": "comparison-stable"})
    return {"format": FORMAT, "comparisons": {k: by_name[k] for k in present},
            "findings": findings}


def power(sd, effect, available=None, alpha=0.05, power_target=0.8):
    """Switching developers needed to detect a work-level effect."""
    s = _num(sd)
    e = _num(effect)
    if s is None or e is None or s <= 0 or e <= 0:
        return {"format": FORMAT, "findings": [{"kind": "invalid-power-input"}]}
    z = statistics.NormalDist().inv_cdf(1 - alpha / 2.0) + statistics.NormalDist().inv_cdf(power_target)
    needed = int(math.ceil(2.0 * z * z * s * s / (e * e)))
    findings = []
    have = int(available or 0)
    if have and have < needed:
        findings.append({"kind": "underpowered", "needed": needed, "available": have})
    else:
        findings.append({"kind": "powered", "needed": needed})
    return {"format": FORMAT, "needed": needed, "findings": findings}


def advise(profile):
    """Map a harness profile onto the paper's failure modes."""
    p = profile or {}
    have = {str(key) for key, value in p.items() if value}
    findings = []
    checks = (
        ("reports_work_outcome", "benchmark-only", "a score is a prediction about work"),
        ("holds_person_fixed", "cross-developer-pooling", "the same developer, before and after"),
        ("has_control_group", "no-control", "a shared trend is not an effect"),
        ("uses_placebo", "no-placebo", "test the parallel trend"),
        ("checks_ceiling", "ceiling-outcome", "an outcome near 100% cannot show a gain"),
        ("reports_interval", "point-estimate", "a null is a bound, not a zero"),
        ("measures_actual_use", "access-only", "access is not usage"),
        ("estimates_power", "single-small-upgrade", "one upgrade rarely has the developers"),
    )
    for key, kind, why in checks:
        if key not in have:
            findings.append({"kind": kind, "why": why})
    return {"format": FORMAT, "findings": findings}
