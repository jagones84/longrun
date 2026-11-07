#!/usr/bin/env python3
"""Retrospective attribution for memory retrieval (MEMOIR-lite, v841).

Source: MEMOIR, arXiv:2611.07631 (2026-11-05) — a training-free memory lifecycle
whose two load-bearing ideas are (a) attribute usefulness AFTER use and (b) screen
for preservation before compression. Longrun already does (a) as a measurement:
`context_engine.usage_signal` (B-6 / v818) says which injected memories the reply
actually repeated, and the turn publishes it as `memory.use`. Nothing consumed it,
so the retrieval order stayed frozen at write-time scores.

This module closes that loop, with the same deliberate limits as the paper:
no model call, no rewrite of the append-only records, no unbounded feedback. A
small ledger (`<data>/memory_attribution.json`, keyed by `mid`) records how often
a memory was retrieved and how often it was used, and `rerank()` multiplies the
retrieval score by a BOUNDED factor, so a memory that keeps helping outranks one
that merely shares words — while staying unable to bury a clearly more relevant
memory, or to entrench a favourite that stopped being useful.

Deterministic, stdlib only.
"""
import json
import os
import threading

from longrun.util.paths import DATA_DIR

#: The evidence is a word-overlap heuristic (`usage_signal`), not proof of use, so
#: the weight it can move is small on purpose: the largest possible inversion is
#: 1.15/0.90 = 1.28x, so a memory that is clearly more relevant still wins.
WEIGHT = 0.30
#: A memory with a long help history cannot be pushed further than this, and an
#: unused one cannot be buried further than the floor: retrieval stays relevant.
CEIL, FLOOR = 1.15, 0.90
#: Below this many retrievals one observation is noise, so no memory is adjusted
#: on a single turn.
MIN_USES = 2

_lock = threading.Lock()


def _file():
    return os.environ.get("LONGRUN_MEMORY_ATTRIBUTION") or os.path.join(
        DATA_DIR, "memory_attribution.json")


def _load():
    try:
        with open(_file(), "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _save(data):
    path = _file()
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False, sort_keys=True)
        os.replace(tmp, path)
    except OSError:
        pass


def note(injected, used, ts=None):
    """Record one turn's evidence: `injected` ids, and the subset `used`.

    Returns the ledger entry written (or None when there was nothing to record).
    A memory that was retrieved and NOT used is evidence too — that is what lets
    a stale favourite decay instead of holding its write-time rank forever.
    """
    ids = [str(m).strip() for m in (injected or []) if str(m or "").strip()]
    if not ids:
        return None
    hit = {str(m).strip() for m in (used or []) if str(m or "").strip()}
    import time
    now = float(ts if ts is not None else time.time())
    with _lock:
        data = _load()
        for mid in ids:
            rec = data.get(mid)
            if not isinstance(rec, dict):
                rec = {"uses": 0, "helped": 0}
            rec["uses"] = int(rec.get("uses") or 0) + 1
            if mid in hit:
                rec["helped"] = int(rec.get("helped") or 0) + 1
                rec["last_helped"] = round(now, 3)
            data[mid] = rec
        data["_total"] = int(data.get("_total") or 0) + len(ids)
        _save(data)
    return {mid: data.get(mid) for mid in ids}


def stats(mid):
    """The evidence for one memory: {'uses': n, 'helped': k, ...} (may be empty)."""
    rec = _load().get(str(mid or "").strip())
    return dict(rec) if isinstance(rec, dict) else {}


def table(prefix=""):
    """Every record whose id starts with `prefix`, in ONE read (HA-2).

    `stats()` above reads the file per id; a caller that needs the whole ledger
    (the skills discovery report) must not load it once per skill. Read-only.
    """
    want = str(prefix or "")
    return {k: dict(v) for k, v in _load().items()
            if isinstance(v, dict) and str(k).startswith(want)}


def boost(mid, data=None):
    """Retrieval multiplier in [FLOOR, CEIL]; exactly 1.0 with no evidence.

    No evidence must mean "no change": a bonus for never-retrieved memories would
    apply to every new memory at once and therefore change no ordering (MEMOIR's
    UCB exploration term needs a per-arm count that Longrun does not have).
    """
    data = data if isinstance(data, dict) else _load()
    rec = data.get(str(mid or "").strip())
    if not isinstance(rec, dict):
        return 1.0
    uses = int(rec.get("uses") or 0)
    helped = int(rec.get("helped") or 0)
    if uses < MIN_USES:
        return 1.0
    rate = max(0.0, min(1.0, helped / float(uses)))
    factor = 1.0 + WEIGHT * (rate - 0.5)
    return round(max(FLOOR, min(CEIL, factor)), 4)


def rerank(items):
    """Order retrieval hits by `score * boost(mid)`, loading the ledger once.

    The multiplier is applied to whichever score actually orders the list — the
    cross-encoder's `relevance` when it ran, the fused `score` otherwise — and the
    result is WRITTEN BACK, so the number the prompt and the UI show is the number
    that ordered the memories (never a displayed score that disagrees with the
    order). The factor itself is kept under `attribution`.
    """
    if not items:
        return items
    data = _load()
    scored = []
    for h in items:
        key = "relevance" if h.get("relevance") is not None else "score"
        base = float(h.get(key) or 0.0)
        factor = boost(h.get("mid"), data)
        if factor != 1.0:
            h = dict(h, **{key: round(base * factor, 4), "attribution": factor})
        scored.append((base * factor, h))
    scored.sort(key=lambda kv: kv[0], reverse=True)
    return [h for _s, h in scored]
