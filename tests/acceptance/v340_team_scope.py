#!/usr/bin/env python3
"""v340 — a selected TEAM scopes the whole board; todos are AX.nY (JAG-339).

Item 5 (user): the team selection on Orbit changes everything (org, chats,
constellation) for that team. Item (naming): the chat todo id is AX.nY, not AX.TY —
`T` is the TEAM namespace, and node ids were already `n1`, `n2`.

Deterministic, no model. Run: python3 tests/acceptance/v340_team_scope.py
"""
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="sf-340-")
os.environ["LONGRUN_AGENTS_FILE"] = os.path.join(TMP, "agents.json")
os.environ["LONGRUN_TEAMS_FILE"] = os.path.join(TMP, "teams.json")
os.environ["LONGRUN_JOBS_FILE"] = os.path.join(TMP, "jobs.json")
os.environ["LONGRUN_SESSIONS_DIR"] = os.path.join(TMP, "sessions")
os.environ["LONGRUN_GRAPH_DIR"] = os.path.join(TMP, "graphs")
os.environ["LONGRUN_DB"] = os.path.join(TMP, "events.db")
os.makedirs(os.environ["LONGRUN_SESSIONS_DIR"], exist_ok=True)
os.makedirs(os.environ["LONGRUN_GRAPH_DIR"], exist_ok=True)
sys.path.insert(0, os.path.join(REPO, "src"))
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.agent import agents  # noqa: E402
from longrun.orchestrate import teams  # noqa: E402
from longrun.orchestrate import jobs  # noqa: E402
from longrun.orbit import api as orbit_api  # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + detail) if detail else ""))


teams.REGISTRY.create("Alpha")
teams.REGISTRY.create("Beta")
a1 = agents.REGISTRY.designate("s1", name="Alpha One")["agent"]
a2 = agents.REGISTRY.designate("s2", name="Beta One")["agent"]
teams.REGISTRY.add_member("T1", a1["id"])
teams.REGISTRY.add_member("T2", a2["id"])
jobs.JOBS.create("alpha work", coordinator=a1["id"], agents=[a1["id"]])
jobs.JOBS.create("beta work", coordinator=a2["id"], agents=[a2["id"]])

allc = orbit_api._constellation("ALL")
check("A1 ALL shows both agents", sorted(x["id"] for x in allc["agents"]) == [a1["id"], a2["id"]])
check("A2 ALL shows both jobs", len(allc["jobs"]) == 2)
check("A3 the payload always lists the teams", len(allc["teams"]) == 2)
check("A4 each agent carries its teams", allc["agents"][0]["teams"] in (["T1"], ["T2"]))

t1c = orbit_api._constellation("T1")
check("B1 a team scopes the agents", [x["id"] for x in t1c["agents"]] == [a1["id"]])
check("B2 a team scopes the jobs", len(t1c["jobs"]) == 1 and t1c["jobs"][0]["agents"] == [a1["id"]])
check("B3 the payload echoes the selected team", t1c["team"] == "T1")

# --- C: the todo id is AX.nY in both GUIs -----------------------------------
html = open(os.path.join(REPO, "webui", "index.html"), encoding="utf-8").read()
check("C1 the main app renders AX.nY", '(y ? ".n" + y : "")' in html and '".T" + y' not in html)
check("C2 the docstring no longer claims AX.TY", "AX.nY is its todo Y" in html)
orbit = open(os.path.join(REPO, "src", "longrun", "orbit", "web", "orbit.html"), encoding="utf-8").read()
check("C3 Orbit renders AX.nY everywhere (label + SVG node text + hint)",
      '".n" + String(node.id)' in orbit          # the popover label
      and "'.n' + esc(y)" in orbit               # the SVG node text (JAG-342 miss)
      and "'.T'" not in orbit and '".T"' not in orbit
      and ".TY" not in orbit and ".TX" not in orbit)
check("C4 Orbit has a team selector that scopes the board",
      'id="teamSel"' in orbit and "renderTeams" in orbit and "inTeam" in orbit)

# --- D: an EMPTY team is assignable and visible (live bug, 2026-10-22) --------
# Operator: "i cant add agents to a team, i created a new team and where are the
# list of agents that can be assigned?" — an empty team was filtered OUT of the
# grouped table (`if (ms.length)`), so a brand-new team rendered nothing and the
# only membership picker lived on an agent row that did not exist.
check("D1 a team with zero agents is still rendered when it is the scoped team",
      "if (ms.length || scoped(t.id))" in orbit and 'this.scope = "ALL"' in orbit)
check("D2 every team header can assign agents (＋ assign -> full-roster picker)",
      "data-tmadd=" in orbit and "openAssignPicker" in orbit
      and "this.roster && this.roster.length" in orbit)
check("D3 the assign picker stays open for a multi-select",
      "setTeamMembership(cb.dataset.asg, tid, cb.checked, true)" in orbit
      and "keepOpen" in orbit)
check("D4 an empty team says HOW to fill it instead of a blank panel",
      "no agents in this team yet" in orbit)
check("D5 the panel states its boundary: agents are DESIGNATED sessions",
      'id="agHint"' in orbit and "designated agents only" in orbit)

print("---")
ok = sum(1 for r in results if r)
print("%d/%d PASS" % (ok, len(results)))
sys.exit(0 if ok == len(results) else 1)

