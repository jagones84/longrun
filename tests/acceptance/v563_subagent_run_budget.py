#!/usr/bin/env python3
"""v563 (STAGED — M8 per-run subagent spawn budget): a run cannot spawn forever.

Contract (`M8-subagent-run-budget.md`): `max_per_run` (default 6, 0 = no cap)
bounds successful spawns per parent_run_id; over budget -> the usual refusal
dict, no thread/run. `None` parent never counts. `purge_parent` clears counts.
"""

import os
import sys
import tempfile
import threading
import time

# tests/acceptance is two levels below the repo root (staged-tests: three).
HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
TMP = tempfile.mkdtemp(prefix="sf-v563-")
os.environ["LONGRUN_SUBAGENTS_CFG"] = os.path.join(TMP, "subagents.yaml")
os.environ["LONGRUN_SUBAGENT_DIR"] = os.path.join(TMP, "subagents")
os.environ["LONGRUN_GRAPH_DIR"] = os.path.join(TMP, "graphs")
os.environ["LONGRUN_SESSIONS_DIR"] = os.path.join(TMP, "sessions")
os.environ["LONGRUN_DB"] = os.path.join(TMP, "events.db")
os.makedirs(os.environ["LONGRUN_GRAPH_DIR"], exist_ok=True)
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.agent import subagent as SA  # noqa: E402
from longrun.core import api_v02 as A2  # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""))


if getattr(SA, "_SPAWN_COUNT", None) is None and not hasattr(SA, "max_per_run"):
    # Graceful RED: implementation missing — fail every contract check by name.
    for n in ("1a", "1b", "1c", "2a", "2b", "3a", "4a", "4b"):
        check(n + " per-run budget enforced", False, "M8 not implemented")
    print("TOTAL %d/%d" % (sum(results), len(results)))
    sys.exit(1)


def _fake_new_run(goal, model=None, max_steps=6, script=None):
    return type("_St", (), {
        "id": "run_%s" % os.urandom(3).hex(), "status": "running",
        "model": model, "parent_run_id": None,
    })()


_orig_new_run = A2.new_run
_orig_run = A2.agent_run_v2
A2.new_run = _fake_new_run
# Children block until released: the refusal below is about CONCURRENT
# spawns, not thread-scheduling luck.
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
    check("1a two spawns under the per-run cap start",
          bool(s1.get("subagent_id")) and bool(s2.get("subagent_id")), (s1, s2))
    check("1b the third spawn for the same parent is refused",
          s3.get("subagent_id") is None and "per run" in (s3.get("error") or ""),
          s3.get("error"))
    _gate.set()
    s4 = SA.spawn("other parent", parent_run_id="p2", max_steps=1, depth=0)
    check("1c a different parent is unaffected",
          bool(s4.get("subagent_id")), s4)
    for sid in (s1.get("subagent_id"), s2.get("subagent_id"), s4.get("subagent_id")):
        if sid:
            SA.collect(sid, timeout=5)

    cfg["max_per_run"] = 0
    SA.save_cfg(cfg)
    SA.load_cfg(reload=True)
    SA._SPAWN_COUNT.clear()
    many = [SA.spawn("x%d" % i, parent_run_id="p1", max_steps=1, depth=0)
            for i in range(8)]
    check("2a cap 0 means uncapped",
          all(m.get("subagent_id") for m in many), many)
    orph = SA.spawn("orphan", parent_run_id=None, max_steps=1, depth=0)
    check("2b a None parent is never counted", bool(orph.get("subagent_id")), orph)
    for m in many + [orph]:
        if m.get("subagent_id"):
            SA.collect(m.get("subagent_id"), timeout=5)

    cfg["max_per_run"] = 1
    SA.save_cfg(cfg)
    SA.load_cfg(reload=True)
    SA._SPAWN_COUNT.clear()
    a = SA.spawn("a", parent_run_id="p9", max_steps=1, depth=0)
    if a.get("subagent_id"):
        SA.collect(a.get("subagent_id"), timeout=5)
    b = SA.spawn("b", parent_run_id="p9", max_steps=1, depth=0)
    check("3a a finished child frees the slot (live budget, not cumulative)",
          bool(b.get("subagent_id")), b)
    if b.get("subagent_id"):
        SA.collect(b.get("subagent_id"), timeout=5)
    SA.purge_parent("p9")
    c = SA.spawn("c", parent_run_id="p9", max_steps=1, depth=0)
    check("4a purge_parent clears the count", bool(c.get("subagent_id")), c)
    if c.get("subagent_id"):
        SA.collect(c.get("subagent_id"), timeout=5)

    api_src = open(os.path.join(REPO, "src", "longrun", "core", "api_v02.py"),
                   encoding="utf-8").read()
    check("4b GET /api/subagents exposes max_per_run",
          '"max_per_run"' in api_src, "")
finally:
    A2.new_run = _orig_new_run
    A2.agent_run_v2 = _orig_run
    SA._running.clear()
    if hasattr(SA, "_SPAWN_COUNT"):
        SA._SPAWN_COUNT.clear()

print("TOTAL %d/%d" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
