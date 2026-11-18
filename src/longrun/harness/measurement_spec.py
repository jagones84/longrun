#!/usr/bin/env python3
"""Measurement choices decide the verdict — so the harness must publish them.

Source: arXiv:2611.21784, "Revisiting the Survival of Agent-Attributed Code:
How Measurement Choices Decide the Verdict" (round 130). Published studies of
how long agent-written code survives after merge disagree: retained longer,
about as long, or modified sooner. Each study's choices are defensible; the
paper measures how much those choices decide the verdict. The result is the
harness-relevant one:

  * the paper varies nine measurement choices in a specification curve of 88
    analyses, under three variance estimators, several observation windows and
    permuted labels;
  * for human-supervised code the choices change the SIZE of the effect but
    not its direction; for the fully-autonomous tier they decide the VERDICT;
  * across repositories 15 of 22 specifications report the autonomous tier
    modified SOONER when lines are treated as independent, but only 3 when
    standard errors are clustered by repository — no more than permuted labels
    produce; within repositories, no specification detects a difference;
  * the five published designs re-run on one dataset EACH change their result
    with a single choice;
  * intent classifiers: keyword rules reach kappa 0.38 against human labels,
    LLM classifiers 0.69-0.72 — and the FAMILY of classifier decides the
    verdict, not the choice among LLMs;
  * with few shared repositories, "no difference" is the absence of a
    detectable difference: the paper's interval is consistent with a 59% lower
    and a twofold higher hazard.

The lesson for a harness is not about code survival. It is that a VERDICT is
only as good as the specification that produced it, and a specification that is
never written down cannot be audited, compared, or defended. Longrun's own
harness modules make verdicts all the time (battery counts, A54 pass/fail
rows, the closure notes). This module makes the verdict's SPECIFICATION a
first-class object:

  * `specify(choice)` — record one measurement choice and its level, or refuse
    the ones the paper says decide verdicts;
  * `specifications(rows)` — the specification curve: which verdicts hold under
    every specification, and which are decided by one choice;
  * `decides(rows)` — the choice that flips a verdict (the estimator, the
    unit, the window);
  * `power(clusters, effect)` — the minimum detectable effect, so "no
    difference" is never read as "equal";
  * `classifier_family(rows)` — keyword rules versus an LLM classifier
    against human labels;
  * `checklist()` — the operationalization checklist the paper derives.

Pure: specification records in, verdict reports out. No paper number is
reproduced here.
"""
from __future__ import annotations

FORMAT = "longrun-measurement-spec/1"

# The nine measurement choices the paper names (§1).
CHOICES = ("tracking", "files-kept", "unit", "modification", "intent",
           "comparison-scope", "uncertainty", "window", "maintainer")

# The levels each choice takes in the paper's design.
LEVELS = {
    "tracking": ("identity", "location"),
    "files-kept": ("without-vendored", "with-vendored"),
    "unit": ("line", "hunk", "pr"),
    "modification": ("syntactic", "structural"),
    "intent": ("keyword", "llm"),
    "comparison-scope": ("within", "across"),
    "uncertainty": ("model-based", "clustered-pr", "clustered-repository"),
    "window": ("short", "long"),
    "maintainer": ("author", "author-and-coauthor"),
}

# The choices the paper shows deciding a verdict rather than an effect size.
VERDICT_DECIDING = ("uncertainty", "unit", "window", "intent", "tracking")

# The checklist the paper derives (Table 19), one recommendation per choice.
CHECKLIST = {
    "tracking": "follow identity rather than location, verify each "
                "modification in its diff, and report the estimate under a "
                "second tracker",
    "files-kept": "remove vendored and generated files, report line- and "
                  "PR-weighted estimates side by side, and state the share of "
                  "lines from the largest PRs",
    "unit": "report the unit and the weighting; a PR may hold a large share "
            "of the lines and dominate an estimate",
    "modification": "report modification events by type and add an "
                    "AST-structural definition as a sensitivity check",
    "intent": "prefer an LLM classifier over keyword rules when the commits "
              "are too many to label by hand, and validate it against a "
              "stratified human sample",
    "comparison-scope": "compare within repositories, stratify by repository, "
                        "and report the number of contributing repositories",
    "uncertainty": "cluster standard errors by repository in every model and "
                   "test the specification curve against permuted labels",
    "window": "report the follow-up window AND the cohort it implies, plus "
              "the estimate under a longer window",
    "maintainer": "state the unit and window of follow-up work and the "
                  "modifier rule, and report the self-modification share "
                  "separately",
}


def _num(value, default=None):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _text(value):
    return str(value or "").strip().lower()


def specify(choice, level, **extra):
    """Record one measurement choice, or refuse an unknown one."""
    key = str(choice or "").strip().lower()
    findings = []
    if key not in CHOICES:
        findings.append({"kind": "unknown-choice", "choice": choice,
                         "why": "a specification with an unnamed choice cannot "
                                "be audited"})
        return {"format": FORMAT, "choice": key, "level": level,
                "findings": findings,
                "why": "the choice is not one of the nine a post-merge study "
                       "must make"}
    value = str(level or "").strip().lower()
    allowed = LEVELS.get(key, ())
    if allowed and value not in allowed:
        findings.append({"kind": "unknown-level", "choice": key, "level": level,
                         "why": "the levels for this choice are: "
                                + ", ".join(allowed)})
    row = {"format": FORMAT, "choice": key, "level": value,
           "verdict_deciding": key in VERDICT_DECIDING, "findings": findings,
           "why": "the recommendation for this choice is: " + CHECKLIST.get(key, "")}
    if extra:
        row["params"] = {k: v for k, v in extra.items() if v is not None}
    return row


def specifications(rows):
    """The specification curve: which verdicts hold under every specification.

    `rows` — [{"spec": "s1", "choice": "uncertainty", "level": "model-based",
               "verdict": "sooner"|"longer"|"none", "significant": True}]
    """
    data = [r for r in (rows or []) if isinstance(r, dict)]
    findings = []
    verdicts = {}
    for row in data:
        key = str(row.get("spec") or "?")
        verdict = _num(row.get("verdict"))
        verdict = str(row.get("verdict") or "").lower() if verdict is None \
            else verdict
        significant = bool(row.get("significant"))
        verdicts.setdefault(verdict, []).append({"spec": key,
                                                 "significant": significant,
                                                 "choice": row.get("choice"),
                                                 "level": row.get("level")})
    for name, entries in sorted(verdicts.items()):
        sig = [e for e in entries if e["significant"]]
        verdicts[name] = {"n": len(entries), "significant": len(sig),
                           "share": round(len(sig) / len(entries), 4)
                           if entries else None}
        if sig and len(sig) < len(entries):
            minority = [e for e in entries if not e["significant"]]
            levels = sorted({str(e.get("level")) for e in minority
                             if e.get("level")})
            findings.append({"kind": "verdict-not-robust", "verdict": name,
                             "significant": len(sig), "of": len(entries),
                             "levels": levels,
                             "why": "the verdict holds only under some of the "
                                    "specifications"})
    significant_total = sum(v["significant"] for v in verdicts.values())
    if data:
        modal = max(verdicts.items(), key=lambda kv: kv[1]["significant"]) \
            if verdicts else None
        if modal and 0 < modal[1]["significant"] < len(data):
            findings.append({"kind": "verdict-not-uniform",
                             "verdict": modal[0],
                             "significant": modal[1]["significant"],
                             "of": len(data),
                             "why": "the leading verdict does not hold under "
                                    "every specification"})
    if data and significant_total / len(data) < 0.5:
        findings.append({"kind": "permuted-labels-range",
                         "why": "fewer than half the specifications are "
                                "significant; the effect is in the range that "
                                "permuted labels produce"})
    return {"format": FORMAT, "n": len(data), "verdicts": verdicts,
            "findings": findings,
            "why": "a verdict that survives every specification is a "
                   "different claim from one that survives one"}


def decides(rows):
    """The choice that flips a verdict.

    `rows` — the same rows as `specifications`, each carrying the verdict.
    """
    data = [r for r in (rows or []) if isinstance(r, dict)]
    by_choice = {}
    for row in data:
        choice = str(row.get("choice") or "").strip().lower()
        level = str(row.get("level") or "").strip().lower()
        verdict = str(row.get("verdict") or "").strip().lower()
        if not choice or not verdict:
            continue
        by_choice.setdefault((choice, level), set()).add(verdict)
    findings = []
    flipped = []
    for choice in sorted({c for c, _ in by_choice}):
        verdicts = set()
        for (c, _level), vs in by_choice.items():
            if c == choice:
                verdicts |= vs
        if len(verdicts) > 1:
            flipped.append({"choice": choice, "verdicts": sorted(verdicts)})
            findings.append({"kind": "choice-decides-the-verdict",
                             "choice": choice, "verdicts": sorted(verdicts),
                             "why": "the same data gives different verdicts "
                                    "under different levels of this choice"})
    return {"format": FORMAT, "flipped": flipped, "findings": findings,
            "why": "a disagreement between two studies is read through their "
                   "measurement choices before it is read as a difference "
                   "between the agents"}


def power(clusters, detectable_below=0.32, detectable_above=3.13):
    """The minimum detectable effect of a comparison.

    `clusters` — the number of contributing repositories (or sessions).
    `detectable_below` / `detectable_above` — the effect band the fitted
    design can actually detect. These are INPUTS from the fitted design, not
    derived here: the paper's own autonomous-tier comparison had 31 shared
    repositories and could detect only hazard ratios below 0.32 or above 3.13.

    The module reports the band of effects that stay INVISIBLE and names the
    comparison when that band swallows a moderate effect, because "no
    difference" then means "no detectable difference".
    """
    n = int(clusters or 0)
    findings = []
    if n <= 0:
        return {"format": FORMAT, "detectable": None, "findings":
                [{"kind": "no-clusters",
                  "why": "without contributing clusters no effect is detectable"}],
                "why": "the comparison has no power"}
    low = _num(detectable_below)
    high = _num(detectable_above)
    moderate_hidden = None
    if low is not None and high is not None:
        moderate_hidden = (low < 0.5 < high) or (low < 2.0 < high)
    if moderate_hidden:
        findings.append({"kind": "low-power-comparison", "clusters": n,
                         "detectable_below": low, "detectable_above": high,
                         "why": "a moderate effect (half or double the rate) "
                                "falls inside the invisible band; 'no "
                                "difference' here is the absence of a "
                                "detectable difference, not evidence of "
                                "equality"})
    return {"format": FORMAT, "clusters": n,
            "detectable_below": round(low, 4) if low is not None else None,
            "detectable_above": round(high, 4) if high is not None else None,
            "invisible_between": [low, high] if low is not None and high is not None
            else None,
            "moderate_effect_detectable": not moderate_hidden
            if moderate_hidden is not None else None,
            "findings": findings,
            "why": "report the number of clusters, the interval and the "
                   "minimum detectable effect, so 'no difference' is not read "
                   "as 'equal'"}


def classifier_family(rows):
    """Keyword rules versus an LLM classifier, against human labels.

    `rows` — [{"classifier": "keyword"|"llm", "agree": int, "n": int,
               "tier": "human-supervised"|"autonomous", "human_agrees":
               int, "human_n": int}]
    """
    data = [r for r in (rows or []) if isinstance(r, dict)]
    table = {}
    for row in data:
        family = _text(row.get("classifier"))
        agree = int(row.get("agree") or 0)
        n = int(row.get("n") or 0)
        if not family or not n:
            continue
        bucket = table.setdefault(family, {"agree": 0, "n": 0})
        bucket["agree"] += agree
        bucket["n"] += n
    findings = []
    out = {}
    for family, bucket in sorted(table.items()):
        rate = round(bucket["agree"] / bucket["n"], 4) if bucket["n"] else None
        out[family] = {"agree": bucket["agree"], "n": bucket["n"],
                        "agreement": rate}
    if "keyword" in out and "llm" in out:
        k = out["keyword"]["agreement"]
        l = out["llm"]["agreement"]
        if k is not None and l is not None and l > k:
            findings.append({"kind": "llm-family-agrees-better",
                             "keyword": k, "llm": l,
                             "why": "the FAMILY of classifier decides the "
                                    "verdict, not the choice among LLMs"})
    human = [r for r in data if r.get("human_agrees") is not None]
    if human:
        findings.append({"kind": "classifier-must-be-validated",
                         "why": "an LLM classifier may replace keyword rules "
                                "only when it is validated against human "
                                "labels"})
    return {"format": FORMAT, "classifiers": out, "findings": findings,
            "why": "the labels a classifier writes decide what the study "
                   "concludes about WHY agent code is modified"}


def checklist():
    """The operationalization checklist the paper derives."""
    return {"format": FORMAT,
            "items": [{"choice": c, "recommendation": CHECKLIST[c],
                       "verdict_deciding": c in VERDICT_DECIDING}
                      for c in CHOICES],
            "why": "a study that departs from the recommendation should say "
                   "so and report the estimate under its own choices too"}
