#!/usr/bin/env python3
"""v482 — TEAM bulk session actions: RESET ALL / COMPACT ALL (JAG-482).

Requested (user): "there shall be the reset all button to reset all sessions (not
delete) but reset, as compact all to compact all content of each session, but this
for teams. With a 3-dot menu in the Control AGENTS pane right of the TEAM name."

Locked:
  * the team header row carries a kebab (``data-tmbulk``) ONLY for a real team
    (the "No team" bucket and unknown group ids have no team to act on);
  * ``POST /api/teams/<tid>/reset``   wipes EVERY member session (chat + tool
    cards + injects + task graph) and DELETES nothing;
  * ``POST /api/teams/<tid>/compact`` runs the MANUAL compaction on EVERY member
    session (one call per session, ``origin="manual"``);
  * sessions that are NOT members of the team are never touched;
  * an unknown team is a 404, an empty team is a clean 0-session no-op.

Deterministic: no model, no network, no server (the summarizer is stubbed).
Run: python3 tests/acceptance/v482_team_bulk.py
"""
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="sf-482-")
os.environ["LONGRUN_DATA_DIR"] = TMP
os.environ["LONGRUN_SESSIONS_DIR"] = os.path.join(TMP, "sessions")
os.environ["LONGRUN_GRAPH_DIR"] = os.path.join(TMP, "graphs")
os.environ["LONGRUN_AGENTS_FILE"] = os.path.join(TMP, "agents.json")
os.environ["LONGRUN_TEAMS_FILE"] = os.path.join(TMP, "teams.json")
os.environ["LONGRUN_JOBS_FILE"] = os.path.join(TMP, "jobs.json")
os.environ["LONGRUN_DB"] = os.path.join(TMP, "events.db")
os.makedirs(os.environ["LONGRUN_SESSIONS_DIR"], exist_ok=True)
os.makedirs(os.environ["LONGRUN_GRAPH_DIR"], exist_ok=True)
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.agent import agents  # noqa: E402
from longrun.core import server  # noqa: E402  (first: httpapi imports server)
from longrun.core import httpapi  # noqa: E402
from longrun.memory import stores  # noqa: E402
from longrun.orchestrate import orchestration  # noqa: E402
from longrun.orchestrate import teams  # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""))


class FakeHandler:
    def __init__(self):
        self.sent = None

    def _send(self, code, obj, ctype=None):
        self.sent = {"code": code, "obj": obj}
        return True


def call(method, path, body=None):
    fh = FakeHandler()
    orchestration.handle(fh, method, path, {}, body or {})
    return fh.sent


def mk(title):
    """A real session with a non-trivial transcript."""
    s = server.get_or_create_session(None, title)
    server.append_message(s, "user", "hello " * 60)
    server.append_message(s, "assistant", "world " * 60)
    return s["id"]


# --- A: the roster — team of 2, plus a loner that must NOT be touched -------
s1, s2, s3 = mk("alpha"), mk("beta"), mk("loner")
T = teams.REGISTRY
T.create("Crew")
a1 = agents.REGISTRY.designate(s1, name="Alpha")["agent"]
a2 = agents.REGISTRY.designate(s2, name="Beta")["agent"]
agents.REGISTRY.designate(s3, name="Loner")
T.add_member("T1", a1["id"])
T.add_member("T1", a2["id"])
check("A1 the team resolves to its 2 member sessions",
      sorted(orchestration._team_bulk("T1", "reset", agents.REGISTRY)["sessions"]) == sorted([s1, s2]))

# --- B: RESET ALL (wipe, never delete) --------------------------------------
res = call("POST", "/api/teams/T1/reset")
check("B1 POST /api/teams/<id>/reset answers 200 ok",
      res["code"] == 200 and res["obj"].get("ok") is True, str(res))
check("B2 it reports every member session", res["obj"]["count"] == 2, str(res["obj"]["count"]))
check("B3 both member transcripts are wiped",
      [stores.load_session(x)["messages"] for x in (s1, s2)] == [[], []])
check("B4 the tool cards are wiped too",
      [stores.load_session(x).get("tool_cards") for x in (s1, s2)] == [[], []])
check("B5 NOTHING is deleted — the sessions still exist",
      all(stores.load_session(x) is not None for x in (s1, s2)))
check("B6 the agents keep existing (reset != release)",
      agents.REGISTRY.is_agent(s1) and agents.REGISTRY.is_agent(s2))
check("B7 both sessions are still listed by the store",
      {s1, s2}.issubset({s["id"] for s in stores.list_sessions()}))
check("B8 a session OUTSIDE the team is untouched",
      len(stores.load_session(s3)["messages"]) == 2)

# --- C: COMPACT ALL (one manual compaction per session, no model) -----------
calls = []


def fake_compact(session, budget_tokens=None, keep_recent=None, origin=None):
    calls.append((session, origin))
    return {"session": session, "input_tokens": 120, "tokens_after": 30,
            "compacted": 3, "origin": origin}


real_compact = httpapi.compact_session
httpapi.compact_session = fake_compact
try:
    res = call("POST", "/api/teams/T1/compact")
finally:
    httpapi.compact_session = real_compact
check("C1 POST /api/teams/<id>/compact answers 200 ok",
      res["code"] == 200 and res["obj"].get("ok") is True, str(res))
check("C2 it compacts every member session exactly once",
      sorted(s for s, _ in calls) == sorted([s1, s2]), str(calls))
check("C3 every compaction uses the MANUAL policy",
      all(o == "manual" for _, o in calls), str(calls))
check("C4 the per-session result is reported back",
      len(res["obj"]["results"]) == 2 and res["obj"]["results"][0]["result"]["tokens_after"] == 30)

# --- D: edges ---------------------------------------------------------------
res = call("POST", "/api/teams/T404/reset")
check("D1 an unknown team is a 404 (never a silent success)",
      res["code"] == 404 and res["obj"].get("ok") is False, str(res))
T.create("Empty")
res = call("POST", "/api/teams/T2/reset")
check("D2 an empty team is a clean 0-session no-op",
      res["code"] == 200 and res["obj"]["count"] == 0 and res["obj"]["results"] == [], str(res))
res = call("POST", "/api/teams/T404/compact")
check("D3 an unknown team refuses the compact too",
      res["code"] == 404 and res["obj"].get("ok") is False, str(res))

# --- E: the Control deck UI (source contract) -------------------------------
with open(os.path.join(REPO, "src", "longrun", "orbit", "web", "orbit.html"), encoding="utf-8") as f:
    deck = f.read()
check("E1 the team header renders a kebab bound to the team id",
      'data-tmbulk="' in deck and 'this.teamById(g.id)' in deck)
check("E2 the kebab is rendered ONLY for a real team",
      "const isTeam = !!this.teamById(g.id);" in deck)
check("E3 the kebab does not toggle the group (event stopped)",
      "ev.stopPropagation();" in deck and "openTeamMenu(ev," in deck)
check("E4 the menu offers reset-all and compact-all",
      "Reset all sessions" in deck and "Compact all sessions" in deck)
check("E5 both actions call the ONE team route",
      '"/api/teams/" + encodeURIComponent(tid) + "/" + action' in deck)
check("E6 the reset copy states it does not delete",
      "Nothing is deleted." in deck)
# JAG-482r: ONE popover primitive for the whole deck. The agents table and the
# constellation both open the same .ctxmenu panel, so the build/clamp/dismiss
# plumbing must exist EXACTLY once — a per-surface copy is how the two menus
# drifted apart in the first place.
check("E7 the deck has ONE .ctxmenu primitive, not one per surface",
      deck.count('m.className = "ctxmenu"') == 1
      and "function openPopover(" in deck and "function closePopover(){" in deck
      and "openPopover(ev," in deck
      and "this.closeTeamPicker()" not in deck and "this.closeTeamMenu()" not in deck
      and "_tmenu" not in deck and "_tmmenu" not in deck
      and "closeMenu(){ closePopover(); }" in deck)

print("---")
ok = sum(1 for r in results if r)
print("%d/%d PASS" % (ok, len(results)))
sys.exit(0 if ok == len(results) else 1)
