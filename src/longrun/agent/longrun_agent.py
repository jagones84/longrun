"""longrunAgent (VEO — the burattinaio of agents) — JAG-535.

Permanent, undeletable, stateless system automation agent that manages the
substrate (Layer 2) of the Longrun harness:
  - Teamorg (`agent.*`, `team.*`, `job.*`, `routine.*`, `session.*`): full
    lifecycle of Orbit AGENTS & TEAMS (creating teams with semantic icon/colour
    chosen from the palette, provisioning agent records + dedicated workspace
    folders, assigning cheap remote LLM models, setting functional roles,
    writing system prompts in ROLE.md, and assigning agents to teams).
  - Universal WebUI substrate automation (`webui.*`, `provider.*`, `mcp.*`,
    `skill.*`, `kb.*`): reading and updating any configurable section of the
    platform (settings forms, rules, routing, compaction) while strictly
    enforcing safety boundaries (NEVER allowed to enable `allow_nucleus_write`
    or `allow_matrix_promote` — those belong exclusively to the human operator).
  - Naming: every exclusive tool is exactly `namespace.tool` (two segments, one
    object namespace, one explicative verb: `agent.prompt_set`, `team.member_add`,
    `kb.notebook_add`). No deeper dotted paths: they produced unreadable names
    (`longrunAgent.teamorg.agents.prompt.set`) and unordered panels.
  - Dual-permission gate: an exclusive tool can execute ONLY when:
      1) the tool is enabled in the global Tool registry (`config/tools.yaml` /
         overlay), AND
      2) the calling session is either the permanent `longrunAgent` system
         session itself or a session explicitly granted `allow_longrun_agent`
         access.
  - Stateless execution: every automation invocation clears the `longrunAgent`
    session history before and after running, injects a section-specific system
    prompt, and uses the configured `roles.longrun_agent.model` (or `@chat` to
    follow the active session's model, preferring cheap cloud models).
"""
import json
import os
import re
import time

from longrun.util import paths
from longrun.util.fswrite import safe_id

LONGRUN_AGENT_SESSION_ID = "longrunAgent"
LONGRUN_AGENT_TITLE = "longrunAgent · VEO"

# Prefer cheap remote cloud models by default; never a heavy local GGUF unless
# the operator explicitly selects one.
PREFERRED_CHEAP_MODELS = (
    "openrouter:deepseek/deepseek-v4.1-flash",
    "openrouter:deepseek/deepseek-v4-flash-0731",
    "openrouter:z-ai/glm-5.3-flash",
    "openrouter:meta/muse-spark-1.3-contributor",
    "deepseek:deepseek-flash",
    "deepseek:deepseek-v4-pro",
)

# Safety boundary: keys that longrunAgent is strictly forbidden from mutating.
FORBIDDEN_SAFETY_KEYS = frozenset({
    "allow_nucleus_write",
    "allow_matrix_promote",
    "approvals.allow_nucleus_write",
    "approvals.allow_matrix_promote",
})

# Semantic keyword map over teams._PALETTE so longrunAgent picks an icon+colour
# that matches the team's domain/meaning from the palette, falling back to
# teams.symbol_for_name(name) when no keyword matches.
_SEMANTIC_PALETTE_KEYWORDS = (
    # index 0: ("🚀", "#3B82F6") — launch, deploy, release, infra, devops, core, platform, velocity
    (0, ("launch", "deploy", "release", "infra", "devops", "ops", "core", "platform", "rocket", "ship", "prod", "build", "cloud")),
    # index 1: ("📣", "#F97316") — comms, marketing, outreach, social, pr, media, content, support, sales
    (1, ("comm", "market", "outreach", "social", "pr", "media", "content", "brand", "voice", "sales", "support", "growth", "news")),
    # index 2: ("🚨", "#EF4444") — security, redteam, incident, sre, guard, alert, audit, defense, triage
    (2, ("sec", "red", "incident", "sre", "guard", "alert", "audit", "defen", "triage", "risk", "vuln", "SOC", "fire")),
    # index 3: ("🧪", "#F59E0B") — qa, test, lab, research, benchmark, eval, experiment, science
    (3, ("qa", "test", "lab", "research", "bench", "eval", "experim", "scien", "verify", "quality", "probe")),
    # index 4: ("🧠", "#8B5CF6") — ai, ml, llm, agent, brain, planner, arch, data,rag, memory, knowledge
    (4, ("ai", "ml", "llm", "agent", "brain", "plan", "arch", "data", "rag", "mem", "know", "think", "reason", "model", "neural")),
    # index 5: ("💰", "#22C55E") — fin, cost, billing, quant, trade, rev, budget, econ, commerce
    (5, ("fin", "cost", "bill", "quant", "trad", "rev", "budget", "econ", "pay", "money", "bank", "invest")),
    # index 6: ("🗺️", "#14B8A6") — nav, map, discovery, search, web, scrape, explore, route, Product, design
    (6, ("map", "nav", "discov", "search", "web", "scrap", "explor", "rout", "product", "ux", "ui", "design", "front")),
    # index 7: ("🎮", "#A855F7") — game, sim, creative, studio, video, audio, mobile, android, app
    (7, ("game", "sim", "creat", "studio", "video", "audio", "mobile", "android", "app", "play", "3d", "render")),
)


def choose_team_symbol(name, description="", explicit_symbol=None, explicit_color=None):
    """Pick `(symbol, color)` from `teams._PALETTE` based on semantic meaning of `name`/`description`.

    An explicit symbol or colour always wins. Otherwise longrunAgent matches the
    team name/description against the semantic domain map over `_PALETTE`, and
    falls back to `teams.symbol_for_name(name)` so the choice is always from the
    official palette and deterministic.
    """
    from longrun.orchestrate import teams as teams_mod
    palette = teams_mod._PALETTE
    sym_default, col_default = teams_mod.symbol_for_name(name)
    text = ("%s %s" % (name or "", description or "")).lower()
    chosen_sym, chosen_col = sym_default, col_default
    best_hits = 0
    for idx, words in _SEMANTIC_PALETTE_KEYWORDS:
        if idx >= len(palette):
            continue
        hits = sum(1 for w in words if w.lower() in text)
        if hits > best_hits:
            best_hits = hits
            chosen_sym, chosen_col = palette[idx]
    final_sym = str(explicit_symbol).strip()[:8] if explicit_symbol else chosen_sym
    final_col = str(explicit_color).strip()[:16] if explicit_color else chosen_col
    return final_sym, final_col


# ------------------------------------------------------------------ schemas ---

TOOL_SCHEMAS = {
    "agent.create": {
        "description": (
            "agent.create — Provision a new org agent record (and its underlying "
            "session + dedicated workspace directory under ~/.longrun/workspaces), optionally setting its "
            "functional role, cheap remote LLM model, system prompt (ROLE.md), manager (`reports_to`), "
            "and team membership in one atomic substrate operation."
        ),
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "Unique human-readable agent name (e.g. 'Backend Lead')."},
            "role": {"type": "string", "description": "Short functional role label (e.g. 'backend-architect')."},
            "prompt": {"type": "string", "description": "System prompt / ROLE.md instructions for this agent."},
            "model": {"type": "string", "description": "Optional <provider>:<model> ref (defaults to a cheap remote model)."},
            "reports_to": {"type": "string", "description": "Optional manager agent ID (e.g. 'A1') or session ID."},
            "team": {"type": "string", "description": "Optional team ID ('T1') or team name to assign the agent into."},
            "workspace": {"type": "string", "description": "Optional workspace folder path (auto-created under workspaces/ if omitted)."},
            "daily_budget": {"type": "integer", "description": "Optional daily run cap (0 = unlimited)."},
        },
        "required": ["name"],
        "_origin": "exclusive",
        "_namespace": "agent",
        "_subtool": "create",
    },
    "agent.update": {
        "description": (
            "agent.update — Update the editable properties of an existing org agent "
            "in ONE call: display name, functional role, manager (`reports_to`), LLM model, workspace "
            "folder and daily budget. Only the properties you pass are touched, so this one tool replaces "
            "the old per-property setters. `model:'auto'` re-picks a cheap remote cloud model."
        ),
        "type": "object",
        "properties": {
            "agent": {"type": "string", "description": "Target agent ID ('A3'), session ID, or agent name."},
            "name": {"type": "string", "description": "New display name."},
            "role": {"type": "string", "description": "Functional role title (e.g. 'qa-engineer', 'researcher')."},
            "reports_to": {"type": "string", "description": "Manager agent ID ('A1'), or '' to make the agent a root."},
            "model": {"type": "string", "description": "Model ref (`<provider>:<model>`), or 'auto' for the cheap remote default."},
            "workspace": {"type": "string", "description": "Workspace folder path (created if missing)."},
            "daily_budget": {"type": "integer", "description": "Daily run cap (0 = unlimited)."},
        },
        "required": ["agent"],
        "_origin": "exclusive",
        "_namespace": "agent",
        "_subtool": "update",
    },
    "agent.get": {
        "description": (
            "agent.get — Read ONE agent's full record (id, session, name, role, model, "
            "manager, teams, budget) plus its ROLE.md size. Ground truth before any update or delete."
        ),
        "type": "object",
        "properties": {
            "agent": {"type": "string", "description": "Agent ID ('A3'), session ID, or agent name."},
        },
        "required": ["agent"],
        "_origin": "exclusive",
        "_namespace": "agent",
        "_subtool": "get",
    },
    "agent.list": {
        "description": (
            "agent.list — List every designated agent with its role, model, manager "
            "and team memberships, as an org tree."
        ),
        "type": "object",
        "properties": {},
        "required": [],
        "_origin": "exclusive",
        "_namespace": "agent",
        "_subtool": "list",
    },
    "agent.delete": {
        "description": (
            "agent.delete — Remove an agent COMPLETELY: un-designate it (its direct "
            "reports are re-parented to nobody), scrub it from jobs and teams, delete its routines, and by "
            "default also delete its session (with graph/run artifacts and its knowledge notebook) and its "
            "workspace folder. Session and workspace are only removed when they are safe to remove."
        ),
        "type": "object",
        "properties": {
            "agent": {"type": "string", "description": "Agent ID ('A3'), session ID, or agent name."},
            "session": {"type": "boolean", "description": "Delete the underlying session too (default true)."},
            "workspace": {"type": "boolean", "description": "Delete the dedicated workspace folder too (default true; only folders under the workspaces root are removed)."},
        },
        "required": ["agent"],
        "_origin": "exclusive",
        "_namespace": "agent",
        "_subtool": "delete",
    },
    "agent.prompt_set": {
        "description": (
            "agent.prompt_set — Write an agent's system prompt (`ROLE.md`) in the "
            "substrate and broadcast `roles.update` so the WebUI and Orbit table refresh immediately."
        ),
        "type": "object",
        "properties": {
            "agent": {"type": "string", "description": "Target agent ID ('A3'), session ID, or agent name."},
            "prompt": {"type": "string", "description": "Full ROLE.md system prompt text for the agent."},
        },
        "required": ["agent", "prompt"],
        "_origin": "exclusive",
        "_namespace": "agent",
        "_subtool": "prompt_set",
    },
    "agent.prompt_get": {
        "description": (
            "agent.prompt_get — Read an agent's system prompt (`ROLE.md`) together "
            "with its path and size, so an edit is never blind."
        ),
        "type": "object",
        "properties": {
            "agent": {"type": "string", "description": "Target agent ID ('A3'), session ID, or agent name."},
        },
        "required": ["agent"],
        "_origin": "exclusive",
        "_namespace": "agent",
        "_subtool": "prompt_get",
    },
    "agent.prompt_clear": {
        "description": (
            "agent.prompt_clear — Delete an agent's `ROLE.md` system prompt, so the "
            "agent falls back to the harness defaults. Broadcasts `roles.update`."
        ),
        "type": "object",
        "properties": {
            "agent": {"type": "string", "description": "Target agent ID ('A3'), session ID, or agent name."},
        },
        "required": ["agent"],
        "_origin": "exclusive",
        "_namespace": "agent",
        "_subtool": "prompt_clear",
    },
    "team.create": {
        "description": (
            "team.create — Spin up a new team (`TN`) with a semantic icon and colour "
            "selected by longrunAgent from the official palette based on the team name/purpose, plus a dedicated "
            "team workspace directory, and optionally provision or assign member agents in one call."
        ),
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "Team name (e.g. 'Security Red Team', 'Frontend Platform')."},
            "description": {"type": "string", "description": "Optional team mission / description."},
            "symbol": {"type": "string", "description": "Optional explicit emoji/symbol override from palette."},
            "color": {"type": "string", "description": "Optional explicit hex colour override."},
            "members": {
                "type": "array",
                "description": "Optional list of existing agent IDs/names OR new agent spec dicts ({name, role, prompt, model, reports_to}) to provision and assign.",
            },
        },
        "required": ["name"],
        "_origin": "exclusive",
        "_namespace": "team",
        "_subtool": "create",
    },
    "team.update": {
        "description": (
            "team.update — Edit a team's own properties: name, description, symbol, "
            "colour, and (with `regenerate_icon`) re-ask longrunAgent for the palette icon that matches the "
            "current name + description. Members are NOT touched here."
        ),
        "type": "object",
        "properties": {
            "team": {"type": "string", "description": "Team ID ('T1') or team name."},
            "name": {"type": "string", "description": "New team name."},
            "description": {"type": "string", "description": "New team mission / description."},
            "symbol": {"type": "string", "description": "Explicit symbol from the palette."},
            "color": {"type": "string", "description": "Explicit hex colour."},
            "regenerate_icon": {"type": "boolean", "description": "Ask longrunAgent to pick the symbol+colour that matches the name and description."},
        },
        "required": ["team"],
        "_origin": "exclusive",
        "_namespace": "team",
        "_subtool": "update",
    },
    "team.delete": {
        "description": (
            "team.delete — Delete a team. Member agents are NOT deleted: they only "
            "lose the team link. This cannot be undone."
        ),
        "type": "object",
        "properties": {
            "team": {"type": "string", "description": "Team ID ('T1') or team name."},
        },
        "required": ["team"],
        "_origin": "exclusive",
        "_namespace": "team",
        "_subtool": "delete",
    },
    "team.get": {
        "description": (
            "team.get — Read ONE team's record (id, name, description, symbol, colour, "
            "members) plus the official palette."
        ),
        "type": "object",
        "properties": {
            "team": {"type": "string", "description": "Team ID ('T1') or team name."},
        },
        "required": ["team"],
        "_origin": "exclusive",
        "_namespace": "team",
        "_subtool": "get",
    },
    "team.list": {
        "description": (
            "team.list — List every team with its members, plus the official icon palette."
        ),
        "type": "object",
        "properties": {},
        "required": [],
        "_origin": "exclusive",
        "_namespace": "team",
        "_subtool": "list",
    },
    "team.member_add": {
        "description": (
            "team.member_add — Put an existing agent into a team and sync the Orbit "
            "constellation."
        ),
        "type": "object",
        "properties": {
            "team": {"type": "string", "description": "Team ID ('T1') or team name."},
            "agent": {"type": "string", "description": "Agent ID ('A3'), session ID, or agent name."},
        },
        "required": ["team", "agent"],
        "_origin": "exclusive",
        "_namespace": "team",
        "_subtool": "member_add",
    },
    "team.member_remove": {
        "description": (
            "team.member_remove — Take an agent out of a team (the agent itself is "
            "untouched) and sync the Orbit constellation."
        ),
        "type": "object",
        "properties": {
            "team": {"type": "string", "description": "Team ID ('T1') or team name."},
            "agent": {"type": "string", "description": "Agent ID ('A3'), session ID, or agent name."},
        },
        "required": ["team", "agent"],
        "_origin": "exclusive",
        "_namespace": "team",
        "_subtool": "member_remove",
    },
    "job.create": {
        "description": (
            "job.create — Create a job: a goal assigned to a coordinator agent and "
            "optional workers, with optional dependencies. It is created NOT dispatched; use "
            "`job.dispatch` to run it."
        ),
        "type": "object",
        "properties": {
            "goal": {"type": "string", "description": "The job goal, in plain language."},
            "coordinator": {"type": "string", "description": "Coordinator agent ID/name (optional)."},
            "agents": {"type": "array", "description": "Worker agent IDs/names (optional)."},
            "deps": {"type": "array", "description": "Optional dependency list."},
            "mode": {"type": "string", "description": "'coordinator' (default) or 'swarm'."},
            "blocked_by": {"type": "array", "description": "Optional list of job IDs that must finish first."},
        },
        "required": ["goal"],
        "_origin": "exclusive",
        "_namespace": "job",
        "_subtool": "create",
    },
    "job.dispatch": {
        "description": (
            "job.dispatch — Run an existing job (coordinator + workers in dependency "
            "waves). This spends real model calls."
        ),
        "type": "object",
        "properties": {
            "job": {"type": "string", "description": "Job ID ('J2')."},
        },
        "required": ["job"],
        "_origin": "exclusive",
        "_namespace": "job",
        "_subtool": "dispatch",
    },
    "job.get": {
        "description": (
            "job.get — Read ONE job in full: workers, subjobs, their todos and state."
        ),
        "type": "object",
        "properties": {
            "job": {"type": "string", "description": "Job ID ('J2')."},
        },
        "required": ["job"],
        "_origin": "exclusive",
        "_namespace": "job",
        "_subtool": "get",
    },
    "job.list": {
        "description": "job.list — List every job with its state, coordinator and workers.",
        "type": "object",
        "properties": {},
        "required": [],
        "_origin": "exclusive",
        "_namespace": "job",
        "_subtool": "list",
    },
    "job.delete": {
        "description": (
            "job.delete — Delete a job. Refused while the job is still running."
        ),
        "type": "object",
        "properties": {
            "job": {"type": "string", "description": "Job ID ('J2')."},
        },
        "required": ["job"],
        "_origin": "exclusive",
        "_namespace": "job",
        "_subtool": "delete",
    },
    "routine.create": {
        "description": (
            "routine.create — Schedule a recurring goal for one agent (a heartbeat "
            "routine). `every_seconds` is the cadence."
        ),
        "type": "object",
        "properties": {
            "agent": {"type": "string", "description": "Agent ID ('A3'), session ID, or agent name the routine runs as."},
            "goal": {"type": "string", "description": "The goal the agent re-runs on every tick."},
            "every_seconds": {"type": "integer", "description": "Cadence in seconds (minimum 30)."},
            "enabled": {"type": "boolean", "description": "Start enabled (default true)."},
            "disabled": {"type": "boolean", "description": "Start disabled — the reverse spelling of `enabled`. Pass ONE of the two."},
            "model": {"type": "string", "description": "Optional model override for the tick."},
        },
        "required": ["agent", "goal", "every_seconds"],
        "_origin": "exclusive",
        "_namespace": "routine",
        "_subtool": "create",
    },
    "routine.update": {
        "description": (
            "routine.update — Edit a routine in place: re-target the agent, rewrite the "
            "goal, change the cadence or flip the switch. Only the fields you pass are touched."
        ),
        "type": "object",
        "properties": {
            "routine": {"type": "string", "description": "Routine ID ('R1')."},
            "agent": {"type": "string", "description": "New agent ID/name for the routine."},
            "goal": {"type": "string", "description": "New goal text."},
            "every_seconds": {"type": "integer", "description": "New cadence in seconds."},
            "enabled": {"type": "boolean", "description": "Enable or disable the routine."},
            "disabled": {"type": "boolean", "description": "Disable/enable — the reverse spelling of `enabled`. Pass ONE of the two."},
            "model": {"type": "string", "description": "New model override."},
        },
        "required": ["routine"],
        "_origin": "exclusive",
        "_namespace": "routine",
        "_subtool": "update",
    },
    "routine.get": {
        "description": "routine.get — Read ONE routine (agent, goal, cadence, runs, last_run).",
        "type": "object",
        "properties": {
            "routine": {"type": "string", "description": "Routine ID ('R1')."},
        },
        "required": ["routine"],
        "_origin": "exclusive",
        "_namespace": "routine",
        "_subtool": "get",
    },
    "routine.list": {
        "description": "routine.list — List every routine with its agent, cadence and last run.",
        "type": "object",
        "properties": {},
        "required": [],
        "_origin": "exclusive",
        "_namespace": "routine",
        "_subtool": "list",
    },
    "routine.delete": {
        "description": "routine.delete — Remove a routine (it stops being scheduled).",
        "type": "object",
        "properties": {
            "routine": {"type": "string", "description": "Routine ID ('R1')."},
        },
        "required": ["routine"],
        "_origin": "exclusive",
        "_namespace": "routine",
        "_subtool": "delete",
    },
    "session.create": {
        "description": (
            "session.create — Open a new bare session (optionally with its own workspace "
            "folder). Sessions are the substrate under every agent, job and routine."
        ),
        "type": "object",
        "properties": {
            "title": {"type": "string", "description": "Optional session title."},
            "workspace": {"type": "string", "description": "Optional workspace folder path for the session."},
        },
        "required": [],
        "_origin": "exclusive",
        "_namespace": "session",
        "_subtool": "create",
    },
    "session.rename": {
        "description": "session.rename — Rename a session.",
        "type": "object",
        "properties": {
            "session": {"type": "string", "description": "Session ID."},
            "title": {"type": "string", "description": "New title."},
        },
        "required": ["session", "title"],
        "_origin": "exclusive",
        "_namespace": "session",
        "_subtool": "rename",
    },
    "session.list": {
        "description": "session.list — List every session (id, title, workspace, model).",
        "type": "object",
        "properties": {},
        "required": [],
        "_origin": "exclusive",
        "_namespace": "session",
        "_subtool": "list",
    },
    "session.delete": {
        "description": (
            "session.delete — Delete a session with its full cascade: running turn "
            "aborted, graph, run metrics, edit journal and its knowledge notebook removed. The permanent "
            "`longrunAgent` session itself can never be deleted."
        ),
        "type": "object",
        "properties": {
            "session": {"type": "string", "description": "Session ID."},
        },
        "required": ["session"],
        "_origin": "exclusive",
        "_namespace": "session",
        "_subtool": "delete",
    },
    "webui.inspect": {
        "description": (
            "webui.inspect — Read the current live substrate state of ANY WebUI "
            "section (`agents`, `teams`, `models`, `subagents`, `providers`, `settings`, `rules`, "
            "`compaction`, `tools`, `skills`, `mcp`, `knowledge`, `index`, `keys`) so longrunAgent "
            "has exact ground truth before applying an automation update."
        ),
        "type": "object",
        "properties": {
            "section": {
                "type": "string",
                "enum": ["agents", "teams", "models", "subagents", "providers", "settings",
                         "rules", "compaction", "tools", "skills", "mcp", "knowledge",
                         "index", "keys", "all"],
                "description": "WebUI section to inspect.",
            },
            "session": {"type": "string", "description": "Optional session ID for session-scoped sections (e.g. rules)."},
        },
        "required": ["section"],
        "_origin": "exclusive",
        "_namespace": "webui",
        "_subtool": "inspect",
    },
    "webui.configure": {
        "description": (
            "webui.configure — Write a CONFIGURATION SECTION of the substrate: the "
            "structured settings forms, the rules files, the compaction policy, the role routing "
            "table, the team model policy, the subagent policy, the tool policy, the code index "
            "config and raw `config/*.yaml`. Emits live-sync SSE events. Object CRUD (providers, "
            "models, skills, MCP clients, knowledge notebooks/sources) has its OWN typed tools. "
            "Strictly refuses the safety-gate keys (`allow_nucleus_write`, `allow_matrix_promote`)."
        ),
        "type": "object",
        "properties": {
            "target": {
                "type": "string",
                "enum": ["settings", "rules", "compaction", "routing", "team_policy",
                         "subagents", "tools", "index", "config"],
                "description": "Substrate configuration section to update.",
            },
            "file": {"type": "string", "description": "For target='settings'/'config': config filename (e.g. 'index.yaml', 'compaction.yaml')."},
            "values": {"type": "object", "description": "Key-value map of the fields to update (settings / routing / compaction / subagents / tools / index)."},
            "scope": {"type": "string", "description": "For target='rules': 'global' or 'project'."},
            "content": {"type": "string", "description": "For target='rules': full markdown content to save."},
            "team": {"type": "string", "description": "For target='team_policy': team ID ('T1') or 'ALL'."},
            "text": {"type": "string", "description": "For target='config': the full YAML body to persist."},
        },
        "required": ["target"],
        "_origin": "exclusive",
        "_namespace": "webui",
        "_subtool": "configure",
    },
    "provider.upsert": {
        "description": (
            "provider.upsert — Add or update ONE provider (its `id`, base URL, "
            "model list). Reference API keys by environment NAME (`${VAR}`), never by value."
        ),
        "type": "object",
        "properties": {
            "id": {"type": "string", "description": "Provider id (e.g. 'openrouter')."},
            "values": {"type": "object", "description": "Provider fields to upsert (id, base_url, keys, models…)."},
        },
        "required": ["id"],
        "_origin": "exclusive",
        "_namespace": "provider",
        "_subtool": "upsert",
    },
    "provider.remove": {
        "description": "provider.remove — Remove (or disable) one provider by id.",
        "type": "object",
        "properties": {
            "id": {"type": "string", "description": "Provider id to remove."},
        },
        "required": ["id"],
        "_origin": "exclusive",
        "_namespace": "provider",
        "_subtool": "remove",
    },
    "provider.add_model": {
        "description": "provider.add_model — Add ONE `<provider>:<model>` to a provider's roster.",
        "type": "object",
        "properties": {
            "provider": {"type": "string", "description": "Provider id."},
            "model": {"type": "string", "description": "Model id to add."},
        },
        "required": ["provider", "model"],
        "_origin": "exclusive",
        "_namespace": "provider",
        "_subtool": "add_model",
    },
    "provider.remove_model": {
        "description": "provider.remove_model — Remove ONE model from a provider's roster.",
        "type": "object",
        "properties": {
            "provider": {"type": "string", "description": "Provider id."},
            "model": {"type": "string", "description": "Model id to remove."},
        },
        "required": ["provider", "model"],
        "_origin": "exclusive",
        "_namespace": "provider",
        "_subtool": "remove_model",
    },
    "provider.set_default": {
        "description": "provider.set_default — Set the harness default model reference.",
        "type": "object",
        "properties": {
            "ref": {"type": "string", "description": "Model reference, e.g. 'openrouter:z-ai/glm-5.3-flash'."},
        },
        "required": ["ref"],
        "_origin": "exclusive",
        "_namespace": "provider",
        "_subtool": "set_default",
    },
    "provider.reload": {
        "description": "provider.reload — Re-read the provider catalogue and `.env` (hot reload).",
        "type": "object",
        "properties": {},
        "required": [],
        "_origin": "exclusive",
        "_namespace": "provider",
        "_subtool": "reload",
    },
    "skill.remove": {
        "description": (
            "skill.remove — Uninstall one local skill by name. Installing a new "
            "skill needs a zip upload and stays manual."
        ),
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "Skill name to uninstall."},
        },
        "required": ["name"],
        "_origin": "exclusive",
        "_namespace": "skill",
        "_subtool": "remove",
    },
    "mcp.upsert": {
        "description": (
            "mcp.upsert — Add or update ONE external MCP client (transport, "
            "command/url). Reference secrets by NAME, never by value."
        ),
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "MCP client name."},
            "values": {"type": "object", "description": "Client spec (command, args, url, headers, env…)."},
        },
        "required": ["name", "values"],
        "_origin": "exclusive",
        "_namespace": "mcp",
        "_subtool": "upsert",
    },
    "mcp.remove": {
        "description": "mcp.remove — Remove ONE external MCP client by name.",
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "MCP client name."},
        },
        "required": ["name"],
        "_origin": "exclusive",
        "_namespace": "mcp",
        "_subtool": "remove",
    },
    "mcp.test": {
        "description": "mcp.test — Probe ONE configured MCP client and report whether it answers.",
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "MCP client name to test."},
        },
        "required": ["name"],
        "_origin": "exclusive",
        "_namespace": "mcp",
        "_subtool": "test",
    },
    "mcp.reload": {
        "description": "mcp.reload — Re-read the MCP client configuration and reconnect.",
        "type": "object",
        "properties": {},
        "required": [],
        "_origin": "exclusive",
        "_namespace": "mcp",
        "_subtool": "reload",
    },
    "kb.notebook_add": {
        "description": "kb.notebook_add — Create ONE knowledge notebook.",
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "Notebook name."},
        },
        "required": ["name"],
        "_origin": "exclusive",
        "_namespace": "kb",
        "_subtool": "notebook_add",
    },
    "kb.notebook_rename": {
        "description": "kb.notebook_rename — Rename ONE knowledge notebook.",
        "type": "object",
        "properties": {
            "id": {"type": "string", "description": "Notebook id."},
            "name": {"type": "string", "description": "New notebook name."},
        },
        "required": ["id", "name"],
        "_origin": "exclusive",
        "_namespace": "kb",
        "_subtool": "notebook_rename",
    },
    "kb.notebook_delete": {
        "description": (
            "kb.notebook_delete — Delete ONE knowledge notebook and its "
            "sources. This cannot be undone."
        ),
        "type": "object",
        "properties": {
            "id": {"type": "string", "description": "Notebook id."},
        },
        "required": ["id"],
        "_origin": "exclusive",
        "_namespace": "kb",
        "_subtool": "notebook_delete",
    },
    "kb.source_add": {
        "description": (
            "kb.source_add — Attach ONE source (file path / URL / inline "
            "text) to a knowledge notebook and index it."
        ),
        "type": "object",
        "properties": {
            "notebook": {"type": "string", "description": "Notebook id or name."},
            "title": {"type": "string", "description": "Source title (for inline text)."},
            "ref": {"type": "string", "description": "File path or URL to index."},
            "content": {"type": "string", "description": "Inline text to add as a source instead of a path."},
        },
        "required": ["notebook"],
        "_origin": "exclusive",
        "_namespace": "kb",
        "_subtool": "source_add",
    },
    "kb.source_remove": {
        "description": "kb.source_remove — Detach ONE source from the knowledge base.",
        "type": "object",
        "properties": {
            "source": {"type": "string", "description": "Source id/ref to remove."},
        },
        "required": ["source"],
        "_origin": "exclusive",
        "_namespace": "kb",
        "_subtool": "source_remove",
    },
    "kb.reembed": {
        "description": "kb.reembed — Re-embed the whole knowledge base (spends compute).",
        "type": "object",
        "properties": {},
        "required": [],
        "_origin": "exclusive",
        "_namespace": "kb",
        "_subtool": "reembed",
    },
}

# The dual-permission gate and the SAFETY_GUARD both key off this set: every
# exclusive tool lives in one of these namespaces, so protecting the namespace
# protects the whole surface even when a caller sends a bare namespace key.
EXCLUSIVE_NAMESPACES = frozenset(k.split(".", 1)[0] for k in TOOL_SCHEMAS)


def is_exclusive_name(name):
    """True when `name` is an exclusive tool or one of its namespaces."""
    return str(name or "").split(".", 1)[0] in EXCLUSIVE_NAMESPACES


# --------------------------------------------------- session & access gate ---

def is_system_session(sid):
    """True when `sid` is the permanent undeletable `longrunAgent` session."""
    return str(sid or "").strip() == LONGRUN_AGENT_SESSION_ID


def ensure_system_session():
    """Ensure the permanent `longrunAgent` session exists on disk and is never tombstoned."""
    from longrun.memory import stores
    with stores._deleted_lock:
        if LONGRUN_AGENT_SESSION_ID in stores._DELETED_SESSIONS:
            stores._DELETED_SESSIONS.discard(LONGRUN_AGENT_SESSION_ID)
            stores._persist_tombstones()
    sess = stores.load_session(LONGRUN_AGENT_SESSION_ID)
    changed = False
    if not isinstance(sess, dict):
        ws = os.path.join(paths.WORKSPACES_DIR, LONGRUN_AGENT_SESSION_ID)
        try:
            os.makedirs(ws, exist_ok=True)
        except OSError:
            ws = paths.REPO_ROOT
        sess = {
            "id": LONGRUN_AGENT_SESSION_ID,
            "title": LONGRUN_AGENT_TITLE,
            "created": round(time.time(), 3),
            "workspace": ws,
            "system": True,
            "undeletable": True,
            "stateless": True,
            "allow_longrun_agent": True,
            "messages": [],
            "tool_cards": [],
            "injects": [],
        }
        stores.ensure_job(sess)
        changed = True
    else:
        for k, v in (("system", True), ("undeletable", True),
                     ("stateless", True), ("allow_longrun_agent", True)):
            if sess.get(k) is not v:
                sess[k] = v
                changed = True
        if not sess.get("title"):
            sess["title"] = LONGRUN_AGENT_TITLE
            changed = True
    if changed:
        stores.save_session(sess)
    return sess


def reset_stateless_session():
    """Wipe `longrunAgent` messages, tool cards, injects, and taskgraph before/after a run."""
    from longrun.memory import stores
    from longrun.memory import threads as threads_mod
    from longrun.plan import taskgraph
    sess = ensure_system_session()
    sess["messages"] = []
    sess["tool_cards"] = []
    sess["injects"] = []
    stores.save_session(sess)
    try:
        taskgraph.reset(LONGRUN_AGENT_SESSION_ID)
    except Exception:  # noqa: BLE001
        pass
    try:
        threads_mod.clear(LONGRUN_AGENT_SESSION_ID)
    except Exception:  # noqa: BLE001
        pass
    return sess


def session_has_access(sid):
    """True when `sid` is permitted to invoke the exclusive (`namespace.tool`) tools.

    Dual-permission model:
      1) `longrunAgent` itself (or a stateless `longrunAgent` run id
         `longrunAgent*`) always has session privilege;
      2) any other session must have `allow_longrun_agent: True` on its session record.
    """
    sid = str(sid or "").strip()
    if not sid:
        return False
    if sid == LONGRUN_AGENT_SESSION_ID or sid.startswith(LONGRUN_AGENT_SESSION_ID + "_"):
        return True
    from longrun.memory import stores
    sess = stores.load_session(sid)
    return bool(isinstance(sess, dict) and sess.get("allow_longrun_agent") is True)


def set_session_access(sid, allowed):
    """Grant or revoke `allow_longrun_agent` privilege on a session."""
    from longrun.memory import stores
    from longrun.core.events import publish
    sid = str(sid or "").strip()
    if not sid:
        return {"ok": False, "error": "session required"}
    if sid == LONGRUN_AGENT_SESSION_ID and not allowed:
        return {"ok": False, "error": "cannot revoke longrunAgent access from the system session itself"}
    sess = stores.load_session(sid)
    if not sess:
        return {"ok": False, "error": "session not found: %s" % sid}
    sess["allow_longrun_agent"] = bool(allowed)
    stores.save_session(sess)
    publish("session.updated", session=sid, allow_longrun_agent=bool(allowed))
    return {"ok": True, "session": sid, "allow_longrun_agent": bool(allowed)}


def check_dual_permission(tool, run_id=None):
    """Verify BOTH global tool enablement AND session privilege for an exclusive tool.

    Returns `(ok, reason)`.
    """
    from longrun.tools import registry
    spec = registry.tool_spec(tool)
    if spec is None:
        return False, "unknown tool %r" % tool
    if not spec.get("enabled"):
        return False, "tool %r is disabled in the global Tool panel (enable longrunAgent tools first)" % tool
    if not session_has_access(run_id):
        return False, (
            "session %r is not authorized to use %r — dual-permission gate requires "
            "either the permanent 'longrunAgent' system session or explicit session "
            "grant (`allow_longrun_agent: true`). approvals.mode=full does NOT "
            "bypass this gate. Operator: grant via POST /api/longrun-agent/access "
            "{\"session\": \"<sid>\", \"allow_longrun_agent\": true} or the session "
            "menu Teamorg grant; agent: use `dispatch` (teammate turn, no grant) "
            "instead of `job.*`, never shell/curl around the gate"
            % (run_id or "anonymous", tool)
        )
    return True, "authorized (dual-permission: tool enabled + session privileged)"


# -------------------------------------------------------- model resolution ---

def pick_cheap_remote_model():
    """Pick the best available cheap remote cloud model (never a local GGUF)."""
    try:
        from longrun.model import routing
        from longrun.orchestrate import teams as teams_mod
        cfg = routing.load_config() or {}
        roles = cfg.get("roles") or {}
        # Check team_lead / subagent / summarizer roles first if they point to cloud
        for rname in ("longrun_agent", "team_lead", "subagent", "summarizer", "team_member"):
            m = (roles.get(rname) or {}).get("model") or ""
            if m and not routing.is_dynamic_ref(m) and teams_mod.machine_of(m) is None:
                return m
    except Exception:  # noqa: BLE001
        pass
    try:
        from longrun.model import providers
        cat = providers.providers() or []
        avail_refs = set()
        cloud_refs = []
        for p in cat:
            if p.get("local"):
                continue
            for m in (p.get("models") or []):
                ref = m.get("ref") or ("%s:%s" % (p.get("id"), m.get("id")))
                cloud_refs.append(ref)
                if p.get("available") is not False:
                    avail_refs.add(ref)
        for pref in PREFERRED_CHEAP_MODELS:
            if pref in avail_refs:
                return pref
        for pref in PREFERRED_CHEAP_MODELS:
            if pref in cloud_refs:
                return pref
        if avail_refs:
            return sorted(avail_refs)[0]
    except Exception:  # noqa: BLE001
        pass
    return PREFERRED_CHEAP_MODELS[0]


def resolve_automation_model(active_session_id=None, explicit_model=None):
    """Resolve the model `longrunAgent` uses for an automation run.

    Precedence:
      1. `explicit_model` (if non-empty and not `@chat`);
      2. `roles.longrun_agent.model` in `config/routing.yaml`;
      3. when `@chat` (or dynamic), the active session's model (if cloud) or
         the harness chat model;
      4. `pick_cheap_remote_model()`.
    """
    from longrun.model import routing
    from longrun.memory import stores
    ref = str(explicit_model or "").strip()
    if not ref:
        cfg = routing.load_config() or {}
        ref = str(((cfg.get("roles") or {}).get("longrun_agent") or {}).get("model") or "").strip()
    if not ref or routing.is_dynamic_ref(ref):
        if active_session_id:
            sess = stores.load_session(active_session_id)
            if sess and sess.get("model") and not routing.is_dynamic_ref(sess.get("model")):
                return sess["model"]
        return pick_cheap_remote_model()
    return ref


# --------------------------------------------------------- helper resolvers ---

def _resolve_agent_session(ref):
    """Resolve an agent ID (`A3`), session ID, or agent name to `(session_id, agent_dict_or_None)`."""
    from longrun.agent import agents as agents_mod
    from longrun.memory import stores
    raw = str(ref or "").strip()
    if not raw:
        return None, None
    a = agents_mod.REGISTRY.get(raw)
    if a:
        return a.get("session"), a
    # Search by agent ID ('A2', case-insensitive) or agent name (case-insensitive)
    low = raw.lower()
    for item in agents_mod.REGISTRY.list().get("agents", []):
        if str(item.get("id") or "").strip().lower() == low:
            return item.get("session"), item
        if str(item.get("name") or "").strip().lower() == low:
            return item.get("session"), item
    # Check if raw is an existing session id or title
    s = stores.load_session(raw)
    if s:
        return s["id"], agents_mod.REGISTRY.get(s["id"])
    for srow in stores.list_sessions():
        if str(srow.get("title") or "").strip().lower() == low:
            sid = srow["id"]
            return sid, agents_mod.REGISTRY.get(sid)
    return None, None


def _ensure_agent_workspace(name, explicit_ws=None):
    """Create or validate a dedicated workspace folder for an agent."""
    if explicit_ws:
        p = os.path.abspath(os.path.expanduser(str(explicit_ws).strip()))
    else:
        slug = safe_id(str(name or "agent").lower(), default="agent", max_len=48)
        p = os.path.join(paths.WORKSPACES_DIR, slug)
    try:
        os.makedirs(p, exist_ok=True)
    except OSError:
        p = paths.REPO_ROOT
    return p


# --------------------------------------------------------- subtool handlers ---

def _agent_create(args):
    from longrun.agent import agents as agents_mod
    from longrun.memory import stores
    from longrun.orchestrate import roles as roles_mod
    from longrun.orchestrate import teams as teams_mod

    name = str(args.get("name") or "").strip()[:80]
    if not name:
        return {"ok": False, "error": "name required"}
    # If an agent with this name already exists, update it idempotently
    existing_sid, existing_ag = _resolve_agent_session(name)
    ws = _ensure_agent_workspace(name, args.get("workspace"))
    model = str(args.get("model") or "").strip()
    if not model or model.lower() == "auto":
        model = pick_cheap_remote_model()

    if existing_sid:
        sid = existing_sid
        sess = stores.load_session(sid) or stores.get_or_create_session(sid, name)
        if args.get("workspace"):
            sess["workspace"] = ws
            stores.save_session(sess)
    else:
        sess = stores.get_or_create_session(None, name)
        sid = sess["id"]
        sess["workspace"] = ws
        stores.save_session(sess)

    role = str(args.get("role") or "").strip()[:80] or "specialist"
    reports_to = args.get("reports_to")
    if reports_to:
        _, mgr = _resolve_agent_session(reports_to)
        if mgr:
            reports_to = mgr.get("id")
    des = agents_mod.REGISTRY.designate(
        sid,
        name=name,
        role=role,
        model=model,
        workspace=ws,
        reports_to=reports_to,
        daily_budget=args.get("daily_budget"),
    )
    if not des.get("ok"):
        return des
    agent_rec = des["agent"]
    stores._set_session_model(sid, model)

    prompt = args.get("prompt")
    if prompt is not None and str(prompt).strip():
        roles_mod.write(sid, str(prompt))

    team_ref = str(args.get("team") or "").strip()
    team_assigned = None
    if team_ref:
        t = teams_mod.REGISTRY.get(team_ref)
        if not t:
            tc = teams_mod.REGISTRY.create(team_ref)
            t = tc.get("team") if tc.get("ok") else None
        if t:
            teams_mod.REGISTRY.add_member(t["id"], agent_rec["id"])
            team_assigned = t["id"]

    return {
        "ok": True,
        "agent": agent_rec,
        "session": sid,
        "workspace": ws,
        "model": model,
        "team": team_assigned,
        "prompt_set": bool(prompt and str(prompt).strip()),
        "stdout": "created/updated agent %s (%s) [role=%s, model=%s, workspace=%s%s]" % (
            agent_rec["id"], name, role, model, ws,
            (", team=%s" % team_assigned) if team_assigned else "",
        ),
    }


def _agent_update(args):
    """JAG-537: ONE update door for every editable property of an agent record.

    Replaces the per-property setters (`agents.setllm` / `agents.setrole`): only the
    properties the caller passes are touched, so `{agent, model}` behaves exactly as
    the old `setllm` did, while `{agent, role, reports_to}` covers the old `setrole`.
    """
    from longrun.agent import agents as agents_mod
    from longrun.memory import stores
    from longrun.orchestrate import teams as teams_mod

    sid, ag = _resolve_agent_session(args.get("agent"))
    if not sid:
        return {"ok": False, "error": "agent not found: %s" % args.get("agent")}
    if not ag:
        des = agents_mod.REGISTRY.designate(sid)
        if not des.get("ok"):
            return des
        ag = des["agent"]

    kw = {}
    if args.get("name") is not None:
        nm = str(args.get("name") or "").strip()[:80]
        if not nm:
            return {"ok": False, "error": "name cannot be empty"}
        kw["name"] = nm
    if args.get("role") is not None:
        role = str(args.get("role") or "").strip()[:80]
        if not role:
            return {"ok": False, "error": "role cannot be empty"}
        kw["role"] = role
    if "reports_to" in args and args.get("reports_to") is not None:
        rep = str(args.get("reports_to") or "").strip()
        if rep:
            _, mgr = _resolve_agent_session(rep)
            kw["reports_to"] = mgr["id"] if mgr else rep
        else:
            kw["reports_to"] = ""
    if args.get("workspace") is not None and str(args.get("workspace") or "").strip():
        kw["workspace"] = _ensure_agent_workspace(
            kw.get("name") or ag.get("name"), args.get("workspace"))
    if args.get("daily_budget") is not None:
        kw["daily_budget"] = args.get("daily_budget")

    model = str(args.get("model") or "").strip()
    if model:
        if model.lower() == "auto":
            model = pick_cheap_remote_model()
        conflict = teams_mod.REGISTRY.local_conflict(ag["id"], model)
        if conflict:
            return {
                "ok": False,
                "error": "local model conflict on %s in team %s (held by %s); prefer a cheap remote model"
                         % (conflict["machine"], conflict["team"], conflict["other"]),
                "conflict": conflict,
            }
        kw["model"] = model

    if not kw:
        return {
            "ok": False,
            "error": "nothing to update — pass at least one of "
                     "name/role/reports_to/model/workspace/daily_budget",
        }
    res = agents_mod.REGISTRY.designate(sid, **kw)
    if not res.get("ok"):
        return res
    if "model" in kw:
        try:
            stores._set_session_model(sid, kw["model"])
        except Exception:  # noqa: BLE001
            pass
    rec = res["agent"]
    return {
        "ok": True,
        "agent": rec,
        "session": sid,
        "changed": sorted(kw),
        "stdout": "updated agent %s (%s): %s" % (
            rec["id"], rec.get("name"),
            ", ".join("%s=%s" % (k, kw[k]) for k in sorted(kw)),
        ),
    }


def _agent_get(args):
    from longrun.orchestrate import roles as roles_mod

    sid, ag = _resolve_agent_session(args.get("agent"))
    if not sid:
        return {"ok": False, "error": "agent not found: %s" % args.get("agent")}
    try:
        text = roles_mod.read(sid) or ""
        path = roles_mod.path_for(sid)
    except Exception:  # noqa: BLE001
        text, path = "", ""
    return {
        "ok": True,
        "agent": ag,
        "session": sid,
        "designated": bool(ag),
        "prompt_path": path,
        "prompt_chars": len(text),
    }


def _agent_list(_args=None):
    from longrun.agent import agents as agents_mod

    tree = agents_mod.REGISTRY.tree()
    agents = tree.get("agents") if isinstance(tree, dict) else tree
    return {
        "ok": True,
        "agents": agents,
        "count": len(agents or []),
        "stdout": "%d designated agent(s)" % len(agents or []),
    }


def _remove_workspace_path(path):
    """Delete a workspace folder, but ONLY when it sits under the workspaces root.

    A workspace is user data: an explicit path outside `paths.WORKSPACES_DIR` (for
    example the repo itself) is never removed — the caller gets `skipped` instead.
    """
    import shutil

    try:
        target = os.path.realpath(os.path.abspath(os.path.expanduser(str(path))))
        root = os.path.realpath(paths.WORKSPACES_DIR)
    except Exception:  # noqa: BLE001
        return {"removed": False, "skipped": str(path), "error": "unresolvable path"}
    if target == root or not target.startswith(root + os.sep):
        return {"removed": False, "skipped": target,
                "reason": "outside the workspaces root (%s)" % root}
    if not os.path.isdir(target):
        return {"removed": False, "skipped": target, "reason": "not a directory"}
    try:
        shutil.rmtree(target)
    except OSError as exc:
        return {"removed": False, "skipped": target, "error": str(exc)}
    return {"removed": True, "path": target}


def _agent_delete(args):
    """JAG-537: remove an agent and everything that only exists for it.

    Full cascade (the operator's contract): un-designate + re-parent reports, scrub
    jobs/teams, drop its routines, delete its ROLE.md, and by default delete the
    session (its artifacts and knowledge notebook) and the workspace folder.
    """
    from longrun.agent import agents as agents_mod
    from longrun.orchestrate import roles as roles_mod

    sid, ag = _resolve_agent_session(args.get("agent"))
    if not sid:
        return {"ok": False, "error": "agent not found: %s" % args.get("agent")}
    if sid == LONGRUN_AGENT_SESSION_ID:
        return {"ok": False,
                "error": "longrunAgent is a permanent system session and cannot be deleted"}
    aid = (ag or {}).get("id")
    workspace = (ag or {}).get("workspace") or ""

    released = agents_mod.REGISTRY.release(sid) if ag else {"ok": True, "released": None}
    try:
        roles_mod.delete(sid)
        prompt_removed = True
    except Exception:  # noqa: BLE001
        prompt_removed = False

    session_deleted = None
    if args.get("session") is not False:
        from longrun.core import httpapi
        session_deleted = bool(httpapi.delete_session(sid).get("ok"))

    workspace_res = None
    if args.get("workspace") is not False and workspace:
        workspace_res = _remove_workspace_path(workspace)

    return {
        "ok": True,
        "agent": aid,
        "session": sid,
        "released": released.get("released"),
        "prompt_removed": prompt_removed,
        "session_deleted": session_deleted,
        "workspace": workspace_res,
        "stdout": "deleted agent %s (session deleted=%s, workspace=%s)" % (
            aid or sid, session_deleted,
            (workspace_res or {}).get("reason") or ("removed" if (workspace_res or {}).get("removed")
                                                    else "kept"),
        ),
    }


def _agent_prompt_set(args):
    from longrun.agent import agents as agents_mod
    from longrun.orchestrate import roles as roles_mod

    target = args.get("agent")
    sid, ag = _resolve_agent_session(target)
    if not sid:
        return {"ok": False, "error": "agent not found: %s" % target}
    if not ag:
        des = agents_mod.REGISTRY.designate(sid)
        if des.get("ok"):
            ag = des["agent"]
    prompt = str(args.get("prompt") or "")
    wres = roles_mod.write(sid, prompt)
    if not wres.get("ok"):
        return wres
    aid = (ag or {}).get("id") or sid
    return {
        "ok": True,
        "agent": aid,
        "session": sid,
        "path": wres.get("path"),
        "bytes": wres.get("bytes", 0),
        "stdout": "configured system prompt (ROLE.md, %d bytes) for %s" % (
            wres.get("bytes", 0), aid
        ),
    }


def _agent_prompt_get(args):
    from longrun.orchestrate import roles as roles_mod

    sid, ag = _resolve_agent_session(args.get("agent"))
    if not sid:
        return {"ok": False, "error": "agent not found: %s" % args.get("agent")}
    text = ""
    try:
        text = roles_mod.read(sid) or ""
    except Exception:  # noqa: BLE001
        text = ""
    return {
        "ok": True,
        "agent": (ag or {}).get("id") or sid,
        "session": sid,
        "path": roles_mod.path_for(sid),
        "chars": len(text),
        "prompt": text,
    }


def _agent_prompt_clear(args):
    from longrun.orchestrate import roles as roles_mod

    sid, ag = _resolve_agent_session(args.get("agent"))
    if not sid:
        return {"ok": False, "error": "agent not found: %s" % args.get("agent")}
    res = roles_mod.delete(sid)
    res.setdefault("ok", True)
    res["agent"] = (ag or {}).get("id") or sid
    res["session"] = sid
    res["stdout"] = "removed ROLE.md for %s" % res["agent"]
    return res


def _team_get(args):
    from longrun.orchestrate import teams as teams_mod

    t = teams_mod.REGISTRY.get(args.get("team"))
    if not t:
        return {"ok": False, "error": "team not found: %s" % args.get("team")}
    return {"ok": True, "team": t, "palette": teams_mod.palette()}


def _team_list(_args=None):
    from longrun.orchestrate import teams as teams_mod

    out = teams_mod.REGISTRY.list()
    out["ok"] = True
    out["palette"] = teams_mod.palette()
    out["stdout"] = "%d team(s)" % len(out.get("teams") or [])
    return out


def _team_update(args):
    from longrun.orchestrate import teams as teams_mod

    t = teams_mod.REGISTRY.get(args.get("team"))
    if not t:
        return {"ok": False, "error": "team not found: %s" % args.get("team")}
    kw = {}
    if args.get("name") is not None:
        nm = str(args.get("name") or "").strip()[:80]
        if not nm:
            return {"ok": False, "error": "name cannot be empty"}
        kw["name"] = nm
    for key in ("description", "symbol", "color"):
        if args.get(key) is not None:
            kw[key] = str(args.get(key) or "").strip()
    regen = bool(args.get("regenerate_icon"))
    if not kw and not regen:
        return {"ok": False,
                "error": "nothing to update — pass name/description/symbol/color/regenerate_icon"}
    res = teams_mod.REGISTRY.update(t["id"], regenerate_icon=regen, **kw)
    if not res.get("ok"):
        return res
    team = res["team"]
    return {
        "ok": True,
        "team": team,
        "changed": sorted(kw) + (["icon"] if regen else []),
        "stdout": "updated team %s (%s %s) [%s]" % (
            team["id"], team.get("symbol"), team.get("name"),
            ", ".join(sorted(kw)) + (" + icon" if regen else ""),
        ),
    }


def _team_delete(args):
    from longrun.orchestrate import teams as teams_mod

    t = teams_mod.REGISTRY.get(args.get("team"))
    if not t:
        return {"ok": False, "error": "team not found: %s" % args.get("team")}
    members = list(t.get("members") or [])
    res = teams_mod.REGISTRY.delete(t["id"])
    if not res.get("ok"):
        return res
    res["members_kept"] = members
    res["stdout"] = "deleted team %s (%s); %d member agent(s) kept" % (
        t["id"], t.get("name"), len(members))
    return res


def _team_member_add(args):
    return _team_membership(args, remove=False)


def _team_member_remove(args):
    return _team_membership(args, remove=True)


def _team_membership(args, remove):
    from longrun.agent import agents as agents_mod
    from longrun.orchestrate import teams as teams_mod

    t = teams_mod.REGISTRY.get(args.get("team"))
    if not t:
        return {"ok": False, "error": "team not found: %s" % args.get("team")}
    sid, ag = _resolve_agent_session(args.get("agent"))
    if not sid:
        return {"ok": False, "error": "agent not found: %s" % args.get("agent")}
    if not ag:
        des = agents_mod.REGISTRY.designate(sid)
        if not des.get("ok"):
            return des
        ag = des["agent"]
    res = (teams_mod.REGISTRY.remove_member(t["id"], ag["id"]) if remove
           else teams_mod.REGISTRY.add_member(t["id"], ag["id"]))
    if not res.get("ok"):
        return res
    return {
        "ok": True,
        "agent": ag["id"],
        "team": res["team"],
        "stdout": "agent %s (%s) %s team %s (%s)" % (
            ag["id"], ag.get("name"), "removed from" if remove else "assigned to",
            res["team"]["id"], res["team"]["name"]
        ),
    }


def _job_create(args):
    from longrun.orchestrate import jobs as jobs_mod

    goal = str(args.get("goal") or "").strip()
    if not goal:
        return {"ok": False, "error": "goal required"}
    workers = []
    for item in (args.get("agents") or []):
        sid, ag = _resolve_agent_session(item)
        workers.append((ag or {}).get("id") or sid or str(item))
    coordinator = args.get("coordinator")
    if coordinator:
        sid, ag = _resolve_agent_session(coordinator)
        coordinator = (ag or {}).get("id") or sid or str(coordinator)
    if coordinator:
        # v629.1: the TEAM is org-driven for the tool too. The panel derives it
        # from the assignee; a tool-created job used to keep only the hand-listed
        # agents, so its subjobs never nested past one level. Same helper, no
        # second derivation — the coordinator's org subtree joins the list.
        try:
            for _aid in jobs_mod.org_agents(coordinator):
                if _aid and _aid not in workers:
                    workers.append(_aid)
        except Exception:  # noqa: BLE001 — an explicit list must still work
            pass
    if not workers:
        return {"ok": False,
                "error": "at least one worker agent required in 'agents' "
                         "(or a coordinator with reports in the org chart)"}
    res = jobs_mod.JOBS.create(
        goal, coordinator=coordinator, agents=workers, deps=args.get("deps"),
        mode=str(args.get("mode") or "coordinator"), blocked_by=args.get("blocked_by"))
    if res.get("ok"):
        job = res["job"]
        res["stdout"] = "created job %s [%s, coordinator=%s, workers=%d]" % (
            job["id"], job.get("status"), job.get("coordinator"), len(job.get("agents") or []))
    return res


def _job_dispatch(args):
    from longrun.orchestrate import jobs as jobs_mod

    jid = str(args.get("job") or "").strip()
    if not jid:
        return {"ok": False, "error": "job required"}
    res = jobs_mod.JOBS.dispatch(jid)
    res.setdefault("ok", True)
    if res.get("ok"):
        res["stdout"] = "dispatched job %s" % jid
    return res


def _job_get(args):
    from longrun.orchestrate import jobs as jobs_mod

    jid = str(args.get("job") or "").strip()
    job = jobs_mod.JOBS.detail(jid) if jid else None
    if not job:
        return {"ok": False, "error": "job not found: %s" % jid}
    return {"ok": True, "job": job}


def _job_list(_args=None):
    from longrun.orchestrate import jobs as jobs_mod

    out = jobs_mod.JOBS.list()
    out["ok"] = True
    out["stdout"] = "%d job(s)" % len(out.get("jobs") or [])
    return out


def _job_delete(args):
    from longrun.orchestrate import jobs as jobs_mod

    jid = str(args.get("job") or "").strip()
    if not jid:
        return {"ok": False, "error": "job required"}
    res = jobs_mod.JOBS.delete(jid)
    res.setdefault("ok", True)
    if res.get("ok"):
        res["stdout"] = "deleted job %s" % jid
    return res


def _routine_create(args):
    from longrun.orchestrate import routines as routines_mod

    sid, ag = _resolve_agent_session(args.get("agent"))
    if not sid:
        return {"ok": False, "error": "agent not found: %s" % args.get("agent")}
    # v663: the switch has TWO spellings (`enabled` / `disabled`) and the layer
    # below already reads both (`routines._enabled_arg`). This mapping hardcoded
    # `bool(args.get("enabled", True))`, so `disabled:true` was silently overruled
    # and the routine came back ENABLED (the operator's retest: "routine.create
    # disabled:true ignorato"). Forward BOTH and let the ONE reader decide.
    res = routines_mod.REGISTRY.create(
        sid, args.get("goal"), args.get("every_seconds"),
        enabled=args.get("enabled"), model=args.get("model"),
        disabled=args.get("disabled"))
    if res.get("ok"):
        rec = res["routine"]
        res["agent"] = (ag or {}).get("id") or sid
        res["stdout"] = "created routine %s for %s every %ss" % (
            rec["id"], rec.get("agent"), rec.get("every_seconds"))
    return res


def _routine_update(args):
    from longrun.orchestrate import routines as routines_mod

    rid = str(args.get("routine") or "").strip()
    if not rid:
        return {"ok": False, "error": "routine required"}
    kw = {}
    if args.get("agent") is not None:
        sid, _ag = _resolve_agent_session(args.get("agent"))
        if not sid:
            return {"ok": False, "error": "agent not found: %s" % args.get("agent")}
        kw["agent"] = sid
    # v663: `disabled` is part of the same switch — it was dropped here, so a patch
    # that ONLY disables answered "nothing to update" (the operator's retest).
    for key in ("goal", "every_seconds", "enabled", "disabled", "model"):
        if args.get(key) is not None:
            kw[key] = args.get(key)
    if not kw:
        return {"ok": False, "error": "nothing to update"}
    res = routines_mod.REGISTRY.update(rid, **kw)
    res.setdefault("ok", True)
    if res.get("ok"):
        res["stdout"] = "updated routine %s (%s)" % (rid, ", ".join(sorted(kw)))
    return res


def _routine_get(args):
    from longrun.orchestrate import routines as routines_mod

    rid = str(args.get("routine") or "").strip()
    rec = routines_mod.REGISTRY.get(rid) if rid else None
    if not rec:
        return {"ok": False, "error": "routine not found: %s" % rid}
    return {"ok": True, "routine": rec}


def _routine_list(_args=None):
    from longrun.orchestrate import routines as routines_mod

    out = routines_mod.REGISTRY.list()
    out["ok"] = True
    out["stdout"] = "%d routine(s)" % len(out.get("routines") or [])
    return out


def _routine_delete(args):
    from longrun.orchestrate import routines as routines_mod

    rid = str(args.get("routine") or "").strip()
    if not rid:
        return {"ok": False, "error": "routine required"}
    res = routines_mod.REGISTRY.delete(rid)
    res["stdout"] = "deleted routine %s" % rid
    return res


def _session_create(args):
    from longrun.memory import stores

    title = str(args.get("title") or "").strip() or None
    sess = stores.get_or_create_session(None, title)
    sid = sess["id"]
    ws = str(args.get("workspace") or "").strip()
    if ws:
        sess["workspace"] = os.path.abspath(os.path.expanduser(ws))
        stores.save_session(sess)
    return {
        "ok": True,
        "session": sid,
        "title": sess.get("title"),
        "workspace": sess.get("workspace"),
        "stdout": "created session %s (%s)" % (sid, sess.get("title") or "untitled"),
    }


def _session_rename(args):
    from longrun.memory import stores

    sid = str(args.get("session") or "").strip()
    title = str(args.get("title") or "").strip()
    if not sid:
        return {"ok": False, "error": "session required"}
    if not title:
        return {"ok": False, "error": "title required"}
    sess = stores.load_session(sid)
    if not sess:
        return {"ok": False, "error": "session not found: %s" % sid}
    sess["title"] = title
    stores.save_session(sess)
    try:
        from longrun.core.events import publish
        publish("session.renamed", session=sid, title=title, by="longrunAgent")
    except Exception:  # noqa: BLE001
        pass
    return {"ok": True, "session": sid, "title": title,
            "stdout": "renamed session %s -> %s" % (sid, title)}


def _session_list(_args=None):
    from longrun.memory import stores

    rows = stores.list_sessions()
    return {"ok": True, "sessions": rows, "count": len(rows or []),
            "stdout": "%d session(s)" % len(rows or [])}


def _session_delete(args):
    from longrun.core import httpapi

    sid = str(args.get("session") or "").strip()
    if not sid:
        return {"ok": False, "error": "session required"}
    return httpapi.delete_session(sid)


def _team_create(args):
    from longrun.orchestrate import teams as teams_mod

    name = str(args.get("name") or "").strip()[:80]
    if not name:
        return {"ok": False, "error": "name required"}
    desc = str(args.get("description") or "").strip()[:400]
    sym, col = choose_team_symbol(
        name, desc,
        explicit_symbol=args.get("symbol"),
        explicit_color=args.get("color"),
    )
    existing = teams_mod.REGISTRY.get(name)
    if existing:
        res = teams_mod.REGISTRY.update(
            existing["id"], name=name, symbol=sym, color=col,
            description=desc if desc else existing.get("description"),
        )
    else:
        res = teams_mod.REGISTRY.create(name, symbol=sym, color=col, description=desc)
    if not res.get("ok"):
        return res
    team = res["team"]
    team_ws = _ensure_agent_workspace("team-" + name)

    provisioned = []
    members_arg = args.get("members") or []
    if isinstance(members_arg, list):
        for item in members_arg:
            if isinstance(item, dict) and item.get("name"):
                sub = dict(item)
                sub["team"] = team["id"]
                sub_res = _agent_create(sub)
                if sub_res.get("ok") and sub_res.get("agent"):
                    provisioned.append(sub_res["agent"]["id"])
            elif isinstance(item, str) and item.strip():
                _, ag = _resolve_agent_session(item.strip())
                if ag:
                    teams_mod.REGISTRY.add_member(team["id"], ag["id"])
                    provisioned.append(ag["id"])

    team = teams_mod.REGISTRY.get(team["id"]) or team
    return {
        "ok": True,
        "team": team,
        "workspace": team_ws,
        "provisioned_members": provisioned,
        "stdout": "team %s (%s %s) ready [color=%s, members=%d, workspace=%s]" % (
            team["id"], team.get("symbol"), team.get("name"),
            team.get("color"), len(team.get("members") or []), team_ws
        ),
    }


def _webui_inspect(args):
    section = str(args.get("section") or "all").strip().lower()
    sid = str(args.get("session") or "").strip()
    out = {"ok": True, "section": section}
    if section in ("agents", "all"):
        from longrun.agent import agents as agents_mod
        out["agents"] = agents_mod.REGISTRY.tree()
    if section in ("teams", "all"):
        from longrun.orchestrate import teams as teams_mod
        out["teams"] = teams_mod.REGISTRY.list()
    if section in ("models", "all"):
        from longrun.model import routing
        out["routing"] = routing.load_config()
        out["preferred_cheap_models"] = list(PREFERRED_CHEAP_MODELS)
    if section in ("subagents", "all"):
        from longrun.agent import subagent as sub_mod
        from longrun.plan import keepgoing as kg
        out["subagents"] = {
            "config": sub_mod.load_cfg(),
            "max_depth": int((kg.cfg() or {}).get("subagent_max_depth", 2)),
            "running": sub_mod._running_count(),
            "context": "isolated",
        }
    if section in ("providers", "all"):
        from longrun.model import providers as providers_mod
        out["providers"] = providers_mod.catalog()
        out["providers_default"] = providers_mod.default_ref()
    if section in ("settings", "all"):
        from longrun.core import settings as settings_mod
        out["settings"] = settings_mod.view()
    if section in ("rules", "all"):
        from longrun.memory import rules as rules_mod
        ws = None
        if sid:
            from longrun.memory import stores
            s = stores.load_session(sid)
            ws = (s or {}).get("workspace")
        out["rules"] = rules_mod.status(ws)
    if section in ("compaction", "all"):
        from longrun.model import compaction_config
        out["compaction"] = compaction_config.load()
    if section in ("tools", "all"):
        from longrun.tools import registry
        cfg = registry.load_config()
        out["approvals"] = cfg.get("approvals") or {}
        out["tools_count"] = len(registry.catalog())
        out["tool_policy"] = {
            str(t.get("name")): {"enabled": t.get("enabled"), "approval": t.get("approval"),
                                 "origin": t.get("origin")}
            for t in registry.catalog() if not t.get("group")
        }
    if section in ("skills", "all"):
        from longrun.memory import skills as skills_mod
        items = skills_mod.list_skills()
        out["skills"] = [{"name": (s or {}).get("name"), "source": (s or {}).get("source")}
                         for s in (items if isinstance(items, list) else items.get("skills", []))]
    if section in ("mcp", "all"):
        from longrun.interop import mcp_client as mcp_client_mod
        out["mcp_clients"] = mcp_client_mod.status()
    if section in ("knowledge", "all"):
        from longrun.memory import knowledge as kb
        out["knowledge"] = {"status": kb.status(), "notebooks": kb.list_notebooks()}
    if section in ("index", "all"):
        from longrun.core import api_v02
        out["index"] = api_v02.index_config_get()
    if section in ("keys", "all"):
        # Names only — longrunAgent never reads or writes secret VALUES.
        from longrun.model import keys as keys_mod
        ks = keys_mod.keys_status()
        out["keys"] = sorted([str(k.get("env")) for k in (ks.get("keys") or [])])
        out["keys_note"] = "secret values are operator-only and never exposed to longrunAgent"
    out["stdout"] = "inspected WebUI substrate section=%s" % section
    return out


def _contains_forbidden_safety_key(obj, prefix=""):
    """Return the forbidden key name if `obj` attempts to touch any safety-only setting."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            ks = str(k).strip()
            path = ("%s.%s" % (prefix, ks)) if prefix else ks
            if ks in FORBIDDEN_SAFETY_KEYS or path in FORBIDDEN_SAFETY_KEYS:
                return path
            hit = _contains_forbidden_safety_key(v, path)
            if hit:
                return hit
    return None


def _contains_forbidden_safety_text(text):
    """Return the forbidden key name if a raw text body (config/rules content) names one.

    Raw file writes bypass the key-path guard, so any string payload that will be
    persisted must also be scanned for the safety-only key names.
    """
    body = str(text or "")
    if not body:
        return None
    for key in ("allow_nucleus_write", "allow_matrix_promote"):
        if key in body:
            return key
    return None


def _webui_configure(args):
    from longrun.core.events import publish

    hit = _contains_forbidden_safety_key(args)
    if hit:
        return {
            "ok": False,
            "error": (
                "SAFETY_GUARD: longrunAgent is forbidden from modifying %r "
                "(Nucleus write and Matrix promotion checkboxes may only be "
                "changed manually by the human operator)." % hit
            ),
        }

    target = str(args.get("target") or "").strip().lower()
    values = args.get("values") if isinstance(args.get("values"), dict) else {}

    if target == "config":
        # Raw config/*.yaml write takes a free-form text body, so the KEY-PATH scan
        # above cannot see it — scan the text itself before it is persisted.
        hit_text = _contains_forbidden_safety_text(
            "%s %s" % (args.get("file") or args.get("name") or "", args.get("text") or args.get("content") or "")
        )
        if hit_text:
            return {
                "ok": False,
                "error": (
                    "SAFETY_GUARD: longrunAgent is forbidden from naming %r in a persisted "
                    "config payload (operator-only safety switch)." % hit_text
                ),
            }

    if target == "settings":
        from longrun.core import settings as settings_mod
        fname = str(args.get("file") or "").strip()
        if not fname:
            return {"ok": False, "error": "file required for target='settings'"}
        res = settings_mod.update({"file": fname, "values": values})
        if res.get("ok"):
            publish("settings.changed", file=fname, by="longrunAgent")
            res["stdout"] = "updated settings %s (%s)" % (fname, ", ".join(sorted(values)))
        return res

    if target == "rules":
        from longrun.memory import rules as rules_mod
        scope = str(args.get("scope") or "project").strip().lower()
        content = args.get("content")
        if content is None:
            return {"ok": False, "error": "content required for target='rules'"}
        res = rules_mod.save(scope, str(content))
        if res.get("ok"):
            publish("rules.update", scope=scope, chars=res.get("chars", 0), by="longrunAgent")
            res["stdout"] = "updated %s rules (%d chars)" % (scope, res.get("chars", 0))
        return res

    if target == "compaction":
        from longrun.model import compaction_config
        patch = {}
        for k, v in values.items():
            if str(k).startswith("summarizer."):
                patch.setdefault("summarizer", {})[str(k).split(".", 1)[1]] = v
            elif k == "summarizer" and isinstance(v, dict):
                patch.setdefault("summarizer", {}).update(v)
        saved = compaction_config.save(
            trigger_pct=values.get("trigger_pct"),
            target_pct=values.get("target_pct"),
            keep_recent=values.get("keep_recent"),
            patch=patch or None,
        )
        publish("settings.changed", file="compaction.yaml", by="longrunAgent")
        return {
            "ok": True,
            "compaction": saved,
            "stdout": "updated compaction policy",
        }

    if target == "routing":
        from longrun.model import routing
        cfg = routing.load_config()
        roles = cfg.setdefault("roles", {})
        for k, v in values.items():
            if k.startswith("roles."):
                parts = k.split(".")
                if len(parts) == 3:
                    roles.setdefault(parts[1], {})[parts[2]] = v
            elif isinstance(v, dict):
                roles.setdefault(k, {}).update(v)
        routing.save_config(cfg)
        publish("settings.changed", file="routing.yaml", by="longrunAgent")
        return {
            "ok": True,
            "routing": cfg,
            "stdout": "updated model routing configuration",
        }

    if target == "team_policy":
        from longrun.orchestrate import teams as teams_mod
        team_ref = str(args.get("team") or "ALL").strip()
        if team_ref.upper() == "ALL":
            tms = [t["id"] for t in teams_mod.REGISTRY.list().get("teams", [])]
        else:
            tms = [team_ref]
        results = [teams_mod.REGISTRY.assign_models(tid) for tid in tms]
        return {
            "ok": True,
            "results": results,
            "stdout": "applied cheap remote model policy across %d team(s)" % len(results),
        }

    if target == "config":
        # JAG-488: validated + atomic write of any config/*.yaml, then hot reload.
        from longrun.core import configfiles
        from longrun.tools import matrix_guard
        name = args.get("file") or args.get("name")
        text = args.get("text") if args.get("text") is not None else args.get("content")
        try:
            with matrix_guard.NUCLEUS_EXEC_LOCK:
                res = configfiles.write_file(name, text)
        except ValueError as e:
            return {"ok": False, "error": str(e)}
        if res.get("ok"):
            publish("config.saved", name=name, ok=True, by="longrunAgent")
            res["stdout"] = "wrote config file %s" % name
        return res

    if target == "subagents":
        # Reuses the exact writers behind POST /api/subagents so the Subagents
        # panel can never drift from the WebUI.
        from longrun.agent import subagent as sub_mod
        from longrun.model import routing
        cfg = dict(sub_mod.load_cfg())
        if "max_parallel" in values:
            try:
                cfg["max_parallel"] = max(0, int(values["max_parallel"]))
            except (TypeError, ValueError):
                return {"ok": False, "error": "max_parallel must be an integer"}
        if isinstance(values.get("roles"), dict):
            cfg["roles"] = {str(k): str(v) for k, v in values["roles"].items()}
        upd = {}
        if "model" in values:
            upd["model"] = str(values.get("model") or "")
        if "fallbacks" in values:
            upd["fallbacks"] = [str(x) for x in (values.get("fallbacks") or [])]
        if upd:
            routing.update({"roles": {"subagent": upd}})
        if "max_depth" in values:
            from longrun.core import api_v02
            res = api_v02.update_policy({"runtime": {"subagent_max_depth": values["max_depth"]}})
            if not res.get("ok", True):
                return res
        sub_mod.save_cfg(cfg)
        publish("settings.changed", file="subagents.yaml", by="longrunAgent")
        return {
            "ok": True,
            "subagents": sub_mod.load_cfg(),
            "model": routing.role_model("subagent"),
            "stdout": "updated subagents policy (%s)" % ", ".join(sorted(values)),
        }

    if target == "tools":
        from longrun.core import api_v02
        body = dict(values)
        # The dual-permission gate on the exclusive namespaces is operator-only: the
        # agent may flip policy for ANY other tool, but never for its own tools.
        targets = [str(k) for k in body]
        targets += [str(body.get("tool") or ""), str(body.get("name") or "")]
        targets += [str(x) for x in (body.get("tools") or []) if isinstance(body.get("tools"), list)]
        self_hit = next((t for t in targets if is_exclusive_name(t)), None)
        if self_hit:
            return {
                "ok": False,
                "error": (
                    "SAFETY_GUARD: longrunAgent may not change its own tool policy "
                    "(%r) — the dual-permission gate is operator-only." % self_hit
                ),
            }
        res = api_v02.update_policy(body)
        if res.get("ok"):
            publish("tools.policy", by="longrunAgent")
            # The writer answers with the FULL catalog (one schema per tool); that is
            # noise in an agent observation, so report counts + what changed instead.
            tools = res.pop("tools", None)
            if isinstance(tools, list):
                res["tools_count"] = len(tools)
            res["stdout"] = "updated tool policy (%s)" % ", ".join(sorted(body))
        return res

    if target == "index":
        from longrun.memory import indexcfg as indexcfg_mod
        res = indexcfg_mod.save_config(values)
        if "ok" not in res:
            res = {"ok": True, "config": res}
        if res.get("ok"):
            publish("settings.changed", file="index.yaml", by="longrunAgent")
            res["stdout"] = "updated index config (%s)" % ", ".join(sorted(values))
        return res

    return {"ok": False, "error": "unknown configure target %r" % target}


def _webui_providers(args, op):
    """JAG-537: the provider/model roster, one typed tool per operation.

    `op` is fixed by the tool NAME (see `_SUBTOOL_MAP`), never chosen by the model,
    so `provider.remove` can only ever remove.
    """
    from longrun.core import api_v02
    from longrun.core.events import publish

    pid = str(args.get("id") or args.get("provider") or "").strip()
    if op == "reload":
        api_v02.provider_reload()
        publish("providers.update", action="reload", by="longrunAgent")
        return {"ok": True, "stdout": "providers reloaded"}
    if not pid:
        return {"ok": False, "error": "id required"}
    if op == "upsert":
        body = dict(args.get("values") or {})
        body.setdefault("id", pid)
        res = api_v02.provider_upsert(body)
    elif op == "remove":
        res = api_v02.provider_remove(pid)
    elif op == "add_model":
        res = api_v02.provider_add_model({
            "provider": args.get("provider") or pid, "model": args.get("model")})
    elif op == "remove_model":
        res = api_v02.provider_remove_model(args.get("provider") or pid, args.get("model"))
    else:  # default
        res = api_v02.provider_set_default({"ref": args.get("ref")})
    res.setdefault("ok", "error" not in res)
    if res.get("ok"):
        res["stdout"] = "providers %s applied" % op
    return res


def _webui_skills_remove(args):
    from longrun.core.events import publish
    from longrun.memory import skills as skills_mod

    nm = str(args.get("name") or "").strip()
    if not nm:
        return {"ok": False, "error": "name required"}
    res = skills_mod.remove(nm)
    res.setdefault("ok", False)
    if res.get("ok"):
        publish("skills.remove", name=nm, ok=True, by="longrunAgent")
        res["stdout"] = "removed skill %s" % nm
    return res


def _webui_mcp(args, op):
    from longrun.core.events import publish
    from longrun.interop import mcp_client as mcp_client_mod

    nm = str(args.get("name") or "").strip()
    if op == "reload":
        mcp_client_mod.reload()
        publish("mcp.clients", action="reload", ok=True, by="longrunAgent")
        return {"ok": True, "stdout": "reloaded MCP clients"}
    if not nm:
        return {"ok": False, "error": "name required"}
    if op == "remove":
        res = mcp_client_mod.remove_client(nm)
    elif op == "test":
        res = mcp_client_mod.test_client({"name": nm})
    else:  # upsert
        values = args.get("values") if isinstance(args.get("values"), dict) else {}
        res = mcp_client_mod.upsert_client(nm, dict(values))
    res.setdefault("ok", False)
    publish("mcp.clients", action=op, name=nm, ok=bool(res.get("ok")))
    if res.get("ok"):
        res["stdout"] = "MCP client %s %s" % (nm, op)
    return res


def _webui_knowledge(args, op):
    from longrun.core import api_v02
    from longrun.core.events import publish

    if op == "notebook.create":
        res = api_v02.knowledge_notebook_action({"action": "create", "name": args.get("name")})
    elif op == "notebook.rename":
        res = api_v02.knowledge_notebook_action({
            "action": "rename", "id": args.get("id"), "name": args.get("name")})
    elif op == "notebook.delete":
        res = api_v02.knowledge_notebook_action({"action": "delete", "id": args.get("id")})
    elif op == "source.add":
        res = api_v02.knowledge_source_action({
            "notebook": args.get("notebook"), "title": args.get("title"),
            "text": args.get("content"), "ref": args.get("ref")})
    elif op == "source.remove":
        res = api_v02.knowledge_source_action({"remove": args.get("source")})
    else:  # reembed
        from longrun.memory import knowledge as kb
        res = kb.reembed()
    res.setdefault("ok", "error" not in res)
    publish("knowledge.docs", action=op, ok=bool(res.get("ok")), by="longrunAgent")
    if res.get("ok"):
        res["stdout"] = "knowledge %s applied" % op
    return res


_SUBTOOL_MAP = {
    "agent.create": _agent_create,
    "agent.update": _agent_update,
    "agent.get": _agent_get,
    "agent.list": _agent_list,
    "agent.delete": _agent_delete,
    "agent.prompt_set": _agent_prompt_set,
    "agent.prompt_get": _agent_prompt_get,
    "agent.prompt_clear": _agent_prompt_clear,
    "team.create": _team_create,
    "team.update": _team_update,
    "team.get": _team_get,
    "team.list": _team_list,
    "team.delete": _team_delete,
    "team.member_add": _team_member_add,
    "team.member_remove": _team_member_remove,
    "job.create": _job_create,
    "job.dispatch": _job_dispatch,
    "job.get": _job_get,
    "job.list": _job_list,
    "job.delete": _job_delete,
    "routine.create": _routine_create,
    "routine.update": _routine_update,
    "routine.get": _routine_get,
    "routine.list": _routine_list,
    "routine.delete": _routine_delete,
    "session.create": _session_create,
    "session.rename": _session_rename,
    "session.list": _session_list,
    "session.delete": _session_delete,
    "webui.inspect": _webui_inspect,
    "webui.configure": _webui_configure,
    # Typed object tools: the operation is bound HERE, by name, so the model can only
    # pick the verb it asked for (no `op` string to get wrong).
    "provider.upsert": lambda a: _webui_providers(a, "upsert"),
    "provider.remove": lambda a: _webui_providers(a, "remove"),
    "provider.add_model": lambda a: _webui_providers(a, "add_model"),
    "provider.remove_model": lambda a: _webui_providers(a, "remove_model"),
    "provider.set_default": lambda a: _webui_providers(a, "default"),
    "provider.reload": lambda a: _webui_providers(a, "reload"),
    "skill.remove": _webui_skills_remove,
    "mcp.upsert": lambda a: _webui_mcp(a, "upsert"),
    "mcp.remove": lambda a: _webui_mcp(a, "remove"),
    "mcp.test": lambda a: _webui_mcp(a, "test"),
    "mcp.reload": lambda a: _webui_mcp(a, "reload"),
    "kb.notebook_add": lambda a: _webui_knowledge(a, "notebook.create"),
    "kb.notebook_rename": lambda a: _webui_knowledge(a, "notebook.rename"),
    "kb.notebook_delete": lambda a: _webui_knowledge(a, "notebook.delete"),
    "kb.source_add": lambda a: _webui_knowledge(a, "source.add"),
    "kb.source_remove": lambda a: _webui_knowledge(a, "source.remove"),
    "kb.reembed": lambda a: _webui_knowledge(a, "reembed"),
}


def execute(tool, args, run_id=None):
    """Execute ONE `namespace.tool` exclusive tool after the dual-permission gate."""
    args = dict(args or {})
    # `action` is RESERVED: no schema carries it, and the dispatcher already
    # resolved the verb from the tool NAME (`team.member_add`), never from args.
    args.pop("action", None)
    tool = str(tool or "").strip()
    ok, reason = check_dual_permission(tool, run_id=run_id)
    if not ok:
        return {
            "ok": False,
            "tool": tool,
            "exit_code": 126,
            "permission_denied": True,
            "error": reason,
        }
    fn = _SUBTOOL_MAP.get(tool)
    if fn is None:
        return {
            "ok": False,
            "tool": tool,
            "exit_code": 127,
            "error": "unknown exclusive tool %r — available: %s"
                     % (tool, ", ".join(sorted(_SUBTOOL_MAP))),
        }
    return fn(args)


# ---------------------------------------------- stateless automation runner ---

# Context-specific system prompts, one per automate-able WebUI section (requirement:
# each section's Automate control must tell longrunAgent WHERE it is, WHAT the
# section is for, and WHICH data to retrieve before acting).
SECTION_PROMPTS = {
    "teamorg": (
        "You are `longrunAgent` (VEO, the burattino of agents), operating inside the "
        "Orbit Control / AGENTS & TEAMS panel. Use ONLY the exclusive object tools "
        "(`namespace.tool`) to fulfill the user's request on the substrate. Every "
        "object you can create, you can also read and remove: "
        "`team.create|update|delete|get|list|member_add|member_remove`, "
        "`agent.create|update|delete|get|list|prompt_set|prompt_get|prompt_clear`, "
        "`job.create|dispatch|delete|get|list`, "
        "`routine.create|update|delete|get|list`, "
        "`session.create|rename|delete|list`. "
        "Always pick lightweight, cost-effective remote cloud models (e.g. "
        "`openrouter:deepseek/deepseek-v4.1-flash`, `deepseek:deepseek-flash`, "
        "`openrouter:z-ai/glm-5.3-flash`, "
        "`openrouter:meta/muse-spark-1.3-contributor`), never heavy local models, and "
        "draft clear, concise `ROLE.md` prompts."
    ),
    "models": (
        "You are `longrunAgent` automating the Settings ▸ Models & Routing section. "
        "Inspect with `webui.inspect` (`section:'models'`) and apply updates "
        "with `webui.configure` (`target:'routing'`). Prefer cheap remote models."
    ),
    "compaction": (
        "You are `longrunAgent` automating the Settings ▸ Compaction section. "
        "Inspect with `webui.inspect` (`section:'compaction'`) and apply updates "
        "with `webui.configure` (`target:'compaction'`)."
    ),
    "rules": (
        "You are `longrunAgent` automating the Rules section (`Global_rules.md` / `Project_rules.md`). "
        "Inspect with `webui.inspect` (`section:'rules'`) and write updated rules "
        "with `webui.configure` (`target:'rules'`)."
    ),
    "settings": (
        "You are `longrunAgent` automating a structured WebUI Settings section. "
        "Inspect with `webui.inspect` (`section:'settings'`) and apply validated "
        "changes with `webui.configure` (`target:'settings'`). Never touch "
        "safety checkboxes (`allow_nucleus_write`, `allow_matrix_promote`)."
    ),
    "subagents": (
        "You are `longrunAgent` automating the Settings ▸ Subagents panel. Inspect with "
        "`webui.inspect` (`section:'subagents'`) and update with "
        "`webui.configure` (`target:'subagents'`, values: model / fallbacks / "
        "max_parallel / max_depth / roles). Prefer cheap remote models; keep role briefs concise."
    ),
    "providers": (
        "You are `longrunAgent` automating the Settings ▸ Providers / Models roster. Inspect "
        "with `webui.inspect` (`section:'providers'`) and change it with the typed "
        "tools `provider.upsert|remove|add_model|remove_model|default|reload`. "
        "Never read or write secret keys."
    ),
    "tools": (
        "You are `longrunAgent` automating the Settings ▸ Tools policy panel. Inspect with "
        "`webui.inspect` (`section:'tools'`) and flip per-tool `enabled`/`approval` "
        "with `webui.configure` (`target:'tools'`). You may NOT change any "
        "exclusive tool entry (`agent.*`, `team.*`, `kb.*`, …) — that gate is operator-only."
    ),
    "skills": (
        "You are `longrunAgent` automating the Settings ▸ Skills panel. Inspect with "
        "`webui.inspect` (`section:'skills'`) and uninstall a local skill with "
        "`skill.remove`. Installing a new skill requires a zip upload and "
        "stays manual."
    ),
    "mcp": (
        "You are `longrunAgent` automating the Settings ▸ MCP panel. Inspect with "
        "`webui.inspect` (`section:'mcp'`) and manage external servers with the "
        "typed tools `mcp.upsert|remove|test|reload`. "
        "Reference secrets by NAME (`${VAR}`), never by value."
    ),
    "knowledge": (
        "You are `longrunAgent` automating the Settings ▸ Knowledge panel. Inspect with "
        "`webui.inspect` (`section:'knowledge'`) and manage notebooks and sources "
        "with `kb.notebook_add|rename|delete`, "
        "`kb.source_add|remove` and "
        "`kb.reembed`."
    ),
    "index": (
        "You are `longrunAgent` automating the Settings ▸ Codebase index configuration. Inspect "
        "with `webui.inspect` (`section:'index'`) and update with "
        "`webui.configure` (`target:'index'`)."
    ),
    "config": (
        "You are `longrunAgent` editing a raw `config/*.yaml` file through the Config-files panel. "
        "Inspect with `webui.inspect` (`section:'all'`) and write with "
        "`webui.configure` (`target:'config'`, file + text). Never name the "
        "operator-only safety switches (`allow_nucleus_write`, `allow_matrix_promote`)."
    ),
    "routing": (
        "You are `longrunAgent` automating the model ROUTING table (which model backs each "
        "role). Inspect with `webui.inspect` (`section:'models'`) and update with "
        "`webui.configure` (`target:'routing'`, `values:{'roles.<role>.model': ref}`). "
        "Prefer cheap remote models."
    ),
    "team_policy": (
        "You are `longrunAgent` re-applying the cheap remote model policy across Orbit teams. "
        "Inspect with `webui.inspect` (`section:'teams'`) and apply with "
        "`webui.configure` (`target:'team_policy'`, `team:'T1'` or `'ALL'`)."
    ),
    "harness": (
        "You are `longrunAgent` automating the Settings ▸ Harness / Sandbox runtime policy "
        "(`config/tools.yaml` ▸ runtime: keepgoing, verifier, best-of-n, difficulty, self-evolve, "
        "thinking effort, sandbox limits). Inspect with `webui.inspect` "
        "(`section:'tools'`) and apply with `webui.configure` (`target:'tools'`, "
        "`values:{runtime:{...}}`). You may NOT change any exclusive tool entry or the "
        "self-improvement policy that edits `src/longrun` — those are operator-only."
    ),
}

# Automate section -> `webui.inspect` section, so the subscriber
# snapshot injected into the goal is NEVER empty for a valid automation request.
AUTOMATE_INSPECT_SECTIONS = {
    "teamorg": "agents",
    "models": "models",
    "routing": "models",
    "team_policy": "teams",
    "compaction": "compaction",
    "rules": "rules",
    "settings": "settings",
    "subagents": "subagents",
    "providers": "providers",
    "tools": "tools",
    "harness": "tools",
    "skills": "skills",
    "mcp": "mcp",
    "knowledge": "knowledge",
    "index": "index",
    "config": "all",
}


# 2026-10-23: automation is limited to text the operator already edits by hand.
# `rules` writes Global/Project rules; the Teamorg aliases create agents/teams and
# their prompts. Every other section rewrites runtime configuration (tools policy,
# routing, providers, subagents, MCP, index): an agent must never flip those
# autonomously, so the endpoint refuses even when a client calls it directly.
AUTOMATE_ALLOWED_SECTIONS = ("rules", "teamorg", "agents", "teams", "orbit")


def automate(section, instruction, context=None, session=None, model=None, max_steps=6):
    """Run a stateless `longrunAgent` automation turn for a WebUI section.

    1. Resets the permanent `longrunAgent` session before starting (stateless);
    2. Checks that `longrunAgent` tools are enabled in the global registry;
    3. Builds a section-specific goal + live substrate snapshot;
    4. Runs `agent_run_v2` under `LONGRUN_AGENT_SESSION_ID` with the resolved
       cheap remote (or `@chat`) model;
    5. Resets the `longrunAgent` session transcript afterwards so no residual
       memory leaks into future runs.
    """
    from longrun.core import api_v02
    from longrun.core.events import publish

    section = str(section or "teamorg").strip().lower()
    instruction = str(instruction or "").strip()
    if section not in AUTOMATE_ALLOWED_SECTIONS:
        return {
            "ok": False, "disabled": True,
            "error": ("automation is disabled for section %r: only text surfaces "
                      "(rules) and Teamorg prompts may be automated; runtime config "
                      "stays manual" % section),
            "allowed_sections": list(AUTOMATE_ALLOWED_SECTIONS),
        }
    if not instruction:
        return {"ok": False, "error": "instruction required"}

    # Verify global tool enablement before launching
    probe_tool = ("team.create"
                  if section in ("teamorg", "agents", "teams", "orbit")
                  else "webui.configure")
    ok_perm, reason = check_dual_permission(probe_tool, run_id=LONGRUN_AGENT_SESSION_ID)
    if not ok_perm:
        return {"ok": False, "error": reason, "permission_denied": True}

    reset_stateless_session()
    resolved_model = resolve_automation_model(active_session_id=session, explicit_model=model)
    sec_prompt = SECTION_PROMPTS.get(section, SECTION_PROMPTS["settings"])
    snap = _webui_inspect({"section": AUTOMATE_INSPECT_SECTIONS.get(section, "all"),
                           "session": session})
    snap_json = json.dumps({k: v for k, v in snap.items() if k not in ("ok", "stdout")},
                           ensure_ascii=False, default=str)[:6000]
    ctx_json = json.dumps(context or {}, ensure_ascii=False, default=str)[:2000]

    full_goal = (
        "[LONGRUN_AGENT STATELESS AUTOMATION — SECTION: %s]\n"
        "%s\n\n"
        "Current section context from UI: %s\n"
        "Current substrate state: %s\n\n"
        "Operator instruction: %s\n"
        "Execute the required exclusive (`namespace.tool`) calls now, then conclude with `final`."
        % (section, sec_prompt, ctx_json, snap_json, instruction)
    )

    publish("longrun_agent.start", section=section, model=resolved_model,
            session=LONGRUN_AGENT_SESSION_ID)
    try:
        st = api_v02.new_run(full_goal, resolved_model, max(1, min(int(max_steps or 6), 12)))
        st.id = "%s_%s" % (LONGRUN_AGENT_SESSION_ID, st.id)
        with api_v02.RUNS_LOCK:
            api_v02.RUNS[st.id] = st
        run_res = api_v02.agent_run_v2(
            full_goal,
            max_steps=max(1, min(int(max_steps or 6), 12)),
            model=resolved_model,
            run_id=st.id,
        )
    finally:
        reset_stateless_session()
        publish("longrun_agent.done", section=section, model=resolved_model,
                session=LONGRUN_AGENT_SESSION_ID)

    return {
        "ok": run_res.get("status") == "done",
        "section": section,
        "session": LONGRUN_AGENT_SESSION_ID,
        "stateless": True,
        "model": resolved_model,
        "result": run_res.get("result") or "",
        "steps": run_res.get("steps") or [],
        "run_id": run_res.get("id"),
    }
