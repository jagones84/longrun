#!/usr/bin/env python3
"""v623 — shared DragSort engine: Sessions sidebar + Control agents, one truth.

  A  the engine lives exactly once (webui/assets/dragsort.js): moveItem,
     orderByIds, bind, consumeClick — pointer+touch, hold-to-drag, drop
     marks, click suppression, server order contract.
  B  Sessions page (webui/index.html) runs on it: script include BEFORE the
     main inline script, orderByIds/moveItem/bind/consumeClick wired, the old
     hand-rolled sidebar engine deleted.
  C  Control agents table (orbit.html) runs on the SAME engine, not a copy:
     script include, orderByIds per group in render, row bindings on
     tr[data-sid] via td.aid with grp-empty append targets, consumeClick
     guards, persist to the SAME /api/sidebar/order store (kind session,
     session ids) through a new Api.patch — no second order truth, no
     second drag state machine.

Deterministic: static source contract, no server, no model, no network.
Run: python3 tests/acceptance/v623_shared_dragsort.py
"""
import os

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _read(*parts):
    with open(os.path.join(REPO, *parts), encoding="utf-8") as f:
        return f.read()


DRAG = _read("webui", "assets", "dragsort.js")
INDEX = _read("webui", "index.html")
ORBIT = _read("src", "longrun", "orbit", "web", "orbit.html")

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""))


# ---------------- A: one engine ----------------------
check("A1 engine exposes moveItem/orderByIds/bind/consumeClick",
      all(("function %s(" % n) in DRAG for n in ("moveItem", "orderByIds"))
      and all(("  %s:" % n) in DRAG or ("%s:" % n) in DRAG
              for n in ("moveItem", "orderByIds", "bind", "consumeClick")))
check("A2 engine owns hold time, drop marks, suppression, capture",
      "HOLD_MS" in DRAG and "drop-before" in DRAG and "SUPPRESS_MS" in DRAG
      and "setPointerCapture" in DRAG)
check("A3 engine documents both pages, no page logic inside",
      "webui/index.html" in DRAG and "orbit.html" in DRAG
      and "sidebar/order" in DRAG)

# ---------------- B: Sessions page on the engine ----------------------
inc = '<script src="/assets/dragsort.js"></script>'
check("B1 Sessions includes the engine before the main inline script",
      inc in INDEX and INDEX.index(inc) < INDEX.index("_bindSidebarDrag"))
check("B2 Sessions orders, moves, binds and suppresses via DragSort",
      "DragSort.orderByIds" in INDEX and "DragSort.moveItem" in INDEX
      and "DragSort.bind" in INDEX and "DragSort.consumeClick" in INDEX)
check("B3 old hand-rolled sidebar engine deleted (no second truth)",
      "_clearSidebarDragState" not in INDEX and "_finishSidebarDrag" not in INDEX
      and "_sidebarMoveDrag" not in INDEX and "TOUCH_DRAG_HOLD_MS" not in INDEX)

# ---------------- C: Control agents on the same engine ----------------------
check("C1 Control includes the engine before its inline script",
      inc in ORBIT and ORBIT.index(inc) < ORBIT.index("class AgentsView"))
check("C2 Control orders each group via DragSort, session keys, no second rule",
      "DragSort.orderByIds" in ORBIT and "a => a.session" in ORBIT
      and "this._orderBase" in ORBIT)
check("C3 Control binds rows (tr[data-sid] via td.aid, grp-empty appends)",
      "_bindRowDrag" in ORBIT and 'itemSel: "tr[data-sid]"' in ORBIT
      and 'td.aid' in ORBIT and 'emptySel: "tr.grp-empty"' in ORBIT
      and "DragSort.bind" in ORBIT and "DragSort.moveItem" in ORBIT)
check("C4 Control clicks suppressed after a drag, mid-drag poll deferred",
      ORBIT.count("DragSort.consumeClick") >= 2
      and 'body.querySelector(".dragging")' in ORBIT)
check("C5 Control persists to the SAME sidebar-order store, session ids",
      "patch(path, body)" in ORBIT and '_persistGroupOrder' in ORBIT
      and 'kind: "session"' in ORBIT)
check("C6 Control adds no second drag state machine",
      "HOLD_MS" not in ORBIT and "function moveDrag" not in ORBIT
      and "function finishDrag" not in ORBIT
      and "setPointerCapture" in ORBIT)  # splitters/org/view-cols keep theirs; rows use DragSort

print("---")
ok = sum(results)
print("\nv623: %d/%d PASS" % (ok, len(results)))
raise SystemExit(0 if ok == len(results) else 1)
