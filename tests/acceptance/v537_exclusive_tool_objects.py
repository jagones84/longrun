#!/usr/bin/env python3
"""v537 — longrunAgent (VEO) exclusive tools are COMPLETE objects (JAG-537).

Locks:
  A  Completeness contract for the exclusive namespace:
     - every `longrunAgent.*` schema has exactly ONE handler and vice versa;
     - the namespace is mirrored on the object model: `teamorg.<object>.<verb>`
       for teams / agents / jobs / routines / sessions, and typed
       `webui.<object>.<verb>` for providers / skills / mcp / knowledge;
     - no tool takes an `op` sub-operation string any more (the verb is bound by
       the tool NAME), and the WebUI-facing prompt says so.
  B  TEAMS: create -> update (description + regenerate_icon) -> member.add/remove
     -> delete, on the real store.
  C  AGENTS: create -> update (name/role/model/budget) -> prompt.set/get/clear ->
     delete with the FULL cascade (designation + ROLE.md + session + workspace).
  D  JOBS: create -> get/list -> delete, on the real registry.
  E  ROUTINES: create -> update -> get/list -> delete, on the real registry.
  F  SESSIONS: create -> rename -> list -> delete (cascade) and the guards
     (permanent `longrunAgent` session, unknown ids).
  G  Destructive paths are bounded: a workspace folder outside the workspaces
     root is NEVER removed.
  H  Typed webui tools reach the real writers (providers / skills / knowledge /
     mcp) without a `target`/`op` bag.

Deterministic: temp dirs, no live model, no network, no server.
Run: python3 tests/acceptance/v537_exclusive_tool_objects.py
"""
import atexit
import os
import shutil
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="sf-v537-")
atexit.register(lambda: shutil.rmtree(TMP, ignore_errors=True))
for _k in ("DATA_DIR", "CONFIG_DIR", "SESSIONS_DIR", "ROLES_DIR", "DB",
           "COSTS_DIR", "EDITS_DIR", "RUNS_DIR", "GRAPH_DIR",
           "AGENTS_FILE", "TEAMS_FILE", "WORKSPACES_ROOT"):
    val = os.path.join(TMP, _k.lower() + (".json" if _k.endswith("_FILE") else ""))
    if not _k.endswith("_FILE") and _k != "DB":
        os.makedirs(val, exist_ok=True)
    os.environ["LONGRUN_" + _k] = val
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.agent import agents as A                  # noqa: E402
from longrun.agent import longrun_agent as LRA         # noqa: E402
from longrun.memory import stores                      # noqa: E402
from longrun.orchestrate import jobs as J              # noqa: E402
from longrun.orchestrate import roles as R             # noqa: E402
from longrun.orchestrate import routines as RT         # noqa: E402
from longrun.orchestrate import teams as TE            # noqa: E402
from longrun.tools import registry                     # noqa: E402

registry._external_tools = lambda: {}

results = []


def check(name, cond, detail=""):
    ok = bool(cond)
    results.append(ok)
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""))


def call(tool, args):
    return LRA.execute(tool, args, run_id="longrunAgent")


LRA.ensure_system_session()

# --- A: completeness contract ------------------------------------------------
schemas = {k for k in LRA.TOOL_SCHEMAS if k.startswith("longrunAgent.")}
handlers = set(LRA._SUBTOOL_MAP)
check("A1 every exclusive schema has ONE handler and no handler is orphaned",
      schemas == handlers, sorted(schemas ^ handlers))
check("A2 the namespace mirrors the object model (teams/agents/jobs/routines/sessions)",
      all(("longrunAgent.%s.%s" % (pref, verb)) in handlers
          for pref, verbs in {
              "teamorg.teams": ("create", "update", "delete", "get", "list"),
              "teamorg.agents": ("create", "update", "delete", "get", "list"),
              "teamorg.jobs": ("create", "dispatch", "delete", "get", "list"),
              "teamorg.routines": ("create", "update", "delete", "get", "list"),
              "teamorg.sessions": ("create", "rename", "delete", "list"),
          }.items() for verb in verbs),
      sorted(handlers))
check("A3 typed webui object tools exist next to the config writer",
      all(("longrunAgent.webui.%s" % n) in handlers for n in (
          "providers.upsert", "providers.remove", "providers.add_model",
          "providers.remove_model", "providers.default", "providers.reload",
          "skills.remove", "mcp.upsert", "mcp.remove", "mcp.test", "mcp.reload",
          "knowledge.notebook.create", "knowledge.notebook.rename",
          "knowledge.notebook.delete", "knowledge.source.add",
          "knowledge.source.remove", "knowledge.reembed")))
check("A4 no exclusive tool takes an `op` sub-operation string any more",
      not any("op" in (s.get("properties") or {})
              for s in LRA.TOOL_SCHEMAS.values() if isinstance(s, dict))
      and '"op"' not in __import__("json").dumps(LRA.TOOL_SCHEMAS))
check("A5 every tool description names itself (self-documenting namespace)",
      all(str(s.get("description") or "").startswith(k + " ")
          for k, s in LRA.TOOL_SCHEMAS.items() if isinstance(s, dict)),
      [k for k, s in LRA.TOOL_SCHEMAS.items()
       if isinstance(s, dict) and not str(s.get("description") or "").startswith(k + " ")])

# --- B: teams ----------------------------------------------------------------
t_new = call("longrunAgent.teamorg.teams.create",
             {"name": "Finance Ops", "description": "budget, cost and billing"})
tid = (t_new.get("team") or {}).get("id")
check("B1 teams.create stores the description and picks the matching palette icon",
      t_new.get("ok") is True and tid
      and (t_new["team"].get("symbol"), t_new["team"].get("color")) == ("\U0001f4b0", "#22C55E"),
      t_new.get("team"))

t_upd = call("longrunAgent.teamorg.teams.update",
             {"team": tid, "description": "security incident triage and red team"})
t_regen = call("longrunAgent.teamorg.teams.update", {"team": tid, "regenerate_icon": True})
check("B2 teams.update edits name/description and re-asks longrunAgent for the icon",
      t_upd.get("ok") is True
      and "security" in (TE.REGISTRY.get(tid) or {}).get("description", "")
      and t_regen.get("ok") is True
      and (t_regen["team"].get("symbol"), t_regen["team"].get("color")) == ("\U0001f6a8", "#EF4444"),
      (t_upd.get("changed"), t_regen.get("team")))

t_get = call("longrunAgent.teamorg.teams.get", {"team": tid})
t_list = call("longrunAgent.teamorg.teams.list", {})
check("B3 teams.get/list read the real store and publish the palette",
      t_get.get("ok") is True and len(t_get.get("palette") or []) == 8
      and t_list.get("ok") is True
      and any(t.get("id") == tid for t in (t_list.get("teams") or [])),
      (t_list.get("count"), len(t_get.get("palette") or [])))

# an agent to move in and out of the team (also used by C/D/E)
a_new = call("longrunAgent.teamorg.agents.create",
             {"name": "Sre Bot", "role": "sre", "prompt": "You watch uptime."})
aid, asid = (a_new.get("agent") or {}).get("id"), a_new.get("session")

m_add = call("longrunAgent.teamorg.teams.member.add", {"team": tid, "agent": aid})
in_team = aid in TE.REGISTRY.members_of(tid)
m_del = call("longrunAgent.teamorg.teams.member.remove", {"team": tid, "agent": aid})
out_team = aid not in TE.REGISTRY.members_of(tid)
check("B4 teams.member.add/remove move the agent in and out of the team",
      m_add.get("ok") is True and in_team and m_del.get("ok") is True and out_team,
      (in_team, out_team))

t_del = call("longrunAgent.teamorg.teams.delete", {"team": tid})
check("B5 teams.delete removes the team but keeps its member agents",
      t_del.get("ok") is True
      and TE.REGISTRY.get(tid) is None
      and A.REGISTRY.get(asid) is not None, t_del)
check("B6 team tools answer with an error (never a crash) on an unknown team",
      call("longrunAgent.teamorg.teams.get", {"team": "T999"}).get("ok") is False
      and call("longrunAgent.teamorg.teams.delete", {"team": "T999"}).get("ok") is False
      and call("longrunAgent.teamorg.teams.update", {"team": "T999", "name": "x"}).get("ok") is False)

# --- C: agents ---------------------------------------------------------------
ws = (a_new.get("agent") or {}).get("workspace") or a_new.get("workspace")
check("C1 agents.create provisions the record, the session, ROLE.md and a workspace folder",
      a_new.get("ok") is True and os.path.isdir(ws)
      and "uptime" in R.read(asid), (ws, a_new.get("model")))

a_upd = call("longrunAgent.teamorg.agents.update",
             {"agent": aid, "name": "Sre Bot II", "role": "senior-sre",
              "model": "openrouter:z-ai/glm-5.3-flash", "daily_budget": 5})
rec = A.REGISTRY.get(asid) or {}
check("C2 agents.update touches ONLY the properties it was given",
      a_upd.get("ok") is True
      and rec.get("name") == "Sre Bot II" and rec.get("role") == "senior-sre"
      and rec.get("daily_budget") == 5
      and stores.load_session(asid).get("model") == "openrouter:z-ai/glm-5.3-flash",
      (a_upd.get("changed"), rec))
check("C3 agents.update refuses an empty patch",
      call("longrunAgent.teamorg.agents.update", {"agent": aid}).get("ok") is False)

p_set = call("longrunAgent.teamorg.agents.prompt.set",
             {"agent": aid, "prompt": "You are the SRE on call."})
p_get = call("longrunAgent.teamorg.agents.prompt.get", {"agent": aid})
p_clr = call("longrunAgent.teamorg.agents.prompt.clear", {"agent": aid})
check("C4 prompt.set/get/clear operate on the real ROLE.md",
      p_set.get("ok") is True
      and "SRE on call" in (p_get.get("prompt") or "")
      and p_clr.get("ok") is True
      and not os.path.isfile(R.path_for(asid)), (p_get.get("chars"), p_clr))

a_get = call("longrunAgent.teamorg.agents.get", {"agent": aid})
a_list = call("longrunAgent.teamorg.agents.list", {})
check("C5 agents.get/list read the real org",
      a_get.get("ok") is True and a_get.get("agent", {}).get("id") == aid
      and a_list.get("ok") is True and a_list.get("count", 0) >= 1)

a_del = call("longrunAgent.teamorg.agents.delete", {"agent": aid})
check("C6 agents.delete cascades: designation + session + workspace folder all gone",
      a_del.get("ok") is True
      and A.REGISTRY.get(asid) is None
      and stores.load_session(asid) is None
      and not os.path.exists(ws), a_del)
check("C7 agents.delete never removes the permanent longrunAgent session",
      call("longrunAgent.teamorg.agents.delete", {"agent": "longrunAgent"}).get("ok") is False)

# --- D: jobs -----------------------------------------------------------------
boss = call("longrunAgent.teamorg.agents.create", {"name": "Job Boss", "role": "lead"})
boss_id, boss_sid = (boss.get("agent") or {}).get("id"), boss.get("session")
worker = call("longrunAgent.teamorg.agents.create", {"name": "Job Worker", "role": "coder"})
worker_id = (worker.get("agent") or {}).get("id")
j_new = call("longrunAgent.teamorg.jobs.create",
             {"goal": "ship the release notes", "coordinator": boss_id, "agents": [worker_id]})
jid = (j_new.get("job") or {}).get("id")
check("D1 jobs.create stores goal + coordinator + workers",
      j_new.get("ok") is True and jid
      and (j_new["job"].get("goal") == "ship the release notes")
      and worker_id in (j_new["job"].get("agents") or []), j_new.get("job"))
check("D2 jobs.create requires at least one worker agent",
      call("longrunAgent.teamorg.jobs.create", {"goal": "x", "agents": []}).get("ok") is False)
j_get = call("longrunAgent.teamorg.jobs.get", {"job": jid})
j_list = call("longrunAgent.teamorg.jobs.list", {})
check("D3 jobs.get/list read the real registry",
      j_get.get("ok") is True and (j_get.get("job") or {}).get("id") == jid
      and j_list.get("ok") is True
      and any(j.get("id") == jid for j in (j_list.get("jobs") or [])))
j_del = call("longrunAgent.teamorg.jobs.delete", {"job": jid})
check("D4 jobs.delete removes the job from the real registry",
      j_del.get("ok") is True and (J.JOBS.get(jid) is None))

# --- E: routines -------------------------------------------------------------
rt_new = call("longrunAgent.teamorg.routines.create",
              {"agent": boss_sid, "goal": "check the queue", "every_seconds": 120})
rid = (rt_new.get("routine") or {}).get("id")
check("E1 routines.create schedules the goal for the resolved agent session",
      rt_new.get("ok") is True and rid
      and (rt_new["routine"].get("agent") == boss_sid)
      and (rt_new["routine"].get("every_seconds") == 120), rt_new.get("routine"))
rt_upd = call("longrunAgent.teamorg.routines.update",
              {"routine": rid, "goal": "check the queue harder", "every_seconds": 300,
               "enabled": False})
rt_rec = RT.REGISTRY.get(rid) or {}
check("E2 routines.update edits only the fields passed (id and runs survive)",
      rt_upd.get("ok") is True
      and rt_rec.get("goal") == "check the queue harder"
      and rt_rec.get("every_seconds") == 300 and rt_rec.get("enabled") is False
      and rt_rec.get("id") == rid, rt_rec)
check("E3 routines.get/list read the real registry",
      call("longrunAgent.teamorg.routines.get", {"routine": rid}).get("ok") is True
      and any(r.get("id") == rid
              for r in (call("longrunAgent.teamorg.routines.list", {}).get("routines") or [])))
check("E4 routines.create refuses an unknown agent",
      call("longrunAgent.teamorg.routines.create",
           {"agent": "nobody", "goal": "x", "every_seconds": 60}).get("ok") is False)
rt_del = call("longrunAgent.teamorg.routines.delete", {"routine": rid})
check("E5 routines.delete removes the routine",
      rt_del.get("ok") is True and RT.REGISTRY.get(rid) is None)

# --- F: sessions -------------------------------------------------------------
s_new = call("longrunAgent.teamorg.sessions.create", {"title": "JAG-537 probe"})
psid = s_new.get("session")
s_ren = call("longrunAgent.teamorg.sessions.rename",
             {"session": psid, "title": "JAG-537 probe (renamed)"})
s_list = call("longrunAgent.teamorg.sessions.list", {})
check("F1 sessions.create/rename/list operate on the real store",
      s_new.get("ok") is True and (stores.load_session(psid) or {}).get("title") == "JAG-537 probe (renamed)"
      and s_ren.get("ok") is True
      and any(s.get("id") == psid for s in (s_list.get("sessions") or [])),
      (psid, s_new.get("title")))
s_del = call("longrunAgent.teamorg.sessions.delete", {"session": psid})
check("F2 sessions.delete removes the session file",
      s_del.get("ok") is True and stores.load_session(psid) is None, s_del)
check("F3 sessions.delete refuses the permanent longrunAgent session and unknown ids",
      call("longrunAgent.teamorg.sessions.delete", {"session": "longrunAgent"}).get("ok") is False
      and call("longrunAgent.teamorg.sessions.delete", {"session": "no-such-session"}).get("ok") is False)

# --- G: bounded destructive paths -------------------------------------------
outside = os.path.join(TMP, "not-a-workspace")
os.makedirs(outside, exist_ok=True)
g_res = LRA._remove_workspace_path(outside)
check("G1 a folder outside the workspaces root is NEVER deleted",
      g_res.get("removed") is False and os.path.isdir(outside)
      and "outside" in str(g_res.get("reason")), g_res)

# --- H: typed webui object tools --------------------------------------------
KB = __import__("longrun.memory.knowledge", fromlist=["knowledge"])
nb = call("longrunAgent.webui.knowledge.notebook.create", {"name": "jag537-nb"})
nb_id = nb.get("id")
nb_ren = call("longrunAgent.webui.knowledge.notebook.rename",
              {"id": nb_id, "name": "jag537-nb-renamed"})
names = [str(n) for n in KB.list_notebooks()]
nb_del = call("longrunAgent.webui.knowledge.notebook.delete", {"id": nb_id})
check("H1 webui.knowledge.notebook.create/rename/delete are real CRUD",
      nb.get("ok") is True and nb_ren.get("ok") is True
      and any("jag537-nb" in n for n in names)
      and nb_del.get("ok") is True
      and not any(nb_id in str(n) for n in KB.list_notebooks()),
      (nb_id, names[:3], nb_del))
check("H2 webui.providers.reload reaches the provider engine",
      call("longrunAgent.webui.providers.reload", {}).get("ok") is True)
check("H3 webui.skills.remove / webui.mcp.remove answer with a real result, never a crash",
      isinstance(call("longrunAgent.webui.skills.remove", {"name": "no-such-skill"}).get("ok"), bool)
      and isinstance(call("longrunAgent.webui.mcp.remove", {"name": "no-such-client"}).get("ok"), bool))
check("H4 the old catch-all still writes CONFIG targets only",
      set(LRA.TOOL_SCHEMAS["longrunAgent.webui.configure"]["properties"]["target"]["enum"])
      == {"settings", "rules", "compaction", "routing", "team_policy", "subagents",
          "tools", "index", "config"})

# cleanup the probe agents so the shared stores stay clean
for ref in (worker_id, boss_id):
    call("longrunAgent.teamorg.agents.delete", {"agent": ref})

print("---")
print("v537: %d/%d PASS" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
