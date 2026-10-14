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
import hashlib
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
        CREATE TABLE IF NOT EXISTS notebooks(
            id TEXT PRIMARY KEY, name TEXT, created REAL,
            hidden INTEGER DEFAULT 0, owner TEXT,
            is_session INTEGER DEFAULT 0);
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
    # JAG-431r6b: phantom → "session notebook". The scope lives in a REAL
    # notebook row flagged is_session=1 with owner == session id. It is shown
    # in the Knowledge UI's dedicated "Session" tab, excluded from the global
    # corpus, and lifecycle-tied to the session (purge on delete/reset).
    # Migrate legacy DBs (r6 added hidden+owner; r6b adds is_session).
    for col, ddl in (("hidden", "INTEGER DEFAULT 0"), ("owner", "TEXT"),
                     ("is_session", "INTEGER DEFAULT 0")):
        try:
            db.execute("ALTER TABLE notebooks ADD COLUMN %s %s" % (col, ddl))
        except sqlite3.OperationalError:
            pass
    db.execute("CREATE INDEX IF NOT EXISTS notebooks_owner ON notebooks(owner)")
    db.execute("CREATE INDEX IF NOT EXISTS notebooks_session ON notebooks(is_session)")
    fts = True
    try:
        db.execute("CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(text, name, path)")
    except sqlite3.OperationalError:
        fts = False
    db.execute("INSERT OR IGNORE INTO notebooks(id, name, created, hidden, owner) "
               "VALUES(?,?,?,0,NULL)",
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
def _notebook_rows(db, session_only):
    """Fetch notebook rows, optionally restricted to SESSION notebooks."""
    sql = "SELECT id, name, created, owner, is_session FROM notebooks"
    if session_only:
        sql += " WHERE IFNULL(is_session,0) = 1"
    else:
        sql += " WHERE IFNULL(is_session,0) = 0"
    sql += " ORDER BY created"
    return db.execute(sql).fetchall()


def list_notebooks():
    """List GLOBAL notebooks only — session notebooks are excluded.

    JAG-431r6b: session-scoped KBs live in notebooks flagged is_session=1 and
    are surfaced via ``list_sessions()`` instead, so the Knowledge UI's main
    notebook menu never mixes them with the global corpus.
    """
    db = _connect()
    try:
        _init(db)
        rows = _notebook_rows(db, session_only=False)
        counts = {r["notebook"]: r["c"] for r in db.execute(
            "SELECT notebook, count(*) c FROM sources GROUP BY notebook")}
        return [{"id": r["id"], "name": r["name"], "created": r["created"],
                 "is_session": False, "owner": None,
                 "sources": counts.get(r["id"], 0)} for r in rows]
    finally:
        db.close()


def list_sessions():
    """List SESSION notebooks (the Knowledge UI's dedicated "Session" tab).

    JAG-431r6b: each is flagged is_session=True so consumers can distinguish
    them from global notebooks. They are lifecycle-tied to their session and
    disappear on ``purge_session``.
    """
    db = _connect()
    try:
        _init(db)
        rows = _notebook_rows(db, session_only=True)
        counts = {r["notebook"]: r["c"] for r in db.execute(
            "SELECT notebook, count(*) c FROM sources GROUP BY notebook")}
        return [{"id": r["id"], "name": r["name"], "created": r["created"],
                 "is_session": True, "owner": r["owner"],
                 "sources": counts.get(r["id"], 0)} for r in rows]
    finally:
        db.close()


def purge_session(sid):
    """Delete every SESSION notebook owned by a session (JAG-431r6b).

    Called when a session is deleted / reset so its KB scope (sources + chunks)
    is removed from the single global DB — it disappears from ``list_sessions()``.
    """
    if not sid:
        return {"ok": True, "removed": []}
    removed = []
    with LOCK:
        db = _connect()
        try:
            _init(db)
            for row in db.execute("SELECT id FROM notebooks WHERE owner=?", (str(sid),)).fetchall():
                for s in db.execute("SELECT id FROM sources WHERE notebook=?", (row["id"],)).fetchall():
                    _drop_source(db, s["id"])
                db.execute("DELETE FROM notebooks WHERE id=?", (row["id"],))
                removed.append(row["id"])
            db.commit()
            return {"ok": True, "removed": removed}
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


# JAG-431r5: notebook='auto' routing — match a new source to an existing notebook
# by FTS5 bm25 over the notebook's chunk corpus, or auto-create a new one when no
# notebook is close enough. Stdlib only, no embeddings required.
_AUTO_MATCH_THRESHOLD = float(os.environ.get("LONGRUN_AUTO_MATCH_BM25") or -3.5)
_AUTO_PREVIEW_CHARS = int(os.environ.get("LONGRUN_AUTO_PREVIEW_CHARS") or 2400)
_AUTO_NOTEBOOKS_IGNORED = {DEFAULT_ID}


def _fts_query_for(text, max_terms=12):
    """Build a safe FTS5 MATCH expression from arbitrary text.

    Splits on non-alphanumerics, keeps 3+ char tokens, wraps each in double
    quotes (FTS5 verbatim) and OR-joins them. The query is bounded so a
    multi-megabyte preview does not explode the bm25 evaluation.
    """
    if not text:
        return None
    toks = re.findall(r"[A-Za-z0-9]{3,}", text)
    if not toks:
        return None
    seen = set()
    out = []
    for t in toks:
        if t in seen:
            continue
        seen.add(t)
        out.append('"' + t.replace('"', '') + '"')
        if len(out) >= max_terms:
            break
    return " OR ".join(out)


def _route_notebook(db, preview_text, fallback_name):
    """Pick a notebook for a new source, or create one.

    The decision is bm25-based: a query is run against every existing notebook
    (excluding the default catch-all) and the best score is compared to
    ``_AUTO_MATCH_THRESHOLD`` (the lower the bm25, the better the match). When no
    notebook is close enough, a new notebook is created using ``fallback_name``
    (truncated to 60 chars, slugified).

    Returns ``(notebook_id, notebook_name, auto_created)``.
    """
    text = (preview_text or "").strip()
    # JAG-431r5: use only the first ~10 distinctive tokens. The full 30-token
    # coverage is diluted by shared boilerplate (Wikipedia menus, footers, etc.);
    # the first tokens are the title + topic terms and carry the strongest signal.
    terms = list(dict.fromkeys(re.findall(r"[A-Za-z0-9]{4,}", text)))[:10]
    if not terms:
        return _auto_create_notebook(db, fallback_name)
    if not _has_fts(db):
        return _auto_create_notebook(db, fallback_name)

    placeholders = ",".join("?" for _ in _AUTO_NOTEBOOKS_IGNORED)
    best_nb = None
    second_cov = 0.0
    best_cov = 0.0
    coverages = []
    for row in db.execute(
            "SELECT id, name FROM notebooks WHERE id NOT IN ({})".format(placeholders),
            tuple(_AUTO_NOTEBOOKS_IGNORED)):
        # Single FTS5 query with each term, count how many had at least one
        # hit in the notebook's chunk corpus. Phrase matches ("foo") so
        # a chunk must contain the literal token.
        hit_terms = 0
        for t in terms:
            cur = db.execute(
                "SELECT count(*) c FROM chunks_fts WHERE chunks_fts MATCH ? "
                "AND rowid IN (SELECT id FROM chunks WHERE source IN "
                "(SELECT id FROM sources WHERE notebook=?)) LIMIT 1",
                ('"' + t.replace('"', '') + '"', row["id"]))
            if cur.fetchone()["c"] > 0:
                hit_terms += 1
        cov = hit_terms / max(1, len(terms))
        coverages.append((cov, row["id"], row["name"]))
    coverages.sort(reverse=True)
    if coverages:
        best_cov, bid, bname = coverages[0]
        if len(coverages) > 1:
            second_cov = coverages[1][0]
    # Match: best coverage >= 0.5 AND margin over the runner-up >= 0.15.
    # The margin prevents pages with lots of shared boilerplate from
    # auto-merging into the wrong notebook.
    if best_nb is None and best_cov >= 0.5 and (best_cov - second_cov) >= 0.15:
        return bid, bname, False
    return _auto_create_notebook(db, fallback_name)


def _auto_create_notebook(db, fallback_name):
    name = (str(fallback_name or "").strip() or "Untitled")[:60]
    name = re.sub(r"\s+", " ", name)
    nid = "nb_" + uuid.uuid4().hex[:8]
    db.execute("INSERT INTO notebooks(id, name, created) VALUES(?,?,?)",
               (nid, name, time.time()))
    return nid, name, True


def _preview_for_path(path):
    """Read up to ``_AUTO_PREVIEW_CHARS`` of text from a file path.

    Uses the new ``docio.extract`` diagnostic so the same diagnostic flows
    into the auto-routing caller.
    """
    if not path or not os.path.isfile(path):
        return "", None
    try:
        res = _docio.extract(path)
    except Exception:  # noqa: BLE001
        return "", None
    if not isinstance(res, dict):
        return (res or "")[:_AUTO_PREVIEW_CHARS], None
    return (res.get("text") or "")[:_AUTO_PREVIEW_CHARS], res


# -------------------------------------------------------------------- sources --
def _ingest(db, sid, notebook, kind, ref, title, pieces, lang, path, cfg, fts):
    n = _insert_chunks(db, sid, path, lang, "doc" if kind != "code" else "code",
                       pieces, fts)
    db.execute("INSERT OR REPLACE INTO sources(id, notebook, kind, ref, title, added, chunks) "
               "VALUES(?,?,?,?,?,?,?)", (sid, notebook, kind, ref, title, time.time(), n))
    return n


def _session_notebook(db, sid, create=True):
    """Get (or create) the SESSION notebook that owns this session's KB scope.

    The notebook id is DETERMINISTIC (``sess-<sha1(sid)>``) so the same session
    always routes to the same session notebook without a lookup. It is flagged
    is_session=1 with owner=<sid>, so it is excluded from the global corpus and
    surfaced in the Knowledge UI's dedicated "Session" tab — reachable only via
    an explicit session scope (the FULL-approval path).
    """
    if not sid:
        return None
    short = hashlib.sha1(str(sid).encode("utf-8")).hexdigest()[:12]
    nid = "sess-" + short
    row = db.execute("SELECT id FROM notebooks WHERE id=?", (nid,)).fetchone()
    if not row and create:
        name = "Session " + str(sid).replace("-", "").upper()[:8]
        db.execute("INSERT INTO notebooks(id, name, created, hidden, owner, is_session) "
                   "VALUES(?,?,?,1,?,1)", (nid, name, time.time(), str(sid)))
    return nid if (row or create) else None


def add_source(notebook, ref, session_id=None):
    """Index ONE source (URL / file / folder) into `notebook`. Returns a result dict.

    JAG-431r5: when ``notebook == "auto"`` the source is routed to the closest
    existing notebook by FTS5 bm25 over its chunks, or a fresh notebook is
    created when nothing is close enough. The result dict carries
    ``notebook_auto: bool``, ``notebook_name: str``, and (for paths that go
    through ``docio.extract``) ``extract_diagnostic`` + ``recommend_visual``.

    JAG-431r6: ``session_id`` (optional) routes the source into a HIDDEN
    per-session notebook (see ``_session_notebook``) instead of tagging rows.
    All notebook/search/embedding machinery applies verbatim.
    """
    notebook = notebook or DEFAULT_ID
    ref = str(ref or "").strip()
    if not ref:
        return {"ok": False, "error": "empty source"}
    auto_routed = False
    extract_diag = None
    cfg = _cfg.load_config()
    with LOCK:
        db = _connect()
        try:
            fts = _init(db)
            notebook_auto_flag = (notebook == "auto")
            # JAG-431r6: an explicit session forces a phantom-notebook scope.
            sess_nb = _session_notebook(db, session_id)
            if sess_nb:
                notebook = sess_nb
                notebook_auto_flag = False
            if notebook_auto_flag:
                notebook = DEFAULT_ID  # placeholder; routed after we have a preview
            else:
                notebook = _resolve_id_db(db, notebook)   # JAG-427: accept a name or an id
            if not notebook_auto_flag and not _notebook_exists(db, notebook):
                return {"ok": False, "error": "no such notebook: %s" % notebook}
            sid = "src:" + uuid.uuid4().hex[:10]
            cl = int(cfg.get("chunk_lines") or 60)
            ov = int(cfg.get("overlap_lines") or 8)
            if ref.startswith("http://") or ref.startswith("https://"):
                try:
                    text = fetch_text(ref)
                except Exception as e:  # noqa: BLE001
                    return {"ok": False, "error": "fetch failed: %s" % e, "ref": ref}
                if notebook_auto_flag:
                    nb_id, nb_name, auto_routed = _route_notebook(
                        db, (text or "")[:_AUTO_PREVIEW_CHARS], ref)
                    notebook = nb_id
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
                if notebook_auto_flag and targets:
                    preview, extract_diag = _preview_for_path(targets[0])
                    nb_id, nb_name, auto_routed = _route_notebook(
                        db, preview, base)
                    notebook = nb_id
                elif notebook_auto_flag:
                    nb_id, nb_name, auto_routed = _route_notebook(db, "", base)
                    notebook = nb_id
                n = 0
                for fp in targets:
                    text = _chunk.read_text(fp, cfg.get("max_file_kb") or 512)
                    if text is None:
                        continue
                    lang, knd = _chunk.lang_for(fp)
                    n += _insert_chunks(db, sid, fp, lang or "text", knd or "doc",
                                        _chunk.chunk_file(text, lang or "text", knd or "doc", cfg), fts)
                db.execute("INSERT OR REPLACE INTO sources(id, notebook, kind, ref, title, added, chunks) "
                           "VALUES(?,?,?,?,?,?,?)",
                           (sid, notebook, "path", ref, base, time.time(), n))
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
            nb_row = db.execute("SELECT name FROM notebooks WHERE id=?", (notebook,)).fetchone()
            result = {"ok": True, "source_id": sid, "notebook": notebook, "kind": kind,
                      "ref": ref, "chunks": n, "embedded": embedded, "embed_error": embed_err,
                      "title": ref if kind == "url" else base,
                      "notebook_auto": bool(auto_routed or notebook_auto_flag),
                      "notebook_name": nb_row["name"] if nb_row else ""}
            if extract_diag is not None:
                result["extract_diagnostic"] = extract_diag
                result["recommend_visual"] = bool(extract_diag.get("recommend_visual"))
            return result
        finally:
            db.close()


def add_text(notebook, title, text, session_id=None):
    """Add a pasted-text source to a notebook.

    JAG-431r6: ``session_id`` (optional) routes into a HIDDEN per-session
    notebook (see ``_session_notebook``).
    """
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
            sess_nb = _session_notebook(db, session_id)
            if sess_nb:
                notebook = sess_nb
            else:
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


def add_source_text(notebook, ref, text, title=None, session_id=None):
    """Ingest pre-fetched text as a URL source. Used by the research executor
    so the same body is NOT re-fetched.

    JAG-431r5: also accepts ``notebook="auto"`` for the same routing logic as
    ``add_source``. JAG-431r6: ``session_id`` (optional) routes into a HIDDEN
    per-session notebook (see ``_session_notebook``).
    """
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
            auto_routed = False
            nb_name = ""
            if session_id:
                notebook = _session_notebook(db, session_id)
            elif notebook == "auto":
                nb_id, nb_name, auto_routed = _route_notebook(
                    db, (text or "")[:_AUTO_PREVIEW_CHARS], title or ref)
                notebook = nb_id
            else:
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
            nb_row = db.execute("SELECT name FROM notebooks WHERE id=?", (notebook,)).fetchone()
            return {"ok": True, "source_id": sid, "notebook": notebook, "kind": "url",
                    "ref": ref, "chunks": n, "embedded": embedded, "embed_error": embed_err,
                    "title": title or ref, "notebook_auto": bool(auto_routed),
                    "notebook_name": nb_row["name"] if nb_row else (nb_name or ""),
                    # JAG-431r5: pre-fetched text is always lexically indexable,
                    # so a visual embedder is never strictly needed. Kept in the
                    # response shape for symmetry with add_source().
                    "recommend_visual": False}
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


def search(query, notebook=None, k=8, kind=None, embed_model=None, session=None):
    """Search the knowledge base.

    JAG-431r6: ``session`` (optional) scopes the search to the HIDDEN notebook
    owned by that session (see ``_session_notebook``) — useful for "what did we
    learn in THIS chat?" without polluting the global notebooks.
    """
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
        # JAG-431r6: a session scope resolves to that session's phantom notebook
        # (lookup only — never create one just for a search).
        if session:
            notebook = _session_notebook(db, session, create=False)
        if notebook:
            notebook = _resolve_id_db(db, notebook)   # JAG-427: accept a name or an id
        terms = re.findall(r"[A-Za-z0-9_]{2,}", query)
        rows = []
        scope = " AND s.notebook = ?" if notebook else ""
        # JAG-431r6b: a GLOBAL search (no session / notebook scope) must not
        # leak the session notebooks. They are only reachable through an
        # explicit session scope (the FULL-approval path). An explicitly named
        # global notebook is unaffected.
        if not notebook:
            scope += " AND s.notebook IN (SELECT id FROM notebooks WHERE IFNULL(is_session,0) = 0)"
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
    # JAG-462: `embed.embed_texts` returns the TUPLE (vecs, usage). Returning `vs[0]`
    # handed the caller the whole vecs LIST (`[[...]]`), so `vectors.cos(query, doc)`
    # always saw a length mismatch and returned 0.0 — hybrid/semantic search silently
    # degraded to lexical-only. Return the FIRST float vector.
    vecs, _usage = embed.embed_texts([query], model=ref)
    return vecs[0] if vecs else None


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
