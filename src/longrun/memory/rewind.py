#!/usr/bin/env python3
"""Turn-anchored rewind (JAG-426 · Domain 2).

Longrun could already snapshot/rollback a checkpoint, but only at RUN start and
only plan/tasks/transcript — there was no way to say "put the session back to
what it was before my 3rd message". This module owns that boundary.

Wave 1 (this file today) ships the ANCHOR half:

    mark(session_id, msg_index)  — one idempotent checkpoint per USER message,
                                   stamped with `msg_index` + the event
                                   high-water mark (`events_upto`).
    marks(session_id)            — the turn anchors of a session, oldest first.

Wave 2 adds the RESTORE half (`rewind()`): truncate the transcript, release the
todos/graph nodes created after the mark, revert the workspace files the HARNESS
edited (never the user's hand-edits), and drop the events after `events_upto` —
keeping a pre-rollback snapshot so the undo itself is undoable.

Pure module: no server import at module load; every entry point swallows its own
failures, because a turn must never break just because it could not be anchored.
"""


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
