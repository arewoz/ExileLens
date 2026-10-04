import { beforeEach, describe, expect, it } from "vitest";
import { env as bindings } from "cloudflare:workers";
import { evaluatePolicy, extractFacts, parseOverrideSecret, parsePolicy, withExtraOverrides, type MembershipFact } from "../src/patreon/policy";
import { NOW, referenceHmac } from "./helpers";
import {
  CAMPAIGN,
  MockPatreon,
  fullLink,
  identityPayload,
  makePatreonEnv,
  pall,
  policyJson,
  resetPatreonDb,
  workerFor,
  type IdentitySpec,
} from "./patreon-helpers";

const policy = parsePolicy(policyJson())!;
const hmac = "a".repeat(64);

const member = (over: Partial<MembershipFact> = {}): MembershipFact => ({
  campaign_id: CAMPAIGN,
  patron_status: "active_patron",
  is_gifted: false,
  is_free_trial: false,
  tiers: [{ id: "9001", amount_cents: 500 }],
  ...over,
});

describe("parsePolicy", () => {
  it("accepts the documented default shape once a campaign id is set", () => {
    expect(policy).toMatchObject({ policy_version: 1, campaign_id: CAMPAIGN, allow_gifted: true, allow_free_trial: true });
    expect(policy.rules).toEqual([{ when: "any_active_paid_tier", capabilities: ["seamless_updates"] }]);
  });

  it("empty campaign_id means not configured; garbage is rejected", () => {
    expect(parsePolicy(policyJson({ campaign_id: "" }))).toBeNull();
    expect(parsePolicy(policyJson({ campaign_id: 5 }))).toBeNull();
    expect(parsePolicy(policyJson({ policy_version: 0 }))).toBeNull();
    expect(parsePolicy(policyJson({ policy_version: 1.5 }))).toBeNull();
    expect(parsePolicy(policyJson({ rules: [] }))).toBeNull();
    expect(parsePolicy(policyJson({ rules: [{ capabilities: ["x"] }] }))).toBeNull();
    expect(parsePolicy(policyJson({ rules: [{ when: "any_active_paid_tier", capabilities: ["Bad Cap"] }] }))).toBeNull();
    expect(parsePolicy(policyJson({ rules: [{ tier_ids: [], capabilities: ["x"] }] }))).toBeNull();
    expect(parsePolicy(policyJson({ allow_gifted: "yes" }))).toBeNull();
    expect(parsePolicy(policyJson({ override_user_hmacs: { nothex: ["x"] } }))).toBeNull();
    expect(parsePolicy("not json")).toBeNull();
    expect(parsePolicy(undefined)).toBeNull();
    expect(parsePolicy("[]")).toBeNull();
  });
});

describe("evaluatePolicy matrix", () => {
  const cases: [string, MembershipFact[], string[]][] = [
    ["active paid tier", [member()], ["seamless_updates"]],
    ["active, several tiers, one paid", [member({ tiers: [{ id: "1", amount_cents: 0 }, { id: "2", amount_cents: 300 }] })], ["seamless_updates"]],
    ["free member (only a free tier)", [member({ tiers: [{ id: "1", amount_cents: 0 }] })], []],
    ["free member (no tier at all)", [member({ tiers: [] })], []],
    ["gifted active paid", [member({ is_gifted: true })], ["seamless_updates"]],
    ["free trial of a paid tier", [member({ is_free_trial: true })], ["seamless_updates"]],
    ["declined patron", [member({ patron_status: "declined_patron" })], []],
    ["former patron", [member({ patron_status: "former_patron" })], []],
    ["null patron status", [member({ patron_status: null })], []],
    ["unknown patron status", [member({ patron_status: "something_new" })], []],
    ["member of another campaign", [member({ campaign_id: "999" })], []],
    ["no memberships", [], []],
    ["other campaign + ours", [member({ campaign_id: "999" }), member()], ["seamless_updates"]],
  ];
  it.each(cases)("%s", (_name, facts, expected) => {
    const res = evaluatePolicy(policy, facts, hmac);
    expect(res.capabilities).toEqual(expected);
    expect(res.eligible).toBe(expected.length > 0);
  });

  it("honours allow_gifted=false and allow_free_trial=false", () => {
    const strict = parsePolicy(policyJson({ allow_gifted: false, allow_free_trial: false }))!;
    expect(evaluatePolicy(strict, [member({ is_gifted: true })], hmac).eligible).toBe(false);
    expect(evaluatePolicy(strict, [member({ is_free_trial: true })], hmac).eligible).toBe(false);
    expect(evaluatePolicy(strict, [member()], hmac).eligible).toBe(true);
  });

  it("tier_ids rules match only the listed tiers; capabilities are sorted and de-duplicated", () => {
    const p = parsePolicy(
      policyJson({
        rules: [
          { tier_ids: ["2"], capabilities: ["zeta", "seamless_updates"] },
          { when: "any_active_paid_tier", capabilities: ["seamless_updates"] },
        ],
      }),
    )!;
    expect(evaluatePolicy(p, [member({ tiers: [{ id: "2", amount_cents: 100 }] })], hmac).capabilities).toEqual(["seamless_updates", "zeta"]);
    expect(evaluatePolicy(p, [member({ tiers: [{ id: "3", amount_cents: 100 }] })], hmac).capabilities).toEqual(["seamless_updates"]);
    const onlyTier = parsePolicy(policyJson({ rules: [{ tier_ids: ["2"], capabilities: ["seamless_updates"] }] }))!;
    expect(evaluatePolicy(onlyTier, [member({ tiers: [{ id: "3", amount_cents: 100 }] })], hmac).eligible).toBe(false);
  });

  it("override_user_hmacs grants capabilities regardless of membership (creator account)", () => {
    const withOverride = parsePolicy(policyJson({ override_user_hmacs: { [hmac]: ["seamless_updates"] } }))!;
    expect(evaluatePolicy(withOverride, [], hmac)).toEqual({ capabilities: ["seamless_updates"], eligible: true });
    expect(evaluatePolicy(withOverride, [], "b".repeat(64)).eligible).toBe(false);
    expect(evaluatePolicy(withOverride, [member({ patron_status: "former_patron" })], hmac).eligible).toBe(true);
  });
});

describe("extractFacts", () => {
  it("reads only user id, member status flags, tier amounts and campaign ids", () => {
    const facts = extractFacts(identityPayload({ userId: "55", patron_status: "active_patron", is_gifted: true, tiers: [{ id: "7", cents: 250 }] }))!;
    expect(facts).toEqual({
      userId: "55",
      memberships: [{ campaign_id: CAMPAIGN, patron_status: "active_patron", is_gifted: true, is_free_trial: false, tiers: [{ id: "7", amount_cents: 250 }] }],
    });
    expect(JSON.stringify(facts)).not.toMatch(/secret|email|@/i);
  });

  it("degrades to no membership on unexpected shapes and rejects payloads without a user id", () => {
    expect(extractFacts(null)).toBeNull();
    expect(extractFacts({})).toBeNull();
    expect(extractFacts({ data: { id: 5 } })).toBeNull();
    expect(extractFacts({ data: { id: "1" }, included: "nope" })).toEqual({ userId: "1", memberships: [] });
    expect(extractFacts({ data: { id: "1" }, included: [{ type: "member", id: "m" }] })).toEqual({ userId: "1", memberships: [] }); // no campaign relationship
    const noTierAmount = extractFacts({
      data: { id: "1" },
      included: [{ type: "member", id: "m", attributes: { patron_status: "active_patron" }, relationships: { campaign: { data: { id: "5" } }, currently_entitled_tiers: { data: [{ id: "t" }] } } }],
    })!;
    expect(noTierAmount.memberships[0]!.tiers).toEqual([{ id: "t", amount_cents: 0 }]); // unknown amount is never "paid"
  });
});

describe("policy matrix through the real link flow (mocked identity payloads)", () => {
  beforeEach(resetPatreonDb);

  const flowCases: [string, IdentitySpec, string, string[]][] = [
    ["paid", { userId: "1", tiers: [{ id: "9", cents: 500 }] }, "linked", ["seamless_updates"]],
    ["free (zero-cent tier)", { userId: "2", tiers: [{ id: "8", cents: 0 }] }, "not_entitled", []],
    ["free (no tier)", { userId: "3", patron_status: null, tiers: [] }, "not_entitled", []],
    ["gifted", { userId: "4", is_gifted: true, tiers: [{ id: "9", cents: 500 }] }, "linked", ["seamless_updates"]],
    ["free trial", { userId: "5", is_free_trial: true, tiers: [{ id: "9", cents: 500 }] }, "linked", ["seamless_updates"]],
    ["declined", { userId: "6", patron_status: "declined_patron", tiers: [{ id: "9", cents: 500 }] }, "not_entitled", []],
    ["former", { userId: "7", patron_status: "former_patron", tiers: [] }, "not_entitled", []],
    ["null status", { userId: "8", patron_status: null, tiers: [{ id: "9", cents: 500 }] }, "not_entitled", []],
    ["other campaign", { userId: "9", campaignId: "42", tiers: [{ id: "9", cents: 500 }] }, "not_entitled", []],
    ["no membership at all", { userId: "10", noMembership: true }, "not_entitled", []],
  ];

  it.each(flowCases)("%s", async (_name, spec, status, caps) => {
    const mock = new MockPatreon();
    mock.defaultIdentity = spec;
    const { pollBody } = await fullLink(workerFor(NOW, mock));
    expect(pollBody.status).toBe(status);
    expect(pollBody.lease!.lease.capabilities).toEqual(caps);
    expect(await pall("SELECT last_capabilities FROM patreon_links")).toEqual([{ last_capabilities: JSON.stringify(caps) }]);
  });

  it("creator override: an account with no membership is linked via ENTITLEMENT_POLICY override_user_hmacs", async () => {
    const creatorHmac = await referenceHmac(bindings.PATREON_ID_PEPPER, "patreon", "31337");
    const env = makePatreonEnv({ ENTITLEMENT_POLICY: policyJson({ override_user_hmacs: { [creatorHmac]: ["seamless_updates"] } }) });
    const mock = new MockPatreon();
    mock.defaultIdentity = { userId: "31337", noMembership: true };
    const { pollBody } = await fullLink(workerFor(NOW, mock), "code-1", env);
    expect(pollBody.status).toBe("linked");
    expect(pollBody.lease!.lease.capabilities).toEqual(["seamless_updates"]);
    expect(await pall("SELECT patreon_user_hmac FROM patreon_links")).toEqual([{ patreon_user_hmac: creatorHmac }]);
    // and a different user without membership gets nothing from the same policy
    mock.defaultIdentity = { userId: "31338", noMembership: true };
    expect((await fullLink(workerFor(NOW, mock), "code-2", env)).pollBody.status).toBe("not_entitled");
  });
});

describe("creator override from the PATREON_OVERRIDE_USER_HMACS secret", () => {
  beforeEach(resetPatreonDb);

  const creator = "c".repeat(64);
  const secret = (value: unknown) => JSON.stringify(value);

  it("parseOverrideSecret: missing, empty and malformed values mean no overrides (fail closed, never throws)", () => {
    expect(parseOverrideSecret(undefined)).toEqual({});
    expect(parseOverrideSecret("")).toEqual({});
    expect(parseOverrideSecret("   ")).toEqual({});
    expect(parseOverrideSecret("not json")).toEqual({});
    expect(parseOverrideSecret("[]")).toEqual({});
    expect(parseOverrideSecret(secret({ nothex: ["seamless_updates"] }))).toEqual({});
    expect(parseOverrideSecret(secret({ [creator]: ["Bad Cap"] }))).toEqual({});
    expect(parseOverrideSecret(secret({ [creator]: "seamless_updates" }))).toEqual({});
    // one bad entry invalidates the whole secret rather than half-applying it
    expect(parseOverrideSecret(secret({ [creator]: ["seamless_updates"], nothex: ["x"] }))).toEqual({});
    expect(parseOverrideSecret(secret({ [creator]: ["seamless_updates"] }))).toEqual({ [creator]: ["seamless_updates"] });
  });

  it("parseOverrideSecret enforces the same count limit as the policy var", () => {
    const many = (n: number) => Object.fromEntries(Array.from({ length: n }, (_, i) => [i.toString(16).padStart(64, "0"), ["seamless_updates"]]));
    expect(Object.keys(parseOverrideSecret(secret(many(64))))).toHaveLength(64);
    expect(parseOverrideSecret(secret(many(65)))).toEqual({});
  });

  it("withExtraOverrides merges with the policy var and de-duplicates; the policy stays the source of truth", () => {
    const other = "d".repeat(64);
    const base = parsePolicy(policyJson({ override_user_hmacs: { [other]: ["seamless_updates", "beta"], [creator]: ["alpha"] } }))!;
    const merged = withExtraOverrides(base, { [creator]: ["seamless_updates", "alpha"] });
    expect(merged.override_user_hmacs[creator]!.slice().sort()).toEqual(["alpha", "seamless_updates"]);
    expect(merged.override_user_hmacs[other]).toEqual(["seamless_updates", "beta"]);
    expect(merged.rules).toEqual(base.rules);
    expect(base.override_user_hmacs[creator]).toEqual(["alpha"]); // input not mutated
    expect(withExtraOverrides(base, {})).toBe(base);
  });

  it("withExtraOverrides ignores extras that would exceed the override limit", () => {
    const full = Object.fromEntries(Array.from({ length: 64 }, (_, i) => [i.toString(16).padStart(64, "0"), ["seamless_updates"]]));
    const base = parsePolicy(policyJson({ override_user_hmacs: full }))!;
    expect(withExtraOverrides(base, { [creator]: ["seamless_updates"] })).toBe(base);
  });

  async function link(userId: string, spec: Record<string, unknown>, secretValue: string | undefined, code: string) {
    const mock = new MockPatreon();
    mock.defaultIdentity = { userId, ...spec } as IdentitySpec;
    const env = makePatreonEnv(secretValue === undefined ? {} : { PATREON_OVERRIDE_USER_HMACS: secretValue });
    return (await fullLink(workerFor(NOW, mock), code, env)).pollBody;
  }

  it("a creator with no membership gets seamless_updates through the secret (no change to the policy var)", async () => {
    const hmac = await referenceHmac(bindings.PATREON_ID_PEPPER, "patreon", "31337");
    const body = await link("31337", { noMembership: true }, secret({ [hmac]: ["seamless_updates"] }), "code-1");
    expect(body.status).toBe("linked");
    expect(body.lease!.lease.capabilities).toEqual(["seamless_updates"]);
  });

  it("a different user without membership gets nothing from the same secret", async () => {
    const hmac = await referenceHmac(bindings.PATREON_ID_PEPPER, "patreon", "31337");
    const body = await link("31338", { noMembership: true }, secret({ [hmac]: ["seamless_updates"] }), "code-2");
    expect(body.status).toBe("not_entitled");
    expect(body.lease!.lease.capabilities).toEqual([]);
  });

  it.each([["unset", undefined], ["garbage", "{not json"], ["wrong shape", "[1,2]"], ["bad hmac", secret({ nothex: ["seamless_updates"] })]])(
    "a malformed or missing secret (%s) grants the creator nothing and does not break linking",
    async (_name, value) => {
      const body = await link("31337", { noMembership: true }, value as string | undefined, "code-3");
      expect(body.status).toBe("not_entitled");
      expect(body.lease!.lease.capabilities).toEqual([]);
    },
  );

  it("supporter rules are unchanged when the secret is set: paid, gifted and trial are eligible, free members are not", async () => {
    const hmac = await referenceHmac(bindings.PATREON_ID_PEPPER, "patreon", "31337");
    const value = secret({ [hmac]: ["seamless_updates"] });
    const paid = { tiers: [{ id: "9", cents: 500 }] };
    expect((await link("1", paid, value, "c-paid")).lease!.lease.capabilities).toEqual(["seamless_updates"]);
    expect((await link("2", { ...paid, is_gifted: true }, value, "c-gift")).lease!.lease.capabilities).toEqual(["seamless_updates"]);
    expect((await link("3", { ...paid, is_free_trial: true }, value, "c-trial")).lease!.lease.capabilities).toEqual(["seamless_updates"]);
    expect((await link("4", { tiers: [{ id: "8", cents: 0 }] }, value, "c-free")).lease!.lease.capabilities).toEqual([]);
  });

  it("the policy var override and the secret override both apply and merge", async () => {
    const fromVar = await referenceHmac(bindings.PATREON_ID_PEPPER, "patreon", "500");
    const fromSecret = await referenceHmac(bindings.PATREON_ID_PEPPER, "patreon", "501");
    const mock = new MockPatreon();
    const env = makePatreonEnv({
      ENTITLEMENT_POLICY: policyJson({ override_user_hmacs: { [fromVar]: ["seamless_updates"] } }),
      PATREON_OVERRIDE_USER_HMACS: secret({ [fromSecret]: ["seamless_updates"] }),
    });
    mock.defaultIdentity = { userId: "500", noMembership: true };
    expect((await fullLink(workerFor(NOW, mock), "m-1", env)).pollBody.lease!.lease.capabilities).toEqual(["seamless_updates"]);
    mock.defaultIdentity = { userId: "501", noMembership: true };
    expect((await fullLink(workerFor(NOW, mock), "m-2", env)).pollBody.lease!.lease.capabilities).toEqual(["seamless_updates"]);
  });
});
