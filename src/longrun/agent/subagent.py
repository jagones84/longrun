#!/usr/bin/env python3
"""Longrun subagent delegation — v0.3

Pattern (deepagents / hierarchical agents): the main agent loop can spawn child
agent runs (subagents) with an isolated context, let them execute, and collect
their result. This enables:

  - Parallel subtask execution
  - Delegation of specialized goals to a different model
  - Recursive decomposition of complex goals

Subagent runs share the same harness infrastructure (tools, sandbox, approvals)
but get their own plan/tasks context and a fresh transcript. The parent receives
a summary / trace when the child finishes.

Usage (from agent loop):
    {"action": "subagent", "goal": "...", "max_steps": 4, "model": "..."}
    {"action": "subagent_result", "id": "..."}
"""

import json
import threading
import time
import uuid

from longrun.core import api_v02  # for the RunState / agent_run_v2 machinery
from longrun.tools import approvals
from longrun.tools import registry
from longrun.tools import sandbox
from longrun.plan import taskgraph  # per-run task graph (child gets its own todo list)
from longrun.tools import tools as toolmod

_lock = threading.RLock()
_running = {}     # subagent_id -> {state, parent_run_id, goal, result}
_DEPTH = {}       # run_id -> depth of nesting (matrioska); 0 = top level


def depth_of(run_id):
    """Depth of a run: 0 for top-level, +1 for each delegated level."""
    return _DEPTH.get(run_id, 0)


def depth_allowed(depth, max_depth=None):
    """True se si puo' ancora annidare (matrioska) sotto `depth` livelli."""
    from longrun.plan import keepgoing
    md = int(keepgoing.cfg()["subagent_max_depth"])
    if max_depth is not None:
        md = int(max_depth)
    return int(depth) < md


def spawn(goal, parent_run_id=None, max_steps=4, model=None, on_event=None, depth=0):
    """Spawn a subagent run and return its id.

    The subagent runs asynchronously in a background thread. Call
    `collect(subagent_id)` to get the result (blocks until done).

    Returns a dict with subagent_id (caller should store it).
    """
    fallbacks = []
    if not model:
        # JAG-259: honour an explicitly pinned "subagent" role model (Settings ->
        # Models) before the role pattern, so the WebUI setting actually applies.
        try:
            from longrun.model import routing
            model = routing.role_model("subagent") or routing.pick("subagent")
            # JAG-448: a real failover chain for cloud subagent models (literal
            # provider:model refs from config, never hardcoded).
            fallbacks = routing.model_chain("subagent")[1:]
        except Exception:  # noqa: BLE001 — routing must never block a spawn
            model = None
    if not depth_allowed(depth):
        return {"subagent_id": None, "run_id": None, "goal": goal,
                "error": "max subagent depth reached"}
    sid = "sub_%s" % uuid.uuid4().hex[:10]
    st = api_v02.new_run("%s (subagent %s)" % (goal[:80], sid), model, max_steps)
    st.parent_run_id = parent_run_id
    _DEPTH[st.id] = int(depth)
    taskgraph.ensure(st.id, session_id=st.id, goal=goal)

    entry = {
        "id": sid,
        "state": st,
        "goal": goal,
        "max_steps": max_steps,
        "model": model,
        "parent_run_id": parent_run_id,
        "created": time.time(),
        "result": None,
        "done": threading.Event(),
    }

    with _lock:
        _running[sid] = entry

    def _run():
        try:
            from longrun.core.server import publish as _publish
            _publish("subagent.start", subagent_id=sid, parent=parent_run_id,
                     goal=goal, max_steps=max_steps, model=model)
        except Exception:
            pass
        # JAG-431r4b: a crash in the child run used to kill this thread SILENTLY —
        # `done` was never set, the parent blocked for the full SUBAGENT_WAIT and
        # reported a bogus "subagent timeout". Always complete the handshake.
        try:
            result = api_v02.agent_run_v2(
                goal, max_steps, model, on_event=on_event, run_id=st.id,
                fallbacks=fallbacks)
            entry["result"] = result
            status_txt = result.get("status")
            steps_n = len(result.get("trace", []))
        except Exception as e:  # noqa: BLE001 — the parent must see the failure
            entry["result"] = {"ok": False, "status": "error", "error": str(e),
                               "summary": "subagent crashed: %s" % e, "trace": []}
            status_txt, steps_n = "error", 0
        finally:
            entry["done"].set()
        try:
            from longrun.core.server import publish as _publish
            _publish("subagent.done", subagent_id=sid, parent=parent_run_id,
                     goal=goal, status=status_txt, steps=steps_n)
        except Exception:
            pass

    threading.Thread(target=_run, daemon=True, name="subagent-%s" % sid).start()
    _publish_event(parent_run_id, "subagent.spawned",
                   subagent_id=sid, goal=goal, max_steps=max_steps, model=model)
    return {"subagent_id": sid, "run_id": st.id, "goal": goal}


def collect(subagent_id, timeout=None):
    """Wait for a subagent to finish and return the result.

    If timeout is None, blocks indefinitely (the main agent loop has a
    max_steps counter, so this is bounded in practice).

    Returns: {"ok": bool, "result": ..., "trace": [...], "summary": str}
    """
    with _lock:
        entry = _running.get(subagent_id)
    if entry is None:
        return {"ok": False, "error": "subagent %r not found" % subagent_id}
    if not entry["done"].wait(timeout=timeout):
        return {"ok": False, "error": "subagent timeout", "subagent_id": subagent_id}
    # JAG-431r4b: pop the finished entry — _running/_DEPTH kept every completed
    # subagent forever (status() listed dead runs; both dicts grew unboundedly).
    with _lock:
        done_entry = _running.pop(subagent_id, None)
        if done_entry is not None:
            st = done_entry.get("state")
            if st is not None:
                _DEPTH.pop(st.id, None)
    result = entry["result"] or {}
    summary = result.get("summary", "")
    parent_run_id = entry.get("parent_run_id")
    if parent_run_id and summary:
        try:
            graph = taskgraph.load(parent_run_id)
            child_run_id = entry.get("state").id if entry.get("state") else None
            if graph and child_run_id:
                for n in graph.get("nodes", []):
                    if n.get("child_run_id") == child_run_id:
                        taskgraph.update_node(
                            graph, n["id"],
                            evidence="[subagent] " + str(summary)[:400])
                        break
        except Exception:
            pass
    return {
        "ok": result.get("status") == "done",
        "status": result.get("status"),
        "result": result,
        "trace": result.get("trace", []),
        "summary": summary,
        "steps": len(result.get("trace", [])),
        "subagent_id": subagent_id,
    }


def status(subagent_id=None):
    """List running / recent subagents, or one by id."""
    with _lock:
        if subagent_id:
            e = _running.get(subagent_id)
            if not e:
                return None
            return {
                "id": e["id"],
                "goal": e["goal"][:120],
                "state": e["state"].status if e["state"] else "unknown",
                "done": e["done"].is_set(),
                "created": e["created"],
            }
        return [{
            "id": e["id"],
            "goal": e["goal"][:80],
            "state": e["state"].status if e["state"] else "unknown",
            "done": e["done"].is_set(),
            "created": e["created"],
        } for e in sorted(_running.values(), key=lambda x: x["created"], reverse=True)]


def _publish_event(run_id, kind, **data):
    try:
        from longrun.core.server import publish
        publish(kind, run_id=run_id, **data)
    except Exception:
        pass


def observation_formatter(result, max_chars=1200):
    """Format a subagent result as an agent observation string."""
    if result.get("ok"):
        return ("[subagent] status=%s summary=%s steps=%d trace_bytes=%d"
                % (result.get("status"), result.get("summary", "")[:160],
                   result.get("steps"), len(json.dumps(result.get("trace", [])))))
    return "[subagent] ERROR: %s" % result.get("error", "unknown")
