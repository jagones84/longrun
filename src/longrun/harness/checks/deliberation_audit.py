#!/usr/bin/env python3
"""Deliberation audit — a generic summary can hide a missing design judgement.

Source: arXiv:2611.22905, "Think Before You Code" (round 137). Code models are
scored on whether the patch works; this benchmark scores whether the reasoning
around a real issue names the same engineering artifacts a human discussion
does (`think_before_code_deliberation_2611.22905.md:28`, `:34`).

  * **the unit is a typed artifact**: type, summary, tags and fixed metadata
    fields, with 31 types and 81 allowed tags (`:88`, `:90`).
  * **metadata is the gap**: even the best model scores below 0.2 metadata F1
    while summary similarity reaches 0.86 BERTScore (`:262`, `:282`).
  * **design choice blindness**: problem and proposed solution are found, while
    trade-off and design-decision artifacts are the weakest (`:254`).
  * **grounding dominates**: with no code context Type F1 collapses to 0.11 and
    BERTScore to 0.15-0.22 (`:298`).
  * **BM25 trades structure for meaning**: keyword retrieval raises Type/Tag F1
    but lowers summary quality, which is why the pipeline keeps hybrid RRF
    (`:298`, `:302`).
  * **coverage must gate quality**: a summary is penalised by coverage recall so
    a model cannot win by covering a narrow slice (`:240`).

  * `artifact(row)` — one typed artifact against the schema.
  * `match(gold, model)` — type precision/recall/F1 and coverage.
  * `tags(gold, model)` — tag F1 on matched types.
  * `metadata(gold, model)` — greedy one-to-one hard and soft F1.
  * `summary(score, coverage_recall)` — coverage-penalised summary quality.
  * `ablation(rows)` — the four settings and what each buys.
  * `audit(record)` — generic summaries, missing design choices, no grounding.
  * `advise(profile)` — map a harness profile onto the paper's failure modes.

Pure: structured artifacts and metric rows in; findings out.
"""
from __future__ import annotations

import re

FORMAT = "longrun-deliberation-audit/1"

TYPES = (
    "problem statement", "proposed solution", "alternative solution", "design decision",
    "trade off argument", "rationale", "constraint", "assumption", "implementation detail",
    "code snippet", "algorithm approach", "api design", "data structure choice",
    "configuration choice", "benchmark result", "performance claim", "test case",
    "bug reproduction steps", "edge case", "empirical evidence", "question",
    "answer clarification", "agreement", "disagreement", "suggestion", "critique",
    "task assignment", "status update", "priority discussion", "blocking issue", "dependency",
)

META_KEYS = {
    "problem statement": ("problem kind", "affected area", "user or system impact"),
    "proposed solution": ("solution kind", "target area", "expected benefit"),
    "design decision": ("decision status", "chosen option", "rejected options"),
    "trade off argument": ("options compared", "comparison axes", "preferred option"),
    "rationale": ("supports artifact type", "reasoning kind", "impact scope"),
    "constraint": ("constraint type", "scope", "severity"),
    "blocking issue": ("blocker type", "blocking target", "unblock condition"),
}

GENERIC = ("improve", "fix the issue", "better", "various", "some changes", "update code")


def _text(value):
    return str(value).strip() if value is not None else ""


def _tokens(text):
    return [t for t in re.findall(r"[a-z0-9]+", _text(text).lower()) if t]


def _f1(hit, predicted, gold):
    precision = hit / predicted if predicted else 0.0
    recall = hit / gold if gold else 0.0
    if precision + recall == 0:
        return 0.0, precision, recall
    return 2 * precision * recall / (precision + recall), precision, recall


def artifact(row):
    """One artifact against the schema: a known type, tags and its fixed fields."""
    r = row or {}
    kind = _text(r.get("type")).lower()
    findings = []
    if kind not in TYPES:
        findings.append({"kind": "unknown-type", "type": r.get("type")})
    tags = [_text(t).lower() for t in (r.get("tags") or ())]
    if not tags:
        findings.append({"kind": "no-tags"})
    if any(not re.fullmatch(r"[a-z0-9]+(_[a-z0-9]+)*", t) for t in tags):
        findings.append({"kind": "tag-not-snake-case"})
    summary = _text(r.get("summary"))
    if not summary:
        findings.append({"kind": "no-summary"})
    elif any(g in summary.lower() for g in GENERIC):
        findings.append({"kind": "generic-summary",
                         "why": "a summary must name the subject, the event and a detail"})
    meta = r.get("metadata") or {}
    required = META_KEYS.get(kind, ())
    missing = [k for k in required if not _text(meta.get(k))]
    if required and missing:
        findings.append({"kind": "metadata-missing", "fields": missing})
    if required and set(meta) - set(required):
        findings.append({"kind": "metadata-extra-keys",
                         "keys": sorted(set(meta) - set(required))})
    if not findings:
        findings.append({"kind": "artifact-valid", "type": kind})
    return {"format": FORMAT, "type": kind, "findings": findings}


def match(gold_types, model_types):
    """Type precision, recall and F1 over the artifact types present."""
    g = {_text(t).lower() for t in (gold_types or ())}
    m = {_text(t).lower() for t in (model_types or ())}
    if not g or not m:
        return {"format": FORMAT, "findings": [{"kind": "empty-side"}]}
    hit = len(g & m)
    f1, precision, recall = _f1(hit, len(m), len(g))
    findings = []
    if not f1:
        findings.append({"kind": "no-type-overlap"})
    elif recall < 0.5:
        findings.append({"kind": "types-missed", "recall": round(recall, 4)})
    else:
        findings.append({"kind": "types-matched", "f1": round(f1, 4)})
    return {"format": FORMAT, "precision": round(precision, 4), "recall": round(recall, 4),
            "f1": round(f1, 4), "covered": sorted(g & m), "findings": findings}


def tags(gold, model):
    """Tag agreement within a matched type."""
    g = {_text(t).lower() for t in (gold or ())}
    m = {_text(t).lower() for t in (model or ())}
    if not g or not m:
        return {"format": FORMAT, "findings": [{"kind": "empty-tag-set"}]}
    f1, precision, recall = _f1(len(g & m), len(m), len(g))
    return {"format": FORMAT, "precision": round(precision, 4), "recall": round(recall, 4),
            "f1": round(f1, 4), "findings": []}


def _similarity(a, b):
    ta, tb = _tokens(a), _tokens(b)
    if not ta or not tb:
        return 0.0
    hit = len(set(ta) & set(tb))
    f1, _, _ = _f1(hit, len(set(tb)), len(set(ta)))
    return f1


def metadata(gold, model, threshold=0.82):
    """Greedy one-to-one metadata matching, hard at a threshold plus soft scores."""
    g = list(gold or ())
    m = list(model or ())
    if not g or not m:
        return {"format": FORMAT, "findings": [{"kind": "empty-metadata"}]}
    pairs = []
    for i, gv in enumerate(g):
        for j, mv in enumerate(m):
            pairs.append((_similarity(gv, mv), i, j))
    pairs.sort(reverse=True)
    used_g, used_m = set(), set()
    kept = []
    for score, i, j in pairs:
        if i in used_g or j in used_m:
            continue
        used_g.add(i)
        used_m.add(j)
        kept.append(score)
    hard = sum(1 for s in kept if s >= float(threshold))
    hard_f1, hard_precision, hard_recall = _f1(hard, len(m), len(g))
    soft_recall = sum(kept) / len(g)
    soft_precision = sum(kept) / len(m)
    soft_f1 = (0.0 if soft_precision + soft_recall == 0
               else 2 * soft_precision * soft_recall / (soft_precision + soft_recall))
    findings = []
    if hard_f1 < 0.2:
        findings.append({"kind": "metadata-gap", "hard_f1": round(hard_f1, 4),
                         "why": "the type is right but its fields are generic or wrong"})
    elif hard_f1 > 0.6:
        findings.append({"kind": "metadata-matched", "hard_f1": round(hard_f1, 4)})
    return {"format": FORMAT, "hard_f1": round(hard_f1, 4),
            "hard_precision": round(hard_precision, 4), "hard_recall": round(hard_recall, 4),
            "soft_f1": round(soft_f1, 4), "findings": findings}


def summary(score, coverage_recall):
    """Coverage-penalised summary quality: quality times coverage."""
    q = _num(score)
    c = _num(coverage_recall)
    if q is None or c is None or not 0 <= q <= 1 or not 0 <= c <= 1:
        return {"format": FORMAT, "findings": [{"kind": "invalid-score"}]}
    adjusted = q * c
    findings = []
    if c < 0.5:
        findings.append({"kind": "narrow-coverage", "coverage": round(c, 4),
                         "why": "similar summaries over a narrow slice are not deliberation"})
    if q > 0.8 and adjusted < 0.5:
        findings.append({"kind": "generic-summary", "raw": round(q, 4),
                         "adjusted": round(adjusted, 4)})
    elif not findings:
        findings.append({"kind": "summary-evidence", "adjusted": round(adjusted, 4)})
    return {"format": FORMAT, "raw": round(q, 4), "adjusted": round(adjusted, 4),
            "findings": findings}


def _num(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def ablation(rows):
    """What each setting buys: grounding, labels, or meaning."""
    data = [r for r in (rows or ()) if _num(r.get("type_f1")) is not None]
    if not data:
        return {"format": FORMAT, "findings": [{"kind": "no-rows"}]}
    by_setting = {}
    for r in data:
        by_setting.setdefault(str(r.get("setting")), []).append(r)
    findings = []
    orig = by_setting.get("orig") or []
    noctx = by_setting.get("noctx") or []
    bm25 = by_setting.get("bm25") or []
    few = by_setting.get("few") or []

    def mean(rows, key):
        vals = [_num(r.get(key)) for r in rows if _num(r.get(key)) is not None]
        return sum(vals) / len(vals) if vals else None

    if orig and noctx:
        o, n = mean(orig, "type_f1"), mean(noctx, "type_f1")
        if o is not None and n is not None and n < 0.5 * o:
            findings.append({"kind": "grounding-required", "orig": round(o, 4),
                             "noctx": round(n, 4)})
    if orig and bm25:
        ot, bt = mean(orig, "type_f1"), mean(bm25, "type_f1")
        os_, bs = mean(orig, "summary"), mean(bm25, "summary")
        if bt is not None and ot is not None and bs is not None and os_ is not None:
            if bt > ot and bs < os_:
                findings.append({"kind": "keyword-trades-meaning",
                                 "type_gain": round(bt - ot, 4),
                                 "summary_loss": round(os_ - bs, 4)})
    if orig and few:
        ft, fs = mean(few, "tag_f1"), mean(few, "summary")
        ot, os_ = mean(orig, "tag_f1"), mean(orig, "summary")
        if ft is not None and ot is not None and ft > ot and (fs is None or os_ is None
                                                              or fs <= os_ + 0.01):
            findings.append({"kind": "few-shot-labels-only",
                             "tag_gain": round(ft - ot, 4)})
    if not findings:
        findings.append({"kind": "no-ablation-effect"})
    return {"format": FORMAT, "settings": sorted(by_setting), "findings": findings}


def audit(record):
    """Does the reasoning space include the decisions, and is the summary grounded?"""
    r = record or {}
    findings = []
    present = {_text(t).lower() for t in (r.get("types") or ())}
    for needed in ("trade off argument", "design decision"):
        if needed not in present:
            findings.append({"kind": "design-choice-missing", "type": needed})
    meta = _num(r.get("metadata_f1"))
    summ = _num(r.get("summary_score"))
    if meta is not None and summ is not None and summ > 0.8 and meta < 0.2:
        findings.append({"kind": "structure-missing-under-similar-summary",
                         "metadata": meta, "summary": summ})
    if r.get("grounded") is False:
        findings.append({"kind": "ungrounded-reasoning",
                         "why": "without repository context the artifact space collapses"})
    if not findings:
        findings.append({"kind": "deliberation-audited"})
    return {"format": FORMAT, "findings": findings}


def advise(profile):
    """Map a harness profile onto the paper's failure modes."""
    p = profile or {}
    have = {str(key) for key, value in p.items() if value}
    findings = []
    checks = (
        ("records_artifact_types", "untagged-reasoning", "name the kind of each judgement"),
        ("fills_metadata", "generic-fields", "the fields are what distinguish two trade-offs"),
        ("covers_tradeoffs", "design-choice-blind", "trade-offs and decisions are the hard part"),
        ("grounds_in_code", "no-code-context", "reasoning without the repository collapses"),
        ("uses_hybrid_retrieval", "keyword-only", "BM25 finds names, dense finds intent"),
        ("penalises_by_coverage", "narrow-coverage", "quality over a small slice is not coverage"),
        ("separates_type_and_summary", "single-score", "labels and meaning fail independently"),
        ("checks_ablation", "unablated", "each component must earn its place"),
    )
    for key, kind, why in checks:
        if key not in have:
            findings.append({"kind": kind, "why": why})
    return {"format": FORMAT, "findings": findings}
