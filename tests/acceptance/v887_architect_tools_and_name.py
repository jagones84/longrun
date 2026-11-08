#!/usr/bin/env python3
"""v887 — the architect can shape the whole deck (jobs included), and is named Architect.

Operator: *"the create jobs shall be made better … capability of longrunagents to assign
and create jobs to the right agents, etcetera. make sure the tools longrun agents has are
enough deep to change, create, edit, remove everything from the control panels objects
referred to the backend so we make an automatic way to design teams agents jobs, assigned
to agents in structural dependant form, assign roles, workspaces, etcetera from the
control panel. make sure all is possible and automatable. longrun agent is architect.
replace its name please everywhere."*

Gap analysis against `src/` (2026-11-08): agents and teams already had the full
create/update/delete/get/list/member set, but JOBS could only be created, dispatched,
read and deleted — no edit, no dependency release door. That is what "assign a job to the
right agents" needs, so it is added here (one method, one tool) with tests, and the
Teamorg prompt is rewritten from "write ROLE.md files" into the WHOLE-ORG shape
(team → agents → jobs → routines → verify).

Pinned here:
  A) `JOBS.update` edits a job in place and refuses a RUNNING one;
  B) `job.update` + `job.wake` are real tools (schema + handler + dispatch map);
  C) the prompt states the whole-org shape and keeps every guard of v678/v886;
  D) the operator-facing NAME is `Architect` (session title, deck copy, Settings row),
     while the machine ids stay stable (session id, /api/longrun-agent/*).

Deterministic: temp data dirs, no model, no network, no server.
"""
import os
import re
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="sf-887-")
os.environ["LONGRUN_SESSIONS_DIR"] = os.path.join(TMP, "sessions")
os.environ["LONGRUN_GRAPH_DIR"] = os.path.join(TMP, "graphs")
os.environ["LONGRUN_DB"] = os.path.join(TMP, "events.db")
os.environ["LONGRUN_AGENTS_FILE"] = os.path.join(TMP, "agents.json")
os.environ["LONGRUN_JOBS_FILE"] = os.path.join(TMP, "jobs.json")
os.environ["LONGRUN_ROLES_DIR"] = os.path.join(TMP, "roles")
os.environ["LONGRUN_WORKSPACES_ROOT"] = os.path.join(TMP, "ws")
for _d in ("sessions", "graphs", "roles", "ws"):
    os.makedirs(os.path.join(TMP, _d), exist_ok=True)
sys.path.insert(0, os.path.join(REPO, "src"))

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""))


from longrun.orchestrate import jobs as jobs_mod          # noqa: E402
from longrun.agent import agents as agents_mod           # noqa: E402
from longrun.agent import architect as lra           # noqa: E402
from longrun.gen import surfaces                         # noqa: E402
from longrun.memory import stores                        # noqa: E402

ORBIT = open(os.path.join(REPO, "src", "longrun", "orbit", "web", "orbit.html"),
             encoding="utf-8").read()
INDEX = open(os.path.join(REPO, "webui", "index.html"), encoding="utf-8").read()
PROMPT = surfaces.SECTION_PROMPTS["teamorg"]

# ---- A: jobs can be edited in place ---------------------------------------
JOBS_SRC = open(os.path.join(REPO, "src", "longrun", "orchestrate", "jobs.py"),
                encoding="utf-8").read()
check("A1 the store exposes one public edit door",
      callable(getattr(jobs_mod.JOBS, "update", None))
      and "is running — abort it first" in JOBS_SRC)

_created = jobs_mod.JOBS.create("draft the api", coordinator="s1", agents=["s1", "s2"])
_jid = (_created.get("job") or {}).get("id")
check("A2 a job is created (baseline)", bool(_jid), _created.get("error"))

_res = jobs_mod.JOBS.update(_jid, goal="draft the API v2")
check("A3 only the passed field changes",
      _res.get("ok") and _res["job"]["goal"] == "draft the API v2"
      and _res["job"]["agents"] == ["s1", "s2"], _res.get("error"))

_res = jobs_mod.JOBS.update(_jid, agents=["s2"])
check("A4 re-assigning the workers drops an empty worker list",
      _res.get("ok") and _res["job"]["agents"] == ["s2"], _res.get("error"))
check("A5 a coordinator that is no longer a worker is replaced by one that is",
      _res.get("ok") and _res["job"]["coordinator"] == "s2", _res["job"].get("coordinator"))
check("A6 an empty goal is refused",
      jobs_mod.JOBS.update(_jid, goal="  ").get("ok") is False)

_res = jobs_mod.JOBS.update(_jid, mode="swarm", blocked_by=["J999"])
check("A7 a blocker that does not exist is dropped (no dead edge)",
      _res.get("ok") and _res["job"]["mode"] == "swarm"
      and _res["job"]["blocked_by"] == [], _res["job"].get("blocked_by"))

jobs_mod.JOBS._update(_jid, lambda j: j.update({"status": "running"}))
check("A8 a RUNNING job cannot be edited",
      jobs_mod.JOBS.update(_jid, goal="nope").get("ok") is False
      and "running" in jobs_mod.JOBS.update(_jid, goal="nope").get("error", ""))
jobs_mod.JOBS._update(_jid, lambda j: j.update({"status": "created"}))

# ---- B: the tools exist and are wired -------------------------------------
_agent = agents_mod.REGISTRY.designate("sessLead", name="Lead", role="coordinator")
check("B0 an agent to resolve names against exists", bool(_agent.get("ok")), _agent.get("error"))
_tool = lra._job_update({"job": _jid, "agents": ["Lead"], "coordinator": "Lead"})
check("B1 job.update resolves a NAME to the agent id and edits the same store",
      _tool.get("ok") and _tool["job"]["agents"] == [_agent["agent"]["id"]],
      _tool.get("error"))
_wake = lra._job_wake({})
check("B2 job.wake reports what it released",
      _wake.get("ok") is True and "stdout" in _wake, _wake)
check("B3 both are registered as exclusive tools with a handler",
      "job.update" in lra.TOOL_SCHEMAS and "job.wake" in lra.TOOL_SCHEMAS
      and lra.TOOL_SCHEMAS["job.update"]["_namespace"] == "job"
      and "job.update" in lra._SUBTOOL_MAP and "job.wake" in lra._SUBTOOL_MAP)

# ---- C: the prompt describes the whole org --------------------------------
check("C1 the identity is the architect",
      "the org architect of this harness" in PROMPT and "longrunAgent" not in PROMPT)
check("C2 the tool list covers jobs end to end",
      "`job.create|update|dispatch|wake|delete|get|list`" in PROMPT)
check("C3 the shape is spelled out step by step",
      all(s in PROMPT for s in ("A. TEAM", "B. AGENTS", "C. JOBS", "D. ROUTINES", "E. VERIFY")))
check("C4 a job is assigned to the agents who execute it, with dependencies",
      "`coordinator` + `agents`" in PROMPT and "`blocked_by`" in PROMPT
      and "job.update" in PROMPT and "a job with no worker is not a job" in PROMPT.lower())
check("C5 the guards of v678/v886 survive",
      "NEVER write to an agent outside the scope" in PROMPT
      and "context.only_empty" in PROMPT
      and "never create a cycle" in PROMPT
      and "NEVER change an agent's model" in PROMPT
      and "ALL FIVE" in PROMPT and "INCOMPLETE result" in PROMPT
      and "never pad the count with" in PROMPT)

# ---- D: the name the operator reads ---------------------------------------
check("D1 the session/agent title is Architect",
      lra.LONGRUN_AGENT_TITLE == "Architect")
check("D2 the machine ids are contracts and did NOT move",
      lra.LONGRUN_AGENT_SESSION_ID == "longrunAgent"
      and '"/api/longrun-agent/automate"' in ORBIT)
check("D3 the deck copy says Architect and no longer the old name",
      ">automate with Architect</span>" in ORBIT
      and "what Architect wrote" in ORBIT
      and "Architect is working…" in ORBIT
      and "automate with longrunAgent" not in ORBIT
      and "what longrunAgent wrote" not in ORBIT)
check("D4 the Sessions Settings row is renamed",
      ">Architect · automation model " in INDEX and "longrunAgent · VEO automation model" not in INDEX)

stores.save_session({"id": "longrunAgent", "title": "longrunAgent · VEO", "messages": []})
lra.ensure_system_session()
_migrated = (stores.load_session("longrunAgent") or {}).get("title")
check("D5 an existing store migrates the OLD title once (and keeps a typed one)",
      _migrated == "Architect", _migrated)
stores.save_session({"id": "longrunAgent", "title": "my own name", "messages": []})
lra.ensure_system_session()
check("D6 a title the operator typed is never overwritten",
      (stores.load_session("longrunAgent") or {}).get("title") == "my own name")

print("---")
passed = sum(results)
print("%d/%d PASS" % (passed, len(results)))
sys.exit(0 if passed == len(results) else 1)
