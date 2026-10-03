/**
 * POST /v1/errors/batch - opt-in structured error reports.
 *
 * Reports are grouped by a SERVER-computed fingerprint (any client value is
 * ignored): sha256(error_code | exception_type | first 5 "module:function"
 * frames). Line numbers are excluded so a code change does not split a group.
 */
import { schema, validateBatch } from "../contract";
import type { TelemetryEnv } from "../env";
import { failure, guardDb, json, secondsUntilNextUtcMidnight, utcDay } from "../http";
import { batchFailure, requestPrelude } from "./guard";
import { hmacHex, sha256Hex } from "./hash";
import { writeBatchAtomic } from "./store";

interface Frame {
  module: string;
  function?: string;
  line?: number;
}

interface Report {
  error_code: string;
  component: string;
  exception_type: string;
  frames: Frame[];
  count: number;
}

interface ErrorsBody {
  batch_id: string;
  diagnostic_id: string;
  app: { version: string };
  reports: Report[];
}

interface Group {
  fp: string;
  ec: string;
  comp: string;
  et: string;
  fr: string;
  occ: number;
}

const FINGERPRINT_FRAMES = 5;

export async function fingerprintOf(report: {
  error_code: string;
  exception_type: string;
  frames: { module: string; function?: string }[];
}): Promise<string> {
  const frames = report.frames
    .slice(0, FINGERPRINT_FRAMES)
    .map((f) => `${f.module}:${f.function ?? ""}`)
    .join(";");
  return sha256Hex(`${report.error_code}|${report.exception_type}|${frames}`);
}

const SQL_PRECHECK = `SELECT
  (SELECT 1 FROM ingest_batches WHERE batch_id = ?1 AND kind = 'errors') AS dup,
  (SELECT CASE WHEN reports_today_day = ?3 THEN reports_today ELSE 0 END
     FROM error_installs WHERE diag_hash = ?2) AS used`;

const SQL_BATCH_ROW = `INSERT INTO ingest_batches (batch_id, kind, day) VALUES (?1, 'errors', ?2)`;

const SQL_DIAG_INSTALL = `INSERT INTO error_installs (diag_hash, first_day, last_day, reports_today_day, reports_today)
VALUES (?1, ?2, ?2, ?2, ?3)
ON CONFLICT (diag_hash) DO UPDATE SET
  last_day = excluded.last_day,
  reports_today = CASE WHEN reports_today_day = excluded.reports_today_day
                       THEN reports_today + excluded.reports_today ELSE excluded.reports_today END,
  reports_today_day = excluded.reports_today_day`;

const SQL_GROUPS = `INSERT INTO error_groups
  (fingerprint, error_code, component, exception_type, frames, first_seen_day, last_seen_day,
   first_version, last_version, occurrences)
SELECT json_extract(value, '$.fp'), json_extract(value, '$.ec'), json_extract(value, '$.comp'),
       json_extract(value, '$.et'), json_extract(value, '$.fr'), ?2, ?2, ?3, ?3,
       json_extract(value, '$.occ')
FROM json_each(?1) WHERE true
ON CONFLICT (fingerprint) DO UPDATE SET
  frames = excluded.frames,
  first_seen_day = MIN(first_seen_day, excluded.first_seen_day),
  last_seen_day = MAX(last_seen_day, excluded.last_seen_day),
  last_version = excluded.last_version,
  occurrences = occurrences + excluded.occurrences`;

const SQL_GROUP_DAYS = `INSERT INTO error_group_days (fingerprint, day, app_version, occurrences)
SELECT json_extract(value, '$.fp'), ?2, ?3, json_extract(value, '$.occ')
FROM json_each(?1) WHERE true
ON CONFLICT (fingerprint, day, app_version) DO UPDATE SET occurrences = occurrences + excluded.occurrences`;

const SQL_GROUP_INSTALLS = `INSERT OR IGNORE INTO error_group_installs (fingerprint, diag_hash, day)
SELECT json_extract(value, '$.fp'), ?2, ?3 FROM json_each(?1)`;

export async function handleErrorBatch(env: TelemetryEnv, request: Request, nowMs: number): Promise<Response> {
  const pre = await requestPrelude(env, request, { respectKillSwitch: true });
  if (!pre.ok) return pre.response;

  const result = validateBatch("errors", pre.body, nowMs);
  if (result.batchCode !== "ok") return batchFailure(result.batchCode);

  const body = pre.body as ErrorsBody;
  const accepted = result.accepted.length;
  if (accepted === 0) return json(202, { ok: true, accepted: 0, rejected: result.rejected });

  const db = env.TELEMETRY_DB;
  const today = utcDay(nowMs);
  const diagHash = await hmacHex(env.DIAGNOSTIC_PEPPER, "diagnostic", body.diagnostic_id);

  const state = await guardDb(() =>
    db.prepare(SQL_PRECHECK).bind(body.batch_id, diagHash, today).first<{ dup: number | null; used: number | null }>(),
  );
  if (state?.dup) return json(200, { ok: true, duplicate: true });

  const cap = schema.limits.error_daily_reports_per_install as number;
  if ((state?.used ?? 0) + accepted > cap) {
    return failure(429, "daily_cap", { "retry-after": String(secondsUntilNextUtcMidnight(nowMs)) });
  }

  // Merge reports sharing a fingerprint so each group is touched once per request.
  const groups = new Map<string, Group>();
  for (const i of result.accepted) {
    const r = body.reports[i] as Report;
    const fp = await fingerprintOf(r);
    const existing = groups.get(fp);
    if (existing) {
      existing.occ += r.count;
      existing.fr = JSON.stringify(r.frames); // keep the latest frames (with line numbers)
    } else {
      groups.set(fp, {
        fp,
        ec: r.error_code,
        comp: r.component,
        et: r.exception_type,
        fr: JSON.stringify(r.frames),
        occ: r.count,
      });
    }
  }
  const groupsJson = JSON.stringify([...groups.values()]);
  const version = body.app.version;

  const outcome = await writeBatchAtomic(db, "errors", body.batch_id, [
    db.prepare(SQL_BATCH_ROW).bind(body.batch_id, today),
    db.prepare(SQL_DIAG_INSTALL).bind(diagHash, today, accepted),
    db.prepare(SQL_GROUPS).bind(groupsJson, today, version),
    db.prepare(SQL_GROUP_DAYS).bind(groupsJson, today, version),
    db.prepare(SQL_GROUP_INSTALLS).bind(groupsJson, diagHash, today),
  ]);
  if (outcome === "duplicate") return json(200, { ok: true, duplicate: true });
  return json(202, { ok: true, accepted, rejected: result.rejected });
}
