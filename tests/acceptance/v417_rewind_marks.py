#!/usr/bin/env python3
"""v417 — turn-anchored rewind: one checkpoint per USER message (JAG-426 · Domain 2).

The harness could snapshot plan/tasks/transcript at RUN start but had no anchor at
the user-message boundary, so "put the session back to before my Nth message" was
impossible. This pins the anchor half: an idempotent, ordered, restorable snapshot
per turn that degrades instead of raising.

Deterministic, no live server. Run: python3 tests/v417_rewind_marks.py
"""
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="sf-v417-")
os.environ["LONGRUN_CONFIG_DIR"] = os.path.join(TMP, "cfg")
os.environ["LONGRUN_SESSIONS_DIR"] = os.path.join(TMP, "sessions")
os.environ["LONGRUN_EDITS_DIR"] = os.path.join(TMP, "edits")
os.environ["LONGRUN_RUNS_DIR"] = os.path.join(TMP, "runs")
os.environ["LONGRUN_DB"] = os.path.join(TMP, "events.db")
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.core import server as s            # noqa: E402
from longrun.memory import checkpoints          # noqa: E402
from longrun.memory import rewind               # noqa: E402

# keep the checkpoint store hermetic (it is otherwise REPO/data/checkpoints)
checkpoints.CKPT_DIR = os.path.join(TMP, "ckpt")

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""))


s.get_or_create_session("v417s", title="v417 session")

# ---- 1. one mark per user message, idempotent + ordered ---------------------
rewind.mark("v417s", 0)
rewind.mark("v417s", 2)
rewind.mark("v417s", 0)          # repeat: must NOT create a second mark
ms = rewind.marks("v417s")
check("1a a repeat mark is idempotent (2 marks, not 3)", len(ms) == 2, [m.get("msg_index") for m in ms])
check("1b the marks are ordered by msg_index",
      [m["msg_index"] for m in ms] == [0, 2])
check("1c each mark is a turn anchor with an event high-water mark",
      all(m.get("kind") == "turn" and isinstance(m.get("events_upto"), int) for m in ms))

# ---- 2. the snapshot carries the PRE-turn transcript ------------------------
m0 = ms[0]
payload = checkpoints.load_payload(m0["id"]) or {}
check("2 the anchor snapshots the session transcript",
      (payload.get("session") or {}).get("id") == "v417s"
      and payload.get("session", {}).get("messages") == [])

# ---- 3. degradation: no raise, no anchor for a missing session --------------
bad = rewind.mark("no-such-session", 0)
check("3a marking a missing session errors cleanly (no raise)",
      isinstance(bad, dict) and "error" in bad, bad)
check("3b no marks are recorded for a missing session",
      rewind.marks("no-such-session") == [])
check("3c mark(None) is a clean no-op", rewind.mark(None, 0) is None)

# ---- 4. the anchor is RESTORABLE (rollback puts the transcript back) --------
sess = s.load_session("v417s")
s.append_message(sess, "user", "hello from the future")
s.append_message(sess, "assistant", "and a reply")
check("4a the session grew after the anchor",
      len((s.load_session("v417s") or {}).get("messages", [])) == 2)
checkpoints.rollback(m0["id"])
check("4b rolling the anchor back restores the pre-turn transcript",
      len((s.load_session("v417s") or {}).get("messages", [])) == 0)

print("---")
okc = sum(results)
print("\nv417: %d/%d PASS" % (okc, len(results)))
sys.exit(0 if okc == len(results) else 1)
