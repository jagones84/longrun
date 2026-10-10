"""Embedding models catalogue + cost math (JAG-403) — stdlib only.

The catalogue ships with KNOWN embedding models from common providers
(OpenAI, Voyage, Cohere, Jina, OpenRouter) with per-1M-token pricing in USD.
Local models (BGE, e5, nomic via llama.cpp / Ollama / TEI) are FREE
(``price_per_mtok = 0``). Users may add custom models via the overlay
(``data/index.overlay.yaml::custom_models``).

Cost source:
  - Direct providers (OpenAI, Voyage, Cohere, Jina) -> ESTIMATED from the
    declared price (no per-call USD in the response).
  - OpenRouter -> EXACT (``usage.cost`` is returned in USD in the response).
  - Local / custom-free -> 0.
  - Unknown model -> 0 (logged with a `unknown` flag for triage).
"""
import os
import threading

from longrun.memory import indexcfg
from longrun.util import paths

LOCK = threading.RLock()

# Known catalogue. `dim` is approximate (the model may report a different
# dim if sliced, e.g. text-embedding-3-* supports Matryoshka). `notes` are
# user-facing, English only.
MODELS = [
    # OpenAI direct
    {"id": "openai:text-embedding-3-small", "provider": "openai",
     "label": "OpenAI text-embedding-3-small", "dim": 1536,
     "price_per_mtok": 0.02, "notes": "Cheap, solid, 1536d (truncatable to 256/512/1024)."},
    {"id": "openai:text-embedding-3-large", "provider": "openai",
     "label": "OpenAI text-embedding-3-large", "dim": 3072,
     "price_per_mtok": 0.13, "notes": "Best OpenAI quality, large, expensive."},
    {"id": "openai:text-embedding-ada-002", "provider": "openai",
     "label": "OpenAI text-embedding-ada-002", "dim": 1536,
     "price_per_mtok": 0.10, "notes": "Legacy, still widely used."},
    # Voyage AI
    {"id": "voyage:voyage-3", "provider": "voyage",
     "label": "Voyage 3", "dim": 1024,
     "price_per_mtok": 0.06, "notes": "Strong general-purpose."},
    {"id": "voyage:voyage-3-lite", "provider": "voyage",
     "label": "Voyage 3 Lite", "dim": 512,
     "price_per_mtok": 0.02, "notes": "Cheap, smaller, fast."},
    {"id": "voyage:voyage-code-3", "provider": "voyage",
     "label": "Voyage Code 3", "dim": 1024,
     "price_per_mtok": 0.06, "notes": "Optimised for source code."},
    # Cohere
    {"id": "cohere:embed-english-v3.0", "provider": "cohere",
     "label": "Cohere embed-english-v3.0", "dim": 1024,
     "price_per_mtok": 0.10, "notes": "English only."},
    {"id": "cohere:embed-multilingual-v3.0", "provider": "cohere",
     "label": "Cohere embed-multilingual-v3.0", "dim": 1024,
     "price_per_mtok": 0.10, "notes": "Multilingual."},
    # Jina
    {"id": "jina:jina-embeddings-v3", "provider": "jina",
     "label": "Jina embeddings v3", "dim": 1024,
     "price_per_mtok": 0.02, "notes": "Multilingual, Matryoshka."},
    # OpenRouter (cost returned by OR — recorded as REAL)
    {"id": "openrouter:openai/text-embedding-3-small", "provider": "openrouter",
     "label": "OpenRouter · OpenAI 3-small", "dim": 1536,
     "price_per_mtok": 0.02, "notes": "OpenRouter returns the exact USD cost."},
    {"id": "openrouter:openai/text-embedding-3-large", "provider": "openrouter",
     "label": "OpenRouter · OpenAI 3-large", "dim": 3072,
     "price_per_mtok": 0.13, "notes": "OpenRouter returns the exact USD cost."},
    {"id": "openrouter:qwen/qwen3-embedding-8b", "provider": "openrouter",
     "label": "OpenRouter · Qwen3 Embedding 8B", "dim": 4096,
     "price_per_mtok": 0.05, "notes": "Qwen, multilingual."},
    {"id": "openrouter:google/gemini-embedding-001", "provider": "openrouter",
     "label": "OpenRouter · Gemini Embedding 001", "dim": 3072,
     "price_per_mtok": 0.025, "notes": "Google Gemini embeddings."},
    # Local / self-hosted — FREE.
    {"id": "local:BAAI/bge-small-en-v1.5", "provider": "local",
     "label": "BGE small EN v1.5 (local)", "dim": 384,
     "price_per_mtok": 0.0, "notes": "Local, free, 384d, English."},
    {"id": "local:BAAI/bge-large-en-v1.5", "provider": "local",
     "label": "BGE large EN v1.5 (local)", "dim": 1024,
     "price_per_mtok": 0.0, "notes": "Local, free, 1024d, English."},
    {"id": "local:BAAI/bge-m3", "provider": "local",
     "label": "BGE-M3 (local, multilingual)", "dim": 1024,
     "price_per_mtok": 0.0, "notes": "Local, free, multilingual + code."},
    {"id": "local:intfloat/e5-large-v2", "provider": "local",
     "label": "E5 large v2 (local)", "dim": 1024,
     "price_per_mtok": 0.0, "notes": "Local, free, English."},
    {"id": "local:nomic-ai/nomic-embed-text-v1.5", "provider": "local",
     "label": "Nomic Embed v1.5 (local)", "dim": 768,
     "price_per_mtok": 0.0, "notes": "Local, free, long context."},
]


def all_models():
    """Catalogue + custom models from the overlay (if any)."""
    base = list(MODELS)
    try:
        custom = indexcfg.load_config().get("custom_models") or []
        if isinstance(custom, list):
            for m in custom:
                if isinstance(m, dict) and m.get("id"):
                    base.append(dict(m))
    except Exception:  # noqa: BLE001
        pass
    return base


def find(model_id):
    """Look up a catalogue entry by id (returns None if unknown)."""
    if not model_id:
        return None
    for m in all_models():
        if m.get("id") == model_id:
            return m
    return None


def active_model():
    """The configured embedding model ('' = lexical only, no model active)."""
    try:
        return indexcfg.embed_model()
    except Exception:  # noqa: BLE001
        return ""


def load_config():
    """Full config (delegate to ``indexcfg.load_config``)."""
    return indexcfg.load_config()


def save_config(patch):
    """Persist overlay keys (active model + custom model catalogue)."""
    return indexcfg.save_config(patch or {})


def set_active(model_id):
    """Persist the new active model into the overlay."""
    return indexcfg.save_config({"embed_model": model_id or ""})


def estimate_cost(model_id, tokens):
    """Estimated USD for a batch of N tokens with `model_id`.

    Returns 0.0 for unknown models. Local models are free.
    """
    try:
        n = float(tokens or 0)
    except (TypeError, ValueError):
        n = 0.0
    if n <= 0:
        return 0.0
    m = find(model_id)
    if not m:
        return 0.0
    price = float(m.get("price_per_mtok") or 0.0)
    if price <= 0.0:
        return 0.0
    return round(price * (n / 1_000_000.0), 9)
