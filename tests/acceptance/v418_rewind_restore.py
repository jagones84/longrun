#!/usr/bin/env python3
"""v418 — full turn rewind: transcript + plan + workspace + events (JAG-426 · D2).

`rewind(session, N)` must put the session back to exactly the state before user
message N: the transcript and plan/tasks from the anchor, the workspace files the
HARNESS edited (never the user's hand-edits), and the event log. It must be
idempotent and must keep a pre-rewind snapshot so the undo is undoable.

Deterministic, no live server. Run: python3 tests/v418_rewind_restore.py
"""
import os
import sys
import tempfile
import time

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="sf-v418-")
for _k in ("CONFIG_DIR", "SESSIONS_DIR", "EDITS_DIR", "RUNS_DIR", "GRAPH_DIR", "ROLES_DIR", "COSTS_DIR"):
    os.environ["LONGRUN_" + _k] = os.path.join(TMP, _k)
os.environ["LONGRUN_DB"] = os.path.join(TMP, "events.db")
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.core import server as s            # noqa: E402
from longrun.core import events                 # noqa: E402
from longrun.memory import checkpoints          # noqa: E402
from longrun.memory import rewind               # noqa: E402
from longrun.tools import edits                 # noqa: E402

checkpoints.CKPT_DIR = os.path.join(TMP, "ckpt")

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""))


# ---- arrange: a session with one turn already behind it ----------------------
s.get_or_create_session("v418s", title="v418 session")
s.save_plan({"steps": [{"id": "a", "status": "todo"}]})
s.save_plan({"steps": [{"id": "a", "status": "todo"}]})
rewind.mark("v418s", 0)                     # anchor: BEFORE the first user message
time.sleep(0.02)                            # ensure journal/event ts > the anchor ts

# the "turn" happens: transcript grows, plan changes, workspace is edited, event fires
sess = s.load_session("v418s")
s.append_message(sess, "user", "please edit the file")
s.append_message(sess, "assistant", "done")
s.save_plan({"steps": [{"id": "a", "status": "done"}, {"id": "b", "status": "todo"}]})

f_mod = os.path.join(TMP, "mod.txt")
with open(f_mod, "w", encoding="utf-8") as f:
    f.write("BEFORE\n")
with open(f_mod, "w", encoding="utf-8") as f:   # the harness now edits it
    f.write("AFTER\n")
edits.record("v418s", f_mod, "BEFORE\n", "AFTER\n", "modified")
f_new = os.path.join(TMP, "created.txt")
with open(f_new, "w", encoding="utf-8") as f:
    f.write("NEW\n")
edits.record("v418s", f_new, "", "NEW\n", "created")
f_hand = os.path.join(TMP, "hand.txt")
with open(f_hand, "w", encoding="utf-8") as f:
    f.write("HAND\n")                            # a user hand-edit: NOT in the journal
events.publish("test.marker", session="v418s", note="after the anchor")
events.publish("test.marker2", session="v418s", note="also after the anchor")

check("0 the turn really changed things",
      len((s.load_session("v418s") or {}).get("messages", [])) == 2
      and open(f_mod, encoding="utf-8").read() == "AFTER\n"
      and bool(events.query_events(session="v418s")))

# ---- act ---------------------------------------------------------------------
r = rewind.rewind("v418s", 0)

# ---- assert ------------------------------------------------------------------
check("1 rewind reports ok", r.get("ok") is True, str(r)[:140])
check("2 transcript is back to the pre-turn state",
      len((s.load_session("v418s") or {}).get("messages", [])) == 0)
check("3 the plan is restored from the anchor",
      [x["id"] for x in s.load_plan().get("steps", [])] == ["a"]
      and s.load_plan()["steps"][0]["status"] == "todo")
check("4 the harness's edit to an existing file is reverted",
      open(f_mod, encoding="utf-8").read() == "BEFORE\n")
check("5 a file the harness CREATED is removed",
      not os.path.exists(f_new))
check("6 a user hand-edit is left alone",
      open(f_hand, encoding="utf-8").read() == "HAND\n")
check("7 the events the rewound turn produced are dropped",
      not any(e.get("kind", "").startswith("test.")
              for e in events.query_events(session="v418s")),
      {"ev": r.get("events"),
       "left": [e.get("kind") for e in events.query_events(session="v418s")]})
check("8 a pre-rewind snapshot exists (undo the undo)",
      bool(r.get("pre_snapshot")) and checkpoints.get(r["pre_snapshot"]) is not None)

# ---- idempotence + clean errors ---------------------------------------------
r2 = rewind.rewind("v418s", 0)
check("9 rewinding the same anchor twice is idempotent",
      r2.get("ok") is True
      and len((s.load_session("v418s") or {}).get("messages", [])) == 0
      and open(f_mod, encoding="utf-8").read() == "BEFORE\n")
check("10 an unknown message index is a clean error",
      rewind.rewind("v418s", 99).get("ok") is False)
check("11 a missing session is a clean error",
      rewind.rewind("nope", 0).get("ok") is False)

print("---")
okc = sum(results)
print("\nv418: %d/%d PASS" % (okc, len(results)))
sys.exit(0 if okc == len(results) else 1)
