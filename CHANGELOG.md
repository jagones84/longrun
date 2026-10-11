# Changelog

All notable changes to Longrun are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project adheres to
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
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

### Changed
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

### Fixed
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
