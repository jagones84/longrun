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
import time

from longrun.tools import registry
from longrun.util.dataio import dump_yaml as _yaml_dump, load_yaml

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
    "roles": {"chat": {}, "agent": {}, "subagent": {}, "summarizer": {}, "longrun_agent": {}},
    "default_fallbacks": [],
}

# JAG-509: a role may FOLLOW the model the chat is using right now instead of a
# fixed ref. `roles.<role>.model: "@chat"` stores that intent; the caller that
# knows the session resolves it at call time (`httpapi._summarize_with_llm`). A
# sentinel is never a real model ref, so it is kept OUT of `model_chain()` — the
# failover chain must never try to send "@chat" to a provider.
CHAT_MODEL_REF = "@chat"
_DYNAMIC_REFS = (CHAT_MODEL_REF,)


def is_dynamic_ref(ref):
    """True when `ref` is a call-time sentinel, not a `provider:model` ref."""
    return str(ref or "").strip().lower() in _DYNAMIC_REFS


_lock = threading.RLock()
_cache = None


def _srv():
    from longrun.core import server
    return server


def _yaml_load(text):
    """YAML (or JSON) config text; the shipped defaults on garbage (JAG-483)."""
    return load_yaml(text, default=dict(DEFAULT_CONFIG))


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
    base = None
    if roster:
        if preferred:
            # JAG-462: match the pin CASE-INSENSITIVELY and never return a model the
            # router marked FAILED — `==` missed a pin whose casing differed from the
            # roster alias (silently falling through to the role pattern, i.e. the
            # operator's chosen model got replaced) and also bypassed the JAG-447r guard.
            p = str(preferred).strip().lower()
            for m in roster:
                if m.get("failed"):
                    continue
                if str(m.get("alias") or "").strip().lower() == p:
                    base = m["alias"]
                    break
        if base is None:
            entry = (cfg.get("roles") or {}).get(role) or {}
            chain = [entry.get("pattern")] + list(entry.get("fallbacks") or []) + \
                    list(cfg.get("default_fallbacks") or [])
            chain = [c for c in chain if c]
            base = _match(chain, roster)
    try:
        from longrun.core import matrix as _mtx
        override = _mtx.call_hook("model", "pick_model", role, base, default=base)
        if isinstance(override, str) and override.strip():
            return override.strip()
    except Exception:  # noqa: BLE001
        pass
    return base


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

    JAG-509: a call-time sentinel (``@chat``) is DROPPED — it is not a
    ``provider:model`` ref, so it can never sit in the failover chain.
    """
    cfg = load_config()
    entry = (cfg.get("roles") or {}).get(role) or {}
    chain = [entry.get("model")] + list(entry.get("fallbacks") or []) + \
            list(cfg.get("default_fallbacks") or [])
    out, seen = [], set()
    for ref in chain:
        ref = str(ref or "").strip()
        if ref and ref not in seen and not is_dynamic_ref(ref):
            out.append(ref)
            seen.add(ref)
    return order_candidates(out)


# ---------------------------------------------------------- I-2 quota cooldown --
# A provider that answers 429 has a CLOSED window for a while. The turn already
# fails over (`api_v02` / `stream_with_fallback` walk the chain), but without a
# memory of the 429 the NEXT turn puts the same model first again and pays one
# doomed call + its latency. Process-local on purpose: a restart forgets it,
# which is correct for a transient quota, and nothing is written to disk.
_EXHAUSTED = {}                 # model ref -> monotonic deadline
_EXHAUSTED_LOCK = threading.Lock()
QUOTA_DEFAULT_COOLDOWN = 3600.0  # seconds, when the transport reports no hint


def quota_cooldown_on():
    """Whether I-2 applies (config `quota_cooldown`, default on)."""
    try:
        return bool(load_config().get("quota_cooldown", True))
    except Exception:  # noqa: BLE001 — a config probe must never break routing
        return True


def note_exhausted(model, secs=None):
    """Remember that `model` hit a quota wall for `secs` (default 1h).

    Returns the deadline (monotonic seconds) or None when nothing was recorded.
    A non-positive `secs` CLEARS the note (the operator/`retry_not_before_s=0`
    saying "try it now").
    """
    ref = str(model or "").strip()
    if not ref or not quota_cooldown_on():
        return None
    try:
        wait = float(secs if secs is not None else QUOTA_DEFAULT_COOLDOWN)
    except (TypeError, ValueError):
        wait = QUOTA_DEFAULT_COOLDOWN
    wait = max(0.0, min(wait, 24 * 3600.0))
    if wait <= 0:
        with _EXHAUSTED_LOCK:
            _EXHAUSTED.pop(ref, None)
        return None
    deadline = time.monotonic() + wait
    with _EXHAUSTED_LOCK:
        _EXHAUSTED[ref] = deadline
    return deadline


def is_exhausted(model):
    """True while `model` is inside a recorded quota window (expires in place)."""
    ref = str(model or "").strip()
    if not ref:
        return False
    with _EXHAUSTED_LOCK:
        deadline = _EXHAUSTED.get(ref)
        if deadline is None:
            return False
        if deadline <= time.monotonic():
            _EXHAUSTED.pop(ref, None)
            return False
        return True


def order_candidates(chain):
    """Exhausted models LAST, order otherwise unchanged, never emptied (I-2).

    A single-model chain still returns that model: a closed quota must cost a
    retry, never a dead end.
    """
    items = []
    for m in (chain or []):
        ref = str(m or "").strip()
        if ref and ref not in items:
            items.append(ref)
    if len(items) < 2 or not quota_cooldown_on():
        return items
    fresh = [m for m in items if not is_exhausted(m)]
    tired = [m for m in items if is_exhausted(m)]
    return fresh + tired


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
