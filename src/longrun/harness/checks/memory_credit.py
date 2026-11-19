#!/usr/bin/env python3
"""Decision-utility memory — relevance is a recall signal, not an arbitration one.

Source: arXiv:2611.15600, "MemCredit: From Relevance to Utility for Decision-Time
Memory in Long-Horizon Web Agents" (round 125). The paper's measurement is the
reason this module exists: across 1,041 context-conditional interventions on 45
ALFWorld tasks, **86.9% produce no measurable behavioural change**, mean utility
is 0.176 in failure contexts but 0.029 elsewhere, and semantic relevance is
essentially uncorrelated with counterfactual utility (rho = -0.011 overall,
-0.191 on the dense subset, +0.135 on the broad subset) (§4.3, Table 3). A
retriever that ranks by similarity is therefore ranking by the wrong quantity.

Two consequences are encoded here:

  * relevance keeps its job — high-RECALL candidate generation only; utility
    arbitrates, and the two are never interpolated (the paper's hybrid with
    lambda=0.5 scores 78.36 vs 84.33 for utility-only, Table 5);
  * utility is STATE- and CONTEXT-conditional, so a memory already covered by
    the selected set stops being worth its tokens: credit is recomputed after
    every insertion and an item may drop to zero.

  * `credit(candidate, reference)` — novelty-weighted utility against the
    memory already selected (the redundancy case single-removal credit hides).
  * `arbitrate(candidates, budget)` — greedy credit per added token, re-scored
    after each insertion, stopping on an empty eligible set (the budget is a
    ceiling, not a target, §3.4).
  * `sparsity(rows)` — the honesty check: how much of this memory set actually
    changed a decision, and is the failure-context effect visible?

The counterfactual collection and the ExtraTrees estimator are NOT reproduced;
`utility` is an input, and the module says so in every answer.
"""
from __future__ import annotations

FORMAT = "longrun-memory-credit/1"


def _tokens(text):
    return {w for w in str(text or "").lower().split() if w}


def _novelty(facts, covered):
    if not facts:
        return 1.0 if not covered else 0.0
    return len(facts - covered) / len(facts)


def credit(candidate, reference=()):
    """A memory already covered by the selection is worth zero, whatever its relevance."""
    cand = candidate if isinstance(candidate, dict) else {}
    facts = _tokens(cand.get("content"))
    covered = set()
    for item in reference or ():
        covered |= _tokens(item.get("content") if isinstance(item, dict) else item)
    novelty = _novelty(facts, covered)
    try:
        utility = float(cand.get("utility") or 0.0)
    except (TypeError, ValueError):
        utility = 0.0
    return {"format": FORMAT, "id": str(cand.get("id") or ""),
            "relevance": cand.get("relevance"),
            "novelty": round(novelty, 4),
            "credit": round(utility * novelty, 4),
            "why": ("covered by the selected set" if novelty == 0
                    else "utility scaled by the facts it still adds")}


def arbitrate(candidates, budget, min_credit=0.0):
    """Select by predicted credit per added token under a token ceiling."""
    rows = [c for c in (candidates or ()) if isinstance(c, dict)]
    try:
        budget = int(budget)
    except (TypeError, ValueError):
        return {"format": FORMAT, "selected": [], "spent": 0, "findings":
                [{"kind": "bad-budget"}], "why": "no ceiling, no arbitration"}
    selected, spent, findings = [], 0, []
    remaining = list(rows)
    if not rows:
        return {"format": FORMAT, "selected": [], "spent": 0,
                "findings": [{"kind": "no-candidates"}], "why": "nothing to arbitrate"}
    while remaining:
        best = None
        for cand in remaining:
            try:
                cost = max(1, int(cand.get("tokens") or 1))
            except (TypeError, ValueError):
                cost = 1
            if spent + cost > budget:
                continue
            c = credit(cand, selected)["credit"]
            if c <= min_credit:      # a zero-credit memory does not earn its tokens
                continue
            per_token = c / cost
            if best is None or per_token > best[0]:
                best = (per_token, cand, cost, c)
        if best is None:
            break
        _per, cand, cost, c = best
        cid = str(cand.get("id") or "")
        if any(s["id"] == cid for s in selected):
            findings.append({"kind": "duplicate-id", "id": cid})
            remaining.remove(cand)
            continue
        selected.append({"id": cid, "tokens": cost, "credit": c,
                         "relevance": cand.get("relevance"),
                         "content": cand.get("content")})
        spent += cost
        remaining.remove(cand)
    unused = budget - spent
    if unused > 0:
        findings.append({"kind": "budget-not-filled", "unused": unused,
                         "why": "the ceiling is a limit, never a quota to fill"})
    return {"format": FORMAT, "selected": selected, "spent": spent,
            "findings": findings,
            "why": "each insertion re-scores the rest, so coverage can zero a candidate"}


def sparsity(rows):
    """How much of this memory set was consequential, and where the effect sits."""
    rows = [r for r in (rows or ()) if isinstance(r, dict)]
    if not rows:
        return {"format": FORMAT, "n": 0,
                "findings": [{"kind": "no-interventions"}],
                "why": "a sparsity claim needs interventions"}
    credits, failure, other = [], [], []
    for row in rows:
        try:
            value = float(row.get("credit") or 0.0)
        except (TypeError, ValueError):
            value = 0.0
        credits.append(value)
        (failure if row.get("state") == "failure_context" else other).append(value)
    zero = sum(1 for c in credits if c == 0)
    mean = sum(credits) / len(credits)
    findings = []
    if zero / len(credits) >= 0.5:
        findings.append({"kind": "utility-sparse", "zero_share": round(zero / len(credits), 4)})
    if failure and other:
        f_mean = sum(failure) / len(failure)
        o_mean = sum(other) / len(other)
        if f_mean > o_mean:
            findings.append({"kind": "failure-concentrated",
                             "failure": round(f_mean, 4), "other": round(o_mean, 4)})
    return {"format": FORMAT, "n": len(credits), "mean": round(mean, 4),
            "zero_share": round(zero / len(credits), 4),
            "failure_mean": round(sum(failure) / len(failure), 4) if failure else None,
            "other_mean": round(sum(other) / len(other), 4) if other else None,
            "findings": findings,
            "why": "relevance is not utility; the zero share is the evidence, not a defect"}
