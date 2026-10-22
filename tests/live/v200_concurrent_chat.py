#!/usr/bin/env python3
"""v200 — LIVE concurrency: two chat turns on ONE session at the same time.

Frontier race: two overlapping turns on the same session must not corrupt the
transcript (invalid JSON, orphan user turn, lost reply) or crash. Uses the cheap
one-shot /api/chat (blocking JSON) in two threads with a trivial prompt.

Run (DGX, server up):  python3 tests/live/v200_concurrent_chat.py
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


def POST(path, body, timeout=120):
    req = urllib.request.Request(BASE + path, data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json",
                                          "Authorization": "Bearer " + TOK}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, json.loads(r.read().decode() or "{}")
    except urllib.error.HTTPError as e:
        return e.code, {"error": e.read(300).decode("utf-8", "replace")}


sess = GET("/api/sessions/new", workspace=WS)
sid = sess.get("id")
print("session=%s" % sid)

out = {}


def turn(tag, msg):
    try:
        st, body = POST("/api/chat", {"session": sid, "message": msg})
        out[tag] = (st, body)
    except Exception as e:  # noqa: BLE001
        out[tag] = (0, {"error": repr(e)})


t1 = threading.Thread(target=turn, args=("A", "Reply with exactly: OKA"))
t2 = threading.Thread(target=turn, args=("B", "Reply with exactly: OKB"))
t0 = time.time()
t1.start(); t2.start()
t1.join(timeout=180); t2.join(timeout=180)
rep("A1 both concurrent turns returned (no hang)", len(out) == 2,
    "elapsed=%.1fs keys=%s" % (time.time() - t0, list(out)))
for tag in ("A", "B"):
    st, body = out.get(tag, (0, {}))
    rep("A2 turn %s settled without 5xx" % tag, st not in (0,) and st < 500,
        "status=%s body=%s" % (st, json.dumps(body)[:180]))

# The transcript must stay consistent: valid JSON, and every user turn answered.
try:
    hist = GET("/api/history", session=sid)
    msgs = hist.get("messages", [])
    rep("B1 history is valid JSON", True, "messages=%d" % len(msgs))
except Exception as e:  # noqa: BLE001
    msgs = []
    rep("B1 history is valid JSON", False, repr(e))
roles = [m.get("role") for m in msgs]
users = roles.count("user")
asst = roles.count("assistant")
rep("B2 both concurrent turns persisted (no lost update)", users >= 2 and asst >= 2,
    "roles=%s" % roles)
rep("B3 no orphan user at the tail", bool(roles) and roles[-1] == "assistant", "tail=%s" % roles[-2:])

live = GET("/api/chat/live").get("active") or []
rep("C1 session not left 'active' after both turns", sid not in live, "active=%s" % live)

try:
    urllib.request.urlopen(urllib.request.Request(
        BASE + "/api/sessions/" + sid, method="DELETE",
        headers={"Authorization": "Bearer " + TOK}), timeout=20)
except Exception:  # noqa: BLE001
    pass

n = sum(1 for ok in RESULTS if ok)
print("\n==== %d/%d concurrent-chat checks passed ====" % (n, len(RESULTS)))
print("CONCURRENT_RESULT " + ("PASS" if n == len(RESULTS) else "FAIL"))

