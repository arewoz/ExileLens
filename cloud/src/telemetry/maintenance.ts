/**
 * Scheduled maintenance: (1) aggregate yesterday into metrics_daily, then
 * (2) delete data past retention. Aggregation ALWAYS runs before deletion.
 *
 * Free-plan budget: a Worker invocation may issue at most 50 D1 queries, so the
 * whole run is capped by `maxQueries` (default 45). Deletes are bounded
 * (2000 rows per statement, at most 25 rounds) and round-robin across tables so
 * every table makes progress each run; leftovers are picked up by the next run.
 */
import { schema } from "../contract";
import type { TelemetryEnv } from "../env";
import { utcDay } from "../http";

const DAY_MS = 86_400_000;
export const DELETE_CHUNK = 2000;
export const MAX_ROUNDS = 25;
export const DEFAULT_MAX_QUERIES = 45;

const INS = "INSERT OR REPLACE INTO metrics_daily (day, metric, dim, value)";
const BUCKETS = "FROM telemetry_events e, json_each(e.props, '$.buckets') b";

/** All aggregates for one UTC day (?1). Idempotent: INSERT OR REPLACE on the primary key. */
export const AGGREGATE_SQL: readonly string[] = [
  `${INS} SELECT ?1, 'active_installs', '', COUNT(*) FROM telemetry_install_days WHERE day = ?1`,
  `${INS} SELECT ?1, 'new_installs', '', COUNT(*) FROM telemetry_installs WHERE first_day = ?1`,
  `${INS} SELECT ?1, 'app_version_active', app_version, COUNT(*) FROM telemetry_install_days
     WHERE day = ?1 GROUP BY app_version`,
  `${INS} SELECT ?1, 'events_by_name', event, COUNT(*) FROM telemetry_events WHERE day = ?1 GROUP BY event`,
  `${INS} SELECT ?1, 'item_checks_by_verdict', json_extract(b.value, '$.verdict'), SUM(json_extract(b.value, '$.n'))
     ${BUCKETS} WHERE e.day = ?1 AND e.event = 'item_checks_summary' GROUP BY json_extract(b.value, '$.verdict')`,
  `${INS} SELECT ?1, 'item_checks_total', '', COALESCE(SUM(json_extract(b.value, '$.n')), 0)
     ${BUCKETS} WHERE e.day = ?1 AND e.event = 'item_checks_summary'`,
  `${INS} SELECT ?1, 'item_check_active_installs', '', COUNT(DISTINCT install_hash)
     FROM telemetry_events WHERE day = ?1 AND event = 'item_checks_summary'`,
  `${INS} SELECT ?1, 'analyze_build_active_installs', '', COUNT(DISTINCT install_hash)
     FROM telemetry_events WHERE day = ?1 AND event = 'analyze_build_completed'`,
  `${INS} SELECT ?1, 'unexpected_session_end', '', COUNT(*) FROM telemetry_events
     WHERE day = ?1 AND event = 'app_started' AND json_extract(props, '$.previous_session') = 'unexpected'`,
  `${INS} SELECT ?1, 'clean_session_end', '', COUNT(*) FROM telemetry_events
     WHERE day = ?1 AND event = 'app_started' AND json_extract(props, '$.previous_session') = 'clean'`,
  `${INS} SELECT ?1, 'analyze_build_by_outcome', json_extract(props, '$.outcome'), COUNT(*) FROM telemetry_events
     WHERE day = ?1 AND event = 'analyze_build_completed' GROUP BY json_extract(props, '$.outcome')`,
  `${INS} SELECT ?1, 'update_install_by_outcome', json_extract(props, '$.outcome'), COUNT(*) FROM telemetry_events
     WHERE day = ?1 AND event = 'update_install_completed' GROUP BY json_extract(props, '$.outcome')`,
  `${INS} SELECT ?1, 'update_download_by_outcome', json_extract(props, '$.outcome'), COUNT(*) FROM telemetry_events
     WHERE day = ?1 AND event = 'update_download_completed' GROUP BY json_extract(props, '$.outcome')`,
];

/** UTC day string `days` days before `nowMs`. */
export function daysAgo(nowMs: number, days: number): string {
  return utcDay(nowMs - days * DAY_MS);
}

/** UTC day string `months` calendar months before `nowMs` (day-of-month clamped). */
export function monthsAgo(nowMs: number, months: number): string {
  const d = new Date(nowMs);
  const y = d.getUTCFullYear();
  const m = d.getUTCMonth() - months;
  const daysInTarget = new Date(Date.UTC(y, m + 1, 0)).getUTCDate();
  return utcDay(Date.UTC(y, m, Math.min(d.getUTCDate(), daysInTarget)));
}

interface RetentionRule {
  table: string;
  column: string;
  cutoff: (nowMs: number) => string;
}

/** Rows whose `column` is strictly older than `cutoff` are deleted. */
export function retentionRules(): RetentionRule[] {
  const r = schema.retention;
  return [
    { table: "ingest_batches", column: "day", cutoff: (n) => daysAgo(n, 7) },
    { table: "telemetry_events", column: "day", cutoff: (n) => daysAgo(n, r.raw_events_days) },
    { table: "telemetry_install_days", column: "day", cutoff: (n) => daysAgo(n, r.install_activity_days) },
    { table: "telemetry_installs", column: "last_day", cutoff: (n) => monthsAgo(n, r.aggregates_months) },
    { table: "metrics_daily", column: "day", cutoff: (n) => monthsAgo(n, r.aggregates_months) },
    { table: "error_group_installs", column: "day", cutoff: (n) => daysAgo(n, r.error_install_links_days) },
    { table: "error_group_days", column: "day", cutoff: (n) => monthsAgo(n, r.aggregates_months) },
    { table: "error_groups", column: "last_seen_day", cutoff: (n) => monthsAgo(n, r.error_groups_months) },
    { table: "error_installs", column: "last_day", cutoff: (n) => monthsAgo(n, r.aggregates_months) },
  ];
}

export interface MaintenanceOptions {
  /** Aggregate yesterday (default true). */
  aggregate?: boolean;
  /** Apply retention (default true). */
  retention?: boolean;
  /** D1 query budget for the whole run (Free plan: 50 per invocation). */
  maxQueries?: number;
}

export interface MaintenanceResult {
  aggregatedDay: string | null;
  deleted: Record<string, number>;
  queries: number;
}

export async function runMaintenance(
  env: TelemetryEnv,
  nowMs: number,
  options: MaintenanceOptions = {},
): Promise<MaintenanceResult> {
  const db = env.TELEMETRY_DB;
  const maxQueries = options.maxQueries ?? DEFAULT_MAX_QUERIES;
  const result: MaintenanceResult = { aggregatedDay: null, deleted: {}, queries: 0 };

  if (options.aggregate !== false) {
    const day = utcDay(nowMs - DAY_MS);
    await db.batch(AGGREGATE_SQL.map((sql) => db.prepare(sql).bind(day)));
    result.queries += AGGREGATE_SQL.length;
    result.aggregatedDay = day;
  }

  if (options.retention !== false) {
    const rules = retentionRules();
    const active = new Set(rules.map((r) => r.table));
    for (let round = 0; round < MAX_ROUNDS && active.size > 0; round++) {
      for (const rule of rules) {
        if (!active.has(rule.table)) continue;
        // Aggregation (if any) is already done; the first round may use the whole budget.
        if (result.queries >= maxQueries) return result;
        const res = await db
          .prepare(
            `DELETE FROM ${rule.table} WHERE rowid IN
               (SELECT rowid FROM ${rule.table} WHERE ${rule.column} < ?1 LIMIT ${DELETE_CHUNK})`,
          )
          .bind(rule.cutoff(nowMs))
          .run();
        result.queries += 1;
        const changes = res.meta.changes ?? 0;
        result.deleted[rule.table] = (result.deleted[rule.table] ?? 0) + changes;
        if (changes < DELETE_CHUNK) active.delete(rule.table);
      }
    }
  }
  return result;
}

/**
 * Scheduled entry point. The heavy job (aggregate + retention) runs at 03:xx UTC;
 * other hours only run a small retention pass so backlogs drain without a big
 * burst. Never throws: a failed run is simply retried by the next trigger.
 */
export async function runScheduled(env: TelemetryEnv, scheduledTimeMs: number): Promise<void> {
  const heavy = new Date(scheduledTimeMs).getUTCHours() === 3;
  const started = Date.now();
  try {
    const res = await runMaintenance(env, scheduledTimeMs, heavy ? {} : { aggregate: false, maxQueries: 20 });
    console.log(
      JSON.stringify({ route: "scheduled", status: 200, ms: Date.now() - started, code: heavy ? "heavy" : "light", queries: res.queries }),
    );
  } catch {
    console.log(JSON.stringify({ route: "scheduled", status: 500, ms: Date.now() - started, code: "maintenance_failed" }));
  }
}
