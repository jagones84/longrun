#!/usr/bin/env python3
"""v347 — every tool's payload must reach the model (observation never empty).

Same defect class as the fs.read bug: a tool whose payload lives outside
stdout/stderr/path rendered as an EMPTY observation (exit=0, no error), so the
agent acted blind. This guards observation() for fs.write / fs.edit / self /
improve / reconcile and any future tool (JSON fallback), without regressing the
stdout-based tools (no clutter) or the error short-circuit.

Deterministic, no model. Run: python3 tests/acceptance/v347_observation_payload.py
"""
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.tools import tools  # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + detail) if detail else ""))


def body(obs):
    return "\n".join(obs.splitlines()[1:]).strip()


HDR = {"ok": True, "exit_code": 0, "backend": "host", "sandboxed": False}

# --- A: fs.write shows its counter (not just the path) ------------------------
o = tools.observation({"tool": "fs.write", "path": "/x/y.txt", "bytes": 32,
                       "append": False, **HDR})
check("A1 fs.write is NOT an empty observation", body(o) != "", repr(o))
check("A2 fs.write leaks the byte count", "32" in o, repr(o))

# --- B: fs.edit shows the replacement count ----------------------------------
o = tools.observation({"tool": "fs.edit", "path": "/x", "replacements": 2,
                       "bytes_before": 10, "bytes_after": 12, **HDR})
check("B1 fs.edit leaks the replacement count", "2" in o and "replacements" in o, repr(o))

# --- C: self (structured dict, no stdout/path) must NOT be empty -------------
o = tools.observation({"tool": "self", "name": "Longrun", "version": "0.5.0",
                       "repo_path": "/r", "skills": {"count": 42}, **HDR})
check("C1 self is NOT an empty observation", body(o) != "", repr(o))
check("C2 self leaks its payload", "Longrun" in o or "0.5.0" in o, repr(o))

# --- D: improve (payload under `proposal`) -----------------------------------
o = tools.observation({"tool": "improve", "proposal": {"scope": "skill", "path": "p"},
                       **HDR})
check("D1 improve leaks its proposal", "proposal" in o, repr(o))

# --- E: reconcile (its own `observation` string is honoured) -----------------
o = tools.observation({"tool": "reconcile", "reconciled": 3,
                       "observation": "reconciled 3 session(s)", **HDR})
check("E1 reconcile shows its own observation text", "reconciled 3" in o, repr(o))

# --- F: no regression — stdout-based tools stay clean & correct --------------
o = tools.observation({"tool": "shell", "stdout": "HELLO", "stderr": "", **HDR})
check("F1 shell stdout still shown", "HELLO" in o, "")
check("F2 stdout tools get NO clutter fallback", "result:" not in o, repr(o))
o = tools.observation({"tool": "fs.read", "path": "/f", "content": "FILEBODY", **HDR})
check("F3 fs.read content still shown", "FILEBODY" in o, "")

# --- G: error still short-circuits, but the verdict stays visible -------------
_err = tools.observation({"tool": "x", "ok": False, "exit_code": 1, "error": "boom"})
check("G1 an error is still reported first with its verdict",
      _err.startswith("[x] exit=1 ok=False") and "ERROR: boom" in _err,
      repr(_err))

# --- H: the fallback is bounded ----------------------------------------------
o = tools.observation({"tool": "self", "blob": "z" * 50000, **HDR}, max_chars=800)
check("H1 the JSON fallback is truncated to the budget", len(o) < 1200, str(len(o)))

print("---")
ok = sum(results)
print("%d/%d PASS" % (ok, len(results)))
sys.exit(0 if ok == len(results) else 1)

