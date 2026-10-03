/**
 * POST /v1/telemetry/batch - opt-in usage statistics ingest.
 *
 * D1 Free keeps us honest: at most 50 queries per invocation and 100 bound
 * parameters per query, so events are written with ONE INSERT ... SELECT over
 * json_each() instead of one statement per event.
 */
import { schema, validateBatch } from "../contract";
import type { TelemetryEnv } from "../env";
import { failure, guardDb, json, secondsUntilNextUtcMidnight, utcDay } from "../http";
import { hmacHex } from "./hash";
import { batchFailure, requestPrelude } from "./guard";
import { writeBatchAtomic } from "./store";

interface UsageBody {
  batch_id: string;
  analytics_id: string;
  app: { version: string };
  events: { name: string; t: string; props: Record<string, unknown> }[];
}

const SQL_PRECHECK = `SELECT
  (SELECT 1 FROM ingest_batches WHERE batch_id = ?1 AND kind = 'usage') AS dup,
  (SELECT events_accepted FROM telemetry_install_days WHERE install_hash = ?2 AND day = ?3) AS used`;

const SQL_BATCH_ROW = `INSERT INTO ingest_batches (batch_id, kind, day) VALUES (?1, 'usage', ?2)`;

const SQL_EVENTS = `INSERT INTO telemetry_events (install_hash, day, hour, event, app_version, props)
SELECT ?1, substr(json_extract(value, '$.t'), 1, 10), json_extract(value, '$.t'),
       json_extract(value, '$.name'), ?2, json_extract(value, '$.props')
FROM json_each(?3)`;

const SQL_INSTALL = `INSERT INTO telemetry_installs (install_hash, first_day, last_day, first_version, last_version)
VALUES (?1, ?2, ?2, ?3, ?3)
ON CONFLICT (install_hash) DO UPDATE SET last_day = excluded.last_day, last_version = excluded.last_version`;

const SQL_INSTALL_DAY = `INSERT INTO telemetry_install_days (install_hash, day, app_version, events_accepted)
VALUES (?1, ?2, ?3, ?4)
ON CONFLICT (install_hash, day) DO UPDATE SET
  events_accepted = events_accepted + excluded.events_accepted, app_version = excluded.app_version`;

export async function handleUsageBatch(env: TelemetryEnv, request: Request, nowMs: number): Promise<Response> {
  const pre = await requestPrelude(env, request, { respectKillSwitch: true });
  if (!pre.ok) return pre.response;

  const result = validateBatch("usage", pre.body, nowMs);
  if (result.batchCode !== "ok") return batchFailure(result.batchCode);

  const body = pre.body as UsageBody;
  const accepted = result.accepted.length;
  // Rejected events are never stored. Nothing to write when nothing was accepted.
  if (accepted === 0) return json(202, { ok: true, accepted: 0, rejected: result.rejected });

  const db = env.TELEMETRY_DB;
  const today = utcDay(nowMs);
  const installHash = await hmacHex(env.ANALYTICS_PEPPER, "analytics", body.analytics_id);

  const state = await guardDb(() =>
    db.prepare(SQL_PRECHECK).bind(body.batch_id, installHash, today).first<{ dup: number | null; used: number | null }>(),
  );
  if (state?.dup) return json(200, { ok: true, duplicate: true });

  const cap = schema.limits.usage_daily_events_per_install as number;
  if ((state?.used ?? 0) + accepted > cap) {
    return failure(429, "daily_cap", { "retry-after": String(secondsUntilNextUtcMidnight(nowMs)) });
  }

  const rows = result.accepted.map((i) => {
    const e = body.events[i] as UsageBody["events"][number];
    return { name: e.name, t: e.t, props: e.props };
  });
  const version = body.app.version;

  const outcome = await writeBatchAtomic(db, "usage", body.batch_id, [
    db.prepare(SQL_BATCH_ROW).bind(body.batch_id, today),
    db.prepare(SQL_EVENTS).bind(installHash, version, JSON.stringify(rows)),
    db.prepare(SQL_INSTALL).bind(installHash, today, version),
    db.prepare(SQL_INSTALL_DAY).bind(installHash, today, version, accepted),
  ]);
  if (outcome === "duplicate") return json(200, { ok: true, duplicate: true });
  return json(202, { ok: true, accepted, rejected: result.rejected });
}
