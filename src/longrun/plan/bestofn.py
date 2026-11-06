#!/usr/bin/env python3
"""Best-of-N with ranker (JAG-132).

Test-time compute "compute-optimal": for a NON-trivial step the harness samples
N candidates from the model and picks the best one with a deterministic ranker
(`prm.rank_text`), instead of accepting the first. For easy tasks (N=1) the
behavior stays identical: no overhead.

PURE module: the selection logic does not depend on the server. The generation of
the candidates (N calls to the model) is the caller's responsibility; here only
`choose()` + the config defaults live.

Config (`bestofn` block in config/tools.yaml):

    bestofn:
      enabled: false
      n: 1            # 1 = disabled (current behavior)
      min_score: 0.0  # if the best stays below this threshold -> None
"""
import os

DEFAULTS = {
    "enabled": False,
    "n": 1,
    "min_score": 0.0,
    "adaptive": True,   # JAG-134: the task difficulty can raise N
    # v838 (2026-11-06): `rank_text` scores TEXT, so it cannot judge an ACTION —
    # two parseable actions both score 0.9 and the length bonus decides. Spending
    # a second full-context sample on every action step measured 34.5% of the token
    # bill over three days (124M of 359M tokens), so by default the extra candidates
    # go to prose answers only. `true` restores the 2026-11-06 gate (sample actions).
    "on_actions": False,
}

# B-5 (v817): a second sample is only worth its tokens if it CAN differ from the
# first. Re-sending the same messages at the same temperature returns the same
# answer, so the fan-out spent 3-6x tokens to re-rank one candidate. Extra samples
# are asked warm and seeded; the RANKER stays deterministic (never a majority vote
# — samples from one model are correlated, so a vote adds nothing).
SAMPLE_TEMPERATURE = 1.0


def sample_params(index):
    """`(temperature, seed)` for extra candidate #`index` (1-based)."""
    return SAMPLE_TEMPERATURE, 1000 + int(index)


def cfg(override=None):
    """Effective config: DEFAULTS <- config/tools.yaml (bestofn) -> override."""
    from longrun.tools.registry import section_config
    return section_config("bestofn", DEFAULTS, override)


def n_of(c=None, signals=None):
    """Number of candidates to sample (>=1). 1 = disabled.

    JAG-134: with `adaptive` on and the task `signals`, N is the maximum between the
    configured value and the one suggested by the difficulty estimate (compute-optimal).
    """
    c = c or cfg()
    if not c.get("enabled"):
        return 1
    try:
        n = int(c.get("n") or 1)
    except (TypeError, ValueError):
        n = 1
    if c.get("adaptive", True) and signals is not None:
        try:
            from longrun.plan import difficulty
            n = max(n, difficulty.n_for(signals))
        except Exception:  # noqa: BLE001
            pass
    return max(1, min(n, 16))


def spend_extra(n, is_action, c=None):
    """True when a second candidate is worth its tokens for THIS step.

    v838: `rank_text` scores text quality, so it cannot discriminate between two
    parseable actions (both get 0.9, then the length bonus decides) — the extra
    sample bought verbosity, at the price of a full-context call per step. Extra
    candidates are therefore spent on prose answers only, where the ranker's
    announcement/substance signals mean something; `bestofn.on_actions: true`
    restores the previous gate.
    """
    if int(n or 1) <= 1:
        return False
    c = c or cfg()
    return bool(is_action) if c.get("on_actions") else not bool(is_action)


def choose(candidates, scorer=None, c=None):
    """Chooses the best candidate according to `scorer` (default prm.rank_text).

    Returns (best, scores): `best` is None if no candidate reaches
    `min_score` (or the list is empty). `scores` is the list (candidate, score).
    """
    c = c or cfg()
    if scorer is None:
        try:
            from longrun.plan import prm
            scorer = prm.rank_text
        except Exception:  # noqa: BLE001
            scorer = lambda _t: 0.0  # noqa: E731
    items = []
    for x in (candidates or []):
        # Audit F4: a scorer failure used to become 0.0 and could still WIN
        # against a floor of 0. Failed candidates are excluded from the
        # ranking instead; only an all-failed field falls back to the legacy
        # first-pick so the loop never breaks on a broken scorer.
        s = _score(scorer, x)
        if s is not None:
            items.append((x, s))
    if not items:
        if not candidates:
            return None, []
        legacy = [(x, 0.0) for x in candidates]
        best, best_score = legacy[0][0], 0.0
        items = legacy
    else:
        best, best_score = max(items, key=lambda kv: kv[1])
    try:
        floor = float(c.get("min_score") or 0.0)
    except (TypeError, ValueError):
        floor = 0.0
    if best_score < floor:
        return None, items
    return best, items


def _score(scorer, text):
    """A scorer's float, or None when the scorer itself fails."""
    try:
        return float(scorer(text))
    except Exception:  # noqa: BLE001
        return None

