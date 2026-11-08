#!/usr/bin/env python3
"""v903 — a dispatch hands back a JOB handle instead of parking the turn (2026-11-08).

Operator: *"if during a dispatch I ask something else to the agent making the
dispatch, it goes on queue however it's wrong since a dispatch can be done
independently so it may be a direct call"*.

The delegating turn used to JOIN the teammate's thread and wait up to
`runtime.dispatch_wait_secs` (3600 s): the operator's next message waited behind
it, and when the wait expired the teammate's reply was lost to a "still running"
note. Now a dispatch is a JOB — created and started, its id returned at once —
and the reply comes back through `util.inbox.deliver` when the job ends
(v902). `wait:true` keeps the old inline turn, and a busy teammate is only a
problem in THAT mode (the detached path simply queues).

Deterministic, no model, no server. Run: python3 tests/acceptance/v903_detached_dispatch.py
"""
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="sf-903-")
for k, v in {
    "LONGRUN_AGENTS_FILE": os.path.join(TMP, "agents.json"),
    "LONGRUN_SESSIONS_DIR": os.path.join(TMP, "sessions"),
    "LONGRUN_GRAPH_DIR": os.path.join(TMP, "graphs"),
    "LONGRUN_DB": os.path.join(TMP, "events.db"),
    "LONGRUN_CONFIG_DIR": os.path.join(TMP, "cfg"),
    "LONGRUN_JOBS_FILE": os.path.join(TMP, "jobs.json"),
    "LONGRUN_TEAMS_FILE": os.path.join(TMP, "teams.json"),
}.items():
    os.environ[k] = v
for d in ("sessions", "graphs", "cfg"):
    os.makedirs(os.path.join(TMP, d), exist_ok=True)
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.core import server as S              # noqa: E402
from longrun.agent import agents as A             # noqa: E402
from longrun.orchestrate import jobs as J         # noqa: E402
from longrun.core import events as events_mod     # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""))


# ---- fixtures: an org chart + stubbed session machinery ---------------------
_store = {}


def _goc(sid):
    _store.setdefault(sid, {"id": sid, "messages": []})
    return _store[sid]


def _load(sid):
    return _store.get(sid) or {"id": sid, "messages": []}


inline_turns = []


def _stream(sess, message, model, *a, **k):
    inline_turns.append((sess.get("id"), message))
    sess.setdefault("messages", []).append({"role": "user", "content": message})
    sess["messages"].append({"role": "assistant", "content": "ACK inline from %s" % sess["id"]})
    return iter(())


S.get_or_create_session = _goc
S.load_session = _load
S.chat_stream_gen = _stream

ev = []
on_event = lambda kind, **kw: ev.append((kind, kw))  # noqa: E731

M = A.REGISTRY.designate("sess_master", name="Master", role="orchestrator")["agent"]
W = A.REGISTRY.designate("sess_worker", name="Worker", role="builder",
                         reports_to=M["id"])["agent"]
A.REGISTRY.designate("sess_stranger", name="Stranger")
master = {"id": "sess_master", "messages": []}

# ---- A) detached by default: a job handle, no inline turn -------------------
started = []
_orig_dispatch = J.JOBS.dispatch
J.JOBS.dispatch = lambda jid: (started.append(jid) or {"ok": True, "job": jid,
                                                       "status": "running"})
inline_turns.clear()
out = S._apply_chat_dispatch(master, {"action": "dispatch", "agent": W["id"],
                                      "goal": "write the parser"}, on_event)
check("A1 a dispatch does NOT run the teammate's turn inline", not inline_turns, inline_turns)
check("A2 it returns a job handle", " as job J" in out, out[:160])
jid = started[0] if started else ""
check("A3 it started exactly one job", jid.startswith("J"), started)
job = J.JOBS.get(jid) or {}
check("A4 the job is assigned to the teammate",
      (job.get("agents") or []) == [W["id"]] and job.get("coordinator") == W["id"], job.get("agents"))
check("A5 the job records the ASSIGNER (who gets the reply)",
      job.get("assigned_by") == M["id"], job.get("assigned_by"))
check("A6 a dispatch job has no coordinator planning turn",
      job.get("mode") == "run", job.get("mode"))
check("A7 the observation names the job and how to read it",
      jid in out and "job.get" in out and "do NOT re-dispatch" in out, out[:200])
check("A8 the job id is in the transcript card's args",
      any(k == "tool.result" and (kw.get("args") or {}).get("job") == jid for k, kw in ev))

# ---- B) a BUSY teammate is accepted (it queues), not refused ---------------
busy_state = {"on": True}
_orig_active = events_mod.turn_active
events_mod.turn_active = lambda sid: bool(busy_state.get("on"))
started.clear()
inline_turns.clear()
out = S._apply_chat_dispatch(master, {"action": "dispatch", "agent": W["id"],
                                      "goal": "second task"}, on_event)
check("B1 a dispatch to a busy teammate is ACCEPTED (queued as a job)",
      " as job J" in out and len(started) == 1 and not inline_turns, out[:160])
# ---- C) wait:true keeps the inline turn ------------------------------------
J.JOBS.dispatch = _orig_dispatch
events_mod.turn_active = lambda sid: False
busy_state["on"] = False
inline_turns.clear()
out = S._apply_chat_dispatch(master, {"action": "dispatch", "agent": W["id"],
                                      "goal": "inline please", "wait": True}, on_event)
check("C1 wait:true runs the teammate's turn inside THIS turn",
      len(inline_turns) == 1 and inline_turns[0][0] == "sess_worker", inline_turns)
check("C2 wait:true returns the teammate's reply", "ACK inline from sess_worker" in out, out[:160])
events_mod.turn_active = lambda sid: True
out = S._apply_chat_dispatch(master, {"action": "dispatch", "agent": W["id"],
                                      "goal": "inline busy", "wait": True}, on_event)
check("C3 wait:true on a busy teammate still fails fast (never parks the caller)",
      out.startswith("dispatch error") and "busy" in out, out[:160])
events_mod.turn_active = _orig_active

# ---- D) the guard rails are unchanged --------------------------------------
inline_turns.clear()
out = S._apply_chat_dispatch(master, {"action": "dispatch", "agent": "A99", "goal": "x"}, on_event)
check("D1 a NON-report is still refused", "not one of your direct reports" in out, out)
out = S._apply_chat_dispatch({"id": "sess_nobody", "messages": []},
                             {"action": "dispatch", "agent": W["id"], "goal": "x"}, on_event)
check("D2 a non-agent session still cannot dispatch", "not an org agent" in out, out)
out = S._apply_chat_dispatch(master, {"action": "dispatch", "agent": W["id"]}, on_event)
check("D3 a goal is still required", "goal required" in out, out)

# ---- E) the brief a run-mode worker receives is never empty ----------------
JOBS_SRC = open(os.path.join(REPO, "src", "longrun", "orchestrate", "jobs.py"),
                encoding="utf-8").read()
check("E1 a run-mode job hands the GOAL as the worker's assignment (v904: so does "
      "a coordinator job whose plan gave this agent no readable line)",
      'or job["goal"])' in JOBS_SRC)
check("E2 the assigner's name rides the delegation message in run mode",
      "sender_label = coord_label or (" in JOBS_SRC
      and "_delegation_msg(jid, sender_label" in JOBS_SRC)
check("E3 the reply slice is anchored on THIS turn's own user message (never a "
      "count taken before the worker's lock)",
      "def _turn_tail(" in JOBS_SRC and 'meta.get("subjob") == subjob' in JOBS_SRC
      and "with _events._turn_lock(sid):" not in JOBS_SRC)
_msgs = [{"role": "user", "content": "someone else"},
         {"role": "assistant", "content": "NOT MINE"},
         {"role": "user", "content": "mine", "meta": {"subjob": "J1.1"}},
         {"role": "assistant", "content": "MINE"}]
_tail = J.JobRegistry._turn_tail(_msgs, 0, "A8", "J1.1")
check("E4 the tail starts at this subjob's own user message",
      _tail and _tail[0].get("content") == "mine", _tail)

# ---- F) the prompts teach the new contract ---------------------------------
AG = open(os.path.join(REPO, "src", "longrun", "agent", "agent.py"), encoding="utf-8").read()
check("F1 the dispatch prompt says DETACHED and names job.get",
      "It is DETACHED" in AG and "readable any time with job.get" in AG)
check("F2 the prompt keeps the wait:true escape hatch",
      '"wait":true only when you must have the answer inside THIS turn' in AG)
check("F3 the v618 pins are intact (no silent rewording)",
      "run the dependency waves in order (job.dispatch, no shell needed)" in AG
      and "approvals.mode=full does NOT bypass it" in AG
      and "`dispatch` (a teammate turn, no grant needed)" in AG)
from longrun.core import api_v02 as api            # noqa: E402
TC = api.tool_context()
check("F4 tool_context says a dispatch is detached and returns a job id",
      "A dispatch is DETACHED" in TC and "returns a job id" in TC, len(TC))
check("F5 tool_context still tells the model dispatches group per teammate",
      "sequential" in TC and "dispatch" in TC)

# ---- summary ---------------------------------------------------------------
bad = results.count(False)
print("\n%d/%d checks passed" % (len(results) - bad, len(results)))
sys.exit(1 if bad else 0)
