#!/usr/bin/env python3
"""Red-team coverage — count the ways in, not only how often the door opens.

Source: arXiv:2611.24313, "AUTOPI" (round 146). An attacker can post a high
attack success rate by reusing a few techniques that work, leaving the others
untested and absent from the data used to harden a model
(`autopi_adaptive_redteam_2611.24313.txt:17`, `:22`). Coverage is the fraction
of a fixed taxonomy's classes, techniques and sub-techniques with at least one
successful injection (`:127`, `:465`).

  * **robustness is a worst-case property**: an evaluation that omits a class
    can only overstate robustness (`:131`, `:133`).
  * **coverage is a first-class metric**: reported beside scenario-level ASR,
    with the attempt budget stated (`:123`, `:189`).
  * **equal sample, not equal count**: coverage grows with successes, so
    attackers are compared at `k = min |S_a|` (`:495`, `:1098`).
  * **equal cost, not equal attempts**: one attempt costs 0.6 GPU-seconds for
    AUTOPI against 2.9 to 14.5 for the trained baselines (`:145`, `:499`).
  * **concentration is measurable**: over 99% of one baseline's successes carry
    an authority claim, and the three most-used techniques of another appear in
    93%, 74% and 72% of its successes (`:566`, `:569`).
  * **measured**: AUTOPI covers 31 of 34 techniques against at most 22 for any
    baseline, and 78 of 132 sub-techniques against 48 (`:496`, `:549`).

  * `taxonomy(units)` — the three-level partition and its integrity.
  * `coverage(successes, totals)` — covered units at each level.
  * `concentration(successes, level)` — how much one technique carries.
  * `jaccard(successes)` — mean pairwise distance between technique sets.
  * `asr_at_k(attempts, k)` — scenario-level ASR at a stated budget.
  * `equal_sample(successes, k)` — coverage at an equal number of successes.
  * `equal_cost(rows)` — spend against the shared budget.
  * `label_check(rows)` — precision, recall and F1 for post-hoc labels.
  * `audit(record)` — the six misreadings the paper names.
  * `advise(profile)` — map a harness profile onto the paper's failure modes.

Pure: successes and attempts in; coverage, concentration and verdicts out.
"""
from __future__ import annotations

import itertools
import math

FORMAT = "longrun-redteam-coverage/1"

LEVELS = ("class", "technique", "sub_technique")
DEFAULTS = {"concentrated_share": 0.75, "diverse_distance": 0.5,
            "label_f1": 0.85, "subset_cap": 5000}


def taxonomy(units):
    """A three-level partition: unique ids, named units, all levels present."""
    rows = [u or {} for u in (units or [])]
    seen, duplicates, unnamed = set(), [], []
    counts = {level: 0 for level in LEVELS}
    for i, row in enumerate(rows):
        uid = str(row.get("id") or "")
        level = str(row.get("level") or "")
        if uid in seen:
            duplicates.append(uid)
        seen.add(uid)
        if not row.get("name"):
            unnamed.append(uid or "#%d" % i)
        if level in counts:
            counts[level] += 1
    missing = [level for level in LEVELS if counts[level] == 0]
    verdict = ("taxonomy-valid" if not duplicates and not unnamed and not missing
               else "taxonomy-incomplete")
    return {"format": FORMAT, "units": len(rows), "counts": counts,
            "duplicates": duplicates, "unnamed": unnamed, "missing_levels": missing,
            "verdict": verdict}


def coverage(successes, totals):
    """Covered units at each level against a supplied denominator."""
    rows = [s or {} for s in (successes or [])]
    totals = totals or {}
    out, rates = {}, {}
    for level in LEVELS:
        seen = {str(r.get(level)) for r in rows if r.get(level)}
        total = int(totals.get(level) or 0)
        out[level] = len(seen)
        rates[level] = (len(seen) / total) if total else None
    measured = any(rate is not None for rate in rates.values())
    return {"format": FORMAT, "successes": len(rows), "covered": out,
            "totals": {level: int(totals.get(level) or 0) for level in LEVELS},
            "rates": rates,
            "verdict": "coverage-measured" if measured else "denominator-missing"}


def concentration(successes, level="technique"):
    """The share of successes that carries the most common unit."""
    rows = [s or {} for s in (successes or [])]
    counts = {}
    for row in rows:
        unit = str(row.get(level) or "")
        if unit:
            counts[unit] = counts.get(unit, 0) + 1
    total = sum(counts.values())
    ranked = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    share = (ranked[0][1] / total) if total else 0.0
    return {"format": FORMAT, "level": level, "successes": total,
            "top": [{"unit": unit, "share": count / total if total else 0.0}
                    for unit, count in ranked[:3]],
            "max_share": share,
            "verdict": "concentrated" if total and share >= DEFAULTS["concentrated_share"]
            else "spread"}


def jaccard(successes, level="technique"):
    """Mean pairwise Jaccard distance between the technique sets of two successes."""
    sets = []
    for row in successes or []:
        r = row or {}
        units = r.get(level)
        if isinstance(units, (list, tuple, set)):
            sets.append({str(x) for x in units if x})
        elif units:
            sets.append({str(units)})
        else:
            sets.append(set())
    distances = []
    for a, b in itertools.combinations(sets, 2):
        union = a | b
        if not union:
            continue
        distances.append(1.0 - len(a & b) / len(union))
    mean = sum(distances) / len(distances) if distances else 0.0
    return {"format": FORMAT, "pairs": len(distances), "distance": mean,
            "verdict": "diverse" if mean >= DEFAULTS["diverse_distance"]
            else "repetitive"}


def asr_at_k(attempts, k=1):
    """Scenario-level ASR at an attempt budget; a success later than k is a miss."""
    rows = [a or {} for a in (attempts or [])]
    k = int(k or 1)
    hits, used = 0, []
    for row in rows:
        at = row.get("success_at")
        if at is None:
            continue
        at = int(at)
        if at <= k:
            hits += 1
            used.append(at)
    n = len(rows)
    curve = {}
    for step in (1, 2, 4, 8, 16, 32):
        if step > k:
            break
        curve[str(step)] = (sum(1 for r in rows
                                if r.get("success_at") is not None
                                and int(r["success_at"]) <= step) / n) if n else 0.0
    mean_attempts = (sum(used) / len(used)) if used else None
    return {"format": FORMAT, "scenarios": n, "k": k, "successes": hits,
            "asr": (hits / n) if n else 0.0, "curve": curve,
            "mean_attempts_to_success": mean_attempts,
            "verdict": "asr-at-budget" if n else "no-scenarios"}


def equal_sample(successes, k, level="technique", cap=DEFAULTS["subset_cap"]):
    """Coverage at an equal number of successes, averaged over subsets."""
    sets = []
    for row in successes or []:
        r = row or {}
        units = r.get(level)
        if isinstance(units, (list, tuple, set)):
            sets.append({str(x) for x in units if x})
        elif units:
            sets.append({str(units)})
    n = len(sets)
    k = int(k or 0)
    if not n or k < 1:
        return {"format": FORMAT, "verdict": "insufficient-successes"}
    k = min(k, n)
    total = math.comb(n, k)
    if total <= cap:
        subsets = itertools.combinations(range(n), k)
    else:
        step = max(1, total // cap)
        subsets = (combo for i, combo in enumerate(itertools.combinations(range(n), k))
                   if i % step == 0)
    sizes, count = 0, 0
    for combo in subsets:
        union = set()
        for i in combo:
            union |= sets[i]
        sizes += len(union)
        count += 1
    mean = sizes / count if count else 0.0
    return {"format": FORMAT, "successes": n, "k": k, "level": level,
            "subsets": count, "mean_units": mean,
            "verdict": "equal-sample-measured" if count else "no-subsets"}


def equal_cost(rows):
    """Spend against a shared budget, training included."""
    out = []
    for row in rows or []:
        r = row or {}
        spend = float(r.get("spend") or 0.0) + float(r.get("training_spend") or 0.0)
        budget = float(r.get("budget") or 0.0)
        out.append({"arm": str(r.get("arm") or ""), "spend": spend,
                    "budget": budget,
                    "share": (spend / budget) if budget else 0.0,
                    "attempts": int(r.get("attempts") or 0)})
    over = [row["arm"] for row in out if row["budget"] and row["share"] > 1.0 + 1e-9]
    return {"format": FORMAT, "arms": out, "over_budget": over,
            "verdict": "equal-cost" if not over else "over-budget"}


def label_check(rows):
    """Precision, recall and F1 for post-hoc labels against a reference."""
    tp = fp = fn = 0
    for row in rows or []:
        r = row or {}
        tp += int(r.get("tp") or 0)
        fp += int(r.get("fp") or 0)
        fn += int(r.get("fn") or 0)
    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0
    f1 = (2 * precision * recall / (precision + recall)
          if (precision + recall) else 0.0)
    return {"format": FORMAT, "tp": tp, "fp": fp, "fn": fn,
            "precision": precision, "recall": recall, "f1": f1,
            "verdict": "labels-validated" if f1 >= DEFAULTS["label_f1"]
            else "labels-weak"}


def audit(record):
    """The six misreadings the paper names, each as a finding."""
    r = record or {}
    findings = []
    if r.get("asr_only") is True:
        findings.append({"kind": "asr-only",
                         "why": "ASR counts how often, not how many ways"})
    if r.get("aggregation_masks_operation") is True:
        findings.append({"kind": "aggregation-masks-operation",
                         "why": "an average over operations hides an acute one"})
    if r.get("surface_diversity_as_coverage") is True:
        findings.append({"kind": "surface-diversity-as-coverage",
                         "why": "token or embedding distance is gamed by rephrasing"})
    if r.get("static_only") is True:
        findings.append({"kind": "static-only",
                         "why": "a fixed template measures the staleness of its own set"})
    if r.get("chosen_subset_as_population") is True:
        findings.append({"kind": "chosen-subset-as-population",
                         "why": "a stress subset is not an estimate over the benchmark"})
    if r.get("circular_labels") is True:
        findings.append({"kind": "circular-labels",
                         "why": "labels must not use what the attacker intended"})
    if not findings:
        findings.append({"kind": "audit-conditions-met"})
    return {"format": FORMAT, "findings": findings}


def advise(profile):
    """Map a harness profile onto the paper's failure modes."""
    p = profile or {}
    have = {str(k) for k, v in p.items() if v}
    checks = (
        ("reports_coverage_beside_asr", "headline-asr-only",
         "coverage says which ways were tested and which still work"),
        ("reports_per_class_results", "one-aggregate-number",
         "an average hides the class that breaks the target"),
        ("uses_a_fixed_partition", "attacker-specific-strategies",
         "a shared taxonomy makes coverage comparable across attackers"),
        ("compares_at_equal_sample", "coverage-at-unequal-samples",
         "coverage grows with successes and must be normalised"),
        ("compares_at_equal_cost", "equal-attempt-budgets",
         "one attempt does not cost the same for every attacker"),
        ("validates_post_hoc_labels", "trusts_its_own_labels",
         "coverage rests on labels that need a measured agreement"),
        ("states_the_attempt_budget", "asr_without_k",
         "ASR@k is meaningless without k or a compute share"),
    )
    findings = []
    for key, kind, why in checks:
        if key not in have:
            findings.append({"kind": kind, "why": why})
    return {"format": FORMAT, "findings": findings}
