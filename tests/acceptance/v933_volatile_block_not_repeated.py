#!/usr/bin/env python3
"""v933 — a volatile block already in the history is not sent a second time.

Once the history became append-only (`wire`, v931), repeating the live task list and
the memory index on every turn only grew the window: measured ~1.7k tokens per turn
on a 3-turn scratch session. The rule is the obvious one — if the EXACT text is
already in the transcript the model is about to receive, it does not need it again:

  * unchanged block  -> not repeated (the model still sees the old copy);
  * CHANGED block    -> sent (a new task list or a new memory is information);
  * empty history    -> sent (first turn, or a session after a compaction that
                        removed the old copy — self-healing, no memo to go stale);
  * the meter asks the SAME function, so its number cannot disagree with the wire.

Deterministic, no live model, no network, no server.
"""
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="sf-v932-")
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
from longrun.memory import memory              # noqa: E402
from longrun.model import prompt               # noqa: E402

results = []
SID = "932d7d1d0e77"
STATE_MARK = "Harness state (your persistent task list):"


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""))


def _read(*p):
    with open(os.path.join(REPO, *p), encoding="utf-8") as fh:
        return fh.read()


memory.core_write("the deploy target is the dgx spark box")
sess = {"id": SID, "messages": [], "created": 1.0,
        "workspace": os.path.join(TMP, "ws")}
os.makedirs(sess["workspace"], exist_ok=True)

full = agent.user_turn_context(session_id=SID, sess=sess)
check("A1 the first turn carries both blocks",
      STATE_MARK in full and "Core memory" in full, full[:60])

# the transcript the NEXT turn would build on: one user message carrying those bytes
hist = [{"role": "user", "content": "ask", "wire": "ask\n\n" + full},
        {"role": "assistant", "content": "reply"}]
_again = agent.user_turn_context(session_id=SID, sess=sess, history=hist)
check("A2 an UNCHANGED block already in the history is not repeated",
      _again == "", repr(_again[:80]))

# a memory write changes the memory block -> it IS information, so it goes again
memory.store("agent.note", "v932 probe note that must travel once", origin="agent")
_changed = agent.user_turn_context(session_id=SID, sess=sess, history=hist)
check("A3 a CHANGED memory block is sent again",
      "Core memory" in _changed or "memory" in _changed.lower(), _changed[:80])
check("A4 ...and the unchanged task list is still not repeated",
      STATE_MARK not in _changed, _changed[:80])

# a history that lost the block (compaction) brings it back without a memo
check("A5 after a compaction (block gone) the block is sent again",
      STATE_MARK in agent.user_turn_context(session_id=SID, sess=sess, history=[]))
check("A6 a caller that passes no history keeps the old behaviour",
      STATE_MARK in agent.user_turn_context(session_id=SID, sess=sess))

_old = [{"role": "user", "content": "ask",
         "wire": "ask\n\nHarness state (your persistent task list):\nOLD — a different list"}]
check("A7 an OLD copy (different text) does not suppress the current block",
      STATE_MARK in agent.user_turn_context(session_id=SID, sess=sess, history=_old))

# ---- B. one owner: the wiring -------------------------------------------------
_src = _read("src", "longrun", "agent", "agent.py")
check("B1 assemble_turn passes the transcript it builds on",
      "history=transcript" in _src)
check("B2 no second decision was added: the meter calls the same function",
      "history=sess.get(\"messages\") or []" in _read("src", "longrun", "core", "httpapi.py"))
check("B3 an empty block list appends NOTHING (no trailing blank lines)",
      "if _extra:" in _src and "if _extra else" in _read("src", "longrun", "core", "httpapi.py"))

print("%d/%d checks" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
