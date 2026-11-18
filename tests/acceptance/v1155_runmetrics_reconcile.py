#!/usr/bin/env python3
"""v1155 — a turn killed by a restart stops saying "running" (round 92).

`runmetrics.start()` writes `outcome: "running"` and only `finish()` replaces it.
`tracing.reconcile_orphans` sweeps the `runs` TABLE at boot, but the metrics
ledger (data/runs/<key>.json) had no sweep — measured 2026-11-18: 19 of 141
records still "running", the oldest 45 days old. The harness record
(`harness/record.py:258`) and `self.info` read that outcome, so the operator and
the agent saw phantom turns.

Contract:
  A a record started before the boot cut becomes `interrupted` and keeps `ended: None`
  B a record started AFTER the cut (a live turn) is untouched
  C a finished record is untouched (done stays done)
  D an unreadable file is skipped, never raised
  E a second call is a no-op (idempotent)
  F the restart is not blamed on any of the four causes
  G the boot hook runs the sweep and publishes when it closed something

Deterministic: its own throwaway runs dir, no model, no network.
Run: python3 tests/acceptance/v1155_runmetrics_reconcile.py
"""
import json
import os
import sys
import tempfile
import time

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="sf-v1155-")
os.environ["LONGRUN_RUNS_DIR"] = os.path.join(TMP, "runs")
os.environ["LONGRUN_DATA_DIR"] = os.path.join(TMP, "data")
os.environ["LONGRUN_CONFIG_DIR"] = os.path.join(TMP, "cfg")
os.environ["LONGRUN_DB"] = os.path.join(TMP, "events.db")
for _d in ("runs", "data", "cfg"):
    os.makedirs(os.path.join(TMP, _d), exist_ok=True)
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.model import runmetrics as RM                # noqa: E402

RESULTS = []


def check(name, ok, detail=""):
    RESULTS.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name
          + ((" :: " + str(detail)[:300]) if detail and not ok else ""))


NOW = round(time.time(), 3)


def _write(key, rec):
    with open(os.path.join(RM.RUNS_DIR, key + ".json"), "w", encoding="utf-8") as f:
        json.dump(rec, f)


def _running(started):
    return {"key": "k", "model": "m", "started": started, "ended": None,
            "duration_s": None, "iterations": 0, "steps": 3, "tokens": 10,
            "outcome": "running", "stop_reason": None, "difficulty": None,
            "code": None}


# A — a stale "running" record is closed, `ended` stays unknown
_write("stale", _running(NOW - 3600))
r = RM.reconcile_stale(before=NOW)
rec = RM.get("stale")
check("A1 one record closed", r.get("closed") == 1, r)
check("A2 outcome is interrupted", rec.get("outcome") == "interrupted", rec)
check("A3 stop_reason names the restart",
      rec.get("stop_reason") == "interrupted-by-restart", rec)
check("A4 ended stays None (the real end is unknown)", rec.get("ended") is None, rec)

# B — a record from a turn the boot did not orphan is untouched
_write("live", _running(NOW + 5))
r = RM.reconcile_stale(before=NOW)
check("B1 the live turn is not closed",
      r.get("closed") == 0 and RM.get("live").get("outcome") == "running",
      (r, RM.get("live")))

# C — a finished record is untouched
_write("done", dict(_running(NOW - 60), outcome="done", stop_reason="goal_reached",
                    ended=NOW - 30))
r = RM.reconcile_stale(before=NOW)
check("C1 a done record keeps its outcome and stop reason",
      RM.get("done").get("outcome") == "done"
      and RM.get("done").get("stop_reason") == "goal_reached", RM.get("done"))

# D — an unreadable file is skipped
with open(os.path.join(RM.RUNS_DIR, "broken.json"), "w", encoding="utf-8") as f:
    f.write("{not json")
r = RM.reconcile_stale(before=NOW)
check("D1 a broken file never raises", r.get("closed") == 0, r)

# E — idempotent
r = RM.reconcile_stale(before=NOW)
check("E1 a second sweep closes nothing", r.get("closed") == 0, r)

# F — a restart is not a failure of provider/budget/model/harness
check("F1 classify_cause('interrupted') is None",
      RM.classify_cause("interrupted", "interrupted-by-restart") is None,
      RM.classify_cause("interrupted", "interrupted-by-restart"))
check("F2 the closed record carries no failure cause",
      RM.get("stale").get("failure_cause") is None, RM.get("stale"))

# G — the boot hook owns the sweep
http = open(os.path.join(REPO, "src", "longrun", "core", "httpapi.py"),
            encoding="utf-8").read()
check("G1 the boot calls reconcile_stale before the cut",
      "_rm_boot.reconcile_stale(before=time.time())" in http, "httpapi boot")
check("G2 the boot publishes what it closed",
      'publish("runmetrics.reconciled"' in http, "httpapi boot")

print("---")
print("%d/%d PASS" % (sum(RESULTS), len(RESULTS)))
sys.exit(0 if all(RESULTS) else 1)
