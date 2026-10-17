import type {
  AdapterEnvironmentCheck,
  AdapterEnvironmentTestContext,
  AdapterEnvironmentTestResult,
} from "@paperclipai/adapter-utils";
import { ensureAdapterExecutionTargetCommandResolvable } from "@paperclipai/adapter-utils/execution-target";

import { resolveAdapterConfig } from "./config-schema.js";

const STATUS_TIMEOUT_MS = 5_000;
const MAX_DETAIL_CHARS = 240;

function summarizeStatus(
  checks: AdapterEnvironmentCheck[],
): AdapterEnvironmentTestResult["status"] {
  if (checks.some((check) => check.level === "error")) return "fail";
  if (checks.some((check) => check.level === "warn")) return "warn";
  return "pass";
}

function boundedError(err: unknown): string {
  const text = err instanceof Error ? err.message : String(err);
  const collapsed = text.replace(/\s+/g, " ").trim();
  return collapsed.length > MAX_DETAIL_CHARS
    ? `${collapsed.slice(0, MAX_DETAIL_CHARS - 1)}…`
    : collapsed;
}

/**
 * The Longrun bearer token comes from the server environment only, exactly as
 * in `execute.ts`. `GET /api/status` is gated, so the probe must present it.
 */
function readToken(value: unknown): string | null {
  if (typeof value !== "string") return null;
  const trimmed = value.trim();
  return trimmed.length > 0 ? trimmed : null;
}

/**
 * Readiness probe for one Longrun adapter configuration.
 *
 * It resolves the configured interpreter and reads `GET /api/status`. It never
 * starts an agent run, spends no model budget, and never echoes a credential.
 */
export async function testEnvironment(
  ctx: AdapterEnvironmentTestContext,
): Promise<AdapterEnvironmentTestResult> {
  const config = resolveAdapterConfig(ctx.config);
  const checks: AdapterEnvironmentCheck[] = [];

  try {
    await ensureAdapterExecutionTargetCommandResolvable(
      config.command,
      ctx.executionTarget,
      config.cwd ?? process.cwd(),
      process.env,
    );
    checks.push({
      code: "longrun_command_resolvable",
      level: "info",
      message: `Command is executable: ${config.command}`,
    });
  } catch (err) {
    checks.push({
      code: "longrun_command_unresolvable",
      level: "error",
      message: "The configured Longrun command cannot be executed.",
      detail: boundedError(err),
      hint: "Set the command and arguments to a Python 3 interpreter that can run this checkout's forge.py.",
    });
  }

  try {
    const token = readToken(process.env.LONGRUN_TOKEN);
    const headers: Record<string, string> = { accept: "application/json" };
    if (token) headers.authorization = `Bearer ${token}`;
    const response = await fetch(new URL("/api/status", config.longrunUrl), {
      method: "GET",
      headers,
      signal: AbortSignal.timeout(STATUS_TIMEOUT_MS),
    });
    checks.push(
      response.ok
        ? {
            code: "longrun_status_ok",
            level: "info",
            message: "Longrun answered GET /api/status.",
            detail: config.longrunUrl,
          }
        : response.status === 401 || response.status === 403
          ? {
              code: "longrun_status_unauthorized",
              level: "error",
              message: `Longrun rejected GET /api/status with HTTP ${response.status}.`,
              detail: config.longrunUrl,
              hint: "Export LONGRUN_TOKEN into the Paperclip server environment; the probe sends it as a bearer credential.",
            }
          : {
              code: "longrun_status_unreachable",
              level: "error",
              message: `Longrun answered GET /api/status with HTTP ${response.status}.`,
              detail: config.longrunUrl,
              hint: "Start Longrun on the configured base URL and confirm it is reachable from the Paperclip server.",
            },
    );
  } catch (err) {
    checks.push({
      code: "longrun_status_unreachable",
      level: "error",
      message: "Longrun did not answer GET /api/status.",
      detail: `${config.longrunUrl} — ${boundedError(err)}`,
      hint: "Start Longrun on the configured base URL and confirm it is reachable from the Paperclip server.",
    });
  }

  return {
    adapterType: ctx.adapterType,
    status: summarizeStatus(checks),
    checks,
    testedAt: new Date().toISOString(),
  };
}
