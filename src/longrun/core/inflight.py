#!/usr/bin/env python3
"""Durable record of the turns that are RUNNING right now (2026-11-10).

Operator: *"dopo un hard restart da systemd l'harness dovrebbe capire che è stato
fatto il restart e inviare messaggi alle sessioni bloccate dal restart che stavano
in RUN … un file di log deve aver real time salvato i running process e al riavvio
deve esser letto e mandato comando alle sessioni specifiche interrotte dal restart
(solo per restart, no per chiusura)."*

`_ACTIVE_CHAT` is process memory, so a restart erases it. This module mirrors it
to `data/inflight_turns.json` at every `turn_begin` / `turn_end` (the ONE bracket
every turn already uses: stream, sync, agent run, MCP), and on boot
`recover()` reads it and hands a continuation message to each session whose turn
never ended.

Restart vs closure: SIGTERM writes `data/last_stop.json`. At boot a marker that is
OLDER than `restart_resume_window_secs` means the operator stopped the service on
purpose (no resume); a fresh marker means `systemctl restart` (resume); no marker
at all means crash / kill -9 (resume).

Nothing here may break a turn: every write is best-effort.
"""

import json
import os
import threading
import time

from longrun.util import fswrite
from longrun.util.paths import DATA_DIR

INFLIGHT = os.path.join(DATA_DIR, "inflight_turns.json")
STOP_MARK = os.path.join(DATA_DIR, "last_stop.json")

_LOCK = threading.Lock()

RESUME_TEXT = (
    "[Harness restart] The service was restarted while a turn was running in this "
    "session (interrupted at %s). Continue the task from where it stopped: read the "
    "conversation and the tool results above, do not repeat steps that already "
    "succeeded, and finish the work. If it was already finished, answer with the "
    "final result."
)


def _read(path):
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except Exception:  # noqa: BLE001 — a missing/corrupt file is "nothing running"
        return {}


def _write(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fswrite.write_json(path, data)


def begin(sid, tok=None):
    """Record that `sid` has a turn in flight now (never raises)."""
    sid = str(sid or "").strip()
    if not sid:
        return
    try:
        with _LOCK:
            data = _read(INFLIGHT)
            data[sid] = {"ts": round(time.time(), 3), "pid": os.getpid(),
                         "turn": None if tok is None else id(tok)}
            _write(INFLIGHT, data)
    except Exception:  # noqa: BLE001 — bookkeeping must never break a turn
        pass


def end(sid, tok=None):
    """Drop the record for `sid`; a newer turn's record is left alone (never raises)."""
    sid = str(sid or "").strip()
    if not sid:
        return
    try:
        with _LOCK:
            data = _read(INFLIGHT)
            rec = data.get(sid)
            if rec is None:
                return
            if tok is not None and rec.get("turn") not in (None, id(tok)):
                return
            data.pop(sid, None)
            if data:
                _write(INFLIGHT, data)
            else:
                try:
                    os.remove(INFLIGHT)
                except OSError:
                    pass
    except Exception:  # noqa: BLE001
        pass


def snapshot():
    """The sessions recorded as running ({} when none)."""
    return _read(INFLIGHT)


def note_stop(reason="exit"):
    """Mark a CLEAN stop of this process (SIGTERM / Ctrl-C), never a crash."""
    try:
        _write(STOP_MARK, {"ts": round(time.time(), 3), "pid": os.getpid(),
                           "reason": str(reason or "exit")})
    except Exception:  # noqa: BLE001
        pass


def _consume_stop():
    """Read and delete the stop marker; None when the last exit was not clean."""
    rec = _read(STOP_MARK)
    try:
        os.remove(STOP_MARK)
    except OSError:
        pass
    return rec or None


def deliberate_stop(window_secs):
    """True when the previous process was STOPPED on purpose (not restarted).

    A marker older than `window_secs` means the operator stopped the service and
    started it again later — a closure, not a restart. A fresh marker is
    `systemctl restart` (the new process came up immediately).
    """
    rec = _consume_stop()
    if not rec:
        return False
    try:
        age = time.time() - float(rec.get("ts") or 0)
    except (TypeError, ValueError):
        return False
    return age > max(0.0, float(window_secs or 0))


def clear():
    """Forget the running set (after recovery, or after a deliberate stop)."""
    try:
        os.remove(INFLIGHT)
    except OSError:
        pass


def recover(window_secs=60, max_sessions=10, *, load=None, active=None,
            deliver=None, clear_after=True):
    """Resume the turns a restart interrupted.

    `load` / `active` / `deliver` are injectable so a test needs no server, no
    model and no session store. Returns a report; never raises.
    """
    rec = snapshot()
    stop = _consume_stop()
    out = {"file": INFLIGHT, "running": sorted(rec), "resumed": [],
           "skipped": [], "stopped": False}
    if not rec:
        return out
    try:
        age = time.time() - float((stop or {}).get("ts") or 0)
    except (TypeError, ValueError):
        age = None
    if stop is not None and age is not None and age > max(0.0, float(window_secs or 0)):
        # A deliberate stop followed by a later start: close the record, no resume.
        out["stopped"] = True
        if clear_after:
            clear()
        return out
    if load is None:
        from longrun.memory import stores as _stores
        load = _stores.load_session
    if active is None:
        from longrun.core import events as _events
        active = _events.turn_active
    if deliver is None:
        from longrun.util import inbox as _inbox
        deliver = _inbox.deliver
    limit = max(0, int(max_sessions or 0))
    for sid in sorted(rec):
        info = rec.get(sid) or {}
        if limit and len(out["resumed"]) >= limit:
            out["skipped"].append({"session": sid, "why": "cap reached"})
            continue
        try:
            sess = load(sid)
        except Exception:  # noqa: BLE001
            sess = None
        if not sess:
            out["skipped"].append({"session": sid, "why": "session no longer exists"})
            continue
        tail = (sess.get("messages") or [])[-3:]
        if any(((m.get("meta") or {}).get("matrix_resumed")
                or (m.get("meta") or {}).get("matrix_continuation")) for m in tail):
            out["skipped"].append({"session": sid, "why": "already resumed by Matrix"})
            continue
        if not (sess.get("interrupted") or {}):
            # reconcile_orphan_turns did not classify it as half-done: either the
            # turn really ended before the process died, or it left no user turn.
            out["skipped"].append({"session": sid, "why": "no interrupted turn"})
            continue
        try:
            if active(sid):
                out["skipped"].append({"session": sid, "why": "already running"})
                continue
        except Exception:  # noqa: BLE001
            pass
        when = time.strftime("%Y-%m-%d %H:%M:%S",
                             time.localtime(float(info.get("ts") or time.time())))
        try:
            res = deliver(sid, RESUME_TEXT % when) or {}
        except Exception as e:  # noqa: BLE001 — one session must not stop the rest
            out["skipped"].append({"session": sid, "why": "delivery raised: %s" % e})
            continue
        if res.get("ok"):
            out["resumed"].append(sid)
        else:
            out["skipped"].append({"session": sid,
                                   "why": res.get("error") or "delivery refused"})
    if clear_after:
        clear()
    return out
