#!/usr/bin/env python3
"""v942 — git's destructive flags are no longer auto-approved.

`^branch(\\s|$)`, `^tag(\\s|$)` and `^remote(\\s|$)` matched ANY flags after the
subcommand, so `git branch -D feature`, `git tag -d v1` and
`git remote set-url origin …` ran with no card while the tool description called
those subcommands read-only. `^(log|diff|show)` also auto-approved
`git diff --output=<path>` — git writes a file the workspace scan never sees (it
reads the CWD, not git's own options).

Only the listing forms stay automatic, and `--output` sits in `always_ask`, which
survives `approvals.mode=full`.

Deterministic: temp dirs, no repo, no server, no network.
Run: python3 tests/acceptance/v942_git_readonly_autapprove.py
"""

import os
import sys
import tempfile

TMP = tempfile.mkdtemp(prefix="sf-v942-")
# The policy OVERLAY lives under the data dir: without this the operator's own
# `data/tools.overlay.yaml` would decide the test.
os.environ["LONGRUN_DATA_DIR"] = TMP
for _k in ("CONFIG_DIR", "SESSIONS_DIR", "EDITS_DIR", "RUNS_DIR", "GRAPH_DIR", "ROLES_DIR"):
    os.environ["LONGRUN_" + _k] = os.path.join(TMP, _k)
    os.makedirs(os.path.join(TMP, _k), exist_ok=True)
os.environ["LONGRUN_DB"] = os.path.join(TMP, "events.db")
os.environ["LONGRUN_JOBS_FILE"] = os.path.join(TMP, "jobs.json")
REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.tools import registry as REG  # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""))


_base = REG.load_config(reload=True)
_normal = REG.load_config(reload=True)
_normal.setdefault("approvals", {})["mode"] = "normal"
_full = REG.load_config(reload=True)
_full.setdefault("approvals", {})["mode"] = "full"


def git(args, cfg=None):
    with REG.scoped_config(cfg or _normal):
        return REG.classify("git", {"args": args})


for read_only in ("status", "log --oneline -5", "show HEAD", "diff HEAD~1",
                  "branch -a", "branch --list", "branch -v", "branch --show-current",
                  "tag -l", "tag --list", "remote -v", "remote show origin",
                  "rev-parse HEAD", "describe --tags", "ls-files"):
    d, r = git(read_only)
    check("A read-only `git %s` is auto" % read_only, d == "auto", "%s :: %s" % (d, r))

for mutating in ("branch -D feature", "branch -d feature", "branch -f main HEAD~3",
                 "branch -m old new", "tag -d v1", "tag -f v2 HEAD~1",
                 "remote set-url origin git@evil:x", "remote remove origin",
                 "remote add evil https://evil/x", "push origin main"):
    d, r = git(mutating)
    check("B mutating `git %s` needs approval" % mutating, d == "required", "%s :: %s" % (d, r))

for writing in ("diff --output=/etc/evil HEAD", "log --output=/tmp/leak -p",
                "show --output=/tmp/leak HEAD"):
    d, r = git(writing)
    check("C `git %s` needs approval (writes a path the scan cannot see)" % writing,
          d == "required", "%s :: %s" % (d, r))

_d, _r = git("diff --output=/tmp/leak HEAD", _full)
check("D even approvals.mode=full sends `git diff --output` to a human",
      _d == "required", "%s :: %s" % (_d, _r))
_d, _r = git("branch -D feature", _full)
check("E full mode is still the operator's opt-out for the other mutating forms",
      _d == "auto", "%s :: %s" % (_d, _r))
_d, _r = git("status", _full)
check("F a plain read-only command stays automatic in full mode", _d == "auto")

print("TOTAL %d/%d" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
