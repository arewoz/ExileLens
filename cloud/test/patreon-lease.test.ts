import { env as bindings } from "cloudflare:workers";
import { describe, expect, it } from "vitest";
import vector from "../contract/lease_vector.json";
import {
  LEASE_DOMAIN_PREFIX,
  buildLease,
  canonicalJson,
  importSigningKey,
  leaseMessage,
  signDomainMessage,
  signLease,
  type Lease,
} from "../src/patreon/lease";
import { fromBase64 } from "../src/patreon/crypto";
import { TEST_PUBLIC_KEY_B64 } from "./patreon-helpers";

const encoder = new TextEncoder();

const FIXED_LEASE: Lease = {
  schema: 1,
  kid: "exilelens-entitlement-test-1",
  lease_id: "fedcba9876543210fedcba9876543210",
  sub: "0123456789abcdef0123456789abcdef",
  capabilities: ["seamless_updates"],
  issued_at: 1790000000,
  refresh_after: 1790086400,
  expires_at: 1790604800,
  policy_version: 1,
};

async function publicKey(): Promise<CryptoKey> {
  return crypto.subtle.importKey("raw", fromBase64(vector.public_key_b64)!, { name: "Ed25519" }, false, ["verify"]);
}

describe("canonical JSON", () => {
  it("sorts keys at every level, no whitespace, integers only", () => {
    expect(canonicalJson({ b: 1, a: { d: [3, { z: 1, y: 2 }], c: "x" } })).toBe('{"a":{"c":"x","d":[3,{"y":2,"z":1}]},"b":1}');
    expect(canonicalJson("é\n\"")).toBe('"é\\n\\""'); // JSON.stringify escaping, non-ASCII kept (ensure_ascii=False)
    expect(() => canonicalJson({ a: 1.5 })).toThrow();
    expect(() => canonicalJson({ a: undefined })).toThrow();
  });
});

describe("lease golden vector (cross-language)", () => {
  it("the committed vector uses the documented test key and fixed lease", () => {
    expect(vector.public_key_b64).toBe(TEST_PUBLIC_KEY_B64);
    expect(vector.kid).toBe("exilelens-entitlement-test-1");
    expect(vector.device_id).toBe("0123456789abcdef0123456789abcdef");
    expect(vector.lease).toEqual(FIXED_LEASE);
    expect(vector.domain_prefix).toBe(LEASE_DOMAIN_PREFIX);
    expect(vector.now.at_issue).toBe(FIXED_LEASE.issued_at);
    expect(vector.now.at_expiry).toBe(FIXED_LEASE.expires_at);
    expect(Object.keys(vector.lease).sort()).toEqual(
      ["capabilities", "expires_at", "issued_at", "kid", "lease_id", "policy_version", "refresh_after", "schema", "sub"],
    );
  });

  it("signing the fixed lease reproduces the committed signature byte for byte", async () => {
    const key = await importSigningKey(bindings.ENTITLEMENT_SIGNING_KEY);
    expect(key).not.toBeNull();
    const signed = await signLease(key!, FIXED_LEASE);
    expect(new TextDecoder().decode(leaseMessage(FIXED_LEASE))).toBe(LEASE_DOMAIN_PREFIX + vector.canonical_lease_json);
    expect(signed.signature).toBe(vector.signature);
    expect(signed.lease).toEqual(vector.lease);
    expect(fromBase64(signed.signature)!.length).toBe(64);
  });

  it("the signature verifies with crypto.subtle.verify over prefix + canonical JSON, and only that", async () => {
    const pub = await publicKey();
    const sig = fromBase64(vector.signature)!;
    const good = encoder.encode(LEASE_DOMAIN_PREFIX + canonicalJson(vector.lease));
    expect(await crypto.subtle.verify({ name: "Ed25519" }, pub, sig, good)).toBe(true);
    // no prefix, other prefix, modified lease: all fail
    expect(await crypto.subtle.verify({ name: "Ed25519" }, pub, sig, encoder.encode(canonicalJson(vector.lease)))).toBe(false);
    expect(await crypto.subtle.verify({ name: "Ed25519" }, pub, sig, encoder.encode("exilelens/other/v1\n" + canonicalJson(vector.lease)))).toBe(false);
    const changed = { ...vector.lease, expires_at: vector.lease.expires_at + 1 };
    expect(await crypto.subtle.verify({ name: "Ed25519" }, pub, sig, encoder.encode(LEASE_DOMAIN_PREFIX + canonicalJson(changed)))).toBe(false);
  });

  it("the signer refuses any message that lacks the domain prefix", async () => {
    const key = (await importSigningKey(bindings.ENTITLEMENT_SIGNING_KEY))!;
    await expect(signDomainMessage(key, encoder.encode(canonicalJson(FIXED_LEASE)))).rejects.toThrow(/domain prefix/);
    await expect(signDomainMessage(key, encoder.encode("exilelens/update/v1\n{}"))).rejects.toThrow(/domain prefix/);
    await expect(signDomainMessage(key, encoder.encode(LEASE_DOMAIN_PREFIX))).rejects.toThrow(); // prefix only, no payload
    await expect(signDomainMessage(key, new Uint8Array(0))).rejects.toThrow();
    await expect(signDomainMessage(key, encoder.encode(LEASE_DOMAIN_PREFIX + "{}"))).resolves.toHaveLength(64);
  });

  it("signLease refuses a lease with extra or missing keys (no URL / version / hash fields)", async () => {
    const key = (await importSigningKey(bindings.ENTITLEMENT_SIGNING_KEY))!;
    await expect(signLease(key, { ...FIXED_LEASE, url: "https://x.invalid/update.zip" } as unknown as Lease)).rejects.toThrow(/key set/);
    const { kid: _kid, ...missing } = FIXED_LEASE;
    await expect(signLease(key, missing as unknown as Lease)).rejects.toThrow(/key set/);
  });
});

describe("signing key import", () => {
  it("accepts base64 DER and PEM, rejects garbage and non-Ed25519 keys", async () => {
    const b64 = bindings.ENTITLEMENT_SIGNING_KEY;
    const pem = `-----BEGIN PRIVATE KEY-----\n${b64.match(/.{1,64}/g)!.join("\n")}\n-----END PRIVATE KEY-----\n`;
    for (const text of [b64, `  ${b64}\n`, pem]) {
      const key = await importSigningKey(text);
      expect(key).not.toBeNull();
      expect((await signLease(key!, FIXED_LEASE)).signature).toBe(vector.signature);
    }
    expect(await importSigningKey(undefined)).toBeNull();
    expect(await importSigningKey("")).toBeNull();
    expect(await importSigningKey("not base64 !!!")).toBeNull();
    expect(await importSigningKey("AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA")).toBeNull();
    const rsa = await crypto.subtle.generateKey({ name: "RSASSA-PKCS1-v1_5", modulusLength: 2048, publicExponent: new Uint8Array([1, 0, 1]), hash: "SHA-256" }, true, ["sign"]);
    const rsaDer = new Uint8Array((await crypto.subtle.exportKey("pkcs8", (rsa as CryptoKeyPair).privateKey)) as ArrayBuffer);
    expect(await importSigningKey(btoa(String.fromCharCode(...rsaDer)))).toBeNull();
  });
});

describe("buildLease", () => {
  it("has exactly nine keys, sorted capabilities and the 24 h / 7 d timings", () => {
    const l = buildLease({ kid: "k", leaseId: "a".repeat(32), deviceId: "b".repeat(32), capabilities: ["z_cap", "seamless_updates"], nowS: 1000, policyVersion: 3 });
    expect(Object.keys(l).sort()).toEqual(
      ["capabilities", "expires_at", "issued_at", "kid", "lease_id", "policy_version", "refresh_after", "schema", "sub"],
    );
    expect(l).toMatchObject({ schema: 1, capabilities: ["seamless_updates", "z_cap"], issued_at: 1000, refresh_after: 1000 + 86400, expires_at: 1000 + 604800, policy_version: 3 });
  });
});
