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
ROUTER_BASE = os.environ.get("LONGRUN_ROUTER", "http://127.0.0.1:8080")
ROUTER_RETRIES = int(os.environ.get("LONGRUN_ROUTER_RETRIES", 5))
ROUTER_BACKOFF = float(os.environ.get("LONGRUN_ROUTER_BACKOFF", 0.75))
ROUTER_BACKOFF_MAX = float(os.environ.get("LONGRUN_ROUTER_BACKOFF_MAX", 8.0))
MODEL_LOAD_TIMEOUT = int(os.environ.get("LONGRUN_MODEL_LOAD_TIMEOUT", 900))
# ROUTER_IDLE_TIMEOUT: max silence tolerated from the router mid-stream (JAG-48).
ROUTER_IDLE_TIMEOUT = float(os.environ.get("LONGRUN_ROUTER_IDLE_TIMEOUT", 120.0))


# ---------------------------------------------------------------- router ----


def router_models():
    """[{alias, status, loaded, n_ctx}] from the llama.cpp router; [] on failure.

    JAG-66: `n_ctx` is the model's REAL context window (from `meta.n_ctx`, or the
    `--ctx-size` in its launch args) — the source of truth for the token budget.
    """
    try:
        with urllib.request.urlopen(ROUTER_BASE + "/v1/models", timeout=6) as r:
            data = json.loads(r.read().decode("utf-8") or "{}")
        out = []
        for m in data.get("data", []):
            st = (m.get("status") or {}).get("value", "unknown")
            meta = m.get("meta") or {}
            n_ctx = meta.get("n_ctx") or meta.get("n_ctx_train") or 0
            if not n_ctx:
                args = (m.get("status") or {}).get("args") or []
                for i, a in enumerate(args):
                    if a == "--ctx-size" and i + 1 < len(args):
                        n_ctx = int(args[i + 1])
                        break
            out.append({"alias": m.get("id"), "status": st, "loaded": st == "loaded",
                        "n_ctx": int(n_ctx or 0)})
        return out
    except Exception:
        return []


CONTEXT_RESERVE = int(os.environ.get("LONGRUN_CONTEXT_RESERVE", "4096"))
# JAG-70: auto-compaction triggers when the REAL prompt reaches this % of the
# budget (the frontier pattern: compact before you hit the wall, not after).
AUTOCOMPACT_PCT = float(os.environ.get("LONGRUN_CONTEXT_AUTOCOMPACT_PCT", "75"))
# JAG-99: after compaction the transcript is shrunk to this % of the budget, so
# the TOTAL prompt lands BELOW the trigger with headroom (no instant re-trigger).
AUTOCOMPACT_TARGET_PCT = float(os.environ.get(
    "LONGRUN_CONTEXT_TARGET_PCT", str(max(10.0, AUTOCOMPACT_PCT - 15.0))))
# JAG-102: the MANUAL "compact now" action must always reduce. It targets this
# fraction of the transcript's CURRENT size — using the full model budget made
# the button a no-op for any session under 100% (so it "did nothing").
COMPACT_FORCE_RATIO = float(os.environ.get("LONGRUN_COMPACT_FORCE_RATIO", "0.5"))
# JAG-110: how many newest turns the MANUAL "compact now" keeps verbatim. The
# automatic path keeps 8; the manual action is a deliberate shrink, so it keeps
# only this few — otherwise a short session (<=8 msgs) compacted nothing and the
# summarizer was never called (no GPU activity, "0 msgs compacted").
COMPACT_MANUAL_KEEP_RECENT = int(os.environ.get("LONGRUN_COMPACT_MANUAL_KEEP_RECENT", "2"))
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
    models = router_models()
    for m in models:
        if m["loaded"]:
            return m["alias"]
    return models[0]["alias"] if models else None


def model_loaded(alias):
    """(loaded_bool, model_dict_or_None) for one alias from the live roster."""
    for m in router_models():
        if m.get("alias") == alias:
            return bool(m.get("loaded")), m
    return False, None


def model_supports_vision(alias):
    """True when `alias` can accept multimodal image content blocks.

    Signal order: an explicit `vision: true` in the provider catalogue, then the
    live llama.cpp roster's `architecture.input_modalities` (the router reports
    the loaded mmproj). Conservative: any doubt returns False, so a text-only
    model never receives image blocks it cannot use.
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
    # Remote providers carry no router roster; only the catalogue flag (checked
    # above) can grant vision there.
    if provider is not None and not provider.get("local"):
        return False
    try:
        with urllib.request.urlopen(ROUTER_BASE + "/v1/models", timeout=6) as r:
            data = json.loads(r.read().decode("utf-8") or "{}")
        for m in data.get("data", []):
            if m.get("id") != mid:
                continue
            arch = (m.get("meta") or {}).get("architecture") or {}
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


def _open_with_retry(req, timeout):
    """urlopen with exponential backoff on 503 (router: model not loaded).

    The llama.cpp router returns 503 while a cold model is still warming up;
    we retry a few times instead of surfacing a hard failure to the client.
    """
    delay = ROUTER_BACKOFF
    for attempt in range(ROUTER_RETRIES + 1):
        try:
            return urllib.request.urlopen(req, timeout=timeout)
        except urllib.error.HTTPError as e:
            if e.code == 503 and attempt < ROUTER_RETRIES:
                publish("model.retry", attempt=attempt + 1, delay=delay,
                        status=503, reason="model not loaded")
                time.sleep(delay)
                delay = min(delay * 2, ROUTER_BACKOFF_MAX)
                continue
            raise


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
                   cancel=None, no_reasoning=False):
    """POST /chat/completions with stream=true; feed deltas to on_delta.

    on_delta(channel, text) with channel in {think, answer}. Returns the
    full (answer, think) pair. Falls back to a non-streaming call.

    JAG-86: when `usage` (a dict) is passed we ask the OpenAI-compatible server
    for its real token accounting (`stream_options.include_usage`) and copy the
    final `usage` object into it — so the ctx meter can show the model's own
    prompt_tokens instead of the ~4-chars/token proxy.

    JAG-403: `no_reasoning=True` omits `reasoning_effort` from the body (retry
    path when a non-thinking model rejects the field).
    """
    url, headers, model_id = _chat_endpoint(model)
    # JAG-217: fail fast on an UNREACHABLE provider, BEFORE the blocking open, so
    # neither the streaming attempt nor the non-streaming fallback (inside the
    # `except` below) can hang on a blackholed host; the caller moves on at once.
    if not _reachable(url):
        raise urllib.error.URLError("provider unreachable: %s" % url)
    body = json.dumps(_completion_body(model_id, messages, True,
                                       MAX_TOKENS or None,
                                       no_reasoning=no_reasoning)).encode("utf-8")
    req = urllib.request.Request(url, data=body, headers=headers)
    answer, think = [], []
    rg = _RepetitionGuard() if (guard if guard is not None else REPEAT_GUARD) else None
    try:
        with _open_with_retry(req, timeout) as resp:
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
    except Exception:
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
        with _open_with_retry(req, timeout) as resp:
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

