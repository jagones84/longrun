#!/usr/bin/env python3
"""Task difficulty estimate (JAG-134).

Test-time compute "compute-optimal" (Snell et al., arXiv:2408.03314): the
effectiveness of scaling depends on the difficulty of the prompt, so the harness
must estimate it and allocate accordingly (how many candidates to sample, how many
continuation rounds to grant) instead of using a fixed budget.

DETERMINISTIC and explainable estimate: no model call, only signals that the
harness already has (open nodes of the task graph, message length,
outcome of previous turns, how many tools were used). PURE module.
"""
DEFAULTS = {
    "enabled": True,
    "easy_n": 1,        # best-of-N candidates for an easy task
    "medium_n": 2,
    "hard_n": 3,
    "medium_at": 0.35,  # score threshold -> "medium"
    "hard_at": 0.65,    # score threshold -> "hard"
}


def cfg(override=None):
    """Effective config: DEFAULTS <- config/tools.yaml (difficulty) -> override."""
    from longrun.tools.registry import section_config
    return section_config("difficulty", DEFAULTS, override)


def score(signals, c=None):
    """Difficulty score in [0,1] from the available signals (0 = trivial)."""
    s = signals or {}
    total = 0.0
    open_nodes = int(s.get("open_nodes") or 0)
    total += min(open_nodes * 0.15, 0.45)
    if int(s.get("msg_words") or 0) >= 120:
        total += 0.15
    if s.get("prev_error"):
        total += 0.20
    if s.get("prev_no_progress"):
        total += 0.20
    if int(s.get("tool_count") or 0) >= 6:
        total += 0.10
    if int(s.get("history_fail") or 0) >= 2:
        total += 0.15
    return round(max(0.0, min(1.0, total)), 3)


def estimate(signals, c=None):
    """Returns {"level","score","n","rounds"} — the allocation policy."""
    c = c or cfg()
    sc = score(signals, c)
    if not c.get("enabled"):
        level = "easy"
    elif sc >= float(c.get("hard_at") or 0.65):
        level = "hard"
    elif sc >= float(c.get("medium_at") or 0.35):
        level = "medium"
    else:
        level = "easy"
    n = {"easy": c.get("easy_n"), "medium": c.get("medium_n"),
         "hard": c.get("hard_n")}.get(level, 1)
    try:
        n = max(1, int(n))
    except (TypeError, ValueError):
        n = 1
    # continuation rounds scale with the difficulty (2x on hard vs easy)
    rounds_mult = {"easy": 1.0, "medium": 1.5, "hard": 2.0}.get(level, 1.0)
    return {"level": level, "score": sc, "n": n, "rounds_mult": rounds_mult}


def n_for(signals, c=None):
    """Number of best-of-N candidates suggested by the difficulty."""
    return estimate(signals, c)["n"]


def rounds_for(base_rounds, signals, c=None):
    """`base_rounds` (keepgoing_max) scaled by the difficulty, capped at 4x."""
    mult = estimate(signals, c)["rounds_mult"]
    try:
        out = int(round(float(base_rounds) * mult))
    except (TypeError, ValueError):
        out = int(base_rounds or 0)
    cap = int(base_rounds or 0) * 4
    return max(1, min(out, cap)) if cap else out

