#!/usr/bin/env python3
"""v213 — LIVE smoke for the deployed Command Deck (requires a running server).

Verifies the ACTUAL deployed app, not the source: the public /console shell is
served (and is the same single-file app, with the interactive Command Console),
its aliases work, the data endpoints underneath stay auth-gated, and the SSE feed
really speaks text/event-stream. No model turn, bounded, server left healthy.

Run (DGX, server up):  python3 tests/live/v213_deck_live.py
"""
import os
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
RESULTS = []


def rep(name, ok, detail=""):
    RESULTS.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + detail) if detail else ""))


def get(path, token=False, timeout=8, read=4000):
    url = BASE + path
    if token and TOK:
        url += ("&" if "?" in path else "?") + urllib.parse.urlencode({"token": TOK})
    headers = {"Authorization": "Bearer " + TOK} if (token and TOK) else {}
    req = urllib.request.Request(url, headers=headers, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            ctype = r.headers.get("Content-Type", "")
            body = r.read(read).decode("utf-8", "replace") if read else ""
            return r.status, ctype, body
    except urllib.error.HTTPError as e:
        return e.code, e.headers.get("Content-Type", "") if e.headers else "", ""
    except OSError as e:  # noqa: BLE001
        return 0, "", repr(e)[:120]


# ---- the public shell ----
st, ct, body = get("/console", read=200000)
rep("A1 GET /console -> 200", st == 200, "status=%d" % st)
rep("A2 it is HTML", "text/html" in ct, ct)
rep("A3 it is the deck", "ORBITAL COMMAND DECK" in body, "")
rep("A4 it carries the interactive Command Console",
    'id="cmdInput"' in body and 'id="cmdSend"' in body and 'id="cmdOut"' in body, "")
rep("A5 it wires the live stream", "/api/chat/stream" in body and "EventSource" in body, "")

# ---- aliases ----
for alias in ("/console.html", "/deck"):
    st2, _, b2 = get(alias)
    rep("A6 alias %s -> 200 + deck" % alias, st2 == 200 and "ORBITAL COMMAND DECK" in b2,
        "status=%d" % st2)

# ---- data underneath stays auth-gated ----
st3, _, _ = get("/api/status")
rep("B1 /api/status WITHOUT token -> 401", st3 == 401, "status=%d" % st3)
st4, _, b4 = get("/api/status", token=True)
rep("B2 /api/status WITH token -> 200 JSON", st4 == 200 and '"version"' in b4,
    "status=%d" % st4)

# ---- the feed really is SSE ----
st5, ct5, _ = get("/api/feed", token=True, read=0, timeout=6)
rep("B3 /api/feed is text/event-stream", st5 == 200 and "text/event-stream" in ct5,
    "status=%d ct=%s" % (st5, ct5))

# ---- server still healthy ----
st6, _, _ = get("/api/status", token=True)
rep("C1 server healthy at the end", st6 == 200, "status=%d" % st6)

ok = sum(RESULTS)
print("\nv213: %d/%d PASS" % (ok, len(RESULTS)))
raise SystemExit(0 if ok == len(RESULTS) else 1)

