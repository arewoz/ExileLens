import { beforeEach, describe, expect, it, vi } from "vitest";
import { createHandler } from "../src/app";
import { schema } from "../src/contract";
import { telemetryEnv } from "../src/env";
import { DELETE_CHUNK, monthsAgo, runMaintenance } from "../src/telemetry/maintenance";
import { NOW, all, count, db, makeEnv, resetDb, send, usageBatch, usageEvent } from "./helpers";

beforeEach(resetDb);

const env = () => telemetryEnv(makeEnv());
const DAY = 86_400_000;
const D = "2026-10-02"; // "yesterday" relative to NOW

async function seedYesterday() {
  const ev = (hash: string, event: string, props: unknown, day = D) =>
    db
      .prepare(
        "INSERT INTO telemetry_events (install_hash, day, hour, event, app_version, props) VALUES (?1, ?2, ?3, ?4, '0.7.0', ?5)",
      )
      .bind(hash, day, `${day}T10:00Z`, event, JSON.stringify(props));
  const bucket = (verdict: string, n: number) => ({ verdict, confidence: "high", quality: "full", latency: "lt_1s", outcome: "ok", n });
  await db.batch([
    ev("h1", "app_started", { launch: "normal", previous_session: "unexpected", pob_configured: true }),
    ev("h2", "app_started", { launch: "normal", previous_session: "clean", pob_configured: true }),
    ev("h3", "app_started", { launch: "normal", previous_session: "clean", pob_configured: true }),
    ev("h3", "app_started", { launch: "normal", previous_session: "first_run", pob_configured: false }),
    ev("h1", "item_checks_summary", { buckets: [bucket("sidegrade", 7), bucket("not_viable", 3)] }),
    ev("h2", "item_checks_summary", { buckets: [bucket("sidegrade", 5)] }),
    ev("h2", "item_checks_summary", { buckets: [bucket("uncertain", 1)] }),
    ev("h1", "analyze_build_completed", { outcome: "ok", coverage: "high", curve_count: 1, hard_issue_present: false, health: "opportunity", duration: "lt_5s" }),
    ev("h2", "analyze_build_completed", { outcome: "error", coverage: "none", curve_count: 0, hard_issue_present: false, health: "none", duration: "lt_1s" }),
    ev("h2", "analyze_build_completed", { outcome: "ok", coverage: "high", curve_count: 1, hard_issue_present: false, health: "opportunity", duration: "lt_5s" }),
    ev("h1", "update_install_completed", { from_version: "0.7.0", to_version: "0.7.1", mode: "restart", outcome: "success" }),
    ev("h2", "update_install_completed", { from_version: "0.7.0", to_version: "0.7.1", mode: "restart", outcome: "relaunch_failed" }),
    ev("h1", "update_download_completed", { to_version: "0.7.1", mode: "auto", outcome: "ok", duration: "lt_5s" }),
    ev("h2", "update_download_completed", { to_version: "0.7.1", mode: "auto", outcome: "network", duration: "lt_5s" }),
    ev("h3", "update_download_completed", { to_version: "0.7.1", mode: "auto", outcome: "ok", duration: "lt_5s" }),
    // events of other days must not leak into yesterday's numbers
    ev("h1", "app_started", { launch: "normal", previous_session: "unexpected", pob_configured: true }, "2026-10-01"),
    ev("h1", "item_checks_summary", { buckets: [bucket("sidegrade", 100)] }, "2026-10-03"),
    db.prepare("INSERT INTO telemetry_install_days VALUES ('h1', ?1, '0.7.0', 4)").bind(D),
    db.prepare("INSERT INTO telemetry_install_days VALUES ('h2', ?1, '0.7.0', 4)").bind(D),
    db.prepare("INSERT INTO telemetry_install_days VALUES ('h3', ?1, '0.7.1', 2)").bind(D),
    db.prepare("INSERT INTO telemetry_install_days VALUES ('h1', '2026-10-03', '0.7.0', 1)"),
    db.prepare("INSERT INTO telemetry_installs VALUES ('h1', '2026-09-01', ?1, '0.7.0', '0.7.0')").bind(D),
    db.prepare("INSERT INTO telemetry_installs VALUES ('h3', ?1, ?1, '0.7.1', '0.7.1')").bind(D),
  ]);
}

async function metrics(day = D): Promise<Record<string, number>> {
  const rows = await all<{ metric: string; dim: string; value: number }>("SELECT * FROM metrics_daily WHERE day = ?1", day);
  return Object.fromEntries(rows.map((r) => [r.dim === "" ? r.metric : `${r.metric}:${r.dim}`, r.value]));
}

describe("aggregation", () => {
  it("aggregates yesterday correctly", async () => {
    await seedYesterday();
    const res = await runMaintenance(env(), NOW, { retention: false });
    expect(res.aggregatedDay).toBe(D);
    expect(await metrics()).toEqual({
      active_installs: 3,
      new_installs: 1,
      "app_version_active:0.7.0": 2,
      "app_version_active:0.7.1": 1,
      "events_by_name:app_started": 4,
      "events_by_name:item_checks_summary": 3,
      "events_by_name:analyze_build_completed": 3,
      "events_by_name:update_install_completed": 2,
      "events_by_name:update_download_completed": 3,
      "item_checks_by_verdict:sidegrade": 12,
      "item_checks_by_verdict:not_viable": 3,
      "item_checks_by_verdict:uncertain": 1,
      item_checks_total: 16,
      item_check_active_installs: 2,
      analyze_build_active_installs: 2,
      unexpected_session_end: 1,
      clean_session_end: 2,
      "analyze_build_by_outcome:ok": 2,
      "analyze_build_by_outcome:error": 1,
      "update_install_by_outcome:success": 1,
      "update_install_by_outcome:relaunch_failed": 1,
      "update_download_by_outcome:ok": 2,
      "update_download_by_outcome:network": 1,
    });
    expect(res.queries).toBeLessThanOrEqual(50);
  });

  it("is idempotent and writes zero rows for a quiet day", async () => {
    await seedYesterday();
    await runMaintenance(env(), NOW, { retention: false });
    const first = await metrics();
    await runMaintenance(env(), NOW, { retention: false });
    expect(await metrics()).toEqual(first);

    await runMaintenance(env(), NOW + 10 * DAY, { retention: false }); // aggregates 2026-10-12: nothing there
    const quiet = await metrics("2026-10-12");
    expect(quiet.active_installs).toBe(0);
    expect(quiet.item_checks_total).toBe(0);
    expect(quiet.unexpected_session_end).toBe(0);
  });

  it("ingest -> aggregate end to end", async () => {
    // events with day 2026-10-02 (event hour) delivered "today"
    const body = usageBatch({ events: [usageEvent({ t: "2026-10-02T09:00Z" }), usageEvent({ t: "2026-10-02T10:00Z", props: { launch: "normal", previous_session: "unexpected", pob_configured: true } })] });
    expect((await send("/v1/telemetry/batch", { body })).status).toBe(202);
    await runMaintenance(env(), NOW, { retention: false });
    const m = await metrics();
    expect(m["events_by_name:app_started"]).toBe(2);
    expect(m.unexpected_session_end).toBe(1);
    expect(m.clean_session_end).toBe(1);
  });
});

describe("retention", () => {
  const ins = (sql: string, ...p: unknown[]) => db.prepare(sql).bind(...p);

  async function seedRetention() {
    const d = (n: number) => new Date(NOW - n * DAY).toISOString().slice(0, 10);
    await db.batch([
      // ingest_batches: 7 days
      ins("INSERT INTO ingest_batches VALUES ('old', 'usage', ?1)", d(8)),
      ins("INSERT INTO ingest_batches VALUES ('new', 'usage', ?1)", d(7)),
      // telemetry_events: 30 days
      ins("INSERT INTO telemetry_events (install_hash, day, hour, event, app_version, props) VALUES ('h', ?1, 'x', 'app_started', '0.7.0', '{}')", d(31)),
      ins("INSERT INTO telemetry_events (install_hash, day, hour, event, app_version, props) VALUES ('h', ?1, 'x', 'app_started', '0.7.0', '{}')", d(30)),
      // install_days: 120 days
      ins("INSERT INTO telemetry_install_days VALUES ('h', ?1, '0.7.0', 1)", d(121)),
      ins("INSERT INTO telemetry_install_days VALUES ('h', ?1, '0.7.0', 1)", d(120)),
      // installs: 13 months after last_day
      ins("INSERT INTO telemetry_installs VALUES ('old', ?1, ?1, '0.1.0', '0.1.0')", monthsAgo(NOW, 14)),
      ins("INSERT INTO telemetry_installs VALUES ('new', ?1, ?1, '0.1.0', '0.1.0')", monthsAgo(NOW, 12)),
      // metrics: 13 months
      ins("INSERT INTO metrics_daily VALUES (?1, 'm', '', 1)", monthsAgo(NOW, 14)),
      ins("INSERT INTO metrics_daily VALUES (?1, 'm', '', 1)", monthsAgo(NOW, 12)),
      // error_groups: 12 months after last_seen
      ins("INSERT INTO error_groups VALUES ('old', 'EL-X-001', 'WRK', 'E', '[]', ?1, ?1, '1', '1', 1)", monthsAgo(NOW, 13)),
      ins("INSERT INTO error_groups VALUES ('new', 'EL-X-001', 'WRK', 'E', '[]', ?1, ?1, '1', '1', 1)", monthsAgo(NOW, 11)),
      // error_group_days: 13 months
      ins("INSERT INTO error_group_days VALUES ('g', ?1, '1', 1)", monthsAgo(NOW, 14)),
      ins("INSERT INTO error_group_days VALUES ('g', ?1, '1', 1)", monthsAgo(NOW, 12)),
      // error_group_installs: 60 days
      ins("INSERT INTO error_group_installs VALUES ('g', 'd', ?1)", d(61)),
      ins("INSERT INTO error_group_installs VALUES ('g', 'd', ?1)", d(60)),
      // error_installs: 13 months after last_day
      ins("INSERT INTO error_installs VALUES ('old', ?1, ?1, ?1, 1)", monthsAgo(NOW, 14)),
      ins("INSERT INTO error_installs VALUES ('new', ?1, ?1, ?1, 1)", monthsAgo(NOW, 12)),
    ]);
  }

  it("deletes expired rows in every table and keeps the rest", async () => {
    await seedRetention();
    const res = await runMaintenance(env(), NOW, { aggregate: false });
    for (const t of [
      "ingest_batches", "telemetry_events", "telemetry_install_days", "telemetry_installs", "metrics_daily",
      "error_groups", "error_group_days", "error_group_installs", "error_installs",
    ]) {
      expect(res.deleted[t], t).toBe(1);
      expect(await count(t), t).toBe(1);
    }
    expect((await all<{ batch_id: string }>("SELECT batch_id FROM ingest_batches"))[0]!.batch_id).toBe("new");
    expect((await all<{ install_hash: string }>("SELECT install_hash FROM telemetry_installs"))[0]!.install_hash).toBe("new");
    expect((await all<{ fingerprint: string }>("SELECT fingerprint FROM error_groups"))[0]!.fingerprint).toBe("new");
  });

  it("retention values come from the contract schema", () => {
    expect(schema.retention).toMatchObject({ raw_events_days: 30, install_activity_days: 120, aggregates_months: 13, error_groups_months: 12, error_install_links_days: 60 });
    expect(monthsAgo(Date.parse("2026-03-31T00:00:00Z"), 1)).toBe("2026-02-28");
    expect(monthsAgo(Date.parse("2026-10-03T00:00:00Z"), 13)).toBe("2025-09-03");
  });

  it("deletes in bounded chunks and resumes on the next run (query budget respected)", async () => {
    const total = DELETE_CHUNK * 2 + 500;
    await db.batch(
      Array.from({ length: Math.ceil(total / 500) }, () =>
        db.prepare(
          "INSERT INTO telemetry_events (install_hash, day, hour, event, app_version, props) SELECT 'h', '2020-01-01', 'x', 'app_started', '0.7.0', '{}' FROM (WITH RECURSIVE c(i) AS (SELECT 1 UNION ALL SELECT i + 1 FROM c WHERE i < 500) SELECT i FROM c)",
        ),
      ),
    );
    expect(await count("telemetry_events")).toBe(total);

    // budget of 1 query: exactly one chunk is removed
    const r1 = await runMaintenance(env(), NOW, { aggregate: false, maxQueries: 1 });
    expect(r1.queries).toBe(1);
    expect(r1.deleted.ingest_batches).toBe(0);
    expect(await count("telemetry_events")).toBe(total);

    const r2 = await runMaintenance(env(), NOW, { aggregate: false, maxQueries: 12 });
    expect(r2.queries).toBeLessThanOrEqual(12);
    expect(await count("telemetry_events")).toBeLessThan(total);

    for (let i = 0; i < 5 && (await count("telemetry_events")) > 0; i++) {
      await runMaintenance(env(), NOW, { aggregate: false });
    }
    expect(await count("telemetry_events")).toBe(0);
  });

  it("aggregates BEFORE deleting: yesterday's raw events are counted even when they are about to expire", async () => {
    await seedYesterday();
    const original = schema.retention.raw_events_days;
    schema.retention.raw_events_days = 0; // everything older than today is expired
    try {
      const res = await runMaintenance(env(), NOW);
      expect(res.aggregatedDay).toBe(D);
      expect(res.deleted.telemetry_events).toBeGreaterThan(0);
    } finally {
      schema.retention.raw_events_days = original;
    }
    // only the event dated today (10-03) survives
    expect(await count("telemetry_events")).toBe(1);
    expect((await metrics()).item_checks_total).toBe(16);
    expect((await metrics()).unexpected_session_end).toBe(1);
  });
});

describe("scheduled handler", () => {
  async function runScheduledAt(iso: string) {
    const handler = createHandler(() => NOW);
    const waits: Promise<unknown>[] = [];
    const ctx = { waitUntil: (p: Promise<unknown>) => waits.push(p), passThroughOnException() {} } as unknown as ExecutionContext;
    const time = Date.parse(iso);
    await handler.scheduled!({ scheduledTime: time, cron: "17 * * * *", noRetry() {} } as ScheduledController, makeEnv(), ctx);
    await Promise.all(waits);
  }

  it("runs the heavy job (aggregation) only at 03:xx UTC", async () => {
    vi.spyOn(console, "log").mockImplementation(() => undefined);
    await seedYesterday();
    await runScheduledAt("2026-10-03T04:17:00Z");
    expect(await count("metrics_daily")).toBe(0);
    await runScheduledAt("2026-10-03T03:17:00Z");
    expect((await metrics()).active_installs).toBe(3);
  });
});
