from __future__ import annotations

import json
import statistics
from dataclasses import dataclass
from typing import Any, Iterable

from exilelens.items.metadata import parse_lightweight_metadata
from exilelens.items.raw_input import RawItemInput
from exilelens.price_check.comparable_features import FAMILY_MATCH_THRESHOLD, ModImportance
from exilelens.price_check.comparable_pricing import OutlierFilter, PriceNormalizer, build_band_estimate
from exilelens.price_check.comparable_query import (
    ComparableSearchQuery,
    RelaxationTier,
    build_search_query,
    listing_similarity_score,
    required_important_matches,
)
from exilelens.price_check.currency_fx import CurrencyFxTable
from exilelens.price_check.models import ComparableListing, PriceCheckResult
from exilelens.price_check.trade2_query import build_trade2_search_body

MOD_FAMILY_MATCH_THRESHOLD = FAMILY_MATCH_THRESHOLD
MINIMUM_PRICED_COUNT = 1


def _minimum_comparable_count() -> int:
    from exilelens.price_check.providers.live_trade2 import _MIN_BAND_COMPARABLES

    return _MIN_BAND_COMPARABLES


@dataclass(frozen=True)
class RuntimeComparableThresholds:
    close_similarity_threshold: float
    loose_similarity_threshold: float
    minimum_comparable_count: int
    minimum_priced_count: int
    mod_family_match_threshold: float = MOD_FAMILY_MATCH_THRESHOLD


def read_runtime_thresholds(query: ComparableSearchQuery) -> RuntimeComparableThresholds:
    key_features = query.identity_features()
    if not key_features:
        close = 1.0
        loose = 1.0
    else:
        close_required = required_important_matches(query.relaxation_tier, len(key_features))
        loose_required = max(1, int(len(key_features) * 0.5))
        close = (close_required * MOD_FAMILY_MATCH_THRESHOLD) / len(key_features)
        loose = (loose_required * MOD_FAMILY_MATCH_THRESHOLD) / len(key_features)
    return RuntimeComparableThresholds(
        close_similarity_threshold=round(close, 4),
        loose_similarity_threshold=round(loose, 4),
        minimum_comparable_count=_minimum_comparable_count(),
        minimum_priced_count=MINIMUM_PRICED_COUNT,
        mod_family_match_threshold=MOD_FAMILY_MATCH_THRESHOLD,
    )


def listing_mod_families(item_raw: str, query: ComparableSearchQuery) -> tuple[list[str], list[str]]:
    from exilelens.price_check.comparable_features import best_feature_score, build_features

    key_features = query.identity_features()
    listing_features = build_features(item_raw, category=query.base_type)
    matched: list[str] = []
    missing: list[str] = []
    for feature in key_features:
        label = feature.family.replace("_", " ")
        if best_feature_score(feature, listing_features) >= MOD_FAMILY_MATCH_THRESHOLD:
            matched.append(label)
        else:
            missing.append(label)
    return matched, missing


def _listing_base_type(item_raw: str) -> str:
    meta = parse_lightweight_metadata(RawItemInput.from_text(item_raw))
    return str(meta.base_type or "")


def _percentiles(values: list[float]) -> dict[str, float | None]:
    if not values:
        return {"min": None, "p25": None, "median": None, "p75": None, "max": None}
    ordered = sorted(values)
    if len(ordered) == 1:
        value = ordered[0]
        return {"min": value, "p25": value, "median": value, "p75": value, "max": value}
    return {
        "min": ordered[0],
        "p25": statistics.quantiles(ordered, n=4)[0],
        "median": statistics.median(ordered),
        "p75": statistics.quantiles(ordered, n=4)[2],
        "max": ordered[-1],
    }


def _candidate_row(
    listing: ComparableListing,
    *,
    query: ComparableSearchQuery,
    fx_table: CurrencyFxTable | None,
) -> dict[str, Any]:
    similarity = listing_similarity_score(listing.item_raw, query)
    matched, missing = listing_mod_families(listing.item_raw, query)
    normalizer = PriceNormalizer(fx_table=fx_table)
    normalized = normalizer.normalize([listing])
    normalized_price = normalized[0].amount if normalized else None
    normalized_currency = normalized[0].currency if normalized else None
    return {
        "listing_id": listing.listing_id,
        "similarity": round(similarity, 4),
        "raw_price": listing.price_amount,
        "raw_currency": listing.price_currency,
        "normalized_price": round(normalized_price, 4) if normalized_price is not None else None,
        "normalized_currency": normalized_currency,
        "base": _listing_base_type(listing.item_raw),
        "matched_important_mod_families": matched,
        "missing_important_mod_families": missing,
    }


def _filtering_counts(
    similar: list[ComparableListing],
    *,
    fx_table: CurrencyFxTable | None,
) -> dict[str, int]:
    normalizer = PriceNormalizer(fx_table=fx_table)
    normalized = normalizer.normalize(similar)
    if not normalized:
        return {
            "duplicate_seller_removed": 0,
            "stale_removed": 0,
            "outliers_removed": 0,
        }
    outlier_filter = OutlierFilter()
    filtered = outlier_filter.filter(normalized)
    duplicate_seller_removed = max(0, len(normalized) - len(OutlierFilter._dedupe_sellers(normalized)))
    outliers_removed = max(0, len(normalized) - len(filtered))
    return {
        "duplicate_seller_removed": duplicate_seller_removed,
        "stale_removed": 0,
        "outliers_removed": outliers_removed,
    }


def build_pass_funnel_snapshot(
    *,
    query: ComparableSearchQuery,
    http_status: int | None,
    search_result_count: int,
    query_result_ids_count: int,
    fetch_requests: int,
    fetched_listing_count: int,
    listings: list[ComparableListing],
    similar: list[ComparableListing] | None = None,
    kept: list[ComparableListing] | None = None,
    fx_table: CurrencyFxTable | None = None,
    has_currency_estimate: bool = False,
    failure_reason: str = "",
) -> dict[str, Any]:
    thresholds = read_runtime_thresholds(query)
    priced_supported = 0
    priced_unsupported = 0
    if fx_table is not None:
        for row in listings:
            if fx_table.is_known_currency(str(row.price_currency or "")):
                priced_supported += 1
            else:
                priced_unsupported += 1
    else:
        priced_supported = len(listings)

    scored_rows = [_candidate_row(row, query=query, fx_table=fx_table) for row in listings]
    similarity_values = [row["similarity"] for row in scored_rows]
    close_count = sum(1 for value in similarity_values if value >= thresholds.close_similarity_threshold)
    loose_count = sum(1 for value in similarity_values if value >= thresholds.loose_similarity_threshold)
    below_loose_count = sum(1 for value in similarity_values if value < thresholds.loose_similarity_threshold)

    similar_listings = similar if similar is not None else [
        row for row in listings if listing_similarity_score(row.item_raw, query) >= thresholds.close_similarity_threshold
    ]
    kept_listings = kept or []
    filtering = _filtering_counts(similar_listings, fx_table=fx_table)

    normalizer = PriceNormalizer(fx_table=fx_table)
    normalized_prices = [row.amount for row in normalizer.normalize(similar_listings)]

    ranked = sorted(scored_rows, key=lambda row: row["similarity"], reverse=True)
    top_10 = ranked[:10]
    near_misses = sorted(
        [row for row in ranked if row["similarity"] < thresholds.loose_similarity_threshold],
        key=lambda row: row["similarity"],
        reverse=True,
    )[:5]

    return {
        "thresholds": thresholds.__dict__,
        "remote_search": {
            "http_status": http_status,
            "search_result_count": search_result_count,
            "query_result_ids_count": query_result_ids_count,
        },
        "fetch": {
            "fetch_requests": fetch_requests,
            "fetched_listing_count": fetched_listing_count,
            "listings_with_price": len(listings),
        },
        "fx": {
            "priced_supported_currency": priced_supported,
            "priced_unsupported_currency": priced_unsupported,
            "fx_usable_count": len(normalizer.normalize(listings)),
        },
        "similarity": {
            "similarity_scored_count": len(scored_rows),
            "count_at_or_above_close_threshold": close_count,
            "count_at_or_above_loose_threshold": loose_count,
            "count_below_loose_threshold": below_loose_count,
            "distribution": _percentiles(similarity_values),
        },
        "filtering": filtering,
        "final": {
            "accepted_comparable_count": len(kept_listings) if kept_listings else len(similar_listings),
            "minimum_required_for_band": thresholds.minimum_comparable_count,
            "has_currency_estimate": has_currency_estimate,
            "failure_reason": failure_reason,
        },
        "normalized_price_distribution": _percentiles(normalized_prices),
        "top_10_candidates": top_10,
        "top_5_near_misses": near_misses,
    }


def build_query_basis_report(item_raw: str, *, league: str | None) -> dict[str, Any]:
    query = build_search_query(item_raw, league=league)
    meta = parse_lightweight_metadata(RawItemInput.from_text(item_raw))
    critical = [feature.source_text for feature in query.features if feature.importance == ModImportance.CRITICAL]
    high_value = [feature.source_text for feature in query.features if feature.importance == ModImportance.HIGH]
    medium = [feature.source_text for feature in query.features if feature.importance == ModImportance.MEDIUM]
    ignored = [feature.source_text for feature in query.features if feature.importance == ModImportance.LOW]
    pseudo = sorted({feature.pseudo_family for feature in query.features if feature.pseudo_family})
    return {
        "category": meta.category,
        "base_requirement": query.base_type,
        "critical_mods": critical,
        "high_value_mods": high_value,
        "medium_mods": medium,
        "ignored_mods": ignored,
        "pseudo_mods": pseudo,
        "feature_families": [feature.family for feature in query.features],
        "remote_query_payload": build_trade2_search_body(query),
    }


def classify_blocker(pass_snapshots: Iterable[dict[str, Any]]) -> str:
    snapshots = list(pass_snapshots)
    if not snapshots:
        return "REMOTE_QUERY_TOO_NARROW"

    last = snapshots[-1]
    remote = last.get("remote_search", {})
    fetch = last.get("fetch", {})
    fx = last.get("fx", {})
    similarity = last.get("similarity", {})
    filtering = last.get("filtering", {})
    final = last.get("final", {})

    search_total = int(remote.get("search_result_count") or 0)
    priced = int(fetch.get("listings_with_price") or 0)
    fx_usable = int(fx.get("fx_usable_count") or 0)
    close_count = int(similarity.get("count_at_or_above_close_threshold") or 0)
    loose_count = int(similarity.get("count_at_or_above_loose_threshold") or 0)
    below_loose = int(similarity.get("count_below_loose_threshold") or 0)
    distribution = similarity.get("distribution") or {}
    median_similarity = distribution.get("median")
    accepted = int(final.get("accepted_comparable_count") or 0)
    minimum_required = int(final.get("minimum_required_for_band") or _minimum_comparable_count())
    outliers_removed = int(filtering.get("outliers_removed") or 0)
    duplicate_removed = int(filtering.get("duplicate_seller_removed") or 0)

    if search_total <= 5:
        return "REMOTE_QUERY_TOO_NARROW"
    if priced < MINIMUM_PRICED_COUNT:
        return "FETCH/PRICE_TOO_WEAK"
    if priced >= 3 and fx_usable < max(1, priced // 2):
        return "FX_NORMALIZATION_BLOCKER"
    if isinstance(median_similarity, (int, float)) and median_similarity < 0.25:
        return "SIMILARITY_MODEL_MISMATCH"
    if loose_count >= minimum_required and close_count < minimum_required:
        return "SIMILARITY_THRESHOLD_BLOCKER"
    if close_count >= minimum_required and accepted < minimum_required and (outliers_removed + duplicate_removed) > 0:
        return "OUTLIER/FILTER_BLOCKER"
    if close_count >= minimum_required and accepted < minimum_required:
        return "MINIMUM_SAMPLE_TOO_STRICT"
    if below_loose >= max(3, priced // 2) and loose_count < minimum_required:
        return "SIMILARITY_THRESHOLD_BLOCKER"
    if final.get("has_currency_estimate"):
        return "MINIMUM_SAMPLE_TOO_STRICT"
    return "SIMILARITY_THRESHOLD_BLOCKER"


def format_funnel_report(
    result: PriceCheckResult,
    *,
    item_raw: str,
    configured_max_fetch_requests: int | None,
    actual_fetch_requests: int | None,
    fetch_budget_note: str,
) -> str:
    lines: list[str] = []
    diagnostics = result.diagnostics
    passes = list(diagnostics.relaxation_passes) if diagnostics and diagnostics.relaxation_passes else []
    query_basis = build_query_basis_report(item_raw, league=result.request.league.league)

    lines.append("=== MARKET-01B6D COMPARABLE FUNNEL ===")
    lines.append("")
    lines.append("THRESHOLDS (runtime)")
    thresholds = read_runtime_thresholds(build_search_query(item_raw, league=result.request.league.league))
    for key, value in thresholds.__dict__.items():
        lines.append(f"  {key}={value}")
    lines.append("")

    lines.append("QUERY BASIS")
    for key in (
        "category",
        "base_requirement",
        "critical_mods",
        "high_value_mods",
        "medium_mods",
        "ignored_mods",
        "pseudo_mods",
        "feature_families",
    ):
        lines.append(f"  {key}: {query_basis[key]}")
    lines.append("  remote_query_payload:")
    lines.append(json.dumps(query_basis["remote_query_payload"], indent=2, sort_keys=True))
    lines.append("")

    for pass_row in passes:
        pass_index = pass_row.get("pass_index", "?")
        lines.append(f"--- PASS INDEX {pass_index} ---")
        funnel = pass_row.get("funnel") or {}
        if not funnel:
            lines.append("  (no funnel snapshot)")
            lines.append("")
            continue

        remote = funnel.get("remote_search", {})
        fetch = funnel.get("fetch", {})
        fx = funnel.get("fx", {})
        similarity = funnel.get("similarity", {})
        filtering = funnel.get("filtering", {})
        final = funnel.get("final", {})

        lines.append("REMOTE SEARCH")
        lines.append(f"  http_status={remote.get('http_status')}")
        lines.append(f"  search_result_count={remote.get('search_result_count')}")
        lines.append(f"  query_result_ids_count={remote.get('query_result_ids_count')}")

        lines.append("FETCH")
        lines.append(f"  fetch_requests={fetch.get('fetch_requests')}")
        lines.append(f"  fetched_listing_count={fetch.get('fetched_listing_count')}")
        lines.append(f"  listings_with_price={fetch.get('listings_with_price')}")

        lines.append("FX")
        lines.append(f"  priced_supported_currency={fx.get('priced_supported_currency')}")
        lines.append(f"  priced_unsupported_currency={fx.get('priced_unsupported_currency')}")
        lines.append(f"  fx_usable_count={fx.get('fx_usable_count')}")

        lines.append("SIMILARITY")
        lines.append(f"  similarity_scored_count={similarity.get('similarity_scored_count')}")
        lines.append(f"  count_at_or_above_close_threshold={similarity.get('count_at_or_above_close_threshold')}")
        lines.append(f"  count_at_or_above_loose_threshold={similarity.get('count_at_or_above_loose_threshold')}")
        lines.append(f"  count_below_loose_threshold={similarity.get('count_below_loose_threshold')}")
        dist = similarity.get("distribution") or {}
        lines.append(
            "  similarity_distribution="
            + json.dumps(dist, sort_keys=True)
        )

        lines.append("FILTERING")
        lines.append(f"  duplicate_seller_removed={filtering.get('duplicate_seller_removed')}")
        lines.append(f"  stale_removed={filtering.get('stale_removed')}")
        lines.append(f"  outliers_removed={filtering.get('outliers_removed')}")

        lines.append("FINAL")
        lines.append(f"  accepted_comparable_count={final.get('accepted_comparable_count')}")
        lines.append(f"  minimum_required_for_band={final.get('minimum_required_for_band')}")
        lines.append(f"  has_currency_estimate={final.get('has_currency_estimate')}")
        lines.append(f"  failure_reason={final.get('failure_reason') or ''}")

        price_dist = funnel.get("normalized_price_distribution") or {}
        if any(value is not None for value in price_dist.values()):
            lines.append(
                "  normalized_price_distribution="
                + json.dumps(price_dist, sort_keys=True)
            )

        lines.append("TOP 10 CANDIDATES")
        for row in funnel.get("top_10_candidates") or []:
            lines.append(
                "  "
                + json.dumps(row, sort_keys=True)
            )

        lines.append("TOP 5 NEAR-MISSES")
        for row in funnel.get("top_5_near_misses") or []:
            lines.append(
                "  "
                + json.dumps(row, sort_keys=True)
            )
        lines.append("")

    lines.append("FETCH BUDGET OBSERVATION")
    lines.append(f"  configured_max_fetch_requests={configured_max_fetch_requests}")
    lines.append(f"  actual_fetch_requests={actual_fetch_requests}")
    lines.append(f"  note={fetch_budget_note}")
    lines.append("")

    classification = classify_blocker((row.get("funnel") or {}) for row in passes)
    lines.append(f"CLASSIFIED_BLOCKER={classification}")
    return "\n".join(lines)


FETCH_BUDGET_NOTE = (
    "fetch_progressive honors max_fetch_requests on both LiveTradeComparableProvider and Trade2Client; "
    "market-only configures max_fetch_requests=1 so a single price check issues at most one fetch batch."
)
