#!/usr/bin/env python3
"""v355 — 6 differentiated themes, the context donut, and the live cost ledger (JAG-355).

Deterministic (no model, no network beyond a refused localhost port + a file:// payload):

  A) the cost ledger prices each LLM call from its REAL usage, accumulates per
     session, never fakes a zero for an unknown price, and parses a models payload;
  B) static guards: the server folds + pushes per-call cost, the /api/costs routes
     exist, the WebUI has a Cost panel + live listener, the context bar is a DONUT,
     and the battery isolates the cost dir.

Run: python3 tests/acceptance/v355_themes_donut_costs.py
"""
import json
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _read(*parts):
    with open(os.path.join(REPO, *parts), encoding="utf-8") as f:
        return f.read()


TMP = tempfile.mkdtemp(prefix="sf-v355-")
os.environ["LONGRUN_COSTS_DIR"] = os.path.join(TMP, "costs")
os.environ["LONGRUN_PRICES_FILE"] = os.path.join(TMP, "prices.json")
os.environ["LONGRUN_PRICES"] = json.dumps({"deepseek/deepseek-chat": [2.0, 8.0]})
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.model import costs as C  # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + detail) if detail else ""))


# --- A: cost ledger ----------------------------------------------------------
check("C1 price lookup: exact ref and its basename",
      C.price_for("deepseek/deepseek-chat") == (2.0, 8.0)
      and C.price_for("deepseek-chat") == (2.0, 8.0), str(C.price_for("deepseek-chat")))
check("C2 an unpriced model has no price", C.price_for("mystery/model") is None)
# JAG-516: the OpenRouter cache only prices the models OpenRouter hosts, so the
# provider-direct DeepSeek models used to record `usd: null` ("unpriced"). The
# repo ships config/prices.yaml with the OFFICIAL rates for them.
check("C2b config/prices.yaml prices the provider-direct DeepSeek models",
      C.price_for("deepseek-reasoner") is not None
      and C.rates_for("deepseek-reasoner")["cache_read"] is not None,
      str(C.rates_for("deepseek-reasoner")))

rec = C.record("s1", "deepseek/deepseek-chat", {"prompt_tokens": 1000, "completion_tokens": 500})
check("C3 one call is priced from its REAL usage ($2/$8 per 1M)", rec and abs(rec["usd"] - 0.006) < 1e-9, str(rec))
check("C4 the record carries the running session total",
      rec and rec.get("calls") == 1 and abs(rec.get("total_usd") - 0.006) < 1e-9, str(rec.get("total_usd")))

rec2 = C.record("s1", "deepseek/deepseek-chat",
                {"prompt_tokens": 2000, "completion_tokens": 0,
                 "prompt_tokens_details": {"cached_tokens": 1500}})
check("C5 cached tokens are captured from prompt_tokens_details",
      rec2 and rec2.get("cached") == 1500, str(rec2))
check("C6 calls accumulate",
      rec2 and rec2.get("calls") == 2 and abs(rec2.get("total_usd") - 0.01) < 1e-9, str(rec2.get("total_usd")))

u = C.record("s1", "mystery/model", {"prompt_tokens": 10, "completion_tokens": 10})
check("C7 an unpriced model yields usd null (NEVER a fake zero)", u and u["usd"] is None, str(u))
check("C8 a usage with no token counts is ignored",
      C.record("s1", "deepseek/deepseek-chat", {}) is None)

s = C.summary("s1")
check("C9 summary totals + recent (newest first)",
      s["calls"] == 3 and s["priced_calls"] == 2 and s["unknown_calls"] == 1
      and s["recent"][0]["model"] == "mystery/model",
      json.dumps({k: s[k] for k in ("calls", "priced_calls", "unknown_calls")}))
check("C10 by_model groups the calls",
      set(s["by_model"]) == {"deepseek/deepseek-chat", "mystery/model"}, str(list(s["by_model"])))

# refresh parser (offline: a file:// payload — no network)
payload = {"data": [
    {"id": "openai/gpt-x", "pricing": {"prompt": "0.000002", "completion": "0.000008"}},
    {"id": "free/model", "pricing": {"prompt": "0", "completion": "0"}},
]}
pf = os.path.join(TMP, "models.json")
with open(pf, "w", encoding="utf-8") as f:
    json.dump(payload, f)
res = C.refresh_openrouter(url="file://" + pf)
check("C11 refresh parses a models payload into USD-per-1M",
      bool(res.get("ok")) and res.get("count") == 2, str(res))
check("C12 the refreshed cache is (re)loaded and priced",
      C.price_for("openai/gpt-x") == (2.0, 8.0), str(C.price_for("openai/gpt-x")))
check("C13 an explicitly-0 model is FREE, not unknown",
      C.price_for("free/model") == (0.0, 0.0), str(C.price_for("free/model")))
bad = C.refresh_openrouter(url="http://127.0.0.1:1/models", timeout=2)
check("C14 a failed refresh returns an error, never raises",
      bad.get("ok") is False and "error" in bad, str(bad))

# --- B: static guards --------------------------------------------------------
SRV = _read("src", "longrun", "core/server.py") + _read("src", "longrun", "agent/agent.py")
API = _read("src", "longrun", "core/api_v02.py")
HTML = _read("webui", "index.html")
BATT = _read("tests", "battery.sh")
COSTS = _read("src", "longrun", "model/costs.py")

check("S1 the server prices each call and pushes `cost.usage`",
      "costs.record(" in SRV and '"cost.usage"' in SRV, "")
check("S2 the /api/costs routes exist (read, refresh, reset)",
      '"/api/costs"' in API and '"/api/costs/refresh"' in API and '"/api/costs/reset"' in API, "")
check("S3 the WebUI has a Cost panel + live listener",
      'data-insp="cost"' in HTML and 'addEventListener("cost.usage"' in HTML
      and "function loadCosts" in HTML, "")
check("S4 the context breakdown is a DONUT now, not the stacked bar",
      "function _ctxDonut" in HTML and ".ctxdonut" in HTML and ".ctxbar" not in HTML, "")
check("S5 the battery isolates the cost dir + the price cache",
      "LONGRUN_COSTS_DIR" in BATT and "LONGRUN_PRICES_FILE" in BATT, "")
check("S6 the price cache path is overridable and the module is stdlib-only",
      "LONGRUN_PRICES_FILE" in COSTS and "urllib.request" in COSTS, "")

print("---")
ok = sum(results)
print("%d/%d PASS" % (ok, len(results)))
sys.exit(0 if ok == len(results) else 1)

