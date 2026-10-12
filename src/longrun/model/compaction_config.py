"""JAG-431r: load the compaction policy from `config/compaction.yaml`.

The file is the single source of truth for `trigger_pct`, `target_pct`,
`keep_recent`, and the summarizer's `instruction`/`max_chars`. The previous
implementation read scattered env vars and module-level constants; this loader
fixes that in one place so a user can tune compaction behaviour WITHOUT a code
edit and WITHOUT a service restart (the file is hot-path).

The loader is intentionally tiny: `load()` returns a plain dict, with safe
defaults substituted for any missing key. Callers cache via `@lru_cache` so we
re-read the file only when its mtime changes.
"""
import os
import time
import threading

try:
    import yaml  # PyYAML — already a dependency
except ImportError:                # pragma: no cover — bare-bones fallback
    yaml = None

_LOCK = threading.Lock()
_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))), "config", "compaction.yaml")

# Defaults match the values recommended in config/compaction.yaml. If the file
# disappears or a key is missing we still behave sensibly (the values match
# the file the user just shipped, so the user never sees a sudden policy shift).
_DEFAULTS = {
    "trigger_pct": 70.0,
    "target_pct": 30.0,
    "keep_recent": 4,
    "summarizer": {
        "input_max_chars": 40000,
        "output_max_chars": 6000,
        "instruction": (
            "Compress the OLDER turns above into the smallest faithful summary "
            "possible. TARGET: ~10x compression of the input. KEEP (one line "
            "each): decisions, concrete facts, open questions, file paths and "
            "function names referenced, the user's stated preferences. DROP: "
            "greetings, narration, partial reasoning, meta-commentary. FORMAT: "
            "terse bullets, no role prefixes, no preamble. Reply in the same "
            "language as the transcript."
        ),
    },
}

_CACHE = {"mtime": None, "data": None}


def _read():
    if not os.path.isfile(_PATH):
        return dict(_DEFAULTS)
    if yaml is None:
        # Bare-bones YAML loader for the very small subset we use: top-level
        # keys, 2-space indent, scalar values, `|` block scalars for the long
        # instruction string. This keeps the policy file editable even on a
        # minimal install.
        return _fallback_yaml(_PATH)
    try:
        with open(_PATH, encoding="utf-8") as f:
            raw = yaml.safe_load(f) or {}
    except Exception:
        return dict(_DEFAULTS)
    return _merge(_DEFAULTS, raw.get("compaction") or {})


def _merge(defaults, override):
    out = dict(defaults)
    for k, v in (override or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge(out[k], v)
        else:
            out[k] = v
    return out


def _fallback_yaml(path):
    """Tiny YAML subset reader — used only when PyYAML is not installed.

    Supports:
      - top-level keys under `compaction:`
      - two-space indent for `summarizer:` subkeys
      - scalars: numbers, `true`/`false`, or rest-of-line as a string
      - `|` block scalar for multi-line values (the summarizer instruction)
    """
    out = {"compaction": {}}
    section = None
    in_block = False
    block_key = None
    block_buf = []
    with open(path, encoding="utf-8") as f:
        for ln in f:
            if in_block:
                if ln.startswith("      ") or ln.strip() == "":
                    block_buf.append(ln[6:] if ln.startswith("      ") else ln.rstrip("\n"))
                    continue
                # block ended
                out["compaction"].setdefault(section, {})[block_key] = "\n".join(block_buf).rstrip()
                in_block = False
                block_buf = []
            if not ln.strip() or ln.lstrip().startswith("#"):
                continue
            stripped = ln.rstrip()
            if stripped.startswith("compaction:"):
                section = None
                continue
            if ln.startswith("  ") and not ln.startswith("    "):
                key = ln.strip().rstrip(":")
                section = key
                out["compaction"].setdefault(section, {})
                continue
            if ln.startswith("    ") and not ln.startswith("      "):
                # either a key:value line or the start of a block scalar
                body = ln[4:].rstrip()
                if ":" in body and not body.lstrip().startswith("|"):
                    k, _, v = body.partition(":")
                    v = v.strip()
                    if v.startswith("[") and v.endswith("]"):
                        v = [x.strip() for x in v[1:-1].split(",") if x.strip()]
                    elif v.lower() in ("true", "false"):
                        v = (v.lower() == "true")
                    else:
                        try:
                            v = int(v) if "." not in v else float(v)
                        except ValueError:
                            v = v.strip('"').strip("'")
                    out["compaction"].setdefault(section, {})[k] = v
                    continue
                if body.lstrip().startswith("|"):
                    in_block = True
                    block_key = body.split(":", 1)[0].strip()
                    block_buf = []
                    continue
        if in_block:
            out["compaction"].setdefault(section, {})[block_key] = "\n".join(block_buf).rstrip()
    return out


def load(force=False):
    """Return the parsed policy dict, refreshing on file mtime change."""
    with _LOCK:
        try:
            mtime = os.path.getmtime(_PATH)
        except OSError:
            mtime = None
        if force or _CACHE["mtime"] != mtime or _CACHE["data"] is None:
            _CACHE["data"] = _read().get("compaction") or dict(_DEFAULTS)
            _CACHE["mtime"] = mtime
        return _CACHE["data"]


def reset_cache():
    """Used by tests; forces the next `load()` to re-read the file."""
    with _LOCK:
        _CACHE["mtime"] = None
        _CACHE["data"] = None


def path():
    return _PATH


if __name__ == "__main__":  # quick smoke test
    import json as _j
    print(_j.dumps(load(force=True), indent=2)[:1500])