import { beforeEach, describe, expect, it } from "vitest";
import { LEASE_DOMAIN_PREFIX, canonicalJson } from "../src/patreon/lease";
import { fromBase64 } from "../src/patreon/crypto";
import { NOW, countingDb } from "./helpers";
import {
  MockPatreon,
  PAID,
  TEST_PUBLIC_KEY_B64,
  fullLink,
  makePatreonEnv,
  nowS,
  pall,
  pcount,
  pdb,
  pdump,
  psend,
  resetPatreonDb,
  workerFor,
  type Fetcher,
} from "./patreon-helpers";

let mock: MockPatreon;
let f: ReturnType<typeof workerFor>;
const HOUR = 3_600_000;

beforeEach(async () => {
  await resetPatreonDb();
  mock = new MockPatreon();
  f = workerFor(NOW, mock);
});

interface Device {
  token: string;
  id: string;
}

async function linkDevice(fetcher: Fetcher = f, code = "code-1"): Promise<Device> {
  const { pollBody } = await fullLink(fetcher, code);
  return { token: pollBody.device_token!, id: pollBody.device_id! };
}

const refresh = (fetcher: Fetcher, token: string | undefined, body: unknown = { schema: 1 }, env = makePatreonEnv()) =>
  psend("/v1/patreon/entitlement/refresh", { fetcher, token, body, env });

async function verifyLease(signed: { lease: Record<string, unknown>; signature: string }): Promise<boolean> {
  const pub = await crypto.subtle.importKey("raw", fromBase64(TEST_PUBLIC_KEY_B64)!, { name: "Ed25519" }, false, ["verify"]);
  return crypto.subtle.verify({ name: "Ed25519" }, pub, fromBase64(signed.signature)!, new TextEncoder().encode(LEASE_DOMAIN_PREFIX + canonicalJson(signed.lease)));
}

const metrics = async () =>
  Object.fromEntries((await pall<{ outcome: string; count: number }>("SELECT outcome, count FROM entitlement_refresh_daily")).map((r) => [r.outcome, r.count]));

describe("POST /v1/patreon/entitlement/refresh", () => {
  it("issues a signed lease with exact timings (24 h refresh, 7 d expiry) from a fresh verification", async () => {
    const dev = await linkDevice();
    const later = workerFor(NOW + 120_000, mock);
    const callsBefore = mock.calls.length;
    const res = await refresh(later, dev.token, { schema: 1, client_version: "0.7.0b2" });
    expect(res.status).toBe(200);
    expect(res.headers.get("cache-control")).toBe("no-store");
    const body = (await res.json()) as { ok: boolean; lease: { lease: Record<string, unknown>; signature: string }; next_refresh_after_s: number; server_time: number };
    expect(Object.keys(body).sort()).toEqual(["lease", "next_refresh_after_s", "ok", "server_time"]);
    const t = nowS + 120;
    expect(body.server_time).toBe(t);
    expect(body.next_refresh_after_s).toBe(86_400);
    expect(body.lease.lease).toMatchObject({
      schema: 1,
      kid: "exilelens-entitlement-test-1",
      sub: dev.id,
      capabilities: ["seamless_updates"],
      issued_at: t,
      refresh_after: t + 86_400,
      expires_at: t + 604_800,
      policy_version: 1,
    });
    expect(body.lease.lease.lease_id).toMatch(/^[0-9a-f]{32}$/);
    expect(Object.keys(body.lease.lease)).toHaveLength(9);
    expect(await verifyLease(body.lease)).toBe(true);
    expect(mock.calls.length).toBe(callsBefore); // verification at link time was fresh: no Patreon call
    expect(await pall("SELECT last_refresh_at, last_lease_expires_at, client_version FROM devices")).toEqual([
      { last_refresh_at: t, last_lease_expires_at: t + 604_800, client_version: "0.7.0b2" },
    ]);
    expect(await metrics()).toEqual({ ok: 1 });
    // each lease has a fresh lease_id
    const again = (await (await refresh(workerFor(NOW + 200_000, mock), dev.token)).json()) as typeof body;
    expect(again.lease.lease.lease_id).not.toBe(body.lease.lease.lease_id);
  });

  it("unknown / missing / malformed device token: 401 device_unknown", async () => {
    for (const token of [undefined, "A".repeat(43), "short"]) {
      const res = await refresh(f, token);
      expect(res.status).toBe(401);
      expect(await res.json()).toEqual({ ok: false, code: "device_unknown" });
    }
    expect(await metrics()).toEqual({ device_unknown: 3 });
    expect(mock.calls).toEqual([]);
  });

  it("validates the body", async () => {
    const dev = await linkDevice();
    const later = workerFor(NOW + 120_000, mock);
    expect((await refresh(later, dev.token, { schema: 1, nope: 1 })).status).toBe(400);
    expect((await refresh(later, dev.token, { schema: 2 })).status).toBe(422);
    expect((await refresh(later, dev.token, {})).status).toBe(400);
    expect((await refresh(later, dev.token, { schema: 1, client_version: "x y;z" })).status).toBe(400);
    expect((await refresh(later, dev.token, { schema: 1, client_version: 5 })).status).toBe(400);
    expect((await psend("/v1/patreon/entitlement/refresh", { fetcher: later, token: dev.token, raw: "{}", headers: { "content-type": "text/plain" } })).status).toBe(415);
    expect((await psend("/v1/patreon/entitlement/refresh", { fetcher: later, token: dev.token, method: "GET" })).status).toBe(405);
    expect((await refresh(later, dev.token)).status).toBe(200); // none of the above burned the throttle
  });

  it("throttles each device to one refresh per 60 seconds (429 + Retry-After)", async () => {
    const dev = await linkDevice();
    expect((await refresh(workerFor(NOW + 100_000, mock), dev.token)).status).toBe(200);
    const res = await refresh(workerFor(NOW + 130_000, mock), dev.token);
    expect(res.status).toBe(429);
    expect(res.headers.get("retry-after")).toBe("30");
    expect(await res.json()).toEqual({ ok: false, code: "rate_limited" });
    expect((await refresh(workerFor(NOW + 160_000, mock), dev.token)).status).toBe(200);
    expect(await metrics()).toEqual({ ok: 2, rate_limited: 1 });
  });

  it("re-verifies with Patreon once the cached verification is older than 12 h, and follows membership changes", async () => {
    const dev = await linkDevice();
    const calls0 = mock.identityCalls.length;
    expect((await refresh(workerFor(NOW + 11 * HOUR, mock), dev.token)).status).toBe(200);
    expect(mock.identityCalls.length).toBe(calls0); // 11 h: cached

    const res = await refresh(workerFor(NOW + 13 * HOUR, mock), dev.token);
    expect(res.status).toBe(200);
    expect(mock.identityCalls.length).toBe(calls0 + 1);

    // membership lapses -> lease without capabilities, outcome not_eligible
    mock.identities.set(PAID.userId, { ...PAID, patron_status: "former_patron", tiers: [] });
    const lapsed = (await (await refresh(workerFor(NOW + 26 * HOUR, mock), dev.token)).json()) as { lease: { lease: { capabilities: string[] } } };
    expect(lapsed.lease.lease.capabilities).toEqual([]);
    expect(await pall("SELECT last_capabilities FROM patreon_links")).toEqual([{ last_capabilities: "[]" }]);
    expect((await metrics()).not_eligible).toBe(1);

    // empty capabilities are re-checked after only 1 h (upgrade becomes visible quickly)
    mock.identities.set(PAID.userId, PAID);
    const calls = mock.identityCalls.length;
    const notYet = await refresh(workerFor(NOW + 26 * HOUR + 30 * 60_000 + 60_000, mock), dev.token);
    expect(mock.identityCalls.length).toBe(calls); // 31 min: still cached
    expect(((await notYet.json()) as { lease: { lease: { capabilities: string[] } } }).lease.lease.capabilities).toEqual([]);
    const upgraded = (await (await refresh(workerFor(NOW + 26 * HOUR + 70 * 60_000, mock), dev.token)).json()) as { lease: { lease: { capabilities: string[] } } };
    expect(mock.identityCalls.length).toBe(calls + 1);
    expect(upgraded.lease.lease.capabilities).toEqual(["seamless_updates"]);
  });

  it("a policy_version bump forces re-verification and is stamped into the lease", async () => {
    const dev = await linkDevice();
    const calls = mock.identityCalls.length;
    const env2 = makePatreonEnv({ ENTITLEMENT_POLICY: JSON.stringify({ policy_version: 2, campaign_id: "1234567", rules: [{ when: "any_active_paid_tier", capabilities: ["seamless_updates"] }] }) });
    const res = await refresh(workerFor(NOW + 120_000, mock), dev.token, { schema: 1 }, env2);
    const body = (await res.json()) as { lease: { lease: { policy_version: number } } };
    expect(body.lease.lease.policy_version).toBe(2);
    expect(mock.identityCalls.length).toBe(calls + 1);
    expect(await pall("SELECT policy_version FROM patreon_links")).toEqual([{ policy_version: 2 }]);
  });

  it("refreshes the Patreon access token when it expires within 3 days and stores the NEW refresh token", async () => {
    const dev = await linkDevice();
    await pdb.prepare("UPDATE patreon_links SET token_expires_at = ?1").bind(nowS + 86_400).run();
    const before = (await pall<{ access_token_enc: string; refresh_token_enc: string; token_version: number }>("SELECT access_token_enc, refresh_token_enc, token_version FROM patreon_links"))[0]!;
    const res = await refresh(workerFor(NOW + 13 * HOUR, mock), dev.token);
    expect(res.status).toBe(200);
    const grants = mock.tokenCalls.map((c) => c.grant);
    expect(grants).toEqual(["authorization_code", "refresh_token"]);
    const after = (await pall<{ access_token_enc: string; refresh_token_enc: string; token_version: number; token_expires_at: number; refresh_lock_until: number | null }>("SELECT * FROM patreon_links"))[0]!;
    expect(after.access_token_enc).not.toBe(before.access_token_enc);
    expect(after.refresh_token_enc).not.toBe(before.refresh_token_enc);
    expect(after.token_version).toBe(before.token_version + 1);
    expect(after.token_expires_at).toBe(nowS + 13 * 3600 + 2_592_000);
    expect(after.refresh_lock_until).toBeNull();
    // the stored token is the rotated one: the next rotation succeeds (single-use tokens would give invalid_grant otherwise)
    await pdb.prepare("UPDATE patreon_links SET token_expires_at = ?1").bind(nowS + 13 * 3600 + 86_400).run();
    expect((await refresh(workerFor(NOW + 27 * HOUR, mock), dev.token)).status).toBe(200);
    expect(mock.tokenCalls.map((c) => c.grant)).toEqual(["authorization_code", "refresh_token", "refresh_token"]);
    expect(await pall("SELECT status FROM patreon_links")).toEqual([{ status: "active" }]);
  });

  it("Patreon outage on the identity call: 503 + Retry-After, NO lease, nothing revoked", async () => {
    const dev = await linkDevice();
    const before = await pall("SELECT last_lease_expires_at FROM devices");
    for (const [name, forced] of [
      ["5xx", () => new Response("oops", { status: 503 })],
      ["429", () => new Response(JSON.stringify({ retry_after_seconds: 17 }), { status: 429 })],
      ["network", () => { throw new TypeError("net"); }],
      ["junk", () => new Response("<html>", { status: 200 })],
    ] as const) {
      mock.identityOverride = forced;
      const res = await refresh(workerFor(NOW + 13 * HOUR + (name.length + 70) * 1000 * 5, mock), dev.token);
      expect(res.status, name).toBe(503);
      expect(await res.json(), name).toEqual({ ok: false, code: "patreon_unavailable" });
      expect(Number(res.headers.get("retry-after")), name).toBeGreaterThanOrEqual(5);
      if (name === "429") expect(res.headers.get("retry-after")).toBe("17");
      // the throttle slot was used; wait it out for the next iteration by shifting the clock above
      await pdb.prepare("UPDATE devices SET last_refresh_at = NULL").run();
    }
    expect(await pall("SELECT last_lease_expires_at FROM devices")).toEqual(before); // no new lease
    expect(await pall("SELECT status, last_capabilities FROM patreon_links")).toEqual([{ status: "active", last_capabilities: '["seamless_updates"]' }]);
    expect((await metrics()).patreon_unavailable).toBe(4);
    // one attempt per request: 4 requests -> 4 identity attempts
    expect(mock.identityCalls.length).toBe(1 + 4); // 1 at link time
  });

  it("Patreon outage on the token refresh: 503, lock released, tokens untouched", async () => {
    const dev = await linkDevice();
    await pdb.prepare("UPDATE patreon_links SET token_expires_at = ?1").bind(nowS + 3600).run();
    const before = await pall("SELECT access_token_enc, refresh_token_enc, token_version FROM patreon_links");
    mock.tokenOverride = (grant) => (grant === "refresh_token" ? new Response("down", { status: 500 }) : undefined);
    const res = await refresh(workerFor(NOW + 13 * HOUR, mock), dev.token);
    expect(res.status).toBe(503);
    expect(await res.json()).toEqual({ ok: false, code: "patreon_unavailable" });
    expect(await pall("SELECT access_token_enc, refresh_token_enc, token_version FROM patreon_links")).toEqual(before);
    expect(await pall("SELECT status, refresh_lock_until FROM patreon_links")).toEqual([{ status: "active", refresh_lock_until: null }]);
    expect(mock.identityCalls).toHaveLength(1); // no identity call after a failed token refresh
    // and it recovers on the next try
    mock.tokenOverride = undefined;
    expect((await refresh(workerFor(NOW + 13 * HOUR + 120_000, mock), dev.token)).status).toBe(200);
  });

  it("invalid_grant: link becomes reauth_required, tokens are deleted, and Patreon is not contacted again", async () => {
    const dev = await linkDevice();
    await pdb.prepare("UPDATE patreon_links SET token_expires_at = ?1").bind(nowS + 3600).run();
    mock.tokenOverride = (grant) => (grant === "refresh_token" ? new Response(JSON.stringify({ error: "invalid_grant" }), { status: 400 }) : undefined);
    const res = await refresh(workerFor(NOW + 13 * HOUR, mock), dev.token);
    expect(res.status).toBe(401);
    expect(await res.json()).toEqual({ ok: false, code: "reauthorize_required" });
    expect(await pall("SELECT status, access_token_enc, refresh_token_enc, token_expires_at, refresh_lock_until FROM patreon_links")).toEqual([
      { status: "reauth_required", access_token_enc: null, refresh_token_enc: null, token_expires_at: null, refresh_lock_until: null },
    ]);
    const calls = mock.calls.length;
    const again = await refresh(workerFor(NOW + 14 * HOUR, mock), dev.token);
    expect(again.status).toBe(401);
    expect(await again.json()).toEqual({ ok: false, code: "reauthorize_required" });
    expect(mock.calls.length).toBe(calls);
    expect((await metrics()).reauthorize_required).toBe(2);

    // re-linking the same Patreon user restores the existing link and its devices
    mock.tokenOverride = undefined;
    await fullLink(workerFor(NOW + 15 * HOUR, mock), "code-2");
    expect(await pall("SELECT status FROM patreon_links")).toEqual([{ status: "active" }]);
    expect((await refresh(workerFor(NOW + 15 * HOUR + 120_000, mock), dev.token)).status).toBe(200);
  });

  it("identity 401 (token revoked at Patreon) also requires re-authorization", async () => {
    const dev = await linkDevice();
    mock.identityOverride = () => new Response("{}", { status: 401 });
    const res = await refresh(workerFor(NOW + 13 * HOUR, mock), dev.token);
    expect(res.status).toBe(401);
    expect(await res.json()).toEqual({ ok: false, code: "reauthorize_required" });
    expect(await pall("SELECT status, access_token_enc FROM patreon_links")).toEqual([{ status: "reauth_required", access_token_enc: null }]);
  });

  it("LEASE_ISSUANCE_ENABLED=false: 503 issuance_disabled and no Patreon call, no lease", async () => {
    const dev = await linkDevice();
    const res = await refresh(workerFor(NOW + 13 * HOUR, mock), dev.token, { schema: 1 }, makePatreonEnv({ LEASE_ISSUANCE_ENABLED: "false" }));
    expect(res.status).toBe(503);
    expect(res.headers.get("retry-after")).toBe("3600");
    expect(await res.json()).toEqual({ ok: false, code: "issuance_disabled" });
    expect(mock.identityCalls).toHaveLength(1);
    expect(await metrics()).toEqual({ issuance_disabled: 1 });
  });

  it("missing configuration: 503 not_configured", async () => {
    const dev = await linkDevice();
    const res = await refresh(workerFor(NOW + 120_000, mock), dev.token, { schema: 1 }, makePatreonEnv({ ENTITLEMENT_SIGNING_KEY: undefined }));
    expect(res.status).toBe(503);
    expect(await res.json()).toEqual({ ok: false, code: "not_configured" });
  });

  it("refresh-lock race: while one request rotates the token, a concurrent one gets refresh_busy; exactly ONE Patreon token call", async () => {
    const a = await linkDevice();
    const b = await linkDevice(f, "code-2"); // same Patreon user -> same link, second device
    expect(await pcount("patreon_links")).toBe(1);
    await pdb.prepare("UPDATE patreon_links SET token_expires_at = ?1").bind(nowS + 3600).run();
    const baseline = mock.tokenCalls.length;

    let release!: () => void;
    const gate = new Promise<void>((r) => (release = r));
    mock.tokenOverride = async (grant) => {
      if (grant === "refresh_token") await gate;
      return undefined;
    };
    const later = workerFor(NOW + 13 * HOUR, mock);
    const first = refresh(later, a.token);
    for (let i = 0; i < 200 && mock.tokenCalls.length === baseline; i++) await new Promise((r) => setTimeout(r, 5));
    expect(mock.tokenCalls.length).toBe(baseline + 1); // request A is inside the Patreon call, holding the lock

    const second = await refresh(later, b.token);
    expect(second.status).toBe(503);
    expect(second.headers.get("retry-after")).toBe("5");
    expect(await second.json()).toEqual({ ok: false, code: "refresh_busy" });
    expect(mock.tokenCalls.length).toBe(baseline + 1);

    release();
    expect((await first).status).toBe(200);
    expect(mock.tokenCalls.length).toBe(baseline + 1);
    expect(await pall("SELECT status, refresh_lock_until FROM patreon_links")).toEqual([{ status: "active", refresh_lock_until: null }]);
    // after the rotation the other device succeeds without another token call
    expect((await refresh(workerFor(NOW + 13 * HOUR + 5_000, mock), b.token)).status).toBe(200);
    expect(mock.tokenCalls.length).toBe(baseline + 1);
  });

  it("two truly parallel refreshes of one link still make only one Patreon token call and never invalidate the link", async () => {
    const a = await linkDevice();
    const b = await linkDevice(f, "code-2");
    await pdb.prepare("UPDATE patreon_links SET token_expires_at = ?1").bind(nowS + 3600).run();
    const baseline = mock.tokenCalls.length;
    const later = workerFor(NOW + 13 * HOUR, mock);
    mock.tokenOverride = async () => {
      await new Promise((r) => setTimeout(r, 30));
      return undefined;
    };
    const [ra, rb] = await Promise.all([refresh(later, a.token), refresh(later, b.token)]);
    expect([ra.status, rb.status].every((s) => s === 200 || s === 503)).toBe(true);
    expect([ra.status, rb.status]).toContain(200);
    expect(mock.tokenCalls.length).toBe(baseline + 1);
    expect(await pall("SELECT status FROM patreon_links")).toEqual([{ status: "active" }]);
  });

  it("a stale lock (crashed request) expires after 30 s", async () => {
    const dev = await linkDevice();
    await pdb.prepare("UPDATE patreon_links SET token_expires_at = ?1, refresh_lock_until = ?2").bind(nowS + 3600, nowS + 13 * 3600 + 20).run();
    expect((await refresh(workerFor(NOW + 13 * HOUR, mock), dev.token)).status).toBe(503);
    expect((await refresh(workerFor(NOW + 13 * HOUR + 100_000, mock), dev.token)).status).toBe(200);
  });

  it("stays within the D1 Free budget per request", async () => {
    const dev = await linkDevice();
    await pdb.prepare("UPDATE patreon_links SET token_expires_at = ?1").bind(nowS + 3600).run();
    const counted = countingDb(pdb);
    const res = await refresh(workerFor(NOW + 13 * HOUR, mock), dev.token, { schema: 1 }, makePatreonEnv({ PATREON_DB: counted.db }));
    expect(res.status).toBe(200);
    expect(counted.prepared.length).toBeLessThanOrEqual(12);
  });
});

describe("POST /v1/patreon/unlink", () => {
  const unlink = (fetcher: Fetcher, token: string | undefined) => psend("/v1/patreon/unlink", { fetcher, token, body: {} });

  it("is idempotent: 204 for unknown, missing and repeated tokens", async () => {
    const dev = await linkDevice();
    for (const t of [undefined, "A".repeat(43), "junk"]) expect((await unlink(f, t)).status).toBe(204);
    expect(await pcount("devices")).toBe(1);
    expect((await unlink(f, dev.token)).status).toBe(204);
    expect((await unlink(f, dev.token)).status).toBe(204);
    expect(await pcount("devices")).toBe(0);
  });

  it("removing the last device deletes the link including its encrypted tokens", async () => {
    const a = await linkDevice();
    const b = await linkDevice(f, "code-2");
    expect(await pcount("devices")).toBe(2);
    await unlink(f, a.token);
    expect(await pcount("devices")).toBe(1);
    expect(await pcount("patreon_links")).toBe(1);
    await unlink(f, b.token);
    expect(await pcount("devices")).toBe(0);
    expect(await pcount("patreon_links")).toBe(0);
    expect(JSON.stringify(await pall("SELECT * FROM patreon_links"))).toBe("[]");
    // the unlinked device can no longer refresh
    const res = await refresh(workerFor(NOW + 120_000, mock), b.token);
    expect(res.status).toBe(401);
    expect(await res.json()).toEqual({ ok: false, code: "device_unknown" });
    expect(mock.calls.filter((c) => c.kind === "other")).toEqual([]); // no revocation call exists / is made
  });

  it("an evicted (6th-device) client is told device_unknown", async () => {
    const devs: Device[] = [];
    for (let i = 0; i < 6; i++) devs.push(await linkDevice(workerFor(NOW + i * 10_000, mock)));
    const res = await refresh(workerFor(NOW + 120_000, mock), devs[0]!.token);
    expect(res.status).toBe(401);
    expect(await res.json()).toEqual({ ok: false, code: "device_unknown" });
    expect((await refresh(workerFor(NOW + 120_000, mock), devs[5]!.token)).status).toBe(200);
  });

  it("without a database binding the answer is 503 not_configured", async () => {
    const res = await psend("/v1/patreon/unlink", { fetcher: f, token: "A".repeat(43), env: makePatreonEnv({ PATREON_DB: undefined }) });
    expect(res.status).toBe(503);
  });
});

describe("device tokens never persist in the clear", () => {
  it("the database holds only SHA-256 hashes of device tokens", async () => {
    const dev = await linkDevice();
    expect(await pdump()).not.toContain(dev.token);
  });
});
