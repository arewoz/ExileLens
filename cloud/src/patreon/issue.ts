import type { PatreonConfig } from "./config";
import { randomId } from "./crypto";
import { buildLease, signLease, type SignedLease } from "./lease";

/** Build and sign one lease for `deviceId` (policy_version comes from the active policy). */
export async function issueLease(
  cfg: PatreonConfig,
  deviceId: string,
  capabilities: string[],
  nowS: number,
): Promise<SignedLease> {
  const lease = buildLease({
    kid: cfg.kid,
    leaseId: randomId(),
    deviceId,
    capabilities,
    nowS,
    policyVersion: cfg.policy.policy_version,
  });
  return signLease(cfg.signKey, lease);
}

/** Parse the stored JSON capability array defensively (anything unexpected -> no capabilities). */
export function parseCapabilities(stored: string | null | undefined): string[] {
  try {
    const v: unknown = JSON.parse(stored ?? "[]");
    if (!Array.isArray(v)) return [];
    return v.filter((c): c is string => typeof c === "string" && /^[a-z][a-z0-9_]{0,31}$/.test(c)).sort();
  } catch {
    return [];
  }
}
