"""Append-only embedding cost log (JAG-403) — stdlib only.

Every embed batch writes ONE row, tagged with the scope that caused it
(``codebase/<workspace>`` for the per-workspace index, ``notebook/<id>``
for the global knowledge base). Aggregations are computed on read — the
log is small (one row per batch, not per chunk) and never pruned.
"""
import csv
import io
import os
import sqlite3
import threading
import time

from longrun.util import paths

DB_PATH = os.path.join(paths.EMBEDDING_DIR, "costs.db")
LOCK = threading.RLock()

_SCHEMA = """
CREATE TABLE IF NOT EXISTS batches (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts REAL NOT NULL,
    model TEXT NOT NULL,
    provider TEXT,
    tokens INTEGER NOT NULL,
    est_cost_usd REAL,
    real_cost_usd REAL,
    scope TEXT,
    scope_id TEXT,
    op TEXT
);
CREATE INDEX IF NOT EXISTS batches_model_ts ON batches(model, ts);
CREATE INDEX IF NOT EXISTS batches_scope ON batches(scope, scope_id);
"""


def _conn():
    os.makedirs(paths.EMBEDDING_DIR, exist_ok=True)
    c = sqlite3.connect(DB_PATH, timeout=10, isolation_level=None)
    c.row_factory = sqlite3.Row
    c.executescript(_SCHEMA)
    return c


def clear():
    """Wipe the log (used by tests)."""
    with LOCK:
        c = _conn()
        c.execute("DELETE FROM batches")
        c.close()


def record(model, provider=None, tokens=0, est_cost_usd=None,
           real_cost_usd=None, scope=None, scope_id=None, op=None):
    """Append one row. Either ``est_cost_usd`` or ``real_cost_usd`` should be set:
    estimated for direct providers, exact for OpenRouter (which returns
    ``usage.cost`` in USD)."""
    with LOCK:
        c = _conn()
        c.execute(
            "INSERT INTO batches(ts, model, provider, tokens, est_cost_usd, "
            "real_cost_usd, scope, scope_id, op) VALUES (?,?,?,?,?,?,?,?,?)",
            (time.time(), str(model or ""), str(provider or ""), int(tokens or 0),
             est_cost_usd, real_cost_usd, str(scope or ""), str(scope_id or ""),
             str(op or "")),
        )
        c.close()


def list_all(scope=None, scope_id=None, model=None, since_ts=None,
             limit=10000):
    """All rows (most recent first), optionally filtered by scope/model/since."""
    with LOCK:
        c = _conn()
        where = []
        args = []
        if scope:
            where.append("scope=?")
            args.append(scope)
        if scope_id:
            where.append("scope_id=?")
            args.append(scope_id)
        if model:
            where.append("model=?")
            args.append(model)
        if since_ts is not None:
            where.append("ts>=?")
            args.append(float(since_ts))
        sql = "SELECT * FROM batches"
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY id DESC LIMIT ?"
        args.append(int(limit))
        rows = c.execute(sql, args).fetchall()
        c.close()
        return [dict(r) for r in rows]


def aggregate(scope=None, scope_id=None):
    """Roll-up: total tokens, total cost (est or real per row), by_model, by_day."""
    with LOCK:
        c = _conn()
        where = []
        args = []
        if scope:
            where.append("scope=?")
            args.append(scope)
        if scope_id:
            where.append("scope_id=?")
            args.append(scope_id)
        clause = (" WHERE " + " AND ".join(where)) if where else ""
        rows = c.execute(
            "SELECT model, SUM(tokens) AS tokens, "
            "SUM(COALESCE(est_cost_usd,0)+COALESCE(real_cost_usd,0)) AS cost, "
            "SUM(CASE WHEN real_cost_usd IS NOT NULL THEN 1 ELSE 0 END) AS real_n, "
            "SUM(COALESCE(real_cost_usd,0)) AS real_cost_usd "
            "FROM batches" + clause + " GROUP BY model ORDER BY cost DESC",
            args,
        ).fetchall()
        total_tokens = c.execute(
            "SELECT COALESCE(SUM(tokens),0) AS t FROM batches" + clause, args
        ).fetchone()["t"]
        total_cost = c.execute(
            "SELECT COALESCE(SUM(COALESCE(est_cost_usd,0)+COALESCE(real_cost_usd,0)),0) "
            "AS c FROM batches" + clause, args
        ).fetchone()["c"]
        # Last 30 days
        days = c.execute(
            "SELECT strftime('%Y-%m-%d', ts, 'unixepoch') AS d, "
            "SUM(tokens) AS tokens, "
            "SUM(COALESCE(est_cost_usd,0)+COALESCE(real_cost_usd,0)) AS cost "
            "FROM batches" + clause + " "
            "GROUP BY d ORDER BY d DESC LIMIT 30", args
        ).fetchall()
        c.close()
    by_model = [
        {"model": r["model"], "tokens": int(r["tokens"] or 0),
         "total_cost_usd": float(r["cost"] or 0.0),
         "real_n": int(r["real_n"] or 0),
         "real_cost_usd": float(r["real_cost_usd"] or 0.0)}
        for r in rows
    ]
    return {
        "total_tokens": int(total_tokens or 0),
        "total_cost_usd": float(total_cost or 0.0),
        "by_model": by_model,
        "by_day": [{"day": r["d"], "tokens": int(r["tokens"] or 0),
                    "cost_usd": float(r["cost"] or 0.0)} for r in days],
    }


def export_csv():
    """Dump the whole log as a CSV string (most recent first)."""
    rows = list_all(limit=1_000_000)
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(["ts_iso", "model", "provider", "tokens", "est_cost_usd",
                "real_cost_usd", "scope", "scope_id", "op"])
    import datetime as _dt
    for r in rows:
        ts_iso = _dt.datetime.utcfromtimestamp(r["ts"]).isoformat() + "Z"
        w.writerow([ts_iso, r["model"], r["provider"] or "",
                    r["tokens"], r["est_cost_usd"] if r["est_cost_usd"] is not None else "",
                    r["real_cost_usd"] if r["real_cost_usd"] is not None else "",
                    r["scope"] or "", r["scope_id"] or "", r["op"] or ""])
    return out.getvalue()
