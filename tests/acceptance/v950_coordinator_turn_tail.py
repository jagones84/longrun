#!/usr/bin/env python3
"""v950 — a coordinator turn cannot report the operator's reply as its own.

`_run_agent` captures `before = len(load_session(sid).messages)` BEFORE the turn
takes the session lock, then slices `messages[before:]`. A delegated worker turn
is anchored on its own `meta.sender` / `meta.subjob`; the coordinator's plan and
synthesis turns carry neither, so they always took the fallback slice. With an
operator turn in flight on that session the slice started inside the operator's
turn, and `_best_reply(longest=True)` could hand the operator's answer back as
the job's plan or deliverable (JAG-310's shape, on the coordinator path).

The turn's own user message carries the exact text this call sent, so that text
is the anchor when nothing else identifies the turn.

Deterministic: pure function on a message list, no store, no model, no network.
Run: python3 tests/acceptance/v950_coordinator_turn_tail.py
"""

import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="sf-v949-")
os.environ["LONGRUN_DATA_DIR"] = TMP
os.environ["LONGRUN_JOBS_FILE"] = os.path.join(TMP, "jobs.json")
os.environ["LONGRUN_SESSIONS_DIR"] = os.path.join(TMP, "sessions")
os.environ["LONGRUN_DB"] = os.path.join(TMP, "events.db")
os.makedirs(os.environ["LONGRUN_SESSIONS_DIR"], exist_ok=True)
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.orchestrate import jobs as JM  # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""))


JOB_MSG = "Team results:\nA4: did the work\n\nProduce the COMPLETE final deliverable."
OP_REPLY = ("Here is a long operator answer that happens to be the longest assistant "
            "message in the whole session — much longer than the plan.")
msgs = [
    {"role": "user", "content": "please do X"},                       # 0 operator
    {"role": "assistant", "content": OP_REPLY},                       # 1 operator reply
    {"role": "user", "content": JOB_MSG},                             # 2 the job's turn
    {"role": "assistant", "content": "PLAN: A4 does it."},            # 3 plan
]
BEFORE = 1     # captured while the operator's turn was still running

tail_sent = JM.JOBS._turn_tail(msgs, BEFORE, None, None, sent=JOB_MSG)
check("A1 the tail starts at the job's OWN user message",
      [m["content"] for m in tail_sent] == [JOB_MSG, "PLAN: A4 does it."],
      [m["content"][:30] for m in tail_sent])
check("A2 the operator's reply is NOT in the tail",
      all(m["content"] != OP_REPLY for m in tail_sent))
check("A3 _best_reply of the anchored tail is the plan, not the operator's answer",
      JM.JOBS._best_reply(tail_sent) == "PLAN: A4 does it.",
      JM.JOBS._best_reply(tail_sent)[:40])

tail_old = JM.JOBS._turn_tail(msgs, BEFORE, None, None)
check("B1 without the anchor the old slice really did swallow the operator turn",
      len(tail_old) == 3 and tail_old[0]["content"] == OP_REPLY,
      [m["content"][:20] for m in tail_old])
check("B2 and its 'best reply' was the operator's answer (the defect)",
      JM.JOBS._best_reply(tail_old) == OP_REPLY)

# ---- the delegated anchor still wins ---------------------------------------
del_msgs = [
    {"role": "user", "content": "operator question"},
    {"role": "user", "content": "Delegation from A8 · J6.1",
     "meta": {"sender": "A8", "subjob": "J6.1"}},
    {"role": "assistant", "content": "worker result"},
]
tail_del = JM.JOBS._turn_tail(del_msgs, 0, "A8", "J6.1", sent="Delegation from A8 · J6.1")
check("C1 a delegated turn still anchors on its subjob marker",
      [m["content"] for m in tail_del] == ["Delegation from A8 · J6.1", "worker result"],
      [m["content"][:24] for m in tail_del])

# ---- the last identical text wins (a re-run of the same goal) --------------
rerun = [
    {"role": "user", "content": JOB_MSG},
    {"role": "assistant", "content": "first plan"},
    {"role": "user", "content": JOB_MSG},
    {"role": "assistant", "content": "second plan"},
]
tail_rerun = JM.JOBS._turn_tail(rerun, 0, None, None, sent=JOB_MSG)
check("D1 a re-run anchors on the NEWEST identical message",
      [m["content"] for m in tail_rerun] == [JOB_MSG, "second plan"],
      [m["content"] for m in tail_rerun])

# ---- no anchor at all keeps the old fallback -------------------------------
fallback = [{"role": "user", "content": "a"}, {"role": "assistant", "content": "b"}]
check("E1 with no marker and no `sent` the fallback slice is unchanged",
      JM.JOBS._turn_tail(fallback, 1, None, None) == fallback[1:])
check("E2 _run_agent passes the text it sent",
      "sent=message" in __import__("inspect").getsource(JM.JobRegistry._run_agent))

print("TOTAL %d/%d" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
