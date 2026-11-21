# Changelog

All notable changes to Longrun are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project adheres to
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- **A compaction now carries the task it was compacting.** Round 165 reads four papers from the
  2026-11-19 batch and lands one capability. `harness/compaction_brief.py` extracts the semantic
  anchors the existing mechanical block does not carry — the user's task statement, its hard
  constraints and the last failure — audits the compacted list, writes
  `<sid>.compactions.jsonl`, and appends one bounded carry-forward block to the system summary when
  a critical anchor is gone. `context_engine.anchors_block` still owns paths/commands/pins; this does
  not duplicate it. Source: arXiv:2611.25673 (CompAct-Bench) — 200 trajectories solved before the
  boundary average 56.7% after compaction (best 68.5%), with omissions causing repeated work and
  distortions early termination. arXiv:2611.26346 (a branch can pass while the merge fails),
  arXiv:2611.26427 (pruning loses evidence) and arXiv:2611.25583 (content is not causal) bound the
  claim: this checks retention, never salience. Locked by `v1255` (22/22); battery 954/954.
- **A turn's report is audited against its own record, and a label travels with the file.**
  Round 164 reads four papers from the 2026-11-19 batch in full and lands two capabilities at
  live seams. (1) `harness/work_report.py` extracts the checkable claims of the final text
  (test-pass, produced file, command, commit, push) and matches each against the turn's calls
  plus the session's own tool-card history; after the reply is persisted the loop writes
  `<sid>.reports.jsonl` and injects one `report.audit` harness note naming the claim whose
  record is absent. The answer is never edited. Source: arXiv:2611.25760 — 37.24% of 435
  sampled reports carry an unsupported claim, 4.29 further user turns to handle one.
  (2) `harness/effect_state.py` keeps one taint set per session, propagates a label through
  `cp`/`mv`/redirection and refuses an egress that NAMES a tainted path before dispatch, so
  the same `curl @report.txt` is allowed before a sensitive copy and denied after it.
  Source: arXiv:2611.25599 (Tether) — one rule over declared paths, not its syscall guarantee.
  LoopRoute (arXiv:2611.25363) is parked: the selector is already the LLM.
  Pandora's Toolbox (arXiv:2611.25325) bounds the claim: enforcement, never verification.
  Locked by `v1250` (28/28); battery 953/953.

### Fixed
- **The inspector header no longer shows the sections scrolling through it; the fold control
  loses its frame; the sessions rail stops paying three layers of vertical air.** Operator, with
  two screenshots: *"see image inspector bar is overlapped in scroll of rh panel. fix."* /
  *"i dont like the collapse/expand button framed. and there's too much space in session bar and
  below, vertical space wasted."* (1) The pinned head is a frameless label (`background:
  transparent`) above a panel that is the scroller, so a section scrolled THROUGH it — the
  Approvals link printed above the word INSPECTOR. The head now paints the panel's own background
  under itself and across the 12px gutter above it (`#inspector .insp-tools::before { top:-12px }`):
  it masks the scroll instead of turning into a card. (2) The fold toggle is a bare 24px glyph
  beside the section name — no border, no filled surface; hover is the only surface. (3) The
  sessions rail paid three layers for the same gap: `--rail-hd` 36 → 28px, head bottom margin
  6 → 0, block gap 10 → 6px (a second `gap: 8px` declared later and winning by source order is
  gone), tools strip `padding: 4px 12px 8px` → `0 0 6px` starting on the label's own edge, and the
  search row follows. Measured on the running page at 1440×900: both labels start at y=64, the
  session list starts at y=134 (70px of chrome under the topbar), and the 12px band above the
  pinned inspector label is ONE colour (no content bleeding through). Locked by `v1266` (16/16,
  `UI_GUARD`); `v758` A1/A3/F4 and `v1070` A1/A2/A6 re-pointed to the new metric and to the shared
  grow rule; badge 951 → 952.
- **Resuming a goal now STARTS the turn that pursues it.** Operator: *"resume goal shall start
  the LLM to pursuit the goal; when paused simply ignores it and listens the user messages
  coming and does what the user currently asks."* `POST /api/goal {action:"resume"}` used to
  flip the record back to `active` and stop there: the bar said the goal was live while no
  turn was running. The resume branch now launches ONE detached, autonomous, goal-mode turn
  through the same worker `/goal` uses (`httpapi.start_goal_turn`, announced on the feed with
  `sender: "goal"` so the transcript does not pretend the operator typed it) and answers with
  the turn id; the page toasts and the feed pulls the turn in without a reload. A paused goal
  still never hijacks an ordinary message (`_goal_mode_of` is false, and the injected goal
  block now says this is an ordinary turn); a `completed` goal whose plan REOPENED is
  resumable again — `settle` no longer runs before `resume`, which had turned that case into
  an `active` record and made resume answer 409. Locked by `v1265` (21/21, `UI_GUARD`); badge
  950 → 951.
- **Queue really queues, steer really steers — and a waiting message is visible.** Operator:
  *"queue message doesn't work, message is sent; steer interrupting current run. I passed from
  steer to queue then sent the message … it shall appear in the up msg box bar … multiple queue
  can be accepted as in Trae."* Two causes. (1) The delivery decision was keyed on `turnSSE`,
  the handle of THIS page: after a reload, or with a turn started by the CLI or another tab, it
  was missing, so the queue branch was skipped and the message started a new turn. `send()` is
  now async and asks `GET /api/chat/live` when it has no handle, attaching to the live turn
  before deciding. (2) A queued message was invisible while a background command owned the
  label. The queue icon now carries a COUNT badge (also in its `aria-label`) and the label
  lists the queue AND the background state; a 5 s reconcile (`_queueReconcile`) drops a stale
  handle and flushes when the server says idle, so a missed `done` can never turn the queue
  into a dead end. Steer keeps posting `/api/chat/steer` into the running turn; a command is
  still always queued. Locked by `v1264` (13/13, `UI_GUARD`); `v1262` C1/C4 re-pointed; badge
  949 → 950.
- **The goal menu's last row and the editor's "cancel" were unpressed above the strip's panel.**
  Found by the testing head (A54 finding **R180-1**, high): the goal bar now lives only inside the
  strip's dropup (`#csBody`, a z-70 layer), while both goal popovers were anchored with
  `bottom: 100%` of the composer (z 45/40) — the panel painted over them, so `elementFromPoint`
  on `✕ delete` and on the editor's `cancel` answered the panel and the press did nothing. The
  menu and the editor are now `position: fixed`, `z-index: 90`, and placed from the panel's own
  rect by `_gbPlaceDropup` (right-aligned above it for the menu, panel-width window above it for
  the editor), so no stacking-context dependency is left; closing the strip also closes both.
  Locked by `v1262` F1–F3 (22/22). Also fixed a live axe 4.14 finding on the chat head: the
  session title button's accessible name now CONTAINS the visible text (WCAG 2.5.3).
- **`v768` F1 re-pointed**: the tool card no longer takes a timestamp argument (round 177 removed
  it); the pin now matches `toolCard(d.tool, d.args)`.

### Changed
- **The testing head is dispatched only for what it can actually check.** Operator: *"stop asking A54
  everything: he cannot access every part of the backend and frontend … he can be invoked only for
  things he can check. Verify before dispatch."* Project rules now list his reach (rendered WebUI over
  CDP, HTTP with the bearer command, repo files, git, the project tests) and require the three-line
  pre-dispatch test — **Observable · Reach · Verdict** — before a brief goes out; a change whose only
  evidence is a deterministic test closes with the battery + the maintainer's own measurement. The
  references in `docs/TESTING-PLAYBOOK.md` and `docs/CLI.md` point at the new section title.

### Added
- **Marketplace: the card scans, the detail reads — full description and the origin page.**
  Operator: *"nel catalogo marketplace non c'è modo di leggere descrizioni complete degli
  oggetti? sono tutte tagliate; cliccando un tasto devo poter vedere la descrizione completa …
  se no portarmi proprio all'URL della pagina d'origine"*. A catalogue card keeps its
  two-line clamp and gains a named ⓘ opener (and the card itself is clickable); both open ONE
  dialog (`#mktDetailWin`) with the SAME `description` whole, publisher/version/category/
  license/downloads/updated/digest/members/server, and **origin page** / artifact links.
  The origin page is catalogue data now: `market_sync` stores `homepage` for ClawHub
  (`<owner>/skills/<slug>`) and for MCP entries (`websiteUrl` or `repository.url`), and
  `market._normalize` derives the ClawHub page for catalogues synced before the field existed —
  so old imports link correctly without a re-sync. Only `http(s)` values become links; a
  `javascript:` homepage is dropped. `DESC_MAX` 300 → 1200, cut on a word boundary with `…`
  instead of mid-sentence. Locked by `v1263` (18/18, `UI_GUARD`); badge 948 → 949.
- **One composer status strip, Trae-style: five icons, one label, one panel above.** Operator:
  *"vedi la barra sopra msg box di trae come è strutturata? le icone … tasks process, file
  review, messages (queued), background command processes, goal, cliccando su ognuna mostra
  sopra la barra ciò che va mostrato … mi piace molto molto compatto"*. The message box's top
  row is now the session status strip: **tasks** (the plan body), **files** (the session's
  changed files), **queued messages**, **background shell commands** and **goal**, then a live
  status label (`4/4 tasks Completed`, `2 files changed`, `1 waiting to send`, `1 background
  command running`, `Goal paused`) and the existing ✨ + close. The goal bar and the queue
  chips are no longer rows: they are BORROWED into the dropup, so verify/pause/edit/delete and
  ✎/⇢/× keep working with no second implementation. Background means the **shell** jobs
  (`shell {background:true}`): `bgjobs.listing()` + `GET /api/bgjobs?session=` (running first,
  log tail) and `POST /api/bgjobs {job}` to stop one; the tool jobs and agent runs stay in
  RH ▸ Feed. Locked by `v1262` (22/22, in `UI_GUARD`); `v1255`/`v1256`/`v1258` re-pointed.
- **Settings ▸ Rules is Trae's Rules list: one folder path, one row per rule file, and a
  per-file "always apply" switch.** Operator: *"metti solo il path delle rules non ogni
  singola rules lì in alto così apri magari il path in hyperlink … se vai in settings rules
  le vedo le rules di progetto tutte cliccabili? e posso selezionare se applicarla ad ogni
  messaggio always apply o no come in trae?"*. The project card is now ONE clickable
  `<ws>/.trae/rules` path (click reveals the folder in the editor tree) plus a row per
  `.md` — name + relative path on the left (click opens the file), an "always apply"
  checkbox on the right. `POST /api/rules {path, always_apply}` stores the switch in
  `projects/<ws>/rules_state.json` (absent = ON, the previous behaviour); a file switched
  OFF leaves the system prompt, the loaded list and the audit in the same turn. The RH
  panel follows: one path link, no duplicated second folder, and the long green footer
  sentence is gone. The project textarea, its save button, its ✨ surface (`rules.project`)
  and the separate "Loaded rule files" card are removed — no single editable project file
  and no dead generated surface. The folder link calls the editor's `showDock()`, so it
  also opens the dock on a phone and after the operator closed it (A54 B-1). Locked by
  `v1261` F1–F7; `v361` A8, `v507`, `v540` A8 re-pointed.
- **`/context` and `/restart` in the composer — two verbs that reuse the doors that already exist.** Operator:
  *"in the slash commands include the restart command /restart … and the context command for showing context
  informations and details (see breakdown RH panel also) don't duplicate code please … commands and tool share
  the same functions."* `/context` (alias `/ctx`) opens a window with the SAME card the composer popover and
  the inspector draw (one builder, `_ctxCardHTML`, fed by `_ctxDisplay` from `/api/context`) and the SAME
  breakdown (`renderCtxItems` from `/api/context/items`), with the SAME two doors (`compactNow`, the compaction
  settings). `/restart` calls the agent's OWN tool — `harness` with `action: "restart"` — so the UI and an
  agent share one implementation; no session is passed, so no continuation turn is spawned. Both are in the
  backend catalogue (`core/slash.py` BUILTINS, so the API catalogue cannot drop them) and the WebUI
  re-attaches the callbacks by id after the catalogue replaces the first-paint fallback. Locked by `v1250`.
- **Three WebUI surfaces: inline image preview · diff change-map · context-ring popover.** Operator: *"se
  chiedo fammi vedere una foto X me la fai vedere in chat oltre che darmi il iperlink path"*; *"il diff view …
  non mostra dove sono le modifiche così non so dove scrollare per trovarle"*; *"il cerchietto di contesto …
  se ci clicchi sopra devono uscire più dettagli minimali più … compact"*. (1) An image the agent references
  is previewed **inline** as a medium box (clicking opens the dedicated image window); the path link stays.
  (2) The diff modal now **lands on the first change** and draws a **change map** on its right edge (add/del/
  change ticks, click to jump). (3) Clicking the composer **context ring** opens a minimal popover (tokens /
  budget / messages) with a **compact** action that reuses `compactNow()` — one compaction door. Locked by
  `v1244` (15/15). Also recorded in the project rules: draw WebUI surfaces with the `impeccable` + `frontendui`
  skills after reading the neighbouring surfaces, and never close a task with an open todo step.
- **Post-turn completeness verifier — an INDEPENDENT model checks the agent's own last message.** Operator:
  *"non doveva esserci dopo ogni fine messaggio … una LLM call al modello stesso in versione verificatore che
  il suo stesso ultimo messaggio non abbia lasciato lavoro incompiuto? … non basterebbe vedere todo aperti
  perché potrebbe non esserci"*. After a turn that produced a final answer, a **dedicated model** (config
  `turn_verify`, default `openrouter:z-ai/glm-5.3-flash`) reads ONLY the operator's request, the agent's own
  final message and the still-open plan steps — never the tool transcript, so the cost is bounded and the
  work is not marked by the model that did it. It returns `{"complete", "missing"}`; on `complete=false` the
  harness gives the agent at most `turn_verify.max_rounds` (default 2) more round(s) to finish, so the loop
  is **bounded** (no infinite loop). One shared judge call (`plan/judge.py`) now serves BOTH this verifier and
  the L3 goal judge, so there is no second mechanism. The cheap SAME-model closure check stays. Editable in
  `config/tools.yaml` (Settings ▸ Config files). Locked by `v1243` (20/20).
- **`/status` — one deterministic report about a session (tool + slash command).** Operator:
  *"in the commands (slash /) list there shall be created a command status that reports
  everything information on the session, context saturation, max context, LLM used … that
  command can be deterministically run as tools also by any agent."* One read-only handler,
  `harness.status`, joins the existing harness lifecycle namespace (`harness.restart`), so any
  agent runs it as `{"action":"status","session":…}` while the composer's `/status` opens the
  same facts in a modal. It aggregates the stores that already own each number — session
  identity/model/workspace (`stores`), context saturation vs the **max context**
  (`httpapi.context_usage`), the live plan and its open steps (`taskgraph.public`), this
  session's pending approvals and running-turn state (`approvals`, `inflight`), and the org
  identity (agent id, teams, role). Grounded in VISTA (arXiv:2606.30005 §3, *state
  proprioception*), the context block also reports the remaining-token **headroom** in
  absolute tokens and the **archive status** of curated tool payloads, so a model can make
  keep-or-archive decisions. Locked by `v1238` (18/18).
- **A brand menu (⋮) beside the LONGRUN wordmark and a changelog button.** Operator: *"a button
  to restart longrun … a three-dot menu just beside right to the LONGRUN title … other high level
  suggestions … shall not be already other buttons in the webui"* and *"a changelog button
  (visible mobile and desktop mode)."* The ⋮ opens ONE body-anchored popover with the lifecycle
  acts the topbar had no home for — **restart longrun** (reuses the supervised-restart route,
  warns about running turns), reload interface, copy diagnostics, about. A dedicated
  **changelog** icon button sits in the topbar action cluster (sized for the 44 px landscape
  rail and the phone header) and opens a modal with the repo's `CHANGELOG.md` releases plus the
  recent git commits and HEAD, served by the new read-only `GET /api/changelog`. Locked by
  `v1237` (9/9).
- **The terminal and feed rail group moved to the top of the tool sidebar**, and the composer
  gained a tiny numberless **context-saturation ring** left of the model name (green < 50%,
  amber < 70%, red ≥ 70%). Operator: *"the feed and terminal icon in the sidebar shall be placed
  on the very top of the sidebar"* and *"the context saturation circle shall appear also in the
  message chat box beside left of the LLM name … tiny … no number percentage only the circle
  with color amber green red. dont duplicate code."* The ring geometry is ONE shared helper
  (`_ringCircles`) used by both the rail row and the composer chip, so the two can never drift;
  both read the same `/api/context` number the rail meter already shows. Locked by `v1239` (8/8);
  the rail-order pins in `v885`/`v890` were updated to the new order.
- **The Architect can preview and delete sessions (and their agents) in bulk.** Operator: *"vorrei
  che A1 architect … abbia la possibilità di cancellare sessioni (agenti) … cancellami le sessioni
  no team che ti sembrano inutili."* `session.delete` now takes `session` OR a `sessions` batch —
  one cascade (running turn aborted, graph/runs/edits/ROLE.md/knowledge notebook purged, agent
  record released with jobs scrubbed, routines deleted, reports re-parented) — plus `workspace:true`
  to remove the dedicated folder. The new read-only `session.delete_preview` reuses the WebUI's own
  No-team bucket (`orchestration._no_team_sessions`), excludes the system session and RUNNING turns,
  and returns title/agent/teams/messages/age/reports/jobs/routines/workspace so the model can judge
  what is useless BEFORE deleting. Workspace removal now refuses the global default and any folder
  a live session still references (both `session.delete` and `agent.delete`). New P1 tools:
  `team.models_set` (lead/member/local-slot model policy in one call), `session.model_set` (pin one
  chat's model in both stores), `provider.test` (probe a provider or ping a model without changing
  config). Locked by `v1236` (34/34); v537 42/42, v740 7/7, v887 23/23, v889 11/11, v534 38/38.

- **Round 163 — four newest online harness papers, four capabilities, all wired where the model
  reads its own work.** Sources (submitted 2026-11-18/19, read in full, max four): S-2026-11-20-015
  ROGUE-AI (arXiv:2611.26553), S-2026-11-20-016 *How Much Should an Agent Remember?*
  (arXiv:2611.26361), S-2026-11-20-017 SkillBridge (arXiv:2611.26256), S-2026-11-20-018 GrepMem
  (arXiv:2611.25123).
  - **A hazard notice on every tool output.** `harness/hazard_notice.py` names the hazard AND its
    consequence (production target, destructive verb, credentials in reach, shared resource, public
    surface, money movement) and the chat loop appends one line to the observation it is about to
    inject — silent when no rule fires, fail-open. ROGUE-AI: this note lowered harm for all five
    tested models, where a fact-only note of the same length did not. Also `forge.py
    hazard classify|notice|audit`, the last one the paper's incident/matched-control test (one-sided
    Fisher).
  - **A lossless history log with grep recall.** `memory/stores.py` appends every message, tool card
    and harness inject to `<data>/sessions/<sid>.log` (beside the transcript, append-only, 200 KB per
    entry, removed by the delete cascade), and `context.grep` / `context.count` search it with a regex
    — chronological line numbers, surrounding context, pagination, count-only, no index. GrepMem:
    95-97% on ContextBench against 6.6-20.7% for summarization/masking. Pure half
    `harness/checks/recall_log.py` (`forge.py greprecall`).
  - **A cross-OS skill contract screen.** `harness/checks/skill_os_contract.py` builds the G/P/M/D/A
    contract and fires a rule only when matched, reachable, conflicting and not covered by a fallback,
    naming the field and the repair target. `skills.install_*` return it as `os_warnings`; the install
    still succeeds (a screen is a hypothesis, never a verdict). `forge.py skillos`.
  - **A memory dose that belongs to the model.** `harness/checks/guideline_budget.py` consolidates
    support-conservingly (sum(support) == lessons, provenance kept) and selects a dose by capability;
    `audit()` names a store that never grew, a run with no call and a high-support failure lesson. The
    live memory index ranks `agent.note` lessons by support and bounds them with the new
    `context.memory_lessons_cap` (default 4). `forge.py guidelines`. Locked by `v1235` (37/37);
    battery 921/921.

- **The chat header hands out the session's FILE, not just its name.** Operator: *"a way to copy the
  session file (absolute path) so you have the path in hand and can hand it to another agent — look at the
  chat in this path … at the top, near the other copy (copy name), always an icon, no text"*. A second
  icon-only button (`#chatHeadPath`, a drawn document glyph beside the existing ⧉) puts the absolute
  transcript path on the clipboard in one tap — ready for another agent, an editor or a shell. The path is
  the SERVER's own: `list_sessions()` now carries `path` (the absolute file each row stands for, resolved
  against the live data home, which the browser cannot derive). It rides the ROW and never the document,
  so `save_session` cannot persist a `path` key into every transcript on disk; a row without one refuses
  out loud instead of copying an empty string. (`LONGRUN_DATA_HOME` moves the data dir, so a
  browser-rebuilt `/data/sessions/<id>.json` would be a guess.) Locked by `v1067` A1–A6, B1–B10.

### Changed
- **A tighter Sessions rail (agent id on hover) and ONE themed popup for every native `<select>`.** Operator:
  *"riduci di poco la spaziatura tra agenti sessione in LH panel ed l'id agente nascondilo, rendilo visibile al
  passaggio mouse sopra"*; *"ci sono menu in mobile mode che si aprono senza tema grafico, sono bianche.
  Esempio jobs assign to nel pannellone agents jobs … controllali tutti gli spawning menus, devono essere in
  linea col tema generale impostato da settings"*. (1) A session row is `padding: 4px 8px` / `margin-bottom:
  1px` (was 6/2 — measured 42 → 38 px per row on the phone list, the `.sess-ctx` ring is what fixes the
  floor) and the `A<n>` chip is `display: none` until `.sess:hover` / `:focus-within`; the id moved into the
  row tooltip (`agent A54`) and the organigram door stays in the ⋮ menu, so nothing is lost. (2) A native
  `<select>` opens a list drawn by the OS/WebView: measured in both documents, every select computes
  `color-scheme: dark` and a themed box, yet the phone's option list is white whatever the theme is. The new
  `ThemedSelect` (in the shared `webui/assets/filtersort.js`, loaded by the WebUI and the deck) intercepts the
  control and draws the list itself: a `role="dialog"` surface containing a `role="listbox"` with
  `role="option"` rows, the page tokens (`--menubg` → `--panel2`, `--line-2` → `--line`, `--txt`, `--sel`), a
  bottom sheet at ≤640 px, keyboard (Enter/Space/Arrows/Home/End/letter jump/Escape) and the real contract —
  `selectedIndex` plus a bubbling `input`/`change` — so every existing `onchange` keeps working. This covers
  the deck's "assign to…", the filter’s own two selects and every settings picker with one implementation.
  (3) `aria-controls` left the filter button: it named the dialog by id and axe's `aria-valid-attr-value`
  reported a CRITICAL incomplete on every run (open or closed); `aria-haspopup` + `aria-expanded` carry the
  same meaning and verify. Locked by `v1259` A1–A5, B1–B7; `v1258` E1 re-pointed to the decision. axe live
  with the popup open: **0 violations** at 1440×900, 390×844 and on the deck (only `color-contrast`
  incomplete). Badge 944 → 945.

- **The Workspace/Plan strip is icon-only, the chat header hides the session id, a todo row is meta-above /
  label-below, and the tool row has TWO readings (file in the editor, `+A −D` in the diff).** Operator:
  *"invece di scrivere workspace and plan sulla barra sopra la msg box metti le icone … e togli il riassunto
  4 done, run id. Lì in alto a destra metti l'autogeneration"*; *"on top of chat … non mettere l'id di
  session chat, occupa spazio: fallo apparire al passaggio del mouse e copiare al click sul nome"*; *"i todo
  in chat thread non possono contenere il testo tutto a destra: deve stare in basso al done e Jx number,
  così occupa lo spazio orizzontale"*; *"se clicco sul file si apre file normale nell'editor; se clicco sui
  numeri di linee modificati a destra si apre il pannello diff"*. (1) The two toggles are 24×24 SVG icons
  (`aria-label` + `title` "workspace"/"plan"), the borrowed `.ihd-s` summary line is gone with its
  `MutationObserver`, and the `chat.prompt` ✨ is the strip's right end (`margin-left: auto`) instead of an
  absolutely positioned control over the textarea (its `padding-right: 36px` is gone). (2) `#chatHead` no
  longer prints the session id inline: `.ch-id` is an absolutely positioned chip shown by
  `.ch-title:hover`/`:focus-visible`, the title is a `role="button"` that copies name + id (Enter/Space
  included), and the existing ⧉ button still copies the same pair. (3) `.tctree > summary` and `.task` are
  ONE column — badge + ids on the first line, the label on the next at full width (measured 92% / 93% of the
  row at 1440×900 and 89% at 390×844) — which retires `_markWrappedTasks`, the `.stacked` class and its
  ResizeObserver: the stacked shape IS the row now. (4) `_wireToolName` opens `openInEditor(path)` from the
  file NAME for every tool (an out-of-workspace path lands in the dock with its own ⚠), and only `.tc-stat`
  calls `showDiff(path)`; `SparkEditor.inWorkspace` is no longer exported because nothing asks it. Also
  closed the axe `aria-valid-attr-value` **critical incomplete** on `#hideEmptyBtn`: `aria-controls` is
  published by `FilterSort.open()` only while the dialog it names is open. Locked by `v1258` A1–A4, B1–B3,
  C1–C3, D1–D3, E1; `v439` (rewritten for the always-stacked row), `v630` A1/B6, `v1253` E2, `v1255`
  B4/C2/E1–E2, `v1256` C2–C3/E2 re-pointed with dated comments. axe live: 0 violations at 1440×900 and
  390×844 (only `color-contrast` incomplete).

- **One 30×30 anatomy in the phone header, a themed full-width filter sheet, and SVG glyphs in the rail
  toolbar.** Operator: *"icone minuscole nella barra, il cerca lente … disallineate, guarda e capisci da solo
  cosa va fatto"*; *"ci sono menu che non sono coerenti col theme, soprattutto mobile, per esempio il
  filtro"*. (1) The search lens rendered **5 px wide**: `#palette-open` had `padding: 0 10px` inside a 27 px
  box and the flex SVG gave way — every topbar glyph now has `flex: 0 0 auto` and its own 17 px. (2) Below
  480 px every right-side control is ONE 30×30 box on one baseline (was 24×30, 24×16, 32×20, 27×30, 27×27,
  27×27 with tops at 11/16/18/11/12): sandbox dot and approvals ✓ included, tabs 32×52; the 360 and 340
  tiers shrink the SAME boxes (28/25) instead of mixing sizes. (3) The FilterSort panel drops the only
  UPPERCASE label in the product (9.5 px + .10em tracking → 11 px sentence case) and, on a phone, is a
  full-width sheet (8 px margins, 12 px radius, 36 px controls) like the model picker; both selects and the
  direction button now carry `aria-label` (axe `label-title-only`). (4) The rail's new-session and search
  buttons are SVG glyphs — the search was the 🔍 emoji. Locked by `v1257` B1–B4, C1–C4, D1–D2;
  `v1245`, `v1028` re-pointed with dated comments.
- **The Workspace/Plan bar is the message box's top strip, session rows are ONE line, the todo id sits
  beside its badge, and the Agents panel gets its funnel back.** Operator, with TRAE screenshots: *"perché
  non hai aggiunto la sovrabar alla message box? come trae"*; *"nel LH panel sessions le cose stanno tutte in
  una riga, non andare accapo con l'ID agent e il contesto"*; *"anche per i done dentro la chat accapo c'è
  A1.n65, mettilo affianco al done … risparmiamo spazio verticale"*; *"in agents panel non lo hai messo il
  filtro come in sessions (non duplicato dato che hanno stessa funzione), dovevi duplicare solo l'oggetto
  grafico"*. (1) The tabs row carries the divider (`border-bottom`) and keeps the plan line even with no tab
  open — the summary is still the Plan section's own `.ihd-s` (TRAE's "0/6 tasks Completed"), so the strip
  says where the session stands at a glance. (2) `.sess` no longer wraps: title (ellipsis) · A-id · context
  ring · age · ⋮ on ONE 32 px row. (3) `.tctree .tcmeta` and `.task .tmeta` are rows, so `done A54.n72` reads
  on one line in the chat tree and in the inspector Plan (the stacked variant included). (4) The hosted deck
  no longer hides `#agFilterBtn`: the Agents panel shows the SAME `FilterSort` control the Sessions rail
  mounts (key "agents"), not a second filter. The queued-message lane needed no work — verified already
  implemented (`#queueBar` with edit/steer/remove, queue vs steer in one stored delivery mode) and pinned by
  `v1256` G1–G2. Locked by `v1256` C1–C3, D1–D2, E1–E2, F1–F2; `v630`, `v439`, `v352`, `v1049` re-pointed.
- **One transcript typography, a Workspace/Plan bar above the message box, the ✨ inside the box, and
  `+A −D` opens the diff.** Operator, with TRAE screenshots: *"trae li ha [workspace e plan] come sovrabar
  intercambiabile sopra la msg box … implementalo anche tu (non distruggere il RH panel), non duplicare
  codice"*; *"l'autogenerate … dentro la msg box piccolo in alto a dx … rimuovilo dalla sidebar"*; *"i diff del
  wrote/edit non si aprono nel diff panel ma espandono l'edit — se clicco proprio dove dice +48 −5 deve aprirsi
  il diff"*; *"il nome file deve essere piccolino come le righe di harness"*; *"command executed è bold e font
  diverso … perché il testo di risposta è BOLD di default? … il font size deve essere uguale e uniforme,
  rimpicciolirei risposte e thought"*; *"i file out of workspace in read > nomefile non li apre nell'editor —
  risolvi"*. (1) The transcript is ONE typography: answer and Thought body **12.5px / 400 / 1.55**, the
  file name **11.5px italic** under a 12px/400 verb, the harness scope 10.5px — and the "bolder text"
  preference no longer reaches the transcript at all (`html.bold-text .bubble` and its `p, li, td` rule are
  gone; only explicit `<b>/<strong>` inside a bubble still gets 800). (2) A **bar above the composer** with
  two toggle buttons, **Workspace** and **Plan**; it **borrows the live `.insp-body`** of the RH inspector
  (`_csOpen`/`_csReturn` move the same node, same ids, same renderers, same listeners, and hand it back on
  close) so there is no second panel, and its summary is the inspector's own `.ihd-s` line through a
  MutationObserver — no second count. The lent section says "· above ↗" and its header still works. (3) The
  chat ✨ (`chat.prompt`) mounts in `#cmpSpark`, top-right inside the message box; the sidebar host no longer
  carries it. (4) The `+A −D` stat is its own link: clicking it calls `showDiff(path)` with
  `stopPropagation`, so the row does not expand. (5) A `fs.read` outside the workspace opens the **preview
  window** instead of a dock tab with "⚠ outside the workspace", through the dock's own predicate
  (`SparkEditor.inWorkspace`, one rule, no second copy of the root logic). Locked by `v1255` (14/14), with
  `v1250`, `v1252`, `v1253`, `v352` and `v890` re-pointed to the new contract (dated comments).
- **The tab is just "Longrun", an answer carries no agent label, and the composer context ring opens the
  compact context card.** Operator: *"perché si chiama longrun dgx harness? non si può chiamare solo longrun?"*;
  *"perché devi continuamente scrivere A54 · LONGRUN? a cosa serve? rimuovi quella cosa"*; *"se clicco sul cerchio
  del contesto in msg box si deve aprire un menu coi dettagli contesto e con la possibilità di compattare,
  simile al RH panel ma più succinto — adesso se clicco non succede nulla."* The document title and the runtime
  `updateDoneTitle()` both read **Longrun** (the boot helper used to overwrite the tab with "⚡ Longrun — DGX
  Harness"). `_aiLabel()` is deleted: a user turn keeps its "YOU" label and a delegated turn keeps its
  sender + subjob, while an answer is just its text — the copy control survives on the same line, revealed on
  hover. The three Thought builders draw no header line. The context ring is a real `<button>` with a 24×24
  hit area around the same 13px ring, a delegated click handler (a re-rendered composer cannot leave it dead),
  a stale-node guard in the toggle, and the SAME context card as the `/context` window and the inspector —
  with `compact` (one compaction door) and `settings`. Locked by `v1254` (11/11) and the rewritten `v585`
  (7/7).
- **One transcript rhythm — dotted rail, aligned 28px rows, no chevrons, plain "harness" row, frameless
  messages, edits that open their diff.** Operator, with TRAE screenshots: *"le cose non sono allineate …
  thought non è tutto nel block … harness è disallineato e diverso dagli altri … la freccetta per espandere
  non serve, basta cliccare sul nome del file … anche risposte LLM no vanno in frame, manco messaggi utente …
  le spaziature non sono uniformi … anche l'edit deve avere le stesse cose, con apribile finestra diff …
  harness → LLM lo toglierei … chiamalo harness e basta … lo scope Observation va tenuto ma non in stampatello
  … il font del thought non è lo stesso del messaggio normale."* Tool rows, "Thought" rows and harness rows now
  share ONE gutter and ONE dotted left rail (`padding: 0 6px 0 14px`, `border-left: 1px dotted`,
  `--row-h: 28px`), and the nested group rails (`tc-kids`, `fg-kids`) are flattened so a tool row, a harness
  row and a message sit on the same x. Every chevron is gone: the row label is the disclosure, the FILE NAME
  opens the file (read) or the diff window (edit/write), and the action icons appear only on hover/focus. The
  `harness → LLM` chip became a plain `harness` row with a soft lowercase scope ("Observation · user") and
  the raw wire body in place. Answers and user prompts are text, not boxes (the prompt keeps one 2px accent
  rule), and the thought body uses the message typography (13px/1.55). An edit row carries `+A −D` read from
  `/api/edits/diff`, and clicking its name opens the same diff window. Locked by `v1253` (20/20).
- **The transcript is a log, not a stack of boxes; only "Thought" carries a frame.** Operator: *"non mi piace
  vedere testi e messaggi vari nei box … guarda TRAE: solo i thoughts ha nei frames … copia spudoratamente il
  formato … non voglio read edit tutto italico, solo il nome file — il Read no … inspector panel e sessions
  panel non hanno stesso margine dal TOP bar … io li toglierei dal frame."* A tool call is now a **26px log
  line on a left timeline** (glyph · verb · italic file · time), with no card surface: transparent background,
  `border: 0`, a 1px `--line` left rule, a hover tint and the details opened in place. Only the **file name**
  is italic and tool-tinted (`.tc-file`: `fs.read` steel, `fs.edit` accent, `fs.write` info); the verb stays
  normal text, and one builder (`_toolNameHTML`) feeds both the new row and its live update. **"Thought" is the
  only block that can be framed**, and — TRAE's shape — the frame appears only while the text is OPEN
  (`details.think` allocates a transparent 1px frame, `details.think[open]` paints it), so opening never
  shifts the row; a live block keeps its pulsing dot until the turn moves on. Both rail heads are now
  **frameless labels at the same 12px offset** from the topbar (sessions by `#aside` padding, inspector by
  margin + sticky `top: 12px`), and they share one anatomy. Locked by `v1252` (22/22).
- **A team scope shows ONE team in the Sessions rail; the team option list has one builder.** Operator: *"if I
  filter a team I want only that team not also other teams (it happens because a member can have multiple teams
  that shall be maintained). Filtering a team will show only that TEAM."* A session is drawn once, under the
  FIRST group that claims it, and the cross-team Pinned bucket and the No-team bucket were unconditional — so
  scoping to T3 left the T1 header on screen carrying its T1+T3 members. Under a scope the rail now renders
  exactly ONE group (its own, pinned rows included), expands it once when the scope CHANGES (a later collapse is
  not fought), and the empty state names the team (`no sessions match this filter in Incident Response`).
  Multi-team membership is preserved: an agent keeps every team it belongs to and appears under the scoped one.
  The team OPTION list was built twice (rail + deck); it now lives once in `webui/assets/filtersort.js` as
  `FilterSort.teamOptions(list)`, and both pages pass their own list — the agents panel keeps its funnel button
  (the same icon) mounting the SAME module under key `agents`, and the rail's scope is pushed to it. Also fixed
  the shared panel's hide-empty checkbox getting the literal id `undefined` (`ids.hide` → `ids.hideEmpty`).
  Measured on the render: scope T3 → one group `Incident Response T3`, 10 rows, 0 off-scope, a T1+T3 session
  under T3; ALL → 9 groups, 98 rows. Locked by `v1251` (19/19, added to `UI_GUARD`).
- **File-operation cards, ONE rail-head surface, every spawning window movable.** Operator: *"i don't like edit
  read write … shall have a different format colour … adequate to THEME selected … maybe italic"*; *"why
  session and inspector bars are in a different background? … uniform … minimise contrast"*; *"all the
  spawning panels in the webui shall be movable"*. (1) `fs.read` / `fs.edit` / `fs.write` cards carry their own
  calm skin — steel (`--acc2`), accent (`--acc`), info (`--info`) — mixed into `--panel2`/`--line`, with an
  inset 2px bar and an italic file name; the verdict pip keeps `--ok`/`--err`, and the labels split into
  `Read` / `Edited` / `Wrote` (write no longer says "Edited"). Measured on the render in indigo and celestial.
  (2) `#aside .rail-head` and `#inspector .insp-tools` are one object: one `--hd-surf` surface, one 36px
  height, one 8px inset card, one padding (they were a flush strip and an inset card, 3px apart). (3) ONE
  `dragify(handle, box, key, opts)` moves settings, the runs popover, the preview, the diff view, every
  picker/dialog and the info windows, remembering each place in `localStorage` and clamping it on open; the
  Control deck's `_dpDrag` now delegates instead of keeping a second pointer algorithm; the pointer maths
  divides by the page zoom (the `645eef0` trap) — measured: at zoom 125% a 100/50 pointer move is 100/50
  visual px; the phone preview stays full-screen (`smallOff`). Locked by `v1250` (31/31); `v758` F4 and
  `v1051` A1 re-pointed to the new single truth.
- **The composer's context popover is now the inspector's Context card — one anatomy, one compaction door.**
  Operator: *"clicking on compact in msg box doesn't open the wanted menu with more context details … similar
  to the RH panel. Don't duplicate code backend."* The ring's popover used to draw a stub of its own (four
  `cp-row`s and a full-width `cp-compact` button). It now renders the SAME card the Inspector's Context section
  draws — percentage + meter + state, then messages / tokens / budget, then the two text actions — from the
  SAME `/api/context` read (`_ctxDisplay`) and the SAME two doors: `compactNow()` (still the only
  `/api/context/compact` call site in the file) and `openSettings("compaction")`. No new endpoint, no second
  vocabulary; the dead stub CSS is gone. Verified on the rendered page (headless Chrome, real rail click on
  `b7329cccf94c` + real event on the ring): `6% · normal`, `195 messages · 65811 tok · 1044480 tok`, both links
  with handlers, on-screen, sharing the panel's anatomy. Locked by `v1249` (20/20) and `v1244` (re-pointed 3b).
- **A document now carries TWO decisions, and the approval policy has ONE owner.** Operator: *"the manual
  approval is required both plan and spec … i was in approval=FULL … a specific checkbox: auto-approve
  plans and specs … one can be approved to do spec but not authorized to implement them … can you change
  it by CLI? i think not otherwise an agent can run the cli and auto change its approval policy"*.
  `approve` decides the **content** and no longer releases the gate; the new **`implement`** — the bar's ▶,
  `POST /api/docs/implement`, `forge.py docs implement`, the inbox's `implement` — authorises the
  **implementation** and opens it (`stores.grant_implement`, refuses before approval). `approvals.mode=full`
  auto-approves the document; the new checkbox **"auto-approve plans and specs"**
  (`approvals.auto_implement_documents`) is the second check and also authorises the implementation —
  only for a request that asked to implement, and `origin` decides that, never prose: composer `/plan`·`/spec`
  and the CLI are `document`, the agent's `docs` tool is `implement`. The model sees which half is missing
  (`DOCUMENT` block: "APPROVED … but did NOT authorise the implementation"). Settings lists the document
  verbs once (derived from the catalogue) with `/plan` → `docs.plan`, `/spec` → `docs.spec` as aliases.
  The CLI can no longer write the policy (`tools policy|approvals|runtime|…` removed): `POST /api/tools`
  and `POST /api/settings` refuse a body carrying `session`/`run_id` (a turn's call is never an operator
  act) and every accepted write publishes `policy.changed`. There is ONE token — the API bearer — and the
  **permission layer** is the control (the operator rejected a second token: *"two tokens no"*): the env
  file is a hard deny in `fs.read`/`fs.write`/`fs.edit` and in `shell.exec` (`cat`, `grep`, …), and
  `shell.exec` can no longer `curl|wget` the control API (`/api/tools|settings|docs|fs|edits`) around the
  tool gate. (Locked by `v1052` B1/B1b, N9d/N9d2, N11b/N11b2, O1–O7; `v785` K1–K5; `v763` F1–F2.)

### Fixed
- **Settings ▸ Rules edits the file it SAVES, and the loaded rule files are links.** The testing head's
  round-177 verdict found the defect: the project editor rendered the COMPOSED corpus (native file + every
  folder `.md` + `AGENTS.md` — 85,396 chars live) while `save("project")` writes one file, so the first save
  would have duplicated every other file's rules into it; the global editor had the same shape with
  `Global_rules.md` + `AGENTS.md`. `rules.status()` now carries `file_text` (the native file's OWN bytes)
  beside the composed `text`, both Settings editors bind `file_text`, and the project card names the two
  folders under its path. The "Uploaded files" card (now "Loaded rule files") renders one `.rfile` button per
  loaded `.md` that opens the real file via `openInEditor` — the same `data-rulepath` contract as the RH
  panel. Measured live: `/api/rules` project `text` 85,396 / `file_text` 0, project editor 0 chars, 4 links,
  a real press opens the dock on `.trae/rules/project_rules.md`; axe 0 violations. Locked by `v1261` F1–F3.
- **The transcript is TRAE-clean, and the project rules FOLDER is loaded whole.** Operator: *"guarda che
  orrore gli orari e gli exit code e la roba a destra nel chat stream elimina tutto. la data va messa sulla
  sinistra e solo degli user messages e risposte dell'agente, non delle fasi intermedie"*; *"perché dopo
  thought aumenta la spaziatura nel thread? perché wrote non ha sulla destra il file che ha scritto come
  edit e read?"*; *"vengono caricate tutte, non solo project_rules … proprio come fa trae … nel RH panel
  hyperlink che me li apre nell'editor"*. (1) Every row's right meta is gone (`exit N · backend · summary`
  and the live "running… …"), the clock is gone everywhere, and ONE date-only stamp (`YYYY-MM-DD`, from the
  server ts) sits at the LEFT of user messages and agent answers; a live answer is stamped when the server
  finalizes it. An in-flight row now pulses its glyph instead of spelling a state. (2) A Thought row was a
  `msg` wrapper, so the 16px message margin stacked on a 28px row — the wrapper is `msg ai think` with
  margin 0, so the thought keeps the transcript rhythm. (3) `fs.write` cards lost their file name and
  `+A −D` because `persist_tool_card` cut `args` at 4000 chars mid-JSON: `JSON.parse` threw, `_argsObj`
  returned {} and the row had no path (14 of 24 file cards measured unparseable). `_card_args` now clips the
  big VALUES and keeps valid JSON, so the path (and the diff/open affordances) survive. (4) The project
  rules scope loads EVERY `.md` of `<workspace>/.trae/rules/` (the operator's rules folder — what Trae shows
  as its Reference) plus the harness `<state>/rules/`, additive and deduped, and the RH panel renders one
  link per file that opens it in the editor (`openInEditor`) instead of a single textarea; the native
  `Project_rules.md` stays supported. `rules_prompt_max_bytes` 32 KB → 128 KB so this workspace's 85 KB
  corpus is not cut mid-file. Measured: block 89,081 chars, no truncation, live `system_tokens` 10,974 →
  31,107. Locked by `v1261` A1–A5/B1–B4/C1–C2/D1–D3/E1–E7.
- **The composer context ring opens where the finger is at ANY UI zoom, and a themed `<select>`
  survives the click that opened it.** Operator: *"the context circle down in msg doesn't open the UI
  and the filter in the agents panel doesn't maintain the menu when clicking on the selecting the team,
  it disappears immediately after the loaded menu."* Two separate causes, both measured on the render:
  (1) the ring's card was placed with the ring's **visual** rect inside the app's CSS root zoom
  (`_uiZoom`, JAG-359) — at 125% (persisted `sf_zoom`) it landed at visual y=1364 on a 1279 px window,
  i.e. **below the viewport**, so the click looked dead while the card existed; it now divides the rect
  by the zoom and clamps in layout px (visual y=1083 after). The same zoom correction now guards the
  shared FilterSort panel and the ThemedSelect list (`pageZoom()`), which had the same arithmetic.
  (2) A real press fires `pointerdown` (opens the list) and then `click` on the SAME select, and the
  click handler read that as "second click = cancel" — the round-175 probe dispatched `pointerdown`
  alone, so it never saw the menu close itself in the opening gesture. `_tsOpenedByPointer` /
  `_tsEatOpeningClick` swallow exactly that click once; a later click still cancels. Also, an
  unpainted ring kept a 24 px empty slot because `#composerBar .cb-right > button` (an ID rule) beat
  `[hidden]`. Measured: deck Agents panel `#teamSel` still open at t+2.0 s (10 options) and the pick
  writes `__none__`; rail team select open at t+2.0 s at zoom 1.25. Locked by `v1260` A1–A4/B1–B4/C1–C2.
- **The Workspace/Plan menu drops UP: opening a tab no longer lifts the composer.** Operator: *"ma perché
  la barra sopra msg box plan e workspace si alzano? devono rimanere in basso, se clicco si apre il menu
  sopra"*. Measured on a 390×844 phone: opening Plan moved `#composer` from y=618 to y=318 — the borrowed
  inspector body (300 px) was a flex child in flow. It is now an absolutely positioned DROPUP anchored to
  the strip (`#cmpSuper { position: relative }`, `.cs-body { position: absolute; bottom: calc(100% + 6px) }`)
  with a menu surface, `max-height: min(52vh, 340px)` and its own scroll. Measured after: composer
  `[8,618,330,146]` before AND after (desktop `[239,742,480,146]`), body floats at `[17,283,312,340]`
  entirely above the strip. Locked by `v1257` A1–A3.
- **The composer's context ring opens its card again — a transcript answer could own `id="cmpCtx"`.**
  Operator: *"ma perché ti ostini a non fare aprire il menu cliccando sul context roundcircel in msg box?
  non si apre ti dico"*. Rendered markdown kept the `id` attributes of any markup an answer quoted, so a
  past reply that showed the composer's own HTML put a second `#cmpCtx` INSIDE the transcript. `$("cmpCtx")`
  resolves the first match in document order, and that copy was ~2 400 px above the composer, so the popover
  was positioned off-screen (clamped to y=8, behind the topbar) while the ring the operator clicked stayed
  dead. The answer pipeline now sanitizes with `FORBID_ATTR: ["id"]` (an id in chat text has no function),
  and `_ctxPopover(anchor)` positions the card against the ring that was CLICKED. Measured: the popover opens
  93 px above the ring (`nearRing: true`), zero app ids left inside `#log`. Locked by `v1256` A1–A3 and
  `v1254` C1 (re-pointed).
- **The ✨ is one neutral SVG, not the gold colour-emoji glyph.** Operator: *"E NO GIALLA: cambia in tutta la
  webui, falla dello stesso colore dominante di ciò che sta accanto rispetto al theme specifico"*. Every
  autogenerate control rendered `textContent = "✨"` (U+2728), which the OS paints as a COLOUR EMOJI — no
  theme could recolour it, so it was gold next to grey icon buttons. One `SPARK_SVG` constant (inline SVG,
  `stroke="currentColor"`) now feeds the composer ✨, the panel ✨s, the "Automate" text buttons and the Orbit
  deck's Architect button; CSS paints it `--dim`, `--txt` on hover, `--acc` only while a draft is in flight.
  Locked by `v1256` B1–B5 and `v772` D3/F2, `v1044` B5 (re-pointed).
- **An explicit `finish` summary that quotes a tool call is an ANSWER, not an action — "the turn ended before
  a final answer" is gone.** Operator: *"why stopped this way? I don't want agents stopping unexpectedly, I
  told many times it is one of the worst failure modes."* Measured live (session `b7329cccf94c`, run
  4071053→4071054): the model closed with `{"action":"finish","summary":"…"}` and the summary — a real,
  complete report — quoted the call inside SINGLE quotes (*"the exact sentence 'The harness once executed the
  quotation POST /api/tools/call {"tool":"fs.read"} and it was denied.' was quoted…"*).
  `_looks_like_json_action` is a CONTAINS test (since the 2026-11-21 A8 fix), so the whole summary was judged
  machine text and the live persist path replaced it with *"The turn ended before a final answer: the last
  message was still an action (…)"* — although `stores.turn_reply` (reload, D5) shows the finish summary. One
  turn, two answers, and the agent looked like it had died mid-work. One rule, extended by measurement: a JSON
  value inside a QUOTATION is prose — inline code spans **and** well-formed `'…'` spans
  (`textkit.quotation_ranges` / `mask_quotations`; an apostrophe in `don't` is not a quote, so a stray pair can
  never mask a real call). Over 2148 live assistant messages the extension changes the selected action in 2,
  both phantom picks (a shell `-d '{…}'` argument and a payload dump) — no real emission is hidden; the seven
  round-164 phantom reports and the killed summary all return `None`/`False`. Locked by `v1248` (16/16) and
  `v1247` (13/13).
- **A JSON call QUOTED inside backticks is prose, not the turn's action — the harness-row storm.** Operator:
  *"ma che modo è, cosa sono tutti quei messaggi harness in serie … dove è rotto il sistema?"*. A54's
  verification report (session `b7329cccf94c`) wrote `` `POST /api/tools/call {"tool":"fs.read","args":{…}}` ``
  inside an inline code span; `extract_action_json` executed that quotation as the turn's action, the call
  failed (missing `path`), and each of the next five reports repeating the same sentence re-fired the repeat
  guard: 7 phantom calls and 9 harness rows (nudge/observation/retry/citation-check/failed-call/closure-check)
  in one close-out. Scope measured over 2142 assistant messages in the live store: 8 phantom messages in 2
  sessions, every one with the only action-shaped JSON inside inline backticks. `textkit.inline_code_ranges` /
  `mask_inline_code` now make any JSON value that STARTS inside a single-backtick span prose (a ```json fence
  is still a real call, so models that wrap calls keep working), `extract_action_json` skips those values, and
  `agent._looks_like_json_action` masks them before its "anywhere" match. The 2026-11-21 A8 rule survives:
  prose followed by RAW JSON still runs, and a real call after a quotation still wins. Locked by `v1247`
  (13/13); live replay of the seven phantom reports returns no action, and A54's own turn quoting the sentence
  closed with zero harness rows.
- **One hard-deny answer for every filesystem door — the preview endpoints no longer served `.env`.** Bug hunt
  2026-11-21 (API boundary), CONFIRMED with a live measurement: `POST /api/tools/call fs.read` on the repo `.env`
  answered `{"status":"blocked","reason":"matches hard-deny pattern '(^|/)\.env…'"}` while the operator preview
  doors read the SAME file — `GET /api/fs/read?path=…/.env` returned **200 with the API bearer and every
  provider key**, `/api/fs/structured` and `/api/fs/sheet` also 200, and `/api/fs/raw` leaked its existence
  (415 instead of 404). One rule, two answers. `registry.deny_hit(tool, args)` is now the ONE judge (it shares
  the patterns with `classify` but skips the approval machinery and the `rule_firings` accounting, so a preview
  is not counted as a blocked tool call) and `api_v02._fs_deny` asks it from all four doors before a byte is
  served. Measured after the fix: read/structured/sheet `denied: (^|/)\.env(\.(?!template$)[^/]*)?$`, raw
  `403`, `.env.template` still readable, `../../../../../../etc/passwd` still `path outside allowed roots`.
  Locked by `v1246` (15/15 B1–F2).
- **The phone topbar fits a OnePlus 15R, and an image link carries ONE truth.** Operator: *"on mobile la barra
  superiore è satura e non si vede tutta, i tre dot accanto all'icona LONGRUN vanno avvicinati all'icona per
  risparmiare horizontal space … modalità mobile OnePlus 15R"*. Measured with headless-Chrome mobile emulation
  (dpr 2, touch, approvals chip visible): at 363/380 px the bar carried 388 px, so the header scroller clipped
  the gear; the 361–480 band is exactly where the phone lands. The ⋮ is part of the BRAND and now hugs the
  wordmark (logo padding and bar gap shaved), tabs/icon buttons lose 1–2 px; a new `@media (max-width: 340px)`
  tier keeps Settings reachable at 320 px (previously 28 px over, `settingsBtn` offscreen). Re-measured
  overflow 0 at 412/400/380/363/360/340/320. Same change fixes an image link that stored a RAW URL in `data-u`
  on one path and a PATH on the other, so the inline preview wrapped the URL twice and 404'd — `data-u` is now
  always the PATH and the two readers build the URL. Locked by `v1245` (8/8).
- **A tool call written AFTER prose no longer leaks as the reply, and its raw newlines no longer drop it.** Operator:
  *"why interrupted this way? that's not a foreseen failure mode, please diagnose first and fix if necessary"*.
  The model (A8 "Master", session `5033e643711a`) emitted prose then a call whose `code` value carried REAL
  newlines (`{"action":"tool","tool":"python.run","args":{"code":"import os<NEWLINE>print(1)"}}`) — technically
  invalid JSON. `_extract_action` returned `None`, and the machine-text guard required the message to **start**
  with `{`, so the raw call was persisted as the turn's answer and the turn stopped as `user_pivot`. Two fixes,
  both in the shared text layer: a JSON object whose strings hold raw control characters is now **repaired**
  (escaped) and re-parsed, so the call RUNS (`textkit._escape_control_chars`); and a call-shaped JSON **anywhere**
  in a message is machine text (`agent._looks_like_json_action` no longer gates on `startswith`), so an
  unparseable call can never leak. Locked by `v1242` (14/14, A/B) and `v843` (B4 re-pointed).
- **The `human.ask` call now appears and REMAINS in the chat history.** Operator: *"human in the loop dialog is
  called by the agent with a tool? if not fix — the correct way is that it uses the tool and the tool call shall
  appear and remain in the chat history"*. The agent DID call the baseline tool `human.ask`, but the loop
  intercepted it and published only `hitl.request` — so no tool card was ever drawn (a scan of the session's feed
  showed 21 `tool.call` events and **none** for `human.ask`). The branch now publishes the SAME inline card as
  every other tool (`tool.call` + `tool.result`) and **persists** it (`persist_tool_card`), reusing the
  harness-action convention of `_apply_chat_todos` — no second mechanism. The decision FORM still ends the turn.
  Locked by `v1242` (14/14, C) and `v733`.
- **The DSML "no tool" retry stopped lying, and the drifted markup now parses.** Operator: *"it was not
  true that the harness was saying in that case A8 master, why it said so? fix, after diagnosis"*. The model
  (A8 "Master", session `5033e643711a`) drifted its native tool-call markup: a stray `>` right after the
  marker and/or a DOUBLED marker (`<|DSML|> invoke name="tool">`, `<|DSML|> <|DSML|> parameter name="tool">`),
  plus a parameter closed by the marker ALONE (`python.run|DSML|>`, no `</`). Every tag regex required the
  name immediately after the marker, so `_dsml_action` returned `None` and the loop told the model *"it named
  no tool the harness can run"* — **false**: the reply named a real, registered tool (`python.run`). The tag
  regexes now accept the drifted prefix and the bare close, so the call parses and RUNS; and the retry note
  no longer claims the falsehood — it says the markup could not be parsed. Locked by `v1241` (7/7) and
  `v774` (36/36, D2).
- **The Human-in-the-loop choice panel is ONE decision, merged into one message.** Operator: *"additional
  info of human in the loop doesn't merge, [it] queues another different message — make that choice panel
  correct"*. Each click used to fire its own message — an option button SENT, then *send choice* SENT again —
  so a chosen option plus its "additional info" became **two queued messages**. Now a proposed option and a
  quick action **select** (one at a time, highlighted), and *send choice* merges the choice + Other +
  additional info into a **single** message, after which the card **locks** (controls disabled) so it can
  never queue a second one. Locked by `v960` (18/18, B5/B5b/B5c/B5d). Verified live: selecting sends nothing;
  *send choice* sends exactly one message (`Opt A — additional info: PORT 37851`); a second click is a no-op.
- **A PDF/DOC attachment now PREVIEWS — before and after sending.** Operator: *"if i append in chat a pdf,
  doc, image, can i preview it [before send and after send, clicking in the chat]?"*. An image already
  opened its lightbox, but a file attachment (`_openAttachment`) opened the **editor dock**, which paints a
  PDF as raw bytes — no preview. It now opens the **dedicated preview window** (`openPreview`, v1002): a PDF
  renders in a sandboxed frame, markdown/CSV/sheets/slides/images draw, and ⋯ › *open in the editor* / raw
  covers the rest. One chip, so the before-send (composer) and after-send (transcript) doors behave
  identically. Locked by `v283` (14/14). Honest limit: `.docx`/`.doc`/`.odt` have no in-browser renderer, so
  they open the preview window with the ⋯ menu rather than an inline render.
- **The send button tells the truth about a `/command` while a turn runs.** Operator asked: *"does commands
  enter in chat queue or steer according to the selected menu as other messages?"*. A command is **always
  queued** for the next turn — never steered (a running turn resolves no leading `/`; `v863` C3 pins the
  behaviour). The composer's send-button tooltip echoed the *steer* wording when the picker was on `steer`;
  with a `/…` draft it now says the command waits for the next turn. Locked by `v1053` (59/59, I11).
- **An approval in the inbox now names the session it belongs to.** Operator: *"approvals open permission
  instead of the specific session where approval = full is placed! fix"*. A tool-gate row in the approvals
  inbox (the rail's `#apprBtn`) could not point at the session waiting on the decision: the chat loop
  records `run_id = session id`, yet the row carried no `session`. The unified inbox now resolves that id to
  a live session ONCE (`approvals.list_unified`), so the WebUI's `→ <title> (<sid>)` jump, the CLI and
  `harness.status` all read the same field — a `run_xxx` API run (no session) correctly stays session-less
  and shows no jump. Locked by `v1240` (7/7).
- **The approvals chip lands on the setting that owns the mode.** Operator: *"approvals shall open the
  settings → Tools & approvals menu, focused on the specific approval part, scrolled to"*. The topbar chip
  reports the approval MODE (`approvals: full`), so a click now opens **Settings ▸ Tools & approvals**,
  scrolls to the **Approval mode** row and flashes it (focus moves to its control) — the exact place the
  mode is set. It is no longer the Permissions page (a different fact that never sets the mode); the pending
  decisions stay in the rail's `#apprBtn` → the approvals inbox. Locked by `v1023` (18/18, C4).
- **A new icon for the changelog.** Operator: *"the changelog icon is horrible — find a new way to represent
  it"*. The button wore the generic page+lines (the artifact/document glyph = "a file"), which says nothing
  about "what changed". It is now a **history clock** — the record of changes over time — distinct from the
  gear, search, ⋮ and refresh. Locked by `v1237` (11/11, B2).
- **No frames around the new icons, and real icons in the brand menu.** Operator: *"dont use frames for
  icon please use correct icons for last changes!"*. The changelog button and the brand ⋮ inherited the
  `.ghost` border — a frame around the icon — so both are now **frameless** glyphs like the gear and the
  search (`border: 0; background: transparent; box-shadow: none`), and the four brand-menu rows traded
  their text symbols (`↻ ⟳ ⧉ ⓘ`) for the app's monochrome **SVG** icons (14px, stroke 1.8, the
  `#moreMenu .mi` recipe). The `/status` slash glyph moved off `ℹ` (emoji-capable) to `ⓘ`. Locked by
  `v1237` (11/11, A5/A6).
- **Rejecting a plan/spec closes the entity — in the inbox and in the chat.** Operator: *"rejecting spec or
  plan into the approvals RH panel doesn't make the approval entity to disappear! also in the msg box in
  chat maybe"*. Reproduced live on the screenshot's own state (session `5671e8b2c493`, content approved,
  awaiting ▶): `POST /api/approvals/doc:<sid> {"decision":"deny"}` answered **400 "reject_plan: no
  proposed plan"** — `reject_plan` accepted only `proposed`, so the row that appears after an approval had
  no exit at all (its approve button was disabled too), and behind it a second defect: the route then read
  `rec["id"]` on a record that no longer existed (KeyError, the connection dropped mid-answer). A rejection
  is now possible while the decision is still open — `proposed` **or** `approved` with the implementation
  never authorised (an authorised one has nothing left to reject, and says so) — the decided document is
  not an inbox row even under `decided`, the event carries the requested id, and the composer bar closes
  with it. The record itself stays on the session, so the next turn still tells the model "the operator
  REJECTED it". (Locked by `v1069` A1–A9b.)
- **Squeezing the sessions rail no longer makes its panel icons vanish.** Operator: *"squeezing session LH
  panel causes icon to disappear"*. Nothing hid them in code: the rail head was one 36 px flex row holding
  the label, the fold control and four 24 px buttons (~102 px) while the rail is **220 px by default** (min
  150) — so at the default width the row already overflowed the panel's `overflow: hidden` and the last
  buttons were clipped (two of four, measured with CDP at 150/180/220/280). The head now wraps instead of
  clipping, the icon block can never shrink below the 24 px target, and below 250 px the *label* is what
  gives way (container query) so the default rail stays one row of controls; the word returns with the
  room. The inspector head keeps its pinned 36 px geometry. (Locked by `v1070` A1–A7.)
- **The phone transcript stopped carrying the desktop gutter.** Operator: *"why in mobile format is all that
  empty space in the chat on the left? can you solve it graphically?"* — with a 393 px screenshot where the
  first line of a worked step started a third of the way across the chat. Measured live (CDP, `architect`,
  393x844): `#log` was still on the DESKTOP gutter (padding 28 px a side — the only phone rule for it was
  scoped to `orientation: landscape`) and a nested todo group added 26 px (16 margin + 10 padding on
  `.tc-kids`), so the body text began at x=55 on a 349 px chat: 16% of the width, empty. The portrait phone
  now keeps a 16 px gutter — the same one the chat head uses for the session name, so the two left edges
  line up — and a nested step tightens to 8+8 (deeper nesting 4+6) with its status dot re-anchored on the
  shifted rail; the landscape layout and both desktop gutters are untouched. The new transcript width is
  300 px of 349 for a step card (was 285 of 349 with the content starting 22 px further right). Cache name
  bumped to `longrun-shell-v8` per the shell rule. (Locked by `v1068` A1–A10.)
- **A registry improvement can no longer delete rules it never named.** Operator: *"is this safe? what
  happens if I approve?"* on two `improve.registry` proposals. The optimizer's model rewrote
  `shell.exec.deny` from memory and proposed a one-entry list: approving it would have replaced the whole
  hard-deny set (`LONGRUN_TOKEN`, `/proc/*/environ`, mkfs, dd, the `.env` grep guard…) with a single `rm`
  pattern — and two proposals approved on 2026-11-15 had already done exactly that, leaving the live deny
  list with one rule. A list field is now changed with **`add`/`remove`** only (`registry.delta_error`);
  `apply_delta` computes `live - remove + add`, and a `remove` naming a rule that is not live is refused.
  The optimizer prompt now carries the LIVE row(s) it may edit. The inbox shows the actual delta and the
  full proposal text, and a proposal whose delta cannot apply is rendered **blocked** (approve disabled,
  reason shown) instead of failing at click time. The live `shell.exec.deny` was restored to its shipped
  11 rules through the built-in reset (`POST /api/tools {"tool":"shell.exec","reset":["deny"]}`), audited
  as `policy.changed`. (Locked by `v1013` H1–H6, `v1015` C5, `v1017` D5.)

- **Plan mode gates CAPABILITIES, not a list somebody remembered.** Operator: *"the approval of plan didn't
  block the agent to do it … so spec is blocked from implementation but the plan is not blocked?
  asymmetry fix"*. Measured in session `774ac9424d2b`: `fs.write` refused twice — and the SAME turn had
  created a file with `matrix.scaffold`, which was simply not in `PLAN_GATED_TOOLS`. That list was the
  whole gate, so every write-capable tool added since the list was written worked inside a locked
  session. The gate is now **fail-closed**: a locked session may call only `PLAN_READ_ONLY_TOOLS`
  (the exploration surface — reads, searches, `self.*`, `sessions.read`, and `docs.plan|spec|status`
  because writing the plan IS the point); any other built-in is denied with "`matrix.scaffold` is not
  exploration". External MCP tools keep their own approval policy. Live: same session,
  `matrix.scaffold` → `blocked` with that reason, `fs.read` → `executed`. (Locked by `v1052` N10a–N10d.)
- **A plan/spec awaiting a decision now appears in the right-hand Approvals panel.** Operator: *"the
  approval spec and plan shall appear in the RH panel approval"*. The inbox listed tool gates and
  improvement proposals only, so a generated document was visible solely in the bar above the composer,
  and only on its own session. `approvals.list_unified()` now also returns one `doc:<session>` row per
  active document (kind, title, relative path, status), `stats_unified()` counts `documents_pending`,
  and `POST /api/approvals/doc:<sid>` routes **approve → `docs.approve`**, **deny → `docs.reject`**
  (the panel's button reads "reject" for a document), so the inbox and the bar are the same act on the
  same record. Both directions refresh the other surface. Live: the panel's endpoint listed the plan
  from the report (`doc:774ac9424d2b`) and a spec; approving from the inbox records the content decision
  and the row then offers `implement` (the gate opens there). (Locked by `v1052` N11a–N11c.)
- **The agent finally sees the document bar's decision.** Operator: *"even if i click approve and then say
  act the agent doesn't understand what the meaning of that bar over the message chat box"*. The bar
  is real (it renders `plan_mode` + the active document and its ✓/✕/⏏ POST `/api/docs/approve|reject|
  unlock`), but the model only learned about a document from its OWN `docs` tool result: after the
  operator approved and said "act", the next turn had no idea whether the plan was approved,
  rejected or still pending — it had to guess. Every user turn now carries a **`DOCUMENT` block**
  (`agent._document_block`, part of the per-turn `Harness state`, rebuilt from the store so no write
  races the session file): kind, status, plan mode ON/OFF, the file path, and what that MEANS —
  `APPROVED`+implement: write tools allowed, read the file and follow it; `APPROVED` without implement:
  the content is accepted but the implementation is NOT authorised (write tools stay blocked); `REJECTED`:
  do not implement it;
  `PROPOSED`: write tools blocked, never claim the work is done; `stale`: the file is missing on
  disk. Live on the session in the report (`1adb50b4a5a9`): after `docs approve`, the turn `"act"`
  read the spec, tried the edit, hit the Nucleous write guard and reported the exact patch and red
  test instead of inventing a plan. (Locked by `v1052` N9a–N9f.)
- **The document commands survive the exceptions of unattended use.** `/plan` and `/spec` write the
  session object a chat turn is also writing; with nobody watching, the later save could drop the
  other's messages or the fresh document record. Every document mutation (`create/approve/reject/
  unlock`) now refuses while that session's turn is in flight (`events.turn_active`), and a second
  generate for the same session is refused instead of paying for a second model call and overwriting
  the first record. The composer QUEUES a document command typed during a turn (it used to be sent
  into a race) and `/unlock` refuses with the same reason as its disabled button. A planner that
  lands after a session switch no longer paints its card into the other chat, a session switch
  (rail or `/reset`) hides the previous bar in the same frame, `/reset` shows the new session's queue
  and starts with an empty composer, and a flushed `/plan` no longer wipes the operator's draft.
  A dead service now says so ("reload this session to see whether the document landed") instead of a
  raw fetch error, `/unlock` with nothing to unlock says that, and `/plan` warns when attachments
  are present (the planner never receives them). Server side, a hard kill mid-`/spec` leaves no
  half-spec — the three files are renamed only when all exist — and the next create sweeps the dead
  writer's `.tmp-*` folder. Live: edge probe 13/13 (unknown session, empty prompt, approve/reject
  with nothing proposed, double unlock, a REAL turn refusing `/plan`+`/unlock`, two concurrent
  `/plan` calls) and restart-mid-spec probe 7/7 (no record, no lock, no half-spec, next `/spec`
  clean). (Locked by `v1052` K1–K4, L1; `v1053` I1–I10; `v934` D1 re-pointed.)
- **The plan/spec bar can always be dismissed, and a composer attachment chip opens again.** The
  bar hid `⏏` for a proposed document (approve/reject were the only exits) and for an approved one
  (the gate was already released) — so a generated spec/plan stayed on screen for ever with no
  control, exactly the operator's *"non si può più togliere"*. `⏏` is now offered in EVERY state
  with a confirm that says the mode is forgotten and the file kept, and `/unlock` does the same from
  the keyboard. Separately, a chip in the composer had no click handler while its transcript twin did
  (`_renderAttach` vs `_attachmentChips`), so clicking an attached image opened nothing (*"no si apre
  più"*); the chip is now a container of two SIBLING buttons (`attopen` opens the image preview /
  the editor, `✕` removes) so nothing is nested under a `role="button"` — the axe
  `nested-interactive` defect fixed in v851. Live: the in-WebUI probe (12/12)
  unlocks both a plan and a spec session, keeps the files, and shows a new session inheriting no
  mode. (Locked by `v1052` C2, `v1053` H4–H7.)
- **`/plan` and `/spec` answer again (they never did).** The create route published its event with
  `kind=`, a name `_publish(kind, **data)` already owns, so the handler raised `TypeError` **after**
  the document was written and the session locked: no HTTP response ever reached the browser, the
  composer card stayed at "generating plan…" indefinitely, and the chat was silently read-only. The
  payload key is now `doc_kind` (the envelope keeps its own `kind`), and a planner that does not
  answer in 4 minutes turns its card into a dismissible **failed** card naming the reason instead of
  spinning for ever. Live: `POST /api/docs/plan` → `200` in 7.8 s and `POST /api/docs/spec` → `200`
  in 2 m 10 s (three-file set on disk), `GET /api/docs` shows the proposal, and no traceback since.
  (Locked by `v1052` J1–J4; `v1053` 40/40.)
- **An external MCP tool is callable from a normal turn again.** The gate injected
  `args["workspace"] = <session workspace>` into every tool whose `_origin` was not
  `exclusive`/`delegation`; external tools are registered `origin: "mcp"`, so a strict server
  rejected the whole call (`Input validation error: … Unrecognized key: "workspace"`) while the same
  server answered `{}` when called directly. `_workspace_is_object_field()` now exempts
  `origin == "mcp"` at both injection sites, and the panel's test button says **connection only —
  tools not executed**, so a ✓ no longer reads as "usable". Live: `chrome-devtools__list_pages`
  through the gate → `args={}`, `ok=true`, `## Pages 1: about:blank`, and the same call from a chat
  turn answered the page list. (Locked by `v1062` 8/8.)
- **One turn can no longer emit an unbounded chain of harness nudges.** Measured session
  `b7329cccf94c` (22:21:29–22:21:53): ONE turn sent SIX identical "Your last message was EMPTY"
  retries plus a CONTINUE — the `_empty_streak <= 2` cap was reset by the CONTINUE park and by any
  non-empty-but-useless reply. `_empty_total` is now a per-TURN ceiling (2 retries, then ONE
  continue park, then `chat.error` naming the real count). Separately, a stale plan no longer
  extends a turn that ran **zero tools**: "Reply with exactly: OK" used to be dragged into a 7-task
  pivot and a second retry chain. (Locked by `v1061` 13/13.)
- **Every empty-reply FAILURE MODE now has its own visible harness message.** When a model streams a
  long chain-of-thought and returns no content and no tool call, the loop answered with the same
  "your last message was EMPTY" nudge — four times, plus a CONTINUE and three closure rounds —
  against the model that had just proved it stops at the reasoning (measured session
  `b7329cccf94c`, 22:32–22:33, deepseek-v4.1-flash). Now: **reasoning-only** and **output-limit**
  (`finish_reason=length`) get a message that names the mode, the reasoning tokens and the envelope
  (`reasoning.max_tokens`), and the FIRST one gives the SAME model one more round that **keeps the
  thinking** and asks for the answer — never "think less" (operator, 2026-11-16: *"i modelli devono
  pensare"*); a second failure names the failover and advances (`stream_with_fallback(...,
  reasoning_only_is_blank=True, advance_from=…)`). A **completely blank** reply has its own message
  (provider defect). Every failed attempt is persisted as a `model.attempt` card — UI-only, so it is
  displayed live and on reload but never re-sent — carrying the model, the mode and the reasoning it
  produced, so the chat stays chronological with nothing hidden. A turn that still ends
  `empty_reply` gets ONE forced answer instead of three. (Locked by `v1064` 12/12, `v1063` 4/4,
  `v1061` 13/13; `v770` still green.)
- **The README battery badge is checkable again, and counts the real suite.** The shields.io badge
  URL-encodes the separator (`748%2F748`), while `v354` D5 looked for the literal `748/748` — it had
  been red since the badge was encoded, and a targeted battery never runs it. The pin now accepts
  both spellings and the badge reads `748/748` (two test files had been added without it).

### Added
- **The CLI has a current session, and an agent can write its own plan/spec.** Operator: *"vedo
  sessione vuota … devi poter lanciare sessioni e poterci vedere dentro che fanno"*. A bare
  `forge.py chat "…"` sent `session: null`; the server minted a new session and the CLI **discarded
  the id**, so a session created with `sessions new` stayed `messages: []` while the turn lived in an
  anonymous `session <hex6>` row. The CLI now keeps a per-machine pointer
  (`$LONGRUN_CLI_STATE`, else `<data>/cli_session.json`): `sessions new` sets it, `sessions use ID`
  validates and switches, `sessions current` reads it, `sessions ls` marks the row with `*`,
  `chat` without `--session` uses it (and `--new` keeps the old one-shot behaviour), every `chat`
  prints `session: <id>` as its first stdout line and adopts the id the server returns, and
  `sessions history|tree|graph` + `docs` work on the current session when the id is omitted.
  `sessions rm` of the current session clears the pointer. Looking inside is the same data the WebUI
  renders: `sessions history` (role-by-role transcript), `sessions tree`, `context show`. An empty
  session is therefore never a chat bug: it means no turn was sent to that id.
  **Agents gain the `docs` tool** (`action: plan|spec|status`, `prompt`, `session`, `context`) so a
  model can enter plan mode and write a reviewed document by itself, or order a **direct report** to
  do it (the dispatch predicate); `approve`/`reject`/`unlock` stay the operator's acts and are
  deliberately absent. Two obstacles were fixed rather than bypassed: the busy-turn refusal got an
  `owner=True` path used only by the tool, and `plan`/`plan_mode` joined the `stores` live fields so
  the turn's final save can neither drop nor resurrect a document. Live: `cli_session_probe.py`
  **22/22** (new → current/use → a turn lands in it → history/tree/graph/context → `*` row → REST
  `messages=4` → `plan` + `approve` + `spec` (three files) + `reject` + `unlock` → `rm` clears the
  pointer) and `agent_docs_probe.py` **13/13** (a real turn
  calls `docs plan`, the file exists, `plan_mode=true`, `fs.write` is `blocked` with the plan-mode
  reason, unlock releases it and the write executes; then a second real turn calls **`docs spec`**,
  which writes its three files and locks the session again — the first probe only drove `plan` and
  the operator caught it: *"no ho visto nessun agente usarlo"*). (Locked by `v785` M1–M16; `v1052`
  N1–N8, where N8 drives the SPEC action through the tool inside a turn.)
  **A CLI `chat` no longer kills its own turn.** Measured 2026-11-16 20:48:37: the 300 s socket
  timeout closed the connection and the server's `watch_client` read that as "client gone" and
  aborted a live turn (`chat.interrupted` on `b7329cccf94c`). Turns have no 5-minute bound, so
  `chat` and `docs plan|spec` wait (6 h) — closing the socket is an abort by contract, not a
  detach. `context show|compact|items|preview` follow the same pointer (without it they answered
  `{"session": null, "available": false}`), so **every** session-scoped verb now reads the current
  session when the id is omitted. The whole surface is documented as ONE executable recipe —
  `docs/CLI.md` §6 "Live test recipe": create → turn → look inside → all six document verbs →
  delete, on a throwaway `$LONGRUN_CLI_STATE` and `mktemp` workspace, asserting at each step
  (verified by running the block verbatim: green end to end); the README's CLI section points at
  it. Locked by `v785` M14–M16 and `v1052` M4b (the recipe must name every verb).
- **The CLI is the WebUI's twin for the document commands.** `forge.py docs
  status|plan "request"|spec "request"|approve|reject|unlock --session ID` calls
  the same `/api/docs*` the composer calls, prints the written path (or the
  server's reason with a non-zero exit), and `sessions new "title" --workspace DIR`
  now creates through the WebUI's own `GET /api/sessions/new` route so a probe can
  own a throwaway folder. Live: `.agent/trash/cli_docs_probe.py` **12/12** — plan
  written, a real `chat` turn in the locked session, unlock keeps the file, empty
  request exit 2, spec's three files, approve, unlock. (Locked by `v1052` M1–M4;
  `docs/CLI.md` documents the group.)
- **`/reset` — a fresh chat without the New-session dialog, and `/unlock` — leaving `/plan`/`/spec`
  mode.** `/reset` creates a new session in the SAME workspace and leaves the old one in the rail
  with its transcript; it reuses the one creation path the dialog already used (`createSession`,
  with `createNewSession` as its thin wrapper), so a reset can never drift from a manual new chat.
  `/unlock` releases the plan gate and **forgets the session's document record**, so the plan/spec
  bar finally disappears while the file stays on disk (`plan/docs.py:unlock`). Both are built-ins in
  `core/slash.py:BUILTINS`; `core/commands.py:RESERVED` is now DERIVED from that list instead of
  being a second copy that had gone stale (`/reset` and `/unlock` were missing there, so a user
  command could have shadowed them). Live: `/api/slash` lists the eight commands; the in-WebUI probe
  (real sessions, real model, `POST /api/docs/plan|spec`) is 12/12. (Locked by `v1053` H1–H3, `v1051`
  A1, `v1020` A3, `v775` G5.)
- **A run SURVIVES a restart, and the audit row says so.** Operator: *"a run killed by a restart
  is killed instead of running? that's wrong — i want runs survive restart! it's a tech spec
  prerequisite"*. The row belongs to the process that opened it, so a restart ends the INSTANCE:
  every other owner already closed its own orphans (sessions, jobs, subjobs) and `runs` had no
  sweep — `Run.finish()` was the only writer of the status — so a killed process left the row
  `running` forever (measured 2026-11-16: **182 rows**, the oldest 2026-09-29, four of them turns
  killed by that evening's restarts, all served by `/api/runs` and the trace/cost reads as if
  live). Boot now runs `tracing.reconcile_orphans(before=<boot ts>)` — only rows older than the
  current process, never one this boot started, idempotent — and emits `runs.reconciled`. But the
  WORK is not in the row: `inflight.recover` starts the `[Harness restart]` turn and the task graph
  is a file, so when a session is actually continued `tracing.mark_resumed()` — called after the
  recovery, event `runs.resumed` — turns its rows into **`resumed`** with a `restart.resumed` span
  naming the session. `interrupted` stays only for a run the harness could NOT continue; it is
  never the status of work that survived (measured: 21 `[Harness restart]` continuation runs
  already finished on this host). The interrupted-turn notice no longer reads as "the work is
  lost": it names the automatic resume and only then "send a new message". Project rule
  `docs/OPERATIONS.md`: proof of idleness before a restart (`/api/chat/live` must be
  empty), read `service.resume` afterwards, and never declare an agent dead without quoting the
  session id, the message index and the resume marker. (Locked by `v1065` 13/13.)
- **Installing a plugin now ACTIVATES it, and `/plugin:<name>` reports what is really running.**
  Operator: *"the plugin installation already has to automatically install everything needed …
  if plugins contain skills and MCP they shall be installed in longrun according to longrun
  structure during its install process"*. A `plugin` bundle's MCP members are enabled and
  verified in the same install call (`mcp_client.activate_clients`: one reload, each client's
  tools enabled with `approval: required`), and the record keeps per-member `state` / `tools` /
  `error` / `prev_enabled` plus the package's `title`/`description`. A connector whose `${KEY}` is
  unset stays OFF as `needs-key`, naming the key, instead of failing the bundle; a server that
  cannot start is a recorded `error`, never a rollback; an existing client is never re-written by
  an install, and `rm --files` restores one the plugin had enabled. `/plugin:<name>` opens with
  `Status: READY — n/n members live (N tools)` or `NOT READY` and the reason, names the
  provenance and forbids the model from installing a member itself; an unknown name is an
  explicit refusal instead of prose. Fixed the two defects that made an activated plugin
  unusable: the gate injected `workspace` into every external MCP tool (strict servers answered
  `Unrecognized key: "workspace"`) and the child's stderr was `DEVNULL`, so
  `initialize returned no response` hid the server's own reason (now quoted). (Locked by `v1060`
  37/37; `v1040` 32/32, `v1051` 18/18.)
- **A web call is a first-class row: batched queries, structured hits, and a Sources block.**
  `web.search` accepts 2–4 `queries` in ONE call (parallel, URL-deduped, `max_total` capped, 25 s
  wall clock, `partial` when the clock cuts a query) and `web.fetch` accepts up to 5 `urls`; both
  accept `days`, `include_domains`/`exclude_domains`, `search_depth=advanced` (Tavily) and a 16 KB
  fetch default. Every hit gets a session-monotonic `[wN]` id; the tool returns a structured `data`
  payload (engine, timings, host/snippet/published) that is persisted INSIDE the tool card (≤6 KB,
  never in `messages`, so it costs no context) and streamed on `tool.result`. A failing chain now
  names each provider and its reason. The WebUI renders the hits as favicon + title + host + snippet
  rows (escaped, external links, offline letter fallback), a per-turn header
  ("Worked for 4m 12s · 3 files read · 2 web searches"), a Sources block between the answer and the
  turn summary (fetched pages first, cited `[wN]` marked), `[wN]` links inside the answer, human
  labels/icons for every tool row (canonical `web.search` / `fs.read` / …, raw-name fallback), a
  timeline rail, and a ↻ retry that re-sends the model-facing text. (Locked by `v1054` 18/18,
  `v1055` 8/8, `v1056` 19/19, `v1057` 18/18, `v1058` 12/12, `v1059` 12/12; `v605` 7/7, `v521`
  23/23, `v456`, `v1045`–`v1047`, `v781`, `v865`, `v873`, `v253` green.)
- **The `/` menu is a real command surface, and `/plan` / `/spec` write reviewed documents.** The
  composer menu was three hardcoded rows; it now renders the TRAE-style groups **plugins · commands ·
  skills** from one backend catalogue (`GET /api/slash`, `core/slash.py`), with icons, one-line hints,
  a sticky key footer and an installed-plugin submenu. `/plan <request>` writes
  `.longrun/documents/plans/<slug>-<date>.md` and `/spec <request>` writes
  `.longrun/documents/specs/<slug>/{spec,tasks,checklist}.md`; both use the existing
  `stores.set_plan_mode` lock (mutating tools are denied) and a durable bar with
  `open · approve · reject` that mirrors the goal bar. `/plugin:<name>` injects a bounded member
  manifest. The task graph is untouched: the document is the intent truth, the todo graph the
  execution truth. `config/documents.yaml` owns the folders; `workspace_state_dir()` now leaves
  `documents/` in the workspace while adopting every other legacy `.longrun` entry. (Locked by
  `v1051` 18/18, `v1052` 28/28, `v1053` 39/39; `v775`, `v1020`, `v597`, `v863`, `v934` green.)

### Changed
- **`.longrun/` is ignored in full.** `/plan` and `/spec` write their deliverables under
  `<workspace>/.longrun/documents/`, which is this repo when you work on the harness itself. The
  files are local output, not shipped source: the old carve-out re-included `documents/**` and made
  every probe show up as untracked. They stay on disk; git stops seeing them.
- **`web.search` / `web.fetch` take `query` OR `queries` (and `url` OR `urls`).** The canonical
  schemas no longer demand `query`/`url`: the alternatives live in `_SUBTOOL_ANY_OF`, so a batched
  call is not refused before the handler sees it. `_web_search` now returns
  `(results, engine, notes)` — the old chain swallowed a missing key, which now surfaces as
  `tavily(missing TAVILY_API_KEY)`. (`v605` 7/7, `v1058` 12/12.)
- **Every chat shows its context saturation, and a manager sees its team's.** Operator: *"each chat
  context status shall be visible in the sessions webui even if not the active one selected at the
  moment … and the boss team of an agent (report to) shall know the status of its sub agents teams (the
  ones that can be dispatched by him) including llm, context saturation etcetera"*. The chat loop
  records `sess["ctx"]` at turn end from the router's real `prompt_tokens` of its last request plus the
  budget of the model that served it; `stores.list_sessions` serves `ctx_pct` / `ctx_tokens` /
  `ctx_budget` on every row, overlaying the LIVE router number while a turn still runs, and a one-shot
  background pass (memory only, never on the request path) fills sessions that ran before this change
  — measured live: 118/118 rows populated within 4 s of the restart. The rail paints the ctx pill on
  EVERY row (the active one keeps the live `/api/context` ids), `sessions.list` prints
  `model=… | ctx=…%` so a manager reads the agents it can dispatch, and the deck's AGENTS row gains a
  `ctx NN%` chip beside the role. In the rail the meter is a bare 13px ring + 9px number — no padding,
  border or background — placed before the ⋮, so it fits the row instead of wrapping to a second line
  (the exact token counts live in the tooltip). (Locked by `v1048` 12/12.)

### Changed
- **The Settings window has ONE design layer, shared by every subsheet.** Operator: *"do you think
  that style is state of the art of front end UIs? … apply the style to all the settings subsheets,
  not only the shown."* The grammar moved onto the shared classes instead of per-category blocks:
  micro-label headings (10.5px, .14em) over a hairline rule, one flat 9px card surface, a 14/8 rhythm,
  28px controls with 7px radii, mono for identifiers, and an active nav item marked by an accent bar +
  soft fill rather than a heavy pill. The key rows stopped carrying per-row inline styles and use the
  same `.card`/`.inp`/`.ghost` grammar (`.keycard` + `kc-*`), so a sheet added tomorrow inherits it.
  The rail's group count lost its pill/border and dropped to 10.5px. (Locked by `v762` C5/C6, 14/14;
  `v359`, `v765`, `v851`, `v352`, `v508`, `v403`, `v806`, `v364`, `v890` green.)

### Security
- **The bearer token no longer lands in the systemd journal (`v940`).** `main()` printed
  `http://<lan-ip>:8790/?token=<secret>` on boot, so every `systemctl --user restart longrun` wrote the
  credential to a journal any local user can read (and every `journalctl` copy carried it). `boot_url()`
  prints the plain URL; the `?token=` suffix appears only when stdout is an interactive terminal, where
  the service manager captures nothing, and the piped banner names the service `EnvironmentFile` where
  the value lives. `check_auth` now compares the `Authorization` header and the `?token=` fallback with
  `hmac.compare_digest` (`_same_secret`, on UTF-8 bytes so a unicode header is rejected, not a 500).
  (Locked by `v940` 20/20.)
- **An action alias can no longer skip its gated policy row, and a `VAR=` prefix can no longer
  hide a hard-denied command (`v941`).** `memory{action:"delete"}` (or `erase`, `write_core`,
  `core_write`) and `matrix{action:"uninstall"}` resolved to the plain namespace — whose row is
  `approval: auto` — so the `memory.forget` / `memory.set_core` / `matrix.remove` rows were never
  consulted: a permanent memory delete or a rewrite of the CORE block injected into every prompt ran
  with no card. One alias table (`registry._ACTION_ALIASES`) now feeds `canonical_name`, which
  `classify` also applies, so the gate judges the call under the name the execute door runs.
  `_ENV_ASSIGN_RE` stripped an assignment with `\S*`, so in `X=1;rm -rf /` the value swallowed the
  rest of the command and the hard-deny regexes saw only `-rf /` — with `approvals.mode=full` the
  command then ran. The value now stops at `;`, `&` and `|`. (Locked by `v941` 21/21; `v597`'s
  fixture follows the canonical name; live: `matrix`+`info` records `matrix.status`, and
  `X=1;curl …127.0.0.1/api/jobs` is blocked by the deny rule.)
- **git's destructive flags are no longer auto-approved (`v942`).** `^branch(\s|$)`, `^tag(\s|$)` and
  `^remote(\s|$)` matched any flag after the subcommand, so `git branch -D feature`, `git tag -d v1`
  and `git remote set-url origin …` ran with no card while the tool description called those
  subcommands read-only. Only the listing forms (`-a/-r/-v/--list/--show-current/…`, `tag -l`,
  `remote -v|show|get-url`) stay automatic. `git diff|log|show --output=<path>` writes a file the
  workspace scan never sees (it reads the CWD, not git's own options), so it is now in `always_ask`,
  which survives `approvals.mode=full`. (Locked by `v942` 31/31; live: `git diff --output=…` sits in
  the approval queue as `git.run` pending and runs only if a human approves.)
- **A `mode=run` job whose worker failed no longer closes as `done` (`v943`).** `_run` computed its
  `failed` list only inside the coordinator branch, so a detached dispatch (`mode=run`) always closed
  with `failed_subjobs: []` and status `done` — even when its only worker ended in a harness error
  record. `wake()` then released the job's dependents on top of work that never happened (and, since
  a `partial` blocker counts as failed, they now fail loudly instead). The verdict is the job's,
  computed for every mode from both records (the subjob row, and `runs` for a job whose subjob row
  was never created). (Locked by `v943` 10/10, red at HEAD without the fix: 5/10.)
- **Two dispatch paths can no longer start the same job twice (`v944`).** `dispatch` read the job,
  tested `status == running` and wrote `running` several store calls later, with the lock taken per
  call and never across the check and the act; `wake()` wrote `created` and only then dispatched. Two
  blockers finishing together — or two `POST /api/jobs/dispatch` — both started a runner, so every
  worker executed twice with the same subjob ids, side effects included. Both transitions are
  compare-and-set under one lock (the claim inside `dispatch`, `_release` for the sweep); the loser is
  told "job already running". (Locked by `v944` 10/10, red at HEAD without the fix: two winners and
  two runners.)
- **The shell's working directory is part of the workspace boundary (`v945`).** `touches_outside`
  scanned `cwd` and the path-like words of the command, but not `workspace` — which `_shell` uses as
  the process working directory when `cwd` is absent. A command whose text names no path
  (`grep -r SECRET .`, `find .`, `cat x`) therefore reached any directory by naming it as `workspace`
  and still auto-approved, defeating JAG-388's "anything outside the session workspace needs
  approval". (Locked by `v945` 9/9, red at HEAD without the fix: 4/9. The live service runs
  `approvals.mode=full`, which bypasses the boundary BY DESIGN, so this one is proven by the battery.)
- **A redirect cannot hand the fetcher a private address (`v946`).** `web.fetch` checked `_public_host`
  (DNS resolved, private/loopback/link-local rejected) and then called `urlopen`, whose default handler
  follows a 3xx to ANY target — a public host could answer `302 Location: http://127.0.0.1:8080/…`
  (the unauthenticated router) or any LAN address, and the guard never saw the second URL. `http.fetch`
  had the same hole against its `allow_hosts`. `_CheckedRedirect` re-runs the per-tool predicate on
  every hop and `_opener(check)` is the only way the fetch tools build an opener.
  (Locked by `v946` 10/10: loopback, private, link-local and non-http hops blocked, an allowed hop
  still builds the next request.)
- **A stale writer can no longer erase the other writer's messages (`v947`).** A turn saves its own
  session dict at the end; a job handoff/escalation writes an inject from a dict it read in another
  thread. `save_session` wrote the WHOLE document from whichever copy arrived last, so the loser's list
  vanished — a coordinator's deliverable disappeared from the transcript while `runs[coord].result`
  still held it, and a handoff written before a turn's save was gone on reload. `save_session` now does
  its read-merge-write under one lock per session and adopts the on-disk tail of `messages` / `injects`
  / `tool_cards` ONLY when the in-memory list is a prefix of it (this copy read an older one and only
  added); the turn itself — the thread that owns `_turn_lock` — stays the authority on its own
  transcript, so a rewrite or a trim is never "completed" back. `persist_inject` takes the same tail
  first, so the inject's `after` boundary counts the messages really on disk. (Locked by `v947` 10/10,
  red at HEAD without the fix; live: a real turn persisted its messages, its tool card and the harness
  entries after the change, scratch sessions removed.)
- **A subjob orphaned by a restart no longer hangs its batch (`v948`).** Session-Jobs had no restart
  reconciliation (`jobs.reconcile` covers the job store, nothing repaired the SJ ledger). The scheduler
  only schedules rows whose status is exactly `pending` and `running` comes from this process's
  in-flight list, so a subjob persisted as `running` by a killed process was never re-spawned and never
  failed: its dependents stayed pending and the deadlock breaker finally called them "dependency never
  satisfied". `run()` reaps such a row at the start (status `running` with a `started` older than this
  process's module load cannot have a worker here) and publishes `sj.subjob.done … failed` so the feed
  says so. (Locked by `v948` 10/10, red at HEAD: 7/10 with the dependent hanging on "dependency never
  satisfied".)
- **A coordinator turn cannot report the operator's reply as its own (`v950`).** `_run_agent` captured
  `before = len(messages)` before the turn took the session lock, and the coordinator's plan/synthesis
  turns carry no `sender`/`subjob`, so they always took the `messages[before:]` fallback. With an
  operator turn in flight on that session, the slice started inside it and `_best_reply(longest=True)`
  could record the operator's answer as the job's plan or deliverable (JAG-310's shape on the
  coordinator path). The turn's own user message carries the exact text the call sent, so that text now
  anchors the tail; the delegated `sender`/`subjob` anchor still wins. (Locked by `v950` 9/9; the
  length-3 slice WITHOUT the anchor is pinned as the defect.)
- **A hook secret and a URL credential no longer reach the model through a file read (`v951`).** The
  tool-result scrubber knew only the `.env` values. `list_hooks` redacts a webhook secret in every
  payload it serves, but `webhooks.json` sits in the repo data home, where `fs.read` is auto-approved:
  one plain read of that file handed every hook secret to the prompt. `webhooks.secret_values()` now
  exposes them to the scrubber (the store format stays owned by that module — no second parser), and a
  URL that carries a credential in its userinfo (`https://user:token@host`, the shape of a git remote
  and of a pasted clone URL) is redacted by pattern, since its value is not ours to know in advance.
  The colon is required on purpose: `ssh://git@host` is a username, not a secret. Known gap: a
  token-only userinfo (`https://<token>@host`) is not covered. (Locked by `v951` 12/12; live: a
  `git remote -v` through `POST /api/tools/call` returns `https://[redacted]@github.com/...` to the
  model. The approval ledger still stores the raw args of the call it recorded — not model-bound.)

### Fixed
- **One name and one compact count per rail row, and the ⋮ is a toggle.** Operator: *"each
  session just one name … the second name example drafting agent→writer only taking space away"*,
  *"the X msg · Y d string i hate — can it be compacted?"*, *"re-click on the tree dot menu shall
  make the menu disappear"*, *"the agent name shall be ABOVE its code and icon … the ID shall go
  down"*, *"the icon on left most … indicates part of a team, remove"*, and *"if going below with
  scroll bar the team shall remain as heading"*. The row is now: **line 1 the NAME** (with 📌 / the
  void-prompt `*`), **line 2 the A-id · ctx ring · `46m` · ⋮** — the message COUNT is gone (it cost the
  width the ring needs beside the A-id); squeezing the rail ellipsizes the name and keeps the id below,
  never the opposite. The ⬢ org mark and the per-row team symbols are deleted (the sticky group header
  states the team; both names and the full count live in the tooltip), and `.sgroup-h` is
  `position: sticky; top: 0` so the team stays visible while its agents scroll. A second click on the
  same ⋮ (or team kebab) closes its menu. The `role` FIELD is untouched. (Locked by `v1048`
  C1c/C1d/D3; `v765` re-pointed at the two font rules that remain, 17/17.)
- **The ⋮ session and team menus open again after being closed.** Operator: *"if i click tree dot
  menus and close and click again it does not start anymore"*. Each open armed a one-shot document
  listener; it was still pending when the ⋮ was clicked again, so it closed the menu that click had
  just opened. ONE persistent listener (`_wireSessMenuClose`) now owns the close, and both rail menus
  are body-level fixed popovers placed from their trigger — so they neither vanish on reopen nor clip
  behind the rail. (Locked by `v1048` D1/D2.)
- **The session ⋮ menu opens fully in front, never behind the rail.** Operator: *"the treedot menus
  opened are not visible because they are beyond the other webui objects instead of being fully front
  as graphical objects."* `.sess-menu` was an absolutely positioned child of the session row with no
  offsets, inside the scrolling rail: the rail clipped it and the rows below painted over it. It is now
  a BODY-level `position: fixed` popover at `z-index: 53`, placed from the ⋮ with the same zoom-aware
  `_placeMenu()` the preview menu uses (it flips above near the bottom edge). Two stale pins were
  re-pointed in the same change: `v311`'s clear emulation now calls the real `clear_session` door (the
  old `save_session(messages=[])` is merged back by the v947 prefix adoption), and "Edit role opens
  ROLE.md in code mode" now pins the deck's agent editor, where that form lives. (Locked by `v311`
  34/34, `v284` 18/18.)
- **A row of "Agents & unread" reveals its chat like the rail's centre button.** Operator: *"the
  agents and unread panel if click on agents shall also make the same work as the left sidebar
  CENTER icon that move camera to the chat session specific agents … make this quick fix, don't
  duplicate codebase."* The popover row only called `selectSession`, so the chat switched while the
  Sessions rail stayed where it was: the 🎯 gesture (open the panel, expand the session's group,
  centre and flash its row) existed only for the active session. The row's click now calls the SAME
  `revealActiveSession()` after the switch — one implementation, no copy. The row's meta line now
  names the AGENT (`A54 · Head of Longrun Testing`), not the model it runs on; the model moved to the
  tooltip. (Locked by `v472` B6b/B6c 30/30.)
- **A deliberate clear outranks any transcript snapshot taken before it (`v1045`).** Operator:
  *"reset no avvenuto vedo ancora 129 messaggi … no ha funzionato"*. `sessions.reset` answered
  `exit 0` and `session.cleared` fired, yet the session file came back with 130 messages / 47 cards /
  66 injects: the chat loop holds the transcript in memory and flushes it into `sess["messages"]` on
  every `persist_tool_card`/`persist_inject` and at turn end, so the turn that had read the document
  BEFORE the wipe wrote its copy back afterwards (`save_session` kept the longer list). `load_session`
  now stamps the copy with a non-persisted `_loaded_at`; `clear_session` arms a per-session
  `_CLEARED_AT` tombstone BEFORE it writes; `save_session` compares the two — a snapshot older than
  the clear has its `messages`/`tool_cards`/`injects` dropped and carries a sticky
  `_stale_after_clear`, so no later save from the same snapshot can resurrect the transcript, while a
  snapshot loaded AFTER the clear appends normally. In-process keys are stripped before `write_json`.
  (Locked by `v1045` 9/9; `v321` reset, `v947` merge, `v222`/`v315` delete still green.)
- **A turn can reset ITSELF from a batch without deadlocking (`v1047`).** Operator: every agent can
  reset its own session. `sessions.reset` on the caller's own session reached `clear_session`, which
  acquires `_turn_lock(sid)`; when the model emitted the call inside a `batch` (a pool worker), the
  turn that owns that lock was blocked waiting for the tool, so the turn froze after `approval.auto`
  — no `tool.result`, no `session.cleared`, the transcript untouched (measured live 2026-11-15 18:38,
  session `a04c331fca32`). `clear_session(from_turn=True)` skips the turn lock for the session's OWN
  turn (the `v1045` tombstone plus the per-session save lock keep the write safe); every other caller
  still serialises, so a chief's reset of a subordinate waits for that subordinate's turn. (Locked by
  `v1047` 9/9.)
- **Reset/compact follow one rule: own session always, then the reporting line (`v1046`).** Operator:
  *"every agent can compact/reset its session and the boss of a team can compact/reset all the other
  sub/dispatchable agents of the team under its line of command at any depth level."* `_may_manage`
  refused `caller == target` ("the calling session cannot reset/compact itself"), while
  `context.compact` allowed self through a `sid != caller` shortcut — two doors, two policies. The rule
  now allows the caller's own session and keeps "below me in the line (any level, same team), never
  upward or sideways" for anyone else; `context.compact` asks the same rule for its own session too,
  and the tool description no longer claims "never yourself". (Locked by `v1046` 13/13; `v939`
  updated to 22/22.)
- **Every turn keeps its duration, printed under the answer (`v1042`).** Operator: *"after a work of
  the session i need to know how much time that turn took to be completed — this shall remain printed
  as a summary in the chat session, i don't like things that appear and disappear from the chat
  history."* The numbers existed (the run ledger records `duration_s`), but the chat only drew them
  as a transient `run.metrics` bubble and a `plan.stopped` line: neither lives in the transcript, so
  both vanished on the next reload. The chat loop now measures the turn ONCE (`_turn_t0` beside
  `runmetrics.start`) and persists `duration_s` / `iterations` / `steps` / `tokens` / `stop_reason`
  ON the assistant message (after every `meta = {...}` branch, before `append_message`), feeds the
  SAME duration to the ledger, and carries it on `chat.final`. The WebUI paints `.turnfoot` under the
  answer from that meta — e.g. `✓ work complete · turn took 5.5s · 3 rounds · 0 steps · 29k tok` —
  both live and on reload (loadHistory), and the transient `runFooter` / `planStopped` bubbles are
  gone (the stop label rides on the summary instead). Verified live in Chrome: the footer under the
  answer is byte-identical before and after a `reloadChat()` (persisted meta 5.5 s / 3 / 0 / 28 513).
  (Locked by `v1042` 13/13; live-nesting set 10/10: `v1041`.)
- **The live chat nests the turn's work under its todo, without a ↻ (`v1041`).** Operator: *"the
  chat session is not refreshed realtime … i don't see the chat workflow under the
  todo/justifications, i see it only if i press the refresh button — but that button causes a
  temporary blackout of the chat."* Every card/inject is PERSISTED with the step it belongs to
  (`node=_cur_node()`, the same value `persist_tool_card`/`persist_inject` store), so a reload nests
  the work under that todo — but the LIVE render events carried no node, `applyGraphEvent` dropped
  any node event without a `run` (half of them: the chat loop's `on_event` pairs), a step was born
  closed, and a completed step's section was collapsed live. So during a turn the work piled into
  the free group ABOVE the todo cards and the workflow appeared under them only after ↻ (which
  blanks `#log`). The chat loop now stamps the SAME step on `tool.call`/`tool.result`/`tool.blocked`/
  `harness.inject` (transient frames — the system-prompt chip, a suppressed repeat, `todo.write`'s
  own top-level card — are skipped, because a reload cannot reproduce them), the WebUI points the
  next append at that step (`_atNode`) and OPENS a step the work lands in, a completed step is
  closed only when it holds no cards (the reload contract), and `applyGraphEvent` gates on the
  SESSION instead of `run`. Verified live in Chrome on a scratch session: the tool cards, harness
  chips and the step's justification paint INSIDE its todo while the turn runs (6 items nested, step
  open, no reload). (Locked by `v1041` 10/10; live-nesting regression set 35/35: `v505`, `v532`,
  `v443`.)
- **The Marketplace's "installed" state follows its owner (`v1038`).** Operator: *"i added from
  marketplace filesystem then deleted from the settings-mcp panel, go again in marketplace and found
  it labeled installed! … marketplace and installed ones shall be synced always. same for MANAGE, and
  for everything actually."* `data/market/installed.json` was written at install time and never
  reconciled, so `remove_client()` left the record behind. Every read now joins the record with the
  owning store: a record whose object is GONE (MCP client absent from the client document, skill
  directory removed) is pruned atomically, with `pruned` in the payload; a DISABLED client still
  counts as installed; an owner that cannot be read prunes nothing. `remove_client()` also forgets the
  record immediately, so the Settings delete needs no extra read to show in the catalogue.
  (Locked by `v1038` 10/10.)
- **A missing MCP credential is named, never sent as `${VAR}` (`v1037`).** Operator: *"✗ github —
  initialize failed: HTTP status 400 … my token should be in .env"*. The bundled GitHub connector
  carries `Authorization: Bearer ${GITHUB_PERSONAL_ACCESS_TOKEN}` while this install only defined
  `GITHUB_TOKEN`; `os.path.expandvars` left the reference VERBATIM, so the literal placeholder went
  out and GitHub answered `400 bad request: Authorization header is badly formatted`. Both transports
  now expand through one helper that reports what stayed unresolved: the client fails BEFORE any
  request (or any child process) with "missing credential: NAME — set it in Settings › Keys", and
  `test_client` / the manager surface that sentence instead of `transport connect failed`.
  (Locked by `v1037` 10/10.)
- **The MCP panel's test button keeps the stored credentials (`v1036`).** Operator: *"testing PMCP button
  gives ✗ PMCP — initialize failed: HTTP status 401"* — while `mcp.test {"name":"PMCP"}` and a direct
  `initialize` with the stored bearer both worked. `status()` deliberately omits `headers` (a panel must
  not echo secrets) and the button posts that redacted row; `test_client` only resolved a stored spec when
  BOTH `command` and `url` were absent, so a row carrying `url` replaced the stored entry and dropped
  `Authorization`. The supplied keys are now layered OVER the stored spec: a URL/args edit still applies,
  credentials survive unless explicitly overridden, and an explicit `headers: {}` still means "no headers".
  (Locked by `v1036` 9/9.)
- **Settings points at the Marketplace instead of growing a second catalogue (`v1035`).** Operator:
  *"in MCP put a button that redirect to marketplace/mcps … the same in the skills settings panel …
  etcetera."* The three Settings categories that own a catalogue (MCP, Connectors, Skills) now carry one
  `◈ marketplace` button that closes Settings, sets the catalogue's `kind` and opens the Marketplace on
  that section — `openMarketKind(kind)` is the single door, so nothing is installed from a second place.
  (Locked by `v1035` A.)
- **The editor no longer sits dead over the Control deck (`v1035`).** Operator: *"if open editors and
  pass to control page and squeeze it doesn't respond to close commands and commands in general."* The
  dock lived inside `#app`, which is `inert` while the deck owns the row: the window stayed visible and
  received neither clicks nor keys, and squeezing turned it into a fixed overlay on top. It is now
  hidden under `body.control-on` and comes back exactly as it was on Sessions; `_clampFloat` also
  refuses a zero rect, so a resize while it is not rendered can no longer clamp a floating window to
  0,0 and lose the position the operator left it at. (Locked by `v1035` B.)
- **The Control deck is one panel under the other below 1200 px (`v1035`).** Operator: *"control page
  horrible squeeze demolish everything and mobile shall become one below the other."* A custom view is a
  flex ROW that wraps, so at a squeezed width four panels shared the strip and the fourth wrapped into a
  second column at `x = viewport + 4` — off-screen (measured at 1100 px). Below 1200 px the deck is now
  a non-wrapping COLUMN: every panel is full width with a 320 px floor and the deck scrolls; the rail is
  a top strip at the same breakpoint and `_layoutViewCols` returns early (tearing down an existing rows
  layout on the way down). Measured at 1440/1204/1201 (unchanged desktop rows) and 1100/900/700/390
  (all four panels at `x=4`, stacked, `scrollHeight` 1351 > 472). (Locked by `v1035` C.)
- **A right-click menu opens at the pointer, under every page zoom (`v1029`).** Operator: *"right click
  that opens menus example in the editor or elsewhere open the editors far away from the mouse click
  that's not good."* At 130 % (the app's own zoom) a right-click at (1110, 183) put the editor-tab menu
  at (1383, 238) — ~270 px right of the pointer and clipped by the window. A click arrives in VISUAL
  px and `innerWidth`/`innerHeight` are visual too, while a CSS `left:` and the menu's own
  `offsetWidth/offsetHeight` are layout px: the shared `_placeMenu` converted only the click, and the
  editor's two menus (file row, tab) plus the Plan-todo menu did not convert at all. All of them now
  go through `_placeMenu`, which converts the click AND the viewport, flips the menu above when it
  would pass the bottom, and keeps it inside the window. (Locked by `v1029` 12/12; live: at 70 %,
  100 %, 130 % and 160 % the menu lands on the click and clamps inside the viewport.)
- **The topbar fits every size, and its tabs are icons at every width (`v1028`).**
  Operator: *"in mobile squeezed format not all objects are visible…"*, then *"still there are sizes
  that do not display all … every size shall fit … leave an icon (mouse ON reveals what they are)"*,
  then *"remove the text on top bar for tabs use only icons always!"*. The header answered with
  `overflow-x: auto`, so the search and the gear slid off the bar (measured: 820 px of content on a
  770 px window; on a 390 px phone the last two controls were outside the viewport). The four section
  tabs are now drawn 17 px SVGs at EVERY width (the rail's stroke recipe: Sessions = layers, Control =
  deck layout, My Artifacts = tiles, Marketplace = bag), named by `aria-label` + `title`; below 980 px
  the sandbox becomes its dot and the approval chip its ✓, also titled. The session badge leaves below
  1101 px (the chat head names the session) and is never shown on My Artifacts or Marketplace, which
  own their row and already carry their own session filter. The 320 px bar narrows the tab targets,
  and the landscape 44 px rail gets the same 30 px approval glyph (its word overflowed the column).
  Verified live at 320, 360, 390, 480, 640, 641, 700, 765, 820, 900, 980, 981, 1000, 1024, 1100,
  1101, 1280 and 1440 px plus the 844×390 rail: `scrollWidth == clientWidth` and every control inside
  the viewport. Nothing is removed: sandbox, approval mode, search and settings all stay. (Locked by
  `v1028` 13/13.)
- **A rail icon stays copper while the surface it opened is expanded (`v1026`).** Operator:
  *"the side bar colours shall be maintained if the relevant panel session is expanded this is still
  not true for the upper icons."* The Inspector jumps were already painted from `.insp-open`, but the
  upper cluster went dim as soon as the pointer left: the editor door never consulted the dock, and
  `editsBtn`/`apprBtn` are `INSP_JUMP_SKIP`, so nothing lit them; `kbSessionBtn` opened Settings ▸
  Knowledge with no mark at all. One rule (`#toolsBar button.is-current { color: var(--acc) }`) now
  covers every group — this also gives the PLAN toggle in the chat group the colour JS was already
  setting — and three truthful sources feed it: `.insp-open` for the two badged Inspector doors,
  `state.dock.hidden` for the editor (`show()`/`close()`), and the visible `knowledge` category for
  the notebook door. (Locked by `v1026` 13/13.)
- **A plan is never abandoned: `finish` faces the closing contract, and a restart cannot drop open
  steps (`v1008`).** Operator: *"i need resilience on any restart or any problem during the run. task
  shall not be abandoned (the plan can be modified, superseded but not forgotten). even if restart."*
  Three holes, one thread. (1) `finish` could END a turn with steps open: it earned the two bounded
  closure-check rounds and then broke out of the loop, so the close-todos forcing every PROSE answer
  faces (JAG-402, its own budget of 4) was never reached — the CLOSING CONTRACT held for prose and not
  for the action that claims completion most explicitly. Both now share `_close_todos_text` and
  `_close_todo_rounds`, so a finish with open steps is rejected with the same wording and the same
  bound. (2) A `[Harness restart]` continuation counted as a PIVOT (`_user_pivot` = "the turn opened
  with open steps"), so the resumed turn was told "leaving steps OPEN is fine and is the DEFAULT" and
  the work the restart interrupted was quietly dropped; `inflight.is_resume_text` now owns the marker
  and the resume turn is NOT a pivot. The operator's OWN message still outranks the plan (JAG-189): a
  pivot turn answers without forced closure. (3) Nothing recorded WHY a turn had left steps open, so
  the next turn could not tell an abandoned step from one nobody had started.
  `taskgraph.note_turn_end` writes the carry ON the graph (file, not process memory) with the open ids
  and the reason (`restart`, `finish`, `user_pivot`, a typed stop), `carry_line` renders one line into
  the always-on state block, and the record is cleared by the first turn that closes every step (and
  never rendered against a superseded plan or a step closed since). `reconcile_orphan_turns` writes it
  where the killed turn cannot. (Locked by `v1008` 30/30 — including a scripted turn whose model only
  emits `finish` with 2 open steps: 4 rejections naming the exact ids, the turn still ends, and the
  steps are carried, never dropped — and a pivot turn that answers and carries the stale steps; plus
  `v592` 11/11, `v584` 12/12, `v449` 14/14, `v999` 6/6, `v1005` 18/18, `v938` 17/17; targeted battery
  35/35 GREEN with the 20 UI-guard tests.)
- **A rail button is a two-way door, and the fold-all icon sits above the plan toggle (`v780`).** The
  two badged rail buttons (Workspace changes, Approvals) opened their Inspector section
  unconditionally, so a second click did nothing — the only rail controls that were one-way, while the
  jump icons already opened on the first click and collapsed on the second. Both now route through
  `_railToggleInsp` (same two-way rule, drawer included on a narrow viewport), so re-clicking any rail
  button closes the object it opened in the RH panel. The collapse-all-groups icon is also moved
  immediately above the expand/collapse-plan icon on every `_buildInspJump` rebuild (operator: "the
  collapse all groups icon just above the expand or collapse plan one in the sidebar"). (Pinned by
  `v780` 17/17; rail/UI guard 8/8 — v885, v890, v879, v426, v851, v761, v758. The static pins plus the
  testing head's `PASS` verdict are the evidence; no browser was available for a rendered click.)
- **The memory report counts LIVE records, and every record can be retired (`v1007`).** An agent
  read the store and reported "`agent_notes.md` 313 records against `memory_max_records: 300` — old
  lessons are being silently retired". The store held exactly **300 live** records: `stats()` (and
  therefore `GET /api/memory`) counted the raw file, so the 13 lessons hygiene had correctly retired
  were counted as memory. `kinds`/`total` are now LIVE, `stored`/`tombstoned` keep the history, and
  `bounded[kind].over` is computed from live records, so a store held at its budget never reads as over.
  `health()` keeps `total` as every record (the repair view) and adds `live`, `stores_live`,
  `unaddressable` and `core_chars`; the `memory{action:'health'}` stdout says LIVE vs stored and names
  the budget. Two further defects the same report exposed: `memory{action:'recent'}` listed the
  invalidate/restore ledger as knowledge (its newest rows were 15 `hygiene: over budget 300`
  tombstones) and the shared ledger file was read twice, double-counting every tombstone in `query()`
  and `health().total`. And a record with **no `mid`** is outside the whole lifecycle — `invalidate`/
  `supersede`/`restore`/`forget` are all id-keyed — so 13 records from the pre-`mid` v0.3 writer
  (12 battery markers + 1 "live check") sat permanently in the store that is never auto-retired;
  `backfill_mids()` now assigns ids at boot (idempotent, content untouched) and the 13 were retired
  with a tombstone. (Locked by `v1007` 24/24; memory suite regression 14/14: v204, v317, v628, v794,
  v818, v819, v841, v853, v876, v929, v972, v996, v997, v998. Live: `/api/memory` reports
  `agent.note` 300 live / 313 stored, `over: 0`; `user_memories` 57 live / 70 stored,
  `unaddressable: 0`.)
- **A model's native DSML arguments are no longer dropped (`v1006`).** Session `fd98ee64e89f`
  (deepseek-flash) made 139 tool calls and 18 failed; 13 of them had ONE cause — the arguments were in
  a dialect the parser did not read. Three shapes: an `args` envelope with a SIBLING `tool` parameter
  (`_dsml_unwrap_args` required it to be the only parameter), a JSON value on a marked body tag
  (`args="{"path": …}"` — only invoke attributes were read, and the old `"([^"]*)"` regex stopped at
  the first inner quote), and a bare body attribute (`command="…"`, never scanned). The calls reached
  the tools with `{}` or `{"args": …, "tool": …}` and were rejected as usage errors, and the model
  re-sent the same shape ten times. `_dsml_attr_value` now decodes a JSON attribute with
  `raw_decode`, `_dsml_body_attrs` reads the marked body tags, `_dsml_unwrap_args` accepts the `tool`
  sibling, and `normalize_args` decodes a string `args` envelope and drops the `tool` sibling when the
  schema does not declare it — so `git`'s string `args` and `self.tools` are untouched. (Locked by
  `v1006` 12/12; regression set 11/11: v369, v782, v793, v978, v968, v736, v742, v510, v904, v774.
  The proposal that records the session evidence is
  `.agent/docs/proposals/2026-11/2026-11-15_tool-registry-audit.html`.)

- **A drifting DSML marker can no longer turn a tool call into the final answer (`v904`).** The last
  turn of session `fd98ee64e89f` emitted its two `shell.exec` calls wrapped in `<「DSML」 …>` — corner
  brackets instead of the bars `textkit.DSML_MARK` knew. `is_dsml` returned False, so the message was
  classified as prose, stored as the assistant's final reply (2 KB of raw markup) and painted in the
  chat; the calls never ran. The detector has ONE owner (`textkit.DSML_MARK`, read by the agent loop
  and by reply selection in `stores.turn_reply`); it now accepts `「」『』【】` as well as `|`/`｜`.
  Replaying the stored message through the real parser yields the two intended calls. A second,
  marker-agnostic rule treats a message that STARTS as a tag envelope and names both `invoke` and
  `parameter` as machine text, so the next glyph drift cannot repaint a call as the answer. (Locked by
  `v904` 39/39, extended with the corner form, the `parameter="x"` spelling, the no-slash `<…invoke>`
  close and the unknown-marker safety net.)

### Changed
- **The official default Desk keeps the operator's proportions (`368201b` round).** The operator's
  screenshot set the official shape: Agents 25 · Jobs 15 · Org chart 36 · Constellation 24 — measured
  off the screenshot (the dragged shape the operator approved; a board needs a wide Org chart and a
  slim Jobs rail). Two earlier defaults are gone: the "agents ≥ 40%" bias (`809e302`) that forced
  agents wider than every neighbour on every fresh desk AND wrote its ratios into the layout store so
  the inherited shape survived, and the one-day equal split that answered it. The proportions live in
  `_deskDefault` as the FALLBACK only — a saved drag always wins, any other view keeps 1/n — and a
  one-shot migration (`orbit_desk_def_v1`) drops the inherited desk ratios ONCE with a real write-back
  of the trimmed store (the first cut forgot the `setItem`, caught live: widths [751, 184, 164, 778]
  survived a reload) and removes the dead `orbit_desk_eq_v1` flag. The default view itself is four
  panels (Agents | Jobs | Org chart | Constellation) via `deck_views.DEFAULT_VIEW`. (Locked by
  re-pointed `v624` B3 + `v644` C2; targeted battery 27/27 incl. the UI guard; service restarted for
  `deck_views.py`; verified live: measured ratios 0.2504/0.1502/0.3596/0.2397 against target
  0.25/0.15/0.36/0.24, console clean.)
- **The ALL constellation is bands, not a pile-up (`12b72e2` round).** The operator's screenshot was
  an honest "orrore": 21 job pills squeezed onto ONE evenly spaced row overlapped into an unreadable
  sausage (~47px per pill), the subjob lane sat at a fixed y=68 so its deeper rows drew OVER the
  agent boxes, empty agents were full-height boxes, and a 1040×~8000 board fitted height-first
  rendered as a ~100px-wide microscopic strip. `_drawAll` is structured now: job SLOTS (104px) wrap
  into rows; each job's subjobs stack in ITS OWN slot below it, one 30px lane per subjob with a
  nested one still one lane lower (v629 kept); agent clusters start BELOW the whole subjob band, so
  pills and boxes never overlap; a task-less agent is a compact 44px chip; and the default fit is
  WIDTH-first — the visible window is the top slice at full scale, wheel/drag reveals the rest
  (short graphs untouched). (Locked by `v629` E12 re-pointed + targeted battery 25/25 incl. the UI
  guard; verified live on `/orbit` in ALL mode at 95 agents · 21 jobs · 33 subjobs: three readable
  job rows, subjob columns under their jobs, console clean.)
- **The Constellation scope is one menu, and the ✨ Architect call stays visible at every width.**
  The deck header carried two buttons (AGENT / ALL) that spent ~90px of a panel the operator keeps
  narrow; they are ONE compact select (`#constMode`) whose value is the mode — `setMode` keeps it in
  sync and the deep-link fallback switches it by `change` event. And the composer rows no longer push
  the ✨ out of the row when a column is squeezed: the v891 110px floor on the assignee picker
  (`#jobTo{flex:1 1 120px;min-width:110px}`) ate the row and shoved ＋ job and the sparkle past the
  panel edge; the picker now yields first (`flex:1 1 0; min-width:0` — same for `#rtAgent`,
  `#rtEvery` yields after it), while ＋ job / ＋ add and the ✨ keep their size. At a 160px column the
  row still holds all three controls (picker sliver ≈ 25px); the controls and their wiring are
  unchanged. (Locked by re-pointed `v294`/`v617`/`v703`/`v891` + `v772`/`v881`/`v678`; targeted
  battery 24/24 green incl. the UI guard; verified live on `/orbit` at 245px and 160px columns; live
  axe: 0 violations, no static-file restart needed.)

### Added
- **A commercial plugin package can be imported, with the adapters inside the harness (`v1040`).**
  Operator: *"where does commercial plugins standard comes from? can be put on marketplace in longrun
  with adapters embedded in longrun? if yes do."* Three container standards are read from the
  package's OWN manifest — Trae (`.trae-plugin/plugin.json`: `skills: "./skills/"` + `mcp: ".mcp.json"`),
  Claude (`.claude-plugin/plugin.json`: `skills/` + `.mcp.json`) and a bare `SKILL.md` directory —
  and each is converted into the `plugin` entry the catalogue already installs: a skill member (the
  directory zipped deterministically so the digest gate still applies) and an `mcp`/`connector` member
  from `mcpServers`, with `${VAR}` making it a connector and naming its key. OpenClaw's
  `openclaw.plugin.json` is a CODE plugin, so only its SKILLS travel (`skills: "./skills"` or a
  SKILL.md at the root — `diffs` and `lobster` on this machine do exactly that); the JavaScript
  (tools, hooks, channels) is named as ignored, because the Longrun home for code is Matrix.
  Anything else a package carries (commands, agents,
  hooks, binaries, apps) is listed as ignored, never installed, so nothing lands half-imported.
  Split roots keep it safe: a path must live under `plugin_sources` (defaults: `~/.trae/plugins`,
  `~/.claude/plugins`, `~/.openclaw/extensions`, `~/.openclaw/plugin-skills`, the repo), an https ZIP
  goes through the existing allow-list fetch plus a zip-slip check, and the install reuses the SAME
  dispatch, digest gate and record (`market.install_entry`). New `market plugin-scan` /
  `market plugin-add <path|url>`, `GET /api/market/plugin-scan`, `POST /api/market/plugin-import`, and
  a "Found on this machine" block in the Plugins section with an Import button. The testing head found
  two diagnostics and both are fixed in the same change: a path outside the roots is now refused for
  WHERE IT LIVES even when it carries no manifest (the location gate runs before the format gate), and
  the reported roots are the enforced ones, repository included. Operator follow-up fixed too: a local
  card names the package (`diffs`) with its shortened location in the meta, because the full path as a
  title painted over the neighbouring card. A plugin's members now also carry their parent: the Skills
  and MCP panels read `installed_map()`, which resolves each member to the plugin that installed it, so
  a bundled skill says `from plugin/X` — and the Manage Remove (like the Skills panel's delete)
  uninstalls the plugin WITH the skills and servers it created (`?files=1`), never a pre-existing one.
  (Locked by `v1040` 31/31.)
- **A plugin is a container, and the Matrix modules are their own kind (`v1039`).** Operator: *"plugins
  are only matrix. does they need adaption to the longrun specific harness …? plugins are combinations
  of skills and mcps? what are plugins?"* — and the answer was no in the catalogue: `plugin` named an
  in-process Matrix module (`src/Matrix/tools/<ns>.py`), so the Plugin tab could only ever show the
  nine modules that ship with the repo. A commercial plugin is a CONTAINER (skills + MCP servers, and
  in other products commands/hooks/code), which is a different object. `plugin` now means exactly that:
  an entry declares `members` (`skill`, `mcp`, `connector`), it writes nothing itself, and every member
  goes to the installer that already owns it — `_install_bundle` validates the whole set first (an
  unknown member kind such as `command` is refused BY NAME, a duplicated member is refused, every
  member must be installable by its own kind's rule), rolls back the members it created if a later one
  fails, and records ONE row carrying them with a `created` flag, so `rm` never removes a skill or
  server that was already there. The shipped Matrix modules are the new `matrix` kind (present, never
  installable). One real bundle ships — `plugin/starter-kit` (release-notes skill + filesystem MCP
  server) — so the tab proves the path end to end. (Locked by `v1039` 27/27.)
- **A chief can free its team's context (`v939`).** `sessions.compact` and `sessions.reset` now let any
  manager act on a member BELOW it in the reporting line, at every level (transitive, same team when
  teams exist) — and nothing else: never itself, never upward, never sideways. `context.compact` used
  to accept ANY `session=` with no check; it now applies the same rule (the caller's own session is
  still free). One compaction policy (`_compact_now`) serves both doors. (Locked by `v939` 20/20; live:
  a scratch chief reset and compacted its child, and the child was refused when it tried the chief.)
- **A turn interrupted by a RESTART resumes itself (`v938`).** The running turns were only in memory, so
  a restart erased them and the operator had to send the continuation by hand. `core/inflight.py` now
  mirrors every turn to `data/inflight_turns.json` at `turn_begin`/`turn_end` (the one bracket every
  turn uses: stream, sync, agent run, MCP). On boot the file is read and each session whose turn never
  ended gets a `[Harness restart] … continue from where it stopped` message — but only when the exit
  looks like a restart: no marker (crash/kill -9) or a fresh SIGTERM marker (systemctl restart). A
  deliberate stop followed by a later start is NOT resumed. SIGTERM now runs a clean exit so the marker
  exists; `runtime.restart_resume_window_secs` / `restart_resume_max` are config. (Locked by `v938`
  16/16; live: a real turn was cut by `systemctl restart`, the boot resumed it and the model answered.)
- **An evaluation never writes the live configuration (`v937`).** The meta-harness saved the candidate
  into the policy overlay and restored the old one in a `finally`, so a crash or kill between the two
  left the candidate installed and a concurrent turn ran under it. The candidate now applies to a copy
  and is exposed through `registry.scoped_config()` (a context-scoped override): nothing is written,
  nothing has to be restored, and the cached config is never mutated. (Locked by `v937` 7/7.)
- **A skill that was shown is no longer counted as a skill that was opened (`v936`).** A search
  recorded the hit as injected AND used, so `uses == helped` always held and the retirement question
  ("was this skill ever reached?") had one degenerate answer. Search now records a RETRIEVAL and read
  records an OPEN in the same attribution ledger; `discovery()` reports both maps (plus
  `never_retrieved`) and its own probe stays read-only. (Locked by `v936` 12/12; `v848` unchanged.)
- **A batch accounts for every item it accepted (`v935`).** The Session Job scheduler could return
  fewer subjobs than it created (observed 2026-11-03: two items in, one result out, turn green), so the
  lost work never appeared as a failure. The batch assembler now compares the ids it created with the
  ids the scheduler returned and reports each missing one as an explicit `FAILED ... no outcome was
  recorded` block — the check is the COUNT, not the message. (Locked by `v935` 6/6.)
- **The "No team" bucket gets the team bulk menu — and a real delete-all (`v910`).** The rail's
  No-team pile (live: 103 sessions) had no bulk actions: the Control deck's kebab (JAG-482) was
  real-teams-only and the Sessions rail had none at all. One backend scope now serves BOTH surfaces:
  `POST /api/teams/__none__/{reset,compact,drop-old-plans,delete-sessions}` resolves the SAME set the
  two UIs group under `__none__` (no agent record or no team membership; the pinned system session is
  never in scope) and runs the ONE per-session engine (`_bulk_apply`, extracted from the team route, so
  the two routes cannot drift). The new `delete-sessions` action — on the bucket AND on real teams — is
  the REAL delete: every session goes through `httpapi.delete_session`, so jobs are scrubbed, routines
  deleted, reports re-parented and a running turn is aborted, exactly like deleting each session by
  hand from the rail. The deck's team header kebab now covers the bucket too; the rail's No-team header
  carries the same four items with the same copy; every bulk alert caps at 12 lines instead of printing
  a 100-line wall. (Locked by `v910` 35/35; `v482` 23/23 with its E2 evolved — the kebab contract now
  names the bucket; targeted battery 8 green, service restarted, live scope verified.)
- **The UI is measured for accessibility, not assumed (`v851`).** axe-core 4.14.0, injected into the
  running page, found five violations: the haze theme's muted text at 4.16:1 on a selected row,
  `#runsBar` whose accessible name did not contain its visible text, a title-only `#qmode`, two
  landmarks with the same name, and a scrollable session list that could not take focus. A second
  live pass found two that exist only in a real transcript — a `role="button"` tool-card head that
  CONTAINED the diff/open buttons (`nested-interactive`) and the diff/image viewers sitting outside
  every landmark (`region`). All are fixed: `--dim` is `#a4b0c0` (4.67:1 on a selected row),
  timestamps composite at 0.9 (4.58:1 in the worst theme), the tool-card disclosure is a native
  `<button>` (so the action buttons are its siblings), the composer's attachment ✕ is a real button
  instead of a mouse-only span, and the viewers are named regions. 49 of 114
  static form controls had no accessible name — a tag regex said 130 and then 93, because it cannot
  see `<label>text <input></label>`; `v851_ui_a11y_gate` is the deterministic half (names, icon
  buttons, the four daily surfaces, and the contrast arithmetic for all 8 themes) and it audits BOTH
  surfaces: the Control deck had 12 of its 13 static controls named by a `title` or a placeholder
  only, and a `role="button"` must never be reachable by mouse alone. Evidence:
  `.agent/docs/research/webui-a11y/2026-11-07_webui-a11y/axe.json` (violations 5 → 0; `incomplete` is reported,
  never counted as a pass).
- **The harness audits its own scaffolding (lot H, `v844`…`v850`).** Six read-only reports now say
  whether the rules, the skills, the tools and the permission gate still earn their place:
  `rules.audit()` finds contradictions, stale paths, duplicates and over-budget scopes with
  `file:line` (`GET /api/rules`); a third correction on the SAME point produces one line of advice
  (add ONE rule, or start clean) instead of silently resetting the chat; `approvals.stats()` gains the
  accept rate, the median time-to-decision and the rubber-stamped tools; `registry.footprint()` names
  the enabled tools never called in the window and the characters of model-facing index they cost
  (`GET /api/tools`); `skills.discovery()` names the never-opened skills from the shared attribution
  ledger and probes their reachability from a plain-language task (`GET /api/skills`); and
  `benchmarks/ablation.py` runs two arms of ONE command differing by exactly one file-backed layer
  (`rules` / `skills` / `hooks`) and compares the two result trees. The three blocks are rendered in
  Settings from the same payloads (live 2026-11-07: `183/183 enabled · 85 unused`, ~30k characters of
  index). Nothing is auto-deleted, auto-disabled or auto-written — every report is advice.
- **Retrieval has a second stage: a cross-encoder re-ranker (V-7, `v824`).** Hybrid search
  fuses a lexical and a semantic list — it says the candidates are *plausible*, never that
  one of them answers the question. A re-ranker scores `(query, passage)` TOGETHER and
  reorders what retrieval already found; it can never invent a document. One
  implementation (`model/rerank.py`), two consumers: Knowledge/codebase search and the
  memories injected into the prompt. It is declared exactly like a chat model — a
  `rerank: true` entry in `config/providers.yaml` — but can never be picked AS one, and its
  own settings live in `config/rerank.yaml` (**Settings → Models**). It ships ON with
  `voyageai/rerank-2.5-lite`, the cheapest model measured on this account, and it **fails
  open**: disabled, a model error, a timeout or an empty answer leaves the fused order
  untouched.
- **A user preference and an open question are first-class memory (V-1, `v819`).** Two new
  kinds — `user.preference` (always in the prompt, under the "user facts" trust label) and
  `question.open` (its own prompt bucket, closed by the ordinary memory lifecycle) — so a
  preference no longer has to be re-stated every session and an unanswered question
  survives the turn that raised it.
- **The tool policy reports which guardrails still fire (V-2, `v820`).** Every matched
  `deny` / `always_ask` rule is counted (first/last hit, persisted), and
  `GET /api/tools` returns the firings plus the rules that NEVER fired — so an obsolete
  gate can be retired instead of guessed at.
- **A skill promotion may replace the skill it supersedes (V-5, `v823`).**
  `selfevolve.promote(..., supersede=True)` retires the installed skill to
  `<skills>/_retired/` (moved, never deleted), stages the candidate outside the library and
  swaps it in, recording the replacement in an append-only ledger and on the new
  proposal. Improvement can finally land on a name that already exists.

### Changed
- **A session switch no longer rebuilds the world (`v853`-`v856`, 2026-11-07).** The operator
  reported that switching session or expanding a team took seconds. Three defects were paying for
  it, each measured before it was touched: `memory.dedupe` compared every record against every
  SURVIVOR and re-tokenised them at each comparison (3695 ms to scan 498 records and drop none —
  it now stops at the requested survivors and caches each survivor's token set); the context METER
  built the prompt with retrieval on, paying the cross-encoder re-ranker (a paid HTTP call, 390 ms)
  twice per switch for a field no client reads; and `registry.catalog()` re-read and re-parsed
  `config/tools.yaml` (13.7 ms) on every prompt render, twice per render, because the tool section
  and the longrunAgent subtool list both ask for it — the parse is now memoised by the file's own
  `(path, mtime, size)` and handed out as a copy. The Context panel also renders the prompt sections
  ONCE instead of twice, handing the meter what it just computed. Measured on the live server:
  `/api/context` 5303 → 23 ms, `/api/context/items` 1402 → 35 ms, `/api/status` 34 → 6 ms, and in
  the browser a full switch ~550 → ~300 ms with a team expand at 70 ms. No capability changed: the
  dedupe contract, the meter's arithmetic and a real turn's single retrieval are pinned by
  `v853`/`v854`, the config memo by `v855` (an edit is always re-parsed, a mutation cannot poison it)
  and the single render by `v856`.
- **Settings ▸ Models is ONE sheet per model stage (2026-11-05, `v825`).** The re-ranker had a live
  picker at the top of the panel and its knobs in a second card of their own — a SAVE chip, a second
  save button and a read-only copy of the model the picker already showed — so one stage read as
  three surfaces. The knobs now live INSIDE the picker's card (a divider, the fields, one save), the
  five numbers share a two-column grid of equal width, the on/off of the stage spans the row, and
  each short label carries its explanation as the tooltip. The provider editor is a section of the
  Providers card rather than a section above it, and its rows are a divided sheet instead of a card
  inside a card.
- **The chat ✨ optimizes the draft you already typed (operator request, 2026-11-03).**
  With text in the composer the same ✨ used to draft a brand-new message and discard it.
  Now the field's state decides the job: EMPTY → the opening/next message as before;
  FILLED → the draft is rewritten into the complete, implementation-ready instruction it
  implies (spelling, grammar, ambiguity fixed; the changes, the behaviour to preserve and
  the way it is proven done spelled out), replacing it with one-click undo and inventing
  nothing the draft does not support. The button's name follows the state, so it is never
  a ✨ that silently throws the draft away (RH-29).
- **Enter sends the message in the composer (operator request, 2026-10-26).** It
  used to insert a newline and demand `Ctrl+Enter`. `Shift+Enter` (and
  `Ctrl/Cmd+Enter`) now insert a newline; the key still does NOT send while an IME
  composition is in progress or while the `/` menu is open (there it picks the
  highlighted command, with or without `Ctrl`). The two tooltips that promised the
  old shortcut say the new one.

### Fixed
- **A turn resumed after a restart keeps ITS plan and finishes it (`v1005`).** Operator, 2026-11-14:
  *"i asked something to architect but after restart wake up he didn't finish the work"*. The
  `[Harness restart]` continuation WAS delivered and the agent worked (a 5-call and a 3-call batch),
  then the turn closed with four steps still open and "Reply to continue". Three defects, measured on
  the durable log: (1) the graph had split in two — the 2026-11-11 identity migration renamed
  `architect.json` and rewrote every identifier except `key`, and `save()` addressed the file by
  `key`, so every write went to a second file while every read by session id served the frozen one:
  the nudge after `todo.write` said "Task list saved (4 new step(s)) … OPEN (0): (none — the current
  plan is empty)" and the continuation loop saw no open step at all (the later 17:12 turn then wrote
  the frozen 9-node copy back, erasing those 4 steps); (2) the three-empty-reply breaker counted
  LIFETIME empties, so two reasoning-only replies, two successful batches and one later empty ended
  the turn with `stop_reason: empty_reply`; (3) the second `retry` injection was suppressed as a
  "byte-identical repeat", re-sending the request that had just produced nothing. One address per
  graph now (`load()` normalises in memory, `save()` keys off it, a boot heal groups files by
  `(session_id, run_id)`, keeps the newer copy and moves the duplicate to the recoverable trash), the
  empty cap counts CONSECUTIVE replies, `retry` is never deduplicated, and an open plan earns up to two
  `CONTINUE` rounds with a fresh tool budget before a turn may close text-only (the agent's own report:
  *"the restart message forced a plain-text answer … tool calls were off the table"*). Locked by
  `v1005` (18/18, red at HEAD without the fix: 10/13 and the exact `empty message three times` error)
  and `v958` (16/16, B7b pins the graph address through the rename).
- **`run.metrics` reports the turn's real loop iterations (`v1005` C5b).** It published `_kg_rounds` —
  the keepgoing continuation counter — so every turn that finished inside its first tool budget said
  `iterations: 0` (114 of 149 measured turns, including the 2026-11-14 incident). It now publishes the
  loop's own `iters`, so the run ledger can be read again.
- **`restart` is a `harness` tool, not a Matrix action, and a `dry_run` rehearsal arms nothing (`v500` G2–H, `v938` F3b).**
  The Tools & approvals row had no `_SUBTOOL_GUIDANCE` entry, so it displayed the whole Matrix suite
  description (scaffold → remove → git → checkpoints) on what is really a harness warm restart, and
  `schedule_restart(dry_run=True)` wrote the durable resume ticket anyway: the NEXT boot, for any
  unrelated reason, consumed it and spawned a continuation turn. The tool is now `harness.restart`
  (`config/tools.yaml` gains the mandatory `harness` row — a namespace with no row is disabled); the
  old `matrix.restart` spelling resolves through `_TOOL_ALIASES`/`_ACTION_ALIAS_TOOLS` before
  validation and the gate, so stored calls keep working. The mechanics moved to `core/restart.py`,
  the ticket lives in the data dir, and resume has ONE owner: when the asking turn has an inflight
  record, boot lets `inflight.recover` send the standard `[Harness restart]` continuation; the ticket
  path only spawns its own turn when there is no record. A rehearsal ticket is marked `dry_run` and
  ignored by `resume_after_restart`.
- **An agent can name its own model, and a chat turn honours the session pin (`v718` E).**
  Live 2026-11-14: asked *"ok am i speaking now with local?"*, A61 could only answer with the router
  URL — nothing in its context carried the model it was actually running on. Three causes: the
  identity block claimed the turn ran *"locally on a DGX Spark … behind a llama.cpp router"* even when
  the session was pinned to a cloud model; `self.info` reported the router endpoint and config paths
  but never the session's model (`self.diagnose` reports the GLOBAL chat default instead); and
  `chat_stream_gen` ignored `sess["model"]` unless the CLIENT sent it, so a headless/API turn answered
  with the chat role's default while the UI, the prompt and the run ledger said something else. One
  derivation now feeds both surfaces — `providers.describe` (provider, kind, local flag, base URL,
  resolved) behind `routing.runtime_facts` — the system prompt gains a `runtime-model` section that
  names the session's model and provider, `self.info.llm` carries the same facts, and the chat route
  falls back to the session pin before the role default. Stable per model, so the prefix cache is not
  invalidated per turn. Pinned by `v718` (23/23).
- **A truncated subagent is a FAILURE, and the plan shows a run's real ending (`v924`/`v925`).**
  A child stopped at its step budget still ended `status: done`, so the Session-Job scheduler marked
  the subjob `done` and handed the sentinel text to every dependent as input — a dependent then worked
  "based on" a truncation (live SJ19, 2026-11-09). Any non-`completed` termination is now recorded as
  a subjob error, the sentinel names the run's evidence file (`data/graphs/<run>.json`, one builder
  for both run loops), and run-finalize closes a `max_steps`/`error` run's open nodes as `cancelled`
  with honest evidence instead of a fabricated "run completed" (an `aborted` run is still finalized
  by nobody, JAG-462). Pinned by `v924` (7/7), `v925` (7/7); `v459` J1's source pin follows the new
  call shape.
- **A restart no longer fails the dependents of an in-flight job (`v926`).** At boot the jobs sweep
  marked every still-`running` job `error: "interrupted by restart"` and then `wake()` treated that
  marker like any failed blocker, so waiting dependents got `error: "dependency failed: J<N>"` even
  though the blocker never failed — observed on every restart (J25<-J24, J35<-J34; both blockers
  later completed normally). The marker is now distinct: the dependent stays `blocked` and is
  released the moment the blocker really ends; a genuinely failed blocker still fails its dependent
  loudly. Pinned by `v926` (5/5); `v348` C2 revised to the new semantics (+C3 release proof).
- **`fs.edit` diffs now resolve the file shown by the tool card.** The edit journal stores absolute paths while the card supplies workspace-relative paths; a unique relative suffix now resolves safely, while ambiguous suffixes are rejected. The card uses compact, theme-aware SVG diff/editor buttons with accessible names and visible keyboard focus (`v872`).
- **A free-group label is a SUMMARY, never a copy of the prompt, and the 🏷 button no longer looks dead
  (extends `v469` / `v453`, no new number).** The rail showed a group's "title" AND its "summary" as two
  slices of the user's own prompt: a deterministic fallback titled every group with the first words of
  its request (`req[:240]` as the summary) and ran before every auto-compaction, so it claimed each
  group before any model could name it — and the 🏷 button only renames UNTITLED groups, so those copies
  were permanent. It is gone. Naming is a model job only; `threads._is_copy` (the label's tokens are a
  prefix of the request's) lets `set_title` REFUSE a copy at the one write point, `_normalise_titles`
  repairs already-stored copies on read (dropped, persisted), and the naming prompt (English-only) asks
  for a 3-7 word paraphrase in the request's language. Root cause measured live on `b7329cccf94c` /
  `dgx:nex-n25`: the naming call was budgeted 800 tokens, the reasoning model spent ALL of them thinking
  and answered 0 characters (the JAG-487 pattern, now retried here too). The route also held the HTTP
  request open for the whole call — minutes on a local model — so the button spun with nothing
  happening: it now answers in 0.3 s and the naming runs in a background thread, the labels repaint one
  by one through `threads.updated`, and `threads.named` closes the run with the totals (or the honest
  "the model returned no summary"). Verified live: 12/12 groups named (`Stabilisci se modificare
  Longrun`, `Audit every subagent output`, …), zero copies, no group left untitled.
- **One version string, so an agent cannot carry a false self-image (`v852`).** The self-knowledge
  block injected into every system prompt said *"you are Longrun v0.6"* while `/api/self` answered
  `1.0.0` — found live in A54's context, then traced to a hand-typed literal in `agent.py` and a
  second one in `server.py`. The package root (`longrun.__version__`) now owns the version,
  `server.VERSION` reads it, and `self_summary()` formats it with a placeholder instead of text;
  `v852_self_knowledge_version` pins all three surfaces (package, `server.VERSION`, prompt, `/api/self`)
  to the same value and fails if any literal `v0.x` reappears.
- **A sub-tool froze the guardrails it inherited (V-3, `v822`).** The permissions panel
  wrote a sub-tool's whole effective entry — its inherited `deny` list included — into the
  local overlay, so a later change to the shipped namespace list never reached it:
  measured live, `shell.exec` kept 8 of the 9 shipped `shell` rules and a secrets guard was
  off. The panel now diffs a sub-tool against its NAMESPACE entry, the same precedence the
  tool spec uses.
- **Settings and the ✨ AI draft moved out of the topbar and the composer into the chat
  rail, level with the send button (operator request, 2026-11-03).** The ✨ ate the
  composer's horizontal space and the settings gear sat in the topbar. Both now live in
  a two-level vertical rail between the chat and the inspector: its `.tb-mid` block
  keeps the session tools (hidden without a session) and its `.tb-foot` pins the ✨
  ABOVE the settings gear (both level with the send button, above the mobile tab bar
  `--sf-bottombar`). The rail is no longer hidden when there is no session, so Settings
  stays reachable on a fresh install and the ✨ can write an empty chat's opening
  message (RH-27, order set by RH-28).
- **A probe's `config.json` leaked a dead `/tmp` workspace path into the checkout.**
  `v772_generate_surfaces` points `LONGRUN_CONFIG_DIR` at the real `config/` to read
  `roles.generate`, and the session store then persisted `last_workspace` there. The
  test now snapshots and restores that file, and `config/config.json` is gitignored as
  per-machine runtime state — it was never tracked (RH-28).
- **A chain-of-thought was truncated on screen while the stored one was complete.**
  The live stream stopped after 20 000 chars and appended `… (live thinking
  truncated)`, and the page then trimmed that text to its last 40 000 chars — so a
  long monologue began mid-sentence and lost its tail, while the transcript held the
  whole reasoning. The live CoT now streams the whole thought (`LONGRUN_THINK_LIVE_CAP`
  defaults to 0 = no cap, >0 stays an explicit opt-in) and the page appends without
  trimming; the 80 ms coalescing that protects the render queue is untouched (RH-26).
- **The 🏷 button spelled every free-group title `request to …`.** The prefix was
  produced in three places (the model-naming prompt, the deterministic fallback and
  the `chapters` tool schema) and **persisted** in the durable thread ledger, so it
  survived compaction and every reload. One rule (`threads._clean_title`) now strips
  it on write, on derivation and on the chapter mirrored onto a group's start
  message; a ledger written before the change is normalised on read and saved, so the
  ledger and the UI cannot spell one title two ways (RH-25).
- **MCP servers reported `npx` as "not installed on this host" while it was
  installed.** `~/.local/bin` is where a per-user Node install puts `npx`/`node`,
  and the systemd USER service inherits a PATH without it, so `shutil.which("npx")`
  failed inside the service: the panel disabled every `command: npx` client, and a
  spawn would have died with `ENOENT`. `osutil.launcher_path()` is now the ONE
  place that builds the launcher PATH (per-user bin dirs prepended; POSIX-only,
  Windows keeps its PATHEXT resolution), and the availability probe, the `mcp.test`
  check and the spawn all use it — the panel can no longer disagree with the launch.
  Probed live: `/home/jagones/.local/bin/npx` → npm, node v22.11.0.
- **A session deleted mid-turn no longer kills the turn's own exit (`v952`).** The streaming worker
  released the turn lock through a FRESH `_turn_lock(sid)` lookup, and `delete_session` pops that lock
  out of the registry: the lookup built a NEW, un-acquired lock, so `release()` raised
  `RuntimeError: cannot release un-acquired lock` inside the worker's `finally` — a traceback from a
  turn that was already over, on a lock nobody held. The worker now binds the lock object at acquire
  and releases THAT. Its neighbour got the same treatment: `turn_end` publishes to the event store and
  sat one line above the release, so a full/locked store (the RH-12 condition) would have left the
  session's lock held by a DEAD worker and wedged every later turn — it is wrapped in its own `try`;
  the release then runs unconditionally. (Locked by `v952` 11/11, red 7/9 before the fix — the
  `RuntimeError` reproduced on the real delete door — and D2 red without the second guard; `v422` F3
  re-pointed to the new, stronger shape; live: a real turn answered, its session deleted, journal clean.)

### Added
- **Sidebar stops fabricating agent ids (phantom-A class closed, v606).**
  Agentless sessions rendered `A<sequence>` (e.g. `A189` for `cmptest1`) —
  an agent that does not exist. The rail badge now renders the roster id
  (`A49`) only for designated agents, else the honest `J` sequence
  (`J189`, tooltiped "no designated agent"). Resolver untouched; render-only
  fix. Evidence: 43-session census (max #202), `_agentNum` fallback path,
  no other `A"+num` fabrication left in the WebUI.
  (Locked by `v606` 4/4; `v286` 26/26 + `v604` 4/4 unchanged.)
- **Research · web → notebook moved above Sources in the KB panel.**
  (Operator request; `v402` 28/28 unchanged, order-agnostic.)
- **`.agent` consolidation: MATRIX/ archived, single spec index.**
  `archive/MATRIX/` (landed long ago), `SPEC-INDEX.md` (the one spec system:
  5 normative docs + procedures + history + debug loop), `MAINTENANCE.md` +
  project-rules pointers. `design-agents-jobs.md` stays (referenced by
  `agents.py`); the frontier plan stays (research continuity).
- **Research live-verified end to end (WebUI + REST, 2026-10-25).**
  Phase A (default model): shallow run from the Knowledge panel — 5 relevant
  sources imported, chunks indexed and searchable, zero console errors. Phase C
  (live model): cited summary with inline `[title](url)` + Sources section.
  Finding: the summary degrades SILENTLY to the `Research summary about: …`
  stub when the model is dead — default `perplexity:sonar-pro` has no
  `PERPLEXITY_API_KEY` on this machine AND catalogue
  `openai/gpt-4o-mini-search-preview` is retired (OpenRouter 404). Keep
  catalogue ids live and the default key present or the v603 contract is void.
  Test notebooks removed afterwards; default model restored.
- **Docs coherence: `docs/CLI.md` covers knowledge/research/index/embeddings.**
  New section + full §3 endpoint rows (`knowledge/*`, `research/model`,
  `codebase/*`, `embedding/active`). Machine-checked: all 77 ARCHITECTURE
  modules exist on disk and are named in the map; all 39 `forge` subcommands
  exist in code (`.agent/trash/docs_coherence.py`).
- **Docs self-organization.** New `.agent/docs/reference/MAINTENANCE.md` (WHEN+HOW per
  section, same-session rule); `AGENTS.md` points at it and drops the stale
  `reports/` reference; `UserPrompts.md` rewritten without leading-dash lists
  (Trae preview hid them) + §3.5 live-verification note.
- **Docs freshness pass (no code).**
  `docs/ARCHITECTURE.md` is a living map again (verified 2026-10-25, SJ level
  added, stale Subjob-only model fixed, generated diagrams marked WIP);
  `docs/RESEARCH-frontier-harnesses-2026.md` marked superseded (current:
  `.agent/docs/research/` + `harness-strengths.md`); `docs/TESTING-PLAYBOOK.md`
  gate commands fixed; `docs/CLI.md` freshness note. Frontier reports merged
  into `.agent/docs/research/` (single stream, no `reports/` split); papers
  `.txt` declared KB-chunk provenance with the correct PDF → `.md` pipeline
  (`markitdown` MCP / `pdf-monster` skill / DGX `fitz`); `harness-strengths.md`
  statuses updated (v595–v598 landed) with a same-commit freshness contract.
  New project rule: docs never go stale silently.
- **Explicit search provider chain (DeerFlow-grade packaging, tool level).**
  `_web_search` was one hardcoded tavily → brave → duckduckgo body; now one
  function per provider (`_search_tavily/_search_brave/_search_duckduckgo`)
  with an ordered fall-through dispatcher. The order is config-overridable
  (`search_providers` in `config/index.yaml` via `researchcfg`) or per-call
  (`providers=`); unknown names are ignored, a dead provider never kills the
  search. Same single `web` tool surface, no new tool, no architecture touched.
  (Locked by `v605` 6/6; `v402` 28/28 unchanged.)
- **Todo labels name a real owner (single source of truth).**
  `A155.n40` was a phantom: node `n40`, agent A49, session number J155 —
  no A155 exists. `_todoid` now resolves against the roster
  (`_agents[sessionId].id` → `A49.n40`); plain sessions fall back to their
  own session number (`J180.n87`); the header J-number carries a tooltip
  (session's own id — team jobs live in Control). One resolver, both
  panels. (Locked by `v604` 4/4; `v286` evolved 26/26.)
- **Plan header tells the truth (job namespace + run-start goal + word cut).**
  The header prefix used the agent namespace (`A180` for job J180, colliding
  with agent ids like A54/A51) — now `J180`. When plans moved on past the run
  start, the goal carries a `· run-start goal` label (live counts, fossil
  text — now declared). The 80-char preview cuts at a word boundary.
  (Locked by `v602` 4/4.)
- **Research citation contract (DeerFlow gap 4, prompt level).**
  The researcher role and the research summary prompt now REQUIRE inline
  `[title](url)` citations on every claim plus a link-only Sources section —
  "cited summary" is a contract now, not a wish. No architecture touched:
  two strings, same read paths (`subagents.yaml` roles, `research.run`).
  (Locked by `v603` 4/4; `v402` 28/28 unchanged.)
- **Plan header goal dropdown + self-explaining evidence badge.**
  The Plan panel header hard-cut the run goal at 40 chars with no ellipsis
  and no way to read the rest (`Team results: A50: ## Report **Il re-di…`).
  It now keeps an 80-char preview ending in … and the FULL goal in the usual
  expandable dropdown (`details.goalfull`, escaped, scrollable); the `📎 N`
  evidence count carries a tooltip (click the row to view evidence and jump
  the chat to the step). Counts, OLD PLAN history and ⏮ rewind untouched.
  (Locked by `v601` 5/5.)
- **Agents table session button + 3 pastel eye-saver themes.**
  The Agents panel rows now carry the same explicit "go to chat session"
  button the Jobs list has (JAG-484 precedent), wired to the deck's shared
  `onOpenAgent` opener — no duplicated open logic, row clicks stop at the
  button. Plus three complete eye-saver themes with full token sets in both
  the WebUI and the Bridge: Celestial (pastel sky-blue daylight), Sakura
  (pastel cherry-blossom daylight, WCAG-AA darkened blossom accent), Haze
  (muted lavender-grey night). (Locked by `v600` 6/6; `v352` evolved 42/42,
  `v364` evolved 9-preview.)
- **1-based task plans with one-way migration.**
  New graphs open plan 1 (no more "older plan 0"); `load()` migrates legacy
  graphs once (every stored plan + 1, untagged nodes count as plan 0, `plan_base`
  marker, persisted; idempotent); all defaults (`plan_nodes`, `add_node`,
  `drop_plan`, `latest_plan_nodes`, WebUI `planNodes`) moved 0 -> 1. (Locked by
  `v599` 16/16; v183/v195/v296/v327/v512 expectations evolved.)
- **F5 Maka thresholded release: eval promotion bar + patience.**
  `selfevolve.verify()` persists a consecutive-green `green_streak` in
  proposal.json (red resets to 0); `promote()` releases only when the
  streak reaches `min_green_streak` (default 1 = today's behavior; legacy
  `verified` proposals without a streak key count as 1; invalid bars fail
  closed), checked before the held-out gate; the bar is operator-settable
  via `update_policy(selfevolve.min_green_streak)`. (Locked by `v598` 13/13;
  v205/v280/v251 unchanged.)
- **F4 Cline plan-before-act: session plan mode gates mutating tools.**
  `stores.set_plan_mode()` / `propose_plan()` / `approve_plan()` /
  `reject_plan()` persist the propose→approve→act state machine (empty
  plans and double approvals raise); `registry.PLAN_GATED_TOOLS`
  (fs.write/fs.edit/shell/git/python, both names) + pure
  `session_plan_locked()`; `classify()` denies gated tools for locked
  sessions while read-only tools pass, and even `approvals.mode=full`
  never bypasses the explicit lock. (Locked by `v597` 16/16.)
- **F3 Aider post-edit loop: zero-config Python syntax gate.**
  `plan.verify.syntax_gate()` `compile()`s every `.py` target of
  fs.write/fs.edit and, on SyntaxError/ValueError, rolls the change back
  to the pre-image and returns the error for fix-and-retry (Aider style);
  `_verify_edit()` runs the gate first, before the operator-configured
  verifier. Green, out-of-scope, and unreadable files pass through
  untouched; the gate never breaks a write. (Locked by `v596` 10/10.)
- **P3 Codex trust profiles: named session sandbox bindings.**
  `sandbox.TRUST_PROFILES = ("locked", "standard", "open")` + pure
  `trust_profile()` (unknown names raise, JAG-2.7 style); `run(...,
  trust=)` forces an isolated backend under `locked` (exit-126 refusal,
  never the host, when host-only) and explicit host execution under
  `open`; sessions persist `trust` (`get_or_create_session(trust=)`,
  `set_session_trust()`); `_shell` resolves the session trust, skips the
  host-terminal shortcut when locked, and passes trust through (as does
  `_python`). (Locked by `v595` 18/18.)
- **P3 CCCC delivery facts: handoff receipts (stored/delivered/replied).**
  `jobs.record_handoff()` persists the handoff inject AND a receipt
  `{id, ts, to, kind, after}` on the subjob; pure `handoff_state()` maps it to
  `stored` / `delivered` (target advanced past the receipt, so the handoff
  entered its context) / `replied` (subjob finished with result or reason);
  `handoff_status()` resolves live states; `_log_escalation` routes both chats
  through receipts with unchanged texts. (Locked by `v594` 17/17.)
- **P2 canonical permission: grants bound to the requesting run.** Maka
  `rememberForTurn` direction on top of M4a consumable grants: `create()`
  stamps `turn_scope` from `run_id`, `consume()` denies cross-run spending
  ("approval belongs to another run") while multi-use inside the run keeps
  working via `uses_left`; unscoped legacy records and run-less callers are
  untouched (no migration); both production consume sites pass their `run_id`.
  (Locked by `v593` 11/11.)
- **OctoMind done-gate: explicit finishes with open work face the closure check.**
  `{"action":"finish","summary":...}` used to break out of the turn loop before
  keepgoing/JAG-402, closing the turn with open todos and no verification. Now
  `agent._finish_gated()` sends non-goal finishes with unfinished work through
  the same bounded verdict (`_selfcheck_left`, `_closure_check_prompt`); clean
  finishes still disarm the check, goal mode keeps its recovery path. v584 pins
  updated for the 4th check (locked by `v592` 11/11).
- **P2 skill trust: content digests bound to (name, path).** OpenClaw's
  skillBinTrust adapted to prompt-only skills (Longrun never executes skill
  binaries, but a swapped SKILL.md silently changes what the model reads):
  `skills.skill_digest()` (sha256 of the bytes), `digest` on every
  `list_skills()` entry, pure `verify_skill_digests()` (ok/changed/new/gone),
  trust-on-first-install stamping in `install_zip()`, and `changed` reporting
  in `audit_skills()` (locked by `v591` 17/17).
- **M10 slice: killed turns are classified, resume records persisted.**
  From the DeepSeek resume/fork/replay direction: `stores.classify_interruption()`
  tells `interrupted_before_effect` (zero current-turn tool cards + PRE-turn
  checkpoint present — replay is safe) from `unknown_effect` (any executed card
  or no checkpoint). `reconcile_orphan_turns()` persists
  `sess["interrupted"] = {effect, executed, checkpoint}` and words the notice by
  effect (resume-from-checkpoint vs send-a-new-message); the meta carries
  `interrupt_effect`. Auto-resume execution itself stays future work — the
  record it needs now exists (locked by `v590` 12/12).
- **Paperclip-grade policy: `rate_limit` + `argument_filters` in `registry.classify()`.**
  From round-3 harness comparison (Paperclip N3): a tool policy may carry
  `rate_limit: {max_calls, window_secs}` (over-budget calls denied fail-closed,
  window expiry resets, invalid config denies) and `argument_filters:
  [{match, decision}]` (full arg match forces `required`/`denied`). Checked after
  `approvals.mode` (full bypasses, like the M11 gate) and before the per-tool
  `auto` fast path; plumbed through `tool_spec` so `config/tools.yaml` entries
  work with no migration (locked by `v589` 20/20).
- **Upgrade Lotto 2 (M1 + M6) is implemented and green.** `model/structured.py`
  validates model replies against an inline JSON Schema subset (stdlib only:
  `$ref` rejected up front, first JSON span extracted from prose/fences,
  `$.path` errors capped at 10, verbatim-errors single retry without re-pasting
  the schema); `subagent.spawn(..., output_schema=...)` rejects malformed schemas
  before spawning, appends the OUTPUT CONTRACT to the child goal, and `collect`
  validates with exactly one sibling repair turn — a run never fails for schema
  (locked by `v560` 21/21). The v2 loop now passes a usage dict to every model
  call, accumulates `RunState.tokens_spent`, counts subagent descendants via
  `parent_run_id`, and stops with `termination="budget"` when `token_budget` is
  reached; missing usage adds 0, never a chars/4 fiction (locked by `v561`
  15/15). FAST battery 254/254.
- **Upgrade Lotto 1 (M11 + M5 + M12) is implemented and green.** From the
  frontier-harness comparison (`.agent/reports/2026-10-24_frontier-harness-kb-vs-longrun.md`):
  `improve.evolve` now passes an approval gate (`registry.subtool_gate`, locked by `v555`
  10/10); the v2 agent loop caps a run when one tool *type* saturates a 50-call window
  (`warn` 30 → nudge, `hard` 50 → `no_progress` + `agent.loop_capped`, shell override
  100/200, `loop_detection` in `config/tools.yaml`, locked by `v556` 12/12); the system
  prompt carries a static `security-policy` section (order 22: prompt injection,
  authority, scope, finish — exactly one "prompt injection" in the assembled prompt,
  locked by `v557` 13/13). FAST battery 252/252.
- **The Cost panel now accounts ATTEMPTS, not just successes.** Every model call is a
  ledger row, including the ones that failed and the ones where the provider reported no
  counters. Rows carry `status`, `usage_basis` (`reported`/`missing`), `latency_ms` and,
  for failures, the error text — so a retry or an outage can no longer look like "$0.00"
  or vanish from the panel. The header adds `N failed · M no usage · p50 Xms`, and each
  row/run shows a `failed` or `no usage` badge. Shape borrowed from Maka's
  `usage_model_call_attempts` (see `.agent/docs/research/notes/2026-10/2026-10-24_maka-usage-ledger.md`);
  no Maka code was copied. Locked by `v558`.
- **The regression gate now says where it is.** `tests/battery.sh` truncates and then
  appends `.agent/logs/battery-progress.log` in real time — `RUN`, one `START`/`END <test>
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

### Changed
- **CLI route parity is pinned (JAG-CLId/e).** `v588` proves every `forge.py` endpoint exists on the server (99 paths across the four route files, including the `_is`/tuple dispatch forms) and every call uses a served HTTP method (128 method+path pairs: `do_GET/do_POST` regions, `method ==` blocks, per-branch gates). 6/6.
### Changed
- **CLI parity: usage, encoding, docs (JAG-CLI).** The `forge.py` Usage block now lists every subcommand (`agents`, `jobs`, `routines`, `roles`, `index`, `knowledge`, `research`, `embedding`, plus the newer `sessions`/`runs`/ `context`/`models`/`mcp` actions); `forge events --session/--kind` URL-encodes its values instead of splicing them raw; `docs/CLI.md` no longer advertises `runs summary --limit` or `context show --model`, flags the parser never had. Locked by `v587` 16/16.
- **README is now the pitch, and the banner wears the runner.** The header drops
  the standalone icon (the banner carries the runner mark), opens with a
  one-liner plus a six-row capability table, and adds a Table of Contents, a
  "Why Longrun" section, and a dispatch/batch/job orchestration example. The
  "Data and search" section no longer claims data lives under
  `<repository>/data/` — it points at the data home. Install sections are
  untouched. The hero is now centered with its tagline (CCCC pattern), the
  leftover bolt is gone everywhere: `assets/logo.svg` carries the runner mark
  like `assets/icon.svg`, and the browser tab title no longer uses the bolt.
- **Keys live in ONE file: the repo `.env`.** Settings ▸ Keys already WROTE there, but
  the harness also READ `~/.hermes/.env`, so a key could look "set" while the panel
  could not find or clear it. `env_files` (providers + MCP), `keys.read_secret()` and
  `tools._secret()` now use the repo `.env` only; the Settings help says so. Existing
  values were migrated into the repo `.env` before the fallback was removed.
  Locked by `v493` C7–C9.
- **The RH Terminal is tabbed.** The panel showed only the SESSION shell, while the
  `shell` tool keys its terminal on the RUN id — so every agent run (and every
  subagent) had a terminal the operator could not see. `GET /api/term/list` now
  returns every live shell (session, busy, cwd) and the panel renders one tab per
  shell, polling/executing on the SELECTED key. Locked by `v530` I1–I4.
- **No local models in the shipped routing defaults.** `chat`/`agent` pointed at
  `pattern: qwen`, which matches nothing on a router that has no qwen loaded (→ `400
  model 'qwen' not found`). Both roles now name explicit cloud models with a cloud
  fallback; local providers stay available for anyone who pins them, they are just
  no longer the default.

### Fixed
- **Every run that called a remote provider died with `message_body should be a bytes-like
  object or an iterable, got <class 'int'>`.** `_open_with_retry` called
  `urllib.request.urlopen(req, timeout)`, but `urlopen(url, data=None, timeout=...)` binds
  its SECOND POSITIONAL argument to `data` — so the integer timeout overwrote the JSON
  completion body and `http.client` raised `TypeError` before a single byte left the box.
  The timeout is now passed by keyword (`urlopen(req, timeout=timeout)`) at both call
  sites. Found while driving the real Paperclip adapter (the external adapter was fine:
  it built a valid bytes body, the fault was downstream in Longrun's model client).
  Locked by `v575` (5/5) — the test drives a real `http.server` over a real socket and
  asserts the server received the exact body, plus that `urlopen` gets no positional
  argument.
- **Attached images reached the agent as a knowledge-base riddle.** `deepseek:deepseek-flash`
  IS vision-capable (verified live: a 64x64 solid-red PNG came back as "red") but the
  catalogue had no `vision` flag, so the harness told the model it could not see; the
  composer then also auto-ingested every image into the session notebook with a "read it
  with `knowledge.search`" hint, and `knowledge.read_source` rejected the filename the
  search shows. Result: an invented OCR story and two failed tool calls. Now: an image
  reports `indexable: false` + `visual: true` and travels as `image_url` pixels; the
  attachment preamble forbids the KB/OCR detour; a text-only model gets an explicit
  cannot-see note and the composer warns BEFORE sending; `read_source` resolves a source
  by title or basename as well as by path/id. Locked by `v559` (21/21) and the updated
  contract in `v490` I1–I2b.
- **A projector-equipped model could still be declared blind.** `model_supports_vision()`
  read the fallback `meta.architecture.input_modalities`, but the live llama.cpp router
  exposes `architecture` at the TOP LEVEL of the `/v1/models` entry, so the fallback
  never fired and the harness told the model "you cannot see these images". The
  top-level shape is now read first (the `meta` shape still works). Locked by `v462`
  A4b–A4d (vision section 36/36 PASS).
- **The DGX GLM context was over-declared in the catalogue.** `config/providers.yaml`
  advertised `glm-5.3-flash-iq2` with `context_length: 262144` while the router runs it
  at 131072, corrupting the context budget. Now 131072. *(The model was retired and its
  weights deleted the same day; the entry is gone from the DGX catalogue. The same
  applies to the censored `qwen-3.8-flash-next-iq3`.)*
- **A stale assertion kept the gate red.** `v494` C1 still required `pattern: qwen` in
  `routing.yaml`, which `45b4636` had intentionally replaced with explicit cloud
  `model:` refs. The check now asserts the current contract (no local alias pattern,
  explicit `model: openrouter:` refs, no default advertised in the README). Battery
  back to 247/247.
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
- **Nucleous snapshot restores no longer blame concurrent Longrun writers.**
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
- **The Nucleous write gate no longer loses a symlink race it cannot see.** The gate
  judges paths AS WRITTEN before the command runs, so
  `ln -sfn <nucleous>/tools /tmp/nl && echo probe > /tmp/nl/_p.txt` passed (at check
  time the link did not exist) and wrote through it into the Nucleous. Creating a
  symlink whose SOURCE resolves inside the Nucleous is now refused outright. Pinned by
  `v498` P.
- **A file created inside the Nucleous is removed whatever its extension.** The
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
  after selecting a session whose workspace is `/home/jagones/Repositories/_workspace/TESTS` the
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
  Multi-subtool modules must be removed by namespace; a promoted Nucleous copy is
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
  the real file. Verified live: the link opened `/home/jagones/Repositories/MyRepos/sparkpulse-server/status_server.py`.
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

## [1.1.0] — 2026-10-23

The second tagged release: 296 commits, **99 features and 100 fixes**, battery 105 → 248
acceptance tests. It turns the harness from "one strong agent plus a team" into a
self-extending, fully editable one.

### Added
- **Matrix — self-evolution, live (`src/Matrix` + its runtime dir).** A second, agent-editable
  zone beside the protected Nucleous: `src/Matrix/<subpkg>/hooks.py` is loaded fail-open on the
  next call, `matrix.enable`/`disable`/`status` toggle it without a restart, and
  `promote_to_nucleous` moves a proven artifact into the core through verification,
  checkpoint and commit gates.
- **longrunAgent (the VEO)** — a permanent stateless system-automation agent that drives the
  WebUI substrate itself (model picker, editing sections, session grant), plus the Teamorg
  view; its tools become one tool per object per verb and it can never be unpinned.
- **Session Jobs (`sj`)** — dependency-ordered subagents inside ONE session, with their own
  ledger directory and no-progress children failing their dependents.
- **Parallel batch dispatch** — several teammates in one `{"action": "batch", ...}` call run
  CONCURRENTLY, plus a direct command-palette button.
- **`sessions.wait`** — a peer waits for the matching job's reply or failure instead of
  polling a transcript.
- **Two search stores, split by scope** — a per-workspace CODEBASE index and a GLOBAL
  KNOWLEDGE base (notebooks), both stdlib: FTS5/bm25 with AST chunking and optional
  embeddings; document ingestion for PDF/Office/OCR (docling backend) and image sources.
- **Embeddings and research with real costs** — a multi-model embedding catalogue, USD cost
  tracking, and a deep-research agent whose prompt/model are chosen in Settings.
- **Rewind** — per-checkpoint and per-todo rewind from the WebUI, with the task graph
  restored to the matching anchor.
- **Rewritten WebUI shell** — Session / Control tabs, a one-row composer, the Orbit deck
  embedded as an in-page view, six themes, a run-grouped cost panel, a mobile header, an
  installable PWA manifest, and keyboard search in every file browser.
- **Every config knob editable** — object editors for `config/*.yaml` (providers, prompts,
  roles, tools, compaction, embeddings) with a sparse overlay, so a save never rewrites the
  shipped comments.
- **Paperclip adapter** — Longrun as an executable arm for the Paperclip control plane.
- **Shell cwd policy as two root-scoped approval tiers**, documented in the UI.

### Changed
- **User data left the checkout.** One configurable data home (`~/.longrun`, or
  `%LOCALAPPDATA%\Longrun`) holds sessions, events, indexes, costs and the Matrix runtime;
  per-workspace project state moved out of the user's projects too, with a rescue path for
  every older layout.
- **Tools became discoverable** instead of being dumped in the prompt, and the Tools &
  approvals panel is grouped by namespace.
- **Compaction** summarises the WHOLE old transcript (map-reduce) instead of head+tail, and a
  role may follow the chat model dynamically.

### Fixed
- **A no-progress child subjob is a failed dependency, not a done one.**
- **Compaction policy and skill search stay coherent**; peer waits are correlated and Nucleous
  writes serialised.
- **The sandbox never runs on the host under an unknown backend name**, and the Nucleous guard
  is deny-only (the auto-revert is gone).

### Quality
- **Battery 105 → 248 deterministic acceptance tests**, all green at the tag.

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
