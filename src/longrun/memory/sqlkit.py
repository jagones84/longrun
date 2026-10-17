"""Shared SQLite primitives for the two index stores (JAG-483).

The per-workspace codebase index and the global knowledge base are separate
databases with separate schemas, but the SAME machinery runs over both: they must
be opened EXACTLY the same way (the default 5 s lock timeout is too short for a
build that runs while a search reads, ``Row`` access is what every query expects,
WAL is what makes a concurrent reader possible at all), they detect FTS5 the same
way, they build the same FTS5 MATCH expression, they insert chunk rows the same
way, and they drop + rebuild their tables the same way. Copies of each had
already drifted between the two modules.

Stdlib-only.
"""

import re
import sqlite3

# The chunk columns both stores share; the knowledge base prepends `source`.
_CHUNK_TAIL_COLS = ("path", "lang", "kind", "name", "start", "end", "tokens", "text")


def connect(path, timeout=30):
    """Open ``path`` for the index stores: WAL journal, dict-like rows, long lock wait."""
    db = sqlite3.connect(path, timeout=timeout)
    db.row_factory = sqlite3.Row
    try:
        db.execute("PRAGMA journal_mode=WAL")
    except Exception:  # noqa: BLE001 — a filesystem without WAL still works
        pass
    return db


def has_fts(db, table="chunks_fts"):
    """True when this DB carries the FTS5 shadow table.

    A sqlite built without FTS5 still works — the caller falls back to ``LIKE``.
    """
    try:
        return bool(db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone())
    except Exception:  # noqa: BLE001
        return False


def terms(query, min_len=2):
    """Word tokens of a lexical query, identical for both stores."""
    return re.findall(r"[A-Za-z0-9_]{%d,}" % min_len, query)


def fts_match(terms):
    """FTS5 MATCH expression: each token as a verbatim phrase, OR-joined."""
    return " OR ".join('"%s"' % t for t in terms)


def insert_chunks(db, pieces, path, lang, kind, fts, source=None):
    """Insert chunk ``pieces`` into an index store's ``chunks`` table (+ FTS shadow).

    ``source`` is the knowledge base's leading column; the codebase index has no
    such column. Returns the new row ids so the caller can post-process them.
    """
    lead = ("source",) if source is not None else ()
    sql = "INSERT INTO chunks(%s) VALUES(%s)" % (
        ", ".join(lead + _CHUNK_TAIL_COLS),
        ", ".join("?" * (len(lead) + len(_CHUNK_TAIL_COLS))))
    lead_vals = (source,) if source is not None else ()
    ids = []
    for p in pieces or []:
        text = p.get("text") or ""
        if not text.strip():
            continue
        cur = db.execute(sql, lead_vals + (
            path, lang, kind, p.get("name") or "", int(p.get("start") or 0),
            int(p.get("end") or 0), max(1, len(text) // 4), text))
        if fts:
            db.execute("INSERT INTO chunks_fts(rowid, text, name, path) VALUES(?,?,?,?)",
                       (cur.lastrowid, text, p.get("name") or "", path))
        ids.append(cur.lastrowid)
    return ids


def reset_tables(db, tables, init):
    """Drop every index table (committing), then rebuild the schema through ``init``."""
    for t in tables:
        try:
            db.execute("DROP TABLE IF EXISTS %s" % t)
        except sqlite3.OperationalError:
            pass
    db.commit()
    init(db)
