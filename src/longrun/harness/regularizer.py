#!/usr/bin/env python3
"""Regularizers for harness evolution — RRSI's search constraints, as predicates.

Source: P. Xia et al., *RRSI: Regularized Recursive Self-Improvement of Agent
Harnesses*, arXiv:2609.24972 (2026), §3.2–§3.3 and Table 2. The paper keeps the
harness edit space open and regularizes how a finite evolve set is turned into
permanent state:

1. an **annealed edit budget** — early rounds may bundle several coordinated
   edits, later rounds may not, so a measured change is attributable;
2. **leakage screening** — a candidate that encodes benchmark task names,
   entities or answers is refused BEFORE it is scored, so it never earns an
   inflated evolve-set score;
3. a **noise-adjusted floor** — a candidate must clear the A/A band and stay
   within it of the best score seen, so the search cannot walk downhill through
   small regressions;
4. **cost-aware acceptance** — a gain above the band must pay for its token
   growth (`Δcost ≤ β0 + β1·Δscore`), so a harness cannot buy score with context;
5. **structural pruning** — a component with no positive gain over a window is a
   deletion target, so the retained harness gets sparser rather than merely
   cheaper.

Every function here is pure and read-only: no model call, no network, no state.
The cycle calls (1) and (2) before probing when `regularize` is on; (3)–(5) are
available to the caller that has a numeric score and a token cost (R1's protocol
supplies both).
"""
import math
import re

#: Defaults from the paper's setting (§4, Appendix E): at most three
#: independently attributable edits early, one late; a negligible gain may cost
#: 5% more, and each point of score may buy half a point of cost.
B_MAX, B_MIN = 3, 1
BETA0, BETA1 = 0.05, 0.5


def edit_budget(round_index, rounds, b_max=None, b_min=None):
    """The number of attributable edits a candidate may bundle at this round.

    Linear annealing from `b_max` at round 0 to `b_min` at the last round, never
    below `b_min`, never above `b_max`. One round is `b_max`; invalid configs
    fail closed to the defaults rather than opening the budget.
    """
    try:
        t = max(0, int(round_index))
        total = max(1, int(rounds))
        hi = int(B_MAX if b_max is None else b_max)
        lo = int(B_MIN if b_min is None else b_min)
    except (TypeError, ValueError):
        hi, lo, t, total = B_MAX, B_MIN, 0, 1
    hi, lo = max(1, hi), max(1, lo)
    if lo > hi:
        lo = hi
    if total <= 1:
        return hi
    step = t / float(total - 1)
    value = int(math.floor(hi - (hi - lo) * min(1.0, step)))
    return max(lo, min(hi, value))


def count_edits(candidate):
    """Independently attributable edits in one candidate (1 when it says nothing).

    A candidate may name its edits (`edits` list) or its touched fields
    (`fields` dict/list); otherwise it is one opaque edit.
    """
    cand = candidate or {}
    edits = cand.get("edits")
    if isinstance(edits, (list, tuple)):
        return max(1, len(edits))
    fields = cand.get("fields")
    if isinstance(fields, (dict, list, tuple, set)):
        return max(1, len(fields))
    return 1


def leakage(candidate, terms):
    """Does the candidate encode a benchmark-specific term? (screen before scoring)

    `terms` are the evolve split's task names, entity names or answers. An empty
    term list screens nothing and says so (`screened: False`) — the honest
    answer, because a caller with no terms cannot make this judgment. Matching is
    case-insensitive and token-bounded where the term allows it, so `task42`
    does not fire on `task420`.
    """
    text = str((candidate or {}).get("content") or "")
    wanted = [str(t).strip() for t in (terms or []) if str(t or "").strip()]
    if not wanted:
        return {"ok": True, "leak": False, "hits": [], "screened": False}
    hits = []
    for term in wanted:
        pat = r"(?<![A-Za-z0-9])%s(?![A-Za-z0-9])" % re.escape(term)
        if re.search(pat, text, re.I):
            hits.append(term)
    return {"ok": True, "leak": bool(hits), "hits": sorted(set(hits)), "screened": True}


def admit(score, best_score, incumbent_score, cost_ratio, noise,
          beta0=None, beta1=None):
    """The acceptance rule: clear the noise, stay near the best, pay for growth.

    `score` / `best_score` / `incumbent_score` are rates in [0, 1]; `noise` is
    the A/A band (a number or `noise_band()`'s dict); `cost_ratio` is the
    candidate's token growth over the incumbent as a fraction (0.10 = +10%).
    Refusals name the rule so the report can say why a candidate did not ship.
    """
    try:
        band = float((noise or {}).get("band")) if isinstance(noise, dict) else float(noise)
        b0 = float(BETA0 if beta0 is None else beta0)
        b1 = float(BETA1 if beta1 is None else beta1)
        s, best, inc = float(score), float(best_score), float(incumbent_score)
        cost = max(0.0, float(cost_ratio))
    except (TypeError, ValueError):
        return {"ok": False, "reason": "invalid-input"}
    gain = round(s - inc, 4)
    if gain <= band:
        return {"ok": False, "reason": "within-noise", "gain": gain, "band": band}
    if s < best - band:
        return {"ok": False, "reason": "below-floor", "score": s,
                "best": best, "band": band}
    allowed = round(b0 + b1 * max(0.0, gain), 4)
    if cost > allowed:
        return {"ok": False, "reason": "cost", "cost_ratio": cost,
                "allowed": allowed, "gain": gain}
    return {"ok": True, "reason": "accepted", "gain": gain, "band": band,
            "allowed_cost_ratio": allowed}


def stalled(scores, window=3, delta=0.0):
    """Has progress over the last `window` rounds stayed inside `delta`?"""
    vals = []
    for value in list(scores or [])[-max(2, int(window or 3)):]:
        try:
            vals.append(float(value))
        except (TypeError, ValueError):
            return False
    if len(vals) < 2:
        return False
    return (max(vals) - min(vals)) <= float(delta or 0.0)


def unexplored(fields, exercised):
    """Fields the run has not tried yet — the structured-exploration target."""
    seen = {str(x) for x in (exercised or [])}
    return sorted({str(f) for f in (fields or []) if str(f) not in seen})


def prune(components, gains, window=3, min_gain=0.0):
    """Components whose recent gains never exceeded `min_gain` (deletion targets).

    `gains` maps a component to its per-round measured gains, oldest first. A
    component needs a full window of evidence to be pruned; missing evidence is
    not a verdict.
    """
    w = max(1, int(window or 3))
    targets = []
    for name in sorted({str(c) for c in (components or [])}):
        history = list((gains or {}).get(name) or [])
        if len(history) < w:
            continue
        recent = []
        for value in history[-w:]:
            try:
                recent.append(float(value))
            except (TypeError, ValueError):
                recent = []
                break
        if recent and max(recent) <= float(min_gain or 0.0):
            targets.append(name)
    return targets
