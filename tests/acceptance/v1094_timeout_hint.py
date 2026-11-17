#!/usr/bin/env python3
"""v1094 — a timed-out command teaches the longer route instead of repeating.

Round 25. The register, after four rounds of cleanup, still shows
`shell.exec · timeout` = **10 failures in 6 sessions**: the call was killed at
`timeout_secs`, the terminal reset, and the model retried the same command. The
observation carried `timed_out: true` and the partial output and nothing else.

  A  a timed-out call carries the `background: true` + `action=status` hint
  B  the hint says the partial output above is real (it is not lost)
  C  the ROOT CAUSE wins: a timed-out heredoc is a timeout, not a quoting problem
  D  a non-timeout failure gets no timeout hint
  E  the heredoc and dialect rules still work, and an existing hint is preserved
  F  the register's own `timeout` remedy says the same thing (one truth)

Deterministic: `_shell` is stubbed; no process, no network, no model.
Run: python3 tests/acceptance/v1094_timeout_hint.py
"""
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_tmp = tempfile.mkdtemp(prefix="sf-1094-")
os.environ["LONGRUN_CONFIG_DIR"] = os.path.join(_tmp, "cfg")
os.makedirs(os.environ["LONGRUN_CONFIG_DIR"], exist_ok=True)
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.tools import tools as T  # noqa: E402
from longrun.util import selfevolve  # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name
          + ((" :: " + str(detail)[:300]) if detail and not ok else ""))


_real = T._shell


def stub(result):
    T._shell = lambda args, run_id=None: dict(result)


TIMEOUT = {"ok": False, "exit_code": 124, "stdout": "step 1 done\nstep 2 …",
           "timed_out": True, "error": "timeout — the terminal was reset"}

try:
    stub(TIMEOUT)
    r = T._shell_hinted({"command": "make -j8", "timeout_secs": 60}, "v1094")
    hint = r.get("hint") or ""
    check("A1 the timed-out call names `background: true`", "background: true" in hint, hint)
    check("A2 and the poll it must use (`action=status` with the job id)",
          'action:"status"' in hint and 'job:"<id>"' in hint, hint)
    check("B1 it says the partial output above is real",
          "partial output above" in hint, hint)
    check("B2 the raw result is preserved (exit 124, stdout, timed_out)",
          r.get("exit_code") == 124 and r.get("timed_out") is True
          and r.get("stdout", "").startswith("step 1 done"), r)

    stub(dict(TIMEOUT))
    r = T._shell_hinted({"command": "python3 - <<'PY'\nprint(1)\nPY",
                         "timeout_secs": 5}, "v1094")
    check("C1 a timed-out heredoc is a TIMEOUT (root cause first), not a quoting bug",
          "background: true" in (r.get("hint") or "")
          and "fs.write" not in (r.get("hint") or ""), r.get("hint"))

    stub({"ok": False, "exit_code": 127, "stdout": "",
          "stderr": "bash: foo: command not found"})
    r = T._shell_hinted({"command": "foo"}, "v1094")
    check("D1 a plain failure gets NO timeout hint", "hint" not in r, r)

    stub({"ok": False, "exit_code": 1, "stdout": "",
          "stderr": 'bash: ls: command not found'})
    r = T._shell_hinted({"command": "python3 - <<'PY'\nprint(1)\nPY"}, "v1094")
    check("E1 the heredoc rule still fires when the call did not time out",
          "fs.write" in (r.get("hint") or ""), r.get("hint"))

    stub({"ok": False, "exit_code": 2, "stdout": "",
          "stderr": "/bin/sh: 1: set: Illegal option -o pipefail"})
    r = T._shell_hinted({"command": "sh -c 'set -o pipefail'"}, "v1094")
    check("E2 the dialect rule still fires", "not bash" in (r.get("hint") or ""),
          r.get("hint"))

    stub(dict(TIMEOUT, hint="set by the tool"))
    r = T._shell_hinted({"command": "sleep 9"}, "v1094")
    check("E3 an existing hint is never replaced", r.get("hint") == "set by the tool",
          r.get("hint"))

    stub({"ok": True, "exit_code": 0, "stdout": "fine", "stderr": ""})
    r = T._shell_hinted({"command": "echo fine"}, "v1094")
    check("E4 a success carries no hint", "hint" not in r, r)
finally:
    T._shell = _real

action = selfevolve.FAMILY_FIX["timeout"][0]
check("F1 the register's timeout remedy names the same two moves (one truth)",
      "background=true" in action and "action=status" in action, action)

print("\n---\nv1094: %d/%d PASS" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
