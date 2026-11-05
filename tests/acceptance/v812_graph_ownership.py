#!/usr/bin/env python3
"""v812 — a graph belongs to an OWNER (session or run) and dies with it.

A chat/agent turn keys its graph by the session, but a RUN keys it by the run id and
records the session inside `session_id`. The delete cascade only removed
`<sid>.json`, so run graphs outlived their chat. Measured live 2026-11-04: 198 of
248 graph files had no session and 589 nodes lived only there — unreachable from the
panel (bound to a session) and from `/api/runs/<id>/graph` (the run is gone).

  A) `files_for_session` finds every graph whose recorded owner is the session, and
     the delete cascade moves them into the recoverable trash with the transcript;
  B) `sweep_orphans` moves owner-less graphs older than the grace window to the
     same trash, keeps a LIVE session's graphs, keeps anything recent, and is
     idempotent;
  C) the server runs the sweep at startup (best-effort).

Deterministic, no live model, no network, no server.
"""
import json
import os
import sys
import tempfile
import time

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="sf-v812-")
os.environ["LONGRUN_CONFIG_DIR"] = os.path.join(TMP, "cfg")
os.environ["LONGRUN_SESSIONS_DIR"] = os.path.join(TMP, "sessions")
os.environ["LONGRUN_DATA_DIR"] = os.path.join(TMP, "data")
os.environ["LONGRUN_DB"] = os.path.join(TMP, "events.db")
os.environ["LONGRUN_GRAPH_DIR"] = os.path.join(TMP, "graphs")
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.core import server                # noqa: E402,F401 — breaks the import cycle
from longrun.plan import taskgraph             # noqa: E402
from longrun.memory import stores              # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""))


G = taskgraph.GRAPH_DIR
TRASH = os.path.join(os.environ["LONGRUN_DATA_DIR"], "trash")
os.makedirs(G, exist_ok=True)
os.makedirs(os.environ["LONGRUN_SESSIONS_DIR"], exist_ok=True)
taskgraph._publish = lambda *a, **k: None      # never touch the store in a unit test


def graph(name, session_id, age_days=0.0):
    key = name.split(".json", 1)[0]
    p = os.path.join(G, name)
    with open(p, "w", encoding="utf-8") as f:
        json.dump({"key": key, "run_id": key, "session_id": session_id,
                   "nodes": [], "plan": 1, "plan_base": 1}, f)
    if age_days:
        t = time.time() - age_days * 86400
        os.utime(p, (t, t))
    return p


# ------------------------------------------------------- A. ownership lookup ---
graph("s2.json", "s2")
r2 = graph("run_e.json", "s2")                 # run graph of session s2
graph("run_f.json", "")                        # unrelated
found = taskgraph.files_for_session("s2")
check("A1 the session's own graph is found",
      os.path.join(G, "s2.json") in found, found)
check("A2 the RUN graph that records the session is found", r2 in found, found)
check("A3 an unrelated graph is not", os.path.join(G, "run_f.json") not in found, found)

stores._purge_session_artifacts("s2")
check("A4 the delete cascade removes the session graph",
      not os.path.exists(os.path.join(G, "s2.json")),
      sorted(os.listdir(G)))
check("A5 the delete cascade removes its run graph too",
      not os.path.exists(r2), sorted(os.listdir(G)))
check("A6 both land in the recoverable trash",
      os.path.exists(os.path.join(TRASH, "s2.json")) and
      os.path.exists(os.path.join(TRASH, "run_e.json")), sorted(os.listdir(TRASH)))
check("A7 an unrelated graph is untouched", os.path.exists(os.path.join(G, "run_f.json")))

# ------------------------------------------------------------- B. the sweep ---
for fn in list(os.listdir(G)):
    os.remove(os.path.join(G, fn))
graph("live.json", "live")                      # the live session's own graph
graph("run_live.json", "live")                  # a run graph of the LIVE session
graph("run_old_empty.json", "", age_days=40)    # orphan, no owner id
graph("run_old_self.json", "run_old_self", age_days=40)   # orphan, owner = itself
graph("run_new.json", "", age_days=0)           # orphan but RECENT
graph("dead.json.reset-1700000000", "dead", age_days=40)  # archived dead graph

res1 = taskgraph.sweep_orphans(known_sessions={"live"}, older_than_days=14)
moved1 = set(res1["moved"])
check("B1 an owner-less old graph is swept", "run_old_empty.json" in moved1, res1)
check("B2 a run graph whose owner IS the file itself is swept",
      "run_old_self.json" in moved1, res1)
check("B3 a reset archive of a dead session is swept",
      "dead.json.reset-1700000000" in moved1, res1)
check("B4 the live session's graph is kept", "live.json" not in moved1, res1)
check("B5 a live session's RUN graph is kept", "run_live.json" not in moved1, res1)
check("B6 a RECENT orphan is kept (grace window)", "run_new.json" not in moved1, res1)
check("B7 the swept files are in the trash, not deleted",
      os.path.exists(os.path.join(TRASH, "run_old_empty.json")), sorted(os.listdir(TRASH)))
check("B8 the originals are gone", not os.path.exists(os.path.join(G, "run_old_empty.json")))

res2 = taskgraph.sweep_orphans(known_sessions={"live"}, older_than_days=14)
check("B9 the sweep is idempotent", res2["moved"] == [], res2)

res3 = taskgraph.sweep_orphans(known_sessions={"live"}, older_than_days=0)
check("B10 the grace window is what protected the recent orphan",
      "run_new.json" in set(res3["moved"]), res3)

# ----------------------------------------------- C. wired at server start -----
http = open(os.path.join(REPO, "src", "longrun", "core", "httpapi.py"), encoding="utf-8").read()
check("C1 the server sweeps at startup", "_tg_boot.sweep_orphans()" in http)
tap = open(os.path.join(REPO, "src", "longrun", "memory", "stores.py"), encoding="utf-8").read()
check("C2 the delete cascade consults the owner lookup",
      "taskgraph.files_for_session(sid)" in tap)

print("---")
passed = sum(results)
print("%d/%d PASS" % (passed, len(results)))
sys.exit(0 if passed == len(results) else 1)
