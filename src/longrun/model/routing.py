#!/usr/bin/env python3
"""Longrun multi-model routing — v0.3 role-based model selection + fallback.

The llama.cpp router on :8080 exposes a roster of models (some loaded, some
unloaded). Routing picks the model per *role* (chat, planner, agent, subagent,
summarizer) by matching configured alias patterns against the live roster,
preferring loaded models. There are NO implicit fallbacks: a role resolves to a
single model via its `pattern` unless the user configures explicit `fallbacks`.

Config: `config/routing.yaml` (edited via POST /api/routing):

    roles:
      chat:     {pattern: "nex-n25-mini", fallbacks: []}
      planner:  {pattern: "qwen", fallbacks: []}
      ...
    default_fallbacks: []          # empty by default — never decided for you

Matching is a case-insensitive substring match on the roster alias, in the
order the patterns appear. `pick()` returns None only if the roster itself is
unreachable — callers then keep their current default behaviour.
"""

import os
import re
import threading

from longrun.tools import registry

REPO = registry.REPO
CONFIG_PATH = os.path.join(REPO, "config", "routing.yaml")

DEFAULT_CONFIG = {
    # JAG-403: NO hardcoded fallback chains. Each role picks its model by
    # `pattern` (substring match on the live roster) only. A user who wants a
    # failover chain can add `fallbacks` per role (CLI/UI or config/routing.yaml).
    # JAG-455: there is NO `planner` role. The planner call always runs on the
    # turn's own model (`turn_model`) — a separate planner model silently made a
    # session pinned to a cloud model burn the LOCAL weights.
    # JAG-461: NO hardcoded model aliases/patterns EITHER. A shipped pattern like
    # `glm` made a role silently match a LOCAL GGUF alias and the router autoloaded
    # it. Roles carry NO default here; config/routing.yaml is the single source of
    # truth, and an unconfigured role falls through to `default_model()` (cloud).
    "roles": {"chat": {}, "agent": {}, "subagent": {}, "summarizer": {}},
    "default_fallbacks": [],
}

_lock = threading.RLock()
_cache = None


def _srv():
    from longrun.core import server
    return server


def _yaml_load(text):
    try:
        import yaml
        return yaml.safe_load(text)
    except Exception:
        pass
    # minimal fallback: JSON-lookalike configs also parse
    import json
    try:
        return json.loads(text)
    except Exception:
        return dict(DEFAULT_CONFIG)


def _yaml_dump(data):
    try:
        import yaml
        return yaml.safe_dump(data, sort_keys=False)
    except Exception:
        import json
        return json.dumps(data, indent=2)


def load_config(reload=False):
    global _cache
    with _lock:
        if _cache is not None and not reload:
            return _cache
        if os.path.isfile(CONFIG_PATH):
            with open(CONFIG_PATH, encoding="utf-8") as _f:
                cfg = _yaml_load(_f.read()) or {}
        else:
            cfg = dict(DEFAULT_CONFIG)
            save_config(cfg)
        _cache = cfg
        return cfg


def save_config(cfg):
    global _cache
    with _lock:
        os.makedirs(os.path.dirname(CONFIG_PATH), exist_ok=True)
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            f.write(_yaml_dump(cfg))
        _cache = cfg


def _roster():
    try:
        return _srv().router_models()
    except Exception:
        return []


def _match(patterns, roster, loaded_only=True):
    """First roster alias matching any pattern (substring, case-insensitive).

    JAG-447r: a model the router reports as FAILED is never a candidate — before
    this, a pattern matching a broken model (e.g. the whole `glm` family) made the
    caller select something that could never load and hang until the load timeout
    (the root cause of "subagent timeout").
    """
    for pat in patterns:
        rx = re.compile(re.escape(str(pat)), re.I)
        for m in roster:
            if m.get("failed"):
                continue
            if loaded_only and not m.get("loaded"):
                continue
            if rx.search(m.get("alias") or ""):
                return m["alias"]
    if loaded_only:
        # nothing loaded matched: fall back to any matching (non-failed) alias
        return _match(patterns, roster, loaded_only=False)
    return None


def pick(role, preferred=None):
    """Choose the model alias for a role.

    Order: explicit `preferred` (if present in the roster) → role pattern
    (loaded first) → role fallbacks → default fallbacks → any loaded model.
    With no configured fallbacks this resolves to the role pattern only.
    Returns None if the roster is empty (caller keeps its own default).
    """
    cfg = load_config()
    roster = _roster()
    if not roster:
        return None
    if preferred:
        for m in roster:
            if m.get("alias") == preferred:
                return preferred
    entry = (cfg.get("roles") or {}).get(role) or {}
    chain = [entry.get("pattern")] + list(entry.get("fallbacks") or []) + \
            list(cfg.get("default_fallbacks") or [])
    chain = [c for c in chain if c]
    return _match(chain, roster)


def role_model(role):
    """Explicit model ref configured for a role (e.g. roles.summarizer.model).

    JAG-160: lets the WebUI pin an EXACT model (a local alias OR a
    ``provider:model`` ref) instead of a substring pattern. Returns None when
    unset, so callers keep the pattern/fallback behaviour of ``pick()``.
    """
    entry = (load_config().get("roles") or {}).get(role) or {}
    return entry.get("model") or None


def turn_model(sess=None, model=None):
    """The ONE model a turn runs on — and therefore the model its planner runs on.

    JAG-455: there is deliberately NO separate planner model. The resolution is
    IDENTICAL to the answering call: an explicit request model, else the session's
    pinned model, else the harness default. `roles.planner` is NOT consulted: it
    matched `pattern: qwen`, i.e. the LOCAL weights, so a session pinned to a cloud
    model still ran its planner on the local GPU (and the router's autoload loaded
    it). A harness comparison must test ONE model — never a mix where a stronger or
    cheaper helper model answers part of the turn.

    `sess` may be a session dict OR a session id (str). Never raises; returns None
    only if the default itself cannot be resolved.
    """
    if model:
        return model
    pin = None
    if isinstance(sess, dict):
        pin = sess.get("model")
    elif isinstance(sess, str) and sess:
        try:
            pin = (_srv().load_session(sess) or {}).get("model")
        except Exception:  # noqa: BLE001 — a missing store must not break a turn
            pin = None
    if pin:
        return pin
    try:
        return _srv().default_model()
    except Exception:  # noqa: BLE001
        return None


def model_chain(role):
    """Literal model refs for a role, primary first: [explicit model] + fallbacks.

    JAG-448: unlike ``fallback_chain`` (which matches ALIAS patterns against the
    live LOCAL llama.cpp roster), these are FULL ``provider:model`` refs resolved
    by ``providers.resolve()`` — used by the agent/subagent loop which calls the
    endpoint directly (cloud or local) and needs a real failover for cloud models
    (e.g. the subagent's OpenRouter GLM with a Meta contributor fallback). Every
    entry is a string from config — NOTHING is hardcoded — and returns [] when
    the role has no explicit model/fallbacks, so callers keep ``pick()``.
    """
    cfg = load_config()
    entry = (cfg.get("roles") or {}).get(role) or {}
    chain = [entry.get("model")] + list(entry.get("fallbacks") or []) + \
            list(cfg.get("default_fallbacks") or [])
    out, seen = [], set()
    for ref in chain:
        ref = str(ref or "").strip()
        if ref and ref not in seen:
            out.append(ref)
            seen.add(ref)
    return out


def fallback_chain(role):
    """Full alias candidates for a role, resolved against the roster.

    Used for live-call fallback: when the primary model fails, the caller
    retries down this chain. Empty unless the user configured fallbacks.
    """
    cfg = load_config()
    roster = _roster()
    entry = (cfg.get("roles") or {}).get(role) or {}
    chain = [entry.get("pattern")] + list(entry.get("fallbacks") or []) + \
            list(cfg.get("default_fallbacks") or [])
    chain = [c for c in chain if c]
    out, seen = [], set()
    for pat in chain:
        alias = _match([pat], roster, loaded_only=False)
        if alias and alias not in seen:
            out.append(alias)
            seen.add(alias)
    return out


def status():
    roster = _roster()
    cfg = load_config()
    roles = {}
    for role in (cfg.get("roles") or {}):
        roles[role] = {
            "model": (cfg.get("roles", {}).get(role) or {}).get("model"),
            "selected": pick(role),
            "chain": fallback_chain(role),
        }
    return {"config": cfg, "roster": roster, "roles": roles,
            "config_path": CONFIG_PATH}


def update(body):
    """POST /api/routing — update role patterns/fallbacks, persist to yaml."""
    cfg = load_config()
    roles = body.get("roles") or {}
    for role, entry in roles.items():
        cur = cfg.setdefault("roles", {}).setdefault(role, {})
        if "model" in entry:
            # JAG-160: explicit model ref (local alias or provider:model); an
            # empty value clears the pin and restores pattern-based selection.
            if entry.get("model"):
                cur["model"] = str(entry["model"])
            else:
                cur.pop("model", None)
        if "pattern" in entry:
            cur["pattern"] = str(entry["pattern"])
        if "fallbacks" in entry:
            cur["fallbacks"] = [str(f) for f in entry["fallbacks"]]
    if "default_fallbacks" in body:
        cfg["default_fallbacks"] = [str(f) for f in body["default_fallbacks"]]
    save_config(cfg)
    return status()
