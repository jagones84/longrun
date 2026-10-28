#!/usr/bin/env python3
"""Durable goal object (G-1): a `/goal` that outlives the turn that started it.

Longrun's `/goal` used to be a PER-REQUEST flag: the chat handler read
`mode=goal` and passed `goal_started=time.time()` into the loop, so the goal
existed only while that HTTP request was streaming (`core/httpapi.py:2074`,
`:2230`, `:2380`). Closing the tab, restarting the service, or wanting to pause
and come back later had no object to act on: there was nothing to pause, resume,
edit or delete. This module is that object.

One owner per fact:

* the OBJECTIVE (what to achieve, and whether it is active) lives here;
* the PLAN (steps and their evidence) stays in `plan.taskgraph`;
* completion is NOT a stored opinion — `progress()` reads the graph, so the bar
  can never say "done" while steps are still open, and a restart cannot
  resurrect a finished goal as active.

The record is small and human-readable, stored beside the other user state:

    {"session", "objective", "status", "created", "updated", "turns",
     "stopped"?, "note"?}

`status` is one of `active`, `paused`, `completed`. There is no `deleted`
status: deleting removes the record, so a deleted goal cannot be resumed by a
stale client.
"""
import os
import time

from longrun.util import paths
from longrun.util.fswrite import write_json

STATUSES = ("active", "paused", "completed")
MAX_OBJECTIVE = 8000


def _dir():
    """`<data>/goals` — one JSON file per session."""
    return os.path.join(paths.DATA_DIR, "goals")


def _safe(session_id):
    """A filesystem-safe session token (never a path escape)."""
    out = "".join(c for c in str(session_id or "") if c.isalnum() or c in "-_").strip("-.")
    return out[:96]


def path(session_id):
    """Absolute path of one session's goal record."""
    return os.path.join(_dir(), _safe(session_id) + ".json")


def load(session_id):
    """The goal record for `session_id`, or None (missing/corrupt = no goal)."""
    if not _safe(session_id):
        return None
    try:
        import json
        with open(path(session_id), "r", encoding="utf-8") as f:
            got = json.load(f)
    except (OSError, ValueError):
        return None
    return got if isinstance(got, dict) and got.get("session") else None


def save(rec):
    """Persist one record (stamping `updated`) and return it."""
    rec["updated"] = round(time.time(), 3)
    os.makedirs(_dir(), exist_ok=True)
    write_json(path(rec.get("session")), rec)
    return rec


def _sync_graph(session_id, objective):
    """Mirror an EDITED/RESUMED objective onto the existing plan goal.

    The plan panel renders the graph's own `goal`, so letting the two disagree
    would show two different objectives for one task. Only an existing graph is
    touched: an empty plan is not a goal, and this module never authors steps.
    """
    if not objective:
        return
    try:
        from longrun.plan import taskgraph
        graph = taskgraph.load(session_id)
        if isinstance(graph, dict) and graph.get("goal") != objective:
            graph["goal"] = objective
            taskgraph.save(graph)
    except Exception:  # noqa: BLE001 — a goal edit must never fail on the graph
        pass


def can_start(session_id):
    """(ok, reason) — may a goal turn start for this session right now?"""
    rec = load(session_id)
    if not rec:
        return True, ""
    if rec.get("status") == "paused":
        return False, "the goal is paused: resume it before continuing"
    return True, ""


def start(session_id, objective=""):
    """Begin (or continue) the goal for this session and count the turn.

    A paused goal is NOT silently reactivated here — `can_start` refuses first,
    and a resume is an explicit operator action. Starting over a COMPLETED goal
    is a new goal: the objective is replaced and the counters restart.
    """
    objective = str(objective or "").strip()[:MAX_OBJECTIVE]
    rec = load(session_id) or {}
    if rec.get("status") not in ("active", "paused"):
        rec = {"session": session_id, "created": round(time.time(), 3), "turns": 0,
               "objective": objective, "status": "active"}
    else:
        if objective:
            rec["objective"] = objective
        rec["status"] = "active"
    rec["turns"] = int(rec.get("turns") or 0) + 1
    rec.pop("stopped", None)
    rec.pop("note", None)
    return save(rec)


def pause(session_id, note=""):
    """Pause an ACTIVE goal (None when there is nothing active to pause)."""
    rec = load(session_id)
    if not rec or rec.get("status") != "active":
        return None
    rec["status"] = "paused"
    if note:
        rec["note"] = str(note)[:400]
    return save(rec)


def resume(session_id):
    """Reactivate a PAUSED goal (None when it is not paused)."""
    rec = load(session_id)
    if not rec or rec.get("status") != "paused":
        return None
    rec["status"] = "active"
    rec.pop("note", None)
    rec.pop("stopped", None)
    rec = save(rec)
    _sync_graph(session_id, rec.get("objective"))
    return rec


def edit(session_id, objective):
    """Replace the objective of an existing goal (None when it does not exist)."""
    text = str(objective or "").strip()[:MAX_OBJECTIVE]
    rec = load(session_id)
    if not rec or not text:
        return None
    rec["objective"] = text
    rec = save(rec)
    _sync_graph(session_id, text)
    return rec


def complete(session_id, reason=""):
    """Mark an existing goal as completed (None when there is no goal)."""
    rec = load(session_id)
    if not rec:
        return None
    rec["status"] = "completed"
    rec["stopped"] = str(reason or "goal complete")[:400]
    return save(rec)


def delete(session_id):
    """Remove the record entirely (True when a record existed)."""
    existed = os.path.isfile(path(session_id))
    try:
        os.remove(path(session_id))
    except OSError:
        return False
    return existed


def progress(session_id):
    """Steps done/open from the PLAN — computed, never copied into the record."""
    out = {"steps": 0, "open": 0, "done": 0, "complete": False}
    try:
        from longrun.plan import taskgraph
        graph = taskgraph.load(session_id)
        if isinstance(graph, dict):
            nodes = taskgraph.plan_nodes(graph)
            out["steps"] = len(nodes)
            out["done"] = sum(1 for n in nodes if n.get("status") == "done")
            out["open"] = out["steps"] - out["done"]
            out["complete"] = bool(taskgraph.goal_complete(graph))
    except Exception:  # noqa: BLE001 — progress is a read-out, never a blocker
        pass
    return out


def status(session_id):
    """What the Active-goal bar renders: the record plus live plan progress."""
    rec = load(session_id)
    return {"session": session_id, "goal": rec, "progress": progress(session_id)}
