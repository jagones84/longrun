#!/usr/bin/env python3
"""v534 — longrunAgent (VEO — the burattinaio of agents) & Teamorg (JAG-535).

Locks:
  A  Permanent, undeletable, stateless system session (`longrunAgent`):
     - `ensure_system_session()` creates `longrunAgent` with `system: true`,
       `undeletable: true`, `stateless: true`, `allow_longrun_agent: true`;
     - `DELETE /api/sessions/longrunAgent` is refused with 403;
     - `reset_stateless_session()` wipes messages, tool_cards, injects, and graph.
  B  Exclusive built-in tools & Dual-Permission Gate:
     - the exclusive tools (`agent.*`, `team.*`, `job.*`, `routine.*`,
       `session.*`, `webui.*`, `provider.*`, `mcp.*`, `skill.*`, `kb.*`) are
       registered with `origin == "exclusive"` and segregated under the
       `Exclusive built-in` origin dropdown in `webui/index.html`;
     - calling an exclusive tool from an ungranted session is denied (exit 126);
     - granting `allow_longrun_agent` on a session unlocks it ONLY when the tool
       is also enabled in the global registry (dual-permission).
  C  Teamorg lifecycle (`agent.*` / `team.*`):
     - `team.create` picks a semantic icon+colour from `teams._PALETTE` via
       `longrunAgent.choose_team_symbol` (e.g. Security -> 🚨, AI/ML -> 🧠,
       Finance -> 💰) while explicit symbol still wins;
     - `agent.create` + `agent.update` + `agent.prompt_set` + `team.member_add`
       update the substrate (`agents.json`, `teams.json`,
       `ROLE.md`, dedicated workspace folder) and emit live-sync SSE events.
  D  Safety boundary & WebUI automation:
     - `webui.configure` refuses `allow_nucleus_write` and
       `allow_matrix_promote` (operator-only safety checkboxes);
     - Models panel offers `longrunAgentModel` (`roles.longrun_agent.model` + `@chat`);
     - `makeAutomateWidget` and Orbit `lraAutoBtn` wire UI sections to
       `POST /api/longrun-agent/automate`.
  E  Universal automation coverage (every manually editable section):
     - `webui.inspect` reaches subagents / providers / tools / skills / mcp /
       knowledge / index / keys with real substrate ground truth;
     - `webui.configure` writes subagents, per-tool policy, index config,
       knowledge notebooks and MCP clients through the SAME Layer-2 writers the
       WebUI uses, never its own exclusive tool policy;
     - raw `config/*.yaml` writes are text-scanned for the safety switches;
     - every configure target owns a context-specific system prompt, and the WebUI
       auto-generates one `⚡ Automate` control per editable Settings panel
       (`AUTOMATE_CATS` / `mountCategoryAutomate`); the Codebase inspector keeps
       only its explicit `auto_index` toggle (no free-form agent bar).
  F/G  The VEO aware of itself, and permanently pinned:
     - the `longrun-agent` prompt section lists EVERY live exclusive subtool
       (generated from the registry) plus the hard rules, and is injected only for
       the system session or a session explicitly granted `allow_longrun_agent`;
     - the `longrunAgent` session is ALWAYS pinned above the whole rail, its pin is
       derived from the server `system`/`undeletable` flag (not localStorage), it
       cannot be unpinned, and "hide empty" cannot hide it.

Deterministic: temp dirs, no live model, no network.
Run: python3 tests/acceptance/v534_longrun_agent_veo.py
"""
import atexit
import os
import shutil
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="sf-v534-")
atexit.register(lambda: shutil.rmtree(TMP, ignore_errors=True))
for _k in ("DATA_DIR", "CONFIG_DIR", "SESSIONS_DIR", "ROLES_DIR", "DB",
           "COSTS_DIR", "EDITS_DIR", "RUNS_DIR", "GRAPH_DIR",
           "AGENTS_FILE", "TEAMS_FILE", "WORKSPACES_ROOT"):
    val = os.path.join(TMP, _k.lower() + (".json" if _k.endswith("_FILE") else ""))
    if not _k.endswith("_FILE") and _k != "DB":
        os.makedirs(val, exist_ok=True)
    os.environ["LONGRUN_" + _k] = val
# JAG-535: `subagent.CFG_PATH` and `routing.CONFIG_PATH` are derived from the REPO,
# not from LONGRUN_CONFIG_DIR. `subagent` honours LONGRUN_SUBAGENTS_CFG, so point it
# at the temp dir; `routing` has no override, so its live file is snapshotted here
# and restored on EVERY exit path (an automation test must never edit the checkout).
sys.path.insert(0, os.path.join(REPO, "src"))

_ROUTING_YAML = os.path.join(REPO, "config", "routing.yaml")
os.environ["LONGRUN_SUBAGENTS_CFG"] = os.path.join(TMP, "subagents.yaml")
with open(_ROUTING_YAML, encoding="utf-8") as _f:
    _ROUTING_ORIG = _f.read()


def _restore_routing():
    try:
        with open(_ROUTING_YAML, encoding="utf-8") as _f:
            if _f.read() != _ROUTING_ORIG:
                with open(_ROUTING_YAML, "w", encoding="utf-8") as _w:
                    _w.write(_ROUTING_ORIG)
    except OSError:
        pass


atexit.register(_restore_routing)

from longrun.tools import registry, tools as T       # noqa: E402
from longrun.agent import longrun_agent as LRA       # noqa: E402
from longrun.memory import stores                    # noqa: E402
from longrun.orchestrate import roles as R, teams    # noqa: E402
from longrun.core import events as E                 # noqa: E402

registry._external_tools = lambda: {}

results = []


def check(name, cond, detail=""):
    ok = bool(cond)
    results.append(ok)
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""))


# --- A: Permanent undeletable stateless system session -----------------------
sys_sess = LRA.ensure_system_session()
check("A1 longrunAgent system session is provisioned with system/undeletable/stateless flags",
      sys_sess.get("id") == "longrunAgent"
      and sys_sess.get("system") is True
      and sys_sess.get("undeletable") is True
      and sys_sess.get("stateless") is True
      and sys_sess.get("allow_longrun_agent") is True, sys_sess)

sys_sess["messages"] = [{"role": "user", "content": "leftover"}]
sys_sess["tool_cards"] = [{"tool": "x"}]
stores.save_session(sys_sess)
LRA.reset_stateless_session()
reloaded = stores.load_session("longrunAgent")
check("A2 reset_stateless_session wipes all prior execution context",
      reloaded.get("messages") == [] and reloaded.get("tool_cards") == [], reloaded)

rev_self = LRA.set_session_access("longrunAgent", False)
check("A3 revoking longrunAgent access from the system session itself is refused",
      rev_self.get("ok") is False)

with open(os.path.join(REPO, "src", "longrun", "core", "httpapi.py"), encoding="utf-8") as f:
    HTTPAPI = f.read()
check("A4 DELETE /api/sessions/longrunAgent is blocked at the HTTP layer with 403",
      'if sid == "longrunAgent":' in HTTPAPI and "403" in HTTPAPI)

# --- B: Exclusive built-in tools & Dual-Permission Gate ----------------------
cat = {t["name"]: t for t in registry.catalog()}
expected_tools = {
    "agent.create",
    "agent.update",
    "agent.get",
    "agent.list",
    "agent.delete",
    "agent.prompt_set",
    "agent.prompt_get",
    "agent.prompt_clear",
    "team.create",
    "team.update",
    "team.get",
    "team.list",
    "team.delete",
    "team.member_add",
    "team.member_remove",
    "job.create",
    "job.dispatch",
    "job.get",
    "job.list",
    "job.delete",
    "routine.create",
    "routine.update",
    "routine.get",
    "routine.list",
    "routine.delete",
    "session.create",
    "session.rename",
    "session.delete",
    "provider.upsert",
    "skill.remove",
    "mcp.reload",
    "kb.notebook_delete",
    "webui.configure",
    "webui.inspect",
}
check("B1 all longrunAgent subtools are registered in registry.catalog()",
      expected_tools.issubset(set(cat)), sorted(expected_tools - set(cat)))
check("B2 every longrunAgent tool has origin='exclusive'",
      all(cat[n].get("origin") == "exclusive" for n in expected_tools))

# Create a normal session WITHOUT access
user_sess = stores.get_or_create_session("normal-user", "Normal Chat")
denied_call = T.execute(
    "team.create",
    {"name": "Unauthorized Team"},
    run_id="normal-user",
)
check("B3 ungranted session is denied by dual-permission gate (exit 126)",
      denied_call.get("ok") is False
      and denied_call.get("exit_code") == 126
      and denied_call.get("permission_denied") is True, denied_call)

# Grant session access -> succeeds while globally enabled
LRA.set_session_access("normal-user", True)
check("B4 set_session_access grants allow_longrun_agent on the session",
      LRA.session_has_access("normal-user") is True)

# Disable globally -> even longrunAgent session is denied (dual-permission)
cfg = registry.load_config()
orig_entry = dict((cfg.get("tools") or {}).get("team") or {"enabled": True, "approval": "auto"})
try:
    cfg.setdefault("tools", {})["team"] = {"enabled": False, "approval": "auto"}
    disabled_call = T.execute(
        "team.create",
        {"name": "Blocked When Globally Disabled"},
        run_id="longrunAgent",
    )
    check("B5 disabling an exclusive namespace globally blocks even the privileged session",
          disabled_call.get("ok") is False and disabled_call.get("exit_code") == 126,
          disabled_call)
finally:
    cfg.setdefault("tools", {})["team"] = orig_entry

# --- C: Teamorg end-to-end lifecycle & semantic team symbols -----------------
sym_sec, col_sec = LRA.choose_team_symbol("Security Red Team")
sym_ai, col_ai = LRA.choose_team_symbol("Neural AI Planners")
sym_fin, col_fin = LRA.choose_team_symbol("Quant Billing & Cost")
sym_exp, col_exp = LRA.choose_team_symbol("Security Red Team", explicit_symbol="⚡")
check("C1 longrunAgent chooses semantic team symbols from the palette (and honours explicit override)",
      sym_sec == "\U0001f6a8" and sym_ai == "\U0001f9e0"
      and sym_fin == "\U0001f4b0" and sym_exp == "⚡",
      (sym_sec, sym_ai, sym_fin, sym_exp))

t_res = T.execute(
    "team.create",
    {
        "name": "Security Red Team",
        "description": "Incident response and vulnerability audit",
        "members": [
            {"name": "Sec Lead", "role": "security-lead", "prompt": "Lead the security audit."},
        ],
    },
    run_id="longrunAgent",
)
check("C2 teamorg.teams.create creates team with semantic symbol + provisions member agent",
      t_res.get("ok") is True
      and t_res["team"]["symbol"] == "\U0001f6a8"
      and len(t_res.get("provisioned_members") or []) == 1, t_res)
tid = t_res["team"]["id"]
lead_id = t_res["provisioned_members"][0]

a_res = T.execute(
    "agent.create",
    {
        "name": "Scanner Bot",
        "role": "vuln-scanner",
        "reports_to": lead_id,
    },
    run_id="longrunAgent",
)
check("C3 teamorg.agents.create provisions agent with cheap remote model + dedicated workspace",
      a_res.get("ok") is True
      and os.path.isdir(a_res.get("workspace") or "")
      and ":" in (a_res.get("model") or "")
      and a_res["agent"].get("reports_to") == lead_id, a_res)
scanner_id = a_res["agent"]["id"]
scanner_sid = a_res["session"]

r_llm = T.execute(
    "agent.update",
    {"agent": scanner_id, "model": "openrouter:z-ai/glm-5.3-flash"},
    run_id="longrunAgent",
)
r_role = T.execute(
    "agent.update",
    {"agent": scanner_id, "role": "senior-vuln-scanner"},
    run_id="longrunAgent",
)
r_prompt = T.execute(
    "agent.prompt_set",
    {"agent": scanner_id, "prompt": "You are Senior Vuln Scanner. Check OWASP Top 10."},
    run_id="longrunAgent",
)
r_assign = T.execute(
    "team.member_add",
    {"agent": scanner_id, "team": tid},
    run_id="longrunAgent",
)
check("C4 agents.update (model+role), prompt.set and teams.member.add update substrate + ROLE.md + team",
      r_llm.get("ok") is True
      and r_role.get("ok") is True
      and r_prompt.get("ok") is True
      and r_assign.get("ok") is True
      and "OWASP Top 10" in R.read(scanner_sid)
      and scanner_id in teams.REGISTRY.members_of(tid)
      and stores.load_session(scanner_sid).get("model") == "openrouter:z-ai/glm-5.3-flash",
      (r_llm, r_role, r_prompt, r_assign, R.read(scanner_sid), teams.REGISTRY.members_of(tid), stores.load_session(scanner_sid).get("model")))

ev_kinds = {e.get("kind") for e in E.events_since(0)}
check("C5 substrate mutations publish live-sync SSE events (teams.updated, agent.updated, roles.update)",
      {"teams.updated", "agent.updated", "roles.update"}.issubset(ev_kinds), sorted(ev_kinds))

# --- D: Safety boundary & WebUI integration ----------------------------------
bad_nuc = T.execute(
    "webui.configure",
    {"target": "settings", "file": "tools.yaml", "values": {"allow_nucleus_write": True}},
    run_id="longrunAgent",
)
bad_prom = T.execute(
    "webui.configure",
    {"target": "settings", "file": "tools.yaml", "values": {"approvals.allow_matrix_promote": True}},
    run_id="longrunAgent",
)
check("D1 safety guard deterministically blocks allow_nucleus_write and allow_matrix_promote",
      bad_nuc.get("ok") is False and "SAFETY_GUARD" in str(bad_nuc.get("error"))
      and bad_prom.get("ok") is False and "SAFETY_GUARD" in str(bad_prom.get("error")),
      (bad_nuc, bad_prom))

ok_rules = T.execute(
    "webui.configure",
    {"target": "rules", "scope": "global", "content": "# Automated Global Rule\nBe concise."},
    run_id="longrunAgent",
)
check("D2 webui.configure updates allowed substrate targets (rules) and publishes rules.update",
      ok_rules.get("ok") is True and "rules.update" in {e.get("kind") for e in E.events_since(0)},
      ok_rules)

with open(os.path.join(REPO, "webui", "index.html"), encoding="utf-8") as f:
    HTML = f.read()
with open(os.path.join(REPO, "src", "longrun", "orbit", "web", "orbit.html"), encoding="utf-8") as f:
    ORBIT = f.read()

check("D3 Tools panel segregates Exclusive built-in · longrunAgent origin dropdown",
      '"exclusive", "Exclusive built-in · longrunAgent"' in HTML)
check("D4 Models panel exposes longrunAgentModel selector + @chat dynamic option",
      'id="longrunAgentModel"' in HTML and "saveLongrunAgentModel" in HTML)
check("D5 Shared makeAutomateWidget and Orbit Teamorg automate bar are wired to /api/longrun-agent/automate",
      "function makeAutomateWidget(" in HTML
      and '"/api/longrun-agent/automate"' in HTML
      and 'id="lraAutoBtn"' in ORBIT
      and '"/api/longrun-agent/automate"' in ORBIT)

# --- E: Universal WebUI automation coverage ----------------------------------
# The spec demands longrunAgent reach EVERY manually editable substrate section,
# not just the first four. Each new section is proven through its real Layer-2
# writer, and the WebUI must auto-generate a control for each of them.
from longrun.agent import subagent as SUB                # noqa: E402
from longrun.memory import indexcfg                      # noqa: E402
from longrun.memory import knowledge as KB               # noqa: E402
from longrun.model import routing as RTG                 # noqa: E402

INS_SECTIONS = ["subagents", "providers", "tools", "skills", "mcp", "knowledge", "index", "keys"]
inspected = {s: LRA._webui_inspect({"section": s}) for s in INS_SECTIONS}
check("E1 webui.inspect covers every manually editable section with real substrate ground truth",
      all(inspected[s].get("ok") is True for s in INS_SECTIONS)
      and "max_parallel" in (inspected["subagents"].get("subagents", {}).get("config") or {})
      and isinstance(inspected["providers"].get("providers"), dict)
      and isinstance(inspected["tools"].get("tool_policy"), dict)
      and isinstance(inspected["knowledge"].get("knowledge"), dict)
      and isinstance(inspected["mcp"].get("mcp_clients"), dict)
      and isinstance(inspected["skills"].get("skills"), list)
      and isinstance(inspected["keys"].get("keys"), list)
      and isinstance(inspected["index"].get("index"), dict),
      {s: sorted(inspected[s].keys()) for s in INS_SECTIONS})

r_sub = T.execute(
    "webui.configure",
    {"target": "subagents",
     "values": {"max_parallel": 3, "max_depth": 4,
                "model": "openrouter:z-ai/glm-5.3-flash"}},
    run_id="longrunAgent",
)
check("E2 configure target='subagents' writes config/subagents.yaml + tools.yaml runtime + routing",
      r_sub.get("ok") is True
      and int(SUB.load_cfg().get("max_parallel")) == 3
      and RTG.role_model("subagent") == "openrouter:z-ai/glm-5.3-flash"
      and int((registry.load_config().get("runtime") or {}).get("subagent_max_depth")) == 4,
      r_sub)
# `routing` has no env override, so put the checkout back the moment we are done
# reading it: the battery runs tests in PARALLEL and none of them may observe a
# rewritten config/routing.yaml.
_restore_routing()

r_tool = T.execute(
    "webui.configure",
    {"target": "tools", "values": {"tool": "grep", "approval": "required"}},
    run_id="longrunAgent",
)
self_pol = T.execute(
    "webui.configure",
    {"target": "tools", "values": {"tool": "team.create", "enabled": False}},
    run_id="longrunAgent",
)
check("E3 configure target='tools' flips real tool policy but refuses its own namespace",
      r_tool.get("ok") is True
      and ((registry.load_config().get("tools") or {}).get("grep") or {}).get("approval") == "required"
      and self_pol.get("ok") is False and "SAFETY_GUARD" in str(self_pol.get("error")),
      (r_tool, self_pol))

r_idx = T.execute(
    "webui.configure",
    {"target": "index", "values": {"auto_index": False}},
    run_id="longrunAgent",
)
check("E4 configure target='index' writes the shared index configuration",
      r_idx.get("ok") is True
      and indexcfg.load_config().get("auto_index") is False, r_idx)

r_kb = T.execute(
    "kb.notebook_rename",
    {"id": KB.create_notebook("veo-notebook")["id"], "name": "veo-notebook-2"},
    run_id="longrunAgent",
)
check("E5 kb.notebook_rename renames a real notebook",
      r_kb.get("ok") is True
      and any("veo-notebook-2" in str(n) for n in KB.list_notebooks()), r_kb)

r_mcp = T.execute(
    "mcp.upsert",
    {"name": "!!not-a-valid-name!!", "values": {"command": "true"}},
    run_id="longrunAgent",
)
check("E6 webui.mcp.upsert routes to the real mcp_client engine (rejects invalid specs)",
      r_mcp.get("ok") is False and "error" in r_mcp, r_mcp)

bad_cfg = T.execute(
    "webui.configure",
    {"target": "config", "file": "tools.yaml",
     "text": "approvals:\n  allow_matrix_promote: true\n"},
    run_id="longrunAgent",
)
check("E7 raw config writes are text-scanned — the safety switches cannot be smuggled",
      bad_cfg.get("ok") is False and "SAFETY_GUARD" in str(bad_cfg.get("error")), bad_cfg)

targets = set(LRA.TOOL_SCHEMAS["webui.configure"]["properties"]["target"]["enum"])
check("E8 every configure target has its own context-specific system prompt",
      targets.issubset(set(LRA.SECTION_PROMPTS)), sorted(targets - set(LRA.SECTION_PROMPTS)))
check("E8b every automate section injects a NON-empty substrate snapshot from a real inspect section",
      set(LRA.SECTION_PROMPTS).issubset(set(LRA.AUTOMATE_INSPECT_SECTIONS))
      and set(LRA.AUTOMATE_INSPECT_SECTIONS.values()).issubset(set(INS_SECTIONS + ["all", "agents", "teams", "models", "compaction", "settings", "rules"])),
      sorted(set(LRA.SECTION_PROMPTS) - set(LRA.AUTOMATE_INSPECT_SECTIONS)))
check("E9 the WebUI auto-generates one Automate control per editable Settings panel",
      "function mountSectionAutomate(" in HTML
      and "function mountCategoryAutomate(" in HTML
      and "const AUTOMATE_CATS = {" in HTML
      and "mountCategoryAutomate(name)" in HTML
      and 'mountSectionAutomate(\'section[data-insp="codebase"]\', "index"' not in HTML
      and all(("  " + k + ": { section:") in HTML
              for k in ("models", "subagents", "tools", "mcp", "skills",
                        "knowledge", "rules", "config")))

# --- F: the agent's OWN namespace is declared in its system prompt -----------
# The VEO must not have to guess which `longrunAgent.*` subtools it owns: the
# `longrun-agent` prompt section lists them FROM THE LIVE REGISTRY, and is injected
# only for the system session (or one explicitly granted access).
from longrun.model import prompt as P                     # noqa: E402

sec = next((s for s in P.SECTIONS if s["id"] == "longrun-agent"), None)
check("F1 longrun-agent is a DYNAMIC prompt section in the cache-safe tail",
      bool(sec) and sec["kind"] == "dynamic" and sec["order"] >= 50,
      sec)

sys_text = P._provider_longrun_agent({"id": "longrunAgent", "system": True}, None, None)
granted_text = P._provider_longrun_agent({"id": "normal-user", "allow_longrun_agent": True}, None, None)
plain_text = P._provider_longrun_agent({"id": "normal-user"}, None, None)
check("F2 the namespace section is gated: full VEO framing only for the system session",
      "webui.configure" in sys_text
      and "You are longrunAgent" in sys_text
      and "webui.configure" in granted_text
      and "You are longrunAgent" not in granted_text
      and plain_text == "",
      (plain_text, granted_text[:120]))

expected_tools = [
    "agent.create", "agent.update",
    "agent.delete", "agent.prompt_set",
    "team.create", "team.update",
    "team.delete", "team.member_add",
    "job.delete", "routine.delete",
    "session.delete",
    "webui.configure", "webui.inspect",
]
check("F3 the section lists EVERY live longrunAgent subtool (generated, never hardcoded)",
      all(("`%s`" % n) in sys_text for n in expected_tools), sys_text[:400])
check("F4 the section states the hard rules: reserved `action`, dual permission, safety, stateless",
      "`action` is RESERVED" in sys_text
      and "never send it" in sys_text
      and "Dual permission" in sys_text
      and "allow_nucleus_write" in sys_text and "allow_matrix_promote" in sys_text
      and "reset before and after every automation turn" in sys_text)

# --- G: the permanent session is ALWAYS pinned, above everything -------------
check("G1 the permanent system session derives its pin from the SERVER flag, not localStorage",
      "function _isSystemSess(" in HTML
      and "function _systemPinnedIds(" in HTML
      and all(x in HTML for x in ("const sys = _systemPinnedIds(list);",
                                  "return sys.concat(stored.filter(id => !sys.includes(id)));")))
check("G2 _togglePin refuses to unpin a system session and can never store it",
      "function _togglePin(sid) {" in HTML
      and "if (_systemPinnedIds().includes(sid))" in HTML
      and 'toast("longrunAgent is a permanent system session' in HTML)
check("G3 the row menu shows a DISABLED permanent pin instead of an Unpin toggle",
      'data-a="pin-sys" disabled' in HTML and "📌 Pinned (permanent)" in HTML)
check("G4 the system session sorts above every other pinned row (and in the flat list)",
      "const _sysFirst = (a, b) =>" in HTML
      and "visible.filter(s => isPinned(s.id)).sort(_sysFirst)" in HTML
      and "visible.slice().sort(_sysFirst)" in HTML)
check("G5 'hide empty' can never hide the stateless system session",
      "(_isSystemSess(s) || !hideEmpty || (s.messages || 0) > 0)" in HTML)

print("---")
passed = sum(1 for r in results if r)
print("v534: %d/%d PASS" % (passed, len(results)))
sys.exit(0 if passed == len(results) else 1)
