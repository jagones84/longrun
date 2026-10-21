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


def _improvement_view(proposal):
    """Shape one improvement proposal as an approval-queue entry."""
    pid = str((proposal or {}).get("id") or "")
    scope = str((proposal or {}).get("scope") or "")
    status = str((proposal or {}).get("status") or "pending")
    blocked = ("skill apply is not implemented (JAG-128B deferred)"
               if scope == "skill" else "")
    return {
        "id": "imp:" + pid,
        "ts": proposal.get("ts"),
        "run_id": None,
        "tool": "improve.%s" % scope,
        "args": {"proposal": pid, "scope": scope},
        "summary": str(proposal.get("content") or "")[:200],
        "status": status,
        "reason": proposal.get("reason") or "",
        "decided_by": None if status == "pending" else "operator",
        "decided_ts": None,
        "kind": "improvement",
        "source": "improvement",
        "scope": scope,
        "origin": proposal.get("origin"),
        "can_approve": bool(scope and scope != "skill" and status == "pending"),
        "blocked_reason": blocked,
    }


def _improvement_records(status=None):
    """Pending (or decided) improvement proposals, newest first. Never raises."""
    try:
        from longrun.util import improve
        proposals = improve.list_proposals(status=status)
    except Exception:  # noqa: BLE001 — a missing proposal store is simply empty
        return []
    return [_improvement_view(p) for p in proposals if p.get("id")]


def list_unified(status=None, limit=100):
    """The operator's single approval inbox: tool gates + improvement proposals."""
    rows = list_all(None, 100000)
    for rec in rows:
        rec.setdefault("kind", "tool")
        rec.setdefault("source", "tool")
        rec.setdefault("can_approve", rec.get("status") == "pending")
        rec.setdefault("blocked_reason", "")
    rows.extend(_improvement_records(status))
    if status:
        rows = [r for r in rows if r.get("status") == status]
    rows.sort(key=lambda r: r.get("ts") or 0, reverse=True)
    return rows[:limit]


def stats_unified():
    """Tool-gate stats plus the improvement backlog, without changing old keys."""
    out = stats()
    impro = _improvement_records("pending")
    out["improvement_pending"] = len(impro)
    out["pending_total"] = out.get("pending", 0) + len(impro)
    return out


def get_any(aid):
    """Look up a tool approval or an `imp:<proposal-id>` improvement request."""
    key = str(aid or "")
    if key.startswith("imp:"):
        try:
            from longrun.util import improve
            proposal = improve.get_proposal(key[4:])
            return _improvement_view(proposal) if proposal else None
        except Exception:  # noqa: BLE001
            return None
    return get(key)


def decide_any(aid, decision, by="human"):
    """Decide either queue from one entry point. Returns {ok, approval|error}."""
    key = str(aid or "")
    if key.startswith("imp:"):
        try:
            from longrun.util import improve
            res = improve.decide(key[4:], "approve" if decision in ("approve", "accept") else decision)
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "error": "proposal decision failed: %s" % e}
        if not res.get("ok"):
            return {"ok": False, "error": res.get("error") or "proposal decision failed"}
        return {"ok": True, "approval": _improvement_view(res)}
    rec = decide(key, decision, by)
    if not rec:
        return {"ok": False, "error": "approval not found"}
    rec.setdefault("kind", "tool")
    rec.setdefault("source", "tool")
    return {"ok": True, "approval": rec}


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

