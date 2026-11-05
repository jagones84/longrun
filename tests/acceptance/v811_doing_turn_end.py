#!/usr/bin/env python3
"""v811 — a todo cannot claim to be `doing` when no turn is running.

`doing` means "this step is being worked RIGHT NOW", but only the model ever moved
a node out of it. A turn that stopped, was aborted, or simply forgot left the claim
standing — measured live 2026-11-04: 13 `doing` nodes, the UI refusing to paint them
live while the data still said "in progress". The turn bracket already knows the
truth (`_ACTIVE_CHAT`), so the correction is attached to its single release point:

  A) ending the turn demotes every `doing` node to `todo` (state only — no close,
     no plan change, no fabricated evidence);
  B) a turn REPLACED by a newer one does not touch the newer turn's steps;
  C) `publish_done=False` (the streaming path) does not emit a second `chat.done`;
  D) the streaming path uses `turn_end` instead of its own manual pop;
  E) a session with no graph is a clean no-op.

Deterministic, no live model, no network, no server.
"""
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="sf-v811-")
os.environ["LONGRUN_CONFIG_DIR"] = os.path.join(TMP, "cfg")
os.environ["LONGRUN_SESSIONS_DIR"] = os.path.join(TMP, "sessions")
os.environ["LONGRUN_DATA_DIR"] = os.path.join(TMP, "data")
os.environ["LONGRUN_DB"] = os.path.join(TMP, "events.db")
os.environ["LONGRUN_GRAPH_DIR"] = os.path.join(TMP, "graphs")
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.core import server                # noqa: E402,F401 — breaks the import cycle
from longrun.core import events               # noqa: E402
from longrun.plan import taskgraph            # noqa: E402

results = []
SEEN = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""))


# never touch the store / the feed: record instead
events.publish = lambda kind, **d: SEEN.append(kind)
taskgraph._publish = lambda kind, **d: None


def _nodes(sid):
    return {n["id"]: n for n in (taskgraph.load(sid) or {}).get("nodes", [])}


# ------------------------------------ A. the ended turn demotes its steps -----
g = taskgraph.ensure("turn-a", session_id="turn-a")
a = taskgraph.add_node(g, "step one")
b = taskgraph.add_node(g, "step two")
taskgraph.update_node(g, a["id"], status="doing")
taskgraph.update_node(g, b["id"], status="doing")
tok = events.turn_begin("turn-a")
events.turn_end("turn-a", tok)
n = _nodes("turn-a")
check("A1 every 'doing' step goes back to todo",
      n[a["id"]]["status"] == "todo" and n[b["id"]]["status"] == "todo",
      (n[a["id"]]["status"], n[b["id"]]["status"]))
check("A2 the correction names itself as the source",
      n[a["id"]]["source"] == "harness:turn-end", n[a["id"]].get("source"))
check("A3 it is NOT a close (no evidence invented)",
      not (n[a["id"]].get("evidence") or []), n[a["id"]].get("evidence"))
check("A4 the plan did not move", n[a["id"]]["plan"] == g["plan"], n[a["id"]]["plan"])
check("A5 the turn is no longer running", "turn-a" not in events._ACTIVE_CHAT)

# a step in an OLD plan is a stale claim too
taskgraph.update_node(g, b["id"], status="doing")
taskgraph.begin_plan(g)
events.turn_end("turn-a")          # legacy call: no token
check("A6 an old-plan 'doing' is corrected too",
      _nodes("turn-a")[b["id"]]["status"] == "todo", _nodes("turn-a")[b["id"]]["status"])

# ------------------------------- B. a newer turn owns the steps it works ------
g2 = taskgraph.ensure("turn-b", session_id="turn-b")
c = taskgraph.add_node(g2, "the step the NEW turn is on")
taskgraph.update_node(g2, c["id"], status="doing")
tok1 = events.turn_begin("turn-b")
tok2 = events.turn_begin("turn-b")      # replaces the registration
events.turn_end("turn-b", tok1)         # the OLD turn finishes late
check("B1 a late old turn does not touch the newer turn's step",
      _nodes("turn-b")[c["id"]]["status"] == "doing", _nodes("turn-b")[c["id"]]["status"])
check("B2 the newer turn still owns the session", "turn-b" in events._ACTIVE_CHAT)
events.turn_end("turn-b", tok2)
check("B3 when the real owner ends, the step is corrected",
      _nodes("turn-b")[c["id"]]["status"] == "todo", _nodes("turn-b")[c["id"]]["status"])

# ------------------------------------------ C. no duplicate chat.done ---------
SEEN.clear()
tok3 = events.turn_begin("turn-c")
SEEN.clear()
events.turn_end("turn-c", tok3, publish_done=False)
check("C1 publish_done=False emits no chat.done", "chat.done" not in SEEN, SEEN)
tok4 = events.turn_begin("turn-c")
SEEN.clear()
events.turn_end("turn-c", tok4)
check("C2 the default still emits chat.done", "chat.done" in SEEN, SEEN)

# -------------------------------------------------- D. the streaming path -----
http = open(os.path.join(REPO, "src", "longrun", "core", "httpapi.py"), encoding="utf-8").read()
check("D1 the stream releases through turn_end",
      "turn_end(sess[\"id\"], _turn_tok, publish_done=False)" in http)
check("D2 the manual pop is gone from the stream teardown",
      "if (_ACTIVE_CHAT.get(sess[\"id\"]) or {}).get(\"tok\") is _turn_tok:" not in http)

# ------------------------------------------------------- E. no graph, no crash
events.turn_end("turn-without-graph")
check("E1 a session with no graph is a clean no-op", True)

print("---")
passed = sum(results)
print("%d/%d PASS" % (passed, len(results)))
sys.exit(0 if passed == len(results) else 1)
