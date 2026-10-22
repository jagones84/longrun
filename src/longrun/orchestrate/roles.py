"""Per-session ROLE.md — a small role + behaviour patch merged into the prompt.

A session (agent or plain) may carry a ROLE: ONLY the role and a few behaviour
notes, never the whole system prompt. It is merged by the prompt section registry
as the ``agent-role`` section, so it applies to chat, jobs and routines alike.

Because the key is the SESSION id (unique), two agents sharing the same workspace
folder never collide, and the file lives OUTSIDE any workspace:

    <LONGRUN_ROLES_DIR or <repo>/data/roles>/<session_id>.md

Reset = write an empty role (the file is removed) or DELETE the session's role.
"""
import os
import re
import threading

from longrun.util import paths
from longrun.util.paths import REPO_ROOT as REPO

_LOCK = threading.RLock()
_MAX = 20000


def roles_dir():
    """The directory holding the per-session ROLE.md files."""
    return os.environ.get("LONGRUN_ROLES_DIR") or os.path.join(paths.DATA_DIR, "roles")


def key(session_id):
    """A filesystem-safe key for a session id (a session id is not a path)."""
    k = re.sub(r"[^A-Za-z0-9._-]", "_", str(session_id or "").strip())[:80]
    return k or "default"


def path_for(session_id):
    """Absolute path of a session's ROLE.md."""
    return os.path.join(roles_dir(), key(session_id) + ".md")


def read(session_id):
    """The session's role text, or "" when it has none."""
    if not session_id:
        return ""
    with _LOCK:
        try:
            with open(path_for(session_id), encoding="utf-8", errors="replace") as f:
                return f.read().strip()
        except OSError:
            return ""


def _announce(session_id, action):
    """Tell the UI that a ROLE.md changed (JAG-532).

    The role is part of the prompt STACK shown in the Sessions inspector, so a
    write made by another surface (Orbit, the CLI, an agent) must repaint it —
    otherwise the panel keeps showing the previous role until F5.
    """
    try:
        from longrun.core.events import publish
        publish("roles.update", session=session_id, action=action)
    except Exception:  # noqa: BLE001 — an event must never block a write
        pass


def write(session_id, text):
    """Set a session's role. An empty text clears it (file removed)."""
    if not session_id:
        return {"ok": False, "error": "session required"}
    text = str(text if text is not None else "")
    if len(text) > _MAX:
        return {"ok": False, "error": "role too large (>%d bytes)" % _MAX}
    with _LOCK:
        p = path_for(session_id)
        if not text.strip():
            try:
                os.remove(p)
            except OSError:
                pass
            _announce(session_id, "cleared")
            return {"ok": True, "session": session_id, "cleared": True, "path": p}
        os.makedirs(roles_dir(), exist_ok=True)
        tmp = "%s.%s.tmp" % (p, os.getpid())
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(text)
        os.replace(tmp, p)
        _announce(session_id, "saved")
        return {"ok": True, "session": session_id, "path": p,
                "bytes": len(text.encode("utf-8"))}


def delete(session_id):
    """Remove a session's role file (a no-op when it has none)."""
    if not session_id:
        return {"ok": False, "error": "session required"}
    with _LOCK:
        p = path_for(session_id)
        try:
            os.remove(p)
            _announce(session_id, "deleted")
            return {"ok": True, "deleted": True, "path": p}
        except OSError:
            return {"ok": True, "deleted": False, "path": p}

