#!/usr/bin/env python3
"""v760 — the Control deck's views are SERVER state, and the selection is shared.

The deck kept its views only in `localStorage`, which is per ORIGIN: the app is served
on `:8790` (http) and `:8791` (https), from the LAN and from Tailscale, so a view built
on one entry point looked "reset" on another and vanished with site data. The operator
asked twice ("non salva i pannelli che aggiungo alla view… dove sono salvate le config
utente grafiche?").

Contract:
  A) `core/deck_views.py` validates on read AND write and never loses the default.
  B) `/api/orbit/views` is served on GET and accepted on POST.
  C) the deck hydrates from the server and keeps localStorage only as a mirror.
  D) the view bar states where the state lives, and tells the truth when a write fails.
  E) picking an agent in Agents/Org focuses the constellation too (one selection).

Run: python tests/acceptance/v760_deck_state.py
"""
import json
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="v760_")
os.environ["LONGRUN_SESSIONS_DIR"] = os.path.join(TMP, "sessions")
os.environ["LONGRUN_GRAPHS_DIR"] = os.path.join(TMP, "graphs")
os.environ["LONGRUN_THREADS_DIR"] = os.path.join(TMP, "threads")
os.environ["LONGRUN_DB"] = os.path.join(TMP, "events.db")
os.environ["LONGRUN_DATA_DIR"] = os.path.join(TMP, "data")
for d in ("cfg", "sessions", "graphs", "threads", "data"):
    os.makedirs(os.path.join(TMP, d), exist_ok=True)
sys.path.insert(0, os.path.join(REPO, "src"))

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""))


def src(*parts):
    with open(os.path.join(REPO, *parts), encoding="utf-8") as f:
        return f.read()


from longrun.core import deck_views as DV          # noqa: E402

API = src("src", "longrun", "core", "httpapi.py")
ORBIT = src("src", "longrun", "orbit", "web", "orbit.html")

# ---- A. the store -------------------------------------------------------------
check("A1 an absent file answers the shipped default",
      DV.get() == {"revision": 0,
                   "views": [{"id": "v-desk", "name": "Desk",
                              "panels": ["agents", "jobs", "org"]}],
                   "active": "view:v-desk"})
saved = DV.save({"views": [{"id": "v-a", "name": "Ops", "panels": ["agents", "const"]},
                           {"id": "v-b", "name": "Flow", "panels": ["jobs", "feed"]}],
                 "active": "view:v-b"})
check("A2 a valid document roundtrips and bumps the revision",
      saved["revision"] == 1 and DV.get() == saved
      and saved["active"] == "view:v-b")
check("A3 unknown panels are dropped, the view survives",
      DV.save({"views": [{"id": "v-c", "name": "x",
                          "panels": ["agents", "nope", "agents"]}]})["views"][0]["panels"] == ["agents"])
for bad, why in (
        ({"views": []}, "empty views"),
        ({"views": [{"id": "", "panels": ["agents"]}]}, "no id"),
        ({"views": [{"id": "v1", "panels": []}]}, "no panel"),
        ({"views": [{"id": "v1", "panels": ["agents"]},
                    {"id": "v1", "panels": ["jobs"]}]}, "duplicate ids"),
        ({"views": [{"id": "v%d" % i, "panels": ["agents"]} for i in range(DV.MAX_VIEWS + 1)]},
         "too many views")):
    try:
        DV.save(bad)
        ok = False
    except ValueError:
        ok = True
    check("A4 refuses %s" % why, ok)
check("A5 a view is capped to six panels",
      len(DV.save({"views": [{"id": "v-cap", "name": "cap",
                              "panels": list(DV.PANELS) + ["agents"]}]})["views"][0]["panels"]) == 6)
with open(DV.VIEWS_FILE, "w", encoding="utf-8") as fh:
    fh.write("{not json")
check("A6 a corrupt file falls back to the default instead of raising",
      DV.get()["views"][0]["id"] == "v-desk")

# ---- B. the route -------------------------------------------------------------
check("B1 GET /api/orbit/views is served next to the sidebar order",
      "deck_views.handle(\"GET\", path)" in API and '"/api/orbit/views"' in API)
check("B2 POST /api/orbit/views is dispatched with the body",
      "deck_views.handle(\"POST\", path, self._body())" in API)
check("B3 the store lives under DATA_DIR",
      'os.path.join(paths.DATA_DIR, "orbit_views.json")' in src("src", "longrun", "core", "deck_views.py"))

# ---- C. the client ------------------------------------------------------------
check("C1 the deck hydrates from the server on boot",
      "this.hydrateViews();" in ORBIT and "/api/orbit/views" in ORBIT)
check("C2 the server wins, localStorage stays the mirror",
      "localStorage.setItem(\"orbit_views_v1\"" in ORBIT
      and "this.api.post(\"/api/orbit/views\"" in ORBIT)
check("C3 a browser copy is pushed up once when the server has none",
      "if (virgin && local) { this.saveViews(); return; }" in ORBIT)

# ---- D. the UI states it ------------------------------------------------------
check("D1 the view bar names the store",
      'id="viewStore"' in ORBIT and "orbit_views.json" in ORBIT
      and "~/.longrun/data" in ORBIT)
check("D2 a failed write turns the chip red and says the browser is the only copy",
      "not saved · browser only" in ORBIT and "#viewBar .vsync.bad" in ORBIT)

# ---- E. one selection ---------------------------------------------------------
check("E1 the constellation follows the Agents/Org selection",
      "this.tac.selectSession(sid);" in ORBIT and "selectSession(sid){" in ORBIT)
check("E2 a plain chat session is pinned through the existing path",
      "this.ensureSession(sid).then(() => {" in ORBIT)
check("E3 the org sync is still there (it must not be replaced)",
      "this.org.selectNode(sid, scroll);" in ORBIT)

print("\nv760: %d/%d PASS" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
