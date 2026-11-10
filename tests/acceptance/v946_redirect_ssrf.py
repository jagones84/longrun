#!/usr/bin/env python3
"""v946 — a redirect cannot hand the fetcher a private address.

`web.fetch` checked `_public_host(url)` (DNS resolved, private/loopback
rejected) and then called `urllib.request.urlopen`, whose default redirect
handler follows a 3xx to ANY target. A public host could answer
`302 Location: http://127.0.0.1:8080/…` (the unauthenticated llama.cpp router) or
any LAN address, and the guard never saw the second URL. `http.fetch` had the
same hole against its `allow_hosts` list.

`_CheckedRedirect` re-runs the per-tool predicate on every hop; `_opener(check)`
is the only way the fetch tools build an opener now.

Deterministic: no socket is opened, the handler is exercised directly.
Run: python3 tests/acceptance/v946_redirect_ssrf.py
"""

import inspect
import os
import sys
import tempfile
import urllib.error
import urllib.request

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="sf-v946-")
os.environ["LONGRUN_DATA_DIR"] = TMP
for _k in ("CONFIG_DIR", "SESSIONS_DIR", "EDITS_DIR", "RUNS_DIR", "GRAPH_DIR", "ROLES_DIR"):
    os.environ["LONGRUN_" + _k] = os.path.join(TMP, _k)
    os.makedirs(os.path.join(TMP, _k), exist_ok=True)
os.environ["LONGRUN_DB"] = os.path.join(TMP, "events.db")
os.environ["LONGRUN_JOBS_FILE"] = os.path.join(TMP, "jobs.json")
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.tools import tools as T      # noqa: E402
from longrun.tools import registry as REG  # noqa: E402,F401 — tools imports the registry

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""))


def hop(check_fn, target):
    """Run one redirect through the handler; return the outcome string."""
    h = T._CheckedRedirect(check_fn)
    req = urllib.request.Request("http://start.example/")
    try:
        got = h.redirect_request(req, None, 302, "Found", {}, target)
        return "request" if isinstance(got, urllib.request.Request) else "other"
    except urllib.error.URLError as e:
        return "blocked: %s" % e
    except Exception as e:  # noqa: BLE001 — anything else is a failure too
        return "raised %s: %s" % (type(e).__name__, e)


# ---- A. the SSRF guard is applied to the HOP, not only the first url --------
out = hop(T._public_host, "http://127.0.0.1:8080/health")
check("A1 a redirect to loopback is blocked", out.startswith("blocked"), out)
out = hop(T._public_host, "http://10.0.0.5/admin")
check("A2 a redirect to a private address is blocked", out.startswith("blocked"), out)
out = hop(T._public_host, "http://169.254.169.254/latest/meta-data")
check("A3 a redirect to link-local (cloud metadata) is blocked", out.startswith("blocked"), out)
out = hop(T._public_host, "file:///etc/passwd")
check("A4 a redirect to a non-http scheme is blocked", out.startswith("blocked"), out)

# ---- B. a normal redirect still works --------------------------------------
out = hop(lambda u: (True, "ok"), "http://elsewhere.example/page")
check("B1 an allowed redirect still builds the next request", out == "request", out)

# ---- C. the http tool keeps its own contract -------------------------------
allow = ["127.0.0.1"]
out = hop(lambda u: T._host_allowed(u, allow), "http://127.0.0.1:8790/api/status")
check("C1 the http allow-list hop to 127.0.0.1 is allowed", out == "request", out)
out = hop(lambda u: T._host_allowed(u, allow), "https://example.com/")
check("C2 a hop OFF the http allow-list is blocked", out.startswith("blocked"), out)

# ---- D. the fetch tools build their opener through _opener -----------------
src_web = inspect.getsource(T._web_fetch)
src_http = inspect.getsource(T._http_fetch)
check("D1 web.fetch uses the checked opener", "_opener(_public_host)" in src_web
      and "urllib.request.urlopen" not in src_web, src_web[:0])
check("D2 http.fetch uses the checked opener", "_opener(" in src_http
      and "urllib.request.urlopen" not in src_http, src_http[:0])
check("D3 _opener installs a redirect handler",
      isinstance(T._opener(lambda u: (True, "ok")).handlers[-1], T._CheckedRedirect)
      or any(isinstance(h, T._CheckedRedirect)
             for h in T._opener(lambda u: (True, "ok")).handlers))

print("TOTAL %d/%d" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
