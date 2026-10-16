import http from "node:http";

/**
 * Deterministic stand-in for the Longrun HTTP API.
 *
 * The Paperclip smoke test points the REAL child (`python forge.py paperclip-bot`)
 * at this server, so the whole adapter path — TypeScript `execute()` → child
 * process → Longrun REST/SSE — runs end to end without any model, live Longrun,
 * or paid API. It serves only the four routes the child actually calls:
 *
 *   GET  /api/status              → health (the adapter's `testEnvironment`)
 *   POST /api/agent/run/stream    → canned SSE: run → iteration → terminal
 *   GET  /api/agent/runs/<id>     → the terminal run record the child fetches
 *   POST /api/agent/control       → the abort receipt
 *
 * It also counts run-start requests so the smoke can assert exactly one run.
 */

export const RUN_ID = "smoke_run_1";

/** One canned SSE frame; `data` is a JSON object serialized inline. */
function sse(event, data) {
  return `event: ${event}\ndata: ${JSON.stringify(data)}\n\n`;
}

/**
 * Build a Longrun look-alike server. Returns `{ server, state }` where `state`
 * exposes `runStarts` (POST run-stream count), `aborts`, and `received`.
 *
 * Options:
 *   termination — "completed" (default) or any other terminal classification.
 *   summary     — the terminal summary text.
 */
export function createLongrunServer(options = {}) {
  const termination = options.termination ?? "completed";
  const summary = options.summary ?? "fixture did the task";

  const body = () => {
    if (termination === "completed") {
      return sse("run", { run_id: RUN_ID })
        + sse("agent.iteration", { i: 1, of: 3 })
        + sse("agent.iteration", { i: 2, of: 3 })
        + sse("agent.finish", { run: RUN_ID, termination, summary });
    }
    return sse("run", { run_id: RUN_ID })
      + sse("agent.iteration", { i: 1, of: 3 })
      + sse("agent.finish", { run: RUN_ID, termination });
  };

  const state = { runStarts: 0, aborts: [], received: [] };

  const server = http.createServer((req, res) => {
    const url = new URL(req.url, "http://127.0.0.1");
    const chunks = [];
    req.on("data", (c) => chunks.push(c));
    req.on("end", () => {
      const raw = Buffer.concat(chunks).toString("utf8");
      state.received.push({ method: req.method, path: url.pathname, body: raw });

      if (req.method === "GET" && url.pathname === "/api/status") {
        return respondJson(res, 200, { ok: true, status: "ok" });
      }

      if (req.method === "POST" && url.pathname === "/api/agent/run/stream") {
        state.runStarts += 1;
        res.writeHead(200, {
          "Content-Type": "text/event-stream",
          "Cache-Control": "no-cache",
          Connection: "keep-alive",
        });
        res.end(body());
        return;
      }

      if (req.method === "POST" && url.pathname === "/api/agent/control") {
        let parsed = {};
        try { parsed = JSON.parse(raw); } catch { /* reject below */ }
        state.aborts.push(parsed);
        return respondJson(res, 200, { id: RUN_ID, status: "aborted" });
      }

      if (req.method === "GET" && url.pathname.startsWith("/api/agent/runs/")) {
        const id = url.pathname.slice("/api/agent/runs/".length);
        if (id !== RUN_ID) {
          return respondJson(res, 404, { error: "unknown run" });
        }
        return respondJson(res, 200, { id: RUN_ID, termination });
      }

      respondJson(res, 404, {});
    });
  });

  return { server, state };
}

function respondJson(res, code, obj) {
  const data = JSON.stringify(obj);
  res.writeHead(code, { "Content-Type": "application/json", "Content-Length": Buffer.byteLength(data) });
  res.end(data);
}

/** Bind the server on an ephemeral port and resolve the bound address. */
export function listen(server, host = "127.0.0.1") {
  return new Promise((resolve, reject) => {
    server.once("error", reject);
    server.listen(0, host, () => {
      server.removeListener("error", reject);
      const address = server.address();
      resolve({ port: address.port, host });
    });
  });
}

/** Close a running server cleanly. */
export function close(server) {
  return new Promise((resolve) => server.close(() => resolve()));
}

// Standalone entry: `node fake-longrun-http.mjs [termination]` prints `{port}`
// once bound (used by the runtime smoke, where the harness needs the port).
const isMain = process.argv[1] && import.meta.url.endsWith(process.argv[1].split("/").pop());
if (isMain) {
  const { server } = createLongrunServer({ termination: process.argv[2] });
  const { port } = await listen(server);
  process.stdout.write(`${JSON.stringify({ port })}\n`);
}