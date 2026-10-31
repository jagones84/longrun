#!/usr/bin/env python3
"""v750 — the delivery read-back is a GATE, not a courtesy.

Measured 2026-10-31 (JobBench dispatch, session da08393e): the harness injected the
READ-BACK at 19:53:46, the next model turn called only `todo.update` (bookkeeping),
and at 19:54:01 the turn closed with "All four deliverables are complete, verified
by read-back". Nothing had been opened since the read-back, yet the answer claimed a
verification. The harness has to remember that the read-back was sent and refuse a
close that never used a real tool afterwards.

Deterministic, no live model, no network, no server.
"""
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="sf-v750-")
os.environ["LONGRUN_CONFIG_DIR"] = os.path.join(TMP, "cfg")
os.environ["LONGRUN_SESSIONS_DIR"] = os.path.join(TMP, "sessions")
os.environ["LONGRUN_EDITS_DIR"] = os.path.join(TMP, "edits")
os.environ["LONGRUN_RUNS_DIR"] = os.path.join(TMP, "runs")
os.environ["LONGRUN_DATA_DIR"] = os.path.join(TMP, "data")
os.environ["LONGRUN_DB"] = os.path.join(TMP, "events.db")
os.environ["LONGRUN_GRAPH_DIR"] = os.path.join(TMP, "graphs")
os.environ["LONGRUN_PROJECTS_DIR"] = os.path.join(TMP, "projects")
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.core import server                # noqa: E402,F401 — breaks the import cycle
from longrun.agent import agent                # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""))


# ---- A. the pure state machine ---------------------------------------------
check("A1 no read-back sent -> nothing owed", agent._review_action_owed({}) is False)
check("A2 read-back sent, no tool since -> owed",
      agent._review_action_owed({"review_sent": True, "after_review": False}) is True)
check("A3 a real tool since the read-back discharges it",
      agent._review_action_owed({"review_sent": True, "after_review": True}) is False)
check("A4 tolerates None", agent._review_action_owed(None) is False)

txt = agent._verify_gate_text()
check("A5 the gate names the concrete call", "fs.read" in txt, txt[:80])
check("A6 it rejects the 'verified by read-back' claim", "verified by read-back" in txt)

# ---- B. a real read-back arms the gate -------------------------------------
ws = tempfile.mkdtemp(prefix="v750-ws-")
with open(os.path.join(ws, "report.csv"), "w", encoding="utf-8") as fh:
    fh.write("id,amount\nA,10\nB,20\n")
sess = {"id": "v750-sess", "messages": [], "workspace": ws}

state = {"left": 1}
text = agent._deliverable_review_text(sess, "write a report.csv", since=0.0, state=state)
check("B1 the read-back is produced", bool(text) and "READ-BACK" in str(text), str(text)[:80])
check("B2 it records that a read-back was sent", state.get("review_sent") is True, state)
check("B3 nothing was done after it", state.get("after_review") is False, state)
check("B4 the close is therefore owed a gate", agent._review_action_owed(state) is True)

again = agent._deliverable_review_text(sess, "write a report.csv", since=0.0, state=state)
check("B5 the read-back itself is still one shot", again is None, again)
check("B6 the debt survives the one-shot read-back", agent._review_action_owed(state) is True)

state["after_review"] = True
check("B7 a tool after the read-back clears the debt",
      agent._review_action_owed(state) is False)

# ---- C. a turn that wrote nothing does not arm the gate --------------------
ws2 = tempfile.mkdtemp(prefix="v750-empty-")
state2 = {"left": 1}
agent._deliverable_review_text({"id": "v750-empty", "messages": [], "workspace": ws2},
                               "write x.csv", since=0.0, state=state2)
check("C1 nothing written -> no artifact read-back",
      state2.get("review_sent") is not True, state2)

print("%d/%d checks" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
