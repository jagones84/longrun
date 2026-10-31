#!/usr/bin/env python3
"""v746 — http.fetch is not dead under approvals.mode=FULL.

The allow-list in config/tools.yaml is a capability boundary (127.0.0.1 by
default), so `http.fetch api.github.com` answered "host not in allow_hosts" even
with approvals.mode=full — measured 2026-10-31, where the model then burned turns
on curl. FULL now routes an unlisted PUBLIC host through the same SSRF-guarded
reader the `web`/`browser` tools use; every other mode keeps the strict list.

Deterministic: the router is pure and the fetch is stubbed. No network.
"""
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="sf-v746-")
os.environ["LONGRUN_CONFIG_DIR"] = os.path.join(TMP, "cfg")
os.environ["LONGRUN_SESSIONS_DIR"] = os.path.join(TMP, "sessions")
os.environ["LONGRUN_EDITS_DIR"] = os.path.join(TMP, "edits")
os.environ["LONGRUN_RUNS_DIR"] = os.path.join(TMP, "runs")
os.environ["LONGRUN_DATA_DIR"] = os.path.join(TMP, "data")
os.environ["LONGRUN_DB"] = os.path.join(TMP, "events.db")
os.environ["LONGRUN_GRAPH_DIR"] = os.path.join(TMP, "graphs")
os.environ["LONGRUN_PROJECTS_DIR"] = os.path.join(TMP, "projects")
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.tools import registry             # noqa: E402
from longrun.tools import tools                # noqa: E402

registry._external_tools = lambda: {}
results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""))


LOCAL = ["127.0.0.1", "localhost"]

# ---- A. the router ---------------------------------------------------------
check("A1 a listed host is served directly",
      tools.http_route("http://127.0.0.1:8790/api/status", LOCAL, False) == ("allow", "127.0.0.1"))
check("A2 an unlisted host stays denied without FULL",
      tools.http_route("https://api.github.com/x", LOCAL, False) == ("deny", "api.github.com"))
check("A3 an unlisted host goes public WITH FULL",
      tools.http_route("https://api.github.com/x", LOCAL, True) == ("public", "api.github.com"))
check("A4 an empty allow-list means public (browser-tool precedent)",
      tools.http_route("https://example.com/x", [], False) == ("public", "example.com"))

# ---- B. the tool honours the route ----------------------------------------
calls = []
tools._web_fetch = lambda url, max_bytes: (calls.append(("public", url)) or
                                           ({"url": url, "text": "PUBLIC BODY", "host": "example.com"}, None))
tools._http_fetch = lambda url, allow, max_bytes, method="GET": (
    calls.append(("allow", url)) or ({"status": 200, "body": "LOCAL BODY", "host": "localhost",
                                      "duration_ms": 1}, None))

registry._approvals_full = lambda: True
res = tools._http({"url": "https://example.com/data.csv"}, "v746")
check("B1 FULL + unlisted host succeeds via the public reader",
      res.get("ok") and "PUBLIC BODY" in str(res.get("stdout"))
      and res.get("backend") == "host(http/public)", res.get("backend"))

registry._approvals_full = lambda: False
res = tools._http({"url": "https://example.com/data.csv"}, "v746")
check("B2 without FULL the same call is refused",
      res.get("ok") is False and "allow_hosts" in str(res.get("error")), res.get("error"))
check("B3 the refusal names the way out",
      "mode=full" in str(res.get("error")) and "web.fetch" in str(res.get("error")),
      res.get("error"))

tools._http_fetch = lambda url, allow, max_bytes, method="GET": (
    ({"status": 200, "body": "LOCAL BODY", "host": "127.0.0.1", "duration_ms": 1}, None))
res = tools._http({"url": "http://127.0.0.1:8790/api/status"}, "v746")
check("B4 a listed host still takes the direct path",
      res.get("ok") and "LOCAL BODY" in str(res.get("stdout"))
      and res.get("backend") == "host(http)", res.get("backend"))

print("%d/%d checks" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
