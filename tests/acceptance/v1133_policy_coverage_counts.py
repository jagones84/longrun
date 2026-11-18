#!/usr/bin/env python3
"""v1133 — the guardrail coverage report reconciles with the policy it describes.

Round 67 (arXiv:2611.15223 guardscope — a control is checked, bypassed or
prevented). `registry.policy_report()` is the guardrail-coverage instrument, and
its three numbers could not be reconciled:

  configured_rules: 23   fired_rules: 38   never_fired: 2

`fired_rules` counted EVERY key the hit ledger holds — including rules the policy
no longer has (round 65 removed the two `.env` reader rules; their history stayed
in the count). An operator reading "38 fired out of 23 configured" cannot tell
which guardrails are load-bearing, which are untested, and which are gone.

  A  fired counts the CONFIGURED rules that fired: fired + never == configured
  B  history under a rule the policy no longer has is NAMED as retired
  C  a never-fired rule stays named, with no invented evidence
  D  `self {action:"info"}` carries the counters (the AGENT can read them)
  E  `/api/tools` exposes the retired list beside the rest

Deterministic: fake config + a temp ledger; no server, no model, no network.
Run: python3 tests/acceptance/v1133_policy_coverage_counts.py
"""
import json
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="sf-v1133-")
os.environ["LONGRUN_CONFIG_DIR"] = os.path.join(TMP, "cfg")
os.environ["LONGRUN_DATA_DIR"] = os.path.join(TMP, "data")
os.environ["LONGRUN_SESSIONS_DIR"] = os.path.join(TMP, "sessions")
os.environ["LONGRUN_DB"] = os.path.join(TMP, "events.db")
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.core import server                 # noqa: E402,F401 — breaks the import cycle
from longrun.tools import registry              # noqa: E402
from longrun.tools import tools as T            # noqa: E402

registry._external_tools = lambda: {}           # never start an MCP client in a test

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name
          + ((" :: " + str(detail)[:300]) if detail and not ok else ""))


CFG = {"tools": {"shell.exec": {"enabled": True, "approval": "auto",
                                "deny": ["rm -rf", "mkfs"],
                                "always_ask": ["deploy"]}},
       "approvals": {"mode": "normal"}}
registry.load_config = lambda reload=False: CFG

# --- A: one of three rules fires ---------------------------------------------
d, why = registry.classify("shell.exec", {"command": "rm -rf /tmp/x"})
check("A1 the deny rule fires", d == "denied", (d, why))
rep = registry.policy_report()
check("A2 configured counts every rule (2 deny + 1 always_ask)",
      rep["configured_rules"] == 3, rep)
check("A3 fired counts the configured rule that fired",
      rep["fired_rules"] == 1, rep)
check("A4 the identity holds: fired + never == configured",
      rep["fired_rules"] + len(rep["never_fired"]) == rep["configured_rules"], rep)
check("A5 the two untouched rules are named",
      sorted(rep["never_fired"]) == ["shell.exec:always_ask:deploy",
                                     "shell.exec:deny:mkfs"], rep["never_fired"])

# --- B: history under a rule the policy no longer has -----------------------
registry.note_rule_hit("shell.exec", "deny", "a-reader-rule-removed-in-round-65")
rep2 = registry.policy_report()
check("B1 the retired key is NAMED", rep2["retired_rules"] ==
      ["shell.exec:deny:a-reader-rule-removed-in-round-65"], rep2["retired_rules"])
check("B2 and it does NOT inflate the fired count", rep2["fired_rules"] == 1, rep2)
check("B3 the identity still holds", rep2["fired_rules"] + len(rep2["never_fired"])
      == rep2["configured_rules"], rep2)
check("B4 its firings are still in the ledger (history is kept)",
      "shell.exec:deny:a-reader-rule-removed-in-round-65" in rep2["firings"],
      list(rep2["firings"])[:4])

# --- C: a never-fired rule invents nothing ----------------------------------
check("C1 no firing entry is created for an untouched rule",
      "shell.exec:deny:mkfs" not in rep2["firings"], rep2["firings"])

# --- D: the AGENT can read the counters -------------------------------------
info = T.execute("self", {"action": "info"})
pol = info.get("policy") or {}
check("D1 self.info carries a policy block", isinstance(pol, dict) and bool(pol), pol)
check("D2 it agrees with the report",
      pol.get("configured") == 3 and pol.get("fired") == 1
      and pol.get("never_fired") == 2 and pol.get("retired") == 1, pol)
check("D3 it carries no rule text (names live in the endpoint)",
      not any(isinstance(v, list) for v in pol.values()), pol)
check("D4 it says what a never-fired rule is worth",
      "untested" in str(pol.get("note") or ""), pol.get("note"))

# --- E: the REST surface names the retired rules too ------------------------
api = open(os.path.join(REPO, "src", "longrun", "core", "api_v02.py"),
           encoding="utf-8").read()
check("E1 /api/tools still carries the whole report",
      '"rule_firings": registry.policy_report()' in api)

print("\n---\nv1133: %d/%d PASS" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
