#!/usr/bin/env python3
"""Per-run metrics (JAG-129E): how much a run worked.

Writes data/runs/<key>.json with: started, ended, duration_s, iterations, steps,
tokens, model, outcome, stop_reason. `human()` produces the plain-text line.
"""
import json
import os
import time

import threading

from longrun.util import paths
from longrun.util.fswrite import safe_id, write_json
from longrun.util.paths import REPO_ROOT as REPO
RUNS_DIR = os.environ.get("LONGRUN_RUNS_DIR", os.path.join(paths.DATA_DIR, "runs"))
_START = {}
_LOCK = threading.Lock()


def _path(key):
    return os.path.join(RUNS_DIR, safe_id(key) + ".json")


# B-4 (v816): the FOUR buckets the benchmark procedure names before any code is
# touched. A stop reason that is one of these is enough on its own; anything else
# falls through to the error text.
_BUDGET_STOPS = ("budget", "wall", "tokens", "max_steps", "timeout")
_MODEL_STOPS = ("empty_reply", "invalid_reply", "no_action", "unparsable")


def classify_cause(outcome="done", stop_reason=None, error=None, code=None):
    """The ONE cause of a failed run: `provider` | `budget` | `model` | `harness`.

    `None` for a clean run. A 5xx/quota is the PROVIDER, a wall-clock/token stop
    is the BUDGET, a reply the loop could not use is the MODEL, and whatever is
    left is the HARNESS — the loop lost the work, which is the only bucket that is
    a harness bug. Reuses the classifiers that already exist (`diagnostics` codes,
    `rllm.classify_retry`) instead of a third spelling of the same rules
    ("Failure Attribution Standard", 2026-11-05: an attribution with no recorded
    counterfactual carries no attribution).
    """
    stop = str(stop_reason or "").strip().lower()
    out = str(outcome or "done").strip().lower()
    if out == "user_abort":
        return None
    if stop in _BUDGET_STOPS:
        return "budget"
    if stop in _MODEL_STOPS:
        return "model"
    if str(code or "").startswith("provider."):
        return "provider"
    text = str(error or "").lower()
    if "empty message" in text or "invalid reply" in text or "no valid action" in text:
        return "model"
    if text:
        try:
            from longrun.model import rllm
            disp = rllm.classify_retry(text).get("disposition")
        except Exception:  # noqa: BLE001 — classification must never raise
            disp = None
        if disp in ("quota", "transient", "fatal"):
            return "provider"
    # The residual bucket is the HARNESS — but only when the turn actually FAILED.
    # A CLEAN turn ends with `outcome="done"` and one of the keeper's own reasons
    # (`goal_reached`, `plan_only`, `no_progress`, `blocked`, `need_input`…), so
    # keying on "the stop reason is unknown" labelled every tool-using success a
    # harness failure (found in independent review 2026-11-05).
    if out not in ("", "done", "completed", "ok", "success"):
        return "harness"
    return None


def start(key, model=None):
    rec = {"key": key, "model": model, "started": round(time.time(), 3),
           "ended": None, "duration_s": None, "iterations": 0, "steps": 0,
           "tokens": 0, "outcome": "running", "stop_reason": None,
           "difficulty": None}
    with _LOCK:
        if len(_START) > 512:
            _START.pop(next(iter(_START)), None)
        _START[key] = rec["started"]
    _write(key, rec)
    return rec


def finish(key, outcome="done", stop_reason=None, iterations=0, steps=0, tokens=0,
           prompt_tokens=0, completion_tokens=0, model=None, difficulty=None,
           error=None, code=None):
    rec = get(key)
    if not rec:
        rec = start(key)
    now = round(time.time(), 3)
    rec.update({"ended": now, "iterations": int(iterations), "steps": int(steps),
                "tokens": int(tokens),
                "prompt_tokens": int(prompt_tokens),
                "completion_tokens": int(completion_tokens),
                "outcome": outcome, "stop_reason": stop_reason,
                # B-4: one classified cause, always present (None = a clean run).
                "failure_cause": classify_cause(outcome, stop_reason, error, code)})
    if model:
        rec["model"] = model
    if difficulty is not None:
        rec["difficulty"] = difficulty
    with _LOCK:
        started = _START.pop(key, None) or rec.get("started") or now
    rec["duration_s"] = round(now - float(started), 1)
    _write(key, rec)
    return rec


def _write(key, rec):
    write_json(_path(key), rec)


def get(key):
    try:
        with open(_path(key), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None
