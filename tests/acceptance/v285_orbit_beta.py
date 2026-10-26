#!/usr/bin/env python3
"""v285 — the optional Orbit command deck (longrun/orbit).

JAG-285 (user): rebuild the /console deck as a coherent, OOP deck that orchestrates
several sessions and can create them ahead of time; the Model Bay must show EVERY
provider, not only the DGX router.

Locked here:
  * the deck is importable as `longrun.orbit` and exposes `serve_page` + `handle`;
  * the Model Bay reads the full `providers.catalog` (all providers), not just the
    local router roster, and maps each model with its context window;
  * the SessionRegistry can pre-create a session and bind a model;
  * the Orchestrator refuses an empty goal / no targets (and only then starts work);
  * the server reaches the deck ONLY through guarded, swallowing hooks, and never
    imports it at the top level — so removing `longrun/orbit/` leaves the app
    untouched;
  * the deck's routes never shadow a non-orbit path.

Deterministic, no live server. Run: python3 tests/v285_longrun.orbit.py
"""
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(REPO, "src"))

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + detail) if detail else ""))


class FakeHandler:
    def __init__(self):
        self.sent = None

    def _send(self, code, obj, ctype=None):
        self.sent = {"code": code, "obj": obj, "ctype": ctype}
        return True


# --- 0) importable as a normal sub-package ------------------------------------
try:
    from longrun import orbit as orbit_beta
    check("the deck imports as longrun.orbit and exposes the two hooks",
          callable(getattr(orbit_beta, "serve_page", None))
          and callable(getattr(orbit_beta, "handle", None)))
except Exception as exc:  # noqa: BLE001
    check("the deck imports as longrun.orbit and exposes the two hooks", False, repr(exc))
    orbit_beta = None

# --- 1) Model Bay = full catalogue -------------------------------------------
with open(os.path.join(REPO, "src", "longrun", "orbit", "bay.py"), encoding="utf-8") as f:
    bay_src = f.read()
check("the Model Bay reads the FULL provider catalogue (not the DGX router only)",
      "catalog(loaded_aliases=" in bay_src and "providers" in bay_src)
if orbit_beta:
    from longrun.orbit.bay import ModelBay
    snap = ModelBay().snapshot()
    check("the snapshot has the expected shape",
          isinstance(snap.get("providers"), list) and isinstance(snap.get("count"), int)
          and "default" in snap)
    p = ModelBay._provider({"id": "x", "name": "X", "kind": "openrouter", "local": False,
                            "available": True, "base_url": "u", "key_env": "K",
                            "models": [{"id": "m", "ref": "x:m", "context_length": 128000,
                                        "loaded": None}]})
    check("a provider maps models with id/ref/context_length",
          p["models"][0]["ref"] == "x:m" and p["models"][0]["context_length"] == 128000
          and p["available"] is True and p["local"] is False)

# --- 2) Session registry: list + pre-create ----------------------------------
if orbit_beta:
    from longrun.orbit.registry import SessionRegistry
    reg = SessionRegistry()
    listed = reg.list()
    check("the roster lists sessions with a running flag",
          isinstance(listed.get("sessions"), list) and "active" in listed
          and all("running" in s for s in listed["sessions"]))
    made = reg.create(title="orbit-test", model="dgx:test")
    check("a session can be pre-created and bound to a model",
          made.get("ok") is True and made.get("session") and made.get("model") == "dgx:test")

# --- 3) Orchestrator guards ---------------------------------------------------
if orbit_beta:
    from longrun.orbit.orchestrator import Orchestrator
    orch = Orchestrator()
    check("dispatch with no goal is refused", orch.dispatch(["s1"], "").get("ok") is False)
    check("dispatch with no target is refused", orch.dispatch([], "do it").get("ok") is False)

# --- 3b) Attention feed ("what needs me", Paperclip-style) -------------------
if orbit_beta:
    from longrun.orbit.attention import AttentionFeed
    from longrun.orbit.registry import SessionRegistry as _Reg
    feed = AttentionFeed(_Reg(), lambda: [{"job": "j1", "session": "s1", "state": "error",
                                           "error": "boom", "started": 1}])
    snap = feed.snapshot()
    check("the attention feed ranks items and exposes the four sources",
          isinstance(snap.get("items"), list) and "by_severity" in snap
          and snap["sources"] == ["approval", "failed_run", "blocked_session", "budget_alert"])
    check("a failed dispatch job becomes a failed_run item",
          any(i["kind"] == "failed_run" and i["severity"] == "high" for i in snap["items"]))
    board = AttentionFeed.board(
        [{"id": "a", "running": True}, {"id": "b", "running": False}, {"id": "c", "running": False}],
        [{"session": "b"}])
    check("the board groups sessions into working / needs / idle",
          len(board["working"]) == 1 and len(board["needs"]) == 1 and len(board["idle"]) == 1)

# --- 4) API surface: routing + page ------------------------------------------
if orbit_beta:
    from longrun.orbit import api
    fh = FakeHandler()
    check("serve_page answers /orbit", api.serve_page(fh, "/orbit") is True
          and "Orbit" in (fh.sent or {}).get("obj", ""))
    fh2 = FakeHandler()
    check("serve_page ignores a non-orbit path", api.serve_page(fh2, "/console") is False)
    fh3 = FakeHandler()
    ok = api.handle(fh3, "GET", "/api/orbit/sessions", {}, None)
    check("GET /api/orbit/sessions answers 200", ok is True and fh3.sent["code"] == 200)
    fh4 = FakeHandler()
    ok = api.handle(fh4, "GET", "/api/orbit/models", {}, None)
    check("GET /api/orbit/models answers 200", ok is True and fh4.sent["code"] == 200)
    fh4b = FakeHandler()
    ok = api.handle(fh4b, "GET", "/api/orbit/attention", {}, None)
    check("GET /api/orbit/attention answers 200 with a board",
          ok is True and fh4b.sent["code"] == 200 and "board" in fh4b.sent["obj"])
    fh5 = FakeHandler()
    check("the deck NEVER shadows a non-orbit path",
          api.handle(fh5, "GET", "/api/status", {}, None) is False and fh5.sent is None)
    fh6 = FakeHandler()
    ok = api.handle(fh6, "POST", "/api/orbit/dispatch", {}, {"goal": ""})
    check("POST dispatch with no goal is a clean 200 + ok:false",
          ok is True and fh6.sent["obj"].get("ok") is False)

# --- 5) detachability: server reaches the deck only via guarded hooks ---------
# JAG-370: the hooks live in `bridge.py`; JAG-393: the deck moved into the package.
with open(os.path.join(REPO, "src", "longrun", "agent/bridge.py"), encoding="utf-8") as f:
    srv = f.read()
with open(os.path.join(REPO, "src", "longrun", "core/server.py"), encoding="utf-8") as f:
    server_src = f.read()
with open(os.path.join(REPO, "src", "longrun", "core/httpapi.py"), encoding="utf-8") as f:
    server_src += f.read()


def _top_level_deck_import(text):
    return any(ln.startswith(("import orbit", "from . import orbit",
                              "from longrun import orbit"))
               for ln in text.splitlines())


check("the app never imports the deck at the top level (no hard dependency)",
      not _top_level_deck_import(server_src) and not _top_level_deck_import(srv))
check("the bridge exposes a swallowing _orbit_module()",
      "def _orbit_module(" in srv and "except Exception:" in srv
      and "_orbit_cache[\"mod\"] = None" in srv)
check("the server serves the deck page only behind a guarded hook",
      "if _orbit_page(self, path):" in server_src)
check("the server delegates deck API routes on every method",
      all(("_orbit_handle(self, %r" % m).replace("'", '"') in server_src
          for m in ("GET", "POST", "PATCH", "DELETE")))

# --- 6) the UI is OOP + self-contained ---------------------------------------
with open(os.path.join(REPO, "src", "longrun", "orbit", "web", "orbit.html"), encoding="utf-8") as f:
    ui = f.read()
check("the Orbit UI is object-oriented (classes)",
      all(("class %s" % c) in ui for c in ("Api", "AgentsView", "OrgChartView",
                                           "JobsView", "RoutinesView", "FeedView", "OrbitApp")))
check("the UI drives the deck + orchestration endpoints",
      "/api/orbit/models" in ui and "/api/orbit/sessions" in ui
      and "/api/agents/tree" in ui and "/api/jobs" in ui)
check("the UI renders a graphical org chart with node boxes + connectors",
      # JAG-424d: connectors are now SVG elbows (.oedge) from the JS wrapped layout,
      # not the old one-row CSS tree's li::before borders.
      # v658: a node may also be marked `class="node cut"` (its manager sits outside
      # the team scope), so the contract is the class PREFIX, not the whole literal.
      'id="orgtree"' in ui and 'class="node' in ui and 'class="oedge"' in ui)

print("---")
passed = sum(results)
print("%d/%d PASS" % (passed, len(results)))
sys.exit(0 if passed == len(results) else 1)

