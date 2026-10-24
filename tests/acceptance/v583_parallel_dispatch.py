#!/usr/bin/env python3
"""v583 — parallel dispatch + bounded dispatch + job fallback prompt.

A54 live findings (all must hold):
  P1 dispatches to DIFFERENT teammates in one batch run CONCURRENTLY (same
     teammate stays sequential — two turns in one session must not
     interleave). Before: the batch ran every dispatch sequentially.
  P2 a dispatch never hangs the orchestrator turn forever: the teammate turn
     is bounded by LONGRUN_DISPATCH_WAIT (default 300s); on timeout the
     orchestrator gets "still running + where to read it" instead of a stuck
     turn, and the teammate turn keeps running to completion in its session.
  P3 the prompts say what to do when job.* answers permission_denied (exit
     126): use batch+dispatch (no grant needed) or ask the operator for the
     Teamorg grant — instead of stalling or shelling around the gate.

Deterministic, no model, no network.
"""
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(REPO, "src"))

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""))


from longrun.core import server as _srv  # noqa: E402,F401 — first: breaks the agent<->server import cycle
from longrun.agent import agent as _ag  # noqa: E402
from longrun.core import api_v02 as _api  # noqa: E402

# ---- P1: grouping -------------------------------------------------------------
check("P1a dispatch key helper exists", callable(getattr(_ag, "_dispatch_key", None)))
k1 = _ag._dispatch_key({"action": "dispatch", "agent": "A48", "goal": "g"})
k2 = _ag._dispatch_key({"action": "tool", "tool": "dispatch",
                        "args": {"to": "A49", "goal": "g"}})
k3 = _ag._dispatch_key({"agent": "A48", "goal": "other goal"})
check("P1b same teammate maps to the same group key",
      k1 is not None and k1 == k3, (k1, k3))
check("P1c different teammates map to different group keys",
      k1 is not None and k2 is not None and k1 != k2, (k1, k2))
check("P1d address-less item gets no group key (never forced sequential)",
      _ag._dispatch_key({"action": "dispatch", "goal": "no address"}) is None)
_SRC = open(os.path.join(REPO, "src", "longrun", "agent", "agent.py"),
            encoding="utf-8").read()
_seg = _SRC[_SRC.find("if dispatch_items:"):]
_seg = _seg[:_seg.find('lines = ["Batch of')]
check("P1e batch runs dispatch groups concurrently (pool), same group in order",
      "ThreadPoolExecutor" in _seg and "sequential" in _seg.lower(), "pool+order")

# ---- P2: bounded dispatch -------------------------------------------------------
check("P2a dispatch wait helper exists", callable(getattr(_ag, "_dispatch_wait", None)))
w = _ag._dispatch_wait()
check("P2b default wait is a positive int (seconds)", isinstance(w, int) and w > 0, w)
check("P2c dispatch path references the wait (bounded teammate turn)",
      "_dispatch_wait()" in _SRC and "still running" in _SRC)
check("P2d timeout observation tells where to read the teammate reply",
      "sessions.read" in _SRC[_SRC.find("still working"):_SRC.find("still working") + 400])

# ---- P3: job fallback prompt ----------------------------------------------------
_TC = _api.tool_context()
check("P3a tool_context says what to do on job permission_denied",
      "permission_denied" in _TC and "batch" in _TC.lower()
      and "dispatch" in _TC.lower(), "fallback contract")
check("P3b agent prompt dispatch paragraph mentions the job fallback",
      "permission_denied" in _SRC and "grant" in _SRC.lower())

print("---")
passed = sum(results)
print("%d/%d PASS" % (passed, len(results)))
sys.exit(0 if passed == len(results) else 1)
