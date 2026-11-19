#!/usr/bin/env python3
"""One run is not enough: a paired design, a noise floor, and a reported null.

Source: arXiv:2611.19359, "One Run Is Not Enough: Reminding a small Gemma 4
coding agent of its last finding made no measurable difference in a paired test"
(round 131). A harness mechanism was added, measured on 98 paired tasks, and
found to make no measurable difference — and the paper's value is the way it
establishes that:

  * the comparison is PAIRED by task, with the discordant pairs reported and an
    exact test on them, not a difference of two accuracies;
  * the noise floor is MEASURED first: the same arm against itself flipped 9 of
    48 tasks (18.75%) with no treatment at all, which sets the minimum
    detectable effect before any claim is made;
  * the first 48 pairs favoured the mechanism by +8.3 points and the
    pre-registered extension of 50 reversed to -10.0: the sign did not
    replicate, and a pre-registering author says so;
  * a mechanism must report DELIVERY (something was actually injected at 47–65%
    of compactions) and ADHERENCE (the model wrote notes in 2 of 16 and 4 of 32
    runs) — a mechanism that depends on the agent's cooperation largely does
    not happen;
  * memory COSTS: +2,000 tokens on every request, compactions 23 → 45, more
    overflows — a gain that is not priced against that cost is not a gain.

This module is the deterministic auditor a harness needs before it believes its
own improvement:

  * `paired(rows)` — per-arm solved counts, discordant pairs, exact McNemar;
  * `noise_floor(run1, run2)` — the A/A flip rate and the minimum detectable
    effect it implies;
  * `claim(rows, strata)` — effect, interval, p, and the findings that decide
    whether the claim survives: within-noise, not-significant, sign-not-
    replicated, delivery, adherence, cost;
  * `funnel(stages)` — the validity funnel a claim must state;
  * `budget(points)` — post-hoc count and the Bonferroni bound;
  * `advise(profile)` — what a harness may claim about a measured improvement.

Pure: run rows in, findings out. No paper number is reproduced.
"""
from __future__ import annotations

import math

FORMAT = "longrun-paired-trial/1"

# z at 0.975 and at 0.80: the two-sided 95% / 80% power factor.
Z_ALPHA = 1.959963984540054
Z_POWER = 0.8416212335729143


def _num(value, default=None):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _wilson(k, n, z=Z_ALPHA):
    """Wilson score interval for one proportion; returns (low, high)."""
    if not n:
        return (0.0, 1.0)
    p = k / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return (max(0.0, centre - half), min(1.0, centre + half))


def _newcombe(b, c, n, z=Z_ALPHA):
    """Newcombe's paired score interval for p1 - p2 on discordant counts.

    p1 = b/n (arm1 wins), p2 = c/n (arm2 wins); the interval combines the two
    Wilson intervals, which is what the paper reports beside exact McNemar.
    """
    if not n:
        return (None, None)
    p1, p2 = b / n, c / n
    l1, u1 = _wilson(b, n, z)
    l2, u2 = _wilson(c, n, z)
    d = p1 - p2
    low = d - math.sqrt((p1 - l1) ** 2 + (u2 - p2) ** 2)
    high = d + math.sqrt((u1 - p1) ** 2 + (p2 - l2) ** 2)
    return (round(low, 4), round(high, 4))


def _mcnemar(b, c):
    """Exact two-sided McNemar p on the discordant pairs (binomial)."""
    b, c = int(b), int(c)
    n = b + c
    if n == 0:
        return 1.0
    k = min(b, c)
    tail = sum(math.comb(n, i) for i in range(0, k + 1)) / (2 ** n)
    return round(min(1.0, 2 * tail), 6)


def paired(rows):
    """Per-arm solved counts and the discordant pairs.

    `rows` — [{"task": id, "control": bool, "treatment": bool}]
    """
    data = [r for r in (rows or []) if isinstance(r, dict) and r.get("task") is not None]
    n = len(data)
    ctrl = sum(1 for r in data if r.get("control"))
    treat = sum(1 for r in data if r.get("treatment"))
    b = sum(1 for r in data if r.get("control") and not r.get("treatment"))
    c = sum(1 for r in data if r.get("treatment") and not r.get("control"))
    both = sum(1 for r in data if r.get("control") and r.get("treatment"))
    findings = []
    if n == 0:
        findings.append({"kind": "no-pairs",
                         "why": "a paired claim needs paired rows"})
    effect = round((treat - ctrl) / n, 4) if n else None
    # The interval is on the treatment-minus-control scale: c wins for the
    # treatment, b wins for the control.
    low, high = _newcombe(c, b, n)
    p = _mcnemar(b, c)
    if n and p >= 0.05:
        findings.append({"kind": "not-significant", "p": p, "b": b, "c": c,
                         "why": "the discordant pairs do not distinguish the "
                                "arms; the difference is inside what pairing leaves"})
    return {"format": FORMAT, "n": n, "control_solved": ctrl,
            "treatment_solved": treat, "both": both,
            "treatment_only": c, "control_only": b,
            "effect": effect, "interval": [low, high], "p": p,
            "findings": findings,
            "why": "pair by task and read the discordant pairs; a difference of "
                   "two accuracies hides who changed"}


def noise_floor(run1, run2):
    """The A/A calibration: the same arm against itself.

    `run1`, `run2` — [{"task": id, "solved": bool}] for the SAME arm, run twice.
    """
    a = {r.get("task"): bool(r.get("solved")) for r in (run1 or [])
         if isinstance(r, dict) and r.get("task") is not None}
    b = {r.get("task"): bool(r.get("solved")) for r in (run2 or [])
         if isinstance(r, dict) and r.get("task") is not None}
    shared = sorted(set(a) & set(b), key=str)
    if not shared:
        return {"format": FORMAT, "flips": None, "flip_rate": None,
                "minimum_detectable_effect": None,
                "findings": [{"kind": "no-aa-calibration",
                              "why": "without running the same arm twice, the "
                                     "noise of one run is unknown and every "
                                     "small difference can be read as an effect"}],
                "why": "measure the noise before measuring the effect"}
    flips = sum(1 for t in shared if a[t] != b[t])
    n = len(shared)
    rate = round(flips / n, 4)
    se = math.sqrt(flips) / n if n else None
    mde = round((Z_ALPHA + Z_POWER) * se, 4) if se is not None else None
    findings = [{"kind": "noise-floor", "flips": flips, "n": n, "rate": rate,
                 "why": "a difference smaller than this floor cannot be told "
                        "from re-running the same arm"}]
    if mde is not None and mde >= 0.10:
        findings.append({"kind": "design-cannot-see-small-effects",
                         "minimum_detectable_effect": mde,
                         "why": "this many pairs can only detect a large "
                                "effect; a null here is not evidence of equality"})
    return {"format": FORMAT, "flips": flips, "n": n, "flip_rate": rate,
            "minimum_detectable_effect": mde, "findings": findings,
            "why": "the A/A contrast is the reference every treatment contrast "
                   "has to beat"}


def claim(rows, strata=None, floor=None):
    """Does the measured difference survive its own design?

    `rows` — paired rows as in `paired`.
    `strata` — [{"name": ..., "rows": paired rows}] — a replication set is a
    stratum whose sign was fixed BEFORE it ran.
    `floor` — the `noise_floor()` result, when the calibration was run.
    """
    base = paired(rows)
    findings = list(base["findings"])
    effect = base["effect"]
    mde = None
    if isinstance(floor, dict):
        mde = _num(floor.get("minimum_detectable_effect"))
    else:
        findings.append({"kind": "noise-floor-missing",
                         "why": "an effect is compared against the A/A floor; "
                                "without it the claim has no scale"})
    if mde is not None and effect is not None and abs(effect) < mde:
        findings.append({"kind": "within-noise", "effect": effect, "mde": mde,
                         "why": "the difference is smaller than what the same "
                                "arm produces against itself"})
    if isinstance(strata, list) and len(strata) >= 2:
        effects = []
        for group in strata:
            sub = paired(group.get("rows") or [])
            if sub["n"]:
                effects.append((str(group.get("name")), sub["effect"], sub["p"]))
        if len(effects) >= 2:
            signs = {1 if (e[1] or 0) > 0 else (-1 if (e[1] or 0) < 0 else 0)
                     for e in effects}
            if len(signs) > 1:
                findings.append({"kind": "sign-does-not-replicate",
                                 "strata": [{"name": n, "effect": e, "p": p}
                                            for n, e, p in effects],
                                 "why": "a hypothesis discovered on one set and "
                                        "reversed on the next is not a finding; "
                                        "the combined estimate is secondary"})
    if isinstance(floor, dict) and mde is not None and effect is not None \
            and abs(effect) >= mde and base["p"] is not None and base["p"] < 0.05:
        findings.append({"kind": "effect-exceeds-noise",
                         "effect": effect, "mde": mde, "p": base["p"],
                         "why": "the difference is larger than the measured "
                                "noise and the discordant pairs support it"})
    return {"format": FORMAT, "n": base["n"], "effect": effect,
            "interval": base["interval"], "p": base["p"],
            "minimum_detectable_effect": mde, "findings": findings,
            "why": "a measured improvement is a claim only when it clears the "
                   "noise floor and replicates in sign"}


def mechanism(stats):
    """Delivery, adherence and the cost of a mechanism.

    `stats` — {"opportunities": int, "delivered": int, "agent_wrote": int,
               "extra_tokens": int, "compactions_before": int,
               "compactions_after": int}
    """
    st = stats if isinstance(stats, dict) else {}
    opp = int(st.get("opportunities") or 0)
    delivered = int(st.get("delivered") or 0)
    wrote = int(st.get("agent_wrote") or 0)
    findings = []
    delivery = round(delivered / opp, 4) if opp else None
    adherence = round(wrote / opp, 4) if opp else None
    if delivery is not None and delivery < 0.9:
        findings.append({"kind": "delivery-too-low", "delivery": delivery,
                         "why": "the mechanism was absent at most of the moments "
                                "it was supposed to act, so its measured effect "
                                "is diluted by its own absence"})
    if adherence is not None and opp and adherence < 0.2:
        findings.append({"kind": "adherence-too-low", "adherence": adherence,
                         "why": "a mechanism that depends on the agent choosing "
                                "to use it largely does not happen"})
    extra = int(st.get("extra_tokens") or 0)
    before = int(st.get("compactions_before") or 0)
    after = int(st.get("compactions_after") or 0)
    if extra > 0 and after > before:
        findings.append({"kind": "context-cost-unpriced", "extra_tokens": extra,
                         "compactions_before": before,
                         "compactions_after": after,
                         "why": "the mechanism added prompt on every request and "
                                "bought more compactions; a gain that does not "
                                "pay for that is not a gain"})
    return {"format": FORMAT, "delivery": delivery, "adherence": adherence,
            "findings": findings,
            "why": "an intervention must report how often it happened, how often "
                   "the agent used it, and what it cost"}


def funnel(stages):
    """The validity funnel, and what a claim owes it.

    `stages` — [{"name": ..., "in": int, "out": int}]
    """
    rows = [s for s in (stages or []) if isinstance(s, dict) and s.get("name")]
    findings = []
    if not rows:
        return {"format": FORMAT, "stages": [], "findings":
                [{"kind": "validity-funnel-missing",
                  "why": "a score over tasks that do not pass their own gold "
                         "patch measures the fixture, not the agent"}],
                "why": "report every drop and the rule that caused it"}
    for row in rows:
        n_in = int(row.get("in") or 0)
        n_out = int(row.get("out") or 0)
        if n_out < n_in:
            findings.append({"kind": "stage-drops", "stage": row.get("name"),
                             "dropped": n_in - n_out,
                             "why": "the excluded tasks must be named with the "
                                    "rule that excluded them"})
    return {"format": FORMAT, "stages": rows,
            "valid": int(rows[-1].get("out") or 0), "findings": findings,
            "why": "the valid set is what the claim is about"}


def budget(points, bound=0.05):
    """Post-hoc count, the smallest p, and whether it survives correction."""
    rows = [p for p in (points or []) if isinstance(p, dict)]
    findings = []
    if not rows:
        return {"format": FORMAT, "post_hoc": 0, "findings": findings,
                "why": "no post-hoc tests reported"}
    p_values = [_num(p.get("p")) for p in rows if _num(p.get("p")) is not None]
    if not p_values:
        return {"format": FORMAT, "post_hoc": len(rows), "findings": findings,
                "why": "post-hoc tests without p-values are not results"}
    smallest = min(p_values)
    threshold = bound / len(rows)
    if smallest >= threshold:
        findings.append({"kind": "post-hoc-not-corrected",
                         "post_hoc": len(rows), "smallest_p": smallest,
                         "threshold": round(threshold, 6),
                         "why": "with this many post-hoc tests, the smallest "
                                "cannot be read as a finding without correction"})
    else:
        findings.append({"kind": "post-hoc-survives-correction",
                         "post_hoc": len(rows), "smallest_p": smallest,
                         "threshold": round(threshold, 6),
                         "why": "the smallest p survives a Bonferroni bound over "
                                "every test that was run"})
    return {"format": FORMAT, "post_hoc": len(rows), "smallest_p": smallest,
            "threshold": round(threshold, 6), "findings": findings,
            "why": "count every test that was run, not only the ones reported"}


def advise(profile):
    """What a harness may claim about a measured improvement."""
    prof = profile if isinstance(profile, dict) else {}
    findings = []
    if not prof.get("paired"):
        findings.append({"kind": "unpaired-comparison",
                         "why": "two accuracies over different samples cannot say "
                                "who changed; the same task must be run in both arms"})
    if not prof.get("aa_calibration"):
        findings.append({"kind": "no-noise-floor",
                         "why": "without running one arm twice, the size of a "
                                "noise-driven difference is unknown"})
    if prof.get("runs_per_task", 0) < 2 and not prof.get("aa_calibration"):
        findings.append({"kind": "single-run-claim",
                         "why": "one run per task on a few dozen tasks sits "
                                "inside run-to-run noise"})
    if not prof.get("preregistered"):
        findings.append({"kind": "not-preregistered",
                         "why": "an analysis chosen after seeing the result is "
                                "exploratory, and must be labelled so"})
    findings.append({"kind": "null-is-a-result",
                     "why": "a mechanism that was delivered, used and measured "
                            "and did not help is a finding about the harness"})
    return {"format": FORMAT, "findings": findings,
            "why": "a harness reports the pairing, the noise floor and the "
                   "validity funnel before it reports a gain"}
