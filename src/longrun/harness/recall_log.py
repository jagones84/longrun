#!/usr/bin/env python3
"""Recall log — a lossless, index-free history that grep can reach.

Source: arXiv:2611.25123, "Forget Freely, Grep Later: Lossless, Index-Free Memory
for Long-Horizon LLM Agents" (round 163). An append-only plain-text log of the
complete interaction plus a regex search tool reaches 95-97% on ContextBench
(KV Store 97.4%, Log Triage 95.3%) where summarization and observation masking
stay at 6.6-20.7%, without embeddings, a retrieval index or a second model
(`grepmem_lossless_recall_2611.25123.txt:332-400`).

The log is the evidence; the search is the reader. This module is the pure half:

  * `search(text, pattern, ...)` — regex matches in chronological order with
    surrounding lines and their original locations, paginated, plus count-only.
  * `count(text, pattern)` — total matching lines, full text never returned.
  * `verify(entries, text)` — every logged interaction is present verbatim.
  * `advantage(rows)` — exact-answer accuracy by strategy, grepmem vs lossy.

Pure: log text and measurements in; findings out. The writer and the tool live in
`memory/stores.py` and `tools/tools.py`; this file never touches disk.
"""
from __future__ import annotations

import re

FORMAT = "longrun-recall-log/1"

HEADER = re.compile(r"^=== (?P<ts>[^|]+)\|(?P<role>[^|]+)\|(?P<kind>[^|]+)\|(?P<session>[^=]+)===$")


def entries(text):
    """Split a log into its header/body entries, in file order."""
    out, cur = [], None
    for line in str(text or "").splitlines():
        m = HEADER.match(line)
        if m:
            if cur is not None:
                out.append(cur)
            cur = {"ts": m.group("ts").strip(), "role": m.group("role").strip(),
                   "kind": m.group("kind").strip(), "session": m.group("session").strip(),
                   "body": []}
        elif cur is not None:
            cur["body"].append(line)
    if cur is not None:
        out.append(cur)
    for e in out:
        e["body"] = "\n".join(e["body"]).strip("\n")
    return out


def _compile(pattern, ignore_case):
    if not str(pattern or "").strip():
        return None, "empty pattern"
    try:
        return re.compile(str(pattern), re.IGNORECASE if ignore_case else 0), None
    except re.error as exc:
        return None, "invalid regex: %s" % exc


def search(text, pattern, context=2, page=1, page_size=20, max_matches=500,
           ignore_case=True, count_only=False):
    """Regex matches over the log, chronological, paginated, with locations.

    `context` is the number of lines kept on each side — the paper's recall tool
    returns surrounding context and the original location, so a match is
    evidence, not a fragment. `count_only` answers "how many" without returning
    any matched text.
    """
    rx, err = _compile(pattern, ignore_case)
    if err:
        return {"format": FORMAT, "ok": False, "error": err, "matches": []}
    lines = str(text or "").splitlines()
    hits = [i for i, line in enumerate(lines) if rx.search(line)]
    total = len(hits)
    if count_only:
        return {"format": FORMAT, "ok": True, "count": total, "lines": len(lines)}
    cap = max(1, int(max_matches))
    hits = hits[:cap]
    size = min(100, max(1, int(page_size)))
    pages = max(1, (len(hits) + size - 1) // size)
    page = min(max(1, int(page)), pages)
    start = (page - 1) * size
    window = max(0, int(context))
    out = []
    for idx in hits[start:start + size]:
        lo, hi = max(0, idx - window), min(len(lines), idx + window + 1)
        out.append({
            "line": idx + 1,
            "text": lines[idx],
            "context": lines[lo:hi],
            "context_start": lo + 1,
        })
    result = {
        "format": FORMAT, "ok": True, "pattern": str(pattern),
        "total_matches": total, "returned": len(out), "page": page,
        "pages": pages, "page_size": size, "lines": len(lines),
        "truncated": total > len(hits), "matches": out,
    }
    if total > cap:
        result["note"] = ("only the first %d matches were scanned; narrow the "
                          "pattern or use count=true" % cap)
    return result


def count(text, pattern, ignore_case=True):
    """Total matching lines, without returning their contents."""
    return search(text, pattern, count_only=True, ignore_case=ignore_case)


def verify(entries_in, log_text):
    """Every logged interaction must appear verbatim in the log.

    `entries_in` is the transcript's own list of `{role, text}` rows. A missing
    or altered body is a loss, and the log is what the agent could have grepped.
    """
    logged = entries(log_text)
    haystack = "\n".join(e["body"] for e in logged)
    missing, checked = [], 0
    for row in entries_in or ():
        body = str((row or {}).get("text") or (row or {}).get("content") or "").strip()
        if not body:
            continue
        checked += 1
        probe = body[:400]
        if probe not in haystack:
            missing.append({"role": (row or {}).get("role"),
                            "head": " ".join(probe.split())[:120]})
    return {
        "format": FORMAT,
        "lossless": not missing,
        "checked": checked,
        "logged_entries": len(logged),
        "missing": missing[:20],
        "missing_count": len(missing),
    }


def advantage(rows):
    """Exact-answer accuracy by strategy, and the gap the paper measures.

    Each row: {"strategy": "grepmem"|"summary"|"masking"|..., "task": str,
    "correct": bool}. The report leads with per-task accuracy and the mean, which
    is the number the paper's own table prints.
    """
    by = {}
    for row in rows or ():
        strat = str((row or {}).get("strategy") or "unknown")
        bucket = by.setdefault(strat, {"n": 0, "correct": 0})
        bucket["n"] += 1
        bucket["correct"] += 1 if (row or {}).get("correct") else 0
    out = {}
    for strat, b in by.items():
        out[strat] = round(b["correct"] / b["n"], 4) if b["n"] else None
    lossy = [v for k, v in out.items() if k != "grepmem" and v is not None]
    return {
        "format": FORMAT,
        "accuracy": out,
        "grepmem_lead": (round(out["grepmem"] - max(lossy), 4)
                         if out.get("grepmem") is not None and lossy else None),
        "findings": ([{"kind": "grepmem-not-best",
                       "note": "a lossy strategy matched or beat the log"}]
                     if out.get("grepmem") is not None and lossy
                     and out["grepmem"] < max(lossy) else []),
    }
