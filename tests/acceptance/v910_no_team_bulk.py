#!/usr/bin/env python3
"""v910 — the "No team" bucket bulk actions + the delete-all cascade.

Requested (user): the No-team pile (100+ sessions) had no bulk menu — add the
SAME kebab the team headers have in the Control deck, identical in the Sessions
rail, plus a "Delete ALL sessions" that really deletes the agents ("le cose
collegate tipo jobs etcetera" must not dangle).

Locked:
  * POST /api/teams/__none__/{reset,compact,drop-old-plans} runs the SAME
    per-session engine as a team route (_bulk_apply) over EVERY session with
    no team membership — team members and the pinned system session untouched;
  * POST /api/teams/__none__/delete-sessions deletes every bucket session AND
    its agent through the ONE cascade (httpapi.delete_session): jobs scrubbed,
    routines deleted, reports re-parented to nobody;
  * POST /api/teams/<tid>/delete-sessions does the same for a real team;
  * an unknown no-team action is a 404, never a silent success;
  * the deck renders the kebab on real teams AND the __none__ bucket; the rail
    renders the same menu on the No-team header; both call the ONE route and
    share the SAME copy.

Deterministic: no model, no network, no server (the summarizer is stubbed).
Run: python3 tests/acceptance/v910_no_team_bulk.py
"""
import json
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="sf-910-")
os.environ["LONGRUN_DATA_DIR"] = TMP
os.environ["LONGRUN_SESSIONS_DIR"] = os.path.join(TMP, "sessions")
os.environ["LONGRUN_GRAPH_DIR"] = os.path.join(TMP, "graphs")
os.environ["LONGRUN_AGENTS_FILE"] = os.path.join(TMP, "agents.json")
os.environ["LONGRUN_TEAMS_FILE"] = os.path.join(TMP, "teams.json")
os.environ["LONGRUN_JOBS_FILE"] = os.path.join(TMP, "jobs.json")
os.environ["LONGRUN_ROUTINES_FILE"] = os.path.join(TMP, "routines.json")
os.environ["LONGRUN_DB"] = os.path.join(TMP, "events.db")
os.makedirs(os.environ["LONGRUN_SESSIONS_DIR"], exist_ok=True)
os.makedirs(os.environ["LONGRUN_GRAPH_DIR"], exist_ok=True)
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.agent import agents  # noqa: E402
from longrun.core import server  # noqa: E402  (first: httpapi imports server)
from longrun.core import httpapi  # noqa: E402
from longrun.memory import stores  # noqa: E402
from longrun.orchestrate import orchestration  # noqa: E402
from longrun.orchestrate import jobs as jobs_mod  # noqa: E402
from longrun.orchestrate import routines as routines_mod  # noqa: E402
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


# --- A: the scope — team members OUT, no-team IN, the system session OUT ----
s1, s2, s3, s4, s5 = mk("alpha"), mk("beta"), mk("stray chat"), mk("boss"), mk("orphan")
T = teams.REGISTRY
T.create("Crew")
a1 = agents.REGISTRY.designate(s1, name="Alpha")["agent"]
a2 = agents.REGISTRY.designate(s2, name="Beta")["agent"]
T.add_member("T1", a1["id"])
T.add_member("T1", a2["id"])
M = agents.REGISTRY.designate(s4, name="Boss")["agent"]   # org agent, NO team
agents.REGISTRY.release(s5)                               # -> a true orphan file
# the pinned system session: a file, never a bucket member
with open(os.path.join(os.environ["LONGRUN_SESSIONS_DIR"], "longrunAgent.json"), "w",
          encoding="utf-8") as f:
    json.dump({"id": "longrunAgent", "title": "Architect", "messages": [],
               "system": True, "undeletable": True}, f)
bucket = orchestration._no_team_sessions(agents.REGISTRY)
check("A1 the bucket is exactly the no-team sessions (stray + boss + orphan)",
      set(bucket) == {s3, s4, s5}, str(bucket))
check("A2 team members are never in the bucket",
      s1 not in bucket and s2 not in bucket, str(bucket))
check("A3 the pinned system session is never in the bucket",
      "longrunAgent" not in bucket, str(bucket))

# --- B: RESET ALL over the bucket (wipe, never delete) -----------------------
res = call("POST", "/api/teams/__none__/reset")
check("B1 POST /api/teams/__none__/reset answers 200 ok",
      res["code"] == 200 and res["obj"].get("ok") is True, str(res))
check("B2 it reports every bucket session", res["obj"]["count"] == 3, str(res["obj"]["count"]))
check("B3 the bucket transcripts are wiped",
      [stores.load_session(x)["messages"] for x in (s3, s4, s5)] == [[], [], []])
check("B4 NOTHING is deleted — the bucket sessions still exist",
      all(stores.load_session(x) is not None for x in (s3, s4, s5)))
check("B5 the team members are untouched",
      len(stores.load_session(s1)["messages"]) == 2 and len(stores.load_session(s2)["messages"]) == 2)

# --- C: COMPACT ALL over the bucket (one manual compaction per session) ------
calls = []


def fake_compact(session, budget_tokens=None, keep_recent=None, origin=None):
    calls.append((session, origin))
    return {"session": session, "input_tokens": 120, "tokens_after": 30,
            "compacted": 3, "origin": origin}


real_compact = httpapi.compact_session
httpapi.compact_session = fake_compact
try:
    res = call("POST", "/api/teams/__none__/compact")
finally:
    httpapi.compact_session = real_compact
check("C1 POST /api/teams/__none__/compact answers 200 ok",
      res["code"] == 200 and res["obj"].get("ok") is True, str(res))
check("C2 it compacts every bucket session exactly once",
      sorted(s for s, _ in calls) == sorted([s3, s4, s5]), str(calls))
check("C3 every compaction uses the MANUAL policy",
      all(o == "manual" for _, o in calls), str(calls))

# --- D: DELETE ALL — the real cascade ----------------------------------------
# W: a TEAM agent managed by M (no team) — M dies, W survives re-parented.
sw = mk("worker")
W = agents.REGISTRY.designate(sw, name="Worker", reports_to=M["id"])["agent"]
T.create("Keepers")
T.add_member("T2", W["id"])
made = jobs_mod.JOBS.create("polish the deck", agents=[M["id"]])
job = made.get("job") or made
rmade = routines_mod.REGISTRY.create(M["id"], "ping", 60)
routine = rmade.get("routine") or rmade
check("D0 the fixtures are in place",
      jobs_mod.JOBS.get(job["id"]) is not None
      and routines_mod.REGISTRY.get(routine["id"]) is not None)
res = call("POST", "/api/teams/__none__/delete-sessions")
check("D1 POST /api/teams/__none__/delete-sessions answers 200 ok",
      res["code"] == 200 and res["obj"].get("ok") is True, str(res))
check("D2 it deleted every bucket session",
      res["obj"]["deleted"] == 3 and res["obj"]["count"] == 3, str(res["obj"]))
check("D3 the bucket session files are gone",
      all(stores.load_session(x) is None for x in (s3, s4, s5)), str(bucket))
check("D4 the agents are RELEASED, not just unlinked",
      not agents.REGISTRY.is_agent(s4) and not agents.REGISTRY.is_agent(s3))
check("D5 the job no longer names a dead agent (scrubbed)",
      jobs_mod.JOBS.get(job["id"])["agents"] == [], str(jobs_mod.JOBS.get(job["id"])))
check("D6 the routine of a deleted agent is gone",
      routines_mod.REGISTRY.get(routine["id"]) is None)
check("D7 the team member survived and was re-parented to nobody",
      stores.load_session(sw) is not None
      and (agents.REGISTRY.get(sw) or {}).get("reports_to") is None, str(agents.REGISTRY.get(sw)))
check("D8 the team sessions were NOT touched",
      stores.load_session(s1) is not None and stores.load_session(s2) is not None)
check("D9 the pinned system session was NOT touched",
      os.path.isfile(os.path.join(os.environ["LONGRUN_SESSIONS_DIR"], "longrunAgent.json")))

# --- E: the REAL delete also exists for a real team (same engine) ------------
res = call("POST", "/api/teams/T1/delete-sessions")
check("E1 POST /api/teams/<tid>/delete-sessions answers 200 ok",
      res["code"] == 200 and res["obj"].get("ok") is True, str(res))
check("E2 both team members AND their agents are really deleted",
      res["obj"]["deleted"] == 2
      and stores.load_session(s1) is None and stores.load_session(s2) is None
      and not agents.REGISTRY.is_agent(s1) and not agents.REGISTRY.is_agent(s2),
      str(res["obj"]))
check("E3 the team itself stays (delete-sessions != delete team)",
      T.get("T1") is not None)

# --- F: edges -----------------------------------------------------------------
res = call("POST", "/api/teams/__none__/flush")
check("F1 an unknown no-team action is a 404 (never a silent success)",
      res["code"] == 404 and res["obj"].get("ok") is False, str(res))
res = call("POST", "/api/teams/__none__/reset")
check("F2 an EMPTY bucket is a clean 0-session no-op",
      res["code"] == 200 and res["obj"]["count"] == 0 and res["obj"]["results"] == [],
      str(res))
res = call("GET", "/api/teams/__none__")
check("F3 GET of the pseudo-team stays a 404 (it is a scope, not a team)",
      res["code"] == 404, str(res))
res = call("POST", "/api/teams/T1/reset")
check("F4 the team bulk route still answers with its team key (refactor guard)",
      res["code"] == 200 and res["obj"].get("team") == "T1", str(res))

# --- G: the two surfaces share ONE menu and ONE copy (source contracts) -------
with open(os.path.join(REPO, "src", "longrun", "orbit", "web", "orbit.html"), encoding="utf-8") as f:
    deck = f.read()
with open(os.path.join(REPO, "webui", "index.html"), encoding="utf-8") as f:
    rail = f.read()
check("G1 the deck kebab covers real teams AND the No-team bucket",
      'const hasKebab = isTeam || g.id === "__none__";' in deck)
check("G2 the deck menu offers Delete ALL sessions and calls the delete action",
      'data-a="delall"' in deck and '"delete-sessions"' in deck)
check("G3 the rail renders the kebab on the No-team header only",
      'g.key === "__none__" ? \'<button class="gkebab"' in rail
      and rail.count("gkebab") >= 2)
check("G4 the rail menu calls the ONE no-team route",
      '"/api/teams/__none__/" + action' in rail)
check("G5 the delete copy is IDENTICAL on both surfaces (no second wording)",
      "The REAL delete: every chat, task list and agent record in scope goes." in deck
      and "The REAL delete: every chat, task list and agent record in scope goes." in rail)
check("G6 the rail menu lists the same four actions",
      all(x in rail for x in ("Reset all sessions…", "Compact all sessions…",
                              "Drop OLD plans…", "Delete ALL sessions…")))
check("G7 the kebab never toggles the group (both surfaces stop it)",
      "e.target.closest(\".gkebab\")" in rail and "data-tmbulk" in deck)

print("---")
ok = sum(1 for r in results if r)
print("%d/%d PASS" % (ok, len(results)))
sys.exit(0 if ok == len(results) else 1)
