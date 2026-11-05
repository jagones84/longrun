#!/usr/bin/env python3
"""v802 — the git tool may push again (operator authorisation, 2026-11-05).

Operator: "Yes agent may push and be connected by the token to github".
`config/tools.yaml` used to hard-deny `^push(\\s|$)`, and a hard deny is absolute
(`approvals.mode=full` never lifts it), so the request could only be met by
removing the pattern — exactly like the `shutdown` removal in D-1 (2026-11-04).

What this pins:
  A  push is no longer denied: the shipped deny list is empty and `classify`
     returns the tool's ordinary approval verdict, not "denied".
  B  the rest of the boundary stands: the shell deny list is untouched and
     still denies `rm -rf /` and the token-leak command (no over-relaxation).
  C  the tool description no longer tells the model "push is denied" (one
     truth: the schema sentence and the policy agree).

Deterministic: temp dirs, no server, no model, no network.
Run: python3 tests/acceptance/v802_git_push_allowed.py
"""
import os
import sys
import tempfile

TMP = tempfile.mkdtemp(prefix="sf-v802-")
for _k in ("CONFIG_DIR", "SESSIONS_DIR", "EDITS_DIR", "RUNS_DIR", "GRAPH_DIR", "ROLES_DIR"):
    os.environ["LONGRUN_" + _k] = os.path.join(TMP, _k)
    os.makedirs(os.path.join(TMP, _k), exist_ok=True)
os.environ["LONGRUN_DB"] = os.path.join(TMP, "events.db")
os.environ["LONGRUN_JOBS_FILE"] = os.path.join(TMP, "jobs.json")
REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(REPO, "src"))


def _read(*parts):
    with open(os.path.join(REPO, *parts), encoding="utf-8") as f:
        return f.read()


from longrun.tools import registry as REG  # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""))


CFG = REG.load_config(reload=True)
TOOLS = CFG.get("tools") or {}

# ---- A: push follows the approval policy ---------------------------------
check("A1 the shipped git deny list is empty",
      list((TOOLS.get("git") or {}).get("deny") or []) == [],
      (TOOLS.get("git") or {}).get("deny"))
_d0, _r0 = REG.classify("git", {"args": "push origin Experimental-Refactor"})
check("A2 push is not hard-denied", _d0 != "denied" and "hard-deny" not in _r0, (_d0, _r0))
check("A3 push follows the tool's own approval verdict (never 'denied')",
      _d0 in ("approval", "required", "auto"), (_d0, _r0))
_d1, _r1 = REG.classify("git", {"args": "push --force origin master"})
check("A4 a force-push is not silently denied either (same policy, not a new rule)",
      _d1 != "denied", (_d1, _r1))
_d2, _r2 = REG.classify("git", {"args": "status --short"})
check("A5 read-only git stays auto-approved", _d2 == "auto", (_d2, _r2))

# ---- B: the rest of the boundary is intact -------------------------------
_sh = (TOOLS.get("shell") or {}).get("deny") or []
check("B1 the shell deny list is still populated", len(_sh) >= 5, len(_sh))
_d3, _r3 = REG.classify("shell", {"command": "rm -rf /"})
check("B2 rm -rf / is still hard-denied", _d3 == "denied" and "hard-deny" in _r3, _r3)
_d4, _r4 = REG.classify("shell", {"command": "echo LONGRUN_TOKEN"})
check("B3 the token name is still hard-denied", _d4 == "denied", _r4)

# ---- C: the schema sentence matches the policy ---------------------------
YAML = _read("config", "tools.yaml")
check("C1 no ^push deny ENTRY survives in config/tools.yaml",
      '- "^push' not in YAML)
REG_SRC = _read("src", "longrun", "tools", "registry.py")
check("C2 the git description no longer claims push is denied",
      "push is denied" not in REG_SRC
      and "push follows the tool's approval policy" in REG_SRC)

print("---")
ok = sum(results)
print("\nv802: %d/%d PASS" % (ok, len(results)))
sys.exit(0 if ok == len(results) else 1)
