# R2 — Cloud services, telemetry and seamless updates

Canonical, concise description of what R2 adds to ExileLens and the rules it must keep. The server code
and its own runbook live in [`cloud/`](../cloud/README.md); the update machinery is described in
[UPDATE_RELEASE_SIGNING.md](UPDATE_RELEASE_SIGNING.md).

## Principles (enforced by tests)

1. **The core app never needs the cloud.** Item Check, Analyze Build, PoB, Shift+C and the manual GitHub
   updater work with Cloudflare, D1, Patreon or GitHub's API unavailable. Losing telemetry is always
   preferable to affecting the app.
2. **Free users lose nothing.** *Download & Install* and *Restart & Update* stay exactly as they were.
3. **Everything optional is opt-in.** Usage statistics and error reports are separate switches, both
   **off by default**. Neither implies the other, and neither implies a Patreon link.
4. **GitHub plus the signed manifest remain the update authority.** The cloud can at most say "this client
   may automate" — never which file, URL, hash or version to install.
5. **Pseudonymous, separated data.** Usage statistics, error reports and (later) Patreon data use different
   random identifiers, different server-side secrets and different D1 databases.
6. **Cloudflare Free first.** Everything runs on Workers Free + D1 Free; upgrading is an operational
   decision made from measured usage, never a code requirement (see *Free-tier operation*).

## Package A — what is implemented

### Contract (single source of truth)

`cloud/schema/events.v1.json` defines every accepted field, enum, bound, the retention periods, the
"never collected" list and the identifier descriptions. It is consumed by:

| Consumer | How |
|---|---|
| Worker (`cloud/src/contract.ts`) | validates every request; unknown fields are rejected (fail closed) |
| Client (`src/exilelens/cloud/contract.py`) | validates every item *before* it is queued |
| *See what is collected* dialog | generated from the same file, so it cannot drift |
| Tests | `cloud/contract/fixtures.json` is run by **both** validators; a byte-equality test keeps the packaged copy (`src/exilelens/cloud/events.v1.json`) identical |

There is no free-text or metadata field. Values are enums, booleans, bounded integers, strict version
strings or strict identifiers.

### Usage statistics (`UsageTelemetry`)

`app_started`, `onboarding_completed`, `pob_connected`, `item_checks_summary`, `analyze_build_completed`,
`update_detected`, `update_download_completed`, `update_install_completed`. Item Check results are counted in memory
by category and uploaded as one `item_checks_summary`; there is never an event per check and no per-check
timestamp. Timestamps are rounded to the hour.

### Error reports (`ErrorReporter`)

Built from objects, never scrubbed from text: registered `EL-*` code, component, allowlisted exception *type*,
up to 12 normalised frames (`module`, `function`, optional `line`), count, first/last hour. The exception
message, `co_filename`, locals and environment are never read. Grouping is deterministic on the server:
`sha256(code | exception type | top 5 module:function)`. `UNCERTAIN`/`UNSUPPORTED` results are evaluation
limitations, not errors, and are never reported.

### Unexpected session end

A local marker (`cloud\session.json`, written only while a category is on) is `running` during a session and
`clean` after an orderly shutdown. A leftover `running` is reported as `previous_session = unexpected`.
This is **not** crash detection: power loss, Task Manager, a forced Windows shutdown and native crashes all
look the same. Reports call it "unexpected session end", never "crash-free".

### Identifiers

`analytics_id` and `diagnostic_id` are random UUIDv4 values created lazily on the PC when a category first
has something to send. No hardware, Windows account, network, PoE or Patreon information is used. The server
stores `HMAC-SHA256(secret, "<domain>:" + uuid)` with a separate secret per domain
(`ANALYTICS_PEPPER`, `DIAGNOSTIC_PEPPER`). Turning a category off deletes its local ID/queue immediately and
sends one best-effort `forget` request; turning it on again creates a new identity. A request already in flight
when the switch is flipped may still complete.

### Transport

* One background thread (`exilelens-cloud-flush`); nothing runs on the hotkey or Item Check path. Result
  slots are connected with `QueuedConnection` and only increment in-memory counters.
* First upload ≈ 60 s after start, then at most every 30 minutes and only if there is something to send.
  Batches are ≤ 100 events and ≤ 32 KB. No request per event.
* Bounded queue: 500 items, 256 KB, 7-day TTL, oldest dropped first; persisted at shutdown with a small local
  write — shutdown never waits for the network.
* Backoff: exponential 1 min → 6 h with jitter, `Retry-After` always honoured (up to 24 h). `400/413/415/422`
  drop the batch (never retried); `410` disables the category until the app is updated.

### Endpoint configuration (fail closed)

`exilelens.cloud.endpoint.cloud_base_url()` is `None` — all cloud features off, toggles disabled — unless the
build was configured:

* **Packaged builds** read `release_config.json` next to the module. It is generated by `release.yml` from the
  repository variable `EXILELENS_CLOUD_API_URL` (https origin; `*.workers.dev` is refused) and is git-ignored.
  Absent file = cloud off. The release gate (`cloud_config`) rejects an invalid file and a contract mismatch.
* **Source runs** may set `EXILELENS_CLOUD_URL` (including `http://127.0.0.1` for `wrangler dev`).
* `security_audit.network_disabled()` turns everything off.

### Privacy UI

Settings → **Privacy** (two switches, status line, **See what is collected**) and a one-time, non-modal card on
the Overview page after onboarding with both boxes unchecked. Consent is stored with the contract's
`consent_version`; if a release materially widens collection the version increases and old choices count as OFF
until confirmed again. *Reset configuration* turns both off and purges.

## Free-tier operation

Cloudflare Workers Free allows 100k requests/day and 10 ms CPU per request; D1 Free allows 100k rows written
and 5M rows read per day. The server writes roughly *events + 3* rows per accepted batch, so the free write
quota is the first limit (order of a few hundred opted-in daily-active installs). When a quota is exhausted
D1 refuses writes: the Worker answers `503 storage_unavailable` with `Retry-After: 3600`, clients back off and
keep their bounded queues, old items expire. Nothing in the app changes.

Review the Paid plan only when measured usage is **consistently around 60–70 % of a daily hard quota** or
growth shows it will be reached. Nothing in the code requires Paid, and billing is never changed by code.

## Abuse model

The app is open source, so no embedded client secret can authenticate telemetry. Defences are layered and
deliberately not "perfect": strict schema (no free text), size/count caps, per-install daily caps keyed on
the install hash, a global kill switch (`INGEST_ENABLED`), an optional coarse per-IP Rate Limiting binding
(IP is never stored) and a recommended Cloudflare WAF rule. Fake installs can pollute metrics; reports label
all numbers "opted-in active installations, best effort".

Operational logs (Workers Logs) are separate from product data: they hold route/status/timing only, are never
used for metrics and never contain bodies, IDs or hashes.

## Metrics (read-only reports)

`cloud/reports/*.sql` + `cloud/scripts/report.mjs` produce: active installations 1/7/30 days, new and returning
installations, D1/D7/D30 retention (small cohorts suppressed), active Item Check installations and checks per
active installation, verdict distribution, Analyze Build adoption, top error groups with affected diagnostic
installations, unexpected-session-end rate, update adoption and update failure rate. Every report is labelled
*opted-in active installations — not users*.

## Package B — Patreon link and entitlement lease

Patreon is **not** an account system and not DRM. Linking only lets the service issue a signed statement that this
device may automate updates (capability `seamless_updates`). Core features, the manual updater and telemetry are
unaffected by whether Patreon is linked.

### Flow (no client secret, no local server, no custom URI scheme)

1. App → `POST /v1/patreon/link/start` → `session_id`, `poll_token`, `authorize_url` (TTL 10 min). The app opens the
   URL only if it is exactly `https://www.patreon.com/oauth2/authorize` (no credentials, default port).
2. Patreon → Worker `GET /v1/patreon/oauth/callback?code&state`: the state is single-use (atomically consumed), the code is
   exchanged **server-side** with the client secret, `identity` is read once, the policy is evaluated, tokens are
   stored encrypted (AES-256-GCM, AAD = link id).
3. App polls `GET /v1/patreon/link/status` with the poll token. A wrong token and an unknown session produce an
   identical `404`. The first poll after success atomically creates the device and returns the random device token
   and the first lease **once**; later polls say `consumed`.
4. Refresh: `POST /v1/patreon/entitlement/refresh` with the device token about every 24 h. Unlink:
   `POST /v1/patreon/unlink` (idempotent). The app removes its local credential and lease first.

### Data minimisation and separation

Scope `identity` only (with a creator-registered client Patreon returns only the membership to the creator's campaign).
Read: user id (stored only as an HMAC), `patron_status`, `is_gifted`, `is_free_trial`, entitled tier ids and tier
`amount_cents`. Never requested: email, name, address, pledge history, posts. `PATREON_DB` is a different D1
database with its own secrets; telemetry handlers cannot receive it and nothing is joined or shared.

### Policy (server-side, replaceable)

`ENTITLEMENT_POLICY` (Worker var): *any active paid tier* → `seamless_updates`; gifted and free-trial memberships
are eligible; free memberships, declined/former patrons and memberships of other campaigns are not; an owner
override list (by HMAC) covers the creator account. Changing tiers is a config deploy, not an app release.

### Lease

`{schema, kid, lease_id, sub, capabilities, issued_at, refresh_after, expires_at, policy_version}` signed with
Ed25519; the signed message is `"exilelens/entitlement-lease/v1\n" + canonical JSON`. Refresh target 24 h, validity
7 days. The key is separate from the update-signing key and its verifier set is disjoint from the update trust set
(tests). The client's only output is a `frozenset` of known capability names; unknown capabilities and unknown fields
cannot influence anything. A Worker-signed vector (`cloud/contract/lease_vector.json`) is verified by the Python
client in the test suite.

Outages: Cloudflare, D1 or Patreon down → `503` and no new lease, the client keeps its valid lease ("offline grace",
at most the remainder of the 7 days) and backs off. Expired, missing, tampered or foreign-device lease → free behaviour.

### Credential storage

The device token is protected with per-user Windows DPAPI (`cloud\patreon\device.bin`, application-specific
entropy, no size limit); the lease and status are non-secret files in the same folder. An unreadable credential
shows "Please reconnect Patreon". Production leases cannot verify until the owner provisions
`PRODUCTION_ENTITLEMENT_KEYS` (see `scripts/create_entitlement_key.py`), so supporter automation stays dark until
activation.

### Live-API assumptions that need a real account to prove

Patreon's docs do not state whether PKCE is supported, how redirect URIs are matched, the real `expires_in`, whether an
empty `fields[user]=` is accepted, or provide a token-revocation endpoint. The implementation assumes none of them;
see *Live activation checks* in `cloud/README.md`.

## Package C — Seamless updates

Supporters (valid lease with `seamless_updates`, signed `seamless_eligible` not false) get: automatic background
download, background pre-staging, install when ExileLens closes (cleanly, by the user, never during a Windows
session end or after a crash), and an explicit **Restart now**. It is the **same** pipeline as the manual flow (see
`docs/UPDATE_RELEASE_SIGNING.md`); entitlement is a yes/no gate with no way to supply a URL, hash, version or file.
Free users keep *Download & Install* and *Restart & Update* unchanged, and nothing here ever restarts the app unasked.

Settings → Updates → **Seamless updates** (the supporter zone) shows the states: not connected, linking, active (with the two toggles, default on),
connected but not eligible, offline grace, expired, reconnect required and service unavailable. Every non-active state
says that manual updates still work.

## Failure behaviour

| Condition | Core app | Manual updates | Supporter automation | Cloud features |
|---|---|---|---|---|
| Cloudflare / D1 down, quota exhausted | works | works | valid lease keeps working (≤ 7 days) | queues stay bounded, back off, expire |
| Patreon down | works | works | valid lease keeps working; new links fail with "temporarily unavailable" | unaffected |
| Lease expired / tampered / wrong device | works | works | off (free behaviour) | unaffected |
| Membership ended | works | works | off at the next lease (≤ 24 h, lease ≤ 7 d) | unaffected |
| GitHub down | works | check fails quietly | no new updates | unaffected |
| Bad signature / hash / manifest | works | blocked for that release | blocked | unaffected |
| Session end (logoff/shutdown) | exits | — | install skipped, update stays pending | cloud queue saved locally |