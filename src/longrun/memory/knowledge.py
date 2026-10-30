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
from longrun.memory import sqlkit as _sqlkit
from longrun.memory import vectors as _vec
from longrun.util import paths

LOCK = threading.RLock()
DB_NAME = "knowledge.db"
DEFAULT_ID = "default"
DEFAULT_NAME = "Default"

# Indirections so tests (and future providers) can swap them without network.
fetch_text = _chunk.fetch_url
# JAG-490: the rich fetcher (content type / final URL / snapshot + binary
# extraction). A test may still override only `fetch_text`; add_source honours it.
fetch_info = _chunk.fetch_url_info


def _default_searcher(query, n):
    from longrun.tools import tools as _tools
    return _tools._web_search(query, n)


SEARCH = _default_searcher


# ---------------------------------------------------------------------- store --
def db_path():
    os.makedirs(paths.KNOWLEDGE_DIR, exist_ok=True)
    return os.path.join(paths.KNOWLEDGE_DIR, DB_NAME)


def _connect():
    """Open the knowledge DB with the shared opener (JAG-483)."""
    return _sqlkit.connect(db_path())


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
    # JAG-490: an online source is not only a URL string — record WHAT was fetched
    # (content type / final redirect URL) and, for binary documents, the local
    # snapshot so the "pointer" is reproducible after the page changes.
    for col, ddl in (("content_type", "TEXT"), ("final_url", "TEXT"),
                     ("snapshot", "TEXT")):
        try:
            db.execute("ALTER TABLE sources ADD COLUMN %s %s" % (col, ddl))
        except sqlite3.OperationalError:
            pass
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
    """True when this DB carries the FTS5 shadow (shared with the codebase index)."""
    return _sqlkit.has_fts(db)


def _insert_chunks(db, sid, path, lang, kind, pieces, fts):
    """Insert a source's chunks (``source`` = ``sid``); returns how many landed."""
    return len(_sqlkit.insert_chunks(db, pieces, path, lang, kind, fts, source=sid))


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
_AUTO_PREVIEW_CHARS = int(os.environ.get("LONGRUN_AUTO_PREVIEW_CHARS") or 2400)
_AUTO_NOTEBOOKS_IGNORED = {DEFAULT_ID}


def _route_notebook(db, preview_text, fallback_name):
    """Pick a notebook for a new source, or create one.

    The decision is token-coverage based over existing notebooks (excluding the
    default catch-all). When no notebook has >=50% coverage with a >=15% margin,
    a new notebook is created using ``fallback_name`` (truncated to 60 chars).

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
    if best_cov >= 0.5 and (best_cov - second_cov) >= 0.15:
        return bid, bname, False
    return _auto_create_notebook(db, fallback_name)


def _auto_create_notebook(db, fallback_name):
    name = (str(fallback_name or "").strip() or "Untitled")[:60]
    name = re.sub(r"\s+", " ", name)
    nid = "nb_" + uuid.uuid4().hex[:8]
    db.execute("INSERT INTO notebooks(id, name, created) VALUES(?,?,?)",
               (nid, name, time.time()))
    return nid, name, True


# -------------------------------------------------------------------- sources --
def _ingest(db, sid, notebook, kind, ref, title, pieces, lang, path, cfg, fts, meta=None):
    meta = meta or {}
    n = _insert_chunks(db, sid, path, lang, "doc" if kind != "code" else "code",
                       pieces, fts)
    db.execute("INSERT OR REPLACE INTO sources(id, notebook, kind, ref, title, added, "
               "chunks, content_type, final_url, snapshot) VALUES(?,?,?,?,?,?,?,?,?,?)",
               (sid, notebook, kind, ref, title, time.time(), n,
                meta.get("content_type"), meta.get("final_url"), meta.get("snapshot")))
    return n


def _session_notebook(db, sid, create=True):
    """Get (or create) the SESSION notebook that owns this session's KB scope.

    The notebook id is DETERMINISTIC (``sess-<sha1(sid)>``) so the same session
    always routes to the same session notebook without a lookup. It is flagged
    is_session=1 with owner=<sid>, so global searches exclude it. The Knowledge UI
    lists session notebooks separately; the agent tool lists only the current
    session's notebook and scopes retrieval to its owner.
    """
    if not sid:
        return None
    short = hashlib.sha1(str(sid).encode("utf-8")).hexdigest()[:12]
    nid = "sess-" + short
    row = db.execute(
        "SELECT owner, hidden, is_session FROM notebooks WHERE id=?", (nid,)
    ).fetchone()
    if row:
        if row["is_session"] and row["owner"] == str(sid):
            return nid
        if row["hidden"] and row["owner"] == str(sid):
            db.execute("UPDATE notebooks SET is_session=1 WHERE id=? AND owner=?",
                       (nid, str(sid)))
            db.commit()
            return nid
        return None
    if not create:
        return None
    # Fix3: the id is DETERMINISTIC, so two writers creating the same session
    # notebook (parallel attachments, two server processes on one data home)
    # used to race SELECT-then-INSERT and the loser crashed with a raw
    # "UNIQUE constraint failed". INSERT OR IGNORE makes creation idempotent;
    # the re-select below returns the winner's row either way.
    name = "Session " + str(sid).replace("-", "").upper()[:8]
    try:
        db.execute("INSERT OR IGNORE INTO notebooks(id, name, created, hidden, owner, is_session) "
                   "VALUES(?,?,?,1,?,1)", (nid, name, time.time(), str(sid)))
    except sqlite3.IntegrityError:
        pass
    row = db.execute(
        "SELECT owner, hidden, is_session FROM notebooks WHERE id=?", (nid,)
    ).fetchone()
    if row and (row["is_session"] or row["hidden"]) and row["owner"] == str(sid):
        if row["is_session"]:
            return nid
        db.execute("UPDATE notebooks SET is_session=1 WHERE id=? AND owner=?",
                   (nid, str(sid)))
        db.commit()
        return nid
    return None


def _existing_source(db: sqlite3.Connection, notebook: str, ref: str) -> dict | None:
    """Return current indexing state when this exact source already exists."""
    row = db.execute(
        "SELECT s.id, s.kind, s.ref, s.title, s.chunks, n.name "
        "FROM sources s LEFT JOIN notebooks n ON n.id=s.notebook "
        "WHERE s.notebook=? AND s.ref=? ORDER BY s.added DESC LIMIT 1",
        (notebook, ref)).fetchone()
    if not row:
        return None
    chunks = int(row["chunks"] or 0)
    embedded = int(db.execute(
        "SELECT count(*) AS n FROM chunks WHERE source=? AND vec IS NOT NULL",
        (row["id"],)).fetchone()["n"])
    return {"ok": True, "duplicate": True, "already_indexed": True,
            "source_id": row["id"], "notebook": notebook,
            "notebook_name": row["name"] or "", "kind": row["kind"],
            "ref": row["ref"], "title": row["title"], "chunks": chunks,
            "embedded": embedded,
            "pending_embeddings": max(0, chunks - embedded) if _cfg.embed_model() else 0}


def _kb_cfg():
    """Index config tuned for the KNOWLEDGE base (not the code index).

    JAG-490: the codebase ignores (`*.png`, `*.svg`, `*.ipynb`, …) and the
    512 KB cap were applied to knowledge folders too, so images and big exports
    were silently skipped. The KB has its own knobs (`knowledge_ignore`,
    `knowledge_max_file_kb`) and always allows documents up to `doc_max_kb`.
    """
    cfg = dict(_cfg.load_config())
    cfg["ignore"] = list(cfg.get("knowledge_ignore") or [])
    cfg["max_file_kb"] = int(cfg.get("knowledge_max_file_kb") or 25600)
    return cfg


def add_source(notebook, ref, session_id=None):
    """Index ONE source (URL / file / folder) into `notebook`. Returns a result dict.

    JAG-431r5: when ``notebook == "auto"`` the source is routed to the closest
    existing notebook by FTS5 bm25 over its chunks, or a fresh notebook is
    created when nothing is close enough.

    JAG-431r6: ``session_id`` (optional) routes the source into a HIDDEN
    per-session notebook (see ``_session_notebook``).

    JAG-490: fetching/extraction happens OUTSIDE the global lock (a 300-page PDF
    used to freeze every KB read for minutes), documents are extracted up to
    ``doc_max_kb`` (not the 512 KB code cap), and URL sources record the real
    content type / final URL / local snapshot of a binary document.
    """
    notebook = notebook or DEFAULT_ID
    ref = str(ref or "").strip()
    if not ref:
        return {"ok": False, "error": "empty source"}
    if session_id:
        with LOCK:
            db = _connect()
            try:
                _init(db)
                session_nb = _session_notebook(db, session_id, create=False)
                if session_nb:
                    existing = _existing_source(db, session_nb, ref)
                    if existing:
                        return existing
            finally:
                db.close()
    auto_routed = False
    extract_diag = None
    cfg = _kb_cfg()
    cl = int(cfg.get("chunk_lines") or 60)
    ov = int(cfg.get("overlap_lines") or 8)
    doc_kb = int(cfg.get("doc_max_kb") or 25600)
    text_kb = int(cfg.get("max_file_kb") or 512)

    # ---- prepare (NO lock): network + document extraction can be slow ------
    kind = "path"
    url_info = None
    pieces = None
    prepared = []          # [(path, text, lang, kind)]
    base = ""
    if ref.startswith("http://") or ref.startswith("https://"):
        if _chunk.is_media_url(ref):
            # A video URL carries the words in its AUDIO: fetching the page
            # yields only title/description/comments, so the source is
            # transcribed. If no transcriber can do it, the add FAILS with the
            # reason — a notebook full of page furniture that answers nothing is
            # worse than a visible error.
            text, terr = _chunk.transcribe_media_url(ref, cfg)
            if terr:
                return {"ok": False, "error": terr, "ref": ref}
            url_info = {"text": text, "kind": "media-url", "engine": "whisper"}
            text = str(text or "").strip()
        else:
            try:
                if fetch_text is _chunk.fetch_url:
                    url_info = fetch_info(
                        ref, max_kb=int(cfg.get("url_max_kb") or 51200),
                        snapshot_dir=os.path.join(paths.KNOWLEDGE_DIR, "raw"))
                    text = url_info.get("text") or ""
                else:
                    # A test / research executor overrode the TEXT fetcher: honour it
                    # (the rich fetcher stays available for callers that want metadata).
                    text = fetch_text(ref)
                    url_info = {"text": text, "kind": "url"}
            except Exception as e:  # noqa: BLE001
                return {"ok": False, "error": "fetch failed: %s" % e, "ref": ref}
        if not str(text or "").strip():
            return {"ok": False,
                    "error": (url_info or {}).get("error") or "fetch produced no text",
                    "ref": ref}
        kind = (url_info or {}).get("kind") or "url"
        base = ref
        pieces = _chunk.chunk_doc(str(text), cl, ov)
        extract_diag = (url_info or {}).get("diagnostic")
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
        if not targets:
            return {"ok": False, "error": "no indexable files in %s" % ref, "ref": ref}
        for fp in targets:
            mb = doc_kb if _docio.supported(fp) else text_kb
            text = _chunk.read_text(fp, mb)
            if text is None:
                continue
            lang, knd = _chunk.lang_for(fp)
            prepared.append((fp, text, lang or "text", knd or "doc"))
        if not prepared:
            return {"ok": False, "error": "no extractable text in %s" % ref, "ref": ref}
        if len(targets) == 1 and _docio.supported(targets[0]):
            extract_diag = _docio.extract(targets[0], max_kb=doc_kb)

    # ---- write (locked): routing + chunks + vectors ------------------------
    with LOCK:
        db = _connect()
        try:
            fts = _init(db)
            notebook_auto_flag = (notebook == "auto")
            sess_nb = _session_notebook(db, session_id)
            if sess_nb:
                notebook = sess_nb
                notebook_auto_flag = False
            if notebook_auto_flag:
                notebook = DEFAULT_ID  # placeholder; routed below
            else:
                notebook = _resolve_id_db(db, notebook)   # JAG-427: name or id
            if not notebook_auto_flag and not _notebook_exists(db, notebook):
                return {"ok": False, "error": "no such notebook: %s" % notebook}
            if notebook_auto_flag:
                preview = pieces[0]["text"] if pieces else prepared[0][1]
                notebook, _nb_name, auto_routed = _route_notebook(
                    db, preview[:_AUTO_PREVIEW_CHARS], base)
            if session_id:
                existing = _existing_source(db, notebook, ref)
                if existing:
                    return existing
            sid = "src:" + uuid.uuid4().hex[:10]
            if pieces is not None:
                n = _ingest(db, sid, notebook, kind, ref, ref, pieces,
                            "markdown", ref, cfg, fts, meta=url_info)
            else:
                n = 0
                for fp, text, lang, knd in prepared:
                    n += _insert_chunks(db, sid, fp, lang, knd,
                                        _chunk.chunk_file(text, lang, knd, cfg), fts)
                db.execute(
                    "INSERT OR REPLACE INTO sources(id, notebook, kind, ref, title, "
                    "added, chunks, content_type, final_url, snapshot) "
                    "VALUES(?,?,?,?,?,?,?,?,?,?)",
                    (sid, notebook, kind, ref, base, time.time(), n, None, None, None))
            # Commit the chunks BEFORE embedding: a large book spends minutes in
            # the embedding API, and an open write transaction (plus the global
            # lock) made the whole KB unavailable and the source invisible.
            db.commit()
            em = _cfg.embed_model()
            embed_err = None
            if em and n:
                # JAG-403j/k: a failing embedder never breaks the ingest (bm25
                # still works) and the failure is REPORTED in the result.
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
                embed_err = "embedding produced no vectors (endpoint, key or model unavailable)"
            pending_embeddings = max(0, n - embedded) if em else 0
            nb_row = db.execute("SELECT name FROM notebooks WHERE id=?", (notebook,)).fetchone()
            result = {"ok": True, "source_id": sid, "notebook": notebook, "kind": kind,
                      "ref": ref, "chunks": n, "embedded": embedded, "embed_error": embed_err,
                      "pending_embeddings": pending_embeddings,
                      "title": ref if pieces is not None else base,
                      "notebook_auto": bool(auto_routed or notebook_auto_flag),
                      "notebook_name": nb_row["name"] if nb_row else "",
                      "content_type": (url_info or {}).get("content_type"),
                      "final_url": (url_info or {}).get("final_url"),
                      "snapshot": (url_info or {}).get("snapshot"),
                      "engine": (extract_diag or {}).get("engine")}
            if extract_diag is not None:
                result["extract_diagnostic"] = _diag_meta(extract_diag)
                result["recommend_visual"] = bool(extract_diag.get("recommend_visual"))
                result["text_quality"] = extract_diag.get("quality")
            return result
        except sqlite3.IntegrityError as e:
            # Fix3: same storage-race contract as add_text — clean retryable
            # error, never a raw "constraint failed" traceback.
            try:
                db.rollback()
            except Exception:  # noqa: BLE001
                pass
            return {"ok": False, "error": "storage conflict, retry once: %s" % e}
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
        except sqlite3.IntegrityError as e:
            # Fix3: a storage race (parallel attachments, two processes on one
            # data home) must surface as a clean retryable error, never as a
            # raw "constraint failed" traceback the model cannot act on.
            try:
                db.rollback()
            except Exception:  # noqa: BLE001
                pass
            return {"ok": False, "error": "storage conflict, retry once: %s" % e}
        finally:
            db.close()


def add_sources(notebook, values, session_id=None):
    """Index many refs; session_id scopes them and repeated session refs are skipped."""
    if isinstance(values, str):
        refs = [ln.strip() for ln in values.splitlines()]
    else:
        refs = [str(v).strip() for v in (values or [])]
    refs = [r for r in dict.fromkeys(refs) if r]
    results = [add_source(notebook, r, session_id=session_id) for r in refs]
    ok = [x for x in results if x.get("ok")]
    failed = [x for x in results if not x.get("ok")]
    added = [x for x in ok if not x.get("duplicate")]
    skipped = len(ok) - len(added)
    out = {"ok": bool(ok) and len(ok) == len(refs), "added": len(added),
           "skipped": skipped, "total": len(refs),
           "chunks": sum(x.get("chunks", 0) for x in added), "results": results}
    if failed:
        # The Knowledge panel reads ONE top-level `error`; a per-ref failure only
        # would leave the operator with a silently smaller notebook.
        out["error"] = "; ".join(
            "%s: %s" % (x.get("ref") or "?", x.get("error") or "failed")
            for x in failed)
    return out


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
        except sqlite3.IntegrityError as e:
            # Fix3: same storage-race contract as add_text/add_source.
            try:
                db.rollback()
            except Exception:  # noqa: BLE001
                pass
            return {"ok": False, "error": "storage conflict, retry once: %s" % e}
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
                 "title": r["title"], "added": r["added"], "chunks": r["chunks"],
                 "content_type": r["content_type"] if "content_type" in r.keys() else None,
                 "final_url": r["final_url"] if "final_url" in r.keys() else None,
                 "snapshot": r["snapshot"] if "snapshot" in r.keys() else None}
                for r in rows]
    finally:
        db.close()


def read_source(ref: str, notebook: str | None = None,
                session: str | None = None, max_chars: int = 20000) -> dict:
    """Read indexed source text inside one global or current-session notebook."""
    ref = str(ref or "").strip()
    if not ref:
        return {"ok": False, "error": "source ref or id required"}
    try:
        limit = int(max_chars)
    except (TypeError, ValueError):
        limit = 20000
    limit = max(1, min(limit, 50000))
    session = str(session or "").strip() or None
    db = _connect()
    try:
        _init(db)
        if notebook:
            notebook = _resolve_id_db(db, notebook)
            nb_row = db.execute(
                "SELECT is_session, owner FROM notebooks WHERE id=?", (notebook,)
            ).fetchone()
            if not nb_row:
                return {"ok": False, "error": "no such notebook: %s" % notebook}
            if nb_row["is_session"] and nb_row["owner"] != session:
                return {"ok": False, "error": "session notebook is outside the current session"}
        elif session:
            notebook = _session_notebook(db, session, create=False)
            if not notebook:
                return {"ok": False, "error": "no indexed source in this session"}
        else:
            return {"ok": False, "error": "session or notebook required"}

        source = db.execute(
            "SELECT id, notebook, kind, ref, title, chunks FROM sources "
            "WHERE notebook=? AND (id=? OR ref=?) ORDER BY added DESC LIMIT 1",
            (notebook, ref, ref),
        ).fetchone()
        if not source:
            # JAG-565: `search` shows the model a TITLE/filename, so `read_source`
            # must accept it. Before this, the agent's honest follow-up failed with
            # "source not found" and the turn went in circles.
            base = os.path.basename(ref)
            loose = [row for row in db.execute(
                "SELECT id, notebook, kind, ref, title, chunks FROM sources "
                "WHERE notebook=? ORDER BY added DESC", (notebook,))
                if (ref in (row["title"], os.path.basename(str(row["ref"] or "")))
                    or base == os.path.basename(str(row["ref"] or "")))]
            if len(loose) == 1:
                source = loose[0]
            elif loose:
                # Audit F6: several same-named sources used to resolve SILENTLY
                # to the newest one. Refuse instead and name the candidates —
                # the model re-asks with the exact ref.
                seen = []
                for row in loose[:5]:
                    seen.append("%s (%s)" % (row["ref"], row["title"] or row["id"]))
                return {"ok": False,
                        "error": "ambiguous source %r: %d matches: %s"
                        % (ref, len(loose), "; ".join(seen))}
        if not source:
            return {"ok": False, "error": "source not found in the selected Knowledge scope"}
        stats = db.execute(
            "SELECT count(*) AS chunks, coalesce(sum(length(text)), 0) AS text_chars, "
            "coalesce(sum(CASE WHEN vec IS NOT NULL THEN 1 ELSE 0 END), 0) AS embedded "
            "FROM chunks WHERE source=?",
            (source["id"],),
        ).fetchone()
        chunk_count = int(stats["chunks"] or 0)
        total_chars = int(stats["text_chars"] or 0) + max(0, chunk_count - 1) * 2
        parts = []
        remaining = limit
        for index, row in enumerate(db.execute(
                "SELECT text FROM chunks WHERE source=? ORDER BY id",
                (source["id"],))):
            separator = "\n\n" if index else ""
            if separator:
                part = separator[:remaining]
                parts.append(part)
                remaining -= len(part)
                if remaining <= 0:
                    break
            chunk_text = str(row["text"] or "")
            part = chunk_text[:remaining]
            parts.append(part)
            remaining -= len(part)
            if len(part) < len(chunk_text) or remaining <= 0:
                break
        return {
            "ok": True,
            "source_id": source["id"],
            "notebook": source["notebook"],
            "kind": source["kind"],
            "ref": source["ref"],
            "title": source["title"],
            "chunks": chunk_count,
            "embedded_chunks": int(stats["embedded"] or 0),
            "total_chars": total_chars,
            "max_chars": limit,
            "truncated": total_chars > limit,
            "text": "".join(parts),
        }
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


def _diag_meta(d):
    """The extract diagnostic WITHOUT its full text (it is already chunked)."""
    if not isinstance(d, dict):
        return d
    return {k: v for k, v in d.items() if k != "text"}


def _rows_by_ids(db, ids, kind=None):
    """Full result rows for the SEMANTIC-only hits (same shape as the lexical one)."""
    if not ids:
        return []
    marks = ",".join("?" * len(ids))
    sql = ("SELECT c.id, c.source, c.path, c.lang, c.kind, c.name, c.start, c.end, c.text, "
           "s.notebook AS notebook, s.ref AS ref, s.title AS title, 0 AS rank, "
           "substr(c.text,1,160) AS snip FROM chunks c JOIN sources s ON s.id=c.source "
           "WHERE c.id IN (%s)" % marks)
    args = list(ids)
    if kind:
        sql += " AND c.kind = ?"
        args.append(kind)
    return [dict(r) for r in db.execute(sql, args)]


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


def search(query, notebook=None, k=8, kind=None, embed_model=None, session=None,
           include_text=False):
    """Return top-k chunks using BM25 or hybrid BM25/vector retrieval.

    JAG-431r6: ``session`` (optional) scopes the search to the session-owned notebook
    owned by that session (see ``_session_notebook``) — useful for "what did we
    learn in THIS chat?" without polluting the global notebooks.
    ``include_text=True`` adds each full extracted chunk for agent retrieval;
    API/UI callers keep the smaller snippet-only response by default.
    """
    query = str(query or "").strip()
    out = {"query": query, "notebook": notebook, "results": [], "mode": "bm25"}
    if not query:
        return out
    db = _connect()
    try:
        _init(db)
        if not db.execute("SELECT 1 FROM chunks LIMIT 1").fetchone():
            return out
        # JAG-431r6: a session scope resolves to that session's notebook
        # (lookup only — never create one just for a search).
        if session:
            notebook = _session_notebook(db, session, create=False)
        if notebook:
            notebook = _resolve_id_db(db, notebook)   # JAG-427: accept a name or an id
        terms = _sqlkit.terms(query)
        rows = []
        scope = " AND s.notebook = ?" if notebook else ""
        # JAG-431r6b: a GLOBAL search (no session / notebook scope) must not
        # leak the session notebooks. They are only reachable through an
        # explicit session scope (the FULL-approval path). An explicitly named
        # global notebook is unaffected.
        if not notebook:
            scope += " AND s.notebook IN (SELECT id FROM notebooks WHERE IFNULL(is_session,0) = 0)"
        # JAG-490: the query vector is computed BEFORE the lexical branch so a
        # paraphrase / cross-language query with zero keyword overlap still finds
        # its chunks. It used to re-rank only the bm25 hits, i.e. nothing.
        ref = embed_model if embed_model is not None else _cfg.embed_model()
        qv = _embed_texts_query(ref, query) if ref else None
        if terms and _has_fts(db):
            fts_q = _sqlkit.fts_match(terms)
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
        elif not qv:
            return out
        if qv:
            sem_ids, _cand = _vec.semantic_hits(
                db, qv, scope, [notebook] if notebook else [],
                limit=max(k * 3, 20))
            have = {r["id"] for r in rows}
            extra = [i for i in sem_ids if i not in have][:max(k * 3, 20)]
            if extra:
                rows += _rows_by_ids(db, extra, kind=kind)
            cand = _vec.vecs_for(db, [r["id"] for r in rows])
            if cand and _vec.fuse_rrf(rows, cand, qv):
                out["mode"] = "hybrid"
        for r in rows[:k]:
            score = r.get("rrf")
            result = {
                "notebook": r["notebook"], "source": r["source"], "ref": r["ref"],
                "title": r["title"], "path": r["path"], "name": r["name"], "kind": r["kind"],
                "lang": r["lang"], "start": r["start"], "end": r["end"],
                "score": round(score, 6) if score is not None else round(-(r["rank"] or 0), 6),
                "snippet": r.get("snip") or (r["text"] or "")[:200],
            }
            if include_text:
                result["text"] = r["text"] or ""
            out["results"].append(result)
        return out
    finally:
        db.close()


def _embed_texts_query(ref, query):
    """The query's flat float vector, or None (JAG-462; shared with the codebase index)."""
    return _vec.query_vector(ref, query)


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


def import_candidates(notebook, urls, session_id=None):
    """Import discovered URLs into a notebook or the requested session scope."""
    return add_sources(notebook, urls, session_id=session_id)


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
            _sqlkit.reset_tables(
                db, ("chunks", "chunks_fts", "sources", "notebooks", "meta"), _init)
            return {"ok": True}
        finally:
            db.close()
