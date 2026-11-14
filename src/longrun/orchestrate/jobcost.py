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


# --- S2 (2026-11-15): backward feedback propagation ---

_FEEDBACK_FILE = os.environ.get("LONGRUN_FEEDBACK_FILE") or os.path.join(
    paths.DATA_DIR, "job_feedback.jsonl")
_FEEDBACK_LOCK = threading.Lock()


def record_feedback(jid, agent_id, summary, details=None):
    """Append one per-agent feedback record after job completion.

    Called from `jobs.py:_propagate_feedback` after the backward DAG pass.
    The record is keyed by job id + agent session id so the optimizer (S1) can
    look up downstream consequences of a specific agent's tool calls.
    """
    jid = str(jid or "").strip()
    if not jid:
        return None
    row = {"ts": round(time.time(), 3), "job": jid,
           "agent": str(agent_id or ""), "summary": str(summary or "")}
    if details and isinstance(details, dict):
        row["details"] = details
    try:
        os.makedirs(os.path.dirname(_FEEDBACK_FILE), exist_ok=True)
        with _FEEDBACK_LOCK:
            with open(_FEEDBACK_FILE, "a", encoding="utf-8") as f:
                f.write(json.dumps(row, sort_keys=True) + "\n")
    except OSError:
        return None
    return row


def feedback_for(jid, agent_id):
    """The most recent feedback record for an agent in a job.

    `jid` may be None to search across all jobs for the agent.
    Returns {} when no record exists (the common case — most jobs succeed).
    """
    jid = str(jid or "").strip()
    aid = str(agent_id or "").strip()
    if not aid:
        return {}
    best = {}
    try:
        with open(_FEEDBACK_FILE, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except ValueError:
                    continue
                if not isinstance(row, dict):
                    continue
                if row.get("agent") != aid:
                    continue
                if jid and row.get("job") != jid:
                    continue
                # Keep the most recent (highest ts)
                if not best or row.get("ts", 0) > best.get("ts", 0):
                    best = row
    except OSError:
        return {}
    return best
