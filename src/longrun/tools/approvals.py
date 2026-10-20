#!/usr/bin/env python3
"""Longrun approval gates — per-action approval queue with HITL wait.

Every sensitive tool action creates a record here. Outcomes:
  * auto_approved — matched a read-only auto-approve pattern (still recorded)
  * pending       — waiting for a human decision (WebUI / phone / MCP)
  * approved      — a human approved it
  * denied        — a human denied it, or hard-deny policy
  * expired       — nobody decided within approvals.timeout_secs

The queue is durable (data/approvals.json) so decisions survive a restart.
"""

import json
import os
import threading
import time
import uuid

from longrun.tools import registry
from longrun.util.fswrite import write_json

DATA_DIR = os.path.join(registry.REPO, "data")
# Distinct file name: another harness build may own data/approvals.json.
PATH = os.environ.get("LONGRUN_APPROVALS",
                      os.path.join(DATA_DIR, "approvals-v02.json"))

_lock = threading.RLock()
_events = {}      # id -> threading.Event (wake a waiting run on decision)
_store = None     # {"approvals": [...]}


def _load():
    global _store
    if _store is None:
        _store = {"approvals": []}
        try:
            with open(PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict) and isinstance(data.get("approvals"), list):
                _store = data
            else:  # foreign / legacy format — archive it, never crash
                os.replace(PATH, PATH + ".legacy-%d" % int(time.time()))
        except (FileNotFoundError, json.JSONDecodeError, ValueError):
            pass
        _store.setdefault("approvals", [])
    return _store


def _persist():
    write_json(PATH, _load())


def _summarize(tool, args):
    if tool in ("shell", "shell.exec"):
        return str(args.get("command", ""))[:200]
    if tool in ("fs.read", "fs.write", "fs.edit"):
        return str(args.get("path", ""))[:200]
    if tool in ("git", "git.run"):
        return "git " + str(args.get("args", ""))[:180]
    if tool in ("http", "http.fetch", "browser", "browser.fetch"):
        return str(args.get("url", ""))[:200]
    return json.dumps(args, ensure_ascii=False)[:200]


def create(tool, args, run_id=None, decision="pending", reason=""):
    """Record an approval request. decision: pending | auto_approved | denied."""
    with _lock:
        store = _load()
        rec = {
            "id": uuid.uuid4().hex[:10],
            "ts": round(time.time(), 3),
            "run_id": run_id,
            "tool": tool,
            "args": args,
            "summary": _summarize(tool, args),
            "status": decision,
            "reason": reason,
            "decided_by": "policy" if decision != "pending" else None,
            "decided_ts": round(time.time(), 3) if decision != "pending" else None,
        }
        store["approvals"].append(rec)
        store["approvals"] = store["approvals"][-500:]
        _persist()
        _events.setdefault(rec["id"], threading.Event())
        return rec


def get(aid):
    with _lock:
        for r in _load()["approvals"]:
            if r["id"] == aid:
                return r
    return None


def list_all(status=None, limit=100):
    with _lock:
        items = list(_load()["approvals"])
    if status:
        items = [r for r in items if r["status"] == status]
    return items[-limit:][::-1]


def stats():
    with _lock:
        items = _load()["approvals"]
    out = {"total": len(items), "pending": 0, "approved": 0, "denied": 0,
           "auto_approved": 0, "expired": 0}
    for r in items:
        if r["status"] in out:
            out[r["status"]] += 1
    return out


def decide(aid, decision, by="human"):
    """decision: approve | deny | expire. Returns the updated record or None."""
    status = {"approve": "approved", "deny": "denied", "expire": "expired"}.get(decision)
    if status is None:
        return None
    with _lock:
        rec = get(aid)
        if not rec:
            return None
        if rec["status"] != "pending":
            return rec
        rec["status"] = status
        rec["decided_by"] = by
        rec["decided_ts"] = round(time.time(), 3)
        _persist()
    _events.setdefault(aid, threading.Event()).set()
    return rec


def delete(aid):
    """Remove one approval record and its wait event (JAG-318).

    Returns ``{ok, deleted, removed}``.
    """
    aid = str(aid or "").strip()
    if not aid:
        return {"ok": False, "error": "id required"}
    with _lock:
        store = _load()
        before = len(store["approvals"])
        store["approvals"] = [r for r in store["approvals"] if r.get("id") != aid]
        removed = before - len(store["approvals"])
        if removed:
            _persist()
        _events.pop(aid, None)   # JAG-318: do not leak a threading.Event per id
    return {"ok": True, "deleted": aid, "removed": removed}


def clear(status=None, keep_pending=True):
    """Delete decided approvals — every record, or only `status` (JAG-318).

    Pending approvals are KEPT by default: an unanswered human request must never
    be dropped silently. Returns ``{ok, removed}``.
    """
    with _lock:
        store = _load()

        def victim(r):
            if status:
                return r.get("status") == status
            return (r.get("status") != "pending") if keep_pending else True

        victims = [r for r in store["approvals"] if victim(r)]
        if victims:
            store["approvals"] = [r for r in store["approvals"] if not victim(r)]
            _persist()
        for r in victims:
            _events.pop(r.get("id"), None)
    return {"ok": True, "removed": len(victims)}


def wait(aid, timeout=None, checkpoint=None, poll=0.5):
    """Block until the approval is decided. `checkpoint()` is called every `poll`
    seconds so a run can still be paused/aborted while it waits."""
    timeout = float(timeout if timeout is not None else registry.load_config()["approvals"]["timeout_secs"])
    ev = _events.setdefault(aid, threading.Event())
    deadline = time.time() + timeout
    while True:
        if checkpoint:
            checkpoint()
        rec = get(aid)
        if rec and rec["status"] != "pending":
            return rec
        remaining = deadline - time.time()
        if remaining <= 0:
            return decide(aid, "expire", by="timeout") or get(aid)
        if ev.wait(min(poll, remaining)):
            ev.clear()

