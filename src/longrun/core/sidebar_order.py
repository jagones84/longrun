"""Server-owned presentation order for the sessions sidebar."""

import copy
import os
import re
import threading

from longrun.util import paths
from longrun.util.fswrite import read_json, write_json

ORDER_FILE = os.path.join(paths.DATA_DIR, "sidebar_order.json")
_LOCK = threading.RLock()
_GROUP_RE = re.compile(r"^(?:T[1-9][0-9]*|__(?:none|pinned)__)$")
_ID_RE = re.compile(r"^[\w.-]{1,160}$", re.UNICODE)
_MAX_ORDER_ITEMS = 10000


def _empty():
    return {"revision": 0, "teams": [], "sessions": {}}


def _safe_id(value, label):
    if not isinstance(value, str) or not _ID_RE.fullmatch(value):
        raise ValueError("%s must be a valid id" % label)
    return value


def _normalise(raw):
    if not isinstance(raw, dict):
        return _empty()
    teams = raw.get("teams")
    sessions = raw.get("sessions")
    teams = teams if isinstance(teams, list) else []
    sessions = sessions if isinstance(sessions, dict) else {}
    clean_teams, seen = [], set()
    for value in teams[:_MAX_ORDER_ITEMS]:
        if isinstance(value, str) and _ID_RE.fullmatch(value) and value not in seen:
            seen.add(value)
            clean_teams.append(value)
    clean_sessions = {}
    for group, values in sessions.items():
        if not isinstance(group, str) or not _GROUP_RE.fullmatch(group):
            continue
        if not isinstance(values, list):
            continue
        clean, seen = [], set()
        for value in values[:_MAX_ORDER_ITEMS]:
            if isinstance(value, str) and _ID_RE.fullmatch(value) and value not in seen:
                seen.add(value)
                clean.append(value)
        clean_sessions[group] = clean
    try:
        revision = max(0, int(raw.get("revision", 0)))
    except (TypeError, ValueError):
        revision = 0
    return {"revision": revision, "teams": clean_teams, "sessions": clean_sessions}


def get():
    with _LOCK:
        return copy.deepcopy(_normalise(read_json(ORDER_FILE, _empty())))


def _validate_scope(kind, group, ids):
    if kind == "team":
        if group is not None:
            raise ValueError("team moves do not take a group")
    elif kind == "session":
        if not isinstance(group, str) or not _GROUP_RE.fullmatch(group):
            raise ValueError("session moves require a valid group")
    else:
        raise ValueError("kind must be team or session")

    if not isinstance(ids, list) or len(ids) > _MAX_ORDER_ITEMS:
        raise ValueError("ids must be a bounded list")
    clean = [_safe_id(value, "id") for value in ids]
    if len(clean) != len(set(clean)):
        raise ValueError("ids must not contain duplicates")
    return clean


def handle(method, path, body=None):
    """Handle the authenticated sidebar-order API; return None for other routes."""
    if path != "/api/sidebar/order":
        return None
    if method == "GET":
        return 200, get()
    if method != "PATCH":
        return 405, {"error": "method not allowed"}
    if not isinstance(body, dict):
        return 400, {"error": "JSON object required"}

    try:
        kind = body.get("kind")
        group = body.get("group")
        ids = _validate_scope(kind, group, body.get("ids"))
        revision = body.get("revision")
        if isinstance(revision, bool) or not isinstance(revision, int) or revision < 0:
            raise ValueError("revision must be a non-negative integer")
    except ValueError as exc:
        return 400, {"error": str(exc)}

    with _LOCK:
        order = _normalise(read_json(ORDER_FILE, _empty()))
        if revision != order["revision"]:
            return 409, {"error": "sidebar order changed", "order": copy.deepcopy(order)}
        if kind == "team":
            changed = order["teams"] != ids
            if changed:
                order["teams"] = ids
        else:
            current = order["sessions"].get(group, [])
            changed = current != ids
            if changed:
                order["sessions"][group] = ids
        if changed:
            order["revision"] += 1
            write_json(ORDER_FILE, order)
        result = copy.deepcopy(order)

    if changed:
        from longrun.core.events import publish
        publish("sidebar.order.updated", revision=result["revision"])
    return 200, result
