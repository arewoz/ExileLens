/**
 * HTTP helpers: JSON responses, bounded body reading, Retry-After helpers,
 * D1 error mapping and operational logging.
 *
 * Operational logs are NOT product telemetry: they carry only route, status,
 * duration and a reason code. Never request bodies, ids, hashes or IPs.
 */

export const MAX_BODY_BYTES = 32768;
export const STORAGE_RETRY_AFTER_SECONDS = 3600;

const BASE_HEADERS: Record<string, string> = {
  "content-type": "application/json; charset=utf-8",
  "cache-control": "no-store",
  "x-content-type-options": "nosniff",
};

/** Thrown when D1 is unavailable or out of quota. Mapped to 503 by the router. */
export class StorageUnavailable extends Error {
  constructor() {
    super("storage_unavailable");
    this.name = "StorageUnavailable";
  }
}

export function json(status: number, body: unknown, extraHeaders?: Record<string, string>): Response {
  return new Response(JSON.stringify(body), { status, headers: { ...BASE_HEADERS, ...extraHeaders } });
}

export function noContent(): Response {
  return new Response(null, { status: 204, headers: { "cache-control": "no-store" } });
}

export function failure(status: number, code: string, extraHeaders?: Record<string, string>): Response {
  return json(status, { ok: false, code }, extraHeaders);
}

/** 503 with Retry-After: 3600 (storage quota exhausted, kill switch, misconfiguration). */
export function unavailable(code: string): Response {
  return failure(503, code, { "retry-after": String(STORAGE_RETRY_AFTER_SECONDS) });
}

export function utcDay(ms: number): string {
  return new Date(ms).toISOString().slice(0, 10);
}

/** Whole seconds from `nowMs` until the next 00:00 UTC (at least 1). */
export function secondsUntilNextUtcMidnight(nowMs: number): number {
  const d = new Date(nowMs);
  const next = Date.UTC(d.getUTCFullYear(), d.getUTCMonth(), d.getUTCDate() + 1);
  return Math.max(1, Math.ceil((next - nowMs) / 1000));
}

/** Run a D1 operation; any failure becomes StorageUnavailable (never an unhandled error). */
export async function guardDb<T>(op: () => Promise<T>): Promise<T> {
  try {
    return await op();
  } catch {
    throw new StorageUnavailable();
  }
}

/** Case-insensitive media type check, ignoring parameters such as charset. */
export function isJsonContentType(header: string | null): boolean {
  if (header === null) return false;
  return (header.split(";")[0] ?? "").trim().toLowerCase() === "application/json";
}

export type BodyResult = { ok: true; value: unknown } | { ok: false; response: Response };

/**
 * Read and parse a JSON body with a hard byte cap enforced WHILE reading
 * (Content-Length is only an early hint). 415 / 413 / 400 on failure.
 */
export async function readJsonBody(request: Request, maxBytes = MAX_BODY_BYTES): Promise<BodyResult> {
  if (!isJsonContentType(request.headers.get("content-type"))) {
    return { ok: false, response: failure(415, "unsupported_media_type") };
  }
  const declared = request.headers.get("content-length");
  if (declared !== null) {
    if (!/^[0-9]+$/.test(declared)) return { ok: false, response: failure(400, "invalid_content_length") };
    if (Number(declared) > maxBytes) return { ok: false, response: failure(413, "payload_too_large") };
  }
  if (request.body === null) return { ok: false, response: failure(400, "invalid_json") };

  const reader = request.body.getReader();
  const chunks: Uint8Array[] = [];
  let total = 0;
  for (;;) {
    let step: ReadableStreamReadResult<Uint8Array>;
    try {
      step = await reader.read();
    } catch {
      return { ok: false, response: failure(400, "invalid_json") };
    }
    if (step.done) break;
    total += step.value.byteLength;
    if (total > maxBytes) {
      reader.cancel().catch(() => undefined);
      return { ok: false, response: failure(413, "payload_too_large") };
    }
    chunks.push(step.value);
  }
  const bytes = new Uint8Array(total);
  let offset = 0;
  for (const chunk of chunks) {
    bytes.set(chunk, offset);
    offset += chunk.byteLength;
  }
  try {
    const text = new TextDecoder("utf-8", { fatal: true, ignoreBOM: false }).decode(bytes);
    return { ok: true, value: JSON.parse(text) };
  } catch {
    return { ok: false, response: failure(400, "invalid_json") };
  }
}

export interface OpsLogEntry {
  route: string;
  status: number;
  ms: number;
  code?: string;
}

/** Operational log line: route / status / duration / reason code only. */
export function opsLog(entry: OpsLogEntry): void {
  console.log(JSON.stringify(entry));
}

/** Read the reason code out of one of our JSON error responses without consuming it. */
export async function reasonCode(response: Response): Promise<string | undefined> {
  if (response.status < 400 || response.status === 204) return undefined;
  try {
    const parsed = (await response.clone().json()) as { code?: unknown };
    return typeof parsed.code === "string" ? parsed.code : undefined;
  } catch {
    return undefined;
  }
}
