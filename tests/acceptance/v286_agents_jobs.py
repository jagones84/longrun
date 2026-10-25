#!/usr/bin/env python3
"""v286 — Agents & Jobs (JAG-287): the orchestration domain model.

Agent = a session (id AX, todos AX.TY). Job = a higher-level goal (JN) that
orchestrates several agents with a coordinator and dependency waves.

Locked here:
  * designate assigns STABLE AX ids, is idempotent, resolves reports_to (org chart);
  * the delete-guard flags an agent that still manages reports;
  * Job.create validates, allocates JN ids, keeps deps to members;
  * waves() honours dependencies, parallelises independents, never hangs on a cycle;
  * the API routes answer and never shadow a non agents/jobs path;
  * the main GUI shows the AX prefix, the org-agent badge and the guarded delete;
  * api_v02 delegates to the routes (the model stays native, no new server hook).

Deterministic, no live model. Run: python3 tests/v286_agents_jobs.py
"""
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(REPO, "src"))
TMP = tempfile.mkdtemp(prefix="sf-v286-")
os.environ["LONGRUN_AGENTS_FILE"] = os.path.join(TMP, "agents.json")
os.environ["LONGRUN_JOBS_FILE"] = os.path.join(TMP, "jobs.json")

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + detail) if detail else ""))


from longrun.agent import agents  # noqa: E402
from longrun.orchestrate import jobs  # noqa: E402
from longrun.orchestrate import orchestration  # noqa: E402

reg = agents.REGISTRY

# --- agents -----------------------------------------------------------------
a1 = reg.designate("sess-1", name="CEO", role="coordinator")
a2 = reg.designate("sess-2", name="Dev", role="engineer", reports_to="sess-1")
check("designate assigns stable AX ids",
      a1["ok"] and a1["agent"]["id"] == "A1" and a2["agent"]["id"] == "A2")
check("reports_to resolves a session id to an agent id", a2["agent"]["reports_to"] == "A1")
a1b = reg.designate("sess-1", role="boss")
check("designate is idempotent (same id, keeps name)",
      a1b["agent"]["id"] == "A1" and a1b["agent"]["name"] == "CEO" and a1b["agent"]["role"] == "boss")
check("is_agent / get work", reg.is_agent("sess-1") and reg.get("sess-2")["name"] == "Dev")

tree = reg.tree()
check("the org tree exposes roots + children",
      tree["roots"] == ["A1"] and "A2" in tree["agents"][0]["children"])

g = reg.guards("sess-1")
check("guards flag an agent managing reports (delete-blocked)",
      g["is_agent"] and g["blocked"] and g["reports"] == ["A2"])
check("guards for a non-agent are inert", reg.guards("nope")["is_agent"] is False)

# --- jobs -------------------------------------------------------------------
J = jobs.JOBS
check("create refuses an empty goal", J.create("", agents=["A1"])["ok"] is False)
check("create refuses no agents", J.create("do it", agents=[])["ok"] is False)
made = J.create("ship it", coordinator="A1", agents=["A1", "A2"], deps={"A2": ["A1"]})
check("create allocates a JN id (J reserved for jobs)",
      made["ok"] and made["job"]["id"] == "J1")
check("deps keep only member agents", made["job"]["deps"]["A2"] == ["A1"])

check("waves order by dependency", jobs.waves(["A1", "A2"], {"A2": ["A1"]}) == [["A1"], ["A2"]])
check("waves parallelise independent agents",
      sorted(jobs.waves(["A1", "A2"], {})[0]) == ["A1", "A2"])
check("waves break a cycle instead of hanging",
      len(jobs.waves(["A1", "A2"], {"A1": ["A2"], "A2": ["A1"]})) == 2)
check("dispatch of an unknown job is refused", J.dispatch("J999")["ok"] is False)

# --- API routing ------------------------------------------------------------
class FakeHandler:
    def __init__(self):
        self.sent = None

    def _send(self, code, obj, ctype=None):
        self.sent = {"code": code, "obj": obj}
        return True


fh = FakeHandler()
ok = orchestration.handle(fh, "GET", "/api/agents", {}, None)
check("GET /api/agents answers the roster", ok and fh.sent["code"] == 200 and fh.sent["obj"]["count"] == 2)
fh = FakeHandler()
ok = orchestration.handle(fh, "GET", "/api/agents/tree", {}, None)
check("GET /api/agents/tree answers", ok and fh.sent["code"] == 200 and "roots" in fh.sent["obj"])
fh = FakeHandler()
ok = orchestration.handle(fh, "GET", "/api/jobs", {}, None)
check("GET /api/jobs answers", ok and fh.sent["code"] == 200)
fh = FakeHandler()
check("a non agents/jobs path is not shadowed",
      orchestration.handle(fh, "GET", "/api/status", {}, None) is False and fh.sent is None)
fh = FakeHandler()
ok = orchestration.handle(fh, "POST", "/api/jobs", {}, {"goal": ""})
check("POST /api/jobs with no goal is ok:false", ok and fh.sent["obj"]["ok"] is False)

# --- release + guarded delete ----------------------------------------------
rel = reg.release("sess-1")
check("releasing the root re-parents its reports to none",
      rel["ok"] and reg.get("sess-2")["reports_to"] is None)

reg.designate("sess-3", name="Mgr")
reg.designate("sess-4", name="Rep", reports_to="sess-3")
fh = FakeHandler()
ok = orchestration.handle(fh, "DELETE", "/api/agents/sess-3", {}, None)
check("DELETE an agent with reports is refused (409)", ok and fh.sent["code"] == 409)

# --- GUI + native wiring ----------------------------------------------------
with open(os.path.join(REPO, "webui", "index.html"), encoding="utf-8") as f:
    html = f.read()
check("the GUI uses the AX prefix for agents",
      "_agentNum" in html and "A${_anum}" in html and '_agents[sessionId]' in html
      and '"J" + curJob' in html and '"A" + curJob' not in html)
check("the GUI badges org agents and guards their delete",
      "org agent " in html and 'api("DELETE", "/api/agents/" + s.id)' in html
      and "is an ORG AGENT" in html)
check("the deck button opens the Orbit beta", "location.href='/orbit'" in html)

with open(os.path.join(REPO, "src", "longrun", "core/api_v02.py"), encoding="utf-8") as f:
    av = f.read()
check("api_v02 delegates to the orchestration routes (native, no new server hook)",
      "orchestration.handle(handler, method, path, qs, body)" in av)

print("---")
passed = sum(results)
print("%d/%d PASS" % (passed, len(results)))
sys.exit(0 if passed == len(results) else 1)

