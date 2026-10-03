/**
 * Worker environment types and the telemetry-only narrowing.
 *
 * The Worker's full `Env` will gain a PATREON_DB binding in Package B. Telemetry
 * and error handlers must never see it, so they only ever receive the object
 * built by `telemetryEnv()`, which copies an explicit allow-list of keys.
 */

/** Minimal shape of the Workers Rate Limiting binding (optional, see wrangler.toml). */
export interface RateLimiter {
  limit(options: { key: string }): Promise<{ success: boolean }>;
}

/** Everything telemetry/error handlers are allowed to see. */
export interface TelemetryEnv {
  TELEMETRY_DB: D1Database;
  ANALYTICS_PEPPER: string;
  DIAGNOSTIC_PEPPER: string;
  /** "false" turns the ingest endpoints off (503 ingest_disabled). */
  INGEST_ENABLED?: string;
  /** Optional coarse outer guard keyed by CF-Connecting-IP (never stored). */
  RL_INGEST?: RateLimiter;
}

/** Full Worker environment. Package B adds its own second database binding here. */
export interface Env extends TelemetryEnv {
  // Package B adds the Patreon database binding and its secrets HERE, never in TelemetryEnv.
}

/**
 * Build the narrowed environment for telemetry/error code. Explicit allow-list:
 * adding a binding to `Env` never leaks it into telemetry handlers.
 */
export function telemetryEnv(env: Env): TelemetryEnv {
  const narrowed: TelemetryEnv = {
    TELEMETRY_DB: env.TELEMETRY_DB,
    ANALYTICS_PEPPER: env.ANALYTICS_PEPPER,
    DIAGNOSTIC_PEPPER: env.DIAGNOSTIC_PEPPER,
  };
  if (env.INGEST_ENABLED !== undefined) narrowed.INGEST_ENABLED = env.INGEST_ENABLED;
  if (env.RL_INGEST !== undefined) narrowed.RL_INGEST = env.RL_INGEST;
  return narrowed;
}
