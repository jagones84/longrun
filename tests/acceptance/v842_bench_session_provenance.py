#!/usr/bin/env python3
"""v842 — a benchmark sample must leave a pointer to its own record.

A stored `result.json` used to carry one lump token total and no session id, so
two runs of the same task could only be compared by their score: the number of
calls, the provider cache share and the duplicate best-of-N samples were
unreachable (the ledger exists per session, and the id was never written). The
SWE slice even stored `tokens_out: 0` for the longrun arm while the ledger knew
the real number — a silent zero, the class of error in "Silent Instrument
Errors" (2026-11-05).

  A) `send_task` returns the session id and the ledger summary;
  B) the ledger request asks for the whole turn, not the UI's last 60 rows;
  C) `ledger_usage` reports real in/out/calls/cache/duplicates;
  D) the SWE slice writes `session` and the rich usage into `result.json`;
  E) `benchmarks.trend` joins a stored sample to its ledger, and says
     `no-ledger` instead of inventing a zero.

Deterministic, no live model, no network, no server.
"""
import json
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, REPO)

from benchmarks.longrun_adapter import LongrunAdapter        # noqa: E402
from benchmarks.protocol import AgentRef                     # noqa: E402
from benchmarks.swebench_slice import ledger_usage           # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""))


LEDGER = {
    "calls": 3, "tokens_in": 1000, "tokens_out": 200, "cached": 800,
    "total_usd": 0.25,
    "recent": [
        {"prompt": 400, "completion": 80, "cached": 300, "latency_ms": 900, "tag": None},
        {"prompt": 400, "completion": 60, "cached": 300, "latency_ms": 800,
         "tag": "bestofn"},
        {"prompt": 200, "completion": 60, "cached": 200, "latency_ms": 0},
    ],
}

# ------------------------------------------------ A. session + usage survive ---
paths = []


def _stub(method, path, body=None, timeout=None):
    paths.append(path)
    if path.startswith("/api/costs"):
        return 200, dict(LEDGER)
    if path.startswith("/api/chat"):
        return 200, {"reply": "done", "run_id": "r1"}
    return 200, {}


ad = LongrunAdapter(token="x")            # explicit token -> no token discovery
ad._req = _stub
res = ad.send_task(AgentRef(id="t", session="S7"), "solve")
check("A1 the result carries the session id", res.session == "S7", res.session)
check("A2 the result carries the ledger summary",
      res.usage.get("calls") == 3 and res.usage.get("tokens_out") == 200,
      {k: res.usage.get(k) for k in ("calls", "tokens_out")})
check("A3 the lump totals still work", res.tokens == 1200, res.tokens)

# ------------------------------------------------- B. the whole turn, not 60 ---
cost_paths = [p for p in paths if p.startswith("/api/costs")]
check("B1 the ledger request asks for every call of the turn",
      cost_paths and "tail=100000" in cost_paths[0], cost_paths)

# ---------------------------------------------------------- C. the rich usage ---
u = ledger_usage(res)
check("C1 in/out are separate, real numbers",
      (u["tokens_in"], u["tokens_out"]) == (1000, 200), u)
check("C2 calls and cache come from the ledger",
      (u["calls"], u["cached"]) == (3, 800), u)
check("C3 a tagged and a legacy zero-latency row both count as duplicates",
      u["dup_calls"] == 2, u["dup_calls"])
check("C4 usd is the ledger total", abs(u["total_usd"] - 0.25) < 1e-9, u["total_usd"])
check("C5 a result without a ledger degrades to zeros, never a crash",
      ledger_usage(type("R", (), {"usage": {}, "cost_usd": 0.0})())["calls"] == 0)

# ---------------------------------------------- D. the SWE slice records it ---
src = open(os.path.join(REPO, "benchmarks", "swebench_slice.py"), encoding="utf-8").read()
check("D1 result.json carries the session", '"session": sid' in src)
check("D2 it does not fabricate tokens_out: 0 any more", '"tokens_out": 0,' not in src)
check("D3 the openclaw arm records its gateway session key", 'sid = "swe:%s:%s"' in src)

# ------------------------------------------- E. the trend view reads the pair ---
tmp = tempfile.mkdtemp(prefix=".v842-", dir=os.path.dirname(REPO))
run_root = os.path.join(tmp, "runs")
run_dir = os.path.join(run_root, "2026-11-07_010101_swe_demo")
os.makedirs(run_dir)
os.makedirs(os.path.join(tmp, "data", "costs"))
with open(os.path.join(run_dir, "result.json"), "w", encoding="utf-8") as fh:
    json.dump({"instance": "demo__demo-1", "arm": "longrun", "strict": True,
               "duration_s": 10.0, "session": "S9",
               "usage": {"tokens_in": 1, "tokens_out": 1, "calls": 1}}, fh)
with open(os.path.join(tmp, "data", "costs", "S9.json"), "w", encoding="utf-8") as fh:
    json.dump([{"prompt": 500, "completion": 50, "cached": 400, "latency_ms": 700,
                "usd": 0.01},
               {"prompt": 500, "completion": 50, "cached": 400, "latency_ms": 0,
                "usd": 0.02, "tag": "bestofn"}], fh)
os.makedirs(os.path.join(run_root, "2026-11-07_020202_swe_old"))
with open(os.path.join(run_root, "2026-11-07_020202_swe_old", "result.json"),
          "w", encoding="utf-8") as fh:
    json.dump({"instance": "demo__demo-2", "arm": "longrun", "strict": False,
               "duration_s": 4.0}, fh)

os.environ["LONGRUN_DATA_DIR"] = os.path.join(tmp, "data")
# `LONGRUN_COSTS_DIR` wins over the data dir in `costs_dir()` (the battery exports
# it for every test), so pin it too or this test reads the live ledger.
os.environ["LONGRUN_COSTS_DIR"] = os.path.join(tmp, "data", "costs")
from benchmarks import trend                                  # noqa: E402

rows = {r["task"]: r for r in trend.samples(run_root)}
check("E1 a sampled run is read from its ledger, not from its score",
      rows["demo__demo-1"]["calls"] == 2 and rows["demo__demo-1"]["tin"] == 1000
      and rows["demo__demo-1"]["src"] == "ledger", rows["demo__demo-1"])
check("E2 the duplicate sample is counted", rows["demo__demo-1"]["dup"] == 1)
check("E3 a sample with no pointer is 'no-ledger', never 0 spent",
      rows["demo__demo-2"]["src"] == "no-ledger", rows["demo__demo-2"])
check("E3b the bill is summed from the per-call rows, not from a stored total",
      abs(float(rows["demo__demo-1"]["usd"] or 0) - 0.03) < 1e-9,
      rows["demo__demo-1"]["usd"])
check("E4 the CLI answers for the stored tree",
      trend.main(["--root", run_root]) == 0)

print("---")
passed = sum(results)
print("%d/%d PASS" % (passed, len(results)))
sys.exit(0 if passed == len(results) else 1)
