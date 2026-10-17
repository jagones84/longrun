#!/usr/bin/env python3
"""Longrun Swarm / Blackboard — Sperimentale

Multiple agents cooperating on shared state via a blackboard architecture.

Architecture:
  - **Blackboard**: shared, versioned data structure that agents read/write.
    Each write is an append-only event. Agents can subscribe to changes.
  - **Coordinator agent**: orchestrates worker agents. It decomposes a goal,
    posts sub-goals to the blackboard, spawns workers, and synthesises results.
  - **Worker agents**: spawned by the coordinator or directly by the harness.
    Each has an isolated subagent context but shared access to the blackboard.
  - **Observers**: agents (or humans) that monitor the blackboard and may
    jump in to refine a partial result.

Blackboard API:
  blackboard/post   - post a new entry (append-only, versioned)
  blackboard/get    - read entries by id or topic
  blackboard/watch  - SSE stream of new entries
  blackboard/search - search entries by content or tags

Concepts (inspired by blackboard systems + multi-agent coordination):
  - Topic: a namespace for related entries ("goal", "plan", "result", "question")
  - Tags: freeform labels for filtering
  - Parent: reference to a prior entry (for threading)
"""

import json
import os
import queue
import threading
import time
import uuid

from longrun.core.sse import sse_tail
from longrun.tools import registry
from longrun.util.fswrite import write_json

REPO = registry.REPO
DATA_DIR = os.path.join(REPO, "data", "blackboard")

_lock = threading.RLock()
_entries = []           # ordered list of entries (memory cache + on-demand)
_watchers = set()       # set of queue.Queue for SSE watchers
_max_entries = 2000

# --------------------------------------------------------------- blackboard ---


def _ensure_file():
    os.makedirs(DATA_DIR, exist_ok=True)
    path = os.path.join(DATA_DIR, "blackboard.json")
    return path


def _load():
    """Load all entries from disk."""
    global _entries
    if _entries:
        return _entries
    path = _ensure_file()
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, list):
            _entries = data
        elif isinstance(data, dict) and "entries" in data:
            _entries = data["entries"]
    except (FileNotFoundError, json.JSONDecodeError):
        _entries = []
    return _entries


def _save():
    path = _ensure_file()
    write_json(path, {"entries": _entries[-_max_entries:]})


def post(topic, content, tags=None, parent=None, author=None, run_id=None):
    """Post a new entry to the blackboard.

    Args:
        topic: namespace (e.g. "goal", "partial_result", "question", "synthesis")
        content: the actual payload (string, or JSON dict/list)
        tags: optional list of label strings
        parent: optional id of the parent entry (for threading)
        author: who wrote this (agent id, "human", "coordinator")
        run_id: optional associated run

    Returns the entry dict (with id and version).
    """
    with _lock:
        entries = _load()
        entry = {
            "id": uuid.uuid4().hex[:10],
            "ts": round(time.time(), 3),
            "version": len(entries) + 1,
            "topic": topic,
            "content": content if isinstance(content, str) else json.dumps(content, indent=2),
            "tags": tags or [],
            "parent": parent,
            "author": author or "agent",
            "run_id": run_id,
            "children": [],
        }
        entries.append(entry)
        if len(entries) > _max_entries:
            _entries = entries[-_max_entries:]
        _save()

        # Update parent's children list
        if parent:
            for e in _entries:
                if e["id"] == parent:
                    e.setdefault("children", []).append(entry["id"])
                    break

        # Notify watchers
        _notify(entry)

        return entry


def get(entry_id=None, topic=None, tags=None, limit=50):
    """Read entries, filtered by id, topic, and/or tags.

    Args:
        entry_id: return exactly one entry
        topic: filter by topic
        tags: filter by tags (any match)
        limit: max entries (default 50)

    Returns a list of entries (newest first when no specific id).
    """
    with _lock:
        entries = _load()

    if entry_id:
        for e in entries:
            if e["id"] == entry_id:
                return [e]
        return []

    result = list(entries)
    if topic:
        result = [e for e in result if e.get("topic") == topic]
    if tags:
        tag_set = set(tags)
        result = [e for e in result if tag_set & set(e.get("tags", []))]
    result.reverse()
    return result[:limit]


def search(query, topic=None, limit=20):
    """Search blackboard entries by content substring."""
    with _lock:
        entries = _load()
    result = []
    for e in reversed(entries):
        if topic and e.get("topic") != topic:
            continue
        content = e.get("content", "")
        if isinstance(content, str) and query.lower() in content.lower():
            result.append(e)
        elif isinstance(content, (dict, list)):
            if query.lower() in json.dumps(content).lower():
                result.append(e)
        if len(result) >= limit:
            break
    return result


def thread(entry_id):
    """Get a conversation thread: the entry + all ancestors + all descendants."""
    with _lock:
        entries = _load()
    index = {e["id"]: e for e in entries}
    result = {}

    # Collect ancestors
    current = index.get(entry_id)
    while current:
        result[current["id"]] = current
        current = index.get(current.get("parent"))

    # Collect descendants (via children list; also scan for any parent ref)
    stack = [entry_id]
    while stack:
        cid = stack.pop()
        entry = index.get(cid)
        if not entry:
            continue
        for child_id in entry.get("children", []):
            if child_id not in result:
                child = index.get(child_id)
                if child:
                    result[child_id] = child
                    stack.append(child_id)
    # Also scan any entry not yet covered
    for e in entries:
        if e.get("parent") in result or e["id"] in result:
            result[e["id"]] = e
    return sorted(result.values(), key=lambda x: x.get("ts", 0))


def stats():
    """Blackboard statistics."""
    with _lock:
        entries = _load()
    topics = {}
    for e in entries:
        t = e.get("topic", "unknown")
        topics[t] = topics.get(t, 0) + 1
    return {
        "total_entries": len(entries),
        "topics": topics,
        "watchers": len(_watchers),
    }


# ----------------------------------------------------------------- watchers ---

def _notify(entry):
    payload = "event: blackboard.post\ndata: %s\n\n" % json.dumps(entry, ensure_ascii=False)
    with _lock:
        for q in list(_watchers):
            try:
                q.put_nowait(payload)
            except Exception:
                _watchers.discard(q)


def watch_gen(since_version=0):
    """SSE generator for blackboard watchers.

    Yields backlog from version N, then live updates (shared tail skeleton: see
    ``core.sse.sse_tail``).
    """
    q = queue.Queue()
    with _lock:
        _watchers.add(q)
    try:
        with _lock:
            backlog = [e for e in _entries if e.get("version", 0) > since_version]
        yield from sse_tail(q, backlog, ": blackboard watch open\n\n")
    finally:
        with _lock:
            _watchers.discard(q)


# ------------------------------------------------------------ coordinator ---

class Coordinator:
    """High-level coordinator agent that orchestrates swarm workers.

    Pattern:
      1. Decompose the main goal into sub-goals.
      2. Post each sub-goal to the blackboard as a topic="subgoal" entry.
      3. Spawn a subagent (or call an external ACP agent) for each.
      4. Collect results (posted as topic="partial_result" with parent ref).
      5. Synthesise the final answer.
    """

    def __init__(self, name="coordinator"):
        self.name = name
        self._lock = threading.Lock()

    def decompose_goal(self, goal, n_workers=3):
        """Post a decomposed goal to the blackboard with subgoals."""
        # In a production system, this would call the LLM
        # For now, we just post the goal and let humans/external agents handle it
        entry = post("goal", goal, tags=[self.name, "goal"],
                     author=self.name)
        subgoals = [
            post("subgoal", "Sub-task %d of: %s" % (i + 1, goal),
                 tags=[self.name, "subgoal"], parent=entry["id"],
                 author=self.name)
            for i in range(n_workers)
        ]
        return {"goal_entry": entry, "subgoal_entries": subgoals}

    def run_swarm(self, goal, n_workers=3, max_steps_per_worker=4, model=None):
        """Decompose, spawn workers via subagent, collect results, synthesise.

        Returns a report with all entries.
        """
        # 1. Decompose
        decomposition = self.decompose_goal(goal, n_workers)
        goal_entry = decomposition["goal_entry"]
        subgoal_entries = decomposition["subgoal_entries"]

        # 2. Spawn workers (each as a subagent)
        from longrun.agent import subagent
        worker_results = []
        for sg in subgoal_entries:
            worker_goal = "Blackboard worker: %s\n\nBlackboard goal id: %s\nSub-goal id: %s" % (
                sg["content"][:200], goal_entry["id"], sg["id"])
            spawned = subagent.spawn(worker_goal, max_steps=max_steps_per_worker,
                                     model=model)
            worker_results.append(spawned)

        # 3. Collect results
        summaries = []
        for spawned in worker_results:
            result = subagent.collect(spawned["subagent_id"], timeout=300)
            summary = result.get("summary", "no summary")
            # Post result to blackboard
            post("partial_result", summary,
                 tags=[self.name, "worker"],
                 parent=goal_entry["id"],
                 run_id=spawned.get("run_id"),
                 author="worker/%s" % spawned["subagent_id"])
            summaries.append(summary)

        # 4. Synthesise
        synthesis = "Swarm synthesis for goal: %s\n\nWorkers: %d\nSummaries:\n%s" % (
            goal, len(summaries), "\n".join("- %s" % s[:200] for s in summaries))
        final = post("synthesis", synthesis, tags=[self.name, "synthesis"],
                     parent=goal_entry["id"], author=self.name)

        return {
            "goal_id": goal_entry["id"],
            "subgoal_ids": [sg["id"] for sg in subgoal_entries],
            "worker_count": n_workers,
            "synthesis_id": final["id"],
            "summaries": summaries,
        }


# ---------------------------------------------------------------- API ----

def init():
    _load()
