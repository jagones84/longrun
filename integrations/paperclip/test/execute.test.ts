import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

import type {
  AdapterExecutionContext,
  AdapterRuntimeEvent,
} from "@paperclipai/adapter-utils";
import { afterEach, describe, expect, test } from "vitest";

import { execute } from "../src/server/execute.js";

const FIXTURE = fileURLToPath(new URL("./fixtures/fake-longrun.mjs", import.meta.url));
const PAPERCLIP_KEY = "PAPERCLIP-SECRET-KEY";
const LONGRUN_TOKEN = "LONGRUN-SECRET-TOKEN-abc123";
const OBSERVATION = "raw observation text";

const tempDirs: string[] = [];

afterEach(() => {
  while (tempDirs.length > 0) {
    const dir = tempDirs.pop();
    if (dir) fs.rmSync(dir, { recursive: true, force: true });
  }
  delete process.env.LONGRUN_TOKEN;
});

interface HarnessOptions {
  mode: string;
  echo?: boolean;
  authToken?: string;
  extraConfig?: Record<string, unknown>;
}

interface Harness {
  ctx: AdapterExecutionContext;
  events: AdapterRuntimeEvent[];
  logs: string[];
  echoPath: string;
}

function harness(options: HarnessOptions): Harness {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "longrun-paperclip-"));
  tempDirs.push(dir);
  const echoPath = path.join(dir, "invocation.json");

  const events: AdapterRuntimeEvent[] = [];
  const logs: string[] = [];

  const ctx = {
    runId: "pc_run_1",
    agent: {
      id: "agent_1",
      companyId: "company_1",
      name: "Longrun Bot",
      adapterType: "longrun",
      adapterConfig: {},
    },
    runtime: {
      sessionId: null,
      sessionParams: null,
      sessionDisplayId: null,
      taskKey: null,
    },
    config: {
      command: process.execPath,
      args: [FIXTURE, options.mode, options.echo ? echoPath : ""],
      longrunUrl: "http://127.0.0.1:9",
      ...options.extraConfig,
    },
    context: {
      taskId: "task_1",
      taskTitle: "Ship the fixture",
      taskBody: "Make the deterministic child behave.",
    },
    authToken: options.authToken,
    onLog: async (_stream: "stdout" | "stderr", chunk: string) => {
      logs.push(chunk);
    },
    onEvent: async (event: AdapterRuntimeEvent) => {
      events.push(event);
    },
  } as unknown as AdapterExecutionContext;

  return { ctx, events, logs, echoPath };
}

function eventTypes(events: AdapterRuntimeEvent[]): string[] {
  return events.map((event) => event.eventType);
}

describe("Longrun adapter execution", () => {
  test("test_execute_streams_safe_runtime_events", async () => {
    const { ctx, events, logs, echoPath } = harness({ mode: "completed", echo: true });

    const result = await execute(ctx);

    expect(eventTypes(events)).toEqual([
      "longrun.run.started",
      "longrun.run.progress",
      "longrun.run.completed",
    ]);
    expect(events[0].payload).toEqual({ runId: "run_fake_1" });
    expect(events[1].payload).toEqual({ iteration: 1, total: 6 });
    expect(events[2].payload).toEqual({
      runId: "run_fake_1",
      termination: "completed",
      summary: "fixture summary",
    });

    expect(result.exitCode).toBe(0);
    expect(result.timedOut).toBe(false);
    expect(result.resultJson).toEqual({
      runId: "run_fake_1",
      termination: "completed",
      summary: "fixture summary",
    });

    // The child received exactly one validated invocation envelope on stdin.
    const sent = JSON.parse(fs.readFileSync(echoPath, "utf8"));
    expect(sent).toEqual({
      schema: "longrun.paperclip.invocation.v1",
      paperclip_run_id: "pc_run_1",
      agent_id: "agent_1",
      company_id: "company_1",
      goal: "Ship the fixture\n\nMake the deterministic child behave.",
      task_id: "task_1",
      model: null,
      max_steps: 6,
      session_id: null,
    });
    expect(sent).not.toHaveProperty("token");
    expect(sent).not.toHaveProperty("longrunUrl");

    // Raw protocol lines never reach the user-visible log.
    const visible = logs.join("");
    expect(visible).not.toContain("longrun.paperclip.event.v1");
    expect(visible).not.toContain('"schema"');
  });

  test("test_execute_succeeds_only_for_completed_termination", async () => {
    const cases: Array<{ mode: string; errorCode: string }> = [
      { mode: "max_steps", errorCode: "longrun_termination_max_steps" },
      { mode: "aborted", errorCode: "longrun_termination_aborted" },
      { mode: "error", errorCode: "longrun_termination_error" },
      { mode: "completed_bad_exit", errorCode: "longrun_unconfirmed_completion" },
    ];

    const completed = await execute(harness({ mode: "completed" }).ctx);
    expect(completed.exitCode).toBe(0);
    expect(completed.errorMessage ?? null).toBeNull();
    expect(completed.resultJson?.termination).toBe("completed");

    for (const { mode, errorCode } of cases) {
      const { ctx, events } = harness({ mode });
      const result = await execute(ctx);

      expect(result.exitCode, mode).not.toBe(0);
      expect(result.errorCode, mode).toBe(errorCode);
      expect(typeof result.errorMessage, mode).toBe("string");
      expect((result.errorMessage ?? "").length, mode).toBeGreaterThan(0);
      expect(result.resultJson?.termination, mode).not.toBe("completed");
      expect(eventTypes(events).at(-1), mode).not.toBe("longrun.run.completed");
    }

    // Only the successful run reports zero, and an incomplete run never does.
    const maxSteps = await execute(harness({ mode: "max_steps" }).ctx);
    expect(maxSteps.exitCode).toBe(1);
    expect(maxSteps.errorMessage).toContain("max_steps");
  });

  test("test_execute_rejects_malformed_or_missing_terminal_frame", async () => {
    const cases: Array<{ mode: string; errorCode: string }> = [
      { mode: "malformed", errorCode: "longrun_protocol_error" },
      { mode: "oversize", errorCode: "longrun_protocol_error" },
      { mode: "no_newline", errorCode: "longrun_protocol_error" },
      { mode: "no_terminal", errorCode: "longrun_missing_terminal_event" },
    ];

    for (const { mode, errorCode } of cases) {
      const { ctx, events } = harness({ mode });
      const result = await execute(ctx);

      expect(result.exitCode, mode).not.toBe(0);
      expect(result.errorCode, mode).toBe(errorCode);
      expect(result.resultJson?.termination ?? null, mode).not.toBe("completed");
      // A broken stream is never a success, and never a forwarded completion.
      expect(eventTypes(events), mode).not.toContain("longrun.run.completed");
      // The rejected frame is not echoed into the operator-visible message.
      expect(result.errorMessage ?? "", mode).not.toContain("{ this is not json");
      expect((result.errorMessage ?? "").length, mode).toBeLessThan(400);
    }
  });

  test("test_execute_never_emits_credentials_or_private_payloads", async () => {
    process.env.LONGRUN_TOKEN = LONGRUN_TOKEN;
    const { ctx, events, logs } = harness({ mode: "leaky", authToken: PAPERCLIP_KEY });

    const result = await execute(ctx);

    expect(result.exitCode).toBe(0);
    const serialized = JSON.stringify({ events, logs, result });

    // Both credentials, the model's own reasoning marker, and the raw
    // observation text are absent from everything Paperclip can see.
    expect(serialized).not.toContain(LONGRUN_TOKEN);
    expect(serialized).not.toContain(PAPERCLIP_KEY);
    expect(serialized).not.toContain("agent.think");
    expect(serialized).not.toContain(OBSERVATION);
    expect(serialized).not.toContain("arguments");

    // The forwarded payloads carry only the bounded allowlisted fields.
    expect(events[0].payload).toEqual({ runId: "run_fake_1" });
    expect(events[1].payload).toEqual({ iteration: 1, total: 6 });
    expect(Object.keys(events[2].payload ?? {}).sort()).toEqual([
      "runId",
      "summary",
      "termination",
    ]);

    // The leaked summary is bounded and redacted before it is forwarded.
    const summary = String(events[2].payload?.summary ?? "");
    expect(summary).toBe("finished [redacted] [redacted]");
    expect(logs.join("")).toContain("[redacted]");
  });
});
