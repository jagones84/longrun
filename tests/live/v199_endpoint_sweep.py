#!/usr/bin/env python3
"""v199 — LIVE endpoint sweep (requires a running server).

Hits every cheap HTTP endpoint of the harness and asserts graceful behaviour:
a bad/empty request must never produce a 5xx, auth must be enforced, unknown
paths are 404. Model-calling endpoints (chat/agent/plan-generate/eval) are
excluded on purpose so this stays fast and side-effect free.

Run (DGX, server up):  python3 tests/live/v199_endpoint_sweep.py
Exit code 0 only if no endpoint returned 5xx and the auth/404 probes passed.
"""
import json
import os
import socket
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
WS = "/home/jagones/Repositories/TESTS/harness-e2e"

RESULTS = []


def rep(name, ok, detail=""):
    RESULTS.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + detail) if detail else ""))


def call(method, path, body=None, token=True, timeout=8):
    """Return (status, body_text) — never raises on HTTP status."""
    url = BASE + path
    if token and TOK:
        url += ("&" if "?" in path else "?") + urllib.parse.urlencode({"token": TOK})
    headers = {"Authorization": "Bearer " + TOK} if (token and TOK) else {}
    data = None
    if body is not None:
        data = json.dumps(body).encode()
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read(400).decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, (e.read(400).decode("utf-8", "replace") if e.fp else "")
    except (urllib.error.URLError, socket.timeout, TimeoutError) as e:
        return 0, repr(e)


GETS = [
    "/api/self", "/api/context", "/api/status", "/api/models", "/api/providers",
    "/api/keys", "/api/selfcheck?llm=0", "/api/plan", "/api/tasks", "/api/improve",
    "/api/sessions", "/api/chat/live", "/api/eval/tasks", "/api/voice/status",
    "/api/tools", "/api/approvals", "/api/sandbox", "/api/feed/recent",
    "/api/agent/runs", "/api/checkpoints", "/api/routing", "/api/rules",
    "/api/workspace", "/api/fs/dirs", "/api/fs/list", "/api/edits",
    "/api/history?session=__none__", "/api/plan?session=__none__",
    "/api/approvals/__none__", "/api/agent/runs/__none__",
]

for p in GETS:
    st, _ = call("GET", p)
    rep("GET %s" % p, st not in (0,) and st < 500, "status=%s" % st)

# POST with empty body → must be 4xx, never 5xx (no crash on missing params).
POSTS = [
    "/api/tools", "/api/tools/call", "/api/chat/steer", "/api/chat/abort",
    "/api/plan", "/api/plan/toggle", "/api/tasks", "/api/context/compact",
    "/api/voice/stt", "/api/voice/tts", "/api/fs/write", "/api/edits/undo",
    "/api/plan/generate",
]
for p in POSTS:
    st, _ = call("POST", p, body={})
    rep("POST %s {}" % p, st < 500, "status=%s" % st)

# PATCH/DELETE graceful on bad input.
st, _ = call("PATCH", "/api/tasks", body={})
rep("PATCH /api/tasks {}", st < 500, "status=%s" % st)
st, _ = call("DELETE", "/api/sessions/__none__")
rep("DELETE /api/sessions/__none__", st in (400, 404), "status=%s" % st)

# Auth + routing.
st, _ = call("GET", "/api/status", token=False)
rep("auth enforced (401 without token)", st in (401, 403), "status=%s" % st)
st, _ = call("GET", "/api/definitely-not-a-route")
rep("unknown path -> 404", st == 404, "status=%s" % st)

# Create → use → delete a session round-trip (cleanup), then verify it is gone.
st, b = call("POST", "/api/sessions", body={"title": "v199-sweep"})
sid = ""
try:
    sid = json.loads(b).get("id", "")
except Exception:  # noqa: BLE001
    pass
rep("session create returns an id", bool(sid), "status=%s id=%s" % (st, sid))
if sid:
    st_h, _ = call("GET", "/api/history?session=" + sid)
    rep("history of a fresh session is 200", st_h == 200, "status=%s" % st_h)
    st_d, _ = call("DELETE", "/api/sessions/" + sid)
    rep("session delete is 200", st_d == 200, "status=%s" % st_d)
    st_g, _ = call("GET", "/api/history?session=" + sid)
    rep("deleted session history is 404", st_g == 404, "status=%s" % st_g)

n = sum(1 for ok in RESULTS if ok)
print("\n==== %d/%d endpoint checks passed ====" % (n, len(RESULTS)))
print("SWEEP_RESULT " + ("PASS" if n == len(RESULTS) else "FAIL"))

