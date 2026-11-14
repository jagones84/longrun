#!/usr/bin/env python3
"""v1014 — upstream feedback is composed through the whole DAG chain (S2).

In a 3-node chain A → B → C (B consumes A's output, C consumes B's), when only the
LAST node fails, `_propagate_feedback` walks the DAG in reverse topological order and
gives EVERY upstream node a record: A learns that its output was consumed by B and
that the chain failed at C. A chain where nothing fails writes nothing.

Deterministic: temp stores, no server, no model.
Run: python3 tests/acceptance/v1014_upstream_feedback_chain.py
"""
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="sf-v1014-")
os.environ["LONGRUN_DATA_DIR"] = TMP
os.environ["LONGRUN_RUNS_DIR"] = os.path.join(TMP, "runs")
os.environ["LONGRUN_JOBCOST_FILE"] = os.path.join(TMP, "job_costs.jsonl")
os.environ["LONGRUN_FEEDBACK_FILE"] = os.path.join(TMP, "job_feedback.jsonl")
os.environ["LONGRUN_JOBS_FILE"] = os.path.join(TMP, "jobs.json")
os.environ["LONGRUN_SESSIONS_DIR"] = os.path.join(TMP, "sessions")
os.makedirs(os.environ["LONGRUN_RUNS_DIR"], exist_ok=True)
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.orchestrate import jobcost              # noqa: E402
from longrun.orchestrate import jobs as jobs_mod     # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""))


def feedback_lines():
    path = os.environ["LONGRUN_FEEDBACK_FILE"]
    try:
        with open(path, encoding="utf-8") as f:
            return [ln for ln in f if ln.strip()]
    except OSError:
        return []


SESSIONS = {"A": "s-a", "B": "s-b", "C": "s-c"}
DEPS = {"B": ["A"], "C": ["B"]}          # deps[node] = the upstream node it consumes
RUNS = {"A": {"state": "done", "result": "A produced the schema v1"},
        "B": {"state": "done", "result": "B built the migration on A's schema"},
        "C": {"state": "failed", "result": ""}}


def make_job():
    return {"runs": dict(RUNS), "subjobs": {}, "declared_deps": dict(DEPS)}


# ---- A) only the LAST node fails: every upstream node is told ---------------
jobs_mod.JOBS._propagate_feedback("J4", dict(SESSIONS), make_job(),
                                  [(None, "C", "boom: could not read the migration")])

fb_a = jobcost.feedback_for("J4", "s-a")
fb_b = jobcost.feedback_for("J4", "s-b")
fb_c = jobcost.feedback_for("J4", "s-c")

check("A1 the first node has a record", bool(fb_a), fb_a)
check("A2 its immediate consumer is named", fb_a.get("details", {}).get("consumed_by") == "B",
      fb_a.get("details"))
check("A3 the chain failure is named", fb_a.get("details", {}).get("failed_agent") == "C",
      fb_a.get("details"))
check("A4 the chain is A's successor path",
      fb_a.get("details", {}).get("chain") == ["B", "C"], fb_a.get("details"))
check("A5 the record names the consumed output",
      "schema v1" in str(fb_a.get("details", {}).get("output_excerpt", "")),
      fb_a.get("details", {}).get("output_excerpt"))

check("A6 the middle node has a record", bool(fb_b), fb_b)
check("A7 the middle node's consumer is named",
      fb_b.get("details", {}).get("consumed_by") == "C", fb_b.get("details"))
check("A8 the middle node failed at C",
      fb_b.get("details", {}).get("failed_agent") == "C", fb_b.get("details"))

check("A9 the failing node gets no downstream record", fb_c == {}, fb_c)

# ---- B) a PASSING chain writes nothing --------------------------------------
before = len(feedback_lines())
jobs_mod.JOBS._propagate_feedback("J5", dict(SESSIONS), make_job(), [])
check("B1 a passing chain writes no feedback", len(feedback_lines()) == before,
      len(feedback_lines()))

# ---- C) a DIRECT consumer failing still names it ----------------------------
jobs_mod.JOBS._propagate_feedback("J6", dict(SESSIONS), make_job(),
                                  [(None, "B", "boom: bad schema")])
fb_a2 = jobcost.feedback_for("J6", "s-a")
check("C1 the first node is told its direct consumer failed",
      fb_a2.get("details", {}).get("consumed_by") == "B", fb_a2.get("details"))
check("C2 the failed agent is the direct consumer",
      fb_a2.get("details", {}).get("failed_agent") == "B", fb_a2.get("details"))
check("C3 the chain stops at the direct consumer",
      fb_a2.get("details", {}).get("chain") == ["B"], fb_a2.get("details"))

# ---- D) a node with no consumers and no failure gets nothing ----------------
jobs_mod.JOBS._propagate_feedback("J7", {"Z": "s-z"}, {"runs": {"Z": {"state": "done",
                                  "result": "x"}}, "declared_deps": {}}, [])
check("D1 a lone passing node writes nothing", jobcost.feedback_for("J7", "s-z") == {},
      jobcost.feedback_for("J7", "s-z"))

print("---")
passed = sum(results)
print("%d/%d PASS" % (passed, len(results)))
sys.exit(0 if passed == len(results) else 1)
