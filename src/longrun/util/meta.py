#!/usr/bin/env python3
"""Longrun Meta-harness self-improvement — Sperimentale

Outer-loop that proposes variants of the harness configuration and evaluates
them on a Pareto frontier (quality vs cost).

Reference: Lil'Log 2026 — "Self-Improving Agent Harnesses"

How it works:
  1. The meta-harness reads the current harness state (config, model roster,
     tool registry, agent trace from a standard eval run).
  2. It proposes candidate variations by varying:
       - Model choice (from the router roster)
       - Agent prompt style (concise / verbose / role-specific)
       - Tool approval policy (auto / required)
       - Sandbox backend (docker vs bwrap vs none)
       - Max steps
  3. Each candidate is scored by running a standard eval task and measuring:
       - Quality score (eval_score from server.eval_score)
       - Cost (tokens used * token prices, wall-clock time)
  4. The Pareto frontier is reported as the set of non-dominated candidates
     (no other candidate has both higher quality AND lower cost).
"""

import json
import os
import random
import threading
import time
import uuid

from longrun.tools import registry
from longrun.tools import sandbox
from longrun.util import paths

REPO = registry.REPO
DATA_DIR = os.path.join(paths.DATA_DIR, "meta")

_lock = threading.RLock()
_history = []  # list of candidate results
_frontier = []  # non-dominated candidates


# --------------------------------------------------------- candidate space ---

CANDIDATE_SPACE = {
    "model": [],           # populated dynamically from the router
    "prompt_style": [
        "balanced",        # default Longrun system prompt
        "concise",         # short, minimal
        "agentic",         # focused on action-driven splits
        "verbose",         # detailed instructions with examples
    ],
    "tool_approval": [
        "required",        # all mutating tools need human approval
        "auto",            # auto-approve all tools (recorded)
        "aggressive_auto", # auto-approve everything including shell
    ],
    "sandbox_backend": [
        "docker",          # full container isolation
        "bwrap",           # bubblewrap (lighter)
        "none",            # no sandbox (only for low-trust experiments)
    ],
    "max_steps": [4, 6, 8],
    "temperature": [0.5, 0.7, 0.9],
    "memory_enabled": [True, False],
    "external_mcp_enabled": [True, False],
}


def determine_candidate_from_config():
    """Read current harness config as a candidate spec."""
    cfg = registry.load_config()
    sb = cfg.get("sandbox", {})
    tools = cfg.get("tools", {})
    shell_policy = tools.get("shell", {}).get("approval", "required")
    # Map to our taxonomy
    if shell_policy == "auto":
        approval = "aggressive_auto"
    elif shell_policy == "required":
        approval = "required"
    else:
        approval = shell_policy
    return {
        "model": None,
        "prompt_style": "balanced",
        "tool_approval": approval,
        "sandbox_backend": sb.get("backend", "auto"),
        "max_steps": 6,
        "temperature": 0.7,
        "memory_enabled": True,
    }


def sample_candidates(n=8, fixed_seed=None):
    """Sample `n` candidate configurations from the space.

    Includes the current config as candidate 0, plus random variations.
    """
    if fixed_seed is not None:
        random.seed(fixed_seed)
    current = determine_candidate_from_config()
    candidates = [current]

    # Resolve available models
    try:
        from longrun.core.server import router_models, default_model
        models = [m["alias"] for m in router_models() if m.get("loaded")]
        if models:
            CANDIDATE_SPACE["model"] = models
    except Exception:
        CANDIDATE_SPACE["model"] = ["default"]

    # Sample random variations
    for _ in range(n - 1):
        cand = {}
        for key, choices in CANDIDATE_SPACE.items():
            if choices:
                cand[key] = random.choice(choices)
        # Ensure at least one difference from current
        if all(cand.get(k) == current.get(k) for k in CANDIDATE_SPACE if k != "model"):
            # Flip one random key
            key = random.choice([k for k in CANDIDATE_SPACE])
            if CANDIDATE_SPACE[key]:
                cand[key] = random.choice(CANDIDATE_SPACE[key])
        candidates.append(cand)

    return candidates


def candidate_label(cand, idx):
    """Human-readable label for a candidate.

    JAG-234: every field is coerced to a safe scalar first. `cand.get("model")`
    returns the stored value even when it is `None` (the key exists but the
    candidate space left it empty), and `None[:20]` / `%d` with a string both
    raised, which dropped the connection on a plain POST /api/meta.
    """
    def _txt(v, default):
        if v is None or (isinstance(v, str) and not v):
            return default
        return v if isinstance(v, str) else str(v)

    def _num(v, default, cast):
        try:
            return cast(v)
        except (TypeError, ValueError):
            return default

    model = _txt(cand.get("model"), "default")[:20]
    style = _txt(cand.get("prompt_style"), "?")[:4]
    approval = {"required": "req", "auto": "auto", "aggressive_auto": "agg"}.get(
        _txt(cand.get("tool_approval"), ""), "?")
    sandbox = _txt(cand.get("sandbox_backend"), "?")[:4]
    steps = _num(cand.get("max_steps", 0), 0, int)
    temp = _num(cand.get("temperature", 0.0), 0.0, float)
    mem = "M" if cand.get("memory_enabled") else "m"
    mcp = "C" if cand.get("external_mcp_enabled") else "c"
    return "C%d[%s-%s-%s-%s-s%d-t%.1f-%s%s]" % (
        idx, model, style, approval, sandbox, steps, temp, mem, mcp)


# --------------------------------------------------------- eval & scoring ---

def evaluate_candidate(cand, label, eval_task_id=None):
    """Run one standard eval task with the candidate's configuration.

    Returns dict: {label, config, quality, cost_tokens, cost_usd,
    duration_s, trace, error?}
    """
    # Store current config to restore later
    old_cfg = json.loads(json.dumps(registry.load_config()))
    result = {"label": label, "config": cand, "ts": time.time(),
              "quality": 0.0, "cost_tokens": 0, "cost_usd": 0.0,
              "duration_s": 0, "error": None}

    try:
        t0 = time.time()

        # Apply candidate config
        cfg = registry.load_config(reload=True)
        # Model is selected per-run, not via registry
        # Sandbox backend
        cfg["sandbox"]["backend"] = cand.get("sandbox_backend", cfg["sandbox"]["backend"])
        # Tool approval
        tool_key = cand.get("tool_approval", "required")
        for tname in ("shell", "fs.write", "git", "http"):
            policy = cfg["tools"].setdefault(tname, {})
            if tool_key == "aggressive_auto":
                policy["approval"] = "auto"
            else:
                policy["approval"] = tool_key
        registry.save_config(cfg)
        registry.load_config(reload=True)

        # Run eval
        from longrun.core.server import eval_run
        eval_result = eval_run(
            model=cand.get("model"),
            max_steps=cand.get("max_steps", 6),
            task_id=eval_task_id,
            save=False,
        )

        duration = time.time() - t0
        mean_score = eval_result.get("mean_score", 0.0)

        # Count tokens from the eval runs
        total_tokens = 0
        for task in eval_result.get("per_task", []):
            run_id = task.get("run_id")
            if run_id:
                from longrun.core.server import get_run_trace
                trace = get_run_trace(run_id)
                if trace:
                    total_tokens += trace.get("tokens_in", 0) + trace.get("tokens_out", 0)

        result.update({
            "quality": round(mean_score, 4),
            "cost_tokens": total_tokens,
            "cost_usd": round(eval_result.get("cost_usd", total_tokens / 1e6 * 0.15), 6),
            "duration_s": round(duration, 2),
            "per_task": eval_result.get("per_task", []),
        })

        # Memory
        if cand.get("memory_enabled"):
            try:
                from longrun.memory import memory
                memory.store("meta.eval", json.dumps(result, indent=2),
                             label=label, kind="meta.eval")
            except Exception:
                pass

    except Exception as e:
        result["error"] = str(e)
        result["quality"] = 0.0
    finally:
        # Restore original config
        try:
            registry.save_config(old_cfg)
            registry.load_config(reload=True)
        except Exception:
            pass

    return result


# ------------------------------------------------------- Pareto frontier ---

def pareto_frontier(results):
    """Return the non-dominated subset.

    A candidate dominates another if it has HIGHER quality and LOWER or equal
    cost (tokens). Ties in both dimensions are collapsed.
    """
    non_dominated = []
    for i, a in enumerate(results):
        dominated = False
        for j, b in enumerate(results):
            if i == j:
                continue
            if (b["quality"] > a["quality"] and b["cost_tokens"] <= a["cost_tokens"]):
                dominated = True
                break
            if (b["quality"] >= a["quality"] and b["cost_tokens"] < a["cost_tokens"]):
                dominated = True
                break
        if not dominated:
            non_dominated.append(a)
    return non_dominated


# --------------------------------------------------------- meta run loop ---

def meta_run(candidates=None, eval_task_id=None):
    """Run the meta-harness loop.

    1. Sample candidates (or use provided list)
    2. Evaluate each on the standard eval task
    3. Compute Pareto frontier
    4. Store in memory
    5. Return results + frontier
    """
    global _history, _frontier
    with _lock:
        if candidates is None:
            candidates = sample_candidates(n=8)
        results = []

        for idx, cand in enumerate(candidates):
            label = candidate_label(cand, idx)
            print("[meta] evaluating %s ..." % label)
            result = evaluate_candidate(cand, label, eval_task_id=eval_task_id)
            results.append(result)
            print("[meta]   quality=%.3f cost=%d tok %.2fs %s"
                  % (result["quality"], result["cost_tokens"],
                     result["duration_s"], "ERR" if result["error"] else "OK"))

        frontier = pareto_frontier(results)

        report = {
            "ts": time.time(),
            "n_candidates": len(results),
            "eval_task_id": eval_task_id,
            "results": results,
            "frontier": frontier,
            "frontier_labels": [r["label"] for r in frontier],
        }

        _history.extend(results)
        _frontier = frontier

        # Save to file
        os.makedirs(DATA_DIR, exist_ok=True)
        path = os.path.join(DATA_DIR, "meta-report-%d.json" % int(time.time()))
        with open(path, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2, ensure_ascii=False)
        report["saved_to"] = path

        # Store in memory
        try:
            from longrun.memory import memory
            memory.store("meta.report",
                         "Meta-harness report: %d candidates, %d on frontier\n%s"
                         % (len(results), len(frontier),
                            json.dumps(report, indent=2)[:4000]),
                         n_candidates=len(results), frontier_sz=len(frontier))
        except Exception:
            pass

        return report


# ---------------------------------------------------------------- API -----

def status():
    """Return meta-harness status / last report."""
    with _lock:
        return {
            "total_evaluated": len(_history),
            "frontier_size": len(_frontier),
            "frontier": [{
                "label": r["label"],
                "quality": r["quality"],
                "cost_tokens": r["cost_tokens"],
                "cost_usd": r["cost_usd"],
                "duration_s": r["duration_s"],
            } for r in _frontier] if _frontier else None,
        }


def propose_best():
    """Return the best candidate from the frontier (highest quality, break ties by cost)."""
    with _lock:
        if not _frontier:
            return {"error": "no frontier yet — run a meta evaluation first"}
        best = max(_frontier, key=lambda r: (r["quality"], -r["cost_tokens"]))
        return {"best": best, "frontier_size": len(_frontier),
                "recommendation": "Try candidate config from the Pareto frontier"}
