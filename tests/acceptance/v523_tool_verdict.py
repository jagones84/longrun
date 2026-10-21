#!/usr/bin/env python3
"""v523 — deterministic tool verdict: exit codes + observation evidence.

The harness is not an LLM: its verdict channel must carry a stable, generic
meaning. This locks the exit-code table and the observation renderer:

  0 success · 1 semantic failure · 64 usage · 124 timeout
  125 sandbox exec error only · 126 blocked · 127 unknown/no implementation

Deterministic, no model, no network. Run: python3 tests/acceptance/v523_tool_verdict.py
"""
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="sf-v523-")
for name, tail in {
    "LONGRUN_DATA_DIR": "data",
    "LONGRUN_CONFIG_DIR": "cfg",
    "LONGRUN_DB": "events.db",
    "LONGRUN_SESSIONS_DIR": "sessions",
    "LONGRUN_GRAPH_DIR": "graphs",
    "LONGRUN_EDITS_DIR": "edits",
    "LONGRUN_RUNS_DIR": "runs",
    "LONGRUN_MATRIX_SRC": "matrix_src",
    "LONGRUN_MATRIX_DOT": "matrix_dot",
    "LONGRUN_APPROVALS": "approvals.json",
}.items():
    os.environ[name] = os.path.join(TMP, tail)
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.model import decision  # noqa: E402
from longrun.tools import tools as T  # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name
          + ((" :: " + str(detail)) if detail else ""))


def run(tool, args):
    return T._dispatch_execute(tool, args, run_id="v523")


# ------------------------------------------------ semantic failures use 1 ----
verify = run("matrix.verify_target", {"kind": "tool", "name": "does_not_exist"})
check("matrix.verify_target semantic failure is exit 1, not sandbox 125",
      verify.get("ok") is False and verify.get("exit_code") == 1,
      {"ok": verify.get("ok"), "exit_code": verify.get("exit_code")})
verify_obs = T.observation(verify)
check("its observation states the verdict and the reason",
      "exit=1" in verify_obs and "ok=False" in verify_obs
      and "ERROR:" in verify_obs and "Matrix artifact not found" in verify_obs,
      verify_obs)

missing = run("fs.read", {"path": "definitely_missing_v523.txt"})
check("a missing file is a semantic failure (exit 1)",
      missing.get("ok") is False and missing.get("exit_code") == 1,
      {"ok": missing.get("ok"), "exit_code": missing.get("exit_code"),
       "error": missing.get("error")})

unknown = run("notatool.run", {})
check("an unimplemented tool is exit 127, not a sandbox failure",
      unknown.get("ok") is False and unknown.get("exit_code") == 127,
      {"ok": unknown.get("ok"), "exit_code": unknown.get("exit_code"),
       "error": unknown.get("error")})
check("the unimplemented-tool observation exposes exit 127",
      "exit=127" in T.observation(unknown) and "ok=False" in T.observation(unknown),
      T.observation(unknown))

# ------------------------------------------- structured evidence survives ----
structured = T.observation({
    "tool": "matrix.test", "ok": False, "exit_code": 1,
    "error": "PROMOTE_UNVERIFIED: test did not pass",
    "kind": "tool", "name": "probe", "path": "/x/probe.py",
    "line": 42, "code_line": "assert r['ok']", "sha256": "deadbeef",
})
check("an error observation keeps kind/name/path/line/sha256",
      all(value in structured for value in
          ("kind", "tool", "probe", "/x/probe.py", "42",
           "assert r['ok']", "deadbeef")),
      structured)

partial = T.observation({
    "tool": "python.run", "ok": False, "exit_code": 1,
    "error": "NameError: name 'x' is not defined",
    "stdout": "partial output before the crash",
    "stderr": "Traceback (most recent call last)",
})
check("a failed run still shows partial stdout and stderr",
      "partial output before the crash" in partial
      and "Traceback" in partial
      and "NameError" in partial,
      partial)

# ------------------------------------------------ success verdict is explicit ----
success = T.observation({
    "tool": "toolcontract.audit", "ok": True, "exit_code": 0,
    "backend": "matrix", "sandboxed": False,
    "scope": "matrix", "total": 91, "collisions": 11,
})
check("a successful observation states ok explicitly",
      "exit=0" in success and "ok=True" in success, success)
check("a successful observation keeps its structured payload",
      '"total": 91' in success and '"collisions": 11' in success, success)

# ------------------------------------------- blocked is 126, not "not found" ----
_old_pre = decision.pre_tool
decision.pre_tool = lambda tool, args: {"ok": False, "reason": "v523 probe block"}
try:
    blocked = T.execute("shell.exec", {"command": "printf never"})
finally:
    decision.pre_tool = _old_pre
check("a policy block is 126 (blocked), not 127 (unknown)",
      blocked.get("ok") is False and blocked.get("exit_code") == 126
      and blocked.get("decision_blocked") is True,
      {"ok": blocked.get("ok"), "exit_code": blocked.get("exit_code"),
       "error": blocked.get("error")})

# ------------------------------------------- every probed path has an exit ----
for tool, args in (("matrix.verify_target", {"kind": "tool", "name": "x"}),
                   ("fs.read", {"path": "definitely_missing_v523.txt"}),
                   ("notatool.run", {})):
    result = run(tool, args)
    check("every dispatch path returns an integer exit code (%s)" % tool,
          isinstance(result.get("exit_code"), int), result.get("exit_code"))

print("---")
passed = sum(results)
print("\nv523: %d/%d PASS" % (passed, len(results)))
sys.exit(0 if passed == len(results) else 1)
