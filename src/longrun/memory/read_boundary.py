#!/usr/bin/env python3
"""Memory read boundary — coherent evidence from several reads, or refuse.

Source: arXiv:2611.19264, "Read Boundaries in Agent Memory: Consistency,
Completeness, and Repair" (round 114). A memory service assembles one answer from
several reads; an update between those reads pairs an assertion with source
content from another revision. The paper compares unprotected recall, a repeated
recall, a read/write lock and OPTIMISTIC EPOCH VALIDATION. Both protected
policies delivered complete, compatible evidence; on failure both REFUSE service,
and the first default retry recovers through a full-rebuild fallback.

This module is the deterministic read boundary:

  * `validate(reads, expected_epoch=None)` — every read must report the same
    epoch (and, when the caller names one, that epoch);
  * `recall(reader, attempts=2)` — optimistic validation with a bounded retry;
    after the last mismatch the service is `refused` (never a silently mixed
    evidence set);
  * `recall_with_rebuild(reader, rebuild)` — the paper's recovery path: one
    full rebuild, then re-read, and the result says it was rebuilt.

Pure: reads in, verdict out; nothing reads a store by itself.
"""
from __future__ import annotations

FORMAT = "longrun-read-boundary/1"


def validate(reads, expected_epoch=None):
    rows = [r for r in (reads or ()) if isinstance(r, dict)]
    if not rows:
        return {"format": FORMAT, "consistent": False, "reason": "no-reads",
                "epochs": [], "action": "retry", "evidence": []}
    epochs = {r.get("epoch") for r in rows}
    evidence = [{"key": r.get("key"), "epoch": r.get("epoch")} for r in rows]
    if len(epochs) > 1:
        return {"format": FORMAT, "consistent": False, "reason": "mixed-epochs",
                "epochs": sorted(str(e) for e in epochs), "action": "retry",
                "evidence": evidence}
    epoch = next(iter(epochs))
    if expected_epoch is not None and epoch != expected_epoch:
        return {"format": FORMAT, "consistent": False, "reason": "stale-epoch",
                "epochs": [str(epoch)], "expected": expected_epoch,
                "action": "retry", "evidence": evidence}
    return {"format": FORMAT, "consistent": True, "reason": "single-epoch",
            "epoch": epoch, "epochs": [str(epoch)], "action": "serve",
            "evidence": evidence}


def recall(reader, attempts=2, expected_epoch=None):
    """Run the caller's reader and validate; refuse rather than mix epochs."""
    last = None
    for attempt in range(max(1, int(attempts))):
        try:
            reads = reader()
        except Exception as exc:  # a failing read is not evidence
            last = {"format": FORMAT, "consistent": False, "reason": "read-error",
                    "detail": str(exc)[:200], "action": "retry", "evidence": []}
            continue
        last = validate(reads, expected_epoch)
        if last["consistent"]:
            last.update({"service": "served", "attempt": attempt + 1})
            return last
    last.update({"service": "refused", "attempt": int(attempts)})
    return last


def recall_with_rebuild(reader, rebuild, attempts=2, expected_epoch=None):
    """On refusal, rebuild once (the paper's full-rebuild fallback) and re-read."""
    res = recall(reader, attempts=attempts, expected_epoch=expected_epoch)
    if res.get("service") == "served":
        return res
    try:
        rebuild()
    except Exception as exc:
        res["rebuild_error"] = str(exc)[:200]
        return res
    again = recall(reader, attempts=1, expected_epoch=expected_epoch)
    again["rebuilt"] = True
    again["first_refusal"] = res.get("reason")
    return again
