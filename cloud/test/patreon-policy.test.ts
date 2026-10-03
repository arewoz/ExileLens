import { beforeEach, describe, expect, it } from "vitest";
import { env as bindings } from "cloudflare:workers";
import { evaluatePolicy, extractFacts, parsePolicy, type MembershipFact } from "../src/patreon/policy";
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
