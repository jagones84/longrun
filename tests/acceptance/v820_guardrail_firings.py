#!/usr/bin/env python3
"""v820 — a guardrail nobody triggers should be visible as such.

The Cursor talk keeps a "shims registry": every deterministic guardrail is logged
when it fires, so one that has stopped being needed can be found and retired.
Longrun published nothing when a `deny` or `always_ask` rule matched, so an
obsolete rule was indistinguishable from a load-bearing one — the Permissions page
showed rules with no evidence of use.

  A) a deny rule that fires is counted, and the untouched rule is named as never fired;
  B) after the second rule fires, nothing is left in `never_fired`;
  C) the counter is persisted (a restart does not forget);
  D) `GET /api/tools` exposes the report.

Deterministic, no live model, no network, no server.
"""
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="sf-v820-")
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


CFG = {"tools": {"faketool": {"enabled": True, "approval": "auto",
                              "deny": ["rm -rf"], "always_ask": ["deploy"]}},
       "approvals": {"mode": "normal"}}
registry.load_config = lambda reload=False: CFG       # a canned policy, no config write

# ------------------------------------------------- A. a deny rule fires once ----
decision, why = registry.classify("faketool", {"command": "rm -rf /tmp/x"})
check("A1 the deny rule denies", decision == "denied", (decision, why))
rep = registry.policy_report()
check("A2 the deny rule is counted once",
      (rep["firings"].get("faketool:deny:rm -rf") or {}).get("n") == 1, rep["firings"])
check("A3 the untouched always-ask rule is named as never fired",
      "faketool:always_ask:deploy" in rep["never_fired"], rep["never_fired"])

# ------------------------------------------------ B. the second rule fires -----
decision2, why2 = registry.classify("faketool", {"command": "deploy to prod"})
check("B1 the always-ask rule requires approval", decision2 == "required", (decision2, why2))
rep2 = registry.policy_report()
check("B2 nothing is left unfired", rep2["never_fired"] == [], rep2["never_fired"])
check("B3 the counts agree with the config",
      rep2["configured_rules"] == 2 and rep2["fired_rules"] == 2, rep2)
check("B4 the deny counter is still there",
      (rep2["firings"].get("faketool:deny:rm -rf") or {}).get("n") == 1, rep2["firings"])

# ------------------------------------------------------------- C. persistence ---
check("C1 the ledger is on disk", os.path.isfile(registry._HIT_PATH), registry._HIT_PATH)

# ---------------------------------------------------------------- D. the REST ---
api = open(os.path.join(REPO, "src", "longrun", "core", "api_v02.py"),
           encoding="utf-8").read()
check("D1 /api/tools exposes rule_firings",
      '"rule_firings": registry.policy_report()' in api)

print("---")
passed = sum(results)
print("%d/%d PASS" % (passed, len(results)))
sys.exit(0 if passed == len(results) else 1)
