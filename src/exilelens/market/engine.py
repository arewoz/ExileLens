from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Callable

from exilelens.analysis.pipeline import analyze_slot
from exilelens.items.primary_metric import resolve_primary_metric
from exilelens.app.build_revision import BuildFileRevision, read_build_revision
from exilelens.errors import EvaluationInvalidBuildState
from exilelens.items.price import ManualPrice, compute_power_per_currency
from exilelens.items.ranking import enrich_slot_comparison
from exilelens.items.raw_input import ItemInputSource, RawItemInput
from exilelens.items.value_profiles import ValueProfile
from exilelens.items.value_layer import parse_profile
from exilelens.market.categories import assign_categories
from exilelens.market.currency import CurrencyRateTable
from exilelens.market.eval_cache import MarketEvalCache
from exilelens.market.models import (
    CandidateEvaluation,
    CandidateListing,
    MarketCandidatePool,
    MarketCandidateResult,
    MarketSearchProgress,
    MarketSearchRequest,
    MarketSearchResult,
    SearchDepth,
)
from exilelens.market.pareto import compute_pareto_frontier
from exilelens.market.prefilter import prefilter_candidates
from exilelens.market.query_plan import build_query_plan
from exilelens.market.sources import FixtureCandidateSource, ImportedCandidateSource

YieldFn = Callable[[], bool]
ProgressFn = Callable[[dict[str, Any]], None]

REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_CORPORA = {
    "RING_1": REPO_ROOT / "fixtures" / "market" / "ring_corpus.json",
    "RING_2": REPO_ROOT / "fixtures" / "market" / "ring_corpus.json",
    "HELMET": REPO_ROOT / "fixtures" / "market" / "helmet_corpus.json",
    "BOOTS": REPO_ROOT / "fixtures" / "market" / "boots_corpus.json",
}


def _resolve_source(request: MarketSearchRequest) -> FixtureCandidateSource | ImportedCandidateSource:
    if request.source == "import" and request.import_path:
        return ImportedCandidateSource(request.import_path)
    corpus = request.fixture_corpus
    if not corpus:
        corpus = str(DEFAULT_CORPORA.get(request.slot, ""))
    return FixtureCandidateSource(corpus_path=corpus if corpus else None)


def _price_for_listing(
    listing: CandidateListing,
    budget_currency: str | None,
    rates: CurrencyRateTable | None,
) -> ManualPrice | None:
    if listing.price is None:
        return None
    if budget_currency and listing.price.currency != budget_currency:
        if rates is None or not rates.comparable(listing.price.currency, budget_currency):
            return None
        if rates:
            converted = rates.convert(listing.price.amount, listing.price.currency, budget_currency)
            if converted is None:
                return None
            return ManualPrice(amount=converted, currency=budget_currency, source="MANUAL_FX")
    return ManualPrice(amount=listing.price.amount, currency=listing.price.currency, source="LISTING")


def _evaluate_listing(
    engine: Any,
    listing: CandidateListing,
    *,
    build_path: str,
    context: str,
    profile: ValueProfile,
    primary_field: str,
    primary_confidence: str,
    pob_slot: str,
    fingerprint: str,
    cache: MarketEvalCache,
    budget_currency: str | None,
    rates: CurrencyRateTable | None,
) -> CandidateEvaluation:
    raw = RawItemInput.from_text(listing.item_raw, source=ItemInputSource.TEST)
    cached = cache.get(fingerprint=fingerprint, slot=pob_slot, content_hash=raw.content_hash)
    if cached:
        cached_listing = cached.get("listing")
        if isinstance(cached_listing, CandidateListing):
            listing_obj = cached_listing
        elif isinstance(cached_listing, dict):
            listing_obj = CandidateListing.from_dict(cached_listing)
        else:
            listing_obj = listing
        return CandidateEvaluation(
            listing=listing_obj,
            comparison=cached.get("comparison") or {},
            build_value_delta=float(cached.get("build_value_delta") or 0.0),
            offense_delta=float(cached.get("offense_delta") or 0.0),
            defense_delta=float(cached.get("defense_delta") or 0.0),
            verdict=str(cached.get("verdict") or "UNRESOLVED"),
            power_per_currency=cached.get("power_per_currency"),
            restore_pass=bool(cached.get("restore_pass", True)),
            cache_hit=True,
            status=str(cached.get("status") or "ok"),
            error=cached.get("error"),
        )

    try:
        result = engine.evaluate_candidate(pob_slot, listing.item_raw, context=context)
        comparison = {
            "product_slot": listing.slot,
            "pob_slot": pob_slot,
            "baseline": result["baseline"],
            "candidate": result["candidate"],
            "restored": result["restored"],
            "restore": result["restore"],
            "delta": result["delta"],
            "primary_metric_field": primary_field,
        }
        price = _price_for_listing(listing, budget_currency, rates)
        enriched = enrich_slot_comparison(
            comparison,
            profile=profile,
            primary_field=primary_field,
            primary_confidence=primary_confidence,
            price=price,
        )
        metric_profile = enriched.get("metric_profile") or {}
        offense = float((metric_profile.get("primary_offense") or {}).get("absolute_delta") or 0.0)
        defense = float((metric_profile.get("ehp") or {}).get("absolute_delta") or 0.0)
        value = float((enriched.get("value") or {}).get("score_delta") or 0.0)
        evaluation = CandidateEvaluation(
            listing=listing,
            comparison=enriched,
            build_value_delta=value,
            offense_delta=offense,
            defense_delta=defense,
            verdict=str(enriched.get("verdict") or "UNRESOLVED"),
            power_per_currency=enriched.get("power_per_currency"),
            restore_pass=bool((result.get("restore") or {}).get("pass", True)),
            cache_hit=False,
            status="ok",
        )
    except Exception as exc:
        evaluation = CandidateEvaluation(
            listing=listing,
            comparison={},
            build_value_delta=0.0,
            offense_delta=0.0,
            defense_delta=0.0,
            verdict="UNRESOLVED",
            restore_pass=False,
            status="error",
            error=str(exc),
        )

    cache.put(
        fingerprint=fingerprint,
        slot=pob_slot,
        content_hash=raw.content_hash,
        payload={
            "listing": listing.to_dict(),
            "comparison": evaluation.comparison,
            "build_value_delta": evaluation.build_value_delta,
            "offense_delta": evaluation.offense_delta,
            "defense_delta": evaluation.defense_delta,
            "verdict": evaluation.verdict,
            "power_per_currency": evaluation.power_per_currency,
            "restore_pass": evaluation.restore_pass,
            "status": evaluation.status,
            "error": evaluation.error,
        },
    )
    return evaluation


def run_market_search(
    engine: Any,
    request: MarketSearchRequest,
    *,
    build_path: str,
    context: str = "MAP",
    loadout: str = "",
    item_set: str = "",
    generation: int = 0,
    pob_path: str = "",
    cache: MarketEvalCache | None = None,
    currency_rates: CurrencyRateTable | None = None,
    should_yield: YieldFn | None = None,
    on_progress: ProgressFn | None = None,
) -> MarketSearchResult:
    started = time.perf_counter()
    cache = cache or MarketEvalCache()
    should_yield = should_yield or (lambda: False)

    def progress(phase: str, message: str, **extra: Any) -> None:
        payload = MarketSearchProgress(phase=phase, message=message, **extra).to_dict()
        if on_progress:
            on_progress(payload)

    revision = read_build_revision(build_path)
    if request.build_revision:
        prior = BuildFileRevision(
            path=str(request.build_revision.get("path") or build_path),
            mtime_ns=int(request.build_revision.get("mtime_ns") or 0),
            size=int(request.build_revision.get("size") or 0),
        )
        if revision and revision.changed_from(prior):
            progress("stale", "Build file changed since search was requested")
            return MarketSearchResult(
                request=request,
                query_plan=MarketQueryPlan(slot=request.slot),
                source_capabilities=_resolve_source(request).capabilities,
                pool=MarketCandidatePool(slot=request.slot, pob_slot="", profile=request.profile),
                progress=MarketSearchProgress(phase="stale", message="Build file changed — refresh baseline"),
                provider_status="STALE_BUILD_REVISION",
                stale=True,
            )

    progress("intent", "Resolving Search Intent")
    intent = request.search_intent
    audit: dict[str, Any] = {}
    if not intent:
        slot_result = analyze_slot(
            engine,
            build_path=build_path,
            context=context,
            profile=request.profile,
            generation=generation,
            loadout=loadout,
            item_set=item_set,
            pob_path=pob_path,
            slot=request.slot,
        )
        audit = slot_result.get("audit") or {}
        slot_row = slot_result.get("slot") or {}
        intent = slot_row.get("search_intent") or {}
    if intent.get("error"):
        raise ValueError(intent.get("error"))

    plan = build_query_plan(intent, request)
    source = _resolve_source(request)
    capabilities = source.capabilities

    progress("source", f"Loading candidates from {source.name}")
    listings = source.search(intent, plan.to_dict())
    sourced = len(listings)

    seen_hashes: set[str] = set()
    deduped: list[CandidateListing] = []
    for listing in listings:
        if listing.identity.content_hash in seen_hashes:
            continue
        seen_hashes.add(listing.identity.content_hash)
        deduped.append(listing)

    progress("prefilter", "Prefiltering candidates", sourced=sourced)
    filtered = prefilter_candidates(deduped, plan)

    if request.budget_amount is not None and request.budget_currency:
        within_budget = []
        for listing in filtered:
            if listing.price is None:
                within_budget.append(listing)
                continue
            price = listing.price
            if price.currency == request.budget_currency and price.amount <= float(request.budget_amount):
                within_budget.append(listing)
            elif currency_rates and currency_rates.comparable(price.currency, request.budget_currency):
                converted = currency_rates.convert(price.amount, price.currency, request.budget_currency)
                if converted is not None and converted <= float(request.budget_amount):
                    within_budget.append(listing)
        filtered = within_budget or filtered

    progress("evaluate", "Evaluating candidates with PoB", prefiltered=len(filtered), total=plan.max_evaluations)

    if hasattr(engine, "ensure_build_ready"):
        loaded = engine.ensure_build_ready(build_path, context=context)
    else:
        loaded = engine.load_build(build_path, context=context)
    from exilelens.baseline import apply_engine_identity

    apply_engine_identity(engine, loadout=loadout, item_set=item_set)
    metrics = engine.get_metrics(context)
    fingerprint = str(metrics.get("fingerprint_hash") or loaded.get("fingerprint_hash") or "")
    build_info = loaded.get("build") or {}
    primary = resolve_primary_metric(build_info, metrics)
    primary_field = audit.get("primary_field") or primary.pob_field
    primary_confidence = audit.get("primary_confidence") or primary.confidence.value
    profile = parse_profile(request.profile)

    evaluations: list[CandidateEvaluation] = []
    pob_recalcs = 0
    for idx, listing in enumerate(filtered[: plan.max_evaluations]):
        if should_yield():
            progress("yielded", "Yielded to gameplay evaluation")
            break
        evaluation = _evaluate_listing(
            engine,
            listing,
            build_path=build_path,
            context=context,
            profile=profile,
            primary_field=primary_field,
            primary_confidence=primary_confidence,
            pob_slot=plan.pob_slot,
            fingerprint=fingerprint,
            cache=cache,
            budget_currency=request.budget_currency,
            rates=currency_rates,
        )
        if not evaluation.cache_hit:
            pob_recalcs += 1
        evaluations.append(evaluation)
        progress(
            "evaluate",
            f"Evaluated {idx + 1}/{min(len(filtered), plan.max_evaluations)}",
            evaluated=idx + 1,
            total=min(len(filtered), plan.max_evaluations),
            prefiltered=len(filtered),
            sourced=sourced,
        )

    final_metrics = engine.get_metrics(context)
    if fingerprint and final_metrics.get("fingerprint_hash") != fingerprint:
        raise EvaluationInvalidBuildState(
            "build fingerprint changed after market evaluation sequence",
            {"baseline": fingerprint, "final": final_metrics.get("fingerprint_hash")},
        )

    results = [MarketCandidateResult(evaluation=row) for row in evaluations]
    frontier = compute_pareto_frontier(evaluations)
    frontier_set = set(frontier.candidate_ids)
    for row in results:
        row.on_frontier = row.evaluation.listing.identity.listing_id in frontier_set
    categories = assign_categories(results)
    results.sort(key=lambda r: r.evaluation.build_value_delta, reverse=True)

    pool = MarketCandidatePool(
        slot=plan.slot,
        pob_slot=plan.pob_slot,
        profile=plan.profile,
        candidates=results,
        pareto=frontier,
        categories=categories,
    )

    elapsed_ms = (time.perf_counter() - started) * 1000
    provider_status = "LIVE MARKET NOT AVAILABLE — fixture/import only"
    return MarketSearchResult(
        request=request,
        query_plan=plan,
        source_capabilities=capabilities,
        pool=pool,
        progress=MarketSearchProgress(
            phase="complete",
            message="Market search complete",
            evaluated=len(evaluations),
            total=min(len(filtered), plan.max_evaluations),
            prefiltered=len(filtered),
            sourced=sourced,
        ),
        provider_status=provider_status,
        performance={
            "elapsed_ms": elapsed_ms,
            "pob_recalcs": pob_recalcs,
            "cache": cache.stats(),
            "deduped": len(deduped),
        },
        network=False,
        live_market=False,
    )
