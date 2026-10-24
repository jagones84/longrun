"""Durable event log + live SSE feed + per-session turn locks.

The SQLite `events` table is the durable REPLAY buffer (not an archive): the live
in-memory deque feeds SSE subscribers, and the log answers post-mortem queries.
`publish()` is the single write path; `_ACTIVE_CHAT` is the SERVER TRUTH for
whether a session is "running" (the session list reads it). Turn locks serialise
one chat turn per session.

Extracted from ``server.py`` (JAG-372). Stdlib only.
"""
import json
import os
import sqlite3
import threading
import time
from collections import deque

from longrun.util.paths import REPO_ROOT as REPO, DATA_DIR as _PATH_DATA_DIR

# JAG-533: the durable event log is user state -> the data home, never the checkout.
DATA_DIR = _PATH_DATA_DIR
MAX_FEED_EVENTS = 800

# --------------------------------------------------------------- sqlite ----

DB_PATH = os.environ.get("LONGRUN_DB", os.path.join(DATA_DIR, "events.db"))
_db_lock = threading.Lock()
_db = None
# JAG-300: the durable event log is a REPLAY buffer, not an archive — it must not
# grow without bound (it had reached 1.12M rows / 159 MB, ~95% streaming deltas).
# Keep only the newest EVENTS_KEEP rows; prune in bounded batches (see prune_events).
EVENTS_KEEP = int(os.environ.get("LONGRUN_EVENTS_KEEP", "200000"))
PRUNE_INTERVAL_S = float(os.environ.get("LONGRUN_EVENTS_PRUNE_S", "900"))
PRUNE_BATCH = 50000


_EVENTS_DDL = """CREATE TABLE IF NOT EXISTS events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts REAL NOT NULL, kind TEXT NOT NULL, data TEXT NOT NULL)"""
_EVENTS_IDX_DDL = (
    "CREATE INDEX IF NOT EXISTS idx_events_kind_id ON events(kind, id DESC)",
    "CREATE INDEX IF NOT EXISTS idx_events_ts ON events(ts)",
)
_RUNS_DDL = """CREATE TABLE IF NOT EXISTS runs (
            id TEXT PRIMARY KEY, kind TEXT NOT NULL, goal TEXT,
            model TEXT, ts REAL NOT NULL, tokens_in INTEGER DEFAULT 0,
            tokens_out INTEGER DEFAULT 0, cost_usd REAL DEFAULT 0.0,
            status TEXT DEFAULT 'running', spans TEXT DEFAULT '[]')"""


def _connect_events():
    """Open the events DB with WAL/NORMAL pragmas + schema.

    Raises ``sqlite3.DatabaseError`` when the file is not a valid database, so
    :func:`db` can quarantine it and start fresh instead of crashing the server.

    JAG-300: the events log writes ONE ROW PER STREAMING DELTA (hundreds of
    thousands per session) under a global lock. With the default rollback
    journal + synchronous=FULL every publish did an fsync — measured at
    6.0 ms/call, throttling every token of every turn. WAL turns commits into
    appends and NORMAL drops the per-commit fsync. Still crash-safe (WAL +
    NORMAL); only a power loss can drop the last few transactions of this
    REPLAY log — the session transcripts are the source of truth for messages.
    """
    conn = sqlite3.connect(DB_PATH, check_same_thread=False, timeout=5.0)
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA busy_timeout=5000")
    except sqlite3.Error:
        # Exotic filesystems may reject WAL — fall back to the default journal.
        pass
    try:
        conn.execute(_EVENTS_DDL)
        for idx_sql in _EVENTS_IDX_DDL:
            conn.execute(idx_sql)
        conn.execute(_RUNS_DDL)
        conn.commit()
    except sqlite3.DatabaseError:
        conn.close()
        raise
    return conn


def db():
    global _db
    if _db is None:
        os.makedirs(DATA_DIR, exist_ok=True)
        try:
            _db = _connect_events()
        except sqlite3.DatabaseError:
            # JAG-413: a corrupted events.db (bad header after a power loss or
            # kill -9) otherwise crashes the server on the very first event. This
            # log is a REPLAY buffer, not the source of truth (session transcripts
            # are), so quarantine the bad file and its WAL sidecars and start fresh
            # rather than fail to boot.
            stamp = time.strftime("%Y%m%d-%H%M%S")
            for suffix in ("", "-wal", "-shm"):
                try:
                    os.replace(DB_PATH + suffix,
                               DB_PATH + ".corrupt-" + stamp + suffix)
                except OSError:
                    pass
            _db = _connect_events()
    return _db


def prune_events(keep=None):
    """JAG-300: keep the durable replay log bounded — newest `keep` rows only.

    Deletes the OLDEST rows beyond the cap in PRUNE_BATCH-sized statements (each
    holds _db_lock only briefly) so pruning a 1M-row log never stalls the server.
    Returns the number of rows removed.
    """
    keep = EVENTS_KEEP if keep is None else int(keep)
    if keep <= 0:
        return 0
    removed = 0
    while True:
        with _db_lock:
            mx = db().execute("SELECT MAX(id) FROM events").fetchone()[0]
            if not mx:
                return removed
            cut = mx - keep
            if cut <= 0:
                return removed
            cur = db().execute(
                "DELETE FROM events WHERE id IN (SELECT id FROM events "
                "WHERE id <= ? ORDER BY id LIMIT ?)", (cut, PRUNE_BATCH))
            db().commit()
            n = cur.rowcount
        removed += n
        if n < PRUNE_BATCH:
            return removed


def truncate(session=None, upto_id=None):
    """JAG-426: drop the events a rewind invalidated (session-scoped, id > upto_id).

    Session filtering mirrors `query_events` — the session id lives inside the JSON
    `data` blob, there is no dedicated column. Returns the number of rows removed.
    """
    if not session or upto_id is None:
        return 0
    try:
        cut = int(upto_id)
    except (TypeError, ValueError):
        return 0
    with _db_lock:
        cur = db().execute("DELETE FROM events WHERE id > ? AND data LIKE ?",
                           (cut, '%"session": "' + str(session) + '"%'))
        db().commit()
        return cur.rowcount


def _start_event_pruning():
    """JAG-300: prune once at start, then every PRUNE_INTERVAL_S (daemon thread)."""
    def loop():
        while True:
            try:
                prune_events()
            except Exception:  # noqa: BLE001
                pass
            time.sleep(PRUNE_INTERVAL_S)
    threading.Thread(target=loop, daemon=True, name="events-prune").start()


# ---------------------------------------------------------------- events ----

_feed_lock = threading.Lock()
_feed = deque(maxlen=MAX_FEED_EVENTS)
_feed_seq = 0
_sse_queues = set()  # each: queue.Queue of str chunks
_sse_lock = threading.Lock()  # guards _sse_queues add/discard/snapshot (SSE fan-out)
# JAG-181: per-session registry of chat turns that are STILL running. The worker
# thread is independent of the HTTP request, so a page refresh/session switch does
# NOT stop the turn — it only drops the browser's SSE channel. This lets the WebUI
# re-attach (see /api/chat/attach) and resume following the live turn.
_ACTIVE_CHAT = {}    # sid -> {"ev0": feed id at turn start, "ts": time}
_ACTIVE_CHAT_LOCK = threading.Lock()

# JAG-201: one chat TURN at a time per session. Two overlapping turns on the same
# session used to race the transcript: read-modify-write on two independent copies
# (lost update) plus the shared ".tmp" collision (unhandled crash → dropped turn).
_TURN_LOCKS = {}
_TURN_LOCKS_GUARD = threading.Lock()


def feed_seq():
    """Current monotonic feed id — the DURABLE high-water mark.

    JAG-426-fix: `_feed_seq` is a process-local counter that resets to 0 on every
    restart, so an anchor stamped from it right after a boot could carry a cut
    BELOW the session's history and a rewind would then drop far too many events.
    Read the durable MAX(id) instead; fall back to the in-memory counter only if
    the store is momentarily unavailable.
    """
    try:
        with _db_lock:
            mx = db().execute("SELECT MAX(id) FROM events").fetchone()[0]
        if mx is not None:
            return int(mx)
    except Exception:  # noqa: BLE001 — never break a caller over the log
        pass
    return _feed_seq


def _turn_lock(sid):
    """Return a re-entrant lock serialising turns for `sid` (created on demand)."""
    with _TURN_LOCKS_GUARD:
        lk = _TURN_LOCKS.get(sid)
        if lk is None:
            lk = threading.RLock()
            _TURN_LOCKS[sid] = lk
        return lk


def turn_active(sid):
    """True when `sid` has a turn in flight right now (Fix2: busy dispatch).

    Checks the _ACTIVE_CHAT registration first (covers the window before the
    worker acquires the turn lock), then probes the per-session turn lock
    without blocking. Never raises; unknown sessions are idle.
    """
    try:
        sid = str(sid or "")
        if not sid:
            return False
        with _ACTIVE_CHAT_LOCK:
            if sid in _ACTIVE_CHAT:
                return True
        lk = _turn_lock(sid)
        got = lk.acquire(blocking=False)
        if got:
            lk.release()
            return False
        return True
    except Exception:  # noqa: BLE001 — a liveness probe must never break a turn
        return False


# JAG-462: event kinds that a helper publishes durably AND whose caller re-emits
# through `on_event` (which also publishes) — so every graph/tool/approval row
# landed in `events.db` (and on `/api/feed`) TWICE. Collapse an IMMEDIATELY
# repeated identical (kind, payload); a legitimate second event always differs or
# is separated by another event. Streaming deltas are never deduped.
_DEDUPE_KINDS = frozenset((
    "graph.node.added", "graph.node.updated", "tool.call", "tool.result",
    "tool.blocked", "approval.request", "approval.auto", "approval.resolved",
    "chat.run", "chat.done", "cost.usage", "model.failover", "model.fallback"))
_last_pub = {"sig": None, "event": None}


def publish(kind, **data):
    """Record an event in the SQLite store + memory cache, fan out to SSE.

    Payload keys never override the envelope: the event's own `id`/`ts` are
    the monotonic feed coordinates, so payloads that carry a domain `id`
    (checkpoints, approvals, ...) are stored under `<kind>_id` instead.
    """
    global _feed_seq
    with _feed_lock:
        # JAG-295-fix: rename the payload's own domain `id`/`ts` BEFORE persisting.
        # Otherwise the SQLite row stored a payload `id`, and on replay
        # (events_since: {**json.loads(r[3])}) it overwrote the integer envelope id
        # — the durable store diverged from the in-memory feed.
        for k in ("id", "ts"):
            if k in data:
                data[k + "_id"] = data.pop(k)
        if kind in _DEDUPE_KINDS:
            try:
                _sig = (kind, json.dumps(data, ensure_ascii=False, sort_keys=True))
            except Exception:  # noqa: BLE001 — an unserialisable payload is never deduped
                _sig = None
            if _sig is not None and _last_pub.get("sig") == _sig:
                return _last_pub.get("event")
            _last_pub["sig"] = _sig
        ts = round(time.time(), 3)
        with _db_lock:
            cur = db().execute("INSERT INTO events(ts, kind, data) VALUES(?,?,?)",
                               (ts, kind, json.dumps(data, ensure_ascii=False)))
            db().commit()
        _feed_seq = cur.lastrowid
        event = {"id": _feed_seq, "ts": ts, "kind": kind, **data}
        _feed.append(event)
        _last_pub["event"] = event
        payload = "id: {id}\nevent: {kind}\ndata: {data}\n\n".format(
            id=event["id"], kind=kind, data=json.dumps(event, ensure_ascii=False)
        )
    with _sse_lock:
        for q in list(_sse_queues):
            try:
                q.put_nowait(payload)
            except Exception:
                pass
    try:
        from longrun.core import matrix as _mtx
        _mtx.call_hook("core", "on_event", event, default=None)
    except Exception:  # noqa: BLE001
        pass
    return event


def turn_begin(sid):
    """JAG-325: bracket ANY turn — stream, sync or in-process MCP — as running.

    `_ACTIVE_CHAT` is the SERVER TRUTH the session list reports as `running`
    (JAG-323). Only the STREAMING path used to register, so a turn driven by the
    synchronous `POST /api/chat` or by the in-process MCP `chat` ran with NO
    graphical signal: the left panel showed the session idle while the model burned
    GPU/tokens — the same "phantom run" (SEVERE). Every entry point MUST call this
    before the model call and `turn_end` after it, whatever the outcome.

    Returns a per-turn token so a newer turn that replaced this registration is
    never un-marked by an older one finishing late.
    """
    tok = object()
    ev0 = feed_seq()
    with _ACTIVE_CHAT_LOCK:
        _ACTIVE_CHAT[sid] = {"ev0": ev0, "ts": time.time(), "tok": tok}
    publish("chat.run", session=sid)
    return tok


def turn_end(sid, tok=None):
    """Release a `turn_begin` bracket and clear the session's running signal."""
    with _ACTIVE_CHAT_LOCK:
        cur = _ACTIVE_CHAT.get(sid)
        if tok is None or (cur or {}).get("tok") is tok:
            _ACTIVE_CHAT.pop(sid, None)
    publish("chat.done", session=sid)


def events_since(last_id, limit=None):
    """Replay events after last_id: memory cache first, SQLite as source of truth.
    An empty in-memory buffer must NOT short-circuit replay — the store is durable.

    JAG-295-fix: `limit` caps the replay to the NEWEST `limit` rows. The durable log
    can hold millions of events; an unbounded replay both materialises the whole log
    server-side and hands the client an enormous backlog frame.
    """
    with _feed_lock:
        if _feed and _feed[0]["id"] <= last_id + 1:
            out = [e for e in _feed if e["id"] > last_id]
            return out[-limit:] if limit else out
    with _db_lock:
        if limit:
            rows = db().execute(
                "SELECT id, ts, kind, data FROM (SELECT id, ts, kind, data FROM events "
                "WHERE id > ? ORDER BY id DESC LIMIT ?) ORDER BY id",
                (last_id, int(limit))).fetchall()
        else:
            rows = db().execute(
                "SELECT id, ts, kind, data FROM events WHERE id > ? ORDER BY id", (last_id,)
            ).fetchall()
    return [{"id": r[0], "ts": r[1], "kind": r[2], **json.loads(r[3])} for r in rows]


def query_events(session=None, kind=None, since=None, until=None, limit=200):
    """JAG-262: filtered history from the durable event log (post-mortem).

    The live feed only replays by id. This answers "what happened to session X"
    (or a kind / time window) after the fact — the evidence needed to diagnose a
    stuck or killed turn. Newest first.
    """
    where, args = [], []
    if kind:
        where.append("kind = ?")
        args.append(kind)
    try:
        if since is not None and str(since) != "":
            where.append("ts >= ?")
            args.append(float(since))
        if until is not None and str(until) != "":
            where.append("ts <= ?")
            args.append(float(until))
    except (TypeError, ValueError):
        pass
    if session:
        where.append("data LIKE ?")
        args.append('%"session": "' + str(session) + '"%')
    sql = "SELECT id, ts, kind, data FROM events"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY id DESC LIMIT ?"
    try:
        lim = max(1, min(int(limit or 200), 5000))
    except (TypeError, ValueError):
        lim = 200
    args.append(lim)
    with _db_lock:
        rows = db().execute(sql, args).fetchall()
    return [{"id": r[0], "ts": r[1], "kind": r[2], "data": json.loads(r[3])} for r in rows]

