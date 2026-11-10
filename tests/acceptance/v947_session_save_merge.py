#!/usr/bin/env python3
"""v947 — a stale writer cannot erase the other writer's messages.

A turn saves its own dict at the end; a job handoff/escalation writes an inject
into a session dict it read from another thread. `save_session` wrote the WHOLE
document from whichever copy arrived last, so the loser's list vanished: a
coordinator's deliverable disappeared from the transcript while
`runs[coord].result` still held it, and a handoff written before a turn's save
was dropped on reload.

`save_session` now takes one lock per session for its read-merge-write, and adopts
the on-disk tail of `messages` / `injects` / `tool_cards` ONLY when the in-memory
list is a strict prefix of it (this copy read an older one and only added). A
rewritten head, a deletion or a compaction keeps the in-memory list: there the
writer is the authority and a merge would resurrect removed records.

Deterministic: temp stores, no server, no model, no network.
Run: python3 tests/acceptance/v947_session_save_merge.py
"""

import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="sf-v947-")
os.environ["LONGRUN_DATA_DIR"] = TMP
for _k in ("SESSIONS_DIR", "EDITS_DIR", "RUNS_DIR", "GRAPH_DIR", "ROLES_DIR", "CONFIG_DIR"):
    os.environ["LONGRUN_" + _k] = os.path.join(TMP, _k)
    os.makedirs(os.path.join(TMP, _k), exist_ok=True)
os.environ["LONGRUN_DB"] = os.path.join(TMP, "events.db")
os.environ["LONGRUN_JOBS_FILE"] = os.path.join(TMP, "jobs.json")
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.memory import stores as S  # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""))


def msg(text, role="user"):
    return {"role": role, "content": text, "ts": 1.0}


def fresh(sid, messages):
    sess = {"id": sid, "title": sid, "messages": messages}
    S.save_session(sess)
    return sess


# ---- A. a handoff writer must not rewind a turn's messages -----------------
SID = "v947a"
s = fresh(SID, [msg("one"), msg("two")])
handoff_view = S.load_session(SID)          # read BEFORE the turn saved
turn_view = S.load_session(SID)
turn_view["messages"].append(msg("three", "assistant"))
S.save_session(turn_view)                   # the turn saves its deliverable
S.persist_inject(handoff_view, "handoff", "worker could not finish")
disk = S.load_session(SID)
check("A1 the deliverable survives the handoff write",
      [m.get("content") for m in disk.get("messages") or []] == ["one", "two", "three"],
      [m.get("content") for m in disk.get("messages") or []])
check("A2 the handoff inject is persisted", len(disk.get("injects") or []) == 1,
      disk.get("injects"))
check("A3 the inject boundary counts the messages really on disk",
      (disk.get("injects") or [{}])[0].get("after") == 3,
      (disk.get("injects") or [{}])[0])

# ---- B. the mirror case: a turn save must not drop a handoff -----------------
SID = "v947b"
fresh(SID, [msg("one"), msg("two")])
turn_view = S.load_session(SID)             # the turn's copy: no inject yet
writer = S.load_session(SID)
S.persist_inject(writer, "escalation", "BACK TO YOU")   # a handoff lands in between
with S._turn_lock(SID):                     # the turn is the lock owner here
    S.save_session(turn_view)
disk = S.load_session(SID)
check("B1 the handoff inject survives the turn's save",
      len(disk.get("injects") or []) == 1, disk.get("injects"))
check("B2 the turn's own messages are intact",
      [m.get("content") for m in disk.get("messages") or []] == ["one", "two"],
      [m.get("content") for m in disk.get("messages") or []])

# ---- C. an authoritative rewrite is NOT resurrected -------------------------
SID = "v947c"
fresh(SID, [msg("one"), msg("two"), msg("three")])
rewrite = S.load_session(SID)
rewrite["messages"] = [msg("[summary of 3 messages]", "system")]
with S._turn_lock(SID):
    S.save_session(rewrite)
disk = S.load_session(SID)
check("C1 a rewritten transcript stays rewritten (no resurrection)",
      [m.get("content") for m in disk.get("messages") or []] == ["[summary of 3 messages]"],
      [m.get("content") for m in disk.get("messages") or []])

# ---- D. a deletion is not undone -------------------------------------------
SID = "v947d"
fresh(SID, [msg("one"), msg("two"), msg("three")])
shorter = S.load_session(SID)
shorter["messages"] = shorter["messages"][:1]
with S._turn_lock(SID):
    S.save_session(shorter)
disk = S.load_session(SID)
check("D1 a shorter in-memory list is not 'completed' back to the old one",
      len(disk.get("messages") or []) == 1, len(disk.get("messages") or []))

# ---- E. tool cards are adopted the same way --------------------------------
SID = "v947e"
fresh(SID, [msg("one")])
card_view = S.load_session(SID)
other = S.load_session(SID)
other.setdefault("tool_cards", []).append({"id": "c1", "tool": "shell", "after": 1})
S.save_session(other)
S.save_session(card_view)
disk = S.load_session(SID)
check("E1 a tool card written by another thread is not dropped",
      [c.get("id") for c in disk.get("tool_cards") or []] == ["c1"], disk.get("tool_cards"))

# ---- G. a WIPE is not a prefix (v534 A2 red since v947) ---------------------
SID = "v947g"
fresh(SID, [msg("one"), msg("two")])
wiped = S.load_session(SID)
wiped["messages"] = []
wiped["tool_cards"] = []
with S._turn_lock(SID):
    S.save_session(wiped, truncate=True)
disk = S.load_session(SID)
check("G1 a truncating save really empties the transcript",
      (disk.get("messages") or []) == [], disk.get("messages"))

SID = "v947h"
fresh(SID, [msg("one")])
S.persist_inject(S.load_session(SID), "handoff", "x")
S.clear_session(SID)
disk = S.load_session(SID)
check("G2 clear_session really clears messages, cards and injects",
      not (disk.get("messages") or disk.get("tool_cards") or disk.get("injects")), disk)

# ---- F. the lock is per session (one writer id does not block another) -----
check("F1 the same session id yields the same lock object",
      S._save_lock("x") is S._save_lock("x"))
check("F2 a different session id yields a different lock",
      S._save_lock("x") is not S._save_lock("y"))

print("TOTAL %d/%d" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
