/**
 * Device-link flow:
 *   POST   /v1/patreon/link/start       desktop app begins a link, gets authorize_url + poll_token
 *   GET    /v1/patreon/oauth/callback   browser returns here from Patreon (static HTML only)
 *   GET    /v1/patreon/link/status      desktop app polls; the FIRST terminal poll delivers credentials
 *   DELETE /v1/patreon/link/session     desktop app cancels
 *
 * Patreon is only used to answer "does this person have an eligible membership?".
 * No profile data is returned or kept; the only durable result is a capability lease.
 */
import type { PatreonEnv } from "../env";
import { failure, guardDb, json, noContent, unavailable } from "../http";
import { exchangeCode, fetchIdentity } from "./api";
import { linkEnabled, loadConfig, type PatreonConfig } from "./config";
import {
  MAX_DEVICES_PER_LINK,
  MAX_PENDING_SESSIONS,
  MAX_POLLS_PER_SESSION,
  POLL_INTERVAL_S,
  SESSION_ID_RE,
  SESSION_TTL_S,
  STATE_RE,
  bearerToken,
  readEnvelope,
  recordMetric,
  type PatreonDeps,
} from "./common";
import { encryptToken, randomId, randomToken, sha256Hex, timingSafeEqualStrings, userHmac } from "./crypto";
import { issueLease, parseCapabilities } from "./issue";
import { LEASE_LIFETIME_S } from "./lease";
import { htmlPage, type PageKind } from "./pages";
import { evaluatePolicy, extractFacts } from "./policy";

/** How long after expiry a finished (linked / not_entitled) session can still hand out credentials. */
const CONSUME_GRACE_S = 600;
/** An `exchanging` session older than expiry + this is considered dead (the Worker died mid-exchange). */
const EXCHANGE_GRACE_S = 120;
const MAX_CODE_LENGTH = 512;
const DUMMY_SESSION_ID = "0".repeat(32);
const DUMMY_HASH = "0".repeat(64);

const nowSeconds = (nowMs: number): number => Math.floor(nowMs / 1000);

// ---------------------------------------------------------------------------
// POST /v1/patreon/link/start
// ---------------------------------------------------------------------------

export async function handleLinkStart(env: PatreonEnv, request: Request, nowMs: number): Promise<Response> {
  if (!linkEnabled(env)) return unavailable("link_disabled");
  const cfg = await loadConfig(env);
  if (cfg === null) return unavailable("not_configured");

  if (env.RL_LINK) {
    // Coarse outer guard only. The key is never stored; an outage of the limiter fails open.
    const key = request.headers.get("cf-connecting-ip") ?? "unknown";
    let allowed = true;
    try {
      allowed = (await env.RL_LINK.limit({ key })).success;
    } catch {
      allowed = true;
    }
    if (!allowed) return failure(429, "rate_limited", { "retry-after": "60" });
  }

  const envelope = await readEnvelope(request, []);
  if (!envelope.ok) return envelope.response;

  const sessionId = randomId();
  const pollToken = randomToken();
  const state = randomToken();
  const nowS = nowSeconds(nowMs);
  const expiresAt = nowS + SESSION_TTL_S;
  const [stateHash, pollHash] = await Promise.all([sha256Hex(state), sha256Hex(pollToken)]);

  // The cap check and the insert are ONE statement, so concurrent starts cannot overshoot the cap.
  const res = await guardDb(() =>
    cfg.db
      .prepare(
        `INSERT INTO link_sessions (session_id, state_hash, poll_token_hash, status, created_at, expires_at)
         SELECT ?1, ?2, ?3, 'pending', ?4, ?5
         WHERE (SELECT COUNT(*) FROM link_sessions WHERE status IN ('pending', 'exchanging') AND expires_at > ?4) < ?6`,
      )
      .bind(sessionId, stateHash, pollHash, nowS, expiresAt, MAX_PENDING_SESSIONS)
      .run(),
  );
  if ((res.meta.changes ?? 0) !== 1) return failure(429, "busy", { "retry-after": "60" });
  await recordMetric(cfg.db, "link_metrics_daily", nowMs, "started");

  const authorize = new URLSearchParams({
    response_type: "code",
    client_id: cfg.clientId,
    redirect_uri: cfg.redirectUri,
    scope: "identity",
    state,
  });
  return json(201, {
    ok: true,
    session_id: sessionId,
    poll_token: pollToken,
    authorize_url: `${cfg.apiBase}/oauth2/authorize?${authorize.toString()}`,
    expires_at: expiresAt,
    poll_interval_s: POLL_INTERVAL_S,
  });
}

// ---------------------------------------------------------------------------
// GET /v1/patreon/oauth/callback
// ---------------------------------------------------------------------------

type FailCode = "patreon_unavailable" | "exchange_failed" | "identity_failed" | "internal";

export async function handleCallback(env: PatreonEnv, request: Request, nowMs: number, deps: PatreonDeps): Promise<Response> {
  if (!linkEnabled(env)) return htmlPage("unavailable");
  const cfg = await loadConfig(env);
  if (cfg === null) return htmlPage("unavailable");
  try {
    return await processCallback(cfg, request, nowMs, deps);
  } catch {
    // D1 outage etc.: never JSON, never details.
    return htmlPage("unavailable");
  }
}

async function processCallback(cfg: PatreonConfig, request: Request, nowMs: number, deps: PatreonDeps): Promise<Response> {
  const params = new URL(request.url).searchParams;
  const state = params.get("state");
  const code = params.get("code");
  const oauthError = params.get("error");
  const nowS = nowSeconds(nowMs);

  // (b) unknown / malformed state: nothing to look up.
  if (state === null || !STATE_RE.test(state)) return htmlPage("expired");
  const stateHash = await sha256Hex(state);

  // (a) the user declined (or Patreon reported an error): pending -> denied. The value is never stored or echoed.
  if (oauthError !== null) {
    const res = await cfg.db
      .prepare("UPDATE link_sessions SET status = 'denied', result_code = ?3 WHERE state_hash = ?1 AND status = 'pending' AND expires_at > ?2")
      .bind(stateHash, nowS, oauthError === "access_denied" ? "access_denied" : "oauth_error")
      .run();
    if ((res.meta.changes ?? 0) === 1) {
      await recordMetric(cfg.db, "link_metrics_daily", nowMs, "denied");
      return htmlPage("denied");
    }
    return htmlPage("expired");
  }
  if (code === null || code.length === 0 || code.length > MAX_CODE_LENGTH) return htmlPage("expired");

  // (c) atomically consume the state: a replayed callback finds the session no longer pending.
  const consumed = await cfg.db
    .prepare("UPDATE link_sessions SET status = 'exchanging' WHERE state_hash = ?1 AND status = 'pending' AND expires_at > ?2")
    .bind(stateHash, nowS)
    .run();
  if ((consumed.meta.changes ?? 0) !== 1) return htmlPage("expired");

  const fail = async (resultCode: FailCode): Promise<Response> => {
    try {
      const res = await cfg.db
        .prepare("UPDATE link_sessions SET status = 'failed', result_code = ?2 WHERE state_hash = ?1 AND status = 'exchanging'")
        .bind(stateHash, resultCode)
        .run();
      if ((res.meta.changes ?? 0) === 1) await recordMetric(cfg.db, "link_metrics_daily", nowMs, "failed");
    } catch {
      /* the session simply ages out */
    }
    return htmlPage("failed");
  };

  try {
    // (d) exchange the code (server side, client secret, one attempt).
    const tokens = await exchangeCode(cfg, deps.fetch, code);
    if (tokens.kind !== "ok") return await fail(tokens.kind === "unavailable" ? "patreon_unavailable" : "exchange_failed");

    // (e) identity (one call, plus the documented fields[user]= fallback inside fetchIdentity).
    const identity = await fetchIdentity(cfg, deps.fetch, tokens.accessToken);
    if (identity.kind !== "ok") return await fail(identity.kind === "unavailable" ? "patreon_unavailable" : "identity_failed");
    const facts = extractFacts(identity.payload);
    if (facts === null) return await fail("identity_failed");
    const hmac = await userHmac(cfg.pepper, facts.userId);
    const result = evaluatePolicy(cfg.policy, facts.memberships, hmac);

    // (f) upsert the link and finish the session.
    const linkId = await upsertLink(cfg, hmac, tokens, result.capabilities, nowS);
    const outcome = result.eligible ? "linked" : "not_entitled";
    const done = await cfg.db
      .prepare("UPDATE link_sessions SET status = ?2, link_id = ?3 WHERE state_hash = ?1 AND status = 'exchanging'")
      .bind(stateHash, outcome, linkId)
      .run();
    if ((done.meta.changes ?? 0) === 1) await recordMetric(cfg.db, "link_metrics_daily", nowMs, outcome);
    return htmlPage(outcome satisfies PageKind);
  } catch {
    return await fail("internal");
  }
}

async function upsertLink(
  cfg: PatreonConfig,
  hmac: string,
  tokens: { accessToken: string; refreshToken: string; expiresInS: number },
  capabilities: string[],
  nowS: number,
): Promise<string> {
  const capsJson = JSON.stringify(capabilities);
  const expiresAt = nowS + tokens.expiresInS;
  for (let attempt = 0; attempt < 2; attempt++) {
    const existing = await cfg.db
      .prepare("SELECT link_id FROM patreon_links WHERE patreon_user_hmac = ?1")
      .bind(hmac)
      .first<{ link_id: string }>();
    if (existing) {
      // Re-link of a known user: replace the tokens, bump token_version, clear any reauth state.
      const linkId = existing.link_id;
      const [access, refresh] = await Promise.all([
        encryptToken(cfg.encKey, tokens.accessToken, linkId),
        encryptToken(cfg.encKey, tokens.refreshToken, linkId),
      ]);
      await cfg.db
        .prepare(
          `UPDATE patreon_links SET access_token_enc = ?2, refresh_token_enc = ?3, token_expires_at = ?4,
             token_version = token_version + 1, refresh_lock_until = NULL, last_verified_at = ?5,
             last_capabilities = ?6, policy_version = ?7, status = 'active' WHERE link_id = ?1`,
        )
        .bind(linkId, access, refresh, expiresAt, nowS, capsJson, cfg.policy.policy_version)
        .run();
      return linkId;
    }
    const linkId = randomId();
    const [access, refresh] = await Promise.all([
      encryptToken(cfg.encKey, tokens.accessToken, linkId),
      encryptToken(cfg.encKey, tokens.refreshToken, linkId),
    ]);
    try {
      await cfg.db
        .prepare(
          `INSERT INTO patreon_links (link_id, patreon_user_hmac, access_token_enc, refresh_token_enc, token_expires_at,
             token_version, refresh_lock_until, last_verified_at, last_capabilities, policy_version, status, created_at)
           VALUES (?1, ?2, ?3, ?4, ?5, 1, NULL, ?6, ?7, ?8, 'active', ?6)`,
        )
        .bind(linkId, hmac, access, refresh, expiresAt, nowS, capsJson, cfg.policy.policy_version)
        .run();
      return linkId;
    } catch (err) {
      // Lost a race with a concurrent link of the same user (UNIQUE patreon_user_hmac): retry as an update.
      if (attempt === 1) throw err;
    }
  }
  throw new Error("upsert_link_failed");
}

// ---------------------------------------------------------------------------
// Session authentication (shared by status and cancel)
// ---------------------------------------------------------------------------

interface SessionRow {
  session_id: string;
  poll_token_hash: string | null;
  status: string;
  expires_at: number;
  link_id: string | null;
  result_code: string | null;
  polls: number;
  consumed: number;
}

/**
 * Returns the session only for a correct (session_id, poll_token) pair. Unknown session,
 * malformed id, missing token and wrong token are indistinguishable to the caller, and all
 * of them do the same work (one SELECT, one SHA-256, one constant-time comparison).
 */
async function authenticateSession(db: D1Database, request: Request, sessionIdParam: string | null): Promise<SessionRow | null> {
  const token = bearerToken(request);
  const idValid = sessionIdParam !== null && SESSION_ID_RE.test(sessionIdParam);
  const [presentedHash, row] = await Promise.all([
    sha256Hex(token ?? ""),
    guardDb(() =>
      db
        .prepare(
          "SELECT session_id, poll_token_hash, status, expires_at, link_id, result_code, polls, consumed FROM link_sessions WHERE session_id = ?1",
        )
        .bind(idValid ? sessionIdParam : DUMMY_SESSION_ID)
        .first<SessionRow>(),
    ),
  ]);
  const tokenMatches = timingSafeEqualStrings(presentedHash, row?.poll_token_hash ?? DUMMY_HASH);
  if (row === null || !idValid || token === null || !tokenMatches) return null;
  return row;
}

const NOT_FOUND = (): Response => failure(404, "not_found");

// ---------------------------------------------------------------------------
// GET /v1/patreon/link/status
// ---------------------------------------------------------------------------

export async function handleLinkStatus(env: PatreonEnv, request: Request, nowMs: number): Promise<Response> {
  if (!linkEnabled(env)) return unavailable("link_disabled");
  const cfg = await loadConfig(env);
  if (cfg === null) return unavailable("not_configured");
  const nowS = nowSeconds(nowMs);

  const session = await authenticateSession(cfg.db, request, new URL(request.url).searchParams.get("session_id"));
  if (session === null) return NOT_FOUND();

  // Poll cap, counted only for authenticated polls (an outsider cannot burn someone's budget).
  const bumped = await guardDb(() =>
    cfg.db
      .prepare("UPDATE link_sessions SET polls = polls + 1 WHERE session_id = ?1 AND polls < ?2")
      .bind(session.session_id, MAX_POLLS_PER_SESSION)
      .run(),
  );
  if ((bumped.meta.changes ?? 0) !== 1) return failure(429, "poll_limit", { "retry-after": "60" });

  let status = session.status;
  // Time-based expiry (persisted opportunistically so the funnel counts it once).
  if (status === "pending" && nowS >= session.expires_at) {
    await expireSession(cfg, session.session_id, "pending", nowMs);
    status = "expired";
  } else if (status === "exchanging") {
    if (nowS >= session.expires_at + EXCHANGE_GRACE_S) {
      await expireSession(cfg, session.session_id, "exchanging", nowMs);
      status = "expired";
    } else {
      status = "pending"; // the browser leg is still running
    }
  } else if ((status === "linked" || status === "not_entitled") && session.consumed === 0 && nowS > session.expires_at + CONSUME_GRACE_S) {
    status = "expired";
  }

  if ((status === "linked" || status === "not_entitled") && session.consumed === 0) {
    return deliverCredentials(cfg, session, status, nowMs);
  }
  if (status === "failed") return json(200, { ok: true, status, code: session.result_code ?? "failed" });
  return json(200, { ok: true, status });
}

async function expireSession(cfg: PatreonConfig, sessionId: string, from: "pending" | "exchanging", nowMs: number): Promise<void> {
  try {
    const res = await cfg.db
      .prepare("UPDATE link_sessions SET status = 'expired' WHERE session_id = ?1 AND status = ?2")
      .bind(sessionId, from)
      .run();
    if ((res.meta.changes ?? 0) === 1) await recordMetric(cfg.db, "link_metrics_daily", nowMs, "expired");
  } catch {
    /* reported as expired anyway; retried on the next poll */
  }
}

/**
 * First poll after linked / not_entitled: atomically consume the session, create the device
 * and return its credentials exactly once. Insert + consume + eviction are ONE D1 batch
 * (a transaction): either the credentials exist and the session is consumed, or nothing happened.
 */
async function deliverCredentials(
  cfg: PatreonConfig,
  session: SessionRow,
  status: "linked" | "not_entitled",
  nowMs: number,
): Promise<Response> {
  if (!cfg.issuanceEnabled) return unavailable("issuance_disabled"); // nothing consumed; retry later
  const nowS = nowSeconds(nowMs);
  const link = session.link_id
    ? await guardDb(() =>
        cfg.db
          .prepare("SELECT last_capabilities FROM patreon_links WHERE link_id = ?1")
          .bind(session.link_id)
          .first<{ last_capabilities: string }>(),
      )
    : null;
  if (link === null) return json(200, { ok: true, status: "failed", code: "link_missing" });

  const deviceId = randomId();
  const deviceToken = randomToken();
  const tokenHash = await sha256Hex(deviceToken);
  const signed = await issueLease(cfg, deviceId, parseCapabilities(link.last_capabilities), nowS);

  const results = await guardDb(() =>
    cfg.db.batch([
      cfg.db
        .prepare(
          `INSERT INTO devices (device_id, link_id, token_hash, created_at, last_refresh_at, last_lease_expires_at, client_version)
           SELECT ?1, ?2, ?3, ?4, NULL, ?5, NULL
           WHERE EXISTS (SELECT 1 FROM link_sessions WHERE session_id = ?6 AND consumed = 0 AND status IN ('linked', 'not_entitled'))
             AND EXISTS (SELECT 1 FROM patreon_links WHERE link_id = ?2)`,
        )
        .bind(deviceId, session.link_id, tokenHash, nowS, nowS + LEASE_LIFETIME_S, session.session_id),
      cfg.db
        .prepare(
          `UPDATE link_sessions SET consumed = 1, status = 'consumed'
           WHERE session_id = ?2 AND consumed = 0 AND status IN ('linked', 'not_entitled')
             AND EXISTS (SELECT 1 FROM devices WHERE device_id = ?1)`,
        )
        .bind(deviceId, session.session_id),
      // Device cap: keep the newest MAX_DEVICES_PER_LINK, evict the oldest by created_at.
      cfg.db
        .prepare(
          `DELETE FROM devices WHERE device_id IN
             (SELECT device_id FROM devices WHERE link_id = ?1 ORDER BY created_at DESC, rowid DESC LIMIT -1 OFFSET ?2)`,
        )
        .bind(session.link_id, MAX_DEVICES_PER_LINK),
    ]),
  );
  const consumed = (results[1]?.meta.changes ?? 0) === 1;
  if (!consumed) {
    // Lost the race to a concurrent poll: credentials were delivered to that one.
    return json(200, { ok: true, status: "consumed" });
  }
  return json(200, { ok: true, status, device_token: deviceToken, device_id: deviceId, lease: signed });
}

// ---------------------------------------------------------------------------
// DELETE /v1/patreon/link/session
// ---------------------------------------------------------------------------

export async function handleLinkCancel(env: PatreonEnv, request: Request): Promise<Response> {
  const db = env.PATREON_DB;
  if (!db) return unavailable("not_configured");
  const session = await authenticateSession(db, request, new URL(request.url).searchParams.get("session_id"));
  if (session !== null) {
    await guardDb(() =>
      db
        .prepare("UPDATE link_sessions SET status = 'cancelled' WHERE session_id = ?1 AND status = 'pending'")
        .bind(session.session_id)
        .run(),
    );
  }
  return noContent(); // identical for unknown session / wrong token / success
}
