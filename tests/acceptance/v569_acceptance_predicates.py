#!/usr/bin/env python3
"""v569 (STAGED — M8b1 acceptance predicates): claims anchored to execution
records, evaluated in code (DeerFlow acceptance_verdict parity, narrow slice).
"""

import os
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
TMP = tempfile.mkdtemp(prefix="sf-v569-")
os.environ["LONGRUN_SUBAGENTS_CFG"] = os.path.join(TMP, "subagents.yaml")
os.environ["LONGRUN_SUBAGENT_DIR"] = os.path.join(TMP, "subagents")
os.environ["LONGRUN_GRAPH_DIR"] = os.path.join(TMP, "graphs")
os.environ["LONGRUN_SESSIONS_DIR"] = os.path.join(TMP, "sessions")
os.environ["LONGRUN_DB"] = os.path.join(TMP, "events.db")
os.makedirs(os.environ["LONGRUN_GRAPH_DIR"], exist_ok=True)
sys.path.insert(0, os.path.join(REPO, "src"))

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""))


try:
    from longrun.agent import acceptance as ACC  # noqa: E402
except ImportError as e:
    for n in ("1a", "1b", "1c", "2a", "2b", "2c", "3a", "3b", "4a", "4b"):
        check(n + " acceptance predicates", False, "M8b1 not implemented (%s)" % e)
    print("TOTAL %d/%d" % (sum(results), len(results)))
    sys.exit(1)

# ---- 1. pure file predicates --------------------------------------------------
probe = os.path.join(TMP, "app.py")
with open(probe, "w", encoding="utf-8") as f:
    f.write("x = 1\n")
r = ACC.check_predicates(["file_exists:" + probe], [])
check("1a existing file holds", r["file_exists:" + probe]["holds"], r)
r = ACC.check_predicates(["file_nonempty:" + probe], [])
check("1b non-empty file holds", r["file_nonempty:" + probe]["holds"], r)
r = ACC.check_predicates(["file_exists:relative/path.py"], [])
check("1c relative path is violated (never implicit cwd)",
      not r["file_exists:relative/path.py"]["holds"], r)
r = ACC.check_predicates(["frobnicate:x"], [])
check("1d unknown predicate is violated, never silent",
      not r["frobnicate:x"]["holds"], r)

# ---- 2. execution-anchored predicates ----------------------------------------
trace = [
    {"action": "tool", "tool": "shell",
     "args": {"command": "pytest tests/test_x.py -q"},
     "tool_result": {"ok": True, "exit_code": 0}},
    {"action": "tool", "tool": "fs.write",
     "args": {"path": "/w/app.py", "content": "x"},
     "tool_result": {"ok": True, "exit_code": 0}},
]
r = ACC.check_predicates(["tests_passed:pytest tests/test_x.py"], trace)
check("2a tests_passed holds on a recorded exit-0 run",
      r["tests_passed:pytest tests/test_x.py"]["holds"], r)
r = ACC.check_predicates(["tests_passed:pytest other.py"], trace)
check("2b tests_passed is violated without a matching record",
      not r["tests_passed:pytest other.py"]["holds"], r)
bad_trace = [{"action": "tool", "tool": "shell",
              "args": {"command": "pytest tests/test_x.py -q"},
              "tool_result": {"ok": False, "exit_code": 1}}]
r = ACC.check_predicates(["tests_passed:pytest tests/test_x.py"], bad_trace)
check("2c tests_passed is violated on a recorded failure",
      not r["tests_passed:pytest tests/test_x.py"]["holds"], r)
r = ACC.check_predicates(["file_written:/w/app.py"], trace)
check("2d file_written holds on a recorded ok write",
      r["file_written:/w/app.py"]["holds"], r)
r = ACC.check_predicates(["file_written:/w/other.py"], trace)
check("2e file_written is violated without a write record",
      not r["file_written:/w/other.py"]["holds"], r)

# ---- 3. spawn/collect wiring --------------------------------------------------
from longrun.agent import subagent as SA  # noqa: E402
from longrun.core import api_v02 as A2  # noqa: E402

if not hasattr(SA, "spawn") or "acceptance_criteria" not in SA.spawn.__code__.co_varnames:
    check("3a spawn accepts acceptance_criteria", False, "kwarg missing")
    check("3b collect attaches an acceptance verdict", False, "skipped")
else:
    def _fake_new_run(goal, model=None, max_steps=6, script=None):
        return type("_St", (), {
            "id": "run_acc", "status": "running",
            "model": model, "parent_run_id": None})()

    _o_new, _o_run = A2.new_run, A2.agent_run_v2
    A2.new_run = _fake_new_run
    A2.agent_run_v2 = lambda *a, **k: {
        "status": "done", "summary": "tests passed, file written",
        "trace": list(trace)}
    try:
        SA.load_cfg(reload=True)
        cfg = SA.load_cfg()
        cfg["max_per_run"] = 0
        cfg["max_parallel"] = 0
        SA.save_cfg(cfg)
        SA.load_cfg(reload=True)
        SA._running.clear()
        if hasattr(SA, "_SPAWN_COUNT"):
            SA._SPAWN_COUNT.clear()
        sp = SA.spawn("do it", parent_run_id="pa", max_steps=1, depth=0,
                      acceptance_criteria=["tests_passed:pytest tests/test_x.py",
                                           "file_written:/w/app.py"])
        got = SA.collect(sp.get("subagent_id"), timeout=5)
        check("3a collect attaches an acceptance verdict",
              isinstance(got.get("acceptance"), dict), got.get("acceptance"))
        check("3b all-holds verdict is True without failing the run",
              got.get("acceptance_ok") is True and got.get("ok") is True, got)
        sp2 = SA.spawn("do it badly", parent_run_id="pa", max_steps=1, depth=0,
                       acceptance_criteria=["tests_passed:pytest missing.py"])
        got2 = SA.collect(sp2.get("subagent_id"), timeout=5)
        check("3c violated verdict is explicit and the run still stands",
              got2.get("acceptance_ok") is False and got2.get("ok") is True,
              (got2.get("acceptance"), got2.get("ok")))
    finally:
        A2.new_run, A2.agent_run_v2 = _o_new, _o_run
        SA._running.clear()
        if hasattr(SA, "_SPAWN_COUNT"):
            SA._SPAWN_COUNT.clear()

print("TOTAL %d/%d" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
