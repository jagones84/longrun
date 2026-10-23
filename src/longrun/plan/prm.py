#!/usr/bin/env python3
"""Longrun v0.95 — process reward / verification engine (prm).

A lightweight, inference-time course-corrector for the agent loop. It scores a
trajectory against an INEFFICIENCY TAXONOMY (spec / reasoning / coordination
errors) and renders a compact natural-language correction that the harness
injects back into the transcript — the same mechanism the frontier harnesses
ship as a Process Reward Model (PRM), but the deterministic core here needs no
model call, so it is cheap, safe and unit-testable.

Rationale (arXiv): 2504.00891 (GenPRM), 2502.10325 (AgentPRM),
2604.16529 (Scaling Test-Time Compute for Agentic Coding). The deterministic
rules cover the failure modes that recur in long-horizon coding runs
(repetition, premature "done", verification skipped).
"""

import json

# Inefficiency taxonomy: code -> human label. The deterministic scorer issues a
# subset of these; the full list is the taxonomy a model-guided PRM would use.
TAXONOMY = {
    "step_repetition": "repeated an identical action without progress",
    "verification_skipped": "declared done while task steps are still open",
    "termination_unaware": "kept working after the goal was already met",
    "tool_misuse": "used the wrong tool for the task",
    "information_ignored": "ignored a previous error or tool output",
    "goal_drift": "deviated from the main objective",
}

# Keys ignored when normalising tool args: volatile parameters a small model
# flips between otherwise-identical calls must not defeat repetition detection.
_IGNORED_ARGS = ("timeout_secs", "timeout", "args")

_PER_ISSUE_PENALTY = 0.15


def _norm_args(args):
    """Normalise tool args to a stable string for repetition comparison."""
    if args is None:
        return ""
    if isinstance(args, dict):
        return json.dumps(
            {k: args[k] for k in sorted(args) if k not in _IGNORED_ARGS},
            sort_keys=True, default=str)
    return str(args)


def _sig(step):
    """Canonical signature of a trajectory step (action, tool, normalised args)."""
    return (str(step.get("action")), str(step.get("tool") or ""),
            _norm_args(step.get("args")))


def evaluate(steps, open_nodes=0):
    """Score a trajectory and render correction feedback.

    Args:
        steps: list of dicts, each with action / tool / args (and optionally
            thought, observation).
        open_nodes: how many task-graph nodes are still open at the end.

    Returns dict(score, issues, feedback). score is in [0, 1]; issues is a list
    of {"code", "label"}; feedback is a compact correction string (empty when
    the trajectory is clean).
    """
    steps = steps or []
    issues = []

    # rule 1: step repetition — the same action+tool+args twice in a row.
    for i in range(1, len(steps)):
        if _sig(steps[i]) == _sig(steps[i - 1]):
            issues.append({"code": "step_repetition", "label": TAXONOMY["step_repetition"]})
            break

    # rule 2: verification skipped — finish while plan nodes are still open.
    if steps and open_nodes > 0 and str(steps[-1].get("action")).lower() == "finish":
        issues.append({"code": "verification_skipped",
                       "label": TAXONOMY["verification_skipped"]})

    score = max(0.0, 1.0 - _PER_ISSUE_PENALTY * len(issues))
    return {"score": round(score, 3), "issues": issues,
            "feedback": feedback_text(issues)}


def feedback_text(issues):
    """Render a compact natural-language correction from the detected issues."""
    if not issues:
        return ""
    return ("PROCESS FEEDBACK (inefficiencies): "
            + "; ".join("- %s" % i["label"] for i in issues))


# ------------------------------------------------------------------ ranking --
# JAG-132: deterministic ranker for best-of-N. Scores a CANDIDATE reply (text),
# not a trajectory: used to pick the best of N samples without a model call.

_ACTION_KEYS = ("action", "tool", "goal", "todos", "tasks")
_ANNOUNCE = ("procedo", "i'll", "i will", "let me", "carico", "now i", "adesso ",
             "sto per", "i'm going to", "let's ")


def _extract_json_obj(text):
    """Best-effort: the first balanced {...} object in `text`, or None."""
    if not text:
        return None
    from longrun.util.textkit import _iter_json_objects as _scan
    for obj in _scan(text):
        if isinstance(obj, dict):
            return obj
    return None


def rank_text(text):
    """Deterministic quality score in [0,1] for a candidate reply.

    Rewards a valid harness action / informative concrete prose; penalises
    malformed JSON and announcement-only replies (which look like work but are
    not). No model call — cheap, so it can rank N candidates in a loop.
    """
    t = (text or "").strip()
    if not t:
        return 0.0
    score = 0.5
    obj = _extract_json_obj(t)
    # a truncated JSON tool-call has no closing brace, so detect intent too
    looks_json = t.startswith(("{", "[")) or '"action"' in t or '"tool"' in t
    if obj is not None and any(k in obj for k in _ACTION_KEYS):
        score += 0.4                      # a real, parseable harness action
    elif looks_json:
        score -= 0.4                      # emitted JSON that did not parse
    low = t.lower()
    if not (obj is not None and any(k in obj for k in _ACTION_KEYS)):
        if any(a in low for a in _ANNOUNCE) and len(t) < 240:
            score -= 0.3                  # announced work without doing it
    for marker in ("```", "python3", "pytest", "git ", "def ", "curl ", "npm "):
        if marker in low:
            score += 0.1
            break
    score += min(len(t) / 4000.0, 0.2)    # prefer informative, substantive replies
    base = round(max(0.0, min(1.0, score)), 3)
    try:
        from longrun.core import matrix as _mtx
        adj = _mtx.call_hook("plan", "score_candidate", text, base, default=base)
        return round(max(0.0, min(1.0, float(adj))), 3)
    except Exception:  # noqa: BLE001
        return base


def rank(candidates):
    """Rank a list of candidate replies: [(text, score)] sorted best-first."""
    items = [(x, rank_text(x)) for x in (candidates or [])]
    return sorted(items, key=lambda kv: kv[1], reverse=True)
