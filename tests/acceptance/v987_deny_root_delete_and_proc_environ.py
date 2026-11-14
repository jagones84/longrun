#!/usr/bin/env python3
"""v987 — the hard-deny list catches every spelling of "delete the root", and
the service environment cannot be read through `/proc`.

A bug-hunt session (`policy` axis, 2026-11-14) reported two provable holes in
`config/tools.yaml`:

  1. `rm\\s+-rf\\s+/(\\s|$)` matched only the literal flag order `-rf` before a
     bare `/`. `rm -fr /`, `rm -r -f /`, `rm -rf /*`, `rm -rf --no-preserve-root /`
     and `rm --recursive --force /` all reached the filesystem root — and a hard
     deny is the only gate that survives `approvals.mode=full`, so nothing else
     caught them.
  2. `/proc` is in `registry._SYSTEM_ROOTS`, so `cat /proc/self/environ` counted
     as "inside the workspace" and the `^cat` auto-approve pattern read it. The
     child shell inherits the service environment, which carries the API token.

Contract:
  A) every recursive+force delete of the root (any flag order / long form) is denied;
  B) every read of `/proc/*/environ` or `/proc/*/mem` is denied;
  C) ordinary work is untouched (`rm -rf ./build`, `/tmp`, a plain file, `/proc/cpuinfo`);
  D) the rest of the shipped hard-deny list still fires.

Deterministic: no shell is executed, no model, no server, no network.
Run: python3 tests/acceptance/v987_deny_root_delete_and_proc_environ.py
"""
import os
import sys
import tempfile

TMP = tempfile.mkdtemp(prefix="sf-v987-")
for _k in ("CONFIG_DIR", "SESSIONS_DIR", "EDITS_DIR", "RUNS_DIR", "GRAPH_DIR", "ROLES_DIR"):
    os.environ["LONGRUN_" + _k] = os.path.join(TMP, _k)
    os.makedirs(os.path.join(TMP, _k), exist_ok=True)
os.environ["LONGRUN_DB"] = os.path.join(TMP, "events.db")
os.environ["LONGRUN_JOBS_FILE"] = os.path.join(TMP, "jobs.json")
REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.tools import registry as REG  # noqa: E402

RESULTS = []


def check(name, ok, detail=""):
    RESULTS.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""))


def decision(cmd):
    return REG.classify("shell", {"command": cmd})


# ---- A: every spelling of a recursive+force root delete -------------------
for label, cmd in [
    ("literal -rf /", "rm -rf /"),
    ("reversed -fr /", "rm -fr /"),
    ("glob -rf /*", "rm -rf /*"),
    ("mixed case -Rf /", "rm -Rf /"),
    ("split -r -f /", "rm -r -f /"),
    ("split -f -r /", "rm -f -r /"),
    ("long options", "rm --recursive --force /"),
    ("no-preserve-root", "rm -rf --no-preserve-root /"),
    ("prefixed sudo", "sudo rm -rf /"),
    ("chained", "cd /tmp && rm -rf /"),
]:
    _d, _r = decision(cmd)
    check("A %s is hard-denied" % label, _d == "denied" and "hard-deny" in _r, (_d, _r))

# ---- B: the service environment is not readable ---------------------------
for label, cmd in [
    ("cat self environ", "cat /proc/self/environ"),
    ("strings pid environ", "strings /proc/1/environ"),
    ("redirect environ", "tr '\\0' '\\n' < /proc/self/environ"),
    ("grep environ", "grep -a TOKEN /proc/self/environ"),
    ("read own memory", "cat /proc/self/mem"),
    ("python open environ", "python3 -c \"print(open('/proc/self/environ').read())\""),
]:
    _d, _r = decision(cmd)
    check("B %s is hard-denied" % label, _d == "denied" and "hard-deny" in _r, (_d, _r))

# ---- C: ordinary work is not denied --------------------------------------
for label, cmd in [
    ("relative workspace delete", "rm -rf ./build"),
    ("scratch delete", "rm -rf /tmp/scratch"),
    ("plain file", "rm file.txt"),
    ("recursive without force", "rm -r ./old"),
    ("cpuinfo", "cat /proc/cpuinfo"),
    ("meminfo", "cat /proc/meminfo"),
    ("grep source tree", "grep -r environ src/"),
    ("list root", "ls /"),
]:
    _d, _r = decision(cmd)
    check("C %s is not hard-denied" % label, _d != "denied" and "hard-deny" not in _r, (_d, _r))

# ---- D: the rest of the list still fires ---------------------------------
for label, cmd in [
    ("mkfs", "mkfs.ext4 /dev/sda1"),
    ("plain mkfs", "mkfs /dev/sda1"),
    ("dd to a device", "dd if=/dev/zero of=/dev/sda"),
    ("dd urandom to a device", "dd if=/dev/urandom of=/dev/sda"),
    ("fork bomb", ":(){ :|:& };:"),
    ("token name", "echo LONGRUN_TOKEN"),
    ("grep .env", "grep -oP 'LONGRUN_TOKEN' .env"),
]:
    _d, _r = decision(cmd)
    check("D %s still denied" % label, _d == "denied" and "hard-deny" in _r, (_d, _r))

_shipped = (REG.load_config(reload=True).get("tools") or {}).get("shell") or {}
check("D6 the shipped shell deny list is still populated",
      len(_shipped.get("deny") or []) >= 8, len(_shipped.get("deny") or []))

ok = sum(RESULTS)
print("\nv987: %d/%d PASS" % (ok, len(RESULTS)))
sys.exit(0 if ok == len(RESULTS) else 1)
