"""Durable presentation state for the Control deck: its named views + the active one.

Why the server owns this. The deck kept its views ONLY in `localStorage`, which is
per ORIGIN: the app is served on `:8790` (http) and `:8791` (https)
(`httpapi._start_tls`), from the LAN address and from Tailscale, and every one of
those is a separate store. A view built on one entry point therefore looked "reset"
on another, and clearing site data erased it. The operator asked twice ("in control
non salva i pannelli che aggiungo alla view… dove sono salvate le config utente
grafiche?").

Same pattern as `core/sidebar_order.py`: one JSON file under DATA_DIR, validated on
read AND on write, so the browser can keep a localStorage mirror for the first paint
without becoming a second truth.
"""

import copy
import os
import threading

from longrun.util import paths
from longrun.util.fswrite import read_json, write_json

VIEWS_FILE = os.path.join(paths.DATA_DIR, "orbit_views.json")
_LOCK = threading.RLock()

#: The deck's panels, in markup order. A view may hold at most six of them.
PANELS = ("agents", "routines", "jobs", "org", "const", "feed")
MAX_VIEWS = 12
MAX_PANELS = 6
MAX_NAME = 40
MAX_ID = 60

DEFAULT_VIEW = {"id": "v-desk", "name": "Desk", "panels": ["agents", "jobs", "org"]}


def _empty():
    return {"revision": 0, "views": [copy.deepcopy(DEFAULT_VIEW)], "active": "view:v-desk"}


def _clean_view(raw):
    if not isinstance(raw, dict):
        return None
    vid = raw.get("id")
    if not isinstance(vid, str) or not vid.strip():
        return None
    vid = vid.strip()[:MAX_ID]
    name = raw.get("name")
    name = name.strip()[:MAX_NAME] if isinstance(name, str) and name.strip() else "View"
    panels, seen = [], set()
    raw_panels = raw.get("panels")
    for panel in (raw_panels if isinstance(raw_panels, list) else []):
        if isinstance(panel, str) and panel in PANELS and panel not in seen:
            seen.add(panel)
            panels.append(panel)
    if not panels:
        return None        # a view with no panel would be an invisible object
    return {"id": vid, "name": name, "panels": panels[:MAX_PANELS]}


def _normalise(raw):
    if not isinstance(raw, dict):
        return _empty()
    views, seen = [], set()
    raw_views = raw.get("views")
    for item in (raw_views if isinstance(raw_views, list) else []):
        view = _clean_view(item)
        if view and view["id"] not in seen:
            seen.add(view["id"])
            views.append(view)
    if not views:
        return _empty()
    active = raw.get("active")
    valid_ids = ["view:" + v["id"] for v in views]
    if not isinstance(active, str) or active not in valid_ids:
        active = valid_ids[0]
    try:
        revision = max(0, int(raw.get("revision", 0)))
    except (TypeError, ValueError):
        revision = 0
    return {"revision": revision, "views": views[:MAX_VIEWS], "active": active}


def get():
    """The stored deck state (never raises: a corrupt file falls back to the default)."""
    with _LOCK:
        return copy.deepcopy(_normalise(read_json(VIEWS_FILE, _empty())))


def save(raw):
    """Replace the whole document. Raises ValueError on a malformed payload."""
    if not isinstance(raw, dict):
        raise ValueError("a JSON object with `views` is required")
    views = raw.get("views")
    if not isinstance(views, list) or not views:
        raise ValueError("`views` must be a non-empty list")
    if len(views) > MAX_VIEWS:
        raise ValueError("at most %d views" % MAX_VIEWS)
    cleaned = []
    for item in views:
        view = _clean_view(item)
        if not view:
            raise ValueError("every view needs an id and at least one known panel")
        cleaned.append(view)
    ids = [v["id"] for v in cleaned]
    if len(set(ids)) != len(ids):
        raise ValueError("view ids must be unique")
    active = raw.get("active")
    valid = ["view:" + i for i in ids]
    if active not in valid:
        active = valid[0]
    with _LOCK:
        current = _normalise(read_json(VIEWS_FILE, _empty()))
        doc = {"revision": int(current.get("revision", 0)) + 1,
               "views": cleaned, "active": active}
        write_json(VIEWS_FILE, doc)
        return copy.deepcopy(doc)


def handle(method, path, body=None):
    """Serve `/api/orbit/views`; return None for any other route."""
    if path != "/api/orbit/views":
        return None
    if method == "GET":
        return 200, get()
    if method != "POST":
        return 405, {"error": "method not allowed"}
    try:
        return 200, save(body)
    except ValueError as exc:
        return 400, {"error": str(exc)}
