#!/usr/bin/env python3
"""v1047 — a turn that resets ITSELF does not deadlock on its own turn lock.

Measured 2026-11-15 18:38 (live service, session a04c331fca32): the model emitted a
batch containing `sessions.reset` on its own session. A batch item runs on a pool
worker, `clear_session` acquired `_turn_lock(sid)` (held by the turn, which is
blocked waiting for that tool), and the turn froze after `approval.auto`: no
`tool.result`, no `session.cleared`, the transcript untouched. `sessions.reset`
returned exit 0 only when the model emitted it OUTSIDE a batch, because that path
runs on the turn's own thread and the RLock is re-entrant.

`clear_session(sid, from_turn=True)` is the one caller that runs inside the turn it
clears: it skips the turn lock (the tombstone + the save lock keep the write safe).
Every other caller still serialises on it.

  A1 fixture: a session with messages, cards and injects
  A2 from_turn=True completes while the turn lock is HELD (no deadlock) and wipes
  A3 the default clear still BLOCKS on that lock, then wipes once it is released
  A4 the tool door self-reset (run as a pool worker) returns ok and wipes
  A5 a FOREIGN target through the same door still waits for its own turn lock

Deterministic: temp stores, no model, no network, no server.
"""
import json
import os
import sys
import tempfile
import threading
import time

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="sf-v1047-")
for _k in ("DATA_DIR", "CONFIG_DIR", "SESSIONS_DIR", "EDITS_DIR", "RUNS_DIR",
           "GRAPH_DIR", "ROLES_DIR", "COSTS_DIR", "THREADS_DIR"):
    os.environ["LONGRUN_" + _k] = os.path.join(TMP, _k)
    os.makedirs(os.path.join(TMP, _k), exist_ok=True)
os.environ["LONGRUN_DB"] = os.path.join(TMP, "events.db")
os.environ["LONGRUN_AGENTS_FILE"] = os.path.join(TMP, "agents.json")
sys.path.insert(0, os.path.join(REPO, "src"))

SID = "aaaaaaaaaaaa"
OTHER_SID = "cccccccccccc"
with open(os.environ["LONGRUN_AGENTS_FILE"], "w", encoding="utf-8") as fh:
    json.dump({"agents": {
        OTHER_SID: {"id": "A1", "n": 1, "kind": "org", "session": OTHER_SID,
                    "name": "Boss", "reports_to": None},
        SID: {"id": "A2", "n": 2, "kind": "org", "session": SID,
              "name": "Worker", "reports_to": "A1"},
    }, "seq": 2}, fh)

from longrun.core import server as _srv  # noqa: E402,F401 — import order (agent cycle)
from longrun.core.events import _turn_lock  # noqa: E402
from longrun.memory import stores  # noqa: E402
from longrun.tools import tools as T  # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name
          + ((" :: " + str(detail)) if detail else ""))


def seed(sid):
    stores.save_session({
        "id": sid, "title": "reset me " + sid[:4],
        "messages": [{"role": "user", "content": "one"},
                     {"role": "assistant", "content": "ok"}],
        "tool_cards": [{"tool": "shell.exec"}],
        "injects": [{"kind": "nudge"}],
    }, truncate=True)


def disk(sid):
    try:
        with open(os.path.join(stores.SESSIONS_DIR, sid + ".json"), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def empty(sid):
    d = disk(sid)
    return not d.get("messages") and not d.get("tool_cards") and not d.get("injects")


def in_worker(fn):
    box = {}

    def _run():
        try:
            box["out"] = fn()
        except BaseException as e:  # noqa: BLE001 — surfaced by the assertion
            box["err"] = "%s: %s" % (type(e).__name__, e)

    th = threading.Thread(target=_run, daemon=True)
    th.start()
    return th, box


seed(SID)
check("A1 fixture: messages, cards and injects", not empty(SID), disk(SID))

# A2 — the turn's own reset, from a worker, while the turn holds its lock.
lock = _turn_lock(SID)
lock.acquire()
try:
    th, box = in_worker(lambda: stores.clear_session(SID, from_turn=True))
    th.join(3.0)
    check("A2 from_turn=True does not wait on the turn's own lock",
          not th.is_alive() and "err" not in box, box.get("err") or "joined")
    check("A2 the self-reset still wipes the transcript", empty(SID), disk(SID))
finally:
    lock.release()

# A3 — every OTHER caller keeps the serialisation.
seed(SID)
lock = _turn_lock(SID)
lock.acquire()
try:
    th, box = in_worker(lambda: stores.clear_session(SID))
    th.join(0.4)
    check("A3 the default clear BLOCKS while a turn owns the session", th.is_alive(),
          "alive=%s" % th.is_alive())
finally:
    lock.release()
th.join(3.0)
check("A3 it wipes as soon as the turn releases", not th.is_alive() and empty(SID),
      box.get("err") or disk(SID))

# A4 — the real door: sessions.reset on ITSELF, executed on a pool worker.
seed(SID)
lock = _turn_lock(SID)
lock.acquire()
try:
    th, box = in_worker(
        lambda: T._sessions({"action": "reset", "session": SID}, SID))
    th.join(3.0)
    out = box.get("out") or {}
    check("A4 sessions.reset on ITSELF returns from a pool worker",
          not th.is_alive() and out.get("ok") is True and out.get("exit_code") == 0,
          box.get("err") or out)
    check("A4 the tool's reset really emptied the session", empty(SID), disk(SID))
finally:
    lock.release()

# A5 — a FOREIGN target still queues on that session's turn lock.
seed(SID)
lock = _turn_lock(SID)
lock.acquire()
try:
    th, box = in_worker(
        lambda: T._sessions({"action": "reset", "session": SID}, OTHER_SID))
    th.join(0.4)
    check("A5 a chief's reset of ANOTHER session still waits for its turn",
          th.is_alive(), "alive=%s" % th.is_alive())
finally:
    lock.release()
th.join(3.0)
out = box.get("out") or {}
check("A5 it completes once the target's turn releases the lock",
      not th.is_alive() and out.get("ok") is True and empty(SID),
      box.get("err") or out)

print("---")
print("%d/%d PASS" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
