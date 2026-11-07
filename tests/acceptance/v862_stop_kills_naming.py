#!/usr/bin/env python3
"""v862 — Stop kills the naming model call, and naming no longer interleaves.

Live report (2026-11-07): the operator clicked compact AND the 🏷 label of the
Free groups at the same time, then queued a chat message, then pressed Stop — and
the local DGX model kept generating. Causes found in the code:

  * `autoname_async` started `autoname_untitled(sess, model=model)` with NO
    cancel, and the loop kept going: the cancelled call returned "", the
    copy-retry fired, and it paid up to 20 rounds;
  * naming took no turn lock, so a 🏷 during a turn/compaction put two
    generations on one session.

  A) a cancelled naming run stops immediately (the model is never called);
  B) `autoname_async` passes a Stop-aware cancel and holds the turn lock;
  C) the loop checks the flag before each round and after each call.

Deterministic: temp dirs, no network, no model.
"""
import atexit
import os
import shutil
import sys
import tempfile
import time

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
tmp = tempfile.mkdtemp(prefix="sf-862-")
atexit.register(lambda: shutil.rmtree(tmp, ignore_errors=True))
os.environ["LONGRUN_CONFIG_DIR"] = os.path.join(tmp, "cfg")
os.environ["LONGRUN_SESSIONS_DIR"] = os.path.join(tmp, "sessions")
os.environ["LONGRUN_DB"] = os.path.join(tmp, "events.db")
os.environ["LONGRUN_THREADS_DIR"] = os.path.join(tmp, "threads")
os.environ["LONGRUN_GRAPH_DIR"] = tmp
os.environ["LONGRUN_RUNS_DIR"] = os.path.join(tmp, "runs")
os.environ["LONGRUN_WORKSPACES_ROOT"] = os.path.join(tmp, "ws")
for d in ("cfg", "sessions", "threads", "runs", "ws"):
    os.makedirs(os.path.join(tmp, d), exist_ok=True)
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.core import server          # noqa: E402 — breaks the import cycle
from longrun.core import httpapi as H    # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""))


# ---- A: a cancelled run never calls the model ------------------------------
calls = {"n": 0}


def fake_stream(*a, **kw):
    calls["n"] += 1
    return '[]', "", "mock"


_orig = H.stream_with_fallback
H.stream_with_fallback = fake_stream
try:
    t0 = time.time()
    res = H.autoname_untitled({"id": "v862-a", "messages": []}, model="mock",
                              cancel=lambda: True)
    dt = time.time() - t0
finally:
    H.stream_with_fallback = _orig

check("A1 a cancelled naming run pays for NO model call", calls["n"] == 0, calls)
check("A2 it returns at once instead of looping the rounds",
      res.get("rounds") == 0 and res.get("titled") == 0 and dt < 2.0,
      (res, round(dt, 3)))

src = open(os.path.join(REPO, "src", "longrun", "core", "httpapi.py"), encoding="utf-8").read()
body = src.split("def autoname_untitled", 1)[1].split("def autoname_async", 1)[0]
check("C1 the loop checks Stop BEFORE every round",
      "while rounds < int(rounds_max):" in body
      and body.index("if cancel is not None and cancel():")
      < body.index("groups = th.untitled_free(sid)"), "loop head")
check("C2 it checks Stop again right after the model call",
      body.count("if cancel is not None and cancel():") >= 2,
      body.count("if cancel is not None and cancel():"))

async_body = src.split("def autoname_async", 1)[1].split("def compact_session", 1)[0]
check("B1 the background naming run passes a Stop-aware cancel",
      "cancel=lambda: _is_aborted(sid)" in async_body)
check("B2 it holds the session's turn lock (no two generations on one session)",
      "_turn_lock(sid)" in async_body)

print("---")
passed = sum(results)
print("%d/%d PASS" % (passed, len(results)))
sys.exit(0 if passed == len(results) else 1)
