"""Shared vector helpers for the index stores (JAG-400 / JAG-403) — stdlib only.

Both the per-workspace codebase index and the global knowledge base store optional
chunk vectors (float32 blobs) and fuse lexical + semantic ranking the same way.

JAG-403: every embedding batch is logged into the cost log (tokens + USD cost).
The cost is EXACT for OpenRouter (it returns ``usage.cost``), and ESTIMATED for
direct providers (price from the catalogue × tokens).
"""
import array
import os
from collections.abc import Callable

from longrun.memory import costlog, embedcfg
from longrun.model import embed


def vec_blob(vec):
    return array.array("f", vec).tobytes()


def blob_vec(blob):
    a = array.array("f")
    a.frombytes(blob)
    return list(a)


def dim(db):
    row = db.execute("SELECT vec FROM chunks WHERE vec IS NOT NULL LIMIT 1").fetchone()
    return len(blob_vec(row["vec"])) if row and row["vec"] else 0


def embed_chunks(db, rows, ref, batch, scope=None, scope_id=None, op=None,
                 progress: Callable[[int, int], None] | None = None):
    """Embed rows in batches and persist the vectors.

    `rows` is a list of (id, text). `scope` / `scope_id` / `op` tag the cost
    log (e.g. scope="codebase", scope_id="<ws hash>", op="build").
    `progress` receives the completed and total row counts after each batch.

    Returns the number of rows successfully embedded.
    """
    if not ref or not rows:
        return 0
    done = 0
    est_total = 0.0
    est_tokens = 0
    for i in range(0, len(rows), max(1, batch)):
        part = rows[i:i + max(1, batch)]
        # embed_texts() drops empty/non-string inputs, so filter here too to
        # keep zip() lengths aligned (otherwise a mismatch silently skips
        # vectors for the trailing chunks while `done` overcounts them).
        part = [(cid, t) for cid, t in part if isinstance(t, str) and t.strip()]
        if not part:
            continue
        out = embed.embed_texts([t for _, t in part], model=ref)
        if not out:
            return done
        vecs, usage = out
        if not vecs:
            return done
        for (cid, _), v in zip(part, vecs):
            db.execute("UPDATE chunks SET vec=? WHERE id=?", (vec_blob(v), cid))
        done += len(part)
        # JAG-403: cost accumulation. Prefer the EXACT cost from the provider
        # (OpenRouter returns it in `usage.cost`); fall back to the catalogue
        # estimate when the provider does not report one.
        tokens = int((usage or {}).get("tokens") or 0)
        real = (usage or {}).get("cost_usd")
        est = None
        if real is None and tokens > 0:
            est = embedcfg.estimate_cost(ref, tokens)
            est_total += est
            est_tokens += tokens
        if (real is not None and float(real) > 0) or (est is not None and est > 0) or tokens > 0:
            try:
                provider = (embedcfg.find(ref) or {}).get("provider", "")
                costlog.record(model=ref, provider=provider, tokens=tokens,
                               est_cost_usd=est, real_cost_usd=real,
                               scope=scope, scope_id=scope_id, op=op)
            except Exception:  # noqa: BLE001 — cost logging must never break indexing
                pass
        if progress:
            try:
                progress(done, len(rows))
            except Exception:  # noqa: BLE001 — progress reporting must not break indexing
                pass
    db.commit()
    return done


def cos(a, b):
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


def query_vector(ref, query):
    """The FIRST embedding vector for ``query``, or None (JAG-462).

    ``embed.embed_texts`` returns the TUPLE ``(vecs, usage)``. Handing ``vecs``
    itself to ``cos()`` compared a length-mismatched list and silently degraded
    hybrid search to lexical-only, so the caller must get a flat float vector.
    """
    out = embed.embed_texts([query], model=ref)
    vecs = out[0] if out else None
    return (vecs[0] if vecs else None)


def vecs_for(db, ids):
    """``{chunk id: vector}`` for those of ``ids`` that already carry one."""
    if not ids:
        return {}
    marks = ",".join("?" * len(ids))
    return {row["id"]: blob_vec(row["vec"]) for row in db.execute(
        "SELECT id, vec FROM chunks WHERE id IN (%s) AND vec IS NOT NULL" % marks, list(ids))}


def semantic_hits(db, qv, where_sql="", where_args=(), limit=20, cap=None):
    """The nearest chunks by cosine, INDEPENDENT of the lexical candidates.

    JAG-490: hybrid search used to re-rank ONLY the bm25 hits, so a paraphrase
    (or a query in another language) with no keyword overlap returned NOTHING
    even though every chunk had a vector. This scans the scoped vectors and
    returns ``(ids, {id: vec})`` for the top ``limit``.

    ``cap`` bounds the scan (default 20 000) so a huge notebook stays responsive;
    numpy is used when present, with a pure-python fallback.
    """
    cap = int(cap or os.environ.get("LONGRUN_VECTOR_SCAN") or 20000)
    sql = ("SELECT c.id AS id, c.vec AS vec FROM chunks c "
           "JOIN sources s ON s.id = c.source WHERE c.vec IS NOT NULL" + (where_sql or ""))
    rows = db.execute(sql + " LIMIT ?", tuple(where_args or ()) + (cap,)).fetchall()
    if not rows:
        return [], {}
    scored = []
    try:
        import numpy as np
        mat = np.frombuffer(b"".join(bytes(r["vec"]) for r in rows), dtype=np.float32)
        mat = mat.reshape(len(rows), -1)
        q = np.asarray(qv, dtype=np.float32)
        if mat.shape[1] != q.shape[0]:
            return [], {}
        denom = np.linalg.norm(mat, axis=1) * (float(np.linalg.norm(q)) or 1.0) + 1e-9
        sims = (mat @ q) / denom
        scored = sorted(((float(sims[i]), i) for i in range(len(rows))), reverse=True)[:limit]
    except Exception:  # noqa: BLE001 — no numpy (or a bad blob): pure python
        scored = sorted(((cos(qv, blob_vec(r["vec"])), i) for i, r in enumerate(rows)),
                        reverse=True)[:limit]
    ids = [rows[i]["id"] for _s, i in scored if _s > -1.0]
    cand = {rows[i]["id"]: blob_vec(rows[i]["vec"]) for _s, i in scored if _s > -1.0}
    return ids, cand


def fuse_rrf(rows, cand, qv, k=60):
    """Reciprocal Rank Fusion of the lexical order and the semantic ranks, in place.

    ``rows`` are the lexical hits in rank order; ``cand`` maps chunk id -> vector.
    Adds ``rrf`` to every row and re-sorts by it. Returns True when it ran.
    """
    if not cand:
        return False
    lex = {r["id"]: i for i, r in enumerate(rows)}
    sem = sorted(((cos(qv, v), cid) for cid, v in cand.items()), reverse=True)
    sem_rank = {cid: i for i, (_, cid) in enumerate(sem)}
    for r in rows:
        r["rrf"] = 1.0 / (k + lex[r["id"]]) + 1.0 / (k + sem_rank.get(r["id"], 10 ** 6))
    rows.sort(key=lambda r: -r["rrf"])
    return True
