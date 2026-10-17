/**
 * Paperclip execution entry point for the Longrun adapter.
 *
 * One Paperclip run becomes exactly one Longrun run: the adapter writes one
 * invocation envelope to the child's stdin, reads back bounded NDJSON protocol
 * frames, and forwards only the allowlisted ones to Paperclip.
 *
 * Rules kept here (design spec, "Cancellation and Failure Handling"):
 *
 *  * the child's stdout is a protocol channel, never a log — raw frames can
 *    carry task text or a credential, so they are decoded and nothing else;
 *  * a broken, oversized, or truncated stream fails the run and is never
 *    half-read into a success;
 *  * completion is reported only when the child's terminal frame and its exit
 *    code agree, so a bounded or contradictory outcome cannot become a
 *    successful Paperclip task result.
 */

import type {
  AdapterExecutionContext,
  AdapterExecutionResult,
  AdapterRuntimeEvent,
} from "@paperclipai/adapter-utils";
import { runChildProcess } from "@paperclipai/adapter-utils/server-utils";

import { resolveAdapterConfig } from "./config-schema.js";
import { NdjsonFrameDecoder, type PaperclipWireEvent } from "./ndjson.js";

/** Stdin envelope schema understood by `forge.py paperclip-bot`. */
export const INVOCATION_SCHEMA = "longrun.paperclip.invocation.v1";

const MAX_GOAL_CHARS = 8_000;
const MAX_SUMMARY_CHARS = 2_000;
const MAX_ERROR_CHARS = 400;
const MAX_LOGGED_CHARS = 4_000;
const REDACTED = "[redacted]";
/** Short values would redact unrelated text; real tokens are far longer. */
const MIN_SECRET_CHARS = 4;

const TERMINAL_EVENTS = new Set<string>([
  "longrun.run.completed",
  "longrun.run.failed",
  "longrun.run.cancelled",
]);

function readText(value: unknown): string | null {
  if (typeof value !== "string") return null;
  const trimmed = value.trim();
  return trimmed.length > 0 ? trimmed : null;
}

function readInteger(value: unknown): number | null {
  return typeof value === "number" && Number.isInteger(value) ? value : null;
}

/** Collapse whitespace and cap the length of anything Paperclip renders. */
function bounded(text: string, limit: number): string {
  const collapsed = text.replace(/\s+/g, " ").trim();
  return collapsed.length > limit ? `${collapsed.slice(0, limit - 1)}…` : collapsed;
}

/** Replace every known credential value with a neutral marker. */
function buildRedactor(secrets: Array<string | null>): (text: string) => string {
  const values = secrets.filter(
    (value): value is string => typeof value === "string" && value.length >= MIN_SECRET_CHARS,
  );
  return (text) =>
    values.reduce((acc, secret) => acc.split(secret).join(REDACTED), text);
}

/** The goal is the assigned task's objective, and nothing else.
 *
 * The installed Paperclip (2026.928 canary) hands a fresh assignment over in
 * `ctx.executionContinuation.objective` — a server-authored snapshot — and leaves
 * `ctx.context` for the LEGACY wake shape (`taskTitle`/`taskBody`). Reading only
 * the legacy keys made every real assignment fail with
 * "carries no title or description" even though the issue had one, so the
 * modern objective wins and the legacy pair remains as a fallback.
 */
function buildGoal(ctx: AdapterExecutionContext): string | null {
  const objective = readText(ctx.executionContinuation?.objective);
  if (objective) return objective.slice(0, MAX_GOAL_CHARS);
  const context = (ctx.context ?? {}) as Record<string, unknown>;
  const parts = [readText(context.taskTitle), readText(context.taskBody)].filter(
    (part): part is string => part !== null,
  );
  if (parts.length === 0) return null;
  return parts.join("\n\n").slice(0, MAX_GOAL_CHARS);
}

/** Terminal classification carried by a terminal frame. */
function terminationOf(frame: PaperclipWireEvent): string {
  const declared = readText(frame.payload.termination);
  if (declared) return declared;
  if (frame.event === "longrun.run.completed") return "completed";
  if (frame.event === "longrun.run.cancelled") return "aborted";
  return "error";
}

/**
 * Map one accepted frame to a Paperclip runtime event.
 *
 * Only bounded, allowlisted fields are forwarded: no reasoning, no raw
 * observation, no tool arguments, no credentials.
 */
function toRuntimeEvent(
  frame: PaperclipWireEvent,
  redact: (text: string) => string,
): AdapterRuntimeEvent | null {
  const runId = frame.run_id;
  if (frame.event === "longrun.run.started") {
    return {
      eventType: frame.event,
      stream: "system",
      level: "info",
      message: "Longrun run started",
      payload: { runId },
    };
  }
  if (frame.event === "longrun.run.progress") {
    const iteration = readInteger(frame.payload.iteration);
    const total = readInteger(frame.payload.total);
    const payload: Record<string, unknown> = {};
    if (iteration !== null) payload.iteration = iteration;
    if (total !== null) payload.total = total;
    const step = iteration === null ? "" : ` ${iteration}${total === null ? "" : `/${total}`}`;
    return {
      eventType: frame.event,
      stream: "system",
      level: "info",
      message: `Longrun step${step}`,
      payload,
    };
  }

  const termination = terminationOf(frame);
  const payload: Record<string, unknown> = { runId, termination };
  const summary = readText(frame.payload.summary);
  if (summary && frame.event === "longrun.run.completed") {
    payload.summary = bounded(redact(summary), MAX_SUMMARY_CHARS);
  }
  const error = readText(frame.payload.error);
  if (error && frame.event === "longrun.run.failed") {
    payload.error = bounded(redact(error), MAX_ERROR_CHARS);
  }

  if (frame.event === "longrun.run.completed") {
    return {
      eventType: frame.event,
      stream: "system",
      level: "info",
      message: "Longrun run completed",
      payload,
    };
  }
  if (frame.event === "longrun.run.cancelled") {
    return {
      eventType: frame.event,
      stream: "system",
      level: "warn",
      message: `Longrun run cancelled (${termination})`,
      payload,
    };
  }
  return {
    eventType: frame.event,
    stream: "system",
    level: "error",
    message: `Longrun run failed (${termination})`,
    payload,
  };
}

/**
 * Every failure path reports a non-zero exit code.
 *
 * The child's own status is what it is; what matters here is that Paperclip
 * never reads a failed run as a success because the process happened to exit
 * cleanly (a truncated stream is the normal case).
 */
function failureExitCode(exitCode: number | null): number {
  return exitCode === null || exitCode === 0 ? 1 : exitCode;
}

function result(
  fields: {
    exitCode: number | null;
    signal: string | null;
    timedOut: boolean;
    runId: string | null;
    termination: string;
    summary?: string | null;
    errorMessage?: string | null;
    errorCode?: string | null;
    errorFamily?: AdapterExecutionResult["errorFamily"];
  },
): AdapterExecutionResult {
  const resultJson: Record<string, unknown> = {
    runId: fields.runId,
    termination: fields.termination,
  };
  if (fields.summary) resultJson.summary = fields.summary;

  return {
    exitCode: fields.exitCode,
    signal: fields.signal,
    timedOut: fields.timedOut,
    errorMessage: fields.errorMessage ?? null,
    errorCode: fields.errorCode ?? null,
    errorFamily: fields.errorFamily ?? null,
    resultJson,
    summary: fields.summary ?? null,
  };
}

/** Run one Paperclip task as exactly one Longrun run. */
export async function execute(ctx: AdapterExecutionContext): Promise<AdapterExecutionResult> {
  const config = resolveAdapterConfig(ctx.config);
  const context = (ctx.context ?? {}) as Record<string, unknown>;

  const goal = buildGoal(ctx);
  if (goal === null) {
    // Diagnostic: name the keys the runner actually sent (names only, never values)
    // so a contract drift is visible in the run log instead of guessed at.
    const keys = Object.keys(context);
    await ctx.onLog(
      "stderr",
      `[longrun] no goal in the assignment: executionContinuation=${ctx.executionContinuation ? "present" : "absent"}` +
        `, context keys=[${keys.slice(0, 12).join(", ")}]`,
    );
    return result({
      exitCode: null,
      signal: null,
      timedOut: false,
      runId: null,
      termination: "indeterminate",
      errorMessage: "The assigned task carries no title or description to run as a goal.",
      errorCode: "longrun_invocation_incomplete",
      errorFamily: "configuration",
    });
  }

  const token = readText(process.env.LONGRUN_TOKEN);
  const redact = buildRedactor([token, ctx.authToken ?? null]);

  const workspace = context.paperclipWorkspace;
  const workspaceCwd =
    typeof workspace === "object" && workspace !== null
      ? readText((workspace as Record<string, unknown>).cwd)
      : null;

  const childEnv: Record<string, string> = { LONGRUN_URL: config.longrunUrl };
  if (token) childEnv.LONGRUN_TOKEN = token;

  // The envelope is the child's only input: no URL, no executable, no token.
  const invocation = {
    schema: INVOCATION_SCHEMA,
    paperclip_run_id: ctx.runId,
    agent_id: ctx.agent.id,
    company_id: ctx.agent.companyId,
    goal,
    task_id: readText(context.taskId) ?? readText(context.issueId)
      ?? readText(ctx.executionContinuation?.issueId),
    model: config.model,
    max_steps: config.maxSteps,
    session_id: config.session,
  };

  const decoder = new NdjsonFrameDecoder();
  const state = {
    runId: null as string | null,
    terminal: null as PaperclipWireEvent | null,
    protocolError: null as string | null,
  };

  const swallow = (err: unknown, fallback: string) => {
    state.protocolError ??= err instanceof Error && err.message ? err.message : fallback;
  };

  try {
    await ctx.onLog(
      "stdout",
      `[longrun] ${config.command} ${config.args.join(" ")} (url=${config.longrunUrl}, maxSteps=${config.maxSteps})\n`,
    );
  } catch {
    // A log sink failure must not stop the run.
  }

  const onLog = async (stream: "stdout" | "stderr", chunk: string): Promise<void> => {
    if (stream === "stderr") {
      // Diagnostics are the only user-visible child output, and only redacted.
      await ctx.onLog("stderr", bounded(redact(chunk), MAX_LOGGED_CHARS));
      return;
    }
    if (state.protocolError) return;
    try {
      for (const frame of decoder.push(chunk)) {
        if (frame.run_id) state.runId = frame.run_id;
        if (TERMINAL_EVENTS.has(frame.event)) {
          // Held back: a terminal frame is published only once the process
          // outcome confirms it.
          state.terminal = frame;
          continue;
        }
        const event = toRuntimeEvent(frame, redact);
        if (event && ctx.onEvent) await ctx.onEvent(event);
      }
    } catch (err) {
      swallow(err, "invalid protocol frame");
    }
  };

  let childResult;
  try {
    childResult = await runChildProcess(ctx.runId, config.command, config.args, {
      cwd: config.cwd ?? workspaceCwd ?? process.cwd(),
      env: childEnv,
      timeoutSec: config.timeoutSec,
      graceSec: config.graceSec,
      stdin: JSON.stringify(invocation),
      onLog,
      onSpawn: ctx.onSpawn,
    });
  } catch (err) {
    return result({
      exitCode: null,
      signal: null,
      timedOut: false,
      runId: state.runId,
      termination: "indeterminate",
      errorMessage: bounded(
        err instanceof Error ? err.message : String(err),
        MAX_ERROR_CHARS,
      ),
      errorCode: "longrun_spawn_failed",
      errorFamily: "configuration",
    });
  }

  if (!state.protocolError) {
    try {
      decoder.finish();
    } catch (err) {
      swallow(err, "the protocol stream ended inside an unterminated frame");
    }
  }

  const exitCode = childResult.exitCode;
  const runId = state.runId;

  if (state.protocolError) {
    return result({
      exitCode: failureExitCode(exitCode),
      signal: childResult.signal,
      timedOut: childResult.timedOut,
      runId,
      termination: "indeterminate",
      errorMessage: bounded(state.protocolError, MAX_ERROR_CHARS),
      errorCode: "longrun_protocol_error",
    });
  }
  if (childResult.timedOut) {
    return result({
      exitCode: failureExitCode(exitCode),
      signal: childResult.signal,
      timedOut: true,
      runId,
      termination: "indeterminate",
      errorMessage: "The Longrun child process exceeded its configured timeout.",
      errorCode: "longrun_timeout",
    });
  }

  const terminal = state.terminal;
  if (!terminal) {
    return result({
      exitCode: failureExitCode(exitCode),
      signal: childResult.signal,
      timedOut: false,
      runId,
      termination: "indeterminate",
      errorMessage: "The Longrun stream ended without a terminal run event.",
      errorCode: "longrun_missing_terminal_event",
    });
  }

  const termination = terminationOf(terminal);
  const completed = terminal.event === "longrun.run.completed";

  if (completed && exitCode !== 0) {
    // The frame claims completion; the process contradicts it. Neither a
    // success nor a forwarded completion.
    return result({
      exitCode: failureExitCode(exitCode),
      signal: childResult.signal,
      timedOut: false,
      runId,
      termination: "indeterminate",
      errorMessage: "The Longrun child reported completion but exited with a failure status.",
      errorCode: "longrun_unconfirmed_completion",
    });
  }

  const event = toRuntimeEvent(terminal, redact);
  if (event && ctx.onEvent) await ctx.onEvent(event);

  if (completed) {
    const summary = (event?.payload?.summary as string | undefined) ?? null;
    return result({
      exitCode: 0,
      signal: childResult.signal,
      timedOut: false,
      runId,
      termination,
      summary,
    });
  }

  const detail = readText(terminal.payload.error);
  return result({
    exitCode: failureExitCode(exitCode),
    signal: childResult.signal,
    timedOut: false,
    runId,
    termination,
    errorMessage: bounded(
      `The Longrun run did not complete (${termination}).${detail ? ` ${redact(detail)}` : ""}`,
      MAX_ERROR_CHARS,
    ),
    errorCode: `longrun_termination_${termination}`,
  });
}
