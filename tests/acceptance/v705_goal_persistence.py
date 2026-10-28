#!/usr/bin/env python3
"""v705 — G-1: `/goal` is a DURABLE object, not a per-request flag.

Before this, `mode=goal` existed only for the duration of one HTTP request
(`core/httpapi.py:2074`, `:2230`, `:2380`): closing the tab or restarting the
service lost the objective, and there was nothing to pause, resume, edit or
delete — the gap against the frontier `/goal` (an Active-goal object with
pause/edit/delete) the operator asked to close.

  A  the store: start / pause / resume / edit / delete / complete, one record
     per session, bounded objective, corrupt file = no goal (never a crash)
  B  completion is the PLAN's decision, not the record's opinion
  C  a `/goal` turn is refused while paused, and counts turns while active
  D  the routes and the chat wiring exist (source pins, not live rendering)
  E  the WebUI bar reads the backend and offers pause/edit/delete

No model, no network, no server: the store, the plan and the handlers are called
directly against temp dirs.
"""
import json
import os
import shutil
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="sf-v705-")
for _k in ("CONFIG_DIR", "SESSIONS_DIR", "DATA_HOME", "DATA_DIR", "HARNESS_DIR",
           "RUNS_DIR", "PROJECTS_DIR", "SKILLS_DIR"):
    os.environ["LONGRUN_" + _k] = os.path.join(TMP, _k)
    os.makedirs(os.path.join(TMP, _k), exist_ok=True)
os.environ["LONGRUN_HOOKS"] = os.path.join(TMP, "hooks.yaml")
os.environ["LONGRUN_DB"] = os.path.join(TMP, "events.db")
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.plan import goal  # noqa: E402
from longrun.plan import taskgraph  # noqa: E402

results = []


def check(name, ok, detail=""):
    """Record one assertion (repo convention)."""
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""))


SID = "sess-goal-1"
OTHER = "sess-goal-2"

# ------------------------------------------------------------------ A: store --
check("A1 no record means no goal, and a goal turn may start",
      goal.load(SID) is None and goal.can_start(SID) == (True, ""))
check("A2 delete of a missing goal is not an error",
      goal.delete(SID) is False and goal.delete(OTHER) is False)

rec = goal.start(SID, "  Ship the reconciliation report.  ")
check("A3 start creates one active record with the trimmed objective",
      rec["status"] == "active" and rec["objective"] == "Ship the reconciliation report."
      and rec["turns"] == 1 and rec["session"] == SID, rec)
check("A4 the record is on disk under <data>/goals and reads back",
      os.path.isfile(goal.path(SID))
      and os.path.dirname(goal.path(SID)) == os.path.join(os.environ["LONGRUN_DATA_DIR"], "goals")
      and goal.load(SID)["objective"] == rec["objective"],
      goal.path(SID))
second = goal.start(SID, "")
check("A5 a second turn keeps the objective and the creation time, and counts",
      second["objective"] == rec["objective"] and second["created"] == rec["created"]
      and second["turns"] == 2, second)

paused = goal.pause(SID, "operator stepped away")
check("A6 pause is a real state", paused["status"] == "paused" and paused.get("note"))
check("A7 pause refuses to run, with a reason that names resume",
      goal.can_start(SID)[0] is False and "resume" in goal.can_start(SID)[1],
      goal.can_start(SID))
check("A8 a non-active goal cannot be paused twice", goal.pause(SID) is None)

resumed = goal.resume(SID)
check("A9 resume returns to active and clears the note",
      resumed["status"] == "active" and not resumed.get("note"))
check("A10 resume of an active goal is not a silent success", goal.resume(SID) is None)

edited = goal.edit(SID, "Ship the reconciliation report AND the ledger.")
check("A11 edit replaces the objective",
      edited["objective"].endswith("AND the ledger.") and edited["created"] == rec["created"])
check("A12 an empty objective is refused, not stored",
      goal.edit(SID, "   ") is None and "ledger" in goal.load(SID)["objective"])

long_rec = goal.start(OTHER, "x" * (goal.MAX_OBJECTIVE + 500))
check("A13 the objective is bounded", len(long_rec["objective"]) == goal.MAX_OBJECTIVE)
goal.delete(OTHER)
check("A14 delete removes the record so a stale tab cannot resume it",
      goal.load(OTHER) is None and goal.can_start(OTHER) == (True, ""))

with open(goal.path(SID), "w", encoding="utf-8") as f:
    f.write("{not json")
check("A15 a corrupt record reads as no goal instead of crashing",
      goal.load(SID) is None and goal.status(SID)["goal"] is None)
goal.start(SID, "Ship the reconciliation report AND the ledger.")

# ------------------------------------------------- B: completion is the plan --
check("B1 an empty plan is not completion",
      goal.progress(SID)["complete"] is False and goal.progress(SID)["steps"] == 0)
graph = taskgraph.ensure(SID, session_id=SID, goal="Ship the report")
graph["nodes"] = [{"id": "n1", "label": "write it", "status": "doing", "plan": 1}]
taskgraph.save(graph)
prog = goal.progress(SID)
check("B2 progress counts the plan's steps", prog["steps"] == 1 and prog["open"] == 1
      and prog["done"] == 0 and prog["complete"] is False, prog)
graph["nodes"] = [{"id": "n1", "label": "write it", "status": "done", "plan": 1,
                   "evidence": [{"text": "wrote report.md"}]}]
taskgraph.save(graph)
check("B3 evidence-backed completion is read from the plan",
      goal.progress(SID)["complete"] is True and goal.progress(SID)["done"] == 1)
check("B4 the record itself did not claim completion",
      goal.load(SID)["status"] == "active")

# ------------------------------------------- C: the chat gate and the closure --
import longrun.core.server  # noqa: E402,F401 — resolve the httpapi<->server cycle first
from longrun.core import httpapi as H  # noqa: E402

SESS = {"id": SID}
ok, payload = H._goal_begin(SESS, False, "just a normal message")
check("C1 a non-goal turn touches no goal", ok is True and payload is None
      and goal.load(SID)["turns"] == 1)

ok, payload = H._goal_begin(SESS, True, "/goal Ship the reconciliation report AND the ledger.")
check("C2 a goal turn counts and does NOT duplicate the /goal prefix",
      ok is True and goal.load(SID)["turns"] == 2
      and not goal.load(SID)["objective"].startswith("/goal"),
      goal.load(SID)["objective"])
check("C3 the begin payload is the real bar state",
      payload["goal"]["goal"]["status"] == "active"
      and payload["goal"]["progress"]["complete"] is True, payload)

goal.pause(SID)
ok, payload = H._goal_begin(SESS, True, "continue please")
check("C4 a paused goal REFUSES the turn before any spend",
      ok is False and "paused" in payload["error"] and "progress" in payload["goal"])
check("C5 the refusal did not count a turn", goal.load(SID)["turns"] == 2)
goal.resume(SID)

check("C6 a completed plan closes the durable goal at turn end",
      (H._goal_end(SESS, True) or {}).get("status") == "completed")
check("C7 a NON-goal turn never touches the goal object",
      H._goal_end(SESS, False) is None and goal.load(SID)["status"] == "completed")
taskgraph.save(dict(graph, nodes=[{"id": "n2", "label": "verify", "status": "todo",
                                   "plan": 1}]))
fresh = goal.start(SID, "Do the next round.")
check("C8 an unfinished plan leaves the goal open (start over a completed goal is new)",
      fresh["status"] == "active" and fresh["turns"] == 1
      and goal.progress(SID)["complete"] is False
      and (H._goal_end(SESS, True) or {}).get("status") == "active")

# ------------------------------------------------------- D: route + wiring ---
api_src = open(os.path.join(REPO, "src", "longrun", "core", "api_v02.py"),
               encoding="utf-8").read()
http_src = open(os.path.join(REPO, "src", "longrun", "core", "httpapi.py"),
                encoding="utf-8").read()
check("D1 GET and POST /api/goal are registered",
      api_src.count('if path == "/api/goal"') == 2
      and "_goal_action(body or {})" in api_src
      and "goal.status(qs.get(\"session\") or \"\")" in api_src)
check("D2 every chat entry point runs the gate",
      http_src.count("_goal_begin(sess, _goal_mode, message)") == 3,
      http_src.count("_goal_begin(sess, _goal_mode, message)"))
check("D3 each gated path answers 409 instead of starting a refused stream",
      http_src.count('if not _goal_ok:') == 3
      and http_src.count('return self._send(409, _goal_payload)') == 3)
check("D4 both turn paths close the goal on real evidence",
      "_goal_end(sess, goal_mode)" in http_src and "_goal_end(sess, _goal_mode)" in http_src)
check("D5 only the command prefix is stripped, never the objective",
      H._goal_objective("/goal   Ship it  ") == "Ship it"
      and H._goal_objective("plain message") == "plain message"
      and H._goal_objective("/goals are not a command") == "/goals are not a command")

# ---------------------------------------------------------------- E: the bar --
ui = open(os.path.join(REPO, "webui", "index.html"), encoding="utf-8").read()
check("E1 the bar markup exists with its three actions",
      'id="goalBar"' in ui and 'id="goalText"' in ui
      and 'data-call="goalToggle"' in ui and 'data-call="goalEdit"' in ui
      and 'data-call="goalDelete"' in ui)
check("E2 the bar reads the backend, not a client copy",
      'api("GET", "/api/goal?session="' in ui and "function loadGoal()" in ui)
check("E3 the bar follows the session and the end of a turn",
      "loadGoal();         // G-1: the Active-goal bar follows the session" in ui
      and ui.split('es.addEventListener("chat.done"')[1].split("});")[0].count("loadGoal()") == 1)
check("E4 a refused goal turn is explained, not silently dropped",
      'es.addEventListener("goal.refused"' in ui and "this goal is paused" in ui)
check("E5 the actions POST the lifecycle instead of guessing locally",
      'api("POST", "/api/goal"' in ui and 'action: action' in ui)

shutil.rmtree(TMP, ignore_errors=True)

print("\n%d/%d checks passed" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
