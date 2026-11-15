#!/usr/bin/env python3
"""v1065 — a run killed by a restart is CLOSED, and the work that SURVIVED says so.

Operator, 2026-11-16: *"there are agents that stop unexpectedly that's the worst thing
can happen"* / *"i want runs survive restart — it's a tech spec prerequisite"*.

Two facts, one record:
  * the PROCESS that owned a run died with the restart — its row cannot keep saying
    `running` (measured: 182 rows, the oldest 2026-09-29, served by `/api/runs` as live);
  * the WORK does not die: `inflight.recover` delivers the `[Harness restart]` turn and the
    task graph is a file. A row whose session was actually continued is therefore marked
    `resumed` (with a `restart.resumed` span), never left reading "stopped".

  A  a run older than the boot cut is closed as `interrupted`
  B  a run started by THIS boot is never touched
  C  a finished run is untouched, and the sweep is idempotent
  D  the closed status is what `/api/runs` serves
  E  the boot runs the sweep, and records the RESUMED rows after the recovery
  F  the interrupted-turn notice says the harness resumes automatically
  G  a run whose session was continued becomes `resumed`, not `interrupted`
"""
import json
import os
import sqlite3
import sys
import tempfile
import time

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_TMP = tempfile.mkdtemp(prefix="sf-v1065-")
for _k in ("DATA_DIR", "CONFIG_DIR", "SESSIONS_DIR", "EDITS_DIR", "RUNS_DIR",
           "GRAPH_DIR", "ROLES_DIR", "COSTS_DIR", "THREADS_DIR"):
    os.environ["LONGRUN_" + _k] = os.path.join(_TMP, _k)
    os.makedirs(os.path.join(_TMP, _k), exist_ok=True)
os.environ["LONGRUN_DB"] = os.path.join(_TMP, "events.db")
os.environ["LONGRUN_AGENTS_FILE"] = os.path.join(_TMP, "agents.json")
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.core import events  # noqa: E402
from longrun.util import tracing  # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""))


def add_run(rid, ts, status="running"):
    events.db().execute(
        "INSERT INTO runs(id, kind, goal, model, ts, status) VALUES(?,?,?,?,?,?)",
        (rid, "chat", "a goal", "m", ts, status))
    events.db().commit()


def status_of(rid):
    return events.db().execute("SELECT status FROM runs WHERE id=?", (rid,)).fetchone()[0]


now = time.time()
add_run("old-running", now - 3600)
add_run("boot-running", now - 1)          # newer than the cut = started by this boot
add_run("old-done", now - 3600, status="done")
add_run("old-error", now - 3600, status="error")

cut = now - 60
res = tracing.reconcile_orphans(before=cut)
check("A1 the killed run is closed as interrupted",
      res.get("ok") is True and res.get("closed") == 1
      and res.get("ids") == ["old-running"] and status_of("old-running") == "interrupted", res)
check("B1 a run started by this boot is never touched",
      status_of("boot-running") == "running", status_of("boot-running"))
check("C1 a finished run keeps its own status",
      status_of("old-done") == "done" and status_of("old-error") == "error")
again = tracing.reconcile_orphans(before=cut)
check("C2 the sweep is idempotent", again.get("closed") == 0
      and status_of("old-running") == "interrupted", again)

summary = {r["run_id"]: r["status"] for r in tracing.runs_summary(20)}
check("D1 `/api/runs` serves the closed status, not `running`",
      summary.get("old-running") == "interrupted" and summary.get("boot-running") == "running",
      summary)

api = open(os.path.join(REPO, "src", "longrun", "core", "httpapi.py"), encoding="utf-8").read()
boot = api.index("reconcile_orphan_turns()")
sweep = api.index("_tracing_boot.reconcile_orphans(before=time.time())")
check("E1 the boot closes orphaned runs, right after the session reconcile",
      sweep > boot and "_tracing_boot.reconcile_orphans" in api and sweep - boot < 2000,
      (boot, sweep))
check("E3 the boot records which runs were RESUMED, after the recovery",
      "_tracing_resumed.mark_resumed" in api
      and api.index("_tracing_resumed.mark_resumed") > api.index("_inflight.recover("),
      api.count("_tracing_resumed.mark_resumed"))

# ── G: the run whose SESSION was continued did not end — it survived ────────
add_run("killed-continued", now - 3600)
add_run("killed-alone", now - 3600)
events.db().execute(
    "INSERT INTO events(ts, kind, data) VALUES(?,?,?)",
    (now, "chat.run", json.dumps({"run_id": "killed-continued", "session": "s-continued"})))
events.db().commit()
tracing.reconcile_orphans(before=cut)
resumed = tracing.mark_resumed(["s-continued"])
check("G1 a run whose session was continued is marked `resumed`",
      resumed.get("marked") == 1 and status_of("killed-continued") == "resumed", resumed)
spans = json.loads(events.db().execute(
    "SELECT spans FROM runs WHERE id='killed-continued'").fetchone()[0])
check("G2 the record says WHAT took over",
      any(s.get("name") == "restart.resumed" and s.get("session") == "s-continued"
          for s in spans), spans)
check("G3 a run with no continuation keeps `interrupted`",
      status_of("killed-alone") == "interrupted", status_of("killed-alone"))
check("G4 marking again changes nothing", tracing.mark_resumed(["s-continued"]).get("marked") == 0)

tr = open(os.path.join(REPO, "src", "longrun", "util", "tracing.py"), encoding="utf-8").read()
check("E2 `Run.finish` is no longer the ONLY writer of the status",
      tr.count("UPDATE runs SET") == 3 and "def reconcile_orphans" in tr
      and "def mark_resumed" in tr,
      tr.count("UPDATE runs SET"))

stores = open(os.path.join(REPO, "src", "longrun", "memory", "stores.py"), encoding="utf-8").read()
check("F1 the interrupted-turn notice does not claim the turn is lost",
      "the harness resumes it automatically" in stores
      and "if nothing follows, send a new message to continue" in stores)

print("\n---\nv1065: %d/%d PASS" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
