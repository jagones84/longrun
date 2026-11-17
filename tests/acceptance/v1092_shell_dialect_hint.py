#!/usr/bin/env python3
"""v1092 — a failure caused by the WRONG shell dialect names the dialect.

Round 23. The failure register (round 21) ranked the classes and showed two
shell-dialect confusions: 6 commands a Windows shell could not recognize
(`ls`, `Get-Item`) and 4 that died on `set: Illegal option -o pipefail` (an
`sh`/`dash` shell, not bash). The model retried the same shape, because the
observation never said which shell had answered.

  A  the Windows message → a hint naming the host syntax and the escape hatch
  B  the pipefail message → a hint saying the shell is not bash
  C  any other failure comes back byte-identical (no invented hint)
  D  a SUCCESS never carries a hint, even when the text appears in stdout
  E  the heredoc rule keeps precedence, and an existing hint is never replaced

Deterministic: `_shell` is stubbed; no process, no network, no model.
Run: python3 tests/acceptance/v1092_shell_dialect_hint.py
"""
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_tmp = tempfile.mkdtemp(prefix="sf-1092-")
os.environ["LONGRUN_CONFIG_DIR"] = os.path.join(_tmp, "cfg")
os.makedirs(os.environ["LONGRUN_CONFIG_DIR"], exist_ok=True)
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.tools import tools as T  # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name
          + ((" :: " + str(detail)[:300]) if detail and not ok else ""))


WIN = ('"ls" non è riconosciuto come comando interno o esterno, un programma '
       'eseguibile o un file batch.')
PIPE = "/bin/sh: 1: set: Illegal option -o pipefail"

_real = T._shell


def stub(result):
    T._shell = lambda args, run_id=None: dict(result)


try:
    stub({"ok": False, "exit_code": 1, "stdout": "", "stderr": WIN})
    r = T._shell_hinted({"command": "ls -la"}, "v1092")
    hint = r.get("hint") or ""
    check("A1 the Windows message yields a dialect hint",
          "Windows syntax" in hint and "Get-ChildItem" in hint, hint)
    check("A2 the hint offers the escape hatch without promising bash",
          "bash -lc" in hint and "only if bash exists" in hint, hint)
    check("A3 the raw failure is preserved beside the hint",
          r.get("ok") is False and r.get("stderr") == WIN, r)

    stub({"ok": False, "exit_code": 2, "stdout": "", "stderr": PIPE})
    r = T._shell_hinted({"command": "set -o pipefail && make"}, "v1092")
    hint = r.get("hint") or ""
    check("B1 the pipefail message names the shell it really was",
          "sh/dash" in hint and "not bash" in hint, hint)
    check("B2 it says what to change (drop it, or call bash)",
          "drop `set -o pipefail`" in hint, hint)

    stub({"ok": False, "exit_code": 127, "stdout": "",
          "stderr": "bash: foo: command not found"})
    r = T._shell_hinted({"command": "foo"}, "v1092")
    check("C1 an unrelated failure carries NO hint and is unchanged",
          r == {"ok": False, "exit_code": 127, "stdout": "",
                "stderr": "bash: foo: command not found"}, r)

    stub({"ok": True, "exit_code": 0,
          "stdout": "grep hit: " + WIN, "stderr": ""})
    r = T._shell_hinted({"command": "grep -r ok ."}, "v1092")
    check("D1 a success never carries a hint, even when the text appears",
          "hint" not in r, r)

    stub({"ok": False, "exit_code": 1, "stdout": WIN, "stderr": ""})
    r = T._shell_hinted({"command": "python3 - <<'PY'\nprint(1)\nPY"}, "v1092")
    check("E1 the heredoc rule keeps precedence (FILE route, not dialect)",
          "fs.write" in (r.get("hint") or ""), r.get("hint"))

    stub({"ok": False, "exit_code": 1, "stdout": WIN, "stderr": "",
          "hint": "explained by the tool"})
    r = T._shell_hinted({"command": "ls"}, "v1092")
    check("E2 an existing hint is never replaced", r.get("hint") == "explained by the tool",
          r.get("hint"))
finally:
    T._shell = _real

print("\n---\nv1092: %d/%d PASS" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
