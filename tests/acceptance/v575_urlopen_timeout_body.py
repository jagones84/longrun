#!/usr/bin/env python3
"""v575: `_open_with_retry` must not clobber the request body with the timeout.

REGRESSION (real outage, 2026-10-24): every Longrun run that called a remote
OpenAI-compatible provider died with

    message_body should be a bytes-like object or an iterable, got <class 'int'>

Root cause: `urllib.request.urlopen(url, data=None, timeout=...)` binds its
SECOND POSITIONAL argument to `data`. The helper called

    urllib.request.urlopen(req, timeout)

so the integer timeout overwrote `req.data` (the JSON completion body).
http.client then raised `TypeError` before a single byte left the box.

This test drives the REAL `http.server` stack over a real socket and asserts
two things:

  1. the server received the EXACT request body (the timeout never became the
     body), and
  2. `urlopen` was called with `timeout` as a KEYWORD argument (so a future
     refactor cannot silently reintroduce the positional call).

Both assertions fail against the pre-fix code (1 raises TypeError, 2 sees a
second positional argument).
"""

import http.server
import os
import sys
import tempfile
import threading
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
TMP = tempfile.mkdtemp(prefix="sf-v575-")
os.environ["LONGRUN_DB"] = os.path.join(TMP, "events.db")
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.model import rllm  # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""))


# ---- a real one-shot HTTP server -------------------------------------------

RECEIVED = {"body": None, "path": None}


class _Handler(http.server.BaseHTTPRequestHandler):
    def do_POST(self):  # noqa: N802 — stdlib naming
        length = int(self.headers.get("Content-Length") or 0)
        RECEIVED["body"] = self.rfile.read(length)
        RECEIVED["path"] = self.path
        payload = b'{"ok":true}'
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, *args):  # noqa: D102 — silence the std access log
        pass


_server = http.server.HTTPServer(("127.0.0.1", 0), _Handler)
_thread = threading.Thread(target=_server.serve_forever, daemon=True)
_thread.start()
BASE = "http://127.0.0.1:%d" % _server.server_address[1]

BODY = b'{"model":"openrouter/auto","messages":[{"role":"user","content":"hi"}]}'
URL = BASE + "/v1/chat/completions"

# ---- 1. the body survives the open -----------------------------------------

req = urllib.request.Request(URL, data=BODY, headers={"Content-Type": "application/json"})
try:
    with rllm._open_with_retry(req, 5) as resp:
        echoed = resp.read()
    check("1a the request body reaches the server intact",
          RECEIVED["body"] == BODY,
          "sent=%r received=%r" % (BODY[:40], (RECEIVED["body"] or b"")[:40]))
    check("1b the response body is read back", echoed == b'{"ok":true}', echoed)
    check("1c the request path is preserved", RECEIVED["path"] == "/v1/chat/completions",
          RECEIVED["path"])
except Exception as exc:  # noqa: BLE001 — the pre-fix failure surfaces here
    check("1a the request body reaches the server intact", False,
          "%s: %s" % (type(exc).__name__, exc))
    check("1b the response body is read back", False, exc)
    check("1c the request path is preserved", False, exc)

# ---- 2. the timeout is passed by keyword ------------------------------------

calls = {"positional": 0, "keyword": 0}
_real_urlopen = urllib.request.urlopen


def _spy(url, *args, **kwargs):
    if args:
        calls["positional"] += 1
    if "timeout" in kwargs:
        calls["keyword"] += 1
    return _real_urlopen(url, *args, **kwargs)


req2 = urllib.request.Request(URL, data=BODY, headers={"Content-Type": "application/json"})
urllib.request.urlopen = _spy
try:
    with rllm._open_with_retry(req2, 5) as resp:
        resp.read()
finally:
    urllib.request.urlopen = _real_urlopen

check("2a the timeout is passed as a keyword argument", calls["keyword"] == 1, calls)
check("2b no positional argument is handed to urlopen", calls["positional"] == 0, calls)

_server.shutdown()
_server.server_close()

print("TOTAL %d/%d" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
