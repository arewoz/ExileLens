/**
 * ExileLens API Worker - /v1 router and handler factory.
 *
 * This file is the only place that sees the full Env. Telemetry and error
 * handlers get `telemetryEnv(env)`, a narrowed object that cannot contain any
 * Patreon binding. (Package B adds its handlers under src/patreon/ and passes
 * them their own narrowed env.)
 */
import { telemetryEnv, type Env } from "./env";
import { StorageUnavailable, failure, json, opsLog, reasonCode, unavailable } from "./http";
import { handleErrorBatch } from "./telemetry/errors";
import { handleForget } from "./telemetry/forget";
import { handleUsageBatch } from "./telemetry/ingest";
import { runScheduled } from "./telemetry/maintenance";

type Handler = (env: Env, request: Request, nowMs: number) => Promise<Response> | Response;

const ROUTES: Record<string, { method: "GET" | "POST"; handler: Handler }> = {
  "/v1/health": {
    method: "GET",
    handler: (_env, _req, nowMs) => json(200, { ok: true, api: "v1", server_time: Math.floor(nowMs / 1000) }),
  },
  "/v1/telemetry/batch": {
    method: "POST",
    handler: (env, req, nowMs) => handleUsageBatch(telemetryEnv(env), req, nowMs),
  },
  "/v1/errors/batch": {
    method: "POST",
    handler: (env, req, nowMs) => handleErrorBatch(telemetryEnv(env), req, nowMs),
  },
  "/v1/telemetry/forget": {
    method: "POST",
    handler: (env, req) => handleForget(telemetryEnv(env), req, "telemetry"),
  },
  "/v1/errors/forget": {
    method: "POST",
    handler: (env, req) => handleForget(telemetryEnv(env), req, "errors"),
  },
};

async function route(env: Env, request: Request, pathname: string, nowMs: number): Promise<Response> {
  const entry = Object.prototype.hasOwnProperty.call(ROUTES, pathname) ? ROUTES[pathname] : undefined;
  if (!entry) return failure(404, "not_found");
  if (request.method !== entry.method) return failure(405, "method_not_allowed", { allow: entry.method });
  try {
    return await entry.handler(env, request, nowMs);
  } catch (err) {
    if (err instanceof StorageUnavailable) return unavailable("storage_unavailable");
    // Never leak details; the ops log records only a reason code.
    return failure(500, "internal_error");
  }
}

/** Build the Worker handler around an injectable clock (tests pin time; production uses Date.now). */
export function createHandler(now: () => number = () => Date.now()): ExportedHandler<Env> {
  return {
    async fetch(request: Request, env: Env): Promise<Response> {
      const started = now();
      const pathname = new URL(request.url).pathname;
      let response: Response;
      try {
        response = await route(env, request, pathname, started);
      } catch {
        response = failure(500, "internal_error");
      }
      opsLog({
        route: Object.prototype.hasOwnProperty.call(ROUTES, pathname) ? pathname : "(unmatched)",
        status: response.status,
        ms: Math.max(0, now() - started),
        code: await reasonCode(response),
      });
      return response;
    },

    async scheduled(controller: ScheduledController, env: Env, ctx: ExecutionContext): Promise<void> {
      ctx.waitUntil(runScheduled(telemetryEnv(env), controller.scheduledTime));
    },
  };
}
