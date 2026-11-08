#!/usr/bin/env python3
"""v290 — Inter-job dependencies (blocked_by) + org-chart cycle guard (JAG-292).

A job may declare ``blocked_by=[JN, ...]``: it stays "blocked" until every blocker
is done, then a level-triggered ``wake()`` releases and dispatches it. A blocker
that FAILED fails the dependent instead of deadlocking (paperclip's
"cancelled blockers never unblock", without the hang). The org chart must stay a
forest: a self-link or a cycle in reports_to is refused.

Deterministic (the worker is stubbed), no live model.
Run: python3 tests/v290_job_deps.py
"""
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(REPO, "src"))
TMP = tempfile.mkdtemp(prefix="sf-v290-")
os.environ["LONGRUN_JOBS_FILE"] = os.path.join(TMP, "jobs.json")
os.environ["LONGRUN_AGENTS_FILE"] = os.path.join(TMP, "agents.json")

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + detail) if detail else ""))


from longrun.agent import agents  # noqa: E402
from longrun.orchestrate import jobs  # noqa: E402

reg = jobs.JOBS
reg._run = lambda jid: None   # never spawn a real worker


# --- a job + a dependent ----------------------------------------------------
a = reg.create("design the API", agents=["A1", "A2"])
j1 = a["job"]["id"]
check("a plain job is runnable at creation", a["ok"] and a["job"]["status"] == "created")

b = reg.create("write the docs", agents=["A1"], blocked_by=[j1])
j2 = b["job"]["id"]
check("a dependent job starts blocked", b["job"]["status"] == "blocked")
check("the blocker ids are recorded", b["job"]["blocked_by"] == [j1])

d1 = reg.dispatch(j2)
check("dispatch refuses a blocked job", d1["ok"] is False)
check("...and names the blocker it waits on", j1 in (d1.get("error") or ""))

c = reg.create("orphan", agents=["A1"], blocked_by=[j2, "J999", j2])
check("unknown + duplicate blockers are dropped", c["job"]["blocked_by"] == [j2])

# --- wake before the blocker is done: nothing happens ----------------------
w = reg.wake()
check("wake with an unfinished blocker releases nothing",
      w["released"] == [] and w["failed"] == [])
check("the dependent is still blocked", reg.get(j2)["status"] == "blocked")

# --- blocker done -> wake releases + dispatches the dependent --------------
reg._update(j1, lambda j: j.update({"status": "done", "ended": 0.0}))
w = reg.wake()
check("wake releases the dependent once the blocker is done",
      any(x["job"] == j2 and x["ok"] for x in w["released"]))
check("the released dependent is now running", reg.get(j2)["status"] == "running")

# --- a FAILED blocker fails the dependent (no deadlock) --------------------
j3 = reg.create("step A", agents=["A1"])["job"]["id"]
j4 = reg.create("step B", agents=["A1"], blocked_by=[j3])["job"]["id"]
reg._update(j3, lambda j: j.update({"status": "error", "error": "boom"}))
w = reg.wake()
check("a failed blocker fails its dependent", j4 in w["failed"])
check("...with a dependency-failed reason",
      "dependency failed" in (reg.get(j4).get("error") or ""))
check("the failed dependent is not left running", reg.get(j4)["status"] == "error")

# --- a blocker already done at create time => runnable immediately ---------
f = reg.create("after done", agents=["A1"], blocked_by=[j1])
check("a fresh job with an already-done blocker is created (not blocked)",
      f["job"]["status"] == "created")

# --- org chart: cycle guard + chain of command -----------------------------
AR = agents.REGISTRY
# 2026-11-08: A1 is RESERVED for the harness supervisor; read the minted ids.
A1 = AR.designate("s1", name="Chief")["agent"]["id"]
A2 = AR.designate("s2", name="Manager")["agent"]["id"]
A3 = AR.designate("s3", name="Worker")["agent"]["id"]
AR.designate("s2", reports_to=A1)
AR.designate("s3", reports_to=A2)
check("a valid reports_to chain is accepted", AR.get("s3").get("reports_to") == A2)
check("chain_of_command walks agent -> manager -> root",
      AR.chain_of_command("s3") == [A3, A2, A1])

bad = AR.designate("s1", reports_to=A3)   # A1 -> A3 -> A2 -> A1
check("a reports_to cycle is refused", bad["ok"] is False and "cycle" in bad["error"])
check("the refused cycle was not stored", AR.get("s1").get("reports_to") is None)
check("a self-link is refused", AR.designate("s2", reports_to=A2)["ok"] is False)
check("chain_of_command on an unknown agent is empty", AR.chain_of_command("A999") == [])

# --- API routing ------------------------------------------------------------
class FakeHandler:
    def __init__(self):
        self.sent = None

    def _send(self, code, obj, ctype=None):
        self.sent = {"code": code, "obj": obj}
        return True


from longrun.orchestrate import orchestration  # noqa: E402

fh = FakeHandler()
ok = orchestration.handle(fh, "POST", "/api/jobs/wake", {}, {})
check("POST /api/jobs/wake answers", ok and fh.sent["code"] == 200 and "released" in fh.sent["obj"])

fh = FakeHandler()
ok = orchestration.handle(fh, "POST", "/api/jobs", {}, {"goal": "x", "agents": ["A1"]})
check("POST /api/jobs forwards blocked_by", ok and "blocked_by" in fh.sent["obj"]["job"])

fh = FakeHandler()
ok = orchestration.handle(fh, "GET", "/api/agents/s3/chain", {}, None)
check("GET /api/agents/<sid>/chain answers the chain",
      ok and fh.sent["obj"]["chain"] == [A3, A2, A1])

# --- UI wiring --------------------------------------------------------------
with open(os.path.join(REPO, "src", "longrun", "orbit", "web", "orbit.html"), encoding="utf-8") as fh2:
    ui = fh2.read()
check("the Orbit job form assigns by recipient (assignee)",
      'id="jobTo"' in ui and "{goal, assignee}" in ui)
check("the job list styles the blocked state", ".st.blocked" in ui)

print("---")
passed = sum(results)
print("%d/%d PASS" % (passed, len(results)))
sys.exit(0 if passed == len(results) else 1)

