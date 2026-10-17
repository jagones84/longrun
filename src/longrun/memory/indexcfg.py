"""Shared index configuration (JAG-400) — stdlib only.

One config governs BOTH stores (the per-workspace codebase index and the global
knowledge base): chunking window/overlap, ignore globs, size cap, and the optional
embedding model. Layering: DEFAULT_CONFIG <- ``config/index.yaml`` (tracked base)
<- ``data/index.overlay.yaml`` (gitignored user override).
"""
import os
import threading

from longrun.util import paths
from longrun.util.dataio import dump_yaml as _yaml_dump, load_yaml

LOCK = threading.RLock()

CONFIG_PATH = os.path.join(paths.REPO_ROOT, "config", "index.yaml")
OVERLAY_PATH = os.path.join(paths.DATA_DIR, "index.overlay.yaml")

DEFAULT_CONFIG = {
    "enabled": True,
    "max_file_kb": 512,
    # JAG-415: before an agent searches a workspace, run a quick INCREMENTAL
    # re-index and make the caller WAIT for it (see codeindex.ensure_fresh). This
    # keeps the index fresh without a background "indexing…" state that would block
    # a second agent — several agents on one workspace simply serialize on the
    # build lock, and the refresh is cheap when nothing changed.
    "auto_index": True,
    # JAG-403j: binary documents (PDF/DOCX/…) may be much larger than code files.
    "doc_max_kb": 25600,
    "chunk_lines": 60,
    "overlap_lines": 8,
    "ignore": ["*.min.js", "*.min.css", "*.map", "*.lock", "*.svg", "*.ipynb"],
    # JAG-403j: a SHIPPED default so a fresh clone has a working embedding model
    # (not an empty field). The overlay still overrides it — set "" to force bm25-only.
    "embed_model": "cohere:embed-multilingual-v3.0",
    "embed_batch": 32,
    # JAG-403: user-added embedding models (provider/id/dim/price_per_mtok).
    "custom_models": [],
    # JAG-403: catalogue entries the user hid in the personal config.
    "disabled_models": [],
    # JAG-403b: the active research model id (``perplexity:sonar-pro`` by default).
    "research_model": "",
    "research_active": "",
}


def _yaml_load(text):
    """YAML (or JSON) text -> a mapping; ``{}`` on garbage (JAG-483)."""
    return load_yaml(text, default={})


def base_config():
    """DEFAULT_CONFIG merged with config/index.yaml (the tracked base)."""
    cfg = dict(DEFAULT_CONFIG)
    try:
        if os.path.isfile(CONFIG_PATH):
            with open(CONFIG_PATH, encoding="utf-8") as f:
                raw = _yaml_load(f.read())
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
                with open(OVERLAY_PATH, encoding="utf-8") as f:
                    raw = _yaml_load(f.read())
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
                with open(OVERLAY_PATH, encoding="utf-8") as f:
                    cur = _yaml_load(f.read()) or {}
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


def auto_index():
    """True when an agent's codebase search must refresh the index first (JAG-415).

    Defaults to True; a user can turn it off from the Codebase panel checkbox.
    """
    return bool(load_config().get("auto_index", True))
