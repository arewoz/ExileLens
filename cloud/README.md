# ExileLens cloud (Package A: usage statistics and error reports; Package B: Patreon entitlement leases)

One Cloudflare Worker (TypeScript, `/v1` API) that receives **opt-in** usage statistics and
error reports from the ExileLens desktop app (Package A) and, separately, links a Patreon membership
to a signed **capability lease** (Package B, see "Patreon entitlement leases" below). It must run on **Workers Free + D1 Free**:
no KV, Queues, Durable Objects, R2 or other paid features.

* Canonical contract (single source of truth, shared with the Python client):
  `schema/events.v1.json`, golden fixtures `contract/fixtures.json`.
* Two logically separate databases: `TELEMETRY_DB` (Package A) and `PATREON_DB` (Package B).
  Telemetry code only ever receives the object built by `telemetryEnv()` in `src/env.ts`; Patreon
  code only ever receives `patreonEnv()` (explicit allow-lists, so neither side can see the other's
  binding or secrets). Nothing under `src/telemetry/` may reference Patreon and nothing under
  `src/patreon/` may reference the telemetry side (both directions enforced by source-grep tests).
  No SQL joins, no shared identifiers, no shared peppers/keys.

## Privacy rules implemented here

* No IP address, User-Agent or raw client UUID is stored or logged. Only
  `HMAC-SHA256(pepper, "<domain>:" + uuid)` hex is stored: `ANALYTICS_PEPPER` + domain
  `analytics` for usage, `DIAGNOSTIC_PEPPER` + domain `diagnostic` for errors.
* Operational logs (`console.log` JSON: route, status, duration, reason code) are separate from
  product telemetry and never feed metrics.
* `POST /v1/*/forget` deletes everything linked to a hashed id; anonymous aggregates stay.

## API

| Method and path | Result |
| --- | --- |
| `GET /v1/health` | `200 {ok, api:"v1", server_time}` |
| `POST /v1/telemetry/batch` | usage events (contract `usage`) |
| `POST /v1/errors/batch` | error reports (contract `errors`) |
| `POST /v1/telemetry/forget` | body `{schema:1, analytics_id}` -> `204` |
| `POST /v1/errors/forget` | body `{schema:1, diagnostic_id}` -> `204` |
| `POST /v1/patreon/link/start` ... `POST /v1/patreon/unlink` | Patreon linking and leases, see the Patreon section |

Batch responses: `202 {ok, accepted, rejected:[{index,code}]}`; duplicate `batch_id` (7 days,
per kind) `200 {ok, duplicate:true}`; batch-level failure `400 {ok:false, code}` (`422` for
`schema_unsupported`, `413 payload_too_large`, `415 unsupported_media_type`, `405`); per-install
daily cap `429 daily_cap`; kill switch `503 ingest_disabled`; D1 quota/outage
`503 storage_unavailable`. `Retry-After` is always present on 429/503. Everything else is
`404 {ok:false, code:"not_found"}`. All responses are JSON with `cache-control: no-store`; no CORS.
Bodies must be `application/json` and at most 32768 bytes (enforced while reading).

Abuse design: the primary limiter is **per install hash** (500 usage events / 60 error reports per
UTC day, batch and event-count caps). IP is only an optional coarse outer guard through the
`RL_INGEST` Rate Limiting binding (see `wrangler.toml`); without the binding it is skipped.
`INGEST_ENABLED=false` is a global kill switch (forget keeps working).

## Local development

```
cd cloud
npm install
cp .dev.vars.example .dev.vars        # fake peppers; git-ignored
npm run migrate:local                 # applies migrations/telemetry to the local D1
npm run migrate:patreon:local         # applies migrations/patreon to the local PATREON_DB
npm run dev                           # wrangler dev (local mode)
npm run typecheck
npm test                              # vitest in the Workers runtime against a real (Miniflare) D1
```

Tests (`test/`) run every golden fixture through the validator and exercise real SQL for ingest,
dedupe, caps, forget, error grouping, cron aggregation/retention, and the report queries.
The Patreon tests (`test/patreon-*.test.ts`) use a mocked Patreon `fetch` (no real call is ever made) and cover the OAuth
flow, the policy matrix, token encryption, leases (incl. the golden vector), refresh/locking, unlink, retention,
reports, privacy scans and the telemetry/Patreon separation.

## Deploying staging / production (owner steps; nothing here uses real IDs)

`wrangler.toml` top level is local-only. `[env.staging]` and `[env.production]` redeclare their
D1 binding with a **placeholder** `database_id`; replace it after creating the database.

```
npx wrangler login
npx wrangler d1 create exilelens-telemetry-staging          # copy database_id into [env.staging]
npx wrangler d1 migrations apply TELEMETRY_DB --env staging --remote
npx wrangler secret put ANALYTICS_PEPPER  --env staging     # paste a long random value
npx wrangler secret put DIAGNOSTIC_PEPPER --env staging     # a DIFFERENT long random value
npx wrangler deploy --env staging
curl https://<staging-worker-url>/v1/health
```

Production is the same with `--env production`, `exilelens-telemetry-production`, and a custom
domain `routes` entry once the domain is decided (`workers_dev` is off). Keep the peppers stable:
rotating one orphans that kind of install history. Never reuse one pepper for both.

The optional `RL_INGEST` Rate Limiting binding is a commented block per environment; whether it is
available on the Free plan must be verified by the owner before enabling it.

Cron (usage statistics): `17 * * * *` hourly. At 03:xx UTC it aggregates yesterday into `metrics_daily`, then applies
retention; other hours run only a small bounded retention pass. Deletes are chunked (2000 rows,
at most 25 rounds per table) and capped at 45 D1 queries per run to respect the Free limit of 50
queries per invocation.

Retention: usage events 30 d, install activity 120 d, aggregates 13 months, error groups 12 months
after last seen, error/install links 60 d, batch ids 7 d, installs 13 months after last activity.

## Patreon entitlement leases (Package B)

Patreon is **not an account system** here. It yields exactly one thing: a short-lived, signed
**capability lease** (`seamless_updates`) for one desktop installation. No profile, e-mail, name or
other Patreon data is returned to the desktop app or stored. The business rules (who is eligible) are
**server-side configuration** (`ENTITLEMENT_POLICY`), never in the app. The Patreon part uses its own
database (`PATREON_DB`), its own migrations (`migrations/patreon/`), its own peppers/keys, and a lease
signing key that is **not** the update-signing key.

### Endpoints (`/v1/patreon/...`)

All JSON unless noted; `cache-control: no-store`; no CORS; no body/ID/token logging; request bodies
are `application/json`, at most 1024 bytes, unknown fields are `400 unknown_field`.

| Method and path | Auth | Result |
| --- | --- | --- |
| `POST link/start` `{schema:1}` | none | `201 {ok, session_id, poll_token, authorize_url, expires_at, poll_interval_s:2}`; `429 busy` (200 pending sessions) / `429 rate_limited` (optional `RL_LINK`) |
| `GET oauth/callback?code&state` | none (browser) | static HTML only (CSP `default-src 'none'`), never JSON, never echoes a query value |
| `GET link/status?session_id=` | `Bearer <poll_token>` | `{ok, status}`; the first poll after `linked`/`not_entitled` also returns `device_token`, `device_id`, `lease` exactly once; unknown session and wrong token are the identical `404 {ok:false, code:"not_found"}` |
| `DELETE link/session?session_id=` | `Bearer <poll_token>` | `204`, uniform for unknown/wrong token; cancels a pending session |
| `POST entitlement/refresh` `{schema:1, client_version?}` | `Bearer <device_token>` | `200 {ok, lease:{lease,signature}, next_refresh_after_s, server_time}` |
| `POST unlink` | `Bearer <device_token>` | `204` always (idempotent) |

Session statuses: `pending | linked | not_entitled | denied | expired | failed (+code) | cancelled | consumed`.
Refresh errors: `401 device_unknown`, `401 reauthorize_required`, `429 rate_limited` (min 60 s per device),
`503 patreon_unavailable` / `refresh_busy` / `issuance_disabled` / `link_disabled` / `not_configured`
(all with `Retry-After`; `not_configured` and the kill switches use 3600). A Patreon outage **never
revokes anything and never produces a lease**: the client keeps its current lease until it expires.

### Link flow

1. The app calls `link/start` and opens `authorize_url` (scope `identity` only; no PKCE is sent, see below).
2. Patreon redirects the browser to `oauth/callback`. The state is consumed with one conditional
   `UPDATE ... WHERE status='pending'` (a replayed callback changes nothing), the code is exchanged
   server-side (one attempt), the identity is fetched (one call), the policy is evaluated and the link is
   stored (tokens AES-256-GCM encrypted, user id stored only as `HMAC-SHA256(PATREON_ID_PEPPER, "patreon:"+id)`).
3. The app polls `link/status` every 2 s (max 400 polls per session, 10 minute TTL). The first poll after
   success atomically consumes the session, creates the device (16-byte id, 32-byte random token of which
   only the SHA-256 is stored; max 5 devices per link, the oldest is evicted) and returns the lease.
   A `not_entitled` link still gets a device and a lease with `capabilities: []`, so the app can show
   "connected, not eligible" and pick up an upgrade later. If that response is lost the user must link again.

### Lease and signature

```
lease = {schema:1, kid, lease_id, sub:<device_id>, capabilities:[sorted], issued_at, refresh_after, expires_at, policy_version}
        (exactly these nine keys; epoch seconds; refresh_after = issued_at + 86400; expires_at = issued_at + 604800)
signature = base64(Ed25519(private_key, UTF8("exilelens/entitlement-lease/v1\n") + canonical_json(lease)))
canonical_json == json.dumps(lease, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
```

A lease never contains a URL, version, file name or hash. The signer refuses any message that lacks the
domain prefix. `contract/lease_vector.json` is a cross-language golden vector (test-only key
`test/keys/entitlement-test-1.pkcs8.b64`, public key `7uT5nCI2848DtVlDbBEUsIM30CjxIt9H1e0eD9hBjr0=`);
`test/patreon-lease.test.ts` checks that the Worker reproduces its signature byte for byte and verifies it with
`crypto.subtle.verify`. Ed25519 is deterministic, so the Python client can verify the same vector.
The vector was produced with Node `crypto` (independent of `src/`) and is reproduced by the Worker code.

A refresh re-verifies the membership with Patreon when the cached verification is older than 12 h (1 h
while capabilities are empty, or when `policy_version` changed), so a lease is only ever issued from a
verification that is at most 12 h old (never more than 24 h). The Patreon access token is rotated when it expires
within 3 days, under a D1 conditional lock (`refresh_lock_until`), so concurrent refreshes cause exactly one
Patreon token call (refresh tokens are single use); a loser answers `503 refresh_busy` (retry in 5 s).
`invalid_grant` (or a 401 from the identity call) marks the link `reauth_required` and deletes the stored tokens.

### Eligibility policy (`ENTITLEMENT_POLICY`, JSON var)

```json
{"policy_version":1,"campaign_id":"<your campaign id>","rules":[{"when":"any_active_paid_tier","capabilities":["seamless_updates"]}],
 "allow_gifted":true,"allow_free_trial":true,"override_user_hmacs":{}}
```

* Empty `campaign_id` means "not configured" (`503 not_configured`); it must be numeric.
* A membership counts only if `relationships.campaign.data.id == campaign_id` and `patron_status == active_patron`
  (declined / former / null never count). `any_active_paid_tier` = at least one currently entitled tier with
  `amount_cents > 0` (free members never match); `{"tier_ids":["123"],"capabilities":[...]}` rules match specific
  tiers. `allow_gifted` / `allow_free_trial` switch those membership kinds off.
* Bump `policy_version` after editing the policy: links are re-verified on their next refresh and the new
  version is stamped into new leases.
* **Creator / tester override.** The creator is not a member of their own campaign, so grant your own account
  explicitly: compute its keyed hash with the production pepper and add it to the map.

  ```
  PATREON_ID_PEPPER=<production pepper> node scripts/patreon-id-hmac.mjs <your numeric Patreon user id>
  ```

  then set `"override_user_hmacs":{"<hex>":["seamless_updates"]}` and bump `policy_version`. The script reads the
  pepper only from the environment and never prints it.

  To keep the hash out of the public repository, put the same map in the optional Worker **secret**
  `PATREON_OVERRIDE_USER_HMACS` instead (`{"<hex>":["seamless_updates"]}`). It is merged with the policy var's
  overrides (de-duplicated, same 64-entry limit); missing, empty or malformed means no extra overrides. An existing
  link with an empty verification picks it up on its next refresh after the hourly empty-result re-check, or at once
  by linking again.

### Configuration

| Name | Kind | Notes |
| --- | --- | --- |
| `PATREON_DB` | D1 binding | separate database, `migrations_dir = "migrations/patreon"` |
| `PATREON_CLIENT_SECRET`, `ENTITLEMENT_SIGNING_KEY`, `TOKEN_ENC_KEY`, `PATREON_ID_PEPPER` | secrets | signing key = PKCS#8 Ed25519, base64 DER or PEM; enc key = 32 random bytes base64; pepper >= 16 chars |
| `PATREON_CLIENT_ID`, `PATREON_REDIRECT_URI` | vars | redirect = this Worker's own `.../v1/patreon/oauth/callback` (https, or http on localhost) |
| `PATREON_API_BASE` | var | default `https://www.patreon.com` |
| `PATREON_LINK_ENABLED` | var | `"false"` => `503 link_disabled` for starting/finishing links |
| `LEASE_ISSUANCE_ENABLED` | var | `"false"` => `503 issuance_disabled`, no lease at all |
| `ENTITLEMENT_KEY_ID` | var | default `exilelens-entitlement-1`; the app needs the matching public key |
| `ENTITLEMENT_POLICY` | var | see above |
| `PATREON_OVERRIDE_USER_HMACS` | optional secret | extra user-HMAC capability overrides, see above |
| `RL_LINK` | optional Rate Limiting binding | coarse per-IP guard for `link/start`, key never stored; verify Free-plan availability first |

Any missing or invalid value gives `503 {code:"not_configured"}` with `Retry-After: 3600`, never a crash.

### Data stored in `PATREON_DB`

`link_sessions` (hashes of state and poll token only; deleted 24 h after expiry), `patreon_links` (user HMAC,
encrypted tokens, cached capabilities; removed with the last device, or when it has no device and no pending
session), `devices` (token hash, timestamps, client version; deleted after 60 idle days),
`link_metrics_daily` / `entitlement_refresh_daily` (day, outcome, count; 13 months). There is no users/accounts
table and no e-mail, name, address, IP or User-Agent anywhere. Tokens are AES-256-GCM encrypted with a random
12-byte IV per value and AAD = `link_id`.

`unlink` deletes the device (and the link with its tokens when it was the last device). **No token
revocation call is made at Patreon** because none is documented; the user can also revoke ExileLens in their
Patreon settings (the next refresh then fails with `invalid_grant`/401 and the link needs re-authorization).

### Maintenance cron

Patreon retention runs from its **own** cron trigger (`47 */6 * * *`) so it never shares an invocation with the
usage-statistics job (Free plan: 50 D1 queries per invocation). It is bounded to 20 queries per run with chunked
deletes. `wrangler.toml` therefore lists two crons per environment; the owner must check the account-wide Free limit
on cron triggers if more environments are added.

### Patreon reports (separate database, anonymous)

```
node scripts/report.mjs --list --db patreon
node scripts/report.mjs patreon_link_outcomes --db patreon --local
node scripts/report.mjs entitlement_refresh_outcomes --db patreon --remote --env production
node scripts/report.mjs active_entitled_devices --db patreon --remote --env production
```

`--db patreon` queries `PATREON_DB` only (reports in `reports/patreon/`); one invocation never touches both
databases. The reports are counts only: link funnel per day, refresh outcomes per day, and the number of devices
holding an unexpired lease for an entitled link. No ids are selected.

### Owner runbook (Patreon)

1. **Patreon client.** Log in as the creator account and create an API v2 client in the Patreon developer portal.
   Redirect URI = `<api origin>/v1/patreon/oauth/callback` (for staging: the staging Worker URL). Use a
   **separate client per environment** (staging / production). The client id goes into `PATREON_CLIENT_ID`; the
   client secret is a secret. Put your campaign id into `ENTITLEMENT_POLICY.campaign_id`.
2. **Databases.**

   ```
   npx wrangler d1 create exilelens-patreon-staging         # copy database_id into [[env.staging.d1_databases]] PATREON_DB
   npx wrangler d1 migrations apply PATREON_DB --env staging --remote
   ```

   Repeat with `exilelens-patreon-production` and `--env production`.
3. **Signing key (OFFLINE).** From the repository root run `python scripts/create_entitlement_key.py` (written
   separately). Keep the private key out of the repo and out of CI logs; ship the public key and `kid` in the app.
4. **Secrets.**

   ```
   npx wrangler secret put ENTITLEMENT_SIGNING_KEY --env staging   # PKCS#8 Ed25519 (base64 DER or PEM)
   npx wrangler secret put PATREON_CLIENT_SECRET   --env staging
   npx wrangler secret put TOKEN_ENC_KEY           --env staging   # 32 random bytes, base64
   npx wrangler secret put PATREON_ID_PEPPER       --env staging   # long random value, different from the other peppers
   ```

   Never reuse a staging value in production. Rotating `TOKEN_ENC_KEY` or `PATREON_ID_PEPPER` invalidates all
   stored links (users must link again); do not rotate casually.
5. **Vars.** Set `PATREON_CLIENT_ID`, `PATREON_REDIRECT_URI` and the policy's `campaign_id` in the environment's
   `[env.*.vars]`, then `npx wrangler deploy --env staging`. Kill switches: set `PATREON_LINK_ENABLED` or
   `LEASE_ISSUANCE_ENABLED` to `"false"` and redeploy.

### Live activation checks still required (NOT verified; do not assume)

The implementation follows the documented Patreon API, but none of this was exercised against the real service
(all tests use a mocked `fetch`). Before enabling it for users, verify on staging:

* [ ] **PKCE.** Patreon documents no PKCE; the Worker sends none. Confirm the flow works without it.
* [ ] **Redirect-URI matching.** Whether Patreon matches the registered URI exactly and whether several may be registered.
* [ ] **`expires_in`.** The real value. The Worker tolerates any or missing value (default 30 days, clamped) and
      refreshes when the token expires within 3 days.
* [ ] **Empty `fields[user]=`.** Whether the identity call accepts it. If it answers 400 the Worker retries once
      without the parameter (`fetchIdentity` in `src/patreon/api.ts`); if the fallback is always used, drop the empty parameter.
* [ ] **Real accounts:** paid, free, gifted, free-trial, declined and former members, and a member of another
      campaign: confirm `patron_status`, `is_gifted`, `is_free_trial` and `currently_entitled_tiers` / `amount_cents`
      behave as the policy assumes (e.g. gifted and trial members really report `active_patron` with a paid tier).
* [ ] **Creator account behaviour:** what the creator's own identity returns; confirm the `override_user_hmacs` route.
* [ ] **Token revocation:** none is documented, so `unlink` does not revoke at Patreon.
* [ ] **Refresh-token rotation:** if the Worker fails to persist a freshly rotated refresh token (D1 outage right after
      Patreon rotated it) the next refresh reports `reauthorize_required`; confirm this is acceptable.
* [ ] **Ed25519 key import on the deployed runtime** (`crypto.subtle.importKey("pkcs8", ..., "Ed25519")` works in the
      local workerd used by the tests; deployed behaviour is unverified) and that the app verifies a deployed lease.
* [ ] **Patreon developer terms** and API usage policy (rate limits: 100 requests/2 s per client, 100/min per token;
      more than 2,000 4xx in 10 minutes triggers a 30-minute block, which is why the Worker never loops on failures).
* [ ] **Free-plan availability** of the optional `RL_LINK` Rate Limiting binding and of the second cron trigger.

**Activation result (staging, 2026-10-03, Cloudflare Free):**

* Verified live: authorize→callback→code exchange→identity→encrypted tokens→device→signed lease works without PKCE with an exactly
  matching single registered redirect URI; Ed25519 import/sign on the deployed runtime, and the Python app verifies the deployed lease
  (tamper, wrong signature, unknown kid, wrong device, expiry and update-key confusion are all rejected); refresh, unlink
  (tokens deleted with the last device) and post-unlink 401; `RL_INGEST`/`RL_LINK` bindings and the second cron work on Free.
* Production client (`https://api.exilelens.app`) repeated the same flow with the same results; production link/lease switches are OFF again.
* Creator account: Patreon returned a `not_entitled` result (no membership in the creator's own campaign), as expected.
  The `override_user_hmacs` route was not exercised.
* **Mocked / unit-tested only (not exercised against real Patreon):** eligible paid patron, gifted, free trial, declined, free member,
  former member, member of another campaign. Accepted by the owner as non-blocking for activation.
* Not observable from outside (no token/response logging by design): real `expires_in`, refresh-token rotation, whether the empty
  `fields[user]=` or its fallback was used. Still unverified; Patreon developer terms still need an owner read.

## Reports (no web dashboard)

`reports/*.sql` are read-only SELECTs; each starts with a comment stating that it counts
**opted-in active installations, not users**. Run one with:

```
node scripts/report.mjs --list
node scripts/report.mjs active_installs --local
node scripts/report.mjs retention --remote --env production          # suppresses cohorts < 20
node scripts/report.mjs retention --remote --env production --min-cohort 50 [--json]
```

`--local` reads the local D1 (`npm run migrate:local` first); `--remote` requires `--env` and uses
whatever Cloudflare login the owner already has. `--min-cohort` defaults to 20 for `--remote` and
0 for `--local`. The script calls `wrangler d1 execute TELEMETRY_DB ... --json --file` and prints a table.

| Report | What it shows |
| --- | --- |
| `active_installs` | active installations over the last 1 / 7 / 30 complete UTC days |
| `new_and_returning_installs` | per day: new vs returning active installations |
| `retention` | D1 / D7 / D30 by weekly first-seen cohort; small cohorts suppressed |
| `item_check_volume` | installations running Item Check and checks per installation, with both denominators (Item Check installs, all active installs) |
| `verdict_distribution` | share of Item Check verdicts, last 30 days |
| `analyze_build_adoption` | installations using Analyze Build and outcomes |
| `top_error_groups` | error groups with affected diagnostic installations, occurrences, first/last seen, versions |
| `unexpected_session_end_rate` | share of app starts whose previous session ended unexpectedly (**not** a crash rate; never "crash-free") |
| `update_adoption` | version mix of active installations and the latest-version share |
| `update_failure_rate` | update download and install outcome shares |

Notes on interpretation: usage `active_installs` is counted by the day the server received a batch;
event-based metrics by the event's own hour. Events that arrive after the nightly aggregation
(late client flushes) are visible in raw tables for 30 days but are not added to that day's
aggregate. Diagnostic and usage ids are unrelated, so error and usage numbers can never be joined.

## D1 Free budget notes

* Each indexed row costs extra "rows written"; the raw events table has two secondary indexes.
* Events are written with one `INSERT ... SELECT ... json_each(?)` statement per batch (D1 allows
  50 queries per invocation and 100 bound parameters per query), so a request uses about 5 queries.
* When D1 refuses writes (quota), handlers return `503 storage_unavailable` + `Retry-After: 3600`.
