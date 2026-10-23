#!/usr/bin/env python3
"""v536 — the "can't edit or delete it after creating it" class of UI/API gaps.

Requested (user): "can't I delete teams? can't I edit all the properties once
created, e.g. the icon? … do a general review to catch these architectural bugs
across the whole WebUI."

Root cause was the same one twice: the substrate had the capability and the WebUI
had no door.
  * teams — ``POST /api/teams/<tid>`` (update) and ``DELETE /api/teams/<tid>``
    already existed but NOTHING reached them: the Orbit team kebab offered only
    reset/compact, so a team was create-and-forget;
  * routines — there was no update at ALL (neither registry nor route): the goal
    and the cadence were frozen at birth, and "editing" meant delete + recreate,
    which lost the id and the run counters.

Locked here:
  * ``teams.REGISTRY.update`` rewrites name/symbol/colour/description, rejects a
    duplicate name, refuses an unknown team;
  * ``POST /api/teams/<tid>`` routes to it; ``DELETE /api/teams/<tid>`` removes the
    team and touches NO agent (only the membership link disappears);
  * ``routines.REGISTRY.update`` rewrites agent/goal/cadence/enabled/model IN PLACE,
    keeping the id + ``runs``/``last_run``, and validates its inputs;
  * ``POST /api/routines/<rid>`` routes to it;
  * the Orbit deck exposes both (an edit form + a delete item) and they hit exactly
    those routes.

Deterministic: no model, no network, no server.
Run: python3 tests/acceptance/v536_ui_edit_parity.py
"""
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="sf-536-")
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
from longrun.orchestrate import orchestration  # noqa: E402
from longrun.orchestrate import routines  # noqa: E402
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
    return server.get_or_create_session(None, title)["id"]


# --- A: TEAM edit (backend contract) ----------------------------------------
s1 = mk("alpha")
T = teams.REGISTRY
a1 = agents.REGISTRY.designate(s1, name="Alpha")["agent"]
T.create("Ops")
T.add_member("T1", a1["id"])

res = call("POST", "/api/teams/T1",
           {"name": "Ops Core", "symbol": "\U0001F680", "color": "#ff8800",
            "description": "platform crew"})
check("A1 POST /api/teams/<tid> updates the team",
      res["code"] == 200 and res["obj"].get("ok") is True, str(res))
t = teams.REGISTRY.get("T1") or {}
check("A2 the name was rewritten", t.get("name") == "Ops Core", str(t.get("name")))
check("A3 the symbol (icon) was rewritten", t.get("symbol") == "\U0001F680", str(t.get("symbol")))
check("A4 the colour was rewritten", t.get("color") == "#ff8800", str(t.get("color")))
check("A5 the description was rewritten", t.get("description") == "platform crew")
check("A6 the id is stable across an edit", t.get("id") == "T1", str(t.get("id")))
check("A7 members survive the edit", t.get("members") == [a1["id"]], str(t.get("members")))

res = call("POST", "/api/teams/T1", {"name": "Ops Core"})
check("A8 a partial edit only touches the fields passed",
      res["obj"].get("ok") is True and (teams.REGISTRY.get("T1") or {}).get("symbol") == "\U0001F680")
T.create("Solo")
res = call("POST", "/api/teams/T1", {"name": "Solo"})
check("A9 a duplicate team name is refused",
      res["obj"].get("ok") is False and "already in use" in (res["obj"].get("error") or ""), str(res))
res = call("POST", "/api/teams/T404", {"name": "ghost"})
check("A10 an unknown team refuses the edit",
      res["obj"].get("ok") is False and "not found" in (res["obj"].get("error") or ""), str(res))

# --- B: TEAM delete (backend contract) --------------------------------------
check("B1 the agent is a member before the delete",
      "T1" in agents.REGISTRY.teams_for(a1["id"]),
      str(agents.REGISTRY.teams_for(a1["id"])))
res = call("DELETE", "/api/teams/T1")
check("B2 DELETE /api/teams/<tid> removes the team",
      res["code"] == 200 and res["obj"].get("ok") is True, str(res))
check("B3 the team is gone", teams.REGISTRY.get("T1") is None)
check("B4 the AGENT still exists (only the link disappears)",
      agents.REGISTRY.is_agent(s1))
check("B5 the agent no longer claims the deleted team",
      "T1" not in agents.REGISTRY.teams_for(a1["id"]),
      str(agents.REGISTRY.teams_for(a1["id"])))
check("B6 the session behind the agent is untouched",
      server.load_session(s1) is not None)
res = call("DELETE", "/api/teams/T404")
check("B7 deleting an unknown team is a clean refusal",
      res["obj"].get("ok") is False, str(res))

# --- C: ROUTINE edit (registry + route) -------------------------------------
R = routines.REGISTRY
made = R.create(a1["id"], "report the build status", 60)
check("C1 a routine was created", made.get("ok") is True, str(made))
rid = (made.get("routine") or {}).get("id")
R._mark(rid, 1000.0)                      # pretend it fired once
before = R.get(rid) or {}
check("C2 the routine carries a run counter", before.get("runs") == 1)

res = call("POST", "/api/routines/" + rid, {"goal": "report the deploy status",
                                            "every_seconds": 120})
check("C3 POST /api/routines/<rid> updates in place",
      res["code"] == 200 and res["obj"].get("ok") is True, str(res))
r = R.get(rid) or {}
check("C4 the goal was rewritten", r.get("goal") == "report the deploy status")
check("C5 the cadence was rewritten", r.get("every_seconds") == 120)
check("C6 the id survives (no delete + recreate)", r.get("id") == rid)
check("C7 the run history survives the edit", r.get("runs") == 1,
      str(r.get("runs")))
check("C8 the next fire uses the NEW cadence",
      r.get("next_run") and r.get("next_run") > 0)

res = call("POST", "/api/routines/" + rid, {"every_seconds": 5})
check("C9 a cadence below the floor is refused",
      res["obj"].get("ok") is False and ">=" in (res["obj"].get("error") or ""), str(res))
check("C10 the refused edit changed nothing", (R.get(rid) or {}).get("every_seconds") == 120)
res = call("POST", "/api/routines/" + rid, {"goal": "   "})
check("C11 an empty goal is refused",
      res["obj"].get("ok") is False, str(res))
res = call("POST", "/api/routines/R404", {"goal": "x"})
check("C12 an unknown routine refuses the edit",
      res["obj"].get("ok") is False and "not found" in (res["obj"].get("error") or ""), str(res))
res = call("POST", "/api/routines/" + rid, {"enabled": False})
check("C13 the switch can be flipped through the same route",
      res["obj"].get("ok") is True and (R.get(rid) or {}).get("enabled") is False, str(res))

with open(os.path.join(REPO, "src", "longrun", "orchestrate", "orchestration.py"),
          encoding="utf-8") as f:
    orch = f.read()
check("C14 the routine-edit route is wired before the create fallback",
      'path.startswith("/api/routines/")' in orch and "rr.update(" in orch)
with open(os.path.join(REPO, "src", "longrun", "orchestrate", "routines.py"),
          encoding="utf-8") as f:
    rout = f.read()
check("C15 the registry grew an update()", "def update(self, rid," in rout)

# --- D: the Orbit deck exposes both (source contract) -----------------------
with open(os.path.join(REPO, "src", "longrun", "orbit", "web", "orbit.html"),
          encoding="utf-8") as f:
    deck = f.read()
check("D1 the team kebab offers Edit team + Delete team",
      "Edit team" in deck and "Delete team" in deck)
check("D2 the team edit form posts to the team-update route",
      '"/api/teams/" + encodeURIComponent(tid), {' in deck)
check("D3 the team delete calls DELETE /api/teams/<tid>",
      'this.api.del("/api/teams/" + encodeURIComponent(tid))' in deck)
check("D4 the team edit offers every editable property",
      all(('fld("%s"' % k) in deck for k in ("name", "symbol", "color", "description")))
check("D5 the routine row has an edit button", 'data-edit="' in deck)
check("D6 the routine edit posts to the routine-update route",
      '"/api/routines/" + encodeURIComponent(rid), {' in deck)
check("D7 both edit forms reopen through the ONE popover primitive",
      deck.count("openPopover(ev,") >= 3)

# --- E: the other write routes that had no UI door ---------------------------
with open(os.path.join(REPO, "webui", "index.html"), encoding="utf-8") as f:
    gui = f.read()
check("E1 every MCP client row can be TESTED before saving",
      '"/api/mcp/clients/test"' in gui and "function testMcpClient(" in gui
      and "test.onclick = () => testMcpClient(" in gui)
check("E2 the provider catalog can be RELOADED from Settings > Models",
      '"/api/providers/reload"' in gui and "function reloadProviders(" in gui
      and 'data-call="reloadProviders"' in gui)
with open(os.path.join(REPO, "src", "longrun", "core", "api_v02.py"), encoding="utf-8") as f:
    api = f.read()
check("E3 the operator route for a Matrix uninstall exists",
      'path == "/api/matrix/remove"' in api and "_matrix_mod.remove(" in api)
check("E4 that route refuses any kind other than tool",
      'only kind=tool is exposed on this route' in api)
check("E5 the UI uninstall button exists and is gated on origin=matrix",
      'data-mtxrm=' in gui.replace('"', '')
      and "const isMatrix = String(t.origin || \"\") === \"matrix\";" in gui
      and "function uninstallMatrixTool(" in gui)
check("E6 the uninstall warns that a whole namespace file is removed",
      "one file holds a whole namespace" in gui
      and "promoted Nucleus copy is never touched" in gui)
check("E7 the uninstall button is emitted ONLY under the isMatrix conditional",
      "(isMatrix ? " in gui and gui.count("data-mtxrm") == 2)

print("---")
ok = sum(1 for r in results if r)
print("%d/%d PASS" % (ok, len(results)))
sys.exit(0 if ok == len(results) else 1)
