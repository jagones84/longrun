"""One delivery rule for a message that must reach a session (2026-11-08).

Three callers need the same answer to "how do I hand this text to a session that
may be busy": ``sessions.send`` (an agent messaging a peer), the job runner (a
finished job telling the agent that assigned it) and the dispatch path (a
teammate's completion notice). Keeping a copy of that branch in each of them is
two truths waiting to drift, so the rule lives here and they all call it:

  * BUSY (a turn is in flight) -> queue it with ``steering.push_steer``; the loop
    injects it as a user message at its next boundary, and the durable steer log
    keeps it visible in the transcript meanwhile.
  * IDLE -> start a real server-side turn (``orbit.dispatch_message``).

The race between the busy probe and the dispatch is closed by queueing when the
dispatch answers "busy": a lost wake-up is the defect this module exists to
prevent. Nothing here raises, and the result says which branch ran so the caller
can report it instead of guessing.
"""


def deliver(sess_id, text, from_session=None):
    """Hand ``text`` to ``sess_id``: queue it if the session is busy, else start a turn.

    Returns ``{"ok", "mode": "steer"|"turn"|"", "session", "messages",
    "queue_depth"|"job", "error"}``. ``messages`` is the session's message count
    BEFORE the delivery, so a caller can read back exactly this reply.
    """
    sid = str(sess_id or "").strip()
    body = str(text or "").strip()
    if not sid or not body:
        return {"ok": False, "mode": "", "session": sid, "messages": 0,
                "error": "session and message required"}
    if str(from_session or "").strip() == sid:
        return {"ok": False, "mode": "", "session": sid, "messages": 0,
                "error": "refusing to send a message to the calling session"}
    try:
        from longrun.core import server as srv
        sess = srv.load_session(sid)
    except Exception as e:  # noqa: BLE001 — a lookup failure must not crash a job
        return {"ok": False, "mode": "", "session": sid, "messages": 0,
                "error": "session lookup failed: %s" % e}
    if not sess:
        return {"ok": False, "mode": "", "session": sid, "messages": 0,
                "error": "no such session: %s" % sid}
    before = len(sess.get("messages") or [])
    if _busy(sid):
        return _queue(sid, body, before)
    res = _turn(sid, body, before)
    if res.get("mode") == "busy":
        # Lost the race between the probe and the dispatch: queue instead of
        # dropping the message.
        return _queue(sid, body, before)
    return res


def _busy(sid):
    """True when a turn is running on `sid` — the owner is `core.events`."""
    try:
        from longrun.core import events
        return bool(events.turn_active(sid))
    except Exception:  # noqa: BLE001 — an unknown session is idle
        return False


def _queue(sid, body, before):
    from longrun.util import steering
    depth = steering.push_steer(sid, body)
    return {"ok": True, "mode": "steer", "session": sid, "messages": before,
            "queue_depth": depth}


def _turn(sid, body, before):
    try:
        from longrun.orbit import api as orbit_api
        res = orbit_api.dispatch_message(sid, body) or {}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "mode": "", "session": sid, "messages": before,
                "error": "turn could not start: %s" % e}
    job = (res.get("jobs") or [{}])[0]
    if str(job.get("state") or "") == "busy":
        return {"ok": False, "mode": "busy", "session": sid, "messages": before,
                "error": str(job.get("error") or "session %s is busy" % sid)}
    if not res.get("ok"):
        return {"ok": False, "mode": "", "session": sid, "messages": before,
                "error": str(res.get("error") or "turn could not start")}
    return {"ok": True, "mode": "turn", "session": sid, "messages": before,
            "job": str(job.get("job") or "")}
