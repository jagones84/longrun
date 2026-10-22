#!/usr/bin/env python3
"""v216 — LIVE: the fallback planner must NOT hold the chat turn open (JAG-216).

Regression for the measured anomaly: a one-line reply streamed in ~1.4s but the
turn stayed "running" for ~20s+ because `start_run_graph` (the fallback planner)
ran synchronously between the reply and `done`. Now the planner runs in a
background daemon thread and publishes its nodes on the FEED, so `done` fires as
soon as the reply is complete, and the graph still appears a moment later.

Requires a running server and a WARM model (a cold model load would inflate the
turn time for reasons unrelated to this fix). Live-only, NOT in the gate.

Run (DGX, server up):  python3 tests/live/v216_planner_async.py
"""
import json
import os
import time
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
H = {"Authorization": "Bearer " + TOK}
RESULTS = []


def rep(name, ok, detail=""):
    RESULTS.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + detail) if detail else ""))


def graph(sid):
    req = urllib.request.Request(BASE + "/api/sessions/" + sid + "/graph", headers=H)
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read().decode() or "{}")


sid = "v216-" + os.urandom(4).hex()
msg = "rispondi in una sola riga: ok"
url = BASE + "/api/chat/stream?message=" + urllib.parse.quote(msg) + "&session=" + sid

t0 = time.time()
turn_end = None
graph_events_in_turn = 0
req = urllib.request.Request(url, headers=H)
with urllib.request.urlopen(req, timeout=180) as resp:
    ev = None
    for raw in resp:
        line = raw.decode("utf-8", "replace").rstrip("\n")
        if line.startswith("event:"):
            ev = line[6:].strip()
            if ev == "graph.node.added":
                graph_events_in_turn += 1
            if ev == "done":
                turn_end = time.time() - t0

rep("A1 the turn reached `done`", turn_end is not None,
    "turn_end=%s" % (round(turn_end, 2) if turn_end else None))
rep("A2 the turn closed FAST (planner no longer blocks `done`)",
    turn_end is not None and turn_end < 20.0, "%.2fs" % (turn_end or -1))
rep("A3 graph events are NOT on the turn SSE anymore (moved to the feed)",
    graph_events_in_turn == 0, "count=%d" % graph_events_in_turn)

graph_at = None
for _ in range(90):
    g = graph(sid)
    if len(g.get("nodes", [])) >= 1:
        graph_at = time.time() - t0
        break
    time.sleep(1)
rep("B1 the fallback planner still created the graph (async)",
    graph_at is not None, "after %s" % (round(graph_at, 2) if graph_at else "never"))
g = graph(sid)
nodes = g.get("nodes", [])
rep("B2 the graph carries >=1 node", len(nodes) >= 1, "n=%d" % len(nodes))

try:  # keep the live data dir clean
    dr = urllib.request.Request(BASE + "/api/sessions/" + sid, headers=H, method="DELETE")
    urllib.request.urlopen(dr, timeout=8).read()
except Exception:  # noqa: BLE001
    pass

print("---")
ok = sum(1 for r in RESULTS if r)
print("%d/%d PASS" % (ok, len(RESULTS)))
raise SystemExit(0 if ok == len(RESULTS) else 1)

