#!/usr/bin/env python3
"""System prompt section registry (JAG-128A).

The prompt is NOT a monolith: it is an ordered list of sections. Each section is:
  - kind="static"  -> default text (default + overlay file, additive)
  - kind="dynamic" -> provider in code, generated at runtime (tools/skills/...)

Overlay file (ADDITIVE, not replacements):
  - global:   <config dir>/prompt.d/<NN>-<id>.md   (default ~/.longrun/config/)
  - project:  <data>/projects/<ws>-<sha>/prompt.d/<NN>-<id>.md
In case of CONTRADICTION the more specific level wins:
  PROJECT > GLOBAL > DEFAULT.
"""
import glob
import os

from longrun.util import paths

GLOBAL_DDIR = os.path.join(paths.config_dir(), "prompt.d")

# Section order and nature. A `<NN>-` prefix on a prompt.d addendum orders it.
#
# JAG-271/273/276 — CACHE-SAFE ORDERING (prefix caching). The provider/llama.cpp
# reuses the KV cache only up to the first byte that differs from the previous
# request, so STABLE content must come first. The system prompt is now 100% STATIC
# at the FRONT (JAG-276 moved the live task list OUT — it now rides in the last
# USER turn, see `server.state_block` / `assemble_turn`), so a change to any
# dynamic section (rules/skills/memory) only invalidates from that point on, and
# the volatile task list no longer invalidates the whole transcript. Rule of thumb:
# never put a timestamp / session id / live list in the EARLY sections — it would
# invalidate the whole prefix every turn.
SECTIONS = [
    {"id": "identity",      "order": 10, "kind": "static"},
    {"id": "prompt-map",    "order": 15, "kind": "static"},
    {"id": "rules-policy",  "order": 20, "kind": "static"},
    {"id": "security-policy", "order": 22, "kind": "static"},
    {"id": "skills-policy", "order": 25, "kind": "static"},
    {"id": "memory-policy", "order": 30, "kind": "static"},
    {"id": "capability",    "order": 40, "kind": "static"},
    {"id": "task-policy",   "order": 45, "kind": "static"},
    {"id": "self-summary",  "order": 50, "kind": "dynamic"},
    {"id": "agent-role",    "order": 52, "kind": "dynamic"},
    {"id": "longrun-agent", "order": 53, "kind": "dynamic"},
    {"id": "tools",         "order": 55, "kind": "dynamic"},
    {"id": "rules",         "order": 60, "kind": "dynamic"},
    {"id": "matrix",        "order": 62, "kind": "dynamic"},
    {"id": "skills",        "order": 65, "kind": "dynamic"},
    {"id": "memory",        "order": 80, "kind": "dynamic"},
]

# static sections whose defaults live in server.py (lazy import: no cycles)
_STATIC_ATTRS = {
    "identity": "SYSTEM_PROMPT",
    "rules-policy": "RULES_POLICY",
    "security-policy": "SECURITY_POLICY",
    "skills-policy": "SKILLS_POLICY",
    "memory-policy": "MEMORY_POLICY",
    "task-policy": "TASK_POLICY",
}


CAPABILITY_RULE = (
    "## Capability questions\n"
    "When the user asks about YOUR OWN capabilities \u2014 which tools you have, "
    "whether a tool exists, where your rules or memory live, what you can do \u2014 "
    "answer FROM YOUR PROMPT: the `Tool registry` block above, `self.info` (the tool `self`), or "
    "`skills.list` (skills{action:'list'}). NEVER run `shell.exec`/`git.run` (ls, find, git status) to answer a "
    "question about yourself: that inspects the machine, not you."
)


def _manifest_text():
    pretty = ", ".join("%s(%s)" % (s["id"], s["kind"]) for s in SECTIONS)
    return (
        "## How you are built (prompt map)\n"
        "Your system prompt is an ordered list of sections; some are generated at "
        "runtime, some are text you can EXTEND with files (adding, never replacing). "
        "In case of CONTRADICTION the more specific level wins: PROJECT > GLOBAL > DEFAULT.\n"
        "- global section addenda: %s/<NN>-<id>.md\n"
        "- project section addenda: %s/<ws-slug>/prompt.d/<NN>-<id>.md\n"
        "- sections: %s" % (GLOBAL_DDIR, paths.PROJECTS_DIR, pretty)
    )


def prompt_map_text():
    """Public wrapper: the prompt-map (manifest) section text."""
    return _manifest_text()


def capability_text():
    """Public wrapper: the capability rule section text."""
    return CAPABILITY_RULE


def project_ddir(ws):
    return os.path.join(paths.workspace_state_dir(ws), "prompt.d")


def _read(path):
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            return f.read().strip()
    except OSError:
        return ""


def _section_id(filename):
    stem = filename[:-3] if filename.endswith(".md") else filename
    head, sep, tail = stem.partition("-")
    if sep and head.isdigit():
        return tail
    return stem


def _addenda(base_dir):
    """{section_id: text} from the overlay files <NN>-<id>.md (alphabetical order)."""
    out = {}
    if not base_dir:
        return out
    for p in sorted(glob.glob(os.path.join(base_dir, "*.md"))):
        sid = _section_id(os.path.basename(p))
        if not sid:
            continue
        text = _read(p)
        out[sid] = (out[sid] + "\n" + text) if sid in out else text
    return out


def _static_text(sid):
    if sid == "capability":
        return CAPABILITY_RULE
    if sid == "prompt-map":
        return _manifest_text()
    from longrun.core import server
    return getattr(server, _STATIC_ATTRS.get(sid, ""), "") or ""


def section_texts(sess=None, ws=None, tool_ctx=None):
    """Per-section rendered text {id: text} (JAG-272: context accounting).

    Same assembly as `render_sections` but keyed by section id, so the Context
    panel can attribute REAL tokens to each part of the system prompt (the sum of
    the buckets then equals the measured context total).
    """
    g = _addenda(GLOBAL_DDIR)
    p = _addenda(project_ddir(ws)) if ws else {}
    out = {}
    for sec in sorted(SECTIONS, key=lambda s: s["order"]):
        sid = sec["id"]
        if sec["kind"] == "static":
            base = _static_text(sid)
        else:
            base = _PROVIDERS.get(sid, lambda *a: "")(sess, ws, tool_ctx)
        parts = [x.strip() for x in (base or "", g.get(sid, ""), p.get(sid, ""))
                 if x and x.strip()]
        out[sid] = "\n".join(parts)
    return out


def render_sections(sess=None, ws=None, tool_ctx=None):
    """Assemble the final prompt: for each section, default + global + project."""
    texts = section_texts(sess, ws, tool_ctx)
    parts_out = []
    for sec in sorted(SECTIONS, key=lambda s: s["order"]):
        text = texts.get(sec["id"])
        if text:
            parts_out.append(text)
    return "\n\n".join(parts_out)


def _provider_self_summary(sess, ws, ctx):
    try:
        from longrun.core import server
        return server.self_summary()
    except Exception:  # noqa: BLE001
        return ""


def _provider_role(sess, ws, ctx):
    """The AGENT identity + the session's ROLE.md — the `agent-role` section.

    JAG-294 added the per-session ROLE.md patch. JAG-362 harmonises the layers:
    a session DESIGNATED as an org agent always announces its identity here
    (``A#`` · name · the short roster label) and the ROLE.md text is appended
    when set. Before this the section was EMPTY for the ~90% of agents with no
    ROLE.md yet, so every agent looked identical to the model (and the agent's
    own name/label never reached the prompt at all).

    Layers, in prompt order: agent identity + ROLE.md (this section, order 52)
    then the standing rules (order 60: GLOBAL Global_rules.md + AGENTS.md, then the
    PROJECT Project_rules.md + rules/*.md + AGENTS.md — the project wins on conflict).
    """
    sid = (sess or {}).get("id") if isinstance(sess, dict) else sess
    if not sid:
        return ""
    who = ""
    try:
        from longrun.agent import agents
        rec = agents.REGISTRY.get(sid) or {}
        if rec.get("id"):
            who = "You are %s" % rec["id"]
            if rec.get("name"):
                who += " \u2014 %s" % rec["name"]
            if rec.get("role"):
                who += " (%s)" % rec["role"]
            who += "."
    except Exception:  # noqa: BLE001 — the prompt must never break the chat
        who = ""
    try:
        from longrun.orchestrate import roles
        text = roles.read(sid) or ""
    except Exception:  # noqa: BLE001
        text = ""
    if not who and not text:
        return ""
    out = "## Your role (%s)\n" % ("this agent" if who else "this session")
    if who:
        out += (who + " Hold this identity and the rules below for everything you "
                "do here.\n")
    else:
        out += ("Hold this role and these behaviour rules for everything you do "
                "here.\n")
    out += ("\n" + text) if text else "\n(No extra role text is set for this agent yet.)"
    # JAG-450: an ORCHESTRATOR (an agent with DIRECT REPORTS) must SEE its team and
    # know it can distribute work to it. Before this the master literally did not
    # know it had teammates, so it ran the whole job alone and never used the org
    # chart. The roster + the `dispatch` action make the team usable from chat.
    try:
        from longrun.agent import agents as _ag
        _rec = (_ag.REGISTRY.get(sid) if sid else None) or {}
        _aid = _rec.get("id")
        if _aid:
            _team = _ag.REGISTRY.team_of(_aid)
            _reports = [x for x in _ag.REGISTRY.list().get("agents", [])
                        if x.get("id") in _team and x.get("id") != _aid]
            if _reports:
                _lines = []
                for _r in _reports:
                    _lbl = _r.get("name") or _r.get("id")
                    _lbl += (" (%s)" % _r["role"]) if _r.get("role") else " (no role set)"
                    _lines.append("- %s \u2014 %s" % (_r.get("id"), _lbl))
                out += ("\n\n## Your team (org chart \u2014 rebuilt from live state every turn)\n"
                        "You are an ORCHESTRATOR. Your direct reports are:\n"
                        + "\n".join(_lines)
                        + "\nThis list is generated at prompt time from the SAME org "
                        "chart the UI shows, so adding, renaming, re-roling or "
                        "removing an agent appears here by itself: never keep your own copy of it, "
                        "and never assume a teammate is missing because this block is short.\n"
                        "DISTRIBUTE work: to hand a self-contained subtask to a "
                        'teammate, emit {"action":"dispatch","agent":"<A-id>",'
                        '"goal":"<the subtask>"} — it runs a REAL turn in that '
                        "teammate's own session (their role and model) and returns "
                        "their reply. Prefer dispatching parallelisable work to your "
                        "team over doing everything yourself. `agent.list` re-reads "
                        "the chart on demand (read-only, no grant required).")
    except Exception:  # noqa: BLE001 — the prompt must never break the chat
        pass
    return out


def _provider_tools(sess, ws, ctx):
    if ctx:
        return ctx
    try:
        from longrun.core import server
        return server._tool_context()
    except Exception:  # noqa: BLE001
        return ""


def _longrun_agent_tool_lines():
    """One `- name — first sentence` line per EXCLUSIVE subtool, from LIVE state.

    Read from the registry, never hardcoded: a new subtool shows up in the prompt
    the moment it is registered, so the agent can never be unaware of its own tools.
    """
    try:
        from longrun.tools import registry
        rows = [t for t in registry.catalog() if str(t.get("origin") or "") == "exclusive"]
    except Exception:  # noqa: BLE001 — the prompt must never break the chat
        return []
    out = []
    for t in sorted(rows, key=lambda r: str(r.get("name"))):
        desc = " ".join(str(t.get("description") or "").split())
        # One sentence, and never the boilerplate action-hint tail.
        head = desc.split(" This tool performs only")[0]
        if "." in head[:200]:
            head = head.split(". ")[0] + "."
        out.append("- `%s` — %s" % (t.get("name"), head[:240]))
    return out


def _provider_longrun_agent(sess, ws, ctx):
    """The `longrun-agent` section — longrunAgent's OWN namespace + hard rules.

    JAG-535: the permanent system agent had no idea it was the VEO or which
    exclusive subtools it owned (the generic Tool registry block is
    summarised and truncated). This section is generated from the live registry and
    injected only for the system session or for a session that was GRANTED
    `allow_longrun_agent`, so the surface is explicit and never drifts.
    """
    try:
        from longrun.agent import longrun_agent as lra
    except Exception:  # noqa: BLE001
        return ""
    sid = (sess or {}).get("id") if isinstance(sess, dict) else sess
    sid = str(sid or "").strip()
    is_system = sid == lra.LONGRUN_AGENT_SESSION_ID
    granted = bool(isinstance(sess, dict) and sess.get("allow_longrun_agent"))
    if not is_system and not granted:
        return ""
    lines = _longrun_agent_tool_lines()
    if not lines:
        return ""

    if is_system:
        intro = (
            "## You are longrunAgent (the VEO \u2014 \u201cburattinaio of agents\u201d)\n"
            "You are the harness's PERMANENT, UNDELETABLE, STATELESS system automation "
            "agent. You own the substrate: you act on the backend state, never on the "
            "graphical objects \u2014 the WebUI re-paints itself from the events your "
            "calls emit, so never try to \u201cclick\u201d or scrape the UI.\n"
            "Your exclusive tools use two-segment names `namespace.tool` "
            "(`agent.prompt_set`, `team.member_add`, `kb.notebook_add`) and these "
            "are ALL of them right now:\n"
        )
    else:
        intro = (
            "## longrunAgent namespace (granted to this session)\n"
            "You were granted access to the VEO's exclusive tools (`namespace.tool`, "
            "e.g. `agent.create`, `team.list`, `webui.configure`). Use them to "
            "manage the harness substrate; the WebUI re-paints "
            "itself from the events your calls emit. Available subtools:\n"
        )

    body = intro + "\n".join(lines) + "\n"
    body += (
        "\nHow to call them (enforced in code, not by you):\n"
        "- call a tool by its FULL dotted name and pass that OBJECT's own fields: every "
        "object has one tool per verb (`create`/`update`/`delete`/`get`/`list`), so there "
        "is no sub-operation to choose. An argument named `action` is RESERVED and "
        "never part of any schema \u2014 never send it: the verb is already in the "
        "tool name.\n"
        "- Dual permission: an exclusive call runs only when the tool is enabled "
        "in the global registry AND the calling session is `longrunAgent*` or carries "
        "`allow_longrun_agent`. Both halves are checked outside you \u2014 do not try to "
        "grant yourself access.\n"
        "- REFUSED, always: `allow_nucleus_write` / `allow_matrix_promote` (the human "
        "operator alone owns those checkboxes), any change to your own exclusive "
        "tool policy, and any edit of `src/longrun` or the self-improvement policy.\n"
        "- Nothing is remembered between runs: your transcript is reset before and "
        "after every automation turn, so plan from the live substrate you inspect, "
        "never from earlier context.\n"
    )
    try:
        cheap = ", ".join("`%s`" % m for m in lra.PREFERRED_CHEAP_MODELS[:4])
        body += ("- Cost: whenever you pick a model, prefer a cheap remote one (%s) and "
                 "NEVER a heavy local GGUF.\n" % cheap)
    except Exception:  # noqa: BLE001
        pass
    body += (
        "- Working rhythm: inspect the real state first (`webui.inspect` for any "
        "settings/config section; the `agent.*` / `team.*` tools are themselves the "
        "read+write path for agents and teams), apply the change, then report exactly "
        "what changed. You also own the semantic team icon+colour choice "
        "(`team.create` decides it from the palette \u2014 an explicit `symbol` "
        "still wins).\n"
    )
    return body


def _provider_rules(sess, ws, ctx):
    try:
        from longrun.memory import rules
        return rules.rules_prompt_block(ws=ws or rules.resolve_workspace(sess))
    except Exception:  # noqa: BLE001
        return ""


def _provider_matrix(sess, ws, ctx):
    try:
        from longrun.core import matrix
        return matrix.prompt_section_text(sess=sess, ws=ws)
    except Exception:  # noqa: BLE001
        return ""


def _provider_skills(sess, ws, ctx):
    try:
        from longrun.memory import skills
        # JAG-202: a SHORT orienting index (name + one-line description), not a
        # full dump. With 179 skills the old 8000-char block was truncated anyway
        # (~2/3 of the library invisible) and burned ~2k tokens of prompt for a
        # list the model cannot fully use. The `skills` tool now SEARCHES
        # (action:search) and lists on demand, so the always-on index stays small.
        return skills.skills_context(max_chars=2600)
    except Exception:  # noqa: BLE001
        return ""


# JAG-447: the memory section injected into every prompt is a BOUNDED INDEX, not
# a dump. Each line is truncated and the whole block is capped, so accumulated
# memory can never balloon the system prompt (the model recalls more on demand
# with the `memory` tool). This keeps the segregation below while staying within
# the same prompt budget as before.
_MEM_PROMPT_MAX = 800
_MEM_ITEM_CHARS = 120


def _provider_memory(sess, ws, ctx):
    """JAG-447: memory is injected in TWO segregated, clearly-labelled buckets —
    durable USER facts (``memory.store``) and SELF-distilled lessons
    (``agent.note``) — so neither the model nor a human reading the context can
    confuse what the user said with what the harness inferred on its own. The
    whole section is hard-bounded (``_MEM_PROMPT_MAX``).
    """
    parts = []
    try:
        from longrun.memory import memory

        def _items(kind, limit):
            out = []
            for r in memory.governed_query(kind=kind, limit=limit):
                c = " ".join(str(r.get("content", "")).split())
                if c:
                    out.append("- " + (c[:_MEM_ITEM_CHARS] + "…"
                                       if len(c) > _MEM_ITEM_CHARS else c))
            return out

        facts = _items("memory.store", 3)
        lessons = _items("agent.note", 5)
        if facts:
            parts.append("## Memory \u2014 user facts (told by the user; trust these)\n"
                         + "\n".join(facts))
        if lessons:
            parts.append("## Memory \u2014 self-distilled lessons (your own past "
                         "reflections; verify before relying)\n" + "\n".join(lessons))
        core = memory.core_read().strip()
        if core:
            parts.append("## Core memory (always visible \u2014 edit with "
                         "memory{action:'set_core'})\n" + core)
    except Exception:  # noqa: BLE001
        pass
    block = "\n\n".join(parts)
    if len(block) > _MEM_PROMPT_MAX:
        block = block[:_MEM_PROMPT_MAX] + "\n… [memory index truncated — use the `memory` tool to recall more]"
    return block


_PROVIDERS = {
    "self-summary": _provider_self_summary,
    "agent-role": _provider_role,
    "longrun-agent": _provider_longrun_agent,
    "tools": _provider_tools,
    "rules": _provider_rules,
    "matrix": _provider_matrix,
    "skills": _provider_skills,
    "memory": _provider_memory,
}

