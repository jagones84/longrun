#!/usr/bin/env python3
"""v1307 — a core module imports ALONE: no order-dependent import cycle.

Measured 2026-11-25 while probing the rules collector: `import longrun.agent.agent`
raised `ImportError: cannot import name 'SYSTEM_PROMPT' from partially initialized
module`. The cause was structural, not cosmetic — `agent.py` imported `server` at its
TOP while `server.py` imports the names `agent.py` defines at its BOTTOM, so the pair
only worked when `server` was imported first. Anything that reaches the agent module
directly (a plugin, a test, `forge.py`, a worker) died on import.

Contract:
  A  the modules a caller may reach directly import in a FRESH interpreter, each on
     its own (agent core, the server aggregate, tools, memory, plan, orchestrate);
  B  the mechanism: `agent.py` binds `server` at its BOTTOM (both halves complete
     before either reads the other), and the comment says why;
  C  the documented exception stays documented: `httpapi` is imported THROUGH
     `server` (it reads `server` at module level and `server` re-exports its names).

Deterministic: subprocesses with isolated temp dirs, no model, no network, no server.
Run: python3 tests/acceptance/v1307_import_each_core_module.py
"""
import os
import subprocess
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="v1307-")

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""))


def read(*parts):
    with open(os.path.join(REPO, *parts), encoding="utf-8") as f:
        return f.read()


ENV = dict(os.environ)
ENV.update({
    "PYTHONPATH": os.path.join(REPO, "src"),
    "LONGRUN_DATA_DIR": os.path.join(TMP, "data"),
    "LONGRUN_CONFIG_DIR": os.path.join(TMP, "cfg"),
    "LONGRUN_SESSIONS_DIR": os.path.join(TMP, "sessions"),
    "LONGRUN_ROLES_DIR": os.path.join(TMP, "roles"),
    "LONGRUN_THREADS_DIR": os.path.join(TMP, "threads"),
    "LONGRUN_DB": os.path.join(TMP, "events.db"),
    "LONGRUN_OFFLINE": "1",
    "LONGRUN_OPTIMIZER": "0",
})
for _d in ("data", "cfg", "sessions", "roles", "threads"):
    os.makedirs(os.path.join(TMP, _d), exist_ok=True)


def imports_alone(mod):
    """(rc, last stderr line) for `import <mod>` in a fresh interpreter."""
    try:
        r = subprocess.run([sys.executable, "-c", "import " + mod], cwd=REPO, env=ENV,
                           capture_output=True, text=True, timeout=120)
    except Exception as exc:  # noqa: BLE001 — report, never crash the gate
        return 99, str(exc)
    err = [ln for ln in (r.stderr or "").strip().splitlines() if ln.strip()]
    return r.returncode, (err[-1] if err else "")


# ---- A: the modules a caller may reach directly -----------------------------
DIRECT = ["longrun",
          "longrun.agent.agent",          # the one that was broken
          "longrun.core.server",          # the aggregate (the app's own entry)
          "longrun.agent.agents",
          "longrun.agent.architect",
          "longrun.tools.tools",
          "longrun.tools.registry",
          "longrun.memory.rules",
          "longrun.memory.threads",
          "longrun.plan.taskgraph",
          "longrun.orchestrate.orchestration"]
for mod in DIRECT:
    rc, last = imports_alone(mod)
    check("A %s imports alone" % mod, rc == 0, last[:200])

# ---- B: the mechanism that makes it order-independent -----------------------
AGENT = read("src", "longrun", "agent", "agent.py")
# the BOTTOM import (a lazy `as _srv` inside one function is a different, fine thing)
_imp = AGENT.rfind("\nfrom longrun.core import server")
_last_def = max(AGENT.rfind("\ndef "), AGENT.rfind("\nasync def "))
check("B1 agent.py binds `server` at its BOTTOM, after every definition",
      _imp > _last_def > 0, "import at %d, last def at %d" % (_imp, _last_def))
check("B2 the reason is written where the next maintainer will read it",
      "import cycle" in AGENT[max(0, _imp - 900):_imp + 200].lower()
      or "partially initialized" in AGENT[max(0, _imp - 900):_imp + 200])
check("B3 no module-level `server.<name>` use can run before the bottom import",
      "server.VERSION" not in AGENT[:AGENT.find("\ndef ")])

# ---- C: the documented exception is still declared as one ------------------
SRV = read("src", "longrun", "core", "server.py")
check("C1 server.py re-exports the httpapi names at its bottom (one documented order)",
      "from longrun.core.httpapi import" in SRV
      and SRV.find("from longrun.core.httpapi import") > len(SRV) // 2,
      "at %d of %d" % (SRV.find("from longrun.core.httpapi import"), len(SRV)))

print("")
print("v1307: %d/%d PASS" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
