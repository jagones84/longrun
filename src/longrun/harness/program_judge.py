#!/usr/bin/env python3
"""Program judge — one readable program per topic instead of a call per document.

Source: arXiv:2611.24849, "Can Programs Replace LLM Judges? Executable Program
Judges for Scalable and Efficient Relevance Labeling" (round 149). The writer
model runs once per topic and returns programs that answer the grade questions;
the programs then label the whole pool on a CPU with no further model call
(`program_judges_2611.24849.txt:42`, `:137`).

  * **the grade scale stays outside the code**: a program answers
    `on_subject / some_answer / exact_answer / dedicated` and a fixed formula
    maps the answers to 0-3 (`:186`, `:187`).
  * **the label is the floored mean of k = 3 programs**: `l(d) = floor(mean
    g_i(d))`, and averaging removes both single-program errors and the tendency
    to grade high (`:176`, `:180`).
  * **a few labels buy most of the agreement**: four labels per topic (one per
    grade) gave +0.081 / +0.104 / +0.054, more than half of the full 16-label
    gain (`:790`, `:767`).
  * **which passages you label matters more than how many**: three BM25 top
    passages move alpha by at most 0.031 (`:336`).
  * **agreement is not ranking**: label agreement and system ranking are two
    measures, and BM25 cutoffs had the worst of both (`:421`).
  * **the cost is one-time**: $0.17-$0.49 per topic to write, and the
    break-even against a listwise judge is ~200-350 documents (`:443`, `:867`).
  * **the errors have a direction**: the classifier over-grades (25.2% of NIST
    0 passages got 2 or 3) while the unlabelled programs miss the top grade
    (10.6% of NIST 2-3 passages got 0) (`:563`, `:986`).

  * `answers(flags)` — the fixed answer-to-grade formula.
  * `consensus(grades)` — the floored mean of k programs.
  * `single(grades)` — the first program only (the averaging ablation).
  * `rubric(criteria)` — the highest level whose checks all pass.
  * `errors(rows)` — exact, two-or-more off, missed top and over-graded shares.
  * `kendall(rows)` — tau-b between a reference and a method ranking.
  * `label_gain(rows)` — how much of the gain the first four labels carry.
  * `break_even(write_cost, per_doc_cost)` — the documents where programs win.
  * `policy(source)` — the sandbox's import and call rules.
  * `audit(record)` — the seven misreadings the paper names.
  * `advise(profile)` — map a harness profile onto the paper's failure modes.

Pure: answers, grades and labels in; labels, agreement and verdicts out.
"""
from __future__ import annotations

import math
import re

FORMAT = "longrun-program-judge/1"

PROGRAMS = 3
ALLOWED = frozenset({
    "re", "math", "string", "collections", "itertools", "functools",
    "statistics", "unicodedata", "difflib", "heapq", "bisect", "typing",
    "dataclasses", "operator", "fractions", "decimal", "datetime", "calendar",
    "json", "random", "numpy", "scipy", "rapidfuzz", "rank_bm25", "sklearn",
    "sklearn_crfsuite", "dateparser", "quantulum3", "pint",
    "snowballstemmer", "pilot",
})
BANNED = ("eval(", "exec(", "open(", "subprocess", "requests", "urllib",
          "socket", "__import__", "importlib")
IMPORT_RE = re.compile(r"^[ \t]*(?:from[ \t]+([\w.]+)[ \t]+import"
                       r"|import[ \t]+([\w., \t]+))", re.MULTILINE)


def _num(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def answers(flags):
    """The fixed formula: the program decides evidence, not the scale."""
    f = flags or {}
    on_subject = bool(f.get("on_subject"))
    some_answer = bool(f.get("some_answer"))
    exact_answer = bool(f.get("exact_answer"))
    dedicated = bool(f.get("dedicated"))
    if not on_subject:
        grade = 0
    elif not some_answer:
        grade = 1
    elif exact_answer and dedicated:
        grade = 3
    else:
        grade = 2
    return {"format": FORMAT, "grade": grade,
            "answers": {"on_subject": on_subject, "some_answer": some_answer,
                        "exact_answer": exact_answer,
                        "dedicated": dedicated},
            "verdict": "graded"}


def consensus(grades):
    """The label is the floored mean of the programs' grades."""
    values = []
    for grade in grades or []:
        g = _num(grade)
        if g is not None:
            values.append(g)
    if not values:
        return {"format": FORMAT, "verdict": "no-grades"}
    mean = sum(values) / len(values)
    label = int(math.floor(mean + 1e-9))
    return {"format": FORMAT, "programs": len(values), "mean": mean,
            "label": label, "disagreement": max(values) - min(values),
            "verdict": "consensus-label"}


def single(grades):
    """The averaging ablation: use only the first program."""
    values = [_num(g) for g in (grades or [])]
    values = [g for g in values if g is not None]
    if not values:
        return {"format": FORMAT, "verdict": "no-grades"}
    return {"format": FORMAT, "label": int(math.floor(values[0] + 1e-9)),
            "verdict": "single-program"}


def rubric(criteria):
    """The highest level whose checks all pass; a failed floor gives 0."""
    levels = {}
    for row in criteria or []:
        r = row or {}
        level = r.get("level")
        if level is None:
            continue
        levels.setdefault(int(level), []).append(r.get("pass") is True)
    if not levels:
        return {"format": FORMAT, "verdict": "no-criteria"}
    if not all(levels[min(levels)]):
        return {"format": FORMAT, "grade": 0, "levels": len(levels),
                "verdict": "floor-failed"}
    passed = [level for level, checks in levels.items() if all(checks)]
    grade = max(passed) if passed else 0
    return {"format": FORMAT, "grade": grade, "levels": len(levels),
            "verdict": "rubric-graded"}


def errors(rows):
    """Exact agreement, gross error and the two directional failures."""
    exact = gross = top_missed = over_graded = 0
    diffs = []
    total = 0
    for row in rows or []:
        r = row or {}
        nist = _num(r.get("nist"))
        label = _num(r.get("label"))
        if nist is None or label is None:
            continue
        total += 1
        diff = label - nist
        diffs.append(diff)
        if diff == 0:
            exact += 1
        if abs(diff) >= 2:
            gross += 1
        if nist == 3 and label == 0:
            top_missed += 1
        if nist == 0 and label >= 2:
            over_graded += 1
    if not total:
        return {"format": FORMAT, "verdict": "no-passages"}
    return {"format": FORMAT, "passages": total, "exact": exact / total,
            "gross": gross / total, "top_missed": top_missed / total,
            "over_graded": over_graded / total,
            "mean_diff": sum(diffs) / total,
            "verdict": "errors-measured"}


def kendall(rows):
    """Kendall's tau-b between a reference ranking and a method ranking."""
    xs = []
    ys = []
    for row in rows or []:
        r = row or {}
        x = _num(r.get("reference"))
        y = _num(r.get("method"))
        if x is None or y is None:
            continue
        xs.append(x)
        ys.append(y)
    n = len(xs)
    if n < 2:
        return {"format": FORMAT, "verdict": "no-pairs"}
    concordant = discordant = 0
    for i in range(n):
        for j in range(i + 1, n):
            product = (xs[i] - xs[j]) * (ys[i] - ys[j])
            if product > 0:
                concordant += 1
            elif product < 0:
                discordant += 1

    def _tied(values):
        counts = {}
        for value in values:
            counts[value] = counts.get(value, 0) + 1
        return sum(c * (c - 1) / 2 for c in counts.values())

    joined = _tied(list(zip(xs, ys)))
    pairs = n * (n - 1) / 2
    denom = math.sqrt((pairs - _tied(xs)) * (pairs - _tied(ys)))
    tau = (concordant - discordant) / denom if denom else 0.0
    return {"format": FORMAT, "pairs": n, "tau": tau, "joint_ties": joined,
            "verdict": "ranking-agrees" if tau >= 0.80
            else "ranking-disagrees"}


def label_gain(rows):
    """How much of the full gain the first four labels carry."""
    curve = {}
    for row in rows or []:
        r = row or {}
        count = r.get("labels")
        alpha = _num(r.get("alpha"))
        if count is None or alpha is None:
            continue
        curve[int(count)] = alpha
    if 0 not in curve or len(curve) < 3:
        return {"format": FORMAT, "verdict": "incomplete-curve"}
    total = max(curve.values()) - curve[0]
    first_key = min(k for k in curve if k > 0)
    early = curve[first_key] - curve[0]
    share = early / total if total else 0.0
    return {"format": FORMAT, "first_labels": first_key, "total_gain": total,
            "early_gain": early, "share": share,
            "verdict": "most-gain-early" if share > 0.5
            else "gain-comes-late"}


def break_even(write_cost, per_doc_cost):
    """Documents per topic where a fixed write cost beats a per-doc judge."""
    write = _num(write_cost)
    per_doc = _num(per_doc_cost)
    if write is None or per_doc is None or per_doc <= 0:
        return {"format": FORMAT, "verdict": "insufficient-input"}
    documents = write / per_doc
    return {"format": FORMAT, "documents": documents,
            "cheaper_beyond": int(math.ceil(documents)),
            "verdict": "fixed-cost-wins-beyond" if documents <= 400
            else "per-document-judge-cheaper"}


def policy(source):
    """The sandbox rules: allowed imports only, no network, files or eval."""
    text = str(source or "")
    imports = []
    for match in IMPORT_RE.finditer(text):
        module = (match.group(1) or "")
        if not module and match.group(2):
            module = match.group(2).split(",")[0].strip()
        root = module.split(".")[0].strip()
        if root:
            imports.append(root)
    violations = []
    for name in sorted(set(imports)):
        if name not in ALLOWED:
            violations.append({"kind": "import", "name": name})
    for name in BANNED:
        if name in text:
            violations.append({"kind": "banned-call", "name": name})
    return {"format": FORMAT, "imports": sorted(set(imports)),
            "violations": violations,
            "verdict": "policy-ok" if not violations else "policy-violated"}


def audit(record):
    """The seven misreadings the paper names, each as a finding."""
    r = record or {}
    findings = []
    if r.get("single_program") is True:
        findings.append({"kind": "single-program",
                         "why": "one program's errors and its high grading survive"})
    if r.get("rounds_to_nearest") is True:
        findings.append({"kind": "rounds-to-nearest",
                         "why": "programs grade high, so rounding down is the unbiased rule"})
    if r.get("labels_are_bm25_top") is True:
        findings.append({"kind": "labels-are-bm25-top",
                         "why": "the top passages do not cover every grade"})
    if r.get("one_global_program") is True:
        findings.append({"kind": "one-global-program",
                         "why": "the topic-specific rules carry the agreement"})
    if r.get("no_gaming_check") is True:
        findings.append({"kind": "no-gaming-check",
                         "why": "a readable program can be tuned against"})
    if r.get("ranks_the_best_runs") is True:
        findings.append({"kind": "ranks-the-best-runs",
                         "why": "agreement over all runs does not hold over the top ten"})
    if r.get("open_weight_writer_assumed") is True:
        findings.append({"kind": "open-weight-writer-assumed",
                         "why": "a weaker writer graded too low on every collection"})
    if not findings:
        findings.append({"kind": "audit-conditions-met"})
    return {"format": FORMAT, "findings": findings, "verdict": "audit-complete"}


def advise(profile):
    """Map a harness profile onto the paper's failure modes."""
    p = profile or {}
    have = {str(k) for k, v in p.items() if v}
    checks = (
        ("writes_the_judge_once_per_topic", "judge_call_per_item",
         "a per-document judge pays for the same criteria again and again"),
        ("keeps_the_scale_outside_the_program", "program_returns_a_soft_score",
         "the fixed formula is what makes programs comparable"),
        ("averages_independent_programs", "trusts_one_program",
         "one program grades high and errs in one direction"),
        ("rounds_according_to_measured_bias", "rounds_by_convention",
         "the rounding rule should follow the programs' bias"),
        ("spends_labels_on_every_grade", "labels_the_easy_rank",
         "the labels exist to show where the grade lines are"),
        ("checks_a_second_metric_beside_agreement", "agreement_only",
         "label agreement and ranking agreement diverge"),
        ("reports_the_cost_curve", "quotes_a_single_cost",
         "the fixed cost only wins past a pool depth"),
    )
    findings = []
    for key, kind, why in checks:
        if key not in have:
            findings.append({"kind": kind, "why": why})
    return {"format": FORMAT, "findings": findings}
