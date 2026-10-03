# ExileLens cloud (Package A: usage statistics and error reports)

One Cloudflare Worker (TypeScript, `/v1` API) that receives **opt-in** usage statistics and
error reports from the ExileLens desktop app. It must run on **Workers Free + D1 Free**:
no KV, Queues, Durable Objects, R2 or other paid features.

* Canonical contract (single source of truth, shared with the Python client):
  `schema/events.v1.json`, golden fixtures `contract/fixtures.json`.
* Two logically separate databases in the final product: `TELEMETRY_DB` (this package) and
  `PATREON_DB` (Package B, not present yet). Telemetry code only ever receives the object built
  by `telemetryEnv()` in `src/env.ts`; nothing under `src/telemetry/` may import from
  `src/patreon/` (enforced by a test). No SQL joins or shared identifiers across the two.

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
npm run dev                           # wrangler dev (local mode)
npm run typecheck
npm test                              # vitest in the Workers runtime against a real (Miniflare) D1
```

Tests (`test/`) run every golden fixture through the validator and exercise real SQL for ingest,
dedupe, caps, forget, error grouping, cron aggregation/retention, and the report queries.

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

Cron: `17 * * * *` hourly. At 03:xx UTC it aggregates yesterday into `metrics_daily`, then applies
retention; other hours run only a small bounded retention pass. Deletes are chunked (2000 rows,
at most 25 rounds per table) and capped at 45 D1 queries per run to respect the Free limit of 50
queries per invocation.

Retention: usage events 30 d, install activity 120 d, aggregates 13 months, error groups 12 months
after last seen, error/install links 60 d, batch ids 7 d, installs 13 months after last activity.

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
