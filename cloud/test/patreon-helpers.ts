/**
 * Test helpers for the Patreon part: a mock Patreon (injected `fetch`), env builder,
 * and the OAuth / poll client flow. NO real Patreon call is ever made.
 */
import { env as bindings } from "cloudflare:workers";
import { vi } from "vitest";
import { createHandler } from "../src/app";
import type { Env } from "../src/env";
import { NOW } from "./helpers";

export const pdb: D1Database = bindings.PATREON_DB;
export const CAMPAIGN = "1234567";
export const REDIRECT = "https://api.test/v1/patreon/oauth/callback";
export const CLIENT_ID = "test-client-id";
export const TEST_PUBLIC_KEY_B64 = "7uT5nCI2848DtVlDbBEUsIM30CjxIt9H1e0eD9hBjr0=";

export const PATREON_TABLES = [
  "link_sessions",
  "patreon_links",
  "devices",
  "link_metrics_daily",
  "entitlement_refresh_daily",
] as const;

export function policyJson(over: Record<string, unknown> = {}): string {
  return JSON.stringify({
    policy_version: 1,
    campaign_id: CAMPAIGN,
    rules: [{ when: "any_active_paid_tier", capabilities: ["seamless_updates"] }],
    allow_gifted: true,
    allow_free_trial: true,
    override_user_hmacs: {},
    ...over,
  });
}

export function makePatreonEnv(over: Partial<Env> = {}): Env {
  return {
    TELEMETRY_DB: bindings.TELEMETRY_DB,
    ANALYTICS_PEPPER: bindings.ANALYTICS_PEPPER,
    DIAGNOSTIC_PEPPER: bindings.DIAGNOSTIC_PEPPER,
    INGEST_ENABLED: "true",
    PATREON_DB: bindings.PATREON_DB,
    PATREON_CLIENT_SECRET: bindings.PATREON_CLIENT_SECRET,
    ENTITLEMENT_SIGNING_KEY: bindings.ENTITLEMENT_SIGNING_KEY,
    TOKEN_ENC_KEY: bindings.TOKEN_ENC_KEY,
    PATREON_ID_PEPPER: bindings.PATREON_ID_PEPPER,
    PATREON_CLIENT_ID: CLIENT_ID,
    PATREON_REDIRECT_URI: REDIRECT,
    PATREON_API_BASE: "https://www.patreon.com",
    PATREON_LINK_ENABLED: "true",
    LEASE_ISSUANCE_ENABLED: "true",
    ENTITLEMENT_KEY_ID: "exilelens-entitlement-test-1",
    ENTITLEMENT_POLICY: policyJson(),
    ...over,
  };
}

// ---------------------------------------------------------------------------
// Mock Patreon
// ---------------------------------------------------------------------------

export interface IdentitySpec {
  userId: string;
  campaignId?: string;
  patron_status?: string | null;
  is_gifted?: boolean;
  is_free_trial?: boolean;
  tiers?: { id: string; cents: number }[];
  /** No membership resource at all. */
  noMembership?: boolean;
}

export const PAID: IdentitySpec = { userId: "4242", patron_status: "active_patron", tiers: [{ id: "9001", cents: 500 }] };

/** A Patreon identity document that also carries personal data we must never keep. */
export function identityPayload(spec: IdentitySpec): unknown {
  const campaignId = spec.campaignId ?? CAMPAIGN;
  const tiers = spec.tiers ?? [];
  const included: unknown[] = [];
  if (!spec.noMembership) {
    included.push({
      id: "member-1",
      type: "member",
      attributes: {
        patron_status: spec.patron_status === undefined ? "active_patron" : spec.patron_status,
        is_gifted: spec.is_gifted ?? false,
        is_free_trial: spec.is_free_trial ?? false,
        email: "member-secret@example.com",
        full_name: "Secret Member Name",
      },
      relationships: {
        campaign: { data: { id: campaignId, type: "campaign" } },
        currently_entitled_tiers: { data: tiers.map((t) => ({ id: t.id, type: "tier" })) },
      },
    });
    for (const t of tiers) included.push({ id: t.id, type: "tier", attributes: { amount_cents: t.cents } });
    included.push({ id: campaignId, type: "campaign" });
  }
  return {
    data: {
      id: spec.userId,
      type: "user",
      attributes: { email: "user-secret@example.com", full_name: "Secret User Name", about: "secret about text" },
      relationships: { memberships: { data: spec.noMembership ? [] : [{ id: "member-1", type: "member" }] } },
    },
    included,
    links: { self: `https://www.patreon.com/api/oauth2/v2/user/${spec.userId}` },
  };
}

export interface MockCall {
  kind: "token" | "identity" | "other";
  grant?: string;
  url: string;
  hadAuthorization?: boolean;
  body?: string;
}

export class MockPatreon {
  calls: MockCall[] = [];
  /** Identity returned for any freshly exchanged code unless `byCode` has an entry. */
  defaultIdentity: IdentitySpec = PAID;
  byCode = new Map<string, IdentitySpec>();
  /** Respond to token requests (return undefined to fall through to the default behaviour). */
  tokenOverride?: (grant: string, form: URLSearchParams) => Response | undefined | Promise<Response | undefined>;
  identityOverride?: (accessToken: string, url: string) => Response | undefined | Promise<Response | undefined>;
  /** Mutable per-user identity, looked up when /identity is called (so tests can change membership over time). */
  identities = new Map<string, IdentitySpec>();
  expiresIn: number | undefined = 2_592_000;

  private n = 0;
  private accessToUser = new Map<string, string>();
  private refreshToUser = new Map<string, string>();

  get tokenCalls(): MockCall[] {
    return this.calls.filter((c) => c.kind === "token");
  }
  get identityCalls(): MockCall[] {
    return this.calls.filter((c) => c.kind === "identity");
  }

  /** Every secret string the mock ever handed out (for log / response / DB scans). */
  issuedSecrets(): string[] {
    return [...this.accessToUser.keys(), ...this.refreshToUser.keys()];
  }

  private issue(userId: string): Response {
    this.n += 1;
    const access = `at_secret_${this.n}_${crypto.randomUUID()}`;
    const refresh = `rt_secret_${this.n}_${crypto.randomUUID()}`;
    this.accessToUser.set(access, userId);
    this.refreshToUser.set(refresh, userId);
    const body: Record<string, unknown> = { access_token: access, refresh_token: refresh, scope: "identity", token_type: "Bearer" };
    if (this.expiresIn !== undefined) body.expires_in = this.expiresIn;
    return new Response(JSON.stringify(body), { status: 200, headers: { "content-type": "application/json" } });
  }

  fetch = async (input: string, init?: RequestInit): Promise<Response> => {
    const url = String(input);
    if (url === "https://www.patreon.com/api/oauth2/token") {
      const form = new URLSearchParams(String(init?.body ?? ""));
      const grant = form.get("grant_type") ?? "";
      this.calls.push({ kind: "token", grant, url, body: String(init?.body ?? "") });
      const forced = await this.tokenOverride?.(grant, form);
      if (forced) return forced;
      if (grant === "authorization_code") {
        const spec = this.byCode.get(form.get("code") ?? "") ?? this.defaultIdentity;
        this.identities.set(spec.userId, spec);
        return this.issue(spec.userId);
      }
      if (grant === "refresh_token") {
        const rt = form.get("refresh_token") ?? "";
        const user = this.refreshToUser.get(rt);
        if (user === undefined) {
          return new Response(JSON.stringify({ error: "invalid_grant" }), { status: 400, headers: { "content-type": "application/json" } });
        }
        this.refreshToUser.delete(rt); // single use
        return this.issue(user);
      }
      return new Response(JSON.stringify({ error: "unsupported_grant_type" }), { status: 400 });
    }
    if (url.startsWith("https://www.patreon.com/api/oauth2/v2/identity")) {
      const auth = (init?.headers as Record<string, string> | undefined)?.authorization ?? "";
      this.calls.push({ kind: "identity", url, hadAuthorization: auth.startsWith("Bearer ") });
      const access = auth.replace(/^Bearer /, "");
      const forced = await this.identityOverride?.(access, url);
      if (forced) return forced;
      const user = this.accessToUser.get(access);
      if (user === undefined) return new Response(JSON.stringify({ errors: [{ code: 1 }] }), { status: 401 });
      const spec = this.identities.get(user) ?? this.defaultIdentity;
      return new Response(JSON.stringify(identityPayload(spec)), { status: 200, headers: { "content-type": "application/json" } });
    }
    this.calls.push({ kind: "other", url });
    return new Response("unexpected", { status: 500 });
  };
}

// ---------------------------------------------------------------------------
// Client flow
// ---------------------------------------------------------------------------

const ctx = { waitUntil() {}, passThroughOnException() {} } as unknown as ExecutionContext;

export function workerFor(nowMs: number, mock: MockPatreon) {
  const handler = createHandler(() => nowMs, mock.fetch);
  return (request: Request, env: Env = makePatreonEnv()) =>
    handler.fetch!(request as Request<unknown, IncomingRequestCfProperties>, env, ctx) as Promise<Response>;
}

export type Fetcher = (request: Request, env?: Env) => Promise<Response>;

export interface PSendOptions {
  method?: string;
  body?: unknown;
  raw?: string;
  token?: string;
  headers?: Record<string, string>;
  env?: Env;
  fetcher: Fetcher;
  noContentType?: boolean;
}

export async function psend(path: string, opts: PSendOptions): Promise<Response> {
  const method = opts.method ?? "POST";
  const headers: Record<string, string> = { ...opts.headers };
  if (!opts.noContentType && method !== "GET" && method !== "DELETE" && headers["content-type"] === undefined) headers["content-type"] = "application/json";
  if (opts.token !== undefined) headers.authorization = `Bearer ${opts.token}`;
  const init: RequestInit = { method, headers };
  if (method === "POST") init.body = opts.raw ?? JSON.stringify(opts.body ?? { schema: 1 });
  return opts.fetcher(new Request(`https://api.test${path}`, init), opts.env ?? makePatreonEnv());
}

export interface Started {
  session_id: string;
  poll_token: string;
  authorize_url: string;
  expires_at: number;
  state: string;
}

export async function startLink(fetcher: Fetcher, env?: Env): Promise<Started> {
  const res = await psend("/v1/patreon/link/start", { fetcher, body: { schema: 1 }, env });
  if (res.status !== 201) throw new Error(`start failed: ${res.status} ${await res.text()}`);
  const body = (await res.json()) as Omit<Started, "state">;
  const state = new URL(body.authorize_url).searchParams.get("state");
  if (!state) throw new Error("no state in authorize_url");
  return { ...body, state };
}

export function callbackRequest(params: Record<string, string>): Request {
  const u = new URL("https://api.test/v1/patreon/oauth/callback");
  for (const [k, v] of Object.entries(params)) u.searchParams.set(k, v);
  return new Request(u, { method: "GET" });
}

export async function callback(fetcher: Fetcher, params: Record<string, string>, env?: Env): Promise<Response> {
  return fetcher(callbackRequest(params), env ?? makePatreonEnv());
}

export async function poll(fetcher: Fetcher, sessionId: string, pollToken: string | undefined, env?: Env): Promise<Response> {
  return psend(`/v1/patreon/link/status?session_id=${sessionId}`, { method: "GET", fetcher, token: pollToken, env });
}

export interface Linked {
  started: Started;
  pollBody: {
    ok: boolean;
    status: string;
    device_token?: string;
    device_id?: string;
    lease?: { lease: Record<string, unknown>; signature: string };
  };
}

/** start -> callback -> first poll. Returns the credentials delivered by the first poll. */
export async function fullLink(fetcher: Fetcher, code = "code-1", env?: Env): Promise<Linked> {
  const started = await startLink(fetcher, env);
  const cb = await callback(fetcher, { code, state: started.state }, env);
  if (cb.status !== 200) throw new Error(`callback failed: ${cb.status}`);
  const res = await poll(fetcher, started.session_id, started.poll_token, env);
  return { started, pollBody: (await res.json()) as Linked["pollBody"] };
}

export async function resetPatreonDb(): Promise<void> {
  await pdb.batch(PATREON_TABLES.map((t) => pdb.prepare(`DELETE FROM ${t}`)));
}

export async function pall<T = Record<string, unknown>>(sql: string, ...params: unknown[]): Promise<T[]> {
  const res = await pdb.prepare(sql).bind(...params).all<T>();
  return res.results;
}

export async function pcount(table: string): Promise<number> {
  const row = await pdb.prepare(`SELECT COUNT(*) AS n FROM ${table}`).first<{ n: number }>();
  return row?.n ?? 0;
}

export async function pdump(): Promise<string> {
  const out: Record<string, unknown[]> = {};
  for (const t of PATREON_TABLES) out[t] = await pall(`SELECT * FROM ${t}`);
  return JSON.stringify(out);
}

export const nowS = Math.floor(NOW / 1000);

/** Capture every console.log / error / warn / info / debug call as one string array. */
export function captureConsole(): { lines: string[]; restore: () => void } {
  const lines: string[] = [];
  const spies = (["log", "error", "warn", "info", "debug"] as const).map((m) =>
    vi.spyOn(console, m).mockImplementation((...args: unknown[]) => {
      lines.push(args.map((a) => (typeof a === "string" ? a : JSON.stringify(a))).join(" "));
    }),
  );
  return { lines, restore: () => spies.forEach((s) => s.mockRestore()) };
}
