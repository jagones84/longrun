#!/usr/bin/env python3
"""v538 — sidebar ordering is server-backed and shared across clients.

Locks the API contract for team ordering and per-group session ordering. A move
is atomic, persisted, revisioned, and announced through the shared event feed.
"""
import atexit
import os
import shutil
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="sf-v538-")
atexit.register(lambda: shutil.rmtree(TMP, ignore_errors=True))
os.environ["LONGRUN_DATA_DIR"] = os.path.join(TMP, "data")
os.environ["LONGRUN_DB"] = os.path.join(TMP, "events.db")
sys.path.insert(0, os.path.join(ROOT, "src"))

from longrun.core import sidebar_order as SO  # noqa: E402
from longrun.core import events               # noqa: E402

results = []


def check(name, ok, detail=""):
    ok = bool(ok)
    results.append(ok)
    print(("PASS " if ok else "FAIL ") + name
          + ((" :: " + str(detail)) if detail else ""))


def request(method, body=None):
    return SO.handle(method, "/api/sidebar/order", body or {})


status, initial = request("GET")
check("A1 empty order has a stable server-owned shape",
      status == 200 and initial == {"revision": 0, "teams": [], "sessions": {}})

cursor = events.events_since(0)
team_status, team_order = request("PATCH", {
    "kind": "team", "ids": ["T2", "T1"], "revision": 0
})
check("A2 team moves are applied atomically and increment the revision",
      team_status == 200 and team_order.get("teams") == ["T2", "T1"]
      and team_order.get("revision") == 1, team_order)

session_status, session_order = request("PATCH", {
    "kind": "session", "ids": ["S2", "S1"], "group": "T1", "revision": 1
})
check("A3 session moves are scoped to their displayed group",
      session_status == 200
      and session_order.get("sessions", {}).get("T1") == ["S2", "S1"]
      and session_order.get("teams") == ["T2", "T1"], session_order)

other_group_status, other_group_order = request("PATCH", {
    "kind": "session", "ids": ["S2"], "group": "__none__", "revision": 2
})
check("A4 the same session can have independent visual order per group",
      other_group_status == 200
      and other_group_order.get("sessions", {}).get("T1") == ["S2", "S1"]
      and other_group_order.get("sessions", {}).get("__none__") == ["S2"],
      other_group_order)

persisted_status, persisted = request("GET")
check("A5 GET returns the latest durable order and revision",
      persisted_status == 200 and persisted == other_group_order, persisted)

invalid_status, invalid = request("PATCH", {
    "kind": "session", "ids": ["S3"], "group": "../teams", "revision": 3
})
check("A6 malformed group keys are rejected without changing state",
      invalid_status == 400 and request("GET")[1] == persisted, invalid)

stale_status, stale = request("PATCH", {
    "kind": "team", "ids": ["T1", "T2"], "revision": 1
})
check("A7 stale clients cannot overwrite a newer device order",
      stale_status == 409 and stale.get("order") == persisted
      and request("GET")[1] == persisted, stale)

new_events = [e for e in events.events_since(0) if e.get("id", 0) > (
    cursor[-1]["id"] if cursor else 0)]
order_events = [e for e in new_events if e.get("kind") == "sidebar.order.updated"]
check("A8 successful moves publish revision events for live clients",
      len(order_events) == 3
      and [e.get("revision") for e in order_events] == [1, 2, 3],
      order_events)

with open(os.path.join(ROOT, "src", "longrun", "core", "httpapi.py"),
          encoding="utf-8") as f:
    http_source = f.read()
get_block = http_source.split("    def do_GET(self):", 1)[1].split(
    "    # ---- POST ----", 1)[0]
patch_block = http_source.split("    def do_PATCH(self):", 1)[1].split(
    "    # ---- DELETE ----", 1)[0]
check("A9 GET and PATCH route through the authenticated HTTP dispatcher",
      "sidebar_order" in get_block and "sidebar_order" in patch_block
      and get_block.index("check_auth") < get_block.index("sidebar_order")
      and patch_block.index("check_auth") < patch_block.index("sidebar_order"))

with open(os.path.join(ROOT, "webui", "index.html"), encoding="utf-8") as f:
    ui_source = f.read()
check("A10 the UI loads canonical server order and refreshes on feed events",
      '"/api/sidebar/order"' in ui_source
      and '"sidebar.order.updated"' in ui_source
      and "loadSidebarOrder" in ui_source)
check("A11 team and session names are the only drag targets",
      '_bindSidebarDrag(d.querySelector(".t")' in ui_source
      and 'head.querySelector(".gname")' in ui_source
      and "function _bindSidebarDrag(label" in ui_source
      and "sorder-controls" not in ui_source)
check("A12 an ordinary tap keeps its existing select or collapse action",
      "function _consumeSidebarDragClick(e, source)" in ui_source
      and "_consumeSidebarDragClick(e, d)" in ui_source
      and "_consumeSidebarDragClick(e, sec)" in ui_source
      and "selectSession(s);" in ui_source and "_toggleGroup(g.key);" in ui_source)
check("A13 drag handlers use Pointer Events without decorative controls",
      "pointerdown" in ui_source and "pointermove" in ui_source
      and "pointerup" in ui_source and "pointercancel" in ui_source
      and "aria-label=\"Move up\"" not in ui_source
      and "aria-label=\"Move down\"" not in ui_source
      and "aria-label=\"Drag session" not in ui_source
      and "_nudgeSidebarOrder" not in ui_source)
check("A14 touch drag requires a hold and suppresses the click action",
      "TOUCH_DRAG_HOLD_MS" in ui_source
      and "pointerType === \"touch\"" in ui_source
      and "state.holdTimer" in ui_source
      and "state.suppressClick" in ui_source
      and 'addEventListener("touchstart"' in ui_source
      and 'addEventListener("touchmove", move, { passive: false })' in ui_source
      and "ev.preventDefault();" in ui_source)
check("A15 session ordering is scoped by group and drag cannot change membership",
      "groupKey" in ui_source and "teams.updated" in ui_source
      and "/api/teams/" not in ui_source[ui_source.find("function _persistSidebarOrder"):
                                       ui_source.find("function _persistSidebarOrder") + 1200])
check("A16 pointer drag uses the shared validated commit path",
      "function _sidebarMoveDrag(state, x, y)" in ui_source
      and "_sidebarSetDropTarget(state, document.elementFromPoint(x, y), y)" in ui_source
      and "function _finishSidebarDrag(state)" in ui_source
      and "_finishSidebarDrag(state)" in ui_source)
check("A17 a team's drop midpoint is measured on its HEADER, not the whole group",
      'state.kind === "team"\n      ? (target.querySelector(".sgroup-h") || target) : target'
      in ui_source
      and 'const r = measure.getBoundingClientRect();' in ui_source)
check("A18 a team header is bound AFTER it is attached (closest finds its group)",
      ui_source.index("sec.appendChild(head);")
      < ui_source.index('_bindSidebarDrag(head.querySelector(".gname")'))

print("v538: %d/%d PASS" % (sum(results), len(results)))
raise SystemExit(0 if all(results) else 1)
