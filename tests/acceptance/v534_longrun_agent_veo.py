#!/usr/bin/env python3
"""v534 — longrunAgent (VEO — the burattinaio of agents) & Teamorg (JAG-535).

Locks:
  A  Permanent, undeletable, stateless system session (`longrunAgent`):
     - `ensure_system_session()` creates `longrunAgent` with `system: true`,
       `undeletable: true`, `stateless: true`, `allow_longrun_agent: true`;
     - `DELETE /api/sessions/longrunAgent` is refused with 403;
     - `reset_stateless_session()` wipes messages, tool_cards, injects, and graph.
  B  Exclusive built-in tools & Dual-Permission Gate:
     - `longrunAgent.teamorg.*` and `longrunAgent.webui.*` are registered with
       `origin == "exclusive"` and segregated under the `Exclusive built-in`
       origin dropdown in `webui/index.html`;
     - calling a `longrunAgent.*` tool from an ungranted session is denied (exit 126);
     - granting `allow_longrun_agent` on a session unlocks it ONLY when the tool
       is also enabled in the global registry (dual-permission).
  C  Teamorg lifecycle (`longrunAgent.teamorg.*`):
     - `teams.create` picks a semantic icon+colour from `teams._PALETTE` via
       `longrunAgent.choose_team_symbol` (e.g. Security -> 🚨, AI/ML -> 🧠,
       Finance -> 💰) while explicit symbol still wins;
     - `agents.create`, `agents.setllm`, `agents.setrole`, `agents.setprompt`,
       `agents.assignagent` update the substrate (`agents.json`, `teams.json`,
       `ROLE.md`, dedicated workspace folder) and emit live-sync SSE events.
  D  Safety boundary & WebUI automation:
     - `longrunAgent.webui.configure` refuses `allow_nucleus_write` and
       `allow_matrix_promote` (operator-only safety checkboxes);
     - Models panel offers `longrunAgentModel` (`roles.longrun_agent.model` + `@chat`);
     - `makeAutomateWidget` and Orbit `lraAutoBtn` wire UI sections to
       `POST /api/longrun-agent/automate`.

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
sys.path.insert(0, os.path.join(REPO, "src"))

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
    "longrunAgent.teamorg.agents.create",
    "longrunAgent.teamorg.agents.setllm",
    "longrunAgent.teamorg.agents.setrole",
    "longrunAgent.teamorg.agents.setprompt",
    "longrunAgent.teamorg.agents.assignagent",
    "longrunAgent.teamorg.teams.create",
    "longrunAgent.webui.inspect",
    "longrunAgent.webui.configure",
}
check("B1 all longrunAgent subtools are registered in registry.catalog()",
      expected_tools.issubset(set(cat)), sorted(expected_tools - set(cat)))
check("B2 every longrunAgent tool has origin='exclusive'",
      all(cat[n].get("origin") == "exclusive" for n in expected_tools))

# Create a normal session WITHOUT access
user_sess = stores.get_or_create_session("normal-user", "Normal Chat")
denied_call = T.execute(
    "longrunAgent.teamorg.teams.create",
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
orig_entry = dict((cfg.get("tools") or {}).get("longrunAgent") or {"enabled": True, "approval": "auto"})
try:
    cfg.setdefault("tools", {})["longrunAgent"] = {"enabled": False, "approval": "auto"}
    disabled_call = T.execute(
        "longrunAgent.teamorg.teams.create",
        {"name": "Blocked When Globally Disabled"},
        run_id="longrunAgent",
    )
    check("B5 disabling longrunAgent globally blocks even the privileged session",
          disabled_call.get("ok") is False and disabled_call.get("exit_code") == 126,
          disabled_call)
finally:
    cfg.setdefault("tools", {})["longrunAgent"] = orig_entry

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
    "longrunAgent.teamorg.teams.create",
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
    "longrunAgent.teamorg.agents.create",
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
    "longrunAgent.teamorg.agents.setllm",
    {"agent": scanner_id, "model": "openrouter:z-ai/glm-5.3-flash"},
    run_id="longrunAgent",
)
r_role = T.execute(
    "longrunAgent.teamorg.agents.setrole",
    {"agent": scanner_id, "role": "senior-vuln-scanner"},
    run_id="longrunAgent",
)
r_prompt = T.execute(
    "longrunAgent.teamorg.agents.setprompt",
    {"agent": scanner_id, "prompt": "You are Senior Vuln Scanner. Check OWASP Top 10."},
    run_id="longrunAgent",
)
r_assign = T.execute(
    "longrunAgent.teamorg.agents.assignagent",
    {"agent": scanner_id, "team": tid},
    run_id="longrunAgent",
)
check("C4 setllm, setrole, setprompt, and assignagent update substrate + ROLE.md + team membership",
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
    "longrunAgent.webui.configure",
    {"target": "settings", "file": "tools.yaml", "values": {"allow_nucleus_write": True}},
    run_id="longrunAgent",
)
bad_prom = T.execute(
    "longrunAgent.webui.configure",
    {"target": "settings", "file": "tools.yaml", "values": {"approvals.allow_matrix_promote": True}},
    run_id="longrunAgent",
)
check("D1 safety guard deterministically blocks allow_nucleus_write and allow_matrix_promote",
      bad_nuc.get("ok") is False and "SAFETY_GUARD" in str(bad_nuc.get("error"))
      and bad_prom.get("ok") is False and "SAFETY_GUARD" in str(bad_prom.get("error")),
      (bad_nuc, bad_prom))

ok_rules = T.execute(
    "longrunAgent.webui.configure",
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

print("---")
passed = sum(1 for r in results if r)
print("v534: %d/%d PASS" % (passed, len(results)))
sys.exit(0 if passed == len(results) else 1)
