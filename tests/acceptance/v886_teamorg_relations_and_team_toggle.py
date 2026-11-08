#!/usr/bin/env python3
"""v886 — a team must end with reporting lines, and a team header must be clickable.

Operator, 2026-11-08:
  *"the icon autogenerate shall animate when running the LLM generating"*
  *"i can't expand by mouse click the teams! expand collapse a single team — it's only
    grabbable"*
  *"I told to generate a team with 3 agents and he generated a research team but with no
    relations (reporting to), it's fundamental. It shall be written in the prompt used by
    the automate agent to create teams/agents; make sure all fields are filled by the
    agents (are mentioned). improve that please in general."*

The live ledger proved the report: run `longrunAgent_run_937b1769` wrote a team + three
agents with ROLE.md prompts and **no** `agent.update` at all — the prompt said the agent
MAY set `reports_to`, so nothing forced it.

Pinned here:
  A) the drag engine only arms click-suppression for TOUCH: a slow mouse click on a
     draggable header is still a click (this is why the team rows never toggled);
  B) the header reads as a disclosure (pointer) while the grip stays the drag handle;
  C) the ✨ pulses in place while the automation runs, and stops in `finally`;
  D) a team creation gets the step budget it actually needs;
  E) the Teamorg prompt REQUIRES the five fields and the reporting line, and still
     forbids models / cycles / out-of-scope managers.

Deterministic: reads the two files + the loaded prompt module, no browser, no network.
"""
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(REPO, "src"))

DRAG = open(os.path.join(REPO, "webui", "assets", "dragsort.js"), encoding="utf-8").read()
ORBIT = open(os.path.join(REPO, "src", "longrun", "orbit", "web", "orbit.html"),
             encoding="utf-8").read()
from longrun.gen import surfaces  # noqa: E402
PROMPT = surfaces.SECTION_PROMPTS["teamorg"]

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""))


# ---- A: a slow mouse click is still a click --------------------------------
hold = DRAG[DRAG.index("state.holdTimer = setTimeout"):DRAG.index("}, HOLD_MS);")]
check("A1 the long press arms the suppression ONLY for touch",
      'if (pointerType !== "touch") return;' in hold
      and hold.index('if (pointerType !== "touch") return;') < hold.index("state.suppressClick = true;"))
check("A2 a real drag still swallows its tail click",
      "state.live = true;\n    state.suppressClick = true;" in DRAG)

# ---- B: the header reads as a disclosure ----------------------------------
check("B1 the group toggle says click, not grab",
      "font:inherit;color:inherit;cursor:pointer;text-align:left}" in ORBIT)
check("B2 the grip is still the grab handle",
      ".rowgrip{display:inline-block;cursor:grab" in ORBIT)
check("B3 the toggle is still the same one control (kebab/assign stop the bubble)",
      'body.querySelectorAll("tr.grp-head .grp-toggle").forEach(h => {' in ORBIT
      and 'body.querySelectorAll("[data-tmadd]").forEach(b => { b.onclick = (ev) => {' in ORBIT
      and 'ev.stopPropagation();' in ORBIT)

# ---- C: the ✨ animates while the LLM runs --------------------------------
run = ORBIT[ORBIT.index("async runTeamorgAutomate(){"):ORBIT.index("async loadReport(open){")]
check("C1 it takes the same in-place pulse as every other ✨",
      'spark.classList.add("gen-busy")' in run and 'spark.setAttribute("aria-busy", "true")' in run)
check("C2 and it is released in finally, not on the happy path only",
      "} finally {" in run
      and 'spark.classList.remove("gen-busy")' in run
      and run.index("} finally {") < run.index('spark.classList.remove("gen-busy")'))

# ---- D: enough steps to finish the creation ------------------------------
check("D1 the run asks for the budget a team needs",
      "max_steps: 10," in run)

# ---- E: the prompt the automation really sends ----------------------------
check("E1 relations are MANDATORY, not optional",
      "RELATIONS ARE PART OF THE CREATION" in PROMPT
      and "INCOMPLETE result" in PROMPT
      and "You MAY set an agent's `reports_to`" not in PROMPT)
check("E2 the five fields are named, in ONE call",
      "ALL FIVE" in PROMPT and "`name`" in PROMPT and "`role`" in PROMPT
      and "`prompt`" in PROMPT and "`team`" in PROMPT and "`reports_to`" in PROMPT
      and "ONE call" in PROMPT)
check("E3 the root rule: the lead is the only agent without a manager",
      "the LEAD is the only agent without a manager" in PROMPT)
check("E4 the old guards survive (models / cycles / scope / empty-only)",
      "NEVER change an agent's model" in PROMPT
      and "never create a cycle" in PROMPT
      and "outside the scope" in PROMPT
      and "context.only_empty" in PROMPT)
check("E5 the budget rule tells it what to do first",
      "do the WRITES FIRST" in PROMPT and "one `team.create`" in PROMPT)

print("---")
passed = sum(results)
print("%d/%d PASS" % (passed, len(results)))
sys.exit(0 if passed == len(results) else 1)
