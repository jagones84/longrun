"""Shared index configuration (JAG-400) — stdlib only.

One config governs BOTH stores (the per-workspace codebase index and the global
knowledge base): chunking window/overlap, ignore globs, size cap, and the optional
embedding model. Layering: DEFAULT_CONFIG <- ``config/index.yaml`` (tracked base)
<- ``data/index.overlay.yaml`` (gitignored user override).
"""
import json
import os
import threading

from longrun.util import paths

LOCK = threading.RLock()

CONFIG_PATH = os.path.join(paths.REPO_ROOT, "config", "index.yaml")
OVERLAY_PATH = os.path.join(paths.DATA_DIR, "index.overlay.yaml")

DEFAULT_CONFIG = {
    "enabled": True,
    "max_file_kb": 512,
    "chunk_lines": 60,
    "overlap_lines": 8,
    "ignore": ["*.min.js", "*.min.css", "*.map", "*.lock", "*.svg", "*.ipynb"],
    "embed_model": "",
    "embed_batch": 32,
}


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


def base_config():
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


def load_config():
    """Merged config: DEFAULT <- config/index.yaml <- data/index.overlay.yaml."""
    with LOCK:
        cfg = base_config()
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
        base = base_config()
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


def embed_model():
    """The configured embedding model ref ('' = lexical only)."""
    return str(load_config().get("embed_model") or "").strip()
