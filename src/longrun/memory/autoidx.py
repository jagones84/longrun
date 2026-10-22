#!/usr/bin/env python3
"""Automatic background codebase indexing (JAG-2.9).

How the reference IDE harness does it (TRAE, Settings > Index & Docs > "automatic
indexing"): when a workspace is open it builds the index in the BACKGROUND and keeps
it up to date as files change — the chat merely consumes a warm index, it never
waits for a walk.

Longrun already had the right *incremental* builder (`codeindex.build` skips files
whose mtime+size did not change) but only a LAZY trigger: `codeindex.ensure_fresh`
runs just before an agent's search, so the FIRST search of a session pays the walk
and a plain chat never indexes at all.

This module moves that work off the request path. One daemon thread per workspace
re-runs the same incremental build on a debounced interval, backing off while
nothing changes and speeding up again after an edit. No new dependency, no watcher
API to install: the build's own mtime/size comparison IS the change detector, so a
no-op pass costs one directory walk and no writes.
"""
import os
import threading
import time

from longrun.memory import codeindex as _codeindex
from longrun.memory import indexcfg as _cfg

# JAG-2.9: the loop starts a few seconds after boot (the server is still wiring
# providers/backfills) and then polls. Two bounds keep it friendly: MIN while the
# tree is changing, MAX once it has been quiet for a while.
STARTUP_DELAY_S = 4.0
POLL_MIN_S = 10.0
POLL_MAX_S = 60.0

_LOCK = threading.Lock()
_STATE = {}   # realpath(ws) -> {"thread": Thread, "stop": Event, "last": dict}


def _interval():
    try:
        v = float(_cfg.load_config().get("auto_index_interval_s") or POLL_MIN_S)
    except Exception:  # noqa: BLE001 — a bad config must not stop the indexer
        v = POLL_MIN_S
    return max(POLL_MIN_S, min(POLL_MAX_S, v))


def _loop(ws, stop, slot):
    delay = STARTUP_DELAY_S
    interval = _interval()
    while not stop.is_set():
        if stop.wait(delay):
            return
        delay = interval
        try:
            if not _cfg.auto_index():
                slot["last"] = {"at": time.time(), "skipped": "auto_index off"}
                continue
            if not os.path.isdir(ws):
                slot["last"] = {"at": time.time(), "skipped": "workspace gone"}
                continue
            t0 = time.monotonic()
            res = _codeindex.build(ws)
            took = time.monotonic() - t0
            slot["last"] = {"at": time.time(), "duration_s": round(took, 2),
                            "files": (res or {}).get("files"),
                            "chunks": (res or {}).get("chunks")}
            # Back off when the tree is quiet; a real edit costs one extra pass.
            interval = POLL_MAX_S if took < 0.25 else POLL_MIN_S
        except Exception as e:  # noqa: BLE001 — indexing must never kill the thread
            slot["last"] = {"at": time.time(), "error": "%s: %s" % (type(e).__name__, e)}
            interval = POLL_MAX_S


def start(ws):
    """Start (idempotently) the background indexer for `ws`. Returns True if new."""
    if not ws:
        return False
    try:
        real = os.path.realpath(ws)
    except OSError:
        return False
    if not os.path.isdir(real):
        return False
    with _LOCK:
        cur = _STATE.get(real)
        if cur and cur["thread"].is_alive():
            return False
        stop = threading.Event()
        slot = {"thread": None, "stop": stop, "last": None}
        t = threading.Thread(target=_loop, args=(real, stop, slot),
                             name="autoidx", daemon=True)
        slot["thread"] = t
        _STATE[real] = slot
        t.start()
        return True


def stop(ws):
    """Stop the indexer for one workspace (no-op when it was never started)."""
    try:
        real = os.path.realpath(ws or "")
    except OSError:
        return
    with _LOCK:
        slot = _STATE.pop(real, None)
    if slot:
        slot["stop"].set()


def stop_all():
    with _LOCK:
        slots = list(_STATE.values())
        _STATE.clear()
    for slot in slots:
        slot["stop"].set()


def status():
    """Diagnostics: which workspaces are watched and when they last ran."""
    with _LOCK:
        items = list(_STATE.items())
    return {"workspaces": [{"workspace": ws,
                            "alive": bool(s["thread"] and s["thread"].is_alive()),
                            "last": s["last"]} for ws, s in items]}
