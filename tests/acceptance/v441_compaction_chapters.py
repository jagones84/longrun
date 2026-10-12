#!/usr/bin/env python3
"""v441 — auto-compaction keeps the thread's Free.* names/summaries (JAG-431q).

The harness AUTO-compacts the stored transcript IN PLACE at the start of a turn when
the context is over threshold (`httpapi.prepare_session_for_turn` -> `compact_session`):
older turns collapse into one summary message. Any state that lived only in the
transcript prose is therefore destroyed at that moment — so a free group's
title/summary must (a) live in the durable thread LEDGER and (b) be carried on the
message that STARTS the group, written BEFORE the rewrite.

This drives the REAL auto path end to end (no live server, no network) and asserts both,
plus that the agent can still recall everything with `chapters` AFTER the compaction.

Run: python3 tests/acceptance/v441_compaction_chapters.py
"""
import os
import sys
import tempfile
import time

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="sf-v441-")
os.environ["LONGRUN_CONFIG_DIR"] = os.path.join(TMP, "cfg")
os.environ["LONGRUN_SESSIONS_DIR"] = os.path.join(TMP, "sessions")
os.environ["LONGRUN_GRAPH_DIR"] = os.path.join(TMP, "graphs")
os.environ["LONGRUN_THREADS_DIR"] = os.path.join(TMP, "threads")
os.environ["LONGRUN_DB"] = os.path.join(TMP, "events.db")
for d in ("cfg", "sessions", "graphs", "threads"):
    os.makedirs(os.path.join(TMP, d), exist_ok=True)
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.memory import stores            # noqa: E402
from longrun.memory import threads as th     # noqa: E402
from longrun.plan import taskgraph           # noqa: E402
from longrun.tools import tools as T         # noqa: E402
from longrun.core import server as _srv      # noqa: E402,F401  (httpapi<->server import order)
from longrun.core import httpapi             # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""))


def _chapters(sess):
    return [m.get("chapter") for m in (sess.get("messages") or []) if m.get("chapter")]


# ---- 1. a naturally grown session: two free threads + a task, both titled -----
sid = "v441-sess"
stores.save_session({"id": sid, "title": "c", "created": time.time(), "messages": []})
sess = stores.load_session(sid)
stores.append_message(sess, "user", "first free request about widgets")
stores.append_message(sess, "assistant", "answer one. " + ("filler " * 700))
g = taskgraph.ensure(sid)
n1 = taskgraph.add_node(g, "do the thing", status="done", evidence="did it, verified")
taskgraph.save(g)
stores.append_message(sess, "assistant", "task note", meta={"node": n1["id"]})
stores.persist_tool_card(sess, "shell", True, args={"command": "ls"}, result="ok", node=n1["id"])
stores.append_message(sess, "user", "second free request about gadgets")
stores.append_message(sess, "assistant", "answer two")

free = [x for x in th.outline(sid) if x["kind"] == "free"]
check("1a the session grew two free threads + one task",
      len(free) == 2 and any(x["kind"] == "task" for x in th.outline(sid)),
      [x["kind"] for x in th.outline(sid)])
th.set_title(sid, free[0]["id"], "request to ask about widgets", summary="asked about widgets; answered")
th.set_title(sid, free[1]["id"], "request to ask about gadgets", summary="asked about gadgets; answered")
stores.save_session(sess)          # choke point -> chapters onto the start messages

before = stores.load_session(sid)
check("1b both titles+summaries are in the durable ledger",
      all((x.get("title") or "").startswith("request to ask about")
          for x in th.outline(sid) if x["kind"] == "free"),
      [x.get("title") for x in th.outline(sid) if x["kind"] == "free"])
check("1c both chapters were written to the transcript BEFORE any compaction",
      len(_chapters(before)) == 2, _chapters(before))
groups_before = len(th.outline(sid))
msgs_before = len(before["messages"])

# ---- 2. drive the REAL auto-compaction trigger --------------------------------
caught = []
httpapi.publish = lambda kind, **kw: caught.append((kind, kw))          # capture events
httpapi._summarize_with_llm = lambda messages, model=None, meta=None: None  # no network
httpapi.AUTOCOMPACT_PCT = -1.0            # every session reads as 'over threshold'
httpapi.context_budget = lambda alias=None: 1500                          # a small window
after = httpapi.prepare_session_for_turn(before, model=None)

check("2a over-threshold triggers AUTO-compaction", any(k == "context.auto_compact" for k, _ in caught),
      [k for k, _ in caught])
check("2b the transcript really SHRANK", len(after["messages"]) < msgs_before,
      (msgs_before, len(after["messages"])))
check("2c the auto event reports what it compacted",
      any(k == "context.auto_compact" and kw.get("compacted") for k, kw in caught),
      [kw.get("compacted") for k, kw in caught if k == "context.auto_compact"])

# ---- 3. what survived the horizon --------------------------------------------
check("3a the ledger still holds EVERY group (compaction-proof)", len(th.outline(sid)) == groups_before,
      (groups_before, len(th.outline(sid))))
check("3b every free group still has its title+summary after compaction",
      all((x.get("title") or "").startswith("request to ask about") and x.get("summary")
          for x in th.outline(sid) if x["kind"] == "free"),
      [(x.get("title"), x.get("summary")) for x in th.outline(sid) if x["kind"] == "free"])
check("3c a task's evidence (its justification) survives too",
      any((n.get("evidence") or []) and n["evidence"][-1].get("text") == "did it, verified"
          for n in (taskgraph.load(sid) or {}).get("nodes", [])))
kept = _chapters(after)
check("3d the RETAINED free thread still carries its chapter (rides the transcript)",
      any((c.get("title") or "") == "request to ask about gadgets" for c in kept), kept)

# ---- 4. the agent's recall AFTER the compaction -------------------------------
r = T.execute("chapters", {"session": sid, "action": "list"}, run_id=sid)
out = r.get("stdout") or ""
check("4a chapters list still returns the free groups' titles+summaries",
      "request to ask about widgets" in out and "request to ask about gadgets" in out, out[:0])
check("4b chapters list still returns the task's justification",
      "why: \u201cdid it, verified" in out, out[:0])
r = T.execute("chapters", {"session": sid, "action": "read", "id": free[0]["id"]}, run_id=sid)
check("4c chapters read still returns a compacted-away group's title+summary",
      "title: request to ask about widgets" in (r.get("stdout") or "")
      and "summary: asked about widgets" in (r.get("stdout") or ""), (r.get("stdout") or "")[:60])

print("---")
okc = sum(results)
print("\nv441: %d/%d PASS" % (okc, len(results)))
sys.exit(0 if okc == len(results) else 1)
