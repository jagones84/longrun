"""Orchestrator — dispatch a goal to one or many sessions, in the background.

This is the "run a team of agents" core that the stock deck never had: a session
can be sent a goal with no browser attached. The turn runs server-side by draining
the SAME generator the SSE chat route uses (`server.chat_stream_gen`), so every
guarantee of a normal turn still holds — per-session turn lock, transcript
persistence, task-graph events and feed publishes.
"""
import threading
import time


def _server():
    from longrun.core import server
    return server


class Orchestrator:
    """Starts background turns on sessions and tracks their jobs."""

    def __init__(self, keep=200):
        self.keep = keep
        self._lock = threading.Lock()
        self._jobs = {}

    def dispatch(self, targets, goal, model=None, mode="goal"):
        goal = (goal or "").strip()
        if not goal:
            return {"ok": False, "error": "goal required", "jobs": []}
        targets = [t for t in (targets or []) if t]
        if not targets:
            return {"ok": False, "error": "no target session", "jobs": []}
        jobs = [self._start(sid, goal, model, mode) for sid in targets]
        return {"ok": True, "jobs": jobs, "count": len(jobs)}

    def _start(self, sid, goal, model, mode):
        srv = _server()
        # Fix2: never silently queue behind (or pile threads onto) a running
        # turn. The old code blocked on the session turn lock with no signal —
        # a dispatch to a busy teammate either hung the caller or lost the
        # work. Fail fast with a named state the caller can retry on.
        try:
            from longrun.core import events as _events
            _busy = _events.turn_active(sid)
        except Exception:  # noqa: BLE001 — probe failure means "not busy"
            _busy = False
        if _busy:
            rec = {
                "job": "%s:%d" % (sid, int(time.time() * 1000)),
                "session": sid,
                "started": round(time.time(), 3),
                "ended": round(time.time(), 3),
                "state": "busy",
                "error": ("session %s is busy (a turn is running) — retry later "
                          "or steer the running turn via sessions.send" % sid),
            }
            with self._lock:
                self._jobs[rec["job"]] = rec
                self._trim()
            return {"job": rec["job"], "session": sid, "state": "busy",
                    "error": rec["error"]}
        sess = srv.get_or_create_session(sid)
        rec = {
            "job": "%s:%d" % (sid, int(time.time() * 1000)),
            "session": sid,
            "title": sess.get("title"),
            "goal": goal[:160],
            "model": model or sess.get("model"),
            "mode": mode,
            "started": round(time.time(), 3),
            "state": "running",
        }
        with self._lock:
            self._jobs[rec["job"]] = rec
            self._trim()

        def _run():
            try:
                gen = srv.chat_stream_gen(sess, goal, model, None,
                                          autonomous=(mode == "goal"))
                for _ in gen:      # drain the SSE generator: runs the whole turn
                    pass
            except Exception as exc:  # noqa: BLE001
                with self._lock:
                    rec["state"] = "error"
                    rec["error"] = str(exc)
            finally:
                with self._lock:
                    if rec["state"] == "running":
                        rec["state"] = "done"
                    rec["ended"] = round(time.time(), 3)

        threading.Thread(target=_run, name="orbit-job-" + sid, daemon=True).start()
        return {"job": rec["job"], "session": sid, "state": "running"}

    def _trim(self):
        if len(self._jobs) <= self.keep:
            return
        for jid in sorted(self._jobs, key=lambda k: self._jobs[k].get("started", 0))[:-self.keep]:
            self._jobs.pop(jid, None)

    def jobs(self, limit=60):
        with self._lock:
            rows = sorted(self._jobs.values(), key=lambda r: r.get("started", 0),
                          reverse=True)[:limit]
        return {"jobs": rows}

    def job(self, job_id: str) -> dict | None:
        """Return one job by its exact id, including terminal state."""
        with self._lock:
            rec = self._jobs.get(str(job_id or ""))
            return dict(rec) if rec else None
