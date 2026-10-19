#!/usr/bin/env python3
"""Longrun persistent memory store — v0.3

Write-rules: append-only markdown documents with an optional vector-similarity
index (via numpy cosine-sim). Records are written on semantically significant
harness events (plan update, task complete, tool result, chat summary) and can
be retrieved by keyword or semantic similarity.

Two backends:
- **flat** — markdown files in `data/memory/` (always on; no deps)
- **vector** — numpy-based cosine similarity on sentence embeddings
  (requires `numpy` and optionally `sentence-transformers` or a local embedding
  endpoint; uses a bag-of-words fallback if neither is available)

Rules:
- Every write has a timestamp, kind, session/run id, and freeform content.
- Old entries are never mutated (append-only).
- The vector index is rebuilt on server start and after every N writes.
"""

import json
import os
import re
import threading
import time
import uuid

from longrun.tools import registry

REPO = registry.REPO
DATA_DIR = os.path.join(REPO, "data", "memory")

_lock = threading.RLock()
_writes_since_index = 0
_REBUILD_INTERVAL = 20  # rebuild vector index every N writes

# ---------------------------------------------------------------- markdown ----

MEMORY_FIELDS = {
    "tool.result": "tool_result.md",
    "plan.update": "plan_updates.md",
    "task.done": "task_done.md",
    "chat.summary": "chat_summaries.md",
    "agent.note": "agent_notes.md",
    "memory.store": "user_memories.md",
    # JAG-204: append-only tombstones that invalidate a stored memory (BAVAR:
    # verification must also cover persistent, reusable artifacts).
    "memory.invalidate": "memory_invalidations.md",
}


def _path(kind):
    fn = MEMORY_FIELDS.get(kind, "other.md")
    p = os.path.join(DATA_DIR, fn)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    return p


# ------------------------------------------------------------- core block ----
# JAG-127f: an always-visible, agent-editable "core memory" block (the Letta /
# MemGPT pattern): durable facts the model rewrites itself, injected into every
# system prompt. Unlike the similarity-retrieved notes above, this is stable and
# the agent owns it (memory{action:'core'|'set_core'}).
CORE_PATH = os.path.join(DATA_DIR, "core.md")
CORE_MAX = int(os.environ.get("LONGRUN_CORE_MAX", "4000"))


def core_read():
    """The CORE memory block (empty string when never written)."""
    try:
        with open(CORE_PATH, "r", encoding="utf-8") as f:
            return f.read()
    except OSError:
        return ""


def core_write(content):
    """Replace the CORE memory block (capped at CORE_MAX chars). Returns {ok, chars}."""
    os.makedirs(DATA_DIR, exist_ok=True)
    text = str(content or "")[:CORE_MAX]
    tmp = CORE_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(text)
    os.replace(tmp, CORE_PATH)
    return {"ok": True, "chars": len(text)}


def store(kind, content, **meta):
    """Write one append-only record.

    Args:
        kind: one of the MEMORY_FIELDS keys (or any string; unknown kinds
              go to other.md)
        content: the main text payload
        meta: key=value pairs stored as YAML front-matter (id, session,
              run_id, tags, etc.)

    Returns the record dict.
    """
    global _writes_since_index
    score = float(meta.pop("score", 1.0))
    with _lock:
        rec = {
            "mid": uuid.uuid4().hex[:8],
            "ts": round(time.time(), 3),
            "kind": kind,
            "content": str(content)[:8000],
            "score": score,
            **{k: str(v)[:500] for k, v in meta.items()},
        }
        md = _render_md(rec)
        p = _path(kind)
        with open(p, "a", encoding="utf-8") as f:
            f.write(md + "\n")
        _writes_since_index += 1
        if _writes_since_index >= _REBUILD_INTERVAL:
            _rebuild_index()
    return rec


def _render_md(rec):
    """Render a record as a multi-line markdown block."""
    lines = ["---"]
    # JAG-447: `origin` is the provenance/segregation key (user | agent |
    # reflect | mining | harness); rendered so recall and the WebUI can tell
    # auto-generated knowledge from what the user actually said.
    for key in ("mid", "ts", "kind", "session", "run_id", "source", "origin",
                "expires_ts", "target", "tags", "model", "tool", "score"):
        val = rec.get(key)
        if val is not None:
            lines.append("%s: %s" % (key, val))
    lines.append("---")
    # JAG-212 (v212): a content line equal to "---" would look like a record
    # delimiter and tear THIS record in two (its id would survive only on the
    # truncated first half). Guard it with a leading backslash; the parser strips
    # it back on read, so the stored content is preserved byte-for-byte.
    body = []
    for cl in str(rec.get("content", "")).strip().split("\n"):
        if cl.strip() == "---":
            cl = "\\" + cl
        body.append(cl)
    lines.append("\n".join(body))
    lines.append("")
    return "\n".join(lines)


# ------------------------------------------------------------------ query ----

def query(term=None, kind=None, limit=20):
    """Search memory by keyword (substring/regex) and/or kind.

    Returns up to `limit` records sorted by recency (newest first).
    """
    out = []
    kinds = [kind] if kind else list(MEMORY_FIELDS.keys()) + ["other"]
    for k in kinds:
        p = _path(k)
        if not os.path.isfile(p):
            continue
        for rec in _parse_md_file(p):
            if term and not _match(rec.get("content", ""), term):
                continue
            out.append(rec)
    out.sort(key=lambda r: r.get("ts", 0), reverse=True)
    return out[:limit]


def _match(text, term):
    """Case-insensitive LITERAL match, with an AND-of-words fallback.

    JAG-207 (v207): the previous version ran `re.search(term, text)` on
    caller-supplied text, so a pathological pattern like `(a+)+$` caused
    catastrophic backtracking — a DoS on recall/health. No `re` on user input.
    """
    if not term:
        return False
    low = str(text).lower()
    term_l = str(term).lower()
    if term_l in low:
        return True
    # fall back to AND-of-words: every meaningful word must appear
    words = [w for w in re.split(r"\W+", term_l) if len(w) > 2]
    return bool(words) and all(w in low for w in words)


def _parse_md_file(path):
    """Parse records from an append-only markdown file.

    Each record is written as::

        ---
        <front-matter key: value lines>
        ---
        <content>

    JAG-204 fix: the previous implementation split on every `\\n---\\n`, which
    tore the front-matter away from its own content (so `ts`, `kind`, `source`
    were lost on read and every store surfaced as two records). Parse with a
    line state machine instead so a record keeps its metadata AND content.
    """
    records = []
    # JAG-207 (v207): a corrupt / non-UTF8 byte in an append-only file must not
    # crash recall/health — decode leniently instead.
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        raw = f.read()
    rec = None
    in_front = False
    buf = []

    def flush():
        nonlocal rec, buf
        if rec is None:
            return
        rec["content"] = "\n".join(l for l in buf if l.strip()).strip()
        if rec.get("content") or rec.get("kind"):
            records.append(rec)
        rec = None
        buf = []

    for line in raw.split("\n"):
        if line.strip() == "---":
            if rec is None or not in_front:
                # opening delimiter of a new record (start, or after content)
                flush()
                rec = {"content": ""}
                in_front = True
            else:
                # closing delimiter of the front-matter → content follows
                in_front = False
            continue
        if rec is None:
            # legacy content-only block before any front-matter
            rec = {"content": ""}
            in_front = False
        if in_front:
            if ":" in line:
                key, _, val = line.partition(":")
                key = key.strip()
                if key:
                    rec[key] = _cast_field(key, val.strip())
                continue
            in_front = False  # front-matter ended without a closing delimiter
        if line.startswith("\\") and line[1:].strip() == "---":
            line = line[1:]  # JAG-212: unescape a guarded '---' content line
        buf.append(line)
    flush()
    return records


# JAG-210 (v204 regression): front-matter fields that are GENUINELY numeric.
# Everything else must stay a STRING. A hex `mid` can be all digits (e.g.
# "33263015"); the old code ran int() on every value, so such an id came back as
# an int and an identity check by string silently missed the record — a ~16%
# flake in the memory suite (A2/B1/A5/C2). Only these fields are cast.
_NUMERIC_FIELDS = frozenset(("ts", "expires_ts", "score"))


def _cast_field(key, val):
    if key in _NUMERIC_FIELDS:
        return _cast(val)
    return val


def _cast(val):
    for fn in (int, float):
        try:
            return fn(val)
        except (ValueError, TypeError):
            continue
    if val.lower() in ("true", "yes"): return True
    if val.lower() in ("false", "no"): return False
    if val.strip().startswith("[") or val.strip().startswith("{"):
        try:
            return json.loads(val)
        except (json.JSONDecodeError, ValueError):
            pass
    return val


# ---------------------------------------------------------- vector index ----

_vector_db = None  # {kind: {vectors: [[…]], records: [{…}], dim: int}}


def _rebuild_index():
    """Rebuild the in-memory vector index from all markdown files."""
    global _vector_db, _writes_since_index
    try:
        import numpy as np  # noqa: F401
    except ImportError:
        _vector_db = {}
        _writes_since_index = 0
        return
    db = {}
    for kind, fn in MEMORY_FIELDS.items():
        p = os.path.join(DATA_DIR, fn)
        if not os.path.isfile(p):
            continue
        records = _parse_md_file(p)
        if not records:
            continue
        texts = [r.get("content", "")[:2000] for r in records]
        vocab = _build_vocab(texts)
        vecs = _embed_batch(texts, vocab)
        if vecs is not None and len(vecs) == len(records):
            db[kind] = {"vectors": vecs, "records": records,
                        "dim": len(vecs[0]), "vocab": vocab}
    _vector_db = db
    _writes_since_index = 0


def _build_vocab(texts):
    """Sorted vocabulary shared by index and query bag-of-words vectors."""
    vocab = set()
    for t in texts:
        vocab.update(t.lower().split())
    return sorted(vocab)


_EMBEDDER = None
_EMBEDDER_READY = False
_EMBEDDER_LOCK = threading.Lock()
_ENDPOINT_DISABLED = False


def _get_embedder():
    """Load the sentence-transformer backend ONCE and reuse it (JAG-72).

    The old code constructed `SentenceTransformer(...)` on EVERY search — seconds
    of work (and, on a cold cache, a possible multi-minute model download) per
    turn. That is the main reason the agent looked "inactive". Now it is loaded a
    single time; if it is unavailable we remember that and never retry.
    """
    global _EMBEDDER, _EMBEDDER_READY
    if _EMBEDDER_READY:
        return _EMBEDDER
    with _EMBEDDER_LOCK:
        if not _EMBEDDER_READY:
            try:
                from sentence_transformers import SentenceTransformer
                _EMBEDDER = SentenceTransformer("all-MiniLM-L6-v2", device="cpu")
            except Exception:
                _EMBEDDER = None
            _EMBEDDER_READY = True
    return _EMBEDDER


def _embed_batch(texts, vocab=None):
    """Return a list of numpy vectors, or None if no embedding backend works.

    `vocab` pins the bag-of-words dimensionality: the query vector must use
    the exact vocab the index was built with or the cosine product misaligns.
    """
    # Priority: sentence-transformers (GPU-friendly) > local endpoint > bag-of-words
    global _ENDPOINT_DISABLED
    model = _get_embedder()
    if model is not None:
        try:
            return model.encode(texts, show_progress_bar=False, normalize_embeddings=True)
        except Exception:
            pass
    if not _ENDPOINT_DISABLED:
        try:
            import urllib.request
            import json as j
            body = j.dumps({"model": "default", "input": texts}).encode()
            req = urllib.request.Request(
                "http://127.0.0.1:8080/v1/embeddings", data=body,
                headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = j.loads(resp.read().decode())
            emb = [d["embedding"] for d in data.get("data", [])]
            import numpy as np
            return np.array(emb) / np.linalg.norm(emb, axis=1, keepdims=True)
        except Exception:
            # JAG-72: one failed probe disables it for the session so we never
            # pay this timeout again (it used to be 30s per kind, per call).
            _ENDPOINT_DISABLED = True
    try:
        import numpy as np
        # bag-of-words fallback over the shared vocab
        if vocab is None:
            vocab = _build_vocab(texts)
        w2i = {w: i for i, w in enumerate(vocab)}
        vecs = np.zeros((len(texts), len(vocab)), dtype=np.float32)
        for i, t in enumerate(texts):
            for w in t.lower().split():
                if w in w2i:
                    vecs[i, w2i[w]] += 1
        norms = np.linalg.norm(vecs, axis=1, keepdims=True)
        norms[norms == 0] = 1
        return vecs / norms
    except Exception:
        return None


def semantic_query(query_text, kind=None, limit=10, min_score=0.15):
    """Semantic similarity search over the vector index.

    Returns [(score, record)] sorted by descending score.
    """
    if _vector_db is None:
        _rebuild_index()
    if not _vector_db:
        # fallback to keyword query
        return [(1.0, r) for r in query(query_text, kind, limit)]
    try:
        import numpy as np
    except ImportError:
        return [(1.0, r) for r in query(query_text, kind, limit)]
    results = []
    for k, db in _vector_db.items():
        if kind and k != kind:
            continue
        # embed the query with this kind's own vocab (bag-of-words dims must
        # match the index exactly); sentence-transformer embeddings are
        # backend-wide so this is a no-op there
        vec = _embed_batch([query_text], db.get("vocab"))
        if vec is None or db["vectors"].shape[1] != vec.shape[1]:
            continue
        scores = np.dot(db["vectors"], vec[0])
        for i, score in enumerate(scores):
            if score >= min_score:
                results.append((float(score), db["records"][i]))
    results.sort(key=lambda x: x[0], reverse=True)
    return results[:limit]


# ----------------------------------------------------------- public API ----

def write(kind, content, **meta):
    """Store a memory record and return it."""
    return store(kind, content, **meta)


def search(query_text, kind=None, limit=10, semantic=False):
    """Search memory: keyword or semantic."""
    if semantic:
        return semantic_query(query_text, kind, limit)
    return [(1.0, r) for r in query(query_text, kind, limit)]


# JAG-95: governed recall — score + time-decay + dedupe. The score is harness-
# set (the agent never rates its own memory), which guards against "memory
# reward inflation" (arXiv 2608.00017); decay keeps stale lessons from crowding
# fresh ones; dedupe prevents context collapse from repeated near-identical
# lessons (arXiv 2609.33013).
HALFLIFE_SECS = 7 * 86400.0


def effective_score(rec, now=None, halflife=None):
    """Time-decayed score: score * 0.5 ** (age / halflife)."""
    now = now if now is not None else time.time()
    hl = halflife if halflife is not None else HALFLIFE_SECS
    try:
        s = float(rec.get("score") or 1.0)
    except (TypeError, ValueError):
        s = 1.0
    try:
        age = max(0.0, now - float(rec.get("ts") or now))
    except (TypeError, ValueError):
        age = 0.0
    return s * (0.5 ** (age / max(hl, 1.0)))


def _norm(content):
    return re.sub(r"\W+", " ", str(content).lower()).strip()


def dedupe(records, threshold=0.85):
    """Drop near-duplicate records by token-overlap (Jaccard-like)."""
    seen = []
    for r in records:
        rt = set(filter(None, _norm(r.get("content", "")).split()))
        if not rt:
            seen.append(r)
            continue
        dup = False
        for s in seen:
            st = set(filter(None, _norm(s.get("content", "")).split()))
            if not st:
                continue
            inter = len(rt & st)
            if inter / max(1, min(len(rt), len(st))) >= threshold:
                dup = True
                break
        if not dup:
            seen.append(r)
    return seen


def rank(records, now=None, halflife=None):
    """Sort records by effective (decayed + scored) relevance, best first."""
    return sorted(records,
                  key=lambda r: effective_score(r, now=now, halflife=halflife),
                  reverse=True)


def invalid_targets():
    """Set of memory ids (mid) invalidated by an append-only tombstone (JAG-204)."""
    p = _path("memory.invalidate")
    if not os.path.isfile(p):
        return set()
    out = set()
    for r in _parse_md_file(p):
        t = str(r.get("target") or "").strip()
        if t:
            out.add(t)
    return out


def is_expired(rec, now=None):
    """True when a record carries an expires_ts in the past (JAG-204)."""
    exp = rec.get("expires_ts")
    if exp in (None, ""):
        return False
    try:
        return float(exp) <= (now if now is not None else time.time())
    except (TypeError, ValueError):
        return False


def is_valid(rec, now=None, invalid=None):
    """A record is VALID unless expired or explicitly invalidated."""
    if is_expired(rec, now=now):
        return False
    bad = invalid if invalid is not None else invalid_targets()
    return str(rec.get("mid") or "") not in bad


def invalidate(target, reason=""):
    """Append a tombstone invalidating a stored memory (mid, or free text).

    Append-only: the original record is never mutated; recall just stops surfacing
    it. Returns the tombstone record.
    """
    return store("memory.invalidate", reason or "invalidated",
                 target=str(target or "").strip())


def _rewrite_records(path, recs):
    """Atomically replace an append-only file with `recs` (used by forget)."""
    tmp = "%s.%s.tmp" % (path, os.getpid())
    with open(tmp, "w", encoding="utf-8") as f:
        for r in recs:
            f.write(_render_md(r) + "\n")
    os.replace(tmp, path)


def forget(target):
    """Physically DELETE a stored memory by `mid` (true delete, JAG-317).

    `invalidate` is a soft, append-only tombstone: the record stays on disk and is
    merely hidden from recall. `forget` is the real thing — it rewrites the owning
    markdown file without the record and drops any tombstone that targeted it.
    Returns ``{ok, removed, files}``.
    """
    target = str(target or "").strip()
    if not target:
        return {"ok": False, "error": "target required"}
    removed, files = 0, []
    with _lock:
        for kind in list(MEMORY_FIELDS.keys()) + ["other"]:
            p = _path(kind)
            if not os.path.isfile(p):
                continue
            recs = _parse_md_file(p)
            keep = [r for r in recs if str(r.get("mid") or "") != target]
            if len(keep) != len(recs):
                removed += len(recs) - len(keep)
                _rewrite_records(p, keep)
                files.append(os.path.basename(p))
        # a tombstone that points at a now-deleted record is meaningless
        p = _path("memory.invalidate")
        if os.path.isfile(p):
            recs = _parse_md_file(p)
            keep = [r for r in recs if str(r.get("target") or "") != target]
            if len(keep) != len(recs):
                _rewrite_records(p, keep)
        _rebuild_index()
    return {"ok": True, "removed": removed, "files": files}


def purge_invalidated():
    """Physically remove every record that is invalidated or expired (JAG-317).

    The bulk form of `forget`: compacts the append-only files by dropping all
    tombstones and the records they (or an expiry) cover. Returns {ok, removed}.
    """
    bad = invalid_targets()
    now = time.time()
    removed = 0
    with _lock:
        for kind in list(MEMORY_FIELDS.keys()) + ["other"]:
            if kind == "memory.invalidate":
                continue
            p = _path(kind)
            if not os.path.isfile(p):
                continue
            recs = _parse_md_file(p)
            keep = [r for r in recs
                    if str(r.get("mid") or "") not in bad
                    and not is_expired(r, now=now)]
            if len(keep) != len(recs):
                removed += len(recs) - len(keep)
                _rewrite_records(p, keep)
        # drop the tombstones too (they have been applied)
        p = _path("memory.invalidate")
        if os.path.isfile(p):
            _rewrite_records(p, [])
        _rebuild_index()
    return {"ok": True, "removed": removed}


def governed_query(kind=None, limit=6, halflife=None, threshold=0.85,
                   include_invalid=False):
    """Retrieve deduped, score+decay-ranked records (governed recall).

    JAG-204: invalidated (tombstoned) and expired records are dropped unless
    `include_invalid`.
    """
    recs = query(None, kind, limit=500)
    if not include_invalid:
        bad = invalid_targets()
        now = time.time()
        recs = [r for r in recs if is_valid(r, now=now, invalid=bad)]
    base = dedupe(rank(recs, halflife=halflife), threshold)[:limit]
    try:
        from longrun.core import matrix as _mtx
        aug = _mtx.call_hook("memory", "augment_recall", kind, base, limit, default=base)
        if isinstance(aug, list):
            return aug
    except Exception:  # noqa: BLE001
        pass
    return base


def health():
    """Read-only memory health: counts of expired / invalidated / no-source."""
    recs = query(None, None, limit=100000)
    bad = invalid_targets()
    now = time.time()
    expired = sum(1 for r in recs if is_expired(r, now=now))
    invalidated = sum(1 for r in recs if str(r.get("mid") or "") in bad)
    stores = [r for r in recs if r.get("kind") == "memory.store"]
    no_source = sum(1 for r in stores if not r.get("source"))
    return {"total": len(recs), "stores": len(stores), "expired": expired,
            "invalidated": invalidated, "no_source": no_source,
            "invalid_targets": sorted(bad)[:20]}


# JAG-447: kinds the HARNESS writes on its own (telemetry + distilled lessons),
# as opposed to `memory.store` which is deliberate provenance-tagged knowledge.
AUTO_KINDS = frozenset(("agent.note", "tool.result", "plan.update",
                        "task.done", "chat.summary"))


def provenance(limit=3000):
    """Segregation report: how much memory is machine-generated vs user-authored.

    Groups every record by `kind` and by `source`/`origin`, and summarises the
    split (auto-written telemetry/lessons vs. deliberate `memory.store`). This is
    what the WebUI "Improvement" panel shows to answer "what did the harness
    write on its own?". Never raises.
    """
    try:
        recs = query(None, None, limit=limit)
    except Exception:  # noqa: BLE001 — a report must never raise
        recs = []
    by_kind, by_source = {}, {}
    for r in recs:
        k = str(r.get("kind") or "other")
        by_kind[k] = by_kind.get(k, 0) + 1
        s = str(r.get("source") or r.get("origin") or "unattributed")
        by_source[s] = by_source.get(s, 0) + 1
    auto = sum(v for k, v in by_kind.items() if k in AUTO_KINDS)
    user = by_kind.get("memory.store", 0)
    return {"by_kind": by_kind, "by_source": by_source,
            "auto": auto, "user": user, "total": len(recs)}


def stats():
    """Return counts per kind and whether the vector index is available."""
    kinds = {}
    for k, fn in MEMORY_FIELDS.items():
        p = os.path.join(DATA_DIR, fn)
        if os.path.isfile(p):
            kinds[k] = len(_parse_md_file(p))
        else:
            kinds[k] = 0
    has_numpy = False
    try:
        import numpy  # noqa: F401
        has_numpy = True
    except ImportError:
        pass
    return {"kinds": kinds, "total": sum(kinds.values()),
            "vector_index": _vector_db is not None,
            "numpy_available": has_numpy}


def init():
    """Load the vector index at startup."""
    _rebuild_index()


# auto-init
init()
