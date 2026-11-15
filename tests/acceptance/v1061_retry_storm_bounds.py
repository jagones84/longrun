#!/usr/bin/env python3
"""v1061 — one turn cannot emit an unbounded chain of harness nudges.

Measured live, session b7329cccf94c (2026-11-15 22:21:29–22:21:53): ONE turn
emitted SIX identical "Your last message was EMPTY" retries plus one CONTINUE
before `chat.error`. The `_empty_streak <= 2` cap did not bound it, because the
CONTINUE park resets the streak and any non-empty-but-useless reply resets it too.

Two invariants this pins:
  A  a per-TURN ceiling (`_empty_total <= 2`) and at most ONE continue park;
  B  a STALE plan (`_user_pivot`) cannot extend a turn that ran no tool at all —
     measured: "Reply with exactly: OK" was dragged into a 7-task pivot.

Static source pins on agent.py (the loop needs a model to exercise end to end);
deterministic, no model, no network, no server.
"""
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
with open(os.path.join(REPO, "src", "longrun", "agent", "agent.py"), encoding="utf-8") as f:
    src = f.read()

results = []


def check(name, ok):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name)


check("A1 per-turn counter exists", "_empty_total = 0" in src)
check("A2 retry requires the per-turn budget",
      "_empty_streak <= 2 and _empty_total <= 2:" in src)
check("A3 every empty increments the total", "_empty_total += 1" in src)
check("A4 at most ONE continue park", "_empty_parks < 1 and not autonomous" in src)
check("A5 the error states the real count", "% _empty_total" in src)
check("A6 no stale two-park comment", "_empty_parks < 2" not in src)
check("B1 pivot needs plan work (two branches)",
      src.count("if _user_pivot and not used_tools:") == 2)
check("B2 the stale plan stops as user_pivot",
      '"continue": False, "reason": "user_pivot"' in src)
check("B3 the pivot gate sits before the decision",
      src.count("else:\n                    _dec = _pivot_decide(") == 2)
check("C1 a reasoning-only reply fails over instead of nudging",
      "if (str(think or \"\").strip() and not _reasoning_failover_used" in src)
check("C2 the failover is requested from the router",
      "reasoning_only_is_blank=_reasoning_failover" in src
      and "advance_from=_advance_from" in src)
check("C3 an empty_reply turn gets ONE forced answer",
      '_final_tries = 1 if _kg_stop_reason == "empty_reply" else 3' in src)

print("\n%d/%d PASS" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
