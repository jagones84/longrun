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

Provider-qualified references (``provider:model``) use an exact provider/model
price key. OpenRouter prices are scoped to OpenRouter; direct-provider prices use
explicit namespaced config or environment entries. Unqualified references retain
legacy basename matching.

Ledger: ``data/costs/<session>.json`` (override dir with LONGRUN_COSTS_DIR).
Stdlib only.
"""
import json
import os
import re
import threading
import time

from longrun.util.dataio import as_int, read_yaml as _read_doc
from longrun.util.fswrite import write_json
from longrun.util.paths import REPO_ROOT as REPO, DATA_DIR

COSTS_DIR = os.environ.get("LONGRUN_COSTS_DIR", os.path.join(DATA_DIR, "costs"))
_PRICES_YAML = os.environ.get("LONGRUN_PRICES_YAML",
                              os.path.join(REPO, "config", "prices.yaml"))
_PRICES_JSON = os.path.join(REPO, "config", "prices.json")
_CACHE_JSON = os.environ.get("LONGRUN_PRICES_FILE", os.path.join(DATA_DIR, "prices.json"))
OPENROUTER_MODELS = "https://openrouter.ai/api/v1/models"
# JAG-527: the OFFICIAL provider-direct price page. The trailing slash matters:
# without it the docs site serves the "Your First API Call" page instead of the
# pricing table (verified over plain urllib, 49 KB vs 26 KB, no "CACHE HIT").
DEEPSEEK_PRICING = "https://api-docs.deepseek.com/quick_start/pricing/"
# These retired V4 identifiers are still accepted and billed at the Flash rate.
# `deepseek-chat` and `deepseek-reasoner` were retired and are not price aliases.
_FLASH_ALIASES = ("deepseek-v4-flash", "deepseek-v4-flash-vision-exp")
MAX_CALLS = 2000
# JAG-415: keep at most one month of the per-session ledger (space bound). Older
# calls are dropped on read, so the file shrinks the next time a call is recorded.
RETENTION_DAYS = 30

_lock = threading.RLock()
_prices = None
_prices_idx = None
_scoped_prices_idx = None
_price_stamp = None


def _sources_stamp():
    """mtime+size of the three price sources + LONGRUN_PRICES env (JAG-527: hot reload)."""
    out = [os.environ.get("LONGRUN_PRICES")]
    for p in (_CACHE_JSON, _PRICES_JSON, _PRICES_YAML):
        try:
            st = os.stat(p)
            out.append((st.st_mtime_ns, st.st_size))
        except OSError:
            out.append(None)
    return tuple(out)


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
        # Optional per-provider off-peak multiplier (never part of the shared
        # shape, so existing exact-equality consumers keep working).
        off = _f(v.get("off_peak"))
        if off is not None:
            r["off_peak"] = off
        return r if (r["in"] is not None or r["out"] is not None) else None
    return None


# DeepSeek is the one provider that publishes a TIME-OF-DAY price: peak hours are
# 01:00-04:00 and 06:00-10:00 UTC, Monday-Friday; every other hour is billed at
# exactly HALF the peak rates (official pricing page, read 2026-10-23). Storing
# peak rates and halving at record time keeps one table and prices each call at
# the rate that was actually in force. Chinese public holidays are also off-peak;
# treating them as peak over-reports, never under-reports.
DEEPSEEK_OFF_PEAK_FACTOR = 0.5
DEEPSEEK_PEAK_HOURS_UTC = ((1, 4), (6, 10))   # [start, end) in UTC


def deepseek_is_peak(ts=None):
    """True when DeepSeek bills PEAK rates at epoch `ts` (UTC, Mon-Fri)."""
    t = time.gmtime(float(ts if ts is not None else time.time()))
    if t.tm_wday >= 5:                      # Saturday / Sunday: always off-peak
        return False
    return any(start <= t.tm_hour < end for start, end in DEEPSEEK_PEAK_HOURS_UTC)


def _is_deepseek_direct(model):
    return str(model or "").split(":", 1)[0].strip().lower() == "deepseek"



def _provider_ids() -> set:
    """Return built-in and configured provider IDs used by qualified model refs."""
    ids = {"openrouter", "deepseek", "openai", "anthropic", "google",
           "cohere", "voyage", "jina", "mistral", "vllm", "dgx", "win"}
    try:
        from longrun.model import providers
        ids.update(str(p.get("id", "")).lower() for p in providers.providers()
                   if p.get("id"))
    except Exception:  # noqa: BLE001 — legacy unqualified pricing must still work
        pass
    return ids


def _is_scoped_price_key(key: str, provider_ids: set) -> bool:
    """True when a colon separates a known provider from its model identifier."""
    value = str(key)
    colon = value.find(":")
    slash = value.find("/")
    return colon > 0 and (slash < 0 or colon < slash) \
        and value[:colon].lower() in provider_ids


def _build_price_index(table):
    provider_ids = _provider_ids()
    idx = {}
    for k, v in (table or {}).items():
        s = str(k)
        if _is_scoped_price_key(s, provider_ids):
            continue
        for key in (s, s.split("/")[-1], s.split(":")[-1]):
            idx[key.lower()] = v
    return idx


def _build_scoped_price_index(table, provider_ids=None):
    """Build exact provider/model mappings without alias or basename matching."""
    provider_ids = provider_ids or _provider_ids()
    return {str(k).lower(): v for k, v in (table or {}).items()
            if _is_scoped_price_key(k, provider_ids)}


def _prices_table():
    global _prices, _prices_idx, _scoped_prices_idx, _price_stamp
    with _lock:
        cur = _sources_stamp()
        if _prices is not None and cur == _price_stamp:
            return _prices
        table = {}
        provider_ids = _provider_ids()
        scoped = {}
        cache = _read_doc(_CACHE_JSON) or {}
        if isinstance(cache, dict):
            table.update(cache)
            for model_id, value in cache.items():
                if _is_scoped_price_key(model_id, provider_ids):
                    scoped[model_id] = value
                else:
                    scoped["openrouter:" + str(model_id)] = value
        for p in (_PRICES_JSON, _PRICES_YAML):
            d = _read_doc(p)
            if d:
                table.update(d)
                scoped.update(_build_scoped_price_index(d, provider_ids))
        env = os.environ.get("LONGRUN_PRICES")
        if env:
            try:
                e = json.loads(env)
                if isinstance(e, dict):
                    table.update(e)
                    scoped.update(_build_scoped_price_index(e, provider_ids))
            except ValueError:
                pass
        _prices = table
        _prices_idx = _build_price_index(table)
        _scoped_prices_idx = {str(k).lower(): v for k, v in scoped.items()}
        _price_stamp = cur
        return table


def _lookup_raw(table, model):
    """Look up exact provider-qualified prices before legacy unqualified aliases."""
    if not model:
        return None
    provider_ids = _provider_ids()
    model_ref = str(model)
    if _is_scoped_price_key(model_ref, provider_ids):
        if table is _prices and _scoped_prices_idx is not None:
            scoped = _scoped_prices_idx
        else:
            scoped = _build_scoped_price_index(table, provider_ids)
        return scoped.get(model_ref.lower())
    if table is _prices and _prices_idx is not None:
        idx = _prices_idx
    else:
        idx = _build_price_index(table)
    m = model_ref
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


def rates_for(model, ts=None):
    """Full rate set (USD per 1M) for a model, or None when unknown.

    When `ts` is given, a DIRECT DeepSeek call is priced with the rate that was in
    force at that instant: the table stores PEAK rates, and every off-peak hour
    (outside 01-04 / 06-10 UTC on weekdays, plus the whole weekend) is billed at
    half. OpenRouter refs are never adjusted: its price already reflects the
    upstream peak/off-peak mix.
    """
    r = _rates(_lookup_raw(_prices_table(), model))
    if r is None or ts is None or not _is_deepseek_direct(model):
        return r
    if deepseek_is_peak(ts):
        return r
    out = dict(r)
    factor = r["off_peak"] if r.get("off_peak") is not None else DEEPSEEK_OFF_PEAK_FACTOR
    for key in ("in", "out", "cache_read", "cache_write"):
        if out.get(key) is not None:
            out[key] = round(float(out[key]) * factor, 6)
    return out


def _int(v):
    """int(v) or None — a usage field may be absent or a string (JAG-231)."""
    return as_int(v, default=None)


def usage_tokens(usage):
    """(prompt, completion, cache_read, cache_write) from a provider `usage` dict.

    Every documented provider shape is accepted, because a missed cache counter is
    not cosmetic — it prices cached input at the FULL input rate:
      * OpenAI-compatible  ``prompt_tokens_details.cached_tokens``
      * DeepSeek           ``prompt_cache_hit_tokens`` / ``prompt_cache_miss_tokens``
      * Anthropic          ``cache_read_input_tokens`` / ``cache_creation_input_tokens``
      * llama.cpp          ``timings.cache_n``
    The returned `prompt` is ALWAYS the inclusive total, so callers can subtract the
    cached part without double-counting.
    """
    u = usage or {}
    pt = _int(u.get("prompt_tokens"))
    ct = _int(u.get("completion_tokens"))
    # Anthropic-native usage names them `input_tokens` / `output_tokens`.
    if pt is None:
        pt = _int(u.get("input_tokens"))
    if ct is None:
        ct = _int(u.get("output_tokens"))
    det = u.get("prompt_tokens_details") or {}
    read = _int(det.get("cached_tokens"))
    write = _int(det.get("cache_creation_tokens"))

    # DeepSeek: hit + miss are reported separately and are INCLUDED in prompt_tokens.
    if read is None:
        read = _int(u.get("prompt_cache_hit_tokens"))
    if read is None:
        miss = _int(u.get("prompt_cache_miss_tokens"))
        if miss is not None and pt is not None:
            read = max(0, pt - miss)

    # Anthropic: `input_tokens` EXCLUDES the cache, so make `pt` inclusive here.
    a_read = _int(u.get("cache_read_input_tokens"))
    a_write = _int(u.get("cache_creation_input_tokens"))
    if a_read is not None or a_write is not None:
        base = pt if pt is not None else (_int(u.get("input_tokens")) or 0)
        if a_read is not None:
            read = a_read
        pt = base + (a_read or 0) + (a_write or 0)
        if write is None:
            write = a_write

    if read is None:
        read = _int((u.get("timings") or {}).get("cache_n"))
    return pt, ct, read, write


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


def cost_from_rates(rates, prompt, completion, cached, cached_write=None):
    """USD for one call from REAL token counts + a rate set (USD per 1M).

    Cached prompt READS are billed at the cache-read rate, cache WRITES at the
    cache-write rate (both falling back to the normal input rate when the provider
    does not publish a separate one), the rest at the input rate, the completion at
    the output rate, plus the fixed per-request fee when the provider charges one.
    """
    if rates is None:
        return None
    pin, pout = rates["in"], rates["out"]
    if pin is None and pout is None:
        return None
    pt = int(prompt or 0)
    ct = int(completion or 0)
    cw = max(0, min(int(cached_write or 0), pt))
    cr = max(0, min(int(cached or 0), max(0, pt - cw)))
    plain = max(0, pt - cr - cw)
    read_rate = rates["cache_read"] if rates["cache_read"] is not None else _f_or_zero(pin)
    write_rate = rates["cache_write"] if rates.get("cache_write") is not None else _f_or_zero(pin)
    usd = (plain / 1e6 * _f_or_zero(pin)) + (cr / 1e6 * read_rate) \
        + (cw / 1e6 * write_rate) + (ct / 1e6 * _f_or_zero(pout))
    if rates["request"]:
        usd += _f_or_zero(rates["request"])
    return round(usd, 6)


def _path(session):
    from longrun.util.fswrite import safe_id
    return os.path.join(COSTS_DIR, safe_id(session) + ".json")


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
    write_json(_path(session), led[-MAX_CALLS:], indent=None)


def _summarise(led):
    tot = 0.0
    priced = unknown = provider_calls = estimated_calls = 0
    tin = tout = tcached = tcached_w = 0
    failed = missing_usage = 0
    latencies = []
    by_model = {}
    for c in led:
        tin += c.get("prompt") or 0
        tout += c.get("completion") or 0
        tcached += c.get("cached") or 0
        tcached_w += c.get("cache_write") or 0
        _failed = c.get("status") == "failed"
        if _failed:
            failed += 1
        if c.get("usage_basis") == "missing":
            missing_usage += 1
        if not _failed and isinstance(c.get("latency_ms"), (int, float)) \
                and c["latency_ms"] >= 0:
            latencies.append(int(c["latency_ms"]))
        if c.get("usd") is None:
            unknown += 1
        else:
            priced += 1
            tot += float(c["usd"])
        if c.get("src") == "provider":
            provider_calls += 1
        elif c.get("src") == "estimate":
            estimated_calls += 1
        m = c.get("model") or "?"
        b = by_model.setdefault(m, {"calls": 0, "usd": 0.0, "unknown": 0, "failed": 0})
        b["calls"] += 1
        if _failed:
            b["failed"] += 1
        if c.get("usd") is None:
            b["unknown"] += 1
        else:
            b["usd"] = round(b["usd"] + float(c["usd"]), 6)
    latencies.sort()
    return {"calls": len(led), "attempts": len(led),
            "tokens_in": tin, "tokens_out": tout,
            "cached": tcached, "cache_write": tcached_w, "total_usd": round(tot, 6),
            "priced_calls": priced, "unknown_calls": unknown,
            "provider_calls": provider_calls, "estimated_calls": estimated_calls,
            "failed": failed, "missing_usage": missing_usage,
            "latency_ms_p50": (latencies[len(latencies) // 2] if latencies else None),
            "by_model": by_model}


def record(session, model, usage, run=None, status="completed", error=None,
           latency_ms=None):
    """Price ONE LLM attempt from its real `usage` and append it to the ledger.

    The provider's OWN charge wins when it reports one (``src: "provider"``,
    exact); otherwise the real token counts are priced against the rate table
    (``src: "estimate"``). An unknown price yields ``usd: null``.

    ``run`` is an optional turn/run id: every LLM call made inside the SAME
    user turn shares it, so the UI can group calls "per run" and collapse them.

    Attempt accounting (JAG-560, shape borrowed from Maka's
    ``usage_model_call_attempts``): a call that FAILED, or one that succeeded
    without the provider reporting any counters, is still a row. Hiding it made
    retries and outages invisible in the Cost panel and let a broken provider
    look free. ``usage_basis`` is ``reported`` or ``missing`` — never a proxy
    number; ``latency_ms`` is the wall clock of the attempt.

    Returns the call record (with the running session total), or None when the
    caller gave no usage at all (not even an empty provider block) and the call
    did not fail.
    """
    pt, ct, cached, cache_write = usage_tokens(usage)
    failed = str(status or "completed").strip().lower() != "completed"
    has_tokens = bool(pt or ct or cached or cache_write)
    if not has_tokens and not failed and not (isinstance(usage, dict) and usage):
        return None
    ts = round(time.time(), 3)
    if failed:
        usd, src = None, None
    else:
        exact = provider_cost(usage)
        if exact is not None:
            usd, src = round(float(exact), 6), "provider"
        elif has_tokens:
            usd = cost_from_rates(rates_for(model, ts), pt, ct, cached, cache_write)
            src = "estimate" if usd is not None else None
        else:
            # No counters: pricing 0 tokens would report a fake "$0.00".
            usd, src = None, None
    rec = {"ts": ts, "model": str(model or ""),
           "prompt": pt or 0, "completion": ct or 0, "cached": cached or 0,
           "cache_write": cache_write or 0,
           "usd": usd, "src": src, "run": (run or None),
           "status": "failed" if failed else "completed",
           "usage_basis": "reported" if has_tokens else "missing"}
    if latency_ms is not None:
        try:
            rec["latency_ms"] = max(0, int(latency_ms))
        except (TypeError, ValueError):
            pass
    if failed and error:
        rec["error"] = str(error)[:200]
    if _is_deepseek_direct(model) and not failed:
        # Truthful provenance for the estimate: which half of the day was billed.
        rec["off_peak"] = not deepseek_is_peak(ts)
    with _lock:
        led = _load(session)
        led.append(rec)
        _save(session, led)
        s = _summarise(led)
    rec.update({key: s[key] for key in (
        "total_usd", "calls", "tokens_in", "tokens_out", "priced_calls", "unknown_calls",
        "provider_calls", "estimated_calls", "attempts", "failed", "missing_usage",
        "latency_ms_p50")})
    rec["tokens_cached"] = s["cached"]
    rec["tokens_cache_write"] = s["cache_write"]
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
        write_json(_CACHE_JSON, table, indent=None, sort_keys=True)
    except OSError as e:
        return {"ok": False, "error": "cache write failed: %s" % e}
    with _lock:
        _prices = None  # force a reload on the next lookup
    return {"ok": True, "count": len(table)}


# ------------------------------------------------------- provider-direct table
# JAG-527: the Cost panel can refresh `config/prices.yaml` from DeepSeek's
# OFFICIAL page. The procedure is deterministic ON PURPOSE: it reads the table,
# validates every number (cache hit < cache miss < output) and writes ONLY when
# the whole shape checks out. Any anomaly aborts before the file is touched, so
# a changed/partial page can never install a wrong price.
def _cell_text(cell):
    import html as _html
    txt = re.sub(r"<[^>]+>", " ", cell)
    return re.sub(r"\s+", " ", _html.unescape(txt)).strip()


def _usd(cell):
    m = re.search(r"\$\s*([0-9]+(?:\.[0-9]+)?)", cell or "")
    return float(m.group(1)) if m else None


def _num(v):
    return ("%g" % float(v))


def _write_prices_yaml(table, source, checked_at):
    """Rewrite `config/prices.yaml` atomically from a validated table."""
    lines = [
        "# Longrun price table — generated by the Cost panel's \"refresh prices\" action.",
        "# Source: %s" % source,
        "# Read: %s" % checked_at,
        "# Unit: USD per 1M tokens. PEAK (upper-bound) rates: an off-peak call may be",
        "# over-reported, never under-reported. Hand edits survive until the next refresh.",
        "# Direct rates use exact provider:model keys; see .agent/runbooks/cost-provider-pricing.md.",
        "",
    ]
    for k in sorted(table):
        r = _rates(table[k])
        if not r or r["in"] is None or r["out"] is None:
            continue
        key = '"%s"' % k if _is_scoped_price_key(k, _provider_ids()) else str(k)
        lines.append("%s:" % key)
        lines.append("  in: %s" % _num(r["in"]))
        lines.append("  out: %s" % _num(r["out"]))
        for fld in ("cache_read", "cache_write", "request"):
            if r[fld] is not None:
                lines.append("  %s: %s" % (fld, _num(r[fld])))
        lines.append("")
    from longrun.util.fswrite import write_text
    write_text(_PRICES_YAML, "\n".join(lines).rstrip() + "\n")


def refresh_deepseek_prices(url=None, timeout=15):
    """Refresh `config/prices.yaml` from DeepSeek's official pricing table.

    Returns ``{"ok", "models", "source", "checked_at"}`` or ``{"ok": False,
    "error"}``. Never raises, and never writes when the table does not validate.
    Existing entries the page does not list are PRESERVED (a partial page must
    not delete a price).
    """
    global _prices
    import urllib.request
    if url is None:
        url = os.environ.get("LONGRUN_DEEPSEEK_PRICES_URL") or DEEPSEEK_PRICING
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "longrun/costs"})
        with urllib.request.urlopen(req, timeout=timeout) as r:  # noqa: S310 — fixed https URL
            page = r.read().decode("utf-8", "replace")
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": "fetch failed: %s" % e}
    t = re.search(r"<table[^>]*>(.*?)</table>", page, re.S)
    if not t:
        return {"ok": False, "error": "official pricing table not found"}
    rows = re.findall(r"<tr[^>]*>(.*?)</tr>", t.group(1), re.S)

    def cells(row):
        return [_cell_text(c) for c in
                re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", row, re.S)]

    head = cells(rows[0]) if rows else []
    if not head or head[0].upper() != "MODEL":
        return {"ok": False, "error": "model header row not found"}
    models = []
    for c in head[1:]:
        name = re.sub(r"\(\d+\)", "", c).strip()
        if re.fullmatch(r"[a-z0-9][a-z0-9._-]*", name):
            models.append(name)
    if not models:
        return {"ok": False, "error": "no model columns in the pricing table"}
    peaks = [cells(r)[1:] for r in rows if cells(r) and cells(r)[0].upper() == "PEAK"]
    if len(peaks) != 3:
        return {"ok": False,
                "error": "expected 3 PEAK rows (cache hit, cache miss, output), got %d"
                         % len(peaks)}
    for p in peaks:
        if len(p) != len(models):
            return {"ok": False, "error": "a PEAK row has %d values for %d models"
                                           % (len(p), len(models))}
    parsed = {}
    for i, m in enumerate(models):
        ch, ci, out = _usd(peaks[0][i]), _usd(peaks[1][i]), _usd(peaks[2][i])
        if None in (ch, ci, out) or not (0 <= ch < ci < out):
            return {"ok": False, "error": "nonsensical rates for %s: %r"
                                           % (m, (ch, ci, out))}
        parsed[m] = {"in": ci, "out": out, "cache_read": ch}
        parsed["deepseek:" + m] = dict(parsed[m])
    flash = next((m for m in models if "flash" in m), None)
    if flash:
        for alias in _FLASH_ALIASES:
            parsed[alias] = dict(parsed[flash])
            parsed["deepseek:" + alias] = dict(parsed[flash])
    old = _read_doc(_PRICES_YAML) or {}
    table = dict(old)
    table.update(parsed)
    checked = time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime())
    try:
        _write_prices_yaml(table, url, checked)
    except OSError as e:
        return {"ok": False, "error": "yaml write failed: %s" % e}
    with _lock:
        _prices = None
    return {"ok": True, "models": sorted(models), "source": url, "checked_at": checked}


def refresh_prices():
    """Refresh BOTH sources in one deterministic pass (Cost panel button)."""
    cloud = refresh_openrouter()
    direct = refresh_deepseek_prices()
    return {"ok": bool(cloud.get("ok")) or bool(direct.get("ok")),
            "count": int(cloud.get("count") or 0),
            "openrouter": cloud, "deepseek": direct}
