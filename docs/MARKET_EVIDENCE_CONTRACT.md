# MarketEvidence contract (v1)

Status: R5-B. The contract, the service and the post-paint lifecycle exist and are tested with injected providers. **The production live provider
remains policy-blocked** (`market_policy.LIVE_TRADE2_AUTHORIZED = False`), so in a shipped build every enabled lookup resolves to
`UNAVAILABLE / PROVIDER_NOT_AUTHORIZED` without a request. There is no user-facing market UI yet (R5-C).

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
  timeout, conversion, containment of every exception. It reuses the provider, trust model, rate policy, FX and league resolver.
- Evidence cache key: `(league, compiled-query fingerprint)`; TTL 10 minutes; only `AVAILABLE` evidence is cached; a hit ages its `freshness`. The PoB build is
  not part of the key because price estimation does not depend on it.

## Lifecycle (`EvaluationController`)

Item Check paints (`TERMINAL_PAINT`) -> `_maybe_schedule_market_evidence` -> off: nothing; policy-blocked: typed evidence inline, no thread; permitted: one
daemon thread (never the PoB worker queue) -> result is applied to a copy of `_last_result` only if the job id, parent request id, presentation generation,
baseline generation, market settings (enabled, consent version, league) and candidate content hash all still match. A new Item Check obsoletes the pending job;
the provider may finish, its result is dropped. `market_evidence_updated(request_id, result)` is emitted for in-place re-rendering; nothing renders it yet.

## Diagnostics

Operational state only: access state, provider id, last status/reason code, freshness, rate-limited, pending, cache size, lookup count. Never queries, listing
ids, sellers, prices, item text, PoB XML or build/character identity. No telemetry events.
