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
      # v658: the two ideas were one predicate before (`scoped` also meant "ALL"), so
      # under a team scope EVERY team counted as scoped and the other teams' groups
      # came back (operator: "se filtro per team mi appaiono altri team"). They are
      # two predicates now: `visible` (in the view) gates the group, `selected`
      # (IS the scope) is the only reason to render an EMPTY one.
      "if (ms.length || selected(t.id))" in orbit
      and "const selected = id => scope === id;" in orbit
      and 'this.scope = "ALL"' in orbit)
check("D2 every team header can assign agents (＋ assign -> full-roster picker)",
      "data-tmadd=" in orbit and "openAssignPicker" in orbit
      and "this.roster && this.roster.length" in orbit)
check("D3 the assign picker stays open for a multi-select",
      "setTeamMembership(cb.dataset.asg, tid, cb.checked, true)" in orbit
      and "keepOpen" in orbit)
check("D4 an empty team says HOW to fill it instead of a blank panel",
      "no agents in this team yet" in orbit)
check("D5 the panel states the roster in full (sessions without an agent id)",
      'id="agHint"' in orbit and "without an agent id" in orbit)

# --- E: a PLAIN session is listed and assignable (live complaint, 2026-10-22) --
# Operator: "in agents no teams ... non ci sono delle sessioni del sessions page ...
# tipo kb test ... non sono sincronizzate". Control must show the SAME roster as the
# Sessions page, and assigning a chat that was never designated must work instead of
# dead-ending: the server designates it on the spot (title -> agent name).
from longrun.core import server as _server  # noqa: E402
from longrun.orchestrate import orchestration as orch  # noqa: E402

_server.save_session({"id": "s_plain_kb", "title": "kb test", "messages": []})
aid, err = orch.member_aid(agents.REGISTRY, "s_plain_kb")
check("E1 a plain session gets an agent id on demand (title becomes the name)",
      bool(aid) and not err
      and (agents.REGISTRY.get("s_plain_kb") or {}).get("name") == "kb test",
      "%s | %s" % (aid, err))
added = teams.REGISTRY.add_member("T1", aid)
check("E2 that new agent can then join a team",
      added.get("ok") is True and aid in (teams.REGISTRY.get("T1") or {}).get("members", []))
missing, merr = orch.member_aid(agents.REGISTRY, "no_such_session")
check("E3 an unknown session is refused (never a silent no-op)",
      missing is None and "unknown session" in str(merr))
check("E4 the members route designates on demand instead of answering 'required'",
      "aid, err = member_aid(reg, data.get(\"agent\") or data.get(\"session\"))"
      in open(os.path.join(REPO, "src", "longrun", "orchestrate",
                           "orchestration.py"), encoding="utf-8").read())
check("E5 Control lists EVERY session (designated + plain) and posts a session ref",
      "designated.concat(extras)" in orbit and "undesignated: true" in orbit
      and 'data-asg="\' + esc(a.session)' in orbit
      and '{session: ref, action:' in orbit)

# --- F: keyboard-reachable menus (live complaint, 2026-10-22) ----------------
# Operator: "the menu bars in AGENTS panel, report to, model search do not go to item
# by keyboard, example pressing ab shall go to agents starting name ab". A native
# <select> type-ahead matches the option TEXT PREFIX only, and the agent options led
# with the A-id ("A8 Master"), so typing a NAME hit nothing. And the deck's popovers
# were click-only: no arrow keys, no Enter.
check("F1 the Reports-to / assign options lead with the NAME, then the A-id",
      "esc(x.name || x.id) + ' · ' + esc(x.id)" in orbit
      and "esc(a.name || a.id) +\n      ' · ' + esc(a.id)" in orbit)
check("F2 every popover is keyboard navigable (arrows + Enter + Escape)",
      "function _popoverKeys" in orbit and "_popoverKeys(m)" in orbit
      and "ArrowDown" in orbit and "if (m.__nav) m.removeEventListener" in orbit)
check("F3 keyboard browsing in a select does not write on every keystroke",
      # A native <select> commits on every change and type-ahead fires one per key:
      # typing "m" instantly WROTE a model and tripped the team local-model guard.
      # Keyboard changes are browsing; the write happens on Enter or blur.
      "el.__browse = true" in orbit and "if (el.__browse) return;" in orbit
      and "el.onblur = () => {" in orbit)

# --- G: a VOID prompt is visible, and the lead leads (JAG-2.8) ---------------
# Operator: "if in AGENTS panel the prompt is void, highlight the prompt button
# somehow with an asterisk red of warning"; and "in sessions, in teams, the
# orchestrator agents shall be up in the display order".
from longrun.core import server as _srv  # noqa: E402
from longrun.orchestrate import roles as roles_mod  # noqa: E402

_srv.get_or_create_session("sess-void", title="Void Bot")
roles_mod.delete("sess-void")
_roster = {r["id"]: r for r in orbit_api._REGISTRY.list()["sessions"]}
check("G1 the session roster reports the prompt size (0 = VOID)",
      _roster.get("sess-void", {}).get("prompt_chars") == 0,
      str(_roster.get("sess-void")))
roles_mod.write("sess-void", "Role: tester")
_roster = {r["id"]: r for r in orbit_api._REGISTRY.list()["sessions"]}
check("G2 a written prompt reports its real size",
      _roster.get("sess-void", {}).get("prompt_chars") == len("Role: tester"),
      str(_roster.get("sess-void")))
check("G3 the deck marks the empty prompt on the button (red asterisk + title)",
      'const voidP = (a.prompt_chars === 0);' in orbit
      and 'class="req"' in orbit and "pbtn" in orbit and "missing" in orbit
      and "This prompt is <b>EMPTY</b>" in orbit)
check("G4 the header counts the rows whose prompt is empty",
      '" with an EMPTY prompt"' in orbit and "haswarn" in orbit)
check("G5 leadership first is the DEFAULT order, with the flat id order kept",
      'this.sort = "org";' in orbit and '<option value="id">agent id' in orbit
      and '<option value="default" selected>' in orbit)
check("G6 the deck's default sort ranks by the reports_to tree (orchestrator first)",
      "const r = this._orgRank(list);" in orbit and "depth-first reports_to walk" in orbit)
check("G7 a team group header is keyboard-operable (groups start collapsed)",
      'class="grp-h" tabindex="0" role="button" aria-expanded="' in orbit
      and 'if (e.key === "Enter" || e.key === " "){ e.preventDefault(); toggleGroup(); }' in orbit
      and ".grp-h:focus-visible{outline:1px solid var(--acc)" in orbit)
check("G8 an in-place toggle keeps the caret and aria-expanded in sync",
      'h.setAttribute("aria-expanded", closed ? "false" : "true");' in orbit)

print("---")
ok = sum(1 for r in results if r)
print("%d/%d PASS" % (ok, len(results)))
sys.exit(0 if ok == len(results) else 1)

