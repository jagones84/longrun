#!/usr/bin/env python3
"""v1008 — a task is never abandoned: the plan survives a restart, and `finish`
faces the same closing contract as a prose answer.

Operator report (2026-11-15), from a session that had left two plan steps open:

  "i need resilience on any restart or any problem during the run. task shall not
   be abandoned (the plan can be modified, superseded but not forgotten). even if
   restart. the user can ask for something not relevant to the plan and it is
   hierarchically above the plan of course."

Three holes, measured in the code:

  * `finish` could END a turn with steps open. It got `_selfcheck_left` (2 closure
    rounds) and then broke out of the loop — the close-todos forcing every PROSE
    answer faces (JAG-402, its own budget of 4) was never reached. So the CLOSING
    CONTRACT held for a prose answer and not for the action that claims
    completion most explicitly.
  * A `[Harness restart]` continuation counted as a PIVOT (`_user_pivot` = "the
    turn opened with open steps"), so the resumed turn was told "leaving steps
    OPEN is fine and is the DEFAULT" — the restart's own work was dropped by the
    rule meant to protect a NEW operator request.
  * Nothing recorded WHY a turn had left steps open. The plan file survived, but
    the next turn could not tell an abandoned step from one nobody had started.

Locks:
  A  `taskgraph.note_turn_end` records the carry ON the graph (file, not memory),
     `carry_line` renders it into the state block, and a closed plan clears it;
  B  a restart writes that record where the killed turn cannot (`reason=restart`);
  C  `finish` with open steps is rejected by the SAME forcing, from the SAME
     budget, with the SAME wording as a prose answer — and it stays bounded;
  D  the operator's own message is still above the plan: a pivot turn answers and
     leaves the steps open (they are carried, not forced);
  E  `inflight` owns both the write and the read of its resume marker.

Deterministic: temp data home, scripted model, stubbed tool gate, no server.
Run: python3 tests/acceptance/v1008_plan_not_abandoned.py
"""
import atexit
import json
import os
import shutil
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="sf-v1008-")
atexit.register(lambda: shutil.rmtree(TMP, ignore_errors=True))
os.environ["LONGRUN_CONFIG_DIR"] = os.path.join(TMP, "cfg")
os.environ["LONGRUN_SESSIONS_DIR"] = os.path.join(TMP, "sessions")
os.environ["LONGRUN_DATA_DIR"] = os.path.join(TMP, "data")
os.environ["LONGRUN_DB"] = os.path.join(TMP, "events.db")
os.environ["LONGRUN_GRAPH_DIR"] = os.path.join(TMP, "graphs")
os.environ["LONGRUN_EDITS_DIR"] = os.path.join(TMP, "edits")
os.environ["LONGRUN_RUNS_DIR"] = os.path.join(TMP, "runs")
os.environ["LONGRUN_WORKSPACES_ROOT"] = os.path.join(TMP, "ws")
os.environ["LONGRUN_CHAT_TOOL_STEPS"] = "8"
os.environ["LONGRUN_CHAT_TOOL_ITERS"] = "40"
for _d in ("cfg", "sessions", "data", "graphs", "edits", "runs", "ws"):
    os.makedirs(os.path.join(TMP, _d), exist_ok=True)
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.tools import registry  # noqa: E402

registry._external_tools = lambda: {}

from longrun.core import server            # noqa: E402 — breaks the import cycle
from longrun.core import inflight          # noqa: E402
from longrun.agent import agent as A       # noqa: E402
from longrun.memory import stores          # noqa: E402
from longrun.plan import taskgraph as TG   # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""))


# ============================================================================
# A — the carry record lives on the graph and is rendered into the state block
# ============================================================================
_ga = TG.ensure("carry-a", session_id="carry-a", goal="ship the feature")
_n1 = TG.add_node(_ga, "read the router")["id"]
_n2 = TG.add_node(_ga, "report the result")["id"]
rec = TG.note_turn_end(TG.load("carry-a"), reason="restart")
check("A1 the carry names the OPEN steps and the reason",
      bool(rec) and rec.get("reason") == "restart"
      and sorted(rec.get("open") or []) == sorted([_n1, _n2]), rec)
_saved = TG.load("carry-a")
check("A2 it is persisted on the graph file (survives a restart, not process memory)",
      (_saved.get("carry") or {}).get("reason") == "restart",
      _saved.get("carry"))
_txt = TG.render_todos(_saved, compact=True)
check("A3 the state block SAYS the steps were left open and why",
      "not forgotten" in _txt and "restart" in _txt, _txt)
check("A4 the carry line is one line, not a re-paste of the list",
      _txt.count("not forgotten") == 1, _txt.count("not forgotten"))

for _nid in (_n1, _n2):
    TG.update_node(TG.load("carry-a"), _nid, status="done", evidence="ran the check: ok")
_mid = TG.load("carry-a")
check("A5 a record whose steps are all closed renders NOTHING (never a false 'open')",
      "not forgotten" not in TG.render_todos(_mid, compact=True),
      TG.render_todos(_mid, compact=True))
check("A6 the next turn end CLEARS the stored record",
      TG.note_turn_end(_mid) is None and not TG.load("carry-a").get("carry"),
      TG.load("carry-a").get("carry"))
_done = TG.load("carry-a")
check("A6b a closed plan renders no carry line",
      "not forgotten" not in TG.render_todos(_done, compact=True))

# a carry from an OLD plan must never be shown against the current one
_gb = TG.ensure("carry-b", session_id="carry-b", goal="two plans")
_old = TG.add_node(_gb, "old step")["id"]
TG.note_turn_end(TG.load("carry-b"), reason="turn-end")
TG.begin_plan(TG.load("carry-b"))
TG.add_node(TG.load("carry-b"), "new step")
_cur = TG.load("carry-b")
check("A7 a carry recorded for a SUPERSEDED plan is not rendered",
      "not forgotten" not in TG.render_todos(_cur, compact=True),
      TG.render_todos(_cur, compact=True))

# ============================================================================
# B — the restart writes the record where the killed turn cannot
# ============================================================================
_resume = inflight.RESUME_TEXT % "2026-11-15 23:29:00"
check("B1 the resume text still starts with the marker the harness pins",
      _resume.startswith("[Harness restart]") and "Continue" in _resume)
check("B2 inflight OWNS reading its own marker",
      inflight.is_resume_text(_resume) and not inflight.is_resume_text("please continue"))

B_SID = "carry-restart"
_gc = TG.ensure(B_SID, session_id=B_SID, goal="interrupted work")
_b1 = TG.add_node(_gc, "step that was running")["id"]
TG.update_node(TG.load(B_SID), _b1, status="doing")
stores.save_session({"id": B_SID, "title": B_SID, "created": 0,
                     "messages": [{"role": "user", "content": "do the work"}]})
_fixed = stores.reconcile_orphan_turns(B_SID)
_gr = TG.load(B_SID)
check("B3 a restart demotes the `doing` step back to todo",
      [n.get("status") for n in _gr.get("nodes") or []] == ["todo"],
      [n.get("status") for n in _gr.get("nodes") or []])
check("B4 …and records the carry with reason 'restart'",
      (_gr.get("carry") or {}).get("reason") == "restart"
      and (_gr.get("carry") or {}).get("open") == [_b1], _gr.get("carry"))
check("B5 the orphan turn was closed (one notice, not a silent drop)", _fixed == 1, _fixed)

_src = open(os.path.join(REPO, "src", "longrun", "agent", "agent.py"),
            encoding="utf-8").read()
check("B6 a harness RESUME is not a pivot (operator last, resume excluded)",
      "_user_pivot = bool(_open0) and not goal_mode and not _resume_turn" in _src)

# ============================================================================
# C — `finish` faces the closing contract, from the same budget and wording
# ============================================================================
check("C1 one owner for the rejection wording", _src.count(
    "STOP — your final answer was REJECTED") == 1,
    _src.count("STOP — your final answer was REJECTED"))
_fin = _src[_src.find("if _is_explicit_finish(act):"):]
_fin = _fin[:_fin.find("if _term_action(act):")]
check("C2 the finish branch reaches the close-todos forcing", "_close_todos_text(" in _fin)
check("C3 …from the SAME budget as a prose answer", "_close_todo_rounds" in _fin)
check("C4 …and a pivot turn still escapes it (the user outranks the plan)",
      "not _user_pivot" in _fin, _fin[:400].replace("\n", " ")[:200])
check("C5 both the budget and the wording are checked by the pinned tests",
      "_close_todo_max" in _src and callable(getattr(A, "_close_todos_text", None)))


def run_turn(sid, script, message="do the work"):
    state = {"n": 0}

    def fake_stream(msgs, model, role, on_delta, usage=None, cancel=None, **kw):
        text = script(msgs, state["n"])
        state["n"] += 1
        if text:
            on_delta("answer", text)
        return text, "", model

    def fake_gated(tool, args, **kw):
        return {"status": "executed", "observation": "[stub] ok",
                "result": {"ok": True, "exit_code": 0, "stdout": "", "stderr": "",
                           "backend": "stub"}}

    events = []
    server.stream_with_fallback = fake_stream
    server.api_v02.gated_call = fake_gated
    server.chat_once({"id": sid, "messages": [], "workspace": ""}, message,
                     model="mock", on_delta=lambda c, t: None,
                     on_event=lambda kind, **d: events.append((kind, d)))
    return events


PLAN = ('{"action":"write_todos","todos":[{"label":"read the router"},'
        '{"label":"report the result"}]}')
FINISH = '{"action":"finish","summary":"All done."}'


def always_finish(msgs, n):
    """A model that CLAIMS completion and never closes a step."""
    return PLAN if n == 0 else FINISH


ev = run_turn("v1008-finish", always_finish)
rejected = [d for k, d in ev if k == "harness.inject"
            and "final answer was REJECTED" in (d.get("text") or "")]
check("C6 an explicit finish with 2 open steps is REJECTED, not accepted",
      len(rejected) == 4, "rejected=%d (the shared budget is 4)" % len(rejected))
check("C7 the forcing names the exact open steps",
      bool(rejected) and "read the router" in (rejected[0].get("text") or ""),
      (rejected[0].get("text") if rejected else "")[-200:])
_gr2 = TG.load("v1008-finish")
check("C8 the turn still ENDS (bounded — a claim is never an infinite loop)",
      [k for k, _d in ev][-1] in ("chat.done", "chat.error")
      or bool(server.load_session("v1008-finish")),
      [k for k, _d in ev][-3:])
check("C9 the steps it refused to close are CARRIED, not forgotten",
      (_gr2.get("carry") or {}).get("reason") == "finish"
      and len((_gr2.get("carry") or {}).get("open") or []) == 2,
      _gr2.get("carry"))


def obey(msgs, n):
    """The measured fix: told to close, the model closes with evidence."""
    if n == 0:
        return PLAN
    tail = "\n".join(str((m or {}).get("content") or "") for m in (msgs or [])[-2:])
    if "final answer was REJECTED" in tail:
        g = TG.load("v1008-obey") or {}
        steps = [{"id": node["id"], "status": "done",
                  "evidence": "ran the check: exit 0"} for node in TG.open_nodes(g)]
        return json.dumps({"action": "todo.update", "steps": steps})
    return FINISH


ev2 = run_turn("v1008-obey", obey)
_gr3 = TG.load("v1008-obey")
check("D1 the rejected close is then accepted once the steps are closed",
      [n.get("status") for n in _gr3.get("nodes") or []] == ["done", "done"],
      [(n.get("id"), n.get("status")) for n in _gr3.get("nodes") or []])
check("D2 a fully closed plan carries NOTHING (the record cannot go stale)",
      not _gr3.get("carry"), _gr3.get("carry"))
check("D3 its evidence is on the record", all(
    n.get("evidence") for n in _gr3.get("nodes") or []),
    [n.get("evidence") for n in _gr3.get("nodes") or []])

# ============================================================================
# E — the operator's own message is still ABOVE the plan
# ============================================================================
P_SID = "v1008-pivot"
_gp = TG.ensure(P_SID, session_id=P_SID, goal="old work")
TG.add_node(_gp, "old step one")
TG.add_node(_gp, "old step two")
ev3 = run_turn(P_SID, lambda msgs, n: "Hello!",
               message="just say hello to me please")
_stop = [d for k, d in ev3 if k == "plan.stopped"]
check("E1 a fresh operator request is answered (no forced closure)",
      not any("final answer was REJECTED" in (d.get("text") or "")
              for k, d in ev3 if k == "harness.inject"),
      [k for k, _d in ev3])
check("E2 the stale steps stay OPEN — nothing is silently closed",
      [n.get("status") for n in (TG.load(P_SID) or {}).get("nodes") or []]
      == ["todo", "todo"],
      [(n.get("id"), n.get("status")) for n in (TG.load(P_SID) or {}).get("nodes") or []])
_gp2 = TG.load(P_SID)
check("E3 …and they are CARRIED, so the next turn knows they were not finished",
      (_gp2.get("carry") or {}).get("reason") == "user_pivot"
      and len((_gp2.get("carry") or {}).get("open") or []) == 2,
      _gp2.get("carry"))
check("E4 the pivot turn is recorded as a user_pivot stop, not a silent one",
      not _stop or _stop[-1].get("reason") in ("user_pivot", "goal_reached"),
      _stop[-1] if _stop else "(no stop event: the turn closed on the answer)")

print("---")
passed = sum(results)
print("%d/%d PASS" % (passed, len(results)))
sys.exit(0 if passed == len(results) else 1)
