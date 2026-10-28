"""Router / LLM backend I/O.

Talks to the local llama.cpp router (127.0.0.1:8080) and, via `providers`, to
remote OpenAI-compatible endpoints: the model roster (`router_models`,
`model_context_window`, `default_model`), the warm-up / load path
(`_router_load`, `ensure_model`), the streaming completion with retry + idle
bounds (`_router_stream`, `_open_with_retry`, `_set_read_idle`, `_chat_endpoint`,
`_completion_body`), the repetition guard, the token-budget helpers
(`context_budget`) and the `selfcheck_payload` diagnostic. Extracted from
``server.py`` (JAG-377); the router config constants live here and are re-exported
by the server. Stdlib + sibling modules only (the app-level ``VERSION`` /
``AUTH_TOKEN`` live in ``server`` and are read lazily, to avoid a cycle).
"""
import json
import os
import select
import socket
import time
import urllib.error
import urllib.request

from longrun.model import routing
from longrun.core.events import publish
from longrun.util.textkit import strip_think

# Router endpoint + resilience config (v0.5.1). Moved here from server.py and
# re-exported so `server.ROUTER_BASE` / `server.ROUTER_RETRIES` still resolve.
ROUTER_ENV = "LONGRUN_ROUTER"
ROUTER_BASE = os.environ.get(ROUTER_ENV, "http://127.0.0.1:8080")
ROUTER_RETRIES = int(os.environ.get("LONGRUN_ROUTER_RETRIES", 5))
ROUTER_BACKOFF = float(os.environ.get("LONGRUN_ROUTER_BACKOFF", 0.75))
ROUTER_BACKOFF_MAX = float(os.environ.get("LONGRUN_ROUTER_BACKOFF_MAX", 8.0))
MODEL_LOAD_TIMEOUT = int(os.environ.get("LONGRUN_MODEL_LOAD_TIMEOUT", 900))
# ROUTER_IDLE_TIMEOUT: max silence tolerated from the router mid-stream (JAG-48).
ROUTER_IDLE_TIMEOUT = float(os.environ.get("LONGRUN_ROUTER_IDLE_TIMEOUT", 120.0))


# ---------------------------------------------------------------- router ----


def _parse_roster(data):
    """Normalise a router ``/v1/models`` payload into roster entries.

    JAG-447r: a model the router reports as FAILED (``status.failed`` truthy or a
    non-zero ``status.exit_code``) is flagged ``failed``. Before this the broken
    signal was discarded, so routing happily selected a model that can never load
    and the caller hung until the load timeout (root cause of "subagent timeout").
    """
    out = []
    for m in (data or {}).get("data", []):
        if not isinstance(m, dict):
            continue
        status = m.get("status") or {}
        if not isinstance(status, dict):
            status = {"value": status}
        st = status.get("value", "unknown")
        failed = bool(status.get("failed")) or bool(status.get("exit_code"))
        meta = m.get("meta") or {}
        n_ctx = meta.get("n_ctx") or meta.get("n_ctx_train") or 0
        args = status.get("args") or []
        if not isinstance(args, list):
            args = []
        if not n_ctx:
            for i, a in enumerate(args):
                if a == "--ctx-size" and i + 1 < len(args):
                    try:
                        n_ctx = int(args[i + 1])
                    except (TypeError, ValueError):
                        n_ctx = 0
                    break
        # JAG-465: the router publishes the server's REAL launch args. A `--mmproj`
        # entry is the projector that makes image inputs usable — the honest signal
        # that a configured model CAN see. It is reported separately from the
        # catalogue flag so `model_supports_vision` can trust the live server state.
        mmproj = any(isinstance(a, str) and (a == "--mmproj" or a.startswith("--mmproj="))
                     for a in args)
        out.append({"alias": m.get("id"), "status": st, "loaded": st == "loaded",
                    "failed": failed, "n_ctx": int(n_ctx or 0), "mmproj": mmproj})
    return out


def router_models():
    """[{alias, status, loaded, failed, n_ctx}] from the llama.cpp router; [] on error.

    JAG-66: `n_ctx` is the model's REAL context window (from `meta.n_ctx`, or the
    `--ctx-size` in its launch args) — the source of truth for the token budget.
    JAG-447r: `failed` marks a model the router could not load.
    """
    try:
        with urllib.request.urlopen(ROUTER_BASE + "/v1/models", timeout=6) as r:
            data = json.loads(r.read().decode("utf-8") or "{}")
        return _parse_roster(data)
    except Exception:
        return []


CONTEXT_RESERVE = int(os.environ.get("LONGRUN_CONTEXT_RESERVE", "4096"))
# JAG-431r: the auto-compaction policy now lives in `config/compaction.yaml`,
# not in scattered env vars / module constants. The loader re-reads the file
# on mtime change, so tuning the policy does NOT require a service restart
# (and never has to touch this file).
#
# Existing call sites (httpapi.py, server.py, tests, ...) still reference
# `AUTOCOMPACT_PCT` and `AUTOCOMPACT_TARGET_PCT` as if they were module-level
# constants. We use PEP 562 module-level `__getattr__` to make those names
# always resolve to the FRESH value from the policy file — no call-site edits
# required, no restart required, no stale value shipped.
try:
    from longrun.model import compaction_config as _ccfg
except Exception:  # pragma: no cover — never let config load break imports
    _ccfg = None

# JAG-431r: tests need a way to FORCE a policy value (e.g. set the trigger to
# -1 so every session reads as "over threshold"). `_POLICY_OVERRIDE` is
# checked BEFORE the file, so a test can pin a value without editing the
# file. Production code never touches this; it's only meaningful for tests
# that want deterministic thresholds.
_POLICY_OVERRIDE = {}


def set_policy_override(**kwargs):
    """Pin one or more policy values for the lifetime of the process (tests)."""
    _POLICY_OVERRIDE.update({k: v for k, v in kwargs.items() if v is not None})


def clear_policy_override():
    """Drop all pinned overrides; reload from `config/compaction.yaml`."""
    _POLICY_OVERRIDE.clear()


def _policy():
    base = ({}
            if _ccfg is None
            else _ccfg.load())
    if _POLICY_OVERRIDE:
        merged = dict(base)
        for k, v in _POLICY_OVERRIDE.items():
            if isinstance(v, dict) and isinstance(merged.get(k), dict):
                inner = dict(merged[k])
                inner.update(v)
                merged[k] = inner
            else:
                merged[k] = v
        return merged
    if not base:
        # Last-resort fallback: previous defaults kept here only as a safety net.
        return {"trigger_pct": 70.0, "target_pct": 30.0, "keep_recent": 4,
                "summarizer": {"input_max_chars": 40000,
                               "output_max_chars": 6000,
                               "max_parts": 24,
                               "instruction": "Compress aggressively."}}
    return base


def __getattr__(name):
    # PEP 562: called when `name` is not found as a module-level attribute.
    # Used to expose the LIVE policy values under their legacy constant names.
    if name == "AUTOCOMPACT_PCT":
        return float(_policy()["trigger_pct"])
    if name == "AUTOCOMPACT_TARGET_PCT":
        return float(_policy()["target_pct"])
    if name == "KEEP_RECENT":
        return int(_policy()["keep_recent"])
    if name == "SUMMARIZER_INSTRUCTION":
        return str(_policy().get("summarizer", {}).get("instruction", ""))
    if name == "SUMMARIZER_MAX_CHARS":
        # Legacy alias: the cap on the summary OUTPUT (output_max_chars).
        # Kept for backward compat; new code should use SUMMARIZER_OUTPUT_CHARS.
        return int(_policy().get("summarizer", {}).get("output_max_chars", 6000))
    if name == "SUMMARIZER_INPUT_CHARS":
        return int(_policy().get("summarizer", {}).get("input_max_chars", 40000))
    if name == "SUMMARIZER_OUTPUT_CHARS":
        return int(_policy().get("summarizer", {}).get("output_max_chars", 6000))
    if name == "SUMMARIZER_MAX_PARTS":
        # JAG-533: cap on the map-reduce part-calls one compaction may make.
        return int(_policy().get("summarizer", {}).get("max_parts", 24))
    if name == "COMPACT_OVERFLOW_NOTE":
        # P1 (N9): when compaction/trimming cannot bring the prompt inside the
        # model window, the harness leaves a durable `context_overflow_after_
        # compaction` note in the transcript. Default generous (True): pure
        # observability, the note never blocks a turn.
        return bool(_policy().get("overflow_note", True))
    raise AttributeError("module %r has no attribute %r" % (__name__, name))


def refresh_compaction_policy():
    """Force the loader to re-read `config/compaction.yaml` on the next access.

    Mostly used by tests; production code relies on the mtime-based auto-refresh
    in `compaction_config.load()`.
    """
    if _ccfg is not None:
        _ccfg.reset_cache()
# JAG-102: the MANUAL "compact now" action must always reduce. It targets this
# fraction of the transcript's CURRENT size — using the full model budget made
# the button a no-op for any session under 100% (so it "did nothing").
COMPACT_FORCE_RATIO = float(os.environ.get("LONGRUN_COMPACT_FORCE_RATIO", "0.5"))
# JAG-110/JAG-526: the manual "compact now" action always FORCES a shrink, but
# it keeps the SAME `keep_recent` window the Context panel exposes (KEEP_RECENT).
# It used to keep a hidden 2 messages, which collapsed a 326-message session to 3
# while the panel said keep=8.
# JAG-214: cap the transcript handed to the LLM summarizer. A session can be
# dominated by ONE huge paste; sending it whole to the summarizer would overflow
# the summarizer's own window and fail. Keep the head + tail (the summarizer only
# needs the gist), so the call always fits and the summary is still faithful.
SUMMARIZER_MAX_CHARS = int(os.environ.get("LONGRUN_SUMMARIZER_MAX_CHARS", "60000"))


def model_context_window(alias=None):
    """Real context window (tokens) of `alias`, else the loaded model, else 0."""
    ms = router_models()
    if alias:
        for m in ms:
            if m.get("alias") == alias and m.get("n_ctx"):
                return m["n_ctx"]
    for m in ms:
        if m.get("loaded") and m.get("n_ctx"):
            return m["n_ctx"]
    return 0


def context_budget(alias=None):
    """Token budget for compaction.

    JAG-66: NOT a hardcoded 6000. An explicit `LONGRUN_CONTEXT_BUDGET` still
    wins (for tests), otherwise we use the model's real context window minus a
    reserve for the reply, so the harness actually exploits 131k/256k instead of
    compacting every trivial conversation.
    """
    env = os.environ.get("LONGRUN_CONTEXT_BUDGET")
    if env:
        try:
            return int(env)
        except ValueError:
            pass
    from longrun.model import context_engine
    # JAG-71: a provider model may declare its window (remote models have no
    # router meta); the live router roster is the fallback for local aliases.
    try:
        from longrun.model import providers
        declared = providers.context_length(alias) if alias else 0
        if declared:
            return max(2048, declared - CONTEXT_RESERVE)
    except Exception:  # noqa: BLE001
        pass
    n = model_context_window(alias)
    if n:
        return max(2048, n - CONTEXT_RESERVE)
    return context_engine.DEFAULT_BUDGET



def _local_ref(model):
    """True when `model` must be warmed on the local router (JAG-71).

    Remote providers (OpenRouter, DeepSeek API) have no `/models/load`, so the
    warm-up path is skipped for them; an unknown alias is assumed local, keeping
    the pre-JAG-71 behaviour.
    """
    try:
        from longrun.model import providers
        hit = providers.resolve(model)
        if hit is None:
            return True
        return bool(hit[0].get("local"))
    except Exception:  # noqa: BLE001
        return True


def default_model():
    # JAG-422: the GENERAL default is the configured one (persisted user choice, or
    # the shipped cloud auto-router) — NOT "whatever local model happens to be
    # loaded". Only fall back to the local router roster when no default resolves.
    try:
        from longrun.model import providers
        ref = providers.default_ref()
        if ref:
            return ref
    except Exception:  # noqa: BLE001 — the catalogue must never break the default
        pass
    models = router_models()
    for m in models:  # JAG-447r: never default to a model the router marked FAILED
        if m["loaded"] and not m.get("failed"):
            return m["alias"]
    for m in models:
        if not m.get("failed"):
            return m["alias"]
    return None


def model_loaded(alias):
    """(loaded_bool, model_dict_or_None) for one alias from the live roster."""
    for m in router_models():
        if m.get("alias") == alias:
            return bool(m.get("loaded")), m
    return False, None


def model_supports_vision(alias):
    """True when `alias` can accept multimodal image content blocks.

    Signal order (JAG-465):
      1. an explicit `vision: true` in the provider catalogue — the user's own
         declaration, always honoured;
      2. the LIVE roster of the model's provider: llama.cpp reports the server's
         real launch args, so a `--mmproj` entry proves a projector is loaded and
         image inputs are usable. `architecture.input_modalities` is read as a
         secondary hint: the current router exposes `architecture` at the TOP
         LEVEL of the roster entry (older shapes nest it under `meta`), so both
         are checked.
    Conservative: any doubt returns False, so a text-only model never receives
    image blocks it cannot use.
    """
    if not alias:
        return False
    provider = None
    mid = alias
    try:
        from longrun.model import providers
        hit = providers.resolve(alias)
        if hit is not None:
            provider, mid = hit
            for m in (provider.get("models") or []):
                if m.get("id") == mid and m.get("vision"):
                    return True
    except Exception:  # noqa: BLE001 — capability must never break a turn
        provider = None
    # Remote providers carry no router roster. OpenRouter publishes the real
    # input modalities per model, so a cloud vision model is detected from live
    # vendor metadata; any other remote provider can only be granted vision by
    # its catalogue `vision: true` flag (checked above).
    if provider is not None and not provider.get("local"):
        if provider.get("kind") == "openrouter":
            return providers.openrouter_vision(mid)
        return False
    try:
        if provider is not None and provider.get("base_url"):
            models_url = provider["base_url"].rstrip("/") + "/models"
            request = urllib.request.Request(
                models_url, headers=providers.headers(provider))
        else:
            request = ROUTER_BASE + "/v1/models"
        with urllib.request.urlopen(request, timeout=6) as r:
            data = json.loads(r.read().decode("utf-8") or "{}")
        for m in data.get("data", []):
            # JAG-465: the router reports the id in ITS own casing (e.g.
            # `gemma-4-26B-A4B`) while the catalogue may spell it differently — an
            # exact match silently missed the projector for those models.
            if str(m.get("id") or "").lower() != str(mid or "").lower():
                continue
            status = m.get("status") or {}
            if not isinstance(status, dict):
                status = {"value": status}
            args = status.get("args") or []
            if isinstance(args, list) and any(
                    isinstance(a, str) and (a == "--mmproj" or a.startswith("--mmproj="))
                    for a in args):
                return True          # a projector is loaded on the live server
            # Secondary hint: llama.cpp exposes `architecture` at the TOP LEVEL of
            # the roster entry (not under `meta`), so read both shapes.
            arch = m.get("architecture") or (m.get("meta") or {}).get("architecture") or {}
            return "image" in (arch.get("input_modalities") or [])
    except Exception:  # noqa: BLE001 — fall back to text-only
        pass
    return False


def router_ping(timeout=3):
    """GET the router /health; returns {reachable, latency_ms, status}."""
    t0 = time.time()
    try:
        with urllib.request.urlopen(ROUTER_BASE + "/health", timeout=timeout) as r:
            body = json.loads(r.read().decode("utf-8") or "{}")
        return {"reachable": True,
                "latency_ms": round((time.time() - t0) * 1000, 1),
                "status": body.get("status", "ok")}
    except Exception as e:  # noqa: BLE001
        return {"reachable": False,
                "latency_ms": round((time.time() - t0) * 1000, 1),
                "error": str(e)}


def _router_load(alias, timeout=MODEL_LOAD_TIMEOUT):
    """POST /models/load {"model": alias} on the llama.cpp router."""
    body = json.dumps({"model": alias}).encode("utf-8")
    req = urllib.request.Request(ROUTER_BASE + "/models/load", data=body,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8") or "{}")


def _fire(on_event, kind, **data):
    """Forward a model-lifecycle event to the caller hook, else to the feed."""
    if on_event:
        on_event(kind, **data)
    else:
        publish(kind, **data)


def ensure_model(alias, timeout=None, on_event=None):
    """Load `alias` on the router if it is cold; return an evidence dict.

    Emits a `model.loading` event (SSE + feed) the moment a cold model is
    detected, so a client can render progress before the first token. The
    router has `models_autoload` on, but we drive the explicit load so the
    wait is observable and bounded instead of a silent stall.
    """
    timeout = timeout or MODEL_LOAD_TIMEOUT
    t0 = time.time()
    loaded, m = model_loaded(alias)
    if loaded:
        return {"model": alias, "loaded": True, "action": "already_loaded",
                "seconds": 0.0}
    if m is None:
        return {"model": alias, "loaded": False, "action": "unknown_model",
                "seconds": round(time.time() - t0, 2),
                "error": "alias not present in router roster"}
    # JAG-447r: the router already reported this model as FAILED — polling for a
    # load that cannot happen burned the full MODEL_LOAD_TIMEOUT (900s) and made
    # the caller (e.g. a subagent) time out. Fail fast with the real reason.
    if m.get("failed"):
        _fire(on_event, "model.load_failed", model=alias, seconds=0.0,
              error="model reported FAILED by the router")
        return {"model": alias, "loaded": False, "action": "failed",
                "seconds": round(time.time() - t0, 2),
                "error": "model reported FAILED by the router — refusing to poll"}
    _fire(on_event, "model.loading", model=alias,
          detail="loading cold model before first token")
    err = None
    try:
        _router_load(alias, timeout=timeout)
    except Exception as e:  # noqa: BLE001
        err = str(e)
    # Poll until loaded (the load call may return before the weights are up).
    while time.time() - t0 < timeout:
        if model_loaded(alias)[0]:
            secs = round(time.time() - t0, 2)
            _fire(on_event, "model.ready", model=alias, seconds=secs)
            return {"model": alias, "loaded": True, "action": "loaded",
                    "seconds": secs}
        time.sleep(1.0)
    secs = round(time.time() - t0, 2)
    _fire(on_event, "model.load_failed", model=alias, seconds=secs, error=err)
    return {"model": alias, "loaded": False, "action": "timeout",
            "seconds": secs, "error": err or "timed out waiting for load"}


def measure_llm_latency(alias, timeout=60):
    """Round-trip latency (ms) of a 1-token completion on `alias`; None on error."""
    if not alias:
        return None
    body = json.dumps({"model": alias, "max_tokens": 1, "stream": False,
                       "messages": [{"role": "user", "content": "ping"}]}).encode("utf-8")
    req = urllib.request.Request(ROUTER_BASE + "/v1/chat/completions", data=body,
                                 headers={"Content-Type": "application/json"})
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            r.read()
        return round((time.time() - t0) * 1000, 1)
    except Exception:  # noqa: BLE001
        return None


def selfcheck_payload(host="127.0.0.1", port=8790, llm_probe=True):
    """GET /api/selfcheck — one JSON object proving the chat path is healthy."""
    from longrun.core import server  # lazy: app-level VERSION / AUTH_TOKEN live in server
    t0 = time.time()
    roster = router_models()
    ping = router_ping()
    requested = routing.pick("chat") or default_model()
    loaded_alias = next((m["alias"] for m in roster if m.get("loaded")), None)
    req_loaded = bool(requested and any(
        m["alias"] == requested and m["loaded"] for m in roster))
    llm_ms = measure_llm_latency(loaded_alias or requested) if (llm_probe and ping["reachable"]) else None
    return {
        "service": "longrun", "version": server.VERSION,
        "ts": round(time.time(), 3),
        "status": "ok" if (ping["reachable"] and llm_ms is not None) else "degraded",
        "model_requested": requested,
        "model_loaded": req_loaded,
        "model_loaded_alias": loaded_alias,
        "models": [{"alias": m["alias"], "loaded": m["loaded"]} for m in roster],
        "router": ROUTER_BASE,
        "router_reachable": ping["reachable"],
        "router_latency_ms": ping["latency_ms"],
        "router_status": ping.get("status"),
        "llm_latency_ms": llm_ms,
        "token_configured": bool(server.AUTH_TOKEN),
        "auth_required": bool(server.AUTH_TOKEN),
        "host": host, "port": port,
        "check_seconds": round(time.time() - t0, 2),
    }


def classify_retry(err):
    """Typed retry budget for a model-endpoint failure (M10, Paperclip parity).

    Returns {"disposition", "retries", "backoff"} where disposition is one of
    "transient" (retry with backoff), "quota" (do NOT tight-retry; the caller
    should surface it and back off for `backoff` seconds), "fatal" (config /
    auth / contract \u2014 never retry) or "unknown" (fail fast, as before).

    Paperclip (`recovery/service.ts:716-750`): transient_infra -> 3 attempts,
    default -> 1, non_retryable -> 0, quota -> no tight retry + 1h signal.
    """
    text = str(err or "").lower()
    code = getattr(err, "code", None)
    try:
        code = int(code) if code is not None else None
    except (TypeError, ValueError):
        code = None
    if code is None:
        import re
        m = re.search(r"\b(4\d{2}|5\d{2})\b", text)
        code = int(m.group(1)) if m else None
    if code == 429 or "rate limit" in text or "rate_limit" in text \
            or "quota" in text or "too many requests" in text:
        return {"disposition": "quota", "retries": 0, "backoff": 3600.0}
    if code in (400, 401, 403, 404, 405, 409, 422) or "auth" in text \
            or "unauthorized" in text or "forbidden" in text \
            or "not found" in text or "invalid" in text:
        return {"disposition": "fatal", "retries": 0, "backoff": 0.0}
    if code in (408, 425) or (code is not None and 500 <= code <= 599) \
            or "timeout" in text or "timed out" in text \
            or "connection reset" in text or "connection refused" in text \
            or "connection" in text:
        return {"disposition": "transient", "retries": 3,
                "backoff": ROUTER_BACKOFF}
    if isinstance(err, (TimeoutError, ConnectionError, urllib.error.URLError)):
        return {"disposition": "transient", "retries": 3,
                "backoff": ROUTER_BACKOFF}
    return {"disposition": "unknown", "retries": 0, "backoff": 0.0}


def _open_with_retry(req, timeout, model=None):
    """urlopen with a typed retry budget (M10: `classify_retry`).

    Transient endpoint failures (5xx, timeout, reset) retry up to 3 times
    with exponential backoff; quota (429) publishes `model.quota` and raises
    immediately instead of burning tight retries; fatal/unknown errors fail
    fast, exactly as before.

    I-2: a quota answer is also RECORDED for `model`, so the next turn stops
    putting a model with a closed window at the head of its chain.
    """
    delay = ROUTER_BACKOFF
    try:
        # NOTE: `timeout` MUST be passed by keyword. `urlopen(url, data=None,
        # timeout=...)` binds a second positional argument to `data`, so
        # `urlopen(req, timeout)` overwrites the request body with an int and
        # http.client raises "message_body should be a bytes-like object ...
        # got <class 'int'>".
        return urllib.request.urlopen(req, timeout=timeout)
    except Exception as first:  # noqa: BLE001 — classified below
        budget = classify_retry(first)
        if budget["disposition"] != "transient":
            if budget["disposition"] == "quota":
                try:
                    publish("model.quota", error=str(first)[:200],
                            retry_not_before_s=budget["backoff"])
                except Exception:  # noqa: BLE001 — diagnostics never break I/O
                    pass
                try:
                    from longrun.model import routing as _routing
                    _routing.note_exhausted(model, budget.get("backoff"))
                except Exception:  # noqa: BLE001 — a cooldown note must not mask the error
                    pass
            raise
        last = first
        for attempt in range(1, budget["retries"] + 1):
            publish("model.retry", attempt=attempt, delay=delay,
                    status=getattr(last, "code", None),
                    reason=str(last)[:200], disposition="transient")
            time.sleep(delay)
            delay = min(delay * 2, ROUTER_BACKOFF_MAX)
            try:
                return urllib.request.urlopen(req, timeout=timeout)
            except Exception as e:  # noqa: BLE001
                last = e
                if classify_retry(e)["disposition"] != "transient":
                    raise
        raise last


def _set_read_idle(resp, seconds):
    """Bound the silence of an in-flight router stream (JAG-48).

    A stalled upstream stream used to hold the chat SSE open forever (events
    already emitted, no `done`, socket ESTAB) — the phone app waits for EOF and
    stayed on `busy`. With an idle read timeout the partial answer is kept and
    the normal `done` path is taken instead.
    """
    for getter in (lambda r: r.fp.raw._sock, lambda r: r.fp.raw, lambda r: r.fp):
        try:
            getter(resp).settimeout(seconds)
            return True
        except Exception:  # noqa: BLE001
            continue
    return False


def _chat_endpoint(model):
    """(url, headers, model_id) for a completion, provider-aware (JAG-71).

    A `<provider>:<model>` reference (or a known bare model id) routes to that
    provider's endpoint with its key; anything unknown falls back to the local
    DGX router, so existing configs keep working unchanged.
    """
    try:
        from longrun.model import providers
        resolved = providers.endpoint(model)
        if resolved:
            return resolved
    except Exception:  # noqa: BLE001 — the catalogue must never break chat
        pass
    return (ROUTER_BASE + "/v1/chat/completions",
            {"Content-Type": "application/json"}, model or "default")


# JAG-111: bound a single completion and cut a degenerate repetition loop, so a
# model stuck repeating itself cannot hang a run (ROUTER_IDLE_TIMEOUT only covers
# *silence*, not a continuous token stream).
# JAG-305: the llama.cpp router defaults to a 4096-token completion when the
# request omits `max_tokens`. A reasoning model spends most of that budget on its
# (hidden) thinking, so a long deliverable — a coordinator's synthesis, a big
# schema — was silently TRUNCATED mid-answer (observed on J2: completion_tokens
# pinned at 4096, think_chars 12k, answer cut mid-table). Send a generous, still
# bounded, cap by default so the model can finish; override with the env var
# (0 = omit and let the router decide, the old behaviour).
MAX_TOKENS = int(os.environ.get("LONGRUN_MAX_TOKENS", "16384"))
REPEAT_GUARD = os.environ.get("LONGRUN_REPEAT_GUARD", "1") not in ("0", "false", "False")
_REPEAT_MIN_PERIOD = int(os.environ.get("LONGRUN_REPEAT_MIN_PERIOD", "20"))
_REPEAT_MAX_PERIOD = int(os.environ.get("LONGRUN_REPEAT_MAX_PERIOD", "240"))
_REPEAT_LIMIT = int(os.environ.get("LONGRUN_REPEAT_LIMIT", "4"))


class _RepetitionGuard:
    """Detect a degenerate repetition loop in a streamed reply.

    Streaming chunks are tiny, so we watch the accumulated text: if the last
    `p*limit` characters are exactly `limit` copies of `text[-p:]` for some period
    `p` in [min_period, max_period], the model is looping and the stream must be
    cut. Blocks with too small an alphabet, or (under 48 chars) without a space,
    are ignored so code/tables/numbers never trip the guard.
    """

    def __init__(self, min_period=_REPEAT_MIN_PERIOD, max_period=_REPEAT_MAX_PERIOD,
                 limit=_REPEAT_LIMIT, max_scan=8000):
        self.min_period = max(4, int(min_period))
        self.max_period = max(self.min_period, int(max_period))
        self.limit = max(2, int(limit))
        self.max_scan = max_scan
        self.text = ""

    def feed(self, piece):
        """Append a streamed chunk; return True when a repetition loop is detected."""
        if not piece:
            return False
        self.text = (self.text + piece)[-self.max_scan:]
        t = self.text
        if len(t) < self.min_period * self.limit:
            return False
        maxp = min(self.max_period, len(t) // self.limit)
        for p in range(self.min_period, maxp + 1):
            blk = t[-p:]
            if len(set(blk.strip())) < 4:
                continue
            if " " not in blk and p < 48:
                continue
            if t[-(p * self.limit):] == blk * self.limit:
                return True
        return False


def _reasoning_effort():
    """JAG-281: the OpenAI-compatible `reasoning_effort` to attach, or None.

    OPT-IN via the Thinking-effort setting (data/tools.overlay.yaml): when it is
    disabled or unset this returns None, so the request body stays byte-identical
    to before and plain/local models that reject the field are never affected.
    """
    try:
        from longrun.tools import registry as _reg
        r = _reg.load_config().get("reasoning") or {}
        if r.get("enabled"):
            eff = str(r.get("effort") or "").strip().lower()
            if eff in ("none", "minimal", "low", "medium", "high", "xhigh"):
                return eff
    except Exception:  # noqa: BLE001
        pass
    return None


def _is_reasoning_rejection(err):
    """True when a provider rejected the request BECAUSE OF `reasoning_effort`.

    JAG-422: a non-thinking model may answer 400/404/422 naming the unsupported
    field. Detect that so `_router_stream` can retry once WITHOUT the field.
    """
    code = getattr(err, "code", None)
    if code not in (400, 404, 422):
        return False
    try:
        body = err.read().decode("utf-8", "replace").lower()
    except Exception:  # noqa: BLE001
        body = ""
    if not body:
        body = str(err).lower()
    return "reasoning" in body or "effort" in body


def _completion_body(model_id, messages, stream, max_tokens=None, no_reasoning=False):
    """Single place that builds the OpenAI-compatible request body (JAG-111).
    JAG-403: `no_reasoning=True` omits `reasoning_effort` (retry path for a
    model that rejects the field)."""
    # JAG-167: strip harness-only metadata (e.g. the per-message `node` used to
    # rebuild the in-chat tree) so ONLY wire-valid fields reach the provider.
    clean = []
    for m in messages or []:
        if not isinstance(m, dict):
            continue
        cm = {"role": m.get("role", "user"), "content": m.get("content", "")}
        if m.get("name"):
            cm["name"] = m["name"]
        clean.append(cm)
    body = {"model": model_id, "messages": clean, "stream": bool(stream),
            "temperature": 0.7}
    if stream:
        body["stream_options"] = {"include_usage": True}
    if max_tokens:
        body["max_tokens"] = int(max_tokens)
    if not no_reasoning:
        effort = _reasoning_effort()
        if effort:
            body["reasoning_effort"] = effort
    return body


# JAG-217: a provider whose host is UNREACHABLE must fail fast. A blackholed
# host (e.g. an offline Tailscale peer such as the `win:` provider) made
# urlopen block for the whole OS connect timeout before the fallback chain moved
# on — measured 140s for one chat turn, which looked exactly like a hang. A short
# TCP connect probe turns that into an immediate, clean failure so failover is
# near-instant (the chain's next model answers right away).
CONNECT_TIMEOUT = float(os.environ.get("LONGRUN_CONNECT_TIMEOUT", "3.0"))


def _reachable(url, timeout=None):
    """True if the endpoint's host:port accepts a TCP connection quickly."""
    try:
        from urllib.parse import urlsplit
        u = urlsplit(url)
        host = u.hostname
        if not host:
            return True
        port = u.port or (443 if u.scheme == "https" else 80)
        sock = socket.create_connection((host, port),
                                        timeout=timeout or CONNECT_TIMEOUT)
        sock.close()
        return True
    except OSError:
        return False


def _router_stream(messages, model, on_delta, timeout=300, usage=None, guard=None,
                   cancel=None, no_reasoning=False, max_tokens=None):
    """POST /chat/completions with stream=true; feed deltas to on_delta.

    on_delta(channel, text) with channel in {think, answer}. Returns the
    full (answer, think) pair. Falls back to a non-streaming call.

    JAG-86: when `usage` (a dict) is passed we ask the OpenAI-compatible server
    for its real token accounting (`stream_options.include_usage`) and copy the
    final `usage` object into it — so the ctx meter can show the model's own
    prompt_tokens instead of the ~4-chars/token proxy.

    JAG-403: `no_reasoning=True` omits `reasoning_effort` from the body (retry
    path when a non-thinking model rejects the field).

    JAG-431r: `max_tokens` overrides the global `MAX_TOKENS` for THIS call only,
    so the summarizer can ask the router for a tight token budget (~200) and the
    chat path can keep the wide 16k budget. None falls back to MAX_TOKENS.
    """
    url, headers, model_id = _chat_endpoint(model)
    # JAG-217: fail fast on an UNREACHABLE provider, BEFORE the blocking open, so
    # neither the streaming attempt nor the non-streaming fallback (inside the
    # `except` below) can hang on a blackholed host; the caller moves on at once.
    if not _reachable(url):
        raise urllib.error.URLError("provider unreachable: %s" % url)
    body = json.dumps(_completion_body(model_id, messages, True,
                                       max_tokens or MAX_TOKENS or None,
                                       no_reasoning=no_reasoning)).encode("utf-8")
    req = urllib.request.Request(url, data=body, headers=headers)
    answer, think = [], []
    rg = _RepetitionGuard() if (guard if guard is not None else REPEAT_GUARD) else None
    try:
        with _open_with_retry(req, timeout, model=model) as resp:
            if ROUTER_IDLE_TIMEOUT > 0:
                # v0.6.1 (JAG-48): mid-stream silence must not hang the run.
                _set_read_idle(resp, ROUTER_IDLE_TIMEOUT)
            # JAG-197: poll in short slices so `cancel` (the Stop button) is
            # honoured even while the router is SILENT. Before this, cancel was
            # only checked when a new line arrived, so during a long silent gap
            # (model "thinking", or a busy single-slot router) Stop did nothing
            # until ROUTER_IDLE_TIMEOUT elapsed — the turn hung and starved every
            # later request on a shared router.
            _poll = 0.5 if ROUTER_IDLE_TIMEOUT > 0 else None
            try:
                _sock = resp.fp.raw._sock
            except Exception:  # noqa: BLE001
                _sock = None
            _last = time.time()
            while True:
                if cancel is not None and cancel():
                    # JAG-129D: Stop kills the in-flight generation (closing the
                    # socket at the end of the `with` block interrupts the router-side inference).
                    break
                if _sock is not None:
                    try:
                        _r, _, _ = select.select([_sock], [], [], _poll)
                    except Exception:  # noqa: BLE001
                        _r = [True]
                    if not _r:
                        if ROUTER_IDLE_TIMEOUT > 0 and \
                                (time.time() - _last) >= ROUTER_IDLE_TIMEOUT:
                            raise socket.timeout("router idle")
                        continue
                raw = resp.readline()
                if not raw:
                    break
                _last = time.time()
                line = raw.decode("utf-8", "replace").strip()
                if not line.startswith("data:"):
                    continue
                payload = line[5:].strip()
                if payload == "[DONE]":
                    break
                try:
                    chunk = json.loads(payload)
                except json.JSONDecodeError:
                    continue
                if usage is not None and isinstance(chunk.get("usage"), dict):
                    usage.update(chunk["usage"])
                delta = ((chunk.get("choices") or [{}])[0].get("delta")) or {}
                # JAG-383: the reasoning delta has NO single name across providers —
                # llama.cpp / vLLM (OpenAI-compat) use `reasoning_content`, OpenRouter
                # uses `reasoning` (+ a structured `reasoning_details`). Reading only
                # `reasoning_content` silently DROPPED every OpenRouter model's chain of
                # thought (e.g. deepseek-v4.1-flash), so the live CoT drawer and the
                # persisted `reasoning` stayed empty ("I can't see thoughts").
                rc = delta.get("reasoning_content") or delta.get("reasoning")
                c = delta.get("content")
                piece = (rc or "") + (c or "")
                if rg is not None and piece and rg.feed(piece):
                    publish("model.runaway", model=model_id, chars=len(rg.text))
                    break
                if rc:
                    think.append(rc)
                    on_delta("think", rc)
                if c:
                    txt = c
                    clean, embedded = strip_think(txt)
                    if embedded:
                        think.append(embedded)
                        on_delta("think", embedded)
                    if clean:
                        answer.append(clean)
                        on_delta("answer", clean)
    except Exception as e:  # noqa: BLE001
        # JAG-422: a model that does not support `reasoning_effort` may answer 400.
        # Retry ONCE with the field OMITTED so thinking-effort can never break a turn.
        # This covers the DIRECT _router_stream callers (compaction, planning, lessons)
        # that do NOT pass through stream_with_fallback's own retry loop.
        if not no_reasoning and _reasoning_effort() and _is_reasoning_rejection(e):
            return _router_stream(messages, model, on_delta, timeout, usage, guard,
                                  cancel, no_reasoning=True)
        # JAG-197: an abort must never enter the blocking non-streaming fallback.
        # That fallback re-issues the WHOLE generation, ignores Stop, and can hold
        # the run — and a single-slot router — hostage for the full timeout.
        if cancel is not None and cancel():
            return "".join(answer), "".join(think)
        if answer or think:
            return "".join(answer), "".join(think)
        # non-streaming fallback
        body = json.dumps(_completion_body(model_id, messages, False,
                                           MAX_TOKENS or None,
                                           no_reasoning=no_reasoning)).encode("utf-8")
        req = urllib.request.Request(url, data=body, headers=headers)
        with _open_with_retry(req, timeout, model=model) as resp:
            # The non-streaming fallback: a 429 here is the SAME closed window, so
            # it must be recorded too (I-2 — `_open_with_retry` owns the note).
            data = json.loads(resp.read().decode("utf-8") or "{}")
        if usage is not None and isinstance(data.get("usage"), dict):
            usage.update(data["usage"])
        msg = (data.get("choices") or [{}])[0].get("message") or {}
        rc = msg.get("reasoning_content") or msg.get("reasoning") or ""
        c = msg.get("content") or ""
        if rc:
            # JAG-383: append BEFORE emitting, exactly like the streaming branch — the
            # caller persists the RETURNED think, so emitting without appending streamed
            # the reasoning live but saved `reasoning: null` (thoughts lost on reload).
            think.append(rc)
            on_delta("think", rc)
        clean, embedded = strip_think(c)
        if embedded:
            think.append(embedded)
            on_delta("think", embedded)
        if clean:
            answer.append(clean)
            on_delta("answer", clean)
    return "".join(answer), "".join(think)
