#!/usr/bin/env python3
"""Model cascade — a cheap first stage, a stronger model only on evidence.

Source: arXiv:2611.24324, "Reducing Inference Cost of Coding Agents with Timeout
Cascades" (round 166). Across 36 open-weight models on SWE-bench Verified, the
gap between small and large is concentrated on hard tasks: GLM-4.7-Flash resolves
62% of easy tasks against 77% for GLM-4.7, 36% vs 68% on medium, and 2% vs 36% on
hard (`timeout-cascades-coding-agents_2611.24324.md:194`). Easy and medium tasks
are 91% of the benchmark (`:196`). A small-first cascade with a 120-minute
timeout keeps the large model's resolve rate (73.4% vs 71.2%) at 16.4% fewer
GPU-hours overall and 33.5% fewer on easy tasks (`:206`, Table 1); a perfect
difficulty router gains only 1.5 points more (`:216`). The price is wall-clock
time on tasks that fall back: 41.6 → 65.5–84.5 minutes (`:228`), which is why the
paper recommends the cascade for asynchronous work.

This module is the harness's policy half, with the same shape and one honest
difference: a fallback here is a MID-TURN escalation (the large model continues
from the small model's state), not the paper's cold restart. That is cheaper for
the caller but unmeasured against their benchmark, so this module claims only
the policy, never their numbers.

Three sources of evidence trigger escalation, all already visible to the loop:
a failure streak, a repeated identical state-action pair, an invalid-output
streak, and an optional wall-clock budget. No confidence calibration and no
learned router (the paper finds the router's extra 1.5 points do not pay for
its complexity).

Pure: config + signals in, a model decision out; the caller owns the call.
"""
from __future__ import annotations

import os

try:  # PyYAML is the app's only third-party dependency
    import yaml
except Exception:  # noqa: BLE001 — a missing parser must not break the import
    yaml = None

FORMAT = "longrun-model-cascade/1"

DEFAULTS = {
    "enabled": False,
    "small": "",
    "large": "",
    "interactive": True,
    "escalate": {
        "failure_streak": 2,
        "same_obs": 2,
        "invalid_streak": 2,
        "wall_seconds": 0,
    },
}


def _merge(base, extra):
    out = dict(base)
    for key, value in (extra or {}).items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _merge(out[key], value)
        elif value is not None:
            out[key] = value
    return out


def _read(path):
    """The yaml mapping at `path`, or {} when it is missing/unparseable."""
    if not path or yaml is None:
        return {}
    try:
        with open(path, encoding="utf-8") as fh:
            data = yaml.safe_load(fh) or {}
    except Exception:  # noqa: BLE001 — a broken file means "not configured"
        return {}
    return data if isinstance(data, dict) else {}


def _overlay_path():
    """The Settings form's gitignored overlay (the shipped file keeps its docs)."""
    try:
        from longrun.util.paths import DATA_DIR
        return os.path.join(DATA_DIR, "cascade.overlay.yaml")
    except Exception:  # noqa: BLE001 — a caller without the app still gets defaults
        return ""


def load(path=None):
    """Read `config/cascade.yaml` (plus the Settings overlay); defaults fill the gaps."""
    explicit = path is not None
    if not explicit:
        try:
            from longrun.util.paths import REPO_ROOT
            path = os.path.join(REPO_ROOT, "config", "cascade.yaml")
        except Exception:  # noqa: BLE001 — a caller without the app still gets defaults
            path = os.path.join("config", "cascade.yaml")
    data = _read(path)
    if not explicit:
        overlay = _read(_overlay_path())
        if overlay:
            data = _merge(data, overlay)
    return _merge(DEFAULTS, data)


def save(values):
    """Persist the operator's changes to the gitignored overlay; return the result."""
    path = _overlay_path()
    if not path:
        raise ValueError("no writable overlay for the cascade config")
    merged = _merge(_read(path), values or {})
    from longrun.util import dataio
    from longrun.util.fswrite import write_text
    write_text(path, dataio.dump_yaml(merged))
    return load()


def plan(config=None, interactive=True):
    """Whether this turn runs small-first, and with which model."""
    cfg = config if isinstance(config, dict) else load()
    small = str(cfg.get("small") or "").strip()
    large = str(cfg.get("large") or "").strip()
    if not cfg.get("enabled"):
        return {"format": FORMAT, "enabled": False, "reason": "disabled"}
    if not small or not large:
        return {"format": FORMAT, "enabled": False, "reason": "small/large not configured"}
    if interactive and not cfg.get("interactive", True):
        return {"format": FORMAT, "enabled": False, "reason": "interactive turn"}
    return {"format": FORMAT, "enabled": True, "model": small,
            "small": small, "large": large, "config": cfg,
            "reason": "small-first"}


def decide(state, config):
    """The model for the NEXT call: stay cheap, or escalate once on evidence."""
    cfg = (config or {}).get("config") if isinstance((config or {}).get("config"), dict) \
        else config
    cfg = _merge(DEFAULTS, cfg or {})
    small = str(cfg.get("small") or "").strip()
    large = str(cfg.get("large") or "").strip()
    current = str((state or {}).get("current") or small or "")
    enabled = bool(config.get("enabled")) if isinstance(config, dict) else False
    if not enabled:
        return {"format": FORMAT, "model": current, "escalate": False,
                "reason": "cascade disabled"}
    if state.get("escalated"):
        return {"format": FORMAT, "model": large or current, "escalate": False,
                "reason": "already escalated"}
    limits = cfg.get("escalate") or {}
    checks = (
        ("failure_streak", "failure-streak"),
        ("same_obs", "repeated-state-action"),
        ("invalid_streak", "invalid-output"),
    )
    for key, reason in checks:
        threshold = int(limits.get(key) or 0)
        if threshold and int((state or {}).get(key) or 0) >= threshold:
            return {"format": FORMAT, "model": large or current, "escalate": True,
                    "reason": reason, "signal": key,
                    "value": int(state.get(key) or 0), "threshold": threshold}
    wall = int(limits.get("wall_seconds") or 0)
    if wall and float((state or {}).get("wall_seconds") or 0) >= wall:
        return {"format": FORMAT, "model": large or current, "escalate": True,
                "reason": "wall-clock", "signal": "wall_seconds",
                "value": round(float(state.get("wall_seconds")), 1), "threshold": wall}
    return {"format": FORMAT, "model": small or current, "escalate": False,
            "reason": "small-first"}


def summary(rows):
    """Escalation rate and a cost proxy, from per-turn rows the caller records.

    `rows`: {tier: "small"|"escalated", solved: bool, calls_small: int,
             calls_large: int, small_cost: float, large_cost: float}
    The proxy is `calls_small*small_cost + calls_large*large_cost`, in the
    operator's own units. With no rows it reports nothing rather than zero.
    """
    rows = [r for r in (rows or []) if isinstance(r, dict)]
    if not rows:
        return {"format": FORMAT, "verdict": "no-rows"}
    escalated = sum(1 for r in rows if r.get("tier") == "escalated")
    solved = sum(1 for r in rows if r.get("solved"))
    small_solved = sum(1 for r in rows if r.get("tier") != "escalated" and r.get("solved"))
    cost = 0.0
    for row in rows:
        cost += (float(row.get("calls_small") or 0) * float(row.get("small_cost") or 0)
                 + float(row.get("calls_large") or 0) * float(row.get("large_cost") or 0))
    return {"format": FORMAT, "turns": len(rows), "escalated": escalated,
            "escalation_rate": round(escalated / len(rows), 4),
            "solved": solved, "small_solved": small_solved,
            "cost_proxy": round(cost, 4),
            "verdict": ("cascade-saves" if small_solved and escalated < len(rows)
                        else "no-evidence")}
