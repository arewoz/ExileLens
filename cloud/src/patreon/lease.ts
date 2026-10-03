/**
 * Signed entitlement leases.
 *
 * Ed25519 via Web Crypto. The signed message is
 *   UTF-8("exilelens/entitlement-lease/v1\n") + canonical JSON of the lease
 * where canonical JSON has lexicographically sorted keys at every level, no
 * whitespace, JSON string escaping and integers only - byte-identical to Python's
 * json.dumps(lease, sort_keys=True, separators=(",",":"), ensure_ascii=False).
 *
 * This key is NOT the update-signing key, and a lease never carries a URL, version,
 * file name or hash: it only says "this device may use these capabilities until X".
 */
import { fromBase64, toBase64 } from "./crypto";

export const LEASE_DOMAIN_PREFIX = "exilelens/entitlement-lease/v1\n";
export const LEASE_REFRESH_AFTER_S = 86_400;
export const LEASE_LIFETIME_S = 604_800;

export const LEASE_KEYS = [
  "capabilities",
  "expires_at",
  "issued_at",
  "kid",
  "lease_id",
  "policy_version",
  "refresh_after",
  "schema",
  "sub",
] as const;

export interface Lease {
  schema: 1;
  kid: string;
  lease_id: string;
  /** device_id */
  sub: string;
  capabilities: string[];
  issued_at: number;
  refresh_after: number;
  expires_at: number;
  policy_version: number;
}

export interface SignedLease {
  lease: Lease;
  /** base64 of the 64-byte Ed25519 signature */
  signature: string;
}

const encoder = new TextEncoder();

/** Canonical JSON (see file header). Throws on non-integer numbers and unsupported types. */
export function canonicalJson(value: unknown): string {
  if (value === null) return "null";
  switch (typeof value) {
    case "string":
      return JSON.stringify(value);
    case "boolean":
      return value ? "true" : "false";
    case "number":
      if (!Number.isInteger(value)) throw new Error("canonical_json: integers only");
      return String(value);
    case "object": {
      if (Array.isArray(value)) return `[${value.map(canonicalJson).join(",")}]`;
      const obj = value as Record<string, unknown>;
      // Code-point order == UTF-16 order for the ASCII keys used here; Python sorts by code point.
      const keys = Object.keys(obj).sort();
      return `{${keys.map((k) => `${JSON.stringify(k)}:${canonicalJson(obj[k])}`).join(",")}}`;
    }
    default:
      throw new Error("canonical_json: unsupported type");
  }
}

/** The exact bytes that get signed: domain prefix + canonical JSON. */
export function leaseMessage(lease: Lease): Uint8Array {
  return encoder.encode(LEASE_DOMAIN_PREFIX + canonicalJson(lease));
}

function assertLeaseShape(lease: Lease): void {
  const keys = Object.keys(lease).sort();
  if (keys.length !== LEASE_KEYS.length || !keys.every((k, i) => k === LEASE_KEYS[i])) {
    throw new Error("lease: unexpected key set");
  }
}

/**
 * Low-level signer. REFUSES any message that does not start with the domain prefix,
 * so this key can never be used to sign anything but a lease.
 */
export async function signDomainMessage(key: CryptoKey, message: Uint8Array): Promise<Uint8Array> {
  const prefix = encoder.encode(LEASE_DOMAIN_PREFIX);
  if (message.length <= prefix.length || !prefix.every((b, i) => message[i] === b)) {
    throw new Error("lease: refusing to sign a message without the domain prefix");
  }
  return new Uint8Array(await crypto.subtle.sign({ name: "Ed25519" }, key, message));
}

export async function signLease(key: CryptoKey, lease: Lease): Promise<SignedLease> {
  assertLeaseShape(lease);
  const signature = await signDomainMessage(key, leaseMessage(lease));
  return { lease, signature: toBase64(signature) };
}

/**
 * Import a PKCS#8 Ed25519 private key given as base64 DER or PEM. Returns null when
 * the value is missing, malformed or not an Ed25519 key.
 */
export async function importSigningKey(text: string | undefined): Promise<CryptoKey | null> {
  if (typeof text !== "string" || text.trim().length === 0) return null;
  const body = text
    .replace(/-----BEGIN [A-Z ]+-----/g, "")
    .replace(/-----END [A-Z ]+-----/g, "")
    .replace(/\s+/g, "");
  const der = fromBase64(body);
  if (der === null || der.length < 16) return null;
  try {
    const key = await crypto.subtle.importKey("pkcs8", der, { name: "Ed25519" }, false, ["sign"]);
    // Some runtimes accept a PKCS#8 key of another type here; a probe signature must be exactly 64 bytes.
    const probe = await signDomainMessage(key, encoder.encode(LEASE_DOMAIN_PREFIX + "{}"));
    return probe.length === 64 ? key : null;
  } catch {
    return null;
  }
}

export function buildLease(args: {
  kid: string;
  leaseId: string;
  deviceId: string;
  capabilities: string[];
  nowS: number;
  policyVersion: number;
}): Lease {
  return {
    schema: 1,
    kid: args.kid,
    lease_id: args.leaseId,
    sub: args.deviceId,
    capabilities: [...args.capabilities].sort(),
    issued_at: args.nowS,
    refresh_after: args.nowS + LEASE_REFRESH_AFTER_S,
    expires_at: args.nowS + LEASE_LIFETIME_S,
    policy_version: args.policyVersion,
  };
}
