import { describe, expect, it } from "vitest";
import fixtures from "../contract/fixtures.json";
import { parseHour, validateBatch } from "../src/contract";
import { APP, usageBatch, usageEvent } from "./helpers";

interface Fixture {
  name: string;
  body: unknown;
  expect: { batch: string; accepted: number[]; rejected: { index: number; code: string }[] };
}

const now = Date.parse(fixtures.now);

describe.each([
  ["usage", fixtures.usage],
  ["errors", fixtures.errors],
] as const)("golden fixtures: %s", (kind, cases) => {
  it.each(cases as Fixture[])("$name", (fx) => {
    const result = validateBatch(kind, fx.body, now);
    expect(result.batchCode).toBe(fx.expect.batch);
    expect(result.accepted).toEqual(fx.expect.accepted);
    expect(result.rejected).toEqual(fx.expect.rejected);
  });
});

describe("validator edge cases", () => {
  const at = Date.parse("2026-10-03T12:30:00Z");

  it("rejects impossible calendar hours instead of rolling them over", () => {
    expect(parseHour("2026-02-31T10:00Z")).toBeNull();
    expect(parseHour("2026-10-03T24:00Z")).toBeNull();
    expect(parseHour("2026-10-03T12:00Z")).toBe(Date.parse("2026-10-03T12:00:00Z"));
    const r = validateBatch("usage", usageBatch({ events: [usageEvent({ t: "2026-10-03T24:00Z" })] }), at);
    expect(r.rejected).toEqual([{ index: 0, code: "invalid_value" }]);
  });

  it("window boundaries: 192 h old is stale only beyond the limit, +1 h future is allowed", () => {
    const ok = [usageEvent({ t: "2026-09-25T13:00Z" }), usageEvent({ t: "2026-10-03T13:00Z" })];
    expect(validateBatch("usage", usageBatch({ events: ok }), at).accepted).toEqual([0, 1]);
    const bad = [usageEvent({ t: "2026-09-25T12:00Z" }), usageEvent({ t: "2026-10-03T14:00Z" })];
    expect(validateBatch("usage", usageBatch({ events: bad }), at).rejected).toEqual([
      { index: 0, code: "stale_event" },
      { index: 1, code: "future_event" },
    ]);
  });

  it("enforces batch size and queue_dropped range", () => {
    const many = Array.from({ length: 101 }, () => usageEvent());
    expect(validateBatch("usage", usageBatch({ events: many }), at).batchCode).toBe("too_many_events");
    const hundred = Array.from({ length: 100 }, () => usageEvent());
    expect(validateBatch("usage", usageBatch({ events: hundred }), at).accepted).toHaveLength(100);
    expect(validateBatch("usage", usageBatch({ queue_dropped: -1 }), at).batchCode).toBe("invalid_envelope");
    expect(validateBatch("usage", usageBatch({ queue_dropped: 1.5 }), at).batchCode).toBe("invalid_envelope");
    expect(validateBatch("usage", usageBatch({ queue_dropped: true }), at).batchCode).toBe("invalid_envelope");
  });

  it("app problems are all invalid_app; missing required envelope keys are invalid_envelope", () => {
    for (const app of [null, [], "x", { ...APP, os: "linux" }, { version: "0.7.0" }, { ...APP, packaged: 1 }]) {
      expect(validateBatch("usage", usageBatch({ app }), at).batchCode).toBe("invalid_app");
    }
    const noApp: Record<string, unknown> = usageBatch();
    delete noApp.app;
    expect(validateBatch("usage", noApp, at).batchCode).toBe("invalid_envelope");
    expect(validateBatch("usage", null, at).batchCode).toBe("invalid_envelope");
  });

  it("__proto__ and inherited names are treated as unknown props", () => {
    const evt = JSON.parse(
      '{"name":"app_started","t":"2026-10-03T12:00Z","props":{"launch":"normal","previous_session":"clean","pob_configured":true,"__proto__":{"x":1}}}',
    );
    expect(validateBatch("usage", usageBatch({ events: [evt] }), at).rejected).toEqual([{ index: 0, code: "unknown_prop" }]);
    const named = usageEvent({ name: "constructor" });
    expect(validateBatch("usage", usageBatch({ events: [named] }), at).rejected).toEqual([{ index: 0, code: "unknown_event" }]);
  });

  it("int rejects floats, strings and booleans; nested non-object bucket is invalid_value", () => {
    const summary = (buckets: unknown) => usageEvent({ name: "item_checks_summary", props: { buckets } });
    const bucket = { verdict: "sidegrade", confidence: "high", quality: "full", latency: "lt_1s", outcome: "ok", n: 1 };
    const run = (b: unknown) => validateBatch("usage", usageBatch({ events: [summary(b)] }), at).rejected;
    expect(run([bucket])).toEqual([]);
    expect(run([{ ...bucket, n: 1.5 }])).toEqual([{ index: 0, code: "invalid_value" }]);
    expect(run([{ ...bucket, n: "1" }])).toEqual([{ index: 0, code: "invalid_value" }]);
    expect(run([{ ...bucket, n: true }])).toEqual([{ index: 0, code: "invalid_value" }]);
    expect(run(["x"])).toEqual([{ index: 0, code: "invalid_value" }]);
    expect(run(Array.from({ length: 61 }, () => bucket))).toEqual([{ index: 0, code: "invalid_value" }]);
  });
});
