/**
 * ExileLens API Worker - /v1 router and handler factory.
 *
 * This file is the only place that sees the full Env. Usage-statistics and error
 * handlers get `telemetryEnv(env)`, a narrowed object that cannot contain any
 * Patreon binding; Patreon handlers get `patreonEnv(env)`, which cannot contain
 * TELEMETRY_DB or any usage-statistics pepper.
 */
import { patreonEnv, telemetryEnv, type Env } from "./env";
import { StorageUnavailable, failure, json, opsLog, reasonCode, unavailable } from "./http";
import { handleErrorBatch } from "./telemetry/errors";
import { handleForget } from "./telemetry/forget";
import { handleUsageBatch } from "./telemetry/ingest";
import { runScheduled } from "./telemetry/maintenance";
import type { PatreonDeps } from "./patreon/common";
import { handleRefresh, handleUnlink } from "./patreon/entitlement";
import { handleCallback, handleLinkCancel, handleLinkStart, handleLinkStatus } from "./patreon/link";
import { PATREON_CRON, runPatreonScheduled } from "./patreon/maintenance";

type Handler = (env: Env, request: Request, nowMs: number, deps: PatreonDeps) => Promise<Response> | Response;

const ROUTES: Record<string, { method: "GET" | "POST" | "DELETE"; handler: Handler }> = {
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
  "/v1/patreon/link/start": {
    method: "POST",
    handler: (env, req, nowMs) => handleLinkStart(patreonEnv(env), req, nowMs),
  },
  "/v1/patreon/oauth/callback": {
    method: "GET",
    handler: (env, req, nowMs, deps) => handleCallback(patreonEnv(env), req, nowMs, deps),
  },
  "/v1/patreon/link/status": {
    method: "GET",
    handler: (env, req, nowMs) => handleLinkStatus(patreonEnv(env), req, nowMs),
  },
  "/v1/patreon/link/session": {
    method: "DELETE",
    handler: (env, req) => handleLinkCancel(patreonEnv(env), req),
  },
  "/v1/patreon/entitlement/refresh": {
    method: "POST",
    handler: (env, req, nowMs, deps) => handleRefresh(patreonEnv(env), req, nowMs, deps),
  },
  "/v1/patreon/unlink": {
    method: "POST",
    handler: (env, req) => handleUnlink(patreonEnv(env), req),
  },
};

async function route(env: Env, request: Request, pathname: string, nowMs: number, deps: PatreonDeps): Promise<Response> {
  const entry = Object.prototype.hasOwnProperty.call(ROUTES, pathname) ? ROUTES[pathname] : undefined;
  if (!entry) return failure(404, "not_found");
  if (request.method !== entry.method) return failure(405, "method_not_allowed", { allow: entry.method });
  try {
    return await entry.handler(env, request, nowMs, deps);
  } catch (err) {
    if (err instanceof StorageUnavailable) return unavailable("storage_unavailable");
    // Never leak details; the ops log records only a reason code.
    return failure(500, "internal_error");
  }
}

/**
 * Build the Worker handler around an injectable clock (tests pin time; production uses Date.now)
 * and an injectable `fetch` for ALL Patreon HTTP traffic (tests pass a mock; no real call is ever made in tests).
 */
export function createHandler(
  now: () => number = () => Date.now(),
  patreonFetch: PatreonDeps["fetch"] = (input, init) => fetch(input, init),
): ExportedHandler<Env> {
  const deps: PatreonDeps = { fetch: patreonFetch };
  return {
    async fetch(request: Request, env: Env): Promise<Response> {
      const started = now();
      const pathname = new URL(request.url).pathname;
      let response: Response;
      try {
        response = await route(env, request, pathname, started, deps);
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
      // Two cron triggers = two invocations, so each stays within the Free-plan 50 D1 queries.
      if (controller.cron === PATREON_CRON) {
        ctx.waitUntil(runPatreonScheduled(patreonEnv(env), controller.scheduledTime));
      } else {
        ctx.waitUntil(runScheduled(telemetryEnv(env), controller.scheduledTime));
      }
    },
  };
}
