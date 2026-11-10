#!/usr/bin/env python3
"""v945 — the shell's working directory is part of the workspace boundary.

`touches_outside` scanned `cwd` and the path-like words of the command for a
`shell` call, but not `workspace` — which `_shell` uses as the process working
directory when `cwd` is absent (`tools/tools.py`). A command whose TEXT names no
path (`grep -r SECRET .`, `find .`, `cat x`) therefore reached any directory by
naming it as `workspace` and still auto-approved: JAG-388 says ANY action that
reaches outside the session workspace needs approval.

Deterministic: temp dirs, approvals.mode pinned to normal, no server, no model.
Run: python3 tests/acceptance/v945_shell_workspace_boundary.py
"""

import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="sf-v945-")
os.environ["LONGRUN_DATA_DIR"] = TMP
for _k in ("CONFIG_DIR", "SESSIONS_DIR", "EDITS_DIR", "RUNS_DIR", "GRAPH_DIR", "ROLES_DIR"):
    os.environ["LONGRUN_" + _k] = os.path.join(TMP, _k)
    os.makedirs(os.path.join(TMP, _k), exist_ok=True)
os.environ["LONGRUN_DB"] = os.path.join(TMP, "events.db")
os.environ["LONGRUN_JOBS_FILE"] = os.path.join(TMP, "jobs.json")
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.tools import registry as REG  # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""))


WS = REPO
# `/etc` is deliberately NOT in the system/scratch allow-list (see
# registry._SYSTEM_ROOTS) — a /tmp path would count as inside and hide the defect.
OUT = "/etc"

_cfg = REG.load_config(reload=True)
_cfg.setdefault("approvals", {})["mode"] = "normal"


def classify(tool, args):
    with REG.scoped_config(_cfg):
        return REG.classify(tool, args, WS)


# A. the reported hole
_d, _r = classify("shell", {"command": "grep -r SECRET .", "workspace": OUT})
check("A1 a `workspace` outside the session needs approval", _d == "required", (("shell", _d, _r)))
_d, _r = classify("shell.exec", {"command": "find .", "workspace": OUT})
check("A2 the dotted name is covered too", _d == "required", ("shell.exec", _d, _r))
_d, _r = classify("shell", {"action": "run", "command": "cat x", "workspace": OUT})
check("A3 an explicit action=run call is covered", _d == "required", ("shell", _d, _r))

# B. normal use is unchanged
_d, _r = classify("shell", {"command": "grep -r TODO .", "workspace": WS})
check("B1 a command in the session workspace stays automatic", _d == "auto", (("shell", _d, _r)))
_d, _r = classify("shell", {"command": "grep -r TODO .", "workspace": os.path.join(WS, "src")})
check("B2 a subfolder of the workspace stays automatic", _d == "auto", (("shell", _d, _r)))
_d, _r = classify("shell", {"command": "grep -r TODO .", "cwd": os.path.join(WS, "src")})
check("B3 `cwd` inside the workspace stays automatic", _d == "auto", (("shell", _d, _r)))
_d, _r = classify("shell", {"command": "grep -r TODO .", "cwd": OUT})
check("B4 `cwd` outside the workspace still needs approval", _d == "required",
      ("shell", _d, _r))

# C. the scanner agrees with the handler about WHICH directory is used
check("C1 touches_outside reports the workspace reason",
      "outside the session workspace" in str(
          REG.touches_outside("shell", {"command": "ls", "workspace": OUT}, WS)))
check("C2 nothing is reported when no workspace arg is given",
      REG.touches_outside("shell", {"command": "grep -r TODO ."}, WS) is None)

print("TOTAL %d/%d" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
