"""Session registry — the Orbit roster: list, inspect and PRE-CREATE sessions.

"Creating them beforehand would be cool" (user): a session can be provisioned with
a title, a model and a workspace without sending it any message, then dispatched to
later. Since sessions are already first-class in the app (`get_or_create_session`,
`list_sessions`), the registry only wraps them and adds a live `running` flag from
the app's `_ACTIVE_CHAT` registry.
"""
import time


def _server():
    from longrun.core import server
    return server


def _prompt_chars(sid):
    """Size of the session's ROLE.md; 0 means the PROMPT IS VOID (JAG-2.8).

    The Control ▸ AGENTS panel used to render every row identically whether the
    agent had a prompt or not, so an agent that ran on the bare system prompt was
    indistinguishable from a configured one. Exposing the size lets the deck mark
    the empty ones. None = could not be read (never claim "empty" on an error).
    """
    try:
        from longrun.orchestrate import roles
        return len(roles.read(sid))
    except Exception:  # noqa: BLE001 — a roster must never fail on one bad file
        return None


class SessionRegistry:
    """The roster of sessions, with live run status."""

    def list(self):
        srv = _server()
        active = self._active()
        rows = []
        for s in srv.list_sessions():
            sid = s.get("id")
            rows.append({
                "id": sid,
                "title": s.get("title") or ("session " + str(sid)[:6]),
                "model": s.get("model"),
                "workspace": s.get("workspace"),
                "job": s.get("job"),
                "messages": s.get("messages", 0),
                "updated": s.get("updated"),
                "running": sid in active,
                "prompt_chars": _prompt_chars(sid),
            })
        return {"sessions": rows, "count": len(rows), "active": len(active)}

    @staticmethod
    def _active():
        try:
            srv = _server()
            with srv._ACTIVE_CHAT_LOCK:
                return set(srv._ACTIVE_CHAT.keys())
        except Exception:  # noqa: BLE001
            return set()

    def create(self, title=None, model=None, workspace=None, sid=None):
        """Provision a session ahead of time (optionally bind a model)."""
        srv = _server()
        sess = srv.get_or_create_session(sid, title=title, workspace=workspace)
        if model:
            sess["model"] = model
            sess["updated"] = round(time.time(), 3)
            srv.save_session(sess)
        return {
            "ok": True,
            "session": sess.get("id"),
            "title": sess.get("title"),
            "model": sess.get("model"),
            "workspace": sess.get("workspace"),
        }

