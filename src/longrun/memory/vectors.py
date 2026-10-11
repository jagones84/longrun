"""Shared vector helpers for the index stores (JAG-400 / JAG-403) — stdlib only.

Both the per-workspace codebase index and the global knowledge base store optional
chunk vectors (float32 blobs) and fuse lexical + semantic ranking the same way.

JAG-403: every embedding batch is logged into the cost log (tokens + USD cost).
The cost is EXACT for OpenRouter (it returns ``usage.cost``), and ESTIMATED for
direct providers (price from the catalogue × tokens).
"""
import array

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


def embed_chunks(db, rows, ref, batch, scope=None, scope_id=None, op=None):
    """Embed rows in batches and persist the vectors.

    `rows` is a list of (id, text). `scope` / `scope_id` / `op` tag the cost
    log (e.g. scope="codebase", scope_id="<ws hash>", op="build").

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
