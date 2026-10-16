# Longrun Paperclip Adapter Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Run one Longrun agent task from a Paperclip assignment through a locally installable external adapter, stream safe progress events to Paperclip, and report an accurate terminal result.

**Architecture:** Keep the Paperclip adapter package and Python producer in the Longrun repository. A Node/TypeScript Paperclip plugin starts `python forge.py paperclip-bot`, supplies a run-scoped JSON envelope on stdin, parses validated NDJSON, emits `AdapterRuntimeEvent`s, and returns an `AdapterExecutionResult`. The Python bridge calls Longrun's authenticated JSON-body SSE route, forwards an allowlist of events, and aborts a known remote run on cancellation.

**Tech Stack:** Python standard library; existing Longrun `forge.py` CLI, HTTP API, and acceptance battery; Node.js ESM and TypeScript; Paperclip `@paperclipai/adapter-utils`; Vitest for package tests.

**Spec:** [2026-10-16-paperclip-adapter-design.md](../specs/2026-10-16-paperclip-adapter-design.md)

## Global Constraints

- Paperclip core, Runner, and Rust broker remain unchanged.
- Longrun's Python runtime remains standard-library-only; Node dependencies stay inside `integrations/paperclip/`.
- CLI stdout contains only `longrun.paperclip.event.v1` NDJSON frames; diagnostics go to stderr.
- Paperclip and Longrun credentials remain separate and never appear in argv, stdin payloads, NDJSON, run logs, or error messages.
- Never forward `agent.think`, raw observations, tool arguments/results, or the full Longrun trace.
- A Paperclip execution starts at most one Longrun run; ambiguous dispatch is not retried automatically.
- Only Longrun termination `completed` maps to a successful Paperclip adapter result.
- No attachments, Paperclip workspace access, inbound bot conversations, or cross-heartbeat session recovery in this release.
- Python and TypeScript tests are deterministic and make no LLM calls.
- Work in the existing Longrun checkout. Do not create a git worktree or commit/push without an explicit request.

## Review Focus

1. **Lost SSE before the run ID arrives:** never start a second run; return an indeterminate failure and record that remote cleanup cannot be proven.
2. **Cancellation after run start:** send exactly one `POST /api/agent/control` abort for the known run ID and settle the child process.
3. **False success at max steps/no progress:** assert only `termination == "completed"` produces exit code zero.
4. **Malformed or fragmented NDJSON/SSE:** buffer split chunks, enforce frame bounds, and reject malformed JSON or non-monotonic sequence numbers.
5. **Secret and private-content leakage:** verify Longrun/Paperclip tokens, reasoning, raw observations, and tool payloads do not enter events or logs.

---

## File Map

| File | Responsibility |
|---|---|
| `src/longrun/core/api_v02.py` | Machine-readable terminal classification and authenticated POST-SSE agent-run route. |
| `src/longrun/core/forge.py` | Register `paperclip-bot` in the existing CLI dispatcher. |
| `src/longrun/integrations/paperclip_adapter.py` | Longrun HTTP/SSE client, cancellation, and Longrun-to-neutral-event mapping. |
| `src/longrun/integrations/paperclip_bot.py` | Validate stdin invocation, emit NDJSON, and translate failures to process exit status. |
| `integrations/paperclip/package.json` | Standalone Paperclip external adapter package metadata and scripts. |
| `integrations/paperclip/package-lock.json` | Locked external adapter package dependencies. |
| `integrations/paperclip/src/index.ts` | `createServerAdapter()` entry point and adapter metadata. |
| `integrations/paperclip/src/server/execute.ts` | Spawn Python bridge, validate NDJSON, emit Paperclip events, and return final result. |
| `integrations/paperclip/src/server/config-schema.ts` | Operator-facing command, URL, timeout, model, and max-step settings. |
| `integrations/paperclip/src/server/test.ts` | Readiness checks without starting a model run. |
| `integrations/paperclip/src/server/ndjson.ts` | Bounded, incremental frame decoder and schema/sequence validation. |
| `integrations/paperclip/test/` | Deterministic package tests and fake child-process fixtures. |
| `integrations/paperclip/test/fixtures/fake-longrun.mjs` | Fake child executable for adapter process tests. |
| `integrations/paperclip/test/fixtures/fake-longrun-http.mjs` | Fake Longrun HTTP/SSE service for local Paperclip smoke. |
| `tests/acceptance/v464_paperclip_run_outcome.py` | Deterministic run terminal classification regression tests. |
| `tests/acceptance/v465_paperclip_stream_route.py` | JSON-body SSE endpoint, initial run ID, terminal event, and cancellation-route tests. |
| `tests/acceptance/v466_paperclip_rest_bridge.py` | Python HTTP/SSE parsing, auth, mapping, timeout, and abort tests. |
| `tests/acceptance/v467_paperclip_bot_cli.py` | CLI stdin/stdout/stderr, exit code, and fixture-server tests. |
| `tests/acceptance/v468_paperclip_docs.py` | CLI command/docs parity assertions. |
| `integrations/paperclip/README.md` | Package install and adapter configuration instructions. |
| `.agent/README-paperclip-adapter.md` | Local maintainer runbook, Paperclip local-path registration, constraints, and future distribution notes. |
| `docs/CLI.md` | Document the new `paperclip-bot` command. |
| `CHANGELOG.md` | Add the user-visible integration under `Unreleased`. |

## Task 1: Machine-Readable Longrun Run Outcomes

**Files:**
- Modify: `src/longrun/core/api_v02.py` (`RunState`, `agent_run_v2`, `_result`)
- Create: `tests/acceptance/v464_paperclip_run_outcome.py`

**Interfaces:**
- Add `termination` to public run results with exactly these values:
  `completed`, `max_steps`, `no_progress`, `aborted`, `error`.
- Preserve the existing `status`, `summary`, and trace fields.
- Explicit model `finish` means `completed`; loop exhaustion means `max_steps`;
  repeated-action guard means `no_progress`; abort and exception paths mean
  `aborted` and `error`.

- [ ] **Step 1: Write failing deterministic outcome assertions**

  In `v464_paperclip_run_outcome.py`, exercise `agent_run_v2` with scripted
  actions and isolated `LONGRUN_*` directories. Assert:
  - explicit finish returns `termination == "completed"`;
  - one non-terminal scripted action with `max_steps=1` returns
    `termination == "max_steps"`;
  - repeated identical actions return `termination == "no_progress"`;
  - forced abort and a forced exception return `aborted` and `error`.
  Also assert `RunState.public()` exposes the same field.
  Name the cases `test_explicit_finish_is_completed`,
  `test_step_limit_is_not_completed`, `test_repeated_action_is_no_progress`,
  `test_operator_abort_is_aborted`, `test_exception_is_error`, and
  `test_public_run_exposes_termination`.

- [ ] **Step 2: Run the new acceptance test and confirm RED**

  Run: `python3 tests/acceptance/v464_paperclip_run_outcome.py`
  Expected: FAIL because the public result does not expose `termination`.

- [ ] **Step 3: Implement terminal classification**

  Initialize `RunState.termination` to `None`, set it at each terminal branch,
  and include it in both `_result()` and `RunState.public()`. Keep legacy
  `status` values and current summaries unchanged.

- [ ] **Step 4: Run the acceptance test and confirm GREEN**

  Run: `python3 tests/acceptance/v464_paperclip_run_outcome.py`
  Expected: all explicit finish, max-step, no-progress, abort, error, and public
  result assertions pass without a model call.

## Task 2: JSON-Body Streaming Run Endpoint

**Files:**
- Modify: `src/longrun/core/api_v02.py` (`handle`, POST routes, SSE run generator)
- Create: `tests/acceptance/v465_paperclip_stream_route.py`

**Interfaces:**
- Add `POST /api/agent/run/stream` with JSON fields `goal`, `max_steps`,
  optional `model`, and optional `session`.
- Return `text/event-stream`; emit the initial `run` frame before progress,
  preserve the existing agent event names, and include the Task 1 terminal
  classification in the terminal event.
- Keep existing `GET /api/agent/run` SSE and `POST /api/agent/run` JSON
  behavior unchanged.

- [ ] **Step 1: Write failing route-contract tests**

  Build a deterministic handler fixture and patch the run worker so no provider
  is called. Assert the POST route accepts a JSON goal, sends the initial run ID,
  streams a progress event and terminal classification, and ends with `done`.
  Add negative cases for a missing/non-string goal and malformed run settings.
  Use test names `test_post_stream_accepts_json_goal`,
  `test_post_stream_emits_run_progress_terminal_and_done`, and
  `test_post_stream_rejects_invalid_goal`.

- [ ] **Step 2: Run the route test and confirm RED**

  Run: `python3 tests/acceptance/v465_paperclip_stream_route.py`
  Expected: the new route returns 404 or does not produce the expected SSE
  frames.

- [ ] **Step 3: Implement the POST streaming route**

  Reuse `agent_stream_gen_v2` and existing run creation. Parse the JSON body,
  resolve only the configured Longrun session/workspace input, return the
  existing SSE framing helpers, and avoid duplicating the GET endpoint's run
  logic.

- [ ] **Step 4: Run the route test and confirm GREEN**

  Run: `python3 tests/acceptance/v465_paperclip_stream_route.py`
  Expected: valid requests stream ordered run/progress/terminal/done frames;
  invalid requests return structured 400 responses.

- [ ] **Step 5: Re-run outcome regression**

  Run: `python3 tests/acceptance/v464_paperclip_run_outcome.py`
  Expected: all Task 1 terminal classifications remain unchanged.

## Task 3: Python REST/SSE Adapter Library

**Files:**
- Create: `src/longrun/integrations/__init__.py`
- Create: `src/longrun/integrations/paperclip_adapter.py`
- Create/update: `tests/acceptance/v466_paperclip_rest_bridge.py`

**Interfaces:**
- `PaperclipInvocation` is a validated immutable record with schema
  `longrun.paperclip.invocation.v1` and fields `paperclip_run_id`, `agent_id`,
  `company_id`, nullable `task_id`, `goal`, optional `model`, `max_steps`, and
  optional operator-configured `session_id`.
- `LongrunApiClient(base_url, token, opener, timeout_sec)` provides
  `stream_run(invocation)`, `get_run(run_id)`, and `abort_run(run_id)`.
- `map_longrun_event(name, payload)` returns a safe protocol event or `None`.
- Protocol frames use `schema`, strictly increasing integer `seq`, `event`,
  nullable `run_id`, and bounded `payload`. `run_id` is null only for failures
  before Longrun returns its initial run frame. The schema is
  `longrun.paperclip.event.v1`; `event` is one of the five allowlisted names in
  the spec.

- [ ] **Step 1: Write failing protocol and client tests**

  Use a fake opener/HTTP response, not the network. Cover SSE comments,
  multiline `data`, arbitrary line boundaries, malformed JSON, start/progress/
  terminal mapping, and the rule that `agent.think`, `agent.observation`, raw
  tool events, and unknown events are not emitted. Simulate a disconnect before
  the first run-ID frame and assert the result is indeterminate, with no
  automatic second start request.
  Assert requests use the configured base URL and
  `Authorization: Bearer <LONGRUN_TOKEN>`, and that abort uses
  `{ "action": "abort", "runId": run_id }`.
  Name the focused cases `test_sse_parser_handles_comments_multiline_and_split_data`,
  `test_event_mapper_drops_reasoning_observations_and_unknown_events`,
  `test_disconnect_before_run_id_is_indeterminate_without_retry`, and
  `test_abort_targets_the_known_run_id`.

- [ ] **Step 2: Run the bridge test and confirm RED**

  Run: `python3 tests/acceptance/v466_paperclip_rest_bridge.py`
  Expected: imports or assertions fail because the adapter client/parser is
  missing.

- [ ] **Step 3: Implement the injectable REST/SSE client**

  Use `urllib.request`; do not add a Python dependency. Build the POST-SSE URL
  from the configured base URL, send invocation JSON in the body, parse SSE
  incrementally, fetch the final run record after stream completion, and abort
  the known run ID on cancellation. Never reconnect or create a replacement run
  after an ambiguous dispatch.

- [ ] **Step 4: Implement the safe event allowlist**

  Map `run` to `longrun.run.started`, `agent.iteration` to
  `longrun.run.progress`, successful `agent.finish` to
  `longrun.run.completed`, non-completed `agent.finish` and `agent.error` to
  `longrun.run.failed`, and `agent.aborted` to `longrun.run.cancelled`. Require
  the final run record and streamed terminal classification to agree. Emit an
  indeterminate/failure outcome if the run record is missing or contradictory.

- [ ] **Step 5: Run the bridge test and confirm GREEN**

  Run: `python3 tests/acceptance/v466_paperclip_rest_bridge.py`
  Expected: all framing, request, mapping, secret-boundary, abort, and
  indeterminate-outcome assertions pass without an LLM.

## Task 4: `paperclip-bot` CLI Shim

**Files:**
- Create: `src/longrun/integrations/paperclip_bot.py`
- Modify: `src/longrun/core/forge.py` (`main`, command dispatch)
- Create/update: `tests/acceptance/v467_paperclip_bot_cli.py`

**Interfaces:**
- Register `python forge.py paperclip-bot`; the command reads exactly one
  invocation JSON object from stdin.
- Read Longrun URL/token from `LONGRUN_URL` and `LONGRUN_TOKEN`; neither may
  be accepted from task content or written to argv/stdout.
- Emit protocol frames from Task 3 as NDJSON on stdout; human diagnostics go
  to stderr. Exit codes: `0` only for `completed`, `1` for incomplete,
  failed, or indeterminate outcomes, and `130` for operator cancellation.

- [ ] **Step 1: Write failing CLI contract tests**

  Launch `forge.py paperclip-bot` as a subprocess against a local fixture HTTP
  server. Assert valid stdin produces only parseable NDJSON on stdout, errors
  appear on stderr, no LLM is contacted, and process exit status matches the
  terminal classification. Cover empty input, invalid JSON, and missing goal.
  Use names `test_cli_emits_only_ndjson_for_valid_invocation`,
  `test_cli_rejects_invalid_stdin_before_network`,
  `test_cli_exit_code_tracks_terminal_classification`, and
  `test_cli_keeps_diagnostics_on_stderr`.

- [ ] **Step 2: Run the CLI test and confirm RED**

  Run: `python3 tests/acceptance/v467_paperclip_bot_cli.py`
  Expected: the subcommand is not registered and/or the protocol assertions
  fail.

- [ ] **Step 3: Implement input validation, signal cleanup, and CLI dispatch**

  Add a `paperclip-bot` argparse subcommand to `forge.py`. Keep command parsing
  in `forge.py`; put protocol work in the integration modules. Install a
  SIGTERM/SIGINT cleanup path that requests abort when a Longrun run ID is
  known, without printing credentials.

- [ ] **Step 4: Run the CLI test and confirm GREEN**

  Run: `python3 tests/acceptance/v467_paperclip_bot_cli.py`
  Expected: the subprocess protocol and exit code match the contract for
  completed, incomplete, aborted, and failed runs.

## Task 5: Standalone Paperclip Plugin Package

**Files:**
- Create: `integrations/paperclip/package.json`
- Create: `integrations/paperclip/tsconfig.json`
- Create: `integrations/paperclip/src/index.ts`
- Create: `integrations/paperclip/src/server/config-schema.ts`
- Create: `integrations/paperclip/src/server/test.ts`
- Create: `integrations/paperclip/test/config-schema.test.ts`

**Interfaces:**
- Package root exports `createServerAdapter(): ServerAdapterModule`.
- Adapter type key is `longrun`; label is `Longrun`.
- Package uses Paperclip `@paperclipai/adapter-utils` compatible with the
  inspected Paperclip package version `0.3.1`; the dependency remains scoped to
  this package.
- Use TypeScript `^7.0.2`, Vitest `^5.0.3`, and `@types/node` `^24.0.0` as
  development dependencies; require Node `>=24.11.0`.
- Config keys are `command`, `args`, `cwd`, `longrunUrl`, `timeoutSec`,
  `graceSec`, `maxSteps`, optional `model`, and optional operator-configured
  `session`. Defaults: command `python`, args `["forge.py", "paperclip-bot"]`,
  timeout 1800 seconds, grace 10 seconds, max steps 6, and Longrun URL
  `http://127.0.0.1:8790`.
- `session` selects a Longrun workspace context only; it does not promise
  cross-heartbeat conversation recovery.
- `LONGRUN_TOKEN` is read from the Paperclip server environment and passed only
  to the child environment; it is not an adapter config field.
- `testEnvironment()` checks the command and `GET /api/status` only; it never
  starts an agent run.

- [ ] **Step 1: Bootstrap only the package test harness, then write failing tests**

  Create the minimal `package.json`, `tsconfig.json`, lockfile, and Vitest
  script/dependencies needed to run tests; add no adapter implementation yet.
  Then assert the package root exposes the adapter factory, the type key is
  `longrun`, config defaults are stable, and environment diagnostics do not
  start a run. Use names `test_factory_declares_longrun_adapter`,
  `test_config_schema_exposes_supported_settings`, and
  `test_environment_check_does_not_start_run`.

- [ ] **Step 2: Run package tests and confirm RED**

  Run: `npm test` from `integrations/paperclip/`
  Expected: the test runner starts and the assertions fail because the adapter
  entry point and config implementation are absent.

- [ ] **Step 3: Implement metadata, config schema, and readiness check**

  Keep the Paperclip plugin interface small. Treat the Longrun URL and token as
  operator configuration. Never derive executable paths, URLs, or secrets from
  task fields.

- [ ] **Step 4: Run package tests and typecheck**

  Run: `npm test` from `integrations/paperclip/`
  Expected: focused tests pass.
  Run: `npm run typecheck` from `integrations/paperclip/`
  Expected: TypeScript reports no errors.

## Task 6: NDJSON Decoder and Paperclip Execution

**Files:**
- Create: `integrations/paperclip/src/server/ndjson.ts`
- Create: `integrations/paperclip/src/server/execute.ts`
- Create: `integrations/paperclip/test/ndjson.test.ts`
- Create: `integrations/paperclip/test/execute.test.ts`
- Create: `integrations/paperclip/test/fixtures/fake-longrun.mjs`
- Modify: `integrations/paperclip/src/index.ts`

**Interfaces:**
- `PaperclipWireEvent` has fields `schema:
  "longrun.paperclip.event.v1"`, `seq: number`, `event` in
  `"longrun.run.started" | "longrun.run.progress" | "longrun.run.completed" |
  "longrun.run.failed" | "longrun.run.cancelled"`, `run_id: string | null`,
  and `payload: Record<string, unknown>`.
- `NdjsonFrameDecoder.push(chunk: string): PaperclipWireEvent[]` buffers partial
  lines; `finish(): void` rejects an unterminated non-empty final frame.
- Decoder accepts only schema `longrun.paperclip.event.v1`, a positive
  increasing `seq`, known event types, and frames no larger than 65,536 UTF-8
  bytes.
- `execute(ctx: AdapterExecutionContext): Promise<AdapterExecutionResult>`
  sends the validated invocation via `runChildProcess(..., { stdin })`, maps
  frames through `ctx.onEvent`, and returns only a bounded result summary and
  run ID in `resultJson`.

- [ ] **Step 1: Write failing decoder tests**

  Test multiple frames per chunk, one frame split across chunks, UTF-8 byte
  limits, malformed JSON, unknown schema/event, sequence gaps/regressions, and
  missing terminal frame.
  Use names `test_decoder_accepts_multiple_frames`,
  `test_decoder_buffers_split_frame`, `test_decoder_enforces_utf8_frame_limit`,
  `test_decoder_rejects_bad_schema_and_sequence`, and
  `test_decoder_requires_terminal_frame`.

- [ ] **Step 2: Run decoder tests and confirm RED**

  Run: `npm test -- ndjson.test.ts` from `integrations/paperclip/`
  Expected: decoder module or expected validations are missing.

- [ ] **Step 3: Implement the bounded decoder**

  Count UTF-8 bytes rather than JavaScript characters. Reject malformed frames
  and clear buffered data on failure; do not pass raw protocol lines to
  Paperclip logs.

- [ ] **Step 4: Write failing execution tests using a real fake child**

  Use a deterministic Node fixture process launched through the real
  `runChildProcess` helper. Verify stdin contains the invocation, safe runtime
  events arrive in order, only `completed` returns exit code zero, and
  malformed/no-terminal output fails.
  Assert `agent.think`, raw observations, `PAPERCLIP_API_KEY`, and
  `LONGRUN_TOKEN` are absent from emitted events and captured user-visible logs.
  Use names `test_execute_streams_safe_runtime_events`,
  `test_execute_succeeds_only_for_completed_termination`,
  `test_execute_rejects_malformed_or_missing_terminal_frame`, and
  `test_execute_never_emits_credentials_or_private_payloads`.

- [ ] **Step 5: Run execution tests and confirm RED**

  Run: `npm test -- execute.test.ts`
  Expected: the adapter does not yet launch/parse the fixture correctly.

- [ ] **Step 6: Implement the Paperclip execution adapter**

  Use `runChildProcess` with shell disabled, configured cwd/command/args,
  bounded timeout/grace period, and JSON stdin. Forward stderr only after
  redaction. Convert accepted frames into `AdapterRuntimeEvent`; do not forward
  raw reasoning, tool payloads, or Longrun credentials.

- [ ] **Step 7: Run focused package tests and typecheck**

  Run: `npm test` and `npm run typecheck` from `integrations/paperclip/`
  Expected: all parser, execution, config, and factory tests pass.

## Task 7: Operator Documentation

**Files:**
- Create: `tests/acceptance/v468_paperclip_docs.py`
- Create: `integrations/paperclip/README.md`
- Create: `.agent/README-paperclip-adapter.md`
- Modify: `docs/CLI.md`
- Modify: `CHANGELOG.md`

**Interfaces:**
- Document the supported invocation as `python forge.py paperclip-bot`.
- Document local Paperclip installation via the external adapter plugin's
  `localPath`, required environment variables, configuration defaults, event
  allowlist, and unsupported capabilities.
- Keep the maintainer README local-only; do not recreate or edit the deleted
  `.agent/HANDOFF.md`.

- [ ] **Step 1: Add CLI documentation test**

  Extend the existing deterministic CLI parity acceptance test to assert the
  documented subcommand is present in `docs/CLI.md` and registered in
  `src/longrun/core/forge.py`.
  Name the new assertion `test_paperclip_bot_command_is_documented_and_registered`.

- [ ] **Step 2: Run the CLI documentation test and confirm RED**

  Run: `python3 tests/acceptance/v468_paperclip_docs.py`
  Expected: the command/docs parity assertion fails before documentation is
  added.

- [ ] **Step 3: Write package and maintainer setup instructions**

  Include the local package build/install sequence, configurable Python
  executable and checkout path, Longrun URL/token setup, how to run the
  environment check, deterministic test commands, and the distinction between
  adapter run events and Paperclip Runner PRP events.

- [ ] **Step 4: Update CLI docs and changelog**

  Add the command to the CLI reference and a concise entry under
  `CHANGELOG.md` → `Unreleased` → `Added`.

- [ ] **Step 5: Run documentation parity and whitespace checks**

  Run: `python3 tests/acceptance/v468_paperclip_docs.py`
  Expected: PASS.
  Run: `git diff --check`
  Expected: no whitespace errors.

## Task 8: Local Paperclip Development Smoke

**Files:**
- Create: `integrations/paperclip/test/fake-longrun-http.test.ts`
- Create: `integrations/paperclip/test/fixtures/fake-longrun-http.mjs`
- Runtime-only: local Paperclip development instance and adapter plugin registration.

**Interfaces:**
- Paperclip loads `integrations/paperclip/` via `localPath`.
- A local fixture Longrun HTTP service supplies canned SSE and final-run JSON;
  no model or paid API is used.
- Use a disposable Paperclip home/company/task where possible. Do not stop,
  reset, or overwrite an existing Paperclip process or database.

- [ ] **Step 1: Write failing fixture-server tests**

  Assert the fake server returns `GET /api/status`, a canned SSE stream for
  `POST /api/agent/run/stream`, a matching final run record, and an abort
  receipt. Verify it counts run-start calls for the no-duplicate assertion.
  Use names `test_fixture_serves_status_and_run_stream`,
  `test_fixture_returns_matching_terminal_record`, and
  `test_fixture_records_abort_without_duplicate_start`.

- [ ] **Step 2: Run the fixture tests and confirm RED**

  Run: `npm test -- fake-longrun-http.test.ts` from `integrations/paperclip/`
  Expected: fixture module or expected routes are missing.

- [ ] **Step 3: Implement the deterministic HTTP fixture**

  Serve only loopback requests with fixed payloads and test credentials. It
  must not call Longrun providers or Paperclip APIs.

- [ ] **Step 4: Run fixture tests and confirm GREEN**

  Run: `npm test -- fake-longrun-http.test.ts` from `integrations/paperclip/`
  Expected: all health, SSE, final-result, abort, and request-count assertions
  pass.

- [ ] **Step 5: Probe the Paperclip dev instance read-only**

  Check whether the requested `http://127.0.0.1:3100` server is already active
  and identify whether it is disposable. Do not mutate adapter registrations
  until the target state is known. If it is not safe to reuse, start an isolated
  Paperclip instance on an available port/home.

- [ ] **Step 6: Register the local plugin and configure the fixture service**

  Install only the local `integrations/paperclip/` package in the disposable
  instance. Configure its child command and the fixture Longrun URL/token using
  test credentials that are never written to the repository.

- [ ] **Step 7: Run one disposable assigned task**

  Invoke one task through Paperclip's normal adapter path. Verify ordered
  `longrun.run.started`, `longrun.run.progress`, and terminal events in the
  Paperclip run log, plus the expected adapter result. Assert the fixture
  received exactly one Longrun run-start request.

- [ ] **Step 8: Remove only resources created by this smoke**

  Uninstall the plugin and remove the uniquely named test company/agent/task
  only from the disposable instance. Leave any server or state identified as
  user-owned running and unchanged.

## Task 9: Final Deterministic Gates

**Files:** No additional files; verify the deliverables from Tasks 1–8.

- [ ] **Step 1: Run all Longrun acceptance tests**

  Run: `bash tests/battery.sh`
  Expected: the full discovered battery passes, including `v464`–`v468`.

- [ ] **Step 2: Run focused Paperclip package checks**

  Run: `npm test` and `npm run typecheck` from `integrations/paperclip/`
  Expected: every parser, execution, config, and package test passes.

- [ ] **Step 3: Report smoke scope and residual limits**

  State whether the Paperclip smoke used the isolated fixture server or a real
  Longrun model. Do not claim provider/model acceptance from a fixture run.

## Handoff

- No commit, push, Paperclip-core edit, or upstream PR is part of this plan.
- After the plan is approved, execute in the current Longrun checkout; do not
  create a worktree.
- A real-model smoke is separate from the deterministic gates, must be
  explicitly reported, and must cost no more than $2 USD.
