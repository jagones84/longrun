#!/usr/bin/env node
/**
 * Deterministic stand-in for `forge.py paperclip-bot`.
 *
 * The adapter tests launch this file as the real child process through
 * Paperclip's `runChildProcess` helper. It never touches the network: every
 * mode is driven by argv (`mode`, optional echo path) and by the environment
 * the adapter passes down (`LONGRUN_TOKEN`).
 *
 * Usage: node fake-longrun.mjs <mode> [echoPath]
 *
 * It validates the stdin envelope exactly like the real shim, then writes only
 * protocol frames to stdout and diagnostics to stderr.
 */

import { writeFileSync } from "node:fs";

const SCHEMA_INVOCATION = "longrun.paperclip.invocation.v1";
const SCHEMA_EVENT = "longrun.paperclip.event.v1";
const RUN_ID = "run_fake_1";

const MODE = process.argv[2] ?? "completed";
const ECHO_PATH = process.argv[3] ?? "";
const TOKEN = process.env.LONGRUN_TOKEN ?? "";
// A producer that leaks Paperclip's own bearer must still be redacted by the
// adapter: this is a literal, never a value the adapter hands to the child.
const FOREIGN_KEY = "PAPERCLIP-SECRET-KEY";
const OBSERVATION = "raw observation text";

function diagnostic(message) {
  process.stderr.write(`fake-longrun: ${message}\n`);
}

async function readStdin() {
  const chunks = [];
  for await (const chunk of process.stdin) chunks.push(chunk);
  return Buffer.concat(chunks).toString("utf8");
}

let seq = 0;
function emit(event, payload, runId = RUN_ID) {
  seq += 1;
  process.stdout.write(
    `${JSON.stringify({
      schema: SCHEMA_EVENT,
      seq,
      event,
      run_id: runId,
      payload,
    })}\n`,
  );
}

const raw = await readStdin();
let invocation = null;
try {
  invocation = JSON.parse(raw);
} catch {
  diagnostic("invalid invocation: stdin is not valid JSON");
  process.exit(2);
}
if (!invocation || invocation.schema !== SCHEMA_INVOCATION) {
  diagnostic("invalid invocation: unsupported schema");
  process.exit(2);
}
for (const key of ["paperclip_run_id", "agent_id", "company_id", "goal"]) {
  const value = invocation[key];
  if (typeof value !== "string" || value.trim().length === 0) {
    diagnostic(`invalid invocation: ${key} is required`);
    process.exit(2);
  }
}
if (ECHO_PATH) writeFileSync(ECHO_PATH, raw);

switch (MODE) {
  case "completed":
    emit("longrun.run.started", {});
    emit("longrun.run.progress", { iteration: 1, total: 6 });
    emit("longrun.run.completed", { termination: "completed", summary: "fixture summary" });
    process.exit(0);
  case "max_steps":
    emit("longrun.run.started", {});
    emit("longrun.run.progress", { iteration: 6, total: 6 });
    emit("longrun.run.failed", { termination: "max_steps", error: "step limit reached" });
    process.exit(1);
  case "aborted":
    emit("longrun.run.started", {});
    emit("longrun.run.cancelled", { termination: "aborted" });
    process.exit(1);
  case "error":
    emit("longrun.run.started", {});
    emit("longrun.run.failed", { termination: "error", error: "fixture failure" });
    process.exit(1);
  case "malformed":
    emit("longrun.run.started", {});
    process.stdout.write("{ this is not json\n");
    process.exit(1);
  case "no_terminal":
    emit("longrun.run.started", {});
    process.exit(0);
  case "no_newline":
    emit("longrun.run.started", {});
    process.stdout.write(
      JSON.stringify({
        schema: SCHEMA_EVENT,
        seq: seq + 1,
        event: "longrun.run.completed",
        run_id: RUN_ID,
        payload: { termination: "completed" },
      }),
    );
    process.exit(0);
  case "oversize":
    emit("longrun.run.started", {});
    process.stdout.write(
      `${JSON.stringify({
        schema: SCHEMA_EVENT,
        seq: seq + 1,
        event: "longrun.run.completed",
        run_id: RUN_ID,
        payload: { termination: "completed", summary: "x".repeat(70_000) },
      })}\n`,
    );
    process.exit(1);
  case "completed_bad_exit":
    // A contradicting producer: the frame says completed but the process
    // reports failure. The adapter must not accept that as a success.
    emit("longrun.run.started", {});
    emit("longrun.run.completed", { termination: "completed", summary: "contradicted" });
    process.exit(1);
  case "leaky":
    // Private model reasoning, raw observations, tool arguments, and two
    // credentials — none of them may reach Paperclip events or logs.
    emit("longrun.run.started", { thinking: `agent.think reasoning ${TOKEN}`, observation: OBSERVATION });
    emit("longrun.run.progress", {
      iteration: 1,
      total: 6,
      observation: OBSERVATION,
      arguments: { command: "echo", token: TOKEN },
    });
    emit("longrun.run.completed", {
      termination: "completed",
      summary: `finished ${TOKEN} ${FOREIGN_KEY}`,
    });
    diagnostic(`leaking ${TOKEN} and ${FOREIGN_KEY}`);
    process.exit(0);
  default:
    diagnostic(`unknown mode: ${MODE}`);
    process.exit(2);
}
