#!/usr/bin/env python3
"""v835 — a turn whose CLIENT is gone must stop, not keep spending.

Live 2026-11-06 (polyglot `python/forth`, session `b3a6b29e897c`): the benchmark's
per-task client timeout is 600 s. At 21:23 the client gave up and closed the
socket; `POST /api/chat` kept the turn RUNNING and the cost ledger shows model
calls at 21:25:05, 21:25:13, 21:25:25, 21:25:30 … — 3+ minutes of paid work whose
answer nobody would ever read, inside the same turn the suite had already scored.

A synchronous `/api/chat` has exactly ONE reader: the request that opened it.
When that reader is gone the honest thing is to abort the turn (same flag the
Stop button sets) instead of finishing an answer that cannot be delivered.

Deterministic and offline: socket pairs only, no model, no network, no server.
"""
import os
import socket
import sys
import tempfile
import threading
import time

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="longrun-v835-")
for _k in ("CONFIG_DIR", "SESSIONS_DIR", "EDIT_DIR", "RUNS_DIR", "GRAPH_DIR", "DATA_DIR"):
    os.environ.setdefault("LONGRUN_" + _k, os.path.join(TMP, _k))
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.core import server  # noqa: E402,F401 — must load FIRST (httpapi imports it)
from longrun.core import httpapi  # noqa: E402
from longrun.util import steering  # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name
          + ((" :: " + str(detail)[:300]) if detail and not ok else ""))


def wait_for(pred, secs=3.0):
    end = time.time() + secs
    while time.time() < end:
        if pred():
            return True
        time.sleep(0.02)
    return False


# ---- A: the detector itself --------------------------------------------------
_srv, _cli = socket.socketpair()
check("A1 an OPEN client is not reported as gone",
      httpapi.client_gone(_srv) is False, httpapi.client_gone(_srv))
_cli.close()
check("A2 a CLOSED client is reported as gone (EOF on the socket)",
      httpapi.client_gone(_srv) is True, httpapi.client_gone(_srv))
_srv.close()
check("A3 a dead/garbage socket is a closure, never an exception",
      httpapi.client_gone(_srv) is True, httpapi.client_gone(_srv))

# ---- B: the watcher aborts the turn -----------------------------------------
SID_LIVE = "orphan-live-835"
_srv, _cli = socket.socketpair()
_stop = threading.Event()
_t = threading.Thread(target=httpapi.watch_client,
                      args=(_srv, SID_LIVE, _stop), kwargs={"poll": 0.05},
                      daemon=True)
_t.start()
time.sleep(0.35)
check("B1 a turn whose client STAYS connected is left alone",
      steering._is_aborted(SID_LIVE) is False, steering._is_aborted(SID_LIVE))
_cli.close()
check("B2 the turn is aborted once the client disconnects",
      wait_for(lambda: steering._is_aborted(SID_LIVE)), steering._is_aborted(SID_LIVE))
_stop.set()
_t.join(timeout=2)
check("B3 the watcher stops when the turn ends (no thread outlives it)",
      not _t.is_alive(), _t.is_alive())
_srv.close()
steering.clear_abort(SID_LIVE)

# ---- C: a live peer's DATA is never consumed by the peek ---------------------
_srv, _cli = socket.socketpair()
_cli.sendall(b"GET /api/sessions HTTP/1.1\r\n\r\n")
time.sleep(0.05)
check("C1 a queued request on the connection reads as OPEN, not as EOF",
      httpapi.client_gone(_srv) is False, httpapi.client_gone(_srv))
check("C2 the peek did NOT consume the client's bytes",
      _srv.recv(4) == b"GET ", "peek consumed the request")
_srv.close()
_cli.close()

print("\n---")
print("v835: %d/%d PASS" % (sum(results), len(results)))
import shutil  # noqa: E402
shutil.rmtree(TMP, ignore_errors=True)
sys.exit(0 if all(results) else 1)
