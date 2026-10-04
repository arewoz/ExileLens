/**
 * Validated Patreon configuration. Built per request from the narrowed PatreonEnv.
 * Any missing or invalid piece yields `null` -> handlers answer 503 not_configured
 * (Retry-After 3600) instead of crashing.
 */
import type { PatreonEnv } from "../env";
import { importEncryptionKey } from "./crypto";
import { importSigningKey } from "./lease";
import { parseOverrideSecret, parsePolicy, withExtraOverrides, type Policy } from "./policy";

export const DEFAULT_API_BASE = "https://www.patreon.com";
export const DEFAULT_KEY_ID = "exilelens-entitlement-1";
const MIN_PEPPER_LENGTH = 16;

export interface PatreonConfig {
  db: D1Database;
  clientId: string;
  clientSecret: string;
  redirectUri: string;
  apiBase: string;
  kid: string;
  policy: Policy;
  pepper: string;
  encKey: CryptoKey;
  signKey: CryptoKey;
  linkEnabled: boolean;
  issuanceEnabled: boolean;
}

/** True for https URLs and for http only on loopback hosts (local development). */
function validRedirect(value: string | undefined): value is string {
  if (typeof value !== "string") return false;
  try {
    const u = new URL(value);
    const local = u.hostname === "localhost" || u.hostname === "127.0.0.1" || u.hostname === "[::1]";
    if (u.protocol !== "https:" && !(u.protocol === "http:" && local)) return false;
    return u.pathname === "/v1/patreon/oauth/callback" && u.search === "" && u.hash === "";
  } catch {
    return false;
  }
}

function validBase(value: string): boolean {
  try {
    const u = new URL(value);
    const local = u.hostname === "localhost" || u.hostname === "127.0.0.1" || u.hostname === "[::1]";
    return (u.protocol === "https:" || (u.protocol === "http:" && local)) && u.search === "" && u.hash === "";
  } catch {
    return false;
  }
}

/** Kill switches (default ON when the var is absent; only the exact string "false" disables). */
export function linkEnabled(env: PatreonEnv): boolean {
  return env.PATREON_LINK_ENABLED !== "false";
}

export function issuanceEnabled(env: PatreonEnv): boolean {
  return env.LEASE_ISSUANCE_ENABLED !== "false";
}

export async function loadConfig(env: PatreonEnv): Promise<PatreonConfig | null> {
  try {
    if (!env.PATREON_DB) return null;
    const clientId = env.PATREON_CLIENT_ID;
    const clientSecret = env.PATREON_CLIENT_SECRET;
    if (typeof clientId !== "string" || clientId.trim() === "") return null;
    if (typeof clientSecret !== "string" || clientSecret.trim() === "") return null;
    if (!validRedirect(env.PATREON_REDIRECT_URI)) return null;
    const apiBase = (env.PATREON_API_BASE ?? "").trim() === "" ? DEFAULT_API_BASE : (env.PATREON_API_BASE as string).trim().replace(/\/+$/, "");
    if (!validBase(apiBase)) return null;
    const kid = (env.ENTITLEMENT_KEY_ID ?? "").trim() === "" ? DEFAULT_KEY_ID : (env.ENTITLEMENT_KEY_ID as string).trim();
    if (!/^[A-Za-z0-9._-]{1,64}$/.test(kid)) return null;
    const basePolicy = parsePolicy(env.ENTITLEMENT_POLICY);
    if (basePolicy === null) return null;
    const policy = withExtraOverrides(basePolicy, parseOverrideSecret(env.PATREON_OVERRIDE_USER_HMACS));
    const pepper = env.PATREON_ID_PEPPER;
    if (typeof pepper !== "string" || pepper.length < MIN_PEPPER_LENGTH) return null;
    const encKey = typeof env.TOKEN_ENC_KEY === "string" ? await importEncryptionKey(env.TOKEN_ENC_KEY) : null;
    if (encKey === null) return null;
    const signKey = await importSigningKey(env.ENTITLEMENT_SIGNING_KEY);
    if (signKey === null) return null;
    return {
      db: env.PATREON_DB,
      clientId: clientId.trim(),
      clientSecret,
      redirectUri: env.PATREON_REDIRECT_URI,
      apiBase,
      kid,
      policy,
      pepper,
      encKey,
      signKey,
      linkEnabled: linkEnabled(env),
      issuanceEnabled: issuanceEnabled(env),
    };
  } catch {
    return null;
  }
}
