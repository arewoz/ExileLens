import { beforeEach, describe, expect, it } from "vitest";
import { all } from "./helpers";
import { pall, pdb, resetPatreonDb } from "./patreon-helpers";

const files = import.meta.glob("../reports/patreon/*.sql", { query: "?raw", import: "default", eager: true }) as Record<string, string>;
const reports = Object.fromEntries(Object.entries(files).map(([p, sql]) => [p.split("/").pop()!.replace(/\.sql$/, ""), sql]));
const REQUIRED = ["patreon_link_outcomes", "entitlement_refresh_outcomes", "active_entitled_devices"];
const day = (offset: number) => new Date(Date.now() - offset * 86_400_000).toISOString().slice(0, 10);
const epoch = () => Math.floor(Date.now() / 1000);

beforeEach(resetPatreonDb);

describe("Patreon report files", () => {
  it("exactly the required reports exist", () => {
    expect(Object.keys(reports).sort()).toEqual([...REQUIRED].sort());
  });

  it.each(REQUIRED)("%s is a single read-only SELECT labelled anonymous and selects no identifiers", (name) => {
    const sql = reports[name]!;
    const header = sql
      .split(/\r?\n/)
      .filter((l) => l.startsWith("--"))
      .map((l) => l.replace(/^--\s?/, ""))
      .join(" ");
    expect(sql.startsWith("--")).toBe(true);
    expect(header).toMatch(/ANONYMOUS/);
    expect(header).toMatch(/not users/i);
    const body = sql
      .split(/\r?\n/)
      .filter((l) => !l.startsWith("--"))
      .join("\n");
    expect(body.trim()).toMatch(/^SELECT\b/i);
    expect(body).not.toMatch(/\b(INSERT|UPDATE|DELETE|DROP|ALTER|CREATE|REPLACE|PRAGMA|ATTACH)\b/i);
    expect(body.trim().replace(/;$/, "")).not.toContain(";");
    // no identifier is ever selected (device / link / user / session / token columns)
    expect(body).not.toMatch(/\bSELECT\b[^]*?\b(d\.device_id|l\.link_id|token_hash|patreon_user_hmac|session_id)\b[^]*?\bFROM\b/i);
    expect(body).not.toMatch(/telemetry_|TELEMETRY_DB/);
  });

  it.each(REQUIRED)("%s runs on an empty database", async (name) => {
    expect(Array.isArray(await pall(reports[name]!))).toBe(true);
  });

  it("they are not runnable against the telemetry database (separate --db choice)", async () => {
    await expect(all(reports.active_entitled_devices!)).rejects.toThrow();
  });
});

describe("Patreon report results", () => {
  it("link and refresh outcomes pivot per day and ignore rows older than 30 days", async () => {
    await pdb.batch([
      pdb.prepare("INSERT INTO link_metrics_daily VALUES (?1, 'started', 10)").bind(day(1)),
      pdb.prepare("INSERT INTO link_metrics_daily VALUES (?1, 'linked', 6)").bind(day(1)),
      pdb.prepare("INSERT INTO link_metrics_daily VALUES (?1, 'not_entitled', 2)").bind(day(1)),
      pdb.prepare("INSERT INTO link_metrics_daily VALUES (?1, 'denied', 1)").bind(day(1)),
      pdb.prepare("INSERT INTO link_metrics_daily VALUES (?1, 'failed', 1)").bind(day(1)),
      pdb.prepare("INSERT INTO link_metrics_daily VALUES (?1, 'started', 5)").bind(day(40)),
      pdb.prepare("INSERT INTO entitlement_refresh_daily VALUES (?1, 'ok', 20)").bind(day(1)),
      pdb.prepare("INSERT INTO entitlement_refresh_daily VALUES (?1, 'not_eligible', 3)").bind(day(1)),
      pdb.prepare("INSERT INTO entitlement_refresh_daily VALUES (?1, 'patreon_unavailable', 2)").bind(day(1)),
      pdb.prepare("INSERT INTO entitlement_refresh_daily VALUES (?1, 'rate_limited', 4)").bind(day(1)),
    ]);
    expect(await pall(reports.patreon_link_outcomes!)).toEqual([
      { day: day(1), started: 10, linked: 6, not_entitled: 2, denied: 1, expired: 0, failed: 1 },
    ]);
    expect(await pall(reports.entitlement_refresh_outcomes!)).toEqual([
      {
        day: day(1),
        ok: 20,
        not_eligible: 3,
        patreon_unavailable: 2,
        reauthorize_required: 0,
        device_unknown: 0,
        rate_limited: 4,
        issuance_disabled: 0,
      },
    ]);
  });

  it("active_entitled_devices counts only devices with an unexpired lease on a link entitled to seamless_updates", async () => {
    const now = epoch();
    const mkLink = (id: string, caps: string) =>
      pdb.prepare("INSERT INTO patreon_links (link_id, patreon_user_hmac, last_capabilities, created_at) VALUES (?1, ?2, ?3, 1)").bind(id, `u-${id}`, caps);
    const mkDev = (id: string, linkId: string, leaseExp: number | null) =>
      pdb
        .prepare("INSERT INTO devices (device_id, link_id, token_hash, created_at, last_lease_expires_at) VALUES (?1, ?2, ?3, 1, ?4)")
        .bind(id, linkId, `t-${id}`, leaseExp);
    await pdb.batch([
      mkLink("paid", '["seamless_updates"]'),
      mkLink("free", "[]"),
      mkDev("a", "paid", now + 1000),
      mkDev("b", "paid", now + 1000),
      mkDev("c", "paid", now - 10), // lease expired
      mkDev("d", "paid", null),
      mkDev("e", "free", now + 1000), // valid lease but not entitled
    ]);
    expect(await pall<Record<string, number>>(reports.active_entitled_devices!)).toEqual([
      { active_entitled_devices: 2, devices_with_valid_lease: 3 },
    ]);
  });
});
