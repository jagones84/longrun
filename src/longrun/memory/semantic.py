#!/usr/bin/env python3
"""The ONE owner of the warm-only semantic half of a discovery search.

`skills.search` and `self.tools {query}` both rank a small, bounded catalogue
(skills, tools) by blending a lexical score with a cosine over short texts.
The embedding model is loaded once at service start by `memory`; a discovery
call must NEVER pay the ~9 s model load, so `ready()` answers from the already
loaded process state and a cold process (CLI, test) stays purely lexical — the
answer keeps its shape, only the ranking is narrower.

One cache NAMESPACE per caller: a tool search and a skill search hold different
text sets, and sharing one slot made each call re-embed the other's library.
"""

import hashlib

#: Floor a row must clear to enter on semantics ALONE (no lexical hit).
MIN_COS = 0.30

_CACHE: dict[str, dict] = {}          # namespace -> {"sig": str, "vecs": ndarray}


def ready():
    """True only when the embedding backend is ALREADY loaded in this process."""
    try:
        from longrun.memory import memory as _mem
        return getattr(_mem, "_EMBEDDER", None) is not None
    except Exception:  # noqa: BLE001 — searching must never break on this
        return False


def scores(texts, query, namespace="default"):
    """Cosine(query, text) per text, or None when the backend is unavailable.

    The per-namespace cache is keyed by a digest of the text set, so a changed
    catalogue (a new tool, an edited SKILL.md) re-embeds it once, and a caller
    whose texts are unchanged pays nothing.
    """
    try:
        import numpy as np
        from longrun.memory import memory as _mem
        texts = [str(t or "") for t in texts]
        sig = hashlib.sha1("\x00".join(texts).encode("utf-8")).hexdigest()
        slot = _CACHE.get(namespace) or {}
        if slot.get("sig") != sig or slot.get("vecs") is None:
            vecs = _mem._embed_batch(texts)
            if vecs is None:
                return None
            slot = {"sig": sig, "vecs": vecs}
            _CACHE[namespace] = slot
        qv = _mem._embed_batch([str(query)])
        if qv is None:
            return None
        q = np.asarray(qv)[0]
        v = np.asarray(slot["vecs"])
        if v.ndim != 2 or len(q) != v.shape[1]:
            return None          # a bag-of-words fallback cannot align with ST vectors
        return [float(x) for x in (v @ q)]
    except Exception:  # noqa: BLE001 — the lexical half is always the answer
        return None
