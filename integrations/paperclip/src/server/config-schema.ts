import type { AdapterConfigSchema } from "@paperclipai/adapter-utils";

/** Paperclip adapter type key and human label for the Longrun harness. */
export const ADAPTER_TYPE = "longrun";
export const ADAPTER_LABEL = "Longrun";

/**
 * Launch defaults for the Longrun CLI shim, which reads one invocation JSON
 * object on stdin and writes NDJSON events on stdout.
 */
export const DEFAULT_COMMAND = "python3";
export const DEFAULT_ARGS: readonly string[] = ["forge.py", "paperclip-bot"];
export const DEFAULT_LONGRUN_URL = "http://127.0.0.1:8790";
export const DEFAULT_TIMEOUT_SEC = 1800;
export const DEFAULT_GRACE_SEC = 10;
export const DEFAULT_MAX_STEPS = 6;

/**
 * Operator configuration with every value resolved to a usable type.
 *
 * `cwd`, `model`, and `session` stay null when unset so callers can tell
 * "operator chose nothing" apart from "operator chose a default".
 */
export interface ResolvedAdapterConfig {
  command: string;
  args: string[];
  cwd: string | null;
  longrunUrl: string;
  timeoutSec: number;
  graceSec: number;
  maxSteps: number;
  model: string | null;
  session: string | null;
}

function readNonEmptyString(value: unknown): string | null {
  if (typeof value !== "string") return null;
  const trimmed = value.trim();
  return trimmed.length > 0 ? trimmed : null;
}

/**
 * Arguments arrive either as a JSON array (REST/CLI configuration) or as the
 * space-separated text the settings form renders.
 */
function readArgs(value: unknown): string[] | null {
  const items = Array.isArray(value)
    ? value.map((item) => (typeof item === "string" ? item.trim() : ""))
    : (readNonEmptyString(value)?.split(/\s+/) ?? []);
  const args = items.filter((item) => item.length > 0);
  return args.length > 0 ? args : null;
}

function readPositiveNumber(value: unknown, fallback: number): number {
  if (typeof value !== "number" || !Number.isFinite(value) || value <= 0) return fallback;
  return value;
}

function readMaxSteps(value: unknown): number {
  const steps = readPositiveNumber(value, DEFAULT_MAX_STEPS);
  return Math.trunc(steps) >= 1 ? Math.trunc(steps) : DEFAULT_MAX_STEPS;
}

/** Resolve operator-supplied configuration against the documented defaults. */
export function resolveAdapterConfig(
  config: Record<string, unknown> | null | undefined,
): ResolvedAdapterConfig {
  const source = config ?? {};
  return {
    command: readNonEmptyString(source.command) ?? DEFAULT_COMMAND,
    args: readArgs(source.args) ?? [...DEFAULT_ARGS],
    cwd: readNonEmptyString(source.cwd),
    longrunUrl: readNonEmptyString(source.longrunUrl) ?? DEFAULT_LONGRUN_URL,
    timeoutSec: readPositiveNumber(source.timeoutSec, DEFAULT_TIMEOUT_SEC),
    graceSec: readPositiveNumber(source.graceSec, DEFAULT_GRACE_SEC),
    maxSteps: readMaxSteps(source.maxSteps),
    model: readNonEmptyString(source.model),
    session: readNonEmptyString(source.session),
  };
}

/**
 * Declarative settings form.
 *
 * The Longrun bearer token is deliberately absent: it is read from the
 * Paperclip server environment (`LONGRUN_TOKEN`) and handed to the child
 * process only.
 */
export function getConfigSchema(): AdapterConfigSchema {
  return {
    fields: [
      {
        key: "command",
        label: "Longrun interpreter",
        type: "text",
        default: DEFAULT_COMMAND,
        hint: "Python 3 interpreter that launches the Longrun CLI shim, for example python3.",
      },
      {
        key: "args",
        label: "Longrun launcher arguments",
        type: "text",
        default: DEFAULT_ARGS.join(" "),
        hint: "Space-separated arguments appended to the interpreter. Point the first argument at forge.py in this checkout.",
      },
      {
        key: "cwd",
        label: "Working directory",
        type: "text",
        hint: "Optional absolute directory for the child process. Defaults to the assigned task workspace.",
      },
      {
        key: "longrunUrl",
        label: "Longrun base URL",
        type: "text",
        default: DEFAULT_LONGRUN_URL,
        hint: "Base URL of the Longrun HTTP API, reachable from the Paperclip server.",
      },
      {
        key: "timeoutSec",
        label: "Timeout seconds",
        type: "number",
        default: DEFAULT_TIMEOUT_SEC,
        hint: "Wall-clock limit for one Longrun assignment before the child process is stopped.",
      },
      {
        key: "graceSec",
        label: "Grace seconds",
        type: "number",
        default: DEFAULT_GRACE_SEC,
        hint: "Seconds to wait after SIGTERM before the child process is killed.",
      },
      {
        key: "maxSteps",
        label: "Max agent steps",
        type: "number",
        default: DEFAULT_MAX_STEPS,
        hint: "Longrun step limit for one assignment. A limited run is reported as an incomplete result, never a success.",
      },
      {
        key: "model",
        label: "Model",
        type: "text",
        hint: "Optional Longrun model override. Leave blank to use the Longrun default.",
      },
      {
        key: "session",
        label: "Longrun session",
        type: "text",
        hint: "Optional Longrun workspace context. It does not promise cross-heartbeat conversation recovery.",
      },
    ],
  };
}
