/**
 * Keyed hashing. The server never stores a raw client UUID: it stores
 * HMAC-SHA256(pepper, "<domain>:" + uuid) as lowercase hex. Usage and error
 * data use different peppers AND different domain prefixes, so the two hashes
 * of one UUID can never be correlated.
 */

export type HashDomain = "analytics" | "diagnostic";

const encoder = new TextEncoder();

function toHex(buf: ArrayBuffer): string {
  return Array.from(new Uint8Array(buf), (b) => b.toString(16).padStart(2, "0")).join("");
}

export async function hmacHex(pepper: string, domain: HashDomain, uuid: string): Promise<string> {
  const key = await crypto.subtle.importKey(
    "raw",
    encoder.encode(pepper),
    { name: "HMAC", hash: "SHA-256" },
    false,
    ["sign"],
  );
  const sig = await crypto.subtle.sign("HMAC", key, encoder.encode(`${domain}:${uuid}`));
  return toHex(sig);
}

export async function sha256Hex(text: string): Promise<string> {
  return toHex(await crypto.subtle.digest("SHA-256", encoder.encode(text)));
}
