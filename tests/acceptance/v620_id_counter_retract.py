#!/usr/bin/env python3
"""v620 — registry counters retract on delete-forever (no A10000).

Deletes popped the record but never touched `seq`, so A/J/R/T numbers grew
forever. Now ONE helper (`fswrite.retract_seq`) pulls the counter back to
the highest LIVE `n` inside every delete path:

  - deleting everything restarts at 1;
  - deleting the top pulls the counter back (next create reuses the number);
  - deleting from the middle changes nothing (the number stays dead — a new
    object must never inherit a deleted id's transcript history);
  - no live id is ever renamed or reused.

Sessions are uuid-hex (no counter) and todos already gap-fill per plan,
so only agents/jobs/routines/teams needed the fix.

Deterministic: temp registry files, no server, no model, no network.
Run: python3 tests/acceptance/v620_id_counter_retract.py
"""
import os
import sys
import tempfile

TMP = tempfile.mkdtemp(prefix="sf-v620-")
for _k in ("CONFIG_DIR", "SESSIONS_DIR", "EDITS_DIR", "RUNS_DIR", "GRAPH_DIR", "ROLES_DIR"):
    os.environ["LONGRUN_" + _k] = os.path.join(TMP, _k)
    os.makedirs(os.path.join(TMP, _k), exist_ok=True)
os.environ["LONGRUN_DB"] = os.path.join(TMP, "events.db")
os.environ["LONGRUN_AGENTS_FILE"] = os.path.join(TMP, "agents.json")
os.environ["LONGRUN_JOBS_FILE"] = os.path.join(TMP, "jobs.json")
os.environ["LONGRUN_ROUTINES_FILE"] = os.path.join(TMP, "routines.json")
os.environ["LONGRUN_TEAMS_FILE"] = os.path.join(TMP, "teams.json")
REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.util import fswrite as FW  # noqa: E402
from longrun.agent import agents as AG  # noqa: E402
from longrun.orchestrate import jobs as JO  # noqa: E402
from longrun.orchestrate import routines as RO  # noqa: E402
from longrun.orchestrate import teams as TE  # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""))


# ---- helper unit ----
d = {"agents": {"s1": {"id": "A1", "n": 1}, "s3": {"id": "A3", "n": 3}}, "seq": 9}
FW.retract_seq(d, "agents")
check("U1 retract lands on max live n, not zero, not old seq",
      d["seq"] == 3, d["seq"])
d2 = {"jobs": {}, "seq": 5}
FW.retract_seq(d2, "jobs")
check("U2 empty registry retracts to 0 (next is 1)", d2["seq"] == 0, d2["seq"])
d3 = {"x": 1}
FW.retract_seq(d3, "missing-key")
check("U3 unknown key leaves the doc alone", d3 == {"x": 1, "seq": 0} or d3.get("seq") == 0, d3)

# ---- agents: full wipe restarts at A1 ----
sids = ["v620-s%d" % i for i in range(3)]
for i, s in enumerate(sids):
    r = AG.REGISTRY.designate(s, name="V620-%d" % i)
    assert r.get("ok"), r
ids = sorted(a["id"] for a in AG.REGISTRY.list()["agents"])
check("A1 three designates mint A1..A3", ids == ["A1", "A2", "A3"], ids)
AG.REGISTRY.release(sids[2])
r = AG.REGISTRY.designate("v620-s3", name="V620-3")
check("A2 deleting the top reuses the number (A3, not A4)",
      r.get("agent", {}).get("id") == "A3", r.get("agent", {}).get("id"))
AG.REGISTRY.release(sids[0])
r = AG.REGISTRY.designate("v620-s4", name="V620-4")
check("A3 deleting from the middle does NOT reuse (next is A4, history stays dead)",
      r.get("agent", {}).get("id") == "A4", r.get("agent", {}).get("id"))
for s in ("v620-s1", "v620-s3", "v620-s4"):
    AG.REGISTRY.release(s)
live = [a["id"] for a in AG.REGISTRY.list()["agents"]]
r = AG.REGISTRY.designate("v620-s5", name="V620-5")
check("A4 wiping everything restarts at A1",
      live == [] and r.get("agent", {}).get("id") == "A1",
      (live, r.get("agent", {}).get("id")))
AG.REGISTRY.release("v620-s5")

# ---- jobs: same contract ----
a = AG.REGISTRY.designate("v620-w", name="V620-W")["agent"]["id"]
j1 = JO.JOBS.create("g1", agents=[a])["job"]["id"]
j2 = JO.JOBS.create("g2", agents=[a])["job"]["id"]
check("J1 jobs mint J1..J2", (j1, j2) == ("J1", "J2"), (j1, j2))
JO.JOBS.delete(j2)
j3 = JO.JOBS.create("g3", agents=[a])["job"]["id"]
check("J2 deleting the top job reuses the number", j3 == "J2", j3)
JO.JOBS.delete(j3)
JO.JOBS.delete(j1)
j4 = JO.JOBS.create("g4", agents=[a])["job"]["id"]
check("J3 wiping all jobs restarts at J1", j4 == "J1", j4)
JO.JOBS.delete(j4)

# ---- routines + teams: same contract ----
ro1 = RO.REGISTRY.create(a, "r1", 60)["routine"]["id"]
RO.REGISTRY.delete(ro1)
ro2 = RO.REGISTRY.create(a, "r2", 60)["routine"]["id"]
check("R1 wiped routines restart at R1", (ro1, ro2) == ("R1", "R1"), (ro1, ro2))
RO.REGISTRY.delete(ro2)
t1 = TE.REGISTRY.create("V620-T1")["team"]["id"]
TE.REGISTRY.delete(t1)
t2 = TE.REGISTRY.create("V620-T2")["team"]["id"]
check("T1 wiped teams restart at T1", (t1, t2) == ("T1", "T1"), (t1, t2))
TE.REGISTRY.delete(t2)
AG.REGISTRY.release("v620-w")

# ---- no live id ever renamed ----
check("Z1 registries empty and counters zeroed",
      AG.REGISTRY.list()["seq"] == 0 and JO.JOBS.list()["seq"] == 0
      and RO.REGISTRY.list()["seq"] == 0 and TE.REGISTRY.list()["seq"] == 0)

print("---")
ok = sum(results)
print("\nv620: %d/%d PASS" % (ok, len(results)))
sys.exit(0 if ok == len(results) else 1)
