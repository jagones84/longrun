#!/usr/bin/env python3
"""v442 — Stop really stops: the abort is cleared at TURN START, and Stop is a panic button.

The reported bug: pressing ■ did not stop the running work. Root cause — `chat_once`
cleared the abort flag AFTER the planner/graph model calls had already run, so a Stop
pressed during that window (the UI shows the turn as running from the first moment) was
silently wiped and the whole turn ran to completion (measured live: abort at t=8s, turn
finished at t=87s with the full answer). Second gap: Stop aborted only the session on
screen, so parallel agents kept the (single-slot) local router busy and "stop" looked
like a no-op.

Deterministic, no live server.
"""
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="sf-v442-")
os.environ["LONGRUN_CONFIG_DIR"] = os.path.join(TMP, "cfg")
os.environ["LONGRUN_SESSIONS_DIR"] = os.path.join(TMP, "sessions")
os.environ["LONGRUN_GRAPH_DIR"] = os.path.join(TMP, "graphs")
os.environ["LONGRUN_THREADS_DIR"] = os.path.join(TMP, "threads")
os.environ["LONGRUN_DB"] = os.path.join(TMP, "events.db")
for d in ("cfg", "sessions", "graphs", "threads"):
    os.makedirs(os.path.join(TMP, d), exist_ok=True)
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.util import steering   # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""))


def _read(path):
    with open(os.path.join(REPO, path), "r", encoding="utf-8") as f:
        return f.read()


def _fn(src, header):
    """The body of a top-level `def header` up to the next top-level `def`/`class`."""
    i = src.index(header)
    rest = src[i:]
    out = [rest.splitlines()[0]]
    for ln in rest.splitlines()[1:]:
        if ln[:1] not in (" ", "\t", "") and (ln.startswith("def ") or ln.startswith("class ")
                                              or ln.startswith("@")):
            break
        out.append(ln)
    return "\n".join(out)


AG = _read("src/longrun/agent/agent.py")
HTTP = _read("src/longrun/core/httpapi.py")
V02 = _read("src/longrun/core/api_v02.py")
IDX = _read("webui/index.html")

# ---- 1. the abort primitive ---------------------------------------------------
steering.push_abort("s1")
check("1a push_abort flags the session", steering._is_aborted("s1") is True)
steering.clear_abort("s1")
check("1b clear_abort drops the flag", steering._is_aborted("s1") is False)

# ---- 2. the clear moved to TURN START (not after the planner) -----------------
co = _fn(AG, "def chat_once(")
check("2a chat_once no longer clears a pending abort (it ran after the planner)",
      "clear_abort(" not in co, [l for l in co.splitlines() if "clear_abort" in l][:1])
check("2b the stream turn clears the abort at turn start",
      'clear_abort(sess["id"])' in HTTP)
check("2c the sync /api/chat turn clears it at turn start too",
      HTTP.count('clear_abort(sess["id"])') >= 2, HTTP.count('clear_abort(sess["id"])'))
check("2d the in-process MCP chat clears it at turn start",
      'clear_abort(sess["id"])' in V02)
check("2e the planner call is abortable (a Stop kills it, not waits for it)",
      'cancel=(lambda: _is_aborted(sess["id"]))' in HTTP)

# ---- 3. Stop = panic button (abort EVERY running turn) ------------------------
check("3a /api/chat/abort supports all=true over the ACTIVE registry",
      'if body.get("all") or qs.get("all"):' in HTTP and "for _s in sids:" in HTTP)
check("3b it aborts every registered session id",
      "sids = list(_ACTIVE_CHAT.keys())" in HTTP)
check("3c the UI Stop aborts every running turn",
      'api("POST", "/api/chat/abort", { all: true })' in IDX)
check("3d the composer button routes to Stop while busy",
      "function sendOrStop() { if (composerBusy()) stopRun(); else send(); }" in IDX)
check("3e Stop reports the number of turns it hit",
      "running turn(s)" in IDX)
check("3f the Stop icon resets from server turn state, not a lingering EventSource",
      "function composerBusy() { return !!(sessionId && runningSessions[sessionId]); }" in IDX)
_feed_done = IDX.split('es.addEventListener("chat.done", e => {', 1)[1].split(
    'es.addEventListener("graph.node.added"', 1)[0]
check("3g server turn completion clears Stop state even if stream cleanup lags",
      "setRunning(d.session, false)" in _feed_done)

print("---")
okc = sum(results)
print("\nv442: %d/%d PASS" % (okc, len(results)))
sys.exit(0 if okc == len(results) else 1)
