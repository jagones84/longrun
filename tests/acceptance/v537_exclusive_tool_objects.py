#!/usr/bin/env python3
"""v537 — longrunAgent (VEO) exclusive tools are COMPLETE objects (JAG-537).

Locks:
  A  Completeness contract for the exclusive namespaces:
     - every exclusive schema has exactly ONE handler and vice versa;
     - every name is EXACTLY `namespace.tool` (one object namespace, one
       explicative verb): `agent.*`, `team.*`, `job.*`, `routine.*`, `session.*`,
       `webui.*`, `provider.*`, `mcp.*`, `skill.*`, `kb.*` — never a deeper
       `a.b.c.d` path;
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
schemas = {k for k in LRA.TOOL_SCHEMAS if LRA.is_exclusive_name(k)}
handlers = set(LRA._SUBTOOL_MAP)
check("A1 every exclusive schema has ONE handler and no handler is orphaned",
      schemas == handlers, sorted(schemas ^ handlers))
check("A2 the namespace mirrors the object model (agent/team/job/routine/session)",
      all(("%s.%s" % (ns, verb)) in handlers
          for ns, verbs in {
              "agent": ("create", "update", "delete", "get", "list"),
              "team": ("create", "update", "delete", "get", "list"),
              "job": ("create", "dispatch", "delete", "get", "list"),
              "routine": ("create", "update", "delete", "get", "list"),
              "session": ("create", "rename", "delete"),
          }.items() for verb in verbs),
      sorted(handlers))
# The exclusive catalog is the DELTA over the builtin registry, never a second
# copy of it: a create/read a normal agent can do stays builtin (EV-46).
check("A3 typed object tools exist next to the config writer",
      all(n in handlers for n in (
          "provider.upsert", "provider.remove", "provider.add_model",
          "provider.remove_model", "provider.set_default", "provider.reload",
          "skill.remove", "mcp.upsert", "mcp.remove", "mcp.test", "mcp.reload",
          "kb.notebook_rename", "kb.notebook_delete",
          "kb.source_remove", "kb.reembed",
          "webui.inspect", "webui.configure")))
check("A3-dupe the builtin-owned verbs are NOT re-declared as exclusive",
      not any(n in handlers for n in ("session.list", "kb.notebook_add",
                                      "kb.source_add"))
      and {"sessions.list", "knowledge.create_notebook",
           "knowledge.add_source"} <= set(registry.TOOL_SCHEMAS))
check("A3b naming contract: every exclusive tool is EXACTLY `namespace.tool`",
      all(len(k.split(".")) == 2 for k in handlers)
      and all(k.split(".", 1)[0] in LRA.EXCLUSIVE_NAMESPACES for k in handlers)
      and LRA.EXCLUSIVE_NAMESPACES == {"agent", "team", "job", "routine",
                                       "session", "webui", "provider", "mcp",
                                       "skill", "kb"}
      and not any(k.startswith("longrunAgent.") for k in handlers),
      sorted(handlers))
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
t_new = call("team.create",
             {"name": "Finance Ops", "description": "budget, cost and billing"})
tid = (t_new.get("team") or {}).get("id")
check("B1 teams.create stores the description and picks the matching palette icon",
      t_new.get("ok") is True and tid
      and (t_new["team"].get("symbol"), t_new["team"].get("color")) == ("\U0001f4b0", "#22C55E"),
      t_new.get("team"))

t_upd = call("team.update",
             {"team": tid, "description": "security incident triage and red team"})
t_regen = call("team.update", {"team": tid, "regenerate_icon": True})
check("B2 teams.update edits name/description and re-asks longrunAgent for the icon",
      t_upd.get("ok") is True
      and "security" in (TE.REGISTRY.get(tid) or {}).get("description", "")
      and t_regen.get("ok") is True
      and (t_regen["team"].get("symbol"), t_regen["team"].get("color")) == ("\U0001f6a8", "#EF4444"),
      (t_upd.get("changed"), t_regen.get("team")))

t_get = call("team.get", {"team": tid})
t_list = call("team.list", {})
check("B3 teams.get/list read the real store and publish the palette",
      t_get.get("ok") is True and len(t_get.get("palette") or []) == 8
      and t_list.get("ok") is True
      and any(t.get("id") == tid for t in (t_list.get("teams") or [])),
      (t_list.get("count"), len(t_get.get("palette") or [])))

# an agent to move in and out of the team (also used by C/D/E)
a_new = call("agent.create",
             {"name": "Sre Bot", "role": "sre", "prompt": "You watch uptime."})
aid, asid = (a_new.get("agent") or {}).get("id"), a_new.get("session")

m_add = call("team.member_add", {"team": tid, "agent": aid})
in_team = aid in TE.REGISTRY.members_of(tid)
m_del = call("team.member_remove", {"team": tid, "agent": aid})
out_team = aid not in TE.REGISTRY.members_of(tid)
check("B4 teams.member.add/remove move the agent in and out of the team",
      m_add.get("ok") is True and in_team and m_del.get("ok") is True and out_team,
      (in_team, out_team))

t_del = call("team.delete", {"team": tid})
check("B5 teams.delete removes the team but keeps its member agents",
      t_del.get("ok") is True
      and TE.REGISTRY.get(tid) is None
      and A.REGISTRY.get(asid) is not None, t_del)
check("B6 team tools answer with an error (never a crash) on an unknown team",
      call("team.get", {"team": "T999"}).get("ok") is False
      and call("team.delete", {"team": "T999"}).get("ok") is False
      and call("team.update", {"team": "T999", "name": "x"}).get("ok") is False)

# --- C: agents ---------------------------------------------------------------
ws = (a_new.get("agent") or {}).get("workspace") or a_new.get("workspace")
check("C1 agents.create provisions the record, the session, ROLE.md and a workspace folder",
      a_new.get("ok") is True and os.path.isdir(ws)
      and "uptime" in R.read(asid), (ws, a_new.get("model")))

a_upd = call("agent.update",
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
      call("agent.update", {"agent": aid}).get("ok") is False)

p_set = call("agent.prompt_set",
             {"agent": aid, "prompt": "You are the SRE on call."})
p_get = call("agent.prompt_get", {"agent": aid})
p_clr = call("agent.prompt_clear", {"agent": aid})
check("C4 prompt.set/get/clear operate on the real ROLE.md",
      p_set.get("ok") is True
      and "SRE on call" in (p_get.get("prompt") or "")
      and p_clr.get("ok") is True
      and not os.path.isfile(R.path_for(asid)), (p_get.get("chars"), p_clr))

a_get = call("agent.get", {"agent": aid})
a_list = call("agent.list", {})
check("C5 agents.get/list read the real org",
      a_get.get("ok") is True and a_get.get("agent", {}).get("id") == aid
      and a_list.get("ok") is True and a_list.get("count", 0) >= 1)

a_del = call("agent.delete", {"agent": aid})
check("C6 agents.delete cascades: designation + session + workspace folder all gone",
      a_del.get("ok") is True
      and A.REGISTRY.get(asid) is None
      and stores.load_session(asid) is None
      and not os.path.exists(ws), a_del)
check("C7 agents.delete never removes the permanent longrunAgent session",
      call("agent.delete", {"agent": "longrunAgent"}).get("ok") is False)

# --- D: jobs -----------------------------------------------------------------
boss = call("agent.create", {"name": "Job Boss", "role": "lead"})
boss_id, boss_sid = (boss.get("agent") or {}).get("id"), boss.get("session")
worker = call("agent.create", {"name": "Job Worker", "role": "coder"})
worker_id = (worker.get("agent") or {}).get("id")
j_new = call("job.create",
             {"goal": "ship the release notes", "coordinator": boss_id, "agents": [worker_id]})
jid = (j_new.get("job") or {}).get("id")
check("D1 jobs.create stores goal + coordinator + workers",
      j_new.get("ok") is True and jid
      and (j_new["job"].get("goal") == "ship the release notes")
      and worker_id in (j_new["job"].get("agents") or []), j_new.get("job"))
check("D2 jobs.create requires at least one worker agent",
      call("job.create", {"goal": "x", "agents": []}).get("ok") is False)
j_get = call("job.get", {"job": jid})
j_list = call("job.list", {})
check("D3 jobs.get/list read the real registry",
      j_get.get("ok") is True and (j_get.get("job") or {}).get("id") == jid
      and j_list.get("ok") is True
      and any(j.get("id") == jid for j in (j_list.get("jobs") or [])))
j_del = call("job.delete", {"job": jid})
check("D4 jobs.delete removes the job from the real registry",
      j_del.get("ok") is True and (J.JOBS.get(jid) is None))

# --- E: routines -------------------------------------------------------------
rt_new = call("routine.create",
              {"agent": boss_sid, "goal": "check the queue", "every_seconds": 120})
rid = (rt_new.get("routine") or {}).get("id")
check("E1 routines.create schedules the goal for the resolved agent session",
      # v659: the routine used to store whatever the caller typed, so a routine
      # bound by SESSION id vanished from every view that compares agent ids
      # (operator: "routine list -> 0 while get saw R1"). One id-space now: passing
      # the session resolves to the AGENT id — the firing path still resolves that
      # id back to the session (see _canonical_agent + _fire).
      rt_new.get("ok") is True and rid
      and (rt_new["routine"].get("agent") == boss_id)
      and (rt_new["routine"].get("every_seconds") == 120), rt_new.get("routine"))
rt_upd = call("routine.update",
              {"routine": rid, "goal": "check the queue harder", "every_seconds": 300,
               "enabled": False})
rt_rec = RT.REGISTRY.get(rid) or {}
check("E2 routines.update edits only the fields passed (id and runs survive)",
      rt_upd.get("ok") is True
      and rt_rec.get("goal") == "check the queue harder"
      and rt_rec.get("every_seconds") == 300 and rt_rec.get("enabled") is False
      and rt_rec.get("id") == rid, rt_rec)
check("E3 routines.get/list read the real registry",
      call("routine.get", {"routine": rid}).get("ok") is True
      and any(r.get("id") == rid
              for r in (call("routine.list", {}).get("routines") or [])))
check("E4 routines.create refuses an unknown agent",
      call("routine.create",
           {"agent": "nobody", "goal": "x", "every_seconds": 60}).get("ok") is False)
rt_del = call("routine.delete", {"routine": rid})
check("E5 routines.delete removes the routine",
      rt_del.get("ok") is True and RT.REGISTRY.get(rid) is None)

# --- F: sessions -------------------------------------------------------------
s_new = call("session.create", {"title": "JAG-537 probe"})
psid = s_new.get("session")
s_ren = call("session.rename",
             {"session": psid, "title": "JAG-537 probe (renamed)"})
_rows = stores.list_sessions()
check("F1 sessions.create/rename operate on the real store (the TABLE is builtin)",
      s_new.get("ok") is True and (stores.load_session(psid) or {}).get("title") == "JAG-537 probe (renamed)"
      and s_ren.get("ok") is True
      and any(s.get("id") == psid for s in _rows),
      (psid, s_new.get("title")))
s_del = call("session.delete", {"session": psid})
check("F2 sessions.delete removes the session file",
      s_del.get("ok") is True and stores.load_session(psid) is None, s_del)
check("F3 sessions.delete refuses the permanent longrunAgent session and unknown ids",
      call("session.delete", {"session": "longrunAgent"}).get("ok") is False
      and call("session.delete", {"session": "no-such-session"}).get("ok") is False)

# --- G: bounded destructive paths -------------------------------------------
outside = os.path.join(TMP, "not-a-workspace")
os.makedirs(outside, exist_ok=True)
g_res = LRA._remove_workspace_path(outside)
check("G1 a folder outside the workspaces root is NEVER deleted",
      g_res.get("removed") is False and os.path.isdir(outside)
      and "outside" in str(g_res.get("reason")), g_res)

# --- H: typed webui object tools --------------------------------------------
KB = __import__("longrun.memory.knowledge", fromlist=["knowledge"])
# the CREATE is a builtin operation (knowledge.create_notebook); only the verbs
# the builtin tool lacks are exclusive.
nb = KB.create_notebook("jag537-nb")
nb_id = nb.get("id")
nb_ren = call("kb.notebook_rename",
              {"id": nb_id, "name": "jag537-nb-renamed"})
names = [str(n) for n in KB.list_notebooks()]
nb_del = call("kb.notebook_delete", {"id": nb_id})
check("H1 webui.knowledge.notebook.create/rename/delete are real CRUD",
      nb.get("ok") is True and nb_ren.get("ok") is True
      and any("jag537-nb" in n for n in names)
      and nb_del.get("ok") is True
      and not any(nb_id in str(n) for n in KB.list_notebooks()),
      (nb_id, names[:3], nb_del))
check("H2 webui.providers.reload reaches the provider engine",
      call("provider.reload", {}).get("ok") is True)
check("H3 webui.skills.remove / webui.mcp.remove answer with a real result, never a crash",
      isinstance(call("skill.remove", {"name": "no-such-skill"}).get("ok"), bool)
      and isinstance(call("mcp.remove", {"name": "no-such-client"}).get("ok"), bool))
check("H4 the old catch-all still writes CONFIG targets only",
      set(LRA.TOOL_SCHEMAS["webui.configure"]["properties"]["target"]["enum"])
      == {"settings", "rules", "compaction", "routing", "team_policy", "subagents",
          "tools", "index", "config"})

# --- I: the deck shows ONE panel at a time -----------------------------------
with open(os.path.join(REPO, "src", "longrun", "orbit", "web", "orbit.html"),
          encoding="utf-8") as _f:
    DECK = _f.read()
check("I1 the deck has a left rail with one button per panel (v617: select gone)",
      '<nav id="deckRail"' in DECK and 'id="deckView"' not in DECK
      and all(('data-view="%s"' % v) in DECK
              for v in ("agents", "routines", "jobs", "org", "const", "feed"))
      and 'data-view="all"' not in DECK)
check("I2 every deck panel is addressable by its view key",
      all(('data-panel="%s"' % v) in DECK
          for v in ("agents", "routines", "jobs", "org", "const", "feed")))
check("I3 applyView hides every other panel, collapses the empty rows, remembers the choice",
      "applyView(name){" in DECK
      and 'main.classList.toggle("view-one"' in DECK
      and 'main.classList.toggle("view-cols"' in DECK
      and "p.hidden = !show.includes(key)" in DECK
      and "row.hidden = kids.length > 0 && kids.every(k => k.hidden)" in DECK
      and 'localStorage.setItem("orbit_view_v1", view)' in DECK)
check("I4 the single-panel layout takes the full width and drops the column handle",
      "main.view-one .grid2{grid-template-columns:1fr !important}" in DECK
      and "main.view-one .rz-cols{display:none}" in DECK
      and "main.view-one .panel[hidden]{display:none !important}" in DECK
      and "main .grid2[hidden]{display:none !important}" in DECK)
check("I5 the rail is wired on boot and restored from the last choice (v617)",
      'b.onclick = () => this.applyView(b.dataset.view)' in DECK
      and 'localStorage.getItem("orbit_view_v1")' in DECK
      and "this.applyView(saved" in DECK)

# cleanup the probe agents so the shared stores stay clean
for ref in (worker_id, boss_id):
    call("agent.delete", {"agent": ref})

print("---")
print("v537: %d/%d PASS" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
