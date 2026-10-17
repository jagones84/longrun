"""Shared SQLite opener for the two index stores (JAG-483).

The per-workspace codebase index and the global knowledge base are separate
databases with separate schemas, but they must be opened EXACTLY the same way:
the default 5 s lock timeout is too short for a build that runs while a search
reads, ``Row`` access is what every query in both stores expects, and WAL is what
makes a concurrent reader possible at all. Two copies of this opener had already
drifted.

Stdlib-only.
"""

import sqlite3


def connect(path, timeout=30):
    """Open ``path`` for the index stores: WAL journal, dict-like rows, long lock wait."""
    db = sqlite3.connect(path, timeout=timeout)
    db.row_factory = sqlite3.Row
    try:
        db.execute("PRAGMA journal_mode=WAL")
    except Exception:  # noqa: BLE001 — a filesystem without WAL still works
        pass
    return db
