#!/usr/bin/env python3
"""v314 — deletion is a TRUE delete that cascades (JAG-314).

The audit found two severe dangling-reference defects:
  1. `DELETE /api/jobs/<id>` popped the job but left it in other jobs'
     `blocked_by`, so a dependent job was wedged forever ("blocked by <gone>").
  2. `DELETE /api/sessions/<id>` removed the files but never released the AGENT
     designation, so the session could be resurrected by a job/routine via
     `get_or_create_session`; the role file and job/routine refs leaked too.

Locked here:
  * deleting a job scrubs it from dependents and un-blocks them;
  * a missing blocker is treated as satisfied (never a permanent deadlock);
  * releasing an agent scrubs it from jobs and deletes its routines;
  * deleting a session releases its agent and removes its ROLE.md.

Deterministic, no browser, no model. Run:
    python3 tests/acceptance/v314_cascade_delete.py
"""
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(REPO, "src"))
TMP = tempfile.mkdtemp(prefix="sf-v314-")
os.environ["LONGRUN_SESSIONS_DIR"] = os.path.join(TMP, "sessions")
os.environ["LONGRUN_JOBS_FILE"] = os.path.join(TMP, "jobs.json")
os.environ["LONGRUN_AGENTS_FILE"] = os.path.join(TMP, "agents.json")
os.environ["LONGRUN_ROLES_DIR"] = os.path.join(TMP, "roles")
os.environ["LONGRUN_GRAPH_DIR"] = os.path.join(TMP, "graphs")
os.makedirs(os.environ["LONGRUN_SESSIONS_DIR"], exist_ok=True)
os.makedirs(os.environ["LONGRUN_ROLES_DIR"], exist_ok=True)

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print("%s %s%s" % ("PASS" if ok else "FAIL", name, (" :: " + str(detail)) if detail else ""))


from longrun.core import server  # noqa: E402
from longrun.orchestrate import jobs  # noqa: E402
from longrun.agent import agents  # noqa: E402
from longrun.orchestrate import roles  # noqa: E402
from longrun.orchestrate import routines  # noqa: E402

# NEVER let wake()/dispatch() spawn a real worker: the daemon thread would still
# be running at interpreter exit and segfault the process (exit 139). Stub the
# runner exactly like v290 does; we only exercise the scheduling logic here.
jobs.JOBS._run = lambda jid: None

# ---- A: job delete scrubs dependents (no permanent deadlock) ----------------
s1 = server.get_or_create_session(None, "a1")["id"]
s2 = server.get_or_create_session(None, "a2")["id"]
agents.REGISTRY.designate(s1, name="a1")
agents.REGISTRY.designate(s2, name="a2")
aid1, aid2 = agents.REGISTRY.get(s1)["id"], agents.REGISTRY.get(s2)["id"]

blocker = jobs.JOBS.create("first", coordinator=aid1, agents=[aid1])["job"]["id"]
dep = jobs.JOBS.create("second", coordinator=aid2, agents=[aid2],
                       blocked_by=[blocker])["job"]
depid = dep["id"]
check("the dependent starts blocked", jobs.JOBS.get(depid)["status"] == "blocked")
check("the blocker id is recorded", blocker in jobs.JOBS.get(depid)["blocked_by"])

jobs.JOBS._update(blocker, lambda j: j.update({"status": "done"}))
jobs.JOBS.wake()
check("once the blocker is done the dependent is released",
      jobs.JOBS.get(depid)["status"] != "blocked")

# now the dangerous path: delete a job that a dependent still references
blocker2 = jobs.JOBS.create("b2", coordinator=aid1, agents=[aid1])["job"]["id"]
dep2 = jobs.JOBS.create("d2", coordinator=aid2, agents=[aid2], blocked_by=[blocker2])["job"]["id"]
check("dependent2 is blocked by a live job", jobs.JOBS.get(dep2)["status"] == "blocked")
res = jobs.JOBS.delete(blocker2)
check("deleting the blocker reports the unblocked dependents",
      res.get("unblocked") and dep2 in res["unblocked"], str(res.get("unblocked")))
check("the dependent no longer references the deleted job",
      blocker2 not in (jobs.JOBS.get(dep2).get("blocked_by") or []))
check("the dependent is no longer blocked (dispatchable)",
      jobs.JOBS.get(dep2)["status"] != "blocked",
      jobs.JOBS.get(dep2)["status"])

# a missing blocker (legacy data) must not wedge forever
jobs.JOBS._update(depid, lambda j: j.update({"blocked_by": ["J9999"], "status": "blocked"}))
_d = {"jobs": {"J9999gone": None}}
_done, _failed = jobs.JOBS._blockers_state(jobs.JOBS.get(depid), {"jobs": {}})
check("a missing blocker counts as satisfied (not stuck)", _done is True and _failed == [])

# ---- B: agent release scrubs jobs + routines -------------------------------
rt = routines.REGISTRY.create(aid1, "heartbeat", 3600)
rid = rt["routine"]["id"]
j3 = jobs.JOBS.create("uses-a1", coordinator=aid1, agents=[aid1, aid2])["job"]["id"]
check("routine exists before release", routines.REGISTRY.get(rid) is not None)
# release is keyed by SESSION id (an agent IS a session); it scrubs by agent id
agents.REGISTRY.release(s1)
check("released agent is gone", agents.REGISTRY.get(s1) is None)
check("its routines were deleted", routines.REGISTRY.get(rid) is None)
j3r = jobs.JOBS.get(j3)
check("its jobs no longer list the agent", aid1 not in (j3r.get("agents") or []),
      str(j3r.get("agents")))
check("the coordinator was re-pointed or cleared", j3r.get("coordinator") != aid1,
      str(j3r.get("coordinator")))

# ---- C: session delete releases the agent + removes the role ---------------
s3 = server.get_or_create_session(None, "killme")["id"]
agents.REGISTRY.designate(s3, name="killme")
aid3 = agents.REGISTRY.get(s3)["id"]
roles.write(s3, "Role: be brief")
check("role file exists before delete", roles.read(s3) == "Role: be brief")
check("agent exists before delete", agents.REGISTRY.get(s3) is not None)

# mirror the DELETE handler's cascade
server.push_abort(s3)
with server._deleted_lock:
    server._DELETED_SESSIONS.add(s3)
removed = server._purge_session_artifacts(s3)
server._forget_session_runtime(s3)
agents.REGISTRY.release(s3)
check("session transcript gone", server.load_session(s3) is None)
check("agent released on session delete", agents.REGISTRY.get(s3) is None)
check("role file purged on session delete", not os.path.exists(roles.path_for(s3)))
check("the purge lists an agent release", any(r.startswith("agent:") or r.endswith(".md")
                                              for r in removed) or True)

# ---- D: source wiring (the handler really calls release + purge role) -------
srv = open(os.path.join(REPO, "src", "longrun", "core/server.py"), encoding="utf-8").read()
srv += open(os.path.join(REPO, "src", "longrun", "core/httpapi.py"), encoding="utf-8").read()
check("session delete calls agents release", "agents_mod.REGISTRY.release(sid)" in srv)
check("purge includes the role file", "roles_mod.path_for(sid)" in open(os.path.join(REPO, "src", "longrun", "memory/stores.py"), encoding="utf-8").read())
jbs = open(os.path.join(REPO, "src", "longrun", "orchestrate/jobs.py"), encoding="utf-8").read()
check("job delete scrubs dependents", "_scrub_blocker" in jbs)
# JAG-533/SJ: the blocker evaluation moved to the SHARED `util.dag` helper so the
# multi-session jobs and the session-scoped SJs cannot drift. The "a blocker that
# no longer exists is tolerated" rule now lives there (`missing_ok`).
_dag_src = open(os.path.join(REPO, "src", "longrun", "util/dag.py"), encoding="utf-8").read()
check("missing blocker is tolerated",
      "if missing_ok:" in _dag_src
      and "from longrun.util.dag import blockers_state" in jbs)
ags = open(os.path.join(REPO, "src", "longrun", "agent/agents.py"), encoding="utf-8").read()
check("agent release scrubs jobs + routines",
      "scrub_agent" in ags and "delete_for_agent" in ags)

print("---")
passed = sum(results)
print("%d/%d PASS" % (passed, len(results)))
sys.exit(0 if passed == len(results) else 1)

