#!/usr/bin/env python3
"""v1012 — backward feedback propagation through job DAG (S2).

After a job completes, _propagate_feedback traverses the DAG in reverse and records
per-agent feedback. The local optimizer (S1) reads this to connect tool calls to
downstream consequences.

Deterministic: temp stores, no server, no model.
Run: python3 tests/acceptance/v1012_feedback_propagation.py
"""
import json
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="sf-v1012-")
os.environ["LONGRUN_DATA_DIR"] = TMP
os.environ["LONGRUN_RUNS_DIR"] = os.path.join(TMP, "runs")
os.environ["LONGRUN_JOBCOST_FILE"] = os.path.join(TMP, "job_costs.jsonl")
os.environ["LONGRUN_FEEDBACK_FILE"] = os.path.join(TMP, "job_feedback.jsonl")
os.environ["LONGRUN_JOBS_FILE"] = os.path.join(TMP, "jobs.json")
os.environ["LONGRUN_SESSIONS_DIR"] = os.path.join(TMP, "sessions")
os.makedirs(os.environ["LONGRUN_RUNS_DIR"], exist_ok=True)
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.orchestrate import jobcost    # noqa: E402
from longrun.orchestrate import jobs as jobs_mod  # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""))


# ---- A) record_feedback writes a feedback record ---------------------------
r = jobcost.record_feedback("J1", "s-worker", "downstream agent s-down failed: timeout",
                            {"failed_agent": "s-down", "error": "timeout"})
check("A1 record_feedback returns the row", r is not None and r.get("job") == "J1", r)
check("A2 row has agent id", r.get("agent") == "s-worker", r.get("agent"))
check("A3 row has summary", "downstream agent" in r.get("summary", ""), r.get("summary"))
check("A4 row has details", r.get("details", {}).get("failed_agent") == "s-down", r.get("details"))

# ---- B) feedback_for retrieves the most recent record ----------------------
fb = jobcost.feedback_for("J1", "s-worker")
check("B1 feedback_for returns the record", fb.get("job") == "J1" and fb.get("agent") == "s-worker", fb)

# Multiple records for the same agent: most recent wins
jobcost.record_feedback("J1", "s-worker", "second failure", {"failed_agent": "s-down2"})
fb2 = jobcost.feedback_for("J1", "s-worker")
check("B2 most recent record wins", "second failure" in fb2.get("summary", ""), fb2.get("summary"))

# ---- C) feedback_for with no matching agent returns empty ------------------
check("C1 no matching agent returns empty",
      jobcost.feedback_for("J1", "s-nonexistent") == {}, "should be {}")
check("C2 empty agent id returns empty",
      jobcost.feedback_for("J1", "") == {}, "should be {}")

# ---- D) _propagate_feedback with no failures writes nothing -----------------
before_count = 0
try:
    with open(os.environ["LONGRUN_FEEDBACK_FILE"], encoding="utf-8") as f:
        before_count = sum(1 for _ in f)
except OSError:
    pass
jobs_mod.JOBS._propagate_feedback("J2", {}, {}, [])
after_count = 0
try:
    with open(os.environ["LONGRUN_FEEDBACK_FILE"], encoding="utf-8") as f:
        after_count = sum(1 for _ in f)
except OSError:
    pass
check("D1 no failures writes nothing", before_count == after_count,
      f"before={before_count} after={after_count}")

# ---- E) _propagate_feedback with failures records upstream agents ----------
sessions = {"agent-a": "s-a", "agent-b": "s-b", "agent-c": "s-c"}
declared_deps = {"agent-b": ["agent-a"], "agent-c": ["agent-b"]}
job = {"runs": {}, "subjobs": {}, "declared_deps": declared_deps}
failed = [(None, "agent-b", "tool timeout after consuming agent-a output")]
jobs_mod.JOBS._propagate_feedback("J3", sessions, job, failed)
fb_a = jobcost.feedback_for("J3", "s-a")
check("E1 upstream agent receives feedback", bool(fb_a), fb_a)
check("E2 feedback mentions the failed downstream agent",
      "agent-b" in fb_a.get("summary", ""), fb_a.get("summary"))

print("---")
passed = sum(results)
print("%d/%d PASS" % (passed, len(results)))
sys.exit(0 if passed == len(results) else 1)