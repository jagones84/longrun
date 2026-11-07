#!/usr/bin/env python3
"""v848 — is a skill REACHABLE, and was it ever opened? (HA-2, lot H)

`audit_skills` reports library hygiene (duplicate descriptions, oversized bodies).
It cannot say whether the model ever SELECTS a skill from its description —
the only thing that decides it while the skill is idle — nor whether a skill was
ever opened. This adds one signal to the ledger the harness already keeps
(`memory/attribution.py`) and one offline probe using the SAME ranker as the tool.

  A) a fresh library reports every skill as never opened;
  B) opening one is recorded and moves it out of `never_opened`;
  C) a plain-language task reaches the right skill; an unrelated one reaches none;
  D) a skill without a description is named;
  E) the ledger is the shared attribution file (no second store);
  F) `GET /api/skills` carries the discovery block.

Deterministic, no live model, no network, no server.
"""
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="sf-v848-")
SKILLS = os.path.join(TMP, "skills")
os.environ["LONGRUN_SKILLS_DIR"] = SKILLS
os.environ["LONGRUN_DATA_DIR"] = os.path.join(TMP, "data")
os.environ["LONGRUN_CONFIG_DIR"] = os.path.join(TMP, "config")
os.environ["LONGRUN_MEMORY_ATTRIBUTION"] = os.path.join(TMP, "attr.json")
sys.path.insert(0, os.path.join(REPO, "src"))


def skill(cat, name, body):
    d = os.path.join(SKILLS, cat, name)
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, "SKILL.md"), "w", encoding="utf-8") as fh:
        fh.write(body)


skill("ops", "deploy-a-service",
      "---\nname: deploy-a-service\ndescription: Deploy a service to staging with "
      "the release checklist and the rollback steps.\n---\n\n# Deploy\n\nRun the checklist.\n")
skill("ops", "invoice-template",
      "---\nname: invoice-template\ndescription: Fill the monthly invoice template "
      "for a client and export the PDF.\n---\n\n# Invoice\n\nUse the template.\n")
skill("ops", "nameless",
      "---\nname: nameless\n---\n\n# Nameless\n")

from longrun.memory import skills as S  # noqa: E402
from longrun.tools import tools as T  # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""))


d = S.discovery()
check("A1 every fixture is listed", d["skills"] == 3, d["skills"])
check("A2 a fresh library has been opened zero times",
      set(d["never_opened"]) == {"deploy-a-service", "invoice-template", "nameless"},
      d["never_opened"])

S.note_opened("deploy-a-service")
d = S.discovery()
check("B1 an open is recorded", d["opened"].get("deploy-a-service") == 1, d["opened"])
check("B2 it leaves never_opened", "deploy-a-service" not in d["never_opened"],
      d["never_opened"])
check("B3 the untouched one stays", "invoice-template" in d["never_opened"],
      d["never_opened"])

probe = S.discovery(samples=["deploy a service to staging", "brewing espresso"])
check("C1 a matching task reaches the skill",
      probe["probes"][0]["found"] and probe["probes"][0]["hits"][0] == "deploy-a-service",
      probe["probes"][0])
check("C2 an unrelated task reaches none", probe["probes"][1]["found"] is False,
      probe["probes"][1])
check("D1 a skill without a description is named",
      d["missing_description"] == ["nameless"], d["missing_description"])

ledger = os.environ["LONGRUN_MEMORY_ATTRIBUTION"]
body = open(ledger, encoding="utf-8").read() if os.path.isfile(ledger) else ""
check("E1 the open lives in the shared attribution ledger",
      "skill:deploy-a-service" in body, ledger)

# the model-facing tool uses the same recorder
T._skills({"action": "read", "name": "invoice-template"}, None)
d2 = S.discovery()
check("F1 reading through the tool records the open",
      d2["opened"].get("invoice-template") == 1, d2["opened"])

src = open(os.path.join(REPO, "src", "longrun", "core", "api_v02.py"), encoding="utf-8").read()
check("G1 GET /api/skills carries the discovery block", '"discovery": disc' in src)

print("---")
passed = sum(results)
print("%d/%d PASS" % (passed, len(results)))
sys.exit(0 if passed == len(results) else 1)
