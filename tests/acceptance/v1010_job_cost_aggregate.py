#!/usr/bin/env python3
"""v1010 — one delegation cost aggregate keyed by job id (R6).

The run ledger knows what a TURN cost and the cost ledger prices it, but neither
is keyed by the ORBIT job a turn belongs to, so dispatch-vs-subagent was chosen
blind. `orchestrate.jobcost` adds exactly that aggregate; `_run_agent` writes one
row per delegated turn through `_note_cost`, which returns the reply untouched.

Deterministic: temp stores and a temp ledger, no server, no model.
Run: python3 tests/acceptance/v1010_job_cost_aggregate.py
"""
import json
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="sf-v1010-")
os.environ["LONGRUN_DATA_DIR"] = TMP
os.environ["LONGRUN_RUNS_DIR"] = os.path.join(TMP, "runs")
os.environ["LONGRUN_JOBCOST_FILE"] = os.path.join(TMP, "job_costs.jsonl")
os.environ["LONGRUN_JOBS_FILE"] = os.path.join(TMP, "jobs.json")
os.environ["LONGRUN_SESSIONS_DIR"] = os.path.join(TMP, "sessions")
os.makedirs(os.environ["LONGRUN_RUNS_DIR"], exist_ok=True)
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.model import runmetrics             # noqa: E402
from longrun.orchestrate import jobcost           # noqa: E402
from longrun.orchestrate import jobs as jobs_mod  # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""))


# ---- A) the aggregate: one key, three numbers ------------------------------
runmetrics.start("s1")
runmetrics.finish("s1", tokens=1200, prompt_tokens=900, completion_tokens=300, usd=0.0042)
_reply = jobs_mod.JOBS._note_cost("J9", "s1", "the reply")
check("A1 _note_cost returns the reply untouched", _reply == "the reply", _reply)
a1 = jobcost.aggregate("J9")
check("A2 one delegated turn is one row with tokens/usd/seconds",
      a1["turns"] == 1 and a1["tokens"] == 1200 and a1["usd"] == 0.0042
      and a1["sessions"] == ["s1"], a1)

# A second turn on the same job, with no priced call: usd stays the priced sum.
runmetrics.start("s1")
runmetrics.finish("s1", tokens=800)
jobs_mod.JOBS._note_cost("J9", "s1", "second")
a2 = jobcost.aggregate("J9")
check("A3 turns accumulate and an unpriced turn never turns usd into 0",
      a2["turns"] == 2 and a2["tokens"] == 2000 and a2["usd"] == 0.0042, a2)

check("A4 an unknown job is empty, not an error",
      jobcost.aggregate("J404") == {"job": "J404", "tokens": 0, "usd": None,
                                    "seconds": 0.0, "turns": 0, "sessions": []},
      jobcost.aggregate("J404"))

# ---- B) the ledger is append-only and tolerant of one bad line -------------
with open(os.environ["LONGRUN_JOBCOST_FILE"], "a", encoding="utf-8") as f:
    f.write("{not json}\n")
check("B1 a malformed row is skipped, not fatal",
      jobcost.aggregate("J9")["turns"] == 2, jobcost.aggregate("J9"))
with open(os.environ["LONGRUN_JOBCOST_FILE"], encoding="utf-8") as f:
    _rows = [json.loads(line) for line in f if line.strip().startswith("{") and "not json" not in line]
check("B2 rows are one JSON object per line with the job key",
      len(_rows) == 2 and all(r.get("job") == "J9" for r in _rows), _rows)

# ---- C) no job id, no row -------------------------------------------------
check("C1 a manual turn (no job) writes nothing",
      jobs_mod.JOBS._note_cost(None, "s1", "manual") == "manual"
      and jobcost.aggregate("J9")["turns"] == 2)

print("---")
passed = sum(results)
print("%d/%d PASS" % (passed, len(results)))
sys.exit(0 if passed == len(results) else 1)
