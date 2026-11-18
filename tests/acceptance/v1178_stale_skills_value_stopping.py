#!/usr/bin/env python3
"""v1178 — stale skills, paired skill value, anytime stopping (round 109).

Sources:
  * arXiv:2611.22525 "When Agent Skills Go Stale" — after an environment change a
    skill can cost 10 pp of success or 40% of cost, and success can look flat
    while the savings vanish; selective maintenance checks the skill's state
    against the current environment.
  * arXiv:2611.22017 "SkillBuffBench" — skill value is a PAIRED comparison on the
    same tasks with a deterministic verifier and task-level uncertainty, with
    cost beside the score.
  * arXiv:2611.22901 "Done, But Still Working" — agents keep working after their
    tests pass; the actionable rule is "stop after the same patch passes twice".

Deterministic: markdown/dicts in, dicts out; a fixed bootstrap seed; no model.

Run: python3 tests/acceptance/v1178_stale_skills_value_stopping.py
"""
import json
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="sf-v1178-")
for _key in ("CONFIG_DIR", "SESSIONS_DIR", "GRAPH_DIR", "EDITS_DIR",
             "RUNS_DIR", "DATA_DIR", "THREADS_DIR", "COSTS_DIR", "MEMORY_DIR"):
    os.environ["LONGRUN_" + _key] = os.path.join(TMP, _key)
    os.makedirs(os.environ["LONGRUN_" + _key], exist_ok=True)
os.environ["LONGRUN_DB"] = os.path.join(TMP, "events.db")
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.tools import registry                # noqa: E402
registry._external_tools = lambda: {}             # noqa: E731
from longrun.harness import skills_maintenance as SM  # noqa: E402
from longrun.harness import skill_value as SV     # noqa: E402
from longrun.plan import stopping as ST           # noqa: E402

RESULTS = []


def check(name, ok, detail=""):
    RESULTS.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name
          + ((" :: " + str(detail)) if detail else ""))


NAMES = {"fs.read", "fs.write", "grep.search"}

# ---- 1. stale skills --------------------------------------------------------
TEXT = ("Run `fs.read` then `fs.reed` on `src/longrun/core/forge.py`, "
        "and never on `src/nope/missing.py`.\n")
res = SM.audit(TEXT, repo=REPO, names=NAMES)
kinds = {(f["kind"], f["value"]) for f in res["findings"]}
check("a valid tool reference is not a finding", ("tool", "fs.read") not in kinds)
check("a renamed tool is a finding", ("tool", "fs.reed") in kinds, res["findings"])
check("a dead path is a finding", ("path", "src/nope/missing.py") in kinds)
check("a real path is not a finding", ("path", "src/longrun/core/forge.py") not in kinds)
reed = next(f for f in res["findings"] if f["value"] == "fs.reed")
check("a stale tool names its candidates", "fs.read" in reed.get("candidates"), reed)

root = os.path.join(TMP, "skills")
os.makedirs(os.path.join(root, "good"))
os.makedirs(os.path.join(root, "bad"))
with open(os.path.join(root, "good", "SKILL.md"), "w", encoding="utf-8") as fh:
    fh.write("Use `fs.read`.\n")
with open(os.path.join(root, "bad", "SKILL.md"), "w", encoding="utf-8") as fh:
    fh.write("Use `fs.reed` on `src/nope.py`.\n")
m = SM.maintain(root, repo=REPO, names=NAMES)
check("maintenance states skills and stale counts",
      m["counts"] == {"skills": 2, "stale": 1}, m["counts"])
check("the stale skill is named with its findings",
      m["stale"][0]["skill"] == "bad" and len(m["stale"][0]["findings"]) == 2)
rep = SM.repair(TEXT, {"fs.reed": "fs.read", "src/nope/missing.py": "src/longrun/core/forge.py"})
check("repair applies the explicit map", "fs.reed" not in rep["text"]
      and rep["changes"][0]["count"] == 1, rep["changes"])

# ---- 2. paired skill value --------------------------------------------------
def recs(with_pass, without_pass, with_cost, without_cost, n=20):
    return [{"task": "t%d" % i, "skill": "s",
             "with": {"pass": with_pass, "cost": with_cost, "rounds": 5},
             "without": {"pass": without_pass, "cost": without_cost, "rounds": 5}}
            for i in range(n)]

keep = SV.paired(recs(1, 0, 10, 10))
check("a skill that raises the pass rate is kept",
      keep["pass"]["verdict"] == "positive" and keep["verdict"] == "keep",
      keep["pass"])
flat = SV.paired(recs(1, 1, 15, 10))
check("flat success with a cost increase is a retire (the paper's trap)",
      flat["flat_savings"] is True and flat["verdict"] == "retire",
      (flat["pass"], flat["cost"]))
neg = SV.paired(recs(0, 1, 10, 10))
check("a skill that lowers the pass rate is retired",
      neg["verdict"] == "retire", neg["pass"])
check("no records is honest no-evidence",
      SV.paired([])["verdict"] == "no-evidence")
check("the bootstrap is deterministic",
      SV.paired(recs(1, 1, 16, 10))["cost"]["ci"] ==
      SV.paired(recs(1, 1, 16, 10))["cost"]["ci"])

# ---- 3. anytime stopping ----------------------------------------------------
def shell(cmd, exit_code=0):
    return {"tool": "shell.exec", "ok": exit_code == 0, "exit_code": exit_code,
            "args": json.dumps({"command": cmd})}


def write(path="a.py"):
    return {"tool": "fs.write", "ok": True, "exit_code": 0,
            "args": json.dumps({"path": path})}


stop = ST.analyze([write(), shell("pytest -q"), shell("pytest -q"),
                   {"tool": "fs.read", "ok": True, "exit_code": 0, "args": "{}"}])
check("two passes on the same patch give stop-now",
      stop["verdict"] == "stop-now" and stop["repeat_pass"] is True, stop)
check("the saving counts the steps after the last pass",
      stop["saving_steps"] == 1, stop["saving_steps"])
check("the rule is named", "passes the test command twice" in stop["rule"])

changed = ST.analyze([write(), shell("pytest -q"), write(), shell("pytest -q")])
check("a write between passes makes it a different patch",
      changed["repeat_pass"] is False
      and changed["verdict"] == "verify-again-before-stopping", changed)
check("no verification is reported, not guessed",
      ST.analyze([write()])["verdict"] == "no-verification")
check("a failing test is not a pass",
      ST.analyze([shell("pytest -q", 1), shell("pytest -q", 1)])["verdict"]
      == "no-verification")
check("post-pass work is measured from the first pass",
      ST.analyze([write(), shell("pytest -q"), {"tool": "fs.read", "ok": True,
                                                "exit_code": 0, "args": "{}"},
                  {"tool": "fs.read", "ok": True, "exit_code": 0, "args": "{}"}]
                 )["post_pass_steps"] == 2)

print("\n%d/%d checks passed" % (sum(RESULTS), len(RESULTS)))
sys.exit(0 if all(RESULTS) else 1)
