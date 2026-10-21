---
name: repo-orientation
description: "Orient an LLM in the Longrun codebase: how to self-inspect the repo, map its architecture, and explain its configuration and capabilities using ONLY repo-relative paths (no absolute/machine paths). Trigger when the agent must explain 'how is this project made', 'what can this harness do', 'how is it configured', 'understand this repo', 'self-inspect', 'explain the architecture', 'map the codebase', or needs to orient itself after landing here. IT: 'com'e' fatto questo repo', 'cosa sa fare', 'spiega la configurazione', 'spiega l'architettura'."
---

# Repo Orientation — self-inspect Longrun

Teach an LLM to answer "how is Longrun made?" and "what can it do?" by READING the
code and config — never by guessing. Every path below is **repo-relative**: it works
on any clone, with no machine-specific paths.

## 1. Read order (the map)

Read in this order; the first four are tracked in every clone:

1. `AGENTS.md` — the 60-second mental model + non-negotiables.
2. `docs/ARCHITECTURE.md` — object model, component table, safety model, data stores.
3. `docs/CLI.md` — every HTTP route and its `forge.py` command.
4. `docs/TESTING-PLAYBOOK.md` — how the harness is tested live.
5. `docs/diagrams/longrun-architecture.architecture.json` — **local only**
   (gitignored): the **archify** machine map with 16 components, their `sources`,
   boundaries and connections. The matching HTML is the human view. If the file
   is absent on this machine, say so instead of claiming it was read.

## 2. Mental model (recite before explaining)

- **stdlib-only Python agent harness** in `src/longrun/`, one process on `:8790`.
- **Five object levels**: `Team (TN) → Job (JN) → Subjob (JN.j) → Agent (AX) → Todo (AX.nY)`.
  An **agent IS a session** (`agent["session"] == sid`); a team owns its roster.
- **The harness is the model's secretary**: it assembles the prompt, injects synthetic
  turns (`nudge`/`observation`/`continue`), gates tools, and drives the completion loop.
- The repo-root `server.py` / `forge.py` / `mcp_server.py` are **launcher shims**; real
  code lives in `src/longrun/` and uses relative imports (cannot run standalone).

## 3. The configuration surface (`config/`)

| File | What it controls |
| --- | --- |
| `tools.yaml` | allowlist + approval policy (`auto/required/denied/disabled`), sandbox backend, `deny` patterns, runtime/verifier/bestofn/difficulty/selfevolve knobs. |
| `providers.yaml` | every LLM provider + models (local llama.cpp/vLLM on the DGX/PC, then cloud). Keys are referenced by ENV VAR name only — never in the file. |
| `routing.yaml` | role→model mapping (`chat/planner/agent/subagent/summarizer`) + fallbacks. |
| `hooks.yaml` | lifecycle scripts (PreToolUse/PostToolUse/Stop); ships empty, exit code decides. |
| `mcp_clients.yaml` | external MCP servers (stdio/HTTP); ships examples only. |

Local overrides that are **gitignored** (never in a clone): `config/providers.local.yaml`,
`config/mcp_clients.local.{yaml,json}`.

## 4. What it can do (capabilities index)

To answer "what can it do", map the feature to its source (all under `src/longrun/`):

- **Drive an LLM** with a real tool loop and disciplined context → `server.py`, `keepgoing.py`, `context_engine.py`.
- **Orchestrate meta-agents in teams** → `agents.py`, `teams.py`, `jobs.py`, `orchestration.py`, `subagent.py`, `swarm.py`.
- **Plan/execute a task graph** → `taskgraph.py`, `verify.py`, `bestofn.py`, `difficulty.py`, `prm.py`, `heldout.py`.
- **Safety** (allowlist → approval gate → sandbox) → `registry.py`, `approvals.py`, `sandbox.py`, `hooks.py`.
- **Model routing** (local + cloud, OpenAI-compatible) → `providers.py`, `routing.py`.
- **Knowledge** (memory, skills, rules, roles, checkpoints) → `memory.py`, `skills.py`, `rules.py`, `roles.py`, `checkpoints.py`.
- **Interop** (bidirectional MCP, ACP) → `mcp.py`, `mcp_client.py`, `mcp_server.py`, `acp.py`.
- **Self-improvement** → `selfevolve.py`, `improve.py`, `meta.py`.
- **Interfaces**: WebUI `webui/index.html`, Orbit `src/longrun/orbit/`, CLI `forge.py`.
- **State** (gitignored `data/`): sessions, task graphs, runs, edits, memory, checkpoints, `events.db`.

## 5. Golden rules

- **Relative paths only.** Never emit `~/...`, `Z:\...`, or `/home/...` — this SKILL is
  clone-portable. If the code shows an absolute path (e.g. a config root), report it as a
  *deployment choice*, not a fact about the project.
- **Code is the source of truth.** `docs/` is the map, `src/` is the terrain; if they
  disagree, trust `src/` and flag the doc.
- **No secrets.** `.env` / `~/.hermes/.env` are gitignored; a provider references its key
  by env-var name only.
- **Evidence over belief.** A claim about "how it works" needs a file/line (or a run of
  `bash tests/battery.sh`) — not a restatement of this SKILL.