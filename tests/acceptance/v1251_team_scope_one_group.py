#!/usr/bin/env python3
"""v1251 — a team scope shows ONE team; the team option list is the shared module's.

Operator (2026-11-22): *"if I filter a team I want only that team not also other teams
(it happens because a member can have multiple teams that shall be maintained). Filtering
team will show only that TEAM. … the filter … it's already applied in agents panel not in
session panel. Also the filter (same one just new icon) shall be [in both] (no duplication
codebase)."*

Two facts made the rail wrong. (1) A session is drawn once, under the FIRST group that
claims it — with scope T3 a member of T1+T3 was claimed by T1, so the T1 header and its
rows stayed on screen. (2) The cross-team Pinned bucket and the "No team" bucket were
unconditional. Now a scope renders exactly ONE group (its own), pinned rows included, and
the scope change opens that group once.

The team OPTION list was built twice — once in webui/index.html, once in the deck's page.
It now lives in webui/assets/filtersort.js as `FilterSort.teamOptions(list)`; the two pages
only pass their team list. The agents panel keeps its own funnel button (the same icon),
mounting the SAME module under key "agents".

  A  the rail renders one group under a scope (pinned / other teams gated)
  B  multi-team membership is preserved; the scoped group claims its rows
  C  the scope change opens the group once (a collapse is not fought)
  D  the empty state names the team
  E  ONE team-option builder, shared by the two pages; the agents panel's funnel is the
     same module (no second copy of the filter)

Deterministic and offline: static pins on the two pages + the shared module.
Run: python3 tests/acceptance/v1251_team_scope_one_group.py
"""
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
UI = open(os.path.join(REPO, "webui", "index.html"), encoding="utf-8").read()
FS = open(os.path.join(REPO, "webui", "assets", "filtersort.js"), encoding="utf-8").read()
DECK = open(os.path.join(REPO, "src", "longrun", "orbit", "web", "orbit.html"),
            encoding="utf-8").read()

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name
          + ((" :: " + str(detail)[:260]) if detail and not ok else ""))


def block(text, start, end):
    return text.split(start)[1].split(end)[0] if start in text else ""


_RAIL = block(UI, "const teamsOf = s =>", "updateSessBadge();")

# --- A: ONE group under a scope ----------------------------------------------
check("A1 the scope flag is derived once",
      'const scoped = teamScope !== "ALL";' in _RAIL)
check("A2 the cross-team Pinned bucket is gated by the scope",
      "if (!scoped && pinGroup.length) groups.push(" in _RAIL,
      _RAIL[:200])
check("A3 the No-team bucket is gated too",
      'if ((!scoped || teamScope === "__none__") && adhoc.length) groups.push(' in _RAIL)
check("A4 every other team is skipped under a scope",
      "if (scoped && t.id !== teamScope) return;" in _RAIL)
check("A5 the scoped group is still emitted even when empty (so the header is not silence)",
      "if (ss.length || t.id === teamScope) groups.push(" in _RAIL)

# --- B: membership is maintained ---------------------------------------------
check("B1 a session keeps ALL its teams (the multi-membership the operator asked to keep)",
      "(ag.teams || []).filter(t => _teamsById[t])" in _RAIL)
check("B2 the filter itself is an INTERSECTION with the scoped team",
      "teamsOf(s).includes(teamScope)" in _RAIL)
check("B3 a row is still claimed by ONE group (no duplicate rows)",
      "const _drawn = new Set();" in _RAIL and "_drawn.has(s.id)" in _RAIL)

# --- C: the scope change opens its group once --------------------------------
check("C1 the previous scope is remembered (module state)",
      "let _lastTeamScope = null;" in UI)
check("C2 the group is expanded only on a CHANGE, so a collapse survives",
      "if (teamScope !== _lastTeamScope)" in _RAIL
      and "_lastTeamScope = teamScope;" in _RAIL
      and "open = open.concat([teamScope])" in _RAIL)

# --- D: the empty state names the team --------------------------------------
check("D1 the empty state says WHICH scope is empty",
      '_scopeName' in _RAIL and "in \" + esc(_scopeName)" in _RAIL)
check("D2 No team is named in words, not as __none__",
      '(teamScope === "__none__") ? "No team"' in _RAIL)

# --- E: ONE option builder, shared; the agents funnel is the same module -----
check("E1 the shared module owns the team option SPEC",
      "function teamOptions(list)" in FS and "teamOptions: teamOptions" in FS)
check("E2 the rail delegates to it (no local builder)",
      "FilterSort.teamOptions(Object.values(_teamsById))" in UI
      and "list.push({ id: t.id" not in UI)
check("E3 the deck's AGENTS table delegates to the SAME builder",
      "FilterSort.teamOptions(this.teams)" in DECK
      and "label: (t.symbol || \"\") + \" \" + t.name" not in DECK)
check("E4 both pages mount the ONE filter module (sessions / agents)",
      'FilterSort.mount({' in UI and 'panelId: "fsPanelSessions"' in UI
      and "FilterSort.mount({" in DECK and 'panelId: "fsPanelAgents"' in DECK)
_FUNNEL = "M2.5 3.2h11L9.2 8.3v4.4l-2.4-1.2V8.3L2.5 3.2z"
check("E5 the agents panel carries the same funnel icon as the rail",
      _FUNNEL in UI and _FUNNEL in DECK
      and 'id="agFilterBtn"' in DECK and 'id="hideEmptyBtn"' in UI)
check("E6 the panel markup is generated by the module, never copied into a page",
      "function panelHtml(ids)" in FS
      and 'class="fs-row"' in FS
      and 'class="fs-row"' not in UI and 'class="fs-row"' not in DECK)
check("E7 the hide-empty checkbox gets its real id (was the literal `undefined`)",
      "ids.hideEmpty" in FS and 'id="\' + ids.hide + \'"' not in FS)

print("\n---\nv1251: %d/%d PASS" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
