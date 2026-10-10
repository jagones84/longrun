"""Embeddings for the knowledge index (JAG-397).

Stdlib-only and OpenAI-compatible. A batch of texts is embedded through, in order:

1. the configured embedding model ref (``<provider>:<model>``, e.g.
   ``openrouter:openai/text-embedding-3-small``) resolved via the providers table;
2. the local llama.cpp router (``ROUTER_BASE + /v1/embeddings``, model ``default``).

Every failure is non-fatal: callers fall back to lexical (bm25) retrieval, so the
index works with no embedding model at all.
"""
import json
import urllib.request

# Offered in the Models settings dropdown (OpenRouter's embedding catalogue).
SUGGESTED = [
    "openrouter:openai/text-embedding-3-small",
    "openrouter:openai/text-embedding-3-large",
    "openrouter:qwen/qwen3-embedding-8b",
    "openrouter:mistralai/mistral-embed",
    "openrouter:google/gemini-embedding-001",
]
TIMEOUT = 30


def model_ref():
    """The configured embedding model ref ('' = lexical only)."""
    try:
        from longrun.memory import index as _index
        return str((_index.load_config() or {}).get("embed_model") or "").strip()
    except Exception:  # noqa: BLE001
        return ""


def _post(url, headers, model, texts, timeout):
    body = json.dumps({"model": model, "input": list(texts)}).encode("utf-8")
    req = urllib.request.Request(url, data=body, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8", "replace"))
    except Exception:  # noqa: BLE001
        return None
    items = data.get("data")
    if not isinstance(items, list):
        return None
    out = [None] * len(texts)
    for it in items:
        if not isinstance(it, dict):
            continue
        try:
            i = int(it.get("index", 0))
        except (TypeError, ValueError):
            i = 0
        vec = it.get("embedding")
        if isinstance(vec, list) and 0 <= i < len(out):
            out[i] = [float(x) for x in vec]
    if any(v is None for v in out):
        return None
    return out


def embed_texts(texts, model=None, timeout=TIMEOUT):
    """Embed a batch -> list of float vectors, or None when unavailable."""
    texts = [t for t in (texts or []) if isinstance(t, str) and t.strip()]
    if not texts:
        return []
    ref = (model if model is not None else model_ref()) or ""
    if ref:
        try:
            from longrun.model import providers
            hit = providers.resolve(ref)
        except Exception:  # noqa: BLE001
            hit = None
        if hit:
            p, mid = hit
            base = (p.get("base_url") or "").rstrip("/")
            if base:
                return _post(base + "/embeddings", providers.headers(p), mid, texts, timeout)
    try:
        from longrun.model import rllm
        base = (getattr(rllm, "ROUTER_BASE", "") or "").rstrip("/")
    except Exception:  # noqa: BLE001
        base = ""
    if base:
        return _post(base + "/v1/embeddings", {"Content-Type": "application/json"},
                     "default", texts, timeout)
    return None


def probe(model=None, timeout=TIMEOUT):
    """One test embedding -> {'ok', 'model', 'dim'|'error'} (for the UI / Model Test)."""
    ref = model if model is not None else model_ref()
    vec = embed_texts(["dimension probe"], model=ref, timeout=timeout)
    if not vec:
        return {"ok": False, "model": ref or "(local default)",
                "error": "no embeddings endpoint answered"}
    return {"ok": True, "model": ref or "(local default)", "dim": len(vec[0])}
