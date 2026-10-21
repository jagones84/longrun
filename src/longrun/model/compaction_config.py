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
# JAG-487: this file is at <repo>/src/longrun/model/, so THREE dirnames landed on
# `src/` — `_PATH` pointed at `src/config/compaction.yaml` (nonexistent) and the
# loader silently served the hard-coded defaults: every edit to the shipped policy
# file was dead. Use the central anchor (4 levels up) instead.
try:
    from longrun.util.paths import REPO_ROOT as _REPO
except Exception:  # pragma: no cover — never let path setup break imports
    _REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__)))))
_PATH = os.path.join(_REPO, "config", "compaction.yaml")
# JAG-487: user overrides saved by the WebUI live in a SIBLING overlay, exactly like
# `providers.local.yaml` / `mcp_clients.local.yaml`. The shipped file keeps its
# comments; the overlay wins key-by-key and is hot-reloaded with it.
_LOCAL_PATH = os.path.join(os.path.dirname(_PATH), "compaction.local.yaml")

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
        "max_parts": 24,
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


def _read_file(path):
    """Return the `compaction:` section of ONE policy file ({} when absent/broken)."""
    if not os.path.isfile(path):
        return {}
    if yaml is None:
        # Bare-bones YAML loader for the very small subset we use: top-level
        # keys, 2-space indent, scalar values, `|` block scalars for the long
        # instruction string. This keeps the policy file editable even on a
        # minimal install.
        return (_fallback_yaml(path) or {}).get("compaction") or {}
    try:
        with open(path, encoding="utf-8") as f:
            raw = yaml.safe_load(f) or {}
    except Exception:
        return {}
    if isinstance(raw, dict) and isinstance(raw.get("compaction"), dict):
        return raw["compaction"]
    return raw if isinstance(raw, dict) else {}


def _read():
    # Shipped policy first, then the WebUI overlay (JAG-487).
    return _merge(_merge(dict(_DEFAULTS), _read_file(_PATH)), _read_file(_LOCAL_PATH))


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
    """Return the parsed policy dict, refreshing when either file changes."""
    with _LOCK:
        try:
            mtime = (os.path.getmtime(_PATH), os.path.getmtime(_LOCAL_PATH))
        except OSError:
            try:
                mtime = (os.path.getmtime(_PATH), None)
            except OSError:
                mtime = (None, None)
        if force or _CACHE["mtime"] != mtime or _CACHE["data"] is None:
            # JAG-462: `_read()` already returns the UNWRAPPED policy dict (it merges
            # `raw["compaction"]` over `_DEFAULTS`). Calling `.get("compaction")` on it
            # always returned None, so `config/compaction.yaml` was SILENTLY IGNORED and
            # the hard-coded defaults won — every user edit to the compaction policy
            # (trigger/target/keep_recent/summarizer) was dead. Accept BOTH shapes so a
            # raw document is handled too.
            data = _read()
            if isinstance(data, dict) and isinstance(data.get("compaction"), dict):
                data = data["compaction"]
            _CACHE["data"] = data or dict(_DEFAULTS)
            _CACHE["mtime"] = mtime
        return _CACHE["data"]


def reset_cache():
    """Used by tests; forces the next `load()` to re-read the file."""
    with _LOCK:
        _CACHE["mtime"] = None
        _CACHE["data"] = None


def path():
    return _PATH


def local_path():
    """The WebUI-owned overlay (JAG-487); absent until the user saves a policy."""
    return _LOCAL_PATH


def save(trigger_pct=None, target_pct=None, keep_recent=None, patch=None):
    """Persist the user-tunable policy keys into the local overlay.

    Writes only the keys passed (the rest keep coming from the shipped file), so
    `config/compaction.yaml` and its comments are never rewritten. The loader
    picks the new values up on the next access — no service restart (JAG-487).
    Returns the validated policy after the write.

    JAG-491: `patch` carries any other policy keys (the summarizer caps + its
    instruction, edited from the structured form). Every prior overlay key is
    kept, so saving from one panel never drops what the other one saved.
    """
    cur = _read()
    trig = float(cur["trigger_pct"] if trigger_pct is None else trigger_pct)
    targ = float(cur["target_pct"] if target_pct is None else target_pct)
    keep = int(cur["keep_recent"] if keep_recent is None else keep_recent)
    if not (0 < trig <= 100):
        raise ValueError("trigger_pct must be > 0 and <= 100")
    if not (0 <= targ < trig):
        raise ValueError("target_pct must be >= 0 and below trigger_pct")
    if not (1 <= keep <= 50):
        raise ValueError("keep_recent must be between 1 and 50")
    merged = dict(_read_file(_LOCAL_PATH))
    merged.update({"trigger_pct": trig, "target_pct": targ, "keep_recent": keep})
    for key, val in (patch or {}).items():
        if isinstance(val, dict) and isinstance(merged.get(key), dict):
            merged[key] = {**merged[key], **val}
        else:
            merged[key] = val
    summ = merged.get("summarizer")
    if isinstance(summ, dict):
        for k, lo, hi in (("input_max_chars", 1000, 1000000),
                          ("output_max_chars", 200, 100000),
                          ("max_parts", 1, 64)):
            if k in summ:
                try:
                    n = int(summ[k])
                except (TypeError, ValueError):
                    raise ValueError("summarizer.%s must be an integer" % k)
                if n < lo or n > hi:
                    raise ValueError("summarizer.%s must be between %d and %d"
                                     % (k, lo, hi))
                summ[k] = n
        if "instruction" in summ:
            txt = str(summ["instruction"] or "").strip()
            if not txt:
                raise ValueError("summarizer.instruction must not be empty")
            summ["instruction"] = txt[:200000]
    payload = {"compaction": merged}
    with _LOCK:
        with open(_LOCAL_PATH, "w", encoding="utf-8") as f:
            if yaml is not None:
                yaml.safe_dump(payload, f, sort_keys=False, allow_unicode=True)
            else:  # pragma: no cover — minimal install without PyYAML
                f.write("compaction:\n"
                        "  trigger_pct: %s\n  target_pct: %s\n  keep_recent: %s\n"
                        % (trig, targ, keep))
        _CACHE["mtime"] = None
        _CACHE["data"] = None
    return load(force=True)


if __name__ == "__main__":  # quick smoke test
    import json as _j
    print(_j.dumps(load(force=True), indent=2)[:1500])
