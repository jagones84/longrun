# Longrun Paperclip Adapter

Status: Proposed; the conversational design is approved, written-spec review pending
Date: 2026-10-16

## Purpose

Integrate Longrun as a Paperclip-managed agent through Paperclip's external
adapter plugin contract. The implementation and its producer protocol live in
the Longrun repository. Paperclip core remains unchanged; the local Paperclip
instance loads the adapter package from the Longrun checkout.

The first release handles a Paperclip-assigned task as one bounded Longrun
agent run, relays a small allowlist of progress events, and returns the final
result through Paperclip's normal adapter execution result.

## Evidence and Constraints

- Paperclip external adapters are ESM packages exporting
  `createServerAdapter()`. Paperclip can install a package from npm or a local
  path. The returned `ServerAdapterModule` owns execution and configuration.
- A custom adapter can spawn a child process, parse its output, and call
  `AdapterExecutionContext.onEvent`. Paperclip persists those events as run
  events. The generic `process` adapter only captures process output; it does
  not parse arbitrary NDJSON.
- Paperclip's `HarnessDriver` is an in-process Runner contract, not a plugin
  wire protocol. Native external bots such as Dot use the Runner and broker;
  that larger integration is not required here.
- Longrun is stdlib-only Python. Its documented CLI entry point is
  `python forge.py ...`; its REST API is configured with `LONGRUN_URL` and
  optional bearer `LONGRUN_TOKEN`.
- Longrun's `GET /api/agent/run` emits SSE, including a run ID and agent
  progress. `POST /api/agent/run` accepts JSON but returns only after the run,
  so it cannot provide live progress. `GET /api/agent/runs/<id>` returns the
  final public run state.
- Longrun currently reports `status: done` for both explicit completion and
  some bounded stops, including max-step exhaustion. The adapter must not
  interpret that status alone as proof the task completed.

## Decision

Use a small external adapter package in `integrations/paperclip/` within the
Longrun repository. The package is Node/TypeScript because Paperclip loads
`createServerAdapter()` modules through its Node plugin loader. It depends on
Paperclip's published `@paperclipai/adapter-utils`; this dependency is isolated
to the integration package and does not enter Longrun's Python runtime.

The package starts Longrun's Python CLI shim. The shim calls Longrun REST and
emits a versioned NDJSON protocol. The TypeScript adapter validates each
protocol frame and maps only approved frames to Paperclip's
`AdapterRuntimeEvent` callback. It returns a structured Paperclip result after
validating the terminal run outcome.

The invocation command is configurable to support local installations. The
repository-supported development form is `python forge.py paperclip-bot`;
this design does not assume a globally installed `longrun` executable.

### Alternatives Considered

- **Configure Paperclip's generic `process` adapter directly.** Rejected for
  this integration: it captures stdout/stderr but does not parse NDJSON into
  Paperclip runtime events or validate the Longrun terminal result.
- **Add a built-in adapter to Paperclip core.** Rejected for the first release:
  Paperclip already supports dynamically loaded external adapter packages, so
  a core change would duplicate its plugin seam and require an upstream PR.
- **Implement a native Paperclip Runner `HarnessDriver`.** Deferred: it is an
  in-process Runner interface and external-bot integration also requires the
  broker/authority lifecycle. That scope is unnecessary for one task-scoped
  Longrun invocation.

## Modules and Data Flow

1. Paperclip invokes `execute(ctx)` for an assigned run. The plugin builds a
   bounded invocation envelope from the Paperclip run, agent, and task context.
2. The plugin sends that envelope to the child process over stdin, using
   Paperclip's `runChildProcess` helper. The envelope contains no credentials.
3. `forge.py paperclip-bot` dispatches to
   `src/longrun/integrations/paperclip_bot.py`.
4. The CLI validates its input and calls
   `src/longrun/integrations/paperclip_adapter.py`.
5. The Python adapter starts one authenticated Longrun
   `POST /api/agent/run/stream` request with a JSON body, using the configured
   Longrun URL and bearer token. Longrun streams SSE without placing task text
   in the URL. The Python adapter parses SSE incrementally and writes one
   versioned NDJSON object per accepted event to stdout. Diagnostics go to
   stderr.
6. Longrun's SSE terminal frame carries the run ID, summary, and machine-readable
   completion classification. The Python adapter may read
   `GET /api/agent/runs/<run_id>` to corroborate the result; a missing or
   contradictory final record makes the outcome indeterminate. It emits exactly
   one terminal NDJSON frame and exits with a status consistent with that
   result.
7. The TypeScript adapter buffers arbitrary stdout chunks, parses complete
   newline-delimited frames, validates schema/version/sequence, forwards safe
   events via `ctx.onEvent`, and constructs `AdapterExecutionResult`.

Paperclip identity is invocation-scoped metadata, not a persistent identity
file. The plugin does not pass Paperclip's `PAPERCLIP_API_KEY` to the child:
Longrun is called with its own separately configured `LONGRUN_TOKEN`.

## Wire Contracts

### Invocation

The stdin envelope is JSON with schema `longrun.paperclip.invocation.v1` and
contains:

- Paperclip run, agent, company, and task IDs for provenance.
- A goal assembled from the assigned task's title and description.
- Optional operator-selected Longrun model, max-step limit, and session.

The Longrun URL and token are supplied through adapter configuration and the
child environment, never through argv, the invocation envelope, stdout, or
Paperclip event payloads. Task-supplied values cannot override the configured
Longrun URL, executable, or credentials.

### NDJSON events

Each stdout line is one JSON object using
`longrun.paperclip.event.v1`, a strictly increasing sequence number, an event
type, and a bounded payload. Stdout contains only valid protocol frames.
Malformed input, invalid frames, or sequence regressions fail the invocation;
they are not silently skipped.

The initial event allowlist is:

| Longrun source | Paperclip runtime event | Forwarded data |
|---|---|---|
| SSE `run` | `longrun.run.started` | Longrun run ID |
| `agent.iteration` | `longrun.run.progress` | Current and maximum step |
| `agent.finish` | `longrun.run.completed` | Bounded final summary, only for successful completion |
| `agent.error` / SSE `error` | `longrun.run.failed` | Sanitized, bounded error |
| `agent.aborted` | `longrun.run.cancelled` | Run ID and terminal classification |

Reasoning events (`agent.think`), raw observations, tool arguments/results, and
the full trace are never forwarded. They may contain private task data,
credentials, or model reasoning. Paperclip receives safe progress and final
status; the final result is not reconstructed from raw stdout.

### Completion semantics

Add an additive, machine-readable terminal classification to Longrun's run
record/result and terminal SSE event:

- `completed`: the agent explicitly selected the finish action.
- `max_steps`: the configured step limit was reached.
- `no_progress`: the no-progress guard ended the run.
- `aborted`: an operator or Paperclip cancellation stopped the run.
- `error`: the run failed.

Existing `status` and summary fields remain backward-compatible. The adapter
returns success only for `completed`; bounded or indeterminate outcomes do not
become successful Paperclip task results.

`POST /api/agent/run/stream` accepts the existing run inputs as JSON
(`goal`, `max_steps`, and optional `model`/`session`) and streams the same
progress vocabulary as the existing GET SSE route. The existing GET SSE and
POST JSON routes retain their current behavior.

## Cancellation and Failure Handling

- On Paperclip cancellation, the CLI sends
  `POST /api/agent/control` with `{ "action": "abort", "runId": "<id>" }`
  when the Longrun run ID is known, then exits after a bounded cleanup period.
- The adapter does not reconnect the SSE request or automatically start a
  second Longrun run. A lost response after dispatch is treated as
  indeterminate, not retried with a new run.
- HTTP errors, malformed SSE/JSON, missing terminal records, and timeout are
  reported as adapter failures with bounded, sanitized messages.
- A disconnect before the initial run-ID frame may leave remote work whose ID
  the client never learned. This remains a residual risk unless a later change
  adds server-side idempotent run creation.
- No attachments or Paperclip workspace files are copied to Longrun in this
  release. Any Longrun tools remain governed by Longrun's own configured
  allowlist, approval policy, and sandbox.

## Configuration

The adapter exposes only the settings needed for a local install:

- Python executable and Longrun checkout/launcher path.
- Longrun base URL.
- Longrun bearer token via secret/environment configuration.
- Optional model, max steps, and execution timeout.

The environment test checks the configured command and Longrun health endpoint
using `GET /api/status`, without starting an agent run. No model call occurs
during installation or configuration validation.

## Testing and Acceptance

Tests remain deterministic and make no LLM calls:

- Python protocol tests use a local fixture HTTP server that returns controlled
  SSE and final-run JSON responses.
- Parser tests split SSE and NDJSON at arbitrary chunk boundaries and cover
  multiline data, keepalives, malformed frames, sequence errors, and terminal
  event classification.
- Adapter tests verify bearer auth, URL encoding, safe event allowlisting,
  error mapping, cancellation/abort, and that no automatic duplicate run is
  started after an ambiguous disconnect.
- TypeScript package tests use a deterministic fake child process to verify
  stdin serialization, NDJSON-to-`onEvent` mapping, result construction, and
  secret/reasoning redaction.
- Longrun acceptance coverage belongs under `tests/acceptance/vNNN_*.py` so
  `tests/battery.sh` discovers and isolates it. The Paperclip package also has
  its focused test command.
- A local Paperclip smoke test verifies adapter installation from the Longrun
  path, one assigned task, visible progress events, and final task outcome.
  It is separate from deterministic tests and must state explicitly whether a
  real model was used.
- The local maintainer runbook is
  `.agent/README-paperclip-adapter.md`; it documents local installation,
  configuration, protocol limits, and the future upstream distribution path.

Acceptance requires all of the following:

1. Paperclip loads the external adapter from the Longrun checkout without
   Paperclip core changes.
2. One Paperclip task starts exactly one Longrun run and receives ordered,
   allowlisted progress events.
3. Explicit completion yields a successful adapter result; max-step,
   no-progress, abort, and error outcomes do not.
4. Paperclip credentials and Longrun credentials never appear in argv, NDJSON,
   run logs, or error messages.
5. Cancellation aborts the known Longrun run, and ambiguous network loss does
   not trigger an automatic duplicate run.
6. The deterministic tests and Longrun regression battery pass.

## Out of Scope

- Changes to the Paperclip core, Runner, Rust broker, or native external-bot
  lifecycle.
- Idle/inbound bot conversations, Paperclip API tool authority, attachment
  transfer, or Paperclip workspace access from Longrun.
- Persistent cross-heartbeat Longrun session recovery.
- Publishing the package, creating a Paperclip upstream PR, or deploying the
  Paperclip development instance.

## Review Notes

- The initial proposal mentioned an identity file. This design instead passes
  run-scoped identity metadata over stdin and creates no persistent identity
  file. Review this distinction before implementation.
- The initial proposal used `longrun paperclip-bot`; the current Longrun source
  CLI is `python forge.py`. The Paperclip adapter therefore accepts a
  configurable executable/argument pair; a global `longrun` launcher is not
  assumed.
- Longrun's current terminal state does not distinguish explicit finish from
  max-step/no-progress termination. The additive terminal classification above
  is required before Paperclip may use the adapter for governed task completion.
- The streaming POST route is a new Longrun REST surface. Its request-body
  limits, auth behavior, cancellation behavior, and SSE framing must be covered
  by the Longrun acceptance suite before the Paperclip plugin relies on it.
