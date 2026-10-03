import { env as bindings } from "cloudflare:workers";
import { createHandler } from "../src/app";
import type { Env } from "../src/env";

export const NOW = Date.parse("2026-10-03T12:30:00Z");
export const TODAY = "2026-10-03";
export const ANALYTICS_ID = "0b9d6a40-5c3e-4f1a-9a0b-7c8d9e0f1a2b";
export const DIAGNOSTIC_ID = "9a0b7c8d-1a2b-4c3d-8e5f-0b9d6a405c3e";
export const APP = { version: "0.7.0", channel: "stable", packaged: true, os: "win11" };

export const DATA_TABLES = [
  "ingest_batches",
  "telemetry_events",
  "telemetry_installs",
  "telemetry_install_days",
  "metrics_daily",
  "error_groups",
  "error_group_days",
  "error_group_installs",
  "error_installs",
] as const;

export const db: D1Database = bindings.TELEMETRY_DB;

export function makeEnv(over: Partial<Env> = {}): Env {
  return {
    TELEMETRY_DB: bindings.TELEMETRY_DB,
    ANALYTICS_PEPPER: bindings.ANALYTICS_PEPPER,
    DIAGNOSTIC_PEPPER: bindings.DIAGNOSTIC_PEPPER,
    INGEST_ENABLED: "true",
    ...over,
  };
}

const ctx = { waitUntil() {}, passThroughOnException() {} } as unknown as ExecutionContext;

export function workerAt(nowMs: number) {
  const handler = createHandler(() => nowMs);
  return (request: Request, env: Env = makeEnv()) =>
    handler.fetch!(request as Request<unknown, IncomingRequestCfProperties>, env, ctx) as Promise<Response>;
}

export const fetchAtNow = workerAt(NOW);

interface SendOptions {
  method?: string;
  body?: unknown;
  /** Raw body string (overrides `body`). */
  raw?: string;
  headers?: Record<string, string>;
  env?: Env;
  fetcher?: (r: Request, e?: Env) => Promise<Response>;
}

export async function send(path: string, opts: SendOptions = {}): Promise<Response> {
  const method = opts.method ?? "POST";
  const headers: Record<string, string> = { "content-type": "application/json", ...opts.headers };
  for (const k of Object.keys(headers)) if (headers[k] === "") delete headers[k];
  const init: RequestInit = { method, headers };
  if (method !== "GET") init.body = opts.raw ?? JSON.stringify(opts.body ?? {});
  const request = new Request(`https://api.test${path}`, init);
  return (opts.fetcher ?? fetchAtNow)(request, opts.env ?? makeEnv());
}

export function uuid4(): string {
  return crypto.randomUUID();
}

export function usageEvent(over: Record<string, unknown> = {}) {
  return {
    name: "app_started",
    t: "2026-10-03T12:00Z",
    props: { launch: "normal", previous_session: "clean", pob_configured: true },
    ...over,
  };
}

export function usageBatch(over: Record<string, unknown> = {}) {
  return {
    schema: 1,
    batch_id: uuid4(),
    analytics_id: ANALYTICS_ID,
    app: APP,
    events: [usageEvent()],
    ...over,
  };
}

export function errorReport(over: Record<string, unknown> = {}) {
  return {
    error_code: "EL-WRK-002",
    component: "WRK",
    exception_type: "TimeoutError",
    frames: [
      { module: "exilelens.app.engine", function: "PobWorker.call", line: 412 },
      { module: "stdlib.threading", function: "run" },
    ],
    count: 2,
    first_t: "2026-10-03T10:00Z",
    last_t: "2026-10-03T12:00Z",
    ...over,
  };
}

export function errorBatch(over: Record<string, unknown> = {}) {
  return {
    schema: 1,
    batch_id: uuid4(),
    diagnostic_id: DIAGNOSTIC_ID,
    app: APP,
    reports: [errorReport()],
    ...over,
  };
}

export async function resetDb(): Promise<void> {
  await db.batch(DATA_TABLES.map((t) => db.prepare(`DELETE FROM ${t}`)));
}

export async function all<T = Record<string, unknown>>(sql: string, ...params: unknown[]): Promise<T[]> {
  const res = await db.prepare(sql).bind(...params).all<T>();
  return res.results;
}

export async function count(table: string): Promise<number> {
  const row = await db.prepare(`SELECT COUNT(*) AS n FROM ${table}`).first<{ n: number }>();
  return row?.n ?? 0;
}

/** Every row of every data table, serialised (for privacy scans). */
export async function dumpAll(): Promise<string> {
  const out: Record<string, unknown[]> = {};
  for (const t of DATA_TABLES) out[t] = await all(`SELECT * FROM ${t}`);
  return JSON.stringify(out);
}

/** HMAC computed independently of src/ with Web Crypto, to cross-check stored hashes. */
export async function referenceHmac(pepper: string, domain: string, id: string): Promise<string> {
  const key = await crypto.subtle.importKey("raw", new TextEncoder().encode(pepper), { name: "HMAC", hash: "SHA-256" }, false, ["sign"]);
  const sig = await crypto.subtle.sign("HMAC", key, new TextEncoder().encode(`${domain}:${id}`));
  return [...new Uint8Array(sig)].map((b) => b.toString(16).padStart(2, "0")).join("");
}

export async function referenceSha256(text: string): Promise<string> {
  const d = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(text));
  return [...new Uint8Array(d)].map((b) => b.toString(16).padStart(2, "0")).join("");
}

/** D1 wrapper whose selected operations throw, to simulate quota exhaustion / outages. */
export function brokenDb(real: D1Database, mode: "all" | "writes"): D1Database {
  const boom = () => {
    throw new Error("D1_ERROR: simulated quota exhausted");
  };
  const wrapStmt = (stmt: D1PreparedStatement): D1PreparedStatement =>
    new Proxy(stmt, {
      get(target, prop) {
        if (mode === "all" && (prop === "first" || prop === "run" || prop === "all" || prop === "raw")) return boom;
        if (prop === "bind") return (...a: unknown[]) => wrapStmt(target.bind(...a));
        const v = (target as unknown as Record<string | symbol, unknown>)[prop];
        return typeof v === "function" ? (v as (...a: unknown[]) => unknown).bind(target) : v;
      },
    });
  return new Proxy(real, {
    get(target, prop) {
      if (prop === "batch") return boom;
      if (prop === "prepare") return (sql: string) => wrapStmt(target.prepare(sql));
      const v = (target as unknown as Record<string | symbol, unknown>)[prop];
      return typeof v === "function" ? (v as (...a: unknown[]) => unknown).bind(target) : v;
    },
  });
}

/** D1 wrapper that counts prepared statements (Free plan: 50 queries per invocation). */
export function countingDb(real: D1Database): { db: D1Database; prepared: string[] } {
  const prepared: string[] = [];
  const proxy = new Proxy(real, {
    get(target, prop) {
      if (prop === "prepare") {
        return (sql: string) => {
          prepared.push(sql);
          return target.prepare(sql);
        };
      }
      const v = (target as unknown as Record<string | symbol, unknown>)[prop];
      return typeof v === "function" ? (v as (...a: unknown[]) => unknown).bind(target) : v;
    },
  });
  return { db: proxy, prepared };
}
