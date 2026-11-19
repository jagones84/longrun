#!/usr/bin/env python3
"""Candidate scoring — should a decision model compare candidates at all?

Source: arXiv:2611.20335, "When Should Decision Models Compare Candidates?"
(round 128). Three scoring families are compared on five agent-decision
benchmarks and two controlled relational tasks: pointwise (each candidate scored
alone), setwise (joint encoding), and candidate attention (independent encoding
followed by cross-candidate attention). The findings are deliberately modest:

  * Pointwise stays competitive and leads on candidate selection and ordinal
    rating (Open-Jev choice 62.6 vs 41.6; rating 62.3 vs 56.9).
  * Setwise leads on tool/function selection (gaps under three points on
    choice; larger on binary) and on web elements only at K = 16.
  * Candidate attention never consistently beats pointwise; where it "wins" on
    binary, the gain is a shifted Yes threshold (34.7% predicted Yes vs 52.3%),
    not a benefit from comparing candidates.
  * Access to other candidates does not guarantee comparison: with relational
    training setwise learns the dependency and transfers to shifted inputs
    (S90R10: 81.3 numeric / 99.7 semantic), while the attention head stays at
    the OOD floor. A pointwise scorer cannot pass a reversal pair by
    construction.

  * `depends_on_candidates(mode)` — the structural difference.
  * `reversal(pair)` — the synthetic test: can independent scoring be right on
    both members of a pair?
  * `select(mode, scores)` — deterministic argmax with a stable tie rule.
  * `paired_success(instances)` — strict paired success (margin 1e-4).
  * `advise(task, candidates)` — what the measured evidence supports, with the
    task-specific caveat and "attention not preferred".
  * `binary_diagnostic(...)` — a Yes-rate shift is a threshold, not comparison.
  * `learnability(mode, relational_share)` — what training can change.

Pure: dicts in, dicts out. No number here reproduces the paper.
"""
from __future__ import annotations

FORMAT = "longrun-candidate-scoring/1"
MODES = ("pointwise", "setwise", "attention")
MARGIN = 1e-4


def depends_on_candidates(mode):
    """Pointwise scores are independent by definition; the others are not."""
    mode = str(mode or "").lower()
    return {"format": FORMAT, "mode": mode,
            "depends": mode in ("setwise", "attention"),
            "why": ("a candidate's score may use the other candidates"
                    if mode in ("setwise", "attention")
                    else "each score uses only the state, question and that candidate")}


def _instance_scores(instance):
    instance = instance if isinstance(instance, dict) else {}
    scores = instance.get("scores")
    return {str(k): float(v) for k, v in scores.items()} if isinstance(scores, dict) else {}


def select(mode, scores):
    """Deterministic argmax: highest score, then lexicographically smallest key."""
    scores = {str(k): float(v) for k, v in (scores or {}).items()}
    if not scores:
        return {"format": FORMAT, "mode": mode, "choice": None,
                "depends": depends_on_candidates(mode)["depends"]}
    choice = sorted(scores.items(), key=lambda kv: (-kv[1], kv[0]))[0][0]
    return {"format": FORMAT, "mode": mode, "choice": choice,
            "score": scores[choice],
            "depends": depends_on_candidates(mode)["depends"],
            "why": "selection compares scores; the mode decides what a score may see"}


def reversal(pair):
    """The synthetic median/singleton test: can independent scoring pass both?"""
    pair = pair if isinstance(pair, dict) else {}
    a = _instance_scores(pair.get("a") or pair.get("instance_a"))
    b = _instance_scores(pair.get("b") or pair.get("instance_b"))
    gold_a = str((pair.get("a") or pair.get("instance_a") or {}).get("gold") or "")
    gold_b = str((pair.get("b") or pair.get("instance_b") or {}).get("gold") or "")
    unchanged = sorted(k for k in a if k in b and a[k] == b[k])
    reversible = bool(gold_a and gold_b and gold_a != gold_b
                      and gold_a in unchanged and gold_b in unchanged)
    return {"format": FORMAT, "unchanged": unchanged,
            "gold_a": gold_a, "gold_b": gold_b,
            "reversible": reversible, "pointwise_sufficient": not reversible,
            "why": ("independent scoring gives the unchanged candidates the same "
                    "scores in both instances, so it cannot choose both"
                    if reversible else
                    "no unchanged pair carries a reversed gold choice")}


def paired_success(instances, margin=MARGIN):
    """Strict paired success: the gold must beat every alternative by > margin."""
    rows = [i for i in (instances or []) if isinstance(i, dict)]
    groups = {}
    for idx, inst in enumerate(rows):
        groups.setdefault(str(inst.get("pair", idx)), []).append(inst)
    strict = 0
    for members in groups.values():
        ok = True
        for inst in members:
            scores = _instance_scores(inst)
            gold = str(inst.get("gold") or "")
            if not gold or gold not in scores:
                ok = False
                break
            best_other = max((v for k, v in scores.items() if k != gold), default=float("-inf"))
            if not scores[gold] > best_other + margin:
                ok = False
                break
        if ok and members:
            strict += 1
    total = len(groups)
    return {"format": FORMAT, "pairs": total, "strict": strict,
            "rate": round(strict / total, 4) if total else None,
            "why": "a tie or a near tie is not evidence that the scorer used "
                   "the surrounding candidates"}


def advise(task, candidates=16):
    """Which scoring family the measured evidence supports for a task."""
    task = str(task or "unknown").lower()
    candidates = int(candidates or 0)
    table = {
        "tool_selection": {"preferred": "setwise", "margin": "small",
                           "caveat": "under three points on choice; the larger binary "
                                     "gap is a threshold shift"},
        "binary": {"preferred": "setwise", "margin": "moderate",
                   "caveat": "a gate has one candidate, so the gain is a changed "
                             "Yes threshold, not comparison"},
        "choice": {"preferred": "pointwise", "margin": "large",
                   "caveat": "pointwise leads by about 21 points on Open-Jev choice"},
        "rating": {"preferred": "pointwise", "margin": "moderate",
                   "caveat": "ordinal geometry is lost when levels become letters"},
        "web_element": {"preferred": "setwise" if 0 < candidates <= 16 else "pointwise",
                        "margin": "mixed",
                        "caveat": "the K = 64 drop is confounded with label coverage"},
    }
    row = table.get(task, {"preferred": "pointwise", "margin": "unmeasured",
                           "caveat": "no benchmark row for this task"})
    return {"format": FORMAT, "task": task, "candidates": candidates,
            "attention": "not-preferred", **row,
            "findings": [{"kind": "interaction-unproven",
                          "why": "access to other candidates does not guarantee "
                                 "effective comparison"}],
            "why": "pointwise remains competitive; prefer it unless the task is "
                   "tool or binary selection"}


def binary_diagnostic(gold_yes_rate, predicted_yes):
    """A binary gate's gain can be a moved threshold, not a comparison."""
    gold = float(gold_yes_rate or 0.0)
    predicted = float(predicted_yes or 0.0)
    shift = round(predicted - gold, 4)
    return {"format": FORMAT, "gold_yes_rate": gold, "predicted_yes_rate": predicted,
            "shift": shift,
            "verdict": "threshold-shift" if abs(shift) > 0.10 else "calibrated",
            "why": "with one candidate there is nothing to compare; only the "
                   "decision boundary moved"}


def learnability(mode, relational_share):
    """What relational supervision can and cannot teach each scorer."""
    mode = str(mode or "").lower()
    share = float(relational_share or 0.0)
    if mode == "pointwise":
        outcome = "impossible"
        why = "independent scores cannot represent a candidate-set dependency"
    elif mode == "attention":
        outcome = "fragile"
        why = "the head fits in-distribution relations but stays at the OOD floor"
    elif mode == "setwise":
        outcome = "learns" if share >= 0.10 else "unproven"
        why = ("relational examples teach the dependency and it transfers"
               if share >= 0.10 else
               "source-only training does not teach the dependency reliably")
    else:
        outcome = "unknown"
        why = "no such scoring mode"
    return {"format": FORMAT, "mode": mode, "relational_share": share,
            "outcome": outcome, "why": why}
