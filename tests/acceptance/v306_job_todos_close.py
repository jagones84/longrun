#!/usr/bin/env python3
"""v306 — a completed turn must NEVER leave a plan nobody authored or closes.

Root cause of "the chat/job finished with OPEN todos" (traced on data/events.db and
PROVEN on kb-agent session 55a29fae70cb):

  * JAG-76 (`chat_stream_gen` end): when the model answered with PROSE (no
    `write_todos`), a BACKGROUND fallback planner generated a plan FROM THE TURN'S
    MESSAGE — AFTER the turn was already over.
  * Its steps therefore describe work that was already done (or never attempted);
    nobody executes them and JAG-173 forbids the harness from auto-closing a step.
  * The next turn's JAG-189 "stale plan" rule (`user_pivot`) then exempted them from
    the JAG-402 close-todo enforcement -> they dangled as OPEN forever.

Proof: the reply landed at ts=1791835170.33 and `graph.node.added` fired at
ts=1791835195..200 — three orphan todos created ~25 s AFTER the answering turn.

The fix is NOT to force-close steps (tried and rejected) but to never CREATE a plan
the model did not author: JAG-431n removed the end-of-turn fallback planner. The
graph is now written ONLY by the model (`write_todos`) or by the operator — the
explicit sync `/api/chat` path, which also FINALIZES its plan (so it cannot dangle).

Locked here:
  * the auto-plan gate `_should_autoplan` is GONE (function + re-export);
  * the stream path no longer spawns a background planner after the reply;
  * the only planner call left is the explicit sync `/api/chat` path;
  * `plan.incomplete` counts only TRULY-open steps (not superseded);
  * the rejected external sweep (`_close_job_todos`) is gone.

Deterministic, no live model. Run: python3 tests/acceptance/v306_job_todos_close.py
"""
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(REPO, "src"))

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""))


def read(*parts):
    with open(os.path.join(REPO, *parts), encoding="utf-8") as f:
        return f.read()


http = read("src", "longrun", "core/httpapi.py")
srv = read("src", "longrun", "core/server.py")
jobs = read("src", "longrun", "orchestrate/jobs.py")

# --- the end-of-turn fallback planner is GONE (JAG-431n) ----------------------
check("the auto-plan gate is GONE (function + re-export)",
      "def _should_autoplan(" not in http and "_should_autoplan" not in srv)
check("no background fallback planner is spawned after a reply",
      "target=start_run_graph" not in http)
check("the ONLY planner call left is the explicit sync /api/chat path",
      http.count("start_run_graph(") == 1, "calls=%d" % http.count("start_run_graph("))
check("nothing in the stream turn creates graph nodes on its own",
      "graph_post(" not in http.split("def chat_stream_gen")[1].split("def ")[0]
      if "def chat_stream_gen" in http else False)

# --- invariants that were already right stay right ---------------------------
check("plan.incomplete counts only TRULY-open steps (not superseded)",
      'not in ("done", "cancelled")' not in (http + srv))
check("the rejected external sweep is gone",
      "def _close_job_todos" not in jobs and "todos_closed" not in jobs)

print("---")
passed = sum(results)
print("%d/%d PASS" % (passed, len(results)))
sys.exit(0 if passed == len(results) else 1)
