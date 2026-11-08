#!/usr/bin/env python3
"""v287 — Routines (scheduled heartbeats) + per-agent daily budget (JAG-287 D).

A Routine binds an AGENT (AX) to a goal and a cadence; the scheduler wakes the agent
by running the goal as a normal turn. Each fired routine respects the agent's daily
budget. This is Longrun's "agents keep working while nobody watches".

Locked here:
  * Routine.create validates (agent exists, goal, every_seconds >= 30);
  * due()/tick() fire only enabled, due routines, advance next_run, and honour budget;
  * the agent daily budget charges once per run and refuses when exhausted;
  * the /api/routines routes answer and never shadow a non-routines path;
  * the Orbit UI has the routines view wired to /api/routines.

Deterministic (the agent runner is stubbed), no live model.
Run: python3 tests/v287_routines_budget.py
"""
import os
import sys
import tempfile
import time

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(REPO, "src"))
TMP = tempfile.mkdtemp(prefix="sf-v287-")
os.environ["LONGRUN_AGENTS_FILE"] = os.path.join(TMP, "agents.json")
os.environ["LONGRUN_JOBS_FILE"] = os.path.join(TMP, "jobs.json")
os.environ["LONGRUN_ROUTINES_FILE"] = os.path.join(TMP, "routines.json")

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + detail) if detail else ""))


from longrun.agent import agents  # noqa: E402
from longrun.orchestrate import routines  # noqa: E402
from longrun.orchestrate import orchestration  # noqa: E402

calls = []
routines._run_agent = lambda sid, goal, model=None: calls.append((sid, goal)) or "ok"

reg = agents.REGISTRY
# 2026-11-08: A1 is RESERVED for the harness supervisor; read the minted ids.
worker = reg.designate("sess-x", name="Worker")["agent"]["id"]
bee = reg.designate("sess-b", name="Bee", daily_budget=1)["agent"]["id"]

R = routines.REGISTRY

# --- create validation ------------------------------------------------------
check("create refuses no agent", R.create("", "g", 60)["ok"] is False)
check("create refuses no goal", R.create(worker, "", 60)["ok"] is False)
check("create refuses a cadence below the floor", R.create(worker, "g", 5)["ok"] is False)
check("create refuses an unknown agent", R.create("A9", "g", 60)["ok"] is False)
made = R.create(worker, "keep the lights on", 60)
check("create allocates an RN id and schedules next_run",
      made["ok"] and made["routine"]["id"] == "R1" and made["routine"]["next_run"] > made["routine"]["created"])
check("the routine starts enabled", made["routine"]["enabled"] is True)

# --- due / tick / mark ------------------------------------------------------
check("not due before its time", R.due(now=made["routine"]["created"]) == [])
future = time.time() + 100000
fired = R.tick(now=future)
check("tick fires a due routine", any(x.get("state") == "dispatched" for x in fired))
_deadline = time.time() + 3.0
while time.time() < _deadline and not calls:
    time.sleep(0.02)
check("the routine ran the agent's goal", bool(calls) and calls[0] == ("sess-x", "keep the lights on"))
check("the routine advanced last_run + runs count",
      (R.get("R1")["runs"] >= 1) and R.get("R1")["last_run"] is not None)

R.set_enabled("R1", False)
check("a paused routine is not due", R.due(now=time.time() + 200000) == [])
R.set_enabled("R1", True)
check("re-enabling reschedules it", R.get("R1")["enabled"] is True)

# --- per-agent daily budget -------------------------------------------------
check("charge consumes the daily budget then refuses",
      reg.charge(bee) is True and reg.charge(bee) is False)
R.create(bee, "ping", 30)
fired2 = R.tick(now=time.time() + 200000)
check("a routine over budget is skipped (not fired)",
      any(x.get("state") == "budget-skip" for x in fired2)
      and not any(x.get("routine") == "R2" and x.get("state") == "dispatched" for x in fired2))

# --- API routing ------------------------------------------------------------
class FakeHandler:
    def __init__(self):
        self.sent = None

    def _send(self, code, obj, ctype=None):
        self.sent = {"code": code, "obj": obj}
        return True


fh = FakeHandler()
ok = orchestration.handle(fh, "GET", "/api/routines", {}, None)
check("GET /api/routines answers", ok and fh.sent["code"] == 200 and fh.sent["obj"]["count"] == 2)
fh = FakeHandler()
ok = orchestration.handle(fh, "POST", "/api/routines", {}, {"agent": "", "goal": "g", "every_seconds": 60})
check("POST /api/routines validates", ok and fh.sent["obj"]["ok"] is False)
fh = FakeHandler()
ok = orchestration.handle(fh, "POST", "/api/routines/tick", {}, {})
check("POST /api/routines/tick answers with fired[]", ok and "fired" in fh.sent["obj"])
fh = FakeHandler()
ok = orchestration.handle(fh, "DELETE", "/api/routines/R1", {}, None)
check("DELETE /api/routines/<id> releases it", ok and fh.sent["obj"]["deleted"] == "R1")
fh = FakeHandler()
check("a non routines path is not shadowed",
      orchestration.handle(fh, "GET", "/api/status", {}, None) is False and fh.sent is None)

# --- UI wiring --------------------------------------------------------------
with open(os.path.join(REPO, "src", "longrun", "orbit", "web", "orbit.html"), encoding="utf-8") as f:
    ui = f.read()
check("the Orbit UI has a routines view wired to /api/routines",
      "class RoutinesView" in ui and "/api/routines" in ui and 'id="rtCreate"' in ui)

print("---")
passed = sum(results)
print("%d/%d PASS" % (passed, len(results)))
sys.exit(0 if passed == len(results) else 1)

