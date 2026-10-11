#!/usr/bin/env python3
"""Turn-anchored rewind (JAG-426 · Domain 2).

Longrun could already snapshot/rollback a checkpoint, but only at RUN start and
only plan/tasks/transcript — there was no way to say "put the session back to what
it was before my 3rd message". This module owns that boundary:

    mark(session_id, msg_index)      — one idempotent checkpoint per USER message,
                                       stamped with `msg_index` + the event
                                       high-water mark (`events_upto`).
    marks(session_id)                — the turn anchors of a session, oldest first.
    rewind(session_id, msg_index)    — restore that pre-turn state: transcript +
                                       plan/tasks (from the anchor), the workspace
                                       files the HARNESS edited (never hand-edits),
                                       and the event log; plus a PRE-REWIND snapshot
                                       so the undo itself is undoable.

Every entry point swallows its own failures: a turn must never break just because
it could not be anchored, and a rewind must report a clean error rather than raise.
"""

import os


def mark(session_id, msg_index, label=None):
    """Anchor the PRE-turn state of the user message at `msg_index`.

    Idempotent (same session+index -> same checkpoint). Returns the manifest, or
    None when the anchor could not be created — never raises.
    """
    if not session_id:
        return None
    try:
        from longrun.memory import checkpoints
        return checkpoints.create_turn(session_id, int(msg_index or 0), label=label)
    except Exception:  # noqa: BLE001 — anchoring must never break a turn
        return None


def marks(session_id, limit=500):
    """The turn anchors of a session, ordered from the earliest message on."""
    try:
        from longrun.memory import checkpoints
        rows = [m for m in checkpoints.list_checkpoints(limit=limit)
                if m.get("session_id") == session_id and m.get("kind") == "turn"]
    except Exception:  # noqa: BLE001
        return []
    rows.sort(key=lambda m: (m.get("msg_index") if m.get("msg_index") is not None else -1))
    return rows


def _anchor(session_id, msg_index):
    try:
        want = int(msg_index)
    except (TypeError, ValueError):
        return None
    for m in marks(session_id):
        if m.get("msg_index") == want:
            return m
    return None


def restore_workspace(session_id, upto_ts):
    """Revert ONLY the files the HARNESS edited after `upto_ts`.

    The journal is append-only, so per file the OLDEST entry after the mark holds
    the true pre-image; a file the harness CREATED is removed instead. The user's
    own hand-edits are never touched (only files in the harness journal are).
    """
    try:
        from longrun.tools import edits
        rows = edits.entries(session_id)
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": "edits journal unavailable: %s" % e, "restored": []}
    cut = float(upto_ts or 0)
    victims = [e for e in rows if float(e.get("ts") or 0) > cut]
    if not victims:
        return {"ok": True, "restored": [], "files": []}
    first = {}
    for e in sorted(victims, key=lambda e: float(e.get("ts") or 0)):
        p = e.get("path")
        if p and p not in first:
            first[p] = e
    restored = []
    for path, e in first.items():
        try:
            if e.get("action") == "created":
                if os.path.isfile(path):
                    os.remove(path)
                restored.append({"path": path, "action": "removed"})
            else:
                with open(path, "w", encoding="utf-8") as f:
                    f.write(e.get("before") or "")
                restored.append({"path": path, "action": "restored"})
        except OSError as ex:
            restored.append({"path": path, "error": str(ex)})
    try:
        edits.drop_after(session_id, cut)
    except Exception:  # noqa: BLE001 — a journal hiccup must not fail the rewind
        pass
    return {"ok": True, "restored": restored, "files": sorted(first)}


def truncate_events(session_id, upto_seq):
    """Drop the event rows a rewind invalidated (session-scoped, id > upto_seq)."""
    try:
        from longrun.core import events
        return {"ok": True, "removed": events.truncate(session_id, upto_seq)}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": str(e), "removed": 0}


def rewind(session_id, msg_index, by="api"):
    """Restore `session_id` to the state BEFORE user message `msg_index`.

    Order: snapshot the CURRENT state (undo-the-undo) -> roll the anchor back
    (transcript + plan/tasks) -> revert the harness's workspace edits -> drop the
    later events. Idempotent: rolling the same anchor twice converges.
    """
    if not session_id:
        return {"ok": False, "error": "session required"}
    m = _anchor(session_id, msg_index)
    if not m:
        return {"ok": False, "error": "no turn anchor for message %s" % msg_index}
    pre = None
    restored = {"error": "checkpoints unavailable"}
    try:
        from longrun.memory import checkpoints
        try:
            pre = checkpoints.create(label="pre-rewind to %s" % msg_index,
                                     session_id=session_id, by=by)
        except Exception:  # noqa: BLE001 — a missing pre-snapshot must not block the rewind
            pre = None
        restored = checkpoints.rollback(m["id"])
    except Exception as e:  # noqa: BLE001
        restored = {"error": str(e)}
    ws = restore_workspace(session_id, m.get("ts"))
    ev = truncate_events(session_id, m.get("events_upto"))
    return {"ok": bool(restored.get("ok")), "anchor": m, "restored": restored,
            "workspace": ws, "events": ev,
            "pre_snapshot": (pre or {}).get("id"), "msg_index": m.get("msg_index")}
