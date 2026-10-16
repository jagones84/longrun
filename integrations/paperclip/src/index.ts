/**
 * Longrun adapter for Paperclip.
 *
 * Runs the Longrun harness as a managed employee in a Paperclip company. The
 * adapter launches the `paperclip-bot` CLI shim, which reads one invocation
 * object on stdin and streams run events as NDJSON on stdout.
 *
 * @packageDocumentation
 */

import type {
  AdapterModel,
  ServerAdapterModule,
} from "@paperclipai/adapter-utils";

import { ADAPTER_LABEL, ADAPTER_TYPE, getConfigSchema } from "./server/config-schema.js";
import { execute } from "./server/execute.js";
import { testEnvironment } from "./server/test.js";

export const type = ADAPTER_TYPE;
export const label = ADAPTER_LABEL;

/**
 * Longrun serves models through its own router, so the adapter ships no curated
 * model list. Operators pin a model through the `model` config field.
 */
export const models: AdapterModel[] = [];

/**
 * Documentation rendered in the Paperclip UI when configuring a Longrun agent.
 */
export const agentConfigurationDoc = `# Longrun Configuration

Longrun is a local agent harness exposed over HTTP. Paperclip launches the
Longrun CLI shim (\`forge.py paperclip-bot\`), which reads one invocation object
on stdin and writes one NDJSON event per line on stdout.

## Prerequisites

- Longrun running and reachable from the Paperclip server (default \`http://127.0.0.1:8790\`).
- A Python 3 interpreter that can run \`forge.py\` from this checkout.
- \`LONGRUN_TOKEN\` set in the Paperclip server environment. It is passed to the
  child process only and is never an adapter config field.

## Configuration

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| command | string | \`python\` | Python 3 interpreter that launches the Longrun CLI shim. |
| args | string | \`forge.py paperclip-bot\` | Space-separated arguments appended to the interpreter. |
| cwd | string | (assigned task workspace) | Optional absolute working directory for the child process. |
| longrunUrl | string | \`http://127.0.0.1:8790\` | Base URL of the Longrun HTTP API. |
| timeoutSec | number | \`1800\` | Wall-clock limit for one assignment. |
| graceSec | number | \`10\` | Seconds to wait after SIGTERM before killing the child. |
| maxSteps | number | \`6\` | Longrun step limit. A limited run is reported as incomplete, never a success. |
| model | string | (Longrun default) | Optional model override. |
| session | string | (none) | Optional Longrun workspace context. It does not promise cross-heartbeat conversation recovery. |

## Notes

- Only a \`completed\` termination is reported as success; every other outcome
  returns a non-zero exit code.
- Raw reasoning, tool payloads, and credentials are never forwarded to Paperclip
  logs or events.
`;

/**
 * External adapter plugin entrypoint expected by Paperclip's adapter manager.
 */
export function createServerAdapter(): ServerAdapterModule {
  return {
    type,
    execute,
    testEnvironment,
    getConfigSchema,
    models,
    agentConfigurationDoc,
  };
}
