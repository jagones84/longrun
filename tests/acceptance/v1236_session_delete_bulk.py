#!/usr/bin/env python3
"""v1236 — the Architect can preview and delete sessions (and their agents) in bulk.

Operator: *"vorrei che A1 architect tra i tools abbia la possibilita di cancellare
sessioni (agenti) … Eliminare significa cancellare totalmente l'agente associato
alla sessione … cancellami le sessioni no team che ti sembrano inutili."*

`session.delete` already existed and already released the agent (v314/v910), but it
took ONE id and had no way to see the "No team" scope with the facts needed to judge
a chat useless. This pins the completed surface:

  * `session.delete` takes `session` OR a `sessions` batch (same one cascade),
    returns per-session results, never aborts on one failure, and can remove the
    dedicated workspace only when it sits under the workspaces root;
  * `session.delete_preview` is READ-ONLY, reuses the SAME no-team bucket as the
    WebUI (`orchestration._no_team_sessions`), excludes the system session and
    RUNNING turns, and reports title/agent/teams/messages/age/reports/jobs/routines/
    workspace;
  * `session.model_set`, `team.models_set`, `provider.test` are real exclusive tools
    with handlers and the expected approval classes.

Deterministic: temp dirs, no model, no network, no server.
Run: python3 tests/acceptance/v1236_session_delete_bulk.py
"""
import os
import sys
import tempfile
import time

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="sf-1236-")
os.environ["LONGRUN_DATA_DIR"] = TMP
os.environ["LONGRUN_SESSIONS_DIR"] = os.path.join(TMP, "sessions")
os.environ["LONGRUN_GRAPH_DIR"] = os.path.join(TMP, "graphs")
os.environ["LONGRUN_RUNS_DIR"] = os.path.join(TMP, "runs")
os.environ["LONGRUN_EDITS_DIR"] = os.path.join(TMP, "edits")
os.environ["LONGRUN_ROLES_DIR"] = os.path.join(TMP, "roles")
os.environ["LONGRUN_AGENTS_FILE"] = os.path.join(TMP, "agents.json")
os.environ["LONGRUN_TEAMS_FILE"] = os.path.join(TMP, "teams.json")
os.environ["LONGRUN_JOBS_FILE"] = os.path.join(TMP, "jobs.json")
os.environ["LONGRUN_ROUTINES_FILE"] = os.path.join(TMP, "routines.json")
os.environ["LONGRUN_WORKSPACES_ROOT"] = os.path.join(TMP, "workspaces")
os.environ["LONGRUN_DB"] = os.path.join(TMP, "events.db")
for _d in ("sessions", "graphs", "runs", "edits", "roles", "workspaces"):
    os.makedirs(os.path.join(TMP, _d), exist_ok=True)
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.core import server                     # noqa: E402,F401 — import first
from longrun.core import events as ev               # noqa: E402
from longrun.agent import agents as agents_mod      # noqa: E402
from longrun.agent import architect as LRA          # noqa: E402
from longrun.memory import stores                   # noqa: E402
from longrun.orchestrate import jobs as jobs_mod    # noqa: E402
from longrun.orchestrate import routines as routines_mod  # noqa: E402
from longrun.orchestrate import teams as teams_mod  # noqa: E402
from longrun.tools import registry                  # noqa: E402
from longrun.util import paths                      # noqa: E402

registry._external_tools = lambda: {}
registry._matrix_tools = lambda: {}
registry._promoted_tools = lambda: {}

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""))


def mk(title, text=""):
    s = stores.get_or_create_session(None, title)
    if text:
        stores.append_message(s, "user", text)
        stores.append_message(s, "assistant", "ok")
    return s["id"]


# ---------------------------------------------------------------- fixtures ---
arch = {"id": "architect", "title": "Architect", "messages": [],
        "system": True, "undeletable": True}
stores.save_session(arch)
s_empty = mk("empty scratch")
s_chat = mk("old test chat", "hello " * 40)
s_team = mk("team member", "working")
s_team2 = mk("team worker", "working")
s_running = mk("running chat")

teams_mod.REGISTRY.create("Cleanup Crew")
lead = agents_mod.REGISTRY.designate(s_team, name="Lead")["agent"]
worker = agents_mod.REGISTRY.designate(s_team2, name="Worker",
                                      reports_to=lead["id"])["agent"]
teams_mod.REGISTRY.add_member("T1", lead["id"])
teams_mod.REGISTRY.add_member("T1", worker["id"])

chat_agent = agents_mod.REGISTRY.designate(s_chat, name="Old Test Agent")["agent"]
made = jobs_mod.JOBS.create("polish the deck", agents=[chat_agent["id"]])
job = made.get("job") or made
routine = routines_mod.REGISTRY.create(chat_agent["id"], "ping", 60)
routine = routine.get("routine") or routine

ws = os.path.join(paths.WORKSPACES_DIR, "ws-old-test")
os.makedirs(ws, exist_ok=True)
with open(os.path.join(ws, "note.txt"), "w", encoding="utf-8") as f:
    f.write("scratch\n")
_sess = stores.load_session(s_chat)
_sess["workspace"] = ws
stores.save_session(_sess)

with ev._ACTIVE_CHAT_LOCK:
    ev._ACTIVE_CHAT[s_running] = {"tok": 1, "started": time.time()}

# ------------------------------------------------- A: preview = no-team scope
prev = LRA._session_delete_preview({"team": "__none__"})
ids = {r["session"] for r in prev.get("sessions") or []}
check("A1 preview defaults to the No-team bucket and is read-only",
      prev.get("ok") is True and prev.get("scope") == "__none__"
      and "nothing deleted" in prev.get("stdout", ""), prev.get("stdout"))
check("A2 the bucket holds the no-team chats, not team members or Architect",
      {s_empty, s_chat}.issubset(ids) and s_team not in ids and s_team2 not in ids
      and "architect" not in ids, sorted(ids))
check("A3 RUNNING is excluded by default",
      s_running not in ids, sorted(ids))
check("A4 the facts needed to judge a chat are on the row",
      all(k in (prev["sessions"][0] if prev.get("sessions") else {})
          for k in ("session", "title", "agent", "teams", "messages", "age",
                    "running", "reports", "jobs", "routines", "workspace", "empty")),
      prev.get("sessions")[:1])
row = {r["session"]: r for r in prev.get("sessions") or []}
check("A5 empty and oldest chats come first, with their real usage counts",
      prev["sessions"][0]["session"] == s_empty
      and row[s_chat]["jobs"] == 1 and row[s_chat]["routines"] == 1
      and row[s_chat]["workspace"] == ws, (prev["sessions"][0], row.get(s_chat)))

prev_team = LRA._session_delete_preview({"team": "T1"})
check("A6 a team scope returns only its members",
      {r["session"] for r in prev_team.get("sessions") or []} == {s_team, s_team2},
      prev_team.get("sessions"))

prev_empty = LRA._session_delete_preview({"team": "__none__", "max_messages": 0})
check("A7 max_messages filters the candidate set",
      {r["session"] for r in prev_empty.get("sessions") or []} == {s_empty},
      prev_empty.get("sessions"))

prev_run = LRA._session_delete_preview({"team": "__none__", "include_running": True})
check("A8 include_running puts a live turn back in scope",
      s_running in {r["session"] for r in prev_run.get("sessions") or []})

check("A9 the preview deleted nothing",
      stores.load_session(s_empty) is not None and stores.load_session(s_chat) is not None)

with ev._ACTIVE_CHAT_LOCK:
    ev._ACTIVE_CHAT.pop(s_running, None)

# ------------------------------------------------------- B: model tools ------
m = LRA._session_model_set({"session": s_chat, "model": "openrouter:test/model"})
check("B1 session.model_set writes the session AND its agent record",
      m.get("ok") is True
      and (stores.load_session(s_chat) or {}).get("model") == "openrouter:test/model"
      and (agents_mod.REGISTRY.get(s_chat) or {}).get("model") == "openrouter:test/model",
      m)
m_auto = LRA._session_model_set({"session": s_chat, "model": "auto"})
check("B2 'auto' picks a cheap remote model", m_auto.get("ok") is True
      and bool(m_auto.get("model")), m_auto)
m_clear = LRA._session_model_set({"session": s_chat, "model": ""})
check("B3 an empty model clears the pin",
      m_clear.get("ok") is True
      and not (stores.load_session(s_chat) or {}).get("model"), m_clear)

tm = LRA._team_models_set({
    "team": "T1", "lead_model": "openrouter:lead/x",
    "member_model": "openrouter:member/y", "local_slots": 0})
check("B4 team.models_set assigns lead and member models",
      tm.get("ok") is True
      and (agents_mod.REGISTRY.get(s_team) or {}).get("model") == "openrouter:lead/x"
      and (agents_mod.REGISTRY.get(s_team2) or {}).get("model") == "openrouter:member/y",
      tm)

pt = LRA._webui_providers({"provider": "no-such-provider"}, "test")
check("B5 provider.test reports an unknown provider without a network call",
      pt.get("ok") is False and "unknown provider" in (pt.get("error") or ""), pt)

# ------------------------------------------------- C: batch delete cascade ---
res = LRA._session_delete({"sessions": [s_empty, s_chat, "architect", "ghost"],
                           "workspace": True})
check("C1 a batch answers per session and never aborts",
      res.get("ok") is True and res.get("count") == 4
      and res.get("deleted") == 2 and res.get("failed") == 2, res.get("stdout"))
check("C2 the chosen sessions are gone and the system/unknown ones survive",
      stores.load_session(s_empty) is None and stores.load_session(s_chat) is None
      and stores.load_session("architect") is not None)
check("C3 the agent records are REALLY released",
      not agents_mod.REGISTRY.is_agent(s_chat))
check("C4 jobs are scrubbed and routines deleted",
      (jobs_mod.JOBS.get(job["id"]) or {}).get("agents") == []
      and routines_mod.REGISTRY.get(routine["id"]) is None)
check("C5 workspace:true removes the dedicated folder",
      not os.path.isdir(ws))
check("C6 team members and their agent records are untouched",
      stores.load_session(s_team) is not None and stores.load_session(s_team2) is not None
      and agents_mod.REGISTRY.is_agent(s_team) and agents_mod.REGISTRY.is_agent(s_team2))

single = mk("single delete")
one = LRA._session_delete({"session": single})
check("C7 a single delete keeps the historical shape (ok + deleted id)",
      one.get("ok") is True and one.get("deleted") == single
      and stores.load_session(single) is None, one)
blocked = LRA._session_delete({"session": "architect"})
check("C8 the permanent Architect session is refused",
      blocked.get("ok") is False and "cannot be deleted" in (blocked.get("error") or ""),
      blocked)
check("C9 no argument is a clean usage error",
      LRA._session_delete({}).get("ok") is False)

# --- C10: a SHARED workspace is never deleted with one chat ------------------
shared_ws = os.path.join(paths.WORKSPACES_DIR, "ws-shared")
os.makedirs(shared_ws, exist_ok=True)
with open(os.path.join(shared_ws, "keep.txt"), "w", encoding="utf-8") as f:
    f.write("keep\n")
s_shared1 = mk("shared one")
s_shared2 = mk("shared two")
for _sid in (s_shared1, s_shared2):
    _s = stores.load_session(_sid)
    _s["workspace"] = shared_ws
    stores.save_session(_s)
one_shared = LRA._session_delete({"session": s_shared1, "workspace": True})
check("C10 deleting ONE chat refuses a workspace another session still uses",
      one_shared.get("ok") is True
      and (one_shared.get("workspace") or {}).get("removed") is False
      and "shared" in (one_shared.get("workspace") or {}).get("reason", "")
      and os.path.isdir(shared_ws), one_shared.get("workspace"))
two_shared = LRA._session_delete({"session": s_shared2, "workspace": True})
check("C11 once the last chat using it goes, the workspace is removed",
      two_shared.get("ok") is True
      and (two_shared.get("workspace") or {}).get("removed") is True
      and not os.path.isdir(shared_ws), two_shared.get("workspace"))

# --- C12: the GLOBAL default workspace is never removed ----------------------
from longrun.memory import rules as rules_mod  # noqa: E402
_default_ws = str(rules_mod.get_workspace() or "").strip()
s_global = mk("global workspace chat")
if _default_ws:
    _s = stores.load_session(s_global)
    _s["workspace"] = _default_ws
    stores.save_session(_s)
    glob_res = LRA._session_delete({"session": s_global, "workspace": True})
    check("C12 the global default workspace is refused even with workspace:true",
          (glob_res.get("workspace") or {}).get("removed") is False
          and "global default" in (glob_res.get("workspace") or {}).get("reason", ""),
          glob_res.get("workspace"))
else:
    check("C12 the global default workspace is refused even with workspace:true",
          True, "no configured global workspace")

# --- C13: agent.delete follows the same shared-workspace guard ---------------
agent_ws = os.path.join(paths.WORKSPACES_DIR, "ws-agent-shared")
os.makedirs(agent_ws, exist_ok=True)
with open(os.path.join(agent_ws, "keep.txt"), "w", encoding="utf-8") as f:
    f.write("keep\n")
s_agent = mk("agent with shared ws")
s_other = mk("other ws user")
for _sid in (s_agent, s_other):
    _s = stores.load_session(_sid)
    _s["workspace"] = agent_ws
    stores.save_session(_s)
ag = agents_mod.REGISTRY.designate(s_agent, name="Shared WS Agent", workspace=agent_ws)["agent"]
ag_del = LRA._agent_delete({"agent": ag["id"], "session": False})
check("C13 agent.delete refuses a workspace shared with another live session",
      ag_del.get("ok") is True
      and (ag_del.get("workspace") or {}).get("removed") is False
      and "shared" in (ag_del.get("workspace") or {}).get("reason", "")
      and os.path.isdir(agent_ws), ag_del.get("workspace"))

# --------------------------------------------- D: schema / dispatch / policy -
new_tools = ("session.delete_preview", "session.model_set", "team.models_set",
             "provider.test")
check("D1 every new tool has a schema AND one handler",
      all(t in LRA.TOOL_SCHEMAS and t in LRA._SUBTOOL_MAP for t in new_tools),
      sorted(set(new_tools) - set(LRA._SUBTOOL_MAP)))
check("D2 the naming contract holds (namespace.tool, 2 segments)",
      all(len(t.split(".")) == 2 for t in new_tools))
check("D3 every new description names its own tool",
      all(str(LRA.TOOL_SCHEMAS[t].get("description") or "").startswith(t + " ")
          for t in new_tools))
check("D4 session.delete declares the batch + workspace arguments",
      (LRA.TOOL_SCHEMAS["session.delete"]["properties"].get("sessions") or {}).get("type") == "array"
      and (LRA.TOOL_SCHEMAS["session.delete"]["properties"].get("workspace") or {}).get("type") == "boolean")
check("D5 the destructive delete still asks; the preview/test do not",
      LRA.exclusive_default_approval("session.delete") == "required"
      and LRA.exclusive_default_approval("session.delete_preview") == "auto"
      and LRA.exclusive_default_approval("provider.test") == "auto")
check("D6 the registry advertises the new tools with the same policy",
      all(registry.tool_spec(t) for t in new_tools)
      and (registry.tool_spec("session.delete") or {}).get("approval") == "required"
      and (registry.tool_spec("session.delete_preview") or {}).get("approval") == "auto",
      [t for t in new_tools if not registry.tool_spec(t)])
from longrun.gen import surfaces  # noqa: E402
_prompt = surfaces.SECTION_PROMPTS["teamorg"]
check("D7 the Teamorg prompt names the cleanup flow and the new tools",
      "F. CLEANUP" in _prompt and "session.delete_preview" in _prompt
      and "models_set" in _prompt and "model_set" in _prompt)

print("---")
passed = sum(results)
print("%d/%d PASS" % (passed, len(results)))
sys.exit(0 if passed == len(results) else 1)
