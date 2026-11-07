#!/usr/bin/env python3
"""The ONE registry of WebUI surfaces an agent may write text for (K-1).

Before this module the per-surface prompt data lived in three dicts buried inside
`agent/longrun_agent.py` (`SECTION_PROMPTS`, `AUTOMATE_INSPECT_SECTIONS`,
`AUTOMATE_ALLOWED_SECTIONS`) and the *frontend* kept a second, narrower copy of the
allowlist. One fact lived in two places and the UI could drift from the server.

Here every surface carries the three things that must stay coherent:

* `system`  — the per-surface system prompt. THE hardcoded prompt data the operator
              asked to locate ("pay attentio on wher ethis hardocded prompt data").
* `ctx`     — the key of the CONTEXT GATHERER that feeds the model the live state of
              this exact surface (the chat's tail, the plan, the agent, the team…).
              A generator that does not know where it is writing cannot know what a
              correct value is.
* `role`    — the model policy: which routing role backs the generation. Two knobs
              only: a SESSION-SCOPED surface runs on THAT SESSION's own model (so a
              chat prompt is written by the model that already holds the chat's
              context), everything else on `roles.generate`.

Two kinds, because there are two genuinely different jobs:

* ``generate`` — ONE non-agentic completion returns TEXT for one field. It never
  writes: the operator reviews the draft in the field and saves (or sends). This is
  what an editable field needs, and it is why the composer can be served at all.
* ``automate`` — `longrun_agent.automate()` runs a stateless VEO turn that CHANGES
  the substrate through exclusive `namespace.tool` calls. Only surfaces the operator
  already edits by hand are allowed (`AUTOMATE_ALLOWED_SECTIONS`); runtime config is
  refused on purpose.

The registry is code-owned so it is testable and citable; `config/generate.yaml` may
override a surface's ``system`` text (prompt tuning without a code change and without
being able to break the feature's shape).
"""
import os
from dataclasses import dataclass, replace

# The kind values. A typo here is a silent hole, so they are named.
GENERATE = "generate"
AUTOMATE = "automate"

# Surfaces whose `generate` runs on the SESSION's own model and its live chat
# context, instead of `roles.generate`. One owner for that rule.
SESSION_ROLE = "chat"
DEFAULT_ROLE = "generate"


@dataclass(frozen=True)
class Surface:
    """One editable WebUI text surface an agent can be asked to write."""

    id: str                    # stable key used by the API and the frontend
    kind: str                  # GENERATE | AUTOMATE
    label: str                 # human name, shown in the control's tooltip
    system: str                # the per-surface system prompt (prompt data)
    ctx: str = ""              # context-gatherer key (generate) / inspect section
    role: str = DEFAULT_ROLE   # routing role that backs the model
    session_scoped: bool = False   # True -> that session's own model + chat context
    apply: str = "replace"     # replace | append (how the text reaches the field)
    inspect: str = ""          # AUTOMATE only: the `webui.inspect` section
    allowed: bool = False      # AUTOMATE only: may the VEO write this surface
    surfaces: tuple = ()       # >1 when one mount serves several ids (aliases)


# --------------------------------------------------------------------------
# AUTOMATE — stateless VEO turns that WRITE the substrate. The prompt text is
# carried over verbatim from `longrun_agent.SECTION_PROMPTS` so the behaviour of
# the existing control is unchanged; only its OWNER moved here.
# --------------------------------------------------------------------------
_AUTOMATE_PROMPTS = {
    "teamorg": (
        "You are `longrunAgent` (VEO, the burattino of agents), operating inside the "
        "Orbit Control / AGENTS & TEAMS panel. Use ONLY the exclusive object tools "
        "(`namespace.tool`) to fulfill the user's request on the substrate. Every "
        "object you can create, you can also read and remove: "
        "`team.create|update|delete|get|list|member_add|member_remove`, "
        "`agent.create|update|delete|get|list|prompt_set|prompt_get|prompt_clear`, "
        "`job.create|dispatch|delete|get|list`, "
        "`routine.create|update|delete|get|list`, "
        "`session.create|rename|delete` (the session TABLE is the builtin "
        "`sessions.list`). "
        "Always pick lightweight, cost-effective remote cloud models (e.g. "
        "`openrouter:deepseek/deepseek-v4.1-flash`, `deepseek:deepseek-flash`, "
        "`openrouter:z-ai/glm-5.3-flash`, "
        "`openrouter:meta/muse-spark-1.3-contributor`), never heavy local models, and "
        "draft clear, concise `ROLE.md` prompts.\n"
        "THREE RULES GOVERN WHAT YOU MAY TOUCH (the UI sends them in the context "
        "block; obey them literally):\n"
        "1. SCOPE. `context.team_scope` and `context.scope_agents` are your whole "
        "world: `ALL` = every designated agent, `__none__` = the agents that belong "
        "to NO team, otherwise only the members of that team. NEVER write to an "
        "agent outside the scope — not its prompt, not its reporting line, nothing.\n"
        "2. PROMPTS. When `context.only_empty` is true, write a `ROLE.md` "
        "(`agent.prompt_set`) ONLY for agents whose snapshot shows an empty prompt "
        "(`prompt_chars == 0`): an existing prompt is the operator's text and you "
        "must never overwrite it. When it is false you MAY rewrite the prompts of "
        "the agents in scope. Either way, one prompt per agent, no placeholders.\n"
        "3. RELATIONS, NOT MODELS. You MAY set an agent's `reports_to` ("
        "`agent.update`) to fix the org chart of the agents in scope, but never "
        "create a cycle and never point at an agent outside the scope. You must "
        "NEVER change an agent's model — routing is the operator's decision.\n"
        "Report at the end which agents you wrote, and nothing else."
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
        "`webui.inspect` (`section:'knowledge'`). CREATE through the builtin "
        "`knowledge.create_notebook` / `knowledge.add_source` (they are not VEO "
        "privileges), and use the exclusive verbs only for what the builtin tool "
        "cannot do: `kb.notebook_rename|delete`, `kb.source_remove`, `kb.reembed`."
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

# AUTOMATE section -> `webui.inspect` section, so the snapshot injected into the goal
# is never empty for a valid request.
_AUTOMATE_INSPECT = {
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
_AUTOMATE_ALLOWED = ("rules", "teamorg", "agents", "teams", "orbit")
# The aliases are the SAME job as `teamorg` (the Orbit deck) spelled its way; they
# exist so a client that calls the deck's own name is not refused.
_AUTOMATE_ALIASES = {"agents": "teamorg", "teams": "teamorg", "orbit": "teamorg"}


# --------------------------------------------------------------------------
# GENERATE — one completion returns TEXT for one field. The system prompt states
# WHAT the field is, WHAT a good value looks like, that the context is real, and
# that the reply must be ONLY the text (no preamble, no quotes, no code fence) —
# anything else gets inserted into the field verbatim.
# --------------------------------------------------------------------------
_BARE = ("\nReply with ONLY the text for the field: no preamble, no explanation, no "
         "quotes and no markdown fence. Write in the same language as the context "
         "when it has one, otherwise in English.")

_GENERATE_PROMPTS = {
    "chat.prompt": (
        "You write the text of THIS chat's composer. The CURRENT CONTENT OF THE FIELD "
        "decides the job, and you never mix the two."
        " EMPTY field and NO conversation yet: write a short OPENING message that asks "
        "the operator what they want to work on — never assume or name a project, "
        "folder or repository."
        " EMPTY field but the conversation has turns: write the NEXT message that moves "
        "the work forward — ask for the missing decision, or restate the next step "
        "concretely. Keep it short (1-3 sentences) and specific to what is actually open."
        " FILLED field: OPTIMIZE the operator's draft. That text is what the operator "
        "wants to say, so keep its intent, its language and every fact it states. Rewrite "
        "it as the COMPLETE, implementation-ready instruction behind it: fix spelling, "
        "grammar and ambiguity, then spell out the requirements the draft already "
        "implies — the concrete changes to make, the behaviour that must keep working, "
        "and how the result is proven done. A one-clause draft usually hides several "
        "requirements: name them all, in 2-5 sentences or a short numbered list. "
        "Overlap with the draft is intended (the rewrite REPLACES it, never appends only "
        "the missing parts). Add nothing the draft or the context does not support — no "
        "new features, names, paths or numbers."
        " Never answer the draft, never explain what you changed, never invent facts "
        "that are not in the context." + _BARE
    ),
    "goal.objective": (
        "You write the OBJECTIVE of a durable goal for this session — the outcome to "
        "reach, in the operator's words. The CURRENT CONTENT OF THE FIELD decides the job."
        " EMPTY field: use the chat's context (recent turns, the task list, the workspace) "
        "to state a concrete, checkable RESULT — an outcome, not a process."
        " FILLED field: REORGANIZE that text — same intent, different order. Keep its "
        "language and every fact it states, fix spelling and ambiguity, put the outcome "
        "first and the constraints after it, and make each clause verifiable by looking "
        "at the workspace. Overlap with the draft is intended (the rewrite REPLACES it); "
        "add nothing the draft or the context does not support — no new features, names, "
        "paths or numbers."
        " One paragraph, at most two." + _BARE
    ),
    "plan.input": (
        "You write ONE step of this session's task graph. The CURRENT CONTENT OF THE FIELD "
        "decides the job."
        " EMPTY field: use the chat's context and the steps already present — the step "
        "must be ONE concrete action that is not already listed, phrased so its completion "
        "can be checked against an artefact."
        " FILLED field: REORGANIZE that text into ONE step — keep its intent and every "
        "fact it states, fix spelling and grammar, drop what is not actionable, and put "
        "the checkable result on the same line. Overlap is intended (the rewrite REPLACES "
        "it); never split it into several steps and never add a fact the draft does not "
        "have."
        " One line." + _BARE
    ),
    "rules.global": (
        "You write one paragraph of the operator's GLOBAL rules for this harness — "
        "standing instructions that hold across every project. The context shows the "
        "rules that already exist: add a rule that is missing and does not duplicate "
        "them. Imperative, testable, no fluff." + _BARE
    ),
    "rules.project": (
        "You write one paragraph of this PROJECT's rules — instructions that hold only "
        "in this workspace. The context shows the existing project and global rules: "
        "add what is missing without duplicating them. Imperative and specific to the "
        "project's real stack." + _BARE
    ),
    "agent.role": (
        "You write the ROLE.md of ONE agent of this team: who it is, what it owns, and "
        "how it reports. The context gives the agent's name, role, model, its team and "
        "its reporting line, plus its current prompt. Write a concise, non-overlapping "
        "brief (120-200 words) that fits that position; never assign a model." + _BARE
    ),
    "subagent.brief": (
        "You write the brief of ONE subagent role: what kind of work it receives and "
        "the standard it must meet. The context names the role, its model and the "
        "other roles. Keep it under 60 words, imperative, and non-overlapping." + _BARE
    ),
    "subagent.new": (
        "You design ONE NEW subagent role for this harness. The context lists every "
        "role that ALREADY exists with its brief: the new role must fill a gap those "
        "roles do not cover, and its name must differ from all of them. Consider what "
        "work this operator actually delegates (the existing briefs are the evidence) "
        "and write the role they are still missing. Reply with ONE JSON object and "
        "nothing else — no preamble, no fence:\n"
        '{"name": "<slug>", "brief": "<under 60 words, imperative, self-contained>"}\n'
        "`name` is a slug: lowercase letters, digits and single hyphens, 2-24 chars. "
        "`brief` says what work the role receives and the standard it must meet; it "
        "must not restate another role's brief. Never invent a model or a tool list."
    ),
    "compaction.instruction": (
        "You write the instruction of the context COMPACTOR: what a summary of a long "
        "chat must preserve so the work can continue. The context shows the current "
        "instruction. Write 2-4 sentences naming what must never be lost." + _BARE
    ),
    "session.title": (
        "You write a chat title: at most 5 words, no punctuation at the end, naming "
        "the actual subject of this conversation. The context is the chat's first "
        "exchange and its workspace." + _BARE
    ),
    "team.description": (
        "You write the description of one team. The context names the team and lists "
        "its members with their roles. One sentence saying what the team is for; it is "
        "also used to pick the team's icon, so name the domain." + _BARE
    ),
    "kb.notebook": (
        "You write the name of a knowledge notebook: 2-5 words naming the subject it "
        "will collect. The context lists the notebooks that already exist — do not "
        "duplicate one." + _BARE
    ),
    "memory.content": (
        "You write ONE distilled lesson to store in long-term memory: a durable fact "
        "or rule learned from the context, phrased so it is useful in a future session. "
        "One or two sentences. The context shows the memories that already exist — do "
        "not duplicate one." + _BARE
    ),
    "blackboard.topic": (
        "You write the CONTENT of one blackboard entry for the agent team: a short, "
        "self-contained note the other agents need. The context gives the topic, the "
        "author and the recent entries. 2-4 sentences, factual, no restating the "
        "topic." + _BARE
    ),
    "routine.goal": (
        "You write the goal of a recurring routine: what the agent must produce each "
        "time it fires. The context names the routine and the team. One sentence with "
        "a checkable outcome." + _BARE
    ),
    "job.goal": (
        "You write the goal of a job to dispatch to a teammate: the deliverable, not "
        "the process. The context names the job and the available agents with their "
        "roles. One or two sentences, addressed to that agent." + _BARE
    ),
}


# A rule is ADDED to a file, never swapped in: these two surfaces append to the field
# so a draft can never silently delete the rules already written next to it.
_APPEND = ("rules.global", "rules.project")
#: RH-18: the reply is ONE JSON object that fills SEVERAL fields, not text for one
#: field. The client reads this from `GET /api/generate/surfaces` and parses it; a
#: surface listed here must say so in its own prompt.
_JSON = ("subagent.new",)


def _build():
    """Assemble the registry — one entry per surface, plus the automate aliases."""
    out = {}

    for sid, prompt in _AUTOMATE_PROMPTS.items():
        out[sid] = Surface(
            id=sid, kind=AUTOMATE, label="Settings ▸ " + sid if sid != "teamorg"
            else "Agents & Teams",
            system=prompt, inspect=_AUTOMATE_INSPECT.get(sid, "all"),
            allowed=sid in _AUTOMATE_ALLOWED,
        )
    # The aliases are not separate surfaces: they resolve to `teamorg` and exist only
    # so `automate()`'s allowlist keeps its published spelling.
    for alias, target in _AUTOMATE_ALIASES.items():
        base = out[target]
        out[alias] = replace(base, id=alias, surfaces=(alias, target), allowed=True)

    for sid, prompt in _GENERATE_PROMPTS.items():
        scoped = sid.startswith("chat.") or sid in (
            "goal.objective", "plan.input", "memory.content", "session.title")
        out[sid] = Surface(
            id=sid, kind=GENERATE, label=sid.replace(".", " · "), system=prompt,
            ctx=sid, role=SESSION_ROLE if scoped else DEFAULT_ROLE,
            session_scoped=scoped, apply=("append" if sid in _APPEND else
                                          "json" if sid in _JSON else "replace"),
        )
    return out


SURFACES = _build()

# ---------------------------------------------------------------- compat views --
#
# `longrun_agent` and its tests read these three names. They are DERIVED from the
# registry above, so the prompt data and the gating have exactly one owner; the
# names stay valid for their callers.
SECTION_PROMPTS = {sid: s.system for sid, s in SURFACES.items() if s.kind == AUTOMATE}
AUTOMATE_INSPECT_SECTIONS = {sid: s.inspect for sid, s in SURFACES.items()
                             if s.kind == AUTOMATE}
AUTOMATE_ALLOWED_SECTIONS = tuple(_AUTOMATE_ALLOWED)


def resolve(surface_id):
    """The surface for an id, accepting an automate alias — None when unknown."""
    sid = str(surface_id or "").strip()
    if not sid:
        return None
    return SURFACES.get(sid) or SURFACES.get(_AUTOMATE_ALIASES.get(sid, ""))


# ------------------------------------------------------------------- overrides --
#
# `config/generate.yaml` may override a surface's `system` text, so a prompt can be
# tuned without a code change. Only the TEXT is overridable: the shape (kind, role,
# context, apply) stays code-owned, so a bad YAML can never make the control write
# where it must not.
_OVERRIDE_FILE = "generate.yaml"


def overrides(reload=False):
    """`{surface_id: system_text}` from `config/generate.yaml` (never raises)."""
    try:
        from longrun.core import configfiles
        got = configfiles.read_file(_OVERRIDE_FILE) or {}
        if not got.get("ok"):
            return {}
        import yaml
        data = yaml.safe_load(got.get("text") or "") or {}
        sur = data.get("surfaces") if isinstance(data, dict) else None
        if not isinstance(sur, dict):
            return {}
        out = {}
        for sid, entry in sur.items():
            if isinstance(entry, dict) and str(entry.get("system") or "").strip():
                out[str(sid)] = str(entry["system"])
        return out
    except Exception:  # noqa: BLE001 — a bad override must never break the feature
        return {}


def registry(public_only=True):
    """The surfaces the UI renders — the single list the frontend reads.

    `public_only` drops the automate aliases (they are the same surface under the
    deck's own spelling and must not become a second button). The prompt TEXT is not
    shipped: the browser only needs to know WHICH surfaces exist and how to render the
    control; the prompts stay server-side.
    """
    out = []
    for sid, s in SURFACES.items():
        if public_only and len(s.surfaces) > 1:
            continue
        out.append({
            "id": s.id, "kind": s.kind, "label": s.label, "apply": s.apply,
            "session_scoped": s.session_scoped,
        })
    return out
