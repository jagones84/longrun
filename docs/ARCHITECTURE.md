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

**The `harness → LLM` chat label is the wire** (2026-11-05). One chip exists per
message actually appended to the outgoing list, its body is that message verbatim
(role + `[harness] ` prefix), and a suppressed repeat is only a counter on the
message it repeats. Nothing the model never received is shown under that label, a
message withdrawn by the mid-turn trim takes its chip with it (`harness.drop` +
`stores.drop_inject`), and `sess["injects"]` records exactly the sends (no merge),
so live, reload and wire agree.

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


## Components (`src/longrun/`, organised in subpackages)

| Subpackage | Modules |
|---|---|
| `core/` | `server.py`, `api_v02.py`, `httpapi.py`, `sse.py`, `events.py`, `forge.py`, `settings.py`, `diagnostics.py`, `configfiles.py`, `sidebar_order.py`, `matrix.py`, `homemove.py` |
| `agent/` | `agent.py`, `agents.py`, `subagent.py`, `bridge.py`, `agency.py`, `swarm.py`, `session_jobs.py`, `architect.py`, `acceptance.py`, `trace_policy.py` |
| `orchestrate/` | `jobs.py`, `orchestration.py`, `teams.py`, `routines.py`, `roles.py` |
| `plan/` | `taskgraph.py`, `keepgoing.py`, `goal.py`, `difficulty.py`, `bestofn.py`, `prm.py`, `heldout.py`, `verify.py` |
| `tools/` | `tools.py`, `registry.py`, `approvals.py`, `sandbox.py`, `hooks.py`, `edits.py`, `term.py`, `bgjobs.py` (detached shell jobs: start/status/stop), `diag.py`, `matrix_guard.py` |
| `model/` | `providers.py`, `routing.py`, `context_engine.py`, `prompt.py`, `runmetrics.py`, `otel_tracing.py`, `rllm.py`, `keys.py`, `costs.py`, `embed.py`, `compaction_config.py`, `structured.py`, `vision.py`, `decision.py`, `rerank.py` |
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
| harness candidate (`skill` kind) | Harness² cycle editor | `harness/editors.propose` → `probe.stage` | material tested by a matched run |
| verified | `improve{verify}` / `decide` | `selfevolve.ensure_check` + `verify` | the sandbox check went green |
| proposal (`scope=skill`, bound to a draft OR to tested bytes) | mined draft or matched experiment | `improve.propose` | ONE decision object |
| installed skill | approval, or `evolve` when `approvals.kinds.skills=auto` **and** the sealed held-out suite is installed | `selfevolve.promote` (draft) / `skills.install_skill_file` (harness bytes) | never clobbers an existing skill — it supersedes it (retire + swap); one ledger `promote` row per install |
| forged Matrix tool (`learned_<slug>.run`) | `improve{forge}` on a draft, `improve{evolve}` (human-approved), or the background pass when `approvals.kinds.matrix=auto` | `selfevolve.forge_target` (the naming) → `selfevolve.forge_bundle` (validation + the exact bytes) → `selfevolve.forge_matrix` → `matrix.scaffold` → `matrix.run_test` → `matrix.verify_target` | executable, but only after its own generated test and the sha-bound contract gate pass; removed when they do not. `evolve` asks `forge_target` first, so a pattern forged in an earlier pass is `skipped`, never a clobber refusal |
| learned Matrix bundle (proposal) | background `evolve` when the `matrix` policy is not `auto` | `improve.propose(scope="matrix", artifacts=[…sha256])` → `improve.decide` → `matrix.apply_learning` | the same bytes `forge_bundle` would write, held pending until the operator approves; approving writes + hot-loads, denying writes nothing |
| Matrix artifact | approval | `core.matrix.apply_learning` | outside Nucleus, hash-bound |

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
