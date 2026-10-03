import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { telemetryEnv } from "../src/env";
import {
  ANALYTICS_ID,
  NOW,
  TODAY,
  all,
  brokenDb,
  count,
  countingDb,
  db,
  dumpAll,
  errorBatch,
  makeEnv,
  referenceHmac,
  resetDb,
  send,
  usageBatch,
  usageEvent,
  uuid4,
  workerAt,
} from "./helpers";

const URL_PATH = "/v1/telemetry/batch";

beforeEach(resetDb);
afterEach(() => vi.restoreAllMocks());

async function installHash(): Promise<string> {
  return referenceHmac(makeEnv().ANALYTICS_PEPPER, "analytics", ANALYTICS_ID);
}

describe("routing and basic responses", () => {
  it("GET /v1/health", async () => {
    const res = await send("/v1/health", { method: "GET" });
    expect(res.status).toBe(200);
    expect(res.headers.get("cache-control")).toBe("no-store");
    expect(await res.json()).toEqual({ ok: true, api: "v1", server_time: Math.floor(NOW / 1000) });
  });

  it("unknown paths are 404, wrong methods are 405, no CORS headers anywhere", async () => {
    const missing = await send("/v1/nope", { method: "GET" });
    expect(missing.status).toBe(404);
    expect(await missing.json()).toEqual({ ok: false, code: "not_found" });
    expect((await send("/v1/constructor", { method: "GET" })).status).toBe(404);
    expect((await send(URL_PATH, { method: "GET" })).status).toBe(405);
    expect((await send("/v1/health", { method: "POST" })).status).toBe(405);
    const options = await send(URL_PATH, { method: "OPTIONS" });
    expect(options.status).toBe(405);
    for (const res of [missing, options, await send("/v1/health", { method: "GET" })]) {
      expect(res.headers.get("access-control-allow-origin")).toBeNull();
      expect(res.headers.get("cache-control")).toBe("no-store");
    }
  });

  it("invalid JSON and non-object bodies are 400", async () => {
    const bad = await send(URL_PATH, { raw: "{not json" });
    expect(bad.status).toBe(400);
    expect(await bad.json()).toEqual({ ok: false, code: "invalid_json" });
    const arr = await send(URL_PATH, { body: [1, 2, 3] });
    expect(arr.status).toBe(400);
    expect(await arr.json()).toEqual({ ok: false, code: "invalid_envelope" });
  });
});

describe("request guards", () => {
  it("wrong or missing content-type is 415", async () => {
    expect((await send(URL_PATH, { body: usageBatch(), headers: { "content-type": "text/plain" } })).status).toBe(415);
    expect((await send(URL_PATH, { body: usageBatch(), headers: { "content-type": "" } })).status).toBe(415);
    const ok = await send(URL_PATH, { body: usageBatch(), headers: { "content-type": "Application/JSON; charset=utf-8" } });
    expect(ok.status).toBe(202);
  });

  it("a body over 32768 bytes is 413, with or without a Content-Length header", async () => {
    const big = JSON.stringify(usageBatch({ pad: "x".repeat(40000) }));
    const streamed = await send(URL_PATH, { raw: big });
    expect(streamed.status).toBe(413);
    expect(await streamed.json()).toEqual({ ok: false, code: "payload_too_large" });
    const declared = await send(URL_PATH, { body: usageBatch(), headers: { "content-length": "99999" } });
    expect(declared.status).toBe(413);
    // exactly at the cap is not rejected for size (it fails validation instead)
    const padded = JSON.stringify(usageBatch());
    const atCap = padded.slice(0, -1) + `,"x":"${"y".repeat(32768 - padded.length - 7)}"}`;
    expect(new TextEncoder().encode(atCap).length).toBe(32768);
    expect((await send(URL_PATH, { raw: atCap })).status).toBe(400);
    expect(await count("telemetry_events")).toBe(0);
  });

  it("kill switch returns 503 ingest_disabled with Retry-After 3600 and writes nothing", async () => {
    const res = await send(URL_PATH, { body: usageBatch(), env: makeEnv({ INGEST_ENABLED: "false" }) });
    expect(res.status).toBe(503);
    expect(res.headers.get("retry-after")).toBe("3600");
    expect(await res.json()).toEqual({ ok: false, code: "ingest_disabled" });
    const err = await send("/v1/errors/batch", { body: {}, env: makeEnv({ INGEST_ENABLED: "false" }) });
    expect(err.status).toBe(503);
    expect(await count("telemetry_events")).toBe(0);
  });

  it("missing peppers are a 503 not_configured, never a crash", async () => {
    const res = await send(URL_PATH, { body: usageBatch(), env: makeEnv({ ANALYTICS_PEPPER: "" }) });
    expect(res.status).toBe(503);
    expect(res.headers.get("retry-after")).toBe("3600");
    expect(await res.json()).toEqual({ ok: false, code: "not_configured" });
  });

  it("optional RL_INGEST binding is consulted with the client IP and enforced when present", async () => {
    const limit = vi.fn(async () => ({ success: false }));
    const res = await send(URL_PATH, {
      body: usageBatch(),
      headers: { "cf-connecting-ip": "203.0.113.9" },
      env: makeEnv({ RL_INGEST: { limit } }),
    });
    expect(res.status).toBe(429);
    expect(res.headers.get("retry-after")).toBe("60");
    expect(limit).toHaveBeenCalledWith({ key: "203.0.113.9" });
    const allow = vi.fn(async () => ({ success: true }));
    expect((await send(URL_PATH, { body: usageBatch(), env: makeEnv({ RL_INGEST: { limit: allow } }) })).status).toBe(202);
    // limiter outage fails open
    const broken = vi.fn(async () => {
      throw new Error("limiter down");
    });
    expect((await send(URL_PATH, { body: usageBatch(), env: makeEnv({ RL_INGEST: { limit: broken } }) })).status).toBe(202);
    // absent binding: skipped (all the other tests)
    expect(telemetryEnv(makeEnv()).RL_INGEST).toBeUndefined();
  });
});

describe("batch-level validation status codes", () => {
  it("maps contract batch codes to HTTP statuses", async () => {
    const cases: [Record<string, unknown>, number, string][] = [
      [usageBatch({ schema: 2 }), 422, "schema_unsupported"],
      [usageBatch({ extra: 1 }), 400, "unknown_field"],
      [usageBatch({ analytics_id: "DESKTOP-ARKADIUSZ" }), 400, "invalid_envelope"],
      [usageBatch({ app: { ...usageBatch().app, machine: "x" } }), 400, "invalid_app"],
      [usageBatch({ events: [] }), 400, "invalid_envelope"],
      [usageBatch({ events: Array.from({ length: 101 }, () => usageEvent()) }), 400, "too_many_events"],
    ];
    for (const [body, status, code] of cases) {
      const res = await send(URL_PATH, { body });
      expect(res.status).toBe(status);
      expect(await res.json()).toEqual({ ok: false, code });
    }
    expect(await count("ingest_batches")).toBe(0);
  });
});

describe("ingest happy path and storage", () => {
  it("stores accepted events, hashed install id, install activity and the batch row", async () => {
    const buckets = [
      { verdict: "sidegrade", confidence: "high", quality: "full", latency: "lt_500ms", outcome: "ok", n: 7 },
      { verdict: "unsupported", confidence: "none", quality: "unsupported", latency: "lt_1s", outcome: "ok", n: 2 },
    ];
    const batch = usageBatch({
      events: [
        usageEvent(),
        usageEvent({ name: "item_checks_summary", t: "2026-10-02T23:00Z", props: { buckets } }),
        usageEvent({ name: "bogus_event" }),
      ],
    });
    const res = await send(URL_PATH, { body: batch });
    expect(res.status).toBe(202);
    expect(await res.json()).toEqual({ ok: true, accepted: 2, rejected: [{ index: 2, code: "unknown_event" }] });

    const hash = await installHash();
    expect(hash).toMatch(/^[0-9a-f]{64}$/);
    const events = await all<{ install_hash: string; day: string; hour: string; event: string; app_version: string; props: string }>(
      "SELECT * FROM telemetry_events ORDER BY id",
    );
    expect(events).toHaveLength(2);
    expect(events[0]).toMatchObject({ install_hash: hash, day: TODAY, hour: "2026-10-03T12:00Z", event: "app_started", app_version: "0.7.0" });
    expect(JSON.parse(events[0]!.props)).toEqual({ launch: "normal", previous_session: "clean", pob_configured: true });
    // event day comes from the event hour, and item_checks_summary is exactly ONE row
    expect(events[1]).toMatchObject({ day: "2026-10-02", event: "item_checks_summary" });
    expect(JSON.parse(events[1]!.props)).toEqual({ buckets });

    expect(await all("SELECT * FROM telemetry_installs")).toEqual([
      { install_hash: hash, first_day: TODAY, last_day: TODAY, first_version: "0.7.0", last_version: "0.7.0" },
    ]);
    expect(await all("SELECT * FROM telemetry_install_days")).toEqual([
      { install_hash: hash, day: TODAY, app_version: "0.7.0", events_accepted: 2 },
    ]);
    expect(await all("SELECT * FROM ingest_batches")).toEqual([{ batch_id: batch.batch_id, kind: "usage", day: TODAY }]);
  });

  it("accumulates per-day counts and updates last_version across batches", async () => {
    await send(URL_PATH, { body: usageBatch() });
    const second = usageBatch({ app: { version: "0.7.1", channel: "stable", packaged: true, os: "win11" }, events: [usageEvent(), usageEvent()] });
    expect((await send(URL_PATH, { body: second })).status).toBe(202);
    const rows = await all<Record<string, unknown>>("SELECT * FROM telemetry_installs");
    expect(rows).toHaveLength(1);
    expect(rows[0]).toMatchObject({ first_version: "0.7.0", last_version: "0.7.1" });
    expect((await all<{ events_accepted: number }>("SELECT events_accepted FROM telemetry_install_days"))[0]!.events_accepted).toBe(3);
    expect(await count("telemetry_events")).toBe(3);
  });

  it("all events rejected is still 202 with accepted 0 and nothing is written", async () => {
    const res = await send(URL_PATH, { body: usageBatch({ events: [usageEvent({ name: "nope" }), usageEvent({ t: "2026-09-01T12:00Z" })] }) });
    expect(res.status).toBe(202);
    expect(await res.json()).toEqual({
      ok: true,
      accepted: 0,
      rejected: [
        { index: 0, code: "unknown_event" },
        { index: 1, code: "stale_event" },
      ],
    });
    for (const t of ["telemetry_events", "telemetry_installs", "telemetry_install_days", "ingest_batches"]) {
      expect(await count(t)).toBe(0);
    }
  });

  it("never persists IP, User-Agent or raw client UUIDs, and never logs them", async () => {
    const log = vi.spyOn(console, "log").mockImplementation(() => undefined);
    const batch = usageBatch();
    const res = await send(URL_PATH, {
      body: batch,
      headers: { "cf-connecting-ip": "203.0.113.77", "user-agent": "ExileLensTestAgent/9.9", "x-forwarded-for": "198.51.100.5" },
    });
    expect(res.status).toBe(202);
    const dump = await dumpAll();
    for (const secret of ["203.0.113.77", "198.51.100.5", "ExileLensTestAgent", ANALYTICS_ID]) {
      expect(dump).not.toContain(secret);
    }
    expect(dump).not.toContain(batch.batch_id.toUpperCase());
    const logged = log.mock.calls.map((c) => String(c[0])).join("\n");
    expect(logged).toContain("/v1/telemetry/batch");
    for (const secret of ["203.0.113.77", "ExileLensTestAgent", ANALYTICS_ID, await installHash(), batch.batch_id, "app_started"]) {
      expect(logged).not.toContain(secret);
    }
    expect(JSON.parse(String(log.mock.calls[0]![0]))).toMatchObject({ route: "/v1/telemetry/batch", status: 202 });
  });

  it("keeps D1 usage small: one request is a handful of queries and ONE statement for all events", async () => {
    const { db: counted, prepared } = countingDb(db);
    const events = Array.from({ length: 100 }, () => usageEvent());
    const res = await send(URL_PATH, { body: usageBatch({ events }), env: makeEnv({ TELEMETRY_DB: counted }) });
    expect(res.status).toBe(202);
    expect(prepared.length).toBeLessThanOrEqual(6);
    expect(await count("telemetry_events")).toBe(100);
  });
});

describe("dedupe", () => {
  it("a repeated batch_id within the window is 200 duplicate and writes nothing", async () => {
    const batch = usageBatch();
    expect((await send(URL_PATH, { body: batch })).status).toBe(202);
    const again = await send(URL_PATH, { body: batch });
    expect(again.status).toBe(200);
    expect(await again.json()).toEqual({ ok: true, duplicate: true });
    expect(await count("telemetry_events")).toBe(1);
    expect((await all<{ events_accepted: number }>("SELECT events_accepted FROM telemetry_install_days"))[0]!.events_accepted).toBe(1);
  });

  it("is scoped by kind: the same batch_id can be used once for usage and once for errors", async () => {
    const id = uuid4();
    expect((await send(URL_PATH, { body: usageBatch({ batch_id: id }) })).status).toBe(202);
    expect((await send("/v1/errors/batch", { body: errorBatch({ batch_id: id }) })).status).toBe(202);
    expect(await count("ingest_batches")).toBe(2);
  });

  it("a concurrent duplicate that slips past the pre-check rolls back atomically", async () => {
    const batch = usageBatch();
    expect((await send(URL_PATH, { body: batch })).status).toBe(202);
    // Blind the pre-check so the INSERT hits the primary key inside the batch.
    const blind = new Proxy(db, {
      get(target, prop) {
        if (prop === "prepare") {
          return (sql: string) => {
            const stmt = target.prepare(sql);
            if (!sql.includes("AS dup") || !sql.includes("used")) return stmt;
            return { bind: () => ({ first: async () => ({ dup: null, used: null }) }) } as unknown as D1PreparedStatement;
          };
        }
        const v = (target as unknown as Record<string | symbol, unknown>)[prop];
        return typeof v === "function" ? (v as (...a: unknown[]) => unknown).bind(target) : v;
      },
    });
    const res = await send(URL_PATH, { body: batch, env: makeEnv({ TELEMETRY_DB: blind as D1Database }) });
    expect(res.status).toBe(200);
    expect(await res.json()).toEqual({ ok: true, duplicate: true });
    expect(await count("telemetry_events")).toBe(1);
    expect((await all<{ events_accepted: number }>("SELECT events_accepted FROM telemetry_install_days"))[0]!.events_accepted).toBe(1);
  });
});

describe("daily cap", () => {
  it("returns 429 daily_cap with Retry-After until UTC midnight, counting only accepted events", async () => {
    const hash = await installHash();
    await db
      .prepare("INSERT INTO telemetry_install_days (install_hash, day, app_version, events_accepted) VALUES (?1, ?2, '0.7.0', 499)")
      .bind(hash, TODAY)
      .run();
    // 1 valid + 5 invalid events: only the accepted one counts -> 500, allowed
    const mixed = usageBatch({ events: [usageEvent(), ...Array.from({ length: 5 }, () => usageEvent({ name: "nope" }))] });
    expect((await send(URL_PATH, { body: mixed })).status).toBe(202);
    // now at 500: any further accepted event is over the cap
    const batch = usageBatch();
    const capped = await send(URL_PATH, { body: batch });
    expect(capped.status).toBe(429);
    expect(await capped.json()).toEqual({ ok: false, code: "daily_cap" });
    expect(capped.headers.get("retry-after")).toBe(String((24 * 3600) - (12 * 3600 + 30 * 60)));
    // the capped batch was not recorded, so it can be retried tomorrow
    expect(await all("SELECT * FROM ingest_batches WHERE batch_id = ?1", batch.batch_id)).toHaveLength(0);
    expect((await all<{ events_accepted: number }>("SELECT events_accepted FROM telemetry_install_days"))[0]!.events_accepted).toBe(500);
    // next UTC day the counter starts fresh
    const tomorrow = workerAt(NOW + 24 * 3600 * 1000);
    const next = await send(URL_PATH, { body: batch, fetcher: tomorrow });
    expect(next.status).toBe(202);
  });

  it("a batch that would cross the cap is rejected whole (no partial writes)", async () => {
    const hash = await installHash();
    await db
      .prepare("INSERT INTO telemetry_install_days (install_hash, day, app_version, events_accepted) VALUES (?1, ?2, '0.7.0', 450)")
      .bind(hash, TODAY)
      .run();
    const res = await send(URL_PATH, { body: usageBatch({ events: Array.from({ length: 51 }, () => usageEvent()) }) });
    expect(res.status).toBe(429);
    expect(await count("telemetry_events")).toBe(0);
  });
});

describe("storage failures", () => {
  it("D1 completely unavailable -> 503 storage_unavailable with Retry-After 3600", async () => {
    const res = await send(URL_PATH, { body: usageBatch(), env: makeEnv({ TELEMETRY_DB: brokenDb(db, "all") }) });
    expect(res.status).toBe(503);
    expect(res.headers.get("retry-after")).toBe("3600");
    expect(await res.json()).toEqual({ ok: false, code: "storage_unavailable" });
  });

  it("D1 write quota exhausted (reads fine, batch fails) -> 503 and nothing stored", async () => {
    const res = await send(URL_PATH, { body: usageBatch(), env: makeEnv({ TELEMETRY_DB: brokenDb(db, "writes") }) });
    expect(res.status).toBe(503);
    expect(res.headers.get("retry-after")).toBe("3600");
    expect(await res.json()).toEqual({ ok: false, code: "storage_unavailable" });
    expect(await count("telemetry_events")).toBe(0);
    const err = await send("/v1/errors/batch", {
      body: errorBatch(),
      env: makeEnv({ TELEMETRY_DB: brokenDb(db, "writes") }),
    });
    expect(err.status).toBe(503);
    const forget = await send("/v1/telemetry/forget", {
      body: { schema: 1, analytics_id: ANALYTICS_ID },
      env: makeEnv({ TELEMETRY_DB: brokenDb(db, "writes") }),
    });
    expect(forget.status).toBe(503);
    expect(forget.headers.get("retry-after")).toBe("3600");
  });
});
