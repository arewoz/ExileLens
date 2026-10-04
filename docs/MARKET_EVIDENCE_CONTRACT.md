# MarketEvidence contract (v1)

Status: R5-B (contract, service, lifecycle) and R5-C (presentation, consent/Settings, Diagnostics) are implemented and tested with injected providers.
**LIVE PROVIDER ACTIVATION REMAINS POLICY-BLOCKED** (`market_policy.LIVE_TRADE2_AUTHORIZED = False`): no market control is offered, no request is made,
and Item Check shows nothing about the market. The UI below is complete but dormant until a provider is authorized.

## Shape (`price_check/market_evidence.py`)

`result["market_evidence"]` is a plain dict (`MarketEvidence.to_dict()`), absent when market prices are off. Item Check results are complete and valid
without it; no consumer may assume it exists. It never alters the PoB verdict or `evaluation_outcome`.

| Field | Meaning |
| --- | --- |
| `contract_version` | `1` |
| `status` | `AVAILABLE`, `UNAVAILABLE`, `DISABLED`, `PENDING`, `RATE_LIMITED` |
| `reason_code`, `reason` | Stable code plus a player-safe sentence (e.g. `PROVIDER_NOT_AUTHORIZED`, `UNIQUE_NOT_PRICED`, `PRICE_DATA_STALE`) |
| `provider_id`, `league`, `fetched_at` | Where and when (wall-clock seconds); `fetched_at` is null when no lookup ran |
| `freshness` | `CURRENT / RECENT / AGING / STALE` (listing age, aged further by evidence-cache age) |
| `headline` | `STRONG_COMPARABLE_SET / WEAK_COMPARABLE_SET / SPARSE_MARKET / VOLATILE_ESTIMATE / NO_TRUSTWORTHY_ESTIMATE`; null unless a lookup produced evidence |
| `estimate_state`, `reasons` | The existing `EstimateState` and `TrustReason` values (leading reasons first) |
| `price` | `{display_currency, low, high, point}` or `null`. **`null` for NO_TRUSTWORTHY_ESTIMATE and VOLATILE_ESTIMATE.** `low`/`high` are the 25th/75th percentile of comparable asks, `point` the median. It is the cost to buy a comparable item, never "worth" |
| `band_basis` | `CHEAPEST_COMPARABLES` (the search is sorted by price ascending) or `FULL_SAMPLE` (the server had no more listings than were read); null without a price |
| `comparable_count`, `distinct_sellers` | After per-seller dedupe and outlier trimming |
| `coverage` | Plain sentences for what the search could not include |
| `listed_price` | `{amount, currency, source: "NOTE"}` from the existing `~b/o` parser, or null |
| `listed_vs_market` | `BELOW / WITHIN / ABOVE / NOT_COMPARABLE` or null; see below |

No confidence percentage, score, history, value class or buy recommendation exists in the contract.

`listed_vs_market` is derived only for a Strong or Weak headline with a price, not STALE, in the same normalized currency; it compares against the actual
`[low, high]` with no tolerance. Anything else is `NOT_COMPARABLE`; no listed note gives null.

## Conversion and service

- `evidence_from_price_result(result, ...)` is the one conversion from `PriceCheckResult`/trust to this contract. Deterministic, never raises.
- `MarketEvidenceService` (`price_check/market_evidence_service.py`) is the only thing Item Check calls: access decision first (disabled, `no_network`, provider
  not authorized all short-circuit before the provider is even constructed), compile with the existing planner, evidence cache, one provider lookup with a
  conversion, containment of every exception. It is synchronous and starts no threads; each lookup builds its own provider. It reuses the provider, trust model, rate policy, FX and league resolver.
- Evidence cache key: `(league, compiled-query fingerprint)`; TTL 10 minutes; only `AVAILABLE` evidence is cached; a hit ages its `freshness`. The PoB build is
  not part of the key because price estimation does not depend on it.

## Lifecycle (`EvaluationController`)

Item Check paints (`TERMINAL_PAINT`) -> `_maybe_schedule_market_evidence` -> off: nothing; policy-blocked: typed evidence inline, no thread; permitted: one
daemon thread (never the PoB worker queue) -> result is applied to a copy of `_last_result` only if the job id, parent request id, presentation generation,
baseline generation, market settings (enabled, consent version, league) and candidate content hash all still match. A new Item Check obsoletes the pending job;
the provider may finish, its result is dropped. `market_evidence_updated(request_id, result)` is emitted for in-place re-rendering; nothing renders it yet.

## Diagnostics

Operational state only: access state, pending, cache size, attempted-lookup count (service), plus provider id, status/reason code, freshness and rate-limited of the last evidence the controller ACCEPTED (set only after the stale guards, so a late superseded lookup never looks current). Never queries, listing
ids, sellers, prices, item text, PoB XML or build/character identity. No telemetry events.

## Presentation (R5-C)

`items/market_presentation.py::market_view` is the only place evidence becomes words; widgets render its strings and never read price_check internals.
`result["market_evidence"]` stays the canonical input and absence is the normal state: no evidence, DISABLED, UNAVAILABLE (including policy-blocked, unique),
RATE_LIMITED or PENDING produce **no view at all** (no placeholder, no "unavailable" line). Only `AVAILABLE` evidence is rendered.

| Headline | Compact tooltip (<= 2 lines, under the notes) | More Info "MARKET" section (after Build Context) |
| --- | --- | --- |
| Strong | `Price ~30–36 Ex · Strong market` | range, `Strong comparable set · N listings`, basis, freshness, coverage |
| Weak | `Price ~30–36 Ex · Limited comparables` | same with "Limited" |
| Sparse | `Sparse market · use cautiously` | `Only N comparable listings were found...`, `Observed ~a–b Ex` if the contract has one |
| Volatile | `Volatile market · no reliable price` | `No reliable price: <reason>.` |
| No trustworthy estimate | nothing | `No trustworthy estimate` + the reason |

Listed price: a comparable `listed_vs_market` (BELOW/WITHIN/ABOVE) becomes `Listed 40 Ex · above market ~30–36 Ex`; never for Sparse, Volatile, no estimate,
stale or a different currency (those show only `Listed 40 Ex` in More Info). "Above" is only relative to the observed comparable range.

Build impact + price pairing (`Damage +6.8% · Comparable cost ~33 Ex`, `EHP +11.0% · ...`) uses the measured `evaluation_outcome.item_impact` as is, with no
ratio and no combined score. Shown only for: quality FULL, a MEANINGFUL/MINOR upgrade, no material conflict or negative axis, a Strong/Weak price that is not stale,
and **exactly one** materially positive pairable axis (Damage; or EHP, with Max hit only as a fallback when EHP is not a usable gain). Percentages on different axes are never compared, so Damage + EHP both improving shows the ordinary price line instead. It replaces the price line; hidden for SIDEGRADE, TRADEOFF, PARTIAL, UNCERTAIN, UNSUPPORTED, NOT_VIABLE-like
outcomes, Sparse, Volatile, stale and no-price evidence.

## Capability, Settings and consent

`market_policy.market_capability(settings)` is derived only from `resolve_market_access` (`provider_available`, `user_enabled`, `consent_current`, `access_state`).
Settings shows the **Market prices** switch (and the Market league row, which only matters to it) **only when `provider_available`**; while the provider is
policy-blocked neither row exists, so nothing invites the player to enable a feature that cannot work (chosen over a disabled row: Settings has no other
"unavailable feature" rows, and a permanently greyed control reads as an unfinished feature). Turning it on asks one compact confirmation with the data
statement and then records exactly `MARKET_CONSENT_VERSION` through `set_market_prices_enabled`; turning it off clears the consent record, cancels pending
evidence and removes it from the current result. A consent version that is not current behaves as off. No telemetry or Patreon setting is coupled. Opening
Settings starts no lookup and builds no service.

Diagnostics Market row (always neutral, never an action): `Off`, `Provider unavailable` (current production), `Ready` (+ last listings freshness),
`Looking up…`, `Rate limited`, `Unavailable`.

## Async update

`market_evidence_updated(request_id, result)` -> `ExileLensApp._on_market_evidence_updated` re-renders the open overlay in place through
`update_result_in_place` (a no-op when it is not showing; no reopen, reposition or focus change) after the presentation-generation check. Pinned snapshots and
history are not rewritten. The R5-B identity guards stay authoritative.
