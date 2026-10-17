# Longrun Paperclip Adapter

An **external adapter package** that lets a Paperclip-managed company assign work
to the [Longrun](../../README.md) agent harness. One Paperclip task becomes
exactly one Longrun agent run; Paperclip receives a small allowlist of progress
events and one final, validated result.

Paperclip core is **not** modified. Paperclip loads this package as a local
external adapter plugin and calls its `createServerAdapter()` factory.

```
Paperclip  --stdin envelope-->  python forge.py paperclip-bot  --REST/SSE-->  Longrun
           <--NDJSON events---                                <--SSE stream--
```

---

## 1. What it does

* `execute(ctx)` builds a bounded invocation envelope from the Paperclip run,
  agent, and assigned task, and writes it to the child's **stdin**.
* The child (`python forge.py paperclip-bot`) validates the envelope, calls
  Longrun, and writes versioned **NDJSON protocol frames** to stdout.
  Diagnostics go to stderr.
* The adapter validates every frame (schema, event allowlist, strictly
  increasing sequence) and forwards only allowlisted events to Paperclip
  through `ctx.onEvent`.
* The final result is reported only when the terminal frame and the child's exit
  status agree. Anything ambiguous is reported as a failure, never a success.

---

## 2. Requirements

* **Node.js >= 24.11.0** (the package is ESM/TypeScript).
* A **Python 3 interpreter** and a **Longrun checkout** containing `forge.py`.
* A reachable Longrun HTTP API (`longrunUrl`) and, when the API is
  token-protected, a bearer token in the Paperclip server environment as
  **`LONGRUN_TOKEN`**.

---

## 3. Install into a local Paperclip instance

Install the package's dependencies and check it compiles:

```bash
cd integrations/paperclip
npm install
npm run typecheck
npm test
npm run build      # tsc → dist/ ; Paperclip imports dist/index.js
```

`npm run build` is required: `exports["."]` resolves to `./dist/index.js`, and the
`src/*.ts` sources carry Node16 `.js` specifiers that only exist after `tsc` has
emitted them. Registering the package without a build fails with
`ERR_MODULE_NOT_FOUND` on the first relative import.

Then register the adapter with Paperclip by appending a record to
`~/.paperclip/adapter-plugins.json` (a JSON array) and restarting the server, with
**`localPath`** pointing at this directory (the **checkout** path), not at a
published tarball:

```jsonc
{
  "packageName": "longrun-paperclip-adapter",
  "type": "longrun",
  "localPath": "/home/jagones/Repositories/longrun/integrations/paperclip",
  "version": "0.1.0"
}
```

Export the bearer token for the Paperclip **server** process before it starts —
the adapter hands it to the child only, never to Paperclip event payloads, argv,
or stdout:

```bash
export LONGRUN_URL=http://127.0.0.1:8790
export LONGRUN_TOKEN=<operator token>
```

The token is deliberately **absent** from the settings schema: it is not a
per-agent setting and it is never written to the repository.

---

## 4. Configuration

The adapter exposes a declarative settings schema (`getConfigSchema()`); every
key falls back to the default below when unset.

| Key | Default | Meaning |
|---|---|---|
| `command` | `python` | The **interpreter** that launches the Longrun CLI shim (use `python3` when `python` is absent). |
| `args` | `forge.py paperclip-bot` | Arguments appended to `command`; point the first one at `forge.py` in this checkout. |
| `cwd` | *(task workspace)* | Optional absolute working directory for the child process. |
| `longrunUrl` | `http://127.0.0.1:8790` | Base URL of the Longrun HTTP API, reachable from the Paperclip server. |
| `timeoutSec` | `1800` | Wall-clock limit for one assignment. |
| `graceSec` | `10` | Seconds to wait after `SIGTERM` before the child is killed. |
| `maxSteps` | `6` | Longrun step limit for one assignment. A limited run is an incomplete result, never a success. |
| `model` | *(Longrun default)* | Optional Longrun model override. |
| `session` | *(none)* | Optional Longrun session context. It does **not** promise cross-heartbeat recovery. |

The default launch command is therefore:

```bash
python forge.py paperclip-bot
```

---

## 5. Environment check

`testEnvironment(ctx)` runs two checks and **never starts an agent run** and
never calls a model:

1. `longrun_command_resolvable` — the configured `command` exists and is
   executable.
2. `longrun_status_ok` — `GET /api/status` on `longrunUrl` answers within 5 s.

A failure reports `longrun_command_unresolvable` or
`longrun_status_unreachable` with a bounded message.

---

## 6. Wire contracts

### Invocation (stdin)

One JSON object, schema **`longrun.paperclip.invocation.v1`**:

```json
{
  "schema": "longrun.paperclip.invocation.v1",
  "paperclip_run_id": "run_...",
  "agent_id": "agent_...",
  "company_id": "co_...",
  "goal": "<task title>\n\n<task description>",
  "task_id": "task_...",
  "model": null,
  "max_steps": 6,
  "session_id": null
}
```

The envelope carries **no** URL, executable, or credential: task-supplied values
cannot override the configured Longrun URL, interpreter, `cwd`, or token.

### Events (stdout, NDJSON)

One JSON object per line, schema **`longrun.paperclip.event.v1`**, with a
strictly increasing `seq`. The allowlist is:

| Longrun source | Paperclip runtime event | Forwarded data |
|---|---|---|
| SSE `run` | `longrun.run.started` | Longrun run ID |
| `agent.iteration` | `longrun.run.progress` | current / total step |
| `agent.finish` | `longrun.run.completed` | bounded final summary (success only) |
| `agent.error` / SSE `error` | `longrun.run.failed` | bounded, sanitized error |
| `agent.aborted` | `longrun.run.cancelled` | run ID + termination |

Reasoning (`agent.think`), raw observations, tool arguments/results, and the
full trace are **never** forwarded — they can carry private task data or
credentials. stdout is a protocol channel, not a log: a malformed frame, a
sequence regression, or a truncated stream fails the run rather than being
half-read into a success.

### Completion semantics

A run completes only for the `completed` termination. `max_steps`,
`no_progress`, `aborted`, and `error` are reported as incomplete or failed
results; an outcome the adapter cannot establish is `indeterminate`. In every
non-completed case the adapter reports a non-zero exit code, so a clean child
exit can never be mistaken for a successful task.

---

## 7. Deterministic tests

No model, no network, no Longrun server:

```bash
cd integrations/paperclip
npm test              # vitest: config schema, NDJSON decoder, execute()
npm run typecheck     # tsc --noEmit
```

Coverage:

* `test/config-schema.test.ts` — defaults, argument parsing, and that the token
  is absent from the schema.
* `test/ndjson.test.ts` — the protocol decoder: split frames, UTF-8 byte
  limits, schema/sequence/poisoning rules, terminal-frame requirement.
* `test/execute.test.ts` — the real `execute()` against the deterministic child
  fixture `test/fixtures/fake-longrun.mjs`: stdin serialization, safe event
  ordering, completion-only success, malformed/truncated/oversized protocol
  failure, and credential/reasoning redaction.

The Longrun-side protocol has its own deterministic acceptance tests
(`tests/acceptance/v464..v467`), which run inside the Longrun regression
battery (`bash tests/battery.sh`).

---

## 8. Adapter run events vs. Paperclip Runner PRP events

These are different things and are easy to confuse:

* **Adapter run events** are what *this* package emits through
  `ctx.onEvent` — the five `longrun.run.*` events above. Paperclip persists them
  as run events and shows them in the run log.
* **Paperclip Runner PRP events** belong to Paperclip's in-process `HarnessDriver`
  / Runner contract, used by native external bots. This adapter does **not**
  implement the Runner, the Rust broker, or the PRP lifecycle: it is a
  task-scoped adapter plugin, and the final task outcome travels through
  Paperclip's normal `AdapterExecutionResult`.

---

## 9. Local smoke

A real smoke run registers this package in a **disposable** local Paperclip
instance, runs one assigned task, and checks the ordered `longrun.run.*` events
plus the adapter result. It is separate from the deterministic tests and must
state explicitly whether a real Longrun model was used.

---

## 10. Out of scope

* No changes to the Paperclip core, Runner, Rust broker, or native bot lifecycle.
* No attachment or workspace **asset** transfer: nothing from the Paperclip
  workspace is copied to Longrun.
* No idle/inbound bot conversations, and no Paperclip API tool authority.
* No persistent cross-heartbeat session recovery.
* No npm publishing and no upstream Paperclip PR from this repository.

Cancellation aborts the known Longrun run id and never starts a second run;
an ambiguous network loss after dispatch is reported as indeterminate, not
retried.
