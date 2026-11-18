#!/usr/bin/env python3
"""v1011 — local harness optimizer gate + evidence collection (S1).

The optimizer (evolve/optimizer.py) reads existing ledgers (runmetrics, policy_hits,
jobcost) after every session, builds the evidence block and the analysis prompt, asks
the model for ONE registry delta, and submits it through the existing approvals
pipeline. It never modifies the harness directly.

This test is DETERMINISTIC: it forces the model call to return nothing (as if the
router were unreachable) and asserts the gate, the evidence, the prompt and the
append-only log. The model-dependent path is v1013.

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

# Deterministic: no model is reachable in this test.
optimizer._call_model = lambda prompt, model=None: None

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""))


# ---- A) the optimizer skips sessions with no activity ----------------------
r = optimizer.run("s-missing")
check("A1 unknown session returns skip", r.get("skip") is True, r)
check("A2 skip reason is 'no trace'", r.get("reason") == "no trace", r.get("reason"))

runmetrics.start("s-empty")
runmetrics.finish("s-empty", tokens=0, steps=0)
r = optimizer.run("s-empty")
check("A3 empty session returns skip", r.get("skip") is True, r)
check("A4 skip reason mentions minimum", "below minimum" in r.get("reason", ""), r.get("reason"))

# ---- B) the optimizer builds evidence + prompt for an active session --------
runmetrics.start("s-active")
runmetrics.finish("s-active", tokens=500, steps=3, outcome="done",
                  code=0, model="test-model")
r = optimizer.run("s-active")
# No model reachable -> the run skips, but ONLY after building the evidence and the
# prompt (both are carried on the skip result).
check("B1 no-model run skips", r.get("skip") is True, r)
check("B2 skip reason names the missing reply (round 76: no reply is not 'unparseable')",
      r.get("reason") == "no reply from the model", r.get("reason"))
check("B3 evidence records token count", (r.get("evidence") or {}).get("tokens") == 500, r.get("evidence"))
check("B4 evidence records step count", (r.get("evidence") or {}).get("steps") == 3, r.get("evidence"))
check("B5 evidence records outcome", (r.get("evidence") or {}).get("outcome") == "done", r.get("evidence"))
check("B6 prompt asks for a registry delta",
      "registry" in str(r.get("prompt", "")).lower() and "target" in str(r.get("prompt", "")),
      len(str(r.get("prompt", ""))))

# ---- C) a failed session is analysed the same way --------------------------
runmetrics.start("s-failed")
runmetrics.finish("s-failed", tokens=300, steps=1, outcome="error", code=124, model="test-model")
r = optimizer.run("s-failed")
check("C1 failed session reaches the model gate",
      r.get("skip") is True and r.get("reason") == "no reply from the model", r)
check("C2 exit code recorded in evidence",
      (r.get("evidence") or {}).get("exit_code") == 124, r.get("evidence"))

# ---- D) the optimizer log is append-only -----------------------------------
with open(os.environ["LONGRUN_OPTIMIZER_LOG"], encoding="utf-8") as f:
    rows = [json.loads(line) for line in f if line.strip()]
check("D1 log has a row per analysed session", len(rows) >= 2, len(rows))
check("D2 each log row has a timestamp", all("ts" in r for r in rows))
check("D3 each log row has a session", all("session" in r for r in rows))

# ---- E) no session id returns skip -----------------------------------------
r = optimizer.run("")
check("E1 empty session id returns skip", r.get("skip") is True, r)
r = optimizer.run(None)
check("E2 None session id returns skip", r.get("skip") is True, r)

# ---- F) the optimizer does NOT modify runmetrics or any other state --------
m = runmetrics.get("s-active") or {}
check("F1 runmetrics unchanged after optimizer run", m.get("tokens") == 500, m)

print("---")
passed = sum(results)
print("%d/%d PASS" % (passed, len(results)))
sys.exit(0 if passed == len(results) else 1)
