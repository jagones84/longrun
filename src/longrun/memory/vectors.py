"""Shared vector helpers for the index stores (JAG-400) — stdlib only.

Both the per-workspace codebase index and the global knowledge base store optional
chunk vectors (float32 blobs) and fuse lexical + semantic ranking the same way.
"""
import array

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


def embed_chunks(db, rows, ref, batch):
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
            db.execute("UPDATE chunks SET vec=? WHERE id=?", (vec_blob(v), cid))
        done += len(part)
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
