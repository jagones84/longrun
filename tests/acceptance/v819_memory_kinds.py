#!/usr/bin/env python3
"""v819 — a durable USER PREFERENCE and an OPEN QUESTION are first-class memory.

The Oracle memory talk names two kinds an agent memory needs beyond facts and
lessons: a durable *preference* (how this operator wants the work done) and the
*unanswered question* (episodic memory of what was asked and never closed). Longrun
had neither: `MEMORY_FIELDS` held telemetry + `memory.store` only, and the prompt
injected facts/lessons/core.

  A) both kinds round-trip through the store and are queryable by kind;
  B) the prompt renders them in labelled buckets, with the user's preferences
     grouped under the "user facts" trust label;
  C) the CORE block comes FIRST, so the truncation tail is never the
     always-visible block;
  D) closing an open question removes it from the prompt (ordinary lifecycle);
  E) the `memory` tool documents the kinds.

Deterministic, no live model, no network, no server.
"""
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="sf-v819-")
os.environ["LONGRUN_CONFIG_DIR"] = os.path.join(TMP, "cfg")
os.environ["LONGRUN_DATA_DIR"] = os.path.join(TMP, "data")
os.environ["LONGRUN_DB"] = os.path.join(TMP, "events.db")
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.core import server                 # noqa: E402,F401 — breaks the import cycle
from longrun.memory import memory               # noqa: E402
from longrun.model import prompt                # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""))


PREF_A = "always answer in English and keep the reply short"
PREF_B = "never commit without asking the operator first"
Q_TEXT = "which router alias serves the 256k window"
CORE = "the deploy target is the dgx spark box"

memory.core_write(CORE)
r1 = memory.store("user.preference", PREF_A, origin="user")
memory.store("user.preference", PREF_B, origin="user")
rq = memory.store("question.open", Q_TEXT, origin="agent")

# --------------------------------------------------------- A. the two kinds ----
prefs = memory.query(None, "user.preference", 50)
check("A1 a preference is stored under its own kind",
      len(prefs) == 2 and all(p.get("kind") == "user.preference" for p in prefs),
      [p.get("kind") for p in prefs])
qs = memory.governed_query(kind="question.open", limit=5)
check("A2 the open question is recalled by kind",
      len(qs) == 1 and Q_TEXT in qs[0].get("content", ""), qs)
check("A3 each kind has its own file",
      os.path.basename(memory._path("user.preference")) == "user_preferences.md" and
      os.path.basename(memory._path("question.open")) == "open_questions.md")

# ------------------------------------------------------------- B. the prompt ----
blk = prompt._provider_memory(None, None, None)
check("B1 the user-facts bucket is present (label kept)", "user facts" in blk, blk[:120])
check("B2 a preference is injected", PREF_A[:40] in blk, blk)
check("B3 the open-questions bucket is present", "open questions" in blk, blk)
check("B4 the open question is injected", Q_TEXT[:40] in blk, blk)
check("B5 the core memory is injected", CORE in blk, blk)

# ---------------------------------------------------------- C. core comes first -
check("C1 the CORE block is not the truncation tail",
      0 <= blk.find("Core memory") < blk.find("user facts"), blk[:80])

# ------------------------------------------------------------- D. the lifecycle -
memory.invalidate(rq["mid"], reason="answered in the following turn")
blk2 = prompt._provider_memory(None, None, None)
check("D1 a closed question leaves the prompt", Q_TEXT not in blk2, blk2)
check("D2 the preference is untouched", PREF_A[:40] in blk2)

# ---------------------------------------------------------------- E. the tool ---
tools_src = open(os.path.join(REPO, "src", "longrun", "tools", "tools.py"),
                 encoding="utf-8").read()
check("E1 the memory tool documents the kinds",
      "user.preference" in tools_src and "question.open" in tools_src)

# ------------------------------------------------- F. the CORE is never cut ------
# The cap used to be applied to the JOINED block, so a core larger than the cap was
# truncated along with everything else (found in independent review 2026-11-05).
BIG = "K" * 1500
memory.core_write(BIG)
blk3 = prompt._provider_memory(None, None, None)
check("F1 a CORE block larger than the cap is never cut", BIG in blk3, len(blk3))
check("F2 and it is still the FIRST part of the section",
      blk3.startswith("## Core memory"), blk3[:40])

# ------------------------------------- G. the segregation buckets still add up ---
prov = memory.provenance()
check("G1 a preference counts as USER knowledge", prov["user"] == 2, prov)
check("G2 auto + user + other == total (nothing silently uncounted)",
      prov["auto"] + prov["user"] + prov["other"] == prov["total"], prov)

print("---")
passed = sum(results)
print("%d/%d PASS" % (passed, len(results)))
sys.exit(0 if passed == len(results) else 1)
