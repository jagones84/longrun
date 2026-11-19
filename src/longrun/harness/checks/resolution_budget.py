#!/usr/bin/env python3
"""Resolution budget — evolution stalls because improvements are not detectable.

Source: arXiv:2611.23068, "The Resolution Hypothesis: Agent Evolution's Key Is
Identifying Improvements" (round 135). Across seven evolution methods and six
models the paper separates two variance components — evaluation noise `sigma^2`
and run-to-run variance `tau^2` — and shows that most published method margins
(median 3.4 pp) are smaller than one single run's standard deviation
(`resolution_hypothesis_agent_evolution_2611.23068.md:114`, `:116`).

  * **one observed score is `Y + eps`**, and `Var(Y_obs) = tau^2 + sigma^2`; the
    two sources must be bounded separately (`:87`, `:93`).
  * **identification costs runs**: `N = 2(z_{1-a/2}+z_{1-b})^2 s^2 / D^2`
    (`:118`, `:509`); at the median margin that is 5 to 23 runs per method.
  * **selection is at chance**: execution-based selection picks the better of
    two artifacts 49.7% of the time, and regressions are 30.5% of the pool but
    62.1% of accepted candidates (`:160`, `:180`).
  * **helpful candidates exist**: `Quality@K` rises from 49.2% at K=1 to 61.8%
    at K=100, +3.4 pp above an equal-quality null (`:152`, `:170`).
  * **in-loop gains are noise exploitation**: in-loop gains reach 6.9-9.0 pp
    while independent re-evaluation stays within +0.4 and -3.2 pp (`:192`).
  * **process metrics are cheaper to resolve**: 13x-57x lower noise than
    terminal pass/fail (`:246`, `:828`).

  * `runs_required(margin, sd)` — the repetition budget for a claimed margin.
  * `decompose(rows)` — `sigma`, `tau`, single-run sd from repeated evaluations.
  * `resolution(rows, margin, budget)` — is the margin identifiable at all.
  * `selection(pairs)` — pairwise accuracy, false acceptance, chance test.
  * `quality_at_k(rows, k)` — posterior `Quality@K` and its equal-quality null.
  * `advantage(rows, k)` — the excess a candidate pool really offers.
  * `advise(profile)` — map a harness profile onto the paper's failure modes.

Pure: measurements in; deterministic estimates out. The posterior draws use a
fixed seed so the same rows always give the same curve.
"""
from __future__ import annotations

import math
import random
import statistics

FORMAT = "longrun-resolution-budget/1"


def _num(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _z(p):
    return statistics.NormalDist().inv_cdf(p)


def runs_required(margin, sd, alpha=0.05, power=0.8):
    """Independent runs per method to identify a true margin, at power 1-beta."""
    m = _num(margin)
    s = _num(sd)
    if m is None or s is None or m <= 0 or s < 0:
        return None
    if not 0 < alpha < 1 or not 0 < power < 1:
        return None
    z = _z(1 - alpha / 2.0) + _z(power)
    return int(math.ceil(2.0 * z * z * s * s / (m * m)))


def decompose(rows, margin=None, alpha=0.05, power=0.8):
    """Split observed variance into evaluation noise and run-to-run variance."""
    data = list(rows or ())
    groups = []
    seen = {}
    for r in data:
        run = str(r.get("run"))
        score = _num(r.get("score"))
        if score is None:
            continue
        if run not in seen:
            seen[run] = []
            groups.append(run)
        seen[run].append(score)
    replicates = [seen[g] for g in groups if len(seen[g]) >= 2]
    if not replicates:
        return {"format": FORMAT, "sigma": None, "tau": None, "single_run": None,
                "findings": [{"kind": "not-enough-repetitions",
                              "why": "at least one artifact needs two or more evaluations"}]}
    sigma2 = statistics.mean(statistics.variance(v) for v in replicates)
    means = [statistics.mean(v) for v in replicates]
    m = statistics.mean(len(v) for v in replicates)
    tau2 = 0.0
    if len(means) >= 2:
        tau2 = max(0.0, statistics.variance(means) - sigma2 / m)
    sigma = math.sqrt(sigma2)
    tau = math.sqrt(tau2)
    single = math.sqrt(sigma2 + tau2)
    out = {"format": FORMAT, "runs": len(means), "evaluations": sum(len(v) for v in replicates),
           "sigma": round(sigma, 4), "tau": round(tau, 4),
           "single_run": round(single, 4), "findings": []}
    if tau > sigma:
        out["findings"].append({"kind": "run-to-run-dominates",
                                "tau": round(tau, 4), "sigma": round(sigma, 4),
                                "why": "repeating evaluations cannot fix this source"})
    if margin is not None:
        need = runs_required(margin, single, alpha, power)
        out["margin"] = _num(margin)
        out["runs_required"] = need
        if need is not None and need > 1:
            out["findings"].append({"kind": "single-run-insufficient",
                                    "runs_required": need,
                                    "why": "the claimed margin is below one single run's spread"})
    return out


def resolution(rows, margin, budget=8, alpha=0.05, power=0.8):
    """Is a claimed margin above the pipeline's resolution within a run budget?"""
    d = decompose(rows, margin, alpha, power)
    if d.get("single_run") is None:
        return d
    need = d.get("runs_required")
    findings = list(d["findings"])
    if need is not None:
        if need <= budget:
            findings.append({"kind": "identifiable", "runs_required": need, "budget": budget})
        else:
            findings.append({"kind": "below-resolution", "runs_required": need, "budget": budget,
                             "why": "the margin cannot be separated from noise at this budget"})
        d["verdict"] = "identifiable" if need <= budget else "below-resolution"
    d["findings"] = findings
    return d


def selection(pairs):
    """Pairwise accuracy and false acceptance of a selector against true quality."""
    rows = [p for p in (pairs or ()) if _num(p.get("chosen")) is not None
            and _num(p.get("rejected")) is not None]
    findings = []
    if not rows:
        return {"format": FORMAT, "findings": [{"kind": "no-comparisons"}]}
    wins = sum(1 for p in rows if _num(p["chosen"]) > _num(p["rejected"]))
    ties = sum(1 for p in rows if _num(p["chosen"]) == _num(p["rejected"]))
    n = len(rows)
    accuracy = (wins + 0.5 * ties) / n
    se = math.sqrt(max(accuracy * (1 - accuracy), 1e-12) / n)
    out = {"format": FORMAT, "comparisons": n, "accuracy": round(accuracy, 4),
           "se": round(se, 4), "findings": findings}
    accepted = [p for p in rows if p.get("accepted") is True]
    if accepted:
        worse = sum(1 for p in accepted
                    if _num(p.get("baseline")) is not None
                    and _num(p["chosen"]) < _num(p["baseline"]))
        out["accepted"] = len(accepted)
        out["false_accept_rate"] = round(worse / len(accepted), 4)
        if worse / len(accepted) > 0.5:
            findings.append({"kind": "regressions-accepted",
                             "rate": out["false_accept_rate"],
                             "why": "most accepted replacements are worse than the baseline"})
    if abs(accuracy - 0.5) <= 1.96 * se:
        findings.append({"kind": "indistinguishable-from-chance",
                         "accuracy": round(accuracy, 4), "se": round(se, 4)})
    elif accuracy > 0.5:
        findings.append({"kind": "better-than-chance", "accuracy": round(accuracy, 4)})
    else:
        findings.append({"kind": "worse-than-chance", "accuracy": round(accuracy, 4)})
    return out


def _prior(rows, kappa_max=100.0):
    rates = [r["successes"] / r["trials"] for r in rows if r["trials"] > 0]
    pooled = sum(r["successes"] for r in rows) / float(sum(r["trials"] for r in rows))
    trials = statistics.mean(r["trials"] for r in rows)
    noise = pooled * (1.0 - pooled) / trials if trials else 0.0
    dispersion = statistics.variance(rates) if len(rates) >= 2 else 0.0
    between = max(0.0, dispersion - noise)
    if between <= 0 or not 0 < pooled < 1:
        kappa = kappa_max
    else:
        kappa = pooled * (1.0 - pooled) / between - 1.0
        kappa = min(max(kappa, 0.25), kappa_max)
    return pooled, pooled * kappa, (1.0 - pooled) * kappa, kappa


def quality_at_k(rows, k, draws=2000, seed=7, _raw=False):
    """Posterior Quality@K: expected quality of the best of K candidates."""
    data = []
    for r in rows or ():
        s = _num(r.get("successes"))
        t = _num(r.get("trials"))
        if s is None or t is None or t <= 0 or s < 0 or s > t:
            continue
        data.append({"successes": s, "trials": t})
    if not data:
        return {"format": FORMAT, "findings": [{"kind": "no-candidates"}]}
    pooled, a, b, kappa = _prior(data)
    if not 0 < pooled < 1:
        return {"format": FORMAT, "quality": round(pooled, 4), "null": round(pooled, 4),
                "findings": [{"kind": "degenerate-pool", "why": "every candidate has the same score"}]}
    n = len(data)
    if k < 1 or k > n:
        return {"format": FORMAT, "findings": [{"kind": "k-exceeds-pool", "pool": n, "k": k}]}
    rng = random.Random(seed)
    observed, null = [], []
    for _ in range(int(draws)):
        sample = sorted(rng.betavariate(a + d["successes"], b + d["trials"] - d["successes"])
                        for d in data)
        null_sample = sorted(rng.betavariate(a + pooled * d["trials"],
                                             b + (1.0 - pooled) * d["trials"]) for d in data)
        weight = 0.0
        obs = 0.0
        nul = 0.0
        for rank in range(1, n + 1):
            if rank < k:
                continue
            weight = math.comb(rank - 1, k - 1) / float(math.comb(n, k))
            obs += weight * sample[rank - 1]
            nul += weight * null_sample[rank - 1]
        observed.append(obs)
        null.append(nul)
    observed.sort()
    null.sort()
    lo = observed[int(0.025 * (len(observed) - 1))]
    hi = observed[int(0.975 * (len(observed) - 1))]
    q = statistics.mean(observed)
    nl = statistics.mean(null)
    out = {"format": FORMAT, "pool": n, "k": int(k), "quality": round(q, 4),
           "ci": [round(lo, 4), round(hi, 4)], "null": round(nl, 4),
           "excess": round(q - nl, 4), "kappa": round(kappa, 2),
           "findings": [] if q > nl else [{"kind": "no-pool-headroom",
                                           "why": "the pool is no better than equal-quality"}]}
    if _raw:
        out["_draws"] = observed
        out["_null_draws"] = null
    return out


def advantage(rows, k, draws=2000, seed=7):
    """The excess a pool really offers, with the equal-quality null separated."""
    q = quality_at_k(rows, k, draws, seed, _raw=True)
    if "_draws" not in q:
        return q
    obs, nul = q.pop("_draws"), q.pop("_null_draws")
    q.pop("null")
    lo = obs[int(0.025 * (len(obs) - 1))]
    nul_hi = nul[int(0.975 * (len(nul) - 1))]
    findings = list(q["findings"])
    if lo > nul_hi:
        findings.append({"kind": "pool-has-headroom", "excess": q["excess"],
                         "why": "the posterior lower bound clears the equal-quality upper bound"})
    else:
        findings.append({"kind": "headroom-not-separated"})
    q["null_ceiling"] = round(nul_hi, 4)
    q["findings"] = findings
    return q


def advise(profile):
    """Map a harness profile onto the paper's failure modes."""
    p = profile or {}
    have = {str(key) for key, value in p.items() if value}
    findings = []
    checks = (
        ("reports_variance", "hides-variance", "publish sigma and tau beside every score"),
        ("repeats_runs", "single-run-ranking", "a ranking needs several independent runs"),
        ("repeats_evaluations", "noisy-evaluation", "re-evaluate each artifact before comparing"),
        ("separates_proposal_and_selection", "conflated-loop",
         "Quality@K and selected quality diagnose different halves"),
        ("audits_shortcuts", "shortcut-gains", "a large gain may exploit the evaluation"),
        ("repairs_evaluation", "unrepaired-evaluator", "grade by meaning, restore the official grader"),
        ("uses_process_metrics", "terminal-only", "low-variance process checks see small shifts"),
        ("declares_resolution", "unstated-resolution", "state the smallest detectable improvement"),
    )
    for key, kind, why in checks:
        if key not in have:
            findings.append({"kind": kind, "why": why})
    return {"format": FORMAT, "findings": findings}
