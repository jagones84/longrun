#!/usr/bin/env python3
"""v1011 — local harness optimizer reads session traces and produces proposals (S1).

The optimizer (evolve/optimizer.py) reads existing ledgers (runmetrics, policy_hits,
jobcost) after every session and produces structured proposals targeting the tool
registry or gate tables. It never modifies the harness directly — proposals go through
the existing human review gate.

Deterministic: temp stores, no server, no model.
Run: python3 tests/acceptance/v1011_local_optimizer.py
"""
import json
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="sf-v1011-")
os.environ["LONGRUN_DATA_DIR"] = TMP
os.environ["LONGRUN_RUNS_DIR"] = os.path.join(TMP, "runs")
os.environ["LONGRUN_OPTIMIZER_LOG"] = os.path.join(TMP, "optimizer_runs.jsonl")
os.makedirs(os.environ["LONGRUN_RUNS_DIR"], exist_ok=True)
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.model import runmetrics      # noqa: E402
from longrun.evolve import optimizer       # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""))


# ---- A) the optimizer skips sessions with no activity ----------------------
runmetrics.start("s-empty")
runmetrics.finish("s-empty", tokens=0, steps=0)
r = optimizer.run("s-empty")
check("A1 empty session returns skip", r.get("skip") is True, r)
check("A2 skip reason mentions minimum", "below minimum" in r.get("reason", ""), r.get("reason"))

# ---- B) the optimizer runs on sessions with tool calls ---------------------
runmetrics.start("s-active")
runmetrics.finish("s-active", tokens=500, steps=3, outcome="done",
                  code=0, model="test-model")
r = optimizer.run("s-active")
check("B1 active session produces a proposal", r.get("skip") is not True, r)
check("B2 proposal has session id", r.get("session") == "s-active", r.get("session"))
check("B3 proposal has evidence block", isinstance(r.get("evidence"), dict), r.get("evidence"))
check("B4 evidence records token count", r["evidence"].get("tokens") == 500, r["evidence"])
check("B5 evidence records step count", r["evidence"].get("steps") == 3, r["evidence"])
check("B6 evidence records outcome", r["evidence"].get("outcome") == "done", r["evidence"])
check("B7 proposal has an analysis prompt", isinstance(r.get("prompt"), str) and len(r["prompt"]) > 50, len(r.get("prompt", "")))
check("B8 proposal has proposal field (None when router unreachable)", "proposal" in r, list(r.keys()))
check("B9 optimizer survives router unreachable without crashing", r.get("skip") is not True, r)

# ---- C) the optimizer handles sessions with exit codes ---------------------
runmetrics.start("s-failed")
runmetrics.finish("s-failed", tokens=300, steps=1, outcome="error",
                  code=124, model="test-model")
r = optimizer.run("s-failed")
check("C1 failed session still produces a proposal", r.get("skip") is not True, r)
check("C2 failure cause recorded in trace",
      isinstance(r["evidence"].get("outcome"), str) and r["evidence"]["outcome"] == "error", r["evidence"])

# ---- D) the optimizer log is append-only -----------------------------------
with open(os.environ["LONGRUN_OPTIMIZER_LOG"], encoding="utf-8") as f:
    rows = [json.loads(line) for line in f if line.strip()]
check("D1 log has rows for all runs", len(rows) >= 2, len(rows))
check("D2 each log row has a timestamp", all("ts" in r for r in rows))
check("D3 each log row has a session", all("session" in r for r in rows))

# ---- E) no session id returns skip -----------------------------------------
r = optimizer.run("")
check("E1 empty session id returns skip", r.get("skip") is True, r)
r = optimizer.run(None)
check("E2 None session id returns skip", r.get("skip") is True, r)

# ---- F) the optimizer does NOT modify runmetrics or any other state --------
# It only reads and writes its own log. Verify runmetrics is unchanged.
m = runmetrics.get("s-active") or {}
check("F1 runmetrics unchanged after optimizer run", m.get("tokens") == 500, m)

print("---")
passed = sum(results)
print("%d/%d PASS" % (passed, len(results)))
sys.exit(0 if passed == len(results) else 1)