#!/usr/bin/env python3
"""v454 — harness comparison bench: adapters, fairness, runner (JAG-454).

Pins the "how much is the harness worth?" infrastructure, all deterministic (no
model, no network, no server):

  A) every arm implements the SAME adapter protocol (bare / longrun / hermes), so
     a comparison is apples-to-apples by construction;
  B) LongrunAdapter enters a BEENCHMARK-READY state (approval gate lifted) and
     restores the operator's settings afterwards — otherwise a headless run
     measures a harness with its hands tied;
  C) the code extraction is applied UNIFORMLY by the scorer (a chatty arm is not
     penalised vs a terse one);
  D) the runner brackets the suite with setup()/teardown() when present;
  E) the pilot task set + the compare CLI exist.

Run: python3 tests/acceptance/v454_bench_compare.py
"""
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(REPO))

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""))


def _read(*parts):
    with open(os.path.join(REPO, *parts), encoding="utf-8") as f:
        return f.read()


from benchmarks.protocol import HarnessAdapter          # noqa: E402
from benchmarks.bare_adapter import BareAdapter         # noqa: E402
from benchmarks.longrun_adapter import LongrunAdapter   # noqa: E402
from benchmarks.hermes_adapter import HermesAdapter     # noqa: E402
from benchmarks import humaneval                        # noqa: E402

# ---- A: one protocol, three arms --------------------------------------------
check("A1 bare implements the adapter protocol", isinstance(BareAdapter(), HarnessAdapter))
check("A2 longrun implements the adapter protocol", isinstance(LongrunAdapter(), HarnessAdapter))
check("A3 hermes implements the adapter protocol", isinstance(HermesAdapter(), HarnessAdapter))
check("A4 each arm declares a distinct name",
      len({BareAdapter().name, LongrunAdapter().name, HermesAdapter().name}) == 3,
      [BareAdapter().name, LongrunAdapter().name, HermesAdapter().name])
# the adapters must NOT import the harness: what is measured is the REST surface
check("A5 the adapters never import longrun.*",
      "import longrun" not in _read("benchmarks", "bare_adapter.py")
      and "from longrun" not in _read("benchmarks", "longrun_adapter.py")
      and "from longrun" not in _read("benchmarks", "hermes_adapter.py"))

# ---- B: the Longrun arm lifts the approval gate (and restores it) -----------
la_src = _read("benchmarks", "longrun_adapter.py")
check("B1 the longrun arm has setup()/teardown()", "def setup(self)" in la_src
      and "def teardown(self)" in la_src)
check("B2 setup() sets approvals.mode=full (a headless run has nobody to approve)",
      '"mode": "full"' in la_src)
check("B3 setup() forces the per-category kinds to auto",
      all(('"%s": "auto"' % k) in la_src for k in ("memory", "proposals", "skills", "subagent")))
check("B4 setup() disables the apply-only-if-green verifier",
      '"verifier": {"enabled": False}' in la_src)
check("B5 the previous policy is captured to restore it later",
      "self._policy = dict(before.get" in la_src and "self._verifier = dict(before.get" in la_src)
check("B6 provenance reports the applied policy", '"policy": self._policy' in la_src)
check("B7 teardown() restores the captured mode", "restore the operator" in la_src
      or 'body = {"approvals": {"mode": (self._policy or {}).get("mode", "normal")}}' in la_src)

# ---- C: uniform code extraction (fair scoring) ------------------------------
check("C1 a fenced block is unwrapped",
      humaneval.extract_code("```python\nx = 1\n```") == "x = 1",
      humaneval.extract_code("```python\nx = 1\n```"))
check("C2 an unterminated fence is handled",
      humaneval.extract_code("```\nx = 1") == "x = 1", humaneval.extract_code("```\nx = 1"))
check("C3 bare code passes through untouched",
      humaneval.extract_code("def f(): return 1") == "def f(): return 1")
check("C4 the SCORER applies extract_code uniformly",
      "check(extract_code(p.get(\"prediction\", \"\")), task)" in _read("benchmarks", "humaneval.py"))
check("C5 the prompt still asks for bare code (so extract is a safety net)",
      "Reply with ONLY the code" in humaneval.prompt_for({"prompt": "def f():"}))

# ---- D: the runner brackets a run with setup/teardown -----------------------
run_src = _read("benchmarks", "runner.py")
check("D1 run_suite calls setup() when the adapter has one",
      'if hasattr(adapter, "setup"):' in run_src and "adapter.setup()" in run_src)
check("D2 run_suite restores via teardown() in a finally",
      'if hasattr(adapter, "teardown"):' in run_src and "finally:" in run_src)

# ---- E: the pilot task set + the compare CLI -------------------------------
check("E1 a HumanEval pilot task file is present",
      os.path.isfile(os.path.join(REPO, "benchmarks", "tasks", "humaneval_n20.jsonl")))
tasks = humaneval.load_tasks(os.path.join(REPO, "benchmarks", "tasks", "humaneval_n20.jsonl"))
check("E2 it holds the official HumanEval shape",
      len(tasks) >= 10 and all(k in tasks[0] for k in ("task_id", "prompt", "test", "entry_point")),
      len(tasks))
cmp_src = _read("benchmarks", "compare.py")
check("E3 compare.py wires the three arms",
      all(('name == "%s"' % a) in cmp_src for a in ("bare", "longrun", "hermes")))
check("E4 it emits a side-by-side artifact",
      '"compare.json"' in cmp_src and '"compare.md"' in cmp_src)
check("E5 it passes the SAME upstream endpoint to the non-harness arms",
      "upstream_base=args.upstream_base" in cmp_src)

# ---- F: operator affordances (keep sessions, parallel tasks) ----------------
check("F1 --keep-sessions means delete_agent is a NO-OP (inspect the run in the WebUI)",
      "if self.keep_sessions:" in la_src and "def delete_agent" in la_src)
check("F2 the kept sessions are TAGGED so the run is findable",
      'title = ("%s · %s" % (self.tag, base_title)) if self.tag else base_title' in la_src)
check("F3 the arm pins its model on the session (a cloud model, not the default)",
      '/model" % urllib.parse.quote(sid)' in la_src)
check("F4 the CLI exposes --keep-sessions + --tag",
      '"--keep-sessions"' in cmp_src and '"--tag"' in cmp_src)
check("F5 run_suite can run tasks in PARALLEL (jobs)",
      "ThreadPoolExecutor" in run_src and "jobs=1" in run_src)
check("F6 parallel results keep task order (written back by index)",
      "rows[i] = " in run_src and "preds[i] = " in run_src)

print("---")
okc = sum(results)
print("\nv454: %d/%d PASS" % (okc, len(results)))
sys.exit(0 if okc == len(results) else 1)