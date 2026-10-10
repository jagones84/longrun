"""Codebase + documentation knowledge index (JAG-397) — stdlib only.

Design (mirrors how the big IDEs do it):

* the index is ONE sqlite database per workspace, kept OUTSIDE the project, in
  the app data dir (``data/index/<slug>.db``), keyed by the workspace path — the
  same convention VS Code / Cursor use (``workspaceStorage`` / ``globalStorage``);
* retrieval is SQLite **FTS5** with ``bm25()`` + ``snippet()`` — built into
  CPython's sqlite3, so zero dependencies, fast and transactional;
* chunks are AST-aware for Python (the ``ast`` module) and heading/paragraph-aware
  for documents; a line-window is the fallback for other languages;
* vectors are OPTIONAL: when an embedding model is configured
  (``model.embed``) the chunk vectors are stored and retrieval becomes hybrid
  (bm25 + cosine, fused with Reciprocal Rank Fusion). No model -> bm25 only.
"""
import ast
import hashlib
import json
import os
import re
import sqlite3
import threading
import time
from fnmatch import fnmatch

from longrun.model import embed
from longrun.util import paths

LOCK = threading.RLock()

CONFIG_PATH = os.path.join(paths.REPO_ROOT, "config", "index.yaml")
OVERLAY_PATH = os.path.join(paths.DATA_DIR, "index.overlay.yaml")

DEFAULT_CONFIG = {
    "enabled": True,
    "automatic": False,
    "max_file_kb": 512,
    "chunk_lines": 60,
    "overlap_lines": 8,
    "ignore": ["*.min.js", "*.min.css", "*.map", "*.lock", "*.svg", "*.ipynb"],
    "embed_model": "",
    "embed_batch": 32,
}

# direct children of a root never scanned
_SKIP_DIRS = {
    ".git", ".hg", ".svn", "node_modules", "__pycache__", ".venv", "venv", "env",
    ".tox", "dist", "build", ".next", ".nuxt", "target", ".mypy_cache",
    ".pytest_cache", ".ruff_cache", "vendor", ".idea", ".eggs", "site-packages",
}
_CODE_EXT = {
    ".py": "python", ".js": "javascript", ".mjs": "javascript", ".cjs": "javascript",
    ".ts": "typescript", ".tsx": "typescript", ".jsx": "javascript", ".java": "java",
    ".go": "go", ".rs": "rust", ".rb": "ruby", ".c": "c", ".h": "c", ".cpp": "cpp",
    ".cc": "cpp", ".hpp": "cpp", ".cs": "csharp", ".php": "php", ".sh": "bash",
    ".bash": "bash", ".kt": "kotlin", ".kts": "kotlin", ".swift": "swift",
    ".sql": "sql", ".css": "css", ".html": "html", ".htm": "html", ".json": "json",
    ".yml": "yaml", ".yaml": "yaml", ".toml": "toml", ".xml": "xml", ".gradle": "groovy",
    ".scala": "scala", ".pl": "perl", ".lua": "lua", ".r": "r", ".dart": "dart",
    ".vue": "vue", ".svelte": "svelte", ".ex": "elixir", ".exs": "elixir",
    ".clj": "clojure", ".hs": "haskell",
}
_DOC_EXT = {".md": "markdown", ".markdown": "markdown", ".rst": "rst", ".txt": "text", ".adoc": "asciidoc"}
_EXTLESS = {"dockerfile": "dockerfile", "makefile": "makefile", "rakefile": "ruby", "procfile": "text"}


# --------------------------------------------------------------------- config --
def _yaml_load(text):
    try:
        import yaml
        return yaml.safe_load(text)
    except Exception:  # noqa: BLE001
        try:
            return json.loads(text)
        except Exception:  # noqa: BLE001
            return {}


def _yaml_dump(data):
    try:
        import yaml
        return yaml.safe_dump(data, sort_keys=False)
    except Exception:  # noqa: BLE001
        return json.dumps(data, indent=2)


def _base_config():
    """DEFAULT_CONFIG merged with config/index.yaml (the tracked base)."""
    cfg = dict(DEFAULT_CONFIG)
    try:
        if os.path.isfile(CONFIG_PATH):
            raw = _yaml_load(open(CONFIG_PATH, encoding="utf-8").read())
            if isinstance(raw, dict):
                cfg.update(raw)
    except Exception:  # noqa: BLE001
        pass
    return cfg


def load_config(reload=False):
    """Merged config: DEFAULT <- config/index.yaml <- data/index.overlay.yaml."""
    with LOCK:
        cfg = _base_config()
        try:
            if os.path.isfile(OVERLAY_PATH):
                raw = _yaml_load(open(OVERLAY_PATH, encoding="utf-8").read())
                if isinstance(raw, dict):
                    cfg.update(raw)
        except Exception:  # noqa: BLE001
            pass
        return cfg


def save_config(patch):
    """Persist only the keys that differ from the base, into the overlay."""
    with LOCK:
        base = _base_config()
        try:
            cur = {}
            if os.path.isfile(OVERLAY_PATH):
                cur = _yaml_load(open(OVERLAY_PATH, encoding="utf-8").read()) or {}
            if not isinstance(cur, dict):
                cur = {}
        except Exception:  # noqa: BLE001
            cur = {}
        for k, v in (patch or {}).items():
            if k in DEFAULT_CONFIG or k in base:
                if base.get(k) == v:
                    cur.pop(k, None)
                else:
                    cur[k] = v
        os.makedirs(os.path.dirname(OVERLAY_PATH), exist_ok=True)
        with open(OVERLAY_PATH, "w", encoding="utf-8") as f:
            f.write(_yaml_dump(cur))
        return load_config()


# ---------------------------------------------------------------------- paths --
def _slug(workspace):
    return hashlib.sha1(os.path.realpath(str(workspace)).encode("utf-8")).hexdigest()[:16]


def db_path(workspace):
    os.makedirs(paths.INDEX_DIR, exist_ok=True)
    return os.path.join(paths.INDEX_DIR, _slug(workspace) + ".db")


def _connect(workspace):
    db = sqlite3.connect(db_path(workspace), timeout=30)
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
        CREATE TABLE IF NOT EXISTS files(path TEXT PRIMARY KEY, mtime REAL, size INTEGER, hash TEXT, lang TEXT);
        CREATE TABLE IF NOT EXISTS sources(id TEXT PRIMARY KEY, kind TEXT, ref TEXT, added REAL, chunks INTEGER);
        CREATE TABLE IF NOT EXISTS chunks(
            id INTEGER PRIMARY KEY, path TEXT, lang TEXT, kind TEXT, name TEXT,
            start INTEGER, end INTEGER, tokens INTEGER, text TEXT, vec BLOB, source TEXT);
        CREATE INDEX IF NOT EXISTS chunks_path ON chunks(path);
        CREATE INDEX IF NOT EXISTS chunks_source ON chunks(source);
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
    for k, v in pairs.items():
        db.execute("INSERT OR REPLACE INTO meta(key, value) VALUES(?,?)", (k, json.dumps(v)))
    db.commit()


def _get_meta(db, key, default=None):
    try:
        row = db.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
        return json.loads(row["value"]) if row else default
    except Exception:  # noqa: BLE001
        return default


# -------------------------------------------------------------------- scanner --
def _load_gitignore(workspace):
    rules = []
    try:
        with open(os.path.join(workspace, ".gitignore"), encoding="utf-8", errors="replace") as f:
            for raw in f:
                line = raw.strip()
                if not line or line.startswith("#") or line.startswith("!"):
                    continue
                dironly = line.endswith("/")
                anchored = line.startswith("/")
                pat = line.strip("/")
                if pat:
                    rules.append({"pat": pat, "dir": dironly, "anchored": anchored})
    except Exception:  # noqa: BLE001
        pass
    return rules


def _git_ignored(rel, name, is_dir, rules):
    for r in rules:
        pat = r["pat"]
        if r["anchored"] or "/" in pat:
            if rel == pat or rel.startswith(pat + "/") or fnmatch(rel, pat):
                return True
        elif fnmatch(name, pat):
            return True
        if r["dir"] and is_dir and fnmatch(name, pat):
            return True
    return False


def _lang_for(rel):
    name = os.path.basename(rel).lower()
    ext = os.path.splitext(name)[1]
    if ext in _CODE_EXT:
        return _CODE_EXT[ext], "code"
    if ext in _DOC_EXT:
        return _DOC_EXT[ext], "doc"
    if name in _EXTLESS:
        return _EXTLESS[name], "code"
    return None, None


def _extra_ignored(name, rel, globs):
    return any(fnmatch(name, g) or fnmatch(rel, g) for g in (globs or []))


def _walk(workspace, cfg):
    """Yield rel paths of indexable files under `workspace`."""
    gi = _load_gitignore(workspace)
    globs = cfg.get("ignore") or []
    maxb = int(cfg.get("max_file_kb") or 512) * 1024
    root = os.path.realpath(workspace)
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames
                       if d not in _SKIP_DIRS and not d.startswith(".")]
        rel_dir = os.path.relpath(dirpath, root)
        keep = []
        for d in dirnames:
            rd = d if rel_dir == "." else os.path.join(rel_dir, d)
            if _git_ignored(rd, d, True, gi) or _extra_ignored(d, rd, globs):
                continue
            keep.append(d)
        dirnames[:] = keep
        for fn in filenames:
            rel = fn if rel_dir == "." else os.path.join(rel_dir, fn)
            lang, kind = _lang_for(rel)
            if not lang:
                continue
            if _git_ignored(rel, fn, False, gi) or _extra_ignored(fn, rel, globs):
                continue
            abspath = os.path.join(dirpath, fn)
            try:
                if os.path.getsize(abspath) > maxb:
                    continue
            except OSError:
                continue
            yield rel, abspath, lang, kind


def _read_text(abspath, max_kb):
    try:
        with open(abspath, "rb") as f:
            data = f.read(int(max_kb) * 1024 + 1)
    except OSError:
        return None
    if b"\x00" in data[:8192]:
        return None
    return data.decode("utf-8", "replace")


# ------------------------------------------------------------------- chunkers --
def _emit_range(out, lines, s, e, name, chunk_lines, overlap):
    overlap = max(0, min(overlap, chunk_lines - 1))
    while s < e:
        end = min(s + chunk_lines, e)
        body = "\n".join(lines[s:end]).strip()
        if body:
            out.append({"name": name, "start": s + 1, "end": end, "text": body})
        if end >= e:
            break
        s = end - overlap


def _chunk_python(text, chunk_lines, overlap):
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return None
    lines = text.splitlines()
    out = []
    tops = [n for n in tree.body
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))]
    first = min([n.lineno for n in tops], default=len(lines) + 1)
    if first > 1:
        head = "\n".join(lines[:first - 1]).strip()
        if head:
            out.append({"name": "<module>", "start": 1, "end": first - 1, "text": head})

    def add(name, node):
        s = max(getattr(node, "lineno", 1) - 1, 0)
        e = getattr(node, "end_lineno", None) or (s + 1)
        body = "\n".join(lines[s:e]).strip()
        if body:
            out.append({"name": name, "start": s + 1, "end": e, "text": body})

    for n in tops:
        if isinstance(n, ast.ClassDef):
            add(n.name, n)
            for m in n.body:
                if isinstance(m, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    add(n.name + "." + m.name, m)
        else:
            add(n.name, n)
    return out or None


def _chunk_doc(text, chunk_lines, overlap):
    lines = text.splitlines()
    n = len(lines)
    heads = [(i, re.sub(r"^#{1,6}\s+", "", lines[i]).strip()[:120])
             for i in range(n) if re.match(r"^#{1,6}\s+\S", lines[i])]
    out = []
    if not heads:
        _emit_range(out, lines, 0, n, "<doc>", chunk_lines, overlap)
        return out
    if heads[0][0] > 0:
        _emit_range(out, lines, 0, heads[0][0], "<intro>", chunk_lines, overlap)
    bounds = [h[0] for h in heads] + [n]
    for idx, (s, name) in enumerate(heads):
        _emit_range(out, lines, s, bounds[idx + 1], name, chunk_lines, overlap)
    return out


def _chunk_file(text, lang, kind, cfg):
    cl = int(cfg.get("chunk_lines") or 60)
    ov = int(cfg.get("overlap_lines") or 8)
    if lang == "python":
        got = _chunk_python(text, cl, ov)
        if got is not None:
            return got
    if kind == "doc":
        return _chunk_doc(text, cl, ov)
    out = []
    _emit_range(out, text.splitlines(), 0, len(text.splitlines()), "<file>", cl, ov)
    return out


# --------------------------------------------------------------------- build ---
def _vec_blob(vec):
    import array
    return array.array("f", vec).tobytes()


def _blob_vec(blob):
    import array
    a = array.array("f")
    a.frombytes(blob)
    return list(a)


def _embed_chunks(db, rows, ref, batch):
    """rows: list of (id, text). Store vectors when an embedding model answers."""
    if not ref or not rows:
        return 0
    done = 0
    for i in range(0, len(rows), max(1, batch)):
        part = rows[i:i + max(1, batch)]
        vecs = embed.embed_texts([t for _, t in part], model=ref)
        if not vecs:
            return done
        for (cid, _), v in zip(part, vecs):
            db.execute("UPDATE chunks SET vec=? WHERE id=?", (_vec_blob(v), cid))
        done += len(part)
    db.commit()
    return done


def build(workspace, force=False):
    """Index (or refresh) the workspace. Returns a stats dict."""
    workspace = os.path.realpath(str(workspace))
    cfg = load_config()
    ref = str(cfg.get("embed_model") or "").strip()
    batch = int(cfg.get("embed_batch") or 32)
    t0 = time.time()
    with LOCK:
        db = _connect(workspace)
        try:
            fts = _init(db)
            known = {r["path"]: (r["mtime"], r["size"]) for r in db.execute("SELECT path, mtime, size FROM files")}
            seen, files_n, chunks_n, embedded = set(), 0, 0, 0
            for rel, abspath, lang, kind in _walk(workspace, cfg):
                seen.add(rel)
                try:
                    st = os.stat(abspath)
                except OSError:
                    continue
                prev = known.get(rel)
                if not force and prev and abs(prev[0] - st.st_mtime) < 1e-6 and prev[1] == st.st_size:
                    continue
                text = _read_text(abspath, cfg.get("max_file_kb") or 512)
                if text is None:
                    continue
                _drop_path(db, rel)
                pieces = _chunk_file(text, lang, kind, cfg)
                ids = _insert_chunks(db, rel, lang, kind, pieces, source=None, fts=fts)
                db.execute("INSERT OR REPLACE INTO files(path, mtime, size, hash, lang) VALUES(?,?,?,?,?)",
                           (rel, st.st_mtime, st.st_size,
                            hashlib.sha1(text.encode("utf-8", "replace")).hexdigest(), lang))
                files_n += 1
                chunks_n += len(ids)
                if ref:
                    embedded += _embed_chunks(db, [(cid, p["text"]) for cid, p in zip(ids, pieces)], ref, batch)
            # drop files that vanished
            for rel in set(known) - seen:
                _drop_path(db, rel)
                db.execute("DELETE FROM files WHERE path=?", (rel,))
            db.commit()
            dim = _dim(db)
            _set_meta(db, {"workspace": workspace, "built_at": time.time(),
                           "embed_model": ref, "dim": dim, "fts": bool(fts)})
            return status(workspace)
        finally:
            db.close()


def _dim(db):
    row = db.execute("SELECT vec FROM chunks WHERE vec IS NOT NULL LIMIT 1").fetchone()
    return len(_blob_vec(row["vec"])) if row and row["vec"] else 0


def _drop_path(db, path):
    ids = [r["id"] for r in db.execute("SELECT id FROM chunks WHERE path=?", (path,))]
    if ids and _has_fts(db):
        db.executemany("DELETE FROM chunks_fts WHERE rowid=?", [(i,) for i in ids])
    db.execute("DELETE FROM chunks WHERE path=?", (path,))


def _insert_chunks(db, path, lang, kind, pieces, source, fts):
    ids = []
    for p in pieces or []:
        text = p.get("text") or ""
        if not text.strip():
            continue
        cur = db.execute(
            "INSERT INTO chunks(path, lang, kind, name, start, end, tokens, text, source) "
            "VALUES(?,?,?,?,?,?,?,?,?)",
            (path, lang, kind, p.get("name") or "", int(p.get("start") or 0),
             int(p.get("end") or 0), max(1, len(text) // 4), text, source))
        cid = cur.lastrowid
        if fts:
            db.execute("INSERT INTO chunks_fts(rowid, text, name, path) VALUES(?,?,?,?)",
                       (cid, text, p.get("name") or "", path))
        ids.append(cid)
    return ids


# -------------------------------------------------------------------- search ---
def _cos(a, b):
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = na = nb = 0.0
    for x, y in zip(a, b):
        dot += x * y
        na += x * x
        nb += y * y
    if na <= 0 or nb <= 0:
        return 0.0
    return dot / ((na ** 0.5) * (nb ** 0.5))


def search(workspace, query, k=8, kind=None, embed_model=None):
    """Return the top-k chunks for `query`. bm25 only, or bm25+cosine (RRF) when
    an embedding model is configured and vectors exist."""
    workspace = os.path.realpath(str(workspace))
    query = str(query or "").strip()
    out = {"query": query, "results": [], "mode": "bm25"}
    if not query:
        return out
    db = _connect(workspace)
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
            sql = "SELECT id, path, lang, kind, name, start, end, text, 0 AS rank, substr(text,1,160) AS snip FROM chunks WHERE " + like
            if kind:
                sql += " AND kind=?"
                args.append(kind)
            sql += " LIMIT ?"
            args.append(max(k * 5, 30))
            rows = [dict(r) for r in db.execute(sql, args)]
        else:
            return out
        ref = embed_model if embed_model is not None else str(load_config().get("embed_model") or "").strip()
        if ref and rows:
            qv = embed.embed_texts([query], model=ref)
            if qv:
                cand = _load_vecs(db, [r["id"] for r in rows])
                if cand:
                    K = 60
                    lex = {r["id"]: i for i, r in enumerate(rows)}
                    sem = sorted((( _cos(qv[0], v), cid) for cid, v in cand.items()), reverse=True)
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


def _load_vecs(db, ids):
    if not ids:
        return {}
    out = {}
    marks = ",".join("?" * len(ids))
    for r in db.execute("SELECT id, vec FROM chunks WHERE id IN (%s) AND vec IS NOT NULL" % marks, list(ids)):
        out[r["id"]] = _blob_vec(r["vec"])
    return out


# --------------------------------------------------------------- docs sources --
def _strip_html(html):
    html = re.sub(r"(?is)<(script|style)\b.*?</\1>", " ", html or "")
    text = re.sub(r"(?s)<[^>]+>", " ", html)
    text = re.sub(r"&nbsp;", " ", text)
    text = re.sub(r"&amp;", "&", text)
    text = re.sub(r"&lt;", "<", text)
    text = re.sub(r"&gt;", ">", text)
    text = re.sub(r"[ \t\u00a0]+", " ", text)
    return re.sub(r"\n\s*\n\s*\n+", "\n\n", text).strip()


def _fetch_url(url, timeout=20):
    import urllib.request
    req = urllib.request.Request(url, headers={"User-Agent": "longrun-index/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        ctype = (resp.headers.get("Content-Type") or "").lower()
        data = resp.read(2 * 1024 * 1024)
    text = data.decode("utf-8", "replace")
    if "html" in ctype or "<html" in text[:400].lower():
        return _strip_html(text)
    return text


def add_source(workspace, ref):
    """Index a doc source (URL or filesystem file/dir) as kind='doc'.

    Returns {'ok', 'source', 'chunks', 'error'}.
    """
    workspace = os.path.realpath(str(workspace))
    ref = str(ref or "").strip()
    if not ref:
        return {"ok": False, "error": "ref required"}
    cfg = load_config()
    db = _connect(workspace)
    try:
        fts = _init(db)
        sid = "doc:" + ref
        _remove_source_rows(db, sid)
        items = []  # (path, lang, kind, pieces)
        if ref.startswith("http://") or ref.startswith("https://"):
            try:
                text = _fetch_url(ref)
            except Exception as e:  # noqa: BLE001
                return {"ok": False, "error": "fetch failed: %s" % e}
            items.append((ref, "markdown", "doc", _chunk_doc(text, int(cfg.get("chunk_lines") or 60),
                                                             int(cfg.get("overlap_lines") or 8))))
        else:
            ap = os.path.realpath(os.path.expanduser(ref))
            if not os.path.exists(ap):
                return {"ok": False, "error": "path not found: %s" % ref}
            files = []
            if os.path.isdir(ap):
                for dp, dns, fns in os.walk(ap):
                    dns[:] = [d for d in dns if d not in _SKIP_DIRS and not d.startswith(".")]
                    for fn in fns:
                        files.append(os.path.join(dp, fn))
            else:
                files.append(ap)
            for fp in files:
                text = _read_text(fp, cfg.get("max_file_kb") or 512)
                if text is None:
                    continue
                items.append((fp, "markdown", "doc",
                              _chunk_doc(text, int(cfg.get("chunk_lines") or 60),
                                         int(cfg.get("overlap_lines") or 8))))
        n = 0
        for path, lang, kind, pieces in items:
            ids = _insert_chunks(db, path, lang, kind, pieces, source=sid, fts=fts)
            n += len(ids)
        db.execute("INSERT OR REPLACE INTO sources(id, kind, ref, added, chunks) VALUES(?,?,?,?,?)",
                   (sid, "url" if ref[:4] in ("http",) else "path", ref, time.time(), n))
        db.commit()
        return {"ok": True, "source": sid, "chunks": n}
    finally:
        db.close()


def _remove_source_rows(db, sid):
    if _has_fts(db):
        ids = [r["id"] for r in db.execute("SELECT id FROM chunks WHERE source=?", (sid,))]
        for i in ids:
            db.execute("DELETE FROM chunks_fts WHERE rowid=?", (i,))
    db.execute("DELETE FROM chunks WHERE source=?", (sid,))
    db.execute("DELETE FROM sources WHERE id=?", (sid,))


def list_sources(workspace):
    db = _connect(workspace)
    try:
        _init(db)
        return [dict(r) for r in db.execute("SELECT id, kind, ref, added, chunks FROM sources ORDER BY added DESC")]
    finally:
        db.close()


def remove_source(workspace, sid):
    db = _connect(workspace)
    try:
        _init(db)
        _remove_source_rows(db, sid)
        db.commit()
        return {"ok": True, "removed": sid}
    finally:
        db.close()


# -------------------------------------------------------------------- status ---
def status(workspace):
    workspace = os.path.realpath(str(workspace))
    cfg = load_config()
    p = db_path(workspace)
    out = {
        "enabled": bool(cfg.get("enabled", True)), "workspace": workspace, "db": p,
        "exists": os.path.isfile(p), "automatic": bool(cfg.get("automatic")),
        "embed_model": str(cfg.get("embed_model") or ""), "files": 0, "chunks": 0,
        "docs": 0, "dim": 0, "built_at": None, "fts": False, "size_kb": 0,
    }
    if not out["exists"]:
        return out
    try:
        out["size_kb"] = round(os.path.getsize(p) / 1024.0, 1)
    except OSError:
        pass
    db = _connect(workspace)
    try:
        _init(db)
        out["files"] = db.execute("SELECT count(*) c FROM files").fetchone()["c"]
        out["chunks"] = db.execute("SELECT count(*) c FROM chunks").fetchone()["c"]
        out["docs"] = db.execute("SELECT count(*) c FROM sources").fetchone()["c"]
        out["dim"] = _dim(db)
        out["built_at"] = _get_meta(db, "built_at")
        out["fts"] = bool(_get_meta(db, "fts", _has_fts(db)))
        return out
    finally:
        db.close()


def list_files(workspace):
    """The indexed files (rel path, language, chunk count), biggest first."""
    workspace = os.path.realpath(str(workspace))
    db = _connect(workspace)
    try:
        _init(db)
        rows = db.execute(
            "SELECT f.path AS path, f.lang AS lang, count(c.id) AS chunks "
            "FROM files f LEFT JOIN chunks c ON c.path = f.path "
            "GROUP BY f.path ORDER BY chunks DESC, f.path").fetchall()
        return {"workspace": workspace, "files": [dict(r) for r in rows]}
    finally:
        db.close()


def clear(workspace):
    workspace = os.path.realpath(str(workspace))
    with LOCK:
        db = _connect(workspace)
        try:
            for t in ("chunks", "chunks_fts", "files", "sources", "meta"):
                try:
                    db.execute("DROP TABLE IF EXISTS %s" % t)
                except sqlite3.OperationalError:
                    pass
            db.commit()
            _init(db)
            return {"ok": True}
        finally:
            db.close()
