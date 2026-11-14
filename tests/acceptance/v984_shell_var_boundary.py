#!/usr/bin/env python3
"""v984 — a shell variable cannot hide a path from the workspace boundary.

`touches_outside` scanned the command for words starting with `/`, `~`, `./`,
`../` or following `cd`. A word like `$HOME/.ssh/id_rsa` matched none of them,
so `cat $HOME/.ssh/id_rsa` hit the `^cat` auto-approve pattern and read the key
with no card — while the same command spelled `~/.ssh/id_rsa` was escalated to
`required`. `_resolve_any` only ever saw what the scan collected.

Contract:
  A) a variable that expands to an absolute path is scanned;
  B) the boundary then reports "outside the session workspace";
  C) the literal spelling keeps working (no regression);
  D) words that are not paths after expansion (`$1`, `$?`) are not invented.

Deterministic: no shell is executed, no model, no server, no network.

Run: python3 tests/acceptance/v984_shell_var_boundary.py
"""
import os
import shutil
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_TMP = tempfile.mkdtemp(prefix="v984_")
# The boundary treats /tmp as a SYSTEM root (a scratch path needs no card), so
# the fixture lives outside it — under the gitignored .agent/trash — or every
# case here would read as "inside" for the wrong reason.
_FIX = os.path.join(REPO, ".agent", "trash", "v984_fixture")
shutil.rmtree(_FIX, ignore_errors=True)
os.makedirs(os.path.join(_FIX, "home", ".ssh"), exist_ok=True)
for _k in ("CONFIG_DIR", "SESSIONS_DIR", "EDITs_DIR", "RUNS_DIR", "GRAPH_DIR",
           "ROLES_DIR", "DATA_DIR"):
    os.environ["LONGRUN_" + _k] = os.path.join(_TMP, _k.lower())
    os.makedirs(os.environ["LONGRUN_" + _k], exist_ok=True)
os.environ["LONGRUN_DB"] = os.path.join(_TMP, "events.db")
os.environ["HOME"] = os.path.join(_FIX, "home")
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.tools import registry as R  # noqa: E402

RESULTS = []
WS = os.path.join(_FIX, "workspace")
os.makedirs(WS, exist_ok=True)


def check(name, ok, detail=""):
    RESULTS.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""))


# --- A: the expanded path is in the scan -----------------------------------
paths = R._shell_paths("cat $HOME/.ssh/id_rsa")
check("A1 $HOME expands into a scanned path",
      any(p.endswith(".ssh/id_rsa") and os.path.isabs(p) for p in paths), paths)
paths2 = R._shell_paths("cat ${HOME}/.ssh/id_rsa")
check("A2 ${HOME} expands too", len(paths2) == 1 and os.path.isabs(paths2[0]), paths2)

# --- B: the boundary escalates it -----------------------------------------
why = R.touches_outside("shell", {"command": "cat $HOME/.ssh/id_rsa"}, WS)
check("B1 a variable path outside the workspace is refused", bool(why), why)
check("B2 the reason names the resolved path", bool(why) and ".ssh/id_rsa" in why, why)

# --- C: the literal spelling is unchanged ---------------------------------
why_tilde = R.touches_outside("shell", {"command": "cat ~/.ssh/id_rsa"}, WS)
check("C1 the tilde spelling still escalates", bool(why_tilde), why_tilde)
why_abs = R.touches_outside("shell", {"command": "cat /etc/passwd"}, WS)
check("C2 an absolute path still escalates", bool(why_abs), why_abs)

# --- D: no invented paths -------------------------------------------------
check("D1 a positional parameter is not a path",
      R._shell_paths("echo $1 $? $USER") == [], R._shell_paths("echo $1 $? $USER"))
check("D2 an unknown variable is left alone",
      R._shell_paths("echo $NOT_SET_ANYWHERE/x") == [],
      R._shell_paths("echo $NOT_SET_ANYWHERE/x"))

ok = sum(RESULTS)
print("\nv984: %d/%d PASS" % (ok, len(RESULTS)))
shutil.rmtree(_FIX, ignore_errors=True)
sys.exit(0 if ok == len(RESULTS) else 1)
