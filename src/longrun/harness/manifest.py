#!/usr/bin/env python3
"""Harness manifest — the harness describing its own decisions to itself.

Source: arXiv:2611.22299, "Harnesses That Improve Themselves: A Unifying
Framework for Self-Improving Agent Harnesses" (round 107). The framework's
first step is self-inspection: a harness that changes its own runtime must be
able to state what it currently decides, so a trace can be attributed to a
runtime bug or to a model limit instead of guessed.

Longrun's self-evolution (`evolve/optimizer.py`) reads traces and proposes
deltas; nothing in it could read the DECISIONS those deltas change. This module
is that read model: one JSON document naming every decision the operator can
change, where it lives, and the budget/role/gate values in force.

Pure read: `build()` loads config and the catalog. Nothing is written and no
model is called.
"""
from __future__ import annotations

import os
import time

FORMAT = "longrun-manifest/1"


def _yaml(path):
    try:
        import yaml
        with open(path, encoding="utf-8") as fh:
            data = yaml.safe_load(fh) or {}
        return data if isinstance(data, dict) else {}
    except Exception:  # noqa: BLE001
        return {}


def build(repo=None):
    """Return the harness manifest: decisions, gates, budgets, roles, tools."""
    from longrun.tools import registry
    from longrun.harness import invariants
    repo = repo or registry.REPO
    cfg = registry.load_config()
    sub = _yaml(os.path.join(repo, "config", "subagents.yaml"))
    routing = _yaml(os.path.join(repo, "config", "routing.yaml"))
    comp = _yaml(os.path.join(repo, "config", "compaction.yaml"))
    names = []
    try:
        names = list(registry.tool_names())
    except Exception:  # noqa: BLE001
        pass
    sandbox = cfg.get("sandbox") or {}
    approvals = cfg.get("approvals") or {}
    runtime = cfg.get("runtime") or {}
    roles = sub.get("roles") or {}
    decisions = [
        {"id": "D1", "question": "what may run without asking",
         "choice": {"approvals.mode": approvals.get("mode"),
                    "kinds": approvals.get("kinds") or {},
                    "allow_nucleous_write": approvals.get("allow_nucleous_write")},
         "source": "config/tools.yaml approvals"},
        {"id": "D2", "question": "where a shell command executes",
         "choice": {"backend": sandbox.get("backend"),
                    "timeout_secs": sandbox.get("timeout_secs"),
                    "network": sandbox.get("network")},
         "source": "config/tools.yaml sandbox"},
        {"id": "D3", "question": "how long a turn may run",
         "choice": dict(runtime), "source": "config/tools.yaml runtime"},
        {"id": "D4", "question": "what a delegated child may do",
         "choice": {"max_parallel": sub.get("max_parallel"),
                    "max_per_run": sub.get("max_per_run"),
                    "max_steps": sub.get("max_steps"),
                    "max_depth": sub.get("max_depth"),
                    "roles": {k: (v.get("tools") if isinstance(v, dict) else None)
                              for k, v in (roles.items() if isinstance(roles, dict) else [])}},
         "source": "config/subagents.yaml"},
        {"id": "D5", "question": "which model answers which role",
         "choice": {"roles": routing.get("roles") or {},
                    "default": routing.get("default")},
         "source": "config/routing.yaml"},
        {"id": "D6", "question": "when the context is compacted",
         "choice": {"policy": comp.get("policy"),
                    "threshold": comp.get("threshold")},
         "source": "config/compaction.yaml"},
    ]
    inv = invariants.check(repo=repo, tools_cfg=cfg, sub_cfg=sub)
    return {
        "format": FORMAT,
        "generated": round(time.time(), 3),
        "decisions": decisions,
        "tools": {"count": len(names), "sample": sorted(names)[:12]},
        "invariants": {"counts": inv["counts"],
                       "ids": [r["id"] for r in inv["rows"]]},
        "sources": {"tools": registry.CONFIG_YAML, "subagents":
                    os.path.join(repo, "config", "subagents.yaml")},
    }
