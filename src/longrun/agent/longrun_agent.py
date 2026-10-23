"""longrunAgent (VEO — the burattinaio of agents) — JAG-535.

Permanent, undeletable, stateless system automation agent that manages the
substrate (Layer 2) of the Longrun harness:
  - Teamorg (`longrunAgent.teamorg.*`): full lifecycle of Orbit AGENTS & TEAMS
    (creating teams with semantic icon/colour chosen from the palette,
    provisioning agent records + dedicated workspace folders, assigning cheap
    remote LLM models, setting functional roles, writing system prompts in
    ROLE.md, and assigning agents to teams).
  - Universal WebUI substrate automation (`longrunAgent.webui.*`): reading and
    updating any configurable section of the platform (settings forms, rules,
    routing, compaction) while strictly enforcing safety boundaries (NEVER
    allowed to enable `allow_nucleus_write` or `allow_matrix_promote` — those
    belong exclusively to the human operator).
  - Dual-permission gate: a `longrunAgent.*` tool can execute ONLY when:
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
    "openrouter:deepseek/deepseek-reasoner",
    "openrouter:deepseek/deepseek-v4-flash-0731",
    "openrouter:z-ai/glm-5.3-flash",
    "openrouter:meta/muse-spark-1.3-contributor",
    "deepseek:deepseek-reasoner",
    "deepseek:deepseek-chat",
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
    "longrunAgent.teamorg.agents.create": {
        "description": (
            "longrunAgent.teamorg.agents.create — Provision a new org agent record (and its underlying "
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
        "_namespace": "longrunAgent",
        "_subtool": "teamorg.agents.create",
    },
    "longrunAgent.teamorg.agents.setllm": {
        "description": (
            "longrunAgent.teamorg.agents.setllm — Assign an LLM model (`<provider>:<model>`) to an existing "
            "agent and its underlying session in lockstep. Prefers lightweight, cost-effective cloud models "
            "when `model` is 'auto' or omitted."
        ),
        "type": "object",
        "properties": {
            "agent": {"type": "string", "description": "Target agent ID (e.g. 'A3'), session ID, or agent name."},
            "model": {"type": "string", "description": "Model reference (`<provider>:<model>`, or 'auto' for cheap remote default)."},
        },
        "required": ["agent", "model"],
        "_origin": "exclusive",
        "_namespace": "longrunAgent",
        "_subtool": "teamorg.agents.setllm",
    },
    "longrunAgent.teamorg.agents.setrole": {
        "description": (
            "longrunAgent.teamorg.agents.setrole — Define or update an agent's functional role badge "
            "and optional manager (`reports_to`) in the Orbit organigram."
        ),
        "type": "object",
        "properties": {
            "agent": {"type": "string", "description": "Target agent ID ('A3'), session ID, or agent name."},
            "role": {"type": "string", "description": "Functional role title (e.g. 'qa-engineer', 'researcher')."},
            "reports_to": {"type": "string", "description": "Optional manager agent ID ('A1') or '' to make root."},
        },
        "required": ["agent", "role"],
        "_origin": "exclusive",
        "_namespace": "longrunAgent",
        "_subtool": "teamorg.agents.setrole",
    },
    "longrunAgent.teamorg.agents.setprompt": {
        "description": (
            "longrunAgent.teamorg.agents.setprompt — Configure an agent's system prompt (`ROLE.md`) in the "
            "substrate and broadcast `roles.update` so the WebUI and Orbit table refresh immediately."
        ),
        "type": "object",
        "properties": {
            "agent": {"type": "string", "description": "Target agent ID ('A3'), session ID, or agent name."},
            "prompt": {"type": "string", "description": "Full ROLE.md system prompt text for the agent."},
        },
        "required": ["agent", "prompt"],
        "_origin": "exclusive",
        "_namespace": "longrunAgent",
        "_subtool": "teamorg.agents.setprompt",
    },
    "longrunAgent.teamorg.agents.assignagent": {
        "description": (
            "longrunAgent.teamorg.agents.assignagent — Add (or remove) an agent to/from a specific team "
            "(`T1` or team name) and sync the Orbit constellation."
        ),
        "type": "object",
        "properties": {
            "agent": {"type": "string", "description": "Target agent ID ('A3'), session ID, or agent name."},
            "team": {"type": "string", "description": "Target team ID ('T1') or team name."},
            "remove": {"type": "boolean", "description": "When true, remove the agent from the team instead of adding."},
        },
        "required": ["agent", "team"],
        "_origin": "exclusive",
        "_namespace": "longrunAgent",
        "_subtool": "teamorg.agents.assignagent",
    },
    "longrunAgent.teamorg.teams.create": {
        "description": (
            "longrunAgent.teamorg.teams.create — Spin up a new team (`TN`) with a semantic icon and colour "
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
        "_namespace": "longrunAgent",
        "_subtool": "teamorg.teams.create",
    },
    "longrunAgent.webui.inspect": {
        "description": (
            "longrunAgent.webui.inspect — Read the current live substrate state of ANY WebUI "
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
        "_namespace": "longrunAgent",
        "_subtool": "webui.inspect",
    },
    "longrunAgent.webui.configure": {
        "description": (
            "longrunAgent.webui.configure — Update configurable fields in ANY WebUI substrate "
            "section: structured settings forms, rules, compaction policy, role routing, team "
            "model policy, subagents, providers/models, tool policy, skills, MCP clients, "
            "knowledge notebooks/sources and the index config. Emits live-sync SSE events. "
            "Strictly refuses safety-gate keys (`allow_nucleus_write`, `allow_matrix_promote`)."
        ),
        "type": "object",
        "properties": {
            "target": {
                "type": "string",
                "enum": ["settings", "rules", "compaction", "routing", "team_policy",
                         "subagents", "providers", "tools", "skills", "mcp", "knowledge",
                         "index", "config"],
                "description": "Substrate target domain to update.",
            },
            "file": {"type": "string", "description": "For target='settings': config filename (e.g. 'index.yaml', 'compaction.yaml', 'decisions.yaml')."},
            "values": {"type": "object", "description": "Key-value map of fields to update (settings / routing / compaction / subagents / tools / index / knowledge)."},
            "scope": {"type": "string", "description": "For target='rules': 'global' or 'project'."},
            "content": {"type": "string", "description": "For target='rules': full markdown content to save."},
            "team": {"type": "string", "description": "For target='team_policy': team ID ('T1') or 'ALL'."},
            "op": {"type": "string", "description": "Sub-operation for target='providers' (upsert|remove|add_model|remove_model|default|reload), 'skills' (remove), 'mcp' (upsert|remove|test|reload) and 'knowledge' (notebook|source|clear|reembed). NOTE: `action` is reserved by the dispatcher (it carries the subtool name), so always use `op`."},
            "id": {"type": "string", "description": "Identifier for providers (`id`/`ref`) and knowledge notebooks (`id`)."},
            "model": {"type": "string", "description": "Model reference for providers / subagents."},
            "provider": {"type": "string", "description": "For target='providers' model ops: provider id."},
            "name": {"type": "string", "description": "For target='skills'/'mcp'/'knowledge': target name (or notebook name)."},
            "notebook": {"type": "string", "description": "For target='knowledge' op='source': notebook id/name."},
            "title": {"type": "string", "description": "For target='knowledge' op='source': source title."},
            "ref": {"type": "string", "description": "For target='knowledge' op='source': source URL/path ref. For target='providers' op='default': model ref."},
            "remove": {"type": "string", "description": "For target='knowledge' op='source': source to remove."},
        },
        "required": ["target"],
        "_origin": "exclusive",
        "_namespace": "longrunAgent",
        "_subtool": "webui.configure",
    },
}


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
    """True when `sid` is permitted to invoke `longrunAgent.*` tools.

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
    """Verify BOTH global tool enablement AND session privilege for `longrunAgent.*`.

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
            "grant (`allow_longrun_agent: true`)" % (run_id or "anonymous", tool)
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


def _agent_setllm(args):
    from longrun.agent import agents as agents_mod
    from longrun.orchestrate import teams as teams_mod

    target = args.get("agent")
    sid, ag = _resolve_agent_session(target)
    if not sid:
        return {"ok": False, "error": "agent not found: %s" % target}
    if not ag:
        des = agents_mod.REGISTRY.designate(sid)
        if not des.get("ok"):
            return des
        ag = des["agent"]
    model = str(args.get("model") or "").strip()
    if not model or model.lower() == "auto":
        model = pick_cheap_remote_model()
    conflict = teams_mod.REGISTRY.local_conflict(ag["id"], model)
    if conflict:
        return {
            "ok": False,
            "error": "local model conflict on %s in team %s (held by %s); prefer a cheap remote model"
                     % (conflict["machine"], conflict["team"], conflict["other"]),
            "conflict": conflict,
        }
    res = agents_mod.REGISTRY.set_model(sid, model)
    if not res.get("ok"):
        return res
    try:
        from longrun.memory import stores
        stores._set_session_model(sid, model)
    except Exception:  # noqa: BLE001
        pass
    return {
        "ok": True,
        "agent": res["agent"],
        "session": sid,
        "model": model,
        "stdout": "assigned model %s to agent %s (%s)" % (model, ag["id"], ag.get("name")),
    }


def _agent_setrole(args):
    from longrun.agent import agents as agents_mod

    target = args.get("agent")
    sid, ag = _resolve_agent_session(target)
    if not sid:
        return {"ok": False, "error": "agent not found: %s" % target}
    role = str(args.get("role") or "").strip()[:80]
    if not role:
        return {"ok": False, "error": "role required"}
    kw = {"role": role}
    if "reports_to" in args and args.get("reports_to") is not None:
        rep = str(args.get("reports_to") or "").strip()
        if rep:
            _, mgr = _resolve_agent_session(rep)
            kw["reports_to"] = mgr["id"] if mgr else rep
        else:
            kw["reports_to"] = ""
    res = agents_mod.REGISTRY.designate(sid, **kw)
    if not res.get("ok"):
        return res
    return {
        "ok": True,
        "agent": res["agent"],
        "session": sid,
        "role": role,
        "stdout": "updated role of %s (%s) -> %s" % (
            res["agent"]["id"], res["agent"].get("name"), role
        ),
    }


def _agent_setprompt(args):
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


def _agent_assign(args):
    from longrun.agent import agents as agents_mod
    from longrun.orchestrate import teams as teams_mod

    target = args.get("agent")
    team_ref = str(args.get("team") or "").strip()
    if not team_ref:
        return {"ok": False, "error": "team required"}
    sid, ag = _resolve_agent_session(target)
    if not sid:
        return {"ok": False, "error": "agent not found: %s" % target}
    if not ag:
        des = agents_mod.REGISTRY.designate(sid)
        if not des.get("ok"):
            return des
        ag = des["agent"]
    t = teams_mod.REGISTRY.get(team_ref)
    if not t:
        return {"ok": False, "error": "team not found: %s" % team_ref}
    if args.get("remove"):
        res = teams_mod.REGISTRY.remove_member(t["id"], ag["id"])
        verb = "removed from"
    else:
        res = teams_mod.REGISTRY.add_member(t["id"], ag["id"])
        verb = "assigned to"
    if not res.get("ok"):
        return res
    return {
        "ok": True,
        "agent": ag["id"],
        "team": res["team"],
        "stdout": "agent %s (%s) %s team %s (%s)" % (
            ag["id"], ag.get("name"), verb, res["team"]["id"], res["team"]["name"]
        ),
    }


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
    # NOTE: `action` is reserved by the tool dispatcher (it always carries the
    # subtool name), so the sub-operation travels in `op`.
    op = str(args.get("op") or args.get("operation") or "").strip().lower()

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

    if target == "providers":
        from longrun.core import api_v02
        if op in ("remove", "delete"):
            res = api_v02.provider_remove(args.get("id") or args.get("provider"))
        elif op in ("add_model", "model"):
            res = api_v02.provider_add_model({
                "provider": args.get("provider") or args.get("id"),
                "model": args.get("model"),
                "context_length": args.get("context_length"),
            })
        elif op == "remove_model":
            res = api_v02.provider_remove_model(args.get("provider"), args.get("model"))
        elif op in ("default", "set_default"):
            res = api_v02.provider_set_default({"ref": args.get("ref") or args.get("model")})
        elif op == "reload":
            api_v02.provider_reload()
            publish("providers.update", action="reload", by="longrunAgent")
            return {"ok": True, "stdout": "providers reloaded"}
        else:
            res = api_v02.provider_upsert(dict(values or args.get("provider_spec") or {}))
        if res.get("ok"):
            res["stdout"] = "providers %s applied" % (op or "upsert")
        return res

    if target == "tools":
        from longrun.core import api_v02
        body = dict(values)
        # The dual-permission gate on `longrunAgent.*` is operator-only: the agent
        # may flip policy for ANY other tool, but never for its own namespace.
        targets = [str(k) for k in body]
        targets += [str(body.get("tool") or ""), str(body.get("name") or "")]
        targets += [str(x) for x in (body.get("tools") or []) if isinstance(body.get("tools"), list)]
        self_hit = next((t for t in targets if t.startswith("longrunAgent")), None)
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

    if target == "skills":
        from longrun.memory import skills as skills_mod
        nm = str(args.get("name") or args.get("id") or "").strip()
        if op not in ("remove", "delete"):
            return {"ok": False, "error": "op='remove' required for target='skills' (install needs a zip upload)"}
        if not nm:
            return {"ok": False, "error": "name required for target='skills'"}
        res = skills_mod.remove(nm)
        if res.get("ok"):
            publish("skills.remove", name=nm, ok=True, by="longrunAgent")
            res["stdout"] = "removed skill %s" % nm
        res.setdefault("ok", False)
        return res

    if target == "mcp":
        from longrun.interop import mcp_client as mcp_client_mod
        nm = str(args.get("name") or args.get("id") or "").strip()
        if op == "reload":
            mcp_client_mod.reload()
            publish("mcp.clients", action="reload", ok=True, by="longrunAgent")
            return {"ok": True, "stdout": "reloaded MCP clients"}
        if op in ("remove", "delete"):
            res = mcp_client_mod.remove_client(nm)
        elif op == "test":
            res = mcp_client_mod.test_client(dict(values or {"name": nm}))
        else:
            res = mcp_client_mod.upsert_client(nm, dict(values or args.get("spec") or {}))
        res.setdefault("ok", False)
        publish("mcp.clients", action=(op or "upsert"), name=nm, ok=bool(res.get("ok")))
        if res.get("ok"):
            res["stdout"] = "MCP client %s %s" % (nm, op or "upsert")
        return res

    if target == "knowledge":
        from longrun.core import api_v02
        if op in ("notebook", "notebooks"):
            nb_action = str((values.get("action") if isinstance(values, dict) else "") or "").strip().lower()
            if not nb_action:
                nb_action = "rename" if args.get("id") else "create"
            res = api_v02.knowledge_notebook_action({
                "action": nb_action,
                "id": args.get("id"),
                "name": args.get("name"),
            })
        elif op in ("source", "sources"):
            res = api_v02.knowledge_source_action({
                "notebook": args.get("notebook"),
                "title": args.get("title"),
                "text": args.get("content"),
                "ref": args.get("ref"),
                "remove": args.get("remove"),
            })
        elif op == "clear":
            from longrun.memory import knowledge as kb
            res = kb.clear()
        elif op == "reembed":
            from longrun.memory import knowledge as kb
            res = kb.reembed()
        else:
            return {"ok": False, "error": "op must be notebook|source|clear|reembed"}
        res.setdefault("ok", "error" not in res)
        publish("knowledge.docs", action=op, ok=bool(res.get("ok")), by="longrunAgent")
        if res.get("ok"):
            res["stdout"] = "knowledge %s applied" % op
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


_SUBTOOL_MAP = {
    "longrunAgent.teamorg.agents.create": _agent_create,
    "longrunAgent.teamorg.agents.setllm": _agent_setllm,
    "longrunAgent.teamorg.agents.setrole": _agent_setrole,
    "longrunAgent.teamorg.agents.setprompt": _agent_setprompt,
    "longrunAgent.teamorg.agents.assignagent": _agent_assign,
    "longrunAgent.teamorg.teams.create": _team_create,
    "longrunAgent.webui.inspect": _webui_inspect,
    "longrunAgent.webui.configure": _webui_configure,
}


def execute(tool, args, run_id=None):
    """Execute a `longrunAgent.*` tool after enforcing the dual-permission gate."""
    args = dict(args or {})
    if not str(tool or "").startswith("longrunAgent."):
        sub = str(args.pop("action", "") or "").strip()
        tool = "longrunAgent." + sub if sub else "longrunAgent"
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
            "error": "unknown longrunAgent subtool %r — available: %s"
                     % (tool, ", ".join(sorted(_SUBTOOL_MAP))),
        }
    return fn(args)


# ---------------------------------------------- stateless automation runner ---

# Context-specific system prompts, one per automate-able WebUI section (requirement:
# each section's Automate control must tell longrunAgent WHERE it is, WHAT the
# section is for, and WHICH data to retrieve before acting).
SECTION_PROMPTS = {
    "teamorg": (
        "You are `longrunAgent` (VEO, the burattinaio of agents), operating inside the "
        "Orbit Control / AGENTS & TEAMS panel. Use ONLY `longrunAgent.teamorg.*` tools "
        "(`longrunAgent.teamorg.teams.create`, `longrunAgent.teamorg.agents.create`, "
        "`longrunAgent.teamorg.agents.setrole`, `longrunAgent.teamorg.agents.setprompt`, "
        "`longrunAgent.teamorg.agents.setllm`, `longrunAgent.teamorg.agents.assignagent`) "
        "to fulfill the user's request on the substrate. Always pick lightweight, "
        "cost-effective remote cloud models (e.g. `openrouter:deepseek/deepseek-reasoner`, "
        "`openrouter:z-ai/glm-5.3-flash`, `openrouter:meta/muse-spark-1.3-contributor`), "
        "never heavy local models, and draft clear, concise `ROLE.md` prompts."
    ),
    "models": (
        "You are `longrunAgent` automating the Settings ▸ Models & Routing section. "
        "Inspect with `longrunAgent.webui.inspect` (`section:'models'`) and apply updates "
        "with `longrunAgent.webui.configure` (`target:'routing'`). Prefer cheap remote models."
    ),
    "compaction": (
        "You are `longrunAgent` automating the Settings ▸ Compaction section. "
        "Inspect with `longrunAgent.webui.inspect` (`section:'compaction'`) and apply updates "
        "with `longrunAgent.webui.configure` (`target:'compaction'`)."
    ),
    "rules": (
        "You are `longrunAgent` automating the Rules section (`Global_rules.md` / `Project_rules.md`). "
        "Inspect with `longrunAgent.webui.inspect` (`section:'rules'`) and write updated rules "
        "with `longrunAgent.webui.configure` (`target:'rules'`)."
    ),
    "settings": (
        "You are `longrunAgent` automating a structured WebUI Settings section. "
        "Inspect with `longrunAgent.webui.inspect` (`section:'settings'`) and apply validated "
        "changes with `longrunAgent.webui.configure` (`target:'settings'`). Never touch "
        "safety checkboxes (`allow_nucleus_write`, `allow_matrix_promote`)."
    ),
    "subagents": (
        "You are `longrunAgent` automating the Settings ▸ Subagents panel. Inspect with "
        "`longrunAgent.webui.inspect` (`section:'subagents'`) and update with "
        "`longrunAgent.webui.configure` (`target:'subagents'`, values: model / fallbacks / "
        "max_parallel / max_depth / roles). Prefer cheap remote models; keep role briefs concise."
    ),
    "providers": (
        "You are `longrunAgent` automating the Settings ▸ Providers / Models roster. Inspect "
        "with `longrunAgent.webui.inspect` (`section:'providers'`) and change with "
        "`longrunAgent.webui.configure` (`target:'providers'`, action: upsert|remove|add_model|"
        "remove_model|default). Never read or write secret keys."
    ),
    "tools": (
        "You are `longrunAgent` automating the Settings ▸ Tools policy panel. Inspect with "
        "`longrunAgent.webui.inspect` (`section:'tools'`) and flip per-tool `enabled`/`approval` "
        "with `longrunAgent.webui.configure` (`target:'tools'`). You may NOT change any "
        "`longrunAgent.*` entry — that gate is operator-only."
    ),
    "skills": (
        "You are `longrunAgent` automating the Settings ▸ Skills panel. Inspect with "
        "`longrunAgent.webui.inspect` (`section:'skills'`) and remove an installed local skill "
        "with `longrunAgent.webui.configure` (`target:'skills'`, action:'remove'). Installing "
        "requires a zip upload and stays manual."
    ),
    "mcp": (
        "You are `longrunAgent` automating the Settings ▸ MCP panel. Inspect with "
        "`longrunAgent.webui.inspect` (`section:'mcp'`) and manage external servers with "
        "`longrunAgent.webui.configure` (`target:'mcp'`, action: upsert|remove|test|reload). "
        "Reference secrets by NAME (`${VAR}`), never by value."
    ),
    "knowledge": (
        "You are `longrunAgent` automating the Settings ▸ Knowledge panel. Inspect with "
        "`longrunAgent.webui.inspect` (`section:'knowledge'`) and manage notebooks/sources with "
        "`longrunAgent.webui.configure` (`target:'knowledge'`, action: notebook|source|clear|reembed)."
    ),
    "index": (
        "You are `longrunAgent` automating the Settings ▸ Codebase index configuration. Inspect "
        "with `longrunAgent.webui.inspect` (`section:'index'`) and update with "
        "`longrunAgent.webui.configure` (`target:'index'`)."
    ),
    "config": (
        "You are `longrunAgent` editing a raw `config/*.yaml` file through the Config-files panel. "
        "Inspect with `longrunAgent.webui.inspect` (`section:'all'`) and write with "
        "`longrunAgent.webui.configure` (`target:'config'`, file + text). Never name the "
        "operator-only safety switches (`allow_nucleus_write`, `allow_matrix_promote`)."
    ),
    "routing": (
        "You are `longrunAgent` automating the model ROUTING table (which model backs each "
        "role). Inspect with `longrunAgent.webui.inspect` (`section:'models'`) and update with "
        "`longrunAgent.webui.configure` (`target:'routing'`, `values:{'roles.<role>.model': ref}`). "
        "Prefer cheap remote models."
    ),
    "team_policy": (
        "You are `longrunAgent` re-applying the cheap remote model policy across Orbit teams. "
        "Inspect with `longrunAgent.webui.inspect` (`section:'teams'`) and apply with "
        "`longrunAgent.webui.configure` (`target:'team_policy'`, `team:'T1'` or `'ALL'`)."
    ),
    "harness": (
        "You are `longrunAgent` automating the Settings ▸ Harness / Sandbox runtime policy "
        "(`config/tools.yaml` ▸ runtime: keepgoing, verifier, best-of-n, difficulty, self-evolve, "
        "thinking effort, sandbox limits). Inspect with `longrunAgent.webui.inspect` "
        "(`section:'tools'`) and apply with `longrunAgent.webui.configure` (`target:'tools'`, "
        "`values:{runtime:{...}}`). You may NOT change any `longrunAgent.*` tool entry or the "
        "self-improvement policy that edits `src/longrun` — those are operator-only."
    ),
}

# Automate section -> `longrunAgent.webui.inspect` section, so the subscriber
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
    if not instruction:
        return {"ok": False, "error": "instruction required"}

    # Verify global tool enablement before launching
    probe_tool = ("longrunAgent.teamorg.teams.create"
                  if section in ("teamorg", "agents", "teams", "orbit")
                  else "longrunAgent.webui.configure")
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
        "Execute the required `longrunAgent.*` tool calls now, then conclude with `final`."
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
