#!/usr/bin/env python3
"""v936 — a skill that was SHOWN is not a skill that was OPENED (RSI-G-1/G-2).

The ledger collapsed two different facts into one: `skills.note_opened` wrote the
same id as injected AND used, so `uses == helped` always held and the retirement
question ("was this skill ever reached?") could not be answered. Now:

  * a search records the hit as RETRIEVED (injected, not used);
  * a read records it as OPENED (injected and used);
  * `discovery()` reports both maps, and its own probe stays read-only.

Deterministic, no model, no network, no server.

Run: python3 tests/acceptance/v936_skill_retrieved_vs_opened.py
"""
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="sf-v936-")
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

from longrun.memory import skills as S  # noqa: E402
from longrun.memory import attribution as ATTR  # noqa: E402
from longrun.tools import tools as T  # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""))


def _rec(name):
    return ATTR.stats("skill:" + name)


d = S.discovery()
check("A1 a fresh library has retrieved nothing",
      not d.get("retrieved") and not d.get("opened"), d)
check("A2 both skills are never opened", len(d["never_opened"]) == 2, d["never_opened"])

# --- one SEARCH is a retrieval, not an open --------------------------------
out = T._skills({"action": "search", "query": "deploy a service to staging"}, None)
check("B0 the search reached the skill", "deploy-a-service" in (out.get("matches") or []), out)
d = S.discovery()
check("B1 the search recorded one retrieval", d["retrieved"].get("deploy-a-service") == 1, d)
check("B2 a retrieval is NOT an open", not d["opened"].get("deploy-a-service"), d["opened"])
check("B3 it stays in never_opened", "deploy-a-service" in d["never_opened"], d["never_opened"])
rec = _rec("deploy-a-service")
check("B4 the ledger keeps the two counters apart (uses=1, helped=0)",
      rec.get("uses") == 1 and not rec.get("helped"), rec)

# --- one READ is an open ---------------------------------------------------
T._skills({"action": "read", "name": "deploy-a-service"}, None)
d = S.discovery()
check("C1 the read recorded the open", d["opened"].get("deploy-a-service") == 1, d["opened"])
check("C2 opening moves it out of never_opened",
      "deploy-a-service" not in d["never_opened"], d["never_opened"])
rec = _rec("deploy-a-service")
check("C3 the ledger now reads uses=2, helped=1",
      rec.get("uses") == 2 and rec.get("helped") == 1, rec)

# --- the discovery probe is read-only --------------------------------------
before = dict(S.discovery()["retrieved"])
S.discovery(samples=["deploy a service to staging", "brewing espresso"])
after = dict(S.discovery()["retrieved"])
check("D1 the probe does not mutate the retrieval ledger", before == after, (before, after))

# --- a skill nobody reached is in neither map ------------------------------
check("E1 the untouched skill was never retrieved or opened",
      not S.discovery()["retrieved"].get("invoice-template")
      and not S.discovery()["opened"].get("invoice-template"))

print("---")
print("%d/%d PASS" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
