# Longrun Architecture

*Living map — Harness2 ownership updated against `src/longrun` 2026-10-28. The code is the source
of truth; this is the map. Update it in the same commit as any structural change
(freshness rule, 2026-10-25).*

Longrun is a **Python agent harness using stdlib plus PyYAML**. It drives one LLM with disciplined
context and a real tool loop, then composes that harness into **meta-agents organised in
teams**. It serves a single-file WebUI, a mission-control deck (Orbit), a CLI and a
mobile-ready HTTP API — all from one process on `:8790`.

```
        WebUI (webui/index.html)   Orbit (src/longrun/orbit)   CLI (forge.py)   Mobile
              │  SSE  ▲  │ HTTP          │  SSE ▲                │ SSE ▲         │
              ▼       │  ▼               ▼      │                ▼     │         ▼
        ┌───────────────────────────────────────────────────────────────────────────┐
        │                  server.py  (:8790 http · :8791 https)                      │
        │   chat (stream)   │   agent loop   │   jobs/orchestration   │   teams         │
        │   ────────────────┼────────────────┼────────────────────────┼──────────────   │
        │   taskgraph       │   tools+registry│  providers/routing    │   memory         │
        │   keepgoing loop  │   approvals    │   sandbox             │   skills         │
        │   ────────────────┴────────────────┴────────────────────────┴──────────────   │
        │   EVENT BUS  publish() → /api/feed   (SSE, monotonic ids + replay backlog)     │
        │   STORES     data/… (atomic JSON + SQLite events.db)                           │
        └───────────────────────────────────┬───────────────────────────────────────────┘
                                            │ OpenAI-compatible, stream
                        ┌───────────────────┼───────────────────────┐
                        ▼                   ▼                       ▼
                 llama.cpp router      vLLM router            cloud providers
                 (Linux x86_64/arm64   (local)      OpenRouter · DeepSeek · OpenAI · Anthropic · Google
                  · Windows)
```

## The object model (five levels)

The whole product is one hierarchy, from a business goal to a checklist item:

```
Team  TN      a symbol + a roster (owns its members)
 └ Job     JN      a goal given to a coordinator
    └ Subjob JN.k   one assignment, bound to ONE agent, with dependencies
       └ Agent  AX   IS a session — its own harness, tools, skills, memory, chat
          └ SJ SJ<n>[.k]  in-session subagents, dependency-ordered (die with the session)
          └ Todo AX.nY  a step, closable only with evidence
```

Membership is owned by the **team** (`teams.py`); `agents.py` only reads it, so the two
stores can never drift. Todo ids are `AX.nY` — the `T` namespace belongs to teams.

## A team job, end to end

1. `POST /api/jobs {goal, assignee}` — the assignee is the coordinator; its team is the
   assignee plus its direct reports.
2. `POST /api/jobs/<id>/dispatch` runs the job in the background:
   - **PLAN turn** — the coordinator decomposes the goal. This turn is **plan-only and
     read-only**: a tight tool budget, no completion loop, and only `fs.read` / `skills`
     / `memory` / `self` may run. It records the plan and stops; it cannot do the work.
   - `parse_plan_deps` reads the declared `(after AX)` edges; `plan_subjobs` turns the
     plan into numbered subjobs with deps; the delegation is written into **both** chats.
   - **Worker waves** — `waves()` topologically orders the subjobs; each worker runs a
     full harness turn and reports with `STATUS: DONE` / `STATUS: BLOCKED: <why>`.
   - **SYNTHESIS turn** — the coordinator receives the team report (unfinished subjobs
     are explicitly flagged) and produces the final deliverable.
3. Bounded retry: a BLOCKED subjob is retried a bounded number of times, then marked
   **failed**; the job becomes **partial** and the failure is surfaced, never hidden.

## Request / turn lifecycle (one chat turn)

`assemble_turn` builds the exact prompt (system sections + compacted transcript +
message + enabled-tool name index + skills index); full tool schemas are discovered
through `self.tools` instead of dumping the registry into every prompt. The provider
is called over an OpenAI-compatible stream; the model may answer **or** emit a
harness action (`tool`, `todo.write`, `todo.update`, `todo.replan`, `subagent`).
Tool calls go through the **approval gate** and the **sandbox**; observations are
fed back. The **completion loop** (`keepgoing.py`) applies ordinary turn limits to
chat and headless jobs. Explicit `/goal` continues past ordinary round/iteration
limits until the current plan is evidence-backed complete, blocked/cancelled, or
the configured wall-clock safety cap stops it incomplete. The goal itself is a
**durable object** (`plan/goal.py`, `data/goals/<session>.json`) with one owner per
fact: the record owns the objective and its lifecycle (`active|paused|completed`),
the plan owns the steps and their evidence, so completion is read from
`taskgraph.goal_complete` and never stored as an opinion. A pause refuses the next
`/goal` turn before any spend (409), and the WebUI's Active-goal bar renders
`GET /api/goal` — pause, edit and delete are POSTs, so the goal survives the turn,
the tab and a service restart. Every step is published
to the event bus and persisted, so a reload rebuilds the transcript and task graph.

## Components (`src/longrun/`, organised in subpackages)

| Subpackage | Modules |
|---|---|
| `core/` | `server.py`, `api_v02.py`, `httpapi.py`, `sse.py`, `events.py`, `forge.py`, `settings.py`, `diagnostics.py`, `configfiles.py`, `sidebar_order.py`, `matrix.py`, `homemove.py` |
| `agent/` | `agent.py`, `agents.py`, `subagent.py`, `bridge.py`, `agency.py`, `swarm.py`, `session_jobs.py`, `longrun_agent.py`, `acceptance.py`, `trace_policy.py` |
| `orchestrate/` | `jobs.py`, `orchestration.py`, `teams.py`, `routines.py`, `roles.py` |
| `plan/` | `taskgraph.py`, `keepgoing.py`, `goal.py`, `difficulty.py`, `bestofn.py`, `prm.py`, `heldout.py`, `verify.py` |
| `tools/` | `tools.py`, `registry.py`, `approvals.py`, `sandbox.py`, `hooks.py`, `edits.py`, `term.py`, `diag.py`, `matrix_guard.py` |
| `model/` | `providers.py`, `routing.py`, `context_engine.py`, `prompt.py`, `runmetrics.py`, `otel_tracing.py`, `rllm.py`, `keys.py`, `costs.py`, `embed.py`, `compaction_config.py`, `structured.py`, `vision.py`, `decision.py` |
| `memory/` | `memory.py`, `skills.py`, `rules.py`, `checkpoints.py`, `stores.py`, `knowledge.py`, `codeindex.py`, `vectors.py`, `embedcfg.py`, `indexcfg.py`, `chunk.py`, `costlog.py`, `docio.py`, `autoidx.py`, `rewind.py`, `threads.py`, `sqlkit.py` |
| `interop/` | `mcp.py`, `mcp_client.py`, `mcp_server.py`, `acp.py` |
| `util/` | `osutil.py`, `paths.py`, `textkit.py`, `steering.py`, `tracing.py`, `voice.py`, `evals.py`, `meta.py`, `selfevolve.py`, `improve.py`, `dag.py`, `dataio.py`, `fswrite.py` |
| `integrations/` | `paperclip_adapter.py`, `paperclip_bot.py` (Paperclip team-chat adapter + bot) |
| `orbit/` | the **Control** deck at `/orbit`: `api.py`, `orchestrator.py`, `attention.py`, `decisions.py`, `registry.py`, `bay.py`, `web/orbit.html` |
| `research/` | `research.py`, `executor.py`, `researchcfg.py` (web-grounded research agent) |
| `harness/` | `record.py`, `contrast.py`, `library.py`, `editors.py`, `probe.py`, `runner.py`, `compose.py`, `cycle.py`, `snapshot.py`, `whole.py`, `gateway.py`, `unixshim.py` (bounded Harness2 evidence workflow) |

## Harness2 evidence workflow

`GET /api/harness/cycle` reports the effective enable flag, whole-run readiness,
canonical library counts and last cycle. `POST` defaults to a dry run: build a
**session aggregate** from existing `memory.stores` tool cards and current
workspace deliverables, then list relevant library entries. It calls no model.

Editors generate ephemeral skill/guardrail candidates, reusing complete bounded
library files with hash provenance. A cycle now freezes ONE matched input package
(`harness/snapshot.py`: code, config, skills, rules, workspace, per-file SHA256),
executes a **reference run**, then each candidate as a hardlinked variant that
differs only by the declared component. `repeats` (1–3) executes paired
reference/candidate runs; reflection raises confidence only when every repeat
agrees and still returns `NO_ENTRY` for durable library writes.

Production execution is confined by `harness/whole.py` through the existing
`sandbox` launcher: pinned image digest (`deploy/harness-runtime.Dockerfile`),
`--network none`, read-only `/input`, bounded tmpfs writes, dropped
capabilities, non-root, resource limits, and verified container removal. Model
access is the ONLY channel: a Unix socket serves `harness/gateway.py`, which
forwards to one fixed loopback upstream and one allowlisted model under request,
body, token and time budgets. The container's loopback TCP is bridged by
`harness/unixshim.py`; the gateway remains the policy owner.

Readiness is reported by real checks (`readiness()` in `whole.py`): POSIX,
non-root, pinned image present with matching identity, configured model,
loopback upstream, reachable daemon. `LONGRUN_HARNESS_ENABLED=1` is not enough.
A verified experiment (two distinct clean runs, each bound to its own package
digest: the frozen reference package and the hardlinked variant that differs from
it by the declared delta, executed successor, `improved` verdict) may create ONE
`origin=harness` proposal; the existing `util.improve` approval path applies it
only when that evidence is present. Selection is not causality or transfer; the
report says so.

Limits stay explicit: Docker shares the host kernel (a hostile-code threat model
needs a VM boundary), launcher-crash recovery and daemon-in-flight creation are
not proven by a cleanup query, the profile is a deliberately reduced
runtime (no MCP/host credentials), and no local scientific superiority is
measured. Rules, skill discovery, approval, atomic-write and path owners remain
authoritative.

### Learning -> Matrix bridge (one reviewed path)

The evidence loop can now also update the mutable Matrix zone, without giving
the model a second code lane:

- Editors may emit `matrix_tool`, `matrix_hook`, `matrix_module`, `matrix_skill`
  and `matrix_rule` candidates. They stay ephemeral.
- The candidate's runtime path comes from the Matrix owner
  (`core.matrix._resolve_target_path`), which refuses absolute/traversal names;
  the frozen package carries `src/Matrix` plus the Matrix runtime `rules/` and
  `skills/`, and the container is bound to them
  (`LONGRUN_MATRIX_SRC=/input/src/Matrix`, `LONGRUN_MATRIX_DOT=/input/matrix`).
  The host lane refuses Matrix kinds: it would test a copy nobody loads.
- A verified experiment admits at most ONE bundle, all-rules or all-Matrix.
  A mixed bundle is refused because one package delta cannot attribute both.
- Approval (`util.improve.decide`) re-checks the matched runs, requires an
  `improved` contrast for Matrix, verifies every artifact SHA256 and delegates
  the write to `core.matrix.apply_learning`: whole-bundle validation (kinds,
  containment, hashes, `compile`), a checkpoint for code, atomic writes, then a
  hot-load whose new errors roll the entire bundle back. Nothing enters Nucleus;
  graduation still needs `matrix.verify_target` + the dedicated
  `allow_matrix_promote` checkbox.
- `matrix{action:'load_module'}` imports ONE arbitrary Matrix module on demand.
  It is never executed at boot, and import failures (including `SystemExit`) are
  isolated like any other dynamic artifact.
- The MINING lane reaches the same gate (EV-17). `selfevolve.forge_bundle` is the
  one owner of the generated module (validation + bytes + sha); `improve{forge}`
  and a human-approved `improve{evolve}` write those bytes and prove them with
  `matrix.run_test` + `matrix.verify_target`, while the background end-of-turn
  pass has no approval of its own and therefore opens a PENDING `matrix` proposal
  with the same bundle — `util.improve.decide` applies it through
  `core.matrix.apply_learning`. The `matrix` approval policy (`approvals.kinds`)
  decides: `auto` lets the background pass write, `required` (default) proposes,
  `denied` emits nothing.

Skill identity is canonical: the repository library and the Matrix runtime are
one namespace, the repository copy wins deterministically, and a shadowed folder
stays visible (`skills.shadowed_skills()`). `skills.install_skill_dir` is the
single writer for `skills/created`, used by both automatic promotion and Matrix
graduation, so neither path can clobber an existing skill.

Machine-mined skill DRAFTS are a third, earlier state: `<DATA>/proposals/skills/<name>`
holds a `proposal.json` but is neither a pending proposal nor an installed skill.
`improve.list_drafts()` (one owner of the folder, `improve.DRAFT_DIR`) is the
read-only view of that state, surfaced by `GET /api/improvement` as `drafts` /
`drafts_total` / `drafts_unreadable` and rendered in the Improve panel as material:
"verify, then promote — nothing here is installed".

A draft moves on by one path: `improve.sweep_drafts()` prunes the junk (single-tool
loops, below `min_len`), `selfevolve.ensure_check()` synthesizes `skill.json` /
`runner.py` / `check.py` when the draft has none, `verify` runs that check in the
sandbox and `promote` archives only a green draft under `skills/created`. Both the
`improve` tool (`verify`/`promote`) and the approval path (`decide`, for a skill
proposal bound to a draft with `target_path`) call those three functions — the
same owner each time, so a mined draft can never be unverifiable-by-construction.
Whether a draft already IS a live Matrix tool is not a stored flag: the row asks
`selfevolve.forge_target()` and checks the module, so `matrix.remove` stops the
claim at once and the panel hides the forge action for a live one.

### Self-evolve: who owns which state (one map, two entry points)

"Unify" here means one lifecycle, not one file: the modules have disjoint jobs, so
merging them would touch the agent loop, the registry, the Matrix guard and the
frozen snapshot at once for no behavioural gain. The states and their single
owners:

| state | entry point | owner | what it means |
|---|---|---|---|
| tool sequence recorded | agent turn | `selfevolve.record/history` | raw material, not a skill; only a name the registry ACCEPTS is recorded (`_dispatchable`), because the loop's own pseudo-actions (`batch`, `subagent`, `dispatch`) can never be replayed |
| mined draft (`proposals/skills/<name>`) | end-of-turn pass or `improve{mine}` | `improve.sweep_drafts` + `selfevolve.draft/synth` | material; needs a purpose; `prune_junk` drops drafts whose steps are not dispatchable |
| harness candidate (`skill` kind) | Harness² cycle editor | `harness/editors.propose` → `probe.stage` | material tested by a matched run |
| verified | `improve{verify}` / `decide` | `selfevolve.ensure_check` + `verify` | the sandbox check went green |
| proposal (`scope=skill`, bound to a draft OR to tested bytes) | mined draft or matched experiment | `improve.propose` | ONE decision object |
| installed skill | approval | `selfevolve.promote` (draft) / `skills.install_skill_file` (harness bytes) | never clobbers an existing skill |
| forged Matrix tool (`learned_<slug>.run`) | `improve{forge}` on a draft, `improve{evolve}` (human-approved), or the background pass when `approvals.kinds.matrix=auto` | `selfevolve.forge_target` (the naming) → `selfevolve.forge_bundle` (validation + the exact bytes) → `selfevolve.forge_matrix` → `matrix.scaffold` → `matrix.run_test` → `matrix.verify_target` | executable, but only after its own generated test and the sha-bound contract gate pass; removed when they do not. `evolve` asks `forge_target` first, so a pattern forged in an earlier pass is `skipped`, never a clobber refusal |
| learned Matrix bundle (proposal) | background `evolve` when the `matrix` policy is not `auto` | `improve.propose(scope="matrix", artifacts=[…sha256])` → `improve.decide` → `matrix.apply_learning` | the same bytes `forge_bundle` would write, held pending until the operator approves; approving writes + hot-loads, denying writes nothing |
| Matrix artifact | approval | `core.matrix.apply_learning` | outside Nucleus, hash-bound |


### Enabling matched whole runs (opt-in, off by default)

Nothing executes until the host is actually able to confine a run. Build and pin
the image once, then name it and the model in the service environment:

```bash
docker build -f deploy/harness-runtime.Dockerfile -t longrun-harness-runtime:2026-10-28 .
docker image inspect --format '{{.Id}}' longrun-harness-runtime:2026-10-28
# then, in the service unit:
LONGRUN_HARNESS_ENABLED=1
LONGRUN_HARNESS_IMAGE=sha256:<the 64-hex id printed above>
LONGRUN_HARNESS_MODEL=<exact model id the loopback router serves>
```

Optional knobs (all owned by `harness/whole.py:DEFAULTS`): `LONGRUN_HARNESS_REPEATS`
(1–3), `LONGRUN_HARNESS_RUN_TIMEOUT`, `LONGRUN_HARNESS_PORT`,
`LONGRUN_HARNESS_CONTEXT`, `LONGRUN_HARNESS_SNAPSHOT_MB`,
`LONGRUN_HARNESS_MAX_CANDIDATES`, `LONGRUN_HARNESS_MAX_CYCLE_SECONDS`,
`LONGRUN_GATEWAY_UPSTREAM`, `LONGRUN_GATEWAY_MAX_REQUESTS`,
`LONGRUN_GATEWAY_MAX_TOKENS`, `LONGRUN_GATEWAY_MAX_SECONDS`. `GET
/api/harness/cycle` reports the real readiness and the reason it is not ready; the
Improvement panel renders that same answer.

## Data stores (the data home — `~/.longrun/data`, never the checkout)

`sessions/` (transcripts) · `graphs/` (per-session task graphs) · `runs/` (traces +
token/cost) · `edits/` (diff journal) · `memory/` · `checkpoints/` · `offload/` (oversized
observations spilled to files) · `codebase/` (per-workspace FTS+vector index) ·
`knowledge/` + `embedding/` (global notebook index + its cost log) · `costs/` (per-session
model-call ledger) · `prices.json` · `tls/` (auto self-signed cert for HTTPS) ·
`agents.json` · `teams.json` · `jobs.json` · `events.db` (durable SSE feed) ·
`projects/` (per-workspace Project_rules.md, rules/, prompt.d/). Writes are
atomic (`tmp` + `os.replace`). The root is resolved by `util/paths.py`
(`LONGRUN_DATA_HOME` → `data_home` in `~/.longrun/config/config.json` → platform
default) and can be moved from Settings ▸ Info.

## Safety model

Allowlist registry (a tool must be `enabled` in `config/tools.yaml`) → per-action
classification (`auto | required | denied | disabled`) → approval queue for anything
world-touching → configured **shell sandbox** (`docker`, `bwrap`, `nsjail`, or
operator-selected `none`). This is not whole-agent confinement. Hard-denied patterns
(`rm -rf /`, `mkfs`, `git push`, …) are blocked even with approval.

## Interfaces

- **WebUI** `webui/index.html` — one file, no build step; chat + CoT, task graph, feed.
- **Orbit** `src/longrun/orbit/` — optional command deck at `/orbit`: org chart,
  constellation, job create/dispatch, team selector, model policy.
- **CLI** `forge.py` — chat, agent runs, tasks, models, MCP.
- **HTTP API** — see [CLI.md](CLI.md); optional bearer auth (`--token`). The server also
  listens over **HTTPS** on `--port + 1` (self-signed cert auto-generated in
  `<data home>/data/tls/`, `LONGRUN_TLS=0` to disable) so the page is a *secure context*
  and browser voice input works.

## Diagrams (WIP — do not trust, do not regenerate yet)

The generated architecture diagrams (`docs/diagrams/`, archify `.architecture.json`
+ rendered HTML) are **gitignored local artifacts** and currently STALE. Per
operator decision 2026-10-25: no regeneration pass now. The ASCII map and the
tables above are the current reference until the WIP is lifted.

## Entry points

The repo-root `server.py`, `forge.py`, `mcp_server.py` are **launcher shims** (they put
`src/` on `sys.path` and call the package `main()`). Real code lives in
`src/longrun/<subpackage>/`; modules import each other with absolute
`from longrun.<subpackage> import ...` paths.
