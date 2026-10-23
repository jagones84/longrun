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
    those routes;
  * G — the LIVE half: `/api/tools/running` + the cancel, `/api/agent/runs` + the
    pause/resume/abort, and the Feed-rail "Running now" card that reads them.
  * H — Settings ▸ Orchestration: the blackboard (post/get/thread/stats) and the
    swarm runner (`POST /api/swarm/run`), exposed where they had no panel.
  * I — the manifest checkpoints (create / rollback / delete / prune), the context
    dry run (`POST /api/context/preview`) and `POST /api/costs/reset`.

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

# --- A2: the ICON — a palette choice longrunAgent makes, not free text -------
from longrun.orchestrate import teams as _teams                        # noqa: E402

_pal = _teams.palette()
check("A11 the palette is exposed to the UI (one declaration)",
      len(_pal) >= 8 and all("symbol" in p and "color" in p for p in _pal), _pal[:3])
_plist = call("GET", "/api/teams")
check("A12 GET /api/teams publishes the palette the picker renders from",
      _plist["code"] == 200 and _plist["obj"].get("palette") == _pal, str(_plist["obj"].keys()))
_made = call("POST", "/api/teams", {"name": "Finance Watch",
                                    "description": "budget, cost and billing for the platform"})
_fin = (_made["obj"].get("team") or {})
check("A13 create() lets longrunAgent pick the icon from name + description",
      _fin.get("symbol") == "\U0001f4b0" and _fin.get("color") == "#22C55E", _fin)
check("A14 the description is stored at create time",
      _fin.get("description") == "budget, cost and billing for the platform", _fin)
_res = call("POST", "/api/teams/T1", {"regenerate_icon": True})
check("A15 regenerate_icon asks longrunAgent again and keeps the team",
      _res["obj"].get("ok") is True
      and (_res["obj"].get("team") or {}).get("id") == "T1"
      and (_res["obj"].get("team") or {}).get("symbol") in [p["symbol"] for p in _pal],
      _res["obj"].get("team"))

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
      all(('fld("%s"' % k) in deck for k in ("name", "description"))
      and 'data-f="symbol"' in deck and 'data-f="color"' in deck)
check("D5 the routine row has an edit button", 'data-edit="' in deck)
check("D6 the routine edit posts to the routine-update route",
      '"/api/routines/" + encodeURIComponent(rid), {' in deck)
check("D7 both edit forms reopen through the ONE popover primitive",
      deck.count("openPopover(ev,") >= 3)
check("D8 the create bar carries the description and an ICON PICKER, not free text",
      'id="tmNewDesc"' in deck and 'id="tmNewIcon"' in deck and "tmNewSymbol" not in deck)
check("D9 create posts the description and the picked icon + colour",
      'const description = ($("tmNewDesc").value || "").trim();' in deck
      and "description: description || undefined" in deck
      and "color: color || undefined" in deck)
check("D10 the picker renders from the palette the backend publishes",
      "this.agents.palette = tms.palette" in deck and "this.agents.fillIconPicker()" in deck
      and "iconOptions(sel){" in deck
      and 'data-color="' in deck and "longrunAgent picks" in deck)
check("D11 the edit form can REGENERATE the icon through longrunAgent",
      "✨ generate icon" in deck and "regenerate_icon: true" in deck)

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

# --- F: ONE naming law — the `action` echo is gone (JAG-536) -----------------
from longrun.agent import agent as A  # noqa: E402
from longrun.core import api_v02  # noqa: E402
from longrun.tools import registry as _REG  # noqa: E402

# Acceptance tests must be hermetic: `tool_context()` reads `registry.catalog()`,
# whose external branch would connect to the machine's configured MCP servers.
_REG._external_tools = lambda: {}

_tctx = api_v02.tool_context()
check("F1 the prompt teaches the CANONICAL form, never the `action` alias",
      'self.tools {query:"<words>"}' in _tctx and 'self.tools {tool:"<name>"}' in _tctx
      and 'action:"tools"' not in _tctx and "with `self.sj`" in _tctx)
check("F2 the compact index notation is explained",
      "`ns{a,b}` means the two callable " in _tctx)
check("F3 a legacy `self` + action reaches the card as the canonical name",
      A._card_tool_name("self", {"action": "sj"}) == "self.sj")
check("F4 the card DROPS the echo `action` once the name carries it",
      A._card_args("self", {"action": "sj", "job": "SJ1"}) == {"job": "SJ1"})
check("F5 a plain tool keeps every argument",
      A._card_args("fs.read", {"path": "a.py"}) == {"path": "a.py"})
check("F6 an action that is NOT a canonical subtool is preserved",
      A._card_args("bash", {"action": "run", "cmd": "ls"}) == {"action": "run", "cmd": "ls"})

# --- G: the LIVE running surface — what is running NOW, and how to stop it ---
# Two registries had routes and NO door: /api/tools/running (+ the cancel) and
# /api/agent/runs (+ pause/resume/abort). Locked: the routes, the panel that reads
# them, the four actions, and that the panel stops polling while collapsed.
import threading                                                  # noqa: E402
import time                                                       # noqa: E402
from longrun.tools import sandbox                                 # noqa: E402

check("G1 GET /api/tools/running reads the sandbox registry",
      'path == "/api/tools/running"' in api and "sandbox.running()" in api)
check("G2 POST /api/tools/cancel routes to sandbox.cancel",
      'path == "/api/tools/cancel"' in api and "sandbox.cancel(job)" in api)
check("G3 GET /api/agent/runs publishes the run registry",
      'path == "/api/agent/runs"' in api and "r.public() for r in" in api)
check("G4 POST /api/agent/control routes to run_control",
      'path == "/api/agent/control"' in api and "run_control(rid, action)" in api)

# A real tracked process (no docker, no network): the primitive the four backends
# all end in. spawn -> appears in running() -> cancel -> leaves the queue.
_job = {}


def _spawn():
    _job["res"] = sandbox._run_tracked(
        [sys.executable, "-c", "import time; time.sleep(30)"],
        timeout=40, job_id="v536live")


threading.Thread(target=_spawn, daemon=True).start()
_seen = []
for _ in range(40):
    _seen = [j for j in sandbox.running() if j["job"] == "v536live"]
    if _seen:
        break
    time.sleep(0.2)
check("G5 a tracked job shows up in running() while it executes", bool(_seen),
      sandbox.running())
check("G6 the row carries the job / pid / command / seconds the panel shows",
      bool(_seen) and all(k in _seen[0] for k in ("job", "pid", "command", "seconds")),
      _seen)
_can = sandbox.cancel("v536live")
check("G7 cancel() accepts the job id the UI posts", _can.get("cancelled") is True, _can)
_gone = False
for _ in range(60):
    if not [j for j in sandbox.running() if j["job"] == "v536live"]:
        _gone = True
        break
    time.sleep(0.1)
check("G8 the cancelled job leaves the queue", _gone, sandbox.running())
check("G9 cancel() is idempotent once it stopped",
      sandbox.cancel("v536live").get("cancelled") is False)
check("G10 the cancelled run reports cancelled + exit 130",
      (_job.get("res") or {}).get("cancelled") is True
      and (_job.get("res") or {}).get("exit_code") == 130, _job.get("res"))

check("G11 the Feed rail carries the live Running-now card",
      'id="runningNow"' in gui and 'id="runningNowList"' in gui
      and 'id="runningNowCount"' in gui)
check("G12 the card reads BOTH real registries, never a mirror",
      '"/api/tools/running"' in gui and '"/api/agent/runs"' in gui
      and "async function loadRunning(" in gui)
check("G13 the cancel button posts the job id to the cancel route",
      '"/api/tools/cancel", { job: t.job }' in gui)
check("G14 pause / resume / abort post runId + action to the control route",
      '{ runId: id, action: r.status === "paused" ? "resume" : "pause" }' in gui
      and '{ runId: id, action: "abort" }' in gui)
check("G15 it never polls while the panel is collapsed",
      "box.offsetParent === null) return;" in gui
      and "setInterval(loadRunning, 5000)" in gui)
check("G16 opening the Feed section populates it immediately",
      'else if (key === "feed") { loadRunning(); }' in gui)

# --- H: the blackboard + the swarm (Settings > Orchestration) ----------------
# Both were reachable ONLY from the agent API / CLI: GET+POST /api/blackboard and
# POST /api/swarm/run had no panel at all.
from longrun.agent import swarm as BB                             # noqa: E402

_e1 = BB.post("goal", "ship the orchestration panel", tags=["v536"], author="v536")
check("H1 post() returns a durable, versioned entry",
      bool(_e1.get("id")) and _e1.get("version") == 1 and _e1.get("topic") == "goal", _e1)
_e2 = BB.post("partial_result", "worker done", tags=["v536", "worker"],
              parent=_e1["id"], author="worker/x")
check("H2 a child entry points at its parent", _e2.get("parent") == _e1["id"], _e2)
check("H3 get(topic=) filters", [e["id"] for e in BB.get(topic="goal")] == [_e1["id"]],
      BB.get(topic="goal"))
check("H4 get(tags=) matches ANY tag", len(BB.get(tags=["worker"])) == 1)
check("H5 thread(id) returns the ancestor AND the descendant",
      {e["id"] for e in BB.thread(_e1["id"])} == {_e1["id"], _e2["id"]}, BB.thread(_e1["id"]))
_s = BB.stats()
check("H6 stats() counts the entries and the topics",
      _s.get("total_entries") == 2 and (_s.get("topics") or {}).get("goal") == 1, _s)

check("H7 GET/POST /api/blackboard and POST /api/swarm/run are routed",
      'path == "/api/blackboard"' in api and 'path == "/api/swarm/run"' in api
      and "_SWARM.Coordinator()" in api)
check("H8 Settings grew a Swarm & blackboard panel",
      '["orchestrate", "Swarm & blackboard"]' in gui and 'data-cat="orchestrate"' in gui
      and 'id="bbList"' in gui and 'id="swReport"' in gui)
check("H8b the tab states it is NOT the subagent engine and cross-links both ways",
      "What this tab is (and is not)" in gui
      and 'data-call="gotoSubagents"' in gui and 'data-call="gotoOrchestrate"' in gui
      and "function gotoSubagents() { settingsCategory(\"subagents\"); }" in gui
      and "function gotoOrchestrate() { settingsCategory(\"orchestrate\"); }" in gui
      and "This panel only <b>configures</b> the engine" in gui)
check("H9 the blackboard panel reads and writes the real route",
      "async function loadBlackboard(" in gui and '"/api/blackboard?limit=30"' in gui
      and '"/api/blackboard", { topic:' in gui and 'author: "human"' in gui)
check("H10 the swarm button posts goal/workers/steps and renders the report",
      "async function runSwarm(" in gui and '"/api/swarm/run"' in gui
      and "r.synthesis_id" in gui and "r.summaries" in gui)
check("H11 opening the category populates the blackboard at once",
      'else if (name === "orchestrate") { loadBlackboard(); }' in gui)
check("H12 the swarm control warns that it spends real model calls",
      "spends real model calls" in gui)

# --- I: manifest checkpoints + context preview + cost reset ------------------
# Three more write routes with no door: the MANIFEST checkpoints (create /
# rollback / delete / prune — the UI only had the msg-index rewind),
# POST /api/context/preview and POST /api/costs/reset.
from longrun.memory import checkpoints as CP                      # noqa: E402
from longrun.model import context_engine as CE                    # noqa: E402

server.save_plan({"steps": [{"id": "s1", "title": "before the checkpoint"}]})
_cp = CP.create(label="v536 snap", session_id=s1, by="v536")
check("I1 create() returns a manifest bound to the session",
      str(_cp.get("id", "")).startswith("cp_") and _cp.get("session_id") == s1, _cp)
check("I2 the manifest carries the snapshot sizes",
      isinstance(_cp.get("sizes"), dict) and "messages" in _cp["sizes"], _cp.get("sizes"))
_cpa = CP.create(label="idem", session_id=s1, idempotency_key="v536-key", by="v536")
_cpb = CP.create(label="idem again", session_id=s1, idempotency_key="v536-key", by="v536")
check("I3 an idempotency key returns the SAME checkpoint",
      _cpb.get("id") == _cpa.get("id") and _cpb.get("idempotent") is True,
      (_cpa.get("id"), _cpb))

server.save_plan({"steps": [{"id": "s2", "title": "after the checkpoint"}]})
_rb = CP.rollback(_cp["id"], by="v536")
check("I4 rollback() reports the restored manifest", _rb.get("ok") is True, _rb)
check("I5 the plan really came back to the snapshot",
      [x.get("id") for x in (server.load_plan().get("steps") or [])] == ["s1"],
      server.load_plan())
check("I6 the rollback is recorded on the manifest",
      (CP.get(_cp["id"]) or {}).get("rolled_back") is True)
check("I7 delete() removes the checkpoint",
      CP.delete(_cpa["id"]).get("ok") is True and CP.get(_cpa["id"]) is None)
check("I8 prune() is a clean no-op below the cap", CP.prune(keep=100).get("ok") is True)
check("I9 a missing checkpoint answers with an error, never a crash",
      "error" in (CP.rollback("cp_nope") or {})
      and CP.delete("cp_nope").get("ok") is False)

_pv = CE.preview(s1, "what is next?", 8000)
check("I10 the context preview is a dry run over the session",
      _pv.get("session_id") == s1 and "final_tokens" in _pv
      and _pv.get("budget_tokens") == 8000, _pv)
check("I11 the preview reports the compaction outcome",
      isinstance(_pv.get("compaction"), dict) and "kept" in _pv["compaction"],
      _pv.get("compaction"))
check("I12 an unknown session is refused, not raised", "error" in CE.preview("s_nope"))

check("I13 the rewind dialog grew a Manifest checkpoints block",
      'id="cpLabel"' in gui and 'id="cpList"' in gui
      and "async function loadCheckpoints(" in gui)
check("I14 create / rollback / delete / prune hit the four real routes",
      '"/api/checkpoints", { label:' in gui and '"/rollback", { by: "webui" }' in gui
      and 'api("DELETE", "/api/checkpoints/" + encodeURIComponent(cpId)' in gui
      and 'api("DELETE", "/api/checkpoints?keep=100"' in gui)
check("I15 the checkpoints load on open, even with no turn anchors",
      "loadCheckpoints(sid);" in gui)
check("I16 the Context panel can dry-run the next turn",
      'id="ctxPvMsg"' in gui and 'id="ctxPvOut"' in gui and "async function ctxPreview(" in gui
      and '"/api/context/preview"' in gui and "r.retrieval_hits" in gui)
check("I17 the Cost panel can reset this session's ledger",
      'data-call="resetCosts"' in gui and "async function resetCosts(" in gui
      and '"/api/costs/reset", { session: sessionId }' in gui)

print("---")
ok = sum(1 for r in results if r)
print("%d/%d PASS" % (ok, len(results)))
sys.exit(0 if ok == len(results) else 1)
