#!/usr/bin/env python3
"""v531 — the cost ledger reads EVERY documented cache counter (JAG-531).

A cache hit priced at the full input rate silently inflates the session total:
DeepSeek's cache-hit rate is ~50x cheaper than a miss, Anthropic bills cache
writes separately, and a provider-reported charge is always exact. This locks
the ledger against all four documented `usage` shapes:

  * OpenAI-compatible  ``prompt_tokens_details.cached_tokens``
  * DeepSeek           ``prompt_cache_hit_tokens`` / ``prompt_cache_miss_tokens``
  * Anthropic          ``cache_read_input_tokens`` / ``cache_creation_input_tokens``
  * llama.cpp          ``timings.cache_n``
  * gateway            ``usage.cost`` / ``usage.cost_details``

Run: python3 tests/acceptance/v531_costs_cache_fields.py
"""
import json
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="sf-v531-")
os.environ["LONGRUN_COSTS_DIR"] = os.path.join(TMP, "costs")
os.environ["LONGRUN_PRICES_FILE"] = os.path.join(TMP, "prices.json")
# USD per 1M: in 1.0, out 8.0, cache read 0.1, cache write 1.25, no per-call fee.
os.environ["LONGRUN_PRICES"] = json.dumps({
    "p/flat": {"in": 1.0, "out": 8.0},
    "p/cache": {"in": 1.0, "out": 8.0, "cache_read": 0.1, "cache_write": 1.25},
    "p/anthropic": {"in": 3.0, "out": 15.0, "cache_read": 0.3, "cache_write": 3.75},
    # DeepSeek publishes peak rates and halves them off-peak (see F2-F6).
    "deepseek:deepseek-flash": {"in": 0.3, "out": 1.2, "cache_read": 0.006},
    "openrouter:deepseek/deepseek-v4.1-flash": {"in": 0.3, "out": 1.2, "cache_read": 0.006},
})
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.model import costs as C  # noqa: E402

results = []


def check(name, cond, extra=""):
    ok = bool(cond)
    results.append(ok)
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(extra)) if extra else ""))


S = "v531"

# --- A: every cache counter maps to `cached` --------------------------------
a1 = C.record(S, "p/cache", {"prompt_tokens": 10000, "completion_tokens": 0,
                             "prompt_tokens_details": {"cached_tokens": 9000}})
check("A1 OpenAI-compatible cached_tokens is priced at the cache-read rate",
      a1 and a1["cached"] == 9000 and a1["usd"] == round(1000 / 1e6 * 1.0 + 9000 / 1e6 * 0.1, 6), a1)

a2 = C.record(S, "p/cache", {"prompt_tokens": 10000, "completion_tokens": 0,
                             "prompt_cache_hit_tokens": 9000,
                             "prompt_cache_miss_tokens": 1000})
check("A2 DeepSeek prompt_cache_hit_tokens is read (the ~50x under-report)",
      a2 and a2["cached"] == 9000 and a2["usd"] == a1["usd"], a2)

a3 = C.record(S, "p/cache", {"prompt_tokens": 10000, "completion_tokens": 0,
                             "prompt_cache_miss_tokens": 2500})
check("A3 DeepSeek miss-only shape derives the hits (prompt - miss)",
      a3 and a3["cached"] == 7500, a3)

a4 = C.record(S, "p/flat", {"prompt_tokens": 1000, "completion_tokens": 0,
                            "timings": {"cache_n": 800}})
check("A4 llama.cpp timings.cache_n is read and falls back to the input rate",
      a4 and a4["cached"] == 800 and a4["usd"] == round(1000 / 1e6 * 1.0, 6), a4)

# --- B: cache WRITES are billed at their own rate ---------------------------
b1 = C.record(S, "p/cache", {"prompt_tokens": 2000, "completion_tokens": 0,
                             "prompt_tokens_details": {"cache_creation_tokens": 500}})
check("B1 cache_creation_tokens is billed at the cache-write rate, not the input rate",
      b1 and b1["cache_write"] == 500 and b1["usd"] == round(1500 / 1e6 * 1.0 + 500 / 1e6 * 1.25, 6), b1)

# --- C: Anthropic reports the cache OUTSIDE input_tokens --------------------
c1 = C.record(S, "p/anthropic", {"input_tokens": 100, "output_tokens": 50,
                                 "cache_read_input_tokens": 4000,
                                 "cache_creation_input_tokens": 1000})
_pt = 100 + 4000 + 1000          # input_tokens EXCLUDES the cache -> must be made inclusive
_c_usd = round((_pt - 4000 - 1000) / 1e6 * 3.0 + 4000 / 1e6 * 0.3
               + 1000 / 1e6 * 3.75 + 50 / 1e6 * 15.0, 6)
check("C1 Anthropic prompt is made INCLUSIVE and both cache sides are billed",
      c1 and c1["prompt"] == _pt and c1["cached"] == 4000
      and c1["cache_write"] == 1000 and c1["completion"] == 50
      and c1["usd"] == _c_usd, (c1, _c_usd))

# --- D: exact provider charge still wins, incl. the cost_details breakdown --
d1 = C.record(S, "p/cache", {"prompt_tokens": 10, "completion_tokens": 5,
                             "cost_details": {"upstream_inference_prompt_cost": 0.001,
                                              "upstream_inference_completions_cost": 0.002}})
check("D1 a cost_details breakdown is summed into an EXACT charge",
      d1 and d1["usd"] == 0.003 and d1["src"] == "provider", d1)

# --- E: the ledger total carries the new counter ---------------------------
e1 = C.summary(S)
check("E1 the session summary exposes cache_write next to cached",
      "cache_write" in e1 and e1["cache_write"] == 1500 and e1["cached"] == 30300,
      {k: e1.get(k) for k in ("cached", "cache_write")})

# --- F: bounds — cache can never exceed the prompt, writes precede reads ----
f1 = C.cost_from_rates({"in": 1.0, "out": 0.0, "cache_read": 0.1,
                        "cache_write": 1.25, "request": None},
                       1000, 0, 5000, 5000)
check("F1 absurd counters are clamped to the prompt (never a negative price)",
      f1 == round(1000 / 1e6 * 1.25, 6), f1)

# --- F2-F6: DeepSeek peak/off-peak is decided by the CALL's UTC timestamp ----
import calendar
peak_ts = calendar.timegm((2026, 10, 26, 2, 0, 0))      # Monday 02:00 UTC
off_ts = calendar.timegm((2026, 10, 26, 12, 0, 0))      # Monday 12:00 UTC
weekend_ts = calendar.timegm((2026, 10, 25, 2, 0, 0))   # Sunday 02:00 UTC
rp = C.rates_for("deepseek:deepseek-flash", peak_ts)
ro = C.rates_for("deepseek:deepseek-flash", off_ts)
rw = C.rates_for("deepseek:deepseek-flash", weekend_ts)
check("F2 a DeepSeek call inside a peak window keeps the table's peak rates",
      rp and (rp["in"], rp["out"], rp["cache_read"]) == (0.3, 1.2, 0.006), rp)
check("F3 the same call off-peak is billed at exactly HALF those rates",
      ro and (ro["in"], ro["out"], ro["cache_read"]) == (0.15, 0.6, 0.003), ro)
check("F4 weekends are always off-peak for DeepSeek",
      rw and (rw["in"], rw["out"]) == (0.15, 0.6), rw)
check("F5 an OpenRouter ref is never halved (its price already mixes peak/off-peak)",
      (C.rates_for("openrouter:deepseek/deepseek-v4.1-flash", off_ts) or {}).get("in") == 0.3,
      C.rates_for("openrouter:deepseek/deepseek-v4.1-flash", off_ts))
check("F6 the peak windows are [01-04) and [06-10) UTC on weekdays only",
      C.deepseek_is_peak(calendar.timegm((2026, 10, 26, 1, 0, 0))) is True
      and C.deepseek_is_peak(calendar.timegm((2026, 10, 26, 4, 0, 0))) is False
      and C.deepseek_is_peak(calendar.timegm((2026, 10, 26, 6, 0, 0))) is True
      and C.deepseek_is_peak(calendar.timegm((2026, 10, 26, 10, 0, 0))) is False
      and C.deepseek_is_peak(calendar.timegm((2026, 10, 25, 2, 0, 0))) is False, "")

# --- G: best-of-N samples keep the provider's own charge -------------------
with open(os.path.join(REPO, "src", "longrun", "agent", "agent.py"), encoding="utf-8") as f:
    AGENT = f.read()
check("G1 an extra best-of-N sample records its OWN usage (never a delta)",
      "_sample = {k: chat_usage[k] for k in _USAGE_KEYS" in AGENT
      and "_usage_delta" not in AGENT, "")
check("G2 the sample carries the provider-charged fields through to the ledger",
      '"cost",' in AGENT and '"cost_details",' in AGENT
      and '"prompt_cache_hit_tokens", "prompt_cache_miss_tokens",' in AGENT, "")
check("G3 the ctx meter reuses the ledger's usage parser (no second copy)",
      "_costs.usage_tokens(chat_usage)" in AGENT
      and 'chat_usage.get("timings")' not in AGENT, "")

# --- H: background LLM calls are priced too (they used to be invisible) -----
with open(os.path.join(REPO, "src", "longrun", "core", "httpapi.py"), encoding="utf-8") as f:
    API = f.read()
check("H1 the compaction calls are billed (summarizer tag)",
      '_record_llm_cost(session, used or model, _u, "summarizer")' in API, "")
check("H2 the auto-title call is billed (title tag)",
      '_record_llm_cost(sid, used_one or ref, _u, "title")' in API, "")

print("---")
ok = sum(results)
print("%d/%d PASS" % (ok, len(results)))
sys.exit(0 if ok == len(results) else 1)
