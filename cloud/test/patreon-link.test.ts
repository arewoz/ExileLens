import { beforeEach, describe, expect, it } from "vitest";
import { NOW } from "./helpers";
import {
  CAMPAIGN,
  MockPatreon,
  PAID,
  callback,
  fullLink,
  makePatreonEnv,
  nowS,
  pall,
  pcount,
  pdb,
  pdump,
  poll,
  psend,
  resetPatreonDb,
  startLink,
  workerFor,
} from "./patreon-helpers";
import { policyJson } from "./patreon-helpers";

let mock: MockPatreon;
let f: ReturnType<typeof workerFor>;

beforeEach(async () => {
  await resetPatreonDb();
  mock = new MockPatreon();
  f = workerFor(NOW, mock);
});

async function snapshot(res: Response) {
  return { status: res.status, body: await res.text(), headers: [...res.headers.entries()].sort() };
}

describe("POST /v1/patreon/link/start", () => {
  it("returns the session, a poll token and an authorize_url; stores only hashes", async () => {
    const res = await psend("/v1/patreon/link/start", { fetcher: f, body: { schema: 1 } });
    expect(res.status).toBe(201);
    expect(res.headers.get("cache-control")).toBe("no-store");
    const body = (await res.json()) as Record<string, unknown>;
    expect(Object.keys(body).sort()).toEqual(["authorize_url", "expires_at", "ok", "poll_interval_s", "poll_token", "session_id"]);
    expect(body.ok).toBe(true);
    expect(body.session_id).toMatch(/^[0-9a-f]{32}$/);
    expect(body.poll_token).toMatch(/^[A-Za-z0-9_-]{43}$/);
    expect(body.poll_interval_s).toBe(2);
    expect(body.expires_at).toBe(nowS + 600);

    const url = new URL(body.authorize_url as string);
    expect(`${url.origin}${url.pathname}`).toBe("https://www.patreon.com/oauth2/authorize");
    expect(Object.fromEntries(url.searchParams)).toEqual({
      response_type: "code",
      client_id: "test-client-id",
      redirect_uri: "https://api.test/v1/patreon/oauth/callback",
      scope: "identity",
      state: expect.stringMatching(/^[A-Za-z0-9_-]{43}$/),
    });
    expect(url.searchParams.has("code_challenge")).toBe(false); // PKCE is not documented: not sent

    const rows = await pall<Record<string, unknown>>("SELECT * FROM link_sessions");
    expect(rows).toHaveLength(1);
    expect(rows[0]).toMatchObject({ status: "pending", polls: 0, consumed: 0, link_id: null, result_code: null, expires_at: nowS + 600, created_at: nowS });
    const dump = await pdump();
    expect(dump).not.toContain(body.poll_token as string);
    expect(dump).not.toContain(url.searchParams.get("state")!);
    expect(await pall("SELECT * FROM link_metrics_daily")).toEqual([{ day: "2026-10-03", outcome: "started", count: 1 }]);
  });

  it("validates the body: unknown fields, schema, media type, JSON", async () => {
    const unknown = await psend("/v1/patreon/link/start", { fetcher: f, body: { schema: 1, extra: 1 } });
    expect(unknown.status).toBe(400);
    expect(await unknown.json()).toEqual({ ok: false, code: "unknown_field" });
    expect((await psend("/v1/patreon/link/start", { fetcher: f, body: {} })).status).toBe(400);
    expect((await psend("/v1/patreon/link/start", { fetcher: f, body: { schema: 2 } })).status).toBe(422);
    expect((await psend("/v1/patreon/link/start", { fetcher: f, raw: "{nope" })).status).toBe(400);
    expect((await psend("/v1/patreon/link/start", { fetcher: f, body: [1] })).status).toBe(400);
    expect((await psend("/v1/patreon/link/start", { fetcher: f, raw: "{}", headers: { "content-type": "text/plain" } })).status).toBe(415);
    expect((await psend("/v1/patreon/link/start", { fetcher: f, raw: JSON.stringify({ schema: 1, pad: "x".repeat(2000) }) })).status).toBe(413);
    expect((await psend("/v1/patreon/link/start", { fetcher: f, method: "GET" })).status).toBe(405);
    expect(await pcount("link_sessions")).toBe(0);
  });

  it("caps concurrently pending sessions at 200 (429 busy + Retry-After)", async () => {
    const stmts = Array.from({ length: 200 }, (_, i) =>
      pdb
        .prepare("INSERT INTO link_sessions (session_id, state_hash, poll_token_hash, status, created_at, expires_at) VALUES (?1, ?2, ?3, 'pending', ?4, ?5)")
        .bind(`s${i}`, `h${i}`, `p${i}`, nowS, nowS + 300),
    );
    await pdb.batch(stmts);
    const res = await psend("/v1/patreon/link/start", { fetcher: f, body: { schema: 1 } });
    expect(res.status).toBe(429);
    expect(res.headers.get("retry-after")).toBe("60");
    expect(await res.json()).toEqual({ ok: false, code: "busy" });
    expect(await pcount("link_sessions")).toBe(200);
    // expired sessions do not count
    await pdb.prepare("UPDATE link_sessions SET expires_at = ?1 WHERE session_id = 's0'").bind(nowS - 1).run();
    expect((await psend("/v1/patreon/link/start", { fetcher: f, body: { schema: 1 } })).status).toBe(201);
  });

  it("kill switch and missing / invalid configuration give 503 with Retry-After 3600, never a crash", async () => {
    const disabled = await psend("/v1/patreon/link/start", { fetcher: f, env: makePatreonEnv({ PATREON_LINK_ENABLED: "false" }) });
    expect(disabled.status).toBe(503);
    expect(disabled.headers.get("retry-after")).toBe("3600");
    expect(await disabled.json()).toEqual({ ok: false, code: "link_disabled" });

    const broken: Record<string, Partial<ReturnType<typeof makePatreonEnv>>> = {
      no_db: { PATREON_DB: undefined },
      no_client_id: { PATREON_CLIENT_ID: "" },
      no_secret: { PATREON_CLIENT_SECRET: undefined },
      bad_redirect: { PATREON_REDIRECT_URI: "http://evil.example/v1/patreon/oauth/callback" },
      wrong_redirect_path: { PATREON_REDIRECT_URI: "https://api.test/other" },
      empty_campaign: { ENTITLEMENT_POLICY: policyJson({ campaign_id: "" }) },
      bad_policy_json: { ENTITLEMENT_POLICY: "{not json" },
      bad_policy_rule: { ENTITLEMENT_POLICY: policyJson({ rules: [{ when: "everyone", capabilities: ["x"] }] }) },
      no_policy: { ENTITLEMENT_POLICY: undefined },
      short_pepper: { PATREON_ID_PEPPER: "short" },
      bad_enc_key: { TOKEN_ENC_KEY: "AAAA" },
      no_enc_key: { TOKEN_ENC_KEY: undefined },
      bad_sign_key: { ENTITLEMENT_SIGNING_KEY: "garbage" },
      no_sign_key: { ENTITLEMENT_SIGNING_KEY: undefined },
      bad_api_base: { PATREON_API_BASE: "ftp://x" },
    };
    for (const [name, over] of Object.entries(broken)) {
      const res = await psend("/v1/patreon/link/start", { fetcher: f, env: makePatreonEnv(over) });
      expect(res.status, name).toBe(503);
      expect(res.headers.get("retry-after"), name).toBe("3600");
      expect(await res.json(), name).toEqual({ ok: false, code: "not_configured" });
    }
    expect(mock.calls).toEqual([]);
  });

  it("optional RL_LINK limiter: denial is 429, an outage of the limiter fails open", async () => {
    let seenKey = "";
    const deny = makePatreonEnv({ RL_LINK: { limit: async ({ key }) => ((seenKey = key), { success: false }) } });
    const res = await psend("/v1/patreon/link/start", { fetcher: f, env: deny, headers: { "cf-connecting-ip": "203.0.113.9" } });
    expect(res.status).toBe(429);
    expect(seenKey).toBe("203.0.113.9");
    expect(await pdump()).not.toContain("203.0.113.9");
    const boom = makePatreonEnv({ RL_LINK: { limit: async () => { throw new Error("down"); } } });
    expect((await psend("/v1/patreon/link/start", { fetcher: f, env: boom })).status).toBe(201);
  });
});

describe("GET /v1/patreon/oauth/callback", () => {
  it("success: static HTML with the required security headers; session becomes linked", async () => {
    const s = await startLink(f);
    const res = await callback(f, { code: "the-code", state: s.state });
    expect(res.status).toBe(200);
    expect(res.headers.get("content-type")).toMatch(/^text\/html/);
    expect(res.headers.get("content-security-policy")).toBe("default-src 'none'; style-src 'unsafe-inline'");
    expect(res.headers.get("x-content-type-options")).toBe("nosniff");
    expect(res.headers.get("referrer-policy")).toBe("no-referrer");
    expect(res.headers.get("cache-control")).toBe("no-store");
    const html = await res.text();
    expect(html).toContain("ExileLens is connected — you can close this tab.");
    expect(html).not.toContain("the-code");
    expect(html).not.toContain(s.state);
    expect(html).not.toMatch(/secret|email|Secret/i);
    expect(await pall("SELECT status, link_id FROM link_sessions")).toEqual([{ status: "linked", link_id: expect.stringMatching(/^[0-9a-f]{32}$/) }]);
    expect(mock.tokenCalls).toHaveLength(1);
    expect(mock.tokenCalls[0]!.grant).toBe("authorization_code");
    const form = new URLSearchParams(mock.tokenCalls[0]!.body);
    expect(form.get("redirect_uri")).toBe("https://api.test/v1/patreon/oauth/callback");
    expect(form.get("client_id")).toBe("test-client-id");
    expect(form.has("code_verifier")).toBe(false);
    expect(mock.identityCalls).toHaveLength(1);
    expect(mock.identityCalls[0]!.url).toContain("fields[user]=");
    expect(mock.identityCalls[0]!.url).toContain("include=memberships,memberships.currently_entitled_tiers,memberships.campaign");
    expect(mock.identityCalls[0]!.url).toContain("fields[member]=patron_status,is_gifted,is_free_trial");
    expect(mock.identityCalls[0]!.url).toContain("fields[tier]=amount_cents");
    expect(await pall("SELECT * FROM link_metrics_daily ORDER BY outcome")).toEqual([
      { day: "2026-10-03", outcome: "linked", count: 1 },
      { day: "2026-10-03", outcome: "started", count: 1 },
    ]);
  });

  it("state replay: the second callback with the same state fails and changes nothing", async () => {
    const s = await startLink(f);
    expect((await callback(f, { code: "c1", state: s.state })).status).toBe(200);
    const before = await pdump();
    const calls = mock.calls.length;
    const replay = await callback(f, { code: "c2", state: s.state });
    expect(replay.status).toBe(400);
    expect(await replay.text()).toContain("This link expired — start again from ExileLens");
    expect(mock.calls.length).toBe(calls); // Patreon is not contacted again
    expect(await pdump()).toBe(before);
  });

  it("concurrent callbacks with one state exchange the code exactly once", async () => {
    const s = await startLink(f);
    const [a, b] = await Promise.all([callback(f, { code: "c1", state: s.state }), callback(f, { code: "c1", state: s.state })]);
    expect([a.status, b.status].sort()).toEqual([200, 400]);
    expect(mock.tokenCalls).toHaveLength(1);
  });

  it("unknown, malformed or missing state shows the expired page and never contacts Patreon", async () => {
    const bad: Record<string, string>[] = [
      { code: "c", state: "A".repeat(43) },
      { code: "c", state: "short" },
      { code: "c" },
      { state: "A".repeat(43) },
      { code: "c", state: "<script>alert(1)</script>" },
    ];
    for (const params of bad) {
      const res = await callback(f, params);
      expect(res.status).toBe(400);
      const html = await res.text();
      expect(html).toContain("This link expired");
      expect(html).not.toContain("alert(1)");
      expect(res.headers.get("content-type")).toMatch(/^text\/html/);
    }
    expect(mock.calls).toEqual([]);
  });

  it("a state from another session cannot be used with a session that expired (injected clock)", async () => {
    const s = await startLink(f);
    const late = workerFor(NOW + 601_000, mock);
    const res = await callback(late, { code: "c", state: s.state });
    expect(res.status).toBe(400);
    expect(await res.text()).toContain("expired");
    expect(mock.calls).toEqual([]);
    expect(await pall("SELECT status FROM link_sessions")).toEqual([{ status: "pending" }]);
    // the poll reports it as expired
    const st = await poll(late, s.session_id, s.poll_token);
    expect(await st.json()).toEqual({ ok: true, status: "expired" });
    expect(await pall("SELECT * FROM link_metrics_daily WHERE outcome = 'expired'")).toEqual([{ day: "2026-10-03", outcome: "expired", count: 1 }]);
  });

  it("denied / cancelled at Patreon: session becomes denied and the code cannot be used afterwards", async () => {
    const s = await startLink(f);
    const res = await callback(f, { error: "access_denied", state: s.state });
    expect(res.status).toBe(200);
    expect(await res.text()).not.toContain("access_denied");
    expect(await pall("SELECT status, result_code FROM link_sessions")).toEqual([{ status: "denied", result_code: "access_denied" }]);
    expect(await (await poll(f, s.session_id, s.poll_token)).json()).toEqual({ ok: true, status: "denied" });
    const again = await callback(f, { code: "c", state: s.state });
    expect(again.status).toBe(400);
    expect(mock.calls).toEqual([]);
    expect(await pcount("patreon_links")).toBe(0);
    // an unknown state with an error changes nothing; arbitrary error text is never stored or echoed
    const s2 = await startLink(f);
    const odd = await callback(f, { error: "<b>weird</b>", state: s2.state });
    expect(await odd.text()).not.toContain("weird");
    expect(await pall("SELECT result_code FROM link_sessions WHERE session_id = ?1", s2.session_id)).toEqual([{ result_code: "oauth_error" }]);
    expect((await callback(f, { error: "access_denied", state: "B".repeat(43) })).status).toBe(400);
  });

  it("Patreon outage at the token exchange: session failed, no link, no lease", async () => {
    mock.tokenOverride = () => new Response("bad gateway", { status: 502 });
    const s = await startLink(f);
    const res = await callback(f, { code: "c", state: s.state });
    expect(res.status).toBe(502);
    expect(await res.text()).not.toContain("bad gateway");
    expect(await pall("SELECT status, result_code FROM link_sessions")).toEqual([{ status: "failed", result_code: "patreon_unavailable" }]);
    expect(await pcount("patreon_links")).toBe(0);
    expect(mock.tokenCalls).toHaveLength(1); // exactly one attempt
    expect(mock.identityCalls).toHaveLength(0);
    const st = await (await poll(f, s.session_id, s.poll_token)).json();
    expect(st).toEqual({ ok: true, status: "failed", code: "patreon_unavailable" });
    expect(await pcount("devices")).toBe(0);
    expect((await pall<{ outcome: string }>("SELECT outcome FROM link_metrics_daily")).map((r) => r.outcome).sort()).toEqual(["failed", "started"]);
  });

  it("network error and invalid_grant at the exchange are failures too", async () => {
    mock.tokenOverride = () => {
      throw new TypeError("network down");
    };
    const a = await startLink(f);
    expect((await callback(f, { code: "c", state: a.state })).status).toBe(502);
    expect(await pall("SELECT result_code FROM link_sessions WHERE session_id = ?1", a.session_id)).toEqual([{ result_code: "patreon_unavailable" }]);
    mock.tokenOverride = () => new Response(JSON.stringify({ error: "invalid_grant" }), { status: 400 });
    const b = await startLink(f);
    await callback(f, { code: "c", state: b.state });
    expect(await pall("SELECT result_code FROM link_sessions WHERE session_id = ?1", b.session_id)).toEqual([{ result_code: "exchange_failed" }]);
    expect(await pcount("patreon_links")).toBe(0);
  });

  it("Patreon outage at the identity call: session failed, no link stored", async () => {
    mock.identityOverride = () => new Response("down", { status: 503 });
    const s = await startLink(f);
    const res = await callback(f, { code: "c", state: s.state });
    expect(res.status).toBe(502);
    expect(await pall("SELECT status, result_code FROM link_sessions")).toEqual([{ status: "failed", result_code: "patreon_unavailable" }]);
    expect(await pcount("patreon_links")).toBe(0);
    expect(mock.identityCalls).toHaveLength(1);
    // an unusable identity payload is a failure as well
    mock.identityOverride = () => new Response(JSON.stringify({ nothing: true }), { status: 200 });
    const s2 = await startLink(f);
    await callback(f, { code: "c", state: s2.state });
    expect(await pall("SELECT result_code FROM link_sessions WHERE session_id = ?1", s2.session_id)).toEqual([{ result_code: "identity_failed" }]);
    expect(await pcount("patreon_links")).toBe(0);
  });

  it("falls back once to an identity URL without fields[user]= when Patreon answers 400", async () => {
    let n = 0;
    mock.identityOverride = (_a, url) => {
      n += 1;
      return url.includes("fields[user]=") ? new Response("bad", { status: 400 }) : undefined;
    };
    const s = await startLink(f);
    expect((await callback(f, { code: "c", state: s.state })).status).toBe(200);
    expect(n).toBe(2);
    expect(mock.identityCalls[1]!.url).not.toContain("fields[user]");
    expect(mock.identityCalls).toHaveLength(2);
  });

  it("a persistent 400 on identity is not retried more than once", async () => {
    mock.identityOverride = () => new Response("bad", { status: 400 });
    const s = await startLink(f);
    expect((await callback(f, { code: "c", state: s.state })).status).toBe(502);
    expect(mock.identityCalls).toHaveLength(2);
  });

  it("kill switch / misconfiguration: HTML 503, never JSON", async () => {
    const s = await startLink(f);
    for (const env of [makePatreonEnv({ PATREON_LINK_ENABLED: "false" }), makePatreonEnv({ PATREON_CLIENT_ID: "" })]) {
      const res = await callback(f, { code: "c", state: s.state }, env);
      expect(res.status).toBe(503);
      expect(res.headers.get("content-type")).toMatch(/^text\/html/);
      expect(res.headers.get("content-security-policy")).toBe("default-src 'none'; style-src 'unsafe-inline'");
    }
    expect(mock.calls).toEqual([]);
    expect(await pall("SELECT status FROM link_sessions")).toEqual([{ status: "pending" }]);
  });

  it("not entitled: the page says so, the link exists, the session is not_entitled", async () => {
    mock.defaultIdentity = { userId: "77", patron_status: "active_patron", tiers: [{ id: "1", cents: 0 }] };
    const s = await startLink(f);
    const res = await callback(f, { code: "c", state: s.state });
    expect(await res.text()).toContain("Connected, but your membership does not include seamless updates.");
    expect(await pall("SELECT status FROM link_sessions")).toEqual([{ status: "not_entitled" }]);
    expect(await pall("SELECT last_capabilities FROM patreon_links")).toEqual([{ last_capabilities: "[]" }]);
  });

  it("re-link of the same Patreon user replaces tokens and bumps token_version (one link row)", async () => {
    await fullLink(f);
    const first = await pall<{ link_id: string; token_version: number; access_token_enc: string }>("SELECT link_id, token_version, access_token_enc FROM patreon_links");
    await fullLink(f);
    const second = await pall<{ link_id: string; token_version: number; access_token_enc: string }>("SELECT link_id, token_version, access_token_enc FROM patreon_links");
    expect(second).toHaveLength(1);
    expect(second[0]!.link_id).toBe(first[0]!.link_id);
    expect(second[0]!.token_version).toBe(first[0]!.token_version + 1);
    expect(second[0]!.access_token_enc).not.toBe(first[0]!.access_token_enc);
    expect(await pcount("devices")).toBe(2);
  });
});

describe("GET /v1/patreon/link/status", () => {
  it("pending while waiting; exchanging is reported as pending", async () => {
    const s = await startLink(f);
    const res = await poll(f, s.session_id, s.poll_token);
    expect(res.status).toBe(200);
    expect(await res.json()).toEqual({ ok: true, status: "pending" });
    await pdb.prepare("UPDATE link_sessions SET status = 'exchanging'").run();
    expect(await (await poll(f, s.session_id, s.poll_token)).json()).toEqual({ ok: true, status: "pending" });
    // a worker that died mid-exchange cannot keep a session alive forever
    const late = workerFor(NOW + (600 + 121) * 1000, mock);
    expect(await (await poll(late, s.session_id, s.poll_token)).json()).toEqual({ ok: true, status: "expired" });
  });

  it("unknown session, wrong token, missing token and malformed ids are byte-identical 404s", async () => {
    const s = await startLink(f);
    const other = await startLink(f);
    const variants = [
      await poll(f, "f".repeat(32), s.poll_token), // unknown session, token valid for another one
      await poll(f, s.session_id, other.poll_token), // wrong token
      await poll(f, s.session_id, "A".repeat(43)), // wrong token, well-formed
      await poll(f, s.session_id, undefined), // missing token
      await poll(f, s.session_id, "short"), // malformed token
      await poll(f, "not-hex", s.poll_token), // malformed session id
      await psend("/v1/patreon/link/status", { method: "GET", fetcher: f, token: s.poll_token }), // no session_id
    ];
    const snaps = await Promise.all(variants.map(snapshot));
    for (const snap of snaps) {
      expect(snap.status).toBe(404);
      expect(snap.body).toBe('{"ok":false,"code":"not_found"}');
      expect(snap).toEqual(snaps[0]);
    }
    // failed authentication does not consume the owner's poll budget
    expect(await pall("SELECT polls FROM link_sessions WHERE session_id = ?1", s.session_id)).toEqual([{ polls: 0 }]);
  });

  it("caps polls per session (429 + Retry-After)", async () => {
    const s = await startLink(f);
    await pdb.prepare("UPDATE link_sessions SET polls = 398").run();
    expect((await poll(f, s.session_id, s.poll_token)).status).toBe(200); // 399
    expect((await poll(f, s.session_id, s.poll_token)).status).toBe(200); // 400
    const over = await poll(f, s.session_id, s.poll_token);
    expect(over.status).toBe(429);
    expect(over.headers.get("retry-after")).toBe("60");
    expect(await over.json()).toEqual({ ok: false, code: "poll_limit" });
  });

  it("delivers credentials exactly once: first poll after linking creates the device + lease, later polls say consumed", async () => {
    const { started, pollBody } = await fullLink(f);
    expect(pollBody.status).toBe("linked");
    expect(pollBody.device_token).toMatch(/^[A-Za-z0-9_-]{43}$/);
    expect(pollBody.device_id).toMatch(/^[0-9a-f]{32}$/);
    const lease = pollBody.lease!.lease;
    expect(lease).toMatchObject({
      schema: 1,
      kid: "exilelens-entitlement-test-1",
      sub: pollBody.device_id,
      capabilities: ["seamless_updates"],
      issued_at: nowS,
      refresh_after: nowS + 86_400,
      expires_at: nowS + 604_800,
      policy_version: 1,
    });
    expect(Object.keys(lease).sort()).toHaveLength(9);
    expect(pollBody.lease!.signature).toMatch(/^[A-Za-z0-9+/]{86}==$/);
    // device row holds only the token hash
    const dump = await pdump();
    expect(dump).not.toContain(pollBody.device_token!);
    const devices = await pall<{ device_id: string; token_hash: string; last_lease_expires_at: number }>("SELECT device_id, token_hash, last_lease_expires_at FROM devices");
    expect(devices).toHaveLength(1);
    expect(devices[0]!.device_id).toBe(pollBody.device_id);
    expect(devices[0]!.token_hash).toMatch(/^[0-9a-f]{64}$/);
    expect(devices[0]!.last_lease_expires_at).toBe(nowS + 604_800);

    for (let i = 0; i < 3; i++) {
      const again = await poll(f, started.session_id, started.poll_token);
      expect(await again.json()).toEqual({ ok: true, status: "consumed" });
    }
    expect(await pcount("devices")).toBe(1);
  });

  it("concurrent first polls deliver the credentials to exactly one caller", async () => {
    const s = await startLink(f);
    await callback(f, { code: "c", state: s.state });
    const results = await Promise.all([1, 2, 3].map(() => poll(f, s.session_id, s.poll_token).then((r) => r.json() as Promise<Record<string, unknown>>)));
    expect(results.filter((r) => r.device_token !== undefined)).toHaveLength(1);
    expect(results.filter((r) => r.status === "consumed")).toHaveLength(2);
    expect(await pcount("devices")).toBe(1);
  });

  it("a not_entitled link still receives a device and a lease with no capabilities", async () => {
    mock.defaultIdentity = { userId: "77", patron_status: "former_patron", tiers: [] };
    const { pollBody } = await fullLink(f);
    expect(pollBody.status).toBe("not_entitled");
    expect(pollBody.device_token).toBeTruthy();
    expect(pollBody.lease!.lease.capabilities).toEqual([]);
    expect(await pcount("devices")).toBe(1);
  });

  it("with LEASE_ISSUANCE_ENABLED=false the poll answers 503 and consumes nothing", async () => {
    const s = await startLink(f);
    await callback(f, { code: "c", state: s.state });
    const off = makePatreonEnv({ LEASE_ISSUANCE_ENABLED: "false" });
    const res = await poll(f, s.session_id, s.poll_token, off);
    expect(res.status).toBe(503);
    expect(await res.json()).toEqual({ ok: false, code: "issuance_disabled" });
    expect(await pcount("devices")).toBe(0);
    const ok = (await (await poll(f, s.session_id, s.poll_token)).json()) as Record<string, unknown>;
    expect(ok.status).toBe("linked");
    expect(ok.device_token).toBeTruthy();
  });

  it("a finished session cannot be redeemed long after it expired", async () => {
    const s = await startLink(f);
    await callback(f, { code: "c", state: s.state });
    const late = workerFor(NOW + (600 + 601) * 1000, mock);
    expect(await (await poll(late, s.session_id, s.poll_token)).json()).toEqual({ ok: true, status: "expired" });
    expect(await pcount("devices")).toBe(0);
  });

  it("keeps at most 5 devices per link and evicts the oldest by created_at", async () => {
    const ids: string[] = [];
    for (let i = 0; i < 6; i++) {
      const fi = workerFor(NOW + i * 10_000, mock);
      const { pollBody } = await fullLink(fi);
      ids.push(pollBody.device_id!);
    }
    const rows = await pall<{ device_id: string }>("SELECT device_id FROM devices ORDER BY created_at");
    expect(rows.map((r) => r.device_id)).toEqual(ids.slice(1));
    expect(await pcount("patreon_links")).toBe(1);
  });

  it("failed and cancelled sessions are reported without credentials", async () => {
    const s = await startLink(f);
    const del = await psend(`/v1/patreon/link/session?session_id=${s.session_id}`, { method: "DELETE", fetcher: f, token: s.poll_token });
    expect(del.status).toBe(204);
    expect(await (await poll(f, s.session_id, s.poll_token)).json()).toEqual({ ok: true, status: "cancelled" });
    const cb = await callback(f, { code: "c", state: s.state });
    expect(cb.status).toBe(400); // a cancelled session cannot be completed
    expect(mock.calls).toEqual([]);
  });
});

describe("DELETE /v1/patreon/link/session", () => {
  it("is a uniform 204 for unknown sessions and wrong tokens and only cancels with the right token", async () => {
    const s = await startLink(f);
    const wrong = await psend(`/v1/patreon/link/session?session_id=${s.session_id}`, { method: "DELETE", fetcher: f, token: "A".repeat(43) });
    const unknown = await psend(`/v1/patreon/link/session?session_id=${"e".repeat(32)}`, { method: "DELETE", fetcher: f, token: s.poll_token });
    const none = await psend(`/v1/patreon/link/session`, { method: "DELETE", fetcher: f });
    const snaps = await Promise.all([wrong, unknown, none].map(snapshot));
    for (const snap of snaps) {
      expect(snap.status).toBe(204);
      expect(snap).toEqual(snaps[0]);
    }
    expect(await pall("SELECT status FROM link_sessions")).toEqual([{ status: "pending" }]);
    expect((await psend(`/v1/patreon/link/session?session_id=${s.session_id}`, { method: "DELETE", fetcher: f, token: s.poll_token })).status).toBe(204);
    expect(await pall("SELECT status FROM link_sessions")).toEqual([{ status: "cancelled" }]);
  });

  it("does not touch a session that already finished linking", async () => {
    const { started } = await fullLink(f);
    await psend(`/v1/patreon/link/session?session_id=${started.session_id}`, { method: "DELETE", fetcher: f, token: started.poll_token });
    expect(await pall("SELECT status FROM link_sessions")).toEqual([{ status: "consumed" }]);
  });
});

describe("campaign constant", () => {
  it("the mock user is a member of the configured campaign", () => {
    expect(PAID.userId).toBeTruthy();
    expect(CAMPAIGN).toBe("1234567");
  });
});
