#!/usr/bin/env python3
"""v1120 — a non-zero exit with no error text is explained, not left opaque.

Round 54. The register's largest row after round 53 is `shell.exec ·
nonzero-exit` — ONE class, `exit=<n> (no error text)`, 15 events in 11
sessions. Reading the commands behind it showed what they are: compound
lookups (`grep … | head`, `which pylint`, `ls -la notes 2>/dev/null`) whose LAST
verb exits non-zero to say "not there". The model got its answer; the harness
filed a failure and the observation said only `exit=1`.

The remedy is not to stop counting (the harness cannot know intent) but to NAME
the convention where the model reads it: a lookup that found nothing exits
non-zero on purpose, and a silent non-zero exit needs `2>&1` to explain itself.

  A  output + a non-zero exit + no error text → the "answer, not a fault" hint
  B  no output at all → the silent-exit hint (`2>&1`)
  C  never on a success
  D  never when the tool already said something (error / stderr / hint)
  E  a zero exit is not this case
  F  the timeout, heredoc and dialect hints keep precedence

Deterministic: `_shell` is stubbed; no process, no network, no model.
Run: python3 tests/acceptance/v1120_status_hint.py
"""
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_tmp = tempfile.mkdtemp(prefix="sf-1120-")
os.environ["LONGRUN_CONFIG_DIR"] = os.path.join(_tmp, "cfg")
os.makedirs(os.environ["LONGRUN_CONFIG_DIR"], exist_ok=True)
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.tools import tools as T  # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name
          + ((" :: " + str(detail)[:300]) if detail and not ok else ""))


_real = T._shell


def stub(result):
    T._shell = lambda args, run_id=None: dict(result)


try:
    # A — a lookup that found nothing.
    stub({"ok": False, "exit_code": 1, "stdout": "0\n", "stderr": ""})
    r = T._shell_hinted({"command": "grep -c -i font web/index.html"}, "v1120")
    hint = r.get("hint") or ""
    check("A1 the output-bearing exit names the convention",
          "grep" in hint and "answer" in hint.lower() and "output" in hint, hint)
    check("A2 it says when to correct the command",
          "only if the output is wrong" in hint, hint)
    check("A3 the raw failure is preserved beside the hint",
          r.get("ok") is False and r.get("exit_code") == 1, r)

    # B — a silent non-zero exit.
    stub({"ok": False, "exit_code": 2, "stdout": "", "stderr": ""})
    r = T._shell_hinted({"command": "which pylint"}, "v1120")
    hint = r.get("hint") or ""
    check("B1 a silent exit says it printed nothing", "printed nothing" in hint, hint)
    check("B2 and how to get the reason (`2>&1`)", "2>&1" in hint, hint)

    # C — never on a success.
    stub({"ok": True, "exit_code": 0, "stdout": "x", "stderr": ""})
    check("C1 a success carries no hint",
          "hint" not in T._shell_hinted({"command": "ls"}, "v1120"), "")

    # D — an existing explanation wins.
    stub({"ok": False, "exit_code": 1, "stdout": "0\n", "stderr": "boom"})
    check("D1 a real stderr suppresses the status hint",
          "hint" not in T._shell_hinted({"command": "make"}, "v1120"), "")
    stub({"ok": False, "exit_code": 1, "stdout": "", "error": "policy denied"})
    check("D2 a tool error suppresses the status hint",
          "hint" not in T._shell_hinted({"command": "make"}, "v1120"), "")
    stub({"ok": False, "exit_code": 1, "stdout": "x", "hint": "explained"})
    check("D3 an existing hint is never replaced",
          T._shell_hinted({"command": "ls"}, "v1120").get("hint") == "explained", "")

    # E — a zero exit is not a non-zero exit.
    stub({"ok": False, "exit_code": 0, "stdout": "x", "stderr": ""})
    check("E1 exit 0 is not this case",
          "hint" not in T._shell_hinted({"command": "ls"}, "v1120"), "")

    # F — the earlier hints still win.
    stub({"ok": False, "exit_code": 1, "stdout": "x", "stderr": "",
          "timed_out": True})
    check("F1 a timeout keeps its hint (background + status)",
          "background" in (T._shell_hinted({"command": "sleep 9"}, "v1120")
                           .get("hint") or ""), "")
    stub({"ok": False, "exit_code": 1, "stdout": "x", "stderr": ""})
    check("F2 a heredoc keeps its hint (write the FILE)",
          "fs.write" in (T._shell_hinted(
              {"command": "python3 - <<'PY'\nprint(1)\nPY"}, "v1120").get("hint") or ""), "")
    stub({"ok": False, "exit_code": 2, "stdout": "",
          "stderr": "/bin/sh: 1: set: Illegal option -o pipefail"})
    check("F3 the dialect hint keeps precedence",
          "sh/dash" in (T._shell_hinted(
              {"command": "set -o pipefail"}, "v1120").get("hint") or ""), "")
finally:
    T._shell = _real

print("\n---\nv1120: %d/%d PASS" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
