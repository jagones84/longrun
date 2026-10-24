#!/usr/bin/env python3
"""v577 — spawn budget is live, batch dispatch is not a spawn (F1/F2).

F1: `_SPAWN_COUNT` leaked — a finished subagent held its budget slot forever
(per-run cap exhausted for the whole session). Slots free when the child ends.
F2: a batch `dispatch` item (work for a teammate's session) was routed into
Session Jobs / `subagent.spawn` — wrong semantics AND budget consumed.
Dispatch now runs the teammate turn directly and never touches the counter.
"""
import os
import sys
import tempfile
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
TMP = tempfile.mkdtemp(prefix="sf-v577-")
os.environ["LONGRUN_SUBAGENTS_CFG"] = os.path.join(TMP, "subagents.yaml")
os.environ["LONGRUN_SUBAGENT_DIR"] = os.path.join(TMP, "subagents")
os.environ["LONGRUN_GRAPH_DIR"] = os.path.join(TMP, "graphs")
os.environ["LONGRUN_SESSIONS_DIR"] = os.path.join(TMP, "sessions")
os.environ["LONGRUN_DB"] = os.path.join(TMP, "events.db")
os.makedirs(os.environ["LONGRUN_GRAPH_DIR"], exist_ok=True)
sys.path.insert(0, os.path.join(REPO, "src"))

# Import the server FIRST: agent.py <-> core/server.py are mutually recursive and
# core/server.py is the side that pulls the prompt constants out of agent.py.
from longrun.core import server as _server  # noqa: E402,F401
from longrun.agent import agent as A  # noqa: E402
from longrun.agent import subagent as SA  # noqa: E402
from longrun.core import api_v02 as A2  # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""))


# ---- F1: slots free on completion ------------------------------------------------
def _fake_new_run(goal, model=None, max_steps=6, script=None):
    return type("_St", (), {
        "id": "run_%s" % os.urandom(3).hex(), "status": "running",
        "model": model, "parent_run_id": None,
    })()


_orig_new_run = A2.new_run
_orig_run = A2.agent_run_v2
A2.new_run = _fake_new_run
# Children block until the test releases them: concurrency is deterministic,
# not thread-scheduling luck.
_gate = threading.Event()


def _fake_run(*a, **k):
    _gate.wait(10)
    return {"status": "done", "trace": [], "summary": "ok"}


A2.agent_run_v2 = _fake_run
try:
    SA.load_cfg(reload=True)
    cfg = SA.load_cfg()
    cfg["max_per_run"] = 2
    cfg["max_parallel"] = 0
    SA.save_cfg(cfg)
    SA.load_cfg(reload=True)
    SA._running.clear()
    SA._SPAWN_COUNT.clear()

    s1 = SA.spawn("one", parent_run_id="p1", max_steps=1, depth=0)
    s2 = SA.spawn("two", parent_run_id="p1", max_steps=1, depth=0)
    s3 = SA.spawn("three", parent_run_id="p1", max_steps=1, depth=0)
    check("F1a budget still refuses the third concurrent spawn",
          bool(s1.get("subagent_id")) and bool(s2.get("subagent_id"))
          and s3.get("subagent_id") is None, s3.get("error"))
    _gate.set()
    for sid in (s1.get("subagent_id"), s2.get("subagent_id")):
        SA.collect(sid, timeout=5)
    check("F1b finished children free their slots",
          SA._SPAWN_COUNT.get("p1", 0) == 0, dict(SA._SPAWN_COUNT))
    s4 = SA.spawn("after completion", parent_run_id="p1", max_steps=1, depth=0)
    check("F1c a new wave spawns after the previous children ended",
          bool(s4.get("subagent_id")), s4)
    if s4.get("subagent_id"):
        SA.collect(s4.get("subagent_id"), timeout=5)
finally:
    A2.new_run = _orig_new_run
    A2.agent_run_v2 = _orig_run

# ---- F2: the splitter --------------------------------------------------------------
_split = getattr(A, "_split_batch_items", None)
_items = [{"tool": "fs.read", "args": {"path": "a"}},
          {"action": "subagent", "goal": "do sub"},
          {"action": "dispatch", "agent": "A9", "goal": "do team"},
          {"goal": "bare goal sub"}]
if _split is None:
    check("F2a splitter exists", False, "A._split_batch_items missing")
    check("F2b a batch dispatch runs the teammate turn directly", False, "no splitter")
    check("F2c dispatch never touches the spawn budget", False, "no splitter")
else:
    _tools, _subs, _disp = _split(_items)
    check("F2a dispatch items (even with a goal) never land in sub_items",
          len(_disp) == 1 and _disp[0].get("agent") == "A9"
          and len(_subs) == 2 and len(_tools) == 1,
          ([i.get("action", i.get("tool")) for i in _tools],
           [i.get("action", "goal") for i in _subs],
           [i.get("action") for i in _disp]))

# ---- F2: dispatch runs the teammate turn, never a spawn -----------------------------
if _split is not None:
    _seen = []
    _orig_dispatch = A._apply_chat_dispatch
    A._apply_chat_dispatch = lambda sess, it, on_event, node=None, after=None: (
        _seen.append(it) or "Teammate A9 replied: done")
    _orig_persist = A.persist_tool_card
    A.persist_tool_card = lambda *a, **k: None
    try:
        SA._SPAWN_COUNT.clear()
        ev = []
        sess = {"id": "v577"}
        obs = A._apply_chat_batch(
            sess,
            {"action": "batch", "calls": [
                {"action": "dispatch", "agent": "A9", "goal": "do team"}]},
            lambda kind, **kw: ev.append((kind, kw)), None)
        check("F2b a batch dispatch runs the teammate turn directly",
              len(_seen) == 1 and _seen[0].get("agent") == "A9"
              and "### dispatch OK" in obs and "replied: done" in obs, obs[:200])
        check("F2c dispatch never touches the spawn budget",
              dict(SA._SPAWN_COUNT) == {}, dict(SA._SPAWN_COUNT))
    finally:
        A._apply_chat_dispatch = _orig_dispatch
        A.persist_tool_card = _orig_persist

print("\n%d/%d" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
