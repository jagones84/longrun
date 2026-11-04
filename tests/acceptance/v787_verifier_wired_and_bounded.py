#!/usr/bin/env python3
"""v787 — the verifier is WIRED to the project, and a red close is bounded.

The instruments already existed but were unplugged: `verifier.command` shipped
empty, so "apply-only-if-green" proved nothing. This pins the wiring and the
bound:

  A  `resolve_command` honours a literal command, and `"auto"` resolves the
     project's own suite from its markers (pytest -> package.json -> Makefile)
  B  no marker = NO command = a SKIP, never a rolled-back edit; per-edit
     verification stays opt-in (an empty command is not "auto")
  C  closeout auto-resolves even with an empty command (the cheap path: one
     suite run per closed step, not per write)
  D  one red check earns ONE repair round: a second `done` with no new mutation
     is refused WITHOUT paying for the suite again; a real mutation re-runs it

Deterministic: temp dirs, the check is injected (no sandbox, no network).
Run: python3 tests/acceptance/v787_verifier_wired_and_bounded.py
"""
import json
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_tmp = tempfile.mkdtemp(prefix="sf-787-")
os.environ["LONGRUN_CONFIG_DIR"] = os.path.join(_tmp, "cfg")
os.makedirs(os.environ["LONGRUN_CONFIG_DIR"], exist_ok=True)

sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.plan import verify  # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name
          + ((" :: " + str(detail)[:300]) if detail and not ok else ""))


def workspace(name, files=None):
    ws = os.path.join(_tmp, name)
    os.makedirs(ws, exist_ok=True)
    for base, text in (files or {}).items():
        path = os.path.join(ws, base)
        os.makedirs(os.path.dirname(path), exist_ok=True) if os.path.dirname(path) else None
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
    return ws


ws_pytest = workspace("pytest", {"pytest.ini": "[pytest]\n"})
ws_npm = workspace("npm", {"package.json": json.dumps({"scripts": {"test": "echo ok"}})})
ws_make = workspace("make", {"Makefile": "test:\n\techo ok\n"})
ws_none = workspace("empty")
ws_tests_dir = workspace("testsdir", {"tests/test_a.py": "def test_a():\n    assert 1\n"})

# ------------------------------------------- A: the project names its suite --
check("A1 a literal command always wins",
      verify.resolve_command(ws_pytest, {"command": "make check"}) == "make check")
check("A2 pytest.ini -> pytest",
      verify.resolve_command(ws_pytest, {"command": "auto"}) == verify.PYTEST_COMMAND,
      verify.resolve_command(ws_pytest, {"command": "auto"}))
check("A3 a tests/ directory is a pytest marker",
      verify.resolve_command(ws_tests_dir, {"command": "auto"}) == verify.PYTEST_COMMAND,
      verify.resolve_command(ws_tests_dir, {"command": "auto"}))
check("A4 package.json with a test script -> npm test",
      verify.resolve_command(ws_npm, {"command": "auto"}) == "npm test",
      verify.resolve_command(ws_npm, {"command": "auto"}))
check("A5 a Makefile test target -> make test",
      verify.resolve_command(ws_make, {"command": "auto"}) == "make test",
      verify.resolve_command(ws_make, {"command": "auto"}))
check("A6 pytest wins over the other markers",
      verify.resolve_command(workspace("both", {"pyproject.toml": "[project]\n",
                                               "package.json": '{"scripts":{"test":"x"}}'}),
                             {"command": "auto"}) == verify.PYTEST_COMMAND)

# -------------------------------- B: no marker is a skip, not a failed edit --
check("B1 no marker resolves to no command",
      verify.resolve_command(ws_none, {"command": "auto"}) == "")
check("B2 an empty command never auto-resolves per edit",
      verify.resolve_command(ws_pytest, {"command": ""}) == "")
ok, out = verify.run_check(ws_pytest, {"command": "", "timeout_secs": 1})
check("B3 an empty command is a green skip", ok is True and out == "", (ok, out))
ok, out = verify.run_check(ws_none, {"command": "auto", "timeout_secs": 1})
check("B4 auto with no marker is a green skip, never a rollback",
      ok is True and "skipped" in out, (ok, out))
check("B5 per-edit verification stays OFF while the command is empty",
      verify.should_verify("fs.write", os.path.join(ws_pytest, "a.py"),
                           {"enabled": True, "command": "", "paths": []}) is False)

# --------------------------- C: closeout resolves "auto" by itself -----------
check("C1 closeout resolves an empty command (auto_when_empty)",
      verify.resolve_command(ws_pytest, {"command": ""}, auto_when_empty=True)
      == verify.PYTEST_COMMAND)

# ------------------------------------ D: one red, one repair, then bounded ---
verify.reset_closeout_memo()
calls = []


def red(workspace=None, c=None, run_id=None):
    calls.append(os.path.basename(str(workspace)))
    return False, "boom: 1 failed"


node = {"id": "n1", "mutated": 11}
c = {"closeout": True, "command": "auto", "timeout_secs": 1}

ok, rep, obs = verify.closeout_gate(node, workspace=ws_pytest, c=c, check=red)
check("D1 the first red keeps the step open with the output",
      ok is False and rep.get("ran") is True and "boom" in rep.get("output", "") and obs is False,
      rep)
check("D2 it is attempt 1 and the suite ran once",
      rep.get("attempts") == 1 and len(calls) == 1, (rep, calls))

ok, rep, obs = verify.closeout_gate(node, workspace=ws_pytest, c=c, check=red)
check("D3 a second claim with NO new mutation is refused",
      ok is False and rep.get("skipped") == "unchanged_since_failure", rep)
check("D4 and it does NOT pay for the suite again", len(calls) == 1, calls)

node["mutated"] = 12
ok, rep, obs = verify.closeout_gate(node, workspace=ws_pytest, c=c, check=red)
check("D5 a real mutation earns the repair round",
      ok is False and rep.get("attempts") == 2 and len(calls) == 2, (rep, calls))

node2 = {"id": "n2", "mutated": 1}
ok, rep, obs = verify.closeout_gate(node2, workspace=ws_pytest, c=c,
                                    check=lambda workspace=None, c=None, run_id=None: (True, "ok"))
check("D6 a green close is observed evidence", ok is True and obs is True, rep)

node3 = {"id": "n3", "mutated": 1}
ok, rep, obs = verify.closeout_gate(node3, workspace=ws_none, c=c, check=red)
check("D7 closeout with no resolvable command refuses instead of pretending",
      ok is False and rep.get("ran") is False and "no test command" in rep.get("error", ""), rep)

print("\n---\nv787: %d/%d PASS" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
