import { env as bindings } from "cloudflare:workers";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { patreonEnv, telemetryEnv, type Env } from "../src/env";
import { decryptToken, encryptToken, fromBase64, importEncryptionKey, toBase64, userHmac } from "../src/patreon/crypto";
import { NOW, all, countingDb, db, makeEnv, referenceHmac } from "./helpers";
import {
  MockPatreon,
  callback,
  captureConsole,
  fullLink,
  makePatreonEnv,
  pall,
  pdb,
  pdump,
  poll,
  psend,
  resetPatreonDb,
  startLink,
  workerFor,
} from "./patreon-helpers";

const sources = import.meta.glob("../src/**/*.ts", { query: "?raw", import: "default", eager: true }) as Record<string, string>;
const patreonSources = Object.entries(sources).filter(([p]) => p.includes("/src/patreon/"));
const telemetrySources = Object.entries(sources).filter(([p]) => p.includes("/src/telemetry/"));
const migrations = import.meta.glob("../migrations/**/*.sql", { query: "?raw", import: "default", eager: true }) as Record<string, string>;

const HOUR = 3_600_000;
let mock: MockPatreon;
let f: ReturnType<typeof workerFor>;
let consoleCapture: ReturnType<typeof captureConsole> | undefined;

beforeEach(async () => {
  await resetPatreonDb();
  mock = new MockPatreon();
  f = workerFor(NOW, mock);
});
afterEach(() => consoleCapture?.restore());

describe("token encryption (AES-256-GCM, AAD = link_id)", () => {
  it("roundtrips, uses a fresh random IV every time and stores base64(iv || ciphertext)", async () => {
    const key = (await importEncryptionKey(bindings.TOKEN_ENC_KEY))!;
    const a = await encryptToken(key, "access-token-123", "link-1");
    const b = await encryptToken(key, "access-token-123", "link-1");
    expect(a).not.toBe(b);
    expect(a).not.toContain("access-token-123");
    expect(await decryptToken(key, a, "link-1")).toBe("access-token-123");
    expect(await decryptToken(key, b, "link-1")).toBe("access-token-123");
    const raw = fromBase64(a)!;
    expect(raw.length).toBe(12 + "access-token-123".length + 16);
    expect(raw.slice(0, 12)).not.toEqual(fromBase64(b)!.slice(0, 12));
  });

  it("detects tampering, a different AAD, a different key and garbage", async () => {
    const key = (await importEncryptionKey(bindings.TOKEN_ENC_KEY))!;
    const stored = await encryptToken(key, "secret-value", "link-1");
    const bytes = fromBase64(stored)!;

    for (const index of [0, 12, bytes.length - 1]) {
      const bad = bytes.slice();
      bad[index] = (bad[index] ?? 0) ^ 1;
      await expect(decryptToken(key, toBase64(bad), "link-1")).rejects.toThrow();
    }
    await expect(decryptToken(key, stored, "link-2")).rejects.toThrow(); // different AAD
    const other = (await importEncryptionKey(toBase64(new Uint8Array(32).fill(7))))!;
    await expect(decryptToken(other, stored, "link-1")).rejects.toThrow();
    await expect(decryptToken(key, "!!!not-base64!!!", "link-1")).rejects.toThrow();
    await expect(decryptToken(key, toBase64(bytes.slice(0, 20)), "link-1")).rejects.toThrow();
    await expect(decryptToken(key, "", "link-1")).rejects.toThrow();
  });

  it("the key must be exactly 32 bytes of base64", async () => {
    expect(await importEncryptionKey("AAAA")).toBeNull();
    expect(await importEncryptionKey(toBase64(new Uint8Array(16)))).toBeNull();
    expect(await importEncryptionKey(toBase64(new Uint8Array(33)))).toBeNull();
    expect(await importEncryptionKey("not base64!")).toBeNull();
    expect(await importEncryptionKey(toBase64(new Uint8Array(32)))).not.toBeNull();
  });

  it("stored Patreon tokens decrypt only with their own link_id and never appear in plaintext", async () => {
    await fullLink(f);
    const row = (await pall<{ link_id: string; access_token_enc: string; refresh_token_enc: string }>("SELECT link_id, access_token_enc, refresh_token_enc FROM patreon_links"))[0]!;
    const key = (await importEncryptionKey(bindings.TOKEN_ENC_KEY))!;
    const issued = mock.issuedSecrets();
    expect(issued).toHaveLength(2);
    const access = await decryptToken(key, row.access_token_enc, row.link_id);
    const refresh = await decryptToken(key, row.refresh_token_enc, row.link_id);
    expect(issued).toContain(access);
    expect(issued).toContain(refresh);
    await expect(decryptToken(key, row.access_token_enc, "0".repeat(32))).rejects.toThrow();
    const dump = await pdump();
    for (const secret of issued) expect(dump).not.toContain(secret);
  });

  it("a tampered stored token forces re-authorization instead of a crash or a lease", async () => {
    const { pollBody } = await fullLink(f);
    const row = (await pall<{ access_token_enc: string }>("SELECT access_token_enc FROM patreon_links"))[0]!;
    const bytes = fromBase64(row.access_token_enc)!;
    bytes[20] = (bytes[20] ?? 0) ^ 0xff;
    await pdb.prepare("UPDATE patreon_links SET access_token_enc = ?1").bind(toBase64(bytes)).run();
    const res = await psend("/v1/patreon/entitlement/refresh", { fetcher: workerFor(NOW + 13 * HOUR, mock), token: pollBody.device_token });
    expect(res.status).toBe(401);
    expect(await res.json()).toEqual({ ok: false, code: "reauthorize_required" });
    expect(await pall("SELECT status, access_token_enc, refresh_token_enc FROM patreon_links")).toEqual([
      { status: "reauth_required", access_token_enc: null, refresh_token_enc: null },
    ]);
  });
});

describe("user identifier hashing", () => {
  it("stores HMAC-SHA256(PATREON_ID_PEPPER, 'patreon:' + id) and never the id", async () => {
    await fullLink(f);
    const expected = await referenceHmac(bindings.PATREON_ID_PEPPER, "patreon", "4242");
    expect(await pall("SELECT patreon_user_hmac FROM patreon_links")).toEqual([{ patreon_user_hmac: expected }]);
    expect(await userHmac(bindings.PATREON_ID_PEPPER, "4242")).toBe(expected);
    expect(await pdump()).not.toMatch(/"4242"|4242,/);
  });

  it("matches the owner helper scripts/patreon-id-hmac.mjs (fixed value computed with Node crypto)", async () => {
    // PATREON_ID_PEPPER=<test pepper> node scripts/patreon-id-hmac.mjs 4242
    expect(await userHmac(bindings.PATREON_ID_PEPPER, "4242")).toBe("3e5c5bcfefe6aa92fde8b8797813d7ca6a82bc05b717f84d1e68de1d0ea18d68");
  });

  it("the Patreon pepper is distinct from the usage-statistics peppers and hashes of one id differ", async () => {
    expect(bindings.PATREON_ID_PEPPER).not.toBe(bindings.ANALYTICS_PEPPER);
    expect(bindings.PATREON_ID_PEPPER).not.toBe(bindings.DIAGNOSTIC_PEPPER);
    const p = await userHmac(bindings.PATREON_ID_PEPPER, "4242");
    expect(p).not.toBe(await referenceHmac(bindings.ANALYTICS_PEPPER, "analytics", "4242"));
    expect(p).not.toBe(await referenceHmac(bindings.ANALYTICS_PEPPER, "patreon", "4242"));
  });
});

describe("no secret, token or personal data leaks", () => {
  it("a full lifecycle leaves no token / secret in console output or responses, and no PII in the database", async () => {
    consoleCapture = captureConsole();
    const bodies: string[] = [];
    const record = async (res: Response) => {
      bodies.push(await res.clone().text());
      return res;
    };
    const tap = (fetcher: typeof f): typeof f => async (req, env) => record(await fetcher(req, env));
    const tapped = tap(f);

    // link
    const started = await startLink(tapped);
    await callback(tapped, { code: "the-secret-code-123", state: started.state });
    const first = (await (await poll(tapped, started.session_id, started.poll_token)).json()) as { device_token: string };
    await poll(tapped, started.session_id, started.poll_token);
    // refresh, outage, unauthorized, 404s, unlink
    const dev = first.device_token;
    await psend("/v1/patreon/entitlement/refresh", { fetcher: tap(workerFor(NOW + 100_000, mock)), token: dev });
    mock.identityOverride = () => new Response("down", { status: 500 });
    await psend("/v1/patreon/entitlement/refresh", { fetcher: tap(workerFor(NOW + 13 * HOUR, mock)), token: dev });
    mock.identityOverride = undefined;
    await psend("/v1/patreon/entitlement/refresh", { fetcher: tapped, token: "A".repeat(43) });
    await poll(tapped, "0".repeat(32), "B".repeat(43));
    await psend("/v1/patreon/unlink", { fetcher: tapped, token: dev });
    // failed flow
    mock.tokenOverride = () => new Response("nope", { status: 500 });
    const s2 = await startLink(tapped);
    await callback(tapped, { code: "another-secret-code", state: s2.state });

    const secrets = [
      ...mock.issuedSecrets(),
      bindings.PATREON_CLIENT_SECRET,
      bindings.TOKEN_ENC_KEY,
      bindings.ENTITLEMENT_SIGNING_KEY,
      bindings.PATREON_ID_PEPPER,
      "the-secret-code-123",
      "another-secret-code",
    ];
    const logged = consoleCapture.lines.join("\n");
    expect(logged.length).toBeGreaterThan(0);
    const everySecretLike = [...secrets, dev, started.poll_token, started.state, s2.poll_token, s2.state, "Bearer", "authorization"];
    for (const s of everySecretLike) expect(logged, `log leaks ${s.slice(0, 8)}`).not.toContain(s);
    expect(logged).not.toMatch(/session_id=|state=|code=/);
    for (const line of consoleCapture.lines) {
      const parsed = JSON.parse(line) as Record<string, unknown>;
      expect(Object.keys(parsed).every((k) => ["route", "status", "ms", "code"].includes(k))).toBe(true);
    }

    const responses = bodies.join("\n");
    for (const s of secrets) expect(responses, `response leaks ${s.slice(0, 8)}`).not.toContain(s);
    expect(responses).not.toMatch(/secret|@example\.com|Secret/i);
    // the device token was delivered once, in exactly one response
    expect(bodies.filter((b) => b.includes(dev))).toHaveLength(1);
    expect(bodies.filter((b) => b.includes(started.poll_token))).toHaveLength(1);
  });

  it("the database contains no plaintext tokens, emails, names or profile text", async () => {
    const { pollBody, started } = await fullLink(f);
    const dump = await pdump();
    for (const s of [...mock.issuedSecrets(), pollBody.device_token!, started.poll_token, started.state, "the-code"]) {
      expect(dump).not.toContain(s);
    }
    expect(dump).not.toMatch(/@|example\.com|Secret|secret|about|full_name|email/);
    // exactly the documented columns exist, nothing like an email / name column
    for (const table of ["link_sessions", "patreon_links", "devices", "link_metrics_daily", "entitlement_refresh_daily"]) {
      const cols = (await pall<{ name: string }>(`SELECT name FROM pragma_table_info('${table}')`)).map((c) => c.name);
      expect(cols.join(","), table).not.toMatch(/email|name|address|ip\b|user_agent|ua\b/);
    }
    const tables = (await pall<{ name: string }>("SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE '_cf_%' AND name NOT LIKE 'd1_%' AND name NOT LIKE 'sqlite_%'")).map((t) => t.name).sort();
    expect(tables).toEqual(["devices", "entitlement_refresh_daily", "link_metrics_daily", "link_sessions", "patreon_links"]);
  });

  it("metric tables hold only day / outcome / count", async () => {
    await fullLink(f);
    for (const t of ["link_metrics_daily", "entitlement_refresh_daily"]) {
      const cols = (await pall<{ name: string }>(`SELECT name FROM pragma_table_info('${t}')`)).map((c) => c.name);
      expect(cols).toEqual(["day", "outcome", "count"]);
    }
  });

  it("every Patreon JSON response is no-store, has no CORS headers and unknown routes are plain 404s", async () => {
    const responses = [
      await psend("/v1/patreon/link/start", { fetcher: f }),
      await psend("/v1/patreon/link/start", { fetcher: f, method: "GET" }),
      await poll(f, "0".repeat(32), "A".repeat(43)),
      await psend("/v1/patreon/entitlement/refresh", { fetcher: f, token: "A".repeat(43) }),
      await psend("/v1/patreon/entitlement/refresh", { fetcher: f, raw: "{" }),
      await psend("/v1/patreon/nope", { fetcher: f, method: "GET" }),
      await psend("/v1/patreon/unlink", { fetcher: f }),
    ];
    for (const res of responses) {
      expect(res.headers.get("cache-control")).toBe("no-store");
      expect(res.headers.get("access-control-allow-origin")).toBeNull();
    }
    expect(responses[5]!.status).toBe(404);
    expect(responses[1]!.status).toBe(405);
  });
});

describe("D1 Free budget (50 queries per invocation)", () => {
  it("each Patreon request uses only a handful of queries", async () => {
    const counted = countingDb(pdb);
    const env = makePatreonEnv({ PATREON_DB: counted.db });
    const mark = () => counted.prepared.length;
    let before = mark();
    const started = await startLink(f, env);
    expect(mark() - before).toBeLessThanOrEqual(3);
    before = mark();
    await callback(f, { code: "c", state: started.state }, env);
    expect(mark() - before).toBeLessThanOrEqual(12);
    before = mark();
    const res = await poll(f, started.session_id, started.poll_token, env);
    expect(res.status).toBe(200);
    expect(mark() - before).toBeLessThanOrEqual(8);
  });
});

describe("separation of the two databases", () => {
  it("patreonEnv() is an explicit allow-list: no TELEMETRY_DB, no usage-statistics pepper, no unknown keys", () => {
    const full = {
      ...makePatreonEnv({ RL_LINK: { limit: async () => ({ success: true }) }, RL_INGEST: { limit: async () => ({ success: true }) }, PATREON_OVERRIDE_USER_HMACS: "{}" }),
      SOMETHING_ELSE: "z",
    } as unknown as Env;
    const narrowed = patreonEnv(full);
    expect(Object.keys(narrowed).sort()).toEqual(
      [
        "ENTITLEMENT_KEY_ID",
        "ENTITLEMENT_POLICY",
        "ENTITLEMENT_SIGNING_KEY",
        "LEASE_ISSUANCE_ENABLED",
        "PATREON_API_BASE",
        "PATREON_CLIENT_ID",
        "PATREON_CLIENT_SECRET",
        "PATREON_DB",
        "PATREON_ID_PEPPER",
        "PATREON_OVERRIDE_USER_HMACS",
        "PATREON_LINK_ENABLED",
        "PATREON_REDIRECT_URI",
        "RL_LINK",
        "TOKEN_ENC_KEY",
      ].sort(),
    );
    expect(JSON.stringify(Object.keys(narrowed))).not.toMatch(/TELEMETRY|ANALYTICS|DIAGNOSTIC|INGEST|SOMETHING_ELSE/);
  });

  it("telemetryEnv() ignores every Patreon key, including the new ones", () => {
    const full = makePatreonEnv({ RL_LINK: { limit: async () => ({ success: true }) }, PATREON_OVERRIDE_USER_HMACS: "{}" });
    const keys = Object.keys(telemetryEnv(full)).sort();
    expect(keys).toEqual(["ANALYTICS_PEPPER", "DIAGNOSTIC_PEPPER", "INGEST_ENABLED", "TELEMETRY_DB"]);
    expect(keys.join(",")).not.toMatch(/PATREON|TOKEN|ENTITLEMENT|RL_LINK|LEASE/);
  });

  it("serving Patreon requests never reads a telemetry binding from the Worker env", async () => {
    const touched: string[] = [];
    const watched = /TELEMETRY|ANALYTICS|DIAGNOSTIC|INGEST/;
    const guarded = new Proxy(makePatreonEnv() as unknown as Record<string, unknown>, {
      get(target, prop) {
        if (typeof prop === "string" && watched.test(prop)) touched.push(prop);
        return target[prop as string];
      },
      has(target, prop) {
        if (typeof prop === "string" && watched.test(prop)) touched.push(prop);
        return prop in target;
      },
    }) as unknown as Env;
    const started = await startLink(f, guarded);
    await callback(f, { code: "c", state: started.state }, guarded);
    const res = await poll(f, started.session_id, started.poll_token, guarded);
    const body = (await res.json()) as { device_token: string };
    expect(body.device_token).toBeTruthy();
    await psend("/v1/patreon/entitlement/refresh", { fetcher: workerFor(NOW + 120_000, mock), token: body.device_token, env: guarded });
    await psend("/v1/patreon/unlink", { fetcher: f, token: body.device_token, env: guarded });
    expect(touched).toEqual([]);
  });

  it("Patreon endpoints work even if the telemetry binding is unusable, and never write to it", async () => {
    const before = JSON.stringify(await all("SELECT name FROM sqlite_master"));
    const boom = new Proxy({}, { get: () => { throw new Error("telemetry db must not be touched"); } }) as unknown as D1Database;
    const env = makePatreonEnv({ TELEMETRY_DB: boom });
    const { pollBody } = await fullLink(f, "code-1", env);
    expect(pollBody.status).toBe("linked");
    expect(JSON.stringify(await all("SELECT name FROM sqlite_master"))).toBe(before);
  });

  it("each database only has its own tables", async () => {
    const names = async (d: D1Database) =>
      (await d.prepare("SELECT name FROM sqlite_master WHERE type = 'table'").all<{ name: string }>()).results.map((r) => r.name);
    const tele = await names(db);
    const pat = await names(pdb);
    expect(tele).toContain("telemetry_events");
    expect(tele.filter((n) => ["link_sessions", "patreon_links", "devices", "link_metrics_daily", "entitlement_refresh_daily"].includes(n))).toEqual([]);
    expect(pat).toContain("patreon_links");
    expect(pat.filter((n) => /^(telemetry_|error_|ingest_|metrics_daily)/.test(n))).toEqual([]);
  });

  it("source grep, both directions: no imports, bindings or table names cross the boundary", () => {
    expect(patreonSources.length).toBeGreaterThanOrEqual(10);
    expect(telemetrySources.length).toBeGreaterThanOrEqual(7);
    const patreonTables = ["link_sessions", "patreon_links", "link_metrics_daily", "entitlement_refresh_daily"];
    const telemetryTables = ["telemetry_events", "telemetry_installs", "telemetry_install_days", "metrics_daily", "error_groups", "error_group_days", "error_group_installs", "error_installs", "ingest_batches"];
    for (const [path, text] of patreonSources) {
      expect(text, path).not.toMatch(/from\s+["'][^"']*telemetry/i);
      expect(text, path).not.toMatch(/import\(\s*["'][^"']*telemetry/i);
      expect(text, path).not.toMatch(/TELEMETRY_|ANALYTICS_PEPPER|DIAGNOSTIC_PEPPER|INGEST_ENABLED|RL_INGEST|telemetryEnv/);
      expect(text, path).not.toMatch(/ATTACH\s+DATABASE/i);
      for (const t of telemetryTables) expect(text, `${path} mentions ${t}`).not.toMatch(new RegExp(`\\b${t}\\b`));
    }
    for (const [path, text] of telemetrySources) {
      expect(text, path).not.toMatch(/patreon/i);
      expect(text, path).not.toMatch(/PATREON_|TOKEN_ENC_KEY|ENTITLEMENT_|patreonEnv|RL_LINK|LEASE_ISSUANCE/);
      for (const t of patreonTables) expect(text, `${path} mentions ${t}`).not.toMatch(new RegExp(`\\b${t}\\b`));
      expect(text, path).not.toMatch(/\bdevices\b/);
    }
  });

  it("migrations are separate files that never reference the other database", () => {
    const tele = Object.entries(migrations).filter(([p]) => p.includes("/telemetry/"));
    const pat = Object.entries(migrations).filter(([p]) => p.includes("/patreon/"));
    expect(tele.length).toBeGreaterThan(0);
    expect(pat.length).toBeGreaterThan(0);
    for (const [p, sql] of pat) {
      expect(sql, p).not.toMatch(/TELEMETRY_DB|telemetry_events|telemetry_installs|ATTACH/i);
    }
    for (const [p, sql] of tele) expect(sql, p).not.toMatch(/patreon_links|link_sessions|devices\b/i);
  });
});

describe("telemetry still works with the full Patreon environment present", () => {
  it("POST /v1/telemetry/batch is unaffected", async () => {
    const res = await psend("/v1/telemetry/batch", {
      fetcher: f,
      env: { ...makeEnv(), ...makePatreonEnv() },
      body: {
        schema: 1,
        batch_id: crypto.randomUUID(),
        analytics_id: crypto.randomUUID(),
        app: { version: "0.7.0", channel: "stable", packaged: true, os: "win11" },
        events: [{ name: "app_started", t: "2026-10-03T12:00Z", props: { launch: "normal", previous_session: "clean", pob_configured: true } }],
      },
    });
    expect(res.status).toBe(202);
  });
});
