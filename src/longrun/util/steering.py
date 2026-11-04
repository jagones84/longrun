"""Mid-run steering + abort inboxes (JAG-127b / JAG-129A).

A message the user types while a turn is still streaming (or a queued message the
app flushes) is queued here and injected as a user message at the next loop
boundary — the modern-IDE "steer" behaviour, with no second turn and no second SSE
stream. Abort is separate: steer redirects, abort stops; the loop checks the flag
on every iteration.

Extracted from ``server.py`` (JAG-375). Stdlib only.
"""
import threading
import time
import uuid

# JAG-127b: mid-run steering. A message the user types while a turn is still
# streaming (or a queued message the app flushes) is dropped here and injected
# as a user message at the next loop boundary — the modern-IDE "steer" behaviour,
# with no second turn and no second SSE stream.
STEER_INBOX = {}
_steer_lock = threading.Lock()


def push_steer(sess_id, text, steer_id=None):
    """Queue a steering message for a running session. Returns the new depth.

    JAG-796: the queue is the IN-MEMORY channel the loop drains; the same text is
    also recorded durably (`record_steer`) so the session transcript can show it
    even while the loop is still blocked and cannot drain it yet. A caller that
    needs the id up front (the HTTP endpoint echoes it) passes `steer_id`, so the
    steer is still recorded exactly ONCE.
    """
    text = str(text or "").strip()
    if not sess_id or not text:
        return 0
    record_steer(sess_id, text, steer_id=steer_id)
    with _steer_lock:
        q = STEER_INBOX.setdefault(sess_id, [])
        q.append(text)
        return len(q)


def drain_steer(sess_id):
    """Pop all steering messages for a session (called per loop iteration)."""
    with _steer_lock:
        # JAG-302: pop the key instead of re-inserting an empty list — the old
        # `STEER_INBOX[sess_id] = []` left a permanent empty entry for every
        # session that ever ran a turn (an unbounded dict).
        return STEER_INBOX.pop(sess_id, [])


def has_steer(sess_id):
    """JAG-129A: True when there is at least one steering message queued."""
    with _steer_lock:
        return bool(STEER_INBOX.get(sess_id))


# JAG-796: the DURABLE side of a steer. STEER_INBOX above dies with the process
# and is only drained at a loop boundary, so a steer typed while the turn was
# blocked inside a dispatch (up to an hour) had NO trace anywhere: the operator's
# own message vanished from the chat and could not survive a reload. Every
# accepted steer is therefore ALSO recorded here, and `save_session` folds the
# missing ones into the transcript as REAL user messages (see
# `stores.adopt_live_steers`). Same shape as `_LIVE` (live operator fields): the
# record is kept for the life of the process and RE-APPLIED on every write, so a
# stale in-memory copy of the session cannot silently drop it either. Each record
# carries its own id, so two identical steers stay two messages.
STEER_LOG = {}              # sid -> [{"id": str, "text": str, "ts": float}]
_steer_log_lock = threading.Lock()


def record_steer(sess_id, text, steer_id=None):
    """Record a steer for the durable transcript fold. Returns its id."""
    text = str(text or "").strip()
    if not sess_id or not text:
        return ""
    sid_key = steer_id or uuid.uuid4().hex[:12]
    with _steer_log_lock:
        STEER_LOG.setdefault(sess_id, []).append(
            {"id": sid_key, "text": text, "ts": round(time.time(), 3)})
    return sid_key


def new_steer_id():
    """An id for a steer the caller needs to name BEFORE queueing it."""
    return uuid.uuid4().hex[:12]


def live_steers(sess_id):
    """Every steer recorded for this session (re-applied on each write)."""
    with _steer_log_lock:
        return [dict(it) for it in (STEER_LOG.get(sess_id) or [])]


def forget_steers(sess_id):
    """Drop the durable steer log for a deleted session (JAG-302: no leak)."""
    with _steer_log_lock:
        STEER_LOG.pop(sess_id, None)


# JAG-129A: abort of an in-flight chat turn (distinct from steer: steer
# redirects, abort stops). The loop checks the flag on every iteration.
ABORT_INBOX = set()
_abort_lock = threading.Lock()


def push_abort(sess_id):
    if not sess_id:
        return False
    with _abort_lock:
        ABORT_INBOX.add(sess_id)
    return True


def _is_aborted(sess_id):
    with _abort_lock:
        return sess_id in ABORT_INBOX


def clear_abort(sess_id):
    with _abort_lock:
        ABORT_INBOX.discard(sess_id)

