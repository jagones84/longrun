#!/usr/bin/env python3
"""v202 — LIVE concurrency: two STREAMING turns on ONE session at the same time.

Same frontier race as v200 but on /api/chat/stream (SSE). Confirms whether the
streaming path also serialises its read-modify-write (the blocking path does).

Run (DGX, server up):  python3 tests/live/v202_concurrent_stream.py
"""
import json
import os
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

ENV = os.path.expanduser("~/.longrun/config/env")
TOK = ""
for line in open(ENV):
    line = line.strip()
    if line.startswith("LONGRUN_TOKEN="):
        TOK = line.split("=", 1)[1].strip().strip('"').strip("'")
BASE = "http://127.0.0.1:8790"
WS = "/home/jagones/Repositories/TESTS/harness-e2e"

RESULTS = []


def rep(name, ok, detail=""):
    RESULTS.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + detail) if detail else ""))


def GET(path, **qs):
    qs["token"] = TOK
    req = urllib.request.Request(BASE + path + "?" + urllib.parse.urlencode(qs),
                                 headers={"Authorization": "Bearer " + TOK})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode())


sess = GET("/api/sessions/new", workspace=WS)
sid = sess.get("id")
print("session=%s" % sid)

st = {}


def stream(tag, msg):
    try:
        req = urllib.request.Request(
            BASE + "/api/chat/stream?token=" + TOK,
            data=json.dumps({"session": sid, "message": msg}).encode(),
            headers={"Content-Type": "application/json", "Authorization": "Bearer " + TOK},
            method="POST")
        events = 0
        with urllib.request.urlopen(req, timeout=180) as r:
            for _ln in r:
                events += 1
        st[tag] = ("closed", events)
    except Exception as e:  # noqa: BLE001
        st[tag] = ("error", repr(e))


t1 = threading.Thread(target=stream, args=("A", "Reply with exactly: SA"))
t2 = threading.Thread(target=stream, args=("B", "Reply with exactly: SB"))
t0 = time.time()
t1.start(); t2.start()
t1.join(timeout=200); t2.join(timeout=200)
rep("A1 both streams closed (no hang)", len(st) == 2 and all(v[0] == "closed" for v in st.values()),
    "elapsed=%.1fs st=%s" % (time.time() - t0, st))

hist = GET("/api/history", session=sid)
roles = [m.get("role") for m in hist.get("messages", [])]
users = roles.count("user")
asst = roles.count("assistant")
rep("B1 both streaming turns persisted (no lost update)", users >= 2 and asst >= 2,
    "roles=%s" % roles)
rep("B2 no orphan user at the tail", bool(roles) and roles[-1] == "assistant", "tail=%s" % roles[-2:])

live = GET("/api/chat/live").get("active") or []
rep("C1 session not left 'active'", sid not in live, "active=%s" % live)

try:
    urllib.request.urlopen(urllib.request.Request(
        BASE + "/api/sessions/" + sid, method="DELETE",
        headers={"Authorization": "Bearer " + TOK}), timeout=20)
except Exception:  # noqa: BLE001
    pass

n = sum(1 for ok in RESULTS if ok)
print("\n==== %d/%d concurrent-stream checks passed ====" % (n, len(RESULTS)))
print("STREAM_RESULT " + ("PASS" if n == len(RESULTS) else "FAIL"))

