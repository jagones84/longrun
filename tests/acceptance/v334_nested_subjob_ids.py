#!/usr/bin/env python3
"""v334 — subjob ids NEST with the org depth: JN.j, then JN.j.x, … (JAG-334).

A subjob handed out by the agent that RECEIVED a subjob must nest one level deeper
(`J8.2` -> `J8.2.1`), so the numbering mirrors the organigram depth of the receiving
session. `subjob_id` + `plan_subjobs(parent_sub=…)` implement it.

Deterministic, no model. Run: python3 tests/acceptance/v334_nested_subjob_ids.py
"""
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="sf-334-")
os.environ["LONGRUN_JOBS_FILE"] = os.path.join(TMP, "jobs.json")
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.orchestrate.jobs import plan_subjobs, subjob_id  # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + detail) if detail else ""))


check("A1 a top-level subjob is JN.j", subjob_id("J8", 1) == "J8.1")
check("A2 a nested subjob appends a level", subjob_id("J8", 2, "J8.1") == "J8.1.2")
check("A3 a two-deep nested id keeps nesting", subjob_id("J8", 3, "J8.1.2") == "J8.1.2.3")

subs = plan_subjobs("J8", ["A9", "A11"], "A8", "- A9: a\n- A11: b (after A9)",
                    {"A11": ["A9"]}, parent_sub="J8.1")
check("B1 nested plan_subjobs id the children under the parent subjob",
      set(subs) == {"J8.1.1", "J8.1.2"}, str(sorted(subs)))
check("B2 each nested subjob records its parent_sub",
      all(s.get("parent_sub") == "J8.1" for s in subs.values()))
check("B3 each nested subjob still records the job as `parent`",
      all(s.get("parent") == "J8" for s in subs.values()))
check("B4 nested deps reference the nested ids (not the flat ones)",
      subs["J8.1.2"]["deps"] == ["J8.1.1"], str({k: v["deps"] for k, v in subs.items()}))

with open(os.path.join(REPO, "src", "longrun", "orchestrate/jobs.py"), encoding="utf-8") as f:
    src = f.read()
check("C1 plan_subjobs accepts parent_sub (v629: and an org `tree`)",
      "def plan_subjobs(jid, agents, coord, plan, deps, parent_sub=None, tree=None)" in src)
check("C2 the id builder nests", "def subjob_id(jid, n, parent_sub=None)" in src)

print("---")
ok = sum(1 for r in results if r)
print("%d/%d PASS" % (ok, len(results)))
sys.exit(0 if ok == len(results) else 1)

