/**
 * Scheduled retention for PATREON_DB. Runs from its own cron trigger so that this work and the
 * usage-statistics job never share one invocation (Workers Free: 50 D1 queries per invocation).
 * The whole run is capped at `maxQueries` (default 20) with bounded, chunked deletes.
 *
 * Retention: link sessions 24 h after expiry; devices idle > 60 days; links without any device
 * (and not awaiting their first poll); both metric tables 13 months.
 */
import type { PatreonEnv } from "../env";
import { utcDay } from "../http";

export const PATREON_CRON = "47 */6 * * *";
export const DEFAULT_PATREON_MAX_QUERIES = 20;
export const PATREON_DELETE_CHUNK = 2000;

const DAY_S = 86_400;
const SESSION_RETENTION_AFTER_EXPIRY_S = DAY_S;
const DEVICE_IDLE_S = 60 * DAY_S;
const METRICS_MONTHS = 13;
/** Rounds per table; 5 + 5 + 5 + 2 + 2 = 19 queries in the worst case. */
const ROUNDS = { sessions: 5, devices: 5, links: 5, linkMetrics: 2, refreshMetrics: 2 } as const;

/** UTC day string `months` calendar months before `nowMs` (day-of-month clamped). */
export function monthsAgoDay(nowMs: number, months: number): string {
  const d = new Date(nowMs);
  const y = d.getUTCFullYear();
  const m = d.getUTCMonth() - months;
  const daysInTarget = new Date(Date.UTC(y, m + 1, 0)).getUTCDate();
  return utcDay(Date.UTC(y, m, Math.min(d.getUTCDate(), daysInTarget)));
}

export interface PatreonMaintenanceResult {
  queries: number;
  deleted: Record<string, number>;
}

export async function runPatreonMaintenance(
  env: PatreonEnv,
  nowMs: number,
  options: { maxQueries?: number } = {},
): Promise<PatreonMaintenanceResult> {
  const result: PatreonMaintenanceResult = { queries: 0, deleted: {} };
  const db = env.PATREON_DB;
  if (!db) return result;
  const maxQueries = options.maxQueries ?? DEFAULT_PATREON_MAX_QUERIES;
  const nowS = Math.floor(nowMs / 1000);
  const metricsCutoff = monthsAgoDay(nowMs, METRICS_MONTHS);

  const steps: { name: string; rounds: number; sql: string; param: string | number }[] = [
    {
      name: "link_sessions",
      rounds: ROUNDS.sessions,
      sql: `DELETE FROM link_sessions WHERE rowid IN (SELECT rowid FROM link_sessions WHERE expires_at < ?1 LIMIT ${PATREON_DELETE_CHUNK})`,
      param: nowS - SESSION_RETENTION_AFTER_EXPIRY_S,
    },
    {
      name: "devices",
      rounds: ROUNDS.devices,
      sql: `DELETE FROM devices WHERE rowid IN
              (SELECT rowid FROM devices WHERE COALESCE(last_refresh_at, created_at) < ?1 LIMIT ${PATREON_DELETE_CHUNK})`,
      param: nowS - DEVICE_IDLE_S,
    },
    {
      // Orphans: no device, and not a finished session that is still waiting for its first poll.
      name: "patreon_links",
      rounds: ROUNDS.links,
      sql: `DELETE FROM patreon_links WHERE rowid IN
              (SELECT l.rowid FROM patreon_links l
               WHERE NOT EXISTS (SELECT 1 FROM devices d WHERE d.link_id = l.link_id)
                 AND NOT EXISTS (SELECT 1 FROM link_sessions s
                                 WHERE s.link_id = l.link_id AND s.consumed = 0 AND s.status IN ('linked', 'not_entitled') AND s.expires_at >= ?1 - ${DAY_S})
                 AND l.created_at < ?1
               LIMIT ${PATREON_DELETE_CHUNK})`,
      param: nowS - 3600,
    },
    {
      name: "link_metrics_daily",
      rounds: ROUNDS.linkMetrics,
      sql: `DELETE FROM link_metrics_daily WHERE rowid IN (SELECT rowid FROM link_metrics_daily WHERE day < ?1 LIMIT ${PATREON_DELETE_CHUNK})`,
      param: metricsCutoff,
    },
    {
      name: "entitlement_refresh_daily",
      rounds: ROUNDS.refreshMetrics,
      sql: `DELETE FROM entitlement_refresh_daily WHERE rowid IN (SELECT rowid FROM entitlement_refresh_daily WHERE day < ?1 LIMIT ${PATREON_DELETE_CHUNK})`,
      param: metricsCutoff,
    },
  ];

  for (const step of steps) {
    for (let round = 0; round < step.rounds; round++) {
      if (result.queries >= maxQueries) return result;
      const res = await db.prepare(step.sql).bind(step.param).run();
      result.queries += 1;
      const changes = res.meta.changes ?? 0;
      result.deleted[step.name] = (result.deleted[step.name] ?? 0) + changes;
      if (changes < PATREON_DELETE_CHUNK) break;
    }
  }
  return result;
}

/** Scheduled entry point for the Patreon cron. Never throws; logs only counts. */
export async function runPatreonScheduled(env: PatreonEnv, scheduledTimeMs: number): Promise<void> {
  const started = Date.now();
  try {
    const res = await runPatreonMaintenance(env, scheduledTimeMs);
    console.log(JSON.stringify({ route: "scheduled", status: 200, ms: Date.now() - started, code: "patreon", queries: res.queries }));
  } catch {
    console.log(JSON.stringify({ route: "scheduled", status: 500, ms: Date.now() - started, code: "patreon_maintenance_failed" }));
  }
}
