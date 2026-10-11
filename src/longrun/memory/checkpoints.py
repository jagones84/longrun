#!/usr/bin/env python3
"""Longrun checkpoints — v0.3 snapshot / resume / rollback of harness state.

Captures the harness stores (PLAN, TASKS, and optionally a session transcript)
into `data/checkpoints/` as one self-contained JSON snapshot with a manifest
(id, ts, label, sizes, optional idempotency key). Rollback restores the stores
atomically (tmp file + os.replace) so a crash mid-restore cannot corrupt them.

Idempotency: `create(..., idempotency_key=K)` returns the already-existing
snapshot for K instead of writing a duplicate; repeated `rollback(cp_id)` on
the same checkpoint is a no-op that returns the same state.

Storage layout:
  data/checkpoints/index.json                     — list of manifests (newest first)
  data/checkpoints/cp_<id>.json                   — full snapshot payload
"""

import json
import os
import threading
import time
import uuid

from longrun.tools import registry
from longrun.util.fswrite import read_json, write_json

REPO = registry.REPO
CKPT_DIR = os.path.join(REPO, "data", "checkpoints")
MAX_CHECKPOINTS = 100

_lock = threading.RLock()


def _srv():
    from longrun.core import server
    return server


def _publish(kind, **data):
    try:
        return _srv().publish(kind, **data)
    except Exception:  # feed must never break the operation
        return None


def _index_path():
    return os.path.join(CKPT_DIR, "index.json")


def _load_index():
    return read_json(_index_path(), [])


def _save_index(entries):
    write_json(_index_path(), entries)


def _snapshot_path(cp_id):
    return os.path.join(CKPT_DIR, "cp_%s.json" % cp_id)


# ------------------------------------------------------------------ create ----

def create(label=None, session_id=None, idempotency_key=None, by="api"):
    """Snapshot plan + tasks (+ optional session transcript).

    With `idempotency_key`, creating twice with the same key returns the same
    checkpoint instead of writing a second copy.
    """
    with _lock:
        if idempotency_key:
            existing = get_by_idempotency_key(idempotency_key)
            if existing:
                return {**existing, "idempotent": True}
        srv = _srv()
        payload = {
            "plan": srv.load_plan(),
            "tasks": srv.load_tasks(),
        }
        if session_id:
            sess = srv.load_session(session_id)
            if sess is None:
                return {"error": "session not found: %s" % session_id}
            payload["session"] = sess
        cp_id = "cp_" + uuid.uuid4().hex[:8]
        manifest = {
            "id": cp_id,
            "ts": round(time.time(), 3),
            "label": (label or "checkpoint")[:120],
            "session_id": session_id,
            "idempotency_key": idempotency_key,
            "created_by": by,
            "sizes": {
                "plan_steps": len(payload["plan"].get("steps", [])),
                "tasks": len(payload["tasks"].get("tasks", [])),
                "messages": len(payload.get("session", {}).get("messages", [])),
            },
            "rolled_back": False,
        }
        write_json(_snapshot_path(cp_id), payload)
        entries = _load_index()
        entries.insert(0, manifest)
        _save_index(entries[:MAX_CHECKPOINTS])
        _publish("checkpoint.created", id=cp_id, label=manifest["label"],
                 session=session_id, by=by)
        return manifest


# ------------------------------------------------------- JAG-426 turn anchor ---

def _feed_seq():
    """High-water mark of the durable event log, for turn-anchored rewind."""
    try:
        from longrun.core import events
        return int(events.feed_seq())
    except Exception:  # noqa: BLE001 — an anchor must never break a turn
        return 0


def _stamp(cp_id, extra):
    """Merge extra fields into a checkpoint manifest."""
    with _lock:
        entries = _load_index()
        for m in entries:
            if m.get("id") == cp_id:
                m.update(extra)
        _save_index(entries)
    return get(cp_id)


def create_turn(session_id, msg_index, label=None, by="chat"):
    """Snapshot the PRE-turn state, anchored to a USER message index (JAG-426).

    `msg_index` is the index of the user message in the session transcript (the
    value `stores.session_mark()` captured just BEFORE it was appended), so a
    later rewind to this message restores exactly the state the turn started
    from. Idempotent per (session, message): a retried request re-uses the same
    checkpoint instead of piling up duplicates.
    """
    cp = create(label=label or ("turn %s" % msg_index), session_id=session_id,
                idempotency_key="turn:%s:%s" % (session_id, msg_index), by=by)
    if cp.get("error"):
        return cp
    return _stamp(cp["id"], {"kind": "turn", "msg_index": int(msg_index),
                             "events_upto": _feed_seq()})


def get_by_idempotency_key(key):
    for m in _load_index():
        if m.get("idempotency_key") == key:
            return m
    return None

def get(cp_id):
    for m in _load_index():
        if m.get("id") == cp_id:
            return m
    return None


def list_checkpoints(limit=50):
    return _load_index()[:limit]


def delete(cp_id):
    """Delete a checkpoint: drop its manifest and unlink its snapshot (JAG-318).

    Returns ``{ok, deleted, files}`` — a missing id is a clean no-op error.
    """
    cp_id = str(cp_id or "").strip()
    if not cp_id:
        return {"ok": False, "error": "id required"}
    with _lock:
        entries = _load_index()
        keep = [m for m in entries if m.get("id") != cp_id]
        if len(keep) == len(entries):
            return {"ok": False, "error": "checkpoint not found: %s" % cp_id}
        _save_index(keep)
        files = []
        for suffix in ("", ".tmp"):
            p = _snapshot_path(cp_id) + suffix
            try:
                os.remove(p)
                files.append(os.path.basename(p))
            except OSError:
                pass
    _publish("checkpoint.deleted", id=cp_id)
    return {"ok": True, "deleted": cp_id, "files": files}


def prune(keep=MAX_CHECKPOINTS):
    """Drop the OLDEST checkpoints beyond `keep` and unlink their payloads
    (JAG-318). The index is already capped on create, so this compacts any
    pre-existing overflow and is safe to call repeatedly."""
    keep = max(1, int(keep))
    with _lock:
        entries = _load_index()
        if len(entries) <= keep:
            return {"ok": True, "removed": 0}
        victims = entries[keep:]
        _save_index(entries[:keep])
        removed = 0
        for m in victims:
            cid = m.get("id")
            if not cid:
                continue
            for suffix in ("", ".tmp"):
                try:
                    os.remove(_snapshot_path(cid) + suffix)
                except OSError:
                    pass
            removed += 1
    _publish("checkpoint.pruned", removed=removed)
    return {"ok": True, "removed": removed}


def purge_session(session_id):
    """JAG-413: drop every checkpoint belonging to `session_id`.

    Deleting a session must not leave its checkpoints behind: a later rollback
    would try to restore a session that no longer exists (its transcript is
    tombstoned), silently applying only the plan/tasks half. Returns the number
    of checkpoints removed.
    """
    sid = str(session_id or "")
    if not sid:
        return 0
    with _lock:
        entries = _load_index()
        victims = [m for m in entries if m.get("session_id") == sid]
        if not victims:
            return 0
        _save_index([m for m in entries if m.get("session_id") != sid])
        for m in victims:
            cid = m.get("id")
            if not cid:
                continue
            for suffix in ("", ".tmp"):
                try:
                    os.remove(_snapshot_path(cid) + suffix)
                except OSError:
                    pass
    _publish("checkpoint.session_purged", session=sid, removed=len(victims))
    return len(victims)


def load_payload(cp_id):
    return read_json(_snapshot_path(cp_id), None)


# ---------------------------------------------------------------- rollback ----

def rollback(cp_id, by="api"):
    """Restore plan/tasks/(session) from a checkpoint. Idempotent: rolling the
    same checkpoint back twice converges to the same restored state."""
    with _lock:
        manifest = get(cp_id)
        if not manifest:
            return {"error": "checkpoint not found: %s" % cp_id}
        payload = load_payload(cp_id)
        if payload is None:
            return {"error": "snapshot payload missing for %s" % cp_id}
        srv = _srv()
        srv.save_plan(payload["plan"])
        srv.save_tasks(payload["tasks"])
        if manifest.get("session_id") and payload.get("session"):
            srv.save_session(payload["session"])
        entries = _load_index()
        for m in entries:
            if m.get("id") == cp_id:
                m["rolled_back"] = True
                m["rollback_count"] = m.get("rollback_count", 0) + 1
                m["last_rollback_ts"] = round(time.time(), 3)
                m["last_rollback_by"] = by
        _save_index(entries)
        _publish("checkpoint.rolled_back", id=cp_id, by=by,
                 label=manifest.get("label"))
        return {"ok": True, "restored": manifest}
