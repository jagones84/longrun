#!/usr/bin/env python3
"""A defense that is never attacked is a guess; the stressors must evolve too.

Source: arXiv:2611.22583, "Evolution Under Fire: Evolving Agent Safety
Harnesses with Adaptive Injection Stressors" (round 131). The paper searches
over complete EXECUTABLE safety harnesses while the task model, the benchmark,
the tools and the evaluator stay fixed, and it couples that search with a second
search over the attacks themselves. Four invariants are harness-relevant:

  * UTILITY IS A CONSTRAINT ON PARENTHOOD, not a coordinate to trade away: a
    candidate that fails the utility requirement can never become a parent, but
    it stays in the archive as a negative example — "safety" obtained by
    disabling useful behaviour is not a candidate;
  * parents are sampled from the Pareto FRONT of separate coordinates under
    FINITE counts (posterior sampling), never from a scalarised score; a linear
    chain cannot go back to a strong earlier branch, and its terminal child can
    be worse than its own best;
  * a stressor is PROMOTED only when the attack succeeds AND the benign task
    still succeeds AND the execution completed without error; a stressor that
    destroys the task, or one whose run failed, is evidence, not feedback;
  * more utility-qualified candidates is NOT a better search: the measure that
    matters is the best adversarial resistance reached at a matched budget, and
    a defence evolved against adaptive stressors must be checked for TRANSFER
    to recipients it never saw.

This module is the deterministic auditor over a search's own records:

  * `qualify(row)` — parent or counterexample;
  * `promote(result)` — may this stressor feed the next stage?
  * `pareto(candidates)` — the first non-dominated front, coordinates separate;
  * `sample_parent(front, seed)` — a deterministic posterior-Pareto pick;
  * `compare_search(configs)` — matched-budget comparison, plus the regression a
    linear chain hides;
  * `transfer(stressors, recipients)` — source-only vs effective-everywhere;
  * `advise(profile)` — what a harness may claim about its own evolution.

Pure: records in, findings out. No paper number is reproduced.
"""
from __future__ import annotations

import random

FORMAT = "longrun-stress-evolution/1"

# The objectives stay separate: utility is maximised, risk minimised, and the
# risk coordinates are sign-reversed only for the dominance comparison.
OBJECTIVES = ("utility", "risk")

# Why a candidate cannot become a parent.
PARENT_REASONS = ("execution-incomplete", "utility-lost", "no-records")


def _num(value, default=None):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def qualify(row):
    """May this candidate become a parent, or is it only a counterexample?"""
    rec = row if isinstance(row, dict) else {}
    reasons = []
    if not rec:
        reasons.append({"kind": "no-records",
                        "why": "a candidate with no evaluated records cannot be "
                               "expanded"})
    if rec.get("complete") is False or rec.get("errors"):
        reasons.append({"kind": "execution-incomplete",
                        "why": "only a run that completed without error "
                               "establishes anything"})
    utility = _num(rec.get("utility"))
    floor = _num(rec.get("utility_floor"))
    if utility is not None and floor is not None and utility < floor:
        reasons.append({"kind": "utility-lost",
                        "utility": utility, "floor": floor,
                        "why": "an apparent safety gain obtained by breaking "
                               "useful behaviour is not a candidate"})
    parent = not reasons
    return {"format": FORMAT, "parent": parent,
            "counterexample": bool(reasons), "findings": reasons,
            "why": "a failed candidate stays visible as a negative example, but "
                   "it never becomes a parent"}


def promote(result):
    """Does a generated stressor become feedback for the next stage?"""
    rec = result if isinstance(result, dict) else {}
    findings = []
    attack = rec.get("attack_succeeded")
    utility = rec.get("task_succeeded")
    complete = rec.get("complete", True)
    if attack is None or utility is None:
        findings.append({"kind": "outcome-unrecorded",
                         "why": "a stressor without both outcomes cannot be "
                                "promoted or rejected"})
    if complete is False or rec.get("errors"):
        findings.append({"kind": "incomplete-run",
                         "why": "a stressor whose evaluation errored proves "
                                "nothing about the defence"})
    if attack is not True:
        findings.append({"kind": "attack-failed",
                         "why": "a stressor the harness already resists carries "
                                "no signal for the next stage"})
    if utility is not True:
        findings.append({"kind": "utility-destroyed",
                         "why": "a stressor that breaks the benign task attacks "
                                "the task, not the defence"})
    promoted = not findings
    dup = bool(rec.get("duplicate"))
    if promoted and dup:
        findings.append({"kind": "duplicate-stressor",
                         "why": "one promoted stressor per distinct behaviour; "
                                "a duplicate adds cost and no coverage"})
        promoted = False
    return {"format": FORMAT, "promoted": promoted,
            "kept_as_evidence": True, "findings": findings,
            "why": "promotion needs the attack to succeed AND the benign task to "
                   "survive, on a run that completed"}


def pareto(candidates):
    """The first non-dominated front, with every coordinate kept separate.

    `candidates` — [{"id": ..., "utility": 0-1, "risk": 0-1, "n": int}]
    """
    rows = [c for c in (candidates or []) if isinstance(c, dict)
            and c.get("id") is not None]
    findings = []
    if not rows:
        return {"format": FORMAT, "front": [], "dominated": [],
                "findings": [{"kind": "no-candidates",
                              "why": "an empty archive has no frontier"}],
                "why": "nothing to rank"}
    for row in rows:
        if row.get("score") is not None and row.get("utility") is None:
            findings.append({"kind": "scalarised-candidate", "id": row.get("id"),
                             "why": "a single aggregate score cannot say which "
                                    "coordinate a candidate won on; the "
                                    "frontier is built from the separate ones"})
    usable = [r for r in rows if _num(r.get("utility")) is not None
              and _num(r.get("risk")) is not None]
    front, dominated = [], []
    for row in usable:
        u, r = _num(row["utility"]), _num(row["risk"])
        beaten = False
        for other in usable:
            if other is row:
                continue
            ou, orr = _num(other["utility"]), _num(other["risk"])
            if ou >= u and orr <= r and (ou > u or orr < r):
                beaten = True
                break
        (dominated if beaten else front).append(row.get("id"))
    if front:
        findings.append({"kind": "frontier", "n": len(front),
                         "why": "parents are drawn from here, so a strong older "
                                "branch can be revisited instead of abandoned"})
    return {"format": FORMAT, "front": sorted(front),
            "dominated": sorted(dominated), "findings": findings,
            "why": "utility up and risk down, both kept as separate coordinates"}


def sample_parent(front, seed=0):
    """A deterministic posterior-Pareto pick over the front.

    `front` — [{"id": ..., "utility_success": int, "n": int,
                "risk_success": int}] — Bernoulli counts, not point estimates:
    the uncertainty of a finite evaluation is part of the choice.
    """
    rows = [r for r in (front or []) if isinstance(r, dict) and r.get("id") is not None]
    if not rows:
        return {"format": FORMAT, "parent": None,
                "findings": [{"kind": "empty-front",
                              "why": "no utility-qualified parent to expand"}],
                "why": "the search cannot expand from nothing"}
    rng = random.Random(seed)
    sampled = []
    for row in rows:
        n = max(int(row.get("n") or 1), 1)
        good = min(max(int(row.get("utility_success") or 0), 0), n)
        bad = n - good
        risk_n = max(int(row.get("risk_n") or n), 1)
        risk_good = min(max(int(row.get("risk_success") or 0), 0), risk_n)
        utility = rng.betavariate(good + 1, bad + 1)
        risk = rng.betavariate(risk_good + 1, risk_n - risk_good + 1)
        sampled.append((row.get("id"), utility - risk))
    sampled.sort(key=lambda pair: (-pair[1], str(pair[0])))
    return {"format": FORMAT, "parent": sampled[0][0],
            "sampled": [{"id": i, "margin": round(m, 6)} for i, m in sampled],
            "findings": [],
            "why": "posterior sampling keeps a small-sample estimate from being "
                   "treated as a measurement"}


def compare_search(configs):
    """Matched-budget comparison: more qualifiers is not a better search.

    `configs` — [{"name": "tree"|"uniform"|"linear", "budget": int,
                  "qualified": int, "best_risk": 0-1, "terminal_risk": 0-1}]
    """
    rows = [c for c in (configs or []) if isinstance(c, dict) and c.get("name")]
    findings = []
    if len(rows) < 2:
        findings.append({"kind": "no-control",
                         "why": "a search is a result only against a "
                                "budget-matched control and a linear chain"})
    budgets = {c.get("budget") for c in rows if c.get("budget") is not None}
    if len(budgets) > 1:
        findings.append({"kind": "budget-mismatch", "budgets": sorted(budgets),
                         "why": "a comparison across different budgets measures "
                                "the budget, not the search"})
    by_name = {str(c["name"]).lower(): c for c in rows}
    linear = by_name.get("linear")
    if linear:
        best = _num(linear.get("best_risk"))
        terminal = _num(linear.get("terminal_risk"))
        if best is not None and terminal is not None and terminal > best:
            findings.append({"kind": "linear-chain-regresses",
                             "best": best, "terminal": terminal,
                             "why": "a chain cannot return to an earlier strong "
                                    "branch, so its last child can be worse than "
                                    "its own best"})
    qualifying = [(str(c["name"]).lower(), int(c.get("qualified") or 0),
                   _num(c.get("best_risk"))) for c in rows
                  if c.get("qualified") is not None and c.get("best_risk") is not None]
    if len(qualifying) >= 2:
        most = max(qualifying, key=lambda t: t[1])
        lowest = min(qualifying, key=lambda t: t[2] if t[2] is not None else 9)
        if most[0] != lowest[0]:
            findings.append({"kind": "more-candidates-is-not-better",
                             "most_qualified": most[0], "best_risk": lowest[0],
                             "why": "the configuration that produced more "
                                    "qualified children did not produce the "
                                    "strongest one"})
    return {"format": FORMAT,
            "configs": {str(c["name"]).lower(): {"qualified": c.get("qualified"),
                                                 "best_risk": c.get("best_risk"),
                                                 "terminal_risk": c.get("terminal_risk")}
                        for c in rows},
            "findings": findings,
            "why": "compare at one budget, against the linear chain and the "
                   "uniform sampler, and read the BEST candidate not the count"}


def transfer(stressors, recipients=None):
    """Did the evolved stressors find weaknesses outside their own target?

    `stressors` — [{"id": ..., "results": [{"recipient": ..., "attack": bool,
                                            "utility": bool, "complete": bool}]}]
    `recipients` — optional [ids]: when given, a stressor that has no result on
    one of them is source-only, because a missing recipient is not a pass.
    """
    rows = [s for s in (stressors or []) if isinstance(s, dict)]
    findings = []
    if not rows:
        return {"format": FORMAT, "transferring": [], "source_only": [],
                "findings": [{"kind": "no-stressors",
                              "why": "no evolved stressor to transfer"}],
                "why": "transfer is measured, never assumed"}
    transferring, source_only = [], []
    wanted = {str(r) for r in (recipients or [])}
    for item in rows:
        results = [r for r in (item.get("results") or []) if isinstance(r, dict)]
        if not results:
            source_only.append(item.get("id"))
            continue
        covered = {str(r.get("recipient")) for r in results}
        if wanted - covered:
            source_only.append(item.get("id"))
            continue
        ok = all(r.get("attack") and r.get("utility") and r.get("complete", True)
                 for r in results)
        (transferring if ok else source_only).append(item.get("id"))
    if transferring:
        findings.append({"kind": "stressor-transfers", "n": len(transferring),
                         "why": "the weakness is not confined to the harness the "
                                "stressor was generated against"})
    if source_only and not transferring:
        findings.append({"kind": "stressor-source-specific", "n": len(source_only),
                         "why": "every evolved stressor works only on its own "
                                "target: the search overfitted to one harness"})
    return {"format": FORMAT, "transferring": sorted(transferring),
            "source_only": sorted(source_only), "findings": findings,
            "why": "a stressor counts as transferred only when it attacks AND "
                   "preserves the task on every recipient"}


def advise(profile):
    """What a harness may claim about its own safety evolution."""
    prof = profile if isinstance(profile, dict) else {}
    findings = []
    if prof.get("safety_gain") and not prof.get("utility_held"):
        findings.append({"kind": "safety-bought-with-utility",
                         "why": "a defence that lowers attack success by breaking "
                                "the task has not defended anything"})
    if not prof.get("negative_archive"):
        findings.append({"kind": "counterexamples-not-kept",
                         "why": "a candidate that failed utility is the most "
                                "informative record of the search; deleting it "
                                "makes the next run repeat it"})
    if not prof.get("adaptive_stressors"):
        findings.append({"kind": "fixed-attack-suite",
                         "why": "optimising against one attack family produces a "
                                "defence for that family"})
    if not prof.get("transfer_checked"):
        findings.append({"kind": "transfer-not-checked",
                         "why": "a harness evolved against its own reported "
                                "failures may simply encode them"})
    findings.append({"kind": "defence-is-a-search-not-a-design",
                     "why": "any single hand-designed defense is one point in "
                            "the space the next attack is chosen against"})
    return {"format": FORMAT, "findings": findings,
            "why": "a harness reports its utility constraint, its negative "
                   "archive and its adaptive pressure, or it reports a guess"}
