#!/usr/bin/env python3
"""v558 — cost ledger records ATTEMPTS, not only successful calls (JAG-560).

Shape borrowed from Maka's `usage_model_call_attempts`: every model attempt is a
row, including failures and calls where the provider reported no counters. The
Cost panel must never turn an outage into "$0.00" or hide a retry.

Locked here:
  * a failed attempt is a row (status/error/latency, usd None, no fake price);
  * a successful call with no usage counters is a row with usage_basis="missing";
  * a caller that passes no usage at all still gets None (no empty-row flood);
  * summary exposes attempts/failed/missing_usage/latency_ms_p50;
  * legacy rows (no status/usage_basis) are treated as completed;
  * the agent loop and the WebUI actually pass/display the new fields.

Deterministic, no model, no network. Run: python3 tests/acceptance/v558_cost_attempts.py
"""
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="sf-v558-")
os.environ["LONGRUN_COSTS_DIR"] = os.path.join(TMP, "costs")
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.model import costs  # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + detail) if detail else ""))


def _read(*parts):
    try:
        with open(os.path.join(REPO, *parts), encoding="utf-8") as f:
            return f.read()
    except OSError:
        return ""


# ---- A: failed attempt is a row, priced as unknown -------------------------
r1 = costs.record("s1", "m-test", {}, status="failed",
                  error="TimeoutError: upstream stalled", latency_ms=1234)
check("A1 a failed attempt returns a row", isinstance(r1, dict))
check("A2 status is failed", (r1 or {}).get("status") == "failed", repr((r1 or {}).get("status")))
check("A3 a failed attempt has no price", (r1 or {}).get("usd") is None, repr((r1 or {}).get("usd")))
check("A4 the error is kept", "TimeoutError" in ((r1 or {}).get("error") or ""), repr((r1 or {}).get("error")))
check("A5 the latency is kept", (r1 or {}).get("latency_ms") == 1234, repr((r1 or {}).get("latency_ms")))
check("A6 a failed attempt reports usage_basis=missing",
      (r1 or {}).get("usage_basis") == "missing", repr((r1 or {}).get("usage_basis")))

# ---- B: a successful call with real counters -------------------------------
r2 = costs.record("s1", "m-test", {
    "prompt_tokens": 100, "completion_tokens": 20,
    "prompt_tokens_details": {"cached_tokens": 40},
}, latency_ms=800)
check("B1 usage_basis=reported", (r2 or {}).get("usage_basis") == "reported",
      repr((r2 or {}).get("usage_basis")))
check("B2 tokens are parsed", (r2 or {}).get("prompt") == 100 and (r2 or {}).get("completion") == 20,
      repr((r2 or {}).get("prompt")))
check("B3 cached tokens are separated", (r2 or {}).get("cached") == 40, repr((r2 or {}).get("cached")))
check("B4 status is completed", (r2 or {}).get("status") == "completed")

# ---- C: no usage at all -> no row (unchanged contract) ---------------------
check("C1 no usage and no failure -> None", costs.record("s1", "m-test", {}) is None)

# ---- D: an opaque usage block is a row with basis=missing ------------------
r4 = costs.record("s1", "m-test", {"opaque": 1}, latency_ms=10)
check("D1 an opaque usage block is recorded", isinstance(r4, dict))
check("D2 it is labelled missing", (r4 or {}).get("usage_basis") == "missing")
check("D3 it is NOT priced at zero", (r4 or {}).get("usd") is None, repr((r4 or {}).get("usd")))

# third completed latency, so the median is unambiguous
r5 = costs.record("s1", "m-test", {"prompt_tokens": 5, "completion_tokens": 1}, latency_ms=30)
check("D4 a cheap completed call is counted", (r5 or {}).get("status") == "completed")

# ---- E: summary -------------------------------------------------------------
s = costs.summary("s1")
check("E1 attempts counts every row", s.get("attempts") == 4, repr(s.get("attempts")))
check("E2 failed counts only failures", s.get("failed") == 1, repr(s.get("failed")))
check("E3 missing_usage counts failed+opaque", s.get("missing_usage") == 2,
      repr(s.get("missing_usage")))
check("E4 p50 latency ignores the failed 1234ms row", s.get("latency_ms_p50") == 30,
      repr(s.get("latency_ms_p50")))
check("E5 by_model carries failed", (s.get("by_model") or {}).get("m-test", {}).get("failed") == 1,
      repr((s.get("by_model") or {}).get("m-test")))

# ---- F: legacy rows are still completed ------------------------------------
import time as _time  # noqa: E402

costs._save("legacy", [{"ts": _time.time(), "model": "old", "prompt": 10, "completion": 2,
                        "cached": 0, "cache_write": 0, "usd": 0.000001,
                        "src": "estimate", "run": None}])
sl = costs.summary("legacy")
check("F1 a legacy row is not failed", sl.get("failed") == 0, repr(sl.get("failed")))
check("F2 a legacy row still counts as an attempt", sl.get("attempts") == 1)
check("F3 a legacy row is not 'missing usage'", sl.get("missing_usage") == 0)

# ---- G: the wiring is real --------------------------------------------------
_agent = _read("src", "longrun", "agent", "agent.py")
check("G1 the chat loop passes status/error into the ledger",
      "status=status, error=error" in _agent)
check("G2 the chat loop measures latency", "latency_ms=latency_ms" in _agent)
check("G3 a model exception records the failed attempt", 'status="failed"' in _agent)

_html = _read("webui", "index.html")
check("G4 the panel renders a failed badge", 'r.status === "failed"' in _html)
check("G5 the panel renders the usage basis", "usage_basis" in _html)
check("G6 the panel shows p50 latency", "latency_ms_p50" in _html)

# ---- H: the API payload carries the new fields ------------------------------
check("H1 summary() exposes latency_ms_p50", "latency_ms_p50" in (s or {}))
check("H2 summary() exposes attempts", "attempts" in (s or {}))

print("\n%d/%d" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
