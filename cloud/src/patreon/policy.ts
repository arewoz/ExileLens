/**
 * Entitlement policy: server-side business rules (the `ENTITLEMENT_POLICY` JSON var).
 * The desktop app never sees or interprets any of this; it only receives the
 * resulting capability names inside a signed lease.
 *
 * `evaluatePolicy` is a pure function. `extractFacts` turns a Patreon identity
 * response (JSON:API) into the minimal facts the policy needs; nothing else from
 * the payload (names, emails, ...) is read or kept.
 */

export type PolicyRule = { when: "any_active_paid_tier"; capabilities: string[] } | { tier_ids: string[]; capabilities: string[] };

export interface Policy {
  policy_version: number;
  campaign_id: string;
  rules: PolicyRule[];
  allow_gifted: boolean;
  allow_free_trial: boolean;
  /** user HMAC (hex) -> capabilities granted regardless of membership (creator / testers). */
  override_user_hmacs: Record<string, string[]>;
}

export interface TierFact {
  id: string;
  amount_cents: number;
}

export interface MembershipFact {
  campaign_id: string;
  patron_status: string | null;
  is_gifted: boolean;
  is_free_trial: boolean;
  tiers: TierFact[];
}

export interface PolicyResult {
  /** Sorted, de-duplicated capability names. */
  capabilities: string[];
  eligible: boolean;
}

const CAPABILITY_RE = /^[a-z][a-z0-9_]{0,31}$/;
const HMAC_RE = /^[0-9a-f]{64}$/;
const MAX_RULES = 16;
const MAX_OVERRIDES = 64;

function isObj(v: unknown): v is Record<string, unknown> {
  return typeof v === "object" && v !== null && !Array.isArray(v);
}

function capList(v: unknown): string[] | null {
  if (!Array.isArray(v) || v.length > 8) return null;
  const out: string[] = [];
  for (const c of v) {
    if (typeof c !== "string" || !CAPABILITY_RE.test(c)) return null;
    out.push(c);
  }
  return out;
}

/**
 * Parse and validate the policy var. Returns null when missing/invalid or when
 * `campaign_id` is empty (empty = "not configured yet").
 */
export function parsePolicy(text: string | undefined): Policy | null {
  if (typeof text !== "string" || text.length === 0 || text.length > 16384) return null;
  let raw: unknown;
  try {
    raw = JSON.parse(text);
  } catch {
    return null;
  }
  if (!isObj(raw)) return null;
  const version = raw.policy_version;
  if (typeof version !== "number" || !Number.isInteger(version) || version < 1 || version > 1_000_000) return null;
  const campaign = raw.campaign_id;
  if (typeof campaign !== "string" || !/^[0-9]{1,20}$/.test(campaign)) return null;
  if (!Array.isArray(raw.rules) || raw.rules.length === 0 || raw.rules.length > MAX_RULES) return null;

  const rules: PolicyRule[] = [];
  for (const r of raw.rules) {
    if (!isObj(r)) return null;
    const caps = capList(r.capabilities);
    if (caps === null) return null;
    if (r.when !== undefined) {
      if (r.when !== "any_active_paid_tier") return null;
      rules.push({ when: "any_active_paid_tier", capabilities: caps });
    } else if (Array.isArray(r.tier_ids)) {
      if (r.tier_ids.length === 0 || r.tier_ids.length > 64) return null;
      if (!r.tier_ids.every((t) => typeof t === "string" && /^[0-9]{1,20}$/.test(t))) return null;
      rules.push({ tier_ids: [...(r.tier_ids as string[])], capabilities: caps });
    } else {
      return null;
    }
  }

  const overrides: Record<string, string[]> = {};
  if (raw.override_user_hmacs !== undefined) {
    if (!isObj(raw.override_user_hmacs)) return null;
    const keys = Object.keys(raw.override_user_hmacs);
    if (keys.length > MAX_OVERRIDES) return null;
    for (const k of keys) {
      const caps = capList(raw.override_user_hmacs[k]);
      if (!HMAC_RE.test(k) || caps === null) return null;
      overrides[k] = caps;
    }
  }
  const gifted = raw.allow_gifted === undefined ? true : raw.allow_gifted;
  const trial = raw.allow_free_trial === undefined ? true : raw.allow_free_trial;
  if (typeof gifted !== "boolean" || typeof trial !== "boolean") return null;

  return {
    policy_version: version,
    campaign_id: campaign,
    rules,
    allow_gifted: gifted,
    allow_free_trial: trial,
    override_user_hmacs: overrides,
  };
}

function ruleMatches(rule: PolicyRule, tiers: TierFact[]): boolean {
  if ("when" in rule) return tiers.some((t) => t.amount_cents > 0);
  return tiers.some((t) => rule.tier_ids.includes(t.id));
}

/**
 * Pure policy evaluation. A membership counts only if it belongs to the configured
 * campaign and its patron_status is `active_patron` (declined / former / null never
 * count). Gifted and free-trial memberships are subject to the allow_* switches.
 * Free members (no tier with amount_cents > 0) match no `any_active_paid_tier` rule.
 */
export function evaluatePolicy(policy: Policy, memberships: MembershipFact[], userHmacHex: string): PolicyResult {
  const caps = new Set<string>();

  const override = Object.prototype.hasOwnProperty.call(policy.override_user_hmacs, userHmacHex)
    ? policy.override_user_hmacs[userHmacHex]
    : undefined;
  if (override) for (const c of override) caps.add(c);

  if (policy.campaign_id !== "") {
    for (const m of memberships) {
      if (m.campaign_id !== policy.campaign_id) continue;
      if (m.patron_status !== "active_patron") continue;
      if (m.is_gifted && !policy.allow_gifted) continue;
      if (m.is_free_trial && !policy.allow_free_trial) continue;
      for (const rule of policy.rules) {
        if (ruleMatches(rule, m.tiers)) for (const c of rule.capabilities) caps.add(c);
      }
    }
  }
  const capabilities = [...caps].sort();
  return { capabilities, eligible: capabilities.length > 0 };
}

export interface Facts {
  /** The Patreon user id (used only to compute the keyed hash; never stored). */
  userId: string;
  memberships: MembershipFact[];
}

function relId(rel: unknown): string | null {
  if (!isObj(rel)) return null;
  const data = rel.data;
  if (isObj(data) && typeof data.id === "string") return data.id;
  return null;
}

/**
 * Extract the policy facts from a Patreon `identity` JSON:API document.
 * Returns null when the payload is not usable (no user id). Unknown shapes degrade
 * to "no membership", never to eligibility.
 */
export function extractFacts(payload: unknown): Facts | null {
  if (!isObj(payload) || !isObj(payload.data)) return null;
  const userId = payload.data.id;
  if (typeof userId !== "string" || userId.length === 0 || userId.length > 64) return null;

  const included = Array.isArray(payload.included) ? payload.included : [];
  const tierAmounts = new Map<string, number>();
  for (const r of included) {
    if (!isObj(r) || r.type !== "tier" || typeof r.id !== "string") continue;
    const attrs = isObj(r.attributes) ? r.attributes : {};
    const cents = attrs.amount_cents;
    tierAmounts.set(r.id, typeof cents === "number" && Number.isFinite(cents) ? cents : 0);
  }

  const memberships: MembershipFact[] = [];
  for (const r of included) {
    if (!isObj(r) || r.type !== "member") continue;
    const attrs = isObj(r.attributes) ? r.attributes : {};
    const rels = isObj(r.relationships) ? r.relationships : {};
    const campaignId = relId(rels.campaign);
    if (campaignId === null) continue;
    const tiers: TierFact[] = [];
    const tierRel = isObj(rels.currently_entitled_tiers) ? rels.currently_entitled_tiers : {};
    if (Array.isArray(tierRel.data)) {
      for (const t of tierRel.data) {
        if (isObj(t) && typeof t.id === "string") tiers.push({ id: t.id, amount_cents: tierAmounts.get(t.id) ?? 0 });
      }
    }
    memberships.push({
      campaign_id: campaignId,
      patron_status: typeof attrs.patron_status === "string" ? attrs.patron_status : null,
      is_gifted: attrs.is_gifted === true,
      is_free_trial: attrs.is_free_trial === true,
      tiers,
    });
  }
  return { userId, memberships };
}
