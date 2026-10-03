#!/usr/bin/env node
// Run a named read-only report against the TELEMETRY_DB D1 database and print a table.
//
//   node scripts/report.mjs <name> [--local | --remote] [--env <staging|production>]
//                                  [--min-cohort <n>] [--json]
//   node scripts/report.mjs --list
//
// All reports count opted-in active INSTALLATIONS, not users. Reports are plain SELECT
// files in cloud/reports/*.sql; this script only substitutes {{MIN_COHORT}} and shells out
// to `wrangler d1 execute`. No credentials are handled here: --remote uses whatever
// `wrangler login` / CLOUDFLARE_API_TOKEN the owner already has.
import { spawnSync } from "node:child_process";
import { mkdtempSync, readFileSync, readdirSync, rmSync, writeFileSync } from "node:fs";
import { createRequire } from "node:module";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const reportsDir = join(root, "reports");

export function listReports() {
  return readdirSync(reportsDir)
    .filter((f) => f.endsWith(".sql"))
    .map((f) => f.slice(0, -4))
    .sort();
}

/** Read a report and substitute {{MIN_COHORT}} with a validated non-negative integer. */
export function renderReport(name, minCohort) {
  if (!/^[a-z0-9_]+$/.test(name) || !listReports().includes(name)) {
    throw new Error(`Unknown report "${name}". Available: ${listReports().join(", ")}`);
  }
  if (!Number.isInteger(minCohort) || minCohort < 0) {
    throw new Error("--min-cohort must be a non-negative integer");
  }
  return readFileSync(join(reportsDir, `${name}.sql`), "utf8").replaceAll("{{MIN_COHORT}}", String(minCohort));
}

export function formatTable(rows) {
  if (!rows.length) return "(no rows)";
  const cols = Object.keys(rows[0]);
  const cell = (v) => (v === null || v === undefined ? "-" : String(v));
  const widths = cols.map((c) => Math.max(c.length, ...rows.map((r) => cell(r[c]).length)));
  const line = (vals) => vals.map((v, i) => v.padEnd(widths[i])).join("  ");
  return [line(cols), line(widths.map((w) => "-".repeat(w))), ...rows.map((r) => line(cols.map((c) => cell(r[c]))))].join("\n");
}

function parseArgs(argv) {
  const opts = { name: null, remote: false, env: null, minCohort: null, json: false, list: false };
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i];
    if (a === "--local") opts.remote = false;
    else if (a === "--remote") opts.remote = true;
    else if (a === "--json") opts.json = true;
    else if (a === "--list") opts.list = true;
    else if (a === "--env") opts.env = argv[++i];
    else if (a === "--min-cohort") opts.minCohort = Number(argv[++i]);
    else if (a.startsWith("--")) throw new Error(`Unknown flag ${a}`);
    else if (opts.name === null) opts.name = a;
    else throw new Error(`Unexpected argument ${a}`);
  }
  return opts;
}

function main() {
  const opts = parseArgs(process.argv.slice(2));
  if (opts.list || !opts.name) {
    console.log(`Reports (opted-in active installations, not users):\n  ${listReports().join("\n  ")}`);
    return opts.list ? 0 : 1;
  }
  if (opts.remote && !opts.env) throw new Error("--remote requires --env <staging|production>");
  if (opts.env && !/^(staging|production)$/.test(opts.env)) throw new Error("--env must be staging or production");
  // Small-cohort suppression defaults to ON (20) only for remote data.
  const minCohort = opts.minCohort ?? (opts.remote ? 20 : 0);
  const sql = renderReport(opts.name, minCohort);

  const require = createRequire(import.meta.url);
  const wranglerJs = join(dirname(require.resolve("wrangler/package.json")), "bin", "wrangler.js");
  const dir = mkdtempSync(join(tmpdir(), "exilelens-report-"));
  const file = join(dir, `${opts.name}.sql`);
  writeFileSync(file, sql);
  try {
    const args = [wranglerJs, "d1", "execute", "TELEMETRY_DB"];
    if (opts.env) args.push("--env", opts.env);
    args.push(opts.remote ? "--remote" : "--local", "--json", "--file", file);
    const res = spawnSync(process.execPath, args, { cwd: root, encoding: "utf8", maxBuffer: 64 * 1024 * 1024 });
    if (res.status !== 0) {
      process.stderr.write(res.stderr || res.stdout || "wrangler failed\n");
      return res.status ?? 1;
    }
    const start = res.stdout.indexOf("[");
    const parsed = JSON.parse(res.stdout.slice(start));
    const rows = parsed.flatMap((entry) => entry.results ?? []);
    if (opts.json) console.log(JSON.stringify(rows, null, 2));
    else {
      console.log(`${opts.name} (${opts.remote ? `remote:${opts.env}` : "local"}) - opted-in installations, not users`);
      console.log(formatTable(rows));
    }
    return 0;
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
}

if (process.argv[1] && fileURLToPath(import.meta.url) === process.argv[1]) {
  try {
    process.exitCode = main();
  } catch (err) {
    process.stderr.write(`${err.message}\n`);
    process.exitCode = 1;
  }
}
