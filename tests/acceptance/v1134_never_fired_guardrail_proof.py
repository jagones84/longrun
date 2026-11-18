#!/usr/bin/env python3
"""v1134 — a never-fired guardrail names the test that proves it, or says it has none.

Round 68 (arXiv:2611.15223 guardscope — a control is checked, bypassed or
prevented). Round 67 made `policy_report()` reconcile with the policy; it still
reported two rules that had NEVER fired and said nothing else:

  fs.edit:deny:(^|/)\\.env(\\.(?!template$)[^/]*)?$
  shell.exec:deny:>\\s*/dev/(sd|nvme|mmcblk)

"Never fired" is not a verdict: the rule may be dead, or simply unexercised — and
the operator cannot tell which from a list of names. A guardrail now carries its
PROOF beside it (`{pattern, why, proof: <test id>}` in `config/tools.yaml`), and
the report separates the two states:

  never_fired            — no firing in the ledger
  never_fired_proof      — {rule: test id} for the ones a test proves
  never_fired_unproven   — the residue: unexercised AND unproven

  A  the two live never-fired rules carry a proof id
  B  this test IS that proof: both rules deny the action they exist for
  C  the id resolves to a real acceptance test
  D  a never-fired rule WITH a proof is not "unproven"
  E  a never-fired rule WITHOUT one is named as unproven
  F  the AGENT sees the residue count

Deterministic: config + registry (+ `self.info`); no server, no model, no network.
Run: python3 tests/acceptance/v1134_never_fired_guardrail_proof.py
"""
import glob
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="sf-v1134-")
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


SELF_ID = "v1134_never_fired_guardrail_proof"

# --- A: the two live never-fired rules carry a proof -------------------------
fs_edit = registry.tool_spec("fs.edit")
shell = registry.tool_spec("shell.exec")
env_pat = "(^|/)\\.env(\\.(?!template$)[^/]*)?$"
dev_pat = ">\\s*/dev/(sd|nvme|mmcblk)"
check("A1 the fs.edit env rule names its proof",
      (fs_edit.get("deny_proof") or {}).get(env_pat) == SELF_ID,
      fs_edit.get("deny_proof"))
check("A2 the block-device rule names its proof",
      (shell.get("deny_proof") or {}).get(dev_pat) == SELF_ID,
      shell.get("deny_proof"))
check("A3 a proof travels beside the pattern it belongs to",
      env_pat in (fs_edit.get("deny") or []) and dev_pat in (shell.get("deny") or []),
      (fs_edit.get("deny"), shell.get("deny")))

# --- B: this test is the proof ----------------------------------------------
d1, why1 = registry.classify("fs.edit", {"path": os.path.join(REPO, ".env"),
                                         "old": "a", "new": "b"})
check("B1 fs.edit of the env file is denied", d1 == "denied", (d1, why1))
d2, why2 = registry.classify("shell.exec", {"command": "echo x > /dev/sda"})
check("B2 writing to a block device is denied", d2 == "denied", (d2, why2))
d3, why3 = registry.classify("shell.exec", {"command": "echo x > /dev/null"})
check("B3 a write to /dev/null is not the same object", d3 != "denied", (d3, why3))
d4, why4 = registry.classify("fs.edit", {"path": os.path.join(REPO, ".env.template"),
                                         "old": "a", "new": "b"})
check("B4 the template stays editable", d4 != "denied", (d4, why4))

# --- C: the id resolves to a real test --------------------------------------
here = os.path.basename(os.path.abspath(__file__))
check("C1 the proof id names THIS test", here.startswith(SELF_ID), here)
check("C2 and the file exists in the acceptance suite",
      bool(glob.glob(os.path.join(REPO, "tests", "acceptance", SELF_ID + "*.py"))))

# --- D/E: a never-fired rule is proven or unproven --------------------------
PROVEN = {"tools": {"shell.exec": {"enabled": True, "approval": "auto",
                                   "deny": [{"pattern": "PROVEN-NEVER-FIRES",
                                             "proof": SELF_ID}]}},
          "approvals": {"mode": "normal"}}
registry.load_config = lambda reload=False: PROVEN
rep = registry.policy_report()
check("D1 a rule with a proof is still never-fired",
      rep["never_fired"] == ["shell.exec:deny:PROVEN-NEVER-FIRES"], rep["never_fired"])
check("D2 but it is NOT in the unproven residue",
      rep["never_fired_unproven"] == [], rep["never_fired_unproven"])
check("D3 and its proof is named in the report",
      rep["never_fired_proof"] == {"shell.exec:deny:PROVEN-NEVER-FIRES": SELF_ID},
      rep["never_fired_proof"])

UNPROVEN = {"tools": {"shell.exec": {"enabled": True, "approval": "auto",
                                     "deny": ["RAN-ONCE", "NEVER-RAN"]}},
            "approvals": {"mode": "normal"}}
registry.load_config = lambda reload=False: UNPROVEN
registry.classify("shell.exec", {"command": "RAN-ONCE"})
rep2 = registry.policy_report()
check("E1 the firing rule is counted", rep2["fired_rules"] == 1, rep2)
check("E2 the unexercised rule with no proof is named",
      rep2["never_fired_unproven"] == ["shell.exec:deny:NEVER-RAN"],
      rep2["never_fired_unproven"])
check("E3 and the proof map stays empty",
      rep2["never_fired_proof"] == {}, rep2["never_fired_proof"])

# --- F: the AGENT sees the residue ------------------------------------------
info = T.execute("self", {"action": "info"})
pol = info.get("policy") or {}
check("F1 self.info counts the unproven residue",
      pol.get("unproven") == 1 and pol.get("never_fired") == 1, pol)
check("F2 its note says a test is what makes a rule proven",
      "test proves" in str(pol.get("note") or ""), pol.get("note"))

print("\n---\nv1134: %d/%d PASS" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
