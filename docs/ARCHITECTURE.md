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

### Team jobs vs Session Jobs (the two "job" words)

| | Team job `J<n>` | Session Job `SJ<n>` |
|---|---|---|
| What | durable work between agents of a team | a `batch` of subagents inside ONE chat |
| Store | `data/jobs.json`, `/api/jobs` | `data/session_jobs/<sid>.json`, `/api/sessions/<sid>/sj` |
| Executor | coordinator + team, dependency waves in each agent's own session | `subagent.spawn` children of the current session |
| Lifecycle | survives restarts; deleted explicitly | read-only, never dispatched; dies with the session, `/clear` or delete |
| Panel | Jobs panel (team section) | Jobs panel (in-chat subagents section, session scope only) |

They share only the pure graph helpers (`util/dag.py`); no code path moves an SJ into
`jobs.json` or a J into a session ledger.

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
| `tools/curation.py` | **live** reversible, agent-directed curation of this session's own tool results (ITER-01/R162, arXiv:2610.10590 §3.1–§3.2): `context.apply` archives each named card's payload and replaces its body with a note in place, the batch is validated whole so one bad target mutates nothing, and `context.recover` returns the archive as a NEW card without re-running the tool; only tool cards are selectable — user/system/assistant messages are not |
| `util/improve.py` | **live** reproduce-or-revert (ITER-01/R162, arXiv:2610.02616 §2.2/§4.4): a proposal that records an outcome change is approved only when it reproduced on a rerun, otherwise the row is stamped `reverted` to its parent; `failure_audit()` reports per-failure-mode approved/reverted/still-failing counts |
| `harness/` | `record.py`, `contrast.py`, `library.py`, `editors.py`, `probe.py`, `runner.py`, `compose.py`, `cycle.py`, `snapshot.py`, `whole.py`, `gateway.py`, `unixshim.py`, `counterfactual.py`, `shellread.py`, `modelcf.py` (bounded evidence workflow; step- and model-level counterfactuals + the purity gate that decides what may be replayed) · rounds 110–123 add one deterministic checker per paper: `reuse.py`, `principals.py`, `intent_journal.py`, `handoff_audit.py`, `approval_audit.py`, `autonomy.py`, `skill_prune.py`, `team_safety.py`, `tool_graph.py`, `instruction_audit.py`, `fault_episode.py`, `api_contract.py`, `effect_recovery.py`, `effect_types.py`, `context_cost.py`, `expectations.py`, `governance.py`, `skill_compiler.py`, `skill_repair.py`, `skill_conflict.py`, `skill_cache.py`, `flow_guard.py`, `self_directed.py`, `harness_evolution.py`, `context_pipeline.py`, `step_zero.py`, `harness_record.py`, `conduct_audit.py`, `completion_gate.py`, `skill_retrieval.py`, `rule_retrieval.py`, `skill_quality.py`; round 124 adds `operational_policy.py` (realization, grounding, per-model affinity), `execution_policy.py` (reversal, frozen-panel replacement, amortization), `skill_adapter.py` (binding, preload re-check, evidence expiry) and `intake_gate.py` (deterministic trigger gate, mandate, shadow-first work); round 125 adds `memory_credit.py` (utility-over-relevance arbitration), `lesson_gate.py` (falsification-gated memory writes) and `security_lattice.py` (product taint lattice, capability attenuation, provenance ledger); round 126 adds `optimizer_memory.py` (root-cause records and continuity decisions), `detour.py` (attainment, residual work, trajectory classes) and `patch_probe.py` (control-gated verdicts, sibling-path divergence); round 127 adds `memory_poison.py` (payload lifecycle, propagation descendants), `trust_boundary.py` (identity/authorization/propagation across seven seams; fail-closed — identity, authorization and capability are required evidence, so an empty call is denied) and `gap_leak.py` (information gap, disclosure, submission-time verification); round 128 adds `provider_binding.py` (selection surface vs verified provider, misbinding outcomes and stability), `gateway_shape.py` (code mode, return-shape hints, paired utility, bounded fallback) and `scoring_mode.py` (pointwise/setwise/attention, reversal pairs, strict paired success); round 129 adds `reversibility.py` (R0-R4 classes, exact-restoration requirements, capture overrides, later-writer preservation, coverage/burden replay), `gain_control.py` (expected positive remaining gain, reference score, calibrated stopping under a quality allowance, tri-state verdicts) and `history_truth.py` (record-vs-world agreement, the falsified-record contrast, the record×world interaction, re-check diagnostics); round 130 adds `composed_harm.py` (cross-screen fact composition, the single-screen guarantee check, recognition-vs-action disconnect, channel and speaker effects, the commit-point gate), `measurement_spec.py` (nine measurement choices, the specification curve, the choice that decides a verdict, the minimum detectable effect, classifier families) and `trap_path.py` (bait on the path vs beside it, prevention vs detection ablation, authenticated fresh unreplayed alert gate, scoped and reversible revocation, bait-use false positives); round 131 adds `evidence_gate.py` (tool outputs as checkable cards, admission ruled from the input and the cards alone, the budget vs selection decomposition against a matched random gate, the first-order usefulness covariance), `stress_evolution.py` (utility-constrained parenthood with counterexamples kept, separate-coordinate Pareto fronts, posterior parent sampling, a stressor promoted only when the attack works AND the task survives, matched-budget search comparison with the linear-chain regression, cross-harness transfer) and `paired_trial.py` (paired counts, exact McNemar, the A/A noise floor and its minimum detectable effect, sign replication across strata, delivery/adherence/context cost, the validity funnel, post-hoc correction); round 132 adds `evidence_scope.py` (the `(source, check, phase, operation, witness)` item, fact vs finite verdict vs authorized scope, witness origin, the three forwarding obligations, reachability and UNKNOWN, the residual-vs-regression-vs-altered-context classification, replay of a repair's explanation), `round_controller.py` (a Champion that never regresses, factual-only lessons, the four-part decision object, the code guardrails, the context ladder, frontier-vs-local evidence) and `attestation_trust.py` (identity from the key hash, the six federated-certificate checks, build attestation of model/tools/prompt, per-call policy, the signed hash-chained log with its silent end, and the multi-model containment read); round 133 adds `criterion_verification.py` (per-criterion ternary verdicts, the two N/A cases kept apart, decomposition density, the false-pass rate and confident false passes, localization and the top-k cascade), `rubric_verification.py` (the three verifier principles, read-only environment alignment, UNMET F1 with over-acceptance vs over-rejection, the batch/cost ladder, a resolved ablation vs a strictness shift) and `doc_maintenance.py` (a resolved ticket as implicit supervision, the five-type gap taxonomy, the deduping tracker, self-review plus human authority, the before/after repair measurement); round 134 adds `priority_criteria.py` (a stated priority vs its assessment criteria, focus-not-criteria, opposite answers on the same focus, a criterion traced through search/citation/judgement, a reviewable interface), `value_disposition.py` (a fixed paired value statement, the effect against the no-values and placebo controls, the solver size/complexity split, self-modification and literature-derived values, values compounding) and `cross_env_tasks.py` (a joint task over shared entities, cross-environment data alignment, executable rules with negative cases, replay plus agent attempts, the structural curriculum, unseen-combination transfer); round 135 adds `resolution_budget.py` (sigma/tau variance decomposition, the repetition budget for a claimed margin, the resolution verdict, pairwise selection accuracy with false acceptance, posterior Quality@K against an equal-quality null, why single-run gains are noise), `replay_parity.py` (state digests and replay determinism, controlled variation that cannot move dynamics, numeric trajectory and pixel parity, the warm-up/median timing protocol, the four-gate speedup audit) and `dialogue_allocation.py` (a posterior over task allocations from action and utterance likelihoods, the entropy speech trigger, typed pick-up/set-down/delivery evidence, only-affected belief updates, deterministic dynamic arrival, timestep and speedup with standard errors); round 136 adds `selective_replay.py` (the selection multiplier at the observed p-value, the tail/body replay correction with the paper's unavailable convention, the corrected decision, Neyman replay allocation, why subsampling and not the bootstrap, the time/source/invariance audit, and why a self-applied family correction does not bind), `continuation_policy.py` (stop rate and burst detection at W=20/rho=0.2, per-bin gains and the diminishing verdict, impossibility judgments and their unproven relabeling, the six-field summary, the stop-aware compaction policy, judgment-vs-no-judgment runs, SCoRe with both component ablations) and `evidence_replay.py` (a knowable evidence state, the frozen provider record, post-hoc leakage and revealed outcomes, Brier and time-averaged Brier, per-question paired intervals, the provider spread against the model spread, memory steadiness and note cost); round 137 adds `deliberation_audit.py` (a typed artifact with its fixed metadata, type/tag/coverage F1, greedy one-to-one metadata matching with hard and soft scores, coverage-penalised summary quality, the grounding/keyword/few-shot ablations, and the design-choice and structure gaps), `complexity_frontier.py` (per-regime brackets and the least-resolved setting status, an open frontier and what a candidate closes, adversarial co-ascent outcomes, domain/review/certification before admission, certified vs provisional vs failed memory, and supported vs open obligations) and `work_transfer.py` (a benchmark gain against a work-change interval, inverse-variance pooling, the ceiling rule, the causal design, the reversal contrast and its placebo, four comparison widths, and the power a single upgrade has); round 138 adds `repair_audit.py` (repair churn, candidate reachability and the acceptance gap, the three loss mechanisms, intervention capability, label-free triage flags, the provenance and replay boundary, and a priced veto), `validation_ladder.py` (the A1-A10 autonomy ladder with consequence multipliers and floor rules, nominal vs effective autonomy, the eight controls, five behavioural domains with an oversight test, ten evidence categories and calibration stability) and `skill_grounding.py` (progressive-disclosure layers, the independent verifier and generator, equivalence checks, the six typed verdicts, session savings, and what the taxonomy and analyzer each buy); round 139 adds `context_folding.py` (three linked history levels under one handle, the recoverability contract, monotone demotion in a fold, the landing-priced trigger, normalized cost, and recovery through scan/ctx/dossier), `invocation_reliability.py` (local vs global rates and the propagation loss, the depth-one wiring check, pinned severity, unobservable recovery, conditional scoring, terminal-error share, the discrimination statistic) and `evolution_capabilities.py` (harness-updating spread, non-monotonic benefit with a ceiling, activation and adherence failures, agent-vs-evolver budget, extreme pairing, in-situ scoring); round 140 adds `handoff_governance.py` (a versioned anchor of gates and requirement primitives, three postures, halt attribution with the false-alarm penalty, the paired gain against its lower bound, and the five silence states), `session_protocol.py` (a finite-state protocol and its well-formedness conditions, per-state tool withholding, rejection before side effects, protocol-safe inheritance, linear budget splits, process compliance beside the outcome, and the pressure comparison) and `pipeline_traceability.py` (structured handoffs, stagewise repair and harm, the earliest unrepaired origin, planner primacy, the accuracy/cost frontier with latency carried, role casting and the accountable-vs-simple gain); round 141 adds `defense_envelope.py` (the A/B/C/D outcome split, component weight under label-memory conflict, backend arbitration, label content against length and format, memory dose, tool roles, why a second component is not an addition, and the four misreadings), `execution_fingerprint.py` (the initial outcome and ordered repair sequence, a Laplace-smoothed Markov profile, attribution with an explicit margin, why the sequence is required intra-family, the query budget, robustness, probe optimization and the conditions a fingerprint depends on) and `model_handoff.py` (a per-step local/verify/cloud gate with risk and budget shifts, six signal families, AUROC/Brier/ECE kept apart, budget-matched headroom, the success/cloud frontier, the minimized packet, recovery by failure type and routing saturation); round 143 adds `admission_schedule.py` (a provider profile, the admission slot, AIMD with a circuit breaker, deterministic backoff, the token budget's warn/checkpoint line, a priority queue with dependency DAG and cycle detection, the ablation that names retry as load-bearing, and the direct-vs-managed pressure comparison), `stateful_scheduling.py` (the HRRN score, event-driven MLFQ promotion/demotion, the starvation guard, HRRN batch packing, the KV preserve/discard/swap choice by estimated waste, per-stage prediction, the lifecycle JCT, the baseline comparison and load stability) and `capacity_pools.py` (five service classes and their protection ordering, the priority scalar, debt and burst EWMAs, KV/concurrency resource accounting, the ordered admission checks with the 429 path, reclaim ordering, protected latency and fair-share convergence); round 144 adds `transcript_privacy.py` (suffix-aware structural slots, format-preserving session-stable handles, guarded local rebinding that rejects traversal, spoofing and metacharacters, the session entity graph, literal/categorical/reconstructive leakage, workflow compatibility and the hot path), `privacy_memory.py` (the PL1–PL4 taxonomy with its default handling policies, a thresholded typed sanitize/restore pair, joint extraction F1, utility loss against no protection, leakage counts, and the strongest threshold within a tolerance) and `privacy_audit.py` (the five-attribute flow, PASS/ABSTRACT/BLOCK under PII, minimization or contextual integrity, exposure/extraction/disposition inventories, the spread collapse, stated-vs-enforced criteria and the auditor swap); round 145 adds `harness_update_gate.py` (the named-block harness and its digest, differential regressions vs shared failures, strict-majority confirmation, rollback localisation by gain retention, verification held apart from admission, the suite-normalised risk gate with its severe-case veto, utility with fixed penalties, transfer as an observation, and the eight misreadings), `experiment_ledger.py` (the five auditability desiderata, the pre-run scope/no-op/precondition guards, the control-plane keep-discard-fail rule, the one-terminal-record invariant, acceptance/invalid/provenance/artifact rates, the repeated-bad rate with its similarity threshold, the governed-vs-ungoverned counterfactual, the structural relabeller and the failure taxonomy) and `context_prefetch.py` (per-target sliding windows, online ordinal ranks over deltas with a bounded vocabulary, the narrow request/reply contract, arrival latency against inter-arrival time, local-vs-remote benefit on runtime and faults, drop-on-full degradation and the warm-up frontier); round 146 adds `redteam_coverage.py` (the three-level taxonomy, coverage per level, technique concentration, pairwise Jaccard distance, ASR at a stated budget, equal-sample and equal-cost comparison, post-hoc label validation and the six misreadings), `purple_loop.py` (a deterministic strategy dictionary, the weighted explainability score and its bands, the coverage reward that ignores repeated strategies, the rolling-dictionary collapse test, per-reward standardisation, the ASR/UA/BU requirements, train-time vs worst-case ASR, and the component ablation) and `render_defense.py` (the three operations, text-vs-image deltas, aggregation that hides an operation, the utility ratio by question type, rendering settings, candidate budgets, the reading/following dissociation and trusted authorization); round 147 adds `state_evidence.py` (the typed semantic state, sparse-delta reconciliation against the archive, acknowledgement as visibility-only, ranked revision-aware recovery with orphan/safety/recent fallbacks and caps, evidence locality, the bounded-replay vs unbounded-pending distinction, exact McNemar on paired outcomes and the token/time benefit), `evidence_review.py` (the four nested outcomes and three steps, the aided arms, shortlist recall and the oracle gap, the figure-only vs text-supported split, asserted conflicts against accepted diagnosis, the rubric/replay/human instrument checks, the near-miss taxonomy and the repeat band) and `uncertainty_context.py` (the paired uncertainty delta, the alignment control, the evidence-budget trend, harmful flips, the upstream-correctness probe, downstream entropy after a corrected decision and prompt sensitivity); round 148 adds `skill_cfi.py` (the compiled control skeleton, the enforce/guidance/unsupported disposition, the C/S/R/F admission checks, correlated results with captures, the violation taxonomy, the typed refusal with next legal steps, and the bare/basic/next-step recovery comparison), `memory_commune.py` (scoped personal/project/session items, approved-only writes, abstraction and localization before a boundary, the confirmed working memory with expected uses, citation resolution, item-level audit with its evidence source, desired-vs-actual alignment, the perceived-vs-actual gap and monitoring/control activity) and `sparse_eval.py` (the benchmark-balanced prior, the closed-form Beta posterior with its prior weight and variance, the exact prior-sensitivity bound, expected information value, Brier, the weighted budget ALC and calibration error); round 149 adds `budget_audit.py` (the finite-horizon `V0/Qb/Vb` values, the per-step `delta` and final-answer `eta`, the exact decomposition identity over the whole tree, the branch-to-selector anchor transition, the staged read losses, the routing gain, the `2 eps` bounds and the seven misreadings), `simulator_audit.py` (paired sensitivity with an interval, the 2.5th-percentile population rule, per-suite perturbation coverage, AUROC and retention for a filter, the three levels with their geometric headline, the per-level leader table and the evidence each level needs) and `program_judge.py` (the answer-to-grade formula, the floored mean of three programs, the rubric variant, the two error directions, tau-b ranking agreement, the label-gain curve, the break-even pool depth and the sandbox import policy); round 150 adds `requirement_loop.py` (issue normalisation, the triage disposition and artifact, the two-source consolidation with `covers`, admission's evidence package and its exclusions, the design and code review gates with a head-bound merge, the issue-flow counts, delivery beside pass, the generalisation share and the seven misreadings), `secure_replan.py` (the seven repair operators over pending subtasks, the four validity conditions plus the explicit-grant rule, the thirteen-condition failure vocabulary, the repair budget and rejection limit, the two close-out channels, the exposed path and the output check's effect) and `local_cost.py` (cost per solved task, the three-term energy decomposition, capacity and the KV cache, the bandwidth bound, the required rate, cached vs computed tokens, the budget notice, local vs cloud and the seven misreadings); round 151 adds `intent_contract.py` (the bounded goal that carries no command, NFKC-validated verbatim quotation, scope narrowing from a baseline, declaration coverage in the goal vs the command, exact McNemar, the outcome triple, bundled-request completion, the four reference categories, the three properties fixed by dispatch code and six misreadings), `evidence_warrant.py` (the WRC record, tri-valued admissibility with `?` never positive, the directed transport judgment, defeasible authorization with hard prohibitions first, provenance dependence and its variance-equivalent size, two-hop composition, the selective-revalidation cost condition and six misreadings) and `platform_eval.py` (dimension means and totals, Cronbach's alpha and the halo verdict, a least-spread three-tier split, non-compensatory gates with a weighted score, Wilson reliability with `pass^k`, cost-of-pass, the business-value identity and seven misreadings); round 152 adds `continuation_audit.py` (turn-end cuts, paired realism against the source session, eval-awareness capped by the real baseline, the deviation/consequence axes with their convention, the narrow judge's severity logic, mandate classification and coverage, the policy ablation and seven misreadings), `tool_extension.py` (verified trajectories from native annotations, per-tool retention with a 0.3-point cap, the new-tool gain, selection drift as total variation, the initiate/select split, extension cost and the admission gate) and `fast_path.py` (D/G/E nodes, the E share, threshold calibration to an agreement target, the confidence gate, the `(1-sE)+sE*kappa` identity, label smoothing, risk–coverage area and the ungated collapse); round 153 adds `context_tariff.py` (the age-weighted charge, the token/request/session bounds, the coverage condition with its break-even hit rate, the decay-family comparison, the tail-for-median test and six misreadings), `hypergraph_ke.py` (native ingest with model-gold refused, entity identity and alias classes, the two-hop join share, ADD/DEL/REFRESH with the provenance invariant and the append-only counterexample, intent routing, the named-file guarantee against top-k and the equal-persona OKE) and `belief_probe.py` (acting without citing, per-category rates, the log-linear scaling fit, the three depth axes, the three-way judge, metric independence and reality separation); round 154 adds `awareness.py` (the deterministic reducer, the frozen route cost with failure and open-circuit terms, observable regret, the bounded and freshness-labelled snapshot, host revalidation and dispatch, the A/B/C ablation with Wilson intervals and the five authority violations), `diagnostics.py` (the 45-type taxonomy in eight families, finding admissibility from requirement plus violation, the count/share scope bands, the defect/risk/waste severity arithmetic, Signal grouping that refuses label-only merges, run updates that cannot establish a fix, deterministic one-to-one occurrence matching and its coverage) and `orchestration_credit.py` (the exact interaction expansion order by order, the visit-count remainder and β, the interaction-aware Z2, empirical-Bernstein certificates with the larger bound, certified selection, the detection size, paired certified leaps, the complementarity trap and the three controlled-task gains); round 155 adds `intent_audit.py` (the intent DAG and its frontier, the hardened scope language, the schema-derived tool classes, the four audit checks with the local-read bypass, ASR at the first and harmful call with benign costs, the rejected γ/identity coupling and six misreadings), `write_integrity.py` (schema-derived tool classes and argument roles, the exact grounding set G(q), the committed-write prefix, the Mediator's ordered checks with execute/deny/ask, the two trace guarantees and the component ablation) and `context_regime.py` (total vs peak context, the context-factor price model at r=0.20, the six-section execution brief, FHA/EoCC/SAC comparison, bounded selective reads with growth, single-action compaction and the collapse check, the coin-toss counterexample and six misreadings); round 156 adds `skill_gate.py` (the Cold/Warm/Hot hierarchy, the three-critic conjunction, the injection gain, the individual/combinatorial taxonomy, the capability–contamination curve, marginal-gain selection, the recovery gap and lineage rollback), `skill_flow.py` (the closed-credit ledger, the zero-sum projection gate, wave/mean-field/dissipative regimes, the acoustic speeds and credit shock, the statistical instruments and the stall diagnosis) and `skill_evolution.py` (the Skill/Reference schemas, source-grounded evidence, the three-cause diagnosis, history-free candidate validation, regression-certified consolidation and the execution bounds); round 157 adds `takeover_eval.py` (the delivery triple, the requirement atom and its five components, the omission check, the RQ1–RQ3 diagnostics, the post-state score and the clarification metrics), `anytime_cert.py` (the time-uniform PAC-Bayes radius, the finite-grid log-M price, the structured prior, the label-aware margin law, water-filling allocation and selection optimism) and `longhorizon_eval.py` (all-or-nothing pass@1, the regrade protocol, the reliability gap, held-out splits and both grading errors); round 158 adds `memory_channel.py` (four write channels by trigger and authority, the nine structural vulnerabilities, the six attack classes, ASR/RSR with the strong/weak split, detector coverage by signal strength and the capability/security premium), `memory_authority.py` (write-time origin binding, non-malleable propagation, corroboration-gated elevation over independent domains, action-bound single-use authorization, the act gate, the malleability check, the theory↔benchmark separation and a bounded state model) and `exfil_defense.py` (the three-step exfiltration chain, four memory-layer defences with undefined backend pairs, per-flow utility with both means, the security/utility frontier and the dormancy sweep); round 159 adds `multiagent_formation.py` (the four formations, outcome shares against a coordinator, the participation curve, Jain fairness, consented vs unconsented interference, mitigation arms that must reach the coordinator, and the failure-behaviour split), `teammate_eval.py` (eight teamwork dimensions, the alone-gate, the teammate drop, the 1/0.5/0 conflict rule, the missed/gave-in/stopped-short split with the recognised share, inherited cheats and the audit) and `principal_policy.py` (principals with authority and private context, precedence with an ambiguity refusal, per-resource access control, selection F1, privacy/utility with over-refusal, required/optional meeting utility and the conflict effect), driven by the `forge.py` groups (`memory`, `episodes`, `contract`, `recovery`, `effects`, `context cost`, `commit`, `expectations`, `governance`, `skills stale|value|repair|prune|compile|optimize|conflict`, `capsule`, `flow`, `selfdirected`, `harnessevo`, `contextpipeline`, `stepzero`, `harnessrecord`, `conduct`, `completion`, `skillret`, `ruleret`, `skillquality`, `opspolicy`, `execpolicy`, `skilladapter`, `intake`, `memcredit`, `lessongate`, `seclattice`, `optmemory`, `detour`, `patchprobe`, `poison`, `boundary`, `gapleak`, `binding`, `gateway`, `scoring`, `reversibility`, `gain`, `history`, `composed`, `measure`, `trap`, `evidence`, `stress`, `trial`, `scope`, `round`, `attest`, `criteria`, `rubric`, `docmaint`, `priority`, `values`, `crossenv`, `resolution`, `replay`, `dialogue`, `selective`, `continuation`, `bench`, `deliberation`, `frontier`, `transfer`, `repair`, `validation`, `grounding`, `folding`, `invocation`, `capabilities`, `govern`, `typed`, `pipeline`, `envelope`, `tracefp`, `modelhandoff`, `admission`, `statesched`, `capacity`, `slots`, `privmem`, `privaudit`, `updategate`, `expledger`, `prefetch`, `coverage`, `purpleloop`, `renderdef`, `stateev`, `evidenceview`, `uncert`, `skillcfi`, `memcomm`, `sparseval`, `budgetaudit`, `simaudit`, `progjudge`, `reql`, `replan`, `localcost`, `intentc`, `warrant`, `platformeval`, `contaudit`, `toolext`, `fastpath`, `tariff`, `hyperke`, `beliefprobe`, `awareness`, `diagnostics`, `orchcredit`, `intentgraph`, `writeguard`, `ctxregime`, `skillgate`, `skillflow`, `skilleve`, `takeover`, `anytime`, `longhorizon`, `memchannel`, `memauthority`, `exfild`, `formation`, `teammate`, `museprincipals`, `approvals`, `autonomy`, `teams`, `toolgraph`, `instructions`) |

## Harness evidence workflow

This is Longrun's own `src/longrun/harness/` package. It is not the external
Harness² upstream (arXiv:2610.14224): that is only a comparison arm in
`benchmarks/jobbench_compare.py`, and none of its code runs here.

Layout (2026-11-20), by runtime role:

* `harness/checks/` — the 137 report-only per-paper checkers. Pure data in,
  verdict out; only `core/forge.py` imports them.
* `harness/execution/` — the 9 gated executors (`probe`, `runner`, `editors`,
  `compose`, `contrast`, `whole`, `snapshot`, `gateway`, `unixshim`). Only
  `cycle` (with `dry_run=False`) reaches them, and only after
  `whole.readiness()` passes; tests inject a fake runner.
* `harness/` root — the 21 modules the running app imports (live turn seams,
  read-only HTTP surfaces and their support, including `hazard_notice` below).

### Wired vs report-only

The package is a measurement and verification library, not a set of runtime
guards. Two statuses coexist and must not be confused.

**Wired into the running app** (they read live state or participate in a real
path): `snapshot.py`, `whole.py`, `gateway.py` and `unixshim.py` for the frozen
experiment runtime below; `counterfactual.py` and `modelcf.py` behind
`api_v02.counterfactual_run` / `model_counterfactual_run` (`POST
/api/sessions/<id>/counterfactual`, `/counterfactual/model`, and the `sessions`
tool's `counterfactual` / `model_counterfactual` actions); `backtrace.py` and
`verification_transport.py` behind `GET /api/sessions/<id>/backtrace` and
`/transport`; `plan/stopping.py` behind `/stopping`; `tools/registry.py`
`TOOL_EFFECTS`, the single owner of each declared tool effect that the
catalogue publishes; `effect_types`, whose `escalation()` runs in
`api_v02.tool_action` and `api_v02.gated_call` before dispatch; and
`intent_audit`, whose objective-scoped DAG (`from_objective`) is built from the
run goal plus the live catalog in `api_v02.tool_action` (its read bypass is
limited to LOCAL reads: an external MCP tool — `client__tool` — is an external
read by construction, so a tainted `github__search_code` is audited, not
bypassed); and `effect_recovery`,
whose `adjudicate()` runs in those same two doors (`_recovery_escalation`). An
automatic approval is upgraded to `required` for a declared `delete`, for an
exact repeat of a non-idempotent call that already executed in the run (the
chat path feeds the session's recent `tool_cards` in as that trace), for a
retry of a non-idempotent call on the SAME object after an ambiguous
(timeout/kill) outcome — unless a declared read-back of that object reports the
object ABSENT (a read that was refused or failed for another reason says nothing
about the write, so the retry still asks) — and for a declared mutating tool the
objective did not authorize. The recovery record is built from that trace: the capability flags
come from `TOOL_EFFECTS` (`idempotent` and a derived `read_after_write`), the
obligation is the proposed action on one object, and `retry` is the proposed
next action. The exact-repeat identity is the caller's arguments: the gate's own
workspace injection is not part of it, and a trace row is normalised the same way
the proposed call is before either side is digested. `approval_audit` also participates: the approval store itself
produces its four observables — `create()` records the generated call,
`decide()` the human decision, `record_outcome()` the dispatch and the native
effect with the tool's own evidence as witness — and `forge approvals audit`
with no FILE audits that live store through `approvals.audit_records()`
(refusal safety and authorization completeness are then statements about the
running gate, not about a hand-written file). An ambiguous outcome (a
timeout/kill, exit 124/137/143) is recorded as `applied: None` and counted as
`approved_unknown`, not as lost approved work; only an observed non-effect is
`applied: False`. `from_objective` only withholds a tool
with a declared effect: untyped and read tools stay authorized, and a goal that
names no namespace or effect verb authorizes everything, so generic prose never
invents a restriction. These are approval gates, not denials, and
`approvals.mode=full` remains the operator's explicit "never ask" opt-out.

`memory_channel` and `memory_authority` participate on both sides of the memory
path. At write time, `memory.store()` records `origin` and `trigger` on every
record (an older caller gets `agent`/`policy`); the `memory.store` tool binds
origin to the CALLER — `agent` — instead of honouring the model's `origin`,
keeps the forged claim as `origin_claim`, classifies the write as the
explicit-instruction channel (C1), and stores the bound act class. The same
binding covers `memory.set_core`, the CORE block injected into every prompt and
a declared write in `TOOL_EFFECTS`; it used to be the one memory write with no
provenance. The tool gate marks a write `untrusted` when the proposing context
carried untrusted content, and its content is tracked per run (bounded per run
and in the number of runs; a run's bucket is dropped when `RUNS` evicts it). At
act time, `api_v02._memory_gate` runs in
`tool_action` and `gated_call`: an automatic approval is upgraded to `required`
when a declared mutating/external call carries content from that untrusted
memory, because `memory_authority.gate()` denies it unless corroborated or
covered by a fresh action-bound authorization. `from_memory()` is the adapter
that turns a stored record into the authority item both checks consume.

Both `intent_audit` and `write_integrity` read the same schema record:
`tools/registry.py` `tool_record()` is the ONE bridge from a live spec to the
flat `args`/`required` shape, and `harness/tool_policy.py` is the ONE
verb/role classifier they share (the old independent lists had already drifted).
`write_integrity.mediate()` therefore classifies real tools instead of denying
them as unclassified, but it still has no live caller: a call needs a
request-grounding set and a committed plan, neither of which the runtime
produces yet.

**Report-only** (measurement, not enforcement): the deterministic per-paper
checkers added from round 110 onward — `trust_boundary`,
`write_integrity`, `context_regime`,
`skill_gate` and the rest of the `harness/` list above — and
the `forge.py` groups that expose them. Each reads a JSON record from disk,
calls one function and prints a verdict; no agent-loop, approval,
tool-dispatch or HTTP path calls it. Memory provenance and the act-time memory
gate are the exception already described above; what stays report-only is the
schema-derived write policy (`write_integrity.mediate()` has no grounding set or
committed plan) and the trust-boundary gate (no seam emits identity,
authorization and capability evidence). A checker's verdict is evidence about
the record it was handed, never a statement that the live system is protected.

`effect_types.verify_trace` stays report-only (the live gate uses
`escalation`), and its findings follow the declared contract: a read clears a
prior write, an append is never a repeat, and a tool's own declared read does
not satisfy `delete-without-read` (that rule measures the agent's trace, not the
tool's precondition). `coverage` reports an invalid declaration as `invalid`
instead of folding it into `untyped` and counting it twice. `tool_graph.rank`
never recommends an edge whose only evidence is failure. `reversibility.classify`
takes the highest matching rule, so reordering the rule list cannot lower a
class, and `capture_override` accepts only R1 and reverts to the base class when
the capture contract is incomplete.

Promoting a checker to enforcement is deliberate work, not an implied
consequence of the module existing. The cut points are the tool gate
(`tools/registry.py` plus dispatch), the memory write path
(`memory/stores.py`), and the approval path (`tools/approvals.py`). Until such
a change lands, treat the report-only groups as a measurement surface.

`GET /api/harness/cycle` reports the effective enable flag, whole-run readiness,
canonical library counts and last cycle. `POST` defaults to a dry run: build a
**session aggregate** from existing `memory.stores` tool cards and current
workspace deliverables, then list relevant library entries. It calls no model.

Editors generate ephemeral skill/guardrail candidates, reusing complete bounded
library files with hash provenance. A cycle now freezes ONE matched input package
(`harness/execution/snapshot.py`: code, config, skills, rules, workspace, per-file SHA256),
executes a **reference run**, then each candidate as a hardlinked variant that
differs only by the declared component. `repeats` (1–3) executes paired
reference/candidate runs; reflection raises confidence only when every repeat
agrees and still returns `NO_ENTRY` for durable library writes.

Production execution is confined by `harness/execution/whole.py` through the existing
`sandbox` launcher: pinned image digest (`deploy/harness-runtime.Dockerfile`),
`--network none`, read-only `/input`, bounded tmpfs writes, dropped
capabilities, non-root, resource limits, and verified container removal. Model
access is the ONLY channel: a Unix socket serves `harness/execution/gateway.py`, which
forwards to one fixed loopback upstream and one allowlisted model under request,
body, token and time budgets. The container's loopback TCP is bridged by
`harness/execution/unixshim.py`; the gateway remains the policy owner.

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

Optional knobs (all owned by `harness/execution/whole.py:DEFAULTS`): `LONGRUN_HARNESS_REPEATS`
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

## Newest online papers (round 163, 2026-11-20)

Four papers submitted 2026-11-18/19, read in full, each landed as one capability.
The deterministic halves are report-only checkers; the two that belong in the live
loop were wired where the model reads its own work.

- **A hazard notice on every tool output** (arXiv:2611.26553, ROGUE-AI). Of 72
  real-world agent incidents 62 had no attacker: the agent did what the task asked
  and missed an ordinary hazard such as a production database shared with the live
  site. A note attached to the tool output that names **the hazard and its
  consequence** lowered harm for all five tested models; a fact-only note of the
  same length did not. `harness/hazard_notice.py` classifies the call from the
  tool name, arguments and output (production target, destructive verb,
  credentials in reach, shared resource, public surface, money movement) and the
  chat loop appends its one line to the observation it is about to inject —
  silent when no rule fires, never fatal. `forge.py hazard classify|notice|audit`
  exposes the same rules plus the incident/control test (one-sided Fisher).
- **A lossless history log with grep recall** (arXiv:2611.25123, GrepMem).
  Summaries and masking lose exactly the detail a later question needs; an
  append-only plain-text log plus one regex tool reached 95-97% on ContextBench
  where lossy baselines stayed at 6.6-20.7%. `memory/stores.py` writes
  `<data>/sessions/<sid>.log` from the three persistence points (message, tool
  card, harness inject) and the delete cascade removes it;
  `context.grep` / `context.count` search it (regex, chronological line numbers,
  context, pagination, count-only) with no index and no embedding. The pure half
  is `harness/checks/recall_log.py` (`forge.py greprecall`).
- **A cross-OS skill contract screen** (arXiv:2611.26256, SkillBridge). A skill
  is a contract over guide text, package surface, metadata, install lines and OS
  assumptions; static screening is recall-oriented triage for dynamic validation,
  never a verdict. `harness/checks/skill_os_contract.py` builds the contract and
  fires a rule only when it is matched, reachable, in conflict with the target OS
  and not covered by a fallback, naming the contract field and the repair target.
  `skills.install_skill_file|install_skill_dir|install_zip` return the screen as
  `os_warnings` beside a successful install (`forge.py skillos`).
- **A memory dose that belongs to the model** (arXiv:2611.26361). A strong model
  improves with the full guideline set; a weak one does worse with it and gives
  no error. Consolidation is support-conserving (each guideline records how many
  lessons it merged, plus polarity and source tasks) and delivery selects a
  dose. `harness/checks/guideline_budget.py` enforces the conservation invariant
  and the per-capability dose (`forge.py guidelines`); the live memory index
  ranks `agent.note` lessons by support and bounds them with the new
  `context.memory_lessons_cap` (default 4).

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
`session_jobs/` (one in-chat SJ ledger per session) ·
`events.db` (durable SSE feed) · `projects/` (per-workspace Project_rules.md, rules/,
prompt.d/ — the project scope ALSO loads every `.md` of `<workspace>/.trae/rules/`, the
operator's own rules folder, exactly like Trae's Reference list; see
`memory/rules.py:project_rules_dirs`). Writes are atomic (`tmp` + `os.replace`). The root is resolved by
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
| Team job / subjob (J<n>) | `DELETE /api/jobs/<id>` / the `job.delete` tool | `jobs.json` has NO automatic retention |
| Session Job (SJ<n>) | dies with its session: `/clear` or `DELETE /api/sessions/<id>` (same cascade) | in-chat ledger only, read-only, no retention |
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
