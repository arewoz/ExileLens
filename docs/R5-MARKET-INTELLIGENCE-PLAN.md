# R5 — Economy / Market Intelligence: repository audit and implementation plan

**Status:** R5-A is complete and merged (#75, `25959b9`). R5-B (MarketEvidence + async enrichment) is implemented on `r5-b/market-evidence-enrichment`; see the records at the end. The live trade2 provider remains **policy-blocked**.

Base: `origin/main` `a6dc07b` (R4 squash-merged). Branch `r5/market-intelligence-1.0`. Planning pass only: the one code change is the verified
`MarketQueryPlan` import fix (§2). Nothing here changes behaviour of Item Check. Version unchanged (not 1.0.0); this is not R6 (Upgrade Finder) and not R3 (character sync).

Evidence labels: **[verified]** = I read the code or ran it in this pass; **[static]** = reported by a read-only code audit and spot-checked where it matters
but not run; **[verify-external]** = depends on GGG behaviour or terms that cannot be established from this repository.

## 0. Summary (what changes the plan)

1. R5 does **not** start from zero, and it does not start from a working feature either. The repo holds ~19k lines of live-trade price estimation
   (`src/exilelens/price_check/`, a build-independent "MARKET-03" compiled-query pipeline with a real trust model), a separate ~1.2k-line build-driven
   candidate search (`market/`, offline fixtures only), a clipboard capture assistant (`market_assist/`), a budgeted gear optimizer (`gear/`), and a manual
   price + `power_per_currency` layer inside Item Check.
2. **None of the live price code is reachable from the running app [verified].** Shift+C goes to Item Check and the code says so (`controller.py` comment in
   `_on_price_check_capture_ready`); `submit_price_check` is only called from inside its own retry/refine chain, which nothing starts. The legacy panel
   surfaces are built and signal-connected but have no trigger.
3. **The only live network call in the default app is the league-list fetch at startup**, and it ignores every live-market off switch and the `no_network`
   audit variant [verified: `LeagueCatalog.refresh` and `Trade2Client` consult none of `is_live_market_enabled` / `network_disabled`]. It runs on the Qt main
   thread with a 30 s timeout [static]. `PRIVACY.md` says the official site is contacted only "for optional market features". This is a privacy/behaviour mismatch
   that must be fixed first (R5-A, P0).
4. **There are effectively no tests for any of it** [verified for market/, price_check/: grep]. The repository history starts at the public import; no price/market
   tests were ever in it. `fixtures/market/` (referenced by `DEFAULT_CORPORA`, the comparable corpus, the diagnostic item and the desirability corpus) **does not exist**
   [verified], so the "offline fixture funnel" silently returns zero listings. `ops/compatibility.json` claims it "is covered by unit tests"; it is not.
5. The price estimator is build-independent by design (`desirability.py`: nothing reads PoB). That is the right boundary: PoB stays the source of truth for impact,
   the market layer answers "what does this item cost and how far can I trust that". R5 combines them at the presentation/contract level only.
6. The existing trust model is good enough to keep and is not a numeric score: `EstimateState` (HIGH CONFIDENCE / ASSISTED ESTIMATE / NEEDS REFINEMENT / BASE MARKET
   ESTIMATE) over named, deterministic reasons. R5 adds a thin mapping and fixes evidence gaps; it does not invent a model.
7. What must **not** survive into 1.0: `power_per_currency` and its EXCELLENT/GOOD/FAIR/LOW/BAD classes (a universal score from Build Value ÷ price with "MVP" thresholds).

## 1. Current architecture map

### 1.1 Item Check side (default runtime)

| Piece | Where | State |
| --- | --- | --- |
| Manual price + `power_per_currency` | `items/price.py`, `items/ranking.py:299`, `items/value_layer.py`, `controller.apply_manual_price`, `_patch_presentation_price` | Works; **no default UI sets a manual price** (`ui/price_dialog.py` is not wired). `heuristic: True, mvp_thresholds: True` in the payload. |
| `~b/o` price note from copied item text | `market_assist/price_parser.py` via `controller._attach_market_context` → `presentation["price"]` ("PRICE NOTE") | Works by default, purely local. This is the only price a default Item Check can show. |
| Presentation price block | `items/presentation.py:759` `_build_price_block` (sources: market capture session, note, manual) | Renders in the full surface; the compact tooltip does not budget a price line. |
| Post-paint enrichment pattern | `controller._maybe_schedule_upgrade_path`, `_maybe_schedule_build_decomp`, `_on_*_finished`, `upgrade_path_updated` → `overlay.update_result_in_place` | **The precedent R5 should copy** (§9). |
| Compact budget | `compact_tooltip.py` (`MAX_NOTES=2`, `build_context_lines` ≤2) | A price/confidence line needs its own budgeted field. |

### 1.2 `price_check/` — live trade2 price estimation (large, parked-in-practice)

| Stage | Where | Notes |
| --- | --- | --- |
| Plan: mods → roles (ANCHOR/FLEXIBLE/OPTIONAL/INFORMATIONAL/DEAD) | `market_mod.py`, `desirability.py`, `market_profiles.py`, `base_value.py`, `defence_semantics.py`, `mod_tier.py`, `stat_registry.py` (51 stat families) | Deterministic, offline, build-independent. Range policy per mod (tier floor, breakpoint, pseudo aggregate, exact for fractured). |
| Compile | `market_plan.py` `plan_for_item`, `TradeQueryCompiler` → `CompiledTradeQuery` + coverage report; `trade2_query_validation.py` | Validates/repairs the wire body locally; records what could **not** be searched. |
| Service + providers | `service.py`, `provider.py` (`MarketCandidateProvider` Protocol), `factory.py` chain: `MarketSessionProvider` → `LiveTradeComparableProvider` → `CachedLiveMarketProvider` → `ObservationCorpusProvider` (+ theoretical fallback) | A provider boundary **already exists**; fixture/import/observation/theoretical providers exist. |
| Live client | `trade2_client.py` (urllib, anonymous), `rate_policy.py` (per-endpoint sliding windows from headers, persisted penalties), `rate_limit.py` (older duplicate), `network_withhold.py` (pause/resume data types), `league_catalog.py` / `league_resolver.py`, `currency_fx.py` (exchange-endpoint rates, 15 min TTL) | Complete in design; never exercised by a test; user agent still `poe2-value-overlay/0.5`. |
| Pricing + trust | `comparable_pricing.py` (normalize → IQR/MAD outliers → per-seller dedupe → p25/p40–p60/p75 bands), `price_trust.py` (`assess_price_trust`) | See §5. |
| Presentation | `panel_model.py`, `presentation.py`, `ui/interactive_price_check_panel.py` | Probable defects, §3.4. |

### 1.3 `market/`, `market_assist/`, `gear/`, `analysis/` — build-driven search (parked)

| Stage | Where | State |
| --- | --- | --- |
| SearchIntent (required/high-value/useful/avoid per slot) | `analysis/search_intent.py`, `opportunity.py`, `slot_compat.py` (via Analyze Build, default runtime) | Implemented, PoB-backed, offline; `docs/SEARCH_INTENT_CONTRACT.md`. |
| Query plan / prefilter / budget / dedupe | `market/query_plan.py`, `prefilter.py`, `engine.py` | Implemented. Plan is a local object; **no trade2 query is built from an intent.** USEFUL tier never reaches the plan; prefilter hints cover ~13 keys. |
| Candidate sources | `market/sources.py` `CandidateSource` Protocol; `FixtureCandidateSource`, `ImportedCandidateSource` | Offline only. `source="live"` silently becomes a fixture source. |
| PoB candidate evaluation + cache | `market/engine._evaluate_listing`, `eval_cache.py` | Real PoB; **cache key omits profile and price** [static]. |
| Frontier / categories | `pareto.py`, `categories.py` | Implemented (`apply_pareto_flags` unused). |
| Status text | `engine.py` hard-codes "LIVE MARKET NOT AVAILABLE — fixture/import only" | **Still true [verified]** — and it is a constant, not derived from the source. |
| Multi-slot optimizer | `gear/` | Implemented; parked. |
| Capture assistant | `market_assist/` (clipboard sessions, guidance, finalization) | Parked; passive, no network. |

Module gating: `SUPPORTED_MODULES = {ITEM_CHECK, BUILD_ANALYSIS}`; MARKET, MARKET_ASSISTANT, GEAR_OPTIMIZER parked. Price Check has **no** module gate: only
`settings.price_check_enabled` (True) and `live_market_mode` (`"auto"`), so "parked" is true by lack of a trigger, not by a switch.

## 2. The `MarketQueryPlan` static error — real, fixed

`market/engine.py` used `MarketQueryPlan` in the stale-build-revision early return of `run_market_search` without importing it (defined in `market/models.py`). The branch
raised `NameError`, surfaced by the controller as a generic error instead of "Build file changed — refresh baseline". Fixed with the one-line import;
`tests/test_r5_market_engine_stale_revision.py` fails without the fix and passes with it [verified]. `ruff check src tests scripts` is clean. No broader cleanup.

## 3. What already exists, what is dead, duplicated or stale

### 3.1 Reusable (keep)
- Compiled query pipeline and its coverage report ("not included in the search: X"): truthful about what was searched. Keep as the single estimator.
- `assess_price_trust` and its enums: pure, deterministic, unit-testable (§5).
- `MarketCandidateProvider` Protocol + factory chain; fixture/import/theoretical providers; `InFlightCoalescer`; `PriceCheckCache` + `TimedResponseCache`.
- `rate_policy.py` (header-driven pacing, persisted penalties, clock hook) and `network_withhold` data types.
- `market_assist/price_parser.py` (`~b/o`), `league_catalog`/`league_resolver`.
- The post-paint enrichment machinery in `controller` and `overlay.update_result_in_place`.
- From `market/`: intent → plan → prefilter → PoB eval → frontier: the **R6** skeleton.

### 3.2 Dead, duplicated or stale (do not extend; resolve or leave marked)
- **Two confidence vocabularies** (`PriceConfidence` HIGH/MEDIUM/LOW/NONE from `ConfidenceScorer`, and `EstimateState` from the trust layer, which overwrites the former). Keep `EstimateState`.
- **Two query models** (legacy `MarketPriceDriver`/`PriceCheckHypothesis` + discovery/signatures vs `MarketSearchPlan`); the legacy path is reachable only through refine. Freeze; do not feed it.
- **Two rate-limit systems** (`rate_limit.RateLimitState`, `rate_policy.TradePolicyRegistry`) parsing the same headers; **two FX tables** (`market/currency.py` manual, `price_check/currency_fx.py` live); **two league resolvers**; **two `CandidateSource` protocols** (`analysis/candidates.py` is unused and stale); **two near-copy live pipelines** (`_lookup_pipeline` vs `_lookup_pipeline_resume_fetch`).
- Unused: `apply_pareto_flags`, `build_dev_price_check_providers`, `RateLimiter` (old), `desirability_corpus.py` (no fixtures), `Trade2Client.stats_data`, dead branches in `comparable_query.build_search_query`, a shadowed `_normalize_family_name` [static].
- Missing: `fixtures/market/*` (corpus, comparable corpus, diagnostic ring, desirability corpus). `docs/PARKED_FEATURES.md` describes a conftest auto-marking hook that does not exist; `ops/compatibility.json` and `ops/regression_registry.json` contradict each other on market tests.
- `market_assist` bug: `best_value_observation_id` is set even when nothing is priced (`best_ppc` starts at -inf). Parked; note only.
- `README.md` advertises "Optional live market pricing"; nothing in the default flow produces one.

### 3.3 Item Check pricing today
`power_per_currency = Build Value score_delta ÷ price`, classified EXCELLENT ≥12 / GOOD ≥6 / FAIR ≥3 / LOW ≥1 / BAD, with the in-code comment "MVP heuristic … Not a market
truth". It also hard-codes `converted: False` after a manual FX conversion. It shows as "VALUE / COST +x Build Value / currency · classification" in the full overlay.
This is exactly the universal score the product rules forbid (§8).

### 3.4 Probable defects in the estimator output path [static — verify in R5-A with fixtures]
1. The interactive panel builds `price_text` from `view["market_price"]`, but the presentation sets `market_price = None` in every `show_currency` branch, so the panel
   likely shows a listing count and **no price**; bands exist in `currency_bands` and are not read.
2. The controller passes the trust assessment as a `dict` (`discovery["price_trust"]`) while the panel model reads it with `getattr`, so the trust label/note are likely always empty.
3. Compiled-path **similarity evidence is empty** (`_live_similarity_match` returns True; discovery only has `h2_disabled_reason`), so `SimilarityBand` is UNKNOWN and
   `HIGH CONFIDENCE` appears unreachable on the default path; also `ConfidenceScorer`'s HIGH/MEDIUM need ≥20–30 comparables while the fetch loop stops after the first batch (~10).
4. The search is sorted `price asc` and the sample is the first batch: quick-sale/fair/optimistic bands are all computed from the **cheapest ~10**. That is a sound "what would I pay" estimate and a biased "what is it worth"; labels must say which.
5. Compiled uniques are queried by base type + rarity + stats (no name filter in the compiler); a unique's price may be a base-type price.
6. Ordinary items get no ilvl / corrupted / socket / quality / requirement filters (by design for finished rares); corrupted and uncorrupted comparables mix.
7. Exception escapes: `InvalidTradeQuery` out of the provider lookup; FX conversion without a guard; no try/except around `provider.lookup` in `PriceCheckService.check`.

## 4. Live-market feasibility

**Current state.** The code anticipates and implements anonymous live trade2: search (`POST /api/trade2/search/poe2/{league}`), fetch (`GET /api/trade2/fetch/{ids}?query=`),
leagues (`GET /api/trade2/data/leagues`), exchange rates (`POST /api/trade2/exchange/poe2/{league}`) against `https://www.pathofexile.com`, via `urllib`, header
`User-Agent: poe2-value-overlay/0.5 (price-check)` [static]. Pacing parses `X-Rate-Limit-*` headers; cold-start limits are hard-coded from a "2026-09-08" observation.
Authentication: **none by default**. An optional `POESESSID` cookie is read only from env `POE2VALUE_TRADE2_SESSION`; there is no OAuth, no settings field, no UI (a 401 shows "CONNECT TRADE" with no flow behind it).
`ops/market_canary.py` is an opt-in live probe (`EXILELENS_LIVE_MARKET_CANARY=1`). **I did not make any network call in this pass.**

**Does R5 need R3/OAuth?** No. Price estimation uses the same anonymous endpoints the code already targets; OAuth is a different (account) API family. R3 being blocked is not an R5 blocker.

**What is currently live in the app:** only the startup league-list fetch (above). Everything else is unreachable.

**[verify-external] before enabling live estimation by default** (the owner or a short research task; do not rely on memory):
1. That anonymous, unauthenticated use of `/api/trade2/*` by a third-party desktop tool is permitted by GGG's current developer terms/policies, and what they require (User-Agent format and contact, attribution, request volume, "no automation of purchases").
2. Current endpoint paths/contracts and stability for PoE2 (search body schema: `status.option`, `type`, `name`, `filters.type_filters`, `equipment_filters`, group types, count `value.min`, `sort`; fetch batch cap of 10; exchange body incl. `"engine":"new"`; response shapes parsed by `parse_exchange_rate`).
3. Rate-limit headers and rules (`X-Rate-Limit-Policy/Rules/-State`, penalties, `Retry-After`) and the cold-start numbers hard-coded in `rate_policy.py`.
4. Whether `/data/leagues` is rate limited without headers (code assumes 1 request / 10 s) and the league id/name conventions (Standard/Hardcore/"HC " rules).
5. PoE2 currency ids (the alias list covers divine/exalted/chaos/regal only).
6. Whether a CDN/bot-protection layer rejects non-browser clients (the code works around "Cloudflare 1010" elsewhere in this project by sending a non-urllib User-Agent).
Run `ops/market_canary.py --live` once manually, owner-approved, to confirm 1-4 on the current API.

## 5. Price-confidence model (smallest credible)

Keep the existing deterministic trust layer; add only a **headline mapping** and fix the evidence gaps in §3.4. No numeric score, no ML.

| Headline (user words) | Condition (from existing signals) | Maps from | Shows |
| --- | --- | --- | --- |
| **Strong** | HIGH CONFIDENCE: sample ≥8 accepted, similarity STRONG, dispersion TIGHT/NORMAL, not multimodal, liquidity not ILLIQUID, freshness ≤24 h, FX coverage ≥80%, specificity USEFUL, stability STABLE | `EstimateState.HIGH_CONFIDENCE` | price band + count |
| **Moderate** | ASSISTED ESTIMATE: median exists, sample ≥ LIMITED, only soft vetoes (thin liquidity, partial FX, omitted anchor, weakened query) | `ASSISTED_ESTIMATE` | band, "treat as a guide" + the soft reason |
| **Sparse market** | few comparables or thin liquidity: SAMPLE_THIN / LIQUIDITY_THIN as the leading reason | `NEEDS_REFINEMENT` with `SAMPLE_*`/`LIQUIDITY_*` | observed range only (q25–q75), "use cautiously" |
| **Volatile** | MARKET_MULTIMODAL or PRICE_WIDE leading | `NEEDS_REFINEMENT` | observed range only, "market has separate price clusters" |
| **Base only / No estimate** | BASE_ONLY, UNSUPPORTED_IDENTITY, STALE, SIMILARITY_WEAK with no usable range, or provider failure | `BASE_MARKET_ESTIMATE` / `NEEDS_REFINEMENT` with no range / provider error | "No trustworthy estimate", reason, **no number** |

The five names requested (STRONG_COMPARABLE_SET, WEAK_COMPARABLE_SET, SPARSE_MARKET, VOLATILE_ESTIMATE, NO_TRUSTWORTHY_ESTIMATE) become the internal enum of the new `MarketEvidence` contract (§7) as a **pure function of the existing `PriceTrustAssessment`**; the wording above is player-facing.

Signals already supported: accepted count, similarity median/low-quartile, IQR+CV dispersion, multimodality (gap ratio 2.5, ≥2 per side), liquidity from the server's total result count, listing + cache freshness, FX coverage, query specificity, coverage omissions (what the query could not express), stability, per-seller dedupe. Signals to **add** (small): query looseness as a first-class reason (compiled queries are STRICT-only; record promoted/dropped filters, `COVERAGE_*` already does this), listing concentration beyond per-seller dedupe (e.g. few distinct sellers), and `OUTLIER` structure as a reason (it is labelled but produces nothing).
Rules to fix: server-matched similarity (§3.4 item 3): for a compiled STRICT query each listing matches **by construction of the query**, so evidence = `SERVER_MATCHED` (STRONG only when the coverage report has no omitted anchor/group), instead of UNKNOWN; sample-size reasoning must use the real fetched sample (and fetch ≥ 20 when the server reports ≥ 20 results, bounded by §10) so HIGH is reachable at all.
Never expose raw IQR/CV; show the reason word and, in More Info, the band and count.

## 6. Comparable-quality model

Preserve the existing selection: it is the strong part. Facts [static]: server-side comparable definition (the compiled query), base role EXACT/FAMILY/CATEGORY, mod normalization and registry
mapping, redundancy groups (one filter per concept), tier floors from real item tiers, pseudo aggregates only with ≥2 contributors, fractured exact, anchors/flexible groups with count-min, and a **coverage report** of everything not searched.

| Question | Today | R5 stance |
| --- | --- | --- |
| Exact vs approximate base | role per class/archetype; FAMILY degrades to category (no family filter in trade2) and records `degraded_reason` | keep; surface "compared with: similar bases" |
| Affix matching | registry-mapped stat ids; unmapped mods are informational only | keep; unmapped anchor ⇒ `COVERAGE_ANCHOR_OMITTED` veto already exists |
| Build-aware desirability | **none, by design** | keep build-independent. Build relevance comes from PoB, not from the price query. Do not weight comparables by the user's build. |
| Corrupted / sockets / quality / ilvl / requirements | filters only for crafting-base/hybrid items | add `corrupted` as a *disclosed* difference (comparable mix) or filter it; decide in R5-A fixtures (open question) |
| Unique vs rare | unique has no name filter in the compiled path | P0 fix or force "no estimate" for uniques until a name-based query exists (R5-A) |
| Crafted/fractured/desecrated | fractured exact; others treated as explicit | keep |
| Outliers | IQR 1.5× + MAD 3.5× (unscaled MAD, unit-dependent fallback), then per-seller dedupe | fix MAD scaling and order (dedupe before fences); add concentration |
| "A listing exists therefore this is the price" | blocked by trust vetoes (sample ≤2 unusable, similarity, multimodal) | keep and **test** every veto |

## 7. Market / value contracts

New, small, serialisable, versioned. They live beside the result dict; they never alter the PoB-derived `evaluation_outcome`.

```
MarketEvidence (contract_version 1)
  status: AVAILABLE | UNAVAILABLE | DISABLED | PENDING | RATE_LIMITED
  reason: str                      # player-safe, e.g. "Market disabled in settings"
  league: str; provider_id: str; fetched_at: float; freshness: CURRENT|RECENT|AGING|STALE
  headline: STRONG_COMPARABLE_SET | WEAK_COMPARABLE_SET | SPARSE_MARKET | VOLATILE_ESTIMATE | NO_TRUSTWORTHY_ESTIMATE
  estimate_state: HIGH CONFIDENCE | ASSISTED ESTIMATE | NEEDS REFINEMENT | BASE MARKET ESTIMATE   # existing EstimateState
  reasons: [TrustReason]           # existing vocabulary, leading reason first
  price: { display_currency, low, high, point? } | null     # null when no trustworthy estimate
  band_basis: CHEAPEST_COMPARABLES | FULL_SAMPLE            # honest about the cheapest-first sample
  comparable_count: int; distinct_sellers: int
  coverage: [ "Not included in the search: …" ]            # existing compiled-query report
  listed_price: { amount, currency, source: NOTE } | null   # ~b/o from the copied item, if any
  listed_vs_market: BELOW | WITHIN | ABOVE | NOT_COMPARABLE | null
```

`CandidateBuildImpact` is **not a new contract**: it is the existing `evaluation_outcome.item_impact` (axes, magnitudes, verdict, quality). `MarketValueContext` = a read-only pairing of
that impact with `MarketEvidence` for presentation: `{ impact_summary, market, efficiency }`.

- **Insufficient market evidence** is a first-class `NO_TRUSTWORTHY_ESTIMATE`/`UNAVAILABLE` state, never an empty price.
- **"Similar build impact appears around X–Y"** requires market candidates evaluated by PoB — that is **R6**. R5 must not compute it from price data and must not render the sentence.
- **Listed-price context** (the one cheap, honest comparison): when the copied item carries a `~b/o` note (the in-game "Copy Item" path already feeds it), show "listed 40 Ex · market ~30–36 Ex" and `listed_vs_market`, only when currencies are comparable and confidence ≥ Moderate.

## 8. Efficiency: what survives

- **Remove for 1.0:** `classify_power_per_currency`, the EXCELLENT/…/BAD classes, `PPC_CLASS_THRESHOLDS`, the "VALUE / COST … Build Value / currency" line, `market_assist` "Best value: X power/currency" in anything user-facing, and any ratio of Build Value to price. Build Value is a profile-weighted score; dividing it by price implies per-point equivalence the project has ruled out (Build Intelligence increments are not comparable).
- **Survives:** *measured improvement alongside cost*, never a derived scalar: "Build improvement +6.8% (offense) · Price ~34 Ex". The user compares two numbers they understand.
- **When shown:** evaluation quality FULL, verdict a directional upgrade with a material POSITIVE axis, price headline Strong or Moderate, price currency comparable to the display currency.
- **When hidden:** PARTIAL/UNCERTAIN/UNSUPPORTED/NOT_VIABLE, SIDEGRADE, TRADEOFF/mixed axes (show impact and price separately without any pairing line), Sparse/Volatile/No estimate, STALE evidence, non-comparable currency.
- **Zero / near-zero price:** no division anywhere; a price below one display-currency floor (set in R5-C, order of 1 Exalted) renders as "<1 Ex", never as an efficiency.
- **Defensive vs offensive vs multi-axis:** pair the price with the *leading measured axis only* and name it ("+11% EHP"); multi-axis outcomes show their existing axis list, no merged number.
- **R6 may rank by improvement/cost internally** over many evaluated candidates; that ordering is an R6 concern with its own rules and is not exposed as a score.

## 9. Provider architecture

Reuse, do not rebuild: `price_check/provider.py::MarketCandidateProvider` (`provider_id`, `capabilities`, `lookup`) and the `factory.py` chain already are the boundary.
R5 adds a thin **`MarketEvidenceService`** (the only thing Item Check talks to) that owns: enablement/consent check, cache-only lookup, one bounded live lookup, error → `MarketEvidence(status=…)` mapping, and timeouts. Providers stay replaceable:

- Fixture provider (kept, new fixture corpus under `fixtures/market/`, synthetic only).
- Import provider (kept if the owner wants offline price notes; otherwise leave unwired).
- Live trade2 provider (kept; behind a **transport seam**: `Trade2Client` takes an injected `request(method, url, headers, body)` callable so tests never touch the network).
- Capabilities report `live`, `requires_auth` (False), `network` and are shown in diagnostics.

Failure contract: every provider exception is caught at the service boundary and becomes `UNAVAILABLE`/`RATE_LIMITED`; **nothing market-related can raise into Item Check**. Item Check must be correct and complete with the market disabled, offline, rate limited, or throwing.
No credentials are committed; no account/password scraping; `POESESSID` env cookie support is removed from the default build (an anonymous-only product), pending owner decision.

## 10. Privacy / security

What a lookup sends today [static]: `www.pathofexile.com` only; league in the URL; body = item base type, rarity, stat ids with minimum values, equipment filters, (uniques: name), `sort`; fetch = listing ids; exchange = currency ids; headers = User-Agent + Accept (+ cookie only if the env var is set). **Not sent:** PoB XML, build name, character/account, clipboard history, other equipped items, raw item text. This stays the rule; R5 adds a test asserting the serialized request body contains no field outside an allowlist.
Required changes:
1. **Gate the startup league fetch** behind the same switches as everything else; do not contact GGG until the user has market enabled (and consent, §12). Move it off the main thread. This also fixes the `no_network` audit variant violation.
2. Update `PRIVACY.md` (lines 5–9, 78–84, 160–163), `README.md` (67, 84) and the diagnostics doc to describe the **actual** trigger, the structured payload, the User-Agent and the opt-out. No new telemetry; usage-statistics events stay free of prices (`events.v1.json` `never_collected` already says so).
3. User-Agent: replace `poe2-value-overlay/0.5` with the product name/version and (if GGG's terms require) a contact; owner/legal decision (§4 item 1).
4. Diagnostics: add market *status* only (enabled, last lookup status, rate-limit state) to the support summary; never queries, listings or prices.
5. Persisted state: `trade2_policy.json` (penalties) already exists; any new cache stays in memory (TTL) unless the owner wants otherwise.

## 11. Performance strategy

Protect Shift+C (R4 baseline: warm median 0.25–1.2 s, first check 0.9–3.5 s).
- Market work **starts only after `TERMINAL_PAINT`**, as a new post-paint step next to `_maybe_schedule_upgrade_path`/`_maybe_schedule_build_decomp`, on a worker thread (the legacy `submit_price_check` runs synchronously on the UI thread with a 30 s timeout and must **not** be reused as is).
- Stale guards copied from the upgrade-path handler: `parent_request_id`, `presentation_generation`, `baseline_generation`, `content_hash`; cancel on the next Item Check; merge into a copy of `_last_result`; re-render in place.
- Bounded I/O: ≤1 search + ≤2 fetch batches (≤20 listings) + FX only for currencies actually present; coalesce identical in-flight lookups; wait ≤ the existing 90 s queue cap, otherwise show "market busy" and stop.
- Cache semantics are explicit: search 90 s / fetch 120 s (existing), evidence cached per `(league, compiled-query fingerprint)` with `fetched_at` shown as freshness; invalidated on league change, settings change, and never reused across a changed query. No PoB evaluation is involved in price estimation, so there is **no new PoB call** in R5. (R6 candidate search is the PoB-heavy part and carries the existing 60/180/450 evaluation caps.)
- Lazy imports: the controller imports the whole market/gear/price_check stack at module import (and `market/__init__` pulls in the analysis pipeline). Make these lazy so startup does not pay for disabled features.
- The R4 reliability gate stays a release-time guard. R5 regression protection = the new engine-free tests plus the R4 `r4_gate_measure.py` timing, run before merging R5-B/C, to prove Item Check latency is unchanged with enrichment disabled and enabled-but-unavailable.

## 12. UX

Respect Status Rail and the compact-tooltip rules (one verdict, ≤5 impact rows, ≤2 notes, no score, colour never the only signal, gold only accent). Minimum surfaces:

1. **Compact tooltip:** one budgeted line under the impact rows — `Price ~30–36 Ex · Strong market (11 comparable)` or `Price: sparse market, use cautiously` or nothing when disabled/unavailable. When a listed price exists: `Listed 40 Ex · market ~30–36 Ex (above)`.
2. **More Info → new "Market" section** (after build context): headline + one-sentence *why* (the leading `TrustReason`, in words), band and basis ("cheapest comparable listings"), comparable and seller count, freshness, "not included in the search" lines, and the paired line "Build improvement +6.8% · Price ~34 Ex" only under the §8 rules.
3. **Settings:** one row, "Market prices": Off / On, with the one-sentence data statement and a link to `PRIVACY.md`; league remains where it is. Diagnostics Market row reports real state (enabled, last status), not just the setting.
4. **Remove/retire:** "VALUE / COST … Build Value / currency", "BAD VALUE" labels, the unreachable legacy price-check panel surfaces (feature-flagged off, not deleted, until R6 decides).
No dashboards, charts, history, badges or pills. Fix `panel_model` price/trust only if the legacy panel stays reachable (it should not in 1.0).

## 13. R5 vs R6 boundary

| R5 (this plan) | R6 (later, depends on R5 contracts) |
| --- | --- |
| Price estimate + confidence for the item **being checked** | "What should I buy?" |
| Comparable quality, coverage report, trust reasons | Generating candidates across the market for a slot/budget |
| Listed-vs-market context for a copied listing | Meaningful-upgrade filtering and ranked recommendations |
| Provider foundation, transport seam, rate pacing, FX, league handling, tests | Live `CandidateSource` that turns a SearchIntent into trade2 queries |
| Query/search reliability, privacy gating, performance isolation | PoB evaluation of many candidates; budget-aware optimizer (`gear/`); fixing the eval-cache key (profile + price) and the `market/` duplicates |
| `MarketEvidence`, `MarketValueContext` | Improvement/cost *ordering* across candidates, "similar impact available around X–Y" |

Reusable by R6 from R5 work: the compiled-query pipeline, `MarketEvidence` (price of a *candidate*), the transport seam + fixtures, rate policy, FX. R5 must not silently implement R6 and leaves `market/`, `market_assist/` and `gear/` parked and untouched apart from the verified import fix.

## 14. Implementation slices

### R5-A — Foundation: privacy gate, transport seam, fixtures, estimator correctness (P0)
- Gate the startup league fetch (settings + env + `no_network` + consent); off-thread; make module imports lazy.
- Inject a transport into `Trade2Client`; create `fixtures/market/` with **synthetic** sanitized responses (search/fetch/exchange/leagues, 429/401/403/5xx/garbage) and listing sets for each confidence case.
- Fix §3.4 items 3, 4 (labels + fetch bound), 5 (unique → no estimate), 7 (exception containment), the shadowed `_normalize_family_name`, MAD scaling/dedupe order; `OUTLIER`/concentration reasons.
- Tests (all engine-free): compiler golden tests per item class, `assess_price_trust` table test per state and per veto, band/outlier/FX tests, `rate_policy` with an injected clock, league resolver, request-body allowlist test, startup-gating test, "no network without consent" test.
- *Acceptance:* with market disabled the app makes zero requests to `pathofexile.com` (asserted); every provider failure path returns a typed status; HIGH CONFIDENCE is reachable in a fixture and each veto reproduces its state; ≥1 deterministic test per signal in §5; `ruff` clean; engine-free suites added to PR validation.

### R5-B — Evidence service + async Item Check enrichment (P0)
- `MarketEvidence`/`MarketValueContext` contracts, headline mapping, `MarketEvidenceService`, listed-vs-market comparison (`~b/o`).
- Post-paint worker + stale guards + cancel + in-place re-render, modelled on the upgrade-path handler; settings key `market_prices` and consent.
- *Acceptance:* Item Check output and `evaluation_finished` timing identical with market off/on/offline/throwing (R4 `r4_gate_measure.py` Part C within noise); contract serialises; stale results never overwrite a newer item; provider failure → `UNAVAILABLE`, no exception reaches Item Check (tests with a throwing fake provider); cache hit/miss/expiry/league-change tests.

### R5-C — Presentation and efficiency cleanup (P0/P1)
- Compact line, More Info "Market" section, Settings row, Diagnostics market status; remove `power_per_currency` classes and the VALUE/COST line; paired "improvement · price" under §8 rules.
- *Acceptance:* snapshot-style presentation tests for each headline, hidden-efficiency rules (SIDEGRADE/TRADEOFF/PARTIAL/Sparse/zero price), compact budget respected, no raw metrics shown, PRIVACY.md/README/diagnostics docs updated, copy review by the owner.

### R5-D — Consolidation and R6 handover (P1/P2, optional before 1.0)
- Retire or mark: duplicate rate-limit/FX/league/`CandidateSource` code, unused functions, stale docs (`PARKED_FEATURES.md`, `ops/*.json`), legacy MARKET-02 path; add the missing market test layer for `market/` (stale-revision, budget, dedupe, pareto) with synthetic fixtures; document the R6 inputs (live source from SearchIntent, eval-cache key fix).
- *Acceptance:* no behaviour change in Item Check; docs match reality; R6 entry conditions written down.

## 15. Test strategy

Deterministic fixtures and pure functions first (compiler, trust table, bands/outliers, FX, rate policy with injected clock, league resolver, normalization, provider-failure matrix, privacy allowlist, gating). Live network is **never** a CI fixture; the opt-in canary stays manual. Real PoB is needed only to prove Item Check is unchanged (one focused real-PoB slice plus the existing R4 timing script); the full corpus is not re-run per edit. The R4 reliability gate remains release-time. CI: the new market tests join the R4 engine-free step in PR validation (they need no PoB).

## 16. Risks and open questions (owner)

1. **Terms/legal:** is anonymous trade2 use by ExileLens acceptable to GGG, and under what User-Agent/volume rules (§4)? Blocks enabling live by default; does not block R5-A/B/C with fixtures.
2. **Default state and consent:** "Market prices" Off by default with an explicit opt-in (recommended: consistent with the privacy model and R2 consent card), or On by default because `live_market_mode="auto"` already exists and README advertises it.
3. **What the estimate means:** "price to buy" (cheapest comparables) vs "worth" (needs more fetching/rate budget). Recommended 1.0: label it honestly as cost to buy comparable items.
4. **Uniques:** no estimate until a name-based query exists, or build it in R5-A.
5. **Corrupted/socket differences:** disclose vs filter.
6. The estimator is untested at runtime in this repo: the §3.4 "probable defects" must be confirmed by fixtures before relying on any of the confidence behaviour.
7. Rate-limit cold-start numbers are from a past observation; verify (§4 item 3).
8. `POESESSID` cookie support: remove for 1.0?
9. Whether the legacy Price Check panel/hotkeys (Ctrl+Shift+R refine) should be removed from the default runtime; recommended: keep dormant, no entry points.

## 17. Recommended 1.0 scope

| Class | Items |
| --- | --- |
| **P0 — required for 1.0** | Gate/relocate the startup league fetch and fix PRIVACY.md/README accuracy; remove `power_per_currency` classes and the VALUE/COST line; transport seam + synthetic fixtures + estimator correctness tests; `MarketEvidence` contract; async, bounded, failure-isolated enrichment that cannot slow or break Item Check; settings row + diagnostics status; compact price+confidence line and More Info "Market" section; "no trustworthy estimate" as an explicit state. |
| **P1 — highly desirable** | Listed-vs-market context from `~b/o`; unique-item name query; corrupted/socket disclosure; concentration/OUTLIER reasons; lazy imports; owner-run live canary result recorded in the docs. |
| **P2 — post-1.0 / R6 foundation** | Live `CandidateSource` from SearchIntent; improvement/cost ordering across candidates; "similar impact available around X–Y"; eval-cache key fix; consolidating `market/` + `gear/` + `market_assist/`; price history or persistence; trade-site deep links beyond the current hint. |
| **NO — do not build** | A universal "best value" score or per-currency class; price-history charts or dashboards; an economy/ticker feed; build-weighted comparables; scraping or account/session-cookie flows; automatic purchasing/whispering; sending PoB XML, build or character data to any service; new telemetry; a second competing confidence system. |

1.0 does not need a large market feature. It needs a trustworthy one: when the evidence is weak the product says so and shows no number.

## 18. Sequence

`R5-A` (foundation, privacy, tests) → `R5-B` (evidence + async enrichment) → `R5-C` (UX + efficiency cleanup) → `R5-D` (consolidation/R6 handover, optional). Each is a separately reviewable PR; A is a prerequisite for B, B for C.

---

# R5-A implementation record (market foundation)

R5-A is the privacy-safe, deterministic foundation: privacy, transport seam, fixtures, estimator correctness, tests. It is **not** user-facing enrichment
(no async Item Check price line, no More Info section, no Settings UI beyond the minimal backing fields, no Upgrade Finder, no live activation).

## A1. Policy correction (overrides §4 and the §16 owner questions where they differ)

**Live trade2 is production-disabled.** GGG's developer documentation supports the documented API Reference / Data Exports resources and prohibits
reverse-engineering unsupported internal website APIs; `/api/trade2/*` is such an interface and nothing in this repository establishes permission. So the
situation is the same as R3: *infrastructure-ready, external-access-blocked*. No live endpoint was contacted while building R5-A; the canary was not run;
nothing was probed. Owner decisions applied: market prices default **off**; explicit opt-in with a recorded consent version; an estimate means the cost of
comparable listings (never "worth / true value / fair value"); `POESESSID` removed; the legacy Price Check panel / Ctrl+Shift+R stays dormant.

## A2. Central enablement contract (`price_check/market_policy.py`)

`resolve_market_access(enabled, consent_version, provider_authorized)` is the one decision. Precedence: `NETWORK_DISABLED` (audit/no_network) ->
`DISABLED_BY_USER` (off, or consent for a different statement) -> `PROVIDER_NOT_AUTHORIZED` (`LIVE_TRADE2_AUTHORIZED = False`, state
`BLOCKED_PENDING_PROVIDER_AUTHORIZATION`) -> `AVAILABLE`. With the constant as shipped, `network_permitted` is False for every setting combination. Environment
variables can only disable. `market_lookup_status()` maps a lookup outcome to `DISABLED_BY_USER / NETWORK_DISABLED / PROVIDER_NOT_AUTHORIZED / RATE_LIMITED /
UNAVAILABLE` without implying an estimate. Consumers: the startup league fetch (not initiated, not caught after the fact; `LeagueCatalog.refresh` re-checks), the
provider-chain mode, the startup banner, the Settings/health text, the canary (inert), and, as defence in depth, `AuthorizedTransport`, which re-checks on every
request and also lets the client skip pacing/accounting for a request that would be refused.

## A3. Transport seam (`price_check/transport.py`)

`TransportRequest` / `TransportResponse` / `TransportError` and a `Trade2Transport` callable Protocol. HTTP statuses are responses; the client maps them to
`Trade2Error` codes in one place (`_send`). Production = `AuthorizedTransport(UrllibTransport(), current_market_access)`; tests inject fakes
(`tests/market_support.py`). `conftest.py` makes any real connection from a `test_r5a_*` module fail the test.

## A4. Findings: estimator defects (reproduced with fixtures first, then fixed)

| | Defect | Result | Fix |
|---|---|---|---|
| A | Compiled path had `similarity_band = UNKNOWN` and no stability, so `current_excellent` and `plus_ok` could never both hold: HIGH CONFIDENCE was **unreachable** | **Confirmed** (every scenario, incl. a 20-seller tight set, topped out at ASSISTED/LOW) | New `SimilarityBand.SERVER_MATCHED` for a compiled STRICT query whose coverage omitted no anchor or flexible group; no similarity number is invented (`median_similarity` stays None). An omitted anchor/group leaves it UNKNOWN; an omitted anchor now also moves the state to NEEDS REFINEMENT. The OVER_SPECIFIC cap no longer applies to a server-matched query with >= 15 results. |
| B | Sample bound | **Confirmed**: target 36 / 40 ids / 4 batches per search (8 per lookup), but an early stop at 3 FX-usable listings made the real sample the cheapest ~10 | Hard bound 20 ids / 2 batches (client and provider); the second batch is read only if the server total exceeds what the first returned (`_make_stop_when`). |
| C | Cheapest-first | Kept (sort price asc) | Documented as "cost to buy comparable listings"; disclaimer rewritten. |
| D | Uniques priced by base type (rarity=unique + base) | **Confirmed** | Typed refusal `LIVE_ITEM_CLASS_UNSUPPORTED` before any request; trust veto `UNIQUE_NOT_PRICED`; no price display. Live unique retrieval not implemented. |
| E | Exceptions escaping | **Confirmed**: `lookup` raised `InvalidTradeQuery`; fetch errors re-raised; the service had no guard | `LiveTradeComparableProvider.lookup` never raises (typed `LIVE_PROVIDER_ERROR` / mapped state); `PriceCheckService.check` also contains a raising provider. Exception text is never surfaced. |
| – | Outlier order and MAD | **Confirmed**: outliers ran before seller dedupe (one account's cheap listings skewed the quartiles); MAD was unscaled (`3.5*MAD`, ~2.4 sigma) with an absolute `1.0` zero fallback that depends on the display currency | Order is normalize -> one listing per seller (cheapest) -> IQR -> scaled MAD (`3.5*1.4826*MAD`, zero fallback = half the median). |
| – | Re-assessing a result changed it (its own `estimate_state` fed back, adding `QUERY_IDENTITY_WEAKENED`) | **Confirmed** | Compiled path no longer feeds the previous state back. |
| – | A refused request still consumed rate-limit budget | Found while testing | `_gate` consults the transport first. |

Known limitation (documented by a test, not changed): two lone extreme asks form a "second mode" of size 2 and read as MULTIMODAL (conservative).

Seller concentration: the sample's listing count, distinct sellers and top-seller share are measured **before** dedupe and carried in the pass diagnostics; a
sample where one seller holds >= 50% of >= 4 listings gets `SELLER_CONCENTRATED` and cannot be HIGH.

## A5. Headline mapping (pure, not wired to UI)

`market_headline(assessment)` -> `STRONG_COMPARABLE_SET | WEAK_COMPARABLE_SET | SPARSE_MARKET | VOLATILE_ESTIMATE | NO_TRUSTWORTHY_ESTIMATE`. Hard no-price vetoes
(unique, base-only, unusable sample, omitted anchor, unsupported identity, weak similarity, stale) -> NO_TRUSTWORTHY; multimodal / extreme spread / sensitive ->
VOLATILE; HIGH -> STRONG; thin sample or thin liquidity -> SPARSE; otherwise WEAK. `PriceTrustAssessment`, `EstimateState` and `TrustReason` are unchanged in
shape (additive members only); there is no numeric score.

## A6. User-Agent

`USER_AGENT = "ExileLens-market/1 (internal; live provider disabled)"` is an ExileLens-specific internal string. No OAuth client id, no contact address and no
GGG-prescribed format is claimed. The format GGG requires for a live provider is **BLOCKED_PENDING_PROVIDER_AUTHORIZATION**; nothing here asserts compliance.

## A7. `power_per_currency`: call sites and removal impact (documented only; R5-C removes it)

Definition/classification: `items/price.py` (`classify_power_per_currency`, `compute_power_per_currency`). Producers: `items/ranking.py:299,310`,
`items/value_layer.py:50`, `items/intelligence.py:51,70`, `items/evaluation.py:815`, `items/build_intel/engine.py:322` (always `None`). Presentation:
`items/presentation.py:205,800`, `ui/overlay_presentation.py:882`, `app/controller.py:4715`. Parked features that depend on it: `market/{categories,engine,models}.py`,
`market_assist/{evaluator,finalization,session_store}.py`, `ui/market_assistant_overlay.py:139`, `gear/registry.py:60`. Impact of removal: the Item Check value
layer and the VALUE / COST line lose their only input (it is `None` unless a manual price is entered), the three parked packages must drop the field in the same change,
and the result-contract field disappears from `ItemEvaluation` consumers. No R5-A foundation test depends on it, so it is untouched here.

## A8. Remaining prerequisites for R5-B

1. Owner/GGG outcome on provider authorization (or a documented-API/Data-Exports provider); flipping `LIVE_TRADE2_AUTHORIZED` is a single reviewed change, and the
   User-Agent/identification format must be settled first.
2. A consent UI that records `market_consent_version` (only backing fields exist now).
3. The MarketEvidence contract and async Item Check enrichment (R5-B), built on `market_headline` and `MarketLookupStatus`.
4. R5-C: remove `power_per_currency`, and rename the internal band label `fair` (it is still `quick_sale / fair / optimistic`), so no surface can read as "fair value".

---

# R5-B implementation record (MarketEvidence + asynchronous enrichment)

Contract reference: [MARKET_EVIDENCE_CONTRACT.md](MARKET_EVIDENCE_CONTRACT.md). Production is unchanged in substance: the live provider is policy-blocked, so an
enabled lookup resolves to `UNAVAILABLE / PROVIDER_NOT_AUTHORIZED` with no request and no trade2 stack loaded. R5-B does not expose the final R5-C UX.

**Delivered:** `price_check/market_evidence.py` (contract v1, the one conversion, listed-price comparison, freshness aging), `price_check/market_evidence_service.py`
(access gate, compile, evidence cache, one provider lookup with timeout, containment), controller post-paint scheduling with identity guards, operational diagnostics,
tests `test_r5b_market_evidence.py` / `test_r5b_market_lifecycle.py`, CI step.

**Deviations from §7/§14, and why:**
1. `headline`, `estimate_state` and `reasons` are null/empty unless a lookup produced evidence (statuses DISABLED/UNAVAILABLE/RATE_LIMITED/PENDING carry none): a headline on
   a state where nothing was looked up would be a claim without evidence.
2. `price` is also null for `VOLATILE_ESTIMATE`, not only `NO_TRUSTWORTHY_ESTIMATE`: a band over two price clusters is not a market range. The observed range stays internal.
3. `price.low/high` are the 25th/75th percentile of comparable asks (the internal `quick_sale`/`optimistic` bands), not the narrow 40th-60th `fair` band, so the listed-price
   comparison is meaningful. `fair` is not exposed.
4. Market work runs on its own daemon thread, not the scheduler/worker used by upgrade-path and build-decomp: that queue is the single PoB engine queue, and market I/O must never
   wait behind (or in front of) PoB jobs. The stale guards are the same ones (parent request id, presentation and baseline generation, content hash) plus a job id and the market
   settings (enabled, consent version, league).
5. `MarketValueContext` is not a separate type: the paired impact lives in the existing result and the market half in `result["market_evidence"]`; `efficiency` is not computed
   (R5-B has no efficiency; `power_per_currency` removal stays with R5-C).
6. `market_evidence_updated` is emitted for in-place re-rendering but `main.py` does not connect it: no surface renders market evidence yet (R5-C), and a re-render with
   unchanged presentation would only cost a repaint.

**R5-C prerequisites:** a consent/Settings surface that records `market_consent_version`; the compact line / More Info section reading `result["market_evidence"]`; removal of
`power_per_currency` and the `fair` label; copy review.
