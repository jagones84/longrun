#!/usr/bin/env python3
"""v208 — LIVE chaos / crash-resistance (requires a running server).

Adversarial HTTP abuse: malformed JSON, a 2 MB body, unknown paths/methods,
raw-socket garbage, a 100 KB header, an abrupt mid-request close, and a 40-thread
mixed burst. The system under test is the RUNNING harness. Success criterion:
NEVER a 5xx and the server is still healthy afterwards ("è rimasto in piedi").

Run (DGX, server up):  python3 tests/live/v208_chaos_http.py
"""
import json
import os
import socket
import tempfile
import threading
import urllib.error
import urllib.parse
import urllib.request

ENV = os.path.expanduser("~/.longrun/config/env")
TOK = ""
try:
    for line in open(ENV):
        line = line.strip()
        if line.startswith("LONGRUN_TOKEN="):
            TOK = line.split("=", 1)[1].strip().strip('"').strip("'")
except OSError:
    pass
BASE = os.environ.get("LONGRUN_BASE", "http://127.0.0.1:8790")
HOST, PORT = "127.0.0.1", int(os.environ.get("LONGRUN_PORT", "8790"))
RESULTS = []


def rep(name, ok, detail=""):
    RESULTS.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + detail) if detail else ""))


def call(method, path, raw=None, token=True, timeout=10):
    url = BASE + path
    if token and TOK:
        url += ("&" if "?" in path else "?") + urllib.parse.urlencode({"token": TOK})
    headers = {"Authorization": "Bearer " + TOK} if (token and TOK) else {}
    if raw is not None:
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=raw, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read(200).decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, (e.read(200).decode("utf-8", "replace") if e.fp else "")
    except OSError as e:
        # URLError, ConnectionResetError, BrokenPipeError, socket.timeout — the
        # server closing a garbage request is expected; never crash the worker.
        return 0, repr(e)[:120]


def health():
    s, _ = call("GET", "/api/status")
    return s


def raw_send(payload, read=True):
    try:
        s = socket.create_connection((HOST, PORT), timeout=5)
        s.sendall(payload)
        if read:
            try:
                s.recv(200)
            except OSError:
                pass
        s.close()
        return True
    except OSError:
        return False


# ---- C1: baseline ----
rep("C1 baseline health 200", health() == 200, "status=%s" % health())

# ---- C2: malformed JSON body ----
st, _ = call("POST", "/api/chat", raw=b"{ this is not json")
rep("C2 malformed JSON -> no 5xx", st not in (500, 502, 503, 504), "status=%s" % st)

# ---- C3: oversized body (2 MB) ----
# JAG-239: probe with /api/context/preview — it processes the message but does
# NOT persist a session. The old /api/chat call created a real 2 MB junk session
# (titled "session xxxxx", showing 195% context forever) AND invoked the model,
# polluting the live WebUI on every run. A chaos test must not write to the store.
st, _ = call("POST", "/api/context/preview",
             raw=json.dumps({"message": "x" * 2_000_000}).encode(), timeout=20)
rep("C3 2MB body -> no 5xx", st not in (500, 502, 503, 504), "status=%s" % st)

# ---- C4: unknown path ----
st, _ = call("GET", "/api/definitely-not-a-real-endpoint")
rep("C4 unknown path -> 404", st == 404, "status=%s" % st)

# ---- C5: bad method ----
st, _ = call("PUT", "/api/status", raw=b"{}")
rep("C5 bad method -> no 5xx", st not in (500, 502, 503, 504), "status=%s" % st)

# ---- C6: raw garbage ----
raw_send(b"NOT A VALID HTTP REQUEST\r\n\r\n")
rep("C6 raw garbage -> survives", health() == 200, "health=%s" % health())

# ---- C7: huge header (100 KB) ----
raw_send(b"GET /api/status HTTP/1.1\r\nHost: x\r\nX-Big: " + b"A" * 100000 + b"\r\n\r\n")
rep("C7 100KB header -> survives", health() == 200, "health=%s" % health())

# ---- C8: abrupt mid-request close ----
try:
    s = socket.create_connection((HOST, PORT), timeout=5)
    s.sendall(b"POST /api/chat HTTP/1.1\r\nHost: x\r\nContent-Length: 1000000\r\n\r\n{")
    s.close()
    ok8 = True
except OSError:
    ok8 = False
rep("C8 abrupt mid-request close -> survives", ok8 and health() == 200, "health=%s" % health())

# ---- C9: 40-thread mixed burst ----
codes = []
lock = threading.Lock()


def worker(i):
    if i % 2 == 0:
        c, _ = call("GET", "/api/status")
    else:
        c, _ = call("POST", "/api/chat", raw=b"@@garbage@@")
    with lock:
        codes.append(c)


ths = [threading.Thread(target=worker, args=(i,)) for i in range(40)]
[t.start() for t in ths]
[t.join() for t in ths]
bad = [c for c in codes if c in (500, 502, 503, 504)]
rep("C9 40-thread mixed burst -> no 5xx", not bad, "codes=%s" % sorted(set(codes)))

# ---- C10: still standing ----
rep("C10 server STILL healthy after the chaos", health() == 200, "health=%s" % health())

# ---- C11: malformed query params -> clean response, never a reset/5xx ----
# JAG-229: `int(qs.get("since", 0))` used to raise ValueError on junk and drop
# the connection (status 0). Every numeric param must now fall back safely.
malformed = [
    ("GET", "/api/runs?limit=abc"),
    ("GET", "/api/runs?limit="),
    ("GET", "/api/feed?since=abc"),
    ("GET", "/api/context?session=..&model=abc"),
]
bad11 = []
for method, path in malformed:
    st, _ = call(method, path, timeout=5)
    if st == 0 or st in (500, 502, 503, 504):
        bad11.append("%s %s -> %s" % (method, path, st))
rep("C11 malformed query params -> no reset/5xx", not bad11, "; ".join(bad11))
rep("C11b server healthy after malformed query",
    health() == 200, "health=%s" % health())

# ---- C12: session-id path traversal must never read outside the store ----
# JAG-230: `/api/history?session=../../x` used to build a path from the raw id.
st12, body12 = call("GET", "/api/history?session=" + urllib.parse.quote("../../../etc/passwd"))
leaked = ("root:" in body12) or ("/bin/" in body12)
rep("C12 history traversal -> no leak", st12 == 404 and not leaked,
    "status=%s leaked=%s" % (st12, leaked))
st12b, _ = call("GET", "/api/sessions/" + urllib.parse.quote("../../etc") + "/graph")
rep("C12b graph traversal -> 200 empty (no crash)", st12b in (200, 404),
    "status=%s" % st12b)
rep("C12c server healthy after traversal attempts", health() == 200,
    "health=%s" % health())

# ---- C13: wire-type abuse -> clean response, never a reset/5xx ----
# JAG-231: a non-OBJECT JSON body (`[1,2]`) and non-int numeric fields crashed
# handlers with unhandled TypeError/ValueError, dropping the connection.
wire = [
    ("POST", "/api/chat", b"[1,2,3]"),
    ("POST", "/api/improve", b'{"id":123,"decision":"approve"}'),
    ("POST", "/api/chat/steer", b'"a string"'),
    ("GET", "/api/checkpoints?limit=abc", None),
    ("GET", "/api/approvals?limit=abc", None),
    ("GET", "/api/feed/recent?limit=abc", None),
    ("GET", "/api/blackboard?limit=abc", None),
]
bad13 = []
for method, path, raw in wire:
    st, _ = call(method, path, raw=raw, timeout=5)
    if st == 0 or st in (500, 502, 503, 504):
        bad13.append("%s %s -> %s" % (method, path, st))
rep("C13 wire-type abuse -> no reset/5xx", not bad13, "; ".join(bad13))
rep("C13b server healthy after wire-type abuse", health() == 200,
    "health=%s" % health())

# ---- C14: /api/fs/raw must not serve a script container inline ----
# JAG-232: an .svg (image/svg+xml) executed its embedded JS at the origin.
try:
    d = tempfile.mkdtemp(dir=os.path.expanduser("~"), prefix="sf-c14-")
    svg = os.path.join(d, "x.svg")
    png = os.path.join(d, "x.png")
    with open(svg, "wb") as f:
        f.write(b'<svg xmlns="http://www.w3.org/2000/svg" onload="x=1"/>')
    with open(png, "wb") as f:
        f.write(b"\x89PNG\r\n\x1a\n" + b"0" * 16)
    st_svg, _ = call("GET", "/api/fs/raw?path=" + urllib.parse.quote(svg))
    st_png, _ = call("GET", "/api/fs/raw?path=" + urllib.parse.quote(png))
    rep("C14 svg preview refused (415)", st_svg == 415, "status=%s" % st_svg)
    rep("C14b raster preview allowed (200)", st_png == 200, "status=%s" % st_png)
    os.remove(svg)
    os.remove(png)
    os.rmdir(d)
except OSError as e:
    rep("C14 svg preview refused (415)", False, repr(e)[:80])
rep("C14c server healthy after preview probes", health() == 200,
    "health=%s" % health())

# ---- C15: wire-type payloads that used to DROP the connection ----
# JAG-233..236: an unhandled exception (None.encode / None[:20] / unhashable key
# / int.rstrip) closed the socket with NO response. They must now answer.
crashers = [
    ("GET", "/api/subagent?id=abc", None),
    ("GET", "/api/subagent?id=" + urllib.parse.quote("../../x"), None),
    ("POST", "/api/agent/control", b'{"run_id":[1],"action":1}'),
    ("POST", "/api/acp/connect", b'{"name":123,"url":999,"token":{}}'),
]
bad15 = []
for method, path, raw in crashers:
    st, _ = call(method, path, raw=raw, timeout=8)
    if st == 0 or st in (500, 502, 503, 504):
        bad15.append("%s %s -> %s" % (method, path, st))
rep("C15 wire-crash payloads -> no reset/5xx", not bad15, "; ".join(bad15))
rep("C15b server healthy after wire-crash probes", health() == 200,
    "health=%s" % health())

ok = sum(RESULTS)
print("\nv208: %d/%d PASS" % (ok, len(RESULTS)))
raise SystemExit(0 if ok == len(RESULTS) else 1)

