import http from "node:http";
import type { AddressInfo } from "node:net";

import { describe, expect, test } from "vitest";

import * as root from "../src/index.js";
import { getConfigSchema, resolveAdapterConfig } from "../src/server/config-schema.js";
import { testEnvironment } from "../src/server/test.js";

describe("Longrun Paperclip adapter package", () => {
  test("test_factory_declares_longrun_adapter", async () => {
    expect(root.type).toBe("longrun");
    expect(root.label).toBe("Longrun");
    expect(typeof root.createServerAdapter).toBe("function");

    const adapter = root.createServerAdapter();
    expect(adapter.type).toBe("longrun");
    expect(typeof adapter.execute).toBe("function");
    expect(typeof adapter.testEnvironment).toBe("function");
    expect(typeof adapter.getConfigSchema).toBe("function");

    const schema = await adapter.getConfigSchema!();
    expect(schema.fields.length).toBeGreaterThan(0);
  });

  test("test_config_schema_exposes_supported_settings", () => {
    const schema = getConfigSchema();
    const keys = schema.fields.map((field) => field.key);

    // The operator sees exactly these settings, and no secret field.
    expect(keys).toEqual([
      "command",
      "args",
      "cwd",
      "longrunUrl",
      "timeoutSec",
      "graceSec",
      "maxSteps",
      "model",
      "session",
    ]);
    expect(keys).not.toContain("LONGRUN_TOKEN");
    expect(keys).not.toContain("token");

    const byKey = new Map(schema.fields.map((field) => [field.key, field]));
    expect(byKey.get("command")?.default).toBe("python");
    expect(byKey.get("args")?.default).toBe("forge.py paperclip-bot");
    expect(byKey.get("longrunUrl")?.default).toBe("http://127.0.0.1:8790");
    expect(byKey.get("timeoutSec")?.default).toBe(1800);
    expect(byKey.get("graceSec")?.default).toBe(10);
    expect(byKey.get("maxSteps")?.default).toBe(6);

    // Defaults resolve to the executable command plus argument list.
    const defaults = resolveAdapterConfig({});
    expect(defaults.command).toBe("python");
    expect(defaults.args).toEqual(["forge.py", "paperclip-bot"]);
    expect(defaults.cwd).toBeNull();
    expect(defaults.longrunUrl).toBe("http://127.0.0.1:8790");
    expect(defaults.timeoutSec).toBe(1800);
    expect(defaults.graceSec).toBe(10);
    expect(defaults.maxSteps).toBe(6);
    expect(defaults.model).toBeNull();
    expect(defaults.session).toBeNull();

    // A space-separated text field and an explicit array both resolve to args.
    expect(resolveAdapterConfig({ args: "python3 /repo/forge.py paperclip-bot" }).args).toEqual([
      "python3",
      "/repo/forge.py",
      "paperclip-bot",
    ]);
    expect(resolveAdapterConfig({ args: ["forge.py", "paperclip-bot", "--verbose"] }).args).toEqual([
      "forge.py",
      "paperclip-bot",
      "--verbose",
    ]);

    // Operator overrides survive; unusable numbers fall back to the default.
    const overridden = resolveAdapterConfig({
      command: "python3",
      cwd: "/home/jagones/Repositories/longrun",
      maxSteps: 3,
      model: "qwen3-coder",
      session: "ops",
    });
    expect(overridden.command).toBe("python3");
    expect(overridden.cwd).toBe("/home/jagones/Repositories/longrun");
    expect(overridden.maxSteps).toBe(3);
    expect(overridden.model).toBe("qwen3-coder");
    expect(overridden.session).toBe("ops");
    expect(resolveAdapterConfig({ timeoutSec: "soon" }).timeoutSec).toBe(1800);
    expect(resolveAdapterConfig({ graceSec: 0 }).graceSec).toBe(10);
    expect(resolveAdapterConfig({ maxSteps: 0 }).maxSteps).toBe(6);
    expect(resolveAdapterConfig({ cwd: "  " }).cwd).toBeNull();
    expect(resolveAdapterConfig({ model: "" }).model).toBeNull();
  });

  test("test_environment_check_does_not_start_run", async () => {
    const requests: string[] = [];
    const server = http.createServer((req, res) => {
      requests.push(`${req.method ?? "GET"} ${req.url ?? "/"}`);
      if (req.method === "GET" && req.url === "/api/status") {
        res.writeHead(200, { "content-type": "application/json" });
        res.end(JSON.stringify({ status: "ok" }));
        return;
      }
      res.writeHead(404, { "content-type": "application/json" });
      res.end(JSON.stringify({ error: "not found" }));
    });

    await new Promise<void>((resolve) => server.listen(0, "127.0.0.1", resolve));
    const { port } = server.address() as AddressInfo;

    try {
      const result = await testEnvironment({
        companyId: "company_test",
        adapterType: "longrun",
        config: {
          command: process.execPath,
          args: ["forge.py", "paperclip-bot"],
          longrunUrl: `http://127.0.0.1:${port}`,
        },
        environmentName: "local test",
      });

      expect(result.adapterType).toBe("longrun");
      expect(Number.isNaN(Date.parse(result.testedAt))).toBe(false);
      expect(result.checks.some((check) => check.code === "longrun_command_resolvable")).toBe(true);
      expect(result.checks.some((check) => check.code === "longrun_status_ok")).toBe(true);
      expect(result.status).toBe("pass");

      // The probe reads health only: it never opens an agent run.
      expect(requests).toEqual(["GET /api/status"]);
      expect(requests.some((entry) => entry.includes("/api/agent/run"))).toBe(false);
      expect(requests.some((entry) => entry.startsWith("POST"))).toBe(false);
    } finally {
      await new Promise<void>((resolve) => server.close(() => resolve()));
    }
  });
});
