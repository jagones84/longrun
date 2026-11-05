#!/usr/bin/env python3
"""v813 — a benchmark arm must report what the task COST it (B-1).

The Longrun adapter left `HarnessResult.tokens` at the protocol's `0` default
(`benchmarks/protocol.py`), so the polyglot suite and the generic runner printed
the longrun arm as free next to a peer that logs per-step cost — a silent zero,
not a measurement (the class of error in "Silent Instrument Errors", 2026-11-05).
The adapter now fills `tokens`/`cost_usd` from the session ledger inside
`send_task`, while the session still exists.

  A) `send_task` returns the session's real token total and USD;
  B) an empty or broken ledger leaves the numbers at 0 and never fails the task;
  C) the polyglot report has a path that consumes that number.

Deterministic, no live model, no network, no server.
"""
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, REPO)

from benchmarks.longrun_adapter import LongrunAdapter    # noqa: E402
from benchmarks.protocol import AgentRef                  # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""))


def _stub(costs=None, chat=None):
    def _req(method, path, body=None, timeout=None):
        if path.startswith("/api/costs"):
            return 200, (costs if costs is not None else {})
        if path.startswith("/api/chat"):
            return 200, (chat or {"reply": "done", "run_id": "r1"})
        return 200, {}
    return _req


# --------------------------------------------- A. the adapter reads the ledger ---
ad = LongrunAdapter(token="x")            # explicit token -> no token-discovery call
ad._req = _stub(costs={"tokens_in": 900, "tokens_out": 300, "total_usd": 0.5})
res = ad.send_task(AgentRef(id="t", session="S1"), "solve")
check("A1 tokens are the session total", res.tokens == 1200, res.tokens)
check("A2 usd comes from the ledger", abs(res.cost_usd - 0.5) < 1e-9, res.cost_usd)
check("A3 the turn result is still correct",
      res.ok and res.output == "done", (res.ok, res.output))

# --------------------------------------------------- B. missing / broken ledger ---
ad._req = _stub(costs={})
res2 = ad.send_task(AgentRef(id="t", session="S2"), "solve")
check("B1 an empty ledger is 0, not a crash", res2.ok and res2.tokens == 0, res2.tokens)


def _boom(method, path, body=None, timeout=None):
    if path.startswith("/api/costs"):
        raise RuntimeError("ledger down")
    return 200, {"reply": "done"}


ad._req = _boom
res3 = ad.send_task(AgentRef(id="t", session="S3"), "solve")
check("B2 a broken ledger never fails the task",
      res3.ok and res3.tokens == 0, (res3.ok, res3.tokens))

# ---------------------------------------------- C. the consumer still reads it ---
pg = open(os.path.join(REPO, "benchmarks", "polyglot_compare.py"), encoding="utf-8").read()
check("C1 the polyglot report falls back to the row's token total",
      'int(r.get("tokens") or 0)' in pg)
runner = open(os.path.join(REPO, "benchmarks", "runner.py"), encoding="utf-8").read()
check("C2 the generic runner stores the result's token total",
      '"tokens": res.tokens' in runner)

print("---")
passed = sum(results)
print("%d/%d PASS" % (passed, len(results)))
sys.exit(0 if passed == len(results) else 1)
