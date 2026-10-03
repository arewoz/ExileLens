/** Small helpers shared by the Patreon handlers. */
import { failure, readJsonBody, utcDay } from "../http";
import type { FetchFn } from "./api";

/** Injected dependencies (tests pass a mock Patreon `fetch`). */
export interface PatreonDeps {
  fetch: FetchFn;
}

export const SESSION_TTL_S = 600;
export const MAX_PENDING_SESSIONS = 200;
export const MAX_POLLS_PER_SESSION = 400;
export const POLL_INTERVAL_S = 2;
export const MAX_DEVICES_PER_LINK = 5;
export const MIN_REFRESH_INTERVAL_S = 60;
export const VERIFY_MAX_AGE_S = 12 * 3600;
export const VERIFY_EMPTY_MAX_AGE_S = 3600;
export const TOKEN_REFRESH_WINDOW_S = 3 * 86_400;
export const REFRESH_LOCK_S = 30;

export const SESSION_ID_RE = /^[0-9a-f]{32}$/;
export const STATE_RE = /^[A-Za-z0-9_-]{43}$/;
const BEARER_RE = /^Bearer ([A-Za-z0-9_-]{43})$/;

export function isObject(v: unknown): v is Record<string, unknown> {
  return typeof v === "object" && v !== null && !Array.isArray(v);
}

/** Extract a well-formed bearer token (43 base64url chars) or null. */
export function bearerToken(request: Request): string | null {
  const header = request.headers.get("authorization");
  if (header === null) return null;
  const m = BEARER_RE.exec(header);
  return m ? (m[1] as string) : null;
}

export type CountTable = "link_metrics_daily" | "entitlement_refresh_daily";

/**
 * Increment an anonymous daily counter. Never throws: a metrics failure must not
 * change the outcome of a request. No identifier of any kind is written.
 */
export async function recordMetric(db: D1Database, table: CountTable, nowMs: number, outcome: string): Promise<void> {
  try {
    await db
      .prepare(`INSERT INTO ${table} (day, outcome, count) VALUES (?1, ?2, 1) ON CONFLICT (day, outcome) DO UPDATE SET count = count + 1`)
      .bind(utcDay(nowMs), outcome)
      .run();
  } catch {
    /* intentionally ignored */
  }
}

/**
 * Read `{schema: 1, ...optional}` bodies. Unknown fields -> 400 unknown_field, missing schema ->
 * 400 invalid_envelope, other schema -> 422 schema_unsupported.
 */
export async function readEnvelope(
  request: Request,
  optional: readonly string[],
): Promise<{ ok: true; body: Record<string, unknown> } | { ok: false; response: Response }> {
  const parsed = await readJsonBody(request, 1024);
  if (!parsed.ok) return parsed;
  const body = parsed.value;
  if (!isObject(body)) return { ok: false, response: failure(400, "invalid_envelope") };
  for (const key of Object.keys(body)) {
    if (key !== "schema" && !optional.includes(key)) return { ok: false, response: failure(400, "unknown_field") };
  }
  if (!("schema" in body)) return { ok: false, response: failure(400, "invalid_envelope") };
  if (body.schema !== 1) return { ok: false, response: failure(422, "schema_unsupported") };
  return { ok: true, body };
}
