#!/usr/bin/env python3
"""v1172 — `available` must not claim a dead provider is callable.

A54 P5: `/api/models` reported `available: true` for providers whose endpoint
refused the connection. `available()` only means "local, or its key is present";
the catalogue then published that as "usable".

Pinned here (no network: `reachable` is stubbed):
  * a configured provider with `reachable=False` is not `available`;
  * a reachable provider keeps all three fields true;
  * an unknown probe (`None`) is not turned into a lie;
  * the routing helper `available()` keeps its old meaning;
  * the API payload and the WebUI consume `configured`/`reachable`.

Run: python3 tests/acceptance/v1172_provider_reachability.py
"""
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="sf-v1172-")
os.environ["LONGRUN_CONFIG_DIR"] = os.path.join(TMP, "cfg")
os.environ["LONGRUN_DATA_DIR"] = os.path.join(TMP, "data")
os.environ["LONGRUN_DB"] = os.path.join(TMP, "events.db")
os.environ["LONGRUN_SESSIONS_DIR"] = os.path.join(TMP, "sessions")
os.environ["LONGRUN_EDITS_DIR"] = os.path.join(TMP, "edits")
os.environ["LONGRUN_RUNS_DIR"] = os.path.join(TMP, "runs")
os.environ["LONGRUN_OFFLINE"] = "1"
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.model import providers as P  # noqa: E402
from longrun.core import server as _server  # noqa: E402,F401 — breaks the httpapi cycle
from longrun.core import httpapi          # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name
          + ((" :: " + str(detail)[:300]) if detail else ""))


ROW = {
    "id": "dead", "name": "Dead endpoint", "kind": "custom", "local": False,
    "base_url": "http://127.0.0.1:1/v1",
    "models": [{"id": "m1", "context_length": 4096}],
}

_orig = (P.load, P.providers, P.default_ref, getattr(P, "reachable", None),
         httpapi.router_models)
try:
    P.load = lambda reload=False: {"providers": [ROW], "default": None}
    P.providers = lambda: [ROW]
    P.default_ref = lambda: None

    P.reachable = lambda provider: False
    row = P.catalog()["providers"][0]
    check("A1 a configured but unreachable provider is not available",
          row.get("configured") is True and row.get("reachable") is False
          and row.get("available") is False, row)

    P.reachable = lambda provider: True
    row = P.catalog()["providers"][0]
    check("A2 a reachable provider keeps configured/reachable/available true",
          row.get("configured") is True and row.get("reachable") is True
          and row.get("available") is True, row)

    P.reachable = lambda provider: None
    row = P.catalog()["providers"][0]
    check("A3 an unknown probe is not treated as dead",
          row.get("configured") is True and row.get("reachable") is None
          and row.get("available") is True, row)

    check("A4 providers.available() keeps its routing meaning",
          P.available(ROW) is True, P.available(ROW))

    httpapi.router_models = lambda: []
    P.reachable = lambda provider: False
    payload = httpapi.providers_catalog()
    api_row = (payload.get("providers") or [{}])[0]
    check("A5 the /api/models payload exposes the three fields",
          "configured" in api_row and "reachable" in api_row
          and api_row.get("available") is False, api_row)
finally:
    (P.load, P.providers, P.default_ref, _reach, httpapi.router_models) = _orig
    if _reach is None:
        try:
            del P.reachable
        except AttributeError:
            pass

with open(os.path.join(REPO, "webui", "index.html"), encoding="utf-8") as f:
    UI = f.read()
check("A6 the models panel reads configured and reachable",
      "configured" in UI and "reachable" in UI and "unreachable" in UI.lower())

print("---")
ok = sum(results)
print("\nv1172: %d/%d PASS" % (ok, len(results)))
sys.exit(0 if ok == len(results) else 1)
