/**
 * Lease refresh and unlink.
 *
 *   POST /v1/patreon/entitlement/refresh   Bearer device token -> a fresh signed lease
 *   POST /v1/patreon/unlink                Bearer device token -> 204 (always)
 *
 * Rules: Patreon problems (5xx / 429 / network) never revoke anything and never produce a
 * lease - the client simply keeps the lease it has until it expires. Only an explicit
 * `invalid_grant` (token refresh) or 401 (identity) from Patreon turns a link into
 * `reauth_required`. One attempt per Patreon call type per request; no loops.
 */
import type { PatreonEnv } from "../env";
import { failure, guardDb, json, noContent, unavailable } from "../http";
import { fetchIdentity, refreshTokens } from "./api";
import { loadConfig, type PatreonConfig } from "./config";
import {
  MIN_REFRESH_INTERVAL_S,
  REFRESH_LOCK_S,
  TOKEN_REFRESH_WINDOW_S,
  VERIFY_EMPTY_MAX_AGE_S,
  VERIFY_MAX_AGE_S,
  bearerToken,
  readEnvelope,
  recordMetric,
  type PatreonDeps,
} from "./common";
import { decryptToken, encryptToken, sha256Hex } from "./crypto";
import { issueLease, parseCapabilities } from "./issue";
import { LEASE_LIFETIME_S, LEASE_REFRESH_AFTER_S } from "./lease";
import { evaluatePolicy, extractFacts } from "./policy";

const CLIENT_VERSION_RE = /^[0-9A-Za-z][0-9A-Za-z.+_-]{0,31}$/;
const nowSeconds = (nowMs: number): number => Math.floor(nowMs / 1000);

interface DeviceLinkRow {
  device_id: string;
  link_id: string;
  last_refresh_at: number | null;
  link_status: string | null;
  patreon_user_hmac: string | null;
  access_token_enc: string | null;
  refresh_token_enc: string | null;
  token_expires_at: number | null;
  last_verified_at: number | null;
  last_capabilities: string | null;
  link_policy_version: number | null;
}

interface LinkTokenRow {
  status: string;
  access_token_enc: string | null;
  refresh_token_enc: string | null;
  token_expires_at: number | null;
  token_version: number;
}

/** A stop condition: the HTTP response to send and the anonymous metric outcome to count. */
interface Stop {
  response: Response;
  outcome: string;
  /** Give the per-device throttle slot back (the request did no useful work, e.g. refresh_busy). */
  releaseThrottle?: boolean;
}

const reauthStop = (): Stop => ({ response: failure(401, "reauthorize_required"), outcome: "reauthorize_required" });
const unavailableStop = (retryAfterS: number): Stop => ({
  response: failure(503, "patreon_unavailable", { "retry-after": String(retryAfterS) }),
  outcome: "patreon_unavailable",
});

async function markReauth(db: D1Database, linkId: string): Promise<void> {
  await guardDb(() =>
    db
      .prepare(
        `UPDATE patreon_links SET status = 'reauth_required', access_token_enc = NULL, refresh_token_enc = NULL,
           token_expires_at = NULL, refresh_lock_until = NULL WHERE link_id = ?1`,
      )
      .bind(linkId)
      .run(),
  );
}

async function releaseLock(db: D1Database, linkId: string): Promise<void> {
  try {
    await db.prepare("UPDATE patreon_links SET refresh_lock_until = NULL WHERE link_id = ?1").bind(linkId).run();
  } catch {
    /* the lock expires by itself after REFRESH_LOCK_S */
  }
}

async function tryDecrypt(cfg: PatreonConfig, stored: string | null, linkId: string): Promise<string | null> {
  if (stored === null || stored === "") return null;
  try {
    return await decryptToken(cfg.encKey, stored, linkId);
  } catch {
    return null;
  }
}

/**
 * Refresh the access token under a D1 conditional lock, so concurrent refreshes of one
 * link cause exactly ONE Patreon token call (refresh tokens are single-use).
 */
async function refreshUnderLock(
  cfg: PatreonConfig,
  deps: PatreonDeps,
  linkId: string,
  nowS: number,
): Promise<{ accessToken: string } | Stop> {
  const lock = await guardDb(() =>
    cfg.db
      .prepare(
        `UPDATE patreon_links SET refresh_lock_until = ?2
         WHERE link_id = ?1 AND status = 'active' AND (refresh_lock_until IS NULL OR refresh_lock_until < ?3)`,
      )
      .bind(linkId, nowS + REFRESH_LOCK_S, nowS)
      .run(),
  );
  if ((lock.meta.changes ?? 0) !== 1) {
    // Someone else holds the lock (or the link stopped being active).
    return { response: failure(503, "refresh_busy", { "retry-after": "5" }), outcome: "patreon_unavailable", releaseThrottle: true };
  }
  try {
    // Re-read under the lock: another request may have rotated the tokens since our first SELECT.
    const cur = await guardDb(() =>
      cfg.db
        .prepare("SELECT status, access_token_enc, refresh_token_enc, token_expires_at, token_version FROM patreon_links WHERE link_id = ?1")
        .bind(linkId)
        .first<LinkTokenRow>(),
    );
    if (cur === null || cur.status !== "active" || cur.refresh_token_enc === null) {
      await releaseLock(cfg.db, linkId);
      return reauthStop();
    }
    if (cur.token_expires_at !== null && cur.token_expires_at > nowS + TOKEN_REFRESH_WINDOW_S) {
      await releaseLock(cfg.db, linkId);
      const access = await tryDecrypt(cfg, cur.access_token_enc, linkId);
      if (access === null) {
        await markReauth(cfg.db, linkId);
        return reauthStop();
      }
      return { accessToken: access };
    }
    const refreshToken = await tryDecrypt(cfg, cur.refresh_token_enc, linkId);
    if (refreshToken === null) {
      await markReauth(cfg.db, linkId);
      return reauthStop();
    }

    const result = await refreshTokens(cfg, deps.fetch, refreshToken);
    switch (result.kind) {
      case "ok": {
        const [access, refresh] = await Promise.all([
          encryptToken(cfg.encKey, result.accessToken, linkId),
          encryptToken(cfg.encKey, result.refreshToken, linkId),
        ]);
        // The NEW refresh token must be persisted together with the version bump. A concurrent
        // re-link (which bumps token_version itself) wins; we then just use our token in memory.
        await guardDb(() =>
          cfg.db
            .prepare(
              `UPDATE patreon_links SET access_token_enc = ?2, refresh_token_enc = ?3, token_expires_at = ?4,
                 token_version = token_version + 1, refresh_lock_until = NULL
               WHERE link_id = ?1 AND token_version = ?5`,
            )
            .bind(linkId, access, refresh, nowS + result.expiresInS, cur.token_version)
            .run(),
        );
        return { accessToken: result.accessToken };
      }
      case "invalid_grant":
        await markReauth(cfg.db, linkId); // also clears the lock
        return reauthStop();
      case "unavailable":
        await releaseLock(cfg.db, linkId);
        return unavailableStop(result.retryAfterS);
      case "rejected":
        await releaseLock(cfg.db, linkId);
        return unavailableStop(300); // our own client credentials are probably wrong: not the user's fault
    }
  } catch (err) {
    await releaseLock(cfg.db, linkId);
    throw err;
  }
}

/** Re-verify the membership with Patreon and cache the resulting capabilities. */
async function verify(cfg: PatreonConfig, deps: PatreonDeps, row: DeviceLinkRow, nowS: number): Promise<{ capabilities: string[] } | Stop> {
  const linkId = row.link_id;
  if (row.patreon_user_hmac === null) return reauthStop();

  let accessToken: string;
  const expiring = row.token_expires_at === null || row.token_expires_at <= nowS + TOKEN_REFRESH_WINDOW_S;
  if (row.access_token_enc === null || row.refresh_token_enc === null) {
    await markReauth(cfg.db, linkId);
    return reauthStop();
  }
  if (expiring) {
    const refreshed = await refreshUnderLock(cfg, deps, linkId, nowS);
    if ("outcome" in refreshed) return refreshed;
    accessToken = refreshed.accessToken;
  } else {
    const access = await tryDecrypt(cfg, row.access_token_enc, linkId);
    if (access === null) {
      await markReauth(cfg.db, linkId);
      return reauthStop();
    }
    accessToken = access;
  }

  const identity = await fetchIdentity(cfg, deps.fetch, accessToken);
  if (identity.kind === "unauthorized") {
    // Patreon explicitly rejected the token (user revoked the app, ...): the user must link again.
    await markReauth(cfg.db, linkId);
    return reauthStop();
  }
  if (identity.kind === "unavailable") return unavailableStop(identity.retryAfterS);
  const facts = extractFacts(identity.payload);
  if (facts === null) return unavailableStop(300);

  const result = evaluatePolicy(cfg.policy, facts.memberships, row.patreon_user_hmac);
  await guardDb(() =>
    cfg.db
      .prepare("UPDATE patreon_links SET last_verified_at = ?2, last_capabilities = ?3, policy_version = ?4 WHERE link_id = ?1")
      .bind(linkId, nowS, JSON.stringify(result.capabilities), cfg.policy.policy_version)
      .run(),
  );
  return { capabilities: result.capabilities };
}

export async function handleRefresh(env: PatreonEnv, request: Request, nowMs: number, deps: PatreonDeps): Promise<Response> {
  const cfg = await loadConfig(env);
  if (cfg === null) return unavailable("not_configured");
  const nowS = nowSeconds(nowMs);
  const stop = async (s: Stop): Promise<Response> => {
    await recordMetric(cfg.db, "entitlement_refresh_daily", nowMs, s.outcome);
    return s.response;
  };

  const envelope = await readEnvelope(request, ["client_version"]);
  if (!envelope.ok) return envelope.response;
  const clientVersion = envelope.body.client_version;
  if (clientVersion !== undefined && (typeof clientVersion !== "string" || !CLIENT_VERSION_RE.test(clientVersion))) {
    return failure(400, "invalid_value");
  }

  // 1. device lookup by SHA-256(device token)
  const token = bearerToken(request);
  const tokenHash = await sha256Hex(token ?? "");
  const row =
    token === null
      ? null
      : await guardDb(() =>
          cfg.db
            .prepare(
              `SELECT d.device_id, d.link_id, d.last_refresh_at,
                      l.status AS link_status, l.patreon_user_hmac, l.access_token_enc, l.refresh_token_enc,
                      l.token_expires_at, l.last_verified_at, l.last_capabilities, l.policy_version AS link_policy_version
               FROM devices d LEFT JOIN patreon_links l ON l.link_id = d.link_id
               WHERE d.token_hash = ?1`,
            )
            .bind(tokenHash)
            .first<DeviceLinkRow>(),
        );
  if (row === null || row.link_status === null) {
    return stop({ response: failure(401, "device_unknown"), outcome: "device_unknown" });
  }

  // 2. per-device throttle (atomic claim of the refresh slot)
  const claim = await guardDb(() =>
    cfg.db
      .prepare("UPDATE devices SET last_refresh_at = ?2 WHERE device_id = ?1 AND (last_refresh_at IS NULL OR last_refresh_at <= ?3)")
      .bind(row.device_id, nowS, nowS - MIN_REFRESH_INTERVAL_S)
      .run(),
  );
  if ((claim.meta.changes ?? 0) !== 1) {
    const wait = Math.max(1, MIN_REFRESH_INTERVAL_S - (nowS - (row.last_refresh_at ?? 0)));
    return stop({ response: failure(429, "rate_limited", { "retry-after": String(wait) }), outcome: "rate_limited" });
  }

  // 3. link state and kill switch
  if (row.link_status === "reauth_required") return stop(reauthStop());
  if (!cfg.issuanceEnabled) return stop({ response: unavailable("issuance_disabled"), outcome: "issuance_disabled" });

  // 4. re-verify with Patreon when the cached verification is stale
  let capabilities = parseCapabilities(row.last_capabilities);
  const age = nowS - (row.last_verified_at ?? 0);
  const stale =
    row.last_verified_at === null ||
    age >= VERIFY_MAX_AGE_S ||
    (capabilities.length === 0 && age >= VERIFY_EMPTY_MAX_AGE_S) ||
    row.link_policy_version !== cfg.policy.policy_version;
  if (stale) {
    const verified = await verify(cfg, deps, row, nowS);
    if ("outcome" in verified) {
      if (verified.releaseThrottle) {
        await guardDb(() =>
          cfg.db
            .prepare("UPDATE devices SET last_refresh_at = ?3 WHERE device_id = ?1 AND last_refresh_at = ?2")
            .bind(row.device_id, nowS, row.last_refresh_at)
            .run(),
        );
      }
      return stop(verified);
    }
    capabilities = verified.capabilities;
  }

  // 5. issue the lease (only ever from a verification at most 12-24 h old, see `stale`)
  const signed = await issueLease(cfg, row.device_id, capabilities, nowS);
  await guardDb(() =>
    cfg.db
      .prepare("UPDATE devices SET last_lease_expires_at = ?2, client_version = COALESCE(?3, client_version) WHERE device_id = ?1")
      .bind(row.device_id, nowS + LEASE_LIFETIME_S, typeof clientVersion === "string" ? clientVersion : null)
      .run(),
  );
  await recordMetric(cfg.db, "entitlement_refresh_daily", nowMs, capabilities.length > 0 ? "ok" : "not_eligible");
  return json(200, { ok: true, lease: signed, next_refresh_after_s: LEASE_REFRESH_AFTER_S, server_time: nowS });
}

export async function handleUnlink(env: PatreonEnv, request: Request): Promise<Response> {
  const db = env.PATREON_DB;
  if (!db) return unavailable("not_configured");
  const token = bearerToken(request);
  if (token !== null) {
    const tokenHash = await sha256Hex(token);
    const row = await guardDb(() =>
      db.prepare("SELECT device_id, link_id FROM devices WHERE token_hash = ?1").bind(tokenHash).first<{ device_id: string; link_id: string }>(),
    );
    if (row !== null) {
      await guardDb(() =>
        db.batch([
          db.prepare("DELETE FROM devices WHERE device_id = ?1").bind(row.device_id),
          // Last device gone -> remove the link including its encrypted tokens.
          db
            .prepare("DELETE FROM patreon_links WHERE link_id = ?1 AND NOT EXISTS (SELECT 1 FROM devices WHERE link_id = ?1)")
            .bind(row.link_id),
        ]),
      );
    }
  }
  return noContent();
}
