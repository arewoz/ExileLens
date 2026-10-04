/**
 * Worker environment types and the two narrowings.
 *
 * The Worker's full `Env` holds BOTH databases. Usage-statistics and error handlers
 * only ever receive the object built by `telemetryEnv()`; Patreon handlers only ever
 * receive the object built by `patreonEnv()`. Each copies an explicit allow-list of
 * keys, so adding a binding to `Env` never leaks it into the other side.
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

/**
 * Everything Patreon handlers are allowed to see. Every field is optional on purpose:
 * missing/invalid configuration must produce `503 not_configured`, never a crash.
 */
export interface PatreonEnv {
  PATREON_DB?: D1Database;
  /** Secrets. */
  PATREON_CLIENT_SECRET?: string;
  /** PKCS#8 Ed25519 private key, base64 DER or PEM. NOT the update-signing key. */
  ENTITLEMENT_SIGNING_KEY?: string;
  /** 32 random bytes, base64. AES-256-GCM key for the stored Patreon tokens. */
  TOKEN_ENC_KEY?: string;
  PATREON_ID_PEPPER?: string;
  /** Vars. */
  PATREON_CLIENT_ID?: string;
  /** The Worker's own `/v1/patreon/oauth/callback` URL. */
  PATREON_REDIRECT_URI?: string;
  /** Default `https://www.patreon.com`. */
  PATREON_API_BASE?: string;
  /** "false" = kill switch for NEW links (503 link_disabled). */
  PATREON_LINK_ENABLED?: string;
  /** "false" = no lease is issued at all (503 issuance_disabled). */
  LEASE_ISSUANCE_ENABLED?: string;
  /** Default `exilelens-entitlement-1`. */
  ENTITLEMENT_KEY_ID?: string;
  /** JSON string, see src/patreon/policy.ts. */
  ENTITLEMENT_POLICY?: string;
  /** Optional secret: JSON `{ "<user hmac hex>": ["capability"] }`, merged into the policy's overrides (creator / testers). */
  PATREON_OVERRIDE_USER_HMACS?: string;
  /** Optional coarse outer guard for link/start, keyed by CF-Connecting-IP (never stored). */
  RL_LINK?: RateLimiter;
}

/** Full Worker environment. */
export interface Env extends TelemetryEnv, PatreonEnv {}

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

const PATREON_KEYS = [
  "PATREON_DB",
  "PATREON_CLIENT_SECRET",
  "ENTITLEMENT_SIGNING_KEY",
  "TOKEN_ENC_KEY",
  "PATREON_ID_PEPPER",
  "PATREON_CLIENT_ID",
  "PATREON_REDIRECT_URI",
  "PATREON_API_BASE",
  "PATREON_LINK_ENABLED",
  "LEASE_ISSUANCE_ENABLED",
  "ENTITLEMENT_KEY_ID",
  "ENTITLEMENT_POLICY",
  "PATREON_OVERRIDE_USER_HMACS",
  "RL_LINK",
] as const satisfies readonly (keyof PatreonEnv)[];

/**
 * Build the narrowed environment for Patreon code: an explicit allow-list that can
 * never contain `TELEMETRY_DB` or any usage-statistics pepper.
 */
export function patreonEnv(env: Env): PatreonEnv {
  const narrowed: Record<string, unknown> = {};
  for (const key of PATREON_KEYS) {
    const value = env[key];
    if (value !== undefined) narrowed[key] = value;
  }
  return narrowed as PatreonEnv;
}
