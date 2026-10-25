#!/usr/bin/env python3
"""v603 (RED) — research answers carry real citations (DeerFlow gap 4).

The researcher role and the research summary prompt must REQUIRE inline
``[title](url)`` citations plus a link-only Sources section — "cited summary"
as a wish is not a contract.

Static, deterministic, no model/browser.
Run: python3 tests/acceptance/v603_research_citations.py
"""
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
ROLES = open(os.path.join(REPO, "config", "subagents.yaml"), encoding="utf-8").read()
RES = open(os.path.join(REPO, "src", "longrun", "research", "research.py"),
           encoding="utf-8").read()

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""))


_role = ROLES.split("researcher:")[1].split("coder:")[0]
_sum = RES.split("final summary via the research LLM")[1].split("tres = ")[0]

check("C1 the researcher role requires inline title(url) citations",
      "](http" in _role or "](url)" in _role, "no citation contract in role")
check("C2 the researcher role requires a link-only Sources section",
      "Sources" in _role)
check("C3 the research summary prompt requires citations",
      "citation" in _sum.lower())
check("C4 no regression (role still read-only, summary still bounded)",
      "Do NOT modify files" in _role and "bullet" in _sum)

print("\n%d/%d" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
