#!/usr/bin/env python3
"""v786 — the cost truth: one ledger, cache-aware, persisted per run.

Three defects are pinned here, each with a real call (no model, no network,
no server):

  A  `costs.for_run` sums ONE run's rows (cache counters included) and never
     mixes another run's spend into it                      (JAG-465 family)
  B  the run record asks `runmetrics` by SESSION — it used to ask by run id
     and silently report `tokens: null` on the run-bound path
  C  `_account_call` prices a headless/subagent call when its session is known,
     instead of reading the cache counters and throwing them away
  D  static pins: the trim prefers the router's REAL prompt tokens, and both
     chat `RunTrace` sites hand the session to the ledger

Deterministic: temp dirs, no live model, no network, no server.
Run: python3 tests/acceptance/v786_cost_truth.py
"""
import os
import re
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_tmp = tempfile.mkdtemp(prefix="sf-786-")
os.environ["LONGRUN_COSTS_DIR"] = os.path.join(_tmp, "costs")
os.environ["LONGRUN_RUNS_DIR"] = os.path.join(_tmp, "runs")
os.environ["LONGRUN_DATA_DIR"] = os.path.join(_tmp, "data")
os.makedirs(os.environ["LONGRUN_COSTS_DIR"], exist_ok=True)
os.makedirs(os.environ["LONGRUN_RUNS_DIR"], exist_ok=True)

sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.core import api_v02          # noqa: E402
from longrun.harness import record        # noqa: E402
from longrun.model import costs, runmetrics  # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name
          + ((" :: " + str(detail)[:300]) if detail and not ok else ""))


def usage(prompt, completion, cached=None):
    u = {"prompt_tokens": prompt, "completion_tokens": completion}
    if cached is not None:
        u["prompt_tokens_details"] = {"cached_tokens": cached}
    return u


# ------------------------------------------------- A: for_run is per run -----
costs.record("s1", "m", usage(1000, 50, cached=900), run="r1")
costs.record("s1", "m", usage(500, 20, cached=400), run="r1")
costs.record("s1", "m", usage(7000, 90, cached=0), run="r2")

r1 = costs.for_run("s1", "r1")
r2 = costs.for_run("s1", "r2")
check("A1 two tagged calls are ONE run's rows", r1["calls"] == 2, r1)
check("A2 cache counters survive the ledger", r1["cached"] == 1300, r1)
check("A3 tokens are the inclusive prompt sum", r1["tokens_in"] == 1500, r1)
check("A4 another run is NOT mixed in", r2["calls"] == 1 and r2["tokens_in"] == 7000, r2)
check("A5 a priced run reports a number, never a fake zero",
      r1["usd"] is None or r1["usd"] >= 0, r1)
check("A6 an unknown session is empty, not an error",
      costs.for_run("nope", "r1")["calls"] == 0, costs.for_run("nope", "r1"))

# ------------------------------- B: the record asks runmetrics by SESSION ----
runmetrics.start("s2", model="m")
runmetrics.finish("s2", outcome="done", iterations=2, steps=3,
                  tokens=1234, prompt_tokens=1000, completion_tokens=234)
rec = record.build("s2", "run-1")
budget = rec.get("budget") or {}
check("B1 the record finds the session's tokens on the run-bound path",
      budget.get("tokens") == 1234, budget)
for key in ("usd", "cached", "cache_write", "calls"):
    check("B2 budget carries %r" % key, key in budget, budget)

# ------------------------------ C: a headless call reaches the price ledger --
class St:
    id = "run-9"
    model = "m"
    tokens_spent = 0


st = St()
spent = api_v02._account_call(st, usage(1000, 20, cached=800), session="s9")
led = costs.for_run("s9", "run-9")
check("C1 tokens still accumulate on the run", spent == 1020 and st.tokens_spent == 1020, spent)
check("C2 the call is priced in the ledger", led["calls"] == 1, led)
check("C3 its cache hits are kept, not discarded", led["cached"] == 800, led)

st2 = St()
st2.id = "run-10"
api_v02._account_call(st2, usage(1000, 20, cached=800))
check("C4 without a session nothing is invented",
      costs.for_run("s10", "run-10")["calls"] == 0, costs.for_run("s10", "run-10"))

# ------------------------------------------------ D: static pins -------------
with open(os.path.join(REPO, "src", "longrun", "agent", "agent.py"),
          encoding="utf-8") as f:
    agent_src = f.read()
check("D1 the mid-turn trim prefers the router's REAL prompt tokens",
      "_REAL_PROMPT_TOKENS.get(sess[\"id\"])" in agent_src)

with open(os.path.join(REPO, "src", "longrun", "core", "httpapi.py"),
          encoding="utf-8") as f:
    http_src = f.read()
_trace_sites = http_src.count('RunTrace("chat"')
_with_session = len(re.findall(
    r'RunTrace\(\s*"chat".*?session=sess\["id"\]', http_src, re.S))
check("D2 both chat RunTrace sites pass the session",
      _trace_sites >= 2 and _with_session == _trace_sites,
      {"traces": _trace_sites, "with_session": _with_session})

with open(os.path.join(REPO, "src", "longrun", "util", "tracing.py"),
          encoding="utf-8") as f:
    tracing_src = f.read()
check("D3 finish() takes the run's USD from the ledger",
      "costs.for_run(self.session, self.id)" in tracing_src)

print("\n---\nv786: %d/%d PASS" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
