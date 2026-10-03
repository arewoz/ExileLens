import { describe, expect, it } from "vitest";
import { telemetryEnv, type Env } from "../src/env";
import { hmacHex } from "../src/telemetry/hash";
import { ANALYTICS_ID, makeEnv, send, usageBatch } from "./helpers";

// Every source file under cloud/src, loaded as raw text at build time (no filesystem access needed).
const sources = import.meta.glob("../src/**/*.ts", { query: "?raw", import: "default", eager: true }) as Record<string, string>;
const telemetrySources = Object.entries(sources).filter(([path]) => path.includes("/src/telemetry/"));

describe("telemetry / Patreon separation", () => {
  it("telemetryEnv() returns only telemetry bindings and never a PATREON key", () => {
    const full = {
      ...makeEnv({ RL_INGEST: { limit: async () => ({ success: true }) } }),
      PATREON_DB: {},
      PATREON_CLIENT_SECRET: "x",
      PATREON_WEBHOOK_SECRET: "y",
      SOMETHING_ELSE: "z",
    } as unknown as Env;
    const narrowed = telemetryEnv(full);
    expect(Object.keys(narrowed).filter((k) => /PATREON/i.test(k))).toEqual([]);
    expect(Object.keys(narrowed).sort()).toEqual(
      ["ANALYTICS_PEPPER", "DIAGNOSTIC_PEPPER", "INGEST_ENABLED", "RL_INGEST", "TELEMETRY_DB"].sort(),
    );
    expect(JSON.stringify(Object.keys(narrowed))).not.toMatch(/PATREON|SOMETHING_ELSE/);
  });

  it("routing a telemetry request never even reads a Patreon binding from the Worker env", async () => {
    const touched: string[] = [];
    const guarded = new Proxy(makeEnv() as unknown as Record<string, unknown>, {
      get(target, prop) {
        if (typeof prop === "string" && /PATREON/i.test(prop)) touched.push(prop);
        return target[prop as string];
      },
      has(target, prop) {
        if (typeof prop === "string" && /PATREON/i.test(prop)) touched.push(prop);
        return prop in target;
      },
      ownKeys(target) {
        return [...Reflect.ownKeys(target), "PATREON_DB"];
      },
    }) as unknown as Env;
    const res = await send("/v1/telemetry/batch", { body: usageBatch(), env: guarded });
    expect(res.status).toBe(202);
    expect(touched).toEqual([]);
    expect(Object.keys(telemetryEnv(guarded)).filter((k) => /PATREON/i.test(k))).toEqual([]);
  });

  it("source files under src/telemetry never import from src/patreon or mention PATREON", () => {
    expect(telemetrySources.length).toBeGreaterThanOrEqual(7);
    for (const [path, text] of telemetrySources) {
      expect(text, path).not.toMatch(/patreon/i);
      expect(text, path).not.toMatch(/from\s+["'][^"']*patreon/i);
      expect(text, path).not.toMatch(/import\(\s*["'][^"']*patreon/i);
    }
  });

  it("no cross-database SQL: telemetry SQL never names a non-telemetry table", () => {
    for (const [path, text] of telemetrySources) {
      expect(text, path).not.toMatch(/ATTACH\s+DATABASE/i);
    }
  });
});

describe("hash domains and peppers", () => {
  it("different peppers and domains give different hashes for the same UUID", async () => {
    const e = makeEnv();
    const usage = await hmacHex(e.ANALYTICS_PEPPER, "analytics", ANALYTICS_ID);
    const diag = await hmacHex(e.DIAGNOSTIC_PEPPER, "diagnostic", ANALYTICS_ID);
    expect(usage).toMatch(/^[0-9a-f]{64}$/);
    expect(diag).toMatch(/^[0-9a-f]{64}$/);
    expect(usage).not.toBe(diag);
    // same pepper, different domain
    expect(await hmacHex(e.ANALYTICS_PEPPER, "diagnostic", ANALYTICS_ID)).not.toBe(usage);
    // same domain, different pepper
    expect(await hmacHex("another-pepper-0123456789", "analytics", ANALYTICS_ID)).not.toBe(usage);
    // deterministic
    expect(await hmacHex(e.ANALYTICS_PEPPER, "analytics", ANALYTICS_ID)).toBe(usage);
  });

  it("the test peppers are distinct", () => {
    const e = makeEnv();
    expect(e.ANALYTICS_PEPPER).not.toBe(e.DIAGNOSTIC_PEPPER);
  });
});
