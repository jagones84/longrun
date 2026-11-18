# Longrun Architecture

*Living map. The code is the source of truth; this is the map. Update it in the
same commit as any structural change (freshness rule, 2026-10-25). The component
diagram under [`diagrams/`](diagrams/architecture.svg) is the visual half of this
page and is generated from a checked spec, so the two cannot drift apart.*

Longrun is a **Python agent harness using stdlib plus PyYAML**. It drives one LLM with disciplined
context and a real tool loop, then composes that harness into **meta-agents organised in
teams**. It serves a single-file WebUI, a mission-control deck (Orbit), a CLI and a
mobile-ready HTTP API — all from one process on `:8790`.

![Longrun architecture](diagrams/architecture.svg)

The diagram is the component view: what exists, and what actually moves between
the blocks. Two facts it deliberately leaves out, because they are properties of
the process rather than of a component:

- **One process, four clients.** `server.py` serves the WebUI, the Orbit deck,
  the CLI and the mobile client on `:8790` (HTTP) and `:8791` (HTTPS). The event
  feed is a second SSE channel with monotonic ids and a replay backlog.
- **One outbound contract.** Every provider call is OpenAI-compatible and
  streamed — `llama.cpp` and vLLM locally, OpenRouter / DeepSeek / OpenAI /
  Anthropic / Google over the network.

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

### Todo lifecycle (the checklist item)

```
todo ──▶ doing ──▶ done        done needs EVIDENCE (a claim is kept but marked)
  │        │
  │        └──▶ todo           a turn ended: nothing is "running" any more (v811)
  ├──▶ blocked                 still open; carries what it waits for
  ├──▶ cancelled               closed, no reason required (a silent close)
  └──▶ superseded              closed, and WHY is required (a vague "still open" is refused)
```

At most ONE step is `doing` at a time. A **plan** is not an object, it is a SCOPE: a
number per session, tagged on every node, so the transcript's cards keep resolving
their ids forever. The model reads the CURRENT plan only (`render_todos`), which is
why a step left in history is invisible to it — `carry` moves such a step forward
(same id, deps into the abandoned plan pruned), `drop-plan` / `drop-old-plans` delete
history for real, and the current plan is never droppable. The panel derives a plan's
state from its nodes (`n done` / `n open`): it is never stored twice.

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
4. **Who assigned it, who is told.** A job records `assigned_by` (an agent that handed
   it over) next to `agents` (the agents it is assigned TO). When the job reaches a
   terminal state, ONE notice goes back to that agent through `util.inbox.deliver` —
   the single rule `sessions.send` also uses: **queued** when the agent is in a turn
   (the loop drains it at its next boundary), a **real turn** when it is idle. The job
   record stays the source of truth; the notice names it and `job.get` still answers in
   full. Delivery is recorded in `notified` (one attempt, never a second copy).
5. **A dispatch is a run-mode job.** The `dispatch` harness action (a teammate turn)
   creates a one-worker job with `assigned_by` = the dispatcher and returns its id in
   the same second, so the delegating turn never parks behind the teammate; the reply
   arrives as the completion notice above. `{"action":"dispatch",…,"wait":true}` keeps
   the inline turn (and fails fast on a busy teammate). `chat_stream_gen` runs each
   turn in its own worker thread, which owns the per-session turn lock — callers pump
   the stream, and a worker identifies its own reply by the user message it wrote
   (`meta.subjob` / `meta.sender`), never by a message count taken before the lock.
   A restart (`reconcile`) closes a running job **and its** still-`running` runs and
   subjobs, so nothing spins on work that died with the process.

## Request / turn lifecycle (one chat turn)

`assemble_turn` builds the exact prompt (system sections + compacted transcript +
message + enabled-tool name index + skills index); full tool schemas are discovered
through `self.tools` instead of dumping the registry into every prompt. The provider
is called over an OpenAI-compatible stream; the model may answer **or** emit a
harness action (`tool`, `todo.write`, `todo.update`, `todo.replan`, `subagent`).
Tool calls go through the **approval gate** and the **sandbox**; observations are
fed back. One rule decides what may live in the system prompt: **only text that does
not change between turns**. The two volatile blocks — the live task list
(`state_block`) and the memory index (`prompt.memory_block`) — ride the current user
message through `agent.user_turn_context`, and `httpapi.context_usage` calls the same
function so the meter measures what is sent. A stable prompt prefix is what lets the
provider reuse its cache, and it is also why the chat shows the `system` card only
when the prompt really changed (`publish_system_prompt`, digest stored on the session).
The history is therefore **append-only from the provider's point of view**: the exact
text a user turn was sent with is stored beside the display text (`wire`, read through
`context_engine.wire_content`), and the next turn rebuilds that message from it. Without
it every turn rewrote the history and the provider re-prefilled the whole transcript
(measured 2026-11-10: the first call of each turn was 100% uncached; after the fix a
turn reuses ~85% of the prompt it already processed).
The **completion loop** (`keepgoing.py`) applies ordinary turn limits to
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

**A plan is never abandoned, and a turn cannot close on one** (2026-11-15). The
closing contract is one rule for every way a turn can end: `finish`, a prose
answer and a made-up "I am done" envelope all face the same close-todos forcing
(`_close_todos_text`) paid from the same budget (`_close_todo_max`), so the
explicit claim to be complete is not the cheapest way out. It is bounded — when
the budget is spent the turn ends — but the steps it could not close are written
ON the graph by `taskgraph.note_turn_end` (open ids + reason: `restart`, `finish`,
`user_pivot`, or the typed stop), and `carry_line` renders one line into the
always-on state block: *"still OPEN after the previous turn ended at … — restart.
They were NOT closed and are not forgotten."* Because the record is a file, it
survives compaction, a crash and a `systemctl restart`; `reconcile_orphan_turns`
writes it where the killed turn cannot (it also demotes `doing` back to `todo`),
and the first turn that closes every step clears it. Two exceptions keep the
hierarchy the operator asked for: the operator's OWN message outranks the plan
(a pivot turn answers without forced closure — the steps are carried, never
silently closed, and a plan can be re-written or `superseded` with a reason), and
a `[Harness restart]` continuation is **not** a pivot (`inflight.is_resume_text`),
because it is the same task resuming and must not inherit the stale-plan
exception. Locked by `v1008`.

**A run survives a restart, and its audit row says so** (2026-11-16). Operator: *"i want runs
survive restart — it's a tech spec prerequisite"*. The `runs` row belongs to the process that
opened it, so a restart ends that INSTANCE (and an old row must never be served as `running`
forever — measured 182 such rows, the oldest three weeks old): boot closes every row older than the
new process with `tracing.reconcile_orphans`, emitting `runs.reconciled`. The WORK is not in the
row — it is the `[Harness restart]` turn `inflight.recover` starts and the task graph file — so
when a session is actually continued, `tracing.mark_resumed()` turns its rows into **`resumed`**
and appends a `restart.resumed` span naming the session (`runs.resumed`); `interrupted` remains
only for a run the harness could NOT continue. Locked by `v1065`.

**The `harness → LLM` chat label is the wire** (2026-11-05). One chip exists per
message actually appended to the outgoing list, its body is that message verbatim
(role + `[harness] ` prefix), and a suppressed repeat is only a counter on the
message it repeats. Nothing the model never received is shown under that label, a
message withdrawn by the mid-turn trim takes its chip with it (`harness.drop` +
`stores.drop_inject`), and `sess["injects"]` records exactly the sends (no merge),
so live, reload and wire agree.

**A deliberate clear outranks any transcript snapshot taken before it** (v1045,
2026-11-15). The running turn keeps `msgs` in memory and flushes it into
`sess["messages"]` at turn end — and on every tool card / inject, because those are
persisted live. `save_session` ([stores.py:390](file:///home/jagones/Repositories/MyRepos/longrun/src/longrun/memory/stores.py#L390))
already merged that copy with the on-disk tail under a per-session lock, but a merge
cannot express a DELETION: a turn that had read the document BEFORE `sessions.reset`
wrote its copy back afterwards, so the wipe reported success and the transcript
returned (measured 2026-11-15 18:28:50: `session.cleared` fired, then 130 messages /
47 cards / 66 injects came back). Two facts now order the writes: `load_session`
stamps each copy with a non-persisted `_loaded_at`
([stores.py:72](file:///home/jagones/Repositories/MyRepos/longrun/src/longrun/memory/stores.py#L72)),
and `clear_session` arms a per-session `_CLEARED_AT` tombstone **before** it writes
([stores.py:605](file:///home/jagones/Repositories/MyRepos/longrun/src/longrun/memory/stores.py#L605)).
`save_session` drops `messages` / `tool_cards` / `injects` from any snapshot older
than the tombstone and marks it `_stale_after_clear` (sticky, so that same in-memory
turn cannot resurrect them with a later save); a snapshot loaded AFTER the clear
appends normally, both bookkeeping keys are stripped before `write_json`, and
`session.cleared` stays the one event the WebUI reacts to. The clear still
serialises with a FOREIGN session's turn (`_turn_lock`), but the session's OWN
turn passes `from_turn=True` and takes no lock: that turn is blocked waiting for
this very call, so a `batch` item on a pool worker deadlocked the session
(measured 2026-11-15 18:38: the turn froze after `approval.auto`), while the
tombstone and the save lock keep the write safe. `v1045` pins the whole order
(9/9), `v1047` the lock rule (9/9); `v321` (reset), `v947` (merge) and `v534`
(deliberate truncate) stay green.

**Every context budget is config** (2026-11-05). How much of the harness's own text
reaches the model — the 6000-char verbatim observation limit, the 200 000 render
ceiling, the 1500/600 offload preview, the per-turn reference caps, the prompt
skills/memory indexes, the rules block cap, the shell capture and `fs.read` default,
the sandbox output ceiling, the acceptance bounds and the step/iteration/wait budgets
— lives in `config/tools.yaml` → `context:` and the persistent-terminal pool
(max shells, idle reap, backlog) in → `shell:`; both are read through ONE resolver
(`model/context_limits.py`): explicit override → `LONGRUN_*` env var → config →
`DEFAULTS` (fallback only). Consumers bind it at import, so an edit needs a restart;
`v827` fails if a key loses its config row, if the loader drops the block, or if a
consumer drifts from it. The same budget applies on BOTH loops: the chat path and the
headless run (`api_v02._run_observation`) paste an observation verbatim up to
`tool_obs_limit` and offload the rest through the same `_offload_observation` owner, so
"one observation" has one size and one spill file wherever it is produced (2026-11-14).

**Four read-only audit surfaces say whether the harness's own scaffolding still earns
its place** (lot H, 2026-11-07). None of them writes anything or adds a second ledger:
`memory.rules.audit()` reports contradictions, stale paths, duplicates and an
over-budget scope, naming file + line (`GET /api/rules`); `tools.registry.footprint()`
names the enabled tools never called in the window and the index characters they cost
(`GET /api/tools` + the MCP adapter); `skills.discovery()` names the never-opened
skills from the shared attribution ledger and probes reachability from plain-language
tasks with the same ranker the tool uses (`GET /api/skills`); `approvals.stats()` now
also carries the accept rate, the median time-to-decision and the per-tool
rubber-stamping. The Settings panels render those blocks from the same payloads — `Rules` shows the
doctor card only when it has findings, `Tools` a `🧾 N unused` button that expands to the names,
`Skills` a never-opened suffix — so the operator sees what the model sees. `benchmarks/ablation.py`
turns the last step into an experiment: two arms of ONE command that differ by exactly one file-backed
layer (`rules`, `skills`, `hooks`), executed by `run()` and compared by `compare()` over the two output
trees.

**Every other limit is config too** (2026-11-06). The third block, `config/tools.yaml`
→ `limits:`, holds the values that used to be `int(os.environ.get("LONGRUN_…", <literal>))`
in `src/`: router retries/backoff/timeouts, answer and compaction budgets, the repeat
guard, HTTP body/feed/stream, event retention, thread digests, the CORE memory cap,
the per-kind memory record budget (`memory_max_records`, v972 — the kinds the harness
writes bound themselves on every store, and `v827`'s rule applies to it too), the offload
budget (`offload_keep_files` / `offload_keep_days`, v973 — one file per oversized tool
observation, bounded by its own writer and swept once per boot),
skill archive caps, graph orphan age, job retries, team slots, the held-out gate, TLS
and the edit-tool bounds (`fs_edit_max_edits`, `fs_edit_stale_guard`). Same resolver,
same precedence, same restart contract; `v827` pins completeness, loader whitelist,
binding and the absence of any surviving literal.

**`fs.edit` is a patch tool, not a rewrite** (2026-11-06). It replaces EXACT text and
refuses a missing or ambiguous match; `edits: [{search, replace}]` applies a batch
all-or-nothing, `start_line`/`end_line` confine the match to a line window of the
current file (so a huge file is patched without restating it), `dry_run` validates
without writing, and the Claude-Code stale guard refuses an edit or an overwrite on a
file whose mtime/size moved after `fs.read` (`force=true` overrides). The write itself
is atomic (`util/fswrite.write_text`) and keeps the file mode; a non-UTF-8 target is
refused rather than silently re-encoded. `v828` pins all of it.

### Bounded nudges (2026-11-16)

The turn loop may inject a harness→LLM nudge, but never without a per-turn ceiling: an EMPTY model
message earns at most **two** retries, then at most **one** `CONTINUE` park, then the turn closes
with `chat.error` naming the real count (`_empty_total`). The old `_empty_streak` alone was not a
bound — the park and any non-empty-but-useless reply reset it, and one measured turn produced six
identical retries (session `b7329cccf94c`, 22:21:29–22:21:53). A **stale plan** (`_user_pivot`)
only earns a continuation when the turn actually ran a tool: a one-line request answered with zero
tools stops as `user_pivot` instead of being dragged into a pivot round (measured: "Reply with
exactly: OK" plus seven open steps produced a second retry chain).

A **reasoning-only** reply (long chain-of-thought, no content, no tool call) or an **output-limit**
reply (`finish_reason=length`) is answered in two visible steps before any model switch: the first
failure names the mode, the reasoning tokens and the envelope (`reasoning.max_tokens`) and asks the
SAME model to think less; only a second failure names the failover and advances past that model. A
completely **blank** reply (no answer, no reasoning) has its own message. Each failed attempt is
persisted as a `model.attempt` card — UI-only (`tool_cards`, never `messages`, so it is displayed
live and after a reload but never re-sent) — carrying the model, the mode and the reasoning it
produced; a turn that still ends `empty_reply` gets one forced answer, not three.

### Diagnosing a failed turn — the trace tree (HD-2, 2026-11-14)

A turn persists everything a post-mortem needs — one card per tool call (`ok`, `error`,
`exit_code`, `node`, `after`) and the plan's steps as graph nodes — but the only reader was
`_render_transcript`, a flat ordered log: "why did this turn go wrong" was answered by reading
and guessing. `util/runtree.py` is the read model over those stores, and
`GET /api/sessions/<id>/trace-tree` (`python3 forge.py sessions tree ID`) serves it.

- **STAGE → STEP.** One stage per plan node that actually executed a tool call; its steps in
  execution order (`ts`, then `after` — the same keys the transcript sorts by, so the two
  readers never disagree). A plan node with no tool call is NOT an empty stage, and the two
  facts it can be are kept apart (round 64, from arXiv:2611.21407's artifact check — "a scorer
  that reads exit status credits work that was never written"): a node whose status is
  `done`/`completed` is a **claim** (`claimed`, with one `claim_note` line — measured 2026-11-18,
  528 of 912 live planned nodes), while a node with no call and no done status is simply
  **open**. Neither is judged; a claim may legitimately have been answered by the final reply.
- **A deleted todo does not delete evidence.** A card naming a node the graph no longer has (a
  replan replaced it) keeps its own `orphan` stage.
- **The onset verdict.** `onset` is the FIRST failed step — a bad `ok` OR a non-zero
  `exit_code` — with the stage it belongs to, whether a later success of the same tool in the
  same stage recovered it, and how many times that tool was retried. `verdict` is one
  operator-readable line; it is empty when nothing failed, never an invented cause.
- **One failure vocabulary.** The class comes from `selfevolve.error_class` (public since this
  change), the same normalizer the miner ranks failures by — the tree and `failure_candidates`
  cannot name the same failure two ways.
- **A retry is a reliability signal.** `selfevolve.session_failures` counts a failure class that
  comes back in the same shape within the next three tool calls (`retry_signal`, one severity step
  at ≥3 retries and ≥34 %, never past `error` and never against a `gate` refusal). This is the
  register's question (a class re-hit in place); the trace tree's onset `retries` is a different one
  (calls of the same tool after the first failure), so the two numbers are not compared.
- **Read-only.** No store is written and no model is called, so it is safe to ask about a
  session that is running right now. It is not causal attribution: that is HD-1, and this tree
  is its precondition.


## Components (`src/longrun/`, organised in subpackages)

| Subpackage | Modules |
|---|---|
| `core/` | `server.py`, `api_v02.py`, `httpapi.py`, `sse.py`, `events.py`, `forge.py`, `settings.py`, `diagnostics.py`, `configfiles.py`, `sidebar_order.py`, `matrix.py`, `homemove.py`, `market.py` (catalogue: skills · MCP · plugins · connectors, digest-gated, origin persisted with each install), `market_sync.py` (bulk import of the official MCP Registry and ClawHub into `data/market/imported.json`, as one background job the page polls; live remote search + import-one), `market_taxonomy.py` (the curated macro-area vocabulary in `config/market_taxonomy.yaml`: a deterministic keyword classifier applied at sync time, no model, no network), `commands.py` (the operator's own `/` commands), `slash.py` (the ONE `/` catalogue: built-ins, user commands, installed plugins and the documents folders, served by `GET /api/slash`), `connectors.py` (an MCP preset plus the key NAMES it needs) |
| `agent/` | `agent.py`, `agents.py`, `subagent.py`, `bridge.py`, `agency.py`, `swarm.py`, `session_jobs.py`, `architect.py`, `acceptance.py`, `trace_policy.py` |
| `orchestrate/` | `jobs.py`, `orchestration.py`, `teams.py`, `routines.py`, `roles.py` |
| `plan/` | `taskgraph.py`, `keepgoing.py`, `goal.py`, `difficulty.py`, `bestofn.py`, `prm.py`, `heldout.py`, `verify.py`, `commitment.py` (repair/replan/abandon by damage depth, arXiv:2611.19663), `docs.py` (the `/plan` and `/spec` markdown documents under `<workspace>/.longrun/documents/`, with the plan-mode gate) |
| `tools/` | `tools.py`, `registry.py` (publishes `TOOL_EFFECTS`: the declared effect, idempotency and read/write resources of a tool, consumed by `harness.effect_types`), `approvals.py`, `sandbox.py`, `hooks.py`, `edits.py`, `term.py`, `bgjobs.py` (detached shell jobs: start/status/stop), `diag.py`, `matrix_guard.py` |
| `model/` | `providers.py`, `routing.py`, `context_engine.py`, `prompt.py`, `runmetrics.py`, `otel_tracing.py`, `rllm.py`, `keys.py`, `costs.py`, `embed.py`, `compaction_config.py`, `structured.py`, `vision.py`, `decision.py`, `rerank.py` |
| `memory/` | `memory.py`, `anchors.py`, `skills.py`, `rules.py`, `checkpoints.py`, `stores.py`, `knowledge.py`, `codeindex.py`, `vectors.py`, `embedcfg.py`, `indexcfg.py`, `chunk.py`, `costlog.py`, `docio.py`, `autoidx.py`, `rewind.py`, `threads.py`, `sqlkit.py`, `rule_surface.py`, `read_boundary.py`, `conflict_surface.py`, `fact_ledger.py` (rounds 110–119: render order, epoch-validated reads, preserved disagreement, versioned facts) |
| `interop/` | `mcp.py`, `mcp_client.py`, `mcp_server.py`, `acp.py` |
| `util/` | `osutil.py`, `paths.py`, `textkit.py`, `steering.py`, `tracing.py`, `runtree.py`, `voice.py`, `evals.py`, `meta.py`, `selfevolve.py`, `improve.py`, `dag.py`, `dataio.py`, `fswrite.py` |
| `integrations/` | `paperclip_adapter.py`, `paperclip_bot.py` (Paperclip team-chat adapter + bot) |
| `orbit/` | the **Control** deck at `/orbit`: `api.py`, `orchestrator.py`, `attention.py`, `decisions.py`, `registry.py`, `bay.py`, `web/orbit.html` |
| `research/` | `research.py`, `executor.py`, `researchcfg.py` (web-grounded research agent) |
| `harness/` | `record.py`, `contrast.py`, `library.py`, `editors.py`, `probe.py`, `runner.py`, `compose.py`, `cycle.py`, `snapshot.py`, `whole.py`, `gateway.py`, `unixshim.py`, `counterfactual.py`, `shellread.py`, `modelcf.py` (bounded evidence workflow; step- and model-level counterfactuals + the purity gate that decides what may be replayed) · rounds 110–123 add one deterministic checker per paper: `reuse.py`, `principals.py`, `intent_journal.py`, `handoff_audit.py`, `approval_audit.py`, `autonomy.py`, `skill_prune.py`, `team_safety.py`, `tool_graph.py`, `instruction_audit.py`, `fault_episode.py`, `api_contract.py`, `effect_recovery.py`, `effect_types.py`, `context_cost.py`, `expectations.py`, `governance.py`, `skill_compiler.py`, `skill_repair.py`, `skill_conflict.py`, `skill_cache.py`, `flow_guard.py`, `self_directed.py`, `harness_evolution.py`, `context_pipeline.py`, `step_zero.py`, `harness_record.py`, `conduct_audit.py`, `completion_gate.py`, `skill_retrieval.py`, `rule_retrieval.py`, `skill_quality.py`, driven by the `forge.py` groups (`memory`, `episodes`, `contract`, `recovery`, `effects`, `context cost`, `commit`, `expectations`, `governance`, `skills compile|optimize|conflict`, `capsule`, `flow`, `selfdirected`, `harnessevo`, `contextpipeline`, `stepzero`, `harnessrecord`, `conduct`, `completion`, `skillret`, `ruleret`, `skillquality`) |

## Harness evidence workflow

This is Longrun's own `src/longrun/harness/` package. It is not the external
Harness² upstream (arXiv:2610.14224): that is only a comparison arm in
`benchmarks/jobbench_compare.py`, and none of its code runs here.

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

### Replaying one step (the agent's own diagnosis)

`harness/counterfactual.py` changes ONE fact of a recorded call and reports whether the
observation moved; `harness/shellread.py` decides what may be replayed (a pure read, both
sides of the intervention). `api_v02.counterfactual_run` is the ONE implementation behind
every surface — `POST /api/sessions/<id>/counterfactual`, `forge.py sessions
counterfactual`, and the agent's `sessions` action `counterfactual` (`card` dereferences
the `#handle` the compacted manifest prints). The replay goes through `gated_call`, so
policy, approvals and workspace are the normal ones; a write is refused before anything
executes.

`harness/modelcf.py` is the other half: replace ONE user message of the stored transcript
(an observation or a nudge), re-issue one model call and compare the next action
(`same-action` / `different-action`). Nothing executes, so this works on a failing turn
whose step was a write. `api_v02.model_counterfactual_run` is its one implementation; its
`fidelity` is `transcript+live-system` — the volatile per-turn blocks are not restored and
every answer says so.

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
  hot-load whose new errors roll the entire bundle back. Nothing enters Nucleous;
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
- A forged module is proven by BEHAVIOUR, not by its refusals (EV-19).
  `selfevolve._forge_test` generates the proof that `matrix.run_test` executes:
  step order, the caller's arguments reaching each step, a failing step stopping
  the run, the ok-count, plus the three refusals — the dispatcher is stubbed
  through `sys.modules`, so the proof needs neither the harness nor a config.
  `core.matrix._drop_bytecode` / `_drop_bytecode_file` run before a hot load and
  before each spec load, and `run_test` executes with `PYTHONDONTWRITEBYTECODE=1`
  and a private `PYTHONPYCACHEPREFIX`: CPython keys a `.pyc` on
  (source mtime in SECONDS, size), so a same-second same-size rewrite would
  otherwise attest bytes it never ran.
- `selfevolve.forged_usage()` is the OUTCOME-attribution owner (EV-20): it walks
  the forged modules (only those whose head carries the forge marker), the run
  history and each module's mtime, and answers `used ×N` / `never used · N run(s)
  since it landed` / `new` — the same object `/api/improvement` serves and the
  WebUI renders.
- `selfevolve.abstract` is the ABSTRACTION owner (EV-22), and the only step that
  reads a repeat as a procedure: ONE single-shot completion (`improve.single_shot`,
  role `reviewer`, injectable call seam) answers
  `{compact, name, goal, why, confidence}`. The record is stored on the draft
  (`abstract`, plus `purpose` = goal), `forge_from_draft` reads it, and the module
  is therefore `learned_<meaning>_<hash8>` with the goal as its description;
  `compact: false` means the repeat is a habit and nothing is written.
  `evolve_once` runs it before the forge bound (`abstract_per_run`) and fails
  OPEN when the model is unavailable — naming degrades, the code gate never does.

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
| tool sequence recorded | agent turn | `selfevolve.record/history_rows` | raw material, not a skill; only a name the registry ACCEPTS is recorded (`_dispatchable`), because the loop's own pseudo-actions (`batch`, `subagent`, `dispatch`) can never be replayed. The row also carries HOW the turn ended (`outcome`) and WHAT it asked for (`purpose`); a row without an outcome is UNKNOWN and is never read as a success |
| mined draft (`proposals/skills/<name>`) | end-of-turn pass or `improve{mine}` | `improve.sweep_drafts` + `selfevolve.draft/synth` | material; `mine` annotates each candidate with the outcome split and the most common purpose of its runs, and refuses a pattern whose known runs ALL failed; `prune_junk` drops drafts whose steps are not dispatchable |
| harness candidate (`skill` kind) | harness cycle editor | `harness/editors.propose` → `probe.stage` | material tested by a matched run |
| verified | `improve{verify}` / `decide` | `selfevolve.ensure_check` + `verify` | the sandbox check went green |
| proposal (`scope=skill`, bound to a draft OR to tested bytes) | mined draft or matched experiment | `improve.propose` | ONE decision object |
| installed skill | approval, or `evolve` when `approvals.kinds.skills=auto` **and** the sealed held-out suite is installed | `selfevolve.promote` (draft) / `skills.install_skill_file` (harness bytes) | never clobbers an existing skill — it supersedes it (retire + swap); one ledger `promote` row per install |
| forged Matrix tool (`learned_<slug>.run`) | `improve{forge}` on a draft, `improve{evolve}` (human-approved), or the background pass when `approvals.kinds.matrix=auto` | `selfevolve.forge_target` (the naming) → `selfevolve.forge_bundle` (validation + the exact bytes) → `selfevolve.forge_matrix` → `matrix.scaffold` → `matrix.run_test` → `matrix.verify_target` | executable, but only after its own generated test and the sha-bound contract gate pass; removed when they do not. `evolve` asks `forge_target` first, so a pattern forged in an earlier pass is `skipped`, never a clobber refusal |
| learned Matrix bundle (proposal) | background `evolve` when the `matrix` policy is not `auto` | `improve.propose(scope="matrix", artifacts=[…sha256])` → `improve.decide` → `matrix.apply_learning` | the same bytes `forge_bundle` would write, held pending until the operator approves; approving writes + hot-loads, denying writes nothing |
| Matrix artifact | approval | `core.matrix.apply_learning` | outside Nucleous, hash-bound |

**The sealed judge is an install step, not a built-in** (2026-11-14). `promote`
refuses every candidate until `data/heldout/manifest.json` exists, so on a fresh
install the skill half of the loop can mine and verify but never close (measured
here: 123 drafts, 0 installed). `heldout.install()` is the admin step that writes
`suite/check_all.py` + a frozen `allowed_tools.json` into the data home and pins
them; it is **not** an agent action (same contract as `pin()`), because the agent
must not author the judge that certifies it. The judge reads only the candidate
and its own allow-list — no repo import, no network, no model — and it can red: an
undispatchable tool, a single repeated tool, a missing `SKILL.md`, one over the
prompt-cost ceiling, or an approval-bypass instruction is refused by name.

**A mined candidate carries the outcome and the purpose of its runs** (OCM,
2026-11-14). The store used to hold `{tools, ts}` only, so the miner could rank a
pattern by frequency and by nothing else — on this install that was 500 runs → 91
candidates, all the same shape. Now the end-of-turn recorder stores how the turn
ended (`ok` / `error` / `corrected`, from `meta.error` and `_is_correction`) and
the turn's request as the row's `purpose`; `mine` annotates every candidate with
`support_ok` / `support_bad` / `unknown` and the most common purpose, and refuses
a pattern whose **known** runs all failed. `history_split()` is the one owner of
the row→aligned-lists mapping (a run dropped for being too short drops its outcome
with it — a misaligned split would attribute one run's failure to another's
sequence). A row with no outcome is UNKNOWN: the 500 rows written before this
change cannot mint a false success and are not blocked retroactively, so the
refusal only ever fires on runs that recorded their outcome. `draft()` writes the
purpose into `proposal.json` and as a `## What it was for` section of `SKILL.md`,
and the outcome split into the draft note. No gate changed: the purpose is
recorded, never required.

**One evolve pass installs at most `selfevolve.promote_per_run` skills** (default
1), the same bound the code arm has had since EV-13 (`forge_per_run`). Without it
a pass over the recorded history would promote every green candidate at once — 91
on this install — and fill `skills/created/` to its 25-skill cap in one go. The
same pass also writes one `promote` (or `retire`) row in the improvement ledger,
so "what did the machine change on its own?" is answerable after the fact.

That ledger is a **hash chain**, not a log file (round 14, 2026-11-18): every row
carries `seq` / `prev` / `hash`, the bounded 500-row window links back to an
anchor (`data/improvement/ledger.head.json`) that names the last evicted row and
the newest row written, and `improve(action="ledger")` / `GET /api/improvement`
report the chain's own verdict (`ledger_integrity`). An edit, a deleted row, a
reordering, a truncation or a removal of the whole file is therefore detectable,
and the agent the ledger records cannot write it: `matrix_guard` and
`config/tools.yaml` deny the `data/improvement` store, like the runs, held-out and
event records. Limit, from arXiv 2609.30266: a chain proves the rows that ARE
there were not altered, never that every action was written down.


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

## Retrieval, and its second stage

Two stores answer "what do we already know": the per-workspace **code index** and the global
**knowledge/notebooks** index (`memory/knowledge.py`, `memory/codeindex.py`, `memory/vectors.py`),
both FTS (BM25) + vector fused by reciprocal rank. Memories recalled for prompt injection come from
the same shape (`model/context_engine.retrieve`).

Rank fusion answers "these candidates are plausible", never "this passage answers the question", so
`model/rerank.py` adds an OPTIONAL cross-encoder stage: it scores `(query, passage)` TOGETHER and
reorders (and optionally trims by `min_score`) what retrieval already found — it never invents a
document. One implementation, two consumers (`memory.knowledge.search` and
`context_engine.retrieve`); `score` keeps its rank-fusion meaning and the cross-encoder number rides
as `relevance`.

Re-rankers are ordinary entries in `config/providers.yaml` flagged `rerank: true`;
`providers.is_rerank_model`/`chat_models` keep them out of every chat surface, and
`providers.rerank_endpoint` resolves a ref to `POST <base>/rerank`. Settings live in
`config/rerank.yaml` (Settings ▸ Models) with a sparse `data/rerank.overlay.yaml`. The stage is
**fail-open**: disabled, unreachable, slow, non-200 or empty leaves the caller's order untouched.

## Web search, and how a turn shows its work (2026-11-16)

The public-internet tool is `web` with two actions: `web.search` runs one query **or 2–4 `queries`
in one call** (parallel fan-out capped at 4 workers, URL de-duplication by host+path, `max_total`
15, 25 s wall clock, `partial` when the clock cuts a query) and `web.fetch` reads one URL or up to
five. Both accept `days`, `include_domains`/`exclude_domains`, `search_depth` (Tavily) and a 16 KB
fetch default (`tools.py:_web_search_many`, `_web_open`). The provider chain stays
Tavily → Brave → DuckDuckGo → Bing, but each miss is now **named** with its reason
(`tavily(missing TAVILY_API_KEY)`), because a swallowed key used to look exactly like "no results".

Every hit gets a **session-monotonic `[wN]` id** (`_web_ids(run_id, …)`: the tool has no turn
context, so a per-call `w1…wN` would collide across two calls in the same turn). The tool returns
the model-facing numbered text unchanged PLUS a structured `data` payload (engine, timings, host,
snippet, published, ids). `persist_tool_card` stores `data` **inside the card**, capped at 6 KB —
`tool_cards` never reach the model prompt (`model/context_engine.build` reads `messages` only), so
this costs no context; `tool.result` carries the same object (the `**extra` path), so the live card
and the reloaded card render through one function.

The WebUI reads that one payload for everything the operator sees: hit rows (favicon with an offline
letter fallback, escaped title/host/snippet, external links), a per-turn header
(`Worked for 4m 12s · 3 files read · 2 web searches`) inserted above the first work item and frozen
on the persisted `duration_s`, a **Sources** block between the answer and `.turnfoot` (fetched pages
weigh more than search hits; a row is marked *cited* only when its `[wN]` appears in the answer), and
`[wN]` links resolved by walking the rendered answer's text nodes (unknown ids stay plain text). The
same pass gives every tool row a human label and an inline SVG icon (`_toolUI`), keyed on the
**canonical** name (`web.search`, `fs.read`, …) with a raw-name fallback so a new Matrix tool never
breaks the row. Nothing here is live-DOM only: a reload rebuilds it from `tool_cards` + message meta,
which is the rule that keeps the chat and the transcript the same object.

## Data stores (the data home — `~/.longrun/data`, never the checkout)

`sessions/` (transcripts) · `graphs/` (task graphs — one per session AND one per run,
each recording its owner) · `runs/` (traces + token/cost) · `edits/` (diff journal) ·
`memory/` · `checkpoints/` · `offload/` (oversized observations spilled to files) ·
`attachments/` + `sandbox/` (per-session folders) · `trash/` (retired files and folders,
recoverable) · `heldout/` (the sealed promotion judge + its hash manifest, never
inside a workspace) ·
`codebase/` (per-workspace FTS+vector index) · `knowledge/` + `embedding/` (global
notebook index + its cost log) · `costs/` (per-session model-call ledger) · `prices.json` ·
`tls/` (auto self-signed cert for HTTPS) · `agents.json` · `teams.json` · `jobs.json` ·
`events.db` (durable SSE feed) · `projects/` (per-workspace Project_rules.md, rules/,
prompt.d/). Writes are atomic (`tmp` + `os.replace`). The root is resolved by
`util/paths.py` (`LONGRUN_DATA_HOME` → `data_home` in `~/.longrun/config/config.json`
→ platform default) and can be moved from Settings ▸ Info.

**One deliberate exception, the documents area (v1051).** `/plan` and `/spec` write
markdown deliverables under `<workspace>/.longrun/documents/` (`plans/` and `specs/`),
because the operator must be able to review and commit them with the project. They are
NOT harness state: `workspace_state_dir()` adopts every other legacy `<ws>/.longrun`
entry into `projects/<slug>-<sha8>/` and leaves `documents/` in place. The layout is
configured in `config/documents.yaml`; the planner has no tools, receives a bounded
workspace context and must mark assumptions. `POST /api/docs/plan|spec` writes the file
and calls `stores.set_plan_mode` — `registry.classify` then denies mutating tools until
the document is **approved AND its implementation authorised** (2026-11-17): `approve`
decides the content and `POST /api/docs/implement` (the bar's ▶) opens the gate
(`grant_implement`); `reject`/`unlock` release it. One policy evaluation inside
`docs.create_*` reads `approvals.mode` (FULL auto-approves the content) and
`approvals.auto_implement_documents` (the second check, only for a request whose
`origin` is the agent's `docs` tool). Policy writes themselves are operator acts with
ONE token (the API bearer): `POST /api/tools|settings` refuse a body that carries a
`session`/`run_id` and publish every accepted change as `policy.changed`; the env file
and the control API are hard-denied in the permission layer, which is what keeps a
shell-capable agent away from both — the env rule matches the FILE as a path token, so
the program that opens it is not part of the guard. Every child the harness starts for an
agent action (the session shell, host execution in a run, a background job) is spawned with
those variables REMOVED (`osutil.scrubbed_env`); `shell.env_passthrough` is the operator's
list of credentials a tool may keep. The task graph (`/api/plan`, todos) is
a DIFFERENT object and is never touched: the document is the intent/decision truth, the
graph is execution state.

Lifecycle and retention — every store has an owner and an end:

| Object | Ends by | What is kept |
|---|---|---|
| Session | `DELETE /api/sessions/<id>` → tombstone + cascade of every per-session file **and folder** (`attachments/<sid>`, `sandbox/<sid>`) | files move to `trash/` (recoverable) |
| Session folder | its session's delete, or the startup sweep `sweep_session_folders` for a folder with no live owner (v973, `graph_orphan_days` grace) | moved to `trash/` (recoverable) |
| Run | finish / abort | its metrics live and die with the session |
| Graph | the owner's delete, or the startup orphan sweep | owner-less graphs older than 14 days move to `trash/` |
| Goal | delete (the record is removed, so a stale client cannot resume it) | per session |
| Job / subjob | manual `job rm` | `jobs.json` has NO automatic retention |
| Approval | decided, or expired by `approvals.timeout_secs` | newest `approvals.max_records` DECIDED rows; a PENDING request is never evicted (`v909`) |
| Checkpoint | manual delete / prune | 100 snapshots + 30 turn anchors per session, and the dropped index entry takes its payload (`v973`) |
| Offload file | `prune_offload` on write + once per boot | newest `offload_keep_files` (200) per session, nothing older than `offload_keep_days` (30) |
| Memory record | invalidate / supersede / expire → tombstone (last entry wins), restore; a harness-written kind also bounds itself on every store | `purge_invalidated` removes the dead ones; a harness-written kind keeps `memory_max_records` (300) live, lowest value first (`v972`) |
| Trash | `_prune_trash` | newest 200 entries + 30 days; sheds files **and folders** (`v973`) |
| Event | `prune_events` | newest 200 000 rows, every 15 minutes |

A **clear** is not a delete: `sessions.reset` / `context.compact` / the Architect's
stateless reset keep the session and empty `messages` + `tool_cards` + `injects` under
the same save lock (the task graph and the thread ledger are reset with them), and no
snapshot read before the clear can put the old transcript back (`v1045`, §Request /
turn lifecycle).

**Memory is operator-wide, and its report counts LIVE records** (2026-11-15). The
store is deliberately not per-agent: an agent IS a session (`EV-30`), so an
agent-scoped store would be a session-scoped one and a lesson learned in one chat
would vanish with it. The only scope is the PROJECT — a record carrying
`workspace=<path>` is visible there alone, a record with no workspace is global
(`M1`/`CO-1`) — while `session`/`origin`/`source` stay as provenance.
`memory.stats()` (`GET /api/memory`) and `memory.health` report `kinds`/`total` as
LIVE, i.e. what recall can return, beside `stored`/`tombstoned`; the old raw count
made a store held exactly at `memory_max_records` (300 live, 13 retired) read as
"313 records over budget" and the caller concluded the bound was broken. A record
with no `mid` is outside the whole lifecycle (`invalidate`/`supersede`/`restore`/
`forget` are all id-keyed), so `backfill_mids()` repairs one at boot and
`unaddressable` stays visible until it does. The invalidate/restore ledger shares
ONE append-only file, is attributed per record, and `memory{action:'recent'}` skips
it unless its kind is named (`v1007`).

## Safety model

Allowlist registry (a tool must be `enabled` in `config/tools.yaml`) → per-action
classification (`auto | required | denied | disabled`) → approval queue for anything
world-touching → configured **shell sandbox** (`docker`, `bwrap`, `nsjail`, or
operator-selected `none`). This is not whole-agent confinement. Hard-denied patterns
(`rm -rf /`, `mkfs`, `git push`, …) are blocked even with approval.

## Interfaces

- **WebUI** `webui/index.html` — one file, no build step; chat + CoT, task graph, feed.
  Three top-level pages share one tab strip (`TAB_IDS`): **Sessions** (`#app`), **Control**
  (the Orbit deck in an iframe) and **My Artifacts** (`#artifactsView`, fed by
  `GET /api/artifacts` — the edit journal read as one cross-session index of produced files).
  The inspector's Workspace list is the SAME journal, reconciled with the disk on every read:
  a file changed or deleted outside the harness reports `disk: changed|missing` with the live
  counts, and an editor-dock save (`POST /api/fs/write`) is journalled under its session, so it
  appears there too. A file opens in a **dedicated preview window** (`#pvWin`), not in the editor
  dock: image/video/audio player, a live HTML page in a sandboxed frame, a workbook's first rows
  (`GET /api/fs/sheet`), sanitized markdown, a CSV/TSV table or the coloured source, with the
  absolute path under the name and a ⋯ menu (editor, raw tab, source, copies) — plus a right-click
  menu on any card or Workspace row that prints the absolute path. The window expands to the screen
  (`#pvSize`, persisted) and switches views only where it has more than one (Preview/Source for
  markdown+HTML, Table/Source for CSV). The source is the SAME CodeMirror 6 engine, theme and
  extension→language table as the editor dock (`webui/assets/filetypes.js`, `viewer.js`,
  `vendor/langs.js`), read-only. Cards with a first frame (image, HTML, PDF, video) carry a poster
  created only while on screen.
- **Orbit** `src/longrun/orbit/` — optional command deck at `/orbit`: org chart,
  constellation, job create/dispatch, team selector, model policy.
- **CLI** `forge.py` — chat, agent runs, tasks, models, MCP.
- **HTTP API** — see [CLI.md](CLI.md); optional bearer auth (`--token`). The server also
  listens over **HTTPS** on `--port + 1` (self-signed cert auto-generated in
  `<data home>/data/tls/`, `LONGRUN_TLS=0` to disable) so the page is a *secure context*
  and browser voice input works.

## Diagrams

`diagrams/` holds the rendered architecture. It is derived — never a second source
of truth — so a structural change updates this page first and the picture is
re-derived from it afterwards.

| File | Ships | What it is |
|---|---|---|
| `architecture.svg` | **yes** | the figure the README embeds; one self-theming file (light and dark from the reader's own preference) |
| `longrun-architecture.architecture.json` | no | the checked spec — components, relationships, boundaries, card text |
| `longrun-architecture.html` | no | the interactive build: five focus views (request path, test-time control, security and the marketplace's digest gate, state and evidence, orchestration), route probe, zoom |
| `longrun-turn-workflow.html` | no | one agent turn end to end: assemble → model → parse → gate → tool → observe → keepgoing |

Everything except the image is gitignored on purpose (`.gitignore`), because a
bundle is regenerable in seconds and would otherwise churn the repository. Both
pages were regenerated against `c08780b` on 2026-11-15 and pass the full gate set
(`validate` → `deliver` → `check` → `browser-check`) with no composition
diagnostics: 25 components, 42 labelled relationships, every block both entered
and leaving a trace. The marketplace is one block (`market`) plus the external
catalogues it mirrors (`registries`), so the picture shows where an installed
skill or MCP server came from. The turn workflow is unchanged by it — an install
happens on the API, not inside a turn — so that page moved only with the revision.

Regenerate with `node <archify>/bin/archify.mjs finalize <type>
<.archify/…/candidate.json> docs/diagrams/<name>.html --repo-root . --quality
<profile> --json`, passing the profile the candidate declares (`standard` for the
dense architecture, `showcase` for the turn workflow), then re-export
`architecture.svg` from the page's own Export ▸ SVG ▸ **SVG · Auto** (the
self-theming variant).

## Entry points

The repo-root `server.py`, `forge.py`, `mcp_server.py` are **launcher shims** (they put
`src/` on `sys.path` and call the package `main()`). Real code lives in
`src/longrun/<subpackage>/`; modules import each other with absolute
`from longrun.<subpackage> import ...` paths.
