#!/usr/bin/env python3
"""v1123 — a reset terminal says what the reset cost, and where the next shell starts.

Round 57. The register carries 8 `shell.exec` cards that died with
`timeout — the terminal was reset` (exit 124). Two shapes live behind that text:

  1. the child was interrupted and the shell SURVIVED
     (`timeout — hung child interrupted, shell preserved`);
  2. the shell itself was stuck, so `term.reset()` KILLED it and the NEXT call
     spawns a fresh one.

The round-25 hint covered (1) and said "was interrupted". For (2) that is wrong
twice: the `cd`/exports/background jobs of the session are gone (the next command
starts in the workspace root), and the killed command's effect is unknown — it
may have finished (`ssh … && echo sent` printed the marker), been cut halfway
(a `pip install`), or never started. The observation also reported `workspace`
from the DEAD shell object, i.e. the directory the next command will NOT be in.

  A  a reset timeout gets the reset hint (state lost, effect unknown, verify)
  B  an interrupted timeout keeps the older sentence and does not claim a reset
  C  a timed-out heredoc still reports the timeout, not the quoting problem
  D  an existing hint is never replaced
  E  `_shell` carries `reset`, and `workspace` is where the next shell starts
  F  a normal run still reports the shell's own cwd
  G  `term.run_capture` marks the reset branch (the one bit the hint branches on)

Deterministic: `_shell` is stubbed for A-D; E/F stub only the terminal. G builds
a real shell whose completion event is faked, so nothing runs and nothing waits.
Run: python3 tests/acceptance/v1123_terminal_reset_hint.py
"""
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_tmp = tempfile.mkdtemp(prefix="sf-1123-")
os.environ["LONGRUN_CONFIG_DIR"] = os.path.join(_tmp, "cfg")
os.makedirs(os.environ["LONGRUN_CONFIG_DIR"], exist_ok=True)
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.tools import term  # noqa: E402
from longrun.tools import tools as T  # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name
          + ((" :: " + str(detail)[:300]) if detail and not ok else ""))


_real_shell = T._shell
_real_terminal = T._shell_terminal


def stub(result):
    T._shell = lambda args, run_id=None: dict(result)


RESET = {"ok": False, "exit_code": 124, "stdout": "shutdown-command-sent\n",
         "timed_out": True, "reset": True,
         "error": "timeout — the terminal was reset"}
INTERRUPTED = {"ok": False, "exit_code": 124, "stdout": "step 1\nstep 2\n",
               "timed_out": True, "interrupted": True,
               "error": "timeout — hung child interrupted, shell preserved"}

try:
    # A — the reset branch says what was lost and that the effect is unknown.
    stub(RESET)
    r = T._shell_hinted({"command": "ssh win 'shutdown /s /t 0'", "timeout_secs": 120},
                        "v1123")
    hint = r.get("hint") or ""
    check("A1 the hint says the terminal was RESET", "RESET" in hint, hint)
    check("A2 it names the lost state (cd / exports / background jobs)",
          "`cd`" in hint and "export" in hint and "background job" in hint, hint)
    check("A3 and where the next command starts (the workspace root)",
          "workspace root" in hint, hint)
    check("A4 it says the killed command's effect is UNKNOWN", "UNKNOWN" in hint, hint)
    check("A5 it asks for a read before assuming it ran",
          "Verify with a read" in hint, hint)
    check("A6 the longer route is still there", "background: true" in hint, hint)
    check("A7 the raw failure is preserved (exit 124, timed_out, reset)",
          r.get("exit_code") == 124 and r.get("timed_out") is True
          and r.get("reset") is True, r)

    # B — an interrupted (shell preserved) timeout keeps the older sentence.
    stub(dict(INTERRUPTED))
    r = T._shell_hinted({"command": "make -j8", "timeout_secs": 60}, "v1123")
    hint = r.get("hint") or ""
    check("B1 the preserved shell is not reported as reset",
          "was interrupted" in hint and "RESET" not in hint, hint)
    check("B2 and it still names the partial output", "partial output above" in hint, hint)

    # C — a timed-out heredoc is a timeout, not a quoting problem.
    stub(dict(RESET))
    r = T._shell_hinted({"command": "python3 - <<'PY'\nprint(1)\nPY",
                         "timeout_secs": 5}, "v1123")
    check("C1 the heredoc route does not win over the reset",
          "RESET" in (r.get("hint") or "") and "fs.write" not in (r.get("hint") or ""),
          r.get("hint"))

    # D — an existing hint is never replaced.
    stub(dict(RESET, hint="set by the tool"))
    r = T._shell_hinted({"command": "sleep 9"}, "v1123")
    check("D1 an existing hint is never replaced", r.get("hint") == "set by the tool",
          r.get("hint"))
finally:
    T._shell = _real_shell


# ---------------------------------------------------------------- E/F/G ----
class _FakeShell:
    """A dead shell: its `.cwd` is where it USED to be."""

    cwd = os.path.join(_tmp, "deep", "subdir")

    def __init__(self, payload):
        self.payload = payload

    def run_capture(self, command, timeout=None, origin=None, cwd=None, on_output=None):
        return dict(self.payload)


work = os.path.join(_tmp, "work")
os.makedirs(work, exist_ok=True)

try:
    T._shell_terminal = lambda sid, cwd: _FakeShell(RESET)
    r = T._shell({"command": "echo x", "workspace": work}, "v1123")
    check("E1 `_shell` carries `reset` through", r.get("reset") is True, r)
    check("E2 `workspace` is where the NEXT shell starts, not the dead shell's cwd",
          r.get("workspace") == work, r.get("workspace"))
    check("E3 the error text is unchanged", "terminal was reset" in str(r.get("error")),
          r.get("error"))

    T._shell_terminal = lambda sid, cwd: _FakeShell({"ok": True, "exit_code": 0,
                                                     "stdout": "ok\n"})
    r = T._shell({"command": "echo x", "workspace": work}, "v1123")
    check("F1 a normal run reports the shell's own cwd",
          r.get("workspace") == _FakeShell.cwd and not r.get("reset"), r.get("workspace"))
finally:
    T._shell_terminal = _real_terminal

# G — the reset branch is the only place that sets `reset`.
sh = term.Shell("v1123-reset")
_orig_int, _orig_kill = term._interrupt_child, term._kill_children
try:
    term._interrupt_child = lambda s: True
    term._kill_children = lambda s: True
    sh._done.wait = lambda timeout=None: False      # never completes, never waits
    r = sh.run_capture("echo x", timeout=1)
    check("G1 a stuck shell returns the reset flag", r.get("reset") is True, r)
    check("G2 and it still says what happened", "terminal was reset" in str(r.get("error")),
          r.get("error"))
    check("G3 and it is still a timeout", r.get("timed_out") is True
          and r.get("exit_code") == 124, r)
finally:
    term._interrupt_child, term._kill_children = _orig_int, _orig_kill
    try:
        sh.kill()
    except Exception:  # noqa: BLE001 — cleanup must not fail the test
        pass

print("\n---\nv1123: %d/%d PASS" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
