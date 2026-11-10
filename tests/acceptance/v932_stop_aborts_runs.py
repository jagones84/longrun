#!/usr/bin/env python3
"""v932 — the Stop button must stop the RUN, not only the streaming chat turn.

Operator (2026-11-10): *"il tasto stop delle webui non interrompe subito il
modello come nelle harness commerciali"*. Measured: the local llama.cpp cancels
the task in ~30 ms when the client closes the socket, so the gap was in the
harness — a background run (job, subagent) never received the Stop at all:

  * `RunState.abort` was raised only by `POST /api/agent/control`;
  * the UI Stop is `POST /api/chat/abort {all:true}` and it aborted the chat
    turns in `_ACTIVE_CHAT`, which a run is not;
  * the run's model call passed NO `cancel`, so its generation ran to the end
    (and a planner/compaction call waited for the router timeout).

Contract pinned here:
  A) the run's model call receives a cancel predicate and the run ends
     `aborted` within a second of the Stop — never `done`;
  B) `abort_all_runs` aborts every live run, honours `only_session`, and is
     idempotent; a terminal run is skipped;
  C) the session Stop (`push_abort`) also reaches a run bound to that session,
     and `checkpoint` refuses to continue one;
  D) wiring: both `/api/chat/abort` branches abort the runs, and every run
     model call passes the predicate.

Deterministic: router stubbed, temp dirs, no model, no network, no server.
"""
import os
import sys
import tempfile
import threading
import time

_tmp = tempfile.mkdtemp(prefix="sf-v932-")
for _k, _d in (("CONFIG_DIR", "cfg"), ("SESSIONS_DIR", "sessions"),
               ("GRAPH_DIR", "graphs"), ("EDITS_DIR", "edits"),
               ("RUNS_DIR", "runs"), ("COSTS_DIR", "costs"),
               ("ROLES_DIR", "roles")):
    _p = os.path.join(_tmp, _d)
    os.makedirs(_p, exist_ok=True)
    os.environ["LONGRUN_" + _k] = _p
os.environ["LONGRUN_DB"] = os.path.join(_tmp, "events.db")

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.core import api_v02, server  # noqa: E402
from longrun.model import routing  # noqa: E402
from longrun.util.steering import clear_abort, push_abort  # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name
          + ((" :: " + str(detail)[:300]) if detail and not ok else ""))


# ---- A. a live generation dies on the Stop --------------------------------
CALLS = []


def stub_stream(messages, alias, on_delta, timeout=None, usage=None, guard=None,
                cancel=None, no_reasoning=False, max_tokens=None,
                temperature=None, seed=None):
    """Call 1 = the run's planner (cheap). Call 2 is the generation the operator
    stops: it behaves like the real loop, polling `cancel` until it fires."""
    CALLS.append(cancel)
    if len(CALLS) == 1:
        return "", ""
    threading.Thread(target=lambda: (time.sleep(0.05), api_v02.abort_all_runs()),
                     daemon=True).start()
    t0 = time.time()
    while not (cancel is not None and cancel()):
        if time.time() - t0 > 5:
            return "TIMEOUT", ""
        time.sleep(0.01)
    return "", ""


_orig_stream = server._router_stream
_orig_order = routing.order_candidates
server._router_stream = stub_stream
routing.order_candidates = lambda c: list(c)
try:
    t0 = time.time()
    out = api_v02.agent_run_v2("stop me", max_steps=3, model="m1",
                               session="S932", on_event=lambda *a, **k: None)
    elapsed = time.time() - t0
    st = api_v02.run_get(out["run_id"])
finally:
    server._router_stream = _orig_stream
    routing.order_candidates = _orig_order

check("A1 the run's generation receives a cancel predicate",
      len(CALLS) >= 2 and CALLS[1] is not None, CALLS)
check("A2 the Stop ends the run as `aborted` (not `done`)",
      st.status == "aborted" and st.termination == "aborted",
      (st.status, st.termination))
check("A3 it ends at once, not after the generation (and not max_steps)",
      elapsed < 2.0 and not [e for e in st.trace if e.get("action") != "abort"],
      (round(elapsed, 2), st.trace))

# ---- B. abort_all_runs: live only, per session, idempotent ----------------
live = api_v02.new_run("live one")
live.session = "S-B"
done = api_v02.new_run("already finished")
done.status = "done"

aborted = api_v02.abort_all_runs()
check("B1 every live run is aborted", live.id in aborted, aborted)
check("B2 a terminal run is skipped", done.id not in aborted, aborted)
check("B3 the run flag and the cancel event are both raised",
      live.abort is True and live.cancel_ev.is_set(), (live.abort, live.cancel_ev.is_set()))
check("B4 a second Stop changes nothing (idempotent)", api_v02.abort_all_runs() == [],
      api_v02.abort_all_runs())

other = api_v02.new_run("someone else's run")
other.session = "S-OTHER"
mine = api_v02.new_run("mine")
mine.session = "S-MINE"
only = api_v02.abort_all_runs(only_session="S-MINE")
check("B5 a session-scoped Stop aborts ITS run only",
      mine.id in only and other.id not in only, only)
api_v02.run_control(other.id, "abort")  # leave nothing live behind

# ---- C. the session Stop reaches a run bound to that session --------------
sess_run = api_v02.new_run("session run")
sess_run.session = "S-STOP"
push_abort("S-STOP")
try:
    pred = api_v02.cancel_of(sess_run)
    check("C1 cancel_of sees the session's Stop", bool(pred and pred()), pred)
    raised = False
    try:
        api_v02.checkpoint(sess_run)
    except api_v02.AbortRun:
        raised = True
    check("C2 checkpoint refuses to continue a stopped run", raised)
finally:
    clear_abort("S-STOP")

api_v02.run_control(sess_run.id, "abort")
free = api_v02.new_run("free")
check("C3 a run with no Stop and no session is not cancelled",
      api_v02.cancel_of(free)() is False)

# ---- D. wiring ------------------------------------------------------------
_http = open(os.path.join(REPO, "src", "longrun", "core", "httpapi.py"),
             encoding="utf-8").read()
_i = _http.find('if path == "/api/chat/abort":')
_seg = _http[_i:_i + 1600] if _i > 0 else ""
check("D1 both /api/chat/abort branches abort the runs",
      _seg.count("api_v02.abort_all_runs(") == 2, _seg.count("api_v02.abort_all_runs("))

_api = open(os.path.join(REPO, "src", "longrun", "core", "api_v02.py"),
            encoding="utf-8").read()
_agent = open(os.path.join(REPO, "src", "longrun", "agent", "agent.py"),
              encoding="utf-8").read()
check("D2 the run loop hands cancel_of to its model call",
      "cancel=cancel_of(st)" in _api)
check("D3 the legacy agent loop hands cancel_of to its model call",
      "cancel=api_v02.cancel_of(st)" in _agent)

print("\n---\nv932: %d/%d PASS" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
