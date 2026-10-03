import { beforeEach, describe, expect, it } from "vitest";
import { all, db, resetDb } from "./helpers";

const files = import.meta.glob("../reports/*.sql", { query: "?raw", import: "default", eager: true }) as Record<string, string>;
const reports = Object.fromEntries(Object.entries(files).map(([p, sql]) => [p.split("/").pop()!.replace(/\.sql$/, ""), sql]));

const REQUIRED = [
  "active_installs",
  "new_and_returning_installs",
  "retention",
  "item_check_volume",
  "verdict_distribution",
  "analyze_build_adoption",
  "top_error_groups",
  "unexpected_session_end_rate",
  "update_adoption",
  "update_failure_rate",
];

const render = (name: string, minCohort = 0) => reports[name]!.replaceAll("{{MIN_COHORT}}", String(minCohort));
const day = (offset: number) => new Date(Date.now() - offset * 86_400_000).toISOString().slice(0, 10);

beforeEach(resetDb);

describe("report files", () => {
  it("all required reports exist", () => {
    expect(Object.keys(reports).sort()).toEqual([...REQUIRED].sort());
  });

  it.each(REQUIRED)("%s is a single read-only SELECT that states it counts installations, not users", (name) => {
    const sql = reports[name]!;
    const header = sql
      .split("\n")
      .filter((l) => l.startsWith("--"))
      .map((l) => l.replace(/^--\s?/, ""))
      .join(" ");
    expect(sql.startsWith("--")).toBe(true);
    expect(header).toMatch(/installations?\b/i);
    expect(header).toMatch(/not users/i);
    const body = sql
      .split("\n")
      .filter((l) => !l.startsWith("--"))
      .join("\n");
    expect(body.trim()).toMatch(/^(SELECT|WITH)\b/i);
    expect(body).not.toMatch(/\b(INSERT|UPDATE|DELETE|DROP|ALTER|CREATE|REPLACE|PRAGMA|ATTACH)\b/i);
    expect(body.trim().replace(/;$/, "")).not.toContain(";");
  });

  it("only unexpected_session_end_rate talks about crashes, and never as 'crash-free' presented as a metric", () => {
    for (const [name, sql] of Object.entries(reports)) {
      const body = sql.split("\n").filter((l) => !l.startsWith("--")).join("\n");
      expect(body, name).not.toMatch(/crash/i);
    }
    expect(reports.unexpected_session_end_rate).toMatch(/unexpected session end/i);
    expect(reports.unexpected_session_end_rate).toMatch(/NOT a crash rate/);
  });

  it.each(REQUIRED)("%s runs against the schema on an empty database", async (name) => {
    const rows = await all(render(name));
    expect(Array.isArray(rows)).toBe(true);
  });
});

describe("report results", () => {
  it("active_installs, new/returning and retention (with small-cohort suppression)", async () => {
    await db.batch([
      db.prepare("INSERT INTO telemetry_installs VALUES ('a', ?1, ?2, '0.7.0', '0.7.0')").bind(day(10), day(1)),
      db.prepare("INSERT INTO telemetry_installs VALUES ('b', ?1, ?1, '0.7.0b2', '0.7.0b2')").bind(day(1)),
      ...[10, 9, 3, 2, 1].map((d) => db.prepare("INSERT INTO telemetry_install_days VALUES ('a', ?1, '0.7.0', 1)").bind(day(d))),
      db.prepare("INSERT INTO telemetry_install_days VALUES ('b', ?1, '0.7.0b2', 1)").bind(day(1)),
    ]);

    expect((await all(render("active_installs")))[0]).toEqual({
      active_installs_1d: 2,
      active_installs_7d: 2,
      active_installs_30d: 2,
      opted_in_installs_known: 2,
    });

    const nr = await all<{ day: string; active_installs: number; new_installs: number; returning_installs: number }>(render("new_and_returning_installs"));
    expect(nr.find((r) => r.day === day(1))).toMatchObject({ active_installs: 2, new_installs: 1, returning_installs: 1 });
    expect(nr.find((r) => r.day === day(10))).toMatchObject({ active_installs: 1, new_installs: 1, returning_installs: 0 });

    const open = await all<Record<string, number | null>>(render("retention", 0));
    const cohortRow = open.find((r) => r.cohort_installs === 1 && r.d1_pct === 100);
    expect(cohortRow).toBeTruthy();
    expect(cohortRow!.d7_pct).toBe(100); // day(10)+7 = day(3) was active
    expect(cohortRow!.d30_pct).toBeNull(); // not old enough yet
    const suppressed = await all<Record<string, number | null>>(render("retention", 20));
    for (const r of suppressed) {
      expect(r.d1_pct).toBeNull();
      expect(r.d7_pct).toBeNull();
      expect(r.d30_pct).toBeNull();
    }
  });

  it("update_adoption marks the highest version as latest (beta sorts below release)", async () => {
    const add = (h: string, v: string) =>
      db.prepare("INSERT INTO telemetry_installs VALUES (?1, ?2, ?2, ?3, ?3)").bind(h, day(1), v);
    await db.batch([add("a", "0.7.0b2"), add("b", "0.7.0"), add("c", "0.7.0"), add("d", "0.6.12"), add("e", "0.10.0")]);
    const rows = await all<{ version: string; installs: number; pct_of_active_installs: number; is_latest: string }>(render("update_adoption"));
    expect(rows.map((r) => r.version)).toEqual(["0.10.0", "0.7.0", "0.7.0b2", "0.6.12"]);
    expect(rows.find((r) => r.is_latest === "latest")?.version).toBe("0.10.0");
    expect(rows.find((r) => r.version === "0.7.0")).toMatchObject({ installs: 2, pct_of_active_installs: 40 });
  });

  it("metrics-based reports pivot correctly", async () => {
    const m = (d: number, metric: string, dim: string, value: number) =>
      db.prepare("INSERT INTO metrics_daily VALUES (?1, ?2, ?3, ?4)").bind(day(d), metric, dim, value);
    await db.batch([
      m(1, "active_installs", "", 10),
      m(1, "item_check_active_installs", "", 4),
      m(1, "item_checks_total", "", 40),
      m(1, "item_checks_by_verdict", "sidegrade", 30),
      m(1, "item_checks_by_verdict", "uncertain", 10),
      m(1, "analyze_build_active_installs", "", 5),
      m(1, "analyze_build_by_outcome", "ok", 8),
      m(1, "analyze_build_by_outcome", "error", 2),
      m(1, "unexpected_session_end", "", 1),
      m(1, "clean_session_end", "", 9),
      m(1, "update_download_by_outcome", "ok", 9),
      m(1, "update_download_by_outcome", "network", 1),
      m(1, "update_install_by_outcome", "success", 3),
      m(1, "update_install_by_outcome", "relaunch_failed", 1),
    ]);
    expect((await all(render("item_check_volume")))[0]).toMatchObject({
      active_installs: 10,
      item_check_installs: 4,
      item_checks_total: 40,
      checks_per_item_check_install: 10,
      checks_per_active_install: 4,
    });
    expect(await all(render("verdict_distribution"))).toEqual([
      { verdict: "sidegrade", checks: 30, pct_of_checks: 75 },
      { verdict: "uncertain", checks: 10, pct_of_checks: 25 },
    ]);
    expect((await all(render("analyze_build_adoption")))[0]).toMatchObject({
      analyze_installs: 5,
      adoption_pct_of_active_installs: 50,
      runs_ok: 8,
      runs_error: 2,
    });
    expect((await all(render("unexpected_session_end_rate")))[0]).toMatchObject({
      unexpected_session_end: 1,
      clean_session_end: 9,
      unexpected_session_end_pct: 10,
    });
    const fail = await all<{ stage: string; outcome: string; pct_of_stage_attempts: number; result: string }>(render("update_failure_rate"));
    expect(fail.find((r) => r.stage === "install" && r.outcome === "relaunch_failed")).toMatchObject({ pct_of_stage_attempts: 25, result: "not_success" });
    expect(fail.find((r) => r.stage === "download" && r.outcome === "ok")).toMatchObject({ pct_of_stage_attempts: 90, result: "success" });
  });

  it("top_error_groups lists affected diagnostic installs", async () => {
    await db.batch([
      db.prepare("INSERT INTO error_groups VALUES ('fp1', 'EL-WRK-002', 'WRK', 'TimeoutError', '[]', ?1, ?1, '0.7.0', '0.7.0', 9)").bind(day(2)),
      db.prepare("INSERT INTO error_groups VALUES ('fp2', 'EL-UI-001', 'UI', 'KeyError', '[]', ?1, ?1, '0.7.0', '0.7.0', 50)").bind(day(1)),
      db.prepare("INSERT INTO error_group_installs VALUES ('fp1', 'd1', ?1)").bind(day(2)),
      db.prepare("INSERT INTO error_group_installs VALUES ('fp1', 'd2', ?1)").bind(day(1)),
      db.prepare("INSERT INTO error_group_installs VALUES ('fp1', 'd2', ?1)").bind(day(2)),
      db.prepare("INSERT INTO error_group_installs VALUES ('fp2', 'd1', ?1)").bind(day(1)),
    ]);
    const rows = await all<{ error_code: string; affected_diag_installs: number; occurrences: number }>(render("top_error_groups"));
    expect(rows.map((r) => [r.error_code, r.affected_diag_installs, r.occurrences])).toEqual([
      ["EL-WRK-002", 2, 9],
      ["EL-UI-001", 1, 50],
    ]);
  });
});
