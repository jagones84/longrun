#!/usr/bin/env python3
"""Verification transport — does the evidence survive compaction?

Source: arXiv:2611.18471, "Do Verifier Judgments Survive Abstraction? Measuring
Verification Transport for LLM Agent Evaluation" (round 108). Its measurement:
a verifier that is correct on the native trajectory fails to reach the same
judgment on an ABSTRACTED view (compacted history, delegation boundary) in about
31% of cases; restoring the execution provenance recovers 85.5% of those
failures. Native-view accuracy alone therefore says nothing about reliability
once the evidence crosses an abstraction boundary.

Longrun compacts aggressively (`model/context_engine.compact`) and its
close-out/verify gates read the surviving transcript. This module measures the
same thing on longrun's own record: which decisive evidence items (exit codes,
error classes, paths) are present before compaction and still readable after it,
and what a restoration block must re-inject.

Pure: strings and message dicts in, dicts out. `compact` is called on a COPY.
"""
from __future__ import annotations

import re

FORMAT = "longrun-verification-transport/1"
MAX_ITEMS = 40

_EXIT = re.compile(r"(?i)\bexit(?:[_ ]?code)?\s*[=:]\s*(-?\d+)\b")
_ERROR = re.compile(r"\b([A-Z][A-Za-z0-9]{2,}(?:Error|Exception|Timeout))\b")
_FAIL = re.compile(r"(?i)\b(FAILED|FAILURE|DENIED|REFUSED|TIMEOUT)\b")
_PATH = re.compile(r"(?<![\w/])(/(?:[\w.@+-]+/)*[\w.@+-]+)")


def evidence(text):
    """`{kind: [values]}` for the decisive items a verifier would cite."""
    s = str(text or "")
    # URLs are not filesystem evidence: a verifier cannot open them offline.
    s = re.sub(r"\w+://\S+", " ", s)
    out = {"exit": [], "error": [], "flag": [], "path": []}
    for cap in _EXIT.findall(s):
        out["exit"].append(str(int(cap)))
    for cap in _ERROR.findall(s):
        out["error"].append(cap)
    for cap in _FAIL.findall(s):
        out["flag"].append(cap.upper())
    for cap in _PATH.findall(s):
        if len(cap) > 3:
            out["path"].append(cap)
    return {k: sorted(set(v))[:MAX_ITEMS] for k, v in out.items() if v}


def _text_of(messages):
    parts = []
    for m in messages or []:
        if isinstance(m, dict):
            parts.append(str(m.get("content") or ""))
    return "\n".join(parts)


def transport(native, abstracted):
    """Which native evidence items are still present in the abstracted text."""
    if isinstance(native, str):
        native = evidence(native)
    else:
        native = native if isinstance(native, dict) else {}
    shown = str(abstracted or "")
    kept, missing = 0, []
    for kind, values in native.items():
        for value in values:
            if value in shown:
                kept += 1
            else:
                missing.append({"kind": kind, "value": value})
    total = kept + len(missing)
    return {"format": FORMAT, "total": total, "kept": kept,
            "fidelity": round(kept / float(total), 4) if total else 1.0,
            "missing": missing[:MAX_ITEMS]}


def restore_block(missing, limit=20):
    """The compact provenance block that recovers a transport failure."""
    items = list(missing or [])[:limit]
    if not items:
        return ""
    lines = ["PROVENANCE (restored from the native trajectory — cite these, do not infer):"]
    for item in items:
        lines.append("- %s: %s" % (item.get("kind"), item.get("value")))
    if len(missing or []) > limit:
        lines.append("- (%d more in the full record)" % (len(missing) - limit))
    return "\n".join(lines)


def audit_messages(messages, budget_tokens=4000, keep_recent=None, summarizer=None):
    """Compact a COPY of `messages` and report what the abstraction lost."""
    from longrun.model import context_engine
    native_text = _text_of(messages)
    kwargs = {"force": True}
    if keep_recent is not None:
        kwargs["keep_recent"] = keep_recent
    if summarizer is not None:
        kwargs["summarizer"] = summarizer
    compacted, stats = context_engine.compact(list(messages or []), budget_tokens,
                                              **kwargs)
    abstracted = _text_of(compacted)
    res = transport(evidence(native_text), abstracted)
    res["stats"] = {k: stats.get(k) for k in
                    ("input_messages", "input_tokens", "compacted", "kept")}
    res["restore"] = restore_block(res["missing"])
    return res
