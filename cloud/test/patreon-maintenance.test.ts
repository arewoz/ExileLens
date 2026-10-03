import { beforeEach, describe, expect, it } from "vitest";
import { createHandler } from "../src/app";
import { PATREON_CRON, monthsAgoDay, runPatreonMaintenance } from "../src/patreon/maintenance";
import { patreonEnv } from "../src/env";
import { NOW, count, countingDb, makeEnv, resetDb, db as telemetryDb } from "./helpers";
import { makePatreonEnv, nowS, pall, pcount, pdb, resetPatreonDb } from "./patreon-helpers";

const DAY = 86_400;
const ago = (seconds: number) => nowS - seconds;

beforeEach(async () => {
  await resetPatreonDb();
  await resetDb();
});

const session = (id: string, expiresAt: number) =>
  pdb
    .prepare("INSERT INTO link_sessions (session_id, state_hash, poll_token_hash, status, created_at, expires_at) VALUES (?1, ?2, ?3, 'pending', ?4, ?5)")
    .bind(id, `h-${id}`, `p-${id}`, expiresAt - 600, expiresAt);
const link = (id: string, createdAt: number) =>
  pdb
    .prepare(
      "INSERT INTO patreon_links (link_id, patreon_user_hmac, access_token_enc, refresh_token_enc, token_expires_at, token_version, last_capabilities, policy_version, status, created_at) VALUES (?1, ?2, 'x', 'y', 1, 1, '[]', 1, 'active', ?3)",
    )
    .bind(id, `u-${id}`, createdAt);
const device = (id: string, linkId: string, createdAt: number, lastRefresh: number | null) =>
  pdb
    .prepare("INSERT INTO devices (device_id, link_id, token_hash, created_at, last_refresh_at) VALUES (?1, ?2, ?3, ?4, ?5)")
    .bind(id, linkId, `t-${id}`, createdAt, lastRefresh);

describe("runPatreonMaintenance", () => {
  it("applies each retention rule and keeps what is still needed", async () => {
    await pdb.batch([
      // sessions: deleted 24 h after expiry
      session("old", ago(DAY + 5)),
      session("recent-expired", ago(DAY - 100)),
      session("live", nowS + 300),
      // links + devices
      link("L-active", ago(100 * DAY)),
      device("d-fresh", "L-active", ago(100 * DAY), ago(DAY)),
      device("d-idle", "L-active", ago(100 * DAY), ago(61 * DAY)),
      device("d-never-refreshed-old", "L-active", ago(61 * DAY), null),
      device("d-never-refreshed-new", "L-active", ago(2 * DAY), null),
      link("L-orphan-old", ago(30 * DAY)),
      link("L-orphan-new", ago(60)),
      link("L-await-first-poll", ago(30 * DAY)),
      link("L-idle-only", ago(100 * DAY)),
      device("d-idle-only", "L-idle-only", ago(100 * DAY), ago(70 * DAY)),
      // metrics: 13 months
      pdb.prepare("INSERT INTO link_metrics_daily VALUES (?1, 'started', 3)").bind(monthsAgoDay(NOW, 14)),
      pdb.prepare("INSERT INTO link_metrics_daily VALUES (?1, 'started', 3)").bind(monthsAgoDay(NOW, 12)),
      pdb.prepare("INSERT INTO entitlement_refresh_daily VALUES (?1, 'ok', 3)").bind(monthsAgoDay(NOW, 14)),
      pdb.prepare("INSERT INTO entitlement_refresh_daily VALUES (?1, 'ok', 3)").bind(monthsAgoDay(NOW, 1)),
    ]);
    await pdb
      .prepare(
        "INSERT INTO link_sessions (session_id, state_hash, poll_token_hash, status, created_at, expires_at, link_id, consumed) VALUES ('await', 'ha', 'pa', 'linked', ?1, ?2, 'L-await-first-poll', 0)",
      )
      .bind(ago(2 * 3600), ago(3600))
      .run();

    const res = await runPatreonMaintenance(patreonEnv(makePatreonEnv()), NOW);
    expect(res.queries).toBeLessThanOrEqual(20);
    expect(res.deleted).toMatchObject({ link_sessions: 1, devices: 3, patreon_links: 2, link_metrics_daily: 1, entitlement_refresh_daily: 1 });

    expect((await pall<{ session_id: string }>("SELECT session_id FROM link_sessions ORDER BY session_id")).map((r) => r.session_id)).toEqual([
      "await",
      "live",
      "recent-expired",
    ]);
    expect((await pall<{ device_id: string }>("SELECT device_id FROM devices ORDER BY device_id")).map((r) => r.device_id)).toEqual([
      "d-fresh",
      "d-never-refreshed-new",
    ]);
    // L-orphan-old and L-idle-only (its last device was idle > 60 days) are gone; the link awaiting its
    // first poll and the brand-new link survive.
    expect((await pall<{ link_id: string }>("SELECT link_id FROM patreon_links ORDER BY link_id")).map((r) => r.link_id)).toEqual([
      "L-active",
      "L-await-first-poll",
      "L-orphan-new",
    ]);
    expect(await pcount("link_metrics_daily")).toBe(1);
    expect(await pcount("entitlement_refresh_daily")).toBe(1);

    // idempotent
    const again = await runPatreonMaintenance(patreonEnv(makePatreonEnv()), NOW);
    expect(Object.values(again.deleted).reduce((a, b) => a + b, 0)).toBe(0);
  });

  it("is bounded: large backlogs are drained in chunks within the query budget", async () => {
    await pdb
      .prepare(
        `WITH RECURSIVE n(i) AS (SELECT 1 UNION ALL SELECT i + 1 FROM n WHERE i < 4500)
         INSERT INTO link_sessions (session_id, state_hash, poll_token_hash, status, created_at, expires_at)
         SELECT 's' || i, 'h' || i, 'p' || i, 'expired', ?1, ?1 FROM n`,
      )
      .bind(ago(5 * DAY))
      .run();
    expect(await pcount("link_sessions")).toBe(4500);
    const counted = countingDb(pdb);
    const res = await runPatreonMaintenance(patreonEnv(makePatreonEnv({ PATREON_DB: counted.db })), NOW);
    expect(res.deleted.link_sessions).toBe(4500);
    expect(counted.prepared.length).toBe(res.queries);
    expect(res.queries).toBeLessThanOrEqual(20);
    expect(await pcount("link_sessions")).toBe(0);
  });

  it("respects a smaller query budget and a missing binding", async () => {
    const res = await runPatreonMaintenance(patreonEnv(makePatreonEnv()), NOW, { maxQueries: 2 });
    expect(res.queries).toBe(2);
    const none = await runPatreonMaintenance(patreonEnv(makePatreonEnv({ PATREON_DB: undefined })), NOW);
    expect(none).toEqual({ queries: 0, deleted: {} });
  });
});

describe("scheduled handler dispatch", () => {
  async function run(cron: string, iso: string, env = makePatreonEnv()) {
    const handler = createHandler(() => NOW);
    const waits: Promise<unknown>[] = [];
    const ctx = { waitUntil: (p: Promise<unknown>) => waits.push(p), passThroughOnException() {} } as unknown as ExecutionContext;
    await handler.scheduled!({ scheduledTime: Date.parse(iso), cron, noRetry() {} } as ScheduledController, env, ctx);
    await Promise.all(waits);
  }

  it("the Patreon cron only touches PATREON_DB; the existing cron only touches the telemetry DB", async () => {
    await telemetryDb.prepare("INSERT INTO ingest_batches VALUES ('old-batch', 'usage', '2020-01-01')").run();
    await pdb.batch([session("old", ago(5 * DAY))]);

    await run("17 * * * *", "2026-10-03T04:17:00Z");
    expect(await pcount("link_sessions")).toBe(1); // untouched by the telemetry cron
    expect(await count("ingest_batches")).toBe(0);

    await telemetryDb.prepare("INSERT INTO ingest_batches VALUES ('old-batch', 'usage', '2020-01-01')").run();
    await run(PATREON_CRON, "2026-10-03T06:47:00Z");
    expect(await pcount("link_sessions")).toBe(0);
    expect(await count("ingest_batches")).toBe(1); // untouched by the Patreon cron
  });

  it("the Patreon cron without a Patreon database does not throw", async () => {
    await expect(run(PATREON_CRON, "2026-10-03T06:47:00Z", makeEnv())).resolves.toBeUndefined();
  });
});

describe("monthsAgoDay", () => {
  it("clamps the day of month", () => {
    expect(monthsAgoDay(Date.parse("2026-03-31T00:00:00Z"), 1)).toBe("2026-02-28");
    expect(monthsAgoDay(NOW, 13)).toBe("2025-09-03");
  });
});
