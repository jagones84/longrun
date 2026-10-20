#!/usr/bin/env python3
"""v510 — /goal continues until its evidenced task graph is complete.

Deterministic: scripted model output, isolated Longrun state, no network.
"""
import os
import sys
import tempfile
import time as _real_time

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="sf-v510-")
for _key in ("CONFIG_DIR", "SESSIONS_DIR", "GRAPH_DIR", "EDITS_DIR",
             "RUNS_DIR", "DATA_DIR", "THREADS_DIR", "COSTS_DIR"):
    os.environ["LONGRUN_" + _key] = os.path.join(TMP, _key)
    os.makedirs(os.environ["LONGRUN_" + _key], exist_ok=True)
os.environ["LONGRUN_DB"] = os.path.join(TMP, "events.db")
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.core import server  # noqa: E402
from longrun.core import matrix as matrix_core  # noqa: E402
from longrun.agent import agent as A  # noqa: E402
from longrun.interop import mcp_client  # noqa: E402
from longrun.plan import bestofn, keepgoing, taskgraph  # noqa: E402

RESULTS = []
_original_mcp_get_manager = mcp_client.get_manager
_offline_mcp_manager = mcp_client.MCPClientManager()
_offline_mcp_manager.start_all = lambda: None
mcp_client.get_manager = lambda: _offline_mcp_manager


def check(name, ok, detail=""):
    RESULTS.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name
          + ((" :: " + str(detail)) if detail else ""))


_LIMITS = {
    "keepgoing_max": 2,
    "no_progress_rounds": 2,
    "max_wall_secs": 10,
    "autocontinue": False,
}

# /goal treats round and no-progress limits as recovery triggers. The wall limit
# remains a visible, incomplete safety stop.
_round_limit = keepgoing.decide(
    open_nodes=1, rounds=9, stale=0, started=0, now=1,
    goal_mode=True, goal_complete=False, override=_LIMITS)
check("goal mode continues past configured round limit",
      _round_limit["continue"] is True, _round_limit)

_stalled = keepgoing.decide(
    open_nodes=1, rounds=0, stale=3, started=0, now=1,
    goal_mode=True, goal_complete=False, override=_LIMITS)
check("goal mode recovers instead of stopping on no progress",
      _stalled["continue"] is True and _stalled["reason"] == "goal_recovery",
      _stalled)

_empty = keepgoing.decide(
    open_nodes=0, rounds=0, stale=0, started=0, now=1,
    goal_mode=True, goal_complete=False, override=_LIMITS)
check("an empty task list is not mistaken for a completed goal",
      _empty["continue"] is True and _empty["reason"] == "goal_recovery",
      _empty)

_empty_wall = keepgoing.decide(
    open_nodes=0, rounds=0, stale=0, started=0, now=10,
    goal_mode=True, goal_complete=False, override=_LIMITS)
check("an incomplete empty plan still respects the wall-clock safety cap",
      _empty_wall["continue"] is False and _empty_wall["reason"] == "budget",
      _empty_wall)

_no_plan = taskgraph.ensure("v510-no-plan", session_id="v510-no-plan")
check("a missing plan is not evidence of goal completion",
      taskgraph.goal_complete(_no_plan) is False)

_only_superseded = taskgraph.ensure(
    "v510-superseded", session_id="v510-superseded")
_superseded_node = taskgraph.add_node(_only_superseded, "Unneeded step")
taskgraph.update_node(_only_superseded, _superseded_node["id"],
                      status="superseded", reason="The objective changed")
check("a plan with no completed work is not goal completion",
      taskgraph.goal_complete(_only_superseded) is False)

_blank_evidence = taskgraph.ensure(
    "v510-blank-evidence", session_id="v510-blank-evidence")
_blank_node = taskgraph.add_node(_blank_evidence, "Corrupted legacy evidence")
_blank_node["status"] = "done"
_blank_node["evidence"] = [{"text": "   "}]
taskgraph.save(_blank_evidence)
check("blank legacy evidence cannot prove goal completion",
      taskgraph.goal_complete(_blank_evidence) is False)

_done_plan = taskgraph.ensure("v510-done", session_id="v510-done")
taskgraph.add_node(_done_plan, "Verified step", status="done",
                   evidence="The deterministic verification passed")
check("a completed plan needs evidence",
      taskgraph.goal_complete(_done_plan) is True)

_complete = keepgoing.decide(
    open_nodes=0, rounds=0, stale=0, started=0, now=1,
    goal_mode=True, goal_complete=True, override=_LIMITS)
check("goal mode stops only after the task graph is evidenced complete",
      _complete["continue"] is False and _complete["reason"] == "goal_reached",
      _complete)

_blocked = keepgoing.decide(
    open_nodes=1, rounds=0, stale=0, started=0, now=1, blocked=True,
    goal_mode=True, goal_complete=False, override=_LIMITS)
check("an explicitly blocked goal stops honestly",
      _blocked["continue"] is False and _blocked["reason"] == "blocked",
      _blocked)

_aborted = keepgoing.decide(
    open_nodes=1, rounds=0, stale=0, started=0, now=1, aborted=True,
    goal_mode=True, goal_complete=False, override=_LIMITS)
check("operator Stop still aborts goal mode",
      _aborted["continue"] is False and _aborted["reason"] == "user_stop",
      _aborted)

_wall = keepgoing.decide(
    open_nodes=1, rounds=0, stale=0, started=0, now=10,
    goal_mode=True, goal_complete=False, override=_LIMITS)
check("the wall-clock safety cap remains a non-success stop",
      _wall["continue"] is False and _wall["reason"] == "budget", _wall)

_ordinary = keepgoing.decide(
    open_nodes=1, rounds=2, stale=0, started=0, now=1, override=_LIMITS)
check("ordinary chat keeps its configured round budget",
      _ordinary["continue"] is False and _ordinary["reason"] == "budget",
      _ordinary)

_original_keepgoing_hook = matrix_core.call_hook
matrix_core.call_hook = lambda *args, **kwargs: {
    "continue": False, "reason": "goal_reached"}
try:
    _hook_false_success = keepgoing.decide(
        open_nodes=1, rounds=1, stale=0, started=0, now=1,
        goal_mode=True, goal_complete=False, override=_LIMITS)
finally:
    matrix_core.call_hook = _original_keepgoing_hook
check("a Matrix hook cannot claim an incomplete goal was reached",
      _hook_false_success["continue"] is True
      and _hook_false_success["reason"] == "goal_recovery",
      _hook_false_success)

# An agent must not accept final prose, a terminal-action envelope, or an
# artifact while the explicit goal has no plan or still-open work.
_sid = "v510-goal"
_session = {
    "id": _sid,
    "title": _sid,
    "messages": [{"role": "assistant", "content": "fixture prior turn"},
                 {"role": "user", "content": "Complete and verify the requested task."}],
}
_script = [
    ("Done.", "", "fixture"),
    ('{"action":"todo.write","todos":[{"label":"Verify the requested result"}]}',
     "", "fixture"),
    ('{"action":"finish","summary":"premature success"}', "", "fixture"),
    ('{"artifact":"premature result"}', "", "fixture"),
    ('{"action":"todo.update","steps":[{"index":0,"status":"done",'
     '"evidence":"verified by the deterministic test"}]}', "", "fixture"),
    ("Goal complete: the requested result is verified.", "", "fixture"),
]
_calls = {"count": 0}
_original_stream = server.stream_with_fallback
_original_tool_context = server._tool_context


def _scripted_stream(msgs, model, kind, on_delta, **kwargs):
    _calls["count"] += 1
    return _script.pop(0) if _script else ("unexpected extra call", "", model)


server.stream_with_fallback = _scripted_stream
server._tool_context = lambda: "fixture tool context"
try:
    _reply, _model = A.chat_once(
        _session, "Complete and verify the requested task.", "fixture",
        autonomous=True, goal_mode=True)
finally:
    server.stream_with_fallback = _original_stream
    server._tool_context = _original_tool_context
    mcp_client.get_manager = _original_mcp_get_manager

_graph = taskgraph.load(_sid)
_nodes = taskgraph.plan_nodes(_graph)
check("the goal loop asks for work after an unplanned final answer",
      _calls["count"] == 6, _calls)
check("the goal loop reaches the final answer only after todo evidence",
      len(_nodes) == 1 and _nodes[0].get("status") == "done"
      and bool(_nodes[0].get("evidence"))
      and "Goal complete:" in (_reply or {}).get("content", ""),
      {"nodes": _nodes, "reply": (_reply or {}).get("content", "")})


class _DeadlineClock:
    def __init__(self):
        self.current = _real_time.time()

    def time(self):
        return self.current

    def advance(self, seconds):
        self.current += seconds

    def __getattr__(self, name):
        return getattr(_real_time, name)


_expired_sid = "v510-expired"
_expired_session = {
    "id": _expired_sid,
    "title": _expired_sid,
    "messages": [{"role": "assistant", "content": "fixture prior turn"},
                 {"role": "user", "content": "Complete the expired task."}],
}
_expired_calls = {"count": 0}
_expired_clock = _DeadlineClock()
_expired_originals = {
    "stream": server.stream_with_fallback,
    "tool_context": server._tool_context,
    "get_manager": mcp_client.get_manager,
    "cfg": keepgoing.cfg,
    "time": A.time,
}


def _expired_stream(msgs, model, kind, on_delta, **kwargs):
    _expired_calls["count"] += 1
    return ("unexpected call after the supplied deadline", "", model)


server.stream_with_fallback = _expired_stream
server._tool_context = lambda: "fixture tool context"
mcp_client.get_manager = lambda: _offline_mcp_manager
keepgoing.cfg = lambda override=None: dict(_LIMITS, **(override or {}))
A.time = _expired_clock
try:
    _expired_reply, _expired_model = A.chat_once(
        _expired_session, "Complete the expired task.", "fixture",
        autonomous=True, goal_mode=True,
        goal_started=_expired_clock.current - _LIMITS["max_wall_secs"])
finally:
    server.stream_with_fallback = _expired_originals["stream"]
    server._tool_context = _expired_originals["tool_context"]
    mcp_client.get_manager = _expired_originals["get_manager"]
    keepgoing.cfg = _expired_originals["cfg"]
    A.time = _expired_originals["time"]

check("a deadline inherited from the request prevents a new model call",
      _expired_calls["count"] == 0
      and "Goal incomplete:" in (_expired_reply or {}).get("content", ""),
      {"calls": _expired_calls["count"],
       "reply": (_expired_reply or {}).get("content", "")})

_bestofn_sid = "v510-bestofn-deadline"
_bestofn_session = {
    "id": _bestofn_sid,
    "title": _bestofn_sid,
    "messages": [{"role": "assistant", "content": "fixture prior turn"},
                 {"role": "user", "content": "Complete the sampled task."}],
}
_bestofn_calls = {"count": 0}
_bestofn_clock = _DeadlineClock()
_bestofn_originals = {
    "stream": server.stream_with_fallback,
    "tool_context": server._tool_context,
    "get_manager": mcp_client.get_manager,
    "cfg": keepgoing.cfg,
    "n_of": bestofn.n_of,
    "time": A.time,
}


def _bestofn_stream(msgs, model, kind, on_delta, **kwargs):
    _bestofn_calls["count"] += 1
    _bestofn_clock.advance(_LIMITS["max_wall_secs"])
    return ('{"action":"tool","tool":"fixture",', "", model)


server.stream_with_fallback = _bestofn_stream
server._tool_context = lambda: "fixture tool context"
mcp_client.get_manager = lambda: _offline_mcp_manager
keepgoing.cfg = lambda override=None: dict(_LIMITS, **(override or {}))
bestofn.n_of = lambda *args, **kwargs: 3
A.time = _bestofn_clock
try:
    _bestofn_reply, _bestofn_model = A.chat_once(
        _bestofn_session, "Complete the sampled task.", "fixture",
        autonomous=True, goal_mode=True)
finally:
    server.stream_with_fallback = _bestofn_originals["stream"]
    server._tool_context = _bestofn_originals["tool_context"]
    mcp_client.get_manager = _bestofn_originals["get_manager"]
    keepgoing.cfg = _bestofn_originals["cfg"]
    bestofn.n_of = _bestofn_originals["n_of"]
    A.time = _bestofn_originals["time"]

check("the deadline prevents best-of-N samples after the main response",
      _bestofn_calls["count"] == 1
      and "Goal incomplete:" in (_bestofn_reply or {}).get("content", ""),
      {"calls": _bestofn_calls["count"],
       "reply": (_bestofn_reply or {}).get("content", "")})


_wall_sid = "v510-wall"
_wall_session = {
    "id": _wall_sid,
    "title": _wall_sid,
    "messages": [{"role": "assistant", "content": "fixture prior turn"},
                 {"role": "user", "content": "Complete the long task."}],
}
_wall_script = [
    ('{"action":"todo.write","todos":[{"label":"Complete the long task"}]}',
     "", "fixture"),
    ('{"action":"todo.update","steps":[{"index":0,"status":"done",'
     '"evidence":"verified after the cap"}]}', "", "fixture"),
    ("Goal complete.", "", "fixture"),
]
_wall_calls = {"count": 0}
_wall_clock = _DeadlineClock()
_wall_originals = {
    "stream": server.stream_with_fallback,
    "tool_context": server._tool_context,
    "get_manager": mcp_client.get_manager,
    "cfg": keepgoing.cfg,
    "time": A.time,
}


def _wall_stream(msgs, model, kind, on_delta, **kwargs):
    _wall_calls["count"] += 1
    _wall_clock.advance(6)
    return _wall_script.pop(0) if _wall_script else ("unexpected extra call", "", model)


server.stream_with_fallback = _wall_stream
server._tool_context = lambda: "fixture tool context"
mcp_client.get_manager = lambda: _offline_mcp_manager
keepgoing.cfg = lambda override=None: dict(_LIMITS, **(override or {}))
A.time = _wall_clock
try:
    _wall_reply, _wall_model = A.chat_once(
        _wall_session, "Complete the long task.", "fixture",
        autonomous=True, goal_mode=True)
finally:
    server.stream_with_fallback = _wall_originals["stream"]
    server._tool_context = _wall_originals["tool_context"]
    mcp_client.get_manager = _wall_originals["get_manager"]
    keepgoing.cfg = _wall_originals["cfg"]
    A.time = _wall_originals["time"]

check("repeated todo actions cannot bypass the wall-clock cap",
      _wall_calls["count"] == 2
      and "Paused:" in (_wall_reply or {}).get("content", ""),
      {"calls": _wall_calls["count"],
       "reply": (_wall_reply or {}).get("content", "")})

print("---")
_passed = sum(RESULTS)
print("v510: %d/%d PASS" % (_passed, len(RESULTS)))
sys.exit(0 if _passed == len(RESULTS) else 1)
