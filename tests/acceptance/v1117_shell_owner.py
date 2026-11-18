#!/usr/bin/env python3
"""v1117 — ONE owner for "which shell runs a command on this host".

Round 51. Measured 2026-11-18 from the failure register + the run records: the
SAME harness answered that question twice and differently.

  * `term._shell_argv()` (the session terminal, and `shell.exec` when the sandbox
    backend is `none`) preferred `$SHELL` / `/bin/bash`;
  * `osutil.shell_argv()` (host execution inside a harness run, and hooks) always
    spawned `/bin/sh` — dash on this host.

So a command that had already worked in the terminal died in a run as
`/bin/sh: 1: set: Illegal option -o pipefail` (3 cards in the live register, 2
more in the run record `caef726a6faa`), and the round-23 hint could only explain
the failure AFTER the model had written it. The harness now picks ONE shell, the
terminal's precedence (override, `$SHELL`, bash, sh), for both callers.

  A  the precedence: override wins, then `$SHELL`, then an executable fallback
  B  `shell_argv` spawns THAT shell with `-c` (Windows keeps `COMSPEC /c`)
  C  `term._shell_argv()` and `osutil.shell_path()` are the same answer
  D  the selected shell really runs `set -o pipefail` (a live spawn), while
    `/bin/sh` does not — the distinction is real on this host
  E  a source pin: term no longer carries a second precedence list

Deterministic: temp dirs only; the one spawn runs `echo`/`set` on the host shell.
Run: python3 tests/acceptance/v1117_shell_owner.py
"""
import os
import stat
import subprocess
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_tmp = tempfile.mkdtemp(prefix="sf-1117-")
os.environ["LONGRUN_CONFIG_DIR"] = os.path.join(_tmp, "cfg")
os.makedirs(os.environ["LONGRUN_CONFIG_DIR"], exist_ok=True)
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.util import osutil  # noqa: E402
from longrun.tools import term  # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name
          + ((" :: " + str(detail)[:300]) if detail and not ok else ""))


def fake_shell(name):
    """An executable file that is not a real shell: only the selection is tested."""
    path = os.path.join(_tmp, name)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("#!/bin/sh\nexit 0\n")
    os.chmod(path, os.stat(path).st_mode | stat.S_IXUSR)
    return path


_orig_env = {k: os.environ.get(k) for k in ("SHELL", "LONGRUN_TERM_SHELL", "COMSPEC")}


def set_env(**kw):
    for key, value in kw.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value


try:
    over = fake_shell("override-shell")
    user = fake_shell("user-shell")

    # A — the precedence, one answer for both callers.
    set_env(SHELL=user, LONGRUN_TERM_SHELL=over)
    check("A1 LONGRUN_TERM_SHELL wins over $SHELL",
          osutil.shell_path() == over, osutil.shell_path())
    check("A2 term agrees with osutil under the same override",
          term._shell_argv() == [over], term._shell_argv())
    set_env(LONGRUN_TERM_SHELL=None)
    check("A3 without the override $SHELL wins", osutil.shell_path() == user,
          osutil.shell_path())
    set_env(SHELL=None)
    pick = osutil.shell_path()
    check("A4 the fallback is an existing executable",
          os.path.isfile(pick) and os.access(pick, os.X_OK), pick)
    check("A5 the fallback prefers bash when the host has it",
          pick == "/bin/bash" if os.access("/bin/bash", os.X_OK) else pick == "/bin/sh",
          pick)

    # B — the argv really carries the chosen shell.
    set_env(LONGRUN_TERM_SHELL=over)
    check("B1 shell_argv uses the selected shell with -c",
          osutil.shell_argv("echo hi") == [over, "-c", "echo hi"],
          osutil.shell_argv("echo hi"))
    set_env(COMSPEC=r"C:\Windows\cmd.exe")
    check("B2 Windows keeps COMSPEC with /c",
          osutil.shell_argv("dir", on_windows=True)
          == [r"C:\Windows\cmd.exe", "/c", "dir"],
          osutil.shell_argv("dir", on_windows=True))
    check("B3 an explicit POSIX flag ignores COMSPEC",
          osutil.shell_argv("ls", on_windows=False) == [over, "-c", "ls"],
          osutil.shell_argv("ls", on_windows=False))

    # C — the terminal's argv IS the osutil answer (no second list).
    set_env(LONGRUN_TERM_SHELL=None, SHELL=user)
    check("C1 term consumes osutil.shell_path()", term._shell_argv() == [user],
          term._shell_argv())

    # D — the distinction is real: bash runs pipefail, /bin/sh does not.
    set_env(LONGRUN_TERM_SHELL=None, SHELL=None)
    pick = osutil.shell_path()
    got = subprocess.run(osutil.shell_argv("set -o pipefail && echo ok"),
                         capture_output=True, text=True)
    bash_like = "bash" in os.path.basename(pick)
    check("D1 the selected shell runs `set -o pipefail`"
          if bash_like else "D1 (this host has no bash: the sh fallback is honest)",
          (got.returncode == 0 and "ok" in got.stdout) if bash_like else True,
          "%s rc=%s err=%s" % (pick, got.returncode, got.stderr[:120]))
    sh = subprocess.run(["/bin/sh", "-c", "set -o pipefail && echo ok"],
                        capture_output=True, text=True)
    check("D2 /bin/sh rejects it on this host (the old path's failure)",
          sh.returncode != 0 and "Illegal option" in (sh.stderr or ""),
          "rc=%s err=%s" % (sh.returncode, sh.stderr[:120]))
    check("D3 the harness no longer chooses that shell",
          os.path.basename(pick) != "sh", pick)

    # E — the one-owner pin survives a future edit.
    with open(os.path.join(REPO, "src", "longrun", "tools", "term.py"),
              encoding="utf-8") as fh:
        TERM = fh.read()
    check("E1 term has no second shell-precedence list",
          'for cand in (os.environ.get("SHELL"), "/bin/bash", "/bin/sh")' not in TERM,
          "the old list is back in term._shell_argv")
    check("E2 term asks osutil for the POSIX shell",
          "osutil.shell_path()" in TERM, "term does not call osutil.shell_path")
finally:
    for key, value in _orig_env.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value

print("\n---\nv1117: %d/%d PASS" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
