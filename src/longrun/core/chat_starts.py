"""Durable idempotency records for detached chat starts."""
import hashlib
import json
import threading

from longrun.core import events

lock = threading.RLock()
_live = set()


def mark_live(turn_id):
    with lock:
        _live.add(turn_id)


def is_live(turn_id):
    with lock:
        return turn_id in _live


def finish(key, turn_id, status):
    with lock:
        set_status(key, status)
        _live.discard(turn_id)


def fingerprint(body):
    data = json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(data.encode("utf-8")).hexdigest()


def _table():
    events.db().execute(
        "CREATE TABLE IF NOT EXISTS chat_starts ("
        "key TEXT PRIMARY KEY, fingerprint TEXT NOT NULL, session TEXT NOT NULL, "
        "turn_id TEXT NOT NULL, status TEXT NOT NULL)")


def lookup(key):
    with events._db_lock:
        _table()
        row = events.db().execute(
            "SELECT fingerprint, session, turn_id, status FROM chat_starts WHERE key=?",
            (key,)).fetchone()
        events.db().commit()
    if row is None:
        return None
    return dict(zip(("fingerprint", "session", "turn_id", "status"), row))


def reserve(key, digest, session, turn_id):
    with events._db_lock:
        _table()
        events.db().execute(
            "INSERT INTO chat_starts(key, fingerprint, session, turn_id, status) "
            "VALUES (?, ?, ?, ?, 'launching')", (key, digest, session, turn_id))
        events.db().commit()


def set_status(key, status):
    with lock:
        with events._db_lock:
            _table()
            events.db().execute("UPDATE chat_starts SET status=? WHERE key=?", (status, key))
            events.db().commit()
