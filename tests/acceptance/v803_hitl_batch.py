#!/usr/bin/env python3
"""v803 — a stray human.ask must not swallow a batch or park a placeholder card.

Measured incident (2026-11-05, session `longrunAgent` msg 138): the model emitted
ONE batch with four calls — `python.run`, `http.fetch`, `web.search` and
`human.ask {"question":"placeholder"}`. The loop recognised the human.ask BEFORE
running the batch, so the three real calls were never executed and the operator
got a card whose question was the word "placeholder".

What this pins:
  A  a placeholder/empty question cannot open a card (one nudge instead);
     a short REAL question still passes (no natural-language guard);
  B  a batch keeps its other calls: they are removed from the card path and
     run first, in the model's order;
  C  the loop's order is real (siblings executed before the card is opened);
  D  the tool and the loop share ONE validator (no second copy of the rule).

Deterministic: temp dirs, no model, no network.
Run: python3 tests/acceptance/v803_hitl_batch.py
"""
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="longrun-v803-")
for name, tail in {
    "LONGRUN_DATA_DIR": "data",
    "LONGRUN_CONFIG_DIR": "cfg",
    "LONGRUN_DB": "events.db",
    "LONGRUN_SESSIONS_DIR": "sessions",
    "LONGRUN_GRAPH_DIR": "graphs",
}.items():
    os.environ[name] = os.path.join(TMP, tail)
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.core import server  # noqa: E402,F401  (import order: agent needs it)
from longrun.agent import agent as A  # noqa: E402
from longrun.tools import tools as T  # noqa: E402

SRC = open(os.path.join(REPO, "src", "longrun", "agent", "agent.py"),
           encoding="utf-8").read()

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name
          + ((" :: " + str(detail)[:300]) if detail and not ok else ""))


# ---- A: the question validator -------------------------------------------
# STRICT (operator, 2026-11-05): a card costs a context switch, so only a real
# question earns one — a '?' AND three words saying what is being decided.
for bad in ("placeholder", "placeholder?", "  PLACEHOLDER  ", "todo", "tbd",
            "n/a", "?", "...", "", "Continue?", "Which region?", "why?",
            "Apply the migration now"):
    check("A1 refused: %r" % bad, bool(T.human_question_problem(bad)), bad)
for good in ("Apply the migration now?", "Ship it or park it?",
             "Which region first?", "Which branch should the release cut from?"):
    check("A2 accepted: %r" % good, T.human_question_problem(good) == "", good)
check("A3 the message names the offending token",
      "placeholder" in T.human_question_problem("placeholder"))
check("A4 a missing '?' is named", "no '?'" in T.human_question_problem("Apply it now"))
check("A5 a too-short ask is named", "too short" in T.human_question_problem("Continue?"))

# ---- B: the batch keeps its other calls ----------------------------------
BATCH = {"action": "batch", "calls": [
    {"action": "tool", "tool": "python.run", "args": {"code": "1"}},
    {"action": "tool", "tool": "human.ask", "args": {"question": "Which one?"}},
    {"action": "tool", "tool": "web.search", "args": {"query": "x"}},
]}
_rest = A._batch_without_human(BATCH)
check("B1 the human item is removed", _rest is not None
      and [c.get("tool") for c in _rest["calls"]] == ["python.run", "web.search"],
      _rest)
check("B2 the model's order is preserved",
      _rest is not None and _rest["calls"][0]["tool"] == "python.run")
check("B3 the original action is not mutated",
      [c.get("tool") for c in BATCH["calls"]]
      == ["python.run", "human.ask", "web.search"])
check("B4 a batch with no human item is left alone",
      A._batch_without_human({"action": "batch", "calls": [
          {"action": "tool", "tool": "fs.read", "args": {}}]}) is None)
check("B5 a batch of ONLY a human item has nothing to run first",
      A._batch_without_human({"action": "batch", "calls": [
          {"action": "tool", "tool": "human.ask", "args": {"question": "Q?"}}]}) is None)
check("B6 the alternate key spelling works too",
      (A._batch_without_human({"action": "batch", "tool_calls": [
          {"action": "tool", "tool": "fs.read", "args": {}},
          {"action": "tool", "tool": "human.ask", "args": {"question": "Q?"}}]})
       or {}).get("tool_calls") == [{"action": "tool", "tool": "fs.read", "args": {}}])

# ---- C: the loop executes the siblings BEFORE the card -------------------
_i_run = SRC.find("_rest = _batch_without_human(act)")
_i_card = SRC.find('_hitl = {"reason": "asked"')
check("C1 both anchors exist", _i_run > 0 and _i_card > 0, (_i_run, _i_card))
check("C2 the siblings run before the card is opened", 0 < _i_run < _i_card,
      (_i_run, _i_card))
_seg = SRC[_i_run:_i_card] if _i_run > 0 and _i_card > 0 else ""
check("C3 the siblings go through the real batch executor",
      "_apply_chat_batch(sess, _rest" in _seg)
check("C4 the placeholder path nudges instead of ending the turn",
      "human.ask was NOT sent" in _seg and "continue" in _seg)

# ---- D: one validator, two callers ---------------------------------------
check("D1 the loop calls the tool's validator (no second copy)",
      "_tmod_hitl.human_question_problem(_q)" in SRC)
check("D2 the tool refuses a placeholder itself",
      T._human({"question": "placeholder"}, None).get("ok") is False)
check("D3 the tool still accepts a real question",
      T._human({"question": "Deploy the release now?"}, None).get("ok") is True)
TOOLS_SRC = open(os.path.join(REPO, "src", "longrun", "tools", "tools.py"),
                 encoding="utf-8").read()
check("D4 the placeholder list is declared exactly once",
      TOOLS_SRC.count("_PLACEHOLDER_QUESTIONS = frozenset") == 1)

print("\n---")
print("v803: %d/%d PASS" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
