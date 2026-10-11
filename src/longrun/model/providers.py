#!/usr/bin/env python3
"""Longrun providers — one catalogue of every LLM the harness can reach (JAG-71).

`config/providers.yaml` declares providers (llama.cpp DGX, llama.cpp Windows,
vLLM, OpenRouter, DeepSeek) and the models each exposes. This module:

  * loads API keys from gitignored .env files (never from the repo),
  * resolves a model reference `<provider>:<model>` (or a bare id, local first)
    to the endpoint + auth headers the request must use,
  * exposes a UI-friendly catalogue (which provider/model is usable right now).

No secret is ever written to the repository: a provider only names its
`api_key_env`, and the value is read from the environment / .env file.
"""

import atexit
import json
import os
import re
import threading
import time

from longrun.util.paths import REPO_ROOT as REPO
CONFIG = os.environ.get("LONGRUN_PROVIDERS") or os.path.join(REPO, "config", "providers.yaml")
# JAG-112: user additions/overrides live in a gitignored overlay (never the repo).
LOCAL_CONFIG = os.environ.get("LONGRUN_PROVIDERS_LOCAL") or \
    os.path.join(REPO, "config", "providers.local.yaml")

DEFAULTS = {"version": "1", "env_files": [".env", "~/.hermes/.env"],
            "providers": [], "default": None}

_cache = {"ts": None, "cfg": None}
_env_loaded = False

# JAG-426-fix: the metadata refreshes below run in background threads and do
# network I/O (`urlopen` -> SSL -> libcrypto). A daemon thread still executing
# inside libcrypto when the interpreter unloads its shared libraries (`_dl_fini`
# in `exit()`) segfaults the whole process. Reproduced: `context_budget()` ->
# `local_contexts()` spawned such a thread and ~80% of short-lived runs (the
# acceptance tests) died with SIGSEGV AFTER printing their results. Fix: keep a
# handle on every such thread and JOIN it from an atexit hook (which runs during
# finalisation, BEFORE the .so files are unloaded), bounded by the fetch timeouts.
_BG_LOCK = threading.Lock()
_BG_THREADS = set()
_BG_JOIN_TIMEOUT = 15.0


def _spawn_bg(target, name="lr-bg"):
    """Start a tracked background thread that is joined at interpreter exit."""
    def _wrap():
        try:
            target()
        finally:
            with _BG_LOCK:
                _BG_THREADS.discard(t)
    t = threading.Thread(target=_wrap, daemon=True, name=name)
    with _BG_LOCK:
        _BG_THREADS.add(t)
    t.start()
    return t


def _join_bg():
    with _BG_LOCK:
        threads = list(_BG_THREADS)
    for t in threads:
        try:
            t.join(timeout=_BG_JOIN_TIMEOUT)
        except Exception:  # noqa: BLE001 — shutdown must never raise
            pass


atexit.register(_join_bg)


def _to_int(x, default=0):
    """Coerce a provider/model field to int, falling back on garbage (JAG-231).

    `context_length` comes from hand-edited YAML or an upstream model list; a
    value like `128k` used to crash the whole catalogue (`int("128k")`).
    """
    try:
        return int(x)
    except (TypeError, ValueError):
        return default


# ------------------------------------------------------------------- env -----

def load_env(reload=False):
    """Populate os.environ from the configured .env files (never overwrite).

    Keys live in a gitignored .env (or ~/.hermes/.env); the repository only ever
    references them by name. Missing files are silently skipped.
    """
    global _env_loaded
    if _env_loaded and not reload:
        return
    cfg = load(reload=True)
    for rel in (cfg.get("env_files") or []):
        path = os.path.expanduser(rel)
        if not os.path.isabs(path):
            path = os.path.join(REPO, path)
        if not os.path.isfile(path):
            continue
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#") or "=" not in line:
                        continue
                    k, v = line.split("=", 1)
                    k, v = k.strip(), v.strip().strip("'\"")
                    if k and k not in os.environ:
                        os.environ[k] = v
        except OSError:
            continue
    _env_loaded = True


# ----------------------------------------------------------------- config -----

_PROVIDER_KINDS = ("llamacpp", "openai", "openrouter", "deepseek", "anthropic", "custom")
_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]*$")
_ENVNAME_RE = re.compile(r"^[A-Z][A-Z0-9_]*$")


def _read_yaml(path):
    """Read a small YAML (or JSON) doc; None when missing/invalid (never fatal)."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            text = f.read()
    except OSError:
        return None
    try:
        import yaml
        data = yaml.safe_load(text)
    except Exception:  # noqa: BLE001 — fall back to JSON
        try:
            data = json.loads(text)
        except Exception:  # noqa: BLE001
            return None
    return data if isinstance(data, dict) else None


def _merge(base, local):
    """Merge the local overlay over the base config (JAG-112).

    Providers match by `id`: local scalars override, model lists are unioned by
    id, and `disabled: true` on a provider or a model is a tombstone (excluded).
    A local `default` wins.
    """
    out = dict(base or {})
    order, by_id = [], {}
    for p in out.get("providers") or []:
        if isinstance(p, dict) and p.get("id"):
            by_id[p["id"]] = dict(p)
            order.append(p["id"])
    for lp in (local or {}).get("providers") or []:
        if not isinstance(lp, dict) or not lp.get("id"):
            continue
        pid = lp["id"]
        if pid not in by_id:
            by_id[pid] = dict(lp)
            order.append(pid)
            continue
        cur = by_id[pid]
        for k, v in lp.items():
            if k != "models":
                cur[k] = v
        if "models" in lp:
            m_by, m_order = {}, []
            for m in cur.get("models") or []:
                spec = m if isinstance(m, dict) else {"id": str(m)}
                m_by[spec.get("id")] = dict(spec)
                m_order.append(spec.get("id"))
            for lm in lp["models"] or []:
                spec = dict(lm) if isinstance(lm, dict) else {"id": str(lm)}
                mid = spec.get("id")
                if mid in m_by:
                    m_by[mid].update(spec)
                else:
                    m_by[mid] = spec
                    m_order.append(mid)
            cur["models"] = [m_by[i] for i in m_order]
    res = dict(out)
    res["providers"] = [by_id[i] for i in order if not by_id[i].get("disabled")]
    if (local or {}).get("default"):
        res["default"] = local["default"]
    return res


def load(reload=False):
    """Cached providers config: base merged with the local overlay (JAG-112)."""
    try:
        mt = os.stat(CONFIG).st_mtime
    except OSError:
        mt = 0
    try:
        lmt = os.stat(LOCAL_CONFIG).st_mtime
    except OSError:
        lmt = 0
    stamp = (mt, lmt)
    if not reload and _cache["ts"] == stamp and _cache["cfg"] is not None:
        return _cache["cfg"]
    base = _read_yaml(CONFIG)
    local = _read_yaml(LOCAL_CONFIG)
    if base is None and local is None:
        cfg = json.loads(os.environ.get("LONGRUN_PROVIDERS_JSON", "{}")) or dict(DEFAULTS)
    else:
        cfg = _merge(base or {}, local or {})
    # normalise
    cfg.setdefault("providers", [])
    for p in cfg["providers"]:
        p.setdefault("kind", "openai")
        p.setdefault("local", False)
        p.setdefault("models", [])
        p["models"] = [m if isinstance(m, dict) else {"id": str(m)}
                       for m in p["models"]
                       if not (isinstance(m, dict) and m.get("disabled"))]
    _cache.update(ts=stamp, cfg=cfg)
    return cfg


# ------------------------------------------------------------ user edits -----

def _local_doc():
    return _read_yaml(LOCAL_CONFIG) or {"providers": []}


def _write_local(doc):
    """Atomic write of the overlay (never the versioned base file)."""
    os.makedirs(os.path.dirname(LOCAL_CONFIG), exist_ok=True)
    tmp = LOCAL_CONFIG + ".tmp"
    try:
        import yaml
        text = yaml.safe_dump(doc, sort_keys=False, allow_unicode=True)
    except Exception:  # noqa: BLE001
        text = json.dumps(doc, indent=2, ensure_ascii=False)
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(text)
    os.replace(tmp, LOCAL_CONFIG)
    return LOCAL_CONFIG


def _local_provider(doc, pid):
    for p in doc.setdefault("providers", []):
        if isinstance(p, dict) and p.get("id") == pid:
            return p
    return None


def _validate_provider(spec):
    # JAG-247: every field is wire data. `id` could be an int (`.strip()` crashed)
    # and take down POST /api/providers with an unhandled AttributeError.
    pid = spec.get("id")
    if not isinstance(pid, str) or not _ID_RE.match(pid.strip()):
        return "invalid id (use [a-z0-9._-])"
    kind = spec.get("kind") or "openai"
    if kind not in _PROVIDER_KINDS:
        return "invalid kind: %s" % kind
    url = spec.get("base_url")
    if url and not str(url).startswith(("http://", "https://")):
        return "base_url must start with http(s)://"
    env = spec.get("api_key_env")
    if env and not _ENVNAME_RE.match(str(env)):
        return "api_key_env must be the NAME of the variable (e.g. OPENROUTER_API_KEY)"
    return None


def upsert_provider(spec):
    """Add or update a provider (only `id` is required). Writes the overlay."""
    spec = dict(spec or {})
    # JAG-250: `models` is wire data. `[dict(m) for m in [1,2]]` raised
    # `TypeError: 'int' object is not iterable` and dropped the connection.
    raw_models = spec.get("models")
    if raw_models:
        if not isinstance(raw_models, list):
            return {"ok": False, "error": "models must be a list"}
        norm = []
        for m in raw_models:
            if isinstance(m, dict):
                norm.append(dict(m))
            elif isinstance(m, (str, int, float)):
                norm.append({"id": str(m)})
            else:
                return {"ok": False, "error": "each model must be an id or an object"}
        spec["models"] = norm
    else:
        spec.pop("models", None)
    err = _validate_provider(spec)
    if err:
        return {"ok": False, "error": err}
    pid = spec["id"].strip()
    spec["id"] = pid
    doc = _local_doc()
    cur = _local_provider(doc, pid)
    if cur is None:
        cur = {"id": pid}
        doc["providers"].append(cur)
    cur.pop("disabled", None)
    for k, v in spec.items():
        if k == "id":
            continue
        cur[k] = [dict(m) for m in v] if k == "models" else v
    _write_local(doc)
    _cache.update(ts=None, cfg=None)
    return {"ok": True, "id": pid, "config": LOCAL_CONFIG}


def remove_provider(pid):
    """Remove a local-only provider, or disable (tombstone) a base one."""
    doc = _local_doc()
    cur = _local_provider(doc, pid)
    in_base = any(isinstance(p, dict) and p.get("id") == pid
                  for p in ((_read_yaml(CONFIG) or {}).get("providers") or []))
    if in_base:
        if cur is None:
            cur = {"id": pid}
            doc["providers"].append(cur)
        cur["disabled"] = True
    elif cur is not None:
        doc["providers"] = [p for p in doc["providers"] if p is not cur]
    _write_local(doc)
    _cache.update(ts=None, cfg=None)
    return {"ok": True, "id": pid, "disabled": in_base}


def add_model(pid, model_id, context_length=None):
    # JAG-247: `model_id` is wire data (an int crashed `.strip()`), and
    # `context_length` may be a non-numeric string (`int()` crashed).
    if not isinstance(model_id, str):
        model_id = "" if model_id is None else str(model_id)
    mid = model_id.strip()
    if not mid:
        return {"ok": False, "error": "model id required"}
    doc = _local_doc()
    cur = _local_provider(doc, pid)
    if cur is None:
        cur = {"id": pid, "models": []}
        doc["providers"].append(cur)
    cur.setdefault("models", [])
    cur["models"] = [m for m in cur["models"]
                     if (m.get("id") if isinstance(m, dict) else m) != mid]
    entry = {"id": mid}
    if context_length:
        try:
            entry["context_length"] = int(context_length)
        except (TypeError, ValueError):
            return {"ok": False, "error": "context_length must be an integer"}
    cur["models"].append(entry)
    _write_local(doc)
    _cache.update(ts=None, cfg=None)
    return {"ok": True, "id": pid, "model": mid}


def remove_model(pid, model_id):
    # JAG-247: coerce the wire value before `.strip()`.
    if not isinstance(model_id, str):
        model_id = "" if model_id is None else str(model_id)
    mid = model_id.strip()
    doc = _local_doc()
    cur = _local_provider(doc, pid)
    base_p = next((p for p in ((_read_yaml(CONFIG) or {}).get("providers") or [])
                   if isinstance(p, dict) and p.get("id") == pid), None)
    in_base = bool(base_p and any((m.get("id") if isinstance(m, dict) else m) == mid
                                  for m in (base_p.get("models") or [])))
    if cur is None:
        cur = {"id": pid, "models": []}
        doc["providers"].append(cur)
    cur.setdefault("models", [])
    cur["models"] = [m for m in cur["models"]
                     if (m.get("id") if isinstance(m, dict) else m) != mid]
    if in_base:
        cur["models"].append({"id": mid, "disabled": True})
    _write_local(doc)
    _cache.update(ts=None, cfg=None)
    return {"ok": True, "id": pid, "model": mid}


def set_default(ref):
    if not isinstance(ref, str):
        ref = "" if ref is None else str(ref)
    ref = ref.strip()
    if not ref:
        return {"ok": False, "error": "ref required"}
    doc = _local_doc()
    doc["default"] = ref
    _write_local(doc)
    _cache.update(ts=None, cfg=None)
    return {"ok": True, "default": ref}


def reload():
    """Drop caches and re-read providers config + .env (hot reload)."""
    load_env(reload=True)
    _cache.update(ts=None, cfg=None)
    return load(reload=True)


def providers():
    return load().get("providers", [])


def get(provider_id):
    for p in providers():
        if p.get("id") == provider_id:
            return p
    return None


def default_ref():
    """The configured default model reference, else a GENERAL available model.

    JAG-422: the user's own choice (persisted by `set_default`) always wins. If no
    default is configured — or its provider is unavailable (no key) — fall back to
    the first AVAILABLE *cloud* provider (a general model), then any available one.
    A local router model is never picked while a cloud key exists.
    """
    load_env()
    d = load().get("default")
    if d:
        hit = resolve(d)
        if hit and available(hit[0]):
            return d
    pool = providers()
    for want_cloud in (True, False):
        for p in pool:
            if not p.get("models") or p.get("embed_only"):
                continue
            if want_cloud and p.get("local"):
                continue
            if available(p):
                return "%s:%s" % (p["id"], p["models"][0]["id"])
    return None


# -------------------------------------------------------------------- auth ----

def api_key(provider):
    """The key for a provider (from env / .env); None for a local server."""
    env = (provider or {}).get("api_key_env")
    if not env:
        return None
    load_env()
    return os.environ.get(env) or None


def available(provider):
    """True when the provider can be called: local, or its key is present."""
    if provider.get("local"):
        return True
    env = provider.get("api_key_env")
    if not env:
        return True
    return bool(api_key(provider))


def headers(provider):
    h = {"Content-Type": "application/json"}
    key = api_key(provider)
    if key:
        h["Authorization"] = "Bearer " + key
    return h


# ---------------------------------------------------------------- resolving ---

def resolve(ref):
    """Resolve `ref` to (provider, model_id). None when nothing matches.

    Grammar: `<provider_id>:<model_id>` when the prefix names a provider (so
    OpenRouter ids that contain ':' — e.g. `deepseek/deepseek-v4.1-flash:batch`
    — are not mis-split); otherwise a bare model id, searched across every
    provider with the local ones first.
    """
    if not ref:
        ref = default_ref()
    if not ref:
        return None
    if ":" in ref:
        pid, mid = ref.split(":", 1)
        p = get(pid)
        if p is not None:
            return p, mid
    ordered = sorted(providers(), key=lambda p: (not p.get("local"), p.get("id") or ""))
    for p in ordered:
        for m in p["models"]:
            if m.get("id") == ref:
                return p, ref
    return None


def endpoint(ref):
    """(url, headers, model_id) for a chat completion on `ref`."""
    hit = resolve(ref)
    if not hit:
        return None
    p, mid = hit
    base = (p.get("base_url") or "").rstrip("/")
    return base + "/chat/completions", headers(p), mid


def ref_of(provider, model_id):
    return "%s:%s" % (provider.get("id"), model_id)


# ------------------------------------------------- remote model metadata ------

_OPENROUTER_CTX = {"ts": None, "map": None, "lock": threading.Lock()}
_CTX_TTL = 6 * 3600


def _fetch_openrouter_contexts():
    """One bounded fetch of OpenRouter's live model list → {id: context_length}."""
    m = {}
    try:
        import urllib.request
        req = urllib.request.Request("https://openrouter.ai/api/v1/models",
                                     headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=6) as resp:
            data = json.loads(resp.read().decode())
        for d in data.get("data", []):
            cid, cl = d.get("id"), d.get("context_length")
            if cid and cl:
                m[cid] = int(cl)
    except Exception:  # noqa: BLE001 — metadata is best-effort, never fatal
        m = _OPENROUTER_CTX["map"] or {}
    _OPENROUTER_CTX.update(ts=time.time(), map=m)
    return m


def openrouter_contexts(block=True):
    """{model_id: context_length} from OpenRouter, cached for 6h.

    Used to report the REAL max context of a remote model (a guess would make the
    "x / max" indicator wrong, which is exactly the bug this fixes).
    """
    m = _OPENROUTER_CTX["map"]
    fresh = m is not None and _OPENROUTER_CTX["ts"] and time.time() - _OPENROUTER_CTX["ts"] < _CTX_TTL
    if fresh:
        return m
    if m is None and block:
        with _OPENROUTER_CTX["lock"]:
            if _OPENROUTER_CTX["map"] is None:
                return _fetch_openrouter_contexts()
    return _OPENROUTER_CTX["map"] or {}


_LOCAL_CTX = {}          # provider_id -> {model_id: real_ctx}
_LOCAL_CTX_TS = {}       # provider_id -> ts of last fetch
_LOCAL_CTX_LOCK = threading.Lock()
_LOCAL_CTX_TTL = 600.0


def _fetch_local_contexts(p):
    """One bounded fetch of a LOCAL llama.cpp provider's live windows.

    A llama.cpp router reports each model's REAL `--ctx-size` (in `status.args`)
    or `meta.n_ctx`. The hand-edited `context_length` in providers.yaml drifts
    (declared 96000 while the server runs 200000, or missing entirely), which made
    auto-compaction use the wrong window. Best-effort: on any failure return {}
    so the caller falls back to the declared value.
    """
    m = {}
    base = (p.get("base_url") or "").rstrip("/")
    if not base:
        return m
    try:
        import urllib.request
        with urllib.request.urlopen(base + "/models", timeout=4) as resp:
            data = json.loads(resp.read().decode() or "{}")
        for d in data.get("data", []):
            mid = d.get("id")
            if not mid:
                continue
            meta = d.get("meta") or {}
            ctx = _to_int(meta.get("n_ctx")) or _to_int(meta.get("n_ctx_train"))
            if not ctx:
                args = (d.get("status") or {}).get("args") or []
                for i, a in enumerate(args):
                    if a == "--ctx-size" and i + 1 < len(args):
                        ctx = _to_int(args[i + 1])
                        break
            if ctx:
                m[mid] = ctx
    except Exception:  # noqa: BLE001 — metadata is best-effort, never fatal
        pass
    return m


def local_contexts(pid, block=False):
    """{model_id: real_ctx} for a local provider, cached for `_LOCAL_CTX_TTL`.

    Non-blocking by default: returns the last good snapshot (or {}) and, when it
    is stale, refreshes it in the background — so no request waits on the network.
    """
    with _LOCAL_CTX_LOCK:
        cur = _LOCAL_CTX.get(pid)
        ts = _LOCAL_CTX_TS.get(pid, 0.0)
    if cur is not None and (time.time() - ts) < _LOCAL_CTX_TTL:
        return cur
    if not block:
        if cur is None or (time.time() - ts) >= _LOCAL_CTX_TTL:
            # JAG-426-fix: tracked spawner (joined at exit) — not a bare daemon.
            _spawn_bg(lambda: local_contexts(pid, block=True), name="lr-ctx")
        return cur or {}
    p = get(pid)
    if not p:
        return cur or {}
    m = _fetch_local_contexts(p)
    with _LOCAL_CTX_LOCK:
        _LOCAL_CTX[pid] = m
        _LOCAL_CTX_TS[pid] = time.time()
    return m


def warm():
    """Warm remote metadata in the background so no request ever waits on it."""
    def _run():
        try:
            with _OPENROUTER_CTX["lock"]:
                if _OPENROUTER_CTX["map"] is None:
                    _fetch_openrouter_contexts()
        except Exception:  # noqa: BLE001
            pass
        # JAG-259: local llama.cpp windows too — the declared value drifts.
        for p in providers():
            if p.get("local"):
                try:
                    local_contexts(p.get("id"), block=True)
                except Exception:  # noqa: BLE001
                    pass
    # JAG-426-fix: tracked spawner (joined at exit) — this thread does HTTPS.
    _spawn_bg(_run, name="lr-warm")


def _local_live_ctx(pid, mid):
    """Real window for `mid` on local provider `pid`, case-insensitively (0 if none)."""
    ctxs = local_contexts(pid)
    live = _to_int(ctxs.get(mid))
    if not live and mid:
        low = mid.lower()
        for k, v in ctxs.items():
            if k.lower() == low:
                live = _to_int(v)
                break
    return live


def context_length(ref):
    """Declared context window for `ref` (0 when unknown).

    Local models declare it in providers.yaml; OpenRouter models fall back to the
    live vendor metadata (never a hardcoded guess).
    """
    hit = resolve(ref)
    if not hit:
        return 0
    p, mid = hit
    declared = 0
    for m in p["models"]:
        if m.get("id") == mid:
            declared = _to_int(m.get("context_length"))
            break
    # JAG-259: for a LOCAL model the server's real window wins over the
    # hand-edited declared value (declared 96000 vs real 200000; a missing value
    # used to fall back to the 32768 default and compact far too early).
    if p.get("local"):
        live = _local_live_ctx(p.get("id"), mid)
        if live:
            return live
    if declared:
        return declared
    if p.get("kind") == "openrouter":
        return _to_int(openrouter_contexts().get(mid))
    return 0


def catalog(loaded_aliases=None):
    """UI-friendly catalogue: providers, their models and what is usable now.

    `loaded_aliases` (optional) is the set of model ids the local router reports
    as loaded, so a mobile picker can show which local model is warm.
    """
    loaded = set(loaded_aliases or [])
    out = []
    for p in providers():
        # JAG-403k: embedding-only endpoints carry no chat models — never list
        # them in the chat catalogue (they would be empty rows / clutter).
        if p.get("embed_only"):
            continue
        avail = available(p)
        models = []
        for m in p["models"]:
            cl = _to_int(m.get("context_length"))
            if p.get("local"):
                # JAG-259: show the server's real window when we have it.
                cl = _local_live_ctx(p.get("id"), m.get("id")) or cl
            elif not cl and p.get("kind") == "openrouter":
                cl = _to_int(openrouter_contexts().get(m.get("id")))
            models.append({
                "id": m.get("id"),
                "ref": ref_of(p, m.get("id")),
                "context_length": cl,
                "loaded": m.get("id") in loaded if p.get("local") else None,
            })
        out.append({
            "id": p.get("id"), "name": p.get("name") or p.get("id"),
            "kind": p.get("kind"), "base_url": p.get("base_url"),
            "local": bool(p.get("local")),
            "available": avail,
            "key_env": p.get("api_key_env"),
            "models": models,
        })
    return {"providers": out, "default": default_ref(),
            "count": sum(len(p["models"]) for p in out)}

