"""KNOWLEDGE base — GLOBAL, notebook-scoped (JAG-400/401) — stdlib only.

A single, GLOBAL sqlite DB (``data/knowledge/knowledge.db``) kept OUTSIDE the repo.
It is a knowledge base you build once and every session/agent can query — SEPARATE
from the per-workspace codebase index and from the session store. Content lives in
**notebooks**: each notebook holds **sources** (a URL, a local file/folder, or pasted
text). Retrieval is SQLite FTS5 (``bm25()`` + ``snippet()``); vectors are optional.

Web discovery (NotebookLM-style): ``discover(query)`` runs a web search and returns
candidate URLs; ``import_candidates(notebook, urls)`` feeds each URL through the same
ingestion pipeline into the chosen notebook.
"""
import json
import os
import re
import sqlite3
import threading
import time
import uuid

from longrun.memory import chunk as _chunk
from longrun.memory import docio as _docio
from longrun.memory import indexcfg as _cfg
from longrun.memory import vectors as _vec
from longrun.util import paths

LOCK = threading.RLock()
DB_NAME = "knowledge.db"
DEFAULT_ID = "default"
DEFAULT_NAME = "Default"

# Indirections so tests (and future providers) can swap them without network.
fetch_text = _chunk.fetch_url


def _default_searcher(query, n):
    from longrun.tools import tools as _tools
    return _tools._web_search(query, n)


SEARCH = _default_searcher


# ---------------------------------------------------------------------- store --
def db_path():
    os.makedirs(paths.KNOWLEDGE_DIR, exist_ok=True)
    return os.path.join(paths.KNOWLEDGE_DIR, DB_NAME)


def _connect():
    db = sqlite3.connect(db_path(), timeout=30)
    db.row_factory = sqlite3.Row
    try:
        db.execute("PRAGMA journal_mode=WAL")
    except Exception:  # noqa: BLE001
        pass
    return db


def _init(db):
    db.executescript(
        """
        CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT);
        CREATE TABLE IF NOT EXISTS notebooks(id TEXT PRIMARY KEY, name TEXT, created REAL);
        CREATE TABLE IF NOT EXISTS sources(
            id TEXT PRIMARY KEY, notebook TEXT, kind TEXT, ref TEXT, title TEXT,
            added REAL, chunks INTEGER);
        CREATE TABLE IF NOT EXISTS chunks(
            id INTEGER PRIMARY KEY, source TEXT, path TEXT, lang TEXT, kind TEXT,
            name TEXT, start INTEGER, end INTEGER, tokens INTEGER, text TEXT, vec BLOB);
        CREATE INDEX IF NOT EXISTS chunks_source ON chunks(source);
        CREATE INDEX IF NOT EXISTS sources_notebook ON sources(notebook);
        """
    )
    fts = True
    try:
        db.execute("CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(text, name, path)")
    except sqlite3.OperationalError:
        fts = False
    db.execute("INSERT OR IGNORE INTO notebooks(id, name, created) VALUES(?,?,?)",
               (DEFAULT_ID, DEFAULT_NAME, time.time()))
    db.commit()
    return fts


def _has_fts(db):
    try:
        return bool(db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='chunks_fts'").fetchone())
    except Exception:  # noqa: BLE001
        return False


def _insert_chunks(db, sid, path, lang, kind, pieces, fts):
    n = 0
    for p in pieces or []:
        text = p.get("text") or ""
        if not text.strip():
            continue
        cur = db.execute(
            "INSERT INTO chunks(source, path, lang, kind, name, start, end, tokens, text) "
            "VALUES(?,?,?,?,?,?,?,?,?)",
            (sid, path, lang, kind, p.get("name") or "", int(p.get("start") or 0),
             int(p.get("end") or 0), max(1, len(text) // 4), text))
        if fts:
            db.execute("INSERT INTO chunks_fts(rowid, text, name, path) VALUES(?,?,?,?)",
                       (cur.lastrowid, text, p.get("name") or "", path))
        n += 1
    return n


def _drop_source(db, sid):
    if _has_fts(db):
        for r in db.execute("SELECT id FROM chunks WHERE source=?", (sid,)):
            db.execute("DELETE FROM chunks_fts WHERE rowid=?", (r["id"],))
    db.execute("DELETE FROM chunks WHERE source=?", (sid,))
    db.execute("DELETE FROM sources WHERE id=?", (sid,))


# ------------------------------------------------------------------ notebooks --
def list_notebooks():
    db = _connect()
    try:
        _init(db)
        rows = db.execute("SELECT id, name, created FROM notebooks ORDER BY created").fetchall()
        counts = {r["notebook"]: r["c"] for r in db.execute(
            "SELECT notebook, count(*) c FROM sources GROUP BY notebook")}
        return [{"id": r["id"], "name": r["name"], "created": r["created"],
                 "sources": counts.get(r["id"], 0)} for r in rows]
    finally:
        db.close()


def create_notebook(name):
    name = str(name or "").strip()
    if not name:
        return {"ok": False, "error": "notebook name required"}
    nid = "nb_" + uuid.uuid4().hex[:8]
    with LOCK:
        db = _connect()
        try:
            _init(db)
            db.execute("INSERT INTO notebooks(id, name, created) VALUES(?,?,?)", (nid, name, time.time()))
            db.commit()
            return {"ok": True, "id": nid, "name": name}
        finally:
            db.close()


def rename_notebook(nid, name):
    name = str(name or "").strip()
    if not name:
        return {"ok": False, "error": "notebook name required"}
    with LOCK:
        db = _connect()
        try:
            _init(db)
            cur = db.execute("UPDATE notebooks SET name=? WHERE id=?", (name, nid))
            db.commit()
            return {"ok": bool(cur.rowcount), "id": nid, "name": name}
        finally:
            db.close()


def delete_notebook(nid):
    if nid == DEFAULT_ID:
        return {"ok": False, "error": "the default notebook cannot be deleted"}
    with LOCK:
        db = _connect()
        try:
            _init(db)
            for r in db.execute("SELECT id FROM sources WHERE notebook=?", (nid,)).fetchall():
                _drop_source(db, r["id"])
            db.execute("DELETE FROM notebooks WHERE id=?", (nid,))
            db.commit()
            return {"ok": True, "removed": nid}
        finally:
            db.close()


def _notebook_exists(db, nid):
    return bool(db.execute("SELECT 1 FROM notebooks WHERE id=?", (nid,)).fetchone())


def _resolve_id_db(db, ref):
    """Map a notebook ID **or** its human NAME to the canonical ID (JAG-427 fix).

    The agent interface lists notebooks by NAME but scopes search by ID, so a name
    passed as the scope silently returned zero hits. Resolve names to their IDs here
    so both spellings work; an unknown value is returned unchanged (caller decides).
    """
    ref = str(ref or "").strip()
    if not ref:
        return ref
    if _notebook_exists(db, ref):
        return ref
    row = db.execute("SELECT id FROM notebooks WHERE name=?", (ref,)).fetchone()
    return row["id"] if row else ref


# -------------------------------------------------------------------- sources --
def _ingest(db, sid, notebook, kind, ref, title, pieces, lang, path, cfg, fts):
    n = _insert_chunks(db, sid, path, lang, "doc" if kind != "code" else "code", pieces, fts)
    db.execute("INSERT OR REPLACE INTO sources(id, notebook, kind, ref, title, added, chunks) "
               "VALUES(?,?,?,?,?,?,?)", (sid, notebook, kind, ref, title, time.time(), n))
    return n


def add_source(notebook, ref):
    """Index ONE source (URL / file / folder) into `notebook`. Returns a result dict."""
    notebook = notebook or DEFAULT_ID
    ref = str(ref or "").strip()
    if not ref:
        return {"ok": False, "error": "empty source"}
    cfg = _cfg.load_config()
    with LOCK:
        db = _connect()
        try:
            fts = _init(db)
            notebook = _resolve_id_db(db, notebook)   # JAG-427: accept a name or an id
            if not _notebook_exists(db, notebook):
                return {"ok": False, "error": "no such notebook: %s" % notebook}
            sid = "src:" + uuid.uuid4().hex[:10]
            cl = int(cfg.get("chunk_lines") or 60)
            ov = int(cfg.get("overlap_lines") or 8)
            if ref.startswith("http://") or ref.startswith("https://"):
                try:
                    text = fetch_text(ref)
                except Exception as e:  # noqa: BLE001
                    return {"ok": False, "error": "fetch failed: %s" % e, "ref": ref}
                n = _ingest(db, sid, notebook, "url", ref, ref, _chunk.chunk_doc(text, cl, ov),
                            "markdown", ref, cfg, fts)
                kind = "url"
            else:
                ap = os.path.realpath(os.path.expanduser(ref))
                if not os.path.exists(ap):
                    return {"ok": False, "error": "path not found: %s" % ref, "ref": ref}
                if os.path.isdir(ap):
                    targets = [abs_ for _rel, abs_, _l, _k in _chunk.walk(ap, cfg)]
                    base = os.path.basename(ap) or ap
                else:
                    lang0, _kind0 = _chunk.lang_for(ap)
                    targets = [ap] if lang0 else []
                    base = os.path.basename(ap)
                n = 0
                for fp in targets:
                    text = _chunk.read_text(fp, cfg.get("max_file_kb") or 512)
                    if text is None:
                        continue
                    lang, knd = _chunk.lang_for(fp)
                    n += _insert_chunks(db, sid, fp, lang or "text", knd or "doc",
                                        _chunk.chunk_file(text, lang or "text", knd or "doc", cfg), fts)
                db.execute("INSERT OR REPLACE INTO sources(id, notebook, kind, ref, title, added, chunks) "
                           "VALUES(?,?,?,?,?,?,?)", (sid, notebook, "path", ref, base, time.time(), n))
                kind = "path"
            em = _cfg.embed_model()
            embed_err = None
            if em and n:
                # JAG-403j: a failing embedder must never break the ingest — the
                # source is still indexed (bm25) even if the vectors cannot be built.
                # JAG-403k: the failure is REPORTED back in the result, not swallowed.
                try:
                    rows = [(r["id"], r["text"]) for r in db.execute(
                        "SELECT id, text FROM chunks WHERE source=? AND vec IS NULL", (sid,))]
                    _vec.embed_chunks(db, rows, em, int(cfg.get("embed_batch") or 32),
                                      scope="notebook", scope_id=str(notebook),
                                      op="add_source")
                except Exception as e:  # noqa: BLE001
                    embed_err = "%s: %s" % (type(e).__name__, e)
            db.commit()
            embedded = db.execute("SELECT count(*) c FROM chunks WHERE source=? AND vec IS NOT NULL",
                                  (sid,)).fetchone()["c"]
            if em and n and embedded == 0 and not embed_err:
                # the embedder ran but stored nothing (endpoint/key/model unavailable) —
                # surface it instead of silently shipping a lexical-only source.
                embed_err = "embedding produced no vectors (endpoint, key or model unavailable)"
            return {"ok": True, "source_id": sid, "notebook": notebook, "kind": kind,
                    "ref": ref, "chunks": n, "embedded": embedded, "embed_error": embed_err,
                    "title": ref if kind == "url" else base}
        finally:
            db.close()


def add_text(notebook, title, text):
    """Add a pasted-text source to a notebook."""
    notebook = notebook or DEFAULT_ID
    title = str(title or "note").strip() or "note"
    text = str(text or "")
    if not text.strip():
        return {"ok": False, "error": "empty text"}
    cfg = _cfg.load_config()
    with LOCK:
        db = _connect()
        try:
            fts = _init(db)
            notebook = _resolve_id_db(db, notebook)   # JAG-427: accept a name or an id
            if not _notebook_exists(db, notebook):
                return {"ok": False, "error": "no such notebook: %s" % notebook}
            sid = "src:" + uuid.uuid4().hex[:10]
            cl = int(cfg.get("chunk_lines") or 60)
            ov = int(cfg.get("overlap_lines") or 8)
            n = _ingest(db, sid, notebook, "text", title, title,
                        _chunk.chunk_doc(text, cl, ov), "markdown", title, cfg, fts)
            db.execute("UPDATE sources SET chunks=? WHERE id=?", (n, sid))
            em = _cfg.embed_model()
            embed_err = None
            if em and n:
                try:
                    rows = [(r["id"], r["text"]) for r in db.execute(
                        "SELECT id, text FROM chunks WHERE source=? AND vec IS NULL", (sid,))]
                    _vec.embed_chunks(db, rows, em, int(cfg.get("embed_batch") or 32),
                                      scope="notebook", scope_id=str(notebook),
                                      op="add_text")
                except Exception as e:  # noqa: BLE001
                    embed_err = "%s: %s" % (type(e).__name__, e)
            db.commit()
            embedded = db.execute("SELECT count(*) c FROM chunks WHERE source=? AND vec IS NOT NULL",
                                  (sid,)).fetchone()["c"]
            return {"ok": True, "source_id": sid, "notebook": notebook, "kind": "text",
                    "ref": title, "chunks": n, "embedded": embedded, "embed_error": embed_err,
                    "title": title}
        finally:
            db.close()


def add_sources(notebook, values):
    """Index MANY sources from a multi-line string (one URL/path per line) or a list."""
    if isinstance(values, str):
        refs = [ln.strip() for ln in values.splitlines()]
    else:
        refs = [str(v).strip() for v in (values or [])]
    refs = [r for r in dict.fromkeys(refs) if r]
    results = [add_source(notebook, r) for r in refs]
    ok = [x for x in results if x.get("ok")]
    return {"ok": bool(ok) and len(ok) == len(refs), "added": len(ok), "total": len(refs),
            "chunks": sum(x.get("chunks", 0) for x in ok), "results": results}


def add_source_text(notebook, ref, text, title=None):
    """Ingest pre-fetched text as a URL source. Used by the research executor
    so the same body is NOT re-fetched."""
    notebook = notebook or DEFAULT_ID
    ref = str(ref or "").strip()
    text = str(text or "")
    if not ref or not text.strip():
        return {"ok": False, "error": "ref and text required"}
    cfg = _cfg.load_config()
    with LOCK:
        db = _connect()
        try:
            fts = _init(db)
            notebook = _resolve_id_db(db, notebook)   # JAG-427: accept a name or an id
            if not _notebook_exists(db, notebook):
                return {"ok": False, "error": "no such notebook: %s" % notebook}
            sid = "src:" + uuid.uuid4().hex[:10]
            cl = int(cfg.get("chunk_lines") or 60)
            ov = int(cfg.get("overlap_lines") or 8)
            n = _ingest(db, sid, notebook, "url", ref, title or ref,
                        _chunk.chunk_doc(text, cl, ov), "markdown", ref, cfg, fts)
            em = _cfg.embed_model()
            embed_err = None
            if em and n:
                rows = [(r["id"], r["text"]) for r in db.execute(
                    "SELECT id, text FROM chunks WHERE source=? AND vec IS NULL", (sid,))]
                try:
                    _vec.embed_chunks(db, rows, em, int(cfg.get("embed_batch") or 32),
                                      scope="notebook", scope_id=str(notebook),
                                      op="add_source")
                except Exception as e:  # noqa: BLE001 — never break ingest on an embed failure
                    embed_err = "%s: %s" % (type(e).__name__, e)
            db.commit()
            embedded = db.execute("SELECT count(*) c FROM chunks WHERE source=? AND vec IS NOT NULL",
                                  (sid,)).fetchone()["c"]
            return {"ok": True, "source_id": sid, "notebook": notebook, "kind": "url",
                    "ref": ref, "chunks": n, "embedded": embedded, "embed_error": embed_err,
                    "title": title or ref}
        finally:
            db.close()


def list_sources(notebook=None):
    db = _connect()
    try:
        _init(db)
        if notebook:
            rows = db.execute("SELECT * FROM sources WHERE notebook=? ORDER BY added DESC",
                              (notebook,)).fetchall()
        else:
            rows = db.execute("SELECT * FROM sources ORDER BY added DESC").fetchall()
        return [{"id": r["id"], "notebook": r["notebook"], "kind": r["kind"], "ref": r["ref"],
                 "title": r["title"], "added": r["added"], "chunks": r["chunks"]} for r in rows]
    finally:
        db.close()


def remove_source(sid):
    with LOCK:
        db = _connect()
        try:
            _init(db)
            _drop_source(db, sid)
            db.commit()
            return {"ok": True, "removed": sid}
        finally:
            db.close()


# --------------------------------------------------------------------- search --
def reembed():
    """Embed EVERY chunk that has no vector yet (JAG-403k).

    Durable fix for indexes built while the embedding model was unavailable:
    instead of deleting + re-adding every source, this back-fills the vectors
    for all pending chunks with the active model.
    """
    em = _cfg.embed_model()
    if not em:
        return {"ok": False, "error": "no embedding model active"}
    cfg = _cfg.load_config()
    with LOCK:
        db = _connect()
        try:
            _init(db)
            rows = [(r["id"], r["text"]) for r in db.execute("SELECT id, text FROM chunks WHERE vec IS NULL")]
            _vec.embed_chunks(db, rows, em, int(cfg.get("embed_batch") or 32),
                              scope="notebook", op="reembed")
            embedded = db.execute("SELECT count(*) c FROM chunks WHERE vec IS NOT NULL").fetchone()["c"]
            total = db.execute("SELECT count(*) c FROM chunks").fetchone()["c"]
            return {"ok": True, "model": em, "pending": len(rows), "embedded": embedded, "chunks": total}
        finally:
            db.close()


def search(query, notebook=None, k=8, kind=None, embed_model=None):
    """Top-k chunks. Optionally scoped to ONE notebook. bm25, or bm25+cosine (RRF)."""
    query = str(query or "").strip()
    out = {"query": query, "notebook": notebook, "results": [], "mode": "bm25"}
    if not query:
        return out
    db = _connect()
    try:
        _init(db)
        if not db.execute("SELECT 1 FROM chunks LIMIT 1").fetchone():
            return out
        if notebook:
            notebook = _resolve_id_db(db, notebook)   # JAG-427: accept a name or an id
        terms = re.findall(r"[A-Za-z0-9_]{2,}", query)
        rows = []
        scope = " AND s.notebook = ?" if notebook else ""
        if terms and _has_fts(db):
            fts_q = " OR ".join('"%s"' % t for t in terms)
            sql = ("SELECT c.id, c.source, c.path, c.lang, c.kind, c.name, c.start, c.end, c.text, "
                   "s.notebook AS notebook, s.ref AS ref, s.title AS title, "
                   "bm25(chunks_fts, 1.0, 3.0, 2.0) AS rank, "
                   "snippet(chunks_fts, 0, '\u00ab', '\u00bb', '\u2026', 14) AS snip "
                   "FROM chunks_fts JOIN chunks c ON c.id = chunks_fts.rowid "
                   "JOIN sources s ON s.id = c.source WHERE chunks_fts MATCH ?" + scope)
            args = [fts_q] + ([notebook] if notebook else [])
            if kind:
                sql += " AND c.kind = ?"
                args.append(kind)
            sql += " ORDER BY rank LIMIT ?"
            args.append(max(k * 5, 30))
            rows = [dict(r) for r in db.execute(sql, args)]
        elif terms:
            like = " OR ".join(["c.text LIKE ?"] * len(terms))
            args = ["%" + t + "%" for t in terms]
            sql = ("SELECT c.id, c.source, c.path, c.lang, c.kind, c.name, c.start, c.end, c.text, "
                   "s.notebook AS notebook, s.ref AS ref, s.title AS title, 0 AS rank, "
                   "substr(c.text,1,160) AS snip FROM chunks c JOIN sources s ON s.id=c.source "
                   "WHERE (" + like + ")" + scope)
            args = args + ([notebook] if notebook else [])
            if kind:
                sql += " AND c.kind=?"
                args.append(kind)
            sql += " LIMIT ?"
            args.append(max(k * 5, 30))
            rows = [dict(r) for r in db.execute(sql, args)]
        else:
            return out
        ref = embed_model if embed_model is not None else _cfg.embed_model()
        if ref and rows:
            qv = _embed_texts_query(ref, query)
            if qv:
                marks = ",".join("?" * len(rows))
                # JAG-403k: `row` (not `r`) — `r` is a function-local from the
                # `for r in rows[:k]` loop below, so using it here raised
                # UnboundLocalError the first time the hybrid path actually ran.
                cand = {row["id"]: _vec.blob_vec(row["vec"]) for row in db.execute(
                    "SELECT id, vec FROM chunks WHERE id IN (%s) AND vec IS NOT NULL" % marks,
                    [x["id"] for x in rows])}
                if cand:
                    K = 60
                    lex = {r["id"]: i for i, r in enumerate(rows)}
                    sem = sorted(((_vec.cos(qv, v), cid) for cid, v in cand.items()), reverse=True)
                    sem_rank = {cid: i for i, (_, cid) in enumerate(sem)}
                    for r in rows:
                        r["rrf"] = 1.0 / (K + lex[r["id"]]) + 1.0 / (K + sem_rank.get(r["id"], 10 ** 6))
                    rows.sort(key=lambda r: -r["rrf"])
                    out["mode"] = "hybrid"
        for r in rows[:k]:
            score = r.get("rrf")
            out["results"].append({
                "notebook": r["notebook"], "source": r["source"], "ref": r["ref"],
                "title": r["title"], "path": r["path"], "name": r["name"], "kind": r["kind"],
                "lang": r["lang"], "start": r["start"], "end": r["end"],
                "score": round(score, 6) if score is not None else round(-(r["rank"] or 0), 6),
                "snippet": r.get("snip") or (r["text"] or "")[:200],
            })
        return out
    finally:
        db.close()


def _embed_texts_query(ref, query):
    from longrun.model import embed
    vs = embed.embed_texts([query], model=ref)
    return vs[0] if vs else None


# ------------------------------------------------------------------- discover --
def discover(query, n=5):
    """Web search -> candidate sources (URL + title + snippet). Nothing is stored."""
    query = str(query or "").strip()
    if not query:
        return {"ok": False, "error": "query required"}
    try:
        results, engine = SEARCH(query, max(1, min(int(n or 5), 10)))
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": "search failed: %s" % e}
    if not results:
        return {"ok": False, "engine": engine, "candidates": [], "error": "no results"}
    return {"ok": True, "engine": engine, "query": query,
            "candidates": [{"title": r.get("title", ""), "url": r.get("url", ""),
                            "snippet": r.get("snippet", "")} for r in results]}


def import_candidates(notebook, urls):
    """Import discovered URLs into a notebook (each through the source pipeline)."""
    return add_sources(notebook, urls)


# --------------------------------------------------------------- status/clear --
def status():
    p = db_path()
    out = {"db": p, "exists": os.path.isfile(p), "embed_model": _cfg.embed_model(),
           "notebooks": 0, "sources": 0, "files": 0, "chunks": 0, "embedded": 0, "dim": 0,
           "built_at": None, "fts": False, "size_kb": 0,
           "extractors": _docio.available()}
    if not out["exists"]:
        return out
    try:
        out["size_kb"] = round(os.path.getsize(p) / 1024.0, 1)
    except OSError:
        pass
    db = _connect()
    try:
        _init(db)
        out["notebooks"] = db.execute("SELECT count(*) c FROM notebooks").fetchone()["c"]
        out["sources"] = db.execute("SELECT count(*) c FROM sources").fetchone()["c"]
        out["files"] = db.execute("SELECT count(*) c FROM (SELECT DISTINCT source,path FROM chunks)").fetchone()["c"]
        out["chunks"] = db.execute("SELECT count(*) c FROM chunks").fetchone()["c"]
        out["embedded"] = db.execute("SELECT count(*) c FROM chunks WHERE vec IS NOT NULL").fetchone()["c"]
        out["dim"] = _vec.dim(db)
        try:
            row = db.execute("SELECT value FROM meta WHERE key='built_at'").fetchone()
            out["built_at"] = json.loads(row["value"]) if row else None
        except Exception:  # noqa: BLE001
            pass
        out["fts"] = _has_fts(db)
        return out
    finally:
        db.close()


def list_files(notebook=None):
    """Every indexed file: path, language, source, notebook, chunk count."""
    db = _connect()
    try:
        _init(db)
        scope = " WHERE s.notebook = ?" if notebook else ""
        args = [notebook] if notebook else []
        rows = db.execute(
            "SELECT c.path AS path, c.source AS source, s.notebook AS notebook, "
            "s.kind AS kind, s.ref AS ref, count(c.id) AS chunks "
            "FROM chunks c JOIN sources s ON s.id=c.source" + scope +
            " GROUP BY c.source, c.path ORDER BY chunks DESC, c.path", args).fetchall()
        return {"notebook": notebook, "files": [dict(r) for r in rows]}
    finally:
        db.close()


def clear():
    with LOCK:
        db = _connect()
        try:
            for t in ("chunks", "chunks_fts", "sources", "notebooks", "meta"):
                try:
                    db.execute("DROP TABLE IF EXISTS %s" % t)
                except sqlite3.OperationalError:
                    pass
            db.commit()
            _init(db)
            return {"ok": True}
        finally:
            db.close()
