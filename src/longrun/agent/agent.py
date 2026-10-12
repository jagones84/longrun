"""The agent core — prompts, the chat loop and the multi-step agent run.

Owns the system / planner / harness prompts and their assembly (`system_prompt`,
`rules_context`, `harness_wrap`, `assemble_turn`), the single-shot chat turn
(`chat_once`), the plan generator (`generate_plan`) and the autonomous multi-step
loop with its tools (`agent_run`, `apply_agent_action`), plus the todo / offload /
reflection / pivot helpers. Extracted from ``server.py`` (JAG-380).

It reaches back into ``server`` for the five app-level names it does not own —
``VERSION``, ``stream_with_fallback`` and the prompt/context helpers
``_system_prompt`` / ``_tool_context`` / ``context_display`` (the latter three live
in ``httpapi`` and are re-exported by ``server``). They are read through the module
object (``server.<name>``) so test monkeypatches on ``server.<name>`` keep taking
effect. Everything else is stdlib or a sibling module.
"""
import base64
import json
import mimetypes
import os
import re
import time
import uuid

from longrun.core import api_v02
from longrun.util import osutil
from longrun.model import routing
from longrun.plan import taskgraph
from longrun.core import server
from longrun.core.events import publish
from longrun.util.paths import DATA_DIR, SESSIONS_DIR, WEBUI_DIR
from longrun.util.paths import REPO_ROOT as REPO
from longrun.model.rllm import ROUTER_BASE, _router_stream, context_budget, default_model
from longrun.model.rllm import model_supports_vision
from longrun.util.steering import _is_aborted, drain_steer, has_steer
from longrun.util.fswrite import write_json
from longrun.memory.stores import (_chat_workspace, _store_path, _tool_event,
                     append_message, load_plan, load_tasks, persist_inject,
                     persist_tool_card, save_plan, save_session, save_tasks)
from longrun.util.textkit import extract_json
from longrun.util.tracing import RunTrace, _REAL_CACHED_TOKENS, _REAL_PROMPT_TOKENS


# ------------------------------------------------------------- agent core ----

SYSTEM_PROMPT = (
    "You are Longrun, the reasoning core of a frontier-style agent harness "
    "running locally on a DGX Spark (GB10, ARM64, unified memory) behind a "
    "llama.cpp router. Be direct, concrete and useful. When asked to plan or "
    "act, produce compact, actionable output."
)

# JAG-159: the PMCP gateway block is injected only when a `pmcp` MCP client is
# actually configured — a clone without it must not advertise tools it lacks.
PMCP_PROMPT = (
    "\n\n## MCP gateway (PMCP)\n"
    "Besides your native tools you can reach ~140 downstream MCP servers through "
    "the PMCP gateway (tools named `pmcp__gateway.*`). To use a capability you do "
    "not have natively:\n"
    "1. `pmcp__gateway.catalog_search` {query} - find the server/tool for a task.\n"
    "2. `pmcp__gateway.describe` {tool_id} - get the exact arguments.\n"
    "3. `pmcp__gateway.invoke` {tool_id:\"server::tool\", arguments:{...}} - run it.\n"
    "Downstream servers are lazy: `invoke` starts them on its own, so NEVER call "
    "`connect_server` first and never assume a server is offline. `invoke` is "
    "approval-gated, so prefer your native tools/skills for local work and use the "
    "gateway only when a capability is genuinely missing. A tool_id is prefixed by "
    "the server name, e.g. `core-time::get_current_time`."
)


def system_prompt():
    """Base system prompt, plus the PMCP block only if a `pmcp` client exists."""
    try:
        from longrun.interop import mcp_client
        if "pmcp" in (mcp_client.get_manager().status().get("clients") or {}):
            return SYSTEM_PROMPT + PMCP_PROMPT
    except Exception:  # noqa: BLE001 — never break the prompt
        pass
    return SYSTEM_PROMPT

# JAG-114/125: standing rules — global (user) + project (workspace), AGENTS.md-style.
# The actual file paths are rendered by rules.rules_prompt_block (below), so the
# model always knows WHERE its instructions live and can read/edit them.
RULES_POLICY = (
    "## Rules (global + project)\n"
    "Your standing rules are FILES on disk (paths given below): a GLOBAL file for "
    "every project and a PROJECT file for the current workspace, each also "
    "loading its scope's AGENTS.md (additive, not a fallback). GLOBAL rules come "
    "from your user config; PROJECT rules override global ones on conflict. "
    "Follow them; if a rule conflicts with the "
    "user's explicit request in this turn, say so before proceeding."
)


def rules_context(sess=None, ws=None):
    """JAG-114/115/125: rules block for the prompt, ALWAYS carrying the paths.

    `ws` (or the session's own workspace) selects the project; without either the
    global default workspace is used. Uses `rules_prompt_block` (never empty) so
    the model always sees where the global/project rules and their AGENTS.md
    additions (also loaded, additive) live — not just their text.
    """
    try:
        from longrun.memory import rules as rules_mod
        return rules_mod.rules_prompt_block(ws=ws or rules_mod.resolve_workspace(sess))
    except Exception:  # noqa: BLE001 — rules must never break a prompt
        return ""

PLANNER_PROMPT = (
    "You are the planner module of the Longrun harness. Break the goal into "
    "3-7 concrete strategy steps. Respond with ONLY a JSON array, each item "
    '{"title": "<short step>", "detail": "<one sentence>"}'
)

# JAG-73: make the memory store explicit and actionable. Before this the agent
# had no tool to remember/recall (the store was passive), and the prompt never
# said memory existed or WHEN to use it.
MEMORY_POLICY = (
    "Memory: you have a persistent memory store seeded across sessions (the "
    "`memory` tool; also GET /api/memory). Relevant past memories are "
    "AUTO-INJECTED below as 'Relevant memories from previous sessions' when they "
    "match the current message. Use it deliberately:\n"
    "- to REMEMBER: call memory{action:'store', content:'...'} as soon as you "
    "learn a durable fact — a user preference, a decision and its reason, a "
    "project convention, the fix for a bug. Keep it short and self-contained.\n"
    "- to RECALL: call memory{action:'recall', query:'...'} whenever the user "
    "refers to earlier work or you are missing context; memory{action:'recent'} "
    "shows the newest notes.\n"
    "- CORE (always visible): keep a compact, living CORE block of durable facts "
    "— user preferences, project conventions, key decisions. Read it with "
    "memory{action:'core'} and REWRITE it with memory{action:'set_core', "
    "content:'...'} whenever it changes; it is injected into every prompt, so "
    "keep it short and current.\n"
    "Never store ephemeral chatter, and never store secrets."
)

# JAG-79: the model knew the `skills` TOOL existed but the system prompt never
# told it WHICH skills are installed, so it never used them (e.g. superpowers,
# brainstorming, tdd). We now inject the live skills list + this directive.
# JAG-80: how long a chat turn waits for a human approval before moving on.
# The gate's own timeout is 300s (approvals.timeout_secs) — waiting that long in
# the chat stream was experienced as "si blocca" and let mobile NAT kill the SSE.
CHAT_APPROVAL_WAIT = 30

# JAG-375: the steer/abort inboxes moved to `steering.py` (imported above).

SKILLS_POLICY = (
    "Skills: you have an installed skill library — the SKILLS list below is "
    "live and includes all symlinked distributions. Before solving a task, SCAN "
    "it: if a skill matches (e.g. using-superpowers, brainstorming, "
    "writing-plans, tdd, systematic-debugging, research, mcp-builder, "
    "code-review), LOAD it with the `skills` tool "
    '({\"action\":\"read\",\"name\":\"<name>\"}) and FOLLOW its instructions '
    "step by step instead of improvising. Use {\"action\":\"list\"} for the "
    "full list with descriptions; if the list is long or truncated, SEARCH it "
    'with {"action":"search","query":"..."} and read the best match.'
)


def self_summary():
    """Compact self-knowledge block injected into the system prompt (v0.5)."""
    return (
        "Self-knowledge: you are Longrun v0.6, a local agent harness installed "
        "at the repo path %s on this DGX Spark. Data dir: %s. Tool policy: "
        "config/tools.yaml; model routing: config/routing.yaml; external MCP "
        "servers: config/mcp_clients.yaml (add a stdio command or HTTP url entry, "
        "tools appear as <client>__<tool>; then reload via POST /api/tools or "
        "restart with %s, unit file "
        "deploy/longrun.service, port 8790). Skills: the `skills` tool lists and "
        "reads agent skills from skills/<category>/<name>/SKILL.md. Harness-"
        "native tools: "
        "registry.TOOL_SCHEMAS + tools.py. Full self report: GET /api/self or "
        "the `self` tool."
    ) % (REPO, DATA_DIR, osutil.service_hint())


def self_knowledge():
    """Full self report: paths, config, docs, service state, extension recipe."""
    import subprocess as sp
    info = {
        "name": "Longrun", "version": server.VERSION,
        "repo_path": REPO, "data_dir": DATA_DIR, "sessions_dir": SESSIONS_DIR,
        "webui": WEBUI_DIR,
        "entrypoint": os.path.join(REPO, "server.py"), "port": 8790,
        "router": ROUTER_BASE,
        "config": {"tools": os.path.join(REPO, "config", "tools.yaml"),
                   "routing": os.path.join(REPO, "config", "routing.yaml"),
                   "mcp_clients": os.path.join(REPO, "config", "mcp_clients.yaml")},
        "docs": {"plan": os.path.join(REPO, "docs", "PLAN.md"),
                 "readme": os.path.join(REPO, "README.md"),
                 "architecture": os.path.join(REPO, "docs", "ARCHITECTURE.md")},
        "service": {"unit": "longrun.service", "scope": "user",
                    "unit_file": os.path.join(REPO, "deploy", "longrun.service"),
                    "restart_cmd": osutil.service_hint()},
        "skills_dir": os.path.join(REPO, "skills"),
        "install_skill": (
            "A skill is a directory with a SKILL.md. Drop/clone it into a "
            "category under skills/ (e.g. skills/ops/<name>/SKILL.md), or symlink "
            "an existing distribution dir: `ln -sfn <source-dir> skills/<cat>`. "
            "Skills are picked up automatically by the `skills` tool (no reload "
            "needed). External MCP servers: add an entry to "
            "config/mcp_clients.yaml with either command+args (stdio) or url "
            "(HTTP); tools are discovered via tools/list and exposed as "
            "<client>__<tool> in the registry. Harness-native tools go in "
            "registry.TOOL_SCHEMAS + tools.py with policy in config/tools.yaml. "
            "Apply with POST /api/tools (reload) or restart: %s."
        ) % osutil.service_hint(),
    }
    try:
        from longrun.memory import skills as skills_mod
        sk = skills_mod.list_skills()
        info["skills"] = {"dir": info["skills_dir"], "count": len(sk),
                          "categories": sorted({s["category"] for s in sk})}
    except Exception as e:  # noqa: BLE001
        info["skills"] = {"error": str(e)}
    try:
        if osutil.IS_POSIX:
            out = sp.run(["systemctl", "--user", "is-active", "longrun.service"],
                         capture_output=True, text=True, timeout=4).stdout.strip()
            info["service"]["active"] = out or "unknown"
        else:
            info["service"]["active"] = "n/a (no systemd on this host)"
    except Exception:
        info["service"]["active"] = "unknown"
    return info


def context_summary(session_id=None, graph_key=None):
    """Harness state injected into EVERY prompt.

    JAG-63: the persistent task list (the graph) is the single TODO the model
    owns. It is re-injected on every turn, so the model never forgets it across
    compaction or restarts. The old parallel `tasks.json` board is no longer
    injected here (it was the source of the "graph vs todo" confusion).

    JAG-276: `state_block` wraps this and injects it into the CURRENT user turn
    (not the system prompt) so the system prompt + transcript stay cache-stable.
    """
    lines = []
    key = graph_key or session_id
    g = None
    if key:
        try:
            g = taskgraph.load(key)
        except Exception:  # noqa: BLE001 — context must never break a turn
            g = None
    if g:
        todos = taskgraph.render_todos(g, compact=True)
        if todos:
            lines.append(todos)
    return "\n".join(lines) if lines else "(no task list yet)"


def state_block(session_id=None, graph_key=None):
    """The live task list, to inject INTO the current USER turn (JAG-276).

    JAG-276 (cache): this block used to be the LAST section of the SYSTEM prompt.
    Any task-list change therefore invalidated the KV prefix FROM THERE ON — i.e.
    the whole transcript had to be recomputed every turn. Putting it in the LAST
    user message (which changes every turn anyway) keeps the system prompt + the
    committed transcript byte-stable, so llama.cpp reuses the prefix cache. This is
    the Claude-Code pattern. Mirrored by `assemble_turn` and `context_usage`.
    """
    return ("Harness state (your persistent task list):\n"
            + context_summary(session_id=session_id, graph_key=graph_key))


def start_run_graph(run_id, goal, session_id=None, model=None, on_event=None,
                    cancel=None):
    """v0.6 — first action of a run: model-generated write_todos → live graph.

    The graph is bound to run_id + session_id and every node lands on the feed as
    a `graph.node.added` event the moment the model emits it. `cancel` (JAG-197)
    makes the planner call abortable.
    """
    try:
        return taskgraph.generate_from_model(run_id, goal, session_id=session_id,
                                             model=model, on_event=on_event,
                                             cancel=cancel)
    except Exception as e:  # noqa: BLE001 — graph must never break the run
        publish("graph.error", run=run_id, error=str(e))
        return taskgraph.ensure(run_id, session_id, goal), []


def finish_run_graph(run_id, session_id, goal, on_event=None):
    """Run end — close every still-open node with evidence (acceptance: all done)."""
    try:
        g = taskgraph.load(run_id)
        if not g or not g.get("nodes"):
            return None
        closed = taskgraph.finalize(g, "run %s completed: %s" % (run_id, str(goal)[:200]))
        payload = {"run": run_id, "session": session_id,
                   "nodes": len(g.get("nodes", [])), "closed": len(closed)}
        (on_event or publish)("graph.finalized", **payload)
        return g
    except Exception as e:  # noqa: BLE001
        publish("graph.error", run=run_id, error=str(e))
        return None


def graph_post(run_id, body):
    """POST /api/runs/<id>/graph/nodes — add / cancel / update / complete / replan.

    Returns (payload, error, code). Evidence is mandatory to move a node to done.
    """
    action = str(body.get("action") or "add").lower()
    source = body.get("source", "operator")
    g = taskgraph.load(run_id)
    if g is None:
        # JAG-215: an OPERATOR "add node" on a session that has no graph yet must
        # CREATE it. The WebUI Plan panel's "+" was silently writing to the dead
        # legacy /api/tasks board for a fresh session, so the node vanished.
        # Other actions still require an existing graph.
        if action in ("add", "node"):
            g = taskgraph.ensure(run_id)
        else:
            return None, {"error": "graph not found for run %s" % run_id}, 404
    try:
        if action in ("add", "node"):
            node = taskgraph.add_node(g, body.get("label") or body.get("title"),
                                      deps=body.get("deps"), status=body.get("status", "todo"),
                                      evidence=body.get("evidence"), source=source)
            return node, None, 200
        if action in ("cancel", "remove", "delete"):
            return taskgraph.cancel_node(g, body.get("id")), None, 200
        if action == "complete" or action == "done":
            return taskgraph.complete_node(g, body.get("id"), body.get("label"),
                                           evidence=body.get("evidence"), source=source), None, 200
        if action == "update":
            return taskgraph.update_node(g, body.get("id"), status=body.get("status"),
                                         label=body.get("label"), deps=body.get("deps"),
                                         evidence=body.get("evidence"), source=source), None, 200
        if action == "replan":
            added = taskgraph.replan_from_model(g, body.get("note") or body.get("goal"),
                                                body.get("model"))
            # JAG-274: announce on the feed so the WebUI can refresh the Plan panel
            # AND show the replan in the chat. We deliberately do NOT inject a chat
            # turn here (the operator chose "update + show only"): the model already
            # owns replan/continue as its OWN tools (replan_todos + the keepgoing
            # loop), and it picks up the new list on its next turn via `state`.
            try:
                publish("graph.replanned", run=run_id, session=g.get("session_id"),
                        added=[n["id"] for n in added],
                        labels=[n["label"] for n in added],
                        nodes=len(g.get("nodes", [])))
            except Exception:  # noqa: BLE001
                pass
            return {"added": [n["id"] for n in added], "added_labels": [n["label"] for n in added],
                    "nodes": len(g.get("nodes", []))}, None, 200
    except ValueError as e:
        return None, {"error": str(e)}, 400
    except KeyError as e:
        return None, {"error": str(e).strip("'\"")}, 404
    return None, {"error": "unknown action %r" % action}, 400


CHAT_TOOL_MAX_STEPS = int(os.environ.get("LONGRUN_CHAT_TOOL_STEPS", "8"))
# JAG-84: hard cap on TOTAL loop iterations (bookkeeping + retries included), so
# that making plan/todo actions "free" can never spin the loop forever.
# JAG-164: the iters cap must NOT preempt the continuation loop — with the tool
# budget now refilled per keepgoing round (<= keepgoing_max rounds, default 8)
# the real governors are keepgoing.decide + the wall-clock budget; this is only a
# runaway backstop.
CHAT_TOOL_MAX_ITERS = int(os.environ.get("LONGRUN_CHAT_TOOL_ITERS", "64"))
# JAG-344: a PLAN-ONLY turn (the job coordinator's decomposition turn). The master
# MAY inspect the workspace and record its own todo plan, but it MUST NOT execute
# the teammates' work: left with the full budget + the keepgoing continuation loop,
# a capable master completed the WHOLE job itself in its planning turn (it wrote the
# deliverable files and "verified" them), bypassing the team. A plan turn is capped
# to a few real tool steps and NEVER continues past them (see `plan_only` below).
PLAN_ONLY_MAX_STEPS = int(os.environ.get("LONGRUN_PLAN_TOOL_STEPS", "3"))
# JAG-344: the tools a PLAN-ONLY turn may still call — INSPECTION only. Everything
# else (shell, fs.write, fs.edit, subagent, improve, …) is refused, so the master can
# read the workspace and consult a skill to inform its plan but CANNOT execute the
# teammates' work instead of delegating it (the SEVERE "master did the whole job").
PLAN_ONLY_TOOLS = {"fs.read", "skills", "memory", "self"}
# JAG-256: the assembled system prompt is published as a collapsed "system" inject
# so the operator can read it. Publishing it EVERY turn spammed the transcript with
# N identical blocks (reported as "the harness re-sends the system prompt ad
# infinitum"). Keep the last hash per session; re-publish only when it changes.
_LAST_SYS_INJECT = {}
# JAG-88 (harness layer L2 — context budgeting): observations above this many
# chars are offloaded to a file instead of being flooded into the context (and
# instead of the old silent 4000-char truncation that LOST the rest).
CHAT_TOOL_OBS_LIMIT = int(os.environ.get("LONGRUN_TOOL_OBS_LIMIT", "6000"))
# JAG-189: how long the chat loop waits for a delegated subagent before giving up
# (the child runs its own bounded agent loop; a chat turn must not hang forever).
SUBAGENT_WAIT = int(os.environ.get("LONGRUN_SUBAGENT_WAIT", "180"))
# JAG-181: the chat loop feeds the FULL tool output to the harness budgeter
# (_offload_observation), which writes it to a file and shows the model a head+tail
# preview. If the tool layer truncated first (tools.observation default 1600) the
# tail was lost forever and the model saw a dead "...[truncated N chars]" marker.
# So the chat path renders observations up to this ceiling, then the harness offload
# bounds the model context while NOTHING is discarded (the file keeps it all).
CHAT_OBS_FULL = int(os.environ.get("LONGRUN_OFFLOAD_MAX", "200000"))
CHAT_TOOL_PROMPT = (
    "\n\n## Tools\nYou are a tool-using agent, not a plain chatbot: you chat with "
    "the user AND you can act. When a request needs a tool (run a command, read or "
    "write a file, call an MCP server, list or read a skill), reply with ONLY this "
    'JSON and nothing else: {"action":"tool","tool":"<name>","args":{...}}. '
    "After the tool runs you receive its observation and MUST continue: call another "
    "tool or answer the user in plain text. Never show JSON to the user; the final "
    "message must be plain prose. To plan a multi-step request, FIRST emit ONLY "
    '{"action":"write_todos","todos":[{"label":"<imperative step>","deps":[],"parent":null}]} '
    "(2-8 steps you author yourself; this list is PERSISTENT — it is saved and "
    "re-shown to you on every turn, and only you or the user may clear it), then "
    "FOLLOW it: address each step by its STABLE id — the list shows it as `label (n3)`. "
    "Before starting a step emit ONLY "
    '{"action":"update_todos","steps":[{"id":"<node id, e.g. n3>","status":"doing"}]}; when '
    "a step is finished emit ONLY "
    '{"action":"update_todos","steps":[{"id":"<node id>","status":"done","evidence":"<what proves it>"}]} '
    "(done REQUIRES evidence). The 0-based `index` still works as a fallback, but the id "
    "is preferred: it never shifts when the list changes. If new work appears or a step "
    "became irrelevant, "
    "briefly re-plan with "
    '{"action":"replan_todos","note":"<why>"} and then IMMEDIATELY resume the plan. '
    "To delegate a self-contained subtask to ONE child agent — it gets an isolated "
    "transcript and its own task list, then reports back its summary — emit ONLY "
    '{"action":"subagent","goal":"<the subtask>","max_steps":4}. Use it for a '
    "distinct subtask that can run on its own (e.g. reading and summarising a big "
    "file); do not delegate the whole task. One delegate per subtask. "
    "Tool registry (allowlist):\n"
)


# JAG-266: the task-list contract as a STANDING rule, not only a reactive nudge. It is
# registered as the `task-policy` prompt section (order 89) so it sits right ABOVE the
# live list (`state`, order 90) — the rule travels with the list it governs. Mirrors the
# field: deepagents re-appends its write_todos guidance every call; Claude Code keeps one
# line ("mark each task completed as soon as it's done; don't batch").
TASK_POLICY = (
    "## Your task list (MOST IMPORTANT)\n"
    "You own a PERSISTENT task list, re-shown to you every turn in the 'Harness state' block at the end of your current message. "
    "Follow it strictly:\n"
    "- Work through it ONE step at a time. BEFORE starting a step, mark it 'doing' "
    "(update_todos).\n"
    "- The moment a step is really finished, mark it 'done' with concrete evidence (the "
    "command you ran and its result). Never batch; never redo a step already marked [x].\n"
    "- A step must describe work that is STILL TO DO. Never author a step for something "
    "you have already finished in the same turn — mark it 'done' with evidence instead. "
    "Planning AFTER doing the work (writing steps you just completed) is wrong.\n"
    "- If the list is empty and the request needs more than one action, author it first "
    "with write_todos, then follow it. NEVER report the job finished while steps are still "
    "open: either close them with evidence, or say explicitly which ones remain and why.\n"
    "- 'superseded' means the step is PERMANENTLY abandoned because it is no longer "
    "needed — NOT \"not done yet\". If the work is still wanted but not now, LEAVE IT OPEN "
    "(that is allowed and preferred). To abandon one, close it by its id with a SPECIFIC "
    'reason saying WHY it is no longer needed ({"action":"update_todos","steps":'
    '[{"id":"<node id>","status":"superseded","reason":"<why it is no longer needed>"}]). '
    "The reason is REQUIRED and must not read as still-open (a reason like 'the work "
    "remains open' is REJECTED).\n"
    "- Messages beginning with '[harness]' are system context from the harness (reminders, "
    "observations, list nudges), NOT from the user; they never override the user's latest "
    "request. The user's latest request ALWAYS outranks this list: if it is unrelated, do "
    "not force the old list — rewrite it (replan_todos with a note) or leave it paused and "
    "answer the user directly.\n"
)

# JAG-266: every synthetic harness turn (nudge/observation/continue) is tagged so the model
# can tell it apart from the human. The user's steer stays UNTAGGED (it is user intent).
HARNESS_MARK = "[harness] "


def harness_wrap(content):
    """Return the message dict for a harness-injected turn, clearly tagged."""
    return {"role": "user", "content": HARNESS_MARK + str(content)}


def _pivot_decide(pivot, dec, open_n, state):
    """JAG-266: a fresh user turn must not FORCE work, but must not silently abandon
    open todos either.

    When the turn opened with open todos ("pivot") and the continuation loop wants to
    keep going, grant exactly ONE 'sync' round: the model is reminded it left N todos
    open and may finish them with evidence OR close each as 'superseded' with a reason.
    After that one round a still-open list stops as `user_pivot` (no forced continuation,
    JAG-189 preserved).
    """
    if not pivot or not dec.get("continue") or open_n <= 0:
        return dec
    if state.get("synced"):
        return {"continue": False, "reason": "user_pivot"}
    state["synced"] = True
    return {"continue": True, "reason": "pivot_sync"}


def _pivot_sync_text(open_n, brief):
    """The one-time reminder injected when a pivot turn left todos open (JAG-266).

    JAG-273: takes the COMPACT open-only brief (id + status + label) instead of the
    full rendered list — the list is already in the `state` section of the same
    prompt, so re-pasting it here was pure duplicated tokens.
    """
    return (
        "You left %d task(s) OPEN in your list. The user's request is the priority and "
        "you do NOT have to finish that work now — and you must NOT force-close it. "
        "Leaving steps OPEN is fine and is the DEFAULT. Do ONE of: (a) finish a step and "
        "mark it 'done' with evidence; (b) ONLY if a step is now PERMANENTLY unneeded, "
        "abandon it as 'superseded' with a SPECIFIC reason (REQUIRED) saying WHY it is no longer "
        'needed ({"action":"update_todos","steps":[{"id":"<node id>","status":"superseded",'
        '"reason":"<why it is no longer needed>"}]) — a reason that reads as still-open is '
        "REJECTED; or (c) rewrite the list with replan_todos. Then answer the "
        "user. Open (full list in 'Harness state' at the end of your message):\n%s" % (open_n, brief)
    )


def _next_stale(prev_stale, prev_hash, cur_hash, worked):
    """JAG-268: advance the 'no progress' counter ONLY for a truly idle round.

    A round that executed at least one tool (`worked`) DID make progress even if the
    todo-list hash did not move — that false positive used to halt a turn while the
    model was verifying its output (shell `FILE_OK` / `STRUCTURE_OK`) without touching
    the list. `stale` counts only a round with NO tool call AND no list change, which
    is the real "model is spinning" case; it stops via keepgoing's no_progress.
    """
    if prev_hash is None or cur_hash != prev_hash or worked:
        return 0
    return prev_stale + 1


# JAG-369: some models (DeepSeek V4 via OpenRouter) answer a tool request with
# their NATIVE tool-call markup instead of the harness' JSON protocol. The marker
# is "DSML" wrapped in full-width vertical bars (U+FF5C); the payload is an
# <invoke name="X"> holding <parameter name="Y">V</parameter> children. The harness
# used to ignore the whole thing and loop forever on "no valid action" (observed on
# the A8 "Master" session: the model re-emitted the same markup every turn). We now
# recognise and parse it, exactly like the near-miss dialects `_normalize_action`
# already accepts.
_DSML = "\uff5c\uff5cDSML\uff5c\uff5c"


def _looks_like_dsml(text):
    """True when `text` carries the model's native (DSML) tool-call markup."""
    return _DSML in (text or "")


def _looks_like_json_action(text):
    """True when `text` is a (possibly malformed/truncated) tool-call JSON OR the
    model's native DSML markup — i.e. machine text we must NEVER show to the user
    as a chat reply."""
    t = (text or "").strip()
    if _DSML in t:
        return True
    if not t.startswith(("{", "[")):
        return False
    return ('"action"' in t) or ('"tool"' in t) or ('"args"' in t)


# JAG-304: a parsed JSON OBJECT is only an ACTION ATTEMPT when it carries one of
# these top-level keys (an action name, a tool name/args, or a raw tool-arg key).
# A dict with NONE of them is the model's own JSON ARTIFACT — a JSON Schema, a
# response envelope, a data record — i.e. its ANSWER, not a stray action.
_JSON_ACTION_KEYS = ("action", "tool", "tool_name", "args", "todos", "steps")
_JSON_TOOL_ARG_KEYS = ("command", "path", "content", "url", "query", "pattern")


def _looks_like_action_dict(act):
    """True when a parsed JSON dict is a (possibly malformed) action/tool call.

    JAG-304: the chat loop used to reject ANY parsed dict as a stray action
    ("That was not a valid action"), so a worker/coordinator that delivered its
    own JSON artifact (a JSON-Schema, a response envelope) as the answer was
    nagged into needless retries — and could be halted at four in a row. Only a
    dict that actually carries an action- or tool-signalling key is an attempt.
    """
    if not isinstance(act, dict):
        return False
    keys = set(act)
    if keys & set(_JSON_ACTION_KEYS):
        return True
    return bool(keys & set(_JSON_TOOL_ARG_KEYS))


# JAG-74: "act, don't announce". A reply that ANNOUNCES work in the first person
# (and is short) is a promise of imminent work, not a result. If no tool ran this
# turn we nudge the model once to actually do it (or conclude).
# JAG-384: the announcement is often NOT the first sentence. Observed live: the
# turn goal "…non cambiare nulla proponi solo" got the reply "No: **non l'ho ancora
# provata sulla codebase**. …\n\nDa ora procedo **in sola lettura**: analizzo e
# propongo …". The START-anchored match MISSED it, so the nudge never fired and the
# turn ended (goal_reached, 0 open steps) with the model having promised work it
# never did. Match the verb at ANY sentence/line start too, allowing a short lead-in
# ("Da ora procedo", "Adesso analizzo", "Then I'll …").
_PROMISE_VERBS = (
    r"carico|procedo|eseguo|lancio|creo|installo|avvio|aggiorno|"
    r"verifico|controllo|continuo|cerco|consulto|analizzo|recupero|"
    r"preparo|inizio|comincio|elaboro|determino|sintetizzo|organizzo|"
    r"accedo|scarico|i'?ll|i will|i'?m going to|let me|loading|running")
_PROMISE_RE = re.compile(
    r"(?:^|\n|[.!?]\s+)\s*(?:\*\*)?"
    r"(?:da ora|adesso|ora|poi|quindi|dopo|subito|allora|"
    r"then|now|next|soon|from now)?\s*(?:\*\*)?(?:" + _PROMISE_VERBS + r")\b",
    re.IGNORECASE)


def _looks_like_promise(text):
    """True when the reply only announces an action (and is not a result)."""
    t = (text or "").strip()
    return bool(t) and len(t) <= 400 and bool(_PROMISE_RE.search(t))


def _skill_hints(text, limit=3):
    """JAG-178: names of installed skills that best match `text`. Cheap keyword
    scoring — a name/title hit weighs more than a description hit — so a stuck
    model is nudged to READ the skill that actually covers the problem instead of
    guessing the syntax again."""
    try:
        from longrun.memory import skills
        words = set(re.findall(r"[a-z]{3,}", (text or "").lower()))
        words -= {"the", "and", "for", "with", "you", "are", "not", "this", "that",
                  "error", "failed", "unknown", "command", "tool", "run", "get", "set"}
        if not words:
            return []
        scored = []
        for s in skills.list_skills():
            name = str(s.get("name") or "")
            strong = (name + " " + str(s.get("title") or "")).lower()
            weak = str(s.get("description") or "").lower()
            score = sum(3 for w in words if w in strong) + sum(1 for w in words if w in weak)
            if score:
                scored.append((score, name))
        scored.sort(key=lambda x: (-x[0], x[1]))
        return [n for _, n in scored[:limit] if n]
    except Exception:  # noqa: BLE001
        return []


def _stuck_note(tool, obs, fail_streak, repeats, hints):
    """JAG-178: a socratic "you are stuck" nudge. The harness does NOT solve the
    problem — it makes the model ask the RIGHT questions (syntax? skill? another
    route? ask the user?) and reminds it that it has skills and tools."""
    why = []
    if fail_streak >= 2:
        why.append("'%s' has failed %d times in a row" % (tool, fail_streak))
    if repeats >= 1:
        why.append("you just repeated the SAME call")
    return "\n".join([
        "Observation for tool %s:" % tool,
        obs,
        "",
        "SYSTEM (harness) — YOU ARE STUCK: %s." % ("; ".join(why) or "no progress"),
        "STOP and THINK before the next tool call. Ask yourself:",
        "  1) Is the command SYNTAX exactly right for this exact subcommand? (re-read the error above)",
        "  2) Have I READ the skill that covers this? You have skills — e.g. %s — "
        "read one with the `skills` tool (action=read, name=<skill>)."
        % (", ".join(hints) if hints else "check them in your system prompt"),
        "  3) Is there a DIFFERENT route to the same result that avoids this broken call?",
        "  4) If you cannot progress, ASK THE USER one precise question instead of retrying.",
        "Do NOT repeat the same call. Change approach, read a skill, or ask the user.",
    ])


def _repeat_block_note(tool, err, repeats, hints):
    """JAG-183: hard anti-loop directive. When the model re-issues an IDENTICAL
    call that already FAILED, the harness refuses to run it again (see the call
    site) and hands back this directive instead of a socratic question. Without it
    a stuck model burned the step budget looping and then resigned with a bare
    "mi fermo e chiedo" (session v176: 3x `adb ... input tap` -> exit 1)."""
    return "\n".join([
        "SYSTEM (harness) — CALL BLOCKED (repeat #%d). It was NOT executed." % repeats,
        "You already ran exactly this `%s` and it FAILED:" % tool,
        "  %s" % ((err or "").strip()[:300] or "(no error text)"),
        "Re-running it verbatim will fail again. Do ONE of these NOW:",
        "  1) a DIFFERENT command / a different route to the same result;",
        "  2) READ the skill that covers this%s;"
        % ((" — e.g. " + ", ".join(hints)) if hints else " (check your system prompt)"),
        "  3) if it is truly blocked, answer the user with ONE precise question:"
        " what you tried, the EXACT error, and what you need from them.",
        "Do NOT repeat the same call.",
    ])


def _plan_only_refusal(tool):
    """JAG-344: directive when a PLAN-ONLY turn tries to run a MUTATING tool.

    The master's planning turn may inspect the workspace (`fs.read`) and consult a
    skill (`skills`) but must NOT execute the teammates' work. Without this the model
    wrote the deliverable files itself and "verified" them, bypassing the team
    (observed live: the coordinator produced the whole KICKOFF PACKAGE in its plan
    turn). The tool is refused and the model is sent back to PLANNING.
    """
    return "\n".join([
        "SYSTEM (harness) — PLAN-ONLY turn: `%s` is NOT available while planning. "
        "It was NOT executed." % tool,
        "You are DECOMPOSING the goal for your team, not doing it. Allowed now: "
        "`fs.read` (inspect a file), `skills` (consult a skill) and your task list.",
        "Do this NOW: record the sub-tasks in your task list and END your reply with "
        "ONE bullet per teammate (agent id first, e.g. \"- A25: ...\"), putting "
        "\"(after AX)\" on any bullet that must WAIT for another agent.",
        "Do NOT write files and do NOT run commands — the workers execute them.",
    ])


def _open_plan_steps(sess):
    """How many plan nodes are still OPEN (todo/doing/blocked) for this session.

    JAG-87 ("verify before you finish", harness layer L7): the persistent plan is
    the execution state; a turn that ends with open steps and no explanation is a
    silent abandonment. Returns 0 when there is no plan at all.
    """
    try:
        from longrun.plan import taskgraph
        g = taskgraph.load(sess["id"])
        if not g or not g.get("nodes"):
            return 0
        c = taskgraph.counts(g)
        return sum(c.get(s, 0) for s in taskgraph.OPEN_STATUSES)
    except Exception:  # noqa: BLE001
        return 0


def _open_todo_brief(sess, limit=10):
    """JAG-271: the EXACT open steps (id + status + label) for a harness nudge.

    "mark the next step 'doing'" told the model nothing it could not guess, so it
    re-derived (and sometimes re-opened) the plan. The nudge must NAME what is left,
    by id (id-first) so the model can act on it directly. Returns (count, brief);
    brief is "(none …)" when the list is fully closed.
    """
    try:
        g = taskgraph.load(sess["id"])
        nodes = taskgraph.plan_nodes(g) or []
        opn = [n for n in nodes if n.get("status") in taskgraph.OPEN_STATUSES]
    except Exception:  # noqa: BLE001
        return 0, ""
    if not opn:
        return 0, "(none — every step is closed)"
    lines = ["  - %s [%s] %s" % (n.get("id"), n.get("status"), n.get("label", ""))
             for n in opn[:limit]]
    if len(opn) > limit:
        lines.append("  - … +%d more" % (len(opn) - limit))
    return len(opn), "\n".join(lines)


def _nudge_open_todos(sess):
    """JAG-271: the post-update nudge — NAMES the exact steps still open (by id).

    Replaces the old generic "mark the next step 'doing'" which named nothing.
    """
    on, brief = _open_todo_brief(sess)
    if on:
        return ("Noted — plan updated (by id). STILL OPEN (%d):\n%s\n"
                "Now do the FIRST one: mark it 'doing' before you start it, then 'done' "
                "with concrete evidence when it is really finished. Never redo a [x] "
                "step; close an unwanted one as 'superseded' WITH a reason."
                % (on, brief))
    return ("Noted — every step is now closed. If the user's request is fully answered, "
            "give the final plain-text answer now; otherwise say what still needs doing.")


# JAG-88: per-session counter for offloaded observation files (001_, 002_, ...).
_OFFLOAD_SEQ = {}
_OFFLOAD_HEAD = 1500
_OFFLOAD_TAIL = 600


def _offload_observation(sess, tool, text):
    """JAG-88 (harness layer L2 — context budgeting): keep big tool outputs OUT
    of the model's context but NEVER lose them.

    The chat loop used to hard-truncate every observation to 4000 chars: a big
    web page, a log dump or a `find` over a tree was silently cut and the tail
    was LOST to the model (and it could not recover it). Now an oversized
    observation is written verbatim to data/offload/<session>/ and the model
    receives a compact reference — size, line count, path, a head+tail preview,
    and the exact call to read the rest (fs.read / shell grep). The context
    stays bounded; nothing is discarded.
    """
    n = len(text)
    seq = _OFFLOAD_SEQ.get(sess["id"], 0) + 1
    _OFFLOAD_SEQ[sess["id"]] = seq
    safe = re.sub(r"[^A-Za-z0-9_.-]", "_", str(tool))[:40] or "tool"
    fallback = ("Observation for tool %s:\n%s\n\n"
                "Now answer the user in plain text, or call another tool."
                % (tool, text[:CHAT_TOOL_OBS_LIMIT]))
    try:
        outdir = os.path.join(DATA_DIR, "offload", sess["id"])
        os.makedirs(outdir, exist_ok=True)
        path = os.path.join(outdir, "%03d_%s.txt" % (seq, safe))
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text)
    except Exception:  # noqa: BLE001 — offload must never kill the turn
        return fallback
    lines = text.count("\n") + 1
    head = text[:_OFFLOAD_HEAD]
    ref = (
        "Observation for tool %s: output is LARGE (%d chars, %d lines) and was "
        "saved to a file so it does not flood your context.\n"
        "FULL OUTPUT FILE: %s\n"
        "Read more of it with {\"action\":\"tool\",\"tool\":\"fs.read\","
        "\"args\":{\"path\":\"%s\"}} (or grep it with the shell tool).\n"
        "Preview — first %d chars:\n%s\n"
        % (tool, n, lines, path, path, min(_OFFLOAD_HEAD, n), head))
    if n > _OFFLOAD_HEAD + _OFFLOAD_TAIL:
        ref += "...\nPreview — last %d chars:\n%s\n" % (_OFFLOAD_TAIL, text[-_OFFLOAD_TAIL:])
    ref += "\nNow answer the user in plain text, or call another tool."
    return ref


def _chat_tool_call(act, av02):
    """Accept the canonical {"action":"tool","tool":X,"args":{...}} and the
    model's frequent variant {"action":X,"args":{...}} when X is a real tool
    name. Returns (tool, args) or None."""
    if not isinstance(act, dict):
        return None
    try:
        names = set(av02.registry.tool_names())
    except Exception:  # noqa: BLE001
        return None
    tool = act.get("tool")
    if tool not in names and act.get("action") in names:
        tool = act.get("action")
    if tool not in names:
        return None
    args = dict(act.get("args") or {})
    for k in ("command", "path", "content", "url"):
        if k in act and k not in args:
            args[k] = act[k]
    return str(tool), args


def _apply_chat_todos(sess, act, on_event, node=None, after=None):
    """Harness action `write_todos`: persist the model-authored todo list.

    The chat loop is the ONLY writer of the task list (no separate planner
    call): when the model emits `{"action":"write_todos","todos":[...]}` we map
    it onto the session graph, publish a normal tool.call/tool.result pair so
    the app renders an inline card, and let the model continue.
    """
    try:
        graph = taskgraph.ensure(sess["id"], session_id=sess["id"])
        todos = act.get("todos")
        if isinstance(todos, str):
            todos, _ = taskgraph.parse_todos(todos)
        todo_args = {"todos": todos if isinstance(todos, list) else []}
        on_event("tool.call", session=sess["id"], tool="write_todos", args=todo_args,
                 inline=True)
        # JAG-177: a new plan REPLACES the previous OPEN plan — cancel the open
        # steps the model did NOT keep, so re-planning never accumulates a wall of
        # obsolete, overlapping steps (session `test`: 27 nodes from 3 re-plans).
        # `done`/`cancelled` history is preserved.
        _labels = []
        for _t in (todos or []):
            _l = _t if isinstance(_t, str) else (_t.get("label") or _t.get("title")
                                                 or _t.get("task"))
            if _l:
                _labels.append(_l)
        if _labels:
            for _cid in taskgraph.supersede_open(graph, _labels):
                _n = taskgraph.find(graph, node_id=_cid)
                if _n:
                    on_event("graph.node.updated", session=sess["id"], node=_n,
                             index=graph["nodes"].index(_n),
                             total=len(graph["nodes"]), changes=["status"])
        base = len(graph.get("nodes", []))
        added = taskgraph.apply_write_todos(
            graph, taskgraph._missing(graph, todos or []))
        total = len(graph.get("nodes", []))
        # surface each node on the chat stream too, so the app renders the list
        # live (apply_write_todos only fans out on the global feed).
        for i, _nd in enumerate(added):
            on_event("graph.node.added", session=sess["id"], node=_nd,
                     index=base + i, total=total)
        # JAG-116: the card must show in AND out, not an empty body.
        # JAG-269: show the CURRENT plan with each node's ID + any close reason
        # (id-first addressing: the model learns the ids here and reuses them).
        out = "\n".join(
            "- [%s] %s %s%s" % (
                n.get("status", "open"), n.get("id", ""), n.get("label", ""),
                ("  (%s: %s)" % (n.get("status"), n.get("reason"))
                 if n.get("reason") else ""))
            for n in (taskgraph.plan_nodes(graph) or graph.get("nodes", [])))
        on_event("tool.result", session=sess["id"], tool="write_todos", ok=True,
                 exit_code=0, backend="harness", args=todo_args,
                 output=out[:2000] or ("+%d node(s)" % len(added)),
                 summary="task list: %d node(s), +%d" % (total, len(added)))
        # JAG-190: persist the card so a reload rebuilds it (harness-action cards
        # were streamed live but never stored, so they vanished on refresh).
        persist_tool_card(sess, "write_todos", True, args=todo_args,
                          result=out[:2000] or ("+%d node(s)" % len(added)),
                          exit_code=0, backend="harness", node=node, after=after)
        return len(added)
    except Exception as e:  # noqa: BLE001 — the task list must never break chat
        try:
            on_event("tool.result", session=sess["id"], tool="write_todos",
                     ok=False, backend="harness", stderr=str(e)[:200])
            persist_tool_card(sess, "write_todos", False, error=str(e)[:200],
                              backend="harness", node=node, after=after)
        except Exception:  # noqa: BLE001
            pass
        return 0


def _resolve_graph_node(graph, step):
    """Locate a node by id, label or 0-based index (JAG-75).

    JAG-196: the model's `update_todos` uses 0-based indices / labels into ITS
    CURRENT list. Since JAG-194 keeps every plan's nodes in the graph, resolving
    against the whole node list made index 0 hit an OLD plan's node — the current
    plan never advanced ("All steps complete" vs "4 open" deadlock). Resolve
    labels/indices against the CURRENT plan only; ids stay globally unique.
    """
    nodes = taskgraph.plan_nodes(graph) or graph.get("nodes", [])
    node = None
    if step.get("id") is not None:
        node = taskgraph.find(graph, node_id=str(step["id"]))
    if node is None and step.get("label"):
        _lbl = str(step["label"]).strip().lower()
        for _n in nodes:
            if str(_n.get("label", "")).strip().lower() == _lbl:
                node = _n
                break
    if node is None and step.get("index") is not None:
        try:
            i = int(step["index"])
        except (TypeError, ValueError):
            return None
        if 0 <= i < len(nodes):
            node = nodes[i]
    return node


def _apply_chat_todo_updates(sess, act, on_event, node=None, after=None):
    """Harness action `update_todos`: the MODEL advances its own plan (JAG-75).

    `{"action":"update_todos","steps":[{"index":0,"status":"doing"}]}` marks a
    step in progress; `{"status":"done","evidence":"..."}` completes it (evidence
    is mandatory — same rule as the API). This is what let the graph advance on
    its own: before, only the UI/API could move a node.
    """
    try:
        graph = taskgraph.ensure(sess["id"], session_id=sess["id"])
        steps = act.get("steps") or act.get("todos") or []
        if isinstance(steps, dict):
            steps = [steps]
        if not isinstance(steps, list):
            steps = []
        on_event("tool.call", session=sess["id"], tool="update_todos",
                 args={"steps": steps}, inline=True)
        changed = []
        # JAG-269: reasons/misses are surfaced (not swallowed) so the model learns
        # WHY a close was rejected instead of silently seeing "0/N updated".
        errors = []
        for step in steps:
            if not isinstance(step, dict):
                continue
            _ref = step.get("id") or step.get("label") or step.get("index")
            _nd = _resolve_graph_node(graph, step)
            if _nd is None:
                errors.append("step %r not found" % (_ref,))
                continue
            status = str(step.get("status") or "").strip().lower()
            ev = step.get("evidence")
            try:
                if status == "done":
                    # JAG-320: refuse a `done` that contradicts a FAILED delegation on
                    # THIS step. Observed live: three subagents timed out for a step,
                    # then the model closed it as done with invented evidence. The
                    # marker is durable (stored on the node) so the guard still fires
                    # hours later / after a restart — a short timer missed it (the real
                    # claim came ~8.6h after the failure). The refusal is ONE-SHOT: the
                    # marker is consumed, so a genuine retry or a self-completed step
                    # is never blocked forever.
                    _fail = _nd.get("delegation")
                    if isinstance(_fail, dict) and _fail.get("ok") is False:
                        errors.append(
                            "step %s: refusing 'done' — its delegated subagent FAILED "
                            "(%s); retry the delegation or do the work yourself, then "
                            "close it again."
                            % (_nd["id"], str(_fail.get("error") or "error")[:120]))
                        try:
                            taskgraph.clear_delegation(graph, _nd["id"])
                        except Exception:  # noqa: BLE001
                            pass
                        continue
                    _nd = taskgraph.complete_node(
                        graph, node_id=_nd["id"], evidence=ev, source="model:update_todos")
                elif status in taskgraph.STATUSES:
                    _nd = taskgraph.update_node(
                        graph, _nd["id"], status=status, evidence=ev,
                        reason=step.get("reason"), source="model:update_todos")
                else:
                    errors.append("step %s: bad status %r" % (_nd["id"], status))
                    continue
            except (KeyError, ValueError) as _e:
                errors.append("step %s: %s" % (_nd["id"], _e))
                continue
            changed.append(_nd)
            on_event("graph.node.updated", session=sess["id"], node=_nd,
                     index=graph["nodes"].index(_nd), total=len(graph["nodes"]),
                     changes=["status"])
        # JAG-177: at most ONE step may be 'doing' — demote the extras to 'todo'.
        for _did in taskgraph.enforce_single_doing(graph):
            _dn = taskgraph.find(graph, node_id=_did)
            if _dn:
                on_event("graph.node.updated", session=sess["id"], node=_dn,
                         index=graph["nodes"].index(_dn),
                         total=len(graph["nodes"]), changes=["status"])
        # JAG-268: show the WHOLE current list (like write_todos), not just the
        # changed lines — a lone "- [doing] <label>" read like a stray claim and
        # hid the step in its list context.
        # JAG-269: each line carries the node's ID (id-first addressing) and, for a
        # closed-with-reason step, the reason — so the card shows the whole object.
        def _render_line(_n):
            _extra = ("  (%s: %s)" % (_n.get("status"), _n.get("reason"))
                      if _n.get("reason") else "")
            return "- [%s] %s %s%s" % (_n.get("status", "open"), _n.get("id", ""),
                                       _n.get("label", ""), _extra)
        _out = ("\n".join(_render_line(n)
                          for n in (taskgraph.plan_nodes(graph) or graph.get("nodes", [])))[:2000]
                or "no step changed")
        if errors:
            _out = (_out + "\n! " + "\n! ".join(str(e) for e in errors))[:2000]
        _err = "; ".join(str(e) for e in errors)[:400]
        _n_steps = len([s for s in steps if isinstance(s, dict)])
        on_event("tool.result", session=sess["id"], tool="update_todos", ok=(not errors),
                 exit_code=(0 if not errors else 1), backend="harness", args={"steps": steps},
                 output=_out, stderr=(_err or None),
                 summary="task list: %d/%d step(s) updated%s"
                         % (len(changed), _n_steps,
                            (", %d rejected" % len(errors)) if errors else ""))
        # JAG-190: persist so the card survives a reload.
        persist_tool_card(sess, "update_todos", (not errors), args={"steps": steps},
                          result=_out, error=_err, exit_code=(0 if not errors else 1),
                          backend="harness", node=node, after=after)
        return len(changed)
    except Exception as e:  # noqa: BLE001 — the task list must never break chat
        try:
            on_event("tool.result", session=sess["id"], tool="update_todos",
                     ok=False, backend="harness", stderr=str(e)[:200])
            persist_tool_card(sess, "update_todos", False, error=str(e)[:200],
                              backend="harness", node=node, after=after)
        except Exception:  # noqa: BLE001
            pass
        return 0


def _apply_chat_replan(sess, act, on_event, node=None, after=None):
    """Harness action `replan_todos`: a brief, controlled re-plan (JAG-75).

    The model asks for the graph to be extended/corrected; only NEW steps are
    generated, existing nodes are preserved, and the loop then resumes the plan.
    """
    try:
        graph = taskgraph.ensure(sess["id"], session_id=sess["id"])
        on_event("tool.call", session=sess["id"], tool="replan_todos", args={}, inline=True)
        added = taskgraph.replan_from_model(
            graph, act.get("note") or act.get("goal") or "", on_event=on_event) or []
        on_event("tool.result", session=sess["id"], tool="replan_todos", ok=True,
                 exit_code=0, backend="harness",
                 summary="re-plan: +%d step(s)" % len(added))
        # JAG-190: persist so the card survives a reload.
        persist_tool_card(sess, "replan_todos", True,
                          result="re-plan: +%d step(s)" % len(added),
                          exit_code=0, backend="harness", node=node, after=after)
        return len(added)
    except Exception as e:  # noqa: BLE001 — never break chat
        try:
            on_event("tool.result", session=sess["id"], tool="replan_todos",
                     ok=False, backend="harness", stderr=str(e)[:200])
            persist_tool_card(sess, "replan_todos", False, error=str(e)[:200],
                              backend="harness", node=node, after=after)
        except Exception:  # noqa: BLE001
            pass
        return 0


def _apply_chat_subagent(sess, act, on_event, node=None, after=None):
    """Harness action `subagent` (JAG-189): delegate ONE subtask to a child run.

    The chat loop spawns a subagent (isolated transcript, its own task list, the
    same tools/approvals/sandbox), WAITS for it, and feeds its summary back as
    the next observation. Mirrors the HTTP `/api/subagent/spawn` endpoint and the
    MCP `longrun_subagent` tool, so the model can actually delegate: before
    JAG-189 the action existed but was nowhere in the model's menu, so a request
    to "delegate to a subagent" looped forever.
    """
    try:
        from longrun.agent import subagent as _sub
        _act = act if isinstance(act, dict) else {}
        _args = _act.get("args") if isinstance(_act.get("args"), dict) else {}
        goal = str(_act.get("goal") or _args.get("goal")
                   or _act.get("detail") or "").strip()
        if not goal:
            on_event("tool.result", session=sess["id"], tool="subagent", ok=False,
                     backend="harness", exit_code=1, summary="subagent: goal required")
            persist_tool_card(sess, "subagent", False, error="goal required",
                              backend="harness", node=node, after=after)
            return "subagent error: goal required"
        try:
            max_steps = int(_act.get("max_steps", _args.get("max_steps", 4)))
        except (TypeError, ValueError):
            max_steps = 4
        model = _act.get("model") or _args.get("model") or None
        on_event("tool.call", session=sess["id"], tool="subagent",
                 args={"goal": goal, "max_steps": max_steps, "model": model},
                 inline=True)
        spawned = _sub.spawn(goal, parent_run_id=sess["id"], max_steps=max_steps,
                             model=model, depth=_sub.depth_of(sess["id"]) + 1) or {}
        sid = spawned.get("subagent_id")
        if not sid:
            err = spawned.get("error") or "spawn failed"
            on_event("tool.result", session=sess["id"], tool="subagent", ok=False,
                     backend="harness", exit_code=1, summary="subagent: " + str(err))
            persist_tool_card(sess, "subagent", False, error=str(err),
                              backend="harness", node=node, after=after)
            return "subagent error: %s" % err
        res = _sub.collect(sid, timeout=SUBAGENT_WAIT) or {}
        summary = str(res.get("summary") or "").strip()
        ok = bool(res.get("ok"))
        # JAG-320: remember the OUTCOME on the delegated step's node (durable, so a
        # later `update_todos ... done` cannot close a step whose subagent failed —
        # even hours later or after a restart). A successful delegation clears it.
        if node:
            try:
                _g = taskgraph.load(sess["id"])
                if _g:
                    taskgraph.record_delegation(_g, node, ok,
                                                error=res.get("error"), subagent_id=sid)
            except Exception:  # noqa: BLE001
                pass
        out = summary or json.dumps(res, ensure_ascii=False, default=str)[:1500]
        on_event("tool.result", session=sess["id"], tool="subagent", ok=ok,
                 exit_code=0 if ok else 1, backend="subagent",
                 args={"goal": goal, "max_steps": max_steps, "subagent_id": sid},
                 output=out[:4000],
                 summary="subagent %s: %s" % (sid, "done" if ok else "error"))
        # JAG-190: persist so the card survives a reload.
        persist_tool_card(sess, "subagent", ok,
                          args={"goal": goal, "max_steps": max_steps,
                                "subagent_id": sid},
                          result=out[:4000], exit_code=0 if ok else 1,
                          backend="subagent", node=node, after=after)
        if ok:
            return ("Subagent %s finished (goal: %s).\nResult:\n%s"
                    % (sid, goal[:120], out[:4000]))
        # JAG-320: say FAILED plainly (the old text said "finished" even on
        # failure) and forbid closing the delegated step on the back of it.
        return ("Subagent %s FAILED: %s. This delegated step is NOT done — retry "
                "the delegation, do the work yourself, or mark the step blocked."
                % (sid, str(res.get("error") or "unknown")[:200]))
    except Exception as e:  # noqa: BLE001 — delegation must never break chat
        try:
            on_event("tool.result", session=sess["id"], tool="subagent", ok=False,
                     backend="harness", exit_code=1, stderr=str(e)[:200],
                     summary="subagent: error")
            persist_tool_card(sess, "subagent", False, error=str(e)[:200],
                              backend="harness", node=node, after=after)
        except Exception:  # noqa: BLE001
            pass
        return "subagent error: %s" % e


# JAG-93: post-turn reflection -> one append-only lesson in the memory store
# (self-improvement). A reflection must never break a turn: everything here is
# guarded and bounded, and a per-session cooldown keeps short bursts from
# spamming the store.
_REFLECT_LATEST = {}
_REFLECT_COOLDOWN = 90.0


def maybe_reflect(sess, message, answer, used_tools, model=None):
    """Distill one short reusable lesson after a tool-using turn.

    Returns the stored lesson string, or None when skipped/failed.
    """
    if not used_tools:
        return None
    now = time.time()
    if now - _REFLECT_LATEST.get(sess["id"], 0) < _REFLECT_COOLDOWN:
        return None
    try:
        from longrun.memory import memory
        msgs = [{"role": "system", "content":
                 "You are the self-improvement module. Read the exchange and write "
                 "ONE short reusable lesson (a durable rule, a fix, a gotcha) for "
                 "future sessions. Max 140 characters. No preamble, no quotes, no markdown."},
                {"role": "user", "content":
                 "Goal: %s\nOutcome: %s" % (str(message)[:500], str(answer)[:800])}]
        lesson, _think, _alias = _router_stream(
            msgs, model or default_model(), lambda ch, t: None, timeout=60)
        lesson = (lesson or "").strip().strip('"').strip()
        if len(lesson) < 6 or len(lesson) > 400:
            return None
        memory.store("agent.note", lesson, session=sess["id"], source="reflect")
        _REFLECT_LATEST[sess["id"]] = now
        return lesson
    except Exception:  # noqa: BLE001 — reflection must never break a turn
        return None


def _apply_skill_slash(message):
    """JAG-109: `/name rest` → injects the SKILL.md into the turn's prompt.

    It does not modify the saved history (stays `/name rest`); the injection is
    transient and applies only to this turn. `/goal` is untouched.
    """
    if not message or not message.startswith("/"):
        return message
    token, _, rest = message[1:].partition(" ")
    token = token.strip().lower()
    if not token or token == "goal":
        return message
    try:
        from longrun.memory import skills as skills_mod
        sk = skills_mod.get_skill(token)
    except Exception:  # noqa: BLE001 — the injection must never break a turn
        return message
    if not sk:
        return message
    body = (sk.get("content") or "")[:20000]
    rel = sk.get("path") or ""
    skill_dir = (os.path.dirname(os.path.abspath(os.path.join(REPO, rel)))
                 if rel else "")
    hint = ""
    if skill_dir:
        hint = (
            "SKILL_DIR (absolute path of this skill \u2014 use it as the skill ROOT; "
            "replace ${CLAUDE_SKILL_DIR} / ${SKILL_DIR} / $SKILL_DIR with it, and "
            "resolve every relative path in the instructions below against it). "
            "DO NOT search the filesystem for the script: it is right here.\n"
            "SKILL_DIR: %s\n\n" % skill_dir)
    return ("SKILL ACTIVATION \u2014 '%s' (follow these instructions for this turn)\n\n"
            "%s%s\n\n---\nUSER: %s" % (token, hint, body, rest.strip()))


# JAG-417: image attachments. The composer serializes an image attachment as a
# `- file: <absolute path>` line inside the user message; a vision model never
# saw the pixels (only the path). Detect those lines, read+base64 the real image
# files, and turn the CURRENT user turn into OpenAI multimodal content blocks.
_IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp"}
_IMAGE_MAX_BYTES = 8 * 1024 * 1024


def _extract_image_paths(text):
    """Absolute local image paths named on `- file: <path>` / `- <path>` lines."""
    out = []
    if not isinstance(text, str):
        return out
    for line in text.splitlines():
        s = line.strip()
        if not s.startswith("-"):
            continue
        s = s[1:].strip()
        if s.startswith("file:"):
            s = s[len("file:"):].strip()
        if not s or not os.path.isabs(s):
            continue
        if os.path.splitext(s)[1].lower() not in _IMAGE_EXTS:
            continue
        if os.path.isfile(s) and s not in out:
            out.append(s)
    return out


def _image_content_blocks(text, paths):
    """[text block] + one image_url block per readable, in-budget image path."""
    blocks = [{"type": "text", "text": text}]
    for p in paths:
        try:
            if os.path.getsize(p) > _IMAGE_MAX_BYTES:
                continue
            mime = mimetypes.guess_type(p)[0] or ""
            if not mime.startswith("image/"):
                continue
            with open(p, "rb") as f:
                b64 = base64.b64encode(f.read()).decode("ascii")
        except OSError:
            continue
        blocks.append({"type": "image_url",
                       "image_url": {"url": "data:%s;base64,%s" % (mime, b64)}})
    return blocks


def _inject_vision_blocks(msgs, model):
    """Give the CURRENT user message multimodal blocks when the model can see.

    Conservative on every axis: no image paths, a text-only model, or any bad
    file leaves `msgs` untouched (the plain-text note still reaches the model).
    """
    if not msgs:
        return msgs
    last = msgs[-1]
    if not isinstance(last, dict) or last.get("role") != "user":
        return msgs
    text = last.get("content")
    if not isinstance(text, str):
        return msgs
    paths = _extract_image_paths(text)
    if not paths:
        return msgs
    try:
        eff_model = model or routing.pick("chat") or default_model()
        if not model_supports_vision(eff_model):
            return msgs
    except Exception:  # noqa: BLE001 — never block a turn on vision detection
        return msgs
    blocks = _image_content_blocks(text, paths)
    if len(blocks) <= 1:  # every image was skipped (size/mime/read error)
        return msgs
    msgs = list(msgs)
    msgs[-1] = dict(last, content=blocks)
    return msgs


def assemble_turn(sess, message, tool_ctx=None, model=None, autonomous=False):
    """Assemble the exact message list SENT to the router for one chat turn.

    JAG-100: the caller has ALREADY appended the `user` turn to the session
    (JAG-51 contract), so we drop that stored copy and let `context_engine.build`
    append the (possibly autonomous-augmented) message exactly ONCE. Before this
    fix the same message was sent twice: harmless for a short prompt, but it
    DOUBLED a large pasted message (a 34.5k-token block reached the model as
    ~72k = 2x block + system). Returns (msgs, ctx_stats); ctx_stats is None when
    the context engine is unavailable (plain fallback).
    """
    if tool_ctx is None:
        tool_ctx = server._tool_context()
    sys = server._system_prompt(sess, tool_ctx)
    eff_message = _apply_skill_slash(message)
    if autonomous:
        eff_message = (
            "AUTONOMOUS GOAL MODE — accomplish the goal below end to end without "
            "asking for confirmation. FIRST emit write_todos with 2-8 steps, then "
            "execute them one by one with tools, marking each 'doing' and then "
            "'done' with evidence, then finish with a short plain-text summary."
            "\n\nGOAL: " + str(message))
    # JAG-100: drop the just-stored user turn so it is never sent twice.
    transcript = list(sess.get("messages", []))
    if transcript and transcript[-1].get("role") == "user":
        transcript = transcript[:-1]
    # JAG-276: the live task list rides in the CURRENT user turn (not the system
    # prompt) so the whole system prompt + committed transcript stay cache-safe.
    eff_message = eff_message + "\n\n" + state_block(session_id=(sess or {}).get("id"))
    try:
        from longrun.model import context_engine
        msgs, ctx_stats = context_engine.build(
            sys, transcript, eff_message, budget_tokens=context_budget(model))
        return _inject_vision_blocks(msgs, model), ctx_stats
    except Exception:  # noqa: BLE001 — never block a turn on the context engine
        msgs = [{"role": "system", "content": sys}]
        msgs += [{"role": m["role"], "content": m["content"]}
                 for m in transcript[-20:]]
        msgs.append({"role": "user", "content": eff_message})
        return _inject_vision_blocks(msgs, model), None


_HARNESS_ACTION_NAMES = ("write_todos", "update_todos", "replan_todos", "subagent",
                         "plan_step", "complete_plan_step", "add_task",
                         "complete_task", "note", "finish")

# JAG-278: a weak model often ends a turn with a made-up envelope whose action is a
# synonym of "I am done" ({"action":"answer","text":"..."} / {"action":"finish"}).
# Treat those as the plain-text answer instead of burning the retry budget on them.
_TERMINAL_ACTIONS = ("answer", "respond", "response", "final", "final_answer",
                     "finish", "complete", "done", "end", "stop", "message",
                     "reply", "result", "output", "report")


def _term_action(act):
    """True when the action is a made-up 'I am done' synonym (JAG-278)."""
    try:
        return str(act.get("action") or "").strip().lower() in _TERMINAL_ACTIONS
    except Exception:  # noqa: BLE001
        return False


def _normalize_action(act):
    """JAG-264: accept the obvious near-misses weak models keep emitting.

    Real tools use {"action":"tool","tool":"<name>","args":{...}}; harness/plan
    actions are TOP-LEVEL ({"action":"update_todos","steps":[...]}). A small model
    conflates the two — it wraps a harness action inside the tool envelope, or
    emits the bare payload with no "action" — then loops forever on the harness's
    "not a valid tool call" retry (observed flooding the WebUI). Normalise those
    back to the intended action; a well-formed tool call or harness action is
    returned unchanged.
    """
    if not isinstance(act, dict):
        return act
    a = act.get("action")
    # JAG-278: an OpenAI-style function call {"name":"x","arguments":{...}}.
    if not a and isinstance(act.get("name"), str) and "arguments" in act:
        _args = act.get("arguments")
        if isinstance(_args, str):
            try:
                _args = json.loads(_args)
            except Exception:  # noqa: BLE001
                _args = {}
        return {"action": "tool", "tool": act["name"], "args": _args or {}}
    if a == "tool":
        name = act.get("tool") or act.get("tool_name") or act.get("name")
        if name in _HARNESS_ACTION_NAMES:
            inner = dict(act.get("args") or {})
            inner["action"] = name
            for k in ("thought", "note", "todos", "steps", "goal", "detail",
                      "model", "max_steps"):
                if k in act and k not in inner:
                    inner[k] = act[k]
            return inner
        if name:
            return {"action": "tool", "tool": name, "args": act.get("args") or {}}
        return act
    if not a:
        if "todos" in act:
            return dict(act, action="write_todos")
        if "steps" in act:
            return dict(act, action="update_todos")
        if "note" in act:
            return dict(act, action="replan_todos")
    # JAG-278: an UNKNOWN action name but a recognizable PAYLOAD — coerce by SHAPE.
    # A weak model writes the right body under a wrong/labelled action ("update",
    # "set_todos", ...); the payload is the reliable signal, not the action name.
    if a not in ("tool", "write_todos", "update_todos", "replan_todos", "subagent"):
        if isinstance(act.get("todos"), list):
            return dict(act, action="write_todos")
        if isinstance(act.get("steps"), list):
            return dict(act, action="update_todos")
    return act


def _dsml_action(text):
    """JAG-369: convert the model's native DSML tool-call markup into the harness
    action. Returns the FIRST invocation as
    ``{"action":"tool","tool":<name>,"args":{...}}``, or ``None`` when `text` is
    not DSML or carries no parseable invocation. A parameter marked
    ``string="false"`` (a number / array / object) is decoded from JSON when it
    parses, otherwise kept verbatim."""
    if not _looks_like_dsml(text):
        return None
    m = re.search(_DSML + r'\s*invoke\s+name="([^"]+)"\s*>(.*?)</' + _DSML
                  + r'\s*invoke>', text, re.S)
    if not m:
        return None
    name = m.group(1).strip()
    args = {}
    for pm in re.finditer(_DSML + r'\s*parameter\s+name="([^"]+)"([^>]*)>(.*?)</'
                          + _DSML + r'\s*parameter>', m.group(2), re.S):
        key = pm.group(1).strip()
        val = pm.group(3)
        if 'string="false"' in pm.group(2):
            try:
                val = json.loads(val)
            except Exception:  # noqa: BLE001
                pass
        args[key] = val
    if not name:
        return None
    return {"action": "tool", "tool": name, "args": args}


def _extract_action(answer):
    """JAG-369: turn the model's raw answer into a harness action (or None).

    Tries the JSON protocol first; if that yields NOTHING usable — `extract_json`
    returns `[]` on failure, not `None`, so a falsy check is required, not an
    `is None` one — fall back to the model's native DSML tool-call markup."""
    act = _normalize_action(extract_json(answer))
    if not act:
        act = _dsml_action(answer)
    return act


def _harness_start_note(sess):
    """JAG-332: ONE durable "session started" harness marker, written on the first turn.

    The full system prompt is emitted every turn but TRANSIENTLY (kind 'system', not
    persisted), so after a reload the operator sees NO harness message at the start of a
    session and cannot tell that the harness passed a real prompt. This writes a single
    durable marker per session stating what the harness LOADED (workspace, rules, skills
    index, tool registry, prompt size) — the wiring the model is actually given.
    """
    sid = (sess or {}).get("id")
    if not sid:
        return
    if any(r.get("kind") == "harness-start" for r in (sess.get("injects") or [])):
        return
    try:
        from longrun.model import prompt as prompt_mod
        from longrun.memory import rules as rules_mod
        ws = rules_mod.resolve_workspace(sess)
        secs = prompt_mod.section_texts(sess, ws=ws, tool_ctx=None)
        text = ("session started \u2014 harness wiring\n"
                "- workspace: %s\n"
                "- rules loaded (RULES.md): %d chars\n"
                "- skills index: %d chars \u2014 search a skill with skills{action:'search'}\n"
                "- tool registry: %d chars\n"
                "- system prompt: %d chars (re-sent with each request; the provider reuses "
                "its KV-cache, so it is recomputed only after compaction/reset)"
                % (ws or "-", len(secs.get("rules") or ""), len(secs.get("skills") or ""),
                   len(secs.get("tools") or ""),
                   len(prompt_mod.render_sections(sess, ws=ws, tool_ctx=None))))
    except Exception:  # noqa: BLE001 — the marker must never break a turn
        text = "session started"
    try:
        persist_inject(sess, "harness-start", text)
        publish("harness.inject", session=sid, inject_kind="harness-start", text=text)
    except Exception:  # noqa: BLE001
        pass


def chat_once(sess, message, model=None, on_delta=None, trace=None, on_event=None,
              autonomous=False, plan_only=False):
    """Run one streamed router call and persist exactly one assistant message.

    Contract (JAG-51): the caller appends the `user` message; this function is
    the only place that persists the matching `assistant` turn. It returns
    `(message, model_used)`. On success the message carries the reply; when the
    model returns no answer at all the message is still persisted, flagged with
    `error=True` / `error_detail` (see `ensure_reply_persisted`) so no request
    can ever end as an orphan `user` turn. Raises only when the router call
    itself fails — callers then persist the error turn (`ensure_reply_persisted`).
    """
    # JAG-332: on the FIRST turn of a session, leave a durable harness marker so the
    # operator can SEE the wiring (the full prompt card is transient, per turn).
    if len(sess.get("messages") or []) <= 1:
        _harness_start_note(sess)
    if on_delta is None:
        on_delta = lambda channel, text: publish(
            "chat.delta", session=sess["id"], channel=channel, text=text)
    if on_event is None:
        on_event = publish
    # JAG-58b: the chat IS the agent — same tool registry as the agent loop, so
    # the model can call tools inline before it answers. Falls back to plain chat
    # if the tool registry is unavailable.
    # JAG-70/JAG-100: one shared assembler builds the EXACT prompt sent here and
    # measured by the context indicator, so the number cannot drift from reality.
    tool_ctx = server._tool_context()
    msgs, ctx_stats = assemble_turn(sess, message, tool_ctx, model, autonomous)
    # JAG-172: everything appended to `msgs` from this index on is THIS turn's
    # agentic history (tool calls, observations, nudges). It is persisted at the
    # end of the turn so the model retains its own work across turns and the ctx
    # meter reflects the real prompt (see the block before `append_message`).
    _turn_base = len(msgs)
    if ctx_stats:
        # JAG-78: `on_event` (not `publish`), so the chat STREAM carries the live
        # prompt size and the app's ctx meter updates during the turn.
        on_event("context.built", session=sess["id"],
                 display=server.context_display(ctx_stats.get("final_tokens"),
                                                ctx_stats.get("budget_tokens")),
                 **{
                     k: v for k, v in ctx_stats.items() if k in (
                         "budget_tokens", "retrieved_memories", "final_messages",
                         "final_tokens")})
    model = model or default_model()
    # JAG-58b: tool-aware chat loop. The model may answer directly, or ask for a
    # tool; the tool runs through the same approval gate as the agent loop and
    # its observation is fed back, then the model continues. Streaming deltas are
    # buffered per iteration so raw tool-call JSON is never shown to the user.
    max_steps = CHAT_TOOL_MAX_STEPS if tool_ctx else 1
    # JAG-344: a plan-only turn keeps a TIGHT real-tool budget (the master inspects
    # a little to inform its plan) and never continues past it (see the loop below).
    if plan_only:
        max_steps = min(max_steps, PLAN_ONLY_MAX_STEPS)
    answer, think = "", ""
    final_answer = ""
    # JAG-304: set when the final answer is the model's own JSON artifact (not an
    # action) — the tail JSON guard must not gut a legitimate artifact that merely
    # contains an "action"/"tool"/"args" substring.
    _final_is_artifact = False
    announce_nudged = False
    _hitl = None   # JAG-171: set when the turn stops with OPEN todos → ask the human
    # JAG-84: only REAL tool calls consume the work budget. Plan/todo bookkeeping
    # (write_todos / update_todos / replan_todos) and invalid-JSON retries used to
    # eat the same 4-step budget, so a "plan then work" turn ran out of steps right
    # after the plan, was forced to "answer in plain text" and announced instead of
    # acting (session 558d0f0fce6e / run 056347769632: write_todos + skills x3 then
    # "I'm proceeding with the live search…" and stop). Now bookkeeping is free but bounded
    # by CHAT_TOOL_MAX_ITERS.
    # JAG-86: the model's REAL token accounting for this turn (from the router's
    # `usage`), so the ctx meter stops being a pure chars/4 proxy.
    chat_usage = {}
    _total_prompt = 0
    _total_completion = 0

    def _record_usage():
        nonlocal _total_prompt, _total_completion
        pt = chat_usage.get("prompt_tokens")
        _total_prompt += int(pt or 0)
        _total_completion += int(chat_usage.get("completion_tokens") or 0)
        if pt:
            try:
                _REAL_PROMPT_TOKENS[sess["id"]] = int(pt)
            except (TypeError, ValueError):
                pass
        # JAG-273: the provider's prefix (KV) cache hit for this call.
        _det = chat_usage.get("prompt_tokens_details") or {}
        _c = _det.get("cached_tokens")
        if _c is None:
            _c = (chat_usage.get("timings") or {}).get("cache_n")
        if _c is not None:
            try:
                _REAL_CACHED_TOKENS[sess["id"]] = int(_c)
            except (TypeError, ValueError):
                pass
        # JAG-355: price this call from its REAL usage, append it to the live cost
        # ledger, and push it so the Cost panel updates mid-run.
        try:
            from longrun.model import costs as _costs
            # JAG-403f: tag every call of this turn with the turn's run id, so the
            # UI can group the ledger "per run" (one collapsible row per turn).
            _call = _costs.record(sess["id"], model, chat_usage,
                                  run=getattr(trace, "id", None))
            if _call:
                on_event("cost.usage", session=sess["id"], call=_call)
        except Exception:  # noqa: BLE001 — accounting must never break a turn
            pass

    def _emit_context():
        """JAG-98: re-emit the live ctx size with the model's REAL prompt_tokens
        (falling back to the chars/4 estimate before the first call), so the
        meter is accurate and grows with the tool observations in this turn."""
        payload = {}
        if ctx_stats:
            payload = {k: ctx_stats.get(k) for k in (
                "budget_tokens", "retrieved_memories", "final_messages",
                "final_tokens") if ctx_stats.get(k) is not None}
        real = chat_usage.get("prompt_tokens")
        if real and int(real) > 0:
            payload["final_tokens"] = int(real)
        if payload:
            payload["display"] = server.context_display(
                payload.get("final_tokens"), payload.get("budget_tokens"))
            on_event("context.built", session=sess["id"], **payload)

    work_steps = 0
    iters = 0
    used_tools = []
    # JAG-129A: completion loop state (see keepgoing.decide).
    from longrun.plan import keepgoing as _kg
    # JAG-431q: the stale-abort clear now happens at TURN START in the caller (httpapi/
    # api_v02), BEFORE the planner/compaction model calls. Clearing it here (after the
    # planner had already run) wiped a Stop pressed during that window, so the turn ran
    # to completion anyway.
    from longrun.model import runmetrics
    runmetrics.start(sess["id"], model=model)
    _abort_now = (lambda: _is_aborted(sess["id"]))  # JAG-129D: Stop kills the generation
    _kg_rounds = 0
    _kg_stop_reason = None
    _kg_prev = None
    _kg_stale = 0
    # JAG-402: dedicated budget for CLOSING open todos before a final answer is
    # accepted. The model must not stop with open todos: every step must be
    # marked done (with evidence) or superseded (with a reason) before the
    # final prose answer reaches the user.
    _close_todo_rounds = 0
    _close_todo_max = 4
    _fail_streak = 0        # JAG-178: consecutive failing tool calls
    _last_tool_hash = None  # JAG-178: detect a repeated identical call
    _tool_repeat = 0
    _last_failed_hash = None  # JAG-183: last FAILED (tool,args) -> verbatim re-run blocked
    _last_failed_err = ""
    _blocked_repeat = 0
    # JAG-272: a weak model can emit NONSENSE turns forever (malformed JSON /
    # unknown action / a bare promise). Without a cap it burned the whole iteration
    # budget. Stop after a few consecutive invalid turns with a clear reason.
    _invalid_streak = 0
    # JAG-189: a NEW user message must be able to supersede a stale plan. When
    # the turn OPENS with steps still open from an earlier request, do NOT force
    # the keepgoing loop back onto them — the model may simply answer the user.
    # The moment it re-engages the plan (write_todos/update_todos/replan_todos)
    # the flag clears and normal keepgoing resumes. Without this a fresh
    # instruction ("no todo list needed") was hijacked by the old list (session
    # a7d2794d8f88: "I'll continue on my own — 2/3 steps open" after a plain answer).
    try:
        _open0 = [n for n in (taskgraph.load(sess["id"]) or {}).get("nodes", [])
                  if n.get("status") in taskgraph.OPEN_STATUSES]
    except Exception:  # noqa: BLE001
        _open0 = []
    _user_pivot = bool(_open0)
    _pivot_state = {"synced": False}  # JAG-266: exactly one pivot sync round per turn
    _kg_started = time.time()
    _kg_last_tool = None
    _last_tool_ok = None
    # JAG-134/135: a SINGLE difficulty estimate (compute-optimal) feeds both the
    # best-of-N and the budget of the keepgoing rounds. The signals are the ones the harness
    # already has, recomputed on every round (a single estimator, no divergence).
    try:
        from longrun.plan import difficulty as _diff
        _kg_base = int(_kg.cfg().get("keepgoing_max") or 0)
    except Exception:  # noqa: BLE001
        _diff, _kg_base = None, None

    def _diff_signals(_msg, _used, _stale=0):
        try:
            _nodes = (taskgraph.load(sess["id"]) or {}).get("nodes", [])
        except Exception:  # noqa: BLE001
            _nodes = []
        _open_n = len([n for n in _nodes if n.get("status") in taskgraph.OPEN_STATUSES])
        return {"open_nodes": _open_n,
                "msg_words": len(str(_msg).split()),
                "tool_count": len(_used or []),
                "prev_error": (_last_tool_ok is False),
                "prev_no_progress": bool(_stale)}

    _diff_level = None
    if _diff is not None:
        try:
            _diff_level = _diff.estimate(_diff_signals(message, [], 0))["level"]
        except Exception:  # noqa: BLE001
            _diff_level = None

    def _cur_node():
        """JAG-167: id of the todo node being worked on right now (first `doing`,
        else first open), so persisted cards/injects nest under the right in-chat
        node on reload. Returns None when the graph is empty or fully closed."""
        try:
            _g = taskgraph.load(sess["id"]) or {}
        except Exception:  # noqa: BLE001
            return None
        # JAG-194: only the CURRENT plan — an abandoned open node from an old plan
        # must not capture a card/reply that belongs to the new task.
        for _st in ("doing", "todo", "blocked"):
            for _n in taskgraph.plan_nodes(_g):
                if _n.get("status") == _st:
                    return _n.get("id")
        return None

    def _after():
        """JAG-192: the transcript boundary a persisted card/inject belongs to.

        The turn's agentic history lives in the local `msgs` list and is flushed
        into `sess["messages"]` only at the END of the turn. So the boundary is
        the transcript length BEFORE the turn plus the messages already emitted
        this turn: `len(sess["messages"]) + (len(msgs) - _turn_base)`. Using only
        `len(sess["messages"])` (the old behaviour) froze every card of the turn
        on the same index and a reload stacked the whole turn at the top.
        """
        return len(sess.get("messages", [])) + (len(msgs) - _turn_base)

    def _inject(content, kind):
        """JAG-166: add a synthetic message to the LLM context AND surface it.

        The harness is the model's secretary: every nudge, observation and
        'continue' it feeds back is ALSO emitted as `harness.inject`, so the chat
        can show exactly what was injected — nothing is hidden.
        """
        msgs.append(harness_wrap(content))  # JAG-266: tag harness turns
        # NOTE: the payload key must NOT be `kind` — the SSE emitters take the
        # event name as a positional `kind`, so a `kind` kwarg collides.
        on_event("harness.inject", session=sess["id"], inject_kind=kind, text=content)
        # JAG-167: persist the injection so a reload rebuilds the in-chat tree.
        # The 'system' prompt is re-published every turn and is transient by
        # design → it is NOT persisted (avoids N identical copies in history).
        if kind != "system":
            persist_inject(sess, kind, content, node=_cur_node(), after=_after())

    # JAG-166: publish the assembled system prompt once per turn (collapsed in the
    # UI), so the operator can read the real prompt the model received.
    try:
        if msgs and msgs[0].get("role") == "system":
            _sys_txt = msgs[0].get("content") or ""
            _h = hash(_sys_txt)
            if _LAST_SYS_INJECT.get(sess["id"]) != _h:
                _LAST_SYS_INJECT[sess["id"]] = _h
                on_event("harness.inject", session=sess["id"], inject_kind="system",
                         text=_sys_txt)
    except Exception:  # noqa: BLE001 — must never break the turn
        pass
    # JAG-170: buffer the live reasoning so each persisted tool card carries the
    # chain-of-thought that led to it — otherwise the COTs between tool calls
    # vanish on reload (they were only ever streamed, never stored).
    _think_buf = {"t": ""}
    while iters < CHAT_TOOL_MAX_ITERS:
        iters += 1
        # JAG-164: the tool budget is PER keepgoing round, not per turn. Before
        # this the turn hard-stopped the moment `work_steps` hit `max_steps`
        # (8 real tool calls) — the loop exited, the forced-final path produced a
        # prose answer and the persistent todos stayed stuck in 'doing' (session
        # 66c66e3c702d: 8 shells, answer "…scaffold incompleto", n2 never closed).
        # Now, when the budget is spent with OPEN steps, the continuation loop
        # decides: refill the budget and push the model to close every step with
        # evidence, or stop for a typed reason (budget/no_progress/blocked).
        if tool_ctx and work_steps >= max_steps:
            _g = taskgraph.load(sess["id"]) or {}
            _nodes = _g.get("nodes", [])
            _open = [n for n in _nodes if n.get("status") in taskgraph.OPEN_STATUSES]
            # JAG-344: a PLAN-ONLY turn never continues. The master's own todos are
            # its DELEGATION plan, not work for it to close itself; the continuation
            # loop would otherwise nag it ("close every step with evidence") into
            # doing the whole job, bypassing the team. Stop here with a typed reason.
            if plan_only:
                _kg_stop_reason = "plan_only"
                on_event("plan.stopped", session=sess["id"], reason="plan_only",
                         open=len(_open), total=len(_nodes), rounds=_kg_rounds,
                         difficulty=_diff_level, duration_s=round(time.time() - _kg_started, 1))
                break
            _cur = _kg.state_hash(_nodes)
            # JAG-268: only a truly idle round (no tool AND no list change) is stale.
            _kg_stale = _next_stale(_kg_stale, _kg_prev, _cur, work_steps > 0)
            _kg_override = None
            if _diff is not None and _kg_base:
                try:
                    _kg_override = {"keepgoing_max": _diff.rounds_for(
                        _kg_base, _diff_signals(message, used_tools, _kg_stale))}
                except Exception:  # noqa: BLE001
                    _kg_override = None
            _dec = _kg.decide(open_nodes=len(_open), rounds=_kg_rounds, stale=_kg_stale,
                              started=_kg_started, aborted=_is_aborted(sess["id"]),
                              blocked=any(n.get("status") == "blocked" for n in _nodes),
                              steer=has_steer(sess["id"]), override=_kg_override)
            _dec = _pivot_decide(_user_pivot, _dec, len(_open), _pivot_state)
            if not _dec["continue"]:
                _kg_stop_reason = _dec["reason"]
                on_event("plan.stopped", session=sess["id"], reason=_dec["reason"],
                         open=len(_open), total=len(_nodes), rounds=_kg_rounds,
                         difficulty=_diff_level, duration_s=round(time.time() - _kg_started, 1))
                break
            _kg_rounds += 1
            _kg_prev = _cur
            work_steps = 0  # grant another round of tool calls
            on_event("plan.continuing", session=sess["id"], round=_kg_rounds,
                     open=len(_open), total=len(_nodes), difficulty=_diff_level)
            if _dec.get("reason") == "pivot_sync":
                _inject(_pivot_sync_text(len(_open), _open_todo_brief(sess)[1]), "pivot")
            else:
                _inject(
                    "CONTINUE — %d task(s) are still OPEN (the full list is in "
                    "'Harness state' at the end of your message). Work ONE step at a time: mark the current "
                    "step 'doing', do the work with a tool call, then mark it 'done' with "
                    "the concrete evidence via update_todos. Never redo a step already "
                    "marked [x]. Open now:\n%s"
                    % (len(_open), _open_todo_brief(sess)[1]), "continue")
            continue
        # JAG-127b: inject any steering message typed while this turn was running.
        for _s in drain_steer(sess["id"]):
            msgs.append({"role": "user", "content":
                         "[user steering — take this into account now] " + _s})
            on_event("chat.steer", session=sess["id"], text=_s, applied=True)
        collected = []

        def _capture(ch, t, _c=collected):
            # JAG-65: stream the model's REASONING live, so a tool-calling turn
            # shows progress instead of dead air; buffer only answer text so raw
            # tool-call JSON is never streamed to the user.
            if ch == "think":
                _think_buf["t"] += t   # JAG-170: remembered for the next card
                on_delta("think", t)
            else:
                _c.append((ch, t))

        answer, think, model = server.stream_with_fallback(msgs, model, "chat", _capture,
                                                           usage=chat_usage, cancel=_abort_now)
        _record_usage()
        _emit_context()  # JAG-98: live meter now uses the model's real count
        if _is_aborted(sess["id"]):
            # JAG-129D: Stop interrupted the generation. No tool may run
            # after an abort: the turn is closed immediately with an explicit outcome.
            publish("chat.interrupted", session=sess["id"])
            # JAG-175: an abort can cut the model mid tool-call, so the buffered
            # answer may be RAW tool-call JSON. Never stream/persist that as the
            # user's reply — fall back to a neutral stop note.
            if answer and not _looks_like_json_action(answer):
                for ch, t in collected:
                    on_delta(ch, t)
                final_answer = answer
            else:
                final_answer = "⏹ Interrupted by the user."
                on_delta("answer", final_answer)
            _kg_stop_reason = "user_stop"
            break
        # JAG-132/134: adaptive best-of-N. Only when the first sample is NOT usable
        # (malformed tool-call JSON) are more samples spent and the
        # best picked with the deterministic ranker (prm.rank_text). N grows with the
        # estimated task difficulty (compute-optimal). n=1 -> zero overhead.
        try:
            from longrun.plan import bestofn as _bn
            _bN = _bn.n_of(signals=_diff_signals(message, used_tools, _kg_stale))
        except Exception:  # noqa: BLE001
            _bN = 1
        if _bN > 1 and _looks_like_json_action(answer):
            _cands = [answer]
            for _ in range(_bN - 1):
                try:
                    _a2, _t2, _m2 = server.stream_with_fallback(
                        msgs, model, "chat", lambda ch, t: None,
                        usage=chat_usage, cancel=_abort_now)
                except Exception:  # noqa: BLE001
                    break
                _cands.append(_a2)
                if (_a2 or "").strip() and not _looks_like_json_action(_a2):
                    break  # a usable candidate already exists: stop spending compute
            _best, _scores = _bn.choose(_cands)
            if _best is not None and _best != answer:
                on_event("bestofn.chosen", session=sess["id"], n=len(_cands),
                         scores=[round(s, 3) for _, s in _scores])
                answer = _best
        act = _extract_action(answer)
        if isinstance(act, dict) and act.get("action") == "write_todos":
            _user_pivot = False   # JAG-189: the model re-engaged the plan
            n = _apply_chat_todos(sess, act, on_event, after=_after())
            _invalid_streak = 0
            msgs.append({"role": "assistant", "content": answer})
            _on, _brief = _open_todo_brief(sess)
            _inject(
                "Task list saved (%d new step(s)) — it is YOURS to keep current. "
                "OPEN (%d):\n%s\nA step must describe work STILL TO DO: if you already "
                "did that work in this turn, mark it 'done' NOW with the concrete evidence "
                "— never leave finished work as an open step. Otherwise start with the "
                "FIRST open step: mark it 'doing' before you start it, do the work, then "
                "'done' with concrete evidence."
                % (n, _on, _brief), "nudge")
            continue
        if isinstance(act, dict) and act.get("action") in ("update_todos", "replan_todos"):
            # JAG-75: the model advances its own plan mid-run (in_progress → done
            # with evidence), or briefly re-plans. Then it must resume the plan.
            _user_pivot = False   # JAG-189: the model re-engaged the plan
            _invalid_streak = 0
            _node_here = _cur_node()   # JAG-190: nest the card where it happened
            if act["action"] == "update_todos":
                _apply_chat_todo_updates(sess, act, on_event, node=_node_here,
                                         after=_after())
                nudge = _nudge_open_todos(sess)
            else:
                _apply_chat_replan(sess, act, on_event, node=_node_here,
                                   after=_after())
                nudge = ("Plan updated. Now resume following the plan from where you "
                         "left off; do not re-plan again unless something really changed.")
            msgs.append({"role": "assistant", "content": answer})
            _inject(nudge, "nudge")
            continue
        if isinstance(act, dict) and act.get("action") == "subagent":
            # JAG-189: synchronous delegation — spawn ONE child run, wait for it,
            # feed its summary back. Counts as a real work step (it is real work).
            if plan_only:
                # JAG-344: the master's plan turn must not spawn subagents either.
                msgs.append({"role": "assistant", "content": answer})
                _inject("SYSTEM (harness) — PLAN-ONLY turn: spawning subagents is not "
                        "allowed while planning. Record the plan and stop.", "nudge")
                work_steps += 1
                continue
            work_steps += 1
            used_tools.append("subagent")
            _th = str(act.get("thought") or "").strip()
            if _th:
                _think_buf["t"] += _th + "\n"
                on_delta("think", _th + "\n")
            obs = _apply_chat_subagent(sess, act, on_event, node=_cur_node(),
                                       after=_after())
            msgs.append({"role": "assistant", "content": answer})
            _inject(obs + "\n\nContinue: call the next tool, or report the result.",
                    "observation")
            continue
        tc = _chat_tool_call(act, api_v02) if tool_ctx else None
        if tc:
            # JAG-127b: surface the model's own `thought` for this step as a
            # "think" delta BEFORE the tool card — otherwise, with models that do
            # not emit reasoning_content, the chat showed tool cards back-to-back
            # with no visible reasoning in between ("I don't see thinking").
            _th = str((act or {}).get("thought") or "").strip()
            if _th:
                _think_buf["t"] += _th + "\n"   # JAG-170: kept with the card
                on_delta("think", _th + "\n")
            tool, args = tc
            # JAG-344: a PLAN-ONLY turn may INSPECT (fs.read / skills) but NEVER mutate.
            # Refuse shell / fs.write / fs.edit / … so the master cannot execute the
            # teammates' work; hand back a directive to plan and stop.
            if plan_only and tool not in PLAN_ONLY_TOOLS:
                msgs.append({"role": "assistant", "content": answer})
                _inject(_plan_only_refusal(tool), "nudge")
                work_steps += 1
                continue
            # JAG-183: HARD anti-loop guard. An IDENTICAL call that already FAILED
            # is NOT executed again: it burned the step budget and led to a resigned
            # stop (v176: 3x `adb ... input tap` -> exit 1 -> "mi fermo"). We refuse
            # it and hand back a directive so the model MUST change route, read a
            # skill, or ask ONE precise question.
            _call_h = _kg.tool_hash(tool, args)
            if _call_h == _last_failed_hash:
                _blocked_repeat += 1
                msgs.append({"role": "assistant", "content": answer})
                _inject(_repeat_block_note(tool, _last_failed_err, _blocked_repeat,
                                           _skill_hints(tool + " " + (_last_failed_err or ""))),
                        "nudge")
                continue
            work_steps += 1
            used_tools.append(tool)
            on_event("tool.call", session=sess["id"], tool=tool, args=args, inline=True)
            try:
                # JAG-80: a `required` tool must never freeze the turn. We wait a
                # SHORT, bounded time (CHAT_APPROVAL_WAIT) so a quick tap on the
                # inline Approve card still executes the tool; if nobody decides,
                # the model gets an observation and continues. The old code waited
                # the full 300s and the mobile SSE died = "si blocca".
                res = api_v02.gated_call(tool, args, run_id=sess["id"],
                                         timeout=CHAT_APPROVAL_WAIT,
                                         workspace=_chat_workspace(sess),
                                         obs_max=CHAT_OBS_FULL)
                status = res.get("status")
                obs = res.get("observation") or res.get("error") or res.get("status") or ""
                if status in ("pending", "expired"):
                    rec = res.get("approval") or {}
                    obs = ("Action '%s' NOT executed: approval %s (id %s). The card is "
                           "in the chat: the user can approve it and retry, or tell me "
                           "to proceed. Do NOT repeat the same call now; continue "
                           "with something else or explain to the user what is needed."
                           % (tool, status, rec.get("id", "?")))
                elif status == "denied":
                    obs = "Action '%s' DENIED by the user." % tool
                ok = status == "executed"
                sub = res.get("result") or {}
                # JAG-178: `ok` means "the tool executed"; a tool can execute and
                # still FAIL (nonzero exit / ok:false). Track failure separately.
                _tool_failed = ((not ok) or (sub.get("ok") is False)
                                or (sub.get("exit_code") not in (None, 0)))
                # JAG-96: persist the card so cold-start UIs rebuild the transcript.
                persist_tool_card(sess, tool, ok, args=args,
                                  result=sub.get("stdout") or obs or "",
                                  error=sub.get("stderr") or "",
                                  exit_code=sub.get("exit_code"),
                                  backend=sub.get("backend") or "harness",
                                  node=_cur_node(), think=_think_buf["t"].strip(),
                                  after=_after())
                _think_buf["t"] = ""   # JAG-170: fresh CoT for the next action
                on_event("tool.result", session=sess["id"], **_tool_event(
                    tool, ok, args=args, output=(sub.get("stdout") or obs or ""),
                    exit_code=sub.get("exit_code"),
                    backend=sub.get("backend") or "harness",
                    inline=True, summary=("error" if not ok else "")))
            except Exception as e:  # noqa: BLE001 — a tool failure must not kill chat
                obs, ok = "tool error: %s" % e, False
                _tool_failed = True   # JAG-178: a raised tool error is a failure too
                persist_tool_card(sess, tool, False, args=args, error=str(e)[:200],
                                  backend="harness", node=_cur_node(),
                                  think=_think_buf["t"].strip(), after=_after())
                _think_buf["t"] = ""
                on_event("tool.result", session=sess["id"], **_tool_event(
                    tool, False, args=args, output=str(e)[:200],
                    backend="harness", inline=True, summary="error"))
            # JAG-134: feeds the prev_error signal of the difficulty estimate.
            _last_tool_ok = bool(ok)
            _invalid_streak = 0
            # JAG-88: an oversized observation goes to a file (referenced) rather
            # than being truncated into the context — nothing is lost.
            obs = str(obs)
            # JAG-178: track consecutive failures + repeated identical calls, and
            # COACH a stuck model (socratic) instead of the generic continue.
            if _call_h == _last_tool_hash:
                _tool_repeat += 1
            else:
                _tool_repeat = 0
            _last_tool_hash = _call_h
            _fail_streak = (_fail_streak + 1) if _tool_failed else 0
            # JAG-183: remember the (tool,args) of a FAILED call so the next verbatim
            # re-issue is blocked (a SUCCESS clears it — only failed calls are frozen).
            if _tool_failed:
                _last_failed_hash = _call_h
                _last_failed_err = obs[:300]
            else:
                _last_failed_hash = None
            if len(obs) <= CHAT_TOOL_OBS_LIMIT and (_fail_streak >= 2 or _tool_repeat >= 1):
                note = _stuck_note(tool, obs, _fail_streak, _tool_repeat,
                                   _skill_hints(tool + " " + obs))
            elif len(obs) > CHAT_TOOL_OBS_LIMIT:
                note = _offload_observation(sess, tool, obs)
            else:
                note = ("Observation for tool %s:\n%s\n\n"
                        "Continue: call the next tool, or report the result. Keep your "
                        "task list current (mark a finished step done with evidence)."
                        % (tool, obs))
            msgs.append({"role": "assistant", "content": answer})
            _inject(note, "observation")
            continue
        if _term_action(act):
            # JAG-278: a made-up "I am done" envelope — take its text as the answer.
            _txt = ""
            for _k in ("text", "content", "answer", "message", "reply", "output", "result"):
                if isinstance(act.get(_k), str) and act[_k].strip():
                    _txt = act[_k].strip()
                    break
            if _txt:
                final_answer = _txt
                on_delta("answer", _txt)
                break
        if isinstance(act, dict) and act:
            if not _looks_like_action_dict(act):
                # JAG-304: a JSON OBJECT with no action/tool key is an ARTIFACT the
                # model means as its answer (a schema, a response envelope, a data
                # record) — surface it instead of rejecting it as a stray action.
                # That rejection forced needless "not a valid action" retries and
                # could halt the turn after four in a row (observed on J2: the
                # coordinator's own Book JSON-Schema deliverable was rejected).
                final_answer = answer
                _final_is_artifact = True
                on_delta("answer", answer)
                break
            # stray JSON the model emitted in a schema we do not recognise: never
            # show it to the user — nudge it back to a valid tool call or prose.
            msgs.append({"role": "assistant", "content": answer})
            _invalid_streak += 1
            if _invalid_streak >= 4:
                _kg_stop_reason = "no_valid_action"
                on_event("plan.no_valid_action", session=sess["id"], streak=_invalid_streak)
                break
            try:
                _snip = json.dumps(act, ensure_ascii=False)[:220]
            except Exception:  # noqa: BLE001
                _snip = str(act)[:220]
            _inject(
                "That was not a valid action. You emitted: " + _snip + "\n"
                'Emit either {"action":"tool","tool":"<name>","args":{...}} for a real '
                "tool, a top-level harness action (write_todos / update_todos / "
                "replan_todos), or answer the user in plain prose (no JSON).", "retry")
            continue
        if _looks_like_json_action(answer):
            # JAG-64: malformed/TRUNCATED tool-call JSON (extract_json failed, so
            # `act` is None). Never leak it into the chat — ask for a clean retry.
            msgs.append({"role": "assistant", "content": answer})
            _invalid_streak += 1
            if _invalid_streak >= 4:
                _kg_stop_reason = "no_valid_action"
                on_event("plan.no_valid_action", session=sess["id"], streak=_invalid_streak)
                break
            _inject(
                "That JSON was invalid or incomplete (it did not parse). "
                "Re-emit a VALID "
                '{"action":"tool","tool":"<name>","args":{...}} with all '
                "braces closed, or answer the user in plain prose. Never "
                "show JSON to the user.", "retry")
            continue
        if _looks_like_promise(answer) and not announce_nudged:
            # JAG-74: the model promised an action ("I'll load another skill…") but
            # called no tool this turn — nudge it ONCE to actually act or conclude.
            announce_nudged = True
            msgs.append({"role": "assistant", "content": answer})
            _inject(
                "You announced an action but did not call any tool. Either "
                'call it NOW with {"action":"tool","tool":"<name>","args":{...}}, '
                "or — if there is nothing left to do — reply with the final "
                "result in plain prose. Do not just repeat the announcement.", "nudge")
            continue
        if tool_ctx:
            # JAG-129A: the harness (the "secretary") decides whether the agent can really
            # close. With open steps it re-injects the list and CONTINUES.
            # JAG-173 (rev): the MODEL owns the todo list — the standard contract
            # (Claude Code TodoWrite): the agent marks a step 'doing' before it
            # starts and 'done' with evidence when it is really finished. The harness
            # only ENFORCES and REMINDS; it never auto-closes a step, because closing
            # a step that is not truly done is "lying about completion".
            _g = taskgraph.load(sess["id"]) or {}
            _nodes = _g.get("nodes", [])
            _open = [n for n in _nodes if n.get("status") in taskgraph.OPEN_STATUSES]
            _cur = _kg.state_hash(_nodes)
            # JAG-268: see the note at the budget branch — a round that ran tools is
            # NOT 'no progress' just because the list hash did not move.
            _kg_stale = _next_stale(_kg_stale, _kg_prev, _cur, work_steps > 0)
            # JAG-134: continuation budget recomputed from the current signals.
            _kg_override = None
            if _diff is not None and _kg_base:
                try:
                    _kg_override = {"keepgoing_max": _diff.rounds_for(
                        _kg_base, _diff_signals(message, used_tools, _kg_stale))}
                except Exception:  # noqa: BLE001
                    _kg_override = None
            _dec = _kg.decide(open_nodes=len(_open), rounds=_kg_rounds, stale=_kg_stale,
                              started=_kg_started, aborted=_is_aborted(sess["id"]),
                              blocked=any(n.get("status") == "blocked" for n in _nodes),
                              steer=has_steer(sess["id"]), override=_kg_override)
            # JAG-266: on a pivot, grant ONE sync round (remind the model it left
            # todos open) instead of stopping silently; after it, stop as user_pivot.
            _dec = _pivot_decide(_user_pivot, _dec, len(_open), _pivot_state)
            # JAG-171: with autocontinue OFF the harness does not insist — the
            # first stop with OPEN todos goes straight to the human gate.
            # JAG-266: but never suppress the single pivot sync round.
            if (_open and _dec.get("reason") != "pivot_sync"
                    and not bool((_kg.cfg(_kg_override) or {}).get("autocontinue", True))):
                _dec = {"continue": False, "reason": "need_input"}
            # JAG-402: the model must NOT stop with open todos IT OWNS this turn.
            # A final prose answer while steps are still open is REJECTED: the
            # model is forced to close every step (done with evidence, or
            # superseded with a reason) before its answer reaches the user.
            # This overrides the normal keepgoing stop reasons (budget /
            # no_progress) up to a small dedicated budget so a weak model cannot
            # "escape" by emitting a final answer and leaving the list dangling.
            # EXCEPTION (JAG-189): a stale plan from a PREVIOUS turn
            # (`_user_pivot` still True = model never re-engaged the list this
            # turn) may be answered directly — the user's new request supersedes
            # the old plan and the model is not forced to close it.
            if (_open and not _user_pivot and not _is_aborted(sess["id"])
                    and _close_todo_rounds < _close_todo_max):
                _dec = {"continue": True, "reason": "close_todos"}
            if _dec["continue"]:
                _kg_rounds += 1
                if _dec.get("reason") == "close_todos":
                    _close_todo_rounds += 1
                _kg_prev = _cur
                for _s in drain_steer(sess["id"]):
                    msgs.append({"role": "user", "content":
                                 "[user steering — take this into account now] " + _s})
                    on_event("chat.steer", session=sess["id"], text=_s, applied=True)
                on_event("plan.continuing", session=sess["id"], round=_kg_rounds,
                         open=len(_open), total=len(_nodes), difficulty=_diff_level)
                msgs.append({"role": "assistant", "content": answer})
                if _dec.get("reason") == "pivot_sync":
                    _inject(_pivot_sync_text(len(_open), _open_todo_brief(sess)[1]), "pivot")
                elif _dec.get("reason") == "close_todos":
                    _inject(
                        "STOP — your final answer was REJECTED because your TASK LIST "
                        "still has %d open step(s). You MUST close every step BEFORE "
                        "you can answer the user. For each open step do ONE of: "
                        "(a) mark it 'done' with the concrete evidence (the command "
                        "you ran and its result); or (b) ONLY if it is PERMANENTLY "
                        "unneeded, mark it 'superseded' with a SPECIFIC reason saying "
                        "WHY. Use update_todos for EVERY open step — do not skip any. "
                        "When the list is fully closed (0 open), your next message will "
                        "be accepted as the final answer. Open now:\n%s"
                        % (len(_open), _open_todo_brief(sess)[1]), "continue")
                else:
                    _inject(
                        "CONTINUE — your TASK LIST still has %d open step(s), and it is "
                        "YOURS (the full list is in 'Harness state' at the end of your message): mark the step "
                        "you are working on 'doing', and when it is REALLY finished mark it "
                        "'done' with the concrete evidence (the command you ran and its "
                        "result) via update_todos. One step at a time. NEVER redo a step "
                        "already marked [x]. Open now:\n%s"
                        % (len(_open), _open_todo_brief(sess)[1]), "continue")
                continue
            _kg_stop_reason = _dec["reason"]
            on_event("plan.stopped", session=sess["id"], reason=_dec["reason"],
                     open=len(_open), total=len(_nodes), rounds=_kg_rounds,
                     difficulty=_diff_level,
                     duration_s=round(time.time() - _kg_started, 1))
            # JAG-171: HUMAN IN THE LOOP — never end on prose with open todos; ask
            # the operator how to proceed (continue / close / replan / stop).
            # JAG-189: but NOT on a user_pivot stop — the user is actively
            # chatting, so the reply is theirs; the paused plan needs no gate.
            # JAG-295: and NEVER on a headless turn (a JOB/routine, autonomous):
            # there is nobody to answer, so the turn just stops.
            if _kg.hitl_gate(_dec["reason"], _open, autonomous):
                _hitl = {"reason": _dec["reason"],
                         "open": [{"id": n.get("id"), "label": n.get("label", "")}
                                  for n in _open[:8]]}
                on_event("hitl.request", session=sess["id"], reason=_dec["reason"],
                         open=_hitl["open"], total=len(_nodes), rounds=_kg_rounds)
        for ch, t in collected:
            on_delta(ch, t)
        final_answer, think = answer, think
        break
    if not final_answer and not _is_aborted(sess["id"]):
        # JAG-78b: the loop ran out of tool steps without a prose answer — force
        # one, but BUFFER it. Streaming it live leaked raw tool-call JSON into
        # the user's chat bubble when the model kept acting instead of answering
        # (the JSON guard below only protected the PERSISTED text, not the stream).
        # JAG-84: a forced "final" that is only an ANNOUNCEMENT ("I'm proceeding with…") is
        # not an answer — retry (bounded) asking for the RESULT, not a promise.
        _inject(
            "Answer the user now in plain text. Do not emit JSON, and do NOT "
            "announce future work: report the RESULT you already have (what "
            "you did, what you found, what is still missing).", "final")
        for _try in range(3):
            forced = []

            def _cap_final(ch, t, _c=forced):
                if ch == "think":
                    on_delta("think", t)
                else:
                    _c.append((ch, t))

            final_answer, think, model = server.stream_with_fallback(msgs, model, "chat",
                                                                     _cap_final, usage=chat_usage,
                                                                     cancel=_abort_now)
            _record_usage()
            if ((final_answer or "").strip() and not _looks_like_json_action(final_answer)
                    and not _looks_like_promise(final_answer)):
                for ch, t in forced:  # only a REAL reply reaches the user live
                    on_delta(ch, t)
                break
            msgs.append({"role": "assistant", "content": final_answer or ""})
            _inject(
                "That was still an announcement/JSON, not a result. Give the "
                "final RESULT in plain prose now.", "final")
        else:
            # last resort: stream whatever prose we have (never leak JSON)
            if final_answer and not _looks_like_json_action(final_answer):
                for ch, t in forced:
                    on_delta(ch, t)
    answer = final_answer or answer
    if trace:
        trace.span("llm.chat", model=model, context=ctx_stats)
        trace.llm_call(msgs, answer + think)
    meta = {"model": model, "node": _cur_node()}
    content = answer.strip()
    if _hitl:
        # JAG-171: the turn stopped with open todos → the visible reply is the
        # human gate, not the model's prose report.
        content = ("⏸ In pausa: ci sono %d passi aperti e serve la tua scelta "
                   "(vedi la card HUMAN IN THE LOOP)." % len(_hitl["open"]))
        meta = {"model": model, "hitl": True, "node": _cur_node(),
                "open": len(_hitl["open"]), "reason": _hitl["reason"],
                "hitl_open": _hitl["open"]}   # JAG-295: replayable card payload
    if (_looks_like_json_action(content) and not _final_is_artifact) or not content:
        # JAG-64/78b: last-resort guard — never show/persist raw tool-call JSON
        # (or an empty turn). Summarise the plan state instead of leaking JSON.
        # JAG-304: a confirmed JSON artifact (checked via _looks_like_action_dict)
        # is the model's ANSWER and must pass this guard untouched.
        try:
            _g = taskgraph.load(sess["id"])
            _nodes = (_g or {}).get("nodes", [])
            _done = sum(1 for x in _nodes if x.get("status") == "done")
        except Exception:  # noqa: BLE001
            _nodes, _done = [], 0
        content = (("Plan updated: %d/%d steps completed. Tell me how to proceed "
                    "or let me continue." % (_done, len(_nodes))) if _nodes else "Done.")
        meta = {"model": model, "synthesised": True,
                "reason": "model emitted JSON instead of a prose reply"}
    # JAG-172: PERSIST the agentic history of this turn (tool calls, observations,
    # nudges) into the transcript. Before, only the final assistant reply was
    # stored, so every tool observation was discarded at the turn boundary: the
    # model lost its own work between turns and the ctx meter measured a prompt
    # that never grew (session test: 15 msgs / 5 KB vs 161 tool cards → a
    # genuinely full context read as 2%). Marked `internal` so the UI keeps
    # rendering these from tool_cards/injects (no duplicate bubbles) while
    # `context_engine` still counts them and `_completion_body` filters the
    # marker out before the provider call.
    try:
        _extra = [dict(_m, internal=True) for _m in msgs[_turn_base:]
                  if isinstance(_m, dict) and _m.get("role") in ("user", "assistant")]
        if _extra:
            sess.setdefault("messages", []).extend(_extra)
            save_session(sess)
    except Exception as _exc:  # noqa: BLE001 — persistence must never break a turn
        publish("graph.error", kind="transcript.persist", error=str(_exc))
    reply = append_message(sess, "assistant", content, reasoning=think.strip() or None,
                           meta=meta)
    try:
        runmetrics.finish(sess["id"], outcome=("user_abort" if _is_aborted(sess["id"]) else "done"),
                          stop_reason=_kg_stop_reason, iterations=_kg_rounds,
                          steps=work_steps,
                          prompt_tokens=_total_prompt,
                      completion_tokens=_total_completion,
                      tokens=_total_prompt + _total_completion,
                          model=model, difficulty=_diff_level)
        publish("run.metrics", session=sess["id"], metrics=runmetrics.get(sess["id"]))
    except Exception:  # noqa: BLE001 — metrics must never break a turn
        pass
    publish("chat.done", session=sess["id"], message_id=len(sess["messages"]),
            model=model, think_chars=len(think), error=bool(meta.get("error")))
    try:  # JAG-133: records the turn's tool sequence for skill mining
        from longrun.util import selfevolve as _se
        if used_tools:
            # per-TURN key (not per-session): so mining sees sequences
            # repeated across different runs instead of always overwriting the same record.
            _se.record("%s#%.3f" % (sess["id"], time.time()), used_tools)
    except Exception:  # noqa: BLE001 — history must never break a turn
        pass
    # JAG-128B: end-of-turn nudge — when the turn used many tools (or
    # errored), it invites evaluating what to persist (free memory or
    # a rule proposal via the `improve` tool). Never blocking: any
    # exception is swallowed so it does not break the turn.
    try:
        from longrun.util import improve as improve_mod
        if improve_mod.should_nudge(used_tools=len(used_tools or []),
                                    errored=bool(meta.get("error"))):
            publish("improve.nudge", session=sess["id"],
                    hint="evaluate what to persist: memory (free) or rule proposal (improve tool)")
    except Exception:  # noqa: BLE001 — the nudge must never break a turn
        pass
    # JAG-129A: safety net — if the turn ends with open steps (e.g. after
    # an abort), it still publishes the end-of-turn metrics. `plan.incomplete`
    # coexists with `plan.stopped` emitted by the loop.
    try:
        _g = taskgraph.load(sess["id"])
        _nodes = (_g or {}).get("nodes", [])
        # JAG-308: count only TRULY-open steps. `status not in ("done","cancelled")`
        # also counted `superseded` (a CLOSED state), so a session whose every step
        # was closed still reported "N open" and re-nagged on the next turn.
        _open = [n for n in _nodes if n.get("status") in taskgraph.OPEN_STATUSES]
        if _open:
            publish("plan.incomplete", session=sess["id"], open=len(_open),
                    total=len(_nodes),
                    items=[str(n.get("label", "")) for n in _open][:12])
    except Exception:  # noqa: BLE001
        pass
    try:  # JAG-69: deterministic Stop hooks at the end of the turn
        from longrun.tools import hooks
        hooks.run("Stop", run_id=sess["id"], observation=content)
    except Exception:  # noqa: BLE001 — a hook must never break a turn
        pass
    # JAG-93: post-turn reflection (self-improvement). Runs after the reply is
    # persisted so it can never delay or corrupt the user-visible turn.
    try:
        maybe_reflect(sess, message, answer, work_steps > 0, model)
    except Exception:  # noqa: BLE001
        pass
    return reply, model


def generate_plan(goal, model=None):
    sess = {"id": "planner", "title": "planner", "created": time.time(), "messages": []}  # ephemeral
    sys = system_prompt() + "\n\n" + PLANNER_PROMPT
    msgs = [{"role": "system", "content": sys}, {"role": "user", "content": goal}]
    model = model or routing.pick("planner") or default_model()
    trace = RunTrace("plan", goal=goal, model=model)
    answer, think = _router_stream(msgs, model, lambda ch, t: publish(
        "plan.think", channel=ch, text=t))
    trace.span("llm.plan", model=model)
    trace.llm_call(msgs, answer + think)
    data = extract_json(answer)
    steps = []
    if isinstance(data, list):
        for item in data:
            if isinstance(item, dict) and item.get("title"):
                steps.append({"id": uuid.uuid4().hex[:6], "title": str(item["title"])[:120],
                              "detail": str(item.get("detail", ""))[:300], "done": False})
    elif isinstance(data, dict) and data.get("title"):
        steps = [{"id": uuid.uuid4().hex[:6], "title": str(data["title"])[:120],
                  "detail": str(data.get("detail", ""))[:300], "done": False}]
    plan = {"goal": goal, "steps": steps, "updated": round(time.time(), 3)}
    write_json(_store_path("plan.json"), plan)
    publish("plan.update", goal=goal, steps=steps, generated=True)
    trace.finish("done")
    return plan, answer, think, trace.id


AGENT_ACTIONS = ("write_todos", "plan_step", "complete_plan_step", "add_task",
                 "complete_task", "subagent", "note", "finish")

AGENT_PROMPT = (
    "You are the agent loop of the Longrun harness. Given the goal and the "
    "current harness state, decide ONE next action. Respond with ONLY a JSON "
    'object: {"thought": "<brief reasoning>", "action": "write_todos|'
    'plan_step|complete_plan_step|add_task|complete_task|subagent|note|finish", '
    '"todos": [{"label": "...", "deps": []}] (for write_todos), '
    '"title": "<for plan_step/add_task>", "id": "<for '
    'complete_plan_step/complete_task>", "detail": "<optional>", '
    '"goal": "<the subtask>" and "max_steps": 4 (for subagent — delegate ONE '
    'self-contained subtask to a child run and get its summary back), '
    '"summary": "<required for finish>"}.'
)


def apply_agent_action(act, run_id=None, session=None):
    """Apply a parsed agent action; returns observation text.

    v0.6: when a run_id is given, the action is mirrored onto the run's task
    graph (plan_step/complete_plan_step/add_task/complete_task → nodes).
    """
    action = act.get("action")
    plan, tasks = load_plan(), load_tasks()
    if action == "plan_step":
        if not plan.get("goal"):
            plan["goal"] = act.get("detail") or act.get("title") or "goal"
        step = {"id": uuid.uuid4().hex[:6], "title": str(act.get("title", "step"))[:120],
                "detail": str(act.get("detail", ""))[:300], "done": False}
        plan.setdefault("steps", []).append(step)
        save_plan(plan)
        return _mirror_graph(run_id, act, "plan step added: %s (%s)" % (step["title"], step["id"]),
                             session)
    if action == "complete_plan_step":
        for s in plan.get("steps", []):
            if s.get("id") == act.get("id") or s.get("title") == act.get("title"):
                s["done"] = True
                save_plan(plan)
                return _mirror_graph(run_id, act,
                                     "plan step completed: %s" % s["title"], session)
        return "plan step not found"
    if action == "add_task":
        t = {"id": uuid.uuid4().hex[:6], "title": str(act.get("title", "task"))[:120],
             "status": "todo", "created": round(time.time(), 3)}
        tasks.setdefault("tasks", []).append(t)
        save_tasks(tasks)
        return _mirror_graph(run_id, act, "task added: %s (%s)" % (t["title"], t["id"]), session)
    if action == "complete_task":
        for t in tasks.get("tasks", []):
            if t.get("id") == act.get("id") or t.get("title") == act.get("title"):
                t["status"] = "done"
                t["done_ts"] = round(time.time(), 3)
                save_tasks(tasks)
                return _mirror_graph(run_id, act, "task completed: %s" % t["title"], session)
        return "task not found"
    if action == "write_todos":
        return _mirror_graph(run_id, act, "write_todos: graph updated", session)
    if action == "subagent":
        goal = str(act.get("goal") or act.get("detail") or "").strip()
        if not goal:
            return "subagent error: goal required"
        try:
            max_steps = int(act.get("max_steps", 4))
        except (TypeError, ValueError):
            max_steps = 4
        from longrun.agent import subagent as _sub
        result = _sub.spawn(goal, parent_run_id=run_id, max_steps=max_steps,
                            model=act.get("model"),
                            depth=_sub.depth_of(run_id) + 1)
        if result.get("error"):
            return "subagent error: %s" % result["error"]
        if run_id:
            try:
                graph = taskgraph.ensure(run_id, session_id=session)
                taskgraph.add_node(graph, goal, source="subagent",
                                   child_run_id=result["run_id"])
            except Exception as e:  # noqa: BLE001 — linking must never break a run
                publish("graph.error", run=run_id, error=str(e))
        return "subagent spawned: %s (goal: %s, max_steps=%d)" % (
            result["subagent_id"], goal[:80], max_steps)
    if action == "note":
        publish("agent.note", text=str(act.get("detail") or act.get("title") or "")[:400])
        return "noted"
    return "unknown action"


def _mirror_graph(run_id, act, observation, session=None):
    """Mirror an applied action onto the run graph, with the observation as evidence."""
    if run_id:
        try:
            taskgraph.map_action(run_id, act, observation=observation, session_id=session)
        except Exception as e:  # noqa: BLE001 — mapping must never break a run
            publish("graph.error", run=run_id, error=str(e))
    return observation


def _agent_history(actions, limit=8):
    """JAG-348: the agent loop's OWN recent steps as text for the next iteration.

    The chat loop learned this the hard way (JAG-61): the observation produced at
    step N MUST be visible at step N+1, or the model re-derives everything, never
    learns a tool/subagent result, cannot correct a rejected action and loops
    forever. The agent loop rebuilt its messages from scratch every iteration and
    dropped every observation -> an open loop. This renders the recent history.
    """
    if not actions:
        return ""
    rows = []
    for a in actions[-limit:]:
        txt = (a.get("observation") or a.get("summary") or "").strip()
        rows.append("  %s. %s -> %s" % (a.get("i", "-"), a.get("action", "?"), txt[:300]))
    return ("\n\nYour previous steps (build on these; do NOT repeat a step that "
            "already failed):\n" + "\n".join(rows))


def agent_run(goal, max_steps=6, model=None, on_event=None, trace=None, run_state=None,
              workspace=None):
    """Sense-think-act loop. No shell, no filesystem writes except harness stores."""
    if on_event is None:
        on_event = lambda kind, **d: publish(kind, **d)
    model = model or default_model()
    # JAG-111: every run is abortable via /api/agent/control, and its id travels
    # in `agent.start` so the WebUI/app stop button can target it.
    st = run_state or api_v02.new_run(goal, model, max_steps)
    on_event("agent.start", goal=goal, max_steps=max_steps, run=st.id, model=model)
    if trace is None:
        trace = RunTrace("agent", goal=goal, model=model)
        trace.span("agent.start", goal=goal, max_steps=max_steps)
    trace_model = model
    llm_log = []

    def _llm(msgs, answer):
        trace.span("llm.step", model=trace_model)
        tin, tout = trace.llm_call(msgs, answer)
        llm_log.append((tin, tout))

    # v0.6: the run's FIRST action is a model-generated write_todos call, which
    # seeds the per-run task graph that the agent loop then advances.
    try:
        start_run_graph(trace.id, goal, None, model, on_event=on_event)
    except Exception as e:  # noqa: BLE001
        publish("graph.error", run=trace.id, error=str(e))

    actions = []
    aborted = False
    rb = rules_context(ws=workspace)  # JAG-114/115: the agent loop honours the same rules
    from longrun.model import prompt as prompt_mod  # JAG-128A: prompt-map + capability in the agent loop too
    try:
        for i in range(max_steps):
            api_v02.checkpoint(st)  # JAG-111: honour pause / abort between steps
            sys = (prompt_mod.prompt_map_text() + "\n\n" + prompt_mod.capability_text()
                   + "\n\n" + system_prompt() + "\n\n" + self_summary() + "\n\n" + AGENT_PROMPT
                   + "\n\n" + RULES_POLICY + ("\n" + rb if rb else ""))
            # JAG-276: the live task list rides in the user turn, not the system prompt.
            # JAG-348: ALSO carry the agent's own previous steps + observations, so the
            # model learns from a tool/subagent result and can correct a rejected action
            # instead of re-deriving the same mistake every iteration (open loop).
            msgs = [{"role": "system", "content": sys},
                    {"role": "user", "content": "Goal: %s (iteration %d/%d)\n\n%s%s"
                     % (goal, i + 1, max_steps, state_block(graph_key=trace.id),
                        _agent_history(actions))}]
            on_event("agent.iteration", i=i + 1, of=max_steps)
            answer, think = _router_stream(msgs, model, lambda ch, t: on_event("agent.think", channel=ch, text=t))
            _llm(msgs, answer + think)
            act = _normalize_action(extract_json(answer)) or {}
            if not isinstance(act, dict) or not act.get("action"):
                act = {"thought": answer[:200], "action": "note", "detail": answer[:400]}
            thought = str(act.get("thought", ""))[:400]
            action = act.get("action")
            on_event("agent.thought", i=i + 1, thought=thought, action=action)
            if action == "finish":
                summary = str(act.get("summary", ""))[:600]
                on_event("agent.finish", summary=summary)
                actions.append({"i": i + 1, "thought": thought, "action": "finish", "summary": summary})
                st.status = "done"
                st.summary = summary
                break
            obs = apply_agent_action(act, run_id=trace.id)
            trace.span("agent.action", i=i + 1, action=action, observation=obs)
            on_event("agent.observation", i=i + 1, observation=obs)
            actions.append({"i": i + 1, "thought": thought, "action": action, "observation": obs})
        else:
            summary = "stopped at max_steps=%d; see trace" % max_steps
            on_event("agent.finish", summary=summary)
            actions.append({"action": "finish", "summary": summary})
            st.status = "done"
            st.summary = summary
    except api_v02.AbortRun:
        aborted = True
        summary = "aborted by operator"
        on_event("agent.aborted", run=st.id)
        on_event("agent.finish", summary=summary)
        actions.append({"action": "finish", "summary": summary})
        st.status = "aborted"
        st.summary = summary
    st.trace = actions
    finish_run_graph(trace.id, None, goal, on_event=on_event)
    trace.finish("aborted" if aborted else "done")
    return {"goal": goal, "model": model, "trace": actions, "run_id": trace.id,
            "aborted": aborted}

