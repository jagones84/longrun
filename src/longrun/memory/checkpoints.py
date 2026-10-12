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


# ------------------------------------------------------- session task graph ----
# JAG-431: the REAL, live todo list is the per-SESSION task graph
# (`data/graphs/<sid>.json`, `longrun.plan.taskgraph`) — NOT the legacy global
# plan.json/tasks.json the panel no longer reads. A snapshot that captured only the
# legacy stores restored nothing the UI renders, so a rewind left the todos on
# screen ("graphical delete only"). The checkpoint must carry the session graph too.

def _load_graph(session_id):
    """The session's task graph (dict) or None. Never raises."""
    try:
        from longrun.plan import taskgraph
        return taskgraph.load(session_id)
    except Exception:  # noqa: BLE001
        return None


def _restore_graph(session_id, snapshot):
    """Put the session task graph back to `snapshot` (or archive it when the graph
    did not exist at anchor time, so the todos truly disappear)."""
    try:
        from longrun.plan import taskgraph
    except Exception:  # noqa: BLE001
        return {"ok": False}
    if snapshot:
        snap = dict(snapshot)
        snap.setdefault("key", session_id)
        snap.setdefault("run_id", session_id)
        taskgraph.save(snap)
        return {"ok": True, "nodes": len(snap.get("nodes", []))}
    taskgraph.reset(session_id)     # soft-clear: archives the graph that appeared after
    return {"ok": True, "nodes": 0, "archived": True}


def _prune_graph_after(session_id, upto_ts):
    """Back-compat rewind for LEGACY anchors (JAG-431): an anchor created BEFORE the
    graph was snapshotted has no `graph` payload, so a snapshot restore is impossible.
    Best effort: drop every node the graph gained AFTER the anchor's timestamp
    (`created > ts`) — that is exactly what the rewound turn(s) added, so the panel no
    longer shows todos that did not exist at that point. Never raises."""
    try:
        from longrun.plan import taskgraph
    except Exception:  # noqa: BLE001
        return {"ok": False}
    g = taskgraph.load(session_id)
    if not g:
        return {"ok": True, "nodes": 0, "removed": 0, "legacy": True}
    cut = float(upto_ts or 0)
    nodes = g.get("nodes", []) or []
    keep = [n for n in nodes if float(n.get("created") or 0) <= cut]
    removed = len(nodes) - len(keep)
    if removed:
        g["nodes"] = keep
        taskgraph.save(g)
    return {"ok": True, "nodes": len(keep), "removed": removed, "legacy": True}


def _prune_graph_at(session_id, cut):
    """Drop every node whose `created` is >= `cut` (the target todo and all later
    ones). Used by the node-targeted rewind (JAG-431d). Never raises."""
    try:
        from longrun.plan import taskgraph
    except Exception:  # noqa: BLE001
        return {"ok": False}
    g = taskgraph.load(session_id)
    if not g:
        return {"ok": True, "nodes": 0, "removed": 0}
    cut = float(cut or 0)
    nodes = g.get("nodes", []) or []
    keep = [n for n in nodes if float(n.get("created") or 0) < cut]
    removed = len(nodes) - len(keep)
    if removed:
        g["nodes"] = keep
        taskgraph.save(g)
    return {"ok": True, "nodes": len(keep), "removed": removed}


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
            # JAG-431: the session task graph IS the live todo list the UI renders —
            # snapshot it so a rewind can put the todos back (or remove them).
            payload["graph"] = _load_graph(session_id)
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
                "graph_nodes": len((payload.get("graph") or {}).get("nodes", [])),
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
    extra = {"kind": "turn", "msg_index": int(msg_index)}
    # JAG-426-fix: a DUPLICATE mark (same session+message, e.g. a retried request)
    # must keep the anchor's ORIGINAL event high-water. Re-stamping it with the
    # current feed id moved the cut ABOVE the turn's own events, so a later rewind
    # silently failed to truncate them. Only stamp it when it is not already set.
    if cp.get("events_upto") is None:
        extra["events_upto"] = _feed_seq()
    stamped = _stamp(cp["id"], extra)
    try:
        prune_turns(session_id)          # JAG-431f: bound the per-session anchor history
    except Exception:  # noqa: BLE001 — pruning must never break a turn
        pass
    return stamped


# JAG-431f: turn anchors are idempotent per (session, message) and would otherwise
# grow forever (one per user message). Keep only the newest N per session.
TURN_KEEP = int(os.environ.get("LONGRUN_TURN_ANCHORS") or 30)


def prune_turns(session_id, keep=None):
    """Drop the OLDEST turn anchors of `session_id` beyond `keep` (newest kept)."""
    keep = max(1, int(keep or TURN_KEEP))
    with _lock:
        entries = _load_index()
        turns = [m for m in entries
                 if m.get("session_id") == session_id and m.get("kind") == "turn"]
        if len(turns) <= keep:
            return 0
        turns.sort(key=lambda m: (m.get("msg_index")
                                  if m.get("msg_index") is not None else -1))
        victims = {m["id"] for m in turns[:-keep]}
        _save_index([m for m in entries if m.get("id") not in victims])
        for cid in victims:
            for suffix in ("", ".tmp"):
                try:
                    os.remove(_snapshot_path(cid) + suffix)
                except OSError:
                    pass
    return len(victims)


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
        # JAG-431: restore the SESSION TASK GRAPH too (the real, live todo list).
        graph_info = None
        if manifest.get("session_id"):
            if "graph" in payload:
                graph_info = _restore_graph(manifest["session_id"], payload.get("graph"))
            else:
                # Legacy anchor (no snapshot): prune the nodes the rewound turn added.
                graph_info = _prune_graph_after(manifest["session_id"], manifest.get("ts"))
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
        out = {"ok": True, "restored": manifest}
        if graph_info is not None:
            out["graph"] = graph_info
        return out
