# R2 activation record (2026-10-03)

Operational state after taking R2 from "implemented" to real services. No public GitHub Release was published.

## Environments (Cloudflare Workers Free + D1 Free only)

| | Staging | Production |
|---|---|---|
| Host | `exilelens-api-staging.exilelens-cloud.workers.dev` | `https://api.exilelens.app` (custom domain, `workers_dev=false`) |
| D1 | `exilelens-{telemetry,patreon}-staging` | `exilelens-{telemetry,patreon}-production` |
| Crons | `17 * * * *`, `47 */6 * * *` | same |
| `INGEST_ENABLED` | true | true |
| `PATREON_LINK_ENABLED` | true (controlled OAuth validation) | **false** (client configured and validated; OFF until the public R2 release) |
| `LEASE_ISSUANCE_ENABLED` | true | **false** (same; set both to `"true"` in `cloud/wrangler.toml` and redeploy to enable) |
| Entitlement key id | `exilelens-entitlement-staging-1` (not trusted by any shipped build) | `exilelens-entitlement-1` (public key in `PRODUCTION_ENTITLEMENT_KEYS`) |

Private keys and all secrets live only as Worker secrets (and an offline backup of the entitlement keys under
`%USERPROFILE%\.exilelens\signing\`). Nothing secret is in the repository. Repository variable
`EXILELENS_CLOUD_API_URL` = `https://api.exilelens.app` (set after production validation; `release.yml` embeds it).

## Kill switches
`INGEST_ENABLED=false` -> telemetry/errors answer 503 `ingest_disabled` with `Retry-After: 3600` (verified live; clients back off).
`PATREON_LINK_ENABLED=false` -> `link/start` 503 `link_disabled`. `LEASE_ISSUANCE_ENABLED=false` -> leases lapse within 7 days.
Change a var in `cloud/wrangler.toml` and `wrangler deploy --env <env>`; propagation takes a few seconds.

## Validated against the real services
Staging and production: contract accept/reject, duplicate batch, 400/413/415, forget, DB separation, no forbidden data in rows.
Staging only: Free-plan rate limiting (429 under burst), both cron triggers (daily aggregation into `metrics_daily`, Patreon
retention), real Python client matrix (OFF/OFF, usage-only, errors-only, opt-out purge + forget, Worker-unavailable backoff),
real Patreon OAuth link / refresh / unlink with the creator account, Ed25519 lease signed by the deployed Worker and verified by
the app (tamper / wrong signature / unknown kid / wrong device / expired / update-key confusion rejected).
Production Patreon (client `ExileLens`, redirect `https://api.exilelens.app/v1/patreon/oauth/callback`, scope `identity`): real OAuth with the
creator account returned `not_entitled`; callback, code exchange, identity, device credential, production-signed lease (verified in Python,
tamper / wrong signature / unknown kid / wrong device / expiry / update-key confusion rejected), refresh, wrong-device 401, unlink and
refresh-after-unlink 401 all verified. The client secret exists only as a Cloudflare production secret. All activation test rows were then
deleted from the production databases by exact key (production holds no data).
Packaged tester build against production: defaults OFF with no cloud directory; opted-in run delivered `app_started` /
`pob_connected` only; trust report shows only `exilelens-prod-1`.

## Not validated against real services (accepted for activation)
Mocked / unit-tested only: eligible paid patron, gifted, free trial, declined, free member. The creator account returned
`not_entitled`, as expected. Real `expires_in`, refresh-token rotation and the `fields[user]=` behaviour are not observable
by design (no token/response logging). A production-signed N -> N+1 update
through the protected release workflow has no non-release smoke and remains a go/no-go item for the first real release.

## Windows fixes found during activation
`exilelens.cloud.tls`: the cloud client trusts only the Windows ROOT store (an expired cross-signed anchor in the CA store makes
default Python reject valid Let's Encrypt chains). Cloudflare 1010 blocks the `Python-urllib` User-Agent; the client always sends
`ExileLens/<version>`.
