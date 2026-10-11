#!/usr/bin/env python3
"""v421 — benchmark runners (JAG-426 · Domain 3).

A harness that cannot be measured cannot be improved. This pins the runner half
of Domain 3:

  * `benchmarks.runner.run_suite` drives ANY HarnessAdapter and emits the two
    artifacts every harness benchmark needs (`predictions.jsonl` + `summary.json`)
    with provenance, and cleans up every agent it created;
  * the runner NEVER scores (scoring belongs to the benchmark's own official
    scorer — a re-implemented scorer silently drifts from the leaderboard);
  * `benchmarks.humaneval.check` runs the task's OWN functional test (pass a
    correct candidate, fail a wrong one), and `score` computes pass@1;
  * the CLI parses and degrades gracefully (no network with an empty task file).

Deterministic, no live server. Run: python3 tests/v421_benchmark_runners.py
"""
import json
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="sf-v421-")
sys.path.insert(0, os.path.join(REPO, "src"))
sys.path.insert(0, REPO)

from benchmarks import humaneval, run                          # noqa: E402
from benchmarks.protocol import AgentRef, HarnessAdapter, HarnessResult  # noqa: E402
from benchmarks.runner import run_suite                        # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""))


class FakeAdapter:
    """In-memory HarnessAdapter — proves the runner drives the protocol only."""
    name = "fake"

    def __init__(self, outs=None, fail=None):
        self.outs = outs or {}
        self.fail = set(fail or [])
        self.created, self.deleted = [], []

    def create_agent(self, task):
        ref = AgentRef(id=str(task.get("id", "")), session="s-" + str(task.get("id", "")))
        self.created.append(ref)
        return ref

    def send_task(self, ref, prompt, timeout=None):
        if ref.id in self.fail:
            return HarnessResult(ok=False, error="boom", run_id="r-" + ref.id)
        return HarnessResult(ok=True, output=self.outs.get(ref.id, "ok"),
                             run_id="r-" + ref.id, duration_s=0.01)

    def backup_session(self, ref):
        return "cp"

    def restore(self, ref, checkpoint):
        return True

    def delete_agent(self, ref):
        self.deleted.append(ref)
        return True

    def docker_args(self):
        return []

    def provenance(self):
        return {"harness": "fake", "git_sha": "deadbeef"}


TASKS = [{"id": "t1"}, {"id": "t2"}, {"id": "t3"}]
OUT = os.path.join(TMP, "run-001")

# ---- 1. the runner drives the protocol --------------------------------------
ad = FakeAdapter(outs={"t1": "42"}, fail=["t2"])
check("1a the runner drives any HarnessAdapter",
      isinstance(ad, HarnessAdapter))
res = run_suite(ad, TASKS, OUT, prompt_fn=lambda t: "do " + t["id"], model="m1")

# ---- 2. it emits the two artifacts a benchmark harness needs ----------------
pp = os.path.join(OUT, "predictions.jsonl")
sp = os.path.join(OUT, "summary.json")
check("2a predictions.jsonl is written", os.path.isfile(pp))
check("2b summary.json is written", os.path.isfile(sp))
preds = [json.loads(ln) for ln in open(pp, encoding="utf-8") if ln.strip()]
check("2c one prediction line per task",
      len(preds) == 3 and {p["task_id"] for p in preds} == {"t1", "t2", "t3"})
check("2d the prediction carries the harness reply",
      next(p for p in preds if p["task_id"] == "t1")["prediction"] == "42")

# ---- 3. summary carries ok/failed + provenance ------------------------------
s = json.load(open(sp, encoding="utf-8"))
check("3a summary counts ok + failed", s["n"] == 3 and s["ok"] == 2 and s["failed"] == 1)
check("3b summary records provenance (version + git sha + model)",
      s["provenance"].get("git_sha") == "deadbeef" and s["model"] == "m1")
check("3c the failed task keeps its error", any(r.get("error") == "boom" for r in s["rows"]))

# ---- 4. cleanup: every created agent is deleted -----------------------------
check("4a every created agent is deleted (no leaked sessions)",
      len(ad.created) == 3 and len(ad.deleted) == 3)

# ---- 5. limit truncates the suite -------------------------------------------
ad2 = FakeAdapter()
run_suite(ad2, TASKS, os.path.join(TMP, "run-002"), limit=2)
check("5 limit caps the number of tasks", len(ad2.created) == 2)

# ---- 6. the runner NEVER scores ---------------------------------------------
runner_src = open(os.path.join(REPO, "benchmarks", "runner.py"), encoding="utf-8").read()
check("6a the runner does not compute a score (no pass@ / correctness)",
      "pass@" not in runner_src and "correctness" not in runner_src)

# ---- 7. HumanEval: the task's OWN test decides pass / fail ------------------
FUNC = {"task_id": "HumanEval/0", "prompt": "def add(a, b):\n    \"\"\"Add.\"\"\"\n",
        "test": "def check(candidate):\n    assert candidate(1, 2) == 3\n"
                "    assert candidate(0, 0) == 0\n",
        "entry_point": "add"}
GOOD = "def add(a, b):\n    return a + b\n"
BAD = "def add(a, b):\n    return a - b\n"
check("7a a correct candidate passes the functional check",
      humaneval.check(GOOD, FUNC) == {"ok": True, "passed": True})
r_bad = humaneval.check(BAD, FUNC)
check("7b a wrong candidate fails the functional check (but the check RAN)",
      r_bad["ok"] is True and r_bad["passed"] is False and r_bad.get("error"))
check("7c a task with no `test` is reported, not silently passed",
      humaneval.check(GOOD, {"entry_point": "add"})["ok"] is False)

# ---- 8. score computes pass@1 over paired predictions -----------------------
tasks = [FUNC, dict(FUNC, task_id="HumanEval/1")]
sc = humaneval.score([{"task_id": "HumanEval/0", "prediction": GOOD},
                      {"task_id": "HumanEval/1", "prediction": BAD}], tasks)
check("8a pass@1 matches the functional results",
      sc["n"] == 2 and sc["passed"] == 1 and sc["pass@1"] == 0.5)
check("8b an unknown task_id is counted as a fail, not a crash",
      humaneval.score([{"task_id": "nope", "prediction": GOOD}], tasks)["passed"] == 0)

# ---- 9. task loading + CLI parsing ------------------------------------------
tf = os.path.join(TMP, "tasks.jsonl")
with open(tf, "w", encoding="utf-8") as f:
    f.write(json.dumps(FUNC) + "\n")
check("9a load_tasks reads the HumanEval jsonl shape",
      len(humaneval.load_tasks(tf)) == 1 and run._tasks(tf)[0]["entry_point"] == "add")

empty = os.path.join(TMP, "empty.jsonl")
open(empty, "w").close()
rc = run.main(["--bench", "humaneval", "--tasks", empty, "--out", os.path.join(TMP, "x")])
check("9b the CLI degrades gracefully on an empty task file (no network)", rc == 2)

print("---")
okc = sum(results)
print("\nv421: %d/%d PASS" % (okc, len(results)))
sys.exit(0 if okc == len(results) else 1)
