/**
 * Patreon HTTP client. ALL Patreon traffic goes through an injectable `fetch`
 * (tests pass a mock; production passes the global). One attempt per call - there
 * are no retry loops here (Patreon blocks clients that cause many 4xx responses),
 * the single exception being the documented `fields[user]=` fallback in fetchIdentity.
 *
 * Nothing in this file logs, and no response body is ever returned to a caller of
 * the Worker: callers only receive the small result unions below.
 */
import type { PatreonConfig } from "./config";

export type FetchFn = (input: string, init?: RequestInit) => Promise<Response>;

const REQUEST_TIMEOUT_MS = 8000;
const MAX_BODY_CHARS = 262_144;
const DEFAULT_RETRY_AFTER_S = 60;
/** Used when Patreon omits or sends a nonsensical `expires_in` (unverified; Patreon tokens last ~1 month). */
const DEFAULT_TOKEN_LIFETIME_S = 2_592_000;
const MIN_TOKEN_LIFETIME_S = 60;
const MAX_TOKEN_LIFETIME_S = 400 * 86_400;

export type TokenResult =
  | { kind: "ok"; accessToken: string; refreshToken: string; expiresInS: number }
  /** Patreon says the code / refresh token is no longer valid. */
  | { kind: "invalid_grant" }
  /** Network error, timeout, 5xx, 429 or an unexpected response: nothing is known about the grant. */
  | { kind: "unavailable"; retryAfterS: number }
  /** Another 4xx (e.g. invalid_client = our own configuration problem). */
  | { kind: "rejected" };

export type IdentityResult =
  | { kind: "ok"; payload: unknown }
  | { kind: "unauthorized" }
  | { kind: "unavailable"; retryAfterS: number };

async function readText(res: Response): Promise<string> {
  try {
    const text = await res.text();
    return text.length > MAX_BODY_CHARS ? text.slice(0, MAX_BODY_CHARS) : text;
  } catch {
    return "";
  }
}

function parseJson(text: string): Record<string, unknown> | null {
  try {
    const v: unknown = JSON.parse(text);
    return typeof v === "object" && v !== null && !Array.isArray(v) ? (v as Record<string, unknown>) : null;
  } catch {
    return null;
  }
}

function retryAfterSeconds(res: Response, body: Record<string, unknown> | null): number {
  const fromBody = body?.retry_after_seconds;
  const header = Number(res.headers.get("retry-after"));
  const raw = typeof fromBody === "number" ? fromBody : Number.isFinite(header) && header > 0 ? header : DEFAULT_RETRY_AFTER_S;
  return Math.min(3600, Math.max(5, Math.ceil(raw)));
}

async function call(fetchFn: FetchFn, url: string, init: RequestInit): Promise<Response | null> {
  try {
    return await fetchFn(url, { ...init, redirect: "manual", signal: AbortSignal.timeout(REQUEST_TIMEOUT_MS) });
  } catch {
    return null;
  }
}

async function tokenRequest(cfg: PatreonConfig, fetchFn: FetchFn, form: Record<string, string>): Promise<TokenResult> {
  const res = await call(fetchFn, `${cfg.apiBase}/api/oauth2/token`, {
    method: "POST",
    headers: { "content-type": "application/x-www-form-urlencoded", accept: "application/json" },
    body: new URLSearchParams(form).toString(),
  });
  if (res === null) return { kind: "unavailable", retryAfterS: DEFAULT_RETRY_AFTER_S };
  const text = await readText(res);
  const body = parseJson(text);
  if (res.status === 200) {
    const access = body?.access_token;
    const refresh = body?.refresh_token;
    if (typeof access !== "string" || access.length === 0 || access.length > 4096) return { kind: "unavailable", retryAfterS: DEFAULT_RETRY_AFTER_S };
    if (typeof refresh !== "string" || refresh.length === 0 || refresh.length > 4096) return { kind: "unavailable", retryAfterS: DEFAULT_RETRY_AFTER_S };
    const exp = body?.expires_in;
    const expiresInS =
      typeof exp === "number" && Number.isFinite(exp)
        ? Math.min(MAX_TOKEN_LIFETIME_S, Math.max(MIN_TOKEN_LIFETIME_S, Math.floor(exp)))
        : DEFAULT_TOKEN_LIFETIME_S;
    return { kind: "ok", accessToken: access, refreshToken: refresh, expiresInS };
  }
  if (res.status === 429 || res.status >= 500 || (res.status >= 300 && res.status < 400)) {
    return { kind: "unavailable", retryAfterS: retryAfterSeconds(res, body) };
  }
  if ((res.status === 400 || res.status === 401) && body?.error === "invalid_grant") return { kind: "invalid_grant" };
  return { kind: "rejected" };
}

/** authorization_code -> tokens. Exactly one HTTP attempt. */
export function exchangeCode(cfg: PatreonConfig, fetchFn: FetchFn, code: string): Promise<TokenResult> {
  return tokenRequest(cfg, fetchFn, {
    grant_type: "authorization_code",
    code,
    client_id: cfg.clientId,
    client_secret: cfg.clientSecret,
    redirect_uri: cfg.redirectUri,
  });
}

/** refresh_token -> NEW tokens (Patreon refresh tokens are single-use). Exactly one HTTP attempt. */
export function refreshTokens(cfg: PatreonConfig, fetchFn: FetchFn, refreshToken: string): Promise<TokenResult> {
  return tokenRequest(cfg, fetchFn, {
    grant_type: "refresh_token",
    refresh_token: refreshToken,
    client_id: cfg.clientId,
    client_secret: cfg.clientSecret,
  });
}

const IDENTITY_QUERY =
  "include=memberships,memberships.currently_entitled_tiers,memberships.campaign" +
  "&fields[member]=patron_status,is_gifted,is_free_trial&fields[tier]=amount_cents";

/**
 * GET /api/oauth2/v2/identity. We ask for NO user fields (`fields[user]=`). Whether
 * Patreon accepts the empty value is UNVERIFIED (see README "Live activation checks"):
 * if it answers 400 we retry exactly once without that parameter. The returned user
 * attributes (if any) are never read, stored or returned.
 */
export async function fetchIdentity(cfg: PatreonConfig, fetchFn: FetchFn, accessToken: string): Promise<IdentityResult> {
  const base = `${cfg.apiBase}/api/oauth2/v2/identity?${IDENTITY_QUERY}`;
  const init: RequestInit = { method: "GET", headers: { authorization: `Bearer ${accessToken}`, accept: "application/json" } };
  let res = await call(fetchFn, `${base}&fields[user]=`, init);
  if (res !== null && res.status === 400) {
    await readText(res); // drain
    res = await call(fetchFn, base, init);
  }
  if (res === null) return { kind: "unavailable", retryAfterS: DEFAULT_RETRY_AFTER_S };
  const text = await readText(res);
  if (res.status === 401) return { kind: "unauthorized" };
  const body = parseJson(text);
  if (res.status === 200 && body !== null) return { kind: "ok", payload: body };
  return { kind: "unavailable", retryAfterS: retryAfterSeconds(res, body) };
}
