import { afterEach, describe, expect, test } from "vitest";

import {
  close,
  createLongrunServer,
  listen,
  RUN_ID,
} from "./fixtures/fake-longrun-http.mjs";

let url = "";
const servers: Array<import("node:http").Server> = [];

async function start(termination = "completed") {
  const { server, state } = createLongrunServer({ termination });
  servers.push(server);
  const { port } = await listen(server);
  url = `http://127.0.0.1:${port}`;
  return state;
}

afterEach(async () => {
  while (servers.length > 0) {
    const server = servers.pop();
    if (server) await close(server);
  }
});

describe("Longrun HTTP fixture (fake Longrun API)", () => {
  test("test_fixture_serves_status_and_run_stream", async () => {
    const state = await start("completed");

    const status = await fetch(`${url}/api/status`).then((r) => r.json());
    expect(status.ok).toBe(true);

    const res = await fetch(`${url}/api/agent/run/stream`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ goal: "do the task", max_steps: 3 }),
    });
    expect(res.headers.get("content-type")).toContain("text/event-stream");

    const stream = await res.text();
    expect(stream).toContain("event: run");
    expect(stream).toContain('"run_id":"' + RUN_ID + '"');
    expect(stream).toContain("event: agent.iteration");
    expect(stream).toContain("event: agent.finish");
    expect(stream).toContain('"termination":"completed"');

    expect(state.runStarts).toBe(1);
  });

  test("test_fixture_returns_matching_terminal_record", async () => {
    await start("completed");

    const record = await fetch(`${url}/api/agent/runs/${RUN_ID}`).then((r) => r.json());
    expect(record).toEqual({ id: RUN_ID, termination: "completed" });

    // A non-completed run streams a terminal frame whose record agrees with it.
    await close(servers.pop() as import("node:http").Server);
    await start("max_steps");
    const limited = await fetch(`${url}/api/agent/runs/${RUN_ID}`).then((r) => r.json());
    expect(limited).toEqual({ id: RUN_ID, termination: "max_steps" });

    const missing = await fetch(`${url}/api/agent/runs/not-a-real-id`);
    expect(missing.status).toBe(404);
  });

  test("test_fixture_records_abort_without_duplicate_start", async () => {
    const state = await start("completed");

    // One dispatch is exactly one run-start.
    await fetch(`${url}/api/agent/run/stream`, {
      method: "POST",
      body: JSON.stringify({ goal: "go" }),
    });
    expect(state.runStarts).toBe(1);

    const abort = await fetch(`${url}/api/agent/control`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ action: "abort", runId: RUN_ID }),
    }).then((r) => r.json());
    expect(abort).toEqual({ id: RUN_ID, status: "aborted" });
    expect(state.aborts).toEqual([{ action: "abort", runId: RUN_ID }]);

    // The abort did not start a second run, and no further dispatch happened.
    expect(state.runStarts).toBe(1);
  });
});