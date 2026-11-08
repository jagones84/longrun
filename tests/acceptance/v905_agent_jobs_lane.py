#!/usr/bin/env python3
"""v905 — the constellation shows the job/subjob level when ONE agent is focused.

Operator: *"no vedo in constellation i jobs solo i tasks"* — with the deck on the
AGENT tab, the diagram drew only `A84.n1 … A84.n8`. The legend under the diagram
(the same in both tabs) already promised jobs and subjobs, and ALL mode drew them:
`_drawAgent` never asked the payload for the level above the tasks.

Now AGENT mode draws the SAME object model above one agent's grid: its jobs
(amber), its subjobs (blue), job → subjob, and subjob → the tasks it embraces
(its `todos`), so `J30` / `J30.3 → A88` are visible without switching tabs.

The pill markup lives in ONE function (`_pills`) used by both modes — the two
views cannot drift into two drawings of the same object.

Deterministic, source-level (a rendered check is done live). Run:
python3 tests/acceptance/v905_agent_jobs_lane.py
"""
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DECK = os.path.join(REPO, "src", "longrun", "orbit", "web", "orbit.html")

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""))


with open(DECK, encoding="utf-8") as f:
    SRC = f.read()


def block(start, end):
    i = SRC.find(start)
    if i < 0:
        return ""
    j = SRC.find(end, i + len(start))
    return SRC[i:(j if j > 0 else len(SRC))]


AGENT = block("_drawAgent(){", "_drawAll(){")
ALL = block("_drawAll(){", "_wire(svg){")
PILLS = block("_pills(jobs, subs, jpos, spos){", "_drawAll(){")
if not PILLS:                                   # _pills sits between the two modes
    PILLS = block("_pills(jobs, subs, jpos, spos){", "_wire(svg){")

# ---- A) the AGENT view asks for the level it used to drop -------------------
check("A1 the focused agent's subjobs are selected from the payload",
      "subjobs" in AGENT and "s.agent === a.id" in AGENT)
check("A2 the jobs come from the subjobs AND the tasks' jid",
      "normJ" in AGENT and "n.jid" in AGENT)
check("A3 both lanes exist in AGENT mode",
      "jpos" in AGENT and "spos" in AGENT)
check("A4 the task grid is pushed down by the lane (no overlap)",
      "46 + lane" in AGENT and "const lane" in AGENT)
check("A5 the AGENT view draws the pills",
      "this._pills(jobs, subs, jpos, spos)" in AGENT)
check("A6 a job is drawn above its subjobs",
      "q.y + 15" in AGENT and "p.y - 12" in AGENT)
check("A7 a subjob is linked to the tasks it embraces",
      "(s.todos || [])" in AGENT and "class=\"clink assign\"" in AGENT)
check("A8 no tasks and no subjobs is still an honest empty state",
      "if (!nodes.length && !subs.length)" in AGENT)
check("A9 the header names the jobs and subjobs in scope",
      "job\" + (jobs.length > 1" in AGENT and "subjob\" + (subs.length > 1" in AGENT)
check("A10 the detail line explains the amber/blue lanes",
      "amber = JOB" in AGENT and "blue = SUBJOB" in AGENT)

# ---- B) ONE drawing of the pills, used by both modes ----------------------
check("B1 the pill markup has one owner", "class=\"cjobg\"" in PILLS and "class=\"csubg\"" in PILLS)
check("B2 the file contains the job pill ONCE", SRC.count('class="cjobg"') == 1,
      SRC.count('class="cjobg"'))
check("B3 the file contains the subjob pill ONCE", SRC.count('class="csubg"') == 1,
      SRC.count('class="csubg"'))
check("B4 both modes draw through it", SRC.count("this._pills(") == 2, SRC.count("this._pills("))
check("B5 ALL mode still draws its lanes", "this._pills(jobs, subs, jpos, spos)" in ALL)

# ---- C) the click / popover wiring still sees the pills -------------------
WIRE = block("_wire(svg){", "_pop(){")
check("C1 job pills are clickable in either mode", '.cjobg' in WIRE and "extractJob" in WIRE)
check("C2 subjob pills are clickable in either mode", '.csubg' in WIRE and "extractSub" in WIRE)

# ---- D) the payload carries what the deck now draws ----------------------
API = os.path.join(REPO, "src", "longrun", "orbit", "api.py")
with open(API, encoding="utf-8") as f:
    api = f.read()
check("D1 the payload carries each subjob's todos", '"todos": [n.get("id") for n in mine]' in api)
check("D2 the payload carries the subjob's status and deps",
      '"deps": s.get("deps") or []' in api and '"status": s.get("status")' in api)
check("D3 the old 'tasks only' detail line is gone",
      '.nY · dashed arrow = dependency"' not in SRC)

print("\n%d/%d checks passed" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
