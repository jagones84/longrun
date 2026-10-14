#!/usr/bin/env python3
"""Completion loop (JAG-129A): the logic that decides whether the harness must
CONTINUE working on a TASK LIST with open steps or stop.

Pattern: Ralph/Stop-hook + Claude `/goal`. The agent does not decide when to
stop: the list decides it, with typed stop conditions
(goal_reached | no_progress | budget | blocked | user_stop).

PURE module: no dependency on server/taskgraph -> testable in isolation.
"""
import hashlib
import json
import time

DEFAULTS = {
    "keepgoing_max": 8,       # continuation rounds before the 'budget' stop
    "no_progress_rounds": 2,  # rounds without progress before the 'no_progress' stop
    "max_wall_secs": 3600,    # time cap per run
    "subagent_max_depth": 2,  # maximum depth of the nesting
    # JAG-171: when True the harness insists on its own (up to keepgoing_max) before
    # stopping; when False, at the first stop attempt with open steps it hands
    # control to the human right away (HUMAN IN THE LOOP).
    "autocontinue": True,
}


def cfg(override=None):
    """Runtime config: DEFAULTS <- config/tools.yaml -> explicit override."""
    out = dict(DEFAULTS)
    try:
        from longrun.tools import registry
        got = (registry.load_config().get("runtime") or {})
        if isinstance(got, dict):
            out.update({k: v for k, v in got.items() if v is not None})
    except Exception:  # noqa: BLE001
        pass
    if isinstance(override, dict):
        out.update(override)
    return out


def hitl_gate(reason, open_nodes, autonomous=False):
    """Whether the HUMAN IN THE LOOP gate must fire (JAG-295).

    It fires only when there ARE open steps, the stop is a real one (not a user
    pivot) AND a human is present. A headless turn — a JOB or a routine runs with
    `autonomous=True`, no browser attached — has NOBODY to answer, so it must
    never gate: the turn just stops and the open steps stay in the graph.
    """
    # JAG-462: an ABORTED turn (`reason == "user_stop"`) must NEVER gate. The whole
    # keepgoing decision already returns `user_stop` when the operator pressed Stop,
    # and the tail gate in the chat loop excludes aborted turns — but this gate did
    # not, so pressing Stop immediately popped a "⏸ Paused — N open step(s)" card.
    return (bool(open_nodes) and reason not in ("user_pivot", "user_stop")
            and not autonomous)


def state_hash(nodes):
    """Stable hash of the nodes' state (id,status): detects 'no progress'."""
    items = sorted("%s:%s" % (n.get("id"), n.get("status")) for n in (nodes or []))
    return hashlib.sha256(("|".join(items)).encode("utf-8")).hexdigest()


def tool_hash(tool, args):
    """Hash of a tool+args call: detects identical repetition."""
    try:
        blob = json.dumps({"t": tool, "a": args}, sort_keys=True, default=str)
    except Exception:  # noqa: BLE001
        blob = "%s:%s" % (tool, args)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def decide(open_nodes, rounds, stale, started, now=None, aborted=False, blocked=False,
           steer=False, override=None):
    """Decide whether to continue. Returns {"continue": bool, "reason": str|None}.

    Priority order (the first one that triggers wins): user_stop, goal_reached,
    blocked, budget (time), budget (rounds), no_progress. `steer` forces
    continuation (user redirection) even with an empty list.
    """
    c = cfg(override)
    now = time.time() if now is None else float(now)
    if aborted:
        return {"continue": False, "reason": "user_stop"}
    if open_nodes <= 0:
        if steer:
            return {"continue": True, "reason": None}
        return {"continue": False, "reason": "goal_reached"}
    if blocked:
        return {"continue": False, "reason": "blocked"}
    # JAG-463: a HUMAN STEER must never be dropped by a budget / no-progress stop.
    # The operator typed a directive while the turn was running; the round/time cap
    # used to win, the loop stopped, and the steer was never drained — the live
    # "forced steer doesn't cause the LLM to proceed".
    if steer:
        return {"continue": True, "reason": None}
    if now - float(started) >= float(c["max_wall_secs"]):
        return {"continue": False, "reason": "budget"}
    if int(rounds) >= int(c["keepgoing_max"]):
        return {"continue": False, "reason": "budget"}
    if int(stale) >= int(c["no_progress_rounds"]):
        return {"continue": False, "reason": "no_progress"}
    return {"continue": True, "reason": None}
