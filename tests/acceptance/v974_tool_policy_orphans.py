#!/usr/bin/env python3
"""v974 — a tool POLICY that names no provider is reported, never silently dropped.

Found on the live install 2026-11-14: `config/tools.yaml` enabled
`python_sandbox__run_python_code` with an auto-approve policy while a Global rule
told EVERY session to call it, and the real tool path answered `unknown tool`;
26 `PMCP__gateway.*` entries spelled the live lowercase tools a second time; and
`sequential-thinking__sequentialthinking` was enabled with no such client. All
three were INVISIBLE — `catalog()` skips a row it cannot resolve, so the operator
had no way to see that their config held dead capabilities.

The provider here is SYNTHETIC (a temporary `TOOL_SCHEMAS` entry), so the test
does not depend on an MCP client being reachable.

  A  a `<client>__<tool>` policy with no provider is reported, with the client named
  B  a case-variant spelling of a LIVE tool is reported as a duplicate, and names it
  C  a real tool, and a DISABLED real tool, are never reported
  D  a plain namespace key (no `__`) is treated as inheritance, never as an orphan
  E  the exact provided name is never reported
  F  the report survives a broken registry (returns {}, never raises)
  G  `self.info` exposes it under `namespaces.orphans` without breaking the report

Deterministic: no live model, no network, no server.
"""
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="longrun-v974-")
for _k in ("DATA_DIR", "CONFIG_DIR", "SESSIONS_DIR", "GRAPH_DIR", "DB"):
    os.environ["LONGRUN_" + _k] = os.path.join(TMP, _k.lower())
os.environ["LONGRUN_AGENTS_FILE"] = os.path.join(TMP, "agents.json")
for _k in ("DATA_DIR", "CONFIG_DIR", "SESSIONS_DIR", "GRAPH_DIR"):
    os.makedirs(os.environ["LONGRUN_" + _k], exist_ok=True)
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.tools import diag  # noqa: E402
from longrun.tools import registry  # noqa: E402
from longrun.tools import tools as T  # noqa: E402

# A synthetic PROVIDER: the lowercase name is real, its uppercase twin is not.
LIVE = "synth_client__synth_tool"
registry.TOOL_SCHEMAS[LIVE] = {"type": "object", "properties": {}}

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print("%s %s%s" % ("PASS" if ok else "FAIL", name,
                       "" if ok else "  -> %r" % (detail,)))


def _set_cfg(extra, drop=()):
    """Write `extra` into the live config, dropping `drop`, and reload."""
    cfg = registry.load_config()
    tools = cfg.setdefault("tools", {})
    for k in drop:
        tools.pop(k, None)
    tools.update(extra)
    registry.save_config(cfg)
    registry.load_config(reload=True)


# ---------------------------------------------------------------- A: phantom --
_set_cfg({"ghost_client__ghost_tool": {"enabled": True, "approval": "auto"}})
o = registry.orphan_policies()
check("A1 a policy with no provider is reported", "ghost_client__ghost_tool" in o, o)
check("A2 the reason names the missing client",
      "ghost_client" in str(o.get("ghost_client__ghost_tool")), o)

# ------------------------------------- B: a case-variant of a LIVE tool -------
_set_cfg({"SYNTH_Client__synth_tool": {"enabled": True}})
o = registry.orphan_policies()
check("B1 a case-variant spelling is reported", "SYNTH_Client__synth_tool" in o, o)
check("B2 and it is called a duplicate of the live tool",
      "duplicate" in str(o.get("SYNTH_Client__synth_tool", ""))
      and LIVE in str(o.get("SYNTH_Client__synth_tool", "")), o)

# --------------------------------------------- C/D: never a false positive ----
_set_cfg({"memory.forget": {"enabled": False}, "shell": {"enabled": True},
          "fs.read": {"enabled": True}},
         drop=("SYNTH_Client__synth_tool", "ghost_client__ghost_tool"))
o = registry.orphan_policies()
check("C1 a real built-in tool is never reported", "shell" not in o and "fs.read" not in o, o)
check("C2 a DISABLED real tool is still not an orphan", "memory.forget" not in o, o)
check("D1 a plain namespace key is inheritance, not an orphan", "shell" not in o, o)
check("E1 the exact provided name is never reported", LIVE not in o, o)
check("E2 the ghost from A was cleaned up", "ghost_client__ghost_tool" not in o, o)

# ------------------------------------------------------------- F: never raises -
_saved = registry.load_config
try:
    registry.load_config = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom"))
    got = registry.orphan_policies()
    check("F1 a broken registry yields {} instead of raising", got == {}, got)
finally:
    registry.load_config = _saved

# ------------------------------------------------- G: surfaced by self.info ----
n = diag.namespaces()
check("G1 the namespace report carries the orphans key", "orphans" in n, sorted(n))
check("G2 the existing keys survive",
      set(("enabled", "disabled", "admitted", "count", "namespaces")) <= set(n), sorted(n))
r = T._self({"action": "info"}, None)
check("G3 self.info still answers", bool(r.get("ok")) and "identity" in r, r)
check("G4 through self.info the report reaches the model",
      isinstance(r.get("namespaces"), dict) and "orphans" in r["namespaces"], sorted(r))

registry.TOOL_SCHEMAS.pop(LIVE, None)

print("---")
passed = sum(results)
print("%d/%d PASS" % (passed, len(results)))
sys.exit(0 if passed == len(results) else 1)
