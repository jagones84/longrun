# Changelog

All notable changes to Longrun are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project adheres to
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- **The regression gate now says where it is.** `tests/battery.sh` truncates and then
  appends `.agent/battery-progress.log` in real time — `RUN`, one `START`/`END <test>
  rc=<n> <ms>` per test, `DONE` — so a slow or hung run names the test instead of
  showing an empty screen until the aggregate summary. The final output prints the
  path. (Diagnosed with it: the same suite that is 247/247 on the DGX reports
  187/247 on Windows when 12 workers share one box — every one of the sampled red
  tests passes standalone.)
- **Sessions can talk to each other.** `sessions` gained `action=send`
  (`session`/`to` + `message`/`text`). A RUNNING peer receives the text inside its
  current turn through the operator's steer inbox; an IDLE peer gets a real
  server-side turn through the shared `Orchestrator`. `send` returns immediately
  with a `message_id`; `sessions.read` can inspect the peer while it works, and
  `sessions.wait` follows that exact job/turn to return its reply, completion time,
  or failure. Repeating `wait` returns its cached terminal result. Every delivery
  is prefixed with `[message from session <id>]`, a peer cannot message itself,
  and the operator explicitly chose session dialogue over isolation. Pinned by
  `v507` F–F9 and `v350` A4.

### Fixed
- **Two `shell` calls in one `batch` silently lost one.** The batch ran every tool
  item in a thread pool, but the shell is ONE persistent terminal per caller with a
  single `busy` slot: the second `shell.exec` returned "busy — wait for the current
  command" and its work vanished (reproduced: 1 busy out of 2). Terminal-backed
  tools are now serialised *inside* the batch, in the model's order, while every
  other call stays parallel — no extra shells, the shared-terminal contract holds
  (the operator still sees the same shell, and parallel subagents keep their own
  per-run terminal). This collision is also what killed delegated work: the child
  repeated the identical batch and the no-progress guard ended the run at
  `max_steps=4`. Locked by `v528` G0–G3.
- **The Codebase panel never said whether a re-index was needed.** The numbers (files,
  chunks, vectors) cannot answer "is a file NEWER than the index?", so a healthy index
  looked identical to a stale one. `codeindex.freshness()` now compares the tree's
  newest mtime with the newest mtime the last build SAW (`newest_mtime`, recorded at
  build time) and the status route always returns a verdict: a warm watcher answers
  by construction (no walk), otherwise a **bounded** scan (0.5 s / 20k files, and it
  admits `partial`) answers. The panel shows a green **✓ no re-index needed** or an
  amber **⚠ N files are newer than the index · press ⚡ build**, plus `built <ago>`
  next to the DB size. Clicking `files` a second time now CLOSES the file list (it
  used to stay open forever), and a workspace change closes it too. Locked by
  `v542` E1–E9.
- **“No indexable files found” was a dead end for an agent session.** An agent owns
  `<data home>/workspaces/<agent>`, which starts EMPTY, so the Codebase rail's build
  honestly indexed 0 files and the panel only said “no indexable files” with no way
  out. `/api/codebase/status` and `/api/codebase/build` now carry
  `default_workspace`, `empty` and a `hint` naming the folder they scanned and the
  default workspace, the panel renders that reason, and an **explicit**
  `index default workspace` button links the default folder to the session and
  rebuilds — the scope is never swapped silently. The Workspace rail refreshes with
  the new folder. Locked by `v542` D1–D7.
- **A failed model turn can no longer be recorded as a finished subjob.** When a
  worker's turn ended in the harness error record (`⚠️ error: … provider 500 /
  timeout`), the subjob and the run were marked `done` with the error text as the
  deliverable, and a job could finish `done` on an error. `jobs._error_turn()` now
  detects that record: the worker outcome is retried like any other non-DONE
  attempt, then marked `failed` with the provider reason, and the coordinator's
  planning/final turns fail loudly instead of synthesising from an error string.
  Locked by `v337` G1–G5.
- **The turn-reply extractor is written once.** `dispatch` and the job runner each
  carried their own copy of "which assistant message is the reply", so a fix in one
  path could silently miss the other. `stores.turn_reply(messages, longest=False)`
  is now the single implementation (`longest=True` keeps the deliverable over a
  trailing harness summary, JAG-303); `v303` locks both call sites.
- **`v536` G10 no longer races the cancel result.** The check read the tracked
  job's result as soon as the process left the registry, before `_run_tracked` had
  published stdout/stderr — it failed intermittently under parallel battery load.
  It now waits (bounded) for the real result.

### Changed
- **Cost panel states its scope and prices DeepSeek by time of day.** The header is
  now `Cost · harness only` (it counts the calls Longrun made, not the whole provider
  API key), with a note that hours are local and DeepSeek is peak/off-peak by UTC.
  `costs.rates_for(model, ts)` halves the table's PEAK rates for a DIRECT DeepSeek
  call outside 01-04 / 06-10 UTC on weekdays (and all weekend), matching the official
  page; each ledger row records `off_peak`. OpenRouter refs are never adjusted.
  Locked by `v531` F2–F6. Stale `deepseek:deepseek-reasoner` session models (retired,
  no longer priced) were migrated to `deepseek:deepseek-flash`.
- **Settings ▸ Orchestration is now “Swarm & blackboard”.** The tab opens with a
  plain explanation that it is NOT the subagent engine (that lives in Subagents) and
  what its two halves do: the shared versioned blackboard and the swarm runner that
  spends N+1 model turns on throwaway subagents. Both panels cross-link each other
  (`gotoSubagents` / `gotoOrchestrate`). Locked by `v536` H8/H8b.
- **Exclusive tools are named `namespace.tool` (two segments, no deep paths).**
  The 48 VEO tools were renamed from `longrunAgent.teamorg.agents.prompt.set`
  style to one object namespace + one explicative verb: `agent.prompt_set`,
  `team.member_add`, `job.dispatch`, `routine.list`, `session.rename`,
  `webui.inspect`/`configure`, `provider.set_default`, `mcp.test`, `skill.remove`,
  `kb.notebook_add`. `_namespace`/`_subtool` follow the key, the dual-permission
  gate and the `SAFETY_GUARD` key off the registry's `_origin: exclusive` (not a
  prefix), and dispatch routes exclusive tools by that same origin. The Tools
  panel therefore shows ten short, alphabetically ordered namespaces instead of
  scattered nested paths. Live overlay keys were migrated in place
  (`longrunAgent.webui.configure` → `webui.configure`,
  `longrunAgent.teamorg.teams.create` → `team.create`). Locked by `v537` A1–A3b.
- **Sidebar reorder is name-only and synchronized.** Mouse drag starts on a team or
  session name; touch requires a hold before dragging. A normal click/tap still
  selects a session or toggles a team. Mobile reorder has no arrow or grab icons.
- **Team drag actually moves teams.** A team header was bound before it was
  attached, so `closest(.sgroup[data-team-order-id])` resolved to null and only
  session rows could be dragged. The bind now runs after attachment, and a team's
  drop midpoint is measured on its header (never on the whole group body), so a
  downward drag over the name inserts after that team. Pinned by `v538` A17–A18.
- **The chat model list follows the live server, not just the example file.**
  A local provider's catalogue is completed from its `/v1/models` roster, so a
  model installed in llama.cpp is selectable without editing providers.yaml.
  Diagnostics read the same live cache and no longer flag such a model as unknown.
  If a saved model disappears (retired ID, removed local model), the UI switches
  to a usable model and persists it: a loaded local model first, then the
  configured default, then another available model. Pinned by `v539`.
- **The Codebase inspector no longer carries a generic Automate bar.** It has an
  explicit `automatic indexing` toggle; the free-form longrunAgent control stays in
  the Settings panels where it can change a section. Pinned by `v534` E9.
- **Agents can read the exact Settings diagnostics.** `self` gained
  `action=diagnostics`, optionally filtered by `code`/`source`, returning the same
  `diagnostics.collect()` report (no duplicated checks) with file/field/panel/
  session/model isolation. Pinned by `v539` and `v414`.
- **Mobile side panels use the full content viewport and remain exclusive.**
  Opening Sessions closes the Inspector and vice versa below 900px; desktop layout
  and resizing remain unchanged. The top bar and bottom navigation stay available.
- **Cost is labeled as an estimate and exposes its evidence.** The ledger separates
  provider-reported exact charges, token-rate estimates, and unpriced calls. Input,
  output, and cached tokens are visible. Direct prices use exact `provider:model`
  keys; OpenRouter and DeepSeek refresh from their documented sources, while other
  verified rates are maintained locally. Unknown or retired models remain unpriced.

### Fixed
- **Retired DeepSeek aliases no longer inherit Flash prices.** The direct provider
  catalog and `longrun_agent` direct fallback now use `deepseek-flash` and
  `deepseek-v4-pro`; its OpenRouter preference and prompt use configured V4.1 Flash.
  Only accepted V4 Flash aliases inherit Flash rates. `deepseek-chat` and
  `deepseek-reasoner` were retired on 2026-07-24.
- **Compaction now reads the WHOLE old transcript instead of dropping its middle.**
  `input_max_chars` (40 000 chars ≈ 10k tokens) was applied to the entire transcript
  as `head 70% + tail 30%` with `…[middle omitted]…`: on a 100k-token session the
  summarizer saw ~10k tokens, so the call was cheap and the summary could not contain
  what the model never read (operator report: "ho pagato pochissimo anche se il
  context era enorme"). Summarization is now map-reduce: every part of the old
  transcript is summarized and the part summaries are merged, bounded by
  `summarizer.max_parts` (default 24). Past that bound the omission is stated IN the
  input, never silent. Retry behavior remains independent for each part; it does
  not carry a learned token budget between parts. The global policy and summarizer
  settings now live together in **Settings ▸ Knowledge ▸ Compaction**; the RH policy
  editor is removed. Config paths link to the integrated editor, including the local
  overlay after its first save. Pinned by `v487` G1–G9 (including a deterministic
  180,720-token-equivalent transcript with all 240 markers reaching map parts) and
  `v491` A1–A6.
- **Nucleus snapshot restores no longer blame concurrent Longrun writers.**
  Protected shell/Python operations already use snapshot → execute → restore; parallel
  sessions could make one operation attribute another's edits to its own command.
  A process-wide reentrant lock now covers guarded executions, Matrix promotion, and
  config writers, while model generation remains parallel. Only narrowly proven
  read-only waits bypass the snapshot. External processes cannot share this in-process
  lock. Pinned by `v498` R–T2.
- **Skill search filters weak multi-term matches.** A single generic word found only
  in a skill body no longer qualifies a multiword query; two distinct terms must
  match unless the skill name/title matches. Single-term searches require a match in
  the name, title, or description. Pinned by `v198` F4b.
- **`memory.forget`/`memory.invalidate` with `query` deleted nothing and said it
  worked.** The ids came only from semantic search, and a semantic backend scores an
  exact ID-like token below `min_score`: live, `forget query="PROBE-STORE-9c1d"`
  answered `forgot 0 memory(ies)` while the string was literally in
  `data/memory/user_memories.md`. Both actions now resolve ids by case-insensitive
  LITERAL substring (never the AND-of-words fallback, never similarity — a delete has
  no undo), and a query that matches nothing is an explicit failure instead of an
  empty success. Verified live: the audit's leftover was removed (`count=1`, token
  gone from disk). Pinned by `v317` E1–E7 (RED at the previous commit: 19/24).
- **`index.search` no longer cites files that were deleted.** A rebuild pruned a
  removed file from the index but a search did not, so the agent could quote
  `_idx_probe.md:1` after `rm`. Hits are now filtered by `os.path.isfile(path)` before
  ranking/fusion. Pinned by `v399` C4a/C4b (RED at the previous commit).
- **The Nucleus write gate no longer loses a symlink race it cannot see.** The gate
  judges paths AS WRITTEN before the command runs, so
  `ln -sfn <nucleus>/tools /tmp/nl && echo probe > /tmp/nl/_p.txt` passed (at check
  time the link did not exist) and wrote through it into the Nucleus. Creating a
  symlink whose SOURCE resolves inside the Nucleus is now refused outright. Pinned by
  `v498` P.
- **A file created inside the Nucleus is removed whatever its extension.** The
  snapshot only tracked a fixed extension list, so a created `_probe.txt` survived
  every restore while `.py`/`.md` creations were removed. The snapshot now records an
  existence set for every file and keeps content bytes only for tracked extensions;
  pre-existing untracked files (`webui/assets/*.png`) are still never deleted. Pinned
  by `v498` Q/Q2.
- **`memory.clear_core` no longer claims a clean wipe.** The CORE block is injected
  into every prompt, so earlier copies are already part of the session transcripts,
  the thread ledger and the event log (the audit found the marker in five files). The
  tool now says so instead of implying the text is gone. Pinned by `v317` E8.

### Fixed
- **The Editor's keyboard search follows the session too.** The tree pane's search
  box is session-scoped (`/api/fs/find` reads `sf_session` when it fires), but a
  session switch left the PREVIOUS session's hits on screen: `loadTree()` gives up on
  the pane while a search is active (JAG-501) and nothing re-ran the query, so the flat
  hit list kept naming files of the old workspace. Live: with `hitl` typed in a session
  whose workspace was `…/TESTS/harness-e2e` (3 hits) switching to one rooted at
  `…/TESTS/kb-agent` now re-runs the query (no match, and `page-1` returns that
  workspace's files); before, the old hits stayed. The switch also refreshes the
  workspace root the tab markers read (`_syncRoot()`), because a search replaces the
  tree rows and the pane is never repainted. The guarded listing fetch is now ONE
  helper (`_sessionListing()`) shared by both callers. Pinned by `v505` A12/A15/A17–A19
  (45/45; RED at the previous commit = 40/45).
- **Switching session now repaints the Editor's file tree.** The dock's tree pane
  mirrors ONE session's workspace, but nothing recorded WHICH session it was showing:
  on a switch the only test was "does the pane already have rows?", and the rows of the
  PREVIOUS session satisfied it, so the reload that mattered was skipped. Live repro:
  after selecting a session whose workspace is `/home/jagones/Repositories/TESTS` the
  tree still read `harness-e2e/` (the previous session's folder) while
  `GET /api/fs/list?session=…` answered `TESTS` (8 entries). A reply that landed after
  the switch was painted too, which is how a first load with no session yet in
  `localStorage` showed the parent `/home/jagones`. The pane now stamps the session it
  belongs to (`state.treeSid`, `null` = never loaded), every load is gated by that
  stamp (`_treeStale()`, used by the switch, `show()` and the reveal), a stale reply is
  discarded instead of painted, and the tab bar is re-rendered once the workspace root
  arrives — the ⚠ "outside the workspace" marker was otherwise computed against the
  previous session's root. Pinned by `v505` (A11–A16, 42/42; 6 new checks RED at HEAD)
  and `v295`.
- **Rewinding to a todo no longer deletes the todo list, the prompt, or the steps
  before it.** The per-todo ⏮ promises "undo this step and everything done after
  it", but the prune was timestamp-based: ONE `todo.write` stamps its whole batch
  with the SAME `created` (verified live: `n1` and `n2` both `1792595473.483`), so
  the cut dropped the entire batch. Worse, a turn anchor is a PRE-turn snapshot, so
  for a step of the current turn the rollback restored a graph that never contained
  the earlier steps and nothing came back — live: ⏮ on `n2` emptied the whole list
  instead of leaving `[n1]`. The prune now goes by the target's POSITION in the live
  graph, and the workspace revert cuts at the last tool call of the last SURVIVING
  step (the edit journal has no node id, so the target's own `created` also reverted
  the surviving step's file, leaving a `done` todo whose evidence pointed at a file
  the rewind had just deleted). Writing the survivors also goes through the graph
  loaded from the session: re-loading after `_restore_graph` archived the file
  returned `None` and `save({})` wrote `data/graphs/unknown.json`, a graph no session
  owns (an orphan of that shape was found on the DGX). Pinned by `v433` (17/17,
  4 new checks + a D5 workspace-cut assertion).
- **A failed manual compaction is now a 400, not a 404.** `POST /api/context/compact`
  answered 404 for every semantic failure (unknown session, nothing to compact), so a
  logic error looked like a missing route and disagreed with `/api/compaction/policy`
  immediately below it. The unrelated ~7 s latency suspected on `/api/skills` and
  `/api/self` was measured and dismissed: every warm route answers in under 50 ms.
- **The WebUI script no longer dies at load, and `.json` attachments upload.**
  `_syncAttachmentBusyUI()` was invoked at script top level although it reads
  `runningSessions`, declared thousands of lines later: a Temporal Dead Zone
  `ReferenceError` that aborted the entire WebUI script, so every binding after it
  (composer wiring, the editor layout constants) was never applied — surfaced as a
  second `Cannot access 'CHAT_MIN_W' before initialization` from `editor.js`. It now
  runs only from the init chain. `POST /api/attach` also accepts EVERY content type:
  the guard that excluded `application/json` (a copy of the zip-upload guard) made a
  plain `.json` attachment fall through to the JSON dispatcher and answer 404.
- **Chat attachments now finish Knowledge ingestion before the next message can
  be sent.** The upload response identifies every supported/indexable file, and
  the UI routes it into the notebook owned by the session captured at upload
  start. The composer stays disabled until indexing finishes; failures remain
  visible and must be removed before sending. Images still travel directly to
  vision-capable models as well as through optional OCR/caption indexing. The
  Session notebooks list refreshes as soon as ingestion succeeds. Knowledge
  chunk insertion also replaces a colliding orphan FTS5 rowid, fixing
  `constraint failed` errors that blocked both attached PDFs and text sources.
- **Tool schemas now teach the exact subtool contract, and destructive actions
  require approval.** Canonical tools expose only arguments used by that action,
  including required source/query/skill inputs; Knowledge clarifies notebook
  names and IDs, and Matrix Git tools identify their separate repo. Matrix reset,
  rollback, cleanup, and WebUI reset, plus permanent memory deletion/core
  writes/clears, now override namespace auto-approval in normal mode;
  `approvals.mode=full` remains the global opt-out. Alternative required fields
  are exposed and validated by the schema; an empty `memory.forget` can no longer
  fall through to bulk purge. Failure coaching counts consecutive failures per
  tool, so `http.fetch` errors cannot mislabel a later `browser.fetch`.
- **Agent tool actions now match their handlers.** `improve.verify`/`promote`
  infer the `mine` scope and require only a proposal path; proposal scope errors
  list exact singular values. Agent-triggered `context.compact` now reloads the
  shared compacted transcript into the active turn before it saves again.
  Hermes-style XML tool calls are parsed instead of being shown as final text.
- **Improvement decisions are distinct from tool approvals.** Skill proposals
  cannot be accepted until skill application exists; the UI disables that action
  and shows failures instead of claiming success. `v521` adds a deterministic
  batch smoke test for basic tools and these UI contracts.
- **One approval inbox for tools and improvement proposals.** `GET /api/approvals`
  now merges gated tool calls with pending proposal requests (`imp:<id>`), and the
  Inspector's Approvals panel decides both. Settings ▸ Improvements links to that
  inbox instead of carrying a second set of buttons; unsupported skill approvals
  stay disabled with the real reason.
- **Matrix artifacts can be uninstalled completely and live.** `matrix.remove`
  deletes the source file, bytecode, imported module, discovery cache, matching
  tool-policy entries and verification record, then hot-reloads with post-checks.
  Multi-subtool modules must be removed by namespace; a promoted Nucleus copy is
  reported but never touched.
- **Matrix lifecycle descriptions now tell the model the real sequence.** Scaffold
  responses return `next_steps` (edit schema/description → hotload → test →
  verify → promote), and the generated tool description is an explicit placeholder
  that must be replaced with precise behavior, inputs and output.
- **Resolved file-change cards no longer offer stale actions.** After a
  successful approve/reject, the chat card shows the decision and removes the
  opposite action; failed or cancelled decisions remain actionable.
- **A pending proposal is no longer hidden by a decided duplicate.** The
  Improvements panel deduplicates by `(scope, content)` but now keeps the
  pending copy, so its count agrees with the approval inbox.
- **A tool's verdict is now one deterministic exit code, and a failure keeps its
  evidence (JAG-523).** `_dispatch_execute` normalises every return path (usage
  error, unknown tool, Matrix/MCP dispatch failure, handler result, crash) to the
  single table `0` success · `1` semantic failure · `64` usage · `124` timeout ·
  `125` sandbox exec error · `126` blocked · `127` unknown/no implementation ·
  `130` cancelled, and `ok` can no longer disagree with it. A handler that
  reported `ok:false` without a code used to inherit an invented `125` (the
  legacy Matrix wrapper's default), so a missing file or a failed verification
  looked like a sandbox failure. The observation renderer now always prints the
  verdict header `[tool] exit=N ok=B backend=… sandboxed=…`: the old
  short-circuit reduced a failure to `[tool] ERROR: …` and dropped
  `kind/name/path/line/sha256`, partial stdout/stderr and the remaining
  structured fields. A local decision-layer block is `126` (blocked), not `127`.
  A Matrix verification script's own return code is reported as `script_exit_code`
  evidence and can no longer masquerade as a harness verdict. `v523` locks the
  table and `v347` locks the renderer.
- **Native DSML tool calls in the live dialect are executed, not retried as "invalid
  JSON".** The `Tool Tests` session (`0e13bdb23c5b`) collapsed after a compaction: the
  model (`deepseek:deepseek-reasoner`) answered with DeepSeek's native markup in a
  THIRD shape — `<invoke name="tool" string="true">shell.exec</…>` (extra attribute, tool
  name as element TEXT, mismatched `</… parameter>` close). `_dsml_action` required
  `name="X">` immediately, returned `None` for all nine calls, and the loop reported
  *"That JSON was invalid or incomplete"* although the reply held no action JSON — no
  tool ever ran and four retries stopped the turn with five steps still open. The
  parser now reads the invoke body to its real close, accepts `invoke`/`invocation`
  and both tool-name sources, and unwraps a lone `args` object. A genuinely nameless
  markup now gets a DSML-specific retry that names the protocol instead of blaming
  JSON. Pinned by `v369` E1–E5 (24/24; E1–E3 RED at the previous commit).
- **A manual compaction keeps the `keep` the Context panel shows.** The 🗜 button
  forced a hidden 2-MESSAGE window: `40 → 3` messages while the panel said
  `keep_recent: 8` (live card: *"target 16% of budget"*, a target that path never
  uses). It now honours `KEEP_RECENT` from `config/compaction.yaml` (or the WebUI
  overlay) and reports the real window (*"kept the newest N messages verbatim"*). The
  dead `COMPACT_MANUAL_KEEP_RECENT` constant is gone. Pinned by `v458` C3–C4
  (RED `after=3` at the previous commit) and `v485` pins its own 2-message window for
  the artifact horizon.
- **An SVG tab no longer requests a preview the server refuses.** The editor treated
  `.svg` as an image and pointed an `<img>` at `/api/fs/raw`, which answers **415** by
  design (an inline SVG runs its embedded JS at this origin — JAG-232). Every SVG tab
  painted a broken image and logged the 415. SVG is XML: it now opens in the code
  editor. Pinned by `v232`.
- **A price change is visible on the next lookup, with no restart.** `_prices_table()`
  cached the merged table for the life of the PROCESS, so a refreshed (or hand-edited)
  `config/prices.yaml` stayed invisible until a service restart. The cache is now
  stamped with the mtime+size of all three sources (cache, `config/prices.json`,
  `config/prices.yaml`), so the Cost panel sees a new table immediately. A price
  change is still never retroactive: each ledger record keeps the `usd` it was priced
  at. Pinned by `v527` B2/C4.
- **The model can no longer compact its own context below the policy trigger.** The
  `context.compact` tool called the MANUAL path, which forces: live, the Tool Tests
  audit compacted `160 → 16` messages at **16.2%** with `trigger=70` and lost its own
  transcript (the worst finding of its own report). The tool now refuses below
  `trigger_pct` and names the real pct/trigger; `force: true` (explicit user request)
  still compacts, and the 🗜 button remains a human decision that forces. Pinned by
  `v214` H1–H4 (RED 15/19 → GREEN 19/19); `v521` exercises the force path.

### Added
- **"Refresh prices" now regenerates BOTH price sources, deterministically.** The Cost
  panel's button used to refresh only the OpenRouter cache. It now also rewrites
  `config/prices.yaml` from DeepSeek's OFFICIAL table: the parser reads the model
  header + the three PEAK rows, requires `cache-hit < cache-miss < output` for every
  model, and writes atomically ONLY when the whole shape validates — a changed,
  truncated or unreachable page aborts and leaves the file untouched. Entries the page
  does not list are preserved, and the legacy provider ids (`deepseek-chat`,
  `deepseek-reasoner`, …) follow the Flash rate. The UI reports both sources
  separately. Pinned by `v527` (22/22; 7/22 RED at the previous commit).
- **A book button in the chat tools bar opens this session's knowledge notebook.**
  Above the transcript refresh (↻), `📖` opens Settings ▸ Knowledge with *Session
  notebooks* already expanded, selects the notebook whose `owner` is the live session
  and scrolls it into view; with no notebook yet it says so instead of leaving the
  operator to scan every session. The notebook of the chat on screen is ALWAYS marked
  `* current` (accent edge) and the mark moves on every session switch while Knowledge
  is open. Pinned by `v428` 1h–1i/1k.
- **The collapse-thoughts control is unmistakable.** The 🧠 button in the chat tools
  bar now carries a diagonal bar over the glyph, so "hide the chain-of-thought" reads
  as an action instead of a category. Pinned by `v428` 1j.

### Changed
- **`/goal` keeps working until evidence-backed completion (JAG-517).**
  - Explicit user goals now have a distinct mode from headless jobs. They continue
    past ordinary round, no-progress, and per-turn iteration limits; the model
    cannot end early with final prose, a `finish` envelope, or an artifact while
    the current plan lacks evidence-backed completion.
  - A missing/closed-but-unverified plan triggers recovery. Stop, a blocked task,
    runtime failure, and the configured wall-clock cap remain explicit incomplete
    outcomes; they are never reported as goal completion. The wall cap is checked
    from request start (including the synchronous planner) and after each model
    response/best-of-N sample. Matrix policy hooks may add explicit stops, but
    cannot label an incomplete plan `goal_reached`.

- **The task-list actions are a real NAMESPACE, and FULL mode unlocks the fs
  roots (JAG-516).**
  - **`todo.write` / `todo.update` / `todo.replan`** replace the flat
    `write_todos` / `update_todos` / `replan_todos`: the chat renders them in the
    SAME card structure as every other namespaced tool (`fs.read`, `shell.exec`),
    the prompts teach the namespaced form, and an explicit pre-namespace spelling
    is still ACCEPTED (old transcripts, the v0.6 taskgraph path, weak models) —
    `_normalize_action` just canonicalises it.
  - **A ↻ button in the Sessions header re-reads the chat**: the same path a page
    reload takes (transcript rebuilt in chronological order, todos and their
    nesting restored, plan and context refreshed).
  - **`approvals.mode=full` now lifts the fs.* ROOT allow-list, not only the
    workspace boundary.** `fs.read` / `fs.write` / `fs.edit` reached only
    `.` + `/home/jagones/Repositories` while `shell.exec` had no root policy at
    all; with the explicit opt-out they see the whole filesystem, and every other
    mode keeps the per-tool roots.
  - **Provider-direct DeepSeek models stop being "unpriced".** The ledger prices
    only what OpenRouter's public catalogue lists, and DeepSeek has no
    machine-readable price endpoint, so `config/prices.yaml` now ships the
    OFFICIAL rates (source + date in the file). A basename collision between the
    cache and a configured file now resolves by the DOCUMENTED precedence
    (env > config > cache) instead of first-writer-wins.

### Fixed
- **Archived plan tasks stay out of the current model plan (JAG-519).** When the
  current plan is empty, prompt rendering, todo deduplication, completion checks,
  re-plan prompts, open-step counts, ordinary-chat pivot/keepgoing gates, and
  update lookup no longer treat historical nodes as active. Empty plans are not
  described as completed. The Plan panel labels its latest-nonempty fallback as
  historical. Narrow cost-panel rows and model labels wrap instead of clipping.
- **Tool calls now reject incomplete web inputs clearly and recover valid nested
  argument wrappers (JAG-518).** `web.search` requires `query`; `web.fetch`
  requires `url`. Missing and blank required values receive distinct errors, and
  empty searches are rejected before contacting a backend. Public `web.fetch`
  remains separate from local-allowlist `http.fetch`.

### Changed
- **The editor's empty state keeps the workspace tree usable (JAG-515).**
  Opening the dock with no active file now reveals the tree and loads it by
  checking for actual tree rows, not static search controls. The empty-state hint
  is shorter; saved tabs and the existing open-by-default behavior remain intact.
- **An older plan can be deleted for real, and the right rail stops spending
  space twice (JAG-514).**
  - **Plan deletion is a GRAPH operation, not a UI hide:** `taskgraph.drop_plan`
    removes every node of that plan, prunes the dependencies that pointed at them,
    persists the graph and publishes `graph.plan_dropped`, so the tasks panel AND
    the Control constellation lose the plan together (they read the same graph).
    The CURRENT plan is refused — the model may still be working on it — and each
    older plan row carries a ✕ with a confirm that states how many steps go.
  - **Workspace panel compacted**: the duplicated "Files · workspace" card is gone,
    `save` sits on the path row and `open editor` moved next to `browse`.
  - **Context ▸ auto-compact policy names the file in force as a link** that opens
    it in the editor (the WebUI overlay when it exists, the shipped file otherwise).
- **Tools are self-describing and discoverable instead of dumped in the prompt,
  and the Control/chat UI stops fighting the operator (JAG-513).**
  - **The system prompt no longer carries the tool registry.** It carried every
    subtool with its argument list, its approval policy and an 140-char synopsis —
    10 000 chars that went stale and still left the model guessing the arguments.
    It is now a 1 948-char **discovery contract** (args is always ONE JSON object;
    read the schema before the first call) plus the ENABLED names grouped by
    namespace, so nothing has to be invented. 80.5% smaller.
  - **`self {action:"tools"}` is the discovery surface**, in the same shape as
    skills: no args → the index with one-line descriptions; `query:"words"` →
    filtered; `tool:"fs.read"` → the FULL input schema (every property, its type,
    its default, the REQUIRED list, roots and one valid example call). An unknown
    name answers with suggestions, never with an empty result.
  - **Every tool and every argument now carries an authoritative description**
    (`v510` fails otherwise), and a canonical `<ns>.<subtool>` keeps the WHOLE
    usage text instead of its first sentence — the line-range contract of
    `fs.read`, "do not re-add an attached path" in `knowledge`, the review
    contract of `improve` were being cut away.
  - **A call missing a REQUIRED argument now TEACHES**: `shell.exec {}` answers
    `missing REQUIRED argument(s) 'command'` with the required list, the types and
    a ready-to-send example, instead of "empty command".
  - **Control ▸ AGENTS**: clicking another agent only SELECTS it — the
    constellation carries the same relative viewport over instead of re-fitting
    (a mode switch agent ⇄ all still re-fits); and the scope filter gained the
    **No team** bucket the AGENTS table already grouped, understood by both the
    client filter and `GET /api/constellation`.
  - **Chat**: the chain-of-thought is collapsed by default, LIVE included (it used
    to open itself, and was re-opened after every tool card), only the user opens
    one, and the chat sidebar has a dedicated 🧠 control that collapses them all.
  - **Composer**: `/` opens the command/skill menu ANYWHERE in the text, not only
    when the whole input is a lone `/`. The picker replaces just that token, so
    the rest of the message survives.
- **Every config knob is now an OBJECT in the WebUI, and the improvement backlog is
  reviewed by an LLM (JAG-491).**
  - **Structured settings** (`src/longrun/core/settings.py` + `GET|POST /api/settings`):
    one schema declares the fields of the files that had no bespoke panel —
    `index.yaml` (chunking, size caps, knowledge knobs, url cap, image caption
    model), `compaction.yaml` (summarizer input/output caps + instruction),
    `routing.yaml` (every role: model / pattern / fallbacks + global fallbacks),
    `decisions.yaml`, `hooks.yaml` (a repeatable row per hook) and
    `mcp_clients.yaml` (env files). Controls are checkbox / bounded number /
    select / text / textarea / line list / repeatable rows — never hand-typed YAML.
    Writes go to the owning overlay (`data/index.overlay.yaml`,
    `config/compaction.local.yaml`, `data/hooks.overlay.yaml`,
    `data/decisions.overlay.yaml`, `config/mcp_clients.local.json`), so shipped
    files and their documentation are never rewritten. Unknown paths and
    out-of-range values are rejected server-side. Keys owned by a dedicated panel
    (providers, embedding catalogue, subagents, tool policy) are listed in the UI
    and deliberately not duplicated; `v491` fails if any config leaf is covered
    by neither.
  - **Tools & approvals gained the missing controls**: sandbox `pids_limit` / `cpus`,
    global approval `outside_workspace` / `timeout_secs`, and a per-tool ⚙ editor
    for `roots`, `auto_approve`, `deny` and `allow_hosts` (validated lists).
  - **LLM backlog audit** (`improve.review`): every proposal + non-user distilled
    lesson is classified against the CURRENT code (evidence retrieved from the
    workspace index) as **keep / implemented / obsolete / update / conflict**, with
    a confidence, a one-line reason and — for `update` — the rewritten text.
    Nothing is applied automatically. Shared by two callers through one function:
    the **🧠 review with LLM** button in Settings ▸ Improvement (last report
    persisted under `data/improvement/reviews/`, shown with its evidence paths and
    an audit-ledger entry) and the base **`improve` tool** (`scope=review` or
    `action=review`, optional `limit`/`model`), so any session agent can audit its
    own backlog. The model comes from `routing.roles.reviewer`, then the general
    default.
  `tests/acceptance/v491_settings_forms.py` (23 checks) and `v492_improvement_review.py`
  (20 checks) pin both, deterministically.
- **External sources are now first-class in the knowledge base (JAG-490).** An audit against
  real documents (PDF, DOCX, XLSX, EPUB, images, URL-pointed PDFs/images, a 23 MB / 783-page book)
  found and fixed the whole ingestion path:
  - a URL to a **PDF or an image** was decoded as UTF-8 text (the KB indexed `%PDF-1.5…`); the
    new `chunk.fetch_url_info()` sniffs magic bytes + `Content-Type`, handles gzip/deflate/brotli,
    follows redirects, caps at `url_max_kb`, snapshots the binary under `data/knowledge/raw/`, and
    runs it through the normal extractor. Sources now record **`content_type`, `final_url` and
    `snapshot`**, so an online pointer is reproducible after the page changes;
  - a knowledge **folder applied the code** ignore list (`*.png`, `*.ipynb`, …) and its 512 KB cap;
    the KB now has its own `knowledge_ignore` / `knowledge_max_file_kb` and extracts documents up to
    `doc_max_kb`;
  - **XLSX** produced "no converter" (LibreOffice's generic text filter cannot write a spreadsheet);
    the office fallback now uses the Calc CSV filter in an isolated profile;
  - a **PDF with a broken font layer** was indexed as symbol soup (`quality 1.00`, `## a0 ✁ ✂ ☎`);
    `docio` now scores the extracted text (share of letters, script-agnostic), tries the fast
    `pdftotext` first for PDFs and goes straight to OCR when the layer is garbage;
  - an **image URL** indexed the docling placeholder `<!-- image -->`; placeholders are stripped and
    a thin-OCR image can be captioned by a real vision model (`image_caption_model`, opt-in, e.g.
    `openrouter:google/gemini-2.5-flash`) — the caption (visible text + description) is what gets
    indexed;
  - **hybrid retrieval returned nothing for a paraphrase** because it only re-ranked the bm25 hits;
    it now computes the query vector first, adds semantic-only hits (`vectors.semantic_hits`) and
    fuses with RRF (`mode: hybrid`);
  - **ingestion held the global lock** during fetch/extraction/embedding (one 783-page book froze
    every KB read and left its source row invisible); preparation moved outside the lock and the
    chunk transaction commits **before** embedding;
  - `fs.read` on a binary document now returns the **extracted** text instead of a UTF-8 decode;
  - the chat **“+”** auto-ingests images as well as documents into the session notebook, and
    **cloud vision detection** was broken: `model_supports_vision()` returned False for
    `openrouter:google/gemini-2.5-flash` even though that model describes images. It now reads the
    live OpenRouter `architecture.input_modalities` (cached, both vendor spellings) — verified live:
    an attached screenshot is transcribed and described correctly.
  `tests/acceptance/v490_kb_external_sources.py` pins all of it (27 checks, no network/model).
- **The whole `config/` store is editable from the WebUI (JAG-488).** A new **Settings ▸ Config files**
  panel lists every top-level `config/*.yaml`, loads the real file into an editor and saves it through
  `GET /api/config/files`, `GET/POST /api/config/file`. The server validates the YAML **before** the
  atomic write (a parse error or a non-mapping top level leaves the file untouched), keeps the previous
  version in `data/config-backups/`, refuses path traversal, and hot-reloads the owning module
  (`tools`, `routing`, `compaction`, `hooks`, `providers`, `mcp_clients`, `subagents`). `decisions.yaml`
  and `hooks.yaml` had no writer at all before this.
- **The sandbox block is editable too (JAG-488).** `POST /api/tools` now accepts
  `{"sandbox": {...}}` with validation (backend `auto|docker|bwrap|nsjail|none`, image, network,
  timeout, memory, pids, cpus, workspace inside the repo), invalidates the probe cache and re-probes.
  Settings ▸ Tools & approvals gained a Sandbox card showing the live probe and these fields; an
  explicitly requested but unavailable backend is reported in the payload instead of returning a 500.
- **Sandbox verified live, then restored (JAG-488).** On this DGX `docker` 29.6.2 works: with
  `sandbox.backend: auto` the probe chose docker and a real `shell` call ran as `uid=65534(nobody)`
  inside `alpine:latest` with only the workspace mounted at `/work`. `bwrap` is blocked by the kernel
  (`loopback: Failed RTM.NEWADDR: Operation not permitted`) and `nsjail` is not installed. The shipped
  value stays `none` on purpose (JAG-59: the DGX toolchain — JDK/Gradle/Android SDK — does not exist in
  a bare alpine image); the pill now says so and the panel shows why.
- **The three headline claims are pinned by a test (JAG-489).** `v489_description_claims` proves against
  the real modules that (1) the compaction policy drives the live trigger and the observation budget is
  bounded, (2) an oversized observation is offloaded verbatim to `data/offload/<session>/` while the
  model receives a head+tail reference, (3) the verification gate rolls a write back when the verify
  command fails and keeps it when green. It also locks the retraction of the discontinued SparkPulse
  client (the live GitHub description already reads "AI agent harness with bounded context, a
  verification gate, and tool-output offload"; no code claims the old client).

- **The auto-compaction policy is editable from the WebUI (JAG-487).** The Context panel now shows the
  live `trigger %` / `target %` / `keep` values with a save button; `GET/POST /api/compaction/policy`
  reads and validates them. Saves go to `config/compaction.local.yaml` (same overlay convention as
  `providers.local.yaml`), so the commented shipped file is never rewritten and the next turn picks
  the new values up with **no restart**. Defaults: **trigger 70% → target 30%, keep 4** — from
  `config/compaction.yaml`.
- **Fixed: the policy file was never read (JAG-487).** `compaction_config._PATH` walked up only three
  parents from `src/longrun/model/`, resolving to `src/config/compaction.yaml` (nonexistent); the
  loader silently served the hard-coded defaults, so every edit to `config/compaction.yaml` was dead
  while the old tests passed (defaults happened to equal the shipped values). It now anchors on the
  repo root `config/compaction.yaml`, verified by editing the file live (66% was picked up with no
  restart).
- **Fixed: a reasoning summarizer could silently degrade a compaction to the extractive path
  (JAG-487).** On a real 317-message session the chosen summarizer (`meta/muse-spark`) spent the whole
  `max_tokens` budget on its thoughts and returned a 0-character answer at 1500 and even 3000 tokens;
  4500 produced the summary. `_summarize_with_llm` now retries ONCE with a larger budget
  (`output_max_chars * 3 / 4`) when the answer is empty but thoughts were produced. The same
  compaction now reports `summary: llm` instead of `extractive`.
- **Verified live on `coder 1` (JAG-487).** 317 messages / 62.9% of 126,976 tokens → auto-compaction at
  the next turn: 317 → 5 messages, **63% → 8%**, 227 tool cards and 265 injects trimmed to 0 / 4,
  LLM summary in the `compacted history` group, all 19 task-graph nodes and the 37 thread-ledger
  groups preserved, every `after` anchor valid, and the turn completed normally.
- **After a compaction, everything on screen now belongs to a group (JAG-486).** The retained window starts
  with the compaction SUMMARY, not with a user turn, so the summary, the harness `final` injection, the
  retained answer and the tail `compact` marker used to render at the ROOT — "text outside a Free.X session"
  above `Free.1`. They are now wrapped in one collapsible **`compacted history`** group that the summary
  opens and the first retained user turn closes. It is deliberately NOT a `Free.N`: it has no ledger
  counterpart, so it consumes no ordinal (`Free.1`/`Free.2` keep their numbers) and is excluded from
  `applyThreadTitles` and the free-group rewind index. Verified live on the Master session: the log's only
  root children are `compacted history` (5 items), `Free.1` (12) and `Free.2` (3) — no floating text.
- **A compaction now trims the WHOLE transcript, not just `messages` (JAG-485).** The WebUI chat is the
  merge of `messages` + `tool_cards` + `injects`, and `compact_session` rewrote only the first one: after a
  manual/auto compaction a reload replayed every card and harness injection of the compacted-away turns, so
  the entire pre-compaction chat came back above the summary — and each card carrying a todo `node`
  re-opened that todo section (the same 4 todos painted 4 times). Compaction now drops the artifacts anchored
  in the summarized region, re-anchors the survivors onto their message in the new list, and also discards
  anchors that point past the transcript (a store left inconsistent by an older build). A one-off cleanup
  (with a backup) repaired the already-compacted live session.
- **`loadHistory` can no longer paint the transcript twice (JAG-485).** On a normal boot two loads ran
  concurrently — the init call plus the `chat.done` feed-backlog replay — each replaying the whole transcript
  into the same `#log`. A generation guard makes the newest load the only winner; every older in-flight call
  bails after its next await, and the winner starts from an empty log. Verified live: the boot still issues
  2 `/api/history` requests, but the DOM contains exactly one section per todo (0 duplicated sections).
- **A replayed compaction summary is labelled `compacted history`, not `compact`, and shows no timestamp
  (JAG-485).** It is the HEAD of the retained window (for the model), not a live harness injection; the
  missing timestamp used to fall back to "now", stamping an October summary with the page-load time. The
  visible compaction event remains the `compact` marker at the TAIL (JAG-451). Verified live on the UX
  Architect session: `compacted history` → nudge → answer → `compact 15:11:16`, with no fabricated time on
  the summary and no todo section left on screen.
- **A subjob row no longer re-implements the ORG chart's click (JAG-484).** In the Control deck's JOB panel,
  single-clicking a subjob row (`J8.1 → A14`) opened that agent's chat — the *same* action the ORG chart
  already performs. The row is now inert (its only job is to stop the click from collapsing the job) and
  every subjob carries its own explicit `↗ session` button on the right, which reuses the deck's shared
  `onOpenAgent` callback (`tac.gotoAgent` → `_deckGo(session)`) so exactly ONE open-session path remains.
  Verified live on `/orbit` (job J16): the row emits no `data-agent`, the button is `btn mini ghost`, and
  clicking it navigated the tab to `/?token=…&session=<sid>` — the Sessions app on that agent's session.
- **De-duplication pass, phase 2: the INDEX and SSE machines now have ONE implementation too (JAG-483).**
  The per-workspace codebase index and the global knowledge base run the same machinery over two different
  schemas, and that machinery lived twice. Consolidated: FTS5 detection (`sqlkit.has_fts`), the lexical query
  splitter + `MATCH` expression (`sqlkit.terms` / `sqlkit.fts_match`), the chunk + FTS-shadow insert loop
  (`sqlkit.insert_chunks`, `source=None` for the codebase index), the drop-and-rebuild used by `clear()`
  (`sqlkit.reset_tables`), and the whole hybrid retrieval tail — the flat query vector
  (`vectors.query_vector`, which also removes the accidental `qv[0]` the codebase index relied on), the
  candidate-vector fetch (`vectors.vecs_for`) and the Reciprocal Rank Fusion (`vectors.fuse_rrf`). The two
  SSE loopback tails (`/api/feed` and the blackboard watcher) now share one skeleton, `core.sse.sse_tail`;
  only the backlog source, the registration set and the open comment stay per-caller. `_embed_texts_query`
  and the private aliases stay as thin wrappers. Verified: FULL battery 199/199 GREEN plus 18 deterministic
  live checks on both stores (hybrid RRF in both, insert/FTS counts, `clear()` rebuilds) and 12 on the SSE
  tails (backlog frame, forwarded item, idle ping, queue release) — no residual queues or watchers.
- **De-duplication pass: every mechanical helper now has ONE implementation (JAG-483).** A codebase-wide
  scan (AST function clustering for Python, block windows for JS) found the same small primitives
  re-implemented and quietly drifted: the `int` coercion (5 copies, two different failure defaults), the
  YAML-or-JSON document loader (5 copies, three different fallbacks), the request-body unwrap (2
  byte-identical copies), the registry reader (4 copies), the sqlite opener (2 copies), the agent-file
  frontmatter parser (2 copies) and the "defaults ← tools.yaml ← override" config merge (5 copies). Each
  copy now delegates to a single source: new `util/dataio.py` (`as_int`, `load_yaml`, `dump_yaml`,
  `read_yaml`, `json_body`), new `memory/sqlkit.py` (`connect`), `util/fswrite.read_registry`,
  `tools/registry.section_config` and `agent/agency.frontmatter`. Behaviour is unchanged, and the `v231`
  guards that pin `api_v02._int` / `providers._to_int` / `server._as_int` still pass because those names
  remain as thin aliases. Verified live that TEAM bulk reset/compact touches ONLY its member sessions — a
  362-message session outside the team came back byte-identical.
- **Repo tagline rewritten; the discontinued SparkPulse client dropped.**
  The repo description still claimed the harness "Powers the SparkPulse Android client" — that client no
  longer exists (its GitHub repo 404s), so the claim was removed and the dead homepage link cleared. The
  text now reads: *"AI agent harness with bounded context, a verification gate, and tool-output offload.
  Runs a team of meta-agents as an org chart — every session is an agent."* The two in-repo docstrings that
  still named the client (`plan/taskgraph.py`, `tools/registry.py`) now simply say "the WebUI".

### Added
- **TEAM bulk actions: reset-all / compact-all from a 3-dot menu on the team header (JAG-482), battery 199/199.**
  The AGENTS table groups the roster under one collapsible header per TEAM, but a team-wide action had to be
  clicked agent by agent. The header now carries a kebab — rendered ONLY for a real team (the "No team" bucket
  and unknown/stray group ids have no team to act on) — offering two actions over EVERY member session:
  **reset all sessions** (the same semantics as the row's ↺ reset, i.e. `stores.clear_session`: transcript,
  tool cards, harness injects and task graph wiped — the sessions, their agents and their ROLE.md are NOT
  deleted) and **compact all sessions** (the MANUAL compaction policy of "compact now", one call per session).
  Both go through ONE new route — `POST /api/teams/<tid>/reset` and `POST /api/teams/<tid>/compact` — instead of
  a browser-side loop, and report per session (`input_tokens → tokens_after`). One failing session never aborts
  the batch (it is reported in `results`), an unknown team is a 404, and an empty team is a clean 0-session
  no-op. The deck's floating menu is now ONE shared `.ctxmenu` primitive: the agent→teams picker, the team
  bulk menu and the constellation node menu used to carry three copies of the same build/clamp/dismiss
  plumbing (and only one may be open at a time — now guaranteed, not maintained by hand). Pinned by new
  `v482` (23 checks).
- **The chat names itself: a small header bar with the ACTIVE session's name (JAG-480), battery 198/198.**
  Hiding the left panel (or collapsing a session's team group) used to hide *which* session you were
  reading, so finding it again meant remembering its name. The chat now carries its own compact top bar
  with the session title and id, both selectable and one-click copyable (`⧉ copy name`, which uses the
  existing secure-context-aware `copyText`). The title comes from the REAL `/api/sessions` payload
  (`_sessTitle`), so it can be pasted straight into the rail's search box. Refreshed on every sessions
  load and hidden when no session is open. Pinned by new `v473`.
- **Every agent run now shows as RUNNING, and the Sessions rail counts them (JAG-479), battery 197/197.**
  Two defects behind one report: "the running symbol never appears on a chat" and "I cannot see how
  many agents are running". (1) **A run that OWNS a session never registered a turn.** The chat and the
  in-process MCP chat bracket their turn with `turn_begin`/`turn_end`, but `agent_stream_gen_v2` — the
  path a Paperclip task or job takes, the one that auto-creates and owns the visible session (JAG-476) —
  did not. So `_ACTIVE_CHAT` never held that session: `list_sessions` reported `running: false`, the rail
  spinner never rendered, and no `chat.done` was published — no finished-bell either. The worker now
  brackets the run (`turn_begin` before the SSE `run` frame; `turn_end` in its `finally`, AFTER the reply
  is persisted, so a browser reacting to `chat.done` already finds the answer on disk). (2) **A counted,
  navigable surface.** The Sessions header gains a runs BAR (`N running · 🔔 M finished`) that opens a
  separate popover panel (`role="dialog"`, Escape / outside-click to close) listing **running agents**
  and **finished-but-unread** sessions, one real hyperlink per row that jumps straight to that chat and
  clears its bell. Running comes from the server flag / `chat.run`; unread is client-side truth
  (`chat.done` on a session this browser was not showing) persisted in `localStorage["sf_unread"]` and
  pruned of deleted ids on every `loadSessions`. The rail spinner, the bell and the panel's dot now all
  respect `prefers-reduced-motion`. Pinned by new `v472` (28 checks).
- **The 🏷 button names EVERY untitled Free.* group in one shot — it is now an LLM subroutine,
  not an agent turn (JAG-473).** The old button only PROMPTED the agent ("use `chapters`
  action=untitled …"), and that turn always stopped after one page: the tool shows ≤8 ids and a
  chat turn may spend only `CHAT_TOOL_MAX_STEPS` (8) real tool calls before the keepgoing loop
  stops — renaming creates no todo, so `keepgoing.decide` sees zero open nodes and returns
  `goal_reached`. Naming is bookkeeping, so it no longer rides the work budget:
  `POST /api/sessions/<id>/chapters/autoname` runs `httpapi.autoname_untitled` — one direct call
  to the SESSION's own chat model that returns a title+summary for all untitled groups at once,
  applied server-side and repeated until none remain (no page cap, no per-call tool budget), with
  the JAG-451 deterministic naming as a fallback whenever the model is unavailable. Pinned by new
  `v469`.
- **A Paperclip external adapter: one assigned task becomes exactly one bounded Longrun run.**
  Paperclip-managed companies can now dispatch work to Longrun without patching Paperclip core: the
  external adapter package in `integrations/paperclip/` is loaded through Paperclip's `localPath`
  plugin seam and spawns the Longrun CLI shim as `python forge.py paperclip-bot`. One task = one run:
  the shim reads one `longrun.paperclip.invocation.v1` envelope on stdin, calls
  `POST /api/agent/run/stream`, and writes `longrun.paperclip.event.v1` NDJSON frames on stdout. A
  five-event allowlist reaches Paperclip — `longrun.run.started`, `longrun.run.progress`,
  `longrun.run.completed`, `longrun.run.failed`, `longrun.run.cancelled` — while reasoning
  (`agent.think`), raw observations, tool arguments and credentials are never forwarded. Completion is
  fail-closed: success requires BOTH the streamed terminal classification and the fetched run record to
  say `completed`, a terminal frame is held back until the child's exit status confirms it, and every
  failure path reports a non-zero exit code so a clean child exit can never be read as success. The
  run record gains an additive machine-readable `termination` (`completed` / `max_steps` /
  `no_progress` / `aborted` / `error`) so `status: done` is no longer mistaken for completion.
  Cancellation aborts the known run id and exits `130`; an ambiguous disconnect is `indeterminate` and
  never starts a second run. `LONGRUN_TOKEN` travels only in the `Authorization` header and is absent
  from the settings schema. Deterministic and offline:

  ```bash
  cd integrations/paperclip && npm install && npm test && npm run typecheck
  ```
  Pinned by new `v464`–`v468`.
- **A harness-vs-harness bench: same weights, same tasks, with and without the harness (JAG-454), battery 180/180.**
  The question "how much is the harness worth?" needs a CONTROL, so `benchmarks/` now runs N arms over one task
  file with the model held fixed and emits a side-by-side artifact. Arms: `bare` (the model API with no tools, no
  system prompt, no memory — the baseline a harness must beat), `longrun` (this harness over its public REST API
  only), `hermes` (a second harness via `cli.py -Q`). `compare.py` supports `--tags`/`--model-map`, `--keep-sessions`
  (the operator wants to open the run in the WebUI and read what the harness actually did), `--jobs` for parallel
  tasks, and `run_suite()` brackets every suite with `setup()`/`teardown()` so a headless run is not measured with
  its hands tied (approval gate lifted, then restored). `humaneval.extract_code()` is applied by the SCORER so a
  chatty arm is not penalised against a terse one. Pinned by new `v454`. **Scoring follows the OFFICIAL contract**: `check()` evaluates
  `prompt + completion + test` — scoring the completion alone failed a correct answer with `NameError: name 'List' is not defined` (the prompt
  carries the typing/import preamble), a scorer artefact that cost BOTH arms ~15 points. Pilot result after the fix (`bare` vs `longrun`,
  `deepseek-reasoner`, HumanEval n20, equal conditions, no local GPU): **1.00 (20/20) vs 1.00 (20/20)** — the task set is SATURATED and cannot
  discriminate between harnesses, which is exactly why the official, much harder Claw-SWE-Bench / SWE-bench Pro suite is the next step.
- **Stop really stops, and a compaction no longer doubles the chat (JAG-431q), battery 166/166.**
  Two WebUI/server defects found by driving the live app (browser + HTTP) end to end. (1) **Stop did
  nothing.** `chat_once` cleared the abort flag AFTER the planner/graph model calls had already run, so a
  Stop pressed during that window (the UI shows the turn as running from the first moment) was silently
  wiped: measured live, abort at t=8s and the turn still finished at t=87s with the full answer. The clear
  now happens at TURN START (stream + sync + in-process MCP paths, before any model work), `chat_once` no
  longer touches it, and the sync planner call is abortable (`cancel=`). Verified live: abort at t=8s → the
  turn ends at 14.3s with `⏹ Interrupted by the user.`. Stop is also a PANIC button now: it aborts EVERY
  running turn (`/api/chat/abort {all:true}` fans out over the ACTIVE-turn registry) — aborting only the
  on-screen session left parallel agents decoding and the single-slot local router busy, so "stop" looked
  like a no-op. (2) **A compaction duplicated the whole chat.** `loadHistory()` APPENDS to `#log` (it is the
  CALLER's job to clear), and the `context.compact` / `context.auto_compact` / `chat.done` handlers never
  cleared it — measured live in the browser: a compact turned 3 messages into 6 (1 free group into 2). All
  three handlers now clear first; re-measured 3 → 3. Pinned by new `v442` (12/12) and `v438` §10j/§10k.
- **Free-group titles now ride the transcript, so the 🏷 button labels every `Free.N` — even after compaction (JAG-431p), battery 164/164.**
  The 🏷 button titled only *some* free groups in the chat: the WebUI labelled `Free.N` by its **ordinal** in a
  list it computed itself, while the agent titled groups by the **ledger's** ids — and the two lists were built by
  different rules (a task item closed the rendered free group; the ledger opened a new one), so the counts drifted
  and the extra on-screen groups stayed untitled (reproduced: session `55a29fae70cb`, ledger 10 free groups vs 8
  rendered). Two fixes: (1) a TASK item now CLOSES the current free group in `_openSection`, making the rendered
  sequence match the ledger's **exactly** (verified for all 6 real sessions); (2) `threads.sync_chapters`, called
  from the `save_session` choke point, mirrors each titled group's `title`/`summary`/`req_from` onto the **message
  that starts** the group (`messages[i].chapter`) — the WebUI labels the group from that chapter, so the label
  travels with the transcript and **survives compaction** (retained messages are kept verbatim) instead of
  depending on an ordinal. A stale `req_from` (post-compaction) is verified against the group's request and never
  labels an unrelated message. The free group's **summary** is now shown on its header line (muted, ellipsized,
  full text in the tooltip), and the ⏮ rewind uses the chapter's anchor. Pinned by `v438` (46/46).
- **`chapters` now carries every group's JUSTIFICATION; free groups get a summary (JAG-431o), battery 164/164.**
  Recalling a thread without its *why* is useless in a long run, so the tool now surfaces metadata that was
  already saved but invisible to the agent: a TODO's `evidence` (the text the model writes when it closes the
  step — durable in `data/graphs/<sid>.json`, never touched by compaction) and a FREE group's new `summary`.
  `list` prints `#2 task n1 [done] label · why: "<evidence>"` for tasks and `· title=… · summary=…` for free
  groups; `read id=<gN>` returns the full record (all evidence entries / title+summary+request+content);
  `title id=<gN> title=… summary=…` stores a free group's name AND its one-line justification in the
  compaction-proof ledger (the free-group equivalent of a todo's evidence). A schema rebuild now PRESERVES
  agent-set titles/summaries (`_carry_meta`), so a version upgrade can never silently drop them. The 🏷 prompt
  asks for both. Pinned by `v438` (35/35).
- **Free threads get rewind + "request to …" titles; full-width chat (JAG-431l/m), battery 164/164.** (m) A free
  thread is a user **request** plus its answer, so it now behaves like a todo in the rewind feature: the ledger
  records the request text and its message index (`req` / `req_from`), and each `Free.N` group carries a **⏮**
  control (a sibling of its `<summary>`, same a11y pattern as the todo rewind) that rewinds to just before that
  request via the existing per-turn rewind API. The `chapters` tool and the 🏷 prompt now instruct the agent to
  name a free group `"request to <short summary of the user's ask>"`; `chapters read` surfaces the request line.
  (l) The chat answers were capped at `max-width: 860px` while the tool cards spanned the column — the per-message
  cap is removed so a message uses the full width of `#log`. Pinned by `v438` (28/28) and `v440` (3/3).
- **Session thread ledger + `chapters` tool — recall a long run across compactions (JAG-431j), battery 163/163.**
  A session's chat is a stream of groups: TASK groups (todo nodes) and FREE groups (`Free.N`, chat with no todo).
  Compaction rewrites the stored transcript in place, so the agent could no longer read an old free thread — even
  though the operator still sees it in the WebUI. New `src/longrun/memory/threads.py` keeps a durable per-session
  ledger (`data/threads/<sid>.json`), written by `stores` **before** compaction can touch the transcript, with a
  bounded digest per group. A new base tool **`chapters`** (agent-callable, `approval: auto`) exposes it:
  `action=list` → the whole thread in chronological order (task + free, ids + ranges + previews); `action=read
  id=<gN>` → a group's preserved content; `action=title id=<gN> title="…"` → name a **free** group (todos already
  carry their node label). `GET /api/threads?session=` serves the ledger to the WebUI, which shows `Free.N · <title>`
  (backfills once for sessions that predate the ledger). A new **🏷** button in the floating chat cluster asks the
  agent — a real turn, like any tool call — to title every `Free.*` group from its content. Ledger lifecycle follows
  the transcript (`/clear` wipes it, rewind truncates it, session-delete purges it). Pinned by `v438` (21/21).
- **RH Plan panel: stack the todo meta on a long wrapped label (JAG-431k), battery 163/163.** A todo row was one
  flat flex line (`[status] [id] [JN] [JN.x] [label …]`); when the label wrapped beyond 3 lines the inline meta
  only stole width and inflated the row height. The row is now split into `.tmeta` + `.tmain`, and a JS pass
  (`_markWrappedTasks`, measuring the label's line boxes via `getClientRects()`) flags such a row with `.w3`, which
  stacks the meta **under the status badge** so the label reclaims the full width (far less vertical space). Re-marks
  on re-render, on panel-width change and when the tasks tab opens. Pinned by `v439` (14/14).
- **Control deck mobile — follow-up: pan-not-zoom + no panel squash (JAG-431i), battery 161/161.** Two
  regressions the phone user hit. (1) **A one-finger drag on the org chart ZOOMED instead of panning:**
  the first cut used a hand-rolled pointer-Id `Map`, which can go **stale** — a missed `pointerup`/
  `pointercancel` leaves a phantom second pointer, so every move is mis-read as a **pinch**. Touch now uses
  **touch events** (`ev.touches` is the browser's authoritative, never-stale live list): 1 touch = pan,
  2 touches = pinch; mouse keeps `mousedown/move/up`. A tap on a node still selects it (both paths bail on
  `.node`). (2) **The Agents panel was squashed and could not be un-squashed:** once the rows STACK (≤1100px)
  the row-height grips sit on the border between two stacked panels and dragging one only compresses them
  (a stored desktop row height did the same). The grips are now hidden below the stacking breakpoint and any
  stored row height ignored (`.grid2{height:auto !important}`), so every panel keeps its natural height.
  Pinned by `v437` (16/16).
- **Control deck on a phone: tidy layout + finger gestures (JAG-431i), battery 161/161.** The Control deck
  (`orbit.html`) was desktop-only in two ways. (1) **Layout:** at ≤640px a new media query restyles the
  toolbars — the `scope`/`sort` labels drop, each `<select>` fills its own row, and the action buttons wrap
  into tidy **≥36px finger-sized** rows instead of a jumble of oversized pills; the panel headers let their
  tools wrap neatly. Desktop is untouched. (2) **Gestures:** the org chart and the constellation panned by
  `mousedown/mousemove` only, so a finger could not drag them; both now use **pointer events (mouse *and*
  touch)** with **pinch-to-zoom**, and `touch-action:none` keeps a drag panning the chart instead of
  scrolling the page. Wheel zoom (desktop) is kept. Pinned by `v437`.
- **Mobile theme fix + Plan goal box (JAG-431h), battery 160/160.** Two phone-reported WebUI fixes.
  (1) **The mobile drawers now follow the theme:** the sessions drawer (`#aside`) and the bottom tab bar
  (`#tabbar`) hardcoded a dark `rgba(…)` background, so switching to the light **Sand** theme left them
  dark; they now use the `--aside` / `--menubg` tokens. (2) **The Plan goal box is full-width on its own
  row**, below the ▶ goal / clear / reset buttons, so it no longer shares a sliver of the panel with three
  buttons. Pinned by `v436`.
- **Free-thread groups + rewind-dialog fixes + no repo venv (JAG-431f/g), battery 159/159.** (g) **Collapsible
  FREE chat threads:** loose chat turns that sit between task groups now collect into **`Free.N`** collapsible
  groups, toggled by the SAME ⊞/⊟ floating controls as the task groups (`_allGroups` covers `details.tctree`
  *and* `details.fgroup`). Verified live: 3 `Free.N` groups (9/12/4 kids) + 5 tctree collapse/expand cleanly,
  0 console errors. (f) **Rewind dialog fixes:** the "delete?" **confirm popup now sits ABOVE** the rewind
  dialog (overlay z-index 30 → 100); and **turn anchors are bounded per session** — `checkpoints.create_turn`
  prunes the oldest turn anchors via `prune_turns` (`LONGRUN_TURN_ANCHORS`, default 30), so a long session
  keeps only the most recent ~30 (the sparse msg 0/14/22/38 list is one anchor per USER turn). Plus the
  **repo `.venv` is gone for good** — the app is explicitly non-venv (system interpreter + `pip install
  --user`), dev tooling lives in a throwaway `$TMPDIR` venv. Pinned by `v435` (and `v433`/`v429` re-pointed).
- **Rewind to a specific todo + non-venv interpreter model (JAG-431d/e), battery 158/158.** (d)
  **Per-todo rewind:** each todo row now carries a **⏮** button (chat tree + Plan panel) that restores
  to *just before that step* — `POST /api/rewind {session, node}` prunes the task graph AT the node (it
  and every later one vanish), rolls the transcript back to the nearest turn anchor, and reverts the
  harness's later file writes. Legacy anchors (created before the graph was snapshotted) fall back to a
  timestamp prune so old sessions work too. Verified live: session `55a29fae70cb` `[n1..n6]` → ⏮ on `n6`
  → `[n1..n5]` (RH panel + chat agree). Pinned by `v433` (and `v431` extended with the legacy path).
  (e) **Interpreter model made explicit:** the app runs on the **system** interpreter (stdlib + PyYAML) —
  `requirements.txt` = runtime extras, installed for *that* interpreter; the repo `.venv/` is
  **dev-only** (rebuilt from the new `requirements-dev.txt`, used by `tests/mega_test.sh`). Documented in
  the README. Pinned by `v434`.
- **Rewind restores the REAL todo list + WebUI fidelity sweep (JAG-431), battery 156/156.** Two fixes
  under one rule — *a UI must mirror the real backend state, never a stub or a disconnected copy*. (1)
  **Rewind truly deletes the todos:** the live todo list is the per-**session** task graph
  (`longrun.plan.taskgraph` → `data/graphs/<sid>.json`), but a checkpoint snapshotted only the legacy
  `plan.json`/`tasks.json` the panel no longer reads, so a rewind left the todos on screen ("graphical
  delete only"). `checkpoints.create` now carries `graph` and `rollback` restores it (archiving it when
  the graph did not yet exist at the anchor), and `POST /api/rewind` reports it. Verified live: a session
  with 4 nodes → rewind → **0 nodes**. (2) **WebUI fidelity sweep** (from a full audit of `index.html` +
  `console.html`): `index.html`'s todo panel now has ONE source — the per-session graph — instead of the
  dual `loadPlan()`//`loadGraph()` paths whose `localStorage("sf_run")` mirror could resurrect stale todos
  (JAG-257); `console.html` no longer **fabricates a whole demo deck on any backend hiccup** (demo is now
  opt-in via `?demo=1`, a real failure shows an explicit empty *offline* state), its task graph reads the
  real per-session graph instead of the legacy `/api/plan` board, its TASKS chip no longer falls back to
  the phantom `tasks.json` counts, and its models grid reads `/api/models`. Pinned by `v431`/`v432`.
- **Optimal RAG ingestion — docling backend + image support (JAG-430), battery 154/154.** The knowledge
  base can now ingest **everything**: `docio` gains **docling** (IBM, MIT) as its top backend — a
  pure-Python package (`pip install docling`, now pinned in `requirements.txt`) that extracts
  layout-aware Markdown with real **TABLE structure** (TableFormer) for PDF/DOCX/PPTX/XLSX/HTML/EPUB and,
  newly, **native images** (PNG/JPEG/TIFF/BMP/WEBP) via OCR/vision. `BINARY_DOC_EXT` now includes the
  image extensions; `available()` reports the backend; the previous stack (markitdown → pdftotext/OCR →
  libreoffice) remains the graceful fallback when docling is absent. Verified live on the DGX: the
  Machiavelli PDF → 178 930 chars of Markdown via `docling`, and a generated PNG was transcribed by
  docling OCR on the GPU. Pinned by `v430`.
- **New-session dialog + workspace auto-creation + CoT collapse (JAG-429), battery 153/153.** Three
  WebUI fixes. (1) The **New-session dialog is now opaque** (it inherited the translucent `.card`
  background and let the transcript bleed through). (2) Naming a **not-yet-existing workspace** used to
  be refused with "no such folder"; `rules.ensure_dir` now **creates it** (`mkdir -p`, parents included)
  and `/api/sessions/new` falls back to it, erroring only if creation truly fails. (3) The **🎯 reveal
  control moved out of the topbar into the floating chat cluster** (`#treeTools`, beside the todo
  ⊞/⊟), and **⊟ collapse-all now also tucks away the chain-of-thought** blocks — deliberately ONE-WAY,
  so ⊞ re-opens the todo groups but never re-opens the CoT the user chose to hide. Pinned by `v429`
  (and `v428` was re-pointed to the new control location).
- **Reveal the active session in the rail (JAG-428), battery 152/152.** While talking in a chat you could
  collapse the active session's team group (or the whole panel) with no quick way back. A topbar **🎯**
  control (`revealActiveSession`, shown only with an open session) opens the sessions panel, expands every
  group that holds the active session (reusing the `_forceExpandActive` path), clears a search filter that
  would hide it, scrolls its row to the CENTER and flashes it. Clicking the collapsed-panel session badge
  (topbar) performs the same gesture. Pinned by `v428`.
- **Harness audit + six upgrades (JAG-426).** A six-domain "harness maxing" pass, shipped in three
  waves and pinned by `v414`-`v421` (battery 137 → 145). (1) **Native self-diagnosis** —
  `tools/diag.py` (`health`/`log_tail`/`context`/`tools_report`) exposed through the `self` tool
  (`action: info|diagnose|logs|context|tools`); every probe degrades gracefully and none depends on
  PMC. (2) **Per-turn checkpoint & rewind** — `memory/rewind.py` anchors a rewind point on every user
  turn (both chat paths) and `POST /api/rewind` restores the plan, task list, transcript, workspace
  files **and** truncates the event log to that turn; `POST /api/checkpoints[/restore]` +
  `GET /api/checkpoints` expose the restore points. (3) **Benchmark adapter + runners** —
  `benchmarks/` ships a harness-agnostic `HarnessAdapter` protocol (Claw-SWE-Bench style), a
  REST-only Longrun adapter, a generic `runner.py` (emits `predictions.jsonl` + `summary.json` with
  provenance) and a HumanEval runner that uses each task's OWN functional test (scoring is never
  re-implemented). (4) **Autonomous skills confined** — self-evolve now defaults to
  `skills/created/` with a core-immutable guard and a creation cap, tagging provenance `origin:auto`.
  (5) **Baseline toolset** — native `python`, `process` (`list`) and `glob` tools. (6) **Local
  decision layer** — `model/decision.py` (Protocol + null/heuristic models, fail-open) with
  `config/decisions.yaml` (disabled by default) and hooks for speculative reads and route hints.
- **WebUI rewind surface (JAG-426 follow-up), battery 149/149.** The session rail's ⋮ menu now offers
  **⏪ Rewind…**, opening a dialog that lists the session's turn anchors (`GET /api/checkpoints?session=`
  → `marks`) newest-first; picking one confirms and calls `POST /api/rewind`, then reloads the
  transcript/plan. `openRewindDlg`/`closeRewindDlg`/`doRewind` + the `#rwDlg` markup/CSS are wired
  through the `data-call` dispatcher and pinned by `v425`. Verified live end to end: the dialog listed
  three anchors, a rewind reported "1 file(s) reverted · 61 event(s) dropped", and the harness journal
  (only the files the harness itself wrote) was honoured.
- **WebUI composer + chat-todo controls (JAG-427), battery 150/150.** (1) The composer toolbar is now
  **always a single row**: the model picker is the only flexible control and shrinks toward its caret
  (min-width 34px) before anything can wrap, so the chat column can no longer grow a broken
  "multi-floor" button stack when it gets narrow. (2) The chat now has **expand-all / collapse-all**
  controls (⊞ / ⊟) for its todo groups (`<details.tctree>`), mirroring the sessions rail's ▲/▼ —
  floating at the chat's bottom-right so they cost zero horizontal space and stay visible even with the
  editor dock open. Pinned by `v426` (and the older `v282`/`v284` composer checks were re-pointed to the
  new one-row contract).
- **Vision input — image attachments now reach the model (JAG-417).** An image attached in the
  composer is sent to vision-capable LLMs as an OpenAI `image_url` content block (base64 data URL),
  not just a text note, so the model actually sees the image. `config/providers.yaml` flags the DGX
  vision models; `rllm.model_supports_vision()` checks the flag then the router's live
  `input_modalities`; `agent.assemble_turn` upgrades ONLY the current user turn (8 MB cap, safe
  degrade to text). Verified end to end: the model describes real screenshots. Text-only models keep
  the previous behavior.
- **Control deck — team management + org-chart fit/zoom (JAG-418).** In the Control tab the AGENTS
  pane can now create teams, assign each agent to one or more teams (a Teams column), and list
  agents grouped by team (a `table` / `by team` toggle). The org chart auto-fits and centers the
  whole tree by default with `−`/`＋` buttons and wheel-zoom + drag-pan.
- **Multi-embedding model catalogue + COST tracking (JAG-403a).** The user can now
  pick from 18 known embedding models (OpenAI `text-embedding-3-small/large`, Voyage
  `voyage-3-large`, Cohere `embed-english-v3.0`, Jina `jina-embeddings-v3`, OpenRouter
  pass-throughs and local BGE/E5/Nomic) — the catalogue lives in the PERSONAL config file
  `config/embedding.yaml` (not hardcoded in Python) and personal additions/removals persist
  in the overlay. Embedding costs are recorded per batch in `data/codebase/costs.db` with the
  EXACT USD reported by OpenRouter (`usage.cost`) and a best-effort estimate for every other
  provider. The **Settings ▸ Models** section shows the active model, lets the user test the
  endpoint, add/remove models, view total + per-model + per-day costs, and export CSV. CLI:
  `forge embedding models|active|set|add|remove|costs|cost-test`. API: `GET/POST
  /api/embedding/models`, `GET/POST /api/embedding/active`, `GET /api/embedding/costs`,
  `GET /api/embedding/costs.csv`. v401 26/26; battery 127 → 128.
- **Research agent (JAG-403b) — discover + iterative summarisation + import.** The user can
  launch a *deep research* run from the chat Settings (Knowledge ▸ Research · agent) or
  from the CLI (`forge knowledge research <q> --notebook --depth --max-rounds`). The
  research LLM is configurable separately from the chat LLM: catalogue ships Perplexity
  Sonar Pro/Sonar (web-grounded, recommended), OpenRouter `gpt-4o-mini-search-preview` /
  `perplexity/sonar-pro`, and the local rllm router (`local:default`). Depth controls
  rounds + sources per round (shallow=1×5, medium=2×5, deep=3×6, capped at max_rounds).
  Each round: web search → fetch top URLs → ingest as notebook sources (deduped,
  budgeted) → final LLM summary stored as a text source alongside the URLs. New
  `/api/knowledge/research` (POST) and `/api/research/model` (GET/POST); v402 25/25;
  battery 128 → 129.

### Fixed
- **First-run authentication no longer requires hand-editing `.env` (JAG-493).**
  An unconfigured local server opens a blocking WebUI setup panel; saving there
  persists and activates `LONGRUN_TOKEN`, while remote clients cannot claim setup.
  Settings → Keys can rotate the live token without a restart, and the browser-only
  credential field is now labelled as such.
- **A token placed in `.env` now actually gates the API, and the README is a
  copy-paste first run (JAG-492).** `main()` ran `argparse` before
  `providers.load_env()`, so `LONGRUN_TOKEN` in the gitignored `.env` was ignored
  (only `--token` worked) while `.env.template` promised otherwise. The server now
  loads the env files first and defaults `--token` to `$LONGRUN_TOKEN` (the flag
  still wins); `LONGRUN_ENV_FILE` — documented in `config/providers.yaml` — is
  honoured too. `deploy/longrun.service` no longer interpolates the token into
  `ExecStart`, so a missing env file means "no auth" instead of an argparse crash
  loop. `.env.template` lists every optional key; the README gained a Quick start,
  a `.env` variable table, an `/api/status` check, first-run troubleshooting and a
  **single canonical URL** (Sessions and Control are tabs of one page — the detached
  `/orbit` entry point is no longer advertised). Stale claims were corrected: the
  70% compaction trigger, the `no sandbox` topbar label, the ACP route
  (`POST /api/acp`), the Workspace panel for the default folder, and the removed CI
  workflow/badge.
- **A run and its session could display DIFFERENT models — the WebUI lied (JAG-478).** Two
  independent resolutions of "which model?" had drifted: an interactive chat honours the session's
  own model (`resolve_ctx_model`), but `POST /api/agent/run/stream` forwarded the raw body model
  (`null` for Paperclip) straight into `agent_run_v2`, which then resolved the ROLE hint
  (`pick("agent")` = the local weights) — the session was read for its WORKSPACE only. The session
  JAG-476 auto-creates recorded no model either, so the composer fell back to the global
  `localStorage.sf_model`: it could show `deepseek:deepseek-reasoner` while `qwen…` really ran. One
  resolver now decides — `agent_model_for(goal, explicit, session)` (explicit → session's own →
  role hint, the SAME precedence as chat), used by the run loop AND the route, which records the
  resolved ref on the session it runs in. A session pinned to X runs on X; whatever runs is
  displayed. Pinned by `v471` (11/11), `v455` B7 restated against the shared resolver.
- **A transient model-endpoint failure killed a run on the first hit (JAG-477).** The DGX router
  runs `--models-max 1 --parallel 1`, so a tool that itself curls the model endpoint (a smoke test
  hitting `:8080`) forces a model swap and the NEXT harness call can answer `500` — the observed
  `run failed: HTTP Error 500` in a Paperclip task. A 5xx / timeout / dropped connection is now
  retried ONCE (after a 2s pause) before failing, and the retry is visible as a `model.retry`
  event; a 4xx is a contract error and still fails fast. Pinned by `v470` (3/3).
- **A headless run was invisible in the WebUI — no session was ever created (JAG-476).**
  `POST /api/agent/run/stream` (the route the Paperclip bridge calls) started an agent run
  with its own task graph and feed events but never a chat session, so a task dispatched from
  Paperclip ran with nothing to watch in the sessions list. When the caller supplies no
  `session`, the route now creates one titled from the task's first line, persists the goal as
  its user turn and the run outcome as the reply, and publishes `session.created`. A
  caller-supplied session keeps its old meaning (workspace context only). Verified live: goal
  `Reply with the single word: pong` → session `80befbeb2b06` with `user`/`assistant` turns.
  Pinned by `v465` (4/4).
- **The Paperclip adapter rejected every real assignment as "no title or description"
  (JAG-475).** The installed Paperclip (`2026.928.0-canary.7`) delivers a fresh assignment in
  `ctx.executionContinuation.objective` and leaves `ctx.context` empty; the adapter only read the
  LEGACY wake keys `context.taskTitle`/`context.taskBody`, so `buildGoal` returned `null` and the
  run failed as `longrun_invocation_incomplete` before any work — the issue itself had a 73-char
  title and a 1519-char description. The modern `objective` now wins (with `issueId` as the
  `task_id` fallback) and the legacy pair stays as a fallback; `DEFAULT_COMMAND` is `python3`
  (the DGX has no `python`). 17/17 vitest tests green.
- **The 🏷 button reported success while no label changed (JAG-474).** The server named the
  groups correctly, but the WebUI never applied the titles: rendered free groups carry no
  chapter `gid`, and the position fallback only fired when the rendered and ledger group counts
  matched — after a compaction they don't (`coder 1`: 13 rendered vs 18 in the ledger, so zero
  matches). `applyThreadTitles` now matches a rendered group by its OWN captured user request
  (compaction-proof, index-free — the same rule `threads._anchor_index` uses) and never stamps
  one ledger group onto two rendered ones. Verified live: 9 untitled → 2 on `coder 1`. Pinned
  by `v469` 6a–6c.

### Changed
- **The ⚡ "run agent" chat action is REMOVED (JAG-431o), battery 164/164.** The ⋯ menu item drove the legacy
  `/api/agent/run` loop — a separate, older agent loop with **no todo enforcement** and a task graph keyed by
  the RUN id (so its todos never appeared in the session's Plan panel). The normal chat turn already does the
  same work, better: inline tools + model-authored todos + the keepgoing/JAG-402 close-todo enforcement. The
  menu item, its handler, the `runAgent()` renderer (`agentline`/`activeSSE`) and its CSS are gone; the
  **`/api/agent/run` endpoint stays** (documented headless entry point for the CLI, the MCP bridge and the
  benchmarks). Pinned by `v306`; `v226` re-pointed (the removed renderer was its old XSS site).
- **Composer one-row + send⇄stop, Control anchor fix, team scope, todo→constellation (JAG-424).**
  The composer toolbar is now a single row: the LLM model picker compresses (max-width 160px, min 96px)
  and every control no longer wraps on desktop; the separate **stop button is removed** — while the
  ACTIVE session runs the green **↑ becomes a red ■ (stop)** (`sendOrStop()`), so send/⋯ stay close and
  no space is wasted. The placeholder is compact again. **Control tab anchor FIXED for real**: the deck
  was pushed down by the app zoom — `_tabTop()` returned the ZOOMED topbar height but assigned it as a
  CSS `top` that the html `zoom` scaled AGAIN; it now divides by the live zoom (and re-applies on
  zoom/resize), so the deck sits flush under the banner at any zoom. **Right-click a todo** in the RH
  Plan panel → "◎ Show in constellation": the Control deck circles that task (pulsing ring) for a few
  seconds and scrolls it into view (crosses into the iframe via postMessage). **Team scope** now filters
  the whole board — routines were the last panel not scoped (agents/jobs/org/constellation already were).
  The Control agent-panel toolbars (scope/sort, new-agent, team) use one uniform `.toolbar` row.
  Guards updated to the intended design: v282/v284 model-picker width.
- **Header/Control polish + mobile (JAG-424b).** The **sandbox pill** moved out of the ☰ app menu
  onto the banner line; the **context meter** left the banner and now sits as a **tiny circular ring**
  (no % label) in the Sessions rail header, beside the collapse/expand icons. On phones (≤640px) the
  banner drops the LONGRUN wordmark and keeps only the sandbox dot, so it never overflows. **Control
  deck panel titles are uniform** — just the panel name (+ count + tools); the Org-chart usage hint
  moved into its `title` tooltip, and **Job → Jobs**. The agents toolbar is split into three tidy rows
  (scope/sort · new-agent · team) instead of the crammed single row, and the per-agent actions cell is
  compacted so **↺ reset** and **✕** sit on ONE line (`white-space:nowrap`). Verified live at a true
  390px mobile viewport (Session + Control): no horizontal overflow anywhere.
- **Brand icon = running man; Sessions/Control naming (JAG-424c).** The PWA/app icons
  (`webui/assets/icon-192/512/maskable-512.png`, `apple-touch-icon.png`) are regenerated from the
  real Longrun mark — a stylized **running man** — instead of the old bolt (`webui/assets/make-icons.py`
  redrawn); `assets/icon.svg` is the source-of-truth repo icon and now heads the README. The UI copy
  no longer says "Bridge" or "the main app": the two top-level views are **Sessions** (`/`) and
  **Control** (`/orbit`), and every user-facing hint (Control job/constellation detail, org-chart menu,
  ROLE.md editor note) now points at the "Sessions tab". README Interfaces + quickstart updated.
- **Control deck: compact org chart + interactive constellation (JAG-424d).** The org chart is no
  longer a one-row CSS tree that stretched a wide fan-out to thousands of px — it is laid out in JS
  with sibling rows that **wrap** (fixed 132×62 node boxes, agent **names wrap to two lines**), so a
  big team grows DOWN in the panel and the `fit()` zoom stays legible; connectors are SVG elbows
  (`.oedge`). In the Constellation, **job and subjob pills are now clickable** like a task: click =
  a metadata popover (goal/status/coordinator/blocked_by/subjobs, or assignment/deps/todos),
  double-click = open the related session. Junctions improved: curved cross-board edges (instead of
  straight lines slicing through clusters), a junction dot at each dependency's source, rounded
  caps, and a clearer legend with the arrow semantics. Guards v285/v328 updated to the new
  connectors/edges (same intent).
- **Control deck: tidy toolbar, correct org-chart routing, collapsed defaults (JAG-424e).** The
  AGENTS toolbar is now ONE ordered row — `scope · sort … ＋ new agent · ＋ new team · ⚙ model
  policy` — with the create inputs revealed on demand (they no longer clutter the panel). The org
  chart routes wrapped rows through a **left trunk + per-row bus**, so a row-2 child's line can no
  longer pass through — and look like an edge to — a row-1 node (the "Reality Checker → Growth
  Hacker" illusion; they are siblings, both reporting to A12). The Routines/Jobs goal textareas are
  capped (`max-height` + vertical resize) so the ＋ buttons can no longer be pushed out of the panel.
  **Default view is COLLAPSED**: the Control AGENTS team groups and the Sessions rail groups both
  open collapsed (the rail keeps only the active session's own group open); the rail stores an
  explicit "open" list, so a brand-new team also starts collapsed.
- **Control/Sessions fixes: persistent zoom, correct org chart, tidy create rows, legible logo (JAG-424f).**
  - The Constellation now **keeps your zoom/pan across the 5s refresh**: `draw()` only re-fits when the
    content box really changed. It used to reset the `viewBox` on EVERY poll, so zooming "snapped back"
    to the default unpredictably.
  - The org chart's wrapped rows are **top-aligned**. Siblings were vertically CENTRED by subtree height,
    so a shallow sibling sat lower than a deep one and read as its child (the "Reality Checker → Growth
    Hacker" illusion — they are siblings, both `reports_to A12`). Verified: 0 node overlaps, every child
    below its parent.
  - The Routines/Jobs **create rows** no longer push the ＋ button out of frame: a full-width `<select>`
    with long options refused to shrink; now the select flexes (`min-width:0`) and the button stays put
    and never wraps.
  - The topbar logo is a **legible bold running-man** (the old 24px glyph turned to mush at 15px).
- **Control/Sessions: real org-chart centring, tab isolation, ctx ring on the session row (JAG-424g).**
  - The org chart **centres every parent over its children** (midpoint of the children's true centres),
    not over the block width. With uneven subtrees the two differ, so a parent's stem missed the bus
    centre (e.g. "Growth Hacker" hung over "Social Media Strategist" instead of between its two kids).
    Wrapped rows are **left-aligned off one short trunk** in a narrow gutter, so a lone child is never
    centred under its parent (a fake parent→child chain) and no connector crosses a node.
  - The Control tab **fully captures the mouse/keyboard**: `#app` (the Sessions page) is set `inert`
    while Control is up and released on return, so nothing behind the overlay is hoverable/clickable.
  - The context ring moved off the **Sessions panel header** onto the **active session's row** (line 1,
    right of the message count) so it shows that ONE session's saturation and no longer overlaps the
    title. Its tooltip still carries the full "used / budget · %" detail.
- **Frontend review pass — accessibility, contrast, motion + a cleaner shell (JAG-425).** A full
  review of the WebUI against the frontend/accessibility bar, then every finding fixed:
  - **Tool cards are a real keyboard disclosure** — the header is `role="button" tabindex="0"` with an
    `aria-expanded` that tracks the open state (Enter/Space toggle) instead of a click-only `<div>`,
    plus a visible focus ring.
  - **The two HITL free-text fields carry a `name` + `aria-label`** (Chrome's "form field needs an
    id/name" issue is gone).
  - **The document outline starts at `<h1>`** — the wordmark is now the page's `h1` (it used to jump
    straight to 33 `<h2>`s with no `h1`).
  - **Sandbox state is never colour-only** — on a phone the sandbox word is visually hidden but stays
    in the a11y tree, so screen readers still announce it.
  - **The sand (light) theme now clears WCAG AA**: secondary text, links and status colours were
    darkened (`--dim/--acc/--ok/--warn/--err`) from ~3.9–4.2:1 to 4.7–5.3:1.
  - **`prefers-reduced-motion` is honoured** — animations/transitions collapse to instant.
  - **No nested horizontal scrollbar on mobile** — `#log` clipped the `overflow-x` that
    `overflow-y:auto` forces on; wide code/tables now scroll inside their own block.
  - **Cleaner shell**: 126 repeated inline styles became ~35 utility classes, and 114 inline
    `onclick`/`onchange` handlers became `data-call`/`data-change` attributes driven by ONE delegated
    listener (no eval). Source-locked assertions in v284/v311/v319/v361/v403/v405/v406 now check the
    intent instead of the old syntax.
  - **The legacy standalone deck (`/console`) says so** — a banner points at the in-app Control tab
    (kept routed for direct links + its tests). Battery 137/137 GREEN.
- **Settings: auto-save everywhere, general default model, Knowledge polish (JAG-423).** Every model
  picker saves on change — the **Compaction model** and **Research model** `save` buttons are gone
  (`onchange`) — consistent with the embedding picker. The verbose "Saved automatically …" helper under
  Thinking effort is removed. **The shipped default model is now GENERAL**: `openrouter:openrouter/auto`
  (the cloud auto-router), not a local DGX model. `providers.default_ref()` prefers the user's persisted
  `★` choice and otherwise falls back to an AVAILABLE cloud provider (never a local model while a cloud
  key exists); `rllm.default_model()` now honours it, so a bare/absent request uses the general default
  instead of "whatever local model happens to be loaded". The user's choice persists across restarts
  (`providers.local.yaml`). The Knowledge settings rows (notebooks, sources, files) are restyled with a
  shared `.kb-row` (bordered, hover, count badge) instead of scattered inline styles. The embedded
  Control deck is anchored flush to the banner (`html.embed .wrap{padding-top:0}`) — no more strip of
  the Sessions view showing above the Agents/Routines panes.
- **Settings ▸ Models cleanup + thinking-effort fixes (JAG-422).** The Models page is decluttered: the
  18-model embedding catalogue, the "add a model" form, the embedding costs and the "add / edit
  provider" form are now collapsible `<details>` (less scroll). The embedding **"set" button is gone** —
  picking a model in the dropdown applies it immediately (`onchange`). **Thinking effort now loads its
  saved value**: it lives in the Models category but only the "harness" category called
  `loadReasoning()`, so the checkbox/effort select showed stale defaults and looked like "the change
  did not save". **⚙ Settings now toggles** — clicking it while the window is open closes it.
  Backend: `_router_stream` retries once WITHOUT `reasoning_effort` when a provider rejects the field
  (400/404/422 naming it), so the DIRECT callers (compaction, planning, lessons) are now fail-safe too,
  not just the main chat/agent path (`stream_with_fallback`).
- **Control deck: one row-resize bar + stale-tab fix + knowledge "sources" + embedding-error surfacing
  (JAG-421).** The per-panel bottom grips are replaced by ONE horizontal bar per row that resizes the
  whole row (`Agents + Job` together); the bar moves the row height directly, so the old per-panel grip
  that a `flex:1` panel ignored is gone. `GET /api/build` now fingerprints BOTH `webui/index.html` AND
  `orbit/web/orbit.html` — previously only `index.html` was hashed, so an `orbit.html` change left an
  already-open tab's Control iframe stale until a manual reload (fingerprint `mtime-size[-mtime-size]`).
  The Knowledge panel's third button is renamed `files` → `sources`. `knowledge.add_source` now returns
  `embed_error` when the embedder produced ZERO vectors (endpoint/429/quota), instead of silently
  shipping a lexical-only source. Battery 137/137.
- **Control deck layout: full-width + resizable panels (JAG-419).** The deck now fills the window
  (the old 1680px cap that left huge side margins on wide screens is gone). Three rows sit side by
  side — Agents|Job, Org chart|Constellation, Routines|Feed — each with a draggable column splitter;
  every panel has a bottom grip to drag its height (mouse + touch). The Job panel is full-height,
  level with its row. Sizes persist in `localStorage`; a **reset layout** button restores defaults.
  The main-app header tagline ("agent harness …") was removed so the banner no longer changes when
  switching tabs.
- **Control deck UX: unified agents table, sorting, collapse/expand-all (JAG-418).** The AGENTS pane is
  now ONE editable table grouped by team (collapsible group rows + editable agent rows) instead of two
  separate `table` / `by team` views. A **sort** selector orders agents (id, name, role, model, team,
  org-chart leadership, running first); **collapse all / expand all** buttons act on every group. The
  `beta · detachable` badge is removed and the team selector moved out of the header into the panel
  toolbar; **Job** now sits beside **Agents**. The main-app session rail gained matching
  collapse-all / expand-all controls.
- **Voice input auto-stop + `Alt+X` shortcut (JAG-416e).** The 🎙 mic closes by itself after
  3 s of silence and the transcript lands in the message bar for the user to review and send
  manually (no auto-send); `Alt+X` toggles recording from the keyboard.
- **Atomic JSON store dedup (JAG-416e).** A single `src/longrun/util/fswrite.py` (`read_json` /
  `write_json`, race-free unique-temp + `os.replace`) now backs 18 stores, removing 6 duplicated
  helpers (~34 call sites) and fixing the latent fixed-`.tmp` race in modules that had not yet
  received the JAG-201/JAG-287 fix. Battery 137/137.
- **Architecture docs refresh (JAG-416e).** `docs/ARCHITECTURE.md` and
  `docs/diagrams/longrun-architecture.architecture.json` updated to the real
  `src/longrun/<subpackage>/` layout and translated to English, with the missing
  orbit / research / knowledge / orchestration components added.
- **Session rail groups by TEAM, collapsible (JAG-414).** The left-hand session panel now
  renders one collapsible group per team (symbol, name, member count) plus a **📌 Pinned** group
  and a **◇ No team** group. A session whose agent belongs to SEVERAL teams — or that is pinned
  and also in a team — is DRAWN once per group: a purely **graphical** duplication (same session
  id, same click handlers, same transcript, same everything). Nothing is duplicated in the
  substrate; the session stays single, and the Bridge page (`/orbit`) is unaffected. The
  running / finished / active markers now update EVERY copy of a session (the rail helpers used
  a singular `querySelector`, now `querySelectorAll`). Collapse state persists per group in
  `localStorage.sf_collapsed_groups`; pinned sessions still sort first within their group. When
  no teams exist the rail keeps the previous flat, header-less list (backward compatible).
- **Embedding UI moves out of the right-hand panel into Settings ▸ Models (JAG-403c).** The
  duplicate `Embedding` inspector section is gone; the model picker, the personal-model
  manager and the cost log now live together under **Settings ▸ Models**. `config/routing.yaml`
  and the routing defaults ship EMPTY fallback chains — a role resolves to a single model via
  its `pattern`, and the Models panel no longer prints an unexplained "fallback: …" chain
  ("the selected model is used as-is"). The knowledge **sources** list now renders URLs as
  real hyperlinks (open in a new tab), opens files in the editor — images in the image window,
  **PDFs in the browser viewer** — and is a bounded, scrollable window (`LIMIT=200`,
  "showing X of Y"). **Thinking effort** now auto-saves on change (the manual button is gone).
  v403 22/22; battery 129 → 130.
- **The research-model picker now offers your SAVED models (JAG-403d).** `researchcfg.all_models()`
  merges the web-grounded catalogue (Perplexity Sonar) with **every model of every configured
  provider** (grouped by provider in the select), and the executor resolves a saved model
  through the normal provider path (`rllm._chat_endpoint`) — plus a `local:<alias>` path for
  the local router. New `GET /api/research/model` companion to the POST setter. v402 28/28.
- **Knowledge panel polish + skills open in the editor (JAG-403e).** The *Discover* and
  *Research* sections are merged into ONE **"Research · web → notebook"** card: a single topic
  bar plus an **auto (agent)** checkbox that switches manual discover ↔ the automated agent.
  *Search knowledge* moved to the top, right under *Knowledge · global*. The Knowledge tab's
  `<h2>` headings now use the SAME style as every other settings tab (the `.sw-cat > h2` rule
  became descendant so a wrapper no longer breaks it). Clicking a **skill** opens its `SKILL.md`
  in the **file editor** (the separate modal was removed; the skills API now returns an
  `abspath`). Fixed: knowledge **search results** and the **notebook files** list are now
  clickable (URLs open in a tab, files in the editor) and the files list is bounded/scrollable.
  v403 31/31; battery 130/130.
- **Cost panel grouped per run + Bridge org UX (JAG-403f).** The right-hand **Cost** panel now
  groups the session's API calls **per run** (one user turn): each run is a collapsed row with
  its time, model(s), call count and **total**; click to expand the individual calls. Every
  ledger record now carries the turn's `run` id (tagged by `chat_once` from the chat `RunTrace`).
  In the **Bridge**, the AGENTS table is content-sized and packed to the LEFT (explicit `<col>`
  widths, no full-width stretch) instead of spread across the panel, and the "+ new agent"
  inputs are no longer full-width. The **org chart** keeps click = preview (constellation) and
  double-click = open the agent's session in the main app, and gains a **right-click** quick
  action menu (Constellation / Open session / Edit prompt / Reset) that reuses existing stores
  and endpoints only. v404 17/17; battery 130 → 131.
- **Ordered live summary beside every inspector tab (JAG-403g).** Each RH tab now
  shows a one-line summary — Cost → session `$` + calls, Context → `pct% · used/budget`,
  Approvals → `N pending` / `none`, Plan → `done · super · doing · todo · blocked · run`
  (counts in a fixed order), Roles → the agent id + name (or `ad-hoc`), **Workspace**
  (the tab formerly named *Files*) → the folder name, Codebase → `files · chunks`,
  Browser → the last `web` action, Terminal → the shell cwd, Feed → a live event
  counter. All update in real time from the renderers that already run on every
  update; the header is a wrapping flex row so the summary drops under the label
  (or ellipsizes) when the rail is narrowed — no need to expand the tab. v405 30/30;
  battery 131 → 132.
- **Knowledge + Bridge cleanups; the duplicate Browser tab is gone (JAG-403h).** The
  RH **Browser** panel was removed — its `search` half was the SAME backend as
  Knowledge ▸ Discover, and the agent still has the `web` tool. In the Bridge org
  chart, a **single click** now only previews the constellation (it no longer yanks
  the AGENTS table around). In Knowledge: a **`text` source** (pasted note / research
  summary) is no longer rendered as a false file link (it has no file — its `ref` is
  the title); the **Notebooks** list is a bounded scroll window; **depth + max
  sources** are now ALWAYS visible in the Research card (they drive both the manual
  discover count and the auto research rounds) instead of being hidden behind the
  auto checkbox; and the **status/clear** buttons sit to the RIGHT of the counts
  (they wrap under only when the panel is narrow). v406 11/11; battery 132 → 133.
- **Cost panel no longer floods with one-call rows (JAG-403h).** Calls that carry no
  `run` id (older ledger rows, non-turn callers) are now folded into a SINGLE collapsed
  bucket ("older calls (no run id)") instead of one row each — the 60-row tail used to
  fill the panel. Real turns stay one collapsible row per run.
- **Settings ▸ Models reordered + Workspace panel trimmed (JAG-403i).** The Models tab
  now reads top-to-bottom: **Thinking effort → Compaction model → Embedding → Add/edit
  provider → Providers → Available models**. The three separate embedding sections
  (model, personal catalogue, costs) are merged into ONE **Embedding · knowledge index**
  card, with *add a model* and *Embedding costs* behind collapsible `<details>` (less
  clutter). Removing a *shipped* catalogue entry and adding your own is now described in
  one place. The Workspace inspector panel no longer prints the redundant
  `session ▸ … · N chars of rules` line nor the `default ▸ …` echo (the path is already
  in the input box); `setWorkspace` reports via a toast. v407 10/10; battery 133 → 134.
- **Document ingestion: PDF / Office / OCR now embed into the knowledge base (JAG-403j).**
  A new `longrun.memory.docio` layer turns BINARY documents into text before chunking +
  embedding, in this order: `markitdown` (if installed — best PDF/DOCX/PPTX/XLSX fidelity),
  else the system tools `pdftotext` (with OCR via `pdftoppm` + `tesseract` for scanned PDFs)
  and `libreoffice --headless --convert-to txt`. `chunk.lang_for`/`read_text` route PDF/DOCX/
  PPTX/XLSX/ODT/… through it, so a knowledge source can now be a URL, a folder **or a PDF**
  (`*.pdf` was removed from the codebase ignore list too). A failing embedder now degrades to
  bm25 instead of breaking a build/ingest. A **default embedding model ships**
  (`cohere:embed-multilingual-v3.0`) so a fresh clone is not left empty. New `requirements.txt`
  documents the optional `markitdown` dependency. The knowledge status shows which extractors
  are installed. v408 15/15; battery 134 → 135.
- **UI polish (JAG-403j).** The composer toolbar is now a FLAT strip (no per-button frames —
  only *send* keeps its button shape). The Notebooks list is a collapsible `<details>` menu
  whose summary shows the active notebook + its source count.
- **Composer + session rail redesign, and a 1-month cost cap (JAG-415).** Seven WebUI changes.
  **Composer:** the textarea now **auto-grows** with the text up to 160 px then scrolls; the
  font is smaller (12.5 px); the button row is decluttered — **reset** moved into the **⋯**
  overflow menu, **run agent** too, and **stop** is a compact **■** icon. **Session rail:** the
  **◇ No team** group now sits right BELOW **📌 Pinned** (before the teams), and rows inside
  every group are ordered by the **ORG tree** (orchestrators first, a depth-first `reports_to`
  walk) instead of "last used". A **redirect** (rail click or an Orbit double-click on a
  constellation/task node) now **expands** the target session's team group if it was collapsed
  (and only then — a plain re-render never fights the user's own collapse). A turn that
  **finished while you were on another session** now raises the same bell + toast as an in-tab
  turn. **Inspector:** **settings / Bridge / command palette / sandbox** moved off the topbar
  into a single **☰** app menu (the Context tab is UNCHANGED and stays).
  **Codebase:** a new **"auto-index before an agent searches"** checkbox (shared index config,
  default ON) makes the agent's `index` search run a quick incremental rebuild first and
  **wait** for it — concurrent agents serialize on the build lock, so the index is never queried
  stale or half-built. **Cost:** both ledgers (per-session model calls and the embedding log)
  now keep at most **one month** of history. Battery 137/137.
- **Top-level Session / Control tabs; the deck is renamed Control (JAG-416).** The app now has a
  segmented **tab bar** in the header — **Session** (this chat app) and **Control** (the agent
  control deck, formerly "Bridge"). Both tabs are styled as a rounded segmented control and
  carry the token across, so switching lands authenticated. The deck is renamed everywhere the
  user can see it: page `<title>`, the header tab and the `orbit/api.py` fallback page now say
  **Control**. **Settings** is now a plain, always-visible ⚙ in the header (it is fundamental);
  the **☰** menu keeps only the sandbox status + the command palette. Battery 137/137.

### Fixed
- **ONE model per turn: the planner IS the session's chat model — the local GPU is never a secret helper (JAG-455), battery 180/180.**
  Reported live: harness sessions whose model read `deepseek-reasoner` while the DGX GPU was busy. Root cause (one, several symptoms): the plan was
  routed by a SEPARATE `planner` role in `config/routing.yaml` whose `pattern: qwen` matched the **LOCAL** weights, so every turn of a cloud-pinned
  session still made one local model call — and the router's autoload then LOADED the local weights, which is the GPU the operator saw. The same role
  was consulted by the sync `/api/chat` path, by `write_todos`/re-plan, by the legacy planner and by the heuristic router; and `/api/agent/run`
  resolved `model or default_model()` FIRST (dead branch) and then ALWAYS overwrote it with the route hint's `pick("agent")` — the LOCAL model — even
  when the caller had pinned a cloud one. **The `planner` role is deleted** (config + defaults + code): every planner call now runs on the turn's own
  model via the new `routing.turn_model()` (explicit request model → session pin → harness default), and the planner and the answer share ONE model
  variable. A harness comparison therefore tests ONE model — never a mix with a stronger or cheaper helper. **Verified live**: a session pinned to
  `deepseek:deepseek-chat` gets the cloud ref for the planner call AND the answer, and the router roster's `loaded` set stays unchanged (no local
  autoload). Deleting sessions is now also safe: a deleted transcript is MOVED to `data/trash/` (recovers a misclick) and a deleted id can no longer
  be answered with a look-alike fresh session — that is why deleting during a running benchmark appeared to *duplicate* rows. Pinned by `v455` (28/28).
- **A completed chat turn can no longer leave a plan nobody authored or closes (JAG-431n), battery 164/164.**
  The JAG-76 "guarantee a plan" fallback ran a planner model call **after** the turn had already answered, so its
  steps described work that was already done; nobody ever executed them, and JAG-173 forbids auto-closing a step
  — so they dangled as OPEN todos forever. Worse, the next turn's JAG-189 "stale plan" rule (`user_pivot`)
  exempted them from the JAG-402 close-todo enforcement, so they were never cleaned up. **Proven** on kb-agent
  `55a29fae70cb`: the reply landed at `ts=1791835170.33` and `graph.node.added` fired at `ts=1791835195..200` —
  3 orphan todos created ~25 s AFTER the answering turn. The fallback planner is **removed** (function +
  re-export + call): the graph is written only by the model (`write_todos`) or by the operator (the explicit
  sync `/api/chat` path, which also finalizes its plan). The session's 3 orphans were deleted (a timestamped
  graph backup kept). Verified live: a fresh chat turn left the graph empty for 60 s. Pinned by the rewritten
  `v306`.
- **Knowledge base could not be queried by notebook name (JAG-427 RAG QA), battery 151/151.** Building
  notebooks from the WebUI worked (`add_source`/`add_text`/`search` were all correct at the API level),
  but the **agent** could not retrieve from them: `knowledge action=list_notebooks` printed only NAMES
  + source counts while `action=search` scopes by notebook ID, so the model passed the name it was shown
  and got a silent `(no matches)` — notebook-scoped agentic RAG looked broken. Fixed: `list_notebooks`
  now prints each notebook's `id=`; `search` AND `add_text`/`add_source`/`add_source_text` resolve a
  notebook given by NAME *or* ID (`knowledge._resolve_id_db`); and an empty scoped search now lists the
  valid notebooks so the model can recover. Verified live end to end (WebUI): a fresh notebook of 3 PDFs
  + 5 web URLs (700 chunks, all embedded with `gemini-embedding-001`) returned the correct sources for
  both a Rademacher-complexity query (Foundations of Machine Learning.pdf) and a Machiavelli query
  (machiavelli_il_principe.pdf). Pinned by `v427`.
- **RAG quality measured on the live corpus (JAG-428 QA).** A 6-question complex evaluation run by a
  knowledge agent (WebUI, local `nex-n25-mini-uncensored-q8`), forced to answer only from `knowledge`
  tool snippets. Result: **5/5 in-corpus questions answered correctly and faithfully** — LIME (Interpretable
  ML PDF), Shapley values (PMC11513550), a LIME-vs-SHAP synthesis across 3 sources, Rademacher complexity
  (Foundations of ML PDF) and an exact Italian Machiavelli quotation — and the **honesty trap
  (Anthropic 2024 revenue) correctly refused** with `NOT IN CORPUS` ("anthropic" occurs only in a timeline
  / blog context; `anthropic`+`revenue` co-occur 0 times). Every cited quote was independently verified as
  a real substring of a stored chunk (no fabrication). Retrieval precision measured from the WebUI over 8
  targeted queries: **P@1 0.75 · P@3 0.88 · MRR 0.81** (the two "misses" were the SHAP docs'
  `partial_dependence_plot` example and the online mirror of the same ML book — both relevant). Honest
  limitation: BM25 OR-terms over a mixed multi-doc corpus can surface loosely-related chunks for vague
  natural-language queries; scoping to the right notebook and using distinctive terms gives crisp hits.
- **Checkpoint/rewind route was unreachable (JAG-426 follow-up), battery 148/148.** While QA-ing the
  WebUI end to end, `GET /api/checkpoints` turned out to be SHADOWED: `httpapi.do_GET` dispatches to
  `api_v02.handle` first, and the older v0.3 handler owned that route — returning the newest N
  checkpoints of EVERY session, ignoring `?session=` and never emitting the `marks` (turn anchors) a
  rewind needs. The newer JAG-426 handler in `httpapi` was dead code, so no client could discover a
  rewind point. The v0.3 handler is now session-aware and returns `marks`; the duplicate GET handler
  in `httpapi` was removed. Verified live: rewind to `msg_index N` trims the transcript, truncates the
  event log, and removes the files the harness wrote through `fs.write`/`fs.edit` (pinned by `v424`).
- **Harness-audit bug fixes (JAG-426 follow-up), battery 147/147.** Five defects found by auditing the
  freshly shipped JAG-426 code, each pinned by a new acceptance test (`v422`, `v423`). (1) `glob`
  escaped its allow-list through an **absolute** or `../` pattern — `os.path.join(root, "/etc/*")`
  discards `root`, so it listed the whole filesystem regardless of policy; absolute patterns are now
  rejected and every match is confined to the resolved root. (2) `events.feed_seq()` returned a
  **process-local** counter that reset to 0 on restart, so a turn anchor stamped right after a boot
  could carry an event cut BELOW the session history and a rewind would then drop far too many
  events; it now reads the durable `MAX(id)`. (3) `checkpoints.create_turn` re-stamped `events_upto`
  on an idempotent **duplicate** mark, moving the cut above the turn's own events (a rewind then
  failed to truncate them); the original cut is now preserved. (4) `decision.pre_tool` built the
  decision model twice and re-read/re-parsed `config/decisions.yaml` on **every** tool call; the
  config is now memoised on `(path, mtime, size)`. (5) the streaming chat path anchored the rewind
  point **outside** the turn lock with a stale message index (racing concurrent turns onto a shared
  idempotency key); the anchor now lives inside the worker, like the sync path. Also fixed a
  long-standing **exit-time SIGSEGV**: `context_budget()` -> `providers.local_contexts()` spawned a
  bare `daemon=True` thread doing `urlopen` (SSL/libcrypto); at `sys.exit()` the interpreter's
  `_dl_fini` unloaded libcrypto while that thread was still inside it (~80% of short-lived `v258`
  runs died with exit 139 after printing 7/7). These refreshes now go through a tracked spawner that
  is joined from an `atexit` hook, so the battery is deterministically green.
- **Voice input over HTTPS, Role tab, composer fit (JAG-416c).** The server now also listens over
  **HTTPS** on a second port (`--port + 1`, self-signed certificate auto-generated into `data/tls/`,
  **on by default**; disable with `LONGRUN_TLS=0` or choose the port with `--tls-port`). Opening
  `https://<host>:<port+1>/` makes the origin a **secure context**, so the Web Speech API (🎙) works
  on the LAN with **no tunnel and no browser flag** (accept the self-signed certificate once). The
  in-app voice help offers this as **Option A** (tunnel and Chrome flag remain as B/C). The inspector
  tab is renamed **Role** (singular — a session is per agent), the composer placeholder is shorter
  and *truthful* (`Ctrl+⏎ send` — Enter is a newline), and the composer toolbar now shrinks the model
  label and tightens the stop / ⋯ / send gaps so it stays on ONE line as the window narrows. Battery
  137/137.
- **UI follow-ups + bug fixes (JAG-416b).** Composer: the send action is now a **green circular
  icon button (↑)** in the toolbar (Trae-style) instead of a "send ⏎" text button, and the model
  selector moved to the right group. The first tab is labelled **Sessions** (plural). Voice input:
  a new one-click Windows helper (**`scripts/open-ui-voice.ps1`** / **`.bat`**) opens a localhost
  tunnel so the browser origin is a *secure context* and the Web Speech API (🎙) works from the
  LAN; the in-app help points at it. Bugs fixed: a duplicate `_growInp` binding (the textarea
  auto-grow ran twice per keystroke); an unescaped `ag.reports` in a session-row `title`
  attribute (HTML-attribute injection); `costs._load` now DROPS (never crashes on) a malformed
  ledger `ts` — one bad row used to break every subsequent cost record; the auto-index refresh is
  debounced (15 s) so a burst of agent searches no longer re-walks the whole workspace each time;
  the incremental index now compares RAW mtimes (a sub-second edit used to be missed); and
  `index` search with no workspace returns a clear error instead of an opaque tool failure.
  Battery 137/137.
- **Embeddings were silently never stored — the semantic layer was dead (JAG-403k).** The
  embedding catalogue referenced providers (`cohere:`, `voyage:`, `jina:`) that were **not
  declared** in `config/providers.yaml`, so `providers.resolve()` returned `None`, the batch
  fell back to the local router (which has no embedding models) and **0 vectors** were written —
  while the UI still showed an active model. Fixed by declaring the three providers as
  **embedding-only endpoints** (`embed_only: true`, no chat models, so the model picker stays
  clean): Cohere `https://api.cohere.ai/compatibility/v1`, Voyage `https://api.voyageai.com/v1`,
  Jina `https://api.jina.ai/v1`. A second, latent bug surfaced once vectors existed: the HYBRID
  retrieval path (`codeindex.search`/`knowledge.search`) raised `UnboundLocalError` (a
  comprehension reused `r`, made function-local by the `for r in rows` loop below) — the branch
  had never run before. Embed build/ingest failures are no longer swallowed: they are recorded
  (`meta.embed_error`) and reported (`embedded` count + error) through `/api/codebase/status`
  and `/api/knowledge/status`, and the UI shows **"N/M embedded"** with a warning on failure.
  `knowledge.reembed()` (API `POST /api/knowledge/reembed`, UI **"⟳ re-embed"**) back-fills
  vectors for indexes built while no model was available. Verified on the DGX: codebase
  116/116 and knowledge 76/76 chunks embedded (dim 1024); a real 2.2 MB arXiv PDF extracted via
  `pdftotext` (61,642 chars) → 18/18 embedded with hybrid search. v409 17/17; README 135 → 136.
- **Deleting the WHOLE knowledge base always asks (JAG-403e).** `confirmDelete` gained a
  `force` flag so the "don't ask again (until reload)" suppression can never skip the
  whole-knowledge-base confirmation.
- Removed a dangling `closeSkillView()` call on Escape (undefined after the skill modal was
  removed) that would have thrown on every Escape press.
- **Bugfinder sweep (JAG-410): six latent bugs fixed, battery still 136/136.**
  - *File handle leaks*: `open()` without `with` in `indexcfg.py` (3), `keys.py` (2),
    `embedcfg.py` (1) — a long-running server under load could exhaust file descriptors.
  - *Silent embedding truncation* (`vectors.embed_chunks`): `embed_texts()` filters out empty
    strings, but `zip(part, vecs)` silently truncated when a batch had any — trailing chunks
    got no vector while `done` overcounted them. `part` is now pre-filtered to match.
  - *TOCTOU race in the persistent terminal* (`term.Shell.run`): the `busy` flag was checked
    then set outside the lock, so two concurrent calls could both write to stdin. The
    check-and-set is now atomic under `self._lock`.
  - *BrokenPipeError on a dead MCP child* (`mcp_client._send_raw`): a crashed stdio MCP server
    left a non-None `proc`/`stdin`, so `stdin.write()` raised `BrokenPipeError` and propagated
    to callers. The write now checks `proc.poll()` and catches pipe errors, returning `None`
    and marking the client disconnected.
  - *Pasted text was never embedded* (`knowledge.add_text`): unlike `add_source` (URL/path),
    `add_text` skipped the embedding step entirely, so notebook text was bm25-only. It now
    embeds and reports `embedded`/`embed_error` consistently.
  - *Silent embed failure in `add_source_text`*: the research executor's ingest path used
    `except Exception: pass` instead of recording the error; now reports `embed_error`.
- **Bugfinder sweep round 2 (JAG-411): seven more bugs fixed, battery 136/136, live turn verified.**
  - *SSE subscriber set race* (`events.publish` + `httpapi.feed_gen`): `_sse_queues` was mutated
    (`add`/`discard`) by request threads while `publish` iterated a snapshot with no lock —
    a size change during iteration raises `RuntimeError` and silently drops a fresh subscriber.
    New `_sse_lock` guards add/discard/snapshot (re-exported through `server`).
  - *Blackboard watcher set race* (`swarm._notify`/`watch_gen`): same shape on `_watchers`;
    now guarded by the module `_lock`.
  - *MCP reader-thread TOCTOU* (`mcp_client._reader`): check-then-`put` on `._pending` outside
    the lock could raise `KeyError` (killing the reader loop) when `_send_raw` popped the entry
    concurrently. Now a lock-guarded `.get()`.
  - *Silent transcript loss* (`agent`): the agentic turn transcript was persisted under
    `except Exception: pass` with no signal — a failure dropped the model's tool calls/observations
    silently. Now publishes `graph.error kind=transcript.persist`.
  - *Silent checkpoint downgrade* (`api_v02`): a failed run-start checkpoint set `_CHECKPOINTS_START=None`
    with no record, leaving the run unrollback-able and unobserved. Now publishes `checkpoint.error`.
  - *File handle leaks*: `open()` without `with` in `routing.load_config` and `voice` STT read.
  - Fixed a self-introduced circular-import regression (`_sse_lock` must be re-exported by
    `server` before `httpapi` imports it); caught by the battery, 136/136 after the fix.
- **Bugfinder sweep round 3 (JAG-412): seven bugs fixed — input validation, token accounting, WebUI.**
  - *Crash on malformed numeric input* (`api_v02` research executor): raw `int()` without try/except
    on `n`/`max_rounds` raised and dropped the connection; now uses `_int()`.
  - *Token undercount per run* (`agent`): `runmetrics.finish()` reported only the LAST LLM call's
    tokens; a turn with retries/tool loops was materially undercounted. Totals now accumulate in
    `_record_usage()` via nonlocal counters.
  - *Operator-precedence bug* (`mcp._routing_call`): `a.get("roles") or "x" in a` silently ignored
    a valid `{"roles": {}}` payload; now a key-presence check.
  - *Null approval id* (`mcp.HttpApi.approvals`): `decide` with a missing id built
    `/api/approvals/None`; now returns a clean error.
  - *WebUI: unchecked `response.ok`* (`api()`): a non-JSON 5xx threw in `r.json()`; now returns a
    synthesized `{error}`.
  - *WebUI: dead feed* (`connectFeed`): the feed EventSource had no error handler, so a dropped
    SSE connection killed the panel permanently; now reconnects after 5 s.
  - *WebUI: XSS* (`memKindsInit`): server-provided memory kind names were injected into innerHTML
    without `esc()`.
- **Bugfinder sweep round 4 (JAG-413): resilience fixes, battery 136/136, live server clean.**
  - *Corrupted `events.db` crashed the whole server* (`events.db`): a bad SQLite header (power loss
    / `kill -9`) raised on the first event with no recovery. `db()` now quarantines the file (and
    its `-wal`/`-shm` sidecars) as `events.db.corrupt-<ts>` and starts a fresh log — it is a REPLAY
    buffer, not the source of truth.
  - *Sandbox OOM* (`sandbox._run`/`_run_tracked`): `communicate()` read ALL stdout/stderr into
    memory, so a command spewing gigabytes exhausted the host. Output now goes to temp files and
    only `MAX_OUTPUT_BYTES` (2 MB, `LONGRUN_SANDBOX_MAX_OUTPUT`) per stream is read back.
  - *Document-extraction OOM* (`docio._run`): same pattern on `pdftotext`/`soffice`/`tesseract`;
    output is captured to temp files and capped at `LONGRUN_DOC_MAX_OUTPUT` (64 MB).
  - *OCR page order* (`docio._ocr_pdf`): `sorted(os.listdir)` reordered a 10+ page scan
    lexicographically (`page-1, page-10, page-2`); now sorted by numeric page index.
  - *Leading-dash paths read as flags* (`docio.extract`): a `-x.pdf` name was passed to the
    converters as an option; now resolved with `os.path.abspath`.
  - *Empty-file guard* (`docio.extract`): a 0-byte document no longer spawns OCR/converters.
  - *Orphaned checkpoints* (`stores._purge_session_artifacts`): deleting a session left its
    checkpoints behind, so a later rollback half-applied to a tombstoned session; new
    `checkpoints.purge_session()` sweeps them.

### Fixed
- Pre-existing `NameError: name 'embed' is not defined` in `codeindex.search` (line 208)
  triggered when an embedding model was configured: `from longrun.model import embed as
  _embed` added and the new `(vecs, usage)` tuple from `embed_texts` unpacked.
- **Thinking effort never persisted (JAG-403c).** `tools/registry._diff_overlay`/`_merge_into`
  did not include the `reasoning` key, so the saved effort was dropped from the overlay and
  silently reset on every restart. `reasoning` is now a known config key (persisted + merged).
  Also, a non-thinking model that rejects `reasoning_effort` no longer crashes the turn:
  `_completion_body`/`_router_stream` accept a `no_reasoning` flag and `stream_with_fallback`
  retries the same model once without the field before failing over.

### Added
- **The WebUI is installable as an app — PWA scaffolding (JAG-390).** Adds a web app
  manifest (`webui/manifest.webmanifest`: standalone, 192/512 + maskable icons), a minimal
  service worker (`webui/sw.js`: network-first shell cache that NEVER intercepts `/api`, so
  the harness stays live-only), the head metadata (`icon`, `apple-touch-icon`,
  `apple-mobile-web-app-*`) and a boot-time `setupPWA()` that injects the manifest with the
  caller's token folded into `start_url` — so the installed icon opens an AUTHENTICATED
  shell while the HTML route stays token-gated (no security change). The icons are generated
  by `webui/assets/make-icons.py` (Pillow, dev-only, not served). The server serves
  `/manifest.webmanifest` and `/sw.js` PUBLICLY (the browser fetches them without the token;
  the SW must live at the root for its scope). NOTE: a service worker / rich install needs a
  **secure context** — over plain HTTP the SW is skipped and Chrome only offers the plain
  "Add to Home screen" shortcut; over HTTPS (e.g. Tailscale) it becomes a full installable
  PWA. New `v390` (8/8); battery 124 → 125.

### Changed
- **Renamed the whole project SparkForge → Longrun.** The package moves from
  `src/sparkforge/` to `src/longrun/`, the env prefix `SPARKFORGE_*` → `LONGRUN_*`, the
  display name and the systemd unit from `sparkforge` to `longrun`, the on-host folder
  from `~/Repositories/sparkforge` to `~/Repositories/longrun`, and the GitHub repo from
  `jagones84/sparkforge` to `jagones84/longrun`. The optional Beta deck is folded from the
  separate `src2/orbit_beta/` into the package as `src/longrun/orbit/` (one `src/` dir,
  no more beta tree). Battery kept 125/125 GREEN.
- **`server.py` split, phase 1 (JAG-370).** The external review was right on one
  point: `server.py` was a 6,432-line / 309 KB god-file. Three self-contained leaf
  clusters moved out, mechanically, with the module keeping thin re-exports so every
  existing `server.<name>` reference still resolves (`server.sse_pump`,
  `server.extract_json`, `server.ThinkCoalescer`, ...):
  - `bridge.py` — the optional `src2/` "Bridge" beta hooks; the app's only coupling
    to the beta is now one file wide.
  - `sse.py` — SSE plumbing (`sse_close`/`sse_response`/`sse_pump`) + `ThinkCoalescer`
    and the two think-coalescing constants.
  - `textkit.py` — `strip_think`, `_iter_json_objects`, `extract_json`.
  `server.py` 6,432 → 6,190 lines. Battery 120/120 GREEN; the split is proven by
  compile + import + re-export checks. One source-text assertion in
  `tests/acceptance/v285_orbit_beta.py` was repointed from `server.py` to `bridge.py`.
- **`server.py` split, phase 2a: `keys.py` (JAG-371).** API-key management
  (`ENV_FILE`, `KNOWN_ENV_KEYS`, `_env_file_upsert`, `set_key`, `reveal_key`,
  `keys_status`) extracted to `keys.py` — a clean leaf (only `os` + lazy
  `providers`/`mcp_client`). `server.py` re-exports the names, so `server.set_key`
  / `server.ENV_FILE` / `server.keys_status` still resolve. `server.py` 6,190 →
  6,048 lines. Battery 120/120 GREEN; verified by compile + import + re-export.
- **`server.py` split, phase 2b: `events.py` (JAG-372).** The durable event log
  (sqlite `db()`, `prune_events`, `_start_event_pruning`), the live SSE feed
  (`publish`, `events_since`, `query_events`, `MAX_FEED_EVENTS`), the per-session
  turn bracket (`turn_begin`/`turn_end`) and the turn locks (`_turn_lock`) moved to
  `events.py`. Its shared mutable state (`_ACTIVE_CHAT`, `_sse_queues`, `_feed`,
  `_TURN_LOCKS`, the locks) is mutated and never rebound, so `server.py` re-imports
  the **same objects** — mutations stay visible both ways. The one rebound global,
  the feed high-water mark `_feed_seq`, is now read through `events.feed_seq()` (the
  single external reader was the streaming turn registration). `server.py` 6,048 →
  5,818 lines. Battery 120/120 GREEN; two source-text tests repointed to `events.py`
  (`v298_perf` WAL/NORMAL pragmas, `v325` bracket definition) and `v325`'s C4 updated
  to the `feed_seq()` form.
- **`server.py` split, phase 2c: `voice.py` (JAG-373).** The whisper STT /
  sherpa-onnx TTS block moved to `voice.py` (self-contained: only `os`/`uuid`,
  `DATA_DIR`, and `events.publish`). `server.py` re-exports `voice_status`/`voice_stt`/
  `voice_tts` + the `WHISPER_*`/`SHERPA_*` constants for the `/api/voice` routes.
- **`server.py` split, phase 2d: `tracing.py` (JAG-374).** `RunTrace`, `get_run_trace`,
  `runs_summary`, the `count_tokens` proxy, `MODEL_PRICES` and the shared
  `_REAL_PROMPT_TOKENS`/`_REAL_CACHED_TOKENS` token dicts moved to `tracing.py`
  (deps: `events.db`/`events._db_lock` + `otel_tracing`). `server.py` re-exports them;
  the token dicts are re-imported as the same objects (mutated, never rebound).
- **`server.py` split, phase 2e: `steering.py` (JAG-375).** The mid-run steer / abort
  inboxes (`STEER_INBOX`, `ABORT_INBOX`, `_steer_lock`/`_abort_lock`,
  `push_steer`/`drain_steer`/`has_steer`, `push_abort`/`_is_aborted`/`clear_abort`)
  moved to `steering.py`. The inboxes + locks are re-imported as the same objects, so
  `_forget_session_runtime`'s cleanup sees the same state. `v302`'s source-lock for
  `drain_steer` repointed to `steering.py`.
- **`server.py` split, phase 2f: `stores.py` (JAG-376).** The session / plan / task
  persistence layer moved to `stores.py`: the on-disk session transcripts
  (`load_session`/`save_session`/`append_message`), the plan + task stores, the
  tombstone bookkeeping, the job / workspace numbering, the per-session runtime
  clean-up (`clear_session`/`_forget_session_runtime`/`_purge_session_artifacts`) and
  the append/persist helpers (`persist_tool_card`/`persist_inject`/`session_mark`/
  `has_reply_since`/`reconcile_orphan_turns`). The path constants
  (`DATA_DIR`/`SESSIONS_DIR`/`_JOBSEQ_FILE`/`WEBUI_DIR`) moved to `paths.py` so the
  new module shares them without a cycle. `server.py` re-exports all 45 names, so
  every `server.load_session` / `server.append_message` reference still resolves.
  `server.py` 5,521 → 4,809 lines. Battery 120/120 GREEN; nine source-text
  assertions repointed from `server.py` to `stores.py` (v293, v302, v309, v311, v314,
  v315, v316, v321, v323). This extraction was driven by a new AST tool,
  `trash/split_move.py`, that moves a byte-exact line range, computes its DEFINES +
  FREE-NAMES dependency report and auto-generates the re-export import.
- **`server.py` split, phase 3a: `rllm.py` (JAG-377).** The router / LLM backend I/O
  moved to `rllm.py`: the model roster (`router_models`, `model_context_window`,
  `default_model`, `model_loaded`, `router_ping`), the warm-up / load path
  (`_router_load`, `ensure_model`, `_local_ref`, `_fire`), the token budget
  (`context_budget` + the `CONTEXT_*`/`AUTOCOMPACT_*`/`COMPACT_*`/`SUMMARIZER_*`
  constants), the streaming completion (`_router_stream`, `_open_with_retry`,
  `_set_read_idle`, `_chat_endpoint`, `_completion_body`, `_reachable`,
  `_reasoning_effort`, `MAX_TOKENS` + the repetition guard) and the
  `selfcheck_payload` diagnostic. The router config (`ROUTER_BASE`/`ROUTER_RETRIES`/
  `ROUTER_BACKOFF`/`ROUTER_BACKOFF_MAX`/`MODEL_LOAD_TIMEOUT`/`ROUTER_IDLE_TIMEOUT`)
  now lives here and is re-exported. Two app-level globals stay in `server`
  (`VERSION`, `AUTH_TOKEN`) and are read lazily from `selfcheck_payload` via
  `from . import server`, so no import cycle. `server.py` 4,821 → 4,284 lines.
  Battery 120/120 GREEN; three source-text tests repointed to `rllm.py` (v281, v305)
  and `v195`'s H-section monkeypatches retargeted to `rllm` (it owns `_router_stream`
  and the router config, so patching through `server` had stopped taking effect).
- **`server.py` split, phase 3b: `evals.py` (JAG-378).** The gold-task eval harness
  (`EVAL_DIR`/`GOLD_PATH`/`EVAL_RESULTS_DIR`, `eval_list_tasks`, `_is_subsequence`,
  `eval_score`, `eval_run`) moved to `evals.py`. It calls the agent loop via a lazy
  `from .server import agent_run` inside `eval_run`, so there is no import cycle.
  `server.py` re-exports the names. `server.py` 4,284 → 4,217 lines. Battery 120/120.
- **`server.py` split, phase 4: `httpapi.py` (JAG-379).** The entire HTTP / JSON
  API layer moved out: the `ThreadingHTTPServer` `Handler`, the bearer-token check
  (`check_auth`/`AUTH_TOKEN`), every `/api/*` route (chat + agent SSE streams
  `chat_stream_gen`/`agent_stream_gen`, sessions, plan/tasks, the context meter
  `context_status`/`context_items`/`context_usage`/`resolve_ctx_model`, manual
  compaction `compact_session`/`_summarize_with_llm`, tools, voice, feed, telemetry,
  the attach/raw-upload routes, static assets, the optional beta Bridge pages) and
  the process entrypoint `main()`. The module is imported at the **bottom** of
  `server.py`, so its `from .server import (...)` resolves against a fully-populated
  module with no import cycle; `server.py` re-exports the 29 names (so `server.Handler`,
  `server.main`, `server._tool_context`, `server._system_prompt`, `server.context_display`
  still resolve — the agent loop calls the latter three). `AUTH_TOKEN` stays the single
  source in `httpapi`; `main()` mirrors it onto `server.AUTH_TOKEN` for the lazy read in
  `selfcheck_payload`. `server.py` 4,217 → 2,582 lines. Battery 120/120 GREEN plus a live
  boot smoke test (`/api/build`, `/api/selfcheck` reporting version + auth, `/api/status`).
  Repointed the source-text guards (27 tests now read `server.py` + `httpapi.py`) and
  `v214`'s summarizer monkeypatch (retargeted to `httpapi`, which owns `compact_session`).
- **`server.py` split, phase 5: `agent.py` (JAG-380).** The agent core moved out — the
  prompt/context assemblers (`system_prompt`, `rules_context`, `self_summary`,
  `self_knowledge`, `context_summary`, `state_block`, `harness_wrap`), the run-graph
  bookkeeping (`start_run_graph`/`finish_run_graph`/`graph_post`), the chat loop
  (`chat_once`, `assemble_turn`, the JSON-action normaliser `_normalize_action`/
  `_term_action` and the pivot/stuck/nudge machinery), the planner (`generate_plan`) and
  the multi-step agent run (`agent_run`, `apply_agent_action`, `_mirror_graph`,
  `_agent_history`) — 72 DEFINES, the harness's whole decision layer. The module is
  imported at the **bottom** of `server.py` (before the `httpapi` import) so its
  `from .server import (...)` resolves against a fully-populated module with no cycle;
  `server.py` re-exports all 72 names.
  Unlike the earlier leaves, this block is the HUB of the test monkeypatches: ~14
  acceptance tests stub `server.stream_with_fallback`, and others stub
  `server._tool_context` / `server._system_prompt` / `server.context_display`, all of which
  the agent core consumes. Rather than retarget every test, the five app-level names the
  agent core does not own — `VERSION` and `stream_with_fallback` (defined in `server`) plus
  `_tool_context` / `_system_prompt` / `context_display` (re-exported from `httpapi`) — are
  now read through the module object (`server.<name>`). Patching `server.X` therefore keeps
  reaching the agent core with **zero test changes** for those monkeypatches; only the 12
  source-text guards were repointed to read `server.py` + `agent.py`. `server.py`
  2,582 → 245 lines. Battery 120/120 GREEN plus a live boot smoke test
  (`trash/smoke379.sh`: `/api/build`, `/api/selfcheck`, `/api/status`). The god-file is now
  a thin façade — imports, constants, `stream_with_fallback` and the re-export blocks.

### Fixed
- **Mobile WebUI: the right side panel was transparent, and the bottom tab bar opened the
  drawer on the WRONG section (JAG-391).** Two independent defects reported together:
  - *Translucent panels.* `aside { background: var(--aside) }` paints BOTH the left
    sessions panel and the right inspector rail, and `--aside` was a translucent
    `rgba(...)` in all six themes — so the chat bled through the rail (the user's
    "Rh side panel is transparent"). The token is now a SOLID colour per theme
    (`#10131f`, `#12151b`, `#e6d6b2`, `#0c1526`, `#221a11`, `#111d16`).
  - *Tabs landing on the wrong section.* `openTab()` called `focusInsp()` BEFORE adding
    `body.show-right`; on a phone the rail is `display:none` until that class arrives, so
    `focusInsp`'s `scrollIntoView()` was a no-op and every tab (tasks/context/feed) opened
    the drawer at its FIRST section (Context) instead of its own. The drawer class is now
    applied FIRST, and `focusInsp` defers the scroll by one frame
    (`requestAnimationFrame`) so the freshly-shown rail has laid out. Live (412×915 touch):
    `openTab('tasks')` now puts `Plan / Tasks` at the rail top (scroll 713, offset 14px),
    `context` likewise; `feed` (the last section) scrolls to the end and is visible.
    Guards in `v368` (E7/E8) and `v352` (L1/L2); battery 125/125.
- **Mobile WebUI: the composer toolbar's buttons overlapped each other (JAG-3xx).** On a
  phone `#composerBar` was forced to `flex-wrap: nowrap`, so the flex algorithm SHRANK
  `.cb-right`; because that group is `justify-content: flex-end`, its buttons spilled
  LEFT over `.cb-left` — measured overlaps `plusBtn↔micBtn`, `qmode↔model-btn`,
  `qmode↔agentBtn`, `model-btn↔agentBtn`. A tap therefore landed on the wrong control:
  `⚡ agent` / `⏹ stop` / `↺ reset` / `⋯` and the bottom tab bar all looked dead. The
  narrow-width toolbar now **wraps** (two tidy rows; the log shrinks first), so every
  control is full-size and tappable; guarded by `v282`. Verified under device emulation
  (412×915, touch): `elementFromPoint` now returns each control itself, the `⋯` opens its
  menu and the `sessions` tab opens the drawer.
- **Mobile WebUI: the editor's file-tree pane and the settings nav could not be resized
  on a phone, and the editor overlay covered the bottom buttons (JAG-3xx).** Three
  touch-unusable spots, all reported from a real phone:
  - the editor dock's two grips (`.ed-resize`, `.ed-tree-resize`) dragged with
    `mousedown`/`mousemove`/`mouseup` only — a finger fires *pointer* events, so on touch
    the file tree stayed stuck at its 210px default (over half the dock) and the dock
    width could not be changed at all. Both now use **pointer events** (with
    `setPointerCapture`) + `touch-action:none`, a wider grip, and a 150px default tree on
    coarse pointers.
  - the settings window's nav was a fixed 190px column with no handle; the window
    drag/resize (`dragify`/`resizify`) was mouse-only, and a position saved on a wide
    desktop could land OFF-SCREEN on a phone. On ≤640px the nav is now a horizontal **top
    tab strip** inside a full-screen window (no left column to fight), the drag/resize use
    pointer events, and the window is clamped into the viewport on open.
  - the editor dock's mobile overlay ran `top:44px -> bottom:0`, so it covered the chat
    composer (send) and the whole `#tabbar` — those buttons looked DEAD because the dock
    received every tap. The overlay now stops between the real header height and the
    bottom chrome (`_headerH` / `_bottomChromeH`), so both stay visible and tappable.
  Verified under Chrome DevTools device emulation (412×915, touch): `elementFromPoint` on
  `send` and on every tab-bar button now returns the button itself, and a synthetic touch
  drag shrinks the file tree (102 → 70). Desktop path re-checked (dock stays a column, nav
  stays a 190px column). `v364`/`v368` assertions updated + extended; battery 121/121.
- **Mobile WebUI: the bottom tab bar only DIMMED the screen, and the sessions panel could
  not be resized (JAG-381).** Two connected defects, both reported from a real phone:
  - the tab bar drove a DEAD mechanism: `openTab()` added `#aside.open` + `#backdrop.show`,
    but the mobile CSS shows the drawer only via `body.show-left #aside` while the base
    `[data-col="sessions"]{display:none}` still won — so the backdrop dimmed the screen and
    NOTHING opened. The tab bar now drives the SAME classes the desktop panel handles use
    (`show-left` for `sessions`; `show-right` for `tasks`/`context`/`feed`, each focusing its
    inspector section); a second tap on the active tab (or `chat` / the backdrop) closes.
  - the drawer's resize grip (gated on `body.show-left`) therefore never appeared either —
    and once shown it was an 8px sliver, too thin for a finger. It is now 16px and centred
    ON the border; an open drawer also ends ABOVE the tab bar (`--sf-bottombar`, published
    from the tab bar's own height) so the nav is never covered, and the bar out-stacks the
    dimmer and the drawers (z-index 18) so every tab stays tappable while a drawer is open.
  Verified live (Chrome DevTools, 412×915 touch): tapping `sessions` opens the drawer
  (`display:flex`, width 260), a synthetic touch drag on the grip resizes it 260→320, all
  five tabs hit-test to themselves with the drawer open, and `tasks`/`context`/`feed` open
  the right inspector. `v368` extended (E1–E6); battery 121/121.
- **Mobile WebUI: the LLM (model) picker was invisible / unusable (JAG-382).** On a phone
  the composer's right group is `nowrap` with `justify-content: flex-end` and the model
  button had `min-width: 0`, so — with mic + model + agent + stop + reset + ⋯ + send wider
  than the row — the group overflowed to the LEFT: at 360px the mic and the model selector
  (and its `▾`) were pushed off-screen; at 412px the model button was squeezed to a ~24px
  sliver, and its 360px popover hung off the left edge. On ≤920px the right group now
  WRAPS, the model label keeps a readable `min-width: 96px`, and the model menu re-anchors
  to the FULL-WIDTH right group (`position: static` on `.model-wrap`) so it always opens
  fully on screen. Verified live (Chrome DevTools, 360 & 412 touch): the model button reads
  its full name (190px), every composer control hit-tests to itself, and the menu opens
  within the viewport (44 entries). `v282` extended; battery 121/121.
- **The LLM's chain-of-thought was silently DROPPED for OpenRouter models (JAG-383).** The
  reasoning delta has no single field name across providers: llama.cpp / vLLM
  (OpenAI-compatible) stream `delta.reasoning_content`, but OpenRouter streams
  `delta.reasoning` (+ a structured `reasoning_details`). `_router_stream` read only
  `reasoning_content`, so every OpenRouter reasoning model — including the A8 Master's
  `deepseek/deepseek-v4.1-flash` — emitted NO thoughts: the live CoT drawer stayed empty
  and the persisted `reasoning` was null ("I can't see thoughts"). The parser now accepts
  both names, in the streaming path AND the non-streaming fallback. A second, latent bug
  surfaced in the fallback: it emitted `rc` via `on_delta` but never appended it to the
  returned `think`, so a fallback turn streamed the reasoning yet persisted
  `reasoning: null`; it now appends before emitting, exactly like the streaming branch.
  Verified live (Chrome DevTools, 412×915 touch): an OpenRouter turn fills the CoT drawer
  (2655 chars) and persists `reasoning` in the session. New `v383` (7/7, transport stubbed
  — OpenRouter `reasoning`, local `reasoning_content`, and the fallback); battery
  121 → 122 (`README` count updated).
- **"The model says it will proceed, then does nothing" — the harness missed a promise that
  was not the first sentence (JAG-384).** Live (session `34e0630510f2`, goal "…non cambiare
  nulla proponi solo"): the model answered "No: … non l'ho ancora provata … / Da ora procedo
  in sola lettura: analizzo e propongo …" and the turn ended `plan.stopped reason=goal_reached`
  with 0 open steps — so the JAG-74 "act, don't announce" nudge never fired and the announced
  work was never done (a background fallback planner then added `todo` nodes a few seconds
  later, which nobody executes — see JAG-308). Root cause: `_PROMISE_RE` was anchored to the
  START of the message, and this promise is the SECOND paragraph, after the actual answer. It
  now matches the verb at ANY sentence/line start too, with a short lead-in ("Da ora procedo",
  "Adesso analizzo", "Then I'll …"), so the harness gets its "last word": it nudges the model
  to call the tool NOW or conclude. Verified deterministically with the exact live reply. New
  `v384` (10/10); battery 122 → 123.
- **The live chain-of-thought was rendered TWICE on mobile (JAG-385).** `_writeThink()`
  wrote every reasoning chunk to BOTH the inline chat block (`ensureThink()`, the
  `🧠 chain-of-thought (live)…` `<details>`) AND the mobile-only `#cotDrawer` strip at the
  bottom of the screen — so on a phone the same monologue scrolled in two places. The
  bottom strip is removed entirely (markup, its CSS, the `@media` `display:block`, the
  `cotFeed()` helper and its call, and the now-dead `cotText` state/closures); the live CoT
  now lives ONLY inline in the chat. Verified live (Chrome DevTools, 412×915 touch): no
  `#cotDrawer` element, `cotFeed`/`cotText` are `undefined`, and a `pushThink`/`flushThink`
  probe lands in exactly ONE inline `.think` block (`msg ai`) with zero bottom strip.
  `v274` extended (3 guards); battery stays 123/123.
- **The `shell` tool ignored an explicit working directory — `cwd` was silently dropped
  (JAG-386).** Reported: a command asked to run in a specific repo started from the SESSION
  workspace instead. The `shell` schema advertised neither `cwd` nor `workspace`, and
  `_shell` only read an UNDOCUMENTED `workspace` key, so the `cwd` the model emitted — the
  very name the `git` tool documents — was ignored, and the chat loop's auto-injected
  session workspace won. `cwd` is now a first-class property of the `shell` schema (mirrors
  `git`), WINS over `workspace`, and is validated up front (a missing dir returns
  `cwd not found` instead of a subprocess traceback). A relative `cwd` resolves against the
  server process cwd, like any shell. A new approval rule mirrors the `fs.*` one: a `cwd`
  OUTSIDE the session workspace escalates to `required` (unless `approvals.mode=full`, which
  is the operator's explicit opt-out). New `v386` (14/14, `sandbox.run` stubbed — schema
  advertises `cwd`, `cwd` reaches the sandbox and beats `workspace`, back-compat, missing
  dir rejected without executing, and the inside/outside/full/relative gate); battery
  123 → 124.
- **Shell `cwd` policy refined into two approval tiers, root-scoped and documented in the UI
  (JAG-387).** Follow-up to JAG-386: the boundary is now BOTH the allowed ROOTS and the
  session workspace — a `cwd` outside every allowed root, or inside a root but outside the
  session workspace, escalates to `required` (never a hard deny), while `approvals.mode=full`
  disables the gate entirely (a `cwd` may then point anywhere). The `shell` tool now declares
  `roots` (same as the `fs.*` tools: `.` + `/home/jagones/Repositories`), and the
  Global-approval-policy card on the approvals/config screen states the rule. `v386` extended
  (17/17) with the root tier, the root-vs-workspace distinction, the `full` bypass, and two
  static guards on the caption; battery stays 124/124.
- **The session workspace now bounds EVERY tool — the `shell` cwd limit was a half-measure
  (JAG-388).** The `cwd` gate (JAG-386/387) only checked the `cwd` PARAMETER, so the model
  could still escape by writing the escape INTO the command: with `shell.approval` set to
  `auto` (and the old `outside_workspace` toggle on `auto`), `cd /fuori && rm -rf x` — and even
  `ls && cd /fuori && rm -rf x`, which rode the auto-approval of the leading `ls` — ran with
  NO approval. There is now ONE rule, in `registry.classify`, applied to EVERY tool that
  names a filesystem path: anything that lands OUTSIDE the session workspace is `required`.
  It covers fs.* / diff (`path`), git (`cwd`) and shell (its `cwd`, any `cd`/`pushd`/`-C`,
  and any absolute / `~` / `..` word in the command). The per-tool `approval: auto` and the
  `outside_workspace` toggle can no longer defeat it — only `approvals.mode=full` (the
  operator's explicit opt-out) relaxes the boundary. System/scratch trees (`/usr`, `/bin`,
  `/lib`, `/dev`, `/proc`, `/sys`, `/tmp`, ...) and the agent's own sandbox stay "inside", so
  ordinary commands (`ls /usr/bin`, `echo x > /tmp/y`) are unaffected; `/etc`, `/root` and
  other repos still escalate. The inert `Outside workspace` toggle was removed from the
  policy card and its caption rewritten. `v386` extended to 22/22; battery stays 124/124.
- **The session list was too tall and truncated the names (JAG-389).** Each row put the
  name BESIDE the badges with the meta below — two lines, and every long name ellipsised
  ("Social Media S…", "Infrastructure…"). The name now sits on its OWN full-width line
  BELOW the badges, while the meta (msgs · age) rides the badge line, pushed right; the
  row is also tightened (`padding` 7→4px, `margin` 4→3px, `line-height` 1.12, smaller team
  chips). Measured in the live drawer: **44px per row, down from 53px**, and the names are
  no longer clipped. `v352` extended (D3/D4); battery stays 124/124.
- **A tool request answered in the model's NATIVE markup was silently dropped,
  freezing the turn (JAG-369).** The A8 "Master" agent runs on
  `openrouter:deepseek/deepseek-v4.1-flash`, which — with no `tools` array on the wire
  (Longrun's protocol is text-based JSON actions) — replies to a tool request with
  DeepSeek's native tool-call markup: an envelope carrying the marker `DSML` wrapped in
  full-width vertical bars (U+FF5C), holding an `invoke name="X"` with `parameter
  name="Y"` children. `extract_json` found no JSON and `_looks_like_json_action` was
  False (the text does not start with `{`/`[`), so the call was silently dropped and the
  harness looped forever on "no valid action" — the model re-emitted the same markup
  every turn and one raw markup message leaked into the visible chat (observed live: the
  user typed "?"). The harness now recognises the dialect: `_dsml_action` parses the
  first invocation into `{"action":"tool","tool":<name>,"args":{...}}` (a
  `string="false"` parameter is JSON-decoded). The JSON→DSML pipeline is factored into
  `_extract_action(answer)`: `extract_json` returns an EMPTY LIST/DICT on failure (not
  `None`), so the fallback uses a **falsy** check, not `is None` — a first attempt with
  `if act is None:` silently skipped the fallback (caught by a live WebUI test).
  `_looks_like_json_action` treats the markup as machine text so it is never shown as a
  reply. Verified against the real session: all stored DSML messages parse to their
  `shell` calls. Guarded by `tests/acceptance/v369_dsml_tool_calls.py` (17/17, including a
  brace-carrying DSML sample that reproduces the falsy-check trap). Battery 120 → 121.
- **Determinism of the regression battery.** Four acceptance tests awaited async
  side-effects with fixed `time.sleep()` calls (v204 memory TTL, v222 concurrent
  late-write, v281 terminal output, v287 routine dispatch) — wall-clock races that
  can fail under load. They now poll the real condition with a bounded timeout, or
  order the threads with an `Event`, so the outcome is deterministic.
- **`fs.read` returned an EMPTY observation — silently, harness-wide.** `tools.observation()`
  rendered `stdout`/`stderr`/`path` but never `content`, and `fs.read` returns its payload
  in `content`. So every `fs.read` (and the "read more with fs.read" offload files the
  harness tells the agent to open) reached the model BLANK, with `exit=0` and no error.
  This is the root cause of the "coder 1" job that could not proceed: it was blind to the
  skill's device-fallback procedure and to the source it was editing. Content is now
  rendered (bounded by the budget); guarded by `tests/acceptance/v346_fs_read_observation.py`.
  Battery 105 → 106.
- **Generalised: no tool may answer the model with nothing.** The same renderer also
  dropped the payload of `fs.write`/`fs.edit` (counters), `self` (its whole self-knowledge
  dict — a tool whose entire purpose is to guide the agent) and `improve`/`reconcile`.
  `observation()` now renders `stdout`/`stderr`/`content`/`path`, then an explicit
  `observation` string, and finally a JSON fallback of the remaining fields. The
  operator-facing `tool.result` events now also fall back to `content`, so file reads are
  no longer blank in the tool cards/feed. `self` reports the LIVE version (was stale
  `0.5.0`). Guarded by `tests/acceptance/v347_observation_payload.py`. Battery 106 → 107.
- **Job dependencies can no longer deadlock (open loop).** A job `blocked_by` a job that
  ended `partial` — a normal outcome when one worker failed — was neither released nor
  failed, so it stayed `blocked` forever. `_blockers_state` now treats any terminal
  blocker that is not `done` (`partial`/`error`) as a FAILED dependency, and `reconcile()`
  now sweeps (`wake()`) the dependents of a restart-killed job instead of leaving them
  blocked. Guarded by `tests/acceptance/v348_job_dep_no_deadlock.py`. Battery 107 → 108.
- **The agent loop (`/api/agent/run`) never saw its own steps (open loop).** It rebuilt
  its messages from scratch every iteration and injected only the task list, dropping every
  observation. The model could not use a subagent's result nor correct a rejected action
  (`unknown action` / `task not found`), so it re-derived the same mistake and could spin —
  the failure JAG-61 fixed in the chat loop but never here. The turn now carries the recent
  `(action -> observation)` history (`_agent_history`). Guarded by
  `tests/acceptance/v349_agent_loop_history.py`. Battery 108 → 109.
- **The coordinator could not look into a teammate's session (SEVERE).** Told
  "coder 1 is failing a lot — understand why and help him", the Master had NO way to
  see that teammate's chat: no DISCOVERY (which session is "coder 1"?) and no readable
  transcript (the raw `data/sessions/<id>.json` is unusable in context). Guiding the
  agent is the harness's whole point, so this was a first-class gap. New read-only
  `sessions` tool: `action=list` maps sessions to agent names, `action=read` renders
  the full transcript (messages + every tool call/result + harness injections,
  time-ordered). The delegation record now also carries each teammate's session id
  and points the master at the tool. Guarded by
  `tests/acceptance/v350_session_inspect.py`. Battery 109 → 110.
- **The Android build/deploy skill steered the agent into failure (SEVERE).** The
  Jago team could not finish, and it was the harness's *guidance*, not the agent or
  the infra: `android-app-build-deploy` step 3 prescribed `compileSdk = 36`, but its
  own reference (`build-on-arm64.md`) proves the ARM64 Debian aapt2 (`2.19`) cannot
  parse `android-35/36` → the build dies. And step 1 told the agent to *read* the ADB
  port from `adb devices -l` (empty on the DGX) or from the PC — never to run the
  trivial, working `adb connect oneplus-15r:5555`. Verified: `adb` over Tailscale
  works from the DGX (connected, phone authorized) yet **0 `adb connect` executions**
  exist across ALL sessions, so "install on device" could never succeed. Both steps
  now lead with the working DGX path (direct `adb connect` + the ARM64 `compileSdk 34`
  rule). Guarded by `tests/acceptance/v351_android_skill_adb.py`. Battery 110 → 111.
- **Chat file links often did nothing (JAG-354).** The reply linkifier only matched
  ABSOLUTE paths (`/…`, `~/…`), so the relative paths and bare filenames agents actually
  emit (`viz/trend.png`, `insights.md`, `README.md`) stayed plain text — and even when a
  link was made, `GET /api/fs/read` / `/api/fs/raw` resolved a relative `?path=` against
  the server CWD instead of the session workspace. Both ends fixed: the pattern now
  matches absolute, relative AND bare paths (code extensions included, so a generated
  script opens in the editor too), and the fs endpoints resolve a relative path against
  the session workspace first. The image preview now carries the session, so relative
  images open as well. Guarded by `tests/acceptance/v354_ui_links_pins.py`. Battery 112 → 113.
- **Sand and Sepia were effectively the SAME theme (JAG-355).** Both were near-white warm
  papers (`--bg #e7d9bd` vs `#e6dcc4`), so switching between them changed almost nothing —
  and Sand was still too bright to be an eye-saver. Sand is now a genuine low-luminance cream
  (`#d9c49c`) and Sepia is a **dark** warm amber (`#17120c`); they are now unmistakably
  different. `Sand` remains the only light theme.
- **The panel-collapse arrows pointed the wrong way and the resize grip could steal the
  press (JAG-356).** The arrows now follow the intended semantics — left panel `◀` open /
  `▶` closed, right panel `▶` open / `◀` closed — and the handle takes precedence over the
  column resize grip on the same border (z-index 30 + a `mousedown` guard), so pressing the
  arrow is always a click, never a drag.
- **"Bolder text" did almost nothing (JAG-356).** It only bumped a handful of nodes by 100.
  It is now a real, app-wide weight (body `600` cascades to panels, chat, inputs) with the
  chat bubble forced, so answers visibly change.
- **Removed the redundant Bridge refresh button (JAG-356).** The deck already polls every 5s
  (and a browser reload covers the rest), so the manual button added nothing.
- **Stripped the instructional prose from the GUI (JAG-356).** The multi-sentence "how to"
  paragraphs in the panels and sub-windows (Plan/Tasks, MCP, Models, Keys, Terminal, Memory,
  Browser, the new-session dialog, the tool-policy legend) are gone — the UI is now
  self-explanatory. The **Harness** settings tab keeps its full explanations, by request.
- **Models: an empty provider kind no longer persists as `""`** (falls back to `openai`).
- **The panel handles drifted off their border (JAG-357).** The app scales the page with CSS
  `zoom` on `<html>` (JAG-283); a fixed element's `left` is multiplied by that zoom while a
  panel's rect is already scaled, so the handle landed ~15% past the edge — and it only
  re-positioned on a *window* resize, so dragging the panel border left it behind. The
  position is now divided by the live zoom, recomputed during the resize drag, on a
  `ResizeObserver` of both panels, and whenever the zoom changes. Verified live: handle
  centre == panel border at rest, mid-drag and after the drag.
- **Collapsing the left panel now shows the active session name in the topbar (JAG-357)** —
  you hide the *panel*, never which session you are in. A collapsed panel also drops its
  resize grip so it cannot sit under the re-open handle.
- **The left arrow was dead at narrow widths (JAG-358).** Two bugs stacked: the drawer CSS
  lived in `@media (max-width: 820px)` while the arrow tested `<= 900`, so between 821–900
  it toggled a class with **no CSS at all**; and the drawer selector used a bare attribute
  (`body.show-left [data-col="sessions"]`), which *loses to the ID rule* `#aside { transform:
  translateX(105%) }`, so even ≤820 the panel never slid in. The CSS now covers `<= 900` and
  targets `#aside`, and the arrow's thresholds match the CSS exactly (sessions 900,
  inspector 1100). Verified live: the drawer opens/closes and the handle lands on its border.
- **Handles could still detach (JAG-358).** Placement trusted `getComputedStyle().zoom`,
  which engines disagree on, and a panel parked off-screen by a `transform` was counted as
  *shown* — flinging its handle past the edge. Placement now calibrates the real scale with a
  one-off probe, treats an element outside the viewport as hidden, and re-glues within a few
  animation frames after any toggle/resize/transition (`_settleHandles`).
- **"Bolder text" off still looked bold (JAG-358).** Many chrome labels ship at `600` in the
  base sheet, so the OFF state was indistinguishable from ON. The OFF state now resets those
  labels to a normal weight, so the switch changes the whole app (chat + labels) both ways.
- **The theme stopped at the app shell (JAG-359).** The Settings window and every popup
  (`#modelMenu`, the folder picker, the skill/diff/mcp windows) were pinned to the indigo dark
  surface (`#0f1320`) and the Harness/Tool-policy cards to raw slate hexes (`#1e293b`), so
  switching to Sand or Sepia left them navy. They now paint with the theme tokens
  (`var(--menubg)` / `--panel` / `--line-2` / `--chipbg`), so the settings panel follows the theme.
- **The topbar read like debug output (JAG-359).** `ctx 41k/127k · 32%` and
  `sandbox: none (by config)` are gone: the context load is now a tiny ring + `%` and the
  sandbox a coloured status dot + one short word, with the full detail moved into the tooltip.
  The context indicator turns **red from 70%** up.
- **Zooming left a gap at the bottom of the screen (JAG-359).** `100dvh` is an absolute unit,
  so the CSS `zoom` on `<html>` scaled it and the shell only covered `zoom × viewport` (~15%
  gap at 0.85, worse zoomed out, and overflow when zoomed in). The body height is now
  `calc(100dvh / var(--zoom))` and `applyZoom` publishes `--zoom`, so the shell fills the real
  viewport at every level (verified: body == viewport at 0.7 / 0.85 / 1.3 / 1.0).

- **The theme STILL stopped at a few surfaces (JAG-360).** After the settings window itself was
  themed, the MCP JSON textarea stayed near-black (`#0b0f18`), the toasts + the session menu
  stayed dark gray (`rgba(24,28,40,.97)`), and ~25 hover/active/chip fills kept the indigo blue
  (`rgba(108,140,255,…)` / `rgba(120,140,255,…)` / `rgba(139,123,240,…)`) — including the
  scrollbar thumb. They all resolve through theme tokens now (`--panel2` / `--menubg` /
  `--hover` / `--sel` / `--hl` / `--chipbg` / `--scroll`), so switching to Sand or Sepia
  re-paints the WHOLE UI.
- **The panel arrow was unreliable (JAG-360).** The toggle fired on the native `click`, which a
  press-and-hold, a 1-2 px wobble, or the resize grip sharing the same border could all
  swallow. It now toggles on POINTER UP with an ≤8px movement guard and a pointer capture, so a
  hold is exactly one click and small movements never cancel it.
- **Widening a side panel crushed the chat (JAG-360).** The panels were `flex: 0 0 <w>` (never
  shrink) with their width persisted to localStorage — a saved `618 + 773` in a ~1200px window
  squeezed the centre column to a sliver (hence the wrapped composer). The panels are now
  `flex: 0 1 <w>` with a 150px floor, the centre column has a hard `min-width: 420px`, and the
  drag + save maths run in CSS px, so a wide panel (or a narrow window) can no longer starve
  the chat.
- **Defaults (JAG-360):** the theme is indigo and bolder text is OFF out of the box.

- **The side rail could no longer edit the rules (JAG-361).** The editable Rules panel lived
  only in Settings, while the side rail had a Role-only pane with no file paths. There is now
  ONE complete **Rules** section: the per-session role, the GLOBAL
  `~/.config/longrun/RULES.md` and the PROJECT `<ws>/.longrun/RULES.md`, each with its
  real absolute path, the `AGENTS.md` addenda that are ALSO loaded, and an in-place editor +
  save. (`loadRole()` is kept as an alias so every call site still works.)
- **Cost was only ever an estimate (JAG-361).** When the provider reports the charge itself it
  is now used verbatim — OpenRouter returns the billed USD in `usage.cost` (with a
  `cost_details` breakdown), so no arithmetic is involved (`src: "provider"`). Otherwise the
  REAL token counts are priced with the full rate set: the cache-read rate for cached tokens
  (instead of the full input rate) plus the fixed per-request fee. Each row states which it is
  (the UI prefixes an estimate with `≈`, the panel header says "exact" / "estimated").
- **Touching a panel's inner border shrank it (JAG-361).** The panels had become `flex: 0 1`
  while the chat's `flex-basis: auto` still ate the free space, so the first pixel of a drag
  redistributed a few px. The panels are fixed-width again and an explicit budget clamp
  (`_panelRoom` / `_fitPanels`, chat floor 420px) protects the centre column instead: verified
  a +20px drag moves the panel exactly 20px and a huge drag stops at the 420px floor.
- **Duplicate `id="ctxPct"` (JAG-361).** The topbar element added in JAG-359 shadowed the
  inspector's meter (`getElementById` returns the first), so the inspector % never updated. The
  topbar one is now `#ctxPctTop`; the inspector reads its real percentage again.
- **Interface polish (JAG-361):** a hidden `#nowbar` no longer keeps rendering; the
  pick / paste-text / voice-help / skill / diff modals get the same border + radius + shadow as
  the rest of the app; `a.ghost` is actually styled; buttons gain a hover and a real disabled
  state; the dot-rail restores its focus ring; the undefined `--line2` token (which killed the
  session-menu border) is fixed; `#qmode` no longer forces a dark native popup on light themes;
  and the hardcoded light-blue id labels use `--acc2`.

- **Every agent looked identical to the model (JAG-362).** The `agent-role` prompt section only
  rendered the per-session `ROLE.md`, so the ~90% of agents with no ROLE.md yet contributed
  **nothing** and their own roster name/label never reached the prompt at all (33 agents, 3 role
  files — the other 30 were a void, which is why "role.md equal for all agents"). The section now
  always announces the agent identity (`You are A7 — coder (coding agent).`) and appends the
  ROLE.md when it is set. The three role-ish things are one story now: the roster `role` is a
  short **label** (UI only, never the prompt), the session `ROLE.md` **is** this prompt section,
  and the standing `RULES.md` (global + project) is the section right below it.
- **You can now see WHICH agent you are and WHERE its text comes from (JAG-362).** The Rules
  panel gained an identity line — `A7 · coder · coding agent — agent identity (roster); the role
  text below is this agent's ROLE.md`, or "ad-hoc session" when the session is not designated.
- **A long-lived tab could hide a GUI fix silently (JAG-362).** A cheap `GET /api/build`
  fingerprint is polled (at boot, every 60s, and on focus/visibility); when the served app
  changes, the tab reloads itself, so a fix is never buried behind a tab opened hours ago.
- **The topbar chips now read like the rest of the UI (JAG-362).** The sandbox pill says what it
  means — `sandboxed` / `no sandbox`, with the backend and the requested mode in the tooltip —
  and the ctx `%` is a ring + label matching the other header chips.

- **Clicking a panel's border shifted the panel (JAG-363).** The resize strip started resizing on
  the raw `mousedown`, so the 1–3px of pointer travel that any physical click carries became a
  1–3px panel move (and a press-and-hold did the same). The resize now engages only once the
  pointer really travels (**> 4px**), and it maps the full delta from there — so a click or a hold
  is a dead no-op, a drag tracks the cursor exactly (verified live: click 0px, 2px wobble 0px,
  drag +10/+30/−10 = exactly +10/+30/−10), and a plain click no longer persists a width.

- **A queued message now shows its attachments (JAG-364).** A message typed while a turn is
  running is queued as `{raw, text, atts}`, and the queue chip shows the text you typed plus a
  marker for what it carries — `🖼 2 images · 📄 1 file · 📝 1 text` — instead of the raw blob
  (skipping the model-only attachment block). Steering and flushing send the raw payload but
  display the human text.
- **A theme sets the TEXT colours, not just the background (JAG-364).** Each theme card now
  previews its own text colour (`Aa`) and accent on the swatch, and the text/colour surfaces
  that were hardcoded are token-driven now: the code blocks and inline code in a reply, the todo
  statuses, the session running/done rings, the queue-dropdown options, and the ghost/copy hover
  borders — all follow the active theme (Sand included).
- **Chat links to a SIBLING project now open (JAG-364).** A relative link like
  `sparkpulse-server/status_server.py` failed with "not a file" because it was only resolved
  inside the session workspace (`Repositories/TESTS/Jago`). `_resolve_fs_arg` now resolves a
  relative path against the workspace **and each of its ancestors** that stays inside a browse
  root (bounded to 12 levels), so a link to a sibling project under `Repositories/` resolves to
  the real file. Verified live: the link opened `/home/jagones/Repositories/sparkpulse-server/status_server.py`.
- **The context breakdown is a list of horizontal bars (JAG-364).** Instead of a wrapping legend
  of words, each category is now a horizontal bar coloured exactly like its donut segment, sorted
  big → small, with a short label (`sys instr`, `tool out`, `harness`, …) so the bars get the
  width; the full label, token count and % stay in the tooltip. The donut is kept above it.

- **The Bridge agent prompts were VOID — now filled from `agency-agents` (JAG-365).** The roster
  was seeded from the local `agency-agents` clone, but the seed stored only the short LABEL
  (`agents.json.role`); the agent's role PROMPT (the clone's `.md` body) was never written, so the
  Bridge `✎ prompt` editor AND the main-app ROLE.md opened empty for all 30 seeded agents. The new
  `longrun.agency` module reads the clone and `scripts/seed_agent_roles.py` materialises each
  agent's body into `data/roles/<session>.md` — the SAME file both UIs read, so the Bridge prompt
  and the main-app ROLE.md are now identical. `scripts/seed_teams.py` calls it after seeding, so a
  seeded agent is never left without its role. Non-destructive: only an EMPTY role is filled
  (`--force` overwrites), so a role you wrote is never clobbered. Applied live: **30 roles filled**
  (the 3 custom agents — Master, coder 1/2 — kept their own).

- **The context PREVIEW understated the system prompt by thousands of tokens (JAG-366).** The
  dry-run `context_engine.preview()` sized its budget, compaction and "messages that fit" maths
  against the legacy monolithic `server.SYSTEM_PROMPT` (~64 tokens) instead of the REAL
  section-registry prompt that `assemble_turn()` sends. The preview therefore LIED about what
  would be sent. `preview()` now calls `server._system_prompt(sess)` (with a dry-run fallback
  that can never raise) and reports `system_prompt_tokens`.
- **The WebUI overflowed on a phone — the JS read a stale `window.innerWidth` (JAG-366).** The
  app's overlay thresholds (`_overlayLeft`/`_overlayRight` and the "is this panel shown" test) and
  the editor dock's overlay decision + both drag clamps read `window.innerWidth`, which can be
  stale under device emulation / the visual viewport / zoom, while the CSS media queries use the
  LAYOUT viewport (`document.documentElement.clientWidth`). Emulated at 390×844 the `#editorDock`
  stayed ~1039px wide and the page scrolled sideways (scrollWidth 1438 vs clientWidth 390). Both
  `webui/index.html` and `webui/assets/editor.js` now resolve the viewport through a shared
  `_vw() = document.documentElement.clientWidth || window.innerWidth`, so the JS thresholds and
  the CSS overlays can never disagree. The `width=device-width, initial-scale=1,
  viewport-fit=cover` meta is asserted as well.
- **The Bridge agent prompt was VOID while the primary UI showed the same ROLE.md (JAG-367).**
  In the Bridge (`/orbit`) the `✎ prompt` box opened EMPTY even though the SAME `ROLE.md` the
  primary Inspector § Role shows had content (the JAG-365 backfill). Root cause: the box loads the
  role ASYNC, but `render()`'s anti-poll dirty-guard — added to protect an in-progress edit from
  the 5 s table refresh — ALSO blocked the LOAD render: the textarea still held `""` while
  `openText` became the fetched text, so `roleDirty` was true and the box was never filled. JAG-365
  merely EXPOSED this latent race (before it, the fetched text was `""` too, so nothing diverged).
  The fetched role is now written straight into the textarea (with an `open !== sid` guard against
  a stale response). Verified live on the Bridge: the editor shows the EXACT ROLE.md (e.g. 15 455
  chars == the API response), i.e. the Bridge prompt and the primary UI are finally identical.
- **On a phone the WebUI clipped its right edge (JAG-367).** The desktop
  `[data-col="chat"] { min-width: 420px }` floor forced the page wider than the screen — measured
  on the REAL Pixel 8: visual viewport 363 px but the layout was forced to 420 px — and
  `body{overflow-x:hidden}` then CUT the right edge (the send button and the 5th tab were partly
  unreachable). A `@media (max-width: 900px) { [data-col="chat"] { min-width: 0; } }` override now
  drops that floor. It sits AFTER the base rule on purpose: same specificity, so source order is
  what lets it win (the first attempt put it in the earlier `max-width:900` block and lost).
  Verified on the device via CDP: `scrollWidth == clientWidth == 363`, the send button and all five
  tabs (`chat/sessions/tasks/context/feed`) now fully visible.
- **The side panels could not be resized on a phone — nor at the border's centre on desktop
  (JAG-368).** Two independent causes: (a) the border grip listened to MOUSE events only, so a
  finger (touch) did nothing; and (b) the circular collapse handle is centred ON the border and its
  `mousedown` called `stopPropagation()`, so pressing the border at its vertical centre was swallowed
  by the handle — which then toggled the panel — and the border never moved. On a narrow layout the
  panels are also fixed DRAWERS whose grips were `display:none`, so there was nothing to grab at all.
  Now: the grip runs on POINTER events (mouse / finger / pen) with `touch-action:none` and captures
  the pointer; it carries `position:relative; z-index:31` so it out-stacks the handle (30) and is the
  hit target across its whole band — verified with `elementFromPoint` that the 5 px border wins at
  every y, including the handle's centre; and a fixed DRAWER gets its own grip glued to its inner edge
  (`positionDrawerResizers`) that resizes the drawer through a CSS var (`--drawer-w-left` /
  `--drawer-w-right`) with its own persisted size (key `_d`). The panel clamps also now account for
  the open editor dock (`_dockRoomW`), and opening/closing the dock re-fits the panels so the row can
  never stay over-constrained (which is how a border ends up off-screen and undraggable).
- **Dragging the editor's left edge shoved the inspector off-screen (JAG-369).** The editor dock is a
  `flex: 0 0 auto` column, so the flex algorithm never shrinks it; once the chat column hit its 420 px
  floor, widening the dock past the room the two side panels + the chat floor leave over-constrained
  the row, which overflowed to the RIGHT and pushed `#rail` out of the viewport — the inspector was
  clipped away, as if it had vanished. Only the collapse arrows may hide a panel; a resize must not.
  Now the app exports `window._dockMaxW()` (the mirror of `_panelRoom()`, from the dock's side) and the
  dock's drag/restore is capped by it (`editor.js`), the fit maths also caps an already-too-wide dock
  so ANY re-fit (window resize, zoom, dock open) heals it, and releasing the drag re-fits the panels.
  Verified live at a 1267 px viewport: a persisted 848 px dock is clamped to 320 and the inspector
  returns to `ctxRight == vw`; dragging the grip to `clientX:-800` leaves `ctxRight == vw` (on-screen).

### Added
- **`src/README.md` (JAG-370)** — states plainly which tree ships: `src/longrun/`
  is the application (what `run.sh` / `python3 server.py` import and what `tests/`
  exercise); the sibling `src2/` is the optional, detachable Bridge beta.
- **`tests/acceptance/v368_panel_resize.py` (16 checks)** — the border grip runs on pointer
  events (mouse/finger/pen), carries `touch-action:none` and out-stacks the collapse handle; a
  fixed DRAWER is resized through a CSS var with a grip glued to its inner edge and its own
  persisted size; a drawer is not treated as a layout column by the fit maths; the panel
  clamps account for the open editor dock while opening/closing the dock re-fits the panels;
  and (JAG-369) the app caps the dock by the room the panels + chat floor leave, the dock drag
  is bounded by that cap, the release re-fits the panels, a restored width is clamped, and the
  fit maths self-heals an already-too-wide dock.
  Battery 119 → 120 (the README badge/one-liner were updated to match).
- **`src/longrun/agency.py` + `scripts/seed_agent_roles.py` (JAG-365)** — map an org agent
  NAME to its role prompt in the local `agency-agents` clone (`by_name`, `role_for`,
  `fill_roles`) and backfill `data/roles/<sid>.md`, non-destructively. `v341_team_seed` grew four
  checks (Q1–Q4) to lock the materialised role + the no-clobber guarantee. Battery stays 119.
- **`tests/acceptance/v364_queue_theme_links_ctx.py` (28 checks)** — a queued message carries its
  attachments and the chip shows the text + a marker (not the raw blob); every theme previews its
  text + accent colour and no hardcoded status text colour survives; `_resolve_fs_arg` walks the
  workspace ancestors so a SIBLING-project link resolves (with a real temp-dir check that a
  workspace-local path still wins and a missing path falls back); the context breakdown is sorted
  horizontal bars with short labels (the donut is kept); and (E1–E4) the app + editor dock resolve
  the viewport through `document.documentElement.clientWidth`, the viewport meta is mobile-ready,
  and on a phone the chat column drops its desktop 420 px floor (no right-edge clip).
  Battery 118 → 119. (`v354_ui_links_pins` gained B7: the preview reports the REAL system prompt;
  `v292_roles` gained two checks: the Orbit prompt editor writes the fetched ROLE.md into the
  textarea and no longer depends on a re-render the poll guard can block.)
- **`tests/acceptance/v362_agent_identity.py` (12 checks)** — every designated agent announces
  its roster identity in the `agent-role` prompt section even with no ROLE.md (and two agents
  get DIFFERENT sections), the ROLE.md is appended under the identity, a plain session still
  contributes nothing, the Rules panel states the agent identity (with the "ad-hoc session"
  fallback), the server exposes the `/api/build` fingerprint the SPA self-reloads on, and the
  sandbox pill says what it means. Battery 117 → 118.
- **`tests/acceptance/v361_rules_cost_polish.py` (16 checks)** — the single complete Rules
  panel (sources + paths + the right backend per scope), the exact-vs-estimated cost path
  (provider cost verbatim, cache-read rate + per-request fee, unknown stays null), the richer
  price cache, the `#ctxPct` duplicate-id fix and the polish guards. Battery 116 → 117.
- **`tests/acceptance/v360_shell_fixes.py` (14 checks)** — no indigo literal survives
  (`#0b0f18` / `rgba(24,28,40` / the blue tints), the settings + popups + MCP textarea +
  scrollbars resolve through theme tokens, the handle toggles on pointer-up with a movement
  guard (no native `onclick`), the chat keeps its `min-width: 420px` while the panels stay
  shrinkable, and the defaults are indigo + no bolder text. Battery 115 → 116.
- **`tests/acceptance/v352_appearance_theme.py` extended to 38 checks** — the six themes, the
  flipped edge-handle arrows, the resize-grip guard, the app-wide bolder text (and its OFF
  baseline), that the panels stay free of instructional prose while the Harness tab keeps it,
  and (K1–K7) that the handles re-glue on resize and on zoom, a collapsed panel drops its
  grip, an off-screen panel is not treated as shown, the toggle thresholds match the CSS
  overlays, and the topbar carries the active session name both when the panel is collapsed
  and when it is parked off screen. Battery stays 114 (an existing file grew, no new file).
- **`tests/acceptance/v359_theme_shell.py` (13 checks)** — every popup paints with a theme
  token (none left on `#0f1320`/`#1e293b`), the topbar ctx/sandbox indicators are the ring +
  status-dot graphics with the 70% red threshold, and the shell height is divided by the live
  zoom. Battery 114 → 115 (a new file).
- **Live cost panel (JAG-355).** The harness already captures the provider's REAL `usage`
  per call; new `costs.py` prices each call (USD per 1M, `[input, output]`) and keeps a
  per-session ledger (`data/costs/<session>.json`), surfaced in a new right-panel **Cost**
  section: session total, tokens in/out, and **one row per API call** (model, time, tokens,
  $), pushed live on a `cost.usage` SSE event so it updates mid-run. Prices come from
  `LONGRUN_PRICES`, `config/prices.yaml` (or `config/prices.json`), or the `↻ prices`
  button, which pulls OpenRouter's PUBLIC model catalogue (no key needed) into
  `data/prices.json`. An unpriced model (e.g. a local GGUF) reports `usd: null` — never a
  fake zero. Verified live: a chat turn wrote 3 priced-shape call records (with cached
  tokens) for the local model, correctly `usd: null`. Routes: `GET /api/costs`,
  `POST /api/costs/refresh`, `POST /api/costs/reset`. Guarded by
  `tests/acceptance/v355_themes_donut_costs.py`. Battery 113 → 114.
- **Six eye-saver themes, all differentiated.** Indigo · Dark · Midnight · **Forest** (deep
  muted green) · Sand (low-luminance cream) · Sepia (dark warm amber) — WebUI **and** Bridge.
- **Context donut.** The token breakdown is now an SVG donut (part-to-whole, centre = total
  tokens) with a compact single-column legend, replacing the 8-px stacked micro-bar and its
  wrapping 12-row legend.
- **`tests/acceptance/v355_themes_donut_costs.py`** — the cost-ledger math + refresh parser +
  the donut/theme/cost static guards. Battery 113 → 114.
- **`tests/acceptance/v354_ui_links_pins.py`** — chat file links (relative/external), the pin
  marker, and that compaction never drops the todo list. Battery 112 → 113.
- **Pinned sessions are marked in the rail (JAG-354).** A pinned session (already sorted
  to the top) now shows a 📌 marker and a heavier title in the left panel, so the pin is
  visible without opening the session menu.
- **Accurate positioning + dependency honesty (JAG-354).** The README no longer frames
  Longrun as "not a meta-harness" (a meta-harness collects *other* harnesses; Longrun
  is ONE harness whose own sessions are the agents you organise into teams and an org
  chart). The dependency claim is now truthful: the core is stdlib-only, with **PyYAML**
  (pure-Python) as the single third-party import — required only to read the shipped
  `config/*.yaml`, and the tool allowlist stays fail-closed if it is missing.
- **`sessions` tool** (read-only): let any agent — above all the coordinator — inspect
  another session's transcript to understand why a teammate is failing and help it.
  Wired in `registry.TOOL_SCHEMAS` + `tools.py`, enabled in `config/tools.yaml`.
- **`tests/acceptance/v351_android_skill_adb.py`** — a guard that the Android
  build/deploy skill keeps the working DGX→phone ADB guidance (a direct
  `adb connect oneplus-15r:5555`) and the ARM64 `compileSdk 34` rule.
- **Appearance settings (WebUI).** A new Settings → **Appearance** panel with three
  themes — **Indigo** (the house blue/purple), **Dark** (neutral graphite) and
  **Sabbia** (warm Egyptian sand & ochre) — applied pre-paint (no flash) and saved per
  device, plus a **Bolder text** preference. The whole surface is token-driven (panels,
  sidebars, popovers, tinted hovers, scrollbars, ambient gradients), so each theme is
  coherent rather than a background swap. Guarded by
  `tests/acceptance/v352_appearance_theme.py`.
- **Compaction model in the chat model menu.** The topbar `model ▾` picker now carries a
  `⛭ compaction` row: click it to switch the list into *compaction mode* and pin the model
  that summarizes/compacts the transcript (the `summarizer` role, via `POST /api/routing`).
  The same control remains under Settings → Models.
- **Five eye-saver themes, English-named, applied app-wide.** Indigo · Dark · Midnight ·
  Sand · Sepia. `Sand` is now a genuine warm cream (was near-white and too luminous); the
  two new ones are `Midnight` (deep blue-black) and `Sepia` (muted paper). The **Bridge**
  deck (formerly “Orbit”) reads the same per-device choice and is themed too — its hardcoded
  dark bits (background, header, constellation fills/links/labels) are now token-driven.
- **Minimal chrome, border handles.** The two topbar “hide panel” icons are gone; each
  panel now collapses from a **circular arrow handle on its own inner border** (left panel
  ▶ open / ◀ closed, right panel ◀ open / ▶ closed), positioned from the panel rect and
  preserved across resize + the mobile off-canvas behaviour. The composer bar is
  token-driven, so its toolbar text is legible on the light themes.
- **The beta deck is renamed “Bridge”.** “Orbit” made no sense for a mission-control deck;
  the label, the page title/`<h1>` and the API fallback page all read **Bridge** (the route
  `/orbit` is unchanged for link stability).
- **`tests/acceptance/v345_json_extract_props.py`** — a stdlib, seeded property gate
  for `server.extract_json` (400 randomized wrapped values + edge cases + malformed
  input). This closes a real coverage gap: `extract_json` previously had no runnable
  test — its only guard was `tests/properties/test_pure_logic.py`, which needs an
  uninstalled `hypothesis` and never ran. Battery: 104 → 105.

## [1.0.0] — 2026-10-07

The first tagged release. Longrun is a local-first, stdlib-only agent harness that
**drives one LLM hard** and then runs **its own sessions as a team of agents**. It is a
single harness — not a meta-harness: every agent is one of its sessions, a full harness
instance with its own tools, skills, plan, memory and transcript.

### Added
- **TEAMS — the fifth object level.** A first-class object model:
  `Team (TN) → Job (JN) → Subjob (JN.j) → Agent (AX) → Todo (AX.nY)`. Teams own their
  roster; agents never own membership, so the two can't drift.
- **Meta-agent orchestration.** A coordinator decomposes a goal into per-teammate
  subjobs, enforces declared `(after AX)` dependencies as real dependency waves, and
  synthesises the team report into the final deliverable.
- **Plan-only coordinator turn (read-only).** The master's planning turn keeps a tight
  tool budget, never enters the completion loop, and may only *inspect* (`fs.read`,
  `skills`, `memory`, `self`) — it cannot execute the team's work, so it can't bypass it.
- **Orbit mission-control deck** (`/orbit`): org chart, live constellation, job
  create/dispatch, a whole-board team selector, and a per-team model policy button —
  single-column, mobile-style.
- **Per-team model policy.** At most **one local model per machine**; the remaining
  agents use cheap cloud models, and the strongest (still cheap) cloud model goes to the
  leads. Enforced on every model set.
- **Team seeding from an org chart** (`scripts/seed_teams.py`) with a model policy flag.
- **Bounded retry + escalation for workers.** A worker that reports `STATUS: BLOCKED`
  is retried a bounded number of times, then marked **failed**; the subjob is failed, the
  job becomes **partial**, and the coordinator is explicitly told which subjobs are
  unfinished so it cannot claim success.

### Changed
- Subjob **assignment text is now per-agent** (the most specific plan line), instead of
  an aggregate "critical path" line that was handed to every worker.
- Orbit board is a single column with a natively-scrolling org chart (no scroll/pan fight).

### Fixed
- Todo ids across the UI are `AX.nY` (the `T` namespace belongs to teams).
- Orbit constellation node labels no longer render the obsolete `AX.TY`.

### Quality
- Deterministic regression **battery: 104/104 GREEN**; CI runs it on every push/PR.

---

Earlier internal milestones (v0.1 → v0.7.7) live in the git history and in
`docs/PLAN.md`; they predate the first public tag and are not individually released.
