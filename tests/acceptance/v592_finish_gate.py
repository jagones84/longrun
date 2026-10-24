#!/usr/bin/env python3
"""v592 (RED) — OctoMind done-gate: an explicit finish with open work is a
claim, not proof.

Hole: `{"action":"finish","summary":...}` breaks out of the turn loop BEFORE
keepgoing/JAG-402, so in non-goal mode it closes the turn with open todos and
no verification — the unverified-success pattern. Goal mode already recovers;
the `_term_action`/artifact/invalid paths already face the bounded closure
check. This extends the SAME check to explicit finishes:

- `agent._finish_gated(sess, goal_mode)` -> True only when the finish must
  face the check (non-goal mode AND `_turn_unfinished`).
- The finish branch consults it (bounded by `_selfcheck_left`) before setting
  `_finished_cleanly`; a clean finish still disarms the check as before.

Deterministic: no model, no network, no server (taskgraph.load monkeypatched).
Run: python3 tests/acceptance/v592_finish_gate.py
"""
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.core import server as _srv  # noqa: E402,F401 — first: breaks the cycle
from longrun.agent import agent as _ag  # noqa: E402
from longrun.plan import taskgraph as _tg  # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""))


# ---- G1: the gate helper ------------------------------------------------------
check("G1 agent._finish_gated exists", callable(getattr(_ag, "_finish_gated", None)))
gate = getattr(_ag, "_finish_gated", None)

# ---- G2/G3: behavior with a patched taskgraph ---------------------------------
real_load = _tg.load
try:
    _tg.load = lambda sid: {}
    if callable(gate):
        check("G2 no open nodes -> not gated",
              gate({"id": "S9"}, False) is False)
        check("G2b goal mode defers to its recovery path -> not gated",
              gate({"id": "S9"}, True) is False)
    _tg.load = lambda sid: {"nodes": [
        {"id": "n1", "status": "todo", "title": "t"},
        {"id": "n2", "status": "done", "title": "d"}]}
    if callable(gate):
        check("G3 open todo in chat mode -> gated",
              gate({"id": "S9"}, False) is True)
        check("G3b open todo in goal mode -> recovery path, not gated",
              gate({"id": "S9"}, True) is False)
    _tg.load = lambda sid: {"nodes": [{"id": "n1", "status": "done"}]}
    if callable(gate):
        check("G3c all done in chat mode -> not gated",
              gate({"id": "S9"}, False) is False)
finally:
    _tg.load = real_load
if not callable(gate):
    for n in ("G2", "G2b", "G3", "G3b", "G3c"):
        check(n, False, "_finish_gated missing")

# ---- G4: the finish branch consults it before accepting -------------------------
_SRC = open(os.path.join(REPO, "src", "longrun", "agent", "agent.py"),
            encoding="utf-8").read()
_seg = _SRC[_SRC.find("if _is_explicit_finish(act):"):]
_seg = _seg[:_seg.find("if _term_action(act):")]
check("G4a finish branch consults the gate", "_finish_gated(" in _seg, "gate call")
_use = _seg.find("_finish_gated(")
_flag = _seg.find("_finished_cleanly = True")
check("G4b the gate sits before the clean flag",
      _use >= 0 and _flag >= 0 and _use < _flag)
check("G4c a gated finish re-enters via the closure prompt",
      "_closure_check_prompt" in _seg, "same bounded verdict")
check("G4d the gate consumes the same bounded budget",
      "_selfcheck_left -= 1" in _seg)
check("G4e silent-end checks are now four (finish joins the three)",
      _SRC.count("_selfcheck_left > 0 and _turn_unfinished(sess, goal_mode)") == 3
      and _SRC.count("_selfcheck_left > 0 and _finish_gated(sess, goal_mode)") == 1,
      "raw=%d gated=%d"
      % (_SRC.count("_selfcheck_left > 0 and _turn_unfinished(sess, goal_mode)"),
         _SRC.count("_selfcheck_left > 0 and _finish_gated(sess, goal_mode)")))

print("---")
passed = sum(results)
print("%d/%d PASS" % (passed, len(results)))
sys.exit(0 if passed == len(results) else 1)
