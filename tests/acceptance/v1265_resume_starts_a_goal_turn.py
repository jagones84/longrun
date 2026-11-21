#!/usr/bin/env python3
"""v1265 — a resumed goal STARTS the turn that pursues it; a paused goal serves the operator.

Operator (2026-11-22): *"1 resume goal shall start the LLM to pursuit the goal. when
paused simply ignores it and listen the user messages coming and do what the user
currently ask"*.

Before this, `POST /api/goal {action:"resume"}` only flipped the record back to
`active`: the bar said the goal was live while nothing was running.

  A  resume launches ONE detached, autonomous, goal-mode turn and says so
  B  resume of a goal that is not paused starts nothing (the 409 stays)
  C  a `completed` goal whose plan REOPENED is resumable (settle no longer eats it)
  D  a paused goal never hijacks an ordinary turn: `_goal_mode_of` is False and the
     prompt says the turn is ordinary
  E  the page announces the turn the backend started

Deterministic and offline: temp dirs, the store + the handler are called directly,
the turn worker is replaced by a recorder (no model, no thread, no HTTP).
Run: python3 tests/acceptance/v1265_resume_starts_a_goal_turn.py
"""
import os
import shutil
import sys
import tempfile

TMP = tempfile.mkdtemp(prefix="v1265_")
for _k in ("CONFIG_DIR", "SESSIONS_DIR", "DATA_HOME", "DATA_DIR", "HARNESS_DIR",
           "RUNS_DIR", "PROJECTS_DIR", "SKILLS_DIR", "EDITS_DIR", "GRAPH_DIR",
           "ROLES_DIR"):
    os.environ["LONGRUN_" + _k] = os.path.join(TMP, _k.lower())
    os.makedirs(os.environ["LONGRUN_" + _k], exist_ok=True)
os.environ["LONGRUN_HOOKS"] = os.path.join(TMP, "hooks.yaml")
os.environ["LONGRUN_DB"] = os.path.join(TMP, "events.db")

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(REPO, "src"))

import longrun.core.server  # noqa: E402,F401 — resolve the httpapi<->server cycle first
from longrun.core import api_v02 as A  # noqa: E402
from longrun.core import httpapi as H  # noqa: E402
from longrun.plan import goal, taskgraph  # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name
          + ((" :: " + str(detail)[:300]) if detail and not ok else ""))


def src(*parts):
    with open(os.path.join(REPO, *parts), encoding="utf-8") as f:
        return f.read()


# The turn worker is the ONE thing we replace: the rest of the path (gate, store,
# handler) is the real code, so the test sees the real decision.
calls = []


def fake_worker(sess, message, model, *a, **kw):
    calls.append(dict({"session": (sess or {}).get("id"), "message": message,
                       "model": model}, **kw))
    return None


H._start_chat_worker = fake_worker

SID = "sess-resume"
SESS = {"id": SID}

# ------------------------------------------------- A: resume really starts ----
goal.start(SID, "Ship the reconciliation report.")
goal.pause(SID, "operator stepped away")
status, payload = A._goal_action({"session": SID, "action": "resume"})
check("A1 resume answers 200 with the record ACTIVE again",
      status == 200 and (payload.get("goal") or {}).get("status") == "active", payload)
check("A2 the answer names the turn that was started",
      isinstance(payload.get("turn"), str) and len(payload["turn"]) == 32, payload.get("turn"))
check("A3 exactly one turn was launched, detached, autonomous and in goal mode",
      len(calls) == 1 and calls[0].get("detached") is True
      and calls[0].get("goal_mode") is True and calls[0].get("autonomous") is True, calls)
check("A4 the turn names the OBJECTIVE (never a fake operator message)",
      calls and calls[0].get("message") == "Continue pursuing this goal: "
      "Ship the reconciliation report."
      and calls[0].get("sender") == H.GOAL_RESUME_SENDER, calls)
check("A4b with no objective the turn falls back to the standing instruction",
      H._resume_message("") == H.GOAL_RESUME_MESSAGE
      and H._resume_message("  Ship   it  ").endswith(": Ship it"))
check("A5 the turn belongs to THIS session and the record counted it",
      calls and calls[0].get("session") == SID
      and (goal.load(SID) or {}).get("turns") == 2,
      {"calls": calls, "goal": goal.load(SID)})

# ------------------------------------------- B: a second resume does nothing ---
n_calls = len(calls)
status, payload = A._goal_action({"session": SID, "action": "resume"})
check("B1 resume of a goal that is NOT paused is still refused (409)",
      status == 409 and (payload or {}).get("ok") is False, payload)
check("B2 the refusal started no turn and counted none",
      len(calls) == n_calls and (goal.load(SID) or {}).get("turns") == 2,
      {"calls": len(calls)})

# ---------------------------------- C: a reopened `completed` goal resumes ----
goal.complete(SID, "plan closed")
graph = taskgraph.ensure(SID, session_id=SID, goal="Ship the reconciliation report.")
graph["nodes"] = [{"id": "n1", "label": "write it", "status": "todo", "plan": 1}]
taskgraph.save(graph)
check("C1 the store reports the goal as reopened, not done",
      (goal.status(SID) or {}).get("effective_status") == "reopened",
      goal.status(SID))
n_calls = len(calls)
status, payload = A._goal_action({"session": SID, "action": "resume"})
check("C2 resume of a reopened goal answers 200 (settle no longer eats the case)",
      status == 200 and (payload.get("goal") or {}).get("status") == "active", payload)
check("C3 that resume starts the pursuing turn too",
      isinstance(payload.get("turn"), str) and len(calls) == n_calls + 1,
      {"calls": len(calls), "turn": payload.get("turn")})

# --------------------------------- D: paused = an ordinary turn, no hijack ----
goal.pause(SID)
check("D1 a paused goal does not turn an ordinary message into a goal turn",
      (goal.status(SID) or {}).get("effective_status") == "paused"
      and H._goal_mode_of(SESS, False) is False,
      {"status": goal.status(SID), "mode": H._goal_mode_of(SESS, False)})
check("D2 an active goal DOES own the session's turns (the opposite fact, pinned)",
      (goal.resume(SID) or {}).get("status") == "active"
      and H._goal_mode_of(SESS, False) is True)
goal.pause(SID)
turns_before = (goal.load(SID) or {}).get("turns")
ok, wp = H._goal_begin(SESS, False, "what is the weather?")
check("D3 an ordinary turn while paused passes the gate and touches nothing",
      ok is True and wp is None and (goal.load(SID) or {}).get("turns") == turns_before,
      {"ok": ok, "payload": wp})
block = __import__("longrun.agent.agent", fromlist=["_goal_block"])._goal_block(SID)
check("D4 the model is told a paused goal does not own this turn",
      "PAUSED" in block and "ORDINARY turn" in block, block)
check("D5 /goal while paused is still refused with a reason naming resume",
      H._goal_begin(SESS, True, "/goal go")[0] is False
      and "resume" in H._goal_begin(SESS, True, "/goal go")[1].get("error", ""))

# ---------------------------------------------- E: the sources and the page ---
api_src = src("src", "longrun", "core", "api_v02.py")
http_src = src("src", "longrun", "core", "httpapi.py")
agent_src = src("src", "longrun", "agent", "agent.py")
ui = src("webui", "index.html")
check("E1 the resume branch is the one that launches the turn",
      'turn_id = _httpapi.start_goal_turn(sid, (body or {}).get("model"))' in api_src
      and 'if action not in ("delete", "resume"):' in api_src
      and 'out["turn"] = turn_id' in api_src)
check("E2 there is ONE launcher, built on the existing chat worker",
      "def start_goal_turn(session_id, model=None):" in http_src
      and "detached=True, turn_id=turn_id" in http_src
      and "_start_chat_worker(" in http_src)
check("E3 the paused rule lives in the prompt, not only in the gate",
      '"- the goal is PAUSED: this is an ORDINARY turn' in agent_src)
check("E4 the page says the goal is being pursued (the feed follows the turn)",
      'if (action === "resume" && r && r.turn) toast("goal resumed' in ui)
check("E5 the resume turn rides the same feed announcement the page listens to",
      'publish("chat.user"' in http_src and 'es.addEventListener("chat.user"' in ui
      and "attachIfRunning(sessionId);" in ui)

shutil.rmtree(TMP, ignore_errors=True)

print("\n---\nv1265: %d/%d PASS" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
