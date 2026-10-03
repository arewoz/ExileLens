/**
 * Crypto helpers for the Patreon side: random ids/tokens, SHA-256, keyed user hash,
 * constant-time comparison and AES-256-GCM token encryption.
 *
 * Nothing here logs. Key material and plaintext never leave the functions that use them.
 */

const encoder = new TextEncoder();

export function toHex(bytes: ArrayBuffer | Uint8Array): string {
  const view = bytes instanceof Uint8Array ? bytes : new Uint8Array(bytes);
  return Array.from(view, (b) => b.toString(16).padStart(2, "0")).join("");
}

export function toBase64(bytes: Uint8Array): string {
  let bin = "";
  for (const b of bytes) bin += String.fromCharCode(b);
  return btoa(bin);
}

/** Strict-ish base64 (standard alphabet, padding optional) -> bytes; null when malformed. */
export function fromBase64(text: string): Uint8Array | null {
  const clean = text.replace(/\s+/g, "");
  if (!/^[A-Za-z0-9+/]*={0,2}$/.test(clean)) return null;
  try {
    const bin = atob(clean);
    const out = new Uint8Array(bin.length);
    for (let i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i);
    return out;
  } catch {
    return null;
  }
}

export function toBase64Url(bytes: Uint8Array): string {
  return toBase64(bytes).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

export function randomBytes(n: number): Uint8Array {
  const out = new Uint8Array(n);
  crypto.getRandomValues(out);
  return out;
}

/** 16 random bytes as 32 hex chars (session ids, device ids, lease ids, link ids). */
export function randomId(): string {
  return toHex(randomBytes(16));
}

/** 32 random bytes, base64url (43 chars): poll tokens, OAuth state, device tokens. */
export function randomToken(): string {
  return toBase64Url(randomBytes(32));
}

export async function sha256Hex(text: string): Promise<string> {
  return toHex(await crypto.subtle.digest("SHA-256", encoder.encode(text)));
}

/** HMAC-SHA256(pepper, "patreon:" + patreonUserId) as lowercase hex. */
export async function userHmac(pepper: string, patreonUserId: string): Promise<string> {
  const key = await crypto.subtle.importKey("raw", encoder.encode(pepper), { name: "HMAC", hash: "SHA-256" }, false, ["sign"]);
  return toHex(await crypto.subtle.sign("HMAC", key, encoder.encode(`patreon:${patreonUserId}`)));
}

/** Constant-time equality for two strings of any length (length difference is not secret here: hex digests). */
export function timingSafeEqualStrings(a: string, b: string): boolean {
  const x = encoder.encode(a);
  const y = encoder.encode(b);
  let diff = x.length ^ y.length;
  const len = Math.max(x.length, y.length);
  for (let i = 0; i < len; i++) diff |= (x[i] ?? 0) ^ (y[i] ?? 0);
  return diff === 0;
}

/** Import the 32-byte AES-256-GCM key from base64; null when it is not exactly 32 bytes. */
export async function importEncryptionKey(base64Key: string): Promise<CryptoKey | null> {
  const raw = fromBase64(base64Key.trim());
  if (raw === null || raw.length !== 32) return null;
  return crypto.subtle.importKey("raw", raw, { name: "AES-GCM" }, false, ["encrypt", "decrypt"]);
}

/** AES-256-GCM, random 12-byte IV, AAD = link id. Output: base64(iv || ciphertext+tag). */
export async function encryptToken(key: CryptoKey, plaintext: string, aad: string): Promise<string> {
  const iv = randomBytes(12);
  const ct = new Uint8Array(
    await crypto.subtle.encrypt({ name: "AES-GCM", iv, additionalData: encoder.encode(aad) }, key, encoder.encode(plaintext)),
  );
  const out = new Uint8Array(iv.length + ct.length);
  out.set(iv, 0);
  out.set(ct, iv.length);
  return toBase64(out);
}

/** Inverse of encryptToken. Throws on any tampering, wrong key or wrong AAD. */
export async function decryptToken(key: CryptoKey, stored: string, aad: string): Promise<string> {
  const bytes = fromBase64(stored);
  if (bytes === null || bytes.length < 12 + 16) throw new Error("bad_ciphertext");
  const iv = bytes.slice(0, 12);
  const ct = bytes.slice(12);
  const pt = await crypto.subtle.decrypt({ name: "AES-GCM", iv, additionalData: encoder.encode(aad) }, key, ct);
  return new TextDecoder().decode(pt);
}
