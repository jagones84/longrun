"""Decision queue — the one place a human drains what needs them.

Paperclip funnels everything that needs a human into ONE inbox. Longrun already
has the ranked feed (attention.py); this adds the *drain*: every item can be
resolved inline, and each resolution either delegates to a real app primitive
(``approvals.decide`` for a tool approval, ``jobs.dispatch`` to retry a failed run)
or is acknowledged (``dismiss``) so the queue stays clean.

No parallel state is invented: approvals and runs live in their own modules; the
only thing persisted here is the set of dismissed item ids.
"""
import json
import os
import threading
import time

from longrun.util.fswrite import write_json
from longrun.util.paths import REPO_ROOT as REPO

from .attention import AttentionFeed

_LOCK = threading.RLock()
FILE = os.environ.get("LONGRUN_DECISIONS_FILE") or os.path.join(
    REPO, "data", "orbit_decisions.json")

_DISMISSABLE = ("dismiss", "ack")


def _load():
    try:
        with open(FILE, encoding="utf-8") as f:
            d = json.load(f)
    except Exception:  # noqa: BLE001 - missing/corrupt file is just an empty set
        d = {}
    d.setdefault("dismissed", [])
    return d


def _save(d):
    write_json(FILE, d)


class DecisionQueue:
    """Ranked, drainable queue built on top of the attention feed."""

    def __init__(self, feed, retry=None):
        self.feed = feed
        self.retry = retry or (lambda jid: {"ok": False, "error": "retry unavailable"})

    # ---- read ---------------------------------------------------------------
    def _dismissed(self):
        with _LOCK:
            return set(_load()["dismissed"])

    def queue(self):
        sessions = self.feed.registry.list().get("sessions", [])
        snap = self.feed.snapshot(sessions)
        dismissed = self._dismissed()
        items = [i for i in snap.get("items", []) if i.get("id") not in dismissed]
        by = {}
        for it in items:
            by[it["severity"]] = by.get(it["severity"], 0) + 1
        return {
            "items": items,
            "count": len(items),
            "by_severity": by,
            "dismissed": len(dismissed),
            "board": AttentionFeed.board(sessions, items),
            "ts": round(time.time(), 3),
        }

    # ---- drain --------------------------------------------------------------
    def resolve(self, item_id, action, by="orbit"):
        item_id = str(item_id or "")
        action = str(action or "").lower()
        if not item_id:
            return {"ok": False, "error": "id required"}

        if action in _DISMISSABLE:
            return self._dismiss(item_id, "dismissed")

        kind, _, ref = item_id.partition(":")
        if action in ("approve", "deny"):
            if kind != "approval" or not ref:
                return {"ok": False, "error": "only approvals can be approved/denied"}
            from longrun.tools import approvals
            rec = approvals.decide(ref, "approve" if action == "approve" else "deny", by=by)
            if rec is None:
                return {"ok": False, "error": "approval not found"}
            self._dismiss(item_id, "dismissed")
            return {"ok": True, "id": item_id, "action": action,
                    "status": rec.get("status")}

        if action == "retry":
            if kind != "failed" or not ref:
                return {"ok": False, "error": "only failed runs can be retried"}
            res = self.retry(ref)
            if not res or not res.get("ok"):
                return {"ok": False, "error": (res or {}).get("error") or "retry failed"}
            self._dismiss(item_id, "dismissed")
            return {"ok": True, "id": item_id, "action": "retry", "job": ref}

        return {"ok": False, "error": "unknown action: " + action}

    def _dismiss(self, item_id, reason):
        with _LOCK:
            d = _load()
            if item_id not in d["dismissed"]:
                d["dismissed"].append(item_id)
                _save(d)
        return {"ok": True, "id": item_id, "action": "dismiss", "reason": reason}

