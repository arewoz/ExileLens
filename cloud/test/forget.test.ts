import { beforeEach, describe, expect, it } from "vitest";
import {
  ANALYTICS_ID,
  DIAGNOSTIC_ID,
  TODAY,
  all,
  count,
  db,
  errorBatch,
  makeEnv,
  referenceHmac,
  resetDb,
  send,
  usageBatch,
  usageEvent,
  uuid4,
} from "./helpers";

beforeEach(resetDb);

const OTHER_ID = "11111111-2222-4333-8444-555555555555";

describe("POST /v1/telemetry/forget", () => {
  async function seed() {
    await send("/v1/telemetry/batch", { body: usageBatch() });
    await send("/v1/telemetry/batch", { body: usageBatch({ analytics_id: OTHER_ID, events: [usageEvent(), usageEvent()] }) });
    await db.prepare("INSERT INTO metrics_daily (day, metric, dim, value) VALUES ('2026-10-02', 'active_installs', '', 2)").run();
  }

  it("removes this install's rows only, keeps aggregates, and is idempotent", async () => {
    await seed();
    expect(await count("telemetry_events")).toBe(3);
    const mine = await referenceHmac(makeEnv().ANALYTICS_PEPPER, "analytics", ANALYTICS_ID);

    const res = await send("/v1/telemetry/forget", { body: { schema: 1, analytics_id: ANALYTICS_ID } });
    expect(res.status).toBe(204);
    expect(await res.text()).toBe("");
    expect(res.headers.get("cache-control")).toBe("no-store");

    expect(await all("SELECT 1 FROM telemetry_events WHERE install_hash = ?1", mine)).toHaveLength(0);
    expect(await all("SELECT 1 FROM telemetry_installs WHERE install_hash = ?1", mine)).toHaveLength(0);
    expect(await all("SELECT 1 FROM telemetry_install_days WHERE install_hash = ?1", mine)).toHaveLength(0);
    expect(await count("telemetry_events")).toBe(2);
    expect(await count("telemetry_installs")).toBe(1);
    expect(await count("metrics_daily")).toBe(1);

    const again = await send("/v1/telemetry/forget", { body: { schema: 1, analytics_id: ANALYTICS_ID } });
    expect(again.status).toBe(204);
    const stranger = await send("/v1/telemetry/forget", { body: { schema: 1, analytics_id: uuid4() } });
    expect(stranger.status).toBe(204);
    expect(await count("telemetry_events")).toBe(2);
  });

  it("is strict: unknown field, wrong id field, bad uuid, wrong schema, wrong method", async () => {
    const post = (body: unknown) => send("/v1/telemetry/forget", { body });
    expect(await (await post({ schema: 1, analytics_id: ANALYTICS_ID, extra: 1 })).json()).toEqual({ ok: false, code: "unknown_field" });
    expect((await post({ schema: 1, diagnostic_id: DIAGNOSTIC_ID })).status).toBe(400);
    expect((await post({ schema: 1, analytics_id: "nope" })).status).toBe(400);
    expect((await post({ schema: 1 })).status).toBe(400);
    expect((await post({ analytics_id: ANALYTICS_ID })).status).toBe(400);
    expect((await post({ schema: 2, analytics_id: ANALYTICS_ID })).status).toBe(422);
    expect((await post([ANALYTICS_ID])).status).toBe(400);
    expect((await send("/v1/telemetry/forget", { method: "GET" })).status).toBe(405);
    expect((await send("/v1/telemetry/forget", { body: { schema: 1, analytics_id: ANALYTICS_ID }, headers: { "content-type": "text/plain" } })).status).toBe(415);
  });

  it("still works while the ingest kill switch is on", async () => {
    await seed();
    const res = await send("/v1/telemetry/forget", {
      body: { schema: 1, analytics_id: ANALYTICS_ID },
      env: makeEnv({ INGEST_ENABLED: "false" }),
    });
    expect(res.status).toBe(204);
    expect(await count("telemetry_events")).toBe(2);
  });
});

describe("POST /v1/errors/forget", () => {
  it("removes the diagnostic install and its group links; anonymous error groups stay", async () => {
    await send("/v1/errors/batch", { body: errorBatch() });
    await send("/v1/errors/batch", { body: errorBatch({ diagnostic_id: OTHER_ID }) });
    expect(await count("error_installs")).toBe(2);
    const mine = await referenceHmac(makeEnv().DIAGNOSTIC_PEPPER, "diagnostic", DIAGNOSTIC_ID);

    const res = await send("/v1/errors/forget", { body: { schema: 1, diagnostic_id: DIAGNOSTIC_ID } });
    expect(res.status).toBe(204);
    expect(await all("SELECT 1 FROM error_installs WHERE diag_hash = ?1", mine)).toHaveLength(0);
    expect(await all("SELECT 1 FROM error_group_installs WHERE diag_hash = ?1", mine)).toHaveLength(0);
    expect(await count("error_installs")).toBe(1);
    expect(await count("error_group_installs")).toBe(1);
    expect(await count("error_groups")).toBe(1);
    expect(await count("error_group_days")).toBe(1);
    expect((await all<{ occurrences: number }>("SELECT occurrences FROM error_groups"))[0]!.occurrences).toBe(4);

    expect((await send("/v1/errors/forget", { body: { schema: 1, diagnostic_id: DIAGNOSTIC_ID } })).status).toBe(204);
    expect((await send("/v1/errors/forget", { body: { schema: 1, analytics_id: DIAGNOSTIC_ID } })).status).toBe(400);
    expect((await send("/v1/errors/forget", { body: { schema: 1, diagnostic_id: DIAGNOSTIC_ID, x: 1 } })).status).toBe(400);
  });

  it("usage forget does not touch error data and vice versa (separate hashes)", async () => {
    // the SAME uuid used as both ids must hash differently in the two domains
    await send("/v1/telemetry/batch", { body: usageBatch({ analytics_id: DIAGNOSTIC_ID }) });
    await send("/v1/errors/batch", { body: errorBatch() });
    const usageHash = (await all<{ install_hash: string }>("SELECT install_hash FROM telemetry_installs"))[0]!.install_hash;
    const diagHash = (await all<{ diag_hash: string }>("SELECT diag_hash FROM error_installs"))[0]!.diag_hash;
    expect(usageHash).not.toBe(diagHash);
    await send("/v1/telemetry/forget", { body: { schema: 1, analytics_id: DIAGNOSTIC_ID } });
    expect(await count("telemetry_installs")).toBe(0);
    expect(await count("error_installs")).toBe(1);
    expect(TODAY).toBe("2026-10-03");
  });
});
