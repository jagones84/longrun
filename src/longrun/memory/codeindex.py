"""CODEBASE index — PER WORKSPACE (JAG-400) — stdlib only.

One sqlite DB per workspace PATH (``data/codebase/<hash>.db``), kept OUTSIDE the
user's project in the app data dir. Scoped exactly like project rules: two
different workspaces have two different, fully isolated indexes. Retrieval is
SQLite **FTS5** (``bm25()`` + ``snippet()``); vectors are optional (``model.embed``)
and make retrieval hybrid (bm25 + cosine fused with RRF).
"""
import hashlib
import os
import re
import sqlite3
import threading
import time

from longrun.memory import chunk as _chunk
from longrun.memory import indexcfg as _cfg
from longrun.memory import vectors as _vec
from longrun.model import embed as _embed
from longrun.util import paths

LOCK = threading.RLock()
# JAG-415b: minimum age before an auto-index refresh re-walks the whole workspace.
FRESH_WINDOW_S = 15


def _slug(ws):
    return hashlib.sha1(os.path.realpath(ws).encode("utf-8", "replace")).hexdigest()[:16]


def db_path(ws):
    """The DB for this workspace (deterministic per path, outside the project)."""
    os.makedirs(paths.CODEBASE_DIR, exist_ok=True)
    return os.path.join(paths.CODEBASE_DIR, _slug(ws) + ".db")


def _connect(ws):
    """Open this workspace's index DB with the shared opener (JAG-483)."""
    from longrun.memory import sqlkit
    return sqlkit.connect(db_path(ws))


def _init(db):
    db.executescript(
        """
        CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT);
        CREATE TABLE IF NOT EXISTS files(path TEXT PRIMARY KEY, mtime REAL, size INTEGER, hash TEXT, lang TEXT);
        CREATE TABLE IF NOT EXISTS chunks(
            id INTEGER PRIMARY KEY, path TEXT, lang TEXT, kind TEXT, name TEXT,
            start INTEGER, end INTEGER, tokens INTEGER, text TEXT, vec BLOB);
        CREATE INDEX IF NOT EXISTS chunks_path ON chunks(path);
        """
    )
    try:
        db.execute("CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(text, name, path)")
        db.commit()
        return True
    except sqlite3.OperationalError:
        db.commit()
        return False


def _has_fts(db):
    try:
        row = db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='chunks_fts'").fetchone()
        return bool(row)
    except Exception:  # noqa: BLE001
        return False


def _set_meta(db, pairs):
    import json
    for k, v in pairs.items():
        db.execute("INSERT OR REPLACE INTO meta(key, value) VALUES(?,?)", (k, json.dumps(v)))
    db.commit()


def _get_meta(db, key, default=None):
    import json
    try:
        row = db.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
        return json.loads(row["value"]) if row else default
    except Exception:  # noqa: BLE001
        return default


def _drop_path(db, path):
    ids = [r["id"] for r in db.execute("SELECT id FROM chunks WHERE path=?", (path,))]
    if ids and _has_fts(db):
        db.executemany("DELETE FROM chunks_fts WHERE rowid=?", [(i,) for i in ids])
    db.execute("DELETE FROM chunks WHERE path=?", (path,))
    db.execute("DELETE FROM files WHERE path=?", (path,))


def _insert_chunks(db, path, lang, kind, pieces, fts):
    ids = []
    for p in pieces or []:
        text = p.get("text") or ""
        if not text.strip():
            continue
        cur = db.execute(
            "INSERT INTO chunks(path, lang, kind, name, start, end, tokens, text) VALUES(?,?,?,?,?,?,?,?)",
            (path, lang, kind, p.get("name") or "", int(p.get("start") or 0),
             int(p.get("end") or 0), max(1, len(text) // 4), text))
        cid = cur.lastrowid
        if fts:
            db.execute("INSERT INTO chunks_fts(rowid, text, name, path) VALUES(?,?,?,?)",
                       (cid, text, p.get("name") or "", path))
        ids.append(cid)
    return ids


def build(ws, force=False):
    """(Re)index the workspace incrementally. Returns the status dict."""
    cfg = _cfg.load_config()
    globs = cfg
    maxk = cfg.get("max_file_kb") or 512
    with LOCK:
        db = _connect(ws)
        try:
            fts = _init(db)
            ws = os.path.realpath(ws)
            seen = set()
            for rel, abspath, lang, kind in _chunk.walk(ws, globs):
                seen.add(abspath)
                try:
                    st = os.stat(abspath)
                except OSError:
                    continue
                row = db.execute("SELECT mtime, size FROM files WHERE path=?", (abspath,)).fetchone()
                # JAG-415b: compare the RAW mtimes (float), not int()-truncated seconds,
                # or a sub-second edit is missed and stale chunks survive.
                if row and not force and abs(float(row["mtime"]) - st.st_mtime) < 1e-6 and row["size"] == st.st_size:
                    continue
                text = _chunk.read_text(abspath, maxk)
                if text is None:
                    continue
                _drop_path(db, abspath)
                ids = _insert_chunks(db, abspath, lang, kind, _chunk.chunk_file(text, lang, kind, cfg), fts)
                db.execute("INSERT OR REPLACE INTO files(path, mtime, size, hash, lang) VALUES(?,?,?,?,?)",
                           (abspath, st.st_mtime, st.st_size,
                            hashlib.sha1(text.encode("utf-8", "replace")).hexdigest(), lang))
                del ids
            for r in db.execute("SELECT path FROM files").fetchall():
                if r["path"] not in seen:
                    _drop_path(db, r["path"])
            em = _cfg.embed_model()
            embed_err = None
            if em:
                # JAG-403j: a failing embedder (missing key / no local server) must
                # NEVER break the build — degrade to bm25-only.
                # JAG-403k: but the failure is RECORDED (meta) instead of silently
                # swallowed, so `status()`/the UI can show that vectors are missing.
                try:
                    rows = [(r["id"], r["text"]) for r in db.execute("SELECT id, text FROM chunks WHERE vec IS NULL")]
                    _embed_chunks(db, rows, em, int(cfg.get("embed_batch") or 32),
                                  scope="codebase", scope_id=str(ws), op="build")
                except Exception as e:  # noqa: BLE001
                    embed_err = "%s: %s" % (type(e).__name__, e)
            db.commit()
            _set_meta(db, {"built_at": time.time(), "embed_model": em, "dim": _dim(db),
                           "fts": bool(fts), "workspace": ws, "embed_error": embed_err})
            return status(ws)
        finally:
            db.close()


_vec_blob = _vec.vec_blob
_blob_vec = _vec.blob_vec
_dim = _vec.dim
_embed_chunks = _vec.embed_chunks
_cos = _vec.cos


def ensure_fresh(ws):
    """JAG-415: incrementally refresh the workspace index, WAITING for any build
    already in flight (even one started by another agent or thread).

    Called by the agent's ``index`` tool right before a search, so a search never
    runs against a stale or half-built index: concurrent agents on the same
    workspace serialize on ``build``'s lock. A no-op when auto-index is disabled.
    A build failure must NEVER break the search — it degrades to the existing
    index (the caller searches whatever is there).
    """
    if not _cfg.auto_index():
        return None
    # JAG-415b: cheap debounce. ``build`` walks the WHOLE workspace tree, so a burst
    # of searches must not re-walk it every time; skip a rebuild that ran moments ago.
    try:
        st = status(ws)
        built = st.get("built_at")
        if built and (time.time() - float(built)) < FRESH_WINDOW_S:
            return st
    except Exception:  # noqa: BLE001 — a bad status must not block the build
        pass
    try:
        return build(ws)
    except Exception:  # noqa: BLE001 — the search must still run on the old index
        return None


def search(ws, query, k=8, kind=None, embed_model=None):
    """Top-k chunks for `query` in THIS workspace. bm25, or bm25+cosine (RRF)."""
    query = str(query or "").strip()
    out = {"query": query, "results": [], "mode": "bm25"}
    if not query:
        return out
    db = _connect(ws)
    try:
        _init(db)
        if not db.execute("SELECT 1 FROM chunks LIMIT 1").fetchone():
            return out
        terms = re.findall(r"[A-Za-z0-9_]{2,}", query)
        rows = []
        if terms and _has_fts(db):
            fts_q = " OR ".join('"%s"' % t for t in terms)
            sql = ("SELECT c.id, c.path, c.lang, c.kind, c.name, c.start, c.end, c.text, "
                   "bm25(chunks_fts, 1.0, 3.0, 2.0) AS rank, "
                   "snippet(chunks_fts, 0, '\u00ab', '\u00bb', '\u2026', 14) AS snip "
                   "FROM chunks_fts JOIN chunks c ON c.id = chunks_fts.rowid "
                   "WHERE chunks_fts MATCH ?")
            args = [fts_q]
            if kind:
                sql += " AND c.kind = ?"
                args.append(kind)
            sql += " ORDER BY rank LIMIT ?"
            args.append(max(k * 5, 30))
            rows = [dict(r) for r in db.execute(sql, args)]
        elif terms:
            like = " OR ".join(["text LIKE ?"] * len(terms))
            args = ["%" + t + "%" for t in terms]
            sql = ("SELECT id, path, lang, kind, name, start, end, text, 0 AS rank, "
                   "substr(text,1,160) AS snip FROM chunks WHERE " + like)
            if kind:
                sql += " AND kind=?"
                args.append(kind)
            sql += " LIMIT ?"
            args.append(max(k * 5, 30))
            rows = [dict(r) for r in db.execute(sql, args)]
        else:
            return out
        ref = embed_model if embed_model is not None else _cfg.embed_model()
        if ref and rows:
            qv_out = _embed.embed_texts([query], model=ref)
            qv = qv_out[0] if qv_out else None
            if qv:
                marks = ",".join("?" * len(rows))
                # JAG-403k: `row` (not `r`) — `r` is a function-local from the
                # `for r in rows[:k]` loop below, so using it here raised
                # UnboundLocalError the first time the hybrid path actually ran.
                cand = {row["id"]: _blob_vec(row["vec"]) for row in db.execute(
                    "SELECT id, vec FROM chunks WHERE id IN (%s) AND vec IS NOT NULL" % marks,
                    [x["id"] for x in rows])}
                if cand:
                    K = 60
                    lex = {r["id"]: i for i, r in enumerate(rows)}
                    sem = sorted(((_cos(qv[0], v), cid) for cid, v in cand.items()), reverse=True)
                    sem_rank = {cid: i for i, (_, cid) in enumerate(sem)}
                    for r in rows:
                        r["rrf"] = 1.0 / (K + lex[r["id"]]) + 1.0 / (K + sem_rank.get(r["id"], 10 ** 6))
                    rows.sort(key=lambda r: -r["rrf"])
                    out["mode"] = "hybrid"
        for r in rows[:k]:
            score = r.get("rrf")
            out["results"].append({
                "path": r["path"], "name": r["name"], "kind": r["kind"], "lang": r["lang"],
                "start": r["start"], "end": r["end"],
                "score": round(score, 6) if score is not None else round(-(r["rank"] or 0), 6),
                "snippet": r.get("snip") or (r["text"] or "")[:200],
            })
        return out
    finally:
        db.close()


def status(ws):
    p = db_path(ws)
    out = {"workspace": os.path.realpath(ws), "db": p, "exists": os.path.isfile(p),
           "embed_model": _cfg.embed_model(), "files": 0, "chunks": 0, "embedded": 0,
           "dim": 0, "built_at": None, "fts": False, "size_kb": 0, "embed_error": None}
    if not out["exists"]:
        return out
    try:
        out["size_kb"] = round(os.path.getsize(p) / 1024.0, 1)
    except OSError:
        pass
    db = _connect(ws)
    try:
        _init(db)
        out["files"] = db.execute("SELECT count(*) c FROM files").fetchone()["c"]
        out["chunks"] = db.execute("SELECT count(*) c FROM chunks").fetchone()["c"]
        out["embedded"] = db.execute("SELECT count(*) c FROM chunks WHERE vec IS NOT NULL").fetchone()["c"]
        out["dim"] = _dim(db)
        out["built_at"] = _get_meta(db, "built_at")
        out["fts"] = bool(_get_meta(db, "fts", _has_fts(db)))
        out["embed_error"] = _get_meta(db, "embed_error")
        return out
    finally:
        db.close()


def list_files(ws):
    """Every indexed file: path, language, chunk count."""
    db = _connect(ws)
    try:
        _init(db)
        rows = db.execute(
            "SELECT f.path AS path, f.lang AS lang, count(c.id) AS chunks "
            "FROM files f LEFT JOIN chunks c ON c.path = f.path "
            "GROUP BY f.path ORDER BY chunks DESC, f.path").fetchall()
        return {"workspace": os.path.realpath(ws), "files": [dict(r) for r in rows]}
    finally:
        db.close()


def clear(ws):
    with LOCK:
        db = _connect(ws)
        try:
            for t in ("chunks", "chunks_fts", "files", "meta"):
                try:
                    db.execute("DROP TABLE IF EXISTS %s" % t)
                except sqlite3.OperationalError:
                    pass
            db.commit()
            _init(db)
            return {"ok": True, "workspace": os.path.realpath(ws)}
        finally:
            db.close()
