#!/usr/bin/env python3
"""v821 — a sub-tool may ADD a restriction, never REMOVE a namespace one.

`tool_spec` built a namespace tool's policy with a shallow `{**ns, **exact}` merge,
so the moment a sub-tool carried its own `deny` list the namespace's list was
REPLACED. Measured on the live config 2026-11-05: `shell` (namespace) denies
`grep[^\n]*\.env`, `shell.exec` had its own list without it, and

    classify("shell.exec", {"command": "grep -r TOKEN …/.env"})  ->  "auto"
    classify("shell",     {"command": "grep -r TOKEN …/.env"})  ->  "denied"

i.e. a secret-exfiltration hard block was bypassable by the tool NAME.

  A) a namespace `deny` survives on the sub-tool and still denies;
  B) `always_ask` is unioned too;
  C) the sub-tool's own restrictions are still there;
  D) `auto_approve` still REPLACES (an exact entry may NARROW what is allowed);
  E) the counter is keyed by the canonical name, so the report can see it fire.

Deterministic, no live model, no network, no server.
"""
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="sf-v821-")
os.environ["LONGRUN_CONFIG_DIR"] = os.path.join(TMP, "cfg")
os.environ["LONGRUN_DATA_DIR"] = os.path.join(TMP, "data")
os.environ["LONGRUN_DB"] = os.path.join(TMP, "events.db")
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.core import server                 # noqa: E402,F401 — breaks the import cycle
from longrun.tools import registry              # noqa: E402

registry._external_tools = lambda: {}           # an acceptance test must not start MCP clients

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""))


CFG = {"tools": {
    "ns": {"enabled": True, "approval": "auto",
           "deny": ["secret-block"], "always_ask": ["careful"],
           "auto_approve": ["^ls$"]},
    "ns.sub": {"enabled": True, "approval": "required",
               "deny": ["other-block"], "auto_approve": []},
}, "approvals": {"mode": "normal"}}
_REAL_LOAD_CONFIG = registry.load_config
registry.load_config = lambda reload=False: CFG

spec = registry.tool_spec("ns.sub")

# --------------------------------------------------- A/B/C. the lists union -----
check("A1 the namespace deny survives on the sub-tool",
      "secret-block" in (spec.get("deny") or []), spec.get("deny"))
check("C1 the sub-tool's own deny is still there",
      "other-block" in (spec.get("deny") or []), spec.get("deny"))
check("B1 always_ask is unioned too",
      "careful" in (spec.get("always_ask") or []), spec.get("always_ask"))

d1, why1 = registry.classify("ns.sub", {"command": "run secret-block now"})
check("A2 the inherited rule actually denies", d1 == "denied", (d1, why1))
d2, why2 = registry.classify("ns.sub", {"command": "run other-block now"})
check("C2 the sub-tool's own rule denies", d2 == "denied", (d2, why2))
d3, why3 = registry.classify("ns.sub", {"command": "be careful please"})
check("B2 the inherited always_ask requires approval", d3 == "required", (d3, why3))

# --------------------------------------------------- D. auto_approve REPLACES --
check("D1 auto_approve still REPLACES (an exact entry may narrow it)",
      (spec.get("auto_approve") or []) == [], spec.get("auto_approve"))
d4, why4 = registry.classify("ns.sub", {"command": "ls -la"})
check("D2 so the namespace's auto-approve is NOT inherited", d4 == "required", (d4, why4))

# --------------------------------------------- E. the counter is canonical ------
rep = registry.policy_report()
check("E1 the fired rule is recorded under the canonical tool name",
      (rep["firings"].get("ns.sub:deny:secret-block") or {}).get("n") == 1, rep["firings"])

# With the REAL config: `shell` and `git` are namespace POLICY keys, not tools —
# only `shell.exec` / `git.run` are in the catalog. The report must key rules by the
# name `classify` actually uses, or a namespace-level rule is never matched against
# its own counter and sits in `never_fired` for ever.
registry.load_config = _REAL_LOAD_CONFIG
real = registry.policy_report()
names = {t.get("name") for t in registry.catalog()}
bad = [k for k in real["never_fired"] if k.split(":", 1)[0] not in names]
check("E2 every reported rule names a REAL tool (no raw config key)",
      not bad, bad)
check("E3 and the report is not empty (the real config does define rules)",
      real["configured_rules"] > 0, real["configured_rules"])

print("---")
passed = sum(results)
print("%d/%d PASS" % (passed, len(results)))
sys.exit(0 if passed == len(results) else 1)
