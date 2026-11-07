#!/usr/bin/env python3
"""v845 — the THIRD correction on the same point becomes a durable rule (HA-6).

`agent._is_correction` already classifies ONE user message (a regex on "no /
wrong / instead / sbagliato …") and feeds the improvement pass. Nothing counted
repetitions: by the third correction of the same thing the chat carries two wrong
attempts the model keeps re-reading, and the correction itself is lost with the
session. The fix is the one the talk names — turn it into ONE line of rules, and
say that a clean session is cheaper than a fourth correction.

  A) three similar corrections count 1, 2, 3;
  B) a fourth says 4 (the note fires exactly once);
  C) three DIFFERENT targets never reach 3;
  D) a non-correction never counts;
  E) the note names the rules file and a clean session, and never claims a reset;
  F) `chat_once` calls the counter and injects with kind "correction".

Deterministic, no live model, no network, no server.
"""
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="sf-v845-")
for _k in ("CONFIG_DIR", "SESSIONS_DIR", "EDITS_DIR", "RUNS_DIR", "GRAPH_DIR", "DATA_DIR"):
    os.environ["LONGRUN_" + _k] = os.path.join(TMP, _k)
os.environ["LONGRUN_DB"] = os.path.join(TMP, "events.db")
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.core import server as _s  # noqa: E402,F401  (bootstraps agent)
from longrun.agent import agent as A  # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""))


sess = {"id": "sess-ha6"}
C1 = "No, the date column is wrong — use order_date, not date."
C2 = "No, the date column is still wrong, use order_date."
C3 = "No, wrong again: the column is order_date."
C4 = "No, still the same column mistake: order_date."

n1, _ = A._note_correction(sess, C1)
n2, _ = A._note_correction(sess, C2)
n3, target = A._note_correction(sess, C3)
n4, _ = A._note_correction(sess, C4)
check("A1 the first correction counts 1", n1 == 1, n1)
check("A2 the same point counts 2", n2 == 2, n2)
check("A3 the third reaches 3", n3 == 3, n3)
check("A3b the target is the shared content", "order_date" in (target or []), target)
check("B1 a fourth says 4 (the note fires once, on exactly 3)", n4 == 4, n4)

sess2 = {"id": "sess-ha6-b"}
d1, _ = A._note_correction(sess2, "No, the diagram colours are wrong.")
d2, _ = A._note_correction(sess2, "No, the deploy script needs sudo.")
d3, _ = A._note_correction(sess2, "No, the invoice template has a typo.")
check("C1 different targets stay at 1", (d1, d2, d3) == (1, 1, 1), (d1, d2, d3))

sess3 = {"id": "sess-ha6-c"}
p1, _ = A._note_correction(sess3, "Please summarise the quarter for the board.")
check("D1 a normal request is not a correction", p1 == 0, p1)
check("D2 it does not create state", not sess3.get("corrections"))

note = A._third_correction_note(["order_date", "column"])
low = note.lower()
check("E1 the note names the rules file", "rules" in low)
check("E2 it offers a clean session", "clean session" in low)
check("E3 it never claims a reset", "nothing was reset" in low)

src = open(os.path.join(REPO, "src", "longrun", "agent", "agent.py"), encoding="utf-8").read()
flat = src.replace("\n", " ")
check("F1 chat_once counts a correction before the loop",
      "_note_correction(sess, message)" in flat)
check("F2 it injects with its own kind",
      '_inject(_third_correction_note' in flat and '"correction")' in flat)

print("---")
passed = sum(results)
print("%d/%d PASS" % (passed, len(results)))
sys.exit(0 if passed == len(results) else 1)
