#!/usr/bin/env python3
"""v843 — the best-of-N spend gate must ask the question the LOOP asks.

v838 stopped sampling ACTION steps, because the ranker (`prm.rank_text`) scores
text and therefore buys verbosity. It decided "is this an action?" with
`_looks_like_json_action`, which requires the message to START with `{` or `[`.
The loop itself decides with `_extract_action`, which finds the action anywhere in
the message. So a step that says *"I'll patch it now.\\n{"action": …}"* is an
ACTION to the loop and PROSE to the gate — and every such step bought a second
full-context sample ranked by length.

Measured live on a SWE-bench instance (2026-11-07, `271dcb827fad`): 11 of 22 calls
were duplicate samples (50%), i.e. the v838 change bought nothing on this workload
against the 46% measured before it (session `dbaa607aa31b`, 56 of 121).

  A) `spend_extra` keeps its meaning (prose-only by default, reversible by config);
  B) a prose-prefixed action is an ACTION for the step classifier;
  C) the gate in `agent.py` passes that classifier, not the shape check.

Deterministic, no live model, no network, no server.
"""
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="sf-v843-")
for _k in ("CONFIG_DIR", "SESSIONS_DIR", "EDITS_DIR", "RUNS_DIR", "GRAPH_DIR"):
    os.environ["LONGRUN_" + _k] = os.path.join(TMP, _k)
os.environ["LONGRUN_DB"] = os.path.join(TMP, "events.db")
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.core import server as _s  # noqa: E402,F401  (server bootstraps agent)
from longrun.agent import agent as A                                    # noqa: E402
from longrun.plan import bestofn as B                                   # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""))


# ------------------------------------------------ A. the policy keeps its shape ---
OFF = {"n": 2, "enabled": True, "on_actions": False}
ON = {"n": 2, "enabled": True, "on_actions": True}
check("A1 a prose step still gets its extra sample", B.spend_extra(2, False, OFF) is True)
check("A2 an action step does not", B.spend_extra(2, True, OFF) is False)
check("A3 the config can restore the old gate",
      B.spend_extra(2, True, ON) is True and B.spend_extra(2, False, ON) is False)
check("A4 n=1 never pays", B.spend_extra(1, False, OFF) is False)

# ------------------------------------------ B. what counts as an ACTION here ---
PREFIXED = ('I will patch the parser now.\n'
            '{"action":"tool","tool":"fs.edit","args":{"path":"a.py","content":"x"}}')
PLAIN = "I will now look at the parser and think about the fix."
check("B1 a prose-prefixed action is an action",
      getattr(A, "_step_is_action", lambda _t: None)(PREFIXED) is True,
      "the gate must not depend on the message STARTING with '{'")
check("B2 plain prose is not", getattr(A, "_step_is_action", lambda _t: None)(PLAIN) is False)
check("B3 a bare action is still an action",
      getattr(A, "_step_is_action", lambda _t: None)(
          '{"action":"tool","tool":"shell","args":{"command":"ls"}}') is True)
check("B4 the shape check is what misses it (the defect, pinned)",
      A._looks_like_json_action(PREFIXED) is False
      and A._extract_action(PREFIXED) is not None)

# ------------------------------------------------- C. the gate uses the truth ---
src = open(os.path.join(REPO, "src", "longrun", "agent", "agent.py"),
           encoding="utf-8").read()
check("C1 the spend gate classifies with the loop's own parser",
      "spend_extra(_bN, _step_is_action(answer)" in src.replace("\n", " "))
check("C2 the failure fallback agrees",
      "_sample_this = _bN > 1 and _step_is_action(answer)" in src)

print("---")
passed = sum(results)
print("%d/%d PASS" % (passed, len(results)))
sys.exit(0 if passed == len(results) else 1)
