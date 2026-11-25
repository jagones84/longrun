#!/usr/bin/env python3
"""v1308 — a MALFORMED session id is a client error, not an empty answer.

Measured 2026-11-25 on the live service: `/api/threads?session=..%2F..%2Fetc%2Fpasswd`
and `/api/context?session=…` answered 200 with the raw id echoed back, and
`/api/sessions/../../etc/graph` answered 200 with an empty graph. The stores refuse
those ids anyway (`stores._valid_sid`), so nothing leaked — but a traversal was
answered as if it had been understood, and a client bug looked like an empty session.

The contract has two halves and both must hold:
  A  MALFORMED ids are refused with `400 {"error": "bad session id"}` on every read
     route that names a session (`/api/threads`, `/api/context`, `/api/context/items`,
     `/api/sessions/<sid>/graph`);
  B  a WELL-FORMED but unknown id keeps answering 200 with defaults (JAG-189): a fresh
     or just-deleted session must not log 404s (or 400s) on every UI poll.

Deterministic: a real `httpapi.Handler` on an ephemeral loopback port, isolated temp
dirs, no model, no router, no network.
Run: python3 tests/acceptance/v1308_bad_session_id_is_refused.py
"""
import atexit
import json
import os
import shutil
import sys
import tempfile
import threading
import urllib.error
import urllib.parse
import urllib.request
from http.server import ThreadingHTTPServer

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_tmp = tempfile.mkdtemp(prefix="sf-1308-")
atexit.register(lambda: shutil.rmtree(_tmp, ignore_errors=True))

# Isolate BEFORE importing: the paths are read at import time.
os.environ["LONGRUN_OFFLINE"] = "1"
os.environ["LONGRUN_OPTIMIZER"] = "0"
for _key in ("DATA_HOME", "DATA_DIR", "CONFIG_DIR", "SESSIONS_DIR", "GRAPH_DIR",
             "EDITS_DIR", "RUNS_DIR", "ROLES_DIR", "COSTS_DIR", "THREADS_DIR",
             "SKILLS_DIR", "PLUGINS_DIR"):
    _p = os.path.join(_tmp, _key.lower())
    os.makedirs(_p, exist_ok=True)
    os.environ["LONGRUN_" + _key] = _p
os.environ["LONGRUN_DB"] = os.path.join(_tmp, "events.db")
os.environ["LONGRUN_PRICES_FILE"] = os.path.join(_tmp, "prices.json")
sys.path.insert(0, os.path.join(REPO, "src"))

# The documented order (httpapi's docstring): `server` first, which binds `httpapi`
# at its bottom against a fully-populated module — `import httpapi` alone is the
# unsupported direction (v1307 C1).
from longrun.core import server, httpapi  # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""))


TOKEN = "v1308-token"
httpapi.AUTH_TOKEN = TOKEN
httpapi._sf_server.AUTH_TOKEN = TOKEN
httpapi._ensure_dirs()
_srv = ThreadingHTTPServer(("127.0.0.1", 0), httpapi.Handler)
_host, _port = _srv.server_address
threading.Thread(target=_srv.serve_forever, daemon=True).start()
BASE = "http://127.0.0.1:%d" % _port


def get(path):
    req = urllib.request.Request(BASE + path, headers={"Authorization": "Bearer " + TOKEN})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")


BAD = "../../etc/passwd"
BAD_Q = urllib.parse.quote(BAD, safe="")
BAD_P = urllib.parse.quote(BAD, safe="")

# ---- A: the helper splits a malformed id from an unknown/missing one ----------
check("A1 a missing id is not an error", httpapi._bad_session_id(None) is False
      and httpapi._bad_session_id("") is False)
check("A2 a real id is not an error",
      httpapi._bad_session_id("991db778424b") is False)
check("A3 a well-formed UNKNOWN id is not an error (JAG-189)",
      httpapi._bad_session_id("deadbeef00") is False)
for _bad in (BAD, "..", "a/b", "a" * 121):
    check("A4 malformed id is an error: %r" % _bad, httpapi._bad_session_id(_bad) is True)

# ---- B: every session-naming READ route refuses the malformed id --------------
routes = [
    "/api/threads?session=" + BAD_Q,
    "/api/context?session=" + BAD_Q,
    "/api/context/items?session=" + BAD_Q,
    "/api/sessions/" + BAD_P + "/graph",
]
for _r in routes:
    st, body = get(_r)
    ok = st == 400 and "bad session id" in body
    check("B %s -> 400 bad session id" % _r, ok, "status=%s body=%s" % (st, body[:90]))

# ---- C: a well-formed but unknown id still answers 200 with defaults ----------
for _r in ("/api/threads?session=deadbeef00",
           "/api/context?session=deadbeef00",
           "/api/context/items?session=deadbeef00",
           "/api/sessions/deadbeef00/graph"):
    st, body = get(_r)
    check("C %s -> 200 (JAG-189 keeps the poll quiet)" % _r, st == 200,
          "status=%s body=%s" % (st, body[:90]))

# ---- D: an existing session still reads its own graph (the happy path) --------
_sess = server.get_or_create_session("v1308-live")
_sid = _sess["id"]
st, body = get("/api/sessions/%s/graph" % _sid)
check("D1 a REAL session id answers 200/graph", st == 200, "status=%s" % st)
st, body = get("/api/threads?session=" + _sid)
check("D2 a REAL session id answers 200/threads", st == 200, "status=%s" % st)
st, body = get("/api/threads")
check("D3 no session at all is still the old 400 session required",
      st == 400 and "session required" in body, "status=%s body=%s" % (st, body[:90]))

# ---- E: the empty graph payload keeps its shape for the UI poll --------------
st, body = get("/api/sessions/deadbeef00/graph")
try:
    payload = json.loads(body)
except Exception:  # noqa: BLE001 — E reports the parse failure
    payload = {}
check("E1 the empty-graph answer keeps the documented keys",
      all(k in payload for k in ("session_id", "run_id", "nodes", "counts",
                                 "status", "node_count")), sorted(payload))

_srv.shutdown()
_srv.server_close()

print("---")
ok = sum(results)
print("%d/%d PASS" % (ok, len(results)))
sys.exit(0 if ok == len(results) else 1)
