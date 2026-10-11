#!/usr/bin/env python3
"""Live cost ledger for model calls (JAG-355, tightened in JAG-361).

The harness captures the provider's REAL `usage` on every LLM call. This module
prices each call and keeps a per-session ledger, so the UI can show the session
total AND the cost of every single API call while you work.

How the cost is computed — EXACT first, estimate second:

  1. EXACT — when the provider reports the charge itself, use it verbatim. Some
     gateways do (OpenRouter puts the billed USD in `usage.cost`, plus a
     `usage.cost_details` breakdown; the same number is re-fetchable from
     ``GET /api/v1/generation?id=<generation_id>``). No estimation is involved.
  2. ESTIMATE — otherwise price the REAL token counts against the rate table
     (USD per 1M tokens). The table may carry the prompt, the completion, the
     cache-read/cache-write rates and a fixed per-request fee, so a cache hit is
     billed at the cache rate instead of the full input rate.

Records carry ``src``: ``"provider"`` (exact) / ``"estimate"`` / ``None`` (no
known price -> ``usd: null``, NEVER a fake zero; a model priced explicitly 0 is
genuinely free).

Prices are resolved, in order, from:
  1. the `LONGRUN_PRICES` env var (JSON: ``{"model": [in, out]}``),
  2. ``config/prices.yaml`` (or ``config/prices.json``),
  3. ``data/prices.json`` — the cache written by :func:`refresh_openrouter`, which
     pulls OpenRouter's PUBLIC models endpoint (no API key required).

Ledger: ``data/costs/<session>.json`` (override dir with LONGRUN_COSTS_DIR).
Stdlib only.
"""
import json
import os
import threading
import time

from longrun.util.paths import REPO_ROOT as REPO, DATA_DIR

COSTS_DIR = os.environ.get("LONGRUN_COSTS_DIR", os.path.join(DATA_DIR, "costs"))
_PRICES_YAML = os.path.join(REPO, "config", "prices.yaml")
_PRICES_JSON = os.path.join(REPO, "config", "prices.json")
_CACHE_JSON = os.environ.get("LONGRUN_PRICES_FILE", os.path.join(DATA_DIR, "prices.json"))
OPENROUTER_MODELS = "https://openrouter.ai/api/v1/models"
MAX_CALLS = 2000
# JAG-415: keep at most one month of the per-session ledger (space bound). Older
# calls are dropped on read, so the file shrinks the next time a call is recorded.
RETENTION_DAYS = 30

_lock = threading.RLock()
_prices = None


def _read_doc(path):
    """Read a small YAML/JSON doc into a dict, or None. Never fatal."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            text = f.read()
    except OSError:
        return None
    try:
        import yaml
        d = yaml.safe_load(text)
    except Exception:  # noqa: BLE001 — fall back to JSON
        try:
            d = json.loads(text)
        except Exception:  # noqa: BLE001
            return None
    return d if isinstance(d, dict) else None


def _f(v):
    """float(v) or None — a price field may be a string, a number or absent."""
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _f_or_zero(v):
    x = _f(v)
    return 0.0 if x is None else x


def _pair(v):
    """Normalise one price entry to (input_per_1m, output_per_1m) floats."""
    r = _rates(v)
    if r is None or r["in"] is None or r["out"] is None:
        return None
    return (r["in"], r["out"])


def _rates(v):
    """Full rate set (USD per 1M tokens) for one price entry, or None.

    Accepts the compact ``[in, out]`` form or the rich form
    ``{"in","out","cache_read","cache_write","request"}`` (``request`` is the
    fixed USD cost of one API call, not a per-token rate). Unknown fields are
    None so the caller can fall back sensibly.
    """
    if v is None:
        return None
    if isinstance(v, (list, tuple)) and len(v) >= 2:
        return {"in": _f(v[0]), "out": _f(v[1]), "cache_read": None,
                "cache_write": None, "request": None}
    if isinstance(v, dict):
        r = {
            "in": _f(v.get("in", v.get("input", v.get("prompt")))),
            "out": _f(v.get("out", v.get("output", v.get("completion")))),
            "cache_read": _f(v.get("cache_read", v.get("input_cache_read"))),
            "cache_write": _f(v.get("cache_write", v.get("input_cache_write"))),
            "request": _f(v.get("request")),
        }
        return r if (r["in"] is not None or r["out"] is not None) else None
    return None


def _prices_table():
    global _prices
    with _lock:
        if _prices is not None:
            return _prices
        table = {}
        for p in (_CACHE_JSON, _PRICES_JSON, _PRICES_YAML):
            d = _read_doc(p)
            if d:
                table.update(d)
        env = os.environ.get("LONGRUN_PRICES")
        if env:
            try:
                e = json.loads(env)
                if isinstance(e, dict):
                    table.update(e)
            except ValueError:
                pass
        _prices = table
        return table


def _lookup_raw(table, model):
    """Raw price entry for a model, matched both directions (case-insensitive).

    Both the table key and the query are indexed by their full form AND their
    last ``/``- or ``:``-segment, so ``deepseek/deepseek-chat``,
    ``openrouter:deepseek-chat`` and a bare ``deepseek-chat`` all resolve to the
    same entry.
    """
    if not model:
        return None
    idx = {}
    for k, v in table.items():
        s = str(k)
        for key in (s, s.split("/")[-1], s.split(":")[-1]):
            idx.setdefault(key.lower(), v)
    m = str(model)
    for key in (m, m.split("/")[-1], m.split(":")[-1]):
        v = idx.get(key.lower())
        if v is not None:
            return v
    return None


def _lookup(table, model):
    v = _lookup_raw(table, model)
    return _pair(v) if v is not None else None


def price_for(model):
    """(input, output) USD per 1M tokens, or None when the price is unknown."""
    return _lookup(_prices_table(), model)


def rates_for(model):
    """Full rate set (USD per 1M) for a model, or None when unknown."""
    return _rates(_lookup_raw(_prices_table(), model))


def _int(v):
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def _usage_tokens(usage):
    """(prompt, completion, cached) from a provider `usage` dict."""
    u = usage or {}
    pt = _int(u.get("prompt_tokens"))
    ct = _int(u.get("completion_tokens"))
    det = u.get("prompt_tokens_details") or {}
    cached = _int(det.get("cached_tokens"))
    if cached is None:
        cached = _int((u.get("timings") or {}).get("cache_n"))
    return pt, ct, cached


def provider_cost(usage):
    """The provider's OWN charge for this call, when it reports one (EXACT).

    OpenRouter returns it as ``usage.cost`` (+ ``usage.cost_details``); some
    gateways use ``total_cost``. Returns None when the provider says nothing, so
    the caller can fall back to pricing the token counts itself.
    """
    u = usage or {}
    for k in ("cost", "total_cost"):
        x = _f(u.get(k))
        if x is not None:
            return x
    cd = u.get("cost_details")
    if isinstance(cd, dict):
        for k in ("upstream_inference_cost", "total_cost"):
            x = _f(cd.get(k))
            if x is not None:
                return x
        total, seen = 0.0, False
        for k in ("upstream_inference_prompt_cost",
                  "upstream_inference_completions_cost", "server_tool_cost"):
            x = _f(cd.get(k))
            if x is not None:
                total += x
                seen = True
        if seen:
            return round(total, 6)
    return None


def cost_from_rates(rates, prompt, completion, cached):
    """USD for one call from REAL token counts + a rate set (USD per 1M).

    Cached prompt tokens are billed at the cache-read rate (falling back to the
    normal input rate), the rest at the input rate, the completion at the output
    rate, plus the fixed per-request fee when the provider charges one.
    """
    if rates is None:
        return None
    pin, pout = rates["in"], rates["out"]
    if pin is None and pout is None:
        return None
    pt = int(prompt or 0)
    ct = int(completion or 0)
    cr = max(0, min(int(cached or 0), pt))
    plain = max(0, pt - cr)
    read_rate = rates["cache_read"] if rates["cache_read"] is not None else _f_or_zero(pin)
    usd = (plain / 1e6 * _f_or_zero(pin)) + (cr / 1e6 * read_rate) + (ct / 1e6 * _f_or_zero(pout))
    if rates["request"]:
        usd += _f_or_zero(rates["request"])
    return round(usd, 6)


def _path(session):
    safe = "".join(c if c.isalnum() or c in "._-" else "_"
                   for c in str(session or "unknown"))[:96]
    return os.path.join(COSTS_DIR, safe + ".json")


def _load(session):
    try:
        with open(_path(session), encoding="utf-8") as f:
            d = json.load(f)
    except (OSError, ValueError):
        return []
    if not isinstance(d, list):
        return []
    # JAG-415: bound the ledger to the last month so the file cannot grow forever.
    # A malformed `ts` (truncated/corrupt write) must be DROPPED, never crash the
    # caller — `record()` calls this on every LLM call.
    cutoff = time.time() - RETENTION_DAYS * 86400
    out = []
    for c in d:
        if not isinstance(c, dict):
            continue
        try:
            ts = float(c.get("ts") or 0)
        except (TypeError, ValueError):
            ts = 0.0
        if ts >= cutoff:
            out.append(c)
    return out


def _save(session, led):
    os.makedirs(COSTS_DIR, exist_ok=True)
    p = _path(session)
    tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(led[-MAX_CALLS:], f, ensure_ascii=False)
    os.replace(tmp, p)


def _summarise(led):
    tot = 0.0
    priced = unknown = 0
    tin = tout = tcached = 0
    by_model = {}
    for c in led:
        tin += c.get("prompt") or 0
        tout += c.get("completion") or 0
        tcached += c.get("cached") or 0
        if c.get("usd") is None:
            unknown += 1
        else:
            priced += 1
            tot += float(c["usd"])
        m = c.get("model") or "?"
        b = by_model.setdefault(m, {"calls": 0, "usd": 0.0, "unknown": 0})
        b["calls"] += 1
        if c.get("usd") is None:
            b["unknown"] += 1
        else:
            b["usd"] = round(b["usd"] + float(c["usd"]), 6)
    return {"calls": len(led), "tokens_in": tin, "tokens_out": tout,
            "cached": tcached, "total_usd": round(tot, 6),
            "priced_calls": priced, "unknown_calls": unknown, "by_model": by_model}


def record(session, model, usage, run=None):
    """Price ONE LLM call from its real `usage` and append it to the ledger.

    The provider's OWN charge wins when it reports one (``src: "provider"``,
    exact); otherwise the real token counts are priced against the rate table
    (``src: "estimate"``). An unknown price yields ``usd: null``.

    ``run`` is an optional turn/run id: every LLM call made inside the SAME
    user turn shares it, so the UI can group calls "per run" and collapse them.

    Returns the call record (with the running session total) or None when the
    usage carried no token counts.
    """
    pt, ct, cached = _usage_tokens(usage)
    if not pt and not ct:
        return None
    exact = provider_cost(usage)
    if exact is not None:
        usd, src = round(float(exact), 6), "provider"
    else:
        usd = cost_from_rates(rates_for(model), pt, ct, cached)
        src = "estimate" if usd is not None else None
    rec = {"ts": round(time.time(), 3), "model": str(model or ""),
           "prompt": pt or 0, "completion": ct or 0, "cached": cached or 0,
           "usd": usd, "src": src, "run": (run or None)}
    with _lock:
        led = _load(session)
        led.append(rec)
        _save(session, led)
        s = _summarise(led)
    rec["total_usd"] = s["total_usd"]
    rec["calls"] = s["calls"]
    return rec


def summary(session, tail=60):
    """Session totals + the most recent calls (newest first)."""
    led = _load(session)
    s = _summarise(led)
    s["session"] = session
    s["recent"] = list(reversed(led[-max(1, int(tail or 60)):]))
    s["priced"] = bool(_prices_table())
    return s


def reset(session):
    """Drop the ledger for one session (the UI 'clear' action)."""
    with _lock:
        try:
            os.remove(_path(session))
        except OSError:
            pass
    return {"ok": True}


def _per_1m(x):
    v = _f(x)
    return None if v is None else round(v * 1e6, 6)


def refresh_openrouter(url=None, timeout=12):
    """Fetch OpenRouter's PUBLIC model list and cache prices.

    No API key needed. Writes ``data/prices.json`` as
    ``{"model_id": {"in","out","cache_read","cache_write","request"}}`` (USD per
    1M tokens; ``request`` is the fixed USD cost per API call). Returns
    ``{"ok", "count", "error"}``. Never raises.
    """
    global _prices
    import urllib.request
    if url is None:
        url = os.environ.get("LONGRUN_PRICES_URL") or OPENROUTER_MODELS
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "longrun/costs"})
        with urllib.request.urlopen(req, timeout=timeout) as r:  # noqa: S310 — fixed https URL
            data = json.loads(r.read().decode("utf-8", "replace"))
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": "fetch failed: %s" % e}
    rows = data.get("data") if isinstance(data, dict) else None
    if not isinstance(rows, list):
        return {"ok": False, "error": "unexpected models payload"}

    table = {}
    for m in rows:
        if not isinstance(m, dict):
            continue
        mid = m.get("id")
        pr = m.get("pricing") or {}
        if not mid:
            continue
        i, o = _per_1m(pr.get("prompt")), _per_1m(pr.get("completion"))
        if i is None or o is None:
            continue
        row = {"in": i, "out": o}
        cr = _per_1m(pr.get("input_cache_read"))
        if cr is not None:
            row["cache_read"] = cr
        cw = _per_1m(pr.get("input_cache_write"))
        if cw is not None:
            row["cache_write"] = cw
        rq = _f(pr.get("request"))     # already USD per call, not per token
        if rq is not None:
            row["request"] = rq
        table[str(mid)] = row
    try:
        os.makedirs(os.path.dirname(_CACHE_JSON), exist_ok=True)
        tmp = _CACHE_JSON + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(table, f, ensure_ascii=False, sort_keys=True)
        os.replace(tmp, _CACHE_JSON)
    except OSError as e:
        return {"ok": False, "error": "cache write failed: %s" % e}
    with _lock:
        _prices = None  # force a reload on the next lookup
    return {"ok": True, "count": len(table)}

