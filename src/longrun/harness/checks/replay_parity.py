#!/usr/bin/env python3
"""Replay parity — a faster environment is admissible only if it replays.

Source: arXiv:2611.23151, "stable-envs-v1: Fast and Reproducible Environments
with Controllable Variations" (round 135). The library renders on the GPU and
claims up to 1.33x end-to-end training speedups, but only because it exposes the
full simulator state, so that dynamics are reproducible given the environment
class and a recorded state (`stable_envs_reproducible_2611.23151.md:58`).

  * **state is the dataset**: a trajectory is stored as low-dimensional states
    and rendered on demand, exploiting the bijection between state and visual
    outlook (`:58`).
  * **variations are controlled**: appearance factors change while the physical
    state stays the same (`:44`, `:65`) — a variation that moves the dynamics is
    not a variation.
  * **parity is measured, not assumed**: next-state dynamics against the source
    over a shared action sequence, and rendering MSE against the source
    (`:62`, `:186`, `:192`).
  * **timing is a protocol**: warm-up, then three windows of at least 3 s,
    median (`:135`); a speedup without parity is not a speedup.
  * **downstream parity closes it**: planning success must not degrade
    (`:203`; TwoRoom 88.7 -> 88.0, PushT 94.0 -> 93.3).

  * `trace(states)` — canonical per-step digests for a recorded roll-out.
  * `replay(record)` — does the same record reproduce the same states?
  * `variation(record)` — appearance changed, dynamics untouched.
  * `parity(a, b, tol)` — numeric trajectory parity (max absolute error).
  * `render_parity(mean, peak, ...)` — pixel-space parity gate.
  * `timing(rows)` — warm-up plus medians, and the speedup ratio.
  * `audit(record)` — the four gates together, in the paper's order.
  * `advise(profile)` — map a harness profile onto the paper's failure modes.

Pure: JSON-able states and measurements in; digests and verdicts out.
"""
from __future__ import annotations

import hashlib
import json
import statistics

FORMAT = "longrun-replay-parity/1"


def _num(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _canon(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def digest(state):
    """A stable digest of one environment state, independent of key order."""
    return hashlib.sha256(_canon(state).encode("utf-8")).hexdigest()[:16]


def trace(states):
    """The digest chain of a recorded roll-out."""
    steps = [digest(s) for s in (states or ())]
    return {"format": FORMAT, "steps": len(steps), "digests": steps,
            "digest": hashlib.sha256("".join(steps).encode("utf-8")).hexdigest()[:16]}


def replay(record):
    """A record reproduces when it replays to the same state digests."""
    r = record or {}
    original = trace(r.get("states") or ())
    again = trace(r.get("replay") or ())
    findings = []
    first = None
    for index in range(min(original["steps"], again["steps"])):
        if original["digests"][index] != again["digests"][index]:
            first = index
            break
    if first is None and original["steps"] != again["steps"]:
        first = min(original["steps"], again["steps"])
    if first is not None:
        findings.append({"kind": "nondeterministic-replay", "step": first,
                         "why": "the same record must reproduce the same state sequence"})
    elif original["steps"] == 0:
        findings.append({"kind": "empty-record"})
    else:
        findings.append({"kind": "deterministic"})
    return {"format": FORMAT, "steps": original["steps"], "digest": original["digest"],
            "first_divergence": first, "findings": findings}


def variation(record):
    """A controlled visual variation changes appearance and only appearance."""
    r = record or {}
    base_state = r.get("base_state")
    variant_state = r.get("variant_state")
    base_render = r.get("base_render")
    variant_render = r.get("variant_render")
    findings = []
    if base_state is None or variant_state is None:
        findings.append({"kind": "state-missing",
                         "why": "a variation must be applied to a recorded physical state"})
    elif digest(base_state) != digest(variant_state):
        findings.append({"kind": "variation-leaks-dynamics",
                         "why": "only appearance factors may change, never the dynamics"})
    if base_render is not None and variant_render is not None:
        if digest(base_render) == digest(variant_render):
            findings.append({"kind": "variation-invisible",
                             "why": "the factor produced no visual change"})
        elif not findings:
            findings.append({"kind": "controlled-variation"})
    else:
        findings.append({"kind": "render-missing"})
    return {"format": FORMAT, "findings": findings}


def parity(source, port, tol=1e-6):
    """Numeric trajectory parity: the largest absolute deviation, against a tol."""
    a = list(source or ())
    b = list(port or ())
    findings = []
    if not a or not b:
        return {"format": FORMAT, "findings": [{"kind": "trajectory-missing"}]}
    if len(a) != len(b):
        return {"format": FORMAT, "findings": [{"kind": "length-mismatch",
                                                "source": len(a), "port": len(b)}]}
    worst = 0.0
    at = 0
    for index, (x, y) in enumerate(zip(a, b)):
        xv, yv = _num(x), _num(y)
        if xv is None or yv is None:
            findings.append({"kind": "non-numeric-state", "step": index})
            return {"format": FORMAT, "findings": findings}
        delta = abs(xv - yv)
        if delta > worst:
            worst, at = delta, index
    passed = worst <= float(tol)
    findings.append({"kind": "dynamics-parity" if passed else "dynamics-diverged",
                     "max_abs": round(worst, 12), "step": at, "tol": tol})
    return {"format": FORMAT, "max_abs": round(worst, 12), "step": at,
            "passed": passed, "findings": findings}


def render_parity(mse_mean, mse_max, tol_mean=1e-3, tol_max=1e-2):
    """Pixel-space parity against the source renderer."""
    mean = _num(mse_mean)
    peak = _num(mse_max)
    if mean is None or peak is None:
        return {"format": FORMAT, "findings": [{"kind": "no-render-measurement"}]}
    passed = mean <= float(tol_mean) and peak <= float(tol_max)
    return {"format": FORMAT, "mse_mean": mean, "mse_max": peak, "passed": passed,
            "findings": [{"kind": "render-parity" if passed else "render-diverged",
                          "why": "rendering must match the source for the same state"}]}


def timing(rows, warmup=1, min_windows=3, min_seconds=3.0):
    """Warm-up then median windows per engine; the speedup is the ratio of medians."""
    data = [r for r in (rows or ()) if _num(r.get("seconds")) is not None
            and r.get("engine") in ("native", "port")]
    findings = []
    if not data:
        return {"format": FORMAT, "findings": [{"kind": "no-timing"}]}
    medians = {}
    windows = {}
    for engine in ("native", "port"):
        times = [_num(r["seconds"]) for r in data if r["engine"] == engine]
        kept = times[int(warmup):] if len(times) > int(warmup) else []
        windows[engine] = len(kept)
        if not kept:
            findings.append({"kind": "no-window-after-warmup", "engine": engine})
            continue
        if len(kept) < min_windows:
            findings.append({"kind": "too-few-windows", "engine": engine, "windows": len(kept)})
        if min(kept) < float(min_seconds):
            findings.append({"kind": "window-too-short", "engine": engine,
                             "seconds": min(kept), "min": min_seconds})
        medians[engine] = statistics.median(kept)
    if "native" not in medians or "port" not in medians:
        return {"format": FORMAT, "windows": windows, "findings": findings}
    speedup = medians["native"] / medians["port"] if medians["port"] > 0 else None
    if speedup is not None and speedup > 1.0:
        findings.append({"kind": "faster", "speedup": round(speedup, 4)})
    else:
        findings.append({"kind": "not-faster", "speedup": None if speedup is None
                         else round(speedup, 4)})
    return {"format": FORMAT, "median": {k: round(v, 6) for k, v in medians.items()},
            "speedup": None if speedup is None else round(speedup, 4),
            "windows": windows, "findings": findings}


def audit(record):
    """The paper's four gates, in order: replay, dynamics, render, downstream."""
    r = record or {}
    findings = []
    replayed = replay({"states": r.get("states"), "replay": r.get("replay")})
    if "deterministic" not in [f["kind"] for f in replayed["findings"]]:
        findings.append({"kind": "replay-failed",
                         "why": "an environment that does not replay cannot carry a dataset"})
    dyn = parity(r.get("source_states") or (), r.get("port_states") or (),
                 r.get("dynamics_tol", 1e-6))
    if "dynamics-parity" not in [f["kind"] for f in dyn["findings"]]:
        findings.append({"kind": "dynamics-failed",
                         "why": "next-state dynamics must match the source"})
    ren = render_parity(r.get("mse_mean"), r.get("mse_max"),
                        r.get("render_tol_mean", 1e-3), r.get("render_tol_max", 1e-2))
    if "render-parity" not in [f["kind"] for f in ren["findings"]]:
        findings.append({"kind": "render-failed",
                         "why": "the same state must render to the same pixels"})
    delta = _num(r.get("downstream_delta"))
    if delta is None:
        findings.append({"kind": "downstream-unmeasured"})
    elif abs(delta) > float(r.get("downstream_tol", 1.0)):
        findings.append({"kind": "downstream-degraded", "delta": delta,
                         "why": "planning success must not fall beyond the declared tolerance"})
    speed = _num(r.get("speedup"))
    if speed is None:
        findings.append({"kind": "speedup-unmeasured"})
    elif speed <= 1.0:
        findings.append({"kind": "no-speedup", "speedup": speed})
    blocked = [f for f in findings if f["kind"].endswith(("failed", "degraded", "unmeasured"))]
    if not blocked:
        findings.append({"kind": "reproducible-speedup", "speedup": speed}
                        if speed is not None and speed > 1.0 else {"kind": "parity-only"})
    return {"format": FORMAT, "gates": {"replay": replayed, "dynamics": dyn,
                                        "render": ren},
            "admissible": not blocked and speed is not None and speed > 1.0,
            "findings": findings}


def advise(profile):
    """Map a harness profile onto the paper's failure modes."""
    p = profile or {}
    have = {str(key) for key, value in p.items() if value}
    findings = []
    checks = (
        ("records_state", "renders-only", "store state, render the frames on demand"),
        ("replays_deterministically", "unreproducible", "the same record must replay exactly"),
        ("applies_variations", "single-appearance", "diversify appearance at fixed physics"),
        ("separates_appearance_and_dynamics", "leaky-variation", "a variation may not move the world"),
        ("measures_dynamics_parity", "unverified-dynamics", "compare next states over shared actions"),
        ("measures_render_parity", "unverified-render", "compare pixels for the same state"),
        ("checks_downstream", "speedup-only", "a faster loop that plans worse is a regression"),
        ("times_with_protocol", "ad-hoc-timing", "warm-up, then median windows"),
    )
    for key, kind, why in checks:
        if key not in have:
            findings.append({"kind": kind, "why": why})
    return {"format": FORMAT, "findings": findings}
