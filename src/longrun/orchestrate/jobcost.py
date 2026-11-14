#!/usr/bin/env python3
"""Per-job delegation cost: one append-only row per delegated turn (R6).

The run ledger already knows what a TURN cost (`model.runmetrics`: tokens and
seconds) and `model.costs` owns the priced half (USD). Neither is keyed by the
ORBIT job a turn belongs to, so "dispatch or subagent?" was decided blind.

This module adds the ONE aggregate the routing decision needs, keyed by job id:
`{tokens, usd, seconds, turns, sessions}`. It stores one small JSON line per
delegated turn and never touches the turn path: a failure here is swallowed by
the caller, so a broken ledger cannot fail a job.
"""
import json
import os
import threading
import time

from longrun.util import paths

LEDGER = os.environ.get("LONGRUN_JOBCOST_FILE") or os.path.join(
    paths.DATA_DIR, "job_costs.jsonl")
_LOCK = threading.Lock()


def record(job, session=None, tokens=None, usd=None, seconds=None):
    """Append ONE delegated turn. Missing numbers stay absent (never 0)."""
    jid = str(job or "").strip()
    if not jid:
        return None
    row = {"ts": round(time.time(), 3), "job": jid,
           "session": str(session or "")}
    for key, value in (("tokens", tokens), ("usd", usd), ("seconds", seconds)):
        if value is None:
            continue
        try:
            row[key] = round(float(value), 6) if key == "usd" else int(value)
        except (TypeError, ValueError):
            continue
    try:
        os.makedirs(os.path.dirname(LEDGER), exist_ok=True)
        with _LOCK:
            with open(LEDGER, "a", encoding="utf-8") as f:
                f.write(json.dumps(row, sort_keys=True) + "\n")
    except OSError:
        return None
    return row


def _rows():
    try:
        with open(LEDGER, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except ValueError:
                    continue
                if isinstance(row, dict) and row.get("job"):
                    yield row
    except OSError:
        return


def aggregate(job):
    """The cost of one job: tokens, usd, seconds, turns, sessions.

    `usd` is None when no row was priced — never a fake 0 (the same rule the
    cost ledger and the run record already follow).
    """
    jid = str(job or "").strip()
    out = {"job": jid, "tokens": 0, "usd": None, "seconds": 0.0,
           "turns": 0, "sessions": []}
    usd = 0.0
    priced = 0
    sessions = set()
    for row in _rows():
        if row.get("job") != jid:
            continue
        out["turns"] += 1
        out["tokens"] += int(row.get("tokens") or 0)
        out["seconds"] = round(out["seconds"] + float(row.get("seconds") or 0), 3)
        if row.get("session"):
            sessions.add(str(row["session"]))
        if row.get("usd") is not None:
            priced += 1
            usd += float(row.get("usd") or 0)
    out["usd"] = round(usd, 6) if priced else None
    out["sessions"] = sorted(sessions)
    return out
