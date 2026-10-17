"""Embedding models catalogue + cost math (JAG-403) — stdlib only.

The catalogue ships as a PERSONAL, editable config file (``config/embedding.yaml``),
NOT hardcoded in Python. A tiny built-in fallback (``BASIC``) is used only when
that file is missing, so the app still works out of the box. Personal additions
and removals persist in the index overlay
(``data/index.overlay.yaml::custom_models`` / ``::disabled_models``), which
OVERRIDES the tracked catalogue on an id collision.

Cost source:
  - Direct providers (OpenAI, Voyage, Cohere, Jina) -> ESTIMATED from the
    declared ``price_per_mtok`` (no per-call USD in the response).
  - OpenRouter -> EXACT (``usage.cost`` is returned in USD in the response).
  - Local / custom-free -> 0.
  - Unknown model -> 0 (recorded with an `unknown` flag for triage).
"""
import os
import threading

from longrun.memory import indexcfg
from longrun.util import paths
from longrun.util.dataio import load_yaml as _yaml_load

LOCK = threading.RLock()

CATALOGUE_PATH = os.path.join(paths.REPO_ROOT, "config", "embedding.yaml")

# Last-resort fallback ONLY when config/embedding.yaml is missing. The user
# asked for "no hardcoded models except the basics" — this is that minimum.
BASIC = [
    {"id": "openai:text-embedding-3-small", "provider": "openai",
     "label": "OpenAI text-embedding-3-small", "dim": 1536, "price_per_mtok": 0.02,
     "notes": "Basic fallback entry."},
    {"id": "local:BAAI/bge-small-en-v1.5", "provider": "local",
     "label": "BGE small EN v1.5 (local)", "dim": 384, "price_per_mtok": 0.0,
     "notes": "Basic fallback entry (local, free)."},
]


def _clean(m):
    """Keep only well-formed catalogue entries."""
    if not isinstance(m, dict) or not m.get("id"):
        return None
    out = {"id": str(m["id"]), "provider": str(m.get("provider") or "custom"),
           "label": str(m.get("label") or m["id"])}
    try:
        out["dim"] = int(m.get("dim") or 0)
    except (TypeError, ValueError):
        out["dim"] = 0
    try:
        out["price_per_mtok"] = float(m.get("price_per_mtok") or 0.0)
    except (TypeError, ValueError):
        out["price_per_mtok"] = 0.0
    if m.get("notes"):
        out["notes"] = str(m["notes"])
    return out


def _load_catalogue():
    """Read config/embedding.yaml -> list of models (BASIC if it is missing)."""
    models = []
    try:
        if os.path.isfile(CATALOGUE_PATH):
            with open(CATALOGUE_PATH, encoding="utf-8") as f:
                raw = _yaml_load(f.read())
            items = raw.get("models") if isinstance(raw, dict) else raw
            if isinstance(items, list):
                models = [c for c in (_clean(x) for x in items) if c]
    except Exception:  # noqa: BLE001
        models = []
    return models or [dict(b) for b in BASIC]


# Module-level snapshot (introspection + tests). Live reads use all_models().
MODELS = _load_catalogue()


def _overlay():
    try:
        return indexcfg.load_config()
    except Exception:  # noqa: BLE001
        return {}


def all_models():
    """Catalogue + personal overlay: custom entries win by id; disabled hidden."""
    cfg = _overlay()
    by_id = {}
    order = []
    for m in _load_catalogue():
        by_id[m["id"]] = m
        order.append(m["id"])
    custom = cfg.get("custom_models") or []
    if isinstance(custom, list):
        for raw in custom:
            c = _clean(raw)
            if c:
                if c["id"] not in by_id:
                    order.append(c["id"])
                by_id[c["id"]] = c
    disabled = set(cfg.get("disabled_models") or [])
    return [by_id[i] for i in order if i not in disabled]


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


def _shipped_ids():
    return [m["id"] for m in _load_catalogue()]


def add_model(spec):
    """Add (or re-enable) a personal embedding model in the overlay."""
    c = _clean(spec)
    if not c:
        return {"ok": False, "error": "a model id is required"}
    cfg = _overlay()
    custom = [x for x in (cfg.get("custom_models") or []) if isinstance(x, dict)
              and x.get("id") != c["id"]]
    custom.append(c)
    disabled = [i for i in (cfg.get("disabled_models") or []) if i != c["id"]]
    indexcfg.save_config({"custom_models": custom, "disabled_models": disabled})
    return {"ok": True, "model": c}


def remove_model(model_id):
    """Remove a model: drop it from the overlay, else hide a shipped entry."""
    model_id = str(model_id or "").strip()
    if not model_id:
        return {"ok": False, "error": "a model id is required"}
    cfg = _overlay()
    custom = [x for x in (cfg.get("custom_models") or []) if isinstance(x, dict)
              and x.get("id") != model_id]
    removed_custom = len(custom) != len(cfg.get("custom_models") or [])
    disabled = [i for i in (cfg.get("disabled_models") or []) if i != model_id]
    if not removed_custom and model_id in _shipped_ids():
        disabled.append(model_id)
    indexcfg.save_config({"custom_models": custom, "disabled_models": disabled})
    return {"ok": True, "removed": model_id}


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
