#!/usr/bin/env python3
"""v952 — a session deleted mid-turn must not turn the turn's own exit into a traceback.

The streaming worker acquires `_turn_lock(sid)` and, in its `finally`, released it
through a FRESH `_turn_lock(sid)` lookup. `delete_session` pops the per-session lock
out of the registry (`stores._forget_session_runtime`), so the fresh lookup built a
NEW, un-acquired lock and `release()` raised `RuntimeError: cannot release un-acquired
lock` inside the worker's `finally`. The turn was over, so nothing was lost — but the
thread died with a traceback nobody asked for and the release it promised never ran.

The fix binds the lock object at acquire and releases THAT object.

Deterministic: temp stores, no server, no model, no network (the turn's model call is
stubbed and parks until the delete has happened).
Run: python3 tests/acceptance/v952_turn_lock_after_delete.py
"""

import os
import sys
import tempfile
import threading

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="sf-v952-")
os.environ["LONGRUN_DATA_DIR"] = TMP
for _k in ("SESSIONS_DIR", "EDITS_DIR", "RUNS_DIR", "GRAPH_DIR", "ROLES_DIR",
           "CONFIG_DIR", "THREADS_DIR", "COSTS_DIR", "DATA_DIR"):
    os.environ["LONGRUN_" + _k] = os.path.join(TMP, _k)
    os.makedirs(os.path.join(TMP, _k), exist_ok=True)
os.environ["LONGRUN_DB"] = os.path.join(TMP, "events.db")
os.environ["LONGRUN_JOBS_FILE"] = os.path.join(TMP, "jobs.json")
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.interop import mcp_client  # noqa: E402

# never start MCP servers from a test
_offline = mcp_client.MCPClientManager()
_offline.start_all = lambda: None
mcp_client.get_manager = lambda: _offline

from longrun.core import server  # noqa: E402,F401  (breaks the agent<->server cycle)
from longrun.core import httpapi as H  # noqa: E402
from longrun.memory import stores as S  # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""))


# ---- the defect's own setup ------------------------------------------------
SID = "v952-turn"
S.save_session({"id": SID, "title": "v952", "messages": []})
sess = S.load_session(SID)

in_once = threading.Event()     # the turn has entered its model call
finish = threading.Event()      # let the turn finish
crashes = []


def _excepthook(args):
    crashes.append("%s: %r" % (getattr(args.thread, "name", "?"), args.exc_value))


_hook_was = threading.excepthook
threading.excepthook = _excepthook


def _fake_chat_once(*_a, **_kw):
    in_once.set()
    finish.wait(10)
    return None


H.chat_once = _fake_chat_once

frames = []


def _consume():
    try:
        for chunk in H.chat_stream_gen(sess, "hello", "v952-model"):
            frames.append(chunk)
    except Exception as e:  # noqa: BLE001 — reported below, not swallowed
        crashes.append("pump: %r" % (e,))


before = set(threading.enumerate())
pump = threading.Thread(target=_consume, daemon=True, name="v952-pump")
pump.start()

check("A1 the turn reaches its model call", in_once.wait(10))

# ---- the real door: delete the session while its OWN turn is running -------
res = H.delete_session(SID)
check("A2 the delete door succeeded while the turn was live",
      res.get("ok") is True and res.get("deleted") == SID, res)
check("A3 the per-session lock is gone from the registry (the situation)",
      S._TURN_LOCKS.get(SID) is None)

finish.set()
pump.join(10)
check("A4 the turn's stream ended after the delete", not pump.is_alive())

# the worker outlives the last frame: `q.put(None)` comes BEFORE turn_end/release
for _t in set(threading.enumerate()) - before:
    _t.join(10)
threading.excepthook = _hook_was

# ---- the contract ----------------------------------------------------------
check("B1 the worker thread died with NO unhandled exception",
      not crashes and not any("release" in c.lower() for c in crashes), crashes)
check("B2 the turn's release did run (it is not a swallowed error)",
      not any("cannot release" in c.lower() for c in crashes), crashes)

# ---- the reason the release exists ----------------------------------------
_lk = S._turn_lock(SID)
check("C1 a later turn on that sid acquires a fresh lock without blocking",
      _lk.acquire(blocking=False) is True)
_lk.release()
check("C2 the registry holds exactly one lock for the sid again",
      S._TURN_LOCKS.get(SID) is _lk)
check("C3 the deleted session was not resurrected by the turn's own exits",
      S.load_session(SID) is None)

# ---- D. a raising turn_end must not wedge the session ----------------------
# The same release, one line further: `turn_end` publishes to the event store, and a
# full/locked store raises (the RH-12 condition). If the release depended on it, the
# lock would stay held by a DEAD worker and every later turn would block forever.
SID2 = "v952-end"
S.save_session({"id": SID2, "title": SID2, "messages": []})
sess2 = S.load_session(SID2)
in_once2 = threading.Event()
finish2 = threading.Event()
_orig_chat_once, _orig_turn_end = H.chat_once, H.turn_end


def _fake_chat_once2(*_a, **_kw):
    in_once2.set()
    finish2.wait(10)
    return None


def _broken_turn_end(*_a, **_kw):
    raise RuntimeError("event store is full")


H.chat_once = _fake_chat_once2
H.turn_end = _broken_turn_end
crashes.clear()
threading.excepthook = _excepthook

before2 = set(threading.enumerate())


def _consume2():
    try:
        for _chunk in H.chat_stream_gen(sess2, "hello", "v952-model"):
            pass
    except Exception:  # noqa: BLE001 — the pump's own exit is not under test
        pass


pump2 = threading.Thread(target=_consume2, daemon=True, name="v952-pump2")
pump2.start()
check("D1 the second turn reached its model call", in_once2.wait(10))
finish2.set()
pump2.join(10)
for _t in set(threading.enumerate()) - before2:
    _t.join(10)
H.chat_once = _orig_chat_once
H.turn_end = _orig_turn_end
threading.excepthook = _hook_was

_lk2 = S._turn_lock(SID2)
_free = _lk2.acquire(blocking=False)
check("D2 a raising turn_end still released the turn lock", _free is True)
if _free:                      # a red run leaves it held by a DEAD worker: nothing to release
    _lk2.release()

print("TOTAL %d/%d" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
