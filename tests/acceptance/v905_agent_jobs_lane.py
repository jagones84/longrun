#!/usr/bin/env python3
"""v905 — the constellation draws the RELATIONS that exist, in the view you opened.

Operator: *"no vedo in constellation i jobs solo i tasks"*, then, looking at the
first attempt: *"usa la logica e le relazioni effettive che esistono tra i vari
oggetti informatici (job, agenti, todos) per creare artefatti visivi corretti e
completi"*.

The object model the deck must draw (one drawing per relation, no repeats):

  Job JN  --contains-->  Subjob JN.j  --assigned to-->  Agent AX
  Job JN  --coordinated by-->  Agent AX
  Subjob JN.j  --holds N tasks-->  {A.nY…}       (a COUNT, not N arrows)
  Task  --depends on-->  Task                    (the chain the operator reads)
  Task  --belongs to-->  Plan P                  (a job opens a FRESH plan)

What was wrong: AGENT mode dropped job/subjob entirely (v905), then drew one
arrow per task (J30.1 → 5 tasks) which buried the dependency chain, and it mixed
the CURRENT plan with the older history — A179's n1..n3 come from a previous
chat turn (no jid/subjob), yet they sat next to the job's n4..n8 as one plan.

Deterministic, source-level (the rendered deck is checked live). Run:
python3 tests/acceptance/v905_agent_jobs_lane.py
"""
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DECK = os.path.join(REPO, "src", "longrun", "orbit", "web", "orbit.html")
API = os.path.join(REPO, "src", "longrun", "orbit", "api.py")

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""))


with open(DECK, encoding="utf-8") as f:
    SRC = f.read()
with open(API, encoding="utf-8") as f:
    API_SRC = f.read()


def block(start, end):
    i = SRC.find(start)
    if i < 0:
        return ""
    j = SRC.find(end, i + len(start))
    return SRC[i:(j if j > 0 else len(SRC))]


AGENT = block("_drawAgent(){", "_drawAll(){")
ALL = block("_drawAll(){", "_wire(svg){")
PILLS = block("_pills(jobs, subs, jpos, spos, opts){", "_drawAll(){")
WIRE = block("_wire(svg){", "_pop(){")
PLAN = block("_planOf(sid){", "_drawAgent(){")

# ---- A) ONE agent focused: the job/subjob level is there -------------------
check("A1 the focused agent's subjobs are selected from the payload",
      "subjobs" in AGENT and "s.agent === a.id" in AGENT)
check("A2 the jobs come from the subjobs AND the tasks' jid",
      "normJ" in AGENT and "n.jid" in AGENT)
check("A3 both lanes exist in AGENT mode", "jpos" in AGENT and "spos" in AGENT)
check("A4 the task grid is pushed down by the lane (no overlap)",
      "46 + lane" in AGENT and "const lane" in AGENT)
check("A5 the AGENT view draws the pills, marked as the owner of its own job",
      "this._pills(jobs, subs, jpos, spos, {owner: a.id, counts: true})" in AGENT)
check("A6 a job is drawn above its subjobs",
      "q.y + 15" in AGENT and "p.y - 12" in AGENT)
check("A7 subjob DEPENDENCIES are drawn between the pills (a real relation)",
      "(s.deps || [])" in AGENT and 'class="clink dep"' in AGENT)
check("A8 no tasks and no subjobs is still an honest empty state",
      "if (!nodes.length && !subs.length)" in AGENT)
check("A9 the header names the jobs and subjobs in scope",
      "job\" + (jobs.length > 1" in AGENT and "subjob\" + (subs.length > 1" in AGENT)

# ---- B) the relations that are NOT arrows ---------------------------------
check("B1 subjob -> N tasks is a COUNT, not one arrow per task",
      "(q.todos || []).length" in PILLS and "(s.todos || []).forEach" not in AGENT)
check("B2 the count only appears in AGENT mode (ALL already has the cluster edge)",
      "opts.counts && n" in PILLS)
check("B3 the job pill names the coordinator's ownership instead of inventing an arrow",
      "j.coordinator === opts.owner" in PILLS and "·coord" in PILLS)
check("B4 the pill geometry follows its label (no clipped text)",
      "lbl.length * 6.6 + 16" in PILLS and "lbl.length * 7 + 18" in PILLS)
check("B5 the pill markup has ONE owner",
      SRC.count('class="cjobg"') == 1 and SRC.count('class="csubg"') == 1)
check("B6 both modes draw through it", SRC.count("this._pills(") == 2, SRC.count("this._pills("))

# ---- C) a PLAN is the unit of work ---------------------------------------
check("C1 the deck can tell the current plan from the history",
      "_planOf(sid){" in SRC and "n.plan == null ? 1 : n.plan" in PLAN)
check("C2 the AGENT view draws the current plan only", "_planOf(a.session)" in AGENT)
check("C3 the ALL view filters each cluster the same way", "_planOf(a.session)" in ALL)
check("C4 the footer says how many older steps are NOT drawn",
      "older step(s) not drawn" in AGENT and "older step(s) not drawn" in ALL)
check("C5 the payload carries the current plan number",
      '"plan": g.get("plan")' in API_SRC)
check("C6 the plan groups the rail shows come from the same field",
      '"plan"' in API_SRC and "run_id" in API_SRC)
check("C7 an older step the current plan DEPENDS on is kept (never dropped)",
      "frontier" in PLAN and "(n.deps || []).forEach" in PLAN)
check("C8 a kept prerequisite is marked, not disguised as current work",
      "const cold = new Set" in PLAN and ".cnode.cold circle" in SRC
      and "prerequisite" in AGENT)

# ---- D) the click still reveals what is not drawn ------------------------
check("D1 a subjob popover lists the tasks it holds",
      "(s.todos && s.todos.length)" in SRC and "todos</span>" in SRC)
check("D2 a job pill lists its subjobs",
      "subjobs</span>" in SRC)
check("D3 job pills are clickable in either mode", ".cjobg" in WIRE and "extractJob" in WIRE)
check("D4 subjob pills are clickable in either mode", ".csubg" in WIRE and "extractSub" in WIRE)

# ---- E) the payload carries what the deck draws --------------------------
check("E1 the payload carries each subjob's todos",
      '"todos": [n.get("id") for n in mine]' in API_SRC)
check("E2 the payload carries the subjob's status and deps",
      '"deps": s.get("deps") or []' in API_SRC and '"status": s.get("status")' in API_SRC)
check("E3 the old 'tasks only' detail line is gone",
      '.nY · dashed arrow = dependency"' not in SRC)

print("\n%d/%d checks passed" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
