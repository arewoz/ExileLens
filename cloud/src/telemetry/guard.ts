/**
 * Shared request prelude for telemetry/error endpoints: kill switch, coarse
 * outer rate limit (optional binding), content-type, size cap, JSON parse.
 * Receives ONLY the narrowed TelemetryEnv.
 */
import type { TelemetryEnv } from "../env";
import { failure, readJsonBody, unavailable } from "../http";

export type Prelude = { ok: true; body: unknown } | { ok: false; response: Response };

const MIN_PEPPER_LENGTH = 16;

export function pepperConfigured(env: TelemetryEnv): boolean {
  return (
    typeof env.ANALYTICS_PEPPER === "string" &&
    env.ANALYTICS_PEPPER.length >= MIN_PEPPER_LENGTH &&
    typeof env.DIAGNOSTIC_PEPPER === "string" &&
    env.DIAGNOSTIC_PEPPER.length >= MIN_PEPPER_LENGTH
  );
}

export async function requestPrelude(
  env: TelemetryEnv,
  request: Request,
  options: { respectKillSwitch: boolean },
): Promise<Prelude> {
  if (options.respectKillSwitch && env.INGEST_ENABLED === "false") {
    return { ok: false, response: unavailable("ingest_disabled") };
  }
  if (!pepperConfigured(env)) {
    return { ok: false, response: unavailable("not_configured") };
  }
  if (env.RL_INGEST) {
    // Coarse outer guard only. The key is never stored; an outage of the limiter fails open.
    const key = request.headers.get("cf-connecting-ip") ?? "unknown";
    let allowed = true;
    try {
      allowed = (await env.RL_INGEST.limit({ key })).success;
    } catch {
      allowed = true;
    }
    if (!allowed) return { ok: false, response: failure(429, "rate_limited", { "retry-after": "60" }) };
  }
  const parsed = await readJsonBody(request);
  if (!parsed.ok) return { ok: false, response: parsed.response };
  return { ok: true, body: parsed.value };
}

/** Batch-level reject codes: 422 for schema_unsupported, 400 for everything else. */
export function batchFailure(code: string): Response {
  return failure(code === "schema_unsupported" ? 422 : 400, code);
}
