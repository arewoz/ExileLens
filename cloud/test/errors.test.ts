import { beforeEach, describe, expect, it } from "vitest";
import { fingerprintOf } from "../src/telemetry/errors";
import {
  DIAGNOSTIC_ID,
  NOW,
  TODAY,
  all,
  count,
  db,
  dumpAll,
  errorBatch,
  errorReport,
  makeEnv,
  referenceHmac,
  referenceSha256,
  resetDb,
  send,
  uuid4,
  workerAt,
} from "./helpers";

const PATH = "/v1/errors/batch";

beforeEach(resetDb);

const frames = (...specs: [string, string | undefined, number?][]) =>
  specs.map(([module, fn, line]) => ({ module, ...(fn !== undefined ? { function: fn } : {}), ...(line ? { line } : {}) }));

describe("error ingest", () => {
  it("stores a hashed diagnostic install, a server-fingerprinted group and per-day rows", async () => {
    const res = await send(PATH, { body: errorBatch() });
    expect(res.status).toBe(202);
    expect(await res.json()).toEqual({ ok: true, accepted: 1, rejected: [] });

    const hash = await referenceHmac(makeEnv().DIAGNOSTIC_PEPPER, "diagnostic", DIAGNOSTIC_ID);
    const fp = await referenceSha256("EL-WRK-002|TimeoutError|exilelens.app.engine:PobWorker.call;stdlib.threading:run");
    const groups = await all<Record<string, unknown>>("SELECT * FROM error_groups");
    expect(groups).toHaveLength(1);
    expect(groups[0]).toMatchObject({
      fingerprint: fp,
      error_code: "EL-WRK-002",
      component: "WRK",
      exception_type: "TimeoutError",
      first_seen_day: TODAY,
      last_seen_day: TODAY,
      first_version: "0.7.0",
      last_version: "0.7.0",
      occurrences: 2,
    });
    // latest frames are kept WITH line numbers
    expect(JSON.parse(groups[0]!.frames as string)[0]).toEqual({ module: "exilelens.app.engine", function: "PobWorker.call", line: 412 });
    expect(await all("SELECT * FROM error_group_days")).toEqual([{ fingerprint: fp, day: TODAY, app_version: "0.7.0", occurrences: 2 }]);
    expect(await all("SELECT * FROM error_group_installs")).toEqual([{ fingerprint: fp, diag_hash: hash, day: TODAY }]);
    expect(await all("SELECT * FROM error_installs")).toEqual([
      { diag_hash: hash, first_day: TODAY, last_day: TODAY, reports_today_day: TODAY, reports_today: 1 },
    ]);
    expect(await dumpAll()).not.toContain(DIAGNOSTIC_ID);
  });

  it("fingerprint ignores line numbers, component, count and frames beyond the first five", async () => {
    const base = errorReport({ frames: frames(["a", "f"], ["b", "g"], ["c", undefined], ["d", "h"], ["e", "i"], ["z", "extra", 3]) });
    const variant = errorReport({
      component: "UI",
      count: 9,
      frames: frames(["a", "f", 100], ["b", "g", 200], ["c", undefined, 300], ["d", "h"], ["e", "i", 5], ["other", "tail"]),
    });
    expect(await fingerprintOf(base as never)).toBe(await fingerprintOf(variant as never));
    expect(await fingerprintOf(base as never)).toBe(await referenceSha256("EL-WRK-002|TimeoutError|a:f;b:g;c:;d:h;e:i"));
    // but a different function, module order, code or exception type splits
    const differentFn = errorReport({ frames: frames(["a", "OTHER"], ["b", "g"], ["c", undefined], ["d", "h"], ["e", "i"]) });
    expect(await fingerprintOf(differentFn as never)).not.toBe(await fingerprintOf(base as never));
  });

  it("same fingerprint merges (line numbers ignored); different frames split", async () => {
    const r1 = errorReport({ frames: frames(["m.a", "f", 10], ["m.b", "g", 20]), count: 2 });
    const r2 = errorReport({ frames: frames(["m.a", "f", 11], ["m.b", "g", 99]), count: 3 });
    const r3 = errorReport({ frames: frames(["m.a", "f", 10], ["m.c", "other", 20]), count: 1 });
    await send(PATH, { body: errorBatch({ reports: [r1] }) });
    await send(PATH, { body: errorBatch({ reports: [r2, r3] }) });

    const groups = await all<{ fingerprint: string; occurrences: number; frames: string }>(
      "SELECT * FROM error_groups ORDER BY occurrences DESC",
    );
    expect(groups).toHaveLength(2);
    expect(groups[0]!.occurrences).toBe(5);
    expect(JSON.parse(groups[0]!.frames)[0].line).toBe(11); // latest frames win
    expect(groups[1]!.occurrences).toBe(1);
    const days = await all<{ occurrences: number }>("SELECT * FROM error_group_days ORDER BY occurrences DESC");
    expect(days.map((d) => d.occurrences)).toEqual([5, 1]);
  });

  it("two reports with one fingerprint in a single batch are merged into one group update", async () => {
    const same = [errorReport({ count: 4 }), errorReport({ count: 6 })];
    const res = await send(PATH, { body: errorBatch({ reports: same }) });
    expect(await res.json()).toEqual({ ok: true, accepted: 2, rejected: [] });
    expect((await all<{ occurrences: number }>("SELECT occurrences FROM error_groups"))[0]!.occurrences).toBe(10);
    expect(await count("error_group_installs")).toBe(1);
    expect((await all<{ reports_today: number }>("SELECT reports_today FROM error_installs"))[0]!.reports_today).toBe(2);
  });

  it("an affected install is counted once per day, a new install adds a link, a new day adds another", async () => {
    await send(PATH, { body: errorBatch() });
    await send(PATH, { body: errorBatch() }); // same install, same day, new batch_id
    expect(await count("error_group_installs")).toBe(1);

    await send(PATH, { body: errorBatch({ diagnostic_id: uuid4() }) }); // other install
    expect(await count("error_group_installs")).toBe(2);
    expect(await count("error_installs")).toBe(2);

    const tomorrow = workerAt(NOW + 24 * 3600 * 1000);
    await send(PATH, { body: errorBatch({ reports: [errorReport({ last_t: "2026-10-04T10:00Z", first_t: "2026-10-04T10:00Z" })] }), fetcher: tomorrow });
    expect(await count("error_group_installs")).toBe(3);

    const group = (await all<Record<string, unknown>>("SELECT * FROM error_groups"))[0]!;
    expect(group).toMatchObject({ first_seen_day: "2026-10-03", last_seen_day: "2026-10-04", occurrences: 8 });
    const diag = await all<{ reports_today_day: string; reports_today: number }>(
      "SELECT reports_today_day, reports_today FROM error_installs WHERE first_day = '2026-10-03' ORDER BY reports_today DESC",
    );
    expect(diag.some((r) => r.reports_today_day === "2026-10-04" && r.reports_today === 1)).toBe(true);
  });

  it("a client-supplied fingerprint is rejected, never trusted", async () => {
    const res = await send(PATH, { body: errorBatch({ reports: [errorReport({ fingerprint: "a".repeat(64) })] }) });
    expect(await res.json()).toEqual({ ok: true, accepted: 0, rejected: [{ index: 0, code: "unknown_prop" }] });
    expect(await count("error_groups")).toBe(0);
  });

  it("rejected reports are not stored while valid ones are", async () => {
    const res = await send(PATH, {
      body: errorBatch({ reports: [errorReport(), errorReport({ message: "C:\\Users\\me\\x" }), errorReport({ last_t: "2026-09-01T10:00Z", first_t: "2026-09-01T09:00Z" })] }),
    });
    expect(await res.json()).toEqual({
      ok: true,
      accepted: 1,
      rejected: [
        { index: 1, code: "unknown_prop" },
        { index: 2, code: "stale_event" },
      ],
    });
    expect(await count("error_groups")).toBe(1);
  });

  it("batch level failures use the same status mapping", async () => {
    expect((await send(PATH, { body: errorBatch({ analytics_id: "x" }) })).status).toBe(400);
    expect((await send(PATH, { body: errorBatch({ schema: 3 }) })).status).toBe(422);
    expect((await send(PATH, { body: errorBatch({ reports: Array.from({ length: 21 }, () => errorReport()) }) })).status).toBe(400);
  });
});

describe("error dedupe and caps", () => {
  it("duplicate batch_id is 200 duplicate with no writes", async () => {
    const batch = errorBatch();
    await send(PATH, { body: batch });
    const again = await send(PATH, { body: batch });
    expect(again.status).toBe(200);
    expect(await again.json()).toEqual({ ok: true, duplicate: true });
    expect((await all<{ occurrences: number }>("SELECT occurrences FROM error_groups"))[0]!.occurrences).toBe(2);
    expect((await all<{ reports_today: number }>("SELECT reports_today FROM error_installs"))[0]!.reports_today).toBe(1);
  });

  it("per-diag daily report cap: 429 daily_cap + Retry-After, resets the next UTC day", async () => {
    const hash = await referenceHmac(makeEnv().DIAGNOSTIC_PEPPER, "diagnostic", DIAGNOSTIC_ID);
    await db
      .prepare("INSERT INTO error_installs (diag_hash, first_day, last_day, reports_today_day, reports_today) VALUES (?1, ?2, ?2, ?2, 59)")
      .bind(hash, TODAY)
      .run();
    const two = errorBatch({ reports: [errorReport(), errorReport({ exception_type: "Other" })] });
    const capped = await send(PATH, { body: two });
    expect(capped.status).toBe(429);
    expect(capped.headers.get("retry-after")).toBe("41400");
    expect(await capped.json()).toEqual({ ok: false, code: "daily_cap" });
    expect(await count("ingest_batches")).toBe(0);
    expect(await count("error_groups")).toBe(0);

    expect((await send(PATH, { body: errorBatch() })).status).toBe(202); // 60th report
    expect((await send(PATH, { body: errorBatch() })).status).toBe(429);

    const tomorrow = workerAt(NOW + 24 * 3600 * 1000);
    const next = await send(PATH, { body: two, fetcher: tomorrow });
    expect(next.status).toBe(202);
    expect((await all<{ reports_today_day: string; reports_today: number }>("SELECT reports_today_day, reports_today FROM error_installs"))[0]).toEqual({
      reports_today_day: "2026-10-04",
      reports_today: 2,
    });
  });
});
