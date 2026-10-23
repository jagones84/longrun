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
           prompt_tokens=0, completion_tokens=0, model=None, difficulty=None):
    rec = get(key)
    if not rec:
        rec = start(key)
    now = round(time.time(), 3)
    rec.update({"ended": now, "iterations": int(iterations), "steps": int(steps),
                "tokens": int(tokens),
                "prompt_tokens": int(prompt_tokens),
                "completion_tokens": int(completion_tokens),
                "outcome": outcome, "stop_reason": stop_reason})
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
