#!/usr/bin/env python3
"""Guideline budget — the right dose is a property of the model, not the memory.

Source: arXiv:2611.26361, "How Much Should an Agent Remember? Deployment Lessons
from Self-Distilled Memory for LLM Agents" (round 163). A strong model keeps
improving as guidelines are added (DeepSeek-V3.2 +9.5 TGC with 191 guidelines);
a weak model gains less from the full set than from ~29 selected ones (gpt-oss:
51.2% at 199 vs 55.4% at ~29) — too much memory is a SILENT failure, because the
agent just does worse (`agent_memory_guideline_budget_2611.26361.txt:126-190`).

  * `consolidate(lessons)` — support-conserving merge: every guideline records
    how many lessons it merged, the evidence polarity, and the source tasks. The
    invariant `sum(support) == len(lessons)` is enforced, not assumed.
  * `dose(guidelines, capability)` — the delivery dose: strong models get
    everything, weak models a selected subset, unknown models a conservative
    high-support core plus a bounded tail.
  * `audit(record)` — the paper's deployment checks: conservation, provenance
    survival, the store actually growing, and support not read as correctness.

Pure: lessons/records in; guidelines and findings out. The paper's own code path
(altk-evolve) is an external library; this is the deterministic policy longrun
can hold without a training loop.
"""
from __future__ import annotations

import hashlib
import re

FORMAT = "longrun-guideline-budget/1"

POLARITIES = ("success", "failure", "both")


def _norm(text):
    return " ".join(re.sub(r"[^\w\s]", " ", str(text or "").lower()).split())


def _cluster_key(lesson):
    """Stable cluster key: an explicit cluster, else the normalised lesson text."""
    explicit = str((lesson or {}).get("cluster") or "").strip().lower()
    if explicit:
        return explicit
    norm = _norm((lesson or {}).get("text"))
    return hashlib.sha1(norm.encode("utf-8")).hexdigest()[:12] if norm else ""


def consolidate(lessons):
    """Merge lessons into guidelines, conserving support and provenance.

    Lessons with no text are dropped (they carry no instruction); a lesson the
    caller does not cluster keeps its own key, so it survives verbatim as a
    support-1 guideline — the paper's long tail is the value, not noise.
    """
    rows = [l for l in (lessons or []) if isinstance(l, dict) and str(l.get("text") or "").strip()]
    groups = {}
    for lesson in rows:
        key = _cluster_key(lesson)
        if not key:
            continue
        g = groups.setdefault(key, {"text": str(lesson.get("text")).strip(),
                                    "support": 0, "sources": [], "polarity": set()})
        g["support"] += 1
        src = str(lesson.get("source_task") or lesson.get("source") or "").strip()
        if src and src not in g["sources"]:
            g["sources"].append(src)
        pol = str(lesson.get("outcome") or lesson.get("polarity") or "").strip().lower()
        if pol in ("success", "failure"):
            g["polarity"].add(pol)
    out = []
    for key, g in groups.items():
        pol = ("both" if len(g["polarity"]) > 1
               else (next(iter(g["polarity"])) if g["polarity"] else "both"))
        out.append({"key": key, "text": g["text"], "support": g["support"],
                    "polarity": pol, "sources": list(g["sources"])})
    out.sort(key=lambda r: (-r["support"], r["key"]))
    conserved = sum(r["support"] for r in out)
    return {
        "format": FORMAT,
        "guidelines": out,
        "lessons": len(rows),
        "conserved": conserved,
        "lossless": conserved == len(rows),
        "findings": ([] if conserved == len(rows) else
                     [{"kind": "support-not-conserved",
                       "note": "%d of %d lessons reached a guideline" %
                               (conserved, len(rows))}]),
    }


def dose(guidelines, capability="unknown", core_support=3, weak_fraction=0.15,
         weak_min=8, weak_max=32, unknown_cap=24):
    """How many guidelines to inject for this model capability.

    `strong` keeps the whole set (the paper's strong-model curve is monotone);
    `weak` gets the high-support core plus a fraction of the tail, because the
    full set makes a weak model do WORSE without any error; `unknown` gets the
    conservative retrieval default the paper ships (core + a bounded tail).
    """
    rows = [g for g in (guidelines or []) if isinstance(g, dict)]
    rows = sorted(rows, key=lambda g: (-int(g.get("support") or 0), str(g.get("text") or "")))
    n = len(rows)
    cap = capability if capability in ("strong", "weak", "unknown") else "unknown"
    if not n:
        return {"format": FORMAT, "capability": cap, "count": 0, "selected": 0,
                "n": 0, "findings": [{"kind": "no-guidelines"}]}
    core = [g for g in rows if int(g.get("support") or 0) >= max(1, int(core_support))]
    tail = [g for g in rows if g not in core]
    if cap == "strong":
        chosen = rows
    elif cap == "weak":
        k = int(round(float(weak_fraction) * n))
        k = max(int(weak_min), min(int(weak_max), k))
        target = max(len(core), min(n, k))
        chosen = (core + tail)[:target]
    else:
        target = max(len(core), min(n, int(unknown_cap)))
        chosen = (core + tail)[:target]
    return {
        "format": FORMAT,
        "capability": cap,
        "n": n,
        "count": len(chosen),
        "core": len(core),
        "selected": chosen,
        "findings": ([{"kind": "capability-unknown",
                       "note": "a model with no measured dose gets the conservative "
                               "core+tail default; the full set can silently hurt a "
                               "weak model"}] if cap == "unknown" else []),
    }


def audit(record):
    """The paper's deployment checks, from one pipeline record.

    `record`: {"lessons": int, "guidelines": [...], "store_before": int,
    "store_after": int, "calls": int, "downstream_fields": [...]}. A missing
    field that a downstream stage ranks on is a provenance loss; a store that
    did not grow while the run reported success is a silently read-only path.
    """
    rec = record or {}
    rows = [g for g in (rec.get("guidelines") or []) if isinstance(g, dict)]
    support = sum(int(g.get("support") or 0) for g in rows)
    try:
        lessons = int(rec.get("lessons") or 0)
    except (TypeError, ValueError):
        lessons = 0
    before = rec.get("store_before")
    after = rec.get("store_after")
    calls = rec.get("calls")
    findings = []
    if lessons and support != lessons:
        findings.append({"kind": "support-not-conserved",
                         "note": "%d lessons -> %d support" % (lessons, support)})
    ranked = [str(f) for f in (rec.get("downstream_fields") or [])
              if str(f) not in ("support", "sources", "polarity")]
    if ranked:
        findings.append({"kind": "provenance-loss",
                         "note": "a downstream stage ranks on %s; every upstream stage "
                                 "must preserve it" % ", ".join(ranked)})
    if before is not None and after is not None and int(after) <= int(before):
        findings.append({"kind": "store-did-not-grow",
                         "note": "memory was read but never written — the write path "
                                 "failed silently"})
    if calls is not None and int(calls) <= 0:
        findings.append({"kind": "no-model-calls",
                         "note": "a run that made no call cannot have learned"})
    top = max(rows, key=lambda g: int(g.get("support") or 0)) if rows else None
    if top and int(top.get("support") or 0) >= 5 and str(top.get("polarity")) == "failure":
        findings.append({"kind": "high-support-failure",
                         "note": "the most recurrent lesson came from failures; "
                                 "support is recurrence, not correctness"})
    return {
        "format": FORMAT,
        "lessons": lessons,
        "guidelines": len(rows),
        "support": support,
        "lossless": (not findings) or all(f["kind"] != "support-not-conserved" for f in findings),
        "findings": findings,
    }
