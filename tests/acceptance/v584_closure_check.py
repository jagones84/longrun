#!/usr/bin/env python3
"""v584 — closure check: the same agent verdicts its own last response.

Premature stops closed turns silently. The fix: an explicit
`{"action":"finish","summary":"..."}` ends the turn cleanly and disarms the
check; a turn that would otherwise end WITH work open gets a bounded
(max 2/turn) fixed harness prompt asking the agent itself to verdict
complete (finish) or keep working. Bounded counter + disarm = no regress.

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


from longrun.core import server as _srv  # noqa: E402,F401 — first: breaks the agent<->server cycle
from longrun.agent import agent as _ag  # noqa: E402

# ---- F1: explicit finish recognition -------------------------------------------
check("F1a finish with summary is an explicit verdict",
      _ag._is_explicit_finish({"action": "finish", "summary": "did X, found Y"}) is True)
check("F1b bare finish stays a made-up envelope (old swallow)",
      _ag._is_explicit_finish({"action": "finish"}) is False)
check("F1c answer/finish synonyms are not the verdict",
      _ag._is_explicit_finish({"action": "answer", "text": "done"}) is False)
check("F1d non-dict is not a verdict",
      _ag._is_explicit_finish("finish") is False)

# ---- F2: fixed verdict prompt ---------------------------------------------------
p = _ag._closure_check_prompt()
check("F2 prompt asks for finish-or-keep-working",
      "finish" in p and "COMPLETE" in p and "keep working" in p, p[:80])

_SRC = open(os.path.join(REPO, "src", "longrun", "agent", "agent.py"),
            encoding="utf-8").read()

# ---- F3: finish ends the turn and disarms ----------------------------------------
_seg = _SRC[_SRC.find("if _is_explicit_finish(act):"):]
_seg = _seg[:_seg.find("if _term_action(act):")]
check("F3 finish branch sets the clean flag and breaks",
      "_finished_cleanly = True" in _seg and "break" in _seg)

# ---- F4: bounded self-check at every silent end -----------------------------------
check("F4a check budget is a small constant",
      _ag._SELFCHECK_MAX == 2, _ag._SELFCHECK_MAX)
check("F4b three silent ends consult the check",
      _SRC.count("_selfcheck_left > 0 and _turn_unfinished(sess, goal_mode)") == 3,
      _SRC.count("_selfcheck_left > 0 and _turn_unfinished(sess, goal_mode)"))
check("F4c every check decrements and re-enters bounded",
      _SRC.count("_selfcheck_left -= 1") == 3)
check("F4d finish branch never triggers the check (disarm, no regress)",
      "_closure_check_prompt" not in _seg)

# ---- F5: prompt teaches the contract by default -------------------------------------
_AP = _ag.CHAT_PROMPT if hasattr(_ag, "CHAT_PROMPT") else _SRC
check("F5 prompt teaches finish-as-verdict plus the check",
      '"finish"' in _AP and "verdict your own" in _AP)

print("---")
passed = sum(results)
print("%d/%d PASS" % (passed, len(results)))
sys.exit(0 if passed == len(results) else 1)
