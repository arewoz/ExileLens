"""R5-A: the comparable-price estimator and trust model, proven against synthetic fixtures (no network, no PoB).

Each section names the defect it pins. Defects were reproduced against the fixtures first (see docs/R5-MARKET-INTELLIGENCE-PLAN.md,
"R5-A findings") and then fixed.
"""

from __future__ import annotations

import dataclasses

import pytest

from exilelens.price_check.comparable_pricing import NormalizedPrice, OutlierFilter, seller_stats
from exilelens.price_check.models import LiveSearchState
from exilelens.price_check.price_trust import (
    DisplayPriceMode,
    EstimateState,
    MarketHeadline,
    PriceTrustAssessment,
    PriceTrustEvidence,
    SimilarityBand,
    TrustReason,
    apply_price_trust,
    assess_price_trust,
    market_headline,
)
from tests.market_support import compiled_request, make_client, make_provider, scenario_transport

pytestmark = pytest.mark.itemcheck


def _lookup(name=None, **kwargs):
    transport = scenario_transport(name, **kwargs)
    client = make_client(transport)
    result = make_provider(client).lookup(compiled_request())
    return result, transport, client


def _trust(result) -> dict:
    return result.discovery["price_trust"]


def _headline(result) -> MarketHeadline:
    return market_headline(_assessment_from(result))


def _assessment_from(result) -> PriceTrustAssessment:
    from exilelens.price_check.price_trust import evidence_from_result

    return assess_price_trust(evidence_from_result(result))


# ------------------------------------------------------------------------------- confidence scenarios, end to end
# Defect A (similarity UNKNOWN on the compiled path made HIGH unreachable) and the headline mapping, on the whole pipeline.


@pytest.mark.parametrize(
    ("scenario", "state", "headline"),
    [
        ("strong", EstimateState.HIGH_CONFIDENCE, MarketHeadline.STRONG_COMPARABLE_SET),
        ("outliers", EstimateState.HIGH_CONFIDENCE, MarketHeadline.STRONG_COMPARABLE_SET),  # one absurd ask is trimmed, not fatal
        ("cheap_seller_skew", EstimateState.HIGH_CONFIDENCE, MarketHeadline.STRONG_COMPARABLE_SET),
        ("moderate", EstimateState.ASSISTED_ESTIMATE, MarketHeadline.SPARSE_MARKET),  # only 9 listings exist on the market
        ("sparse", EstimateState.ASSISTED_ESTIMATE, MarketHeadline.SPARSE_MARKET),
        ("volatile", EstimateState.NEEDS_REFINEMENT, MarketHeadline.VOLATILE_ESTIMATE),
        ("unusable", EstimateState.NEEDS_REFINEMENT, MarketHeadline.NO_TRUSTWORTHY_ESTIMATE),
        ("concentrated", EstimateState.NEEDS_REFINEMENT, MarketHeadline.NO_TRUSTWORTHY_ESTIMATE),
        ("stale", EstimateState.NEEDS_REFINEMENT, MarketHeadline.NO_TRUSTWORTHY_ESTIMATE),
    ],
)
def test_confidence_scenarios(scenario, state, headline):
    result, _, _ = _lookup(scenario)
    assert result.estimate_state == state.value
    assert _headline(result) is headline


def test_high_confidence_is_reachable_and_server_matched_not_invented():
    result, _, _ = _lookup("strong")
    trust = _trust(result)
    assert result.estimate_state == EstimateState.HIGH_CONFIDENCE.value
    assert result.estimate.confidence.value == "HIGH"
    assert trust["similarity_band"] == SimilarityBand.SERVER_MATCHED.value
    assert TrustReason.SIMILARITY_SERVER_MATCHED.value in trust["reason_codes"]
    # No client-side similarity number is fabricated for a server match.
    assert trust["median_similarity"] is None and trust["low_similarity_quantile"] is None
    assert trust["hard_vetoes"] == []


def test_weak_evidence_gives_no_trustworthy_estimate_and_no_price_display():
    result, _, _ = _lookup("unusable")
    assert result.estimate_state == EstimateState.NEEDS_REFINEMENT.value
    assert result.estimate.has_currency_estimate is False
    assert _trust(result)["display_price_mode"] == DisplayPriceMode.NONE.value
    assert result.estimate.confidence.value == "NONE"


def test_stale_listings_veto_the_estimate():
    result, _, _ = _lookup("stale")
    assert TrustReason.PRICE_DATA_STALE.value in _trust(result)["hard_vetoes"]
    assert result.estimate_state == EstimateState.NEEDS_REFINEMENT.value


def test_partial_fx_is_recorded_and_blocks_high_confidence():
    result, _, _ = _lookup("partial_fx")
    trust = _trust(result)
    assert TrustReason.FX_PARTIAL.value in trust["reason_codes"]
    assert trust["fx_coverage"] == pytest.approx(0.6)
    assert result.estimate_state != EstimateState.HIGH_CONFIDENCE.value
    assert result.estimate.comparables and all(row.normalized_currency == "exalted" for row in result.estimate.comparables)


def test_assessing_a_result_twice_changes_nothing():
    """Re-assessment used to feed the result's own previous state back in, adding a spurious QUERY_IDENTITY_WEAKENED veto."""
    result, _, _ = _lookup("stale")
    again = apply_price_trust(result)
    assert _trust(again)["reason_codes"] == _trust(result)["reason_codes"]
    assert again.estimate_state == result.estimate_state


# ----------------------------------------------------------------------------------- similarity evidence (defect A)


def _evidence(**overrides) -> PriceTrustEvidence:
    base = dict(
        accepted_prices=tuple(float(v) for v in range(31, 51)),
        listing_ages_seconds=(60.0,) * 20,
        remote_count=64,
        priced_count=20,
        fx_usable_count=20,
        identity_source="PRIMARY",
        selected_driver_count=4,
        available_driver_count=6,
        server_matched=True,
        seller_listing_count=20,
        distinct_sellers=20,
        top_seller_share=0.05,
    )
    base.update(overrides)
    return PriceTrustEvidence(**base)


def test_server_matched_full_coverage_is_strong_enough_for_high():
    assessment = assess_price_trust(_evidence(accepted_prices=tuple(float(v) for v in (30, 31, 32, 33, 34, 35, 36, 37, 38, 39))))
    assert assessment.similarity_band == SimilarityBand.SERVER_MATCHED.value
    assert assessment.state is EstimateState.HIGH_CONFIDENCE


def test_an_omitted_anchor_leaves_similarity_unknown_and_vetoes():
    assessment = assess_price_trust(_evidence(omitted_anchor_labels=("+89 to maximum Energy Shield",), coverage_severity="SERIOUS"))
    assert assessment.similarity_band == SimilarityBand.UNKNOWN.value
    assert TrustReason.COVERAGE_ANCHOR_OMITTED.value in assessment.hard_vetoes
    assert assessment.state is EstimateState.NEEDS_REFINEMENT
    assert market_headline(assessment) is MarketHeadline.NO_TRUSTWORTHY_ESTIMATE


def test_an_omitted_flexible_group_is_not_strong():
    assessment = assess_price_trust(_evidence(omitted_flexible_labels=("fire resistance",), coverage_severity="MINOR"))
    assert assessment.similarity_band == SimilarityBand.UNKNOWN.value
    assert assessment.state is not EstimateState.HIGH_CONFIDENCE
    assert TrustReason.COVERAGE_GROUP_OMITTED.value in assessment.reason_codes


def test_without_server_match_evidence_similarity_stays_unknown():
    assessment = assess_price_trust(_evidence(server_matched=False))
    assert assessment.similarity_band == SimilarityBand.UNKNOWN.value
    assert assessment.state is EstimateState.ASSISTED_ESTIMATE


def test_over_specific_query_only_blocks_high_when_the_result_set_is_thin():
    deep = assess_price_trust(_evidence(remote_count=64))
    thin = assess_price_trust(_evidence(remote_count=10))
    assert deep.state is EstimateState.HIGH_CONFIDENCE
    assert thin.state is not EstimateState.HIGH_CONFIDENCE  # 4 ANDed filters and only 10 results on the whole market


# --------------------------------------------------------------------------------------------- the trust table


@pytest.mark.parametrize(
    ("overrides", "state", "headline", "reason"),
    [
        ({}, EstimateState.HIGH_CONFIDENCE, MarketHeadline.STRONG_COMPARABLE_SET, None),
        (
            {"accepted_prices": (30.0, 32.0), "remote_count": 2, "priced_count": 2, "fx_usable_count": 2},
            EstimateState.NEEDS_REFINEMENT,
            MarketHeadline.NO_TRUSTWORTHY_ESTIMATE,
            TrustReason.SAMPLE_TOO_SMALL,
        ),
        (
            {"accepted_prices": (30.0, 31.0, 33.0), "remote_count": 40},
            EstimateState.ASSISTED_ESTIMATE,
            MarketHeadline.SPARSE_MARKET,
            TrustReason.SAMPLE_THIN,
        ),
        (
            {"accepted_prices": tuple([4.0] * 5 + [60.0] * 5), "priced_count": 10, "fx_usable_count": 10},
            EstimateState.NEEDS_REFINEMENT,
            MarketHeadline.VOLATILE_ESTIMATE,
            TrustReason.MARKET_MULTIMODAL,
        ),
        (
            {"listing_ages_seconds": (30 * 24 * 3600.0,) * 20},
            EstimateState.NEEDS_REFINEMENT,
            MarketHeadline.NO_TRUSTWORTHY_ESTIMATE,
            TrustReason.PRICE_DATA_STALE,
        ),
        (
            {"fx_usable_count": 8},  # 8 of 20 priced listings could be converted: a weak set, flagged, not a refused one
            EstimateState.ASSISTED_ESTIMATE,
            MarketHeadline.WEAK_COMPARABLE_SET,
            TrustReason.FX_PARTIAL,
        ),
        (
            {"is_unique": True},
            EstimateState.NEEDS_REFINEMENT,
            MarketHeadline.NO_TRUSTWORTHY_ESTIMATE,
            TrustReason.UNIQUE_NOT_PRICED,
        ),
        (
            {"top_seller_share": 0.6, "distinct_sellers": 4},
            EstimateState.ASSISTED_ESTIMATE,
            MarketHeadline.WEAK_COMPARABLE_SET,
            TrustReason.SELLER_CONCENTRATED,
        ),
    ],
)
def test_trust_table(overrides, state, headline, reason):
    assessment = assess_price_trust(_evidence(**overrides))
    assert assessment.state is state
    assert market_headline(assessment) is headline
    if reason is not None:
        assert reason.value in assessment.reason_codes


def test_headline_is_a_pure_label_with_no_numeric_score():
    assert {h.value for h in MarketHeadline} == {
        "STRONG_COMPARABLE_SET",
        "WEAK_COMPARABLE_SET",
        "SPARSE_MARKET",
        "VOLATILE_ESTIMATE",
        "NO_TRUSTWORTHY_ESTIMATE",
    }
    fields = {f.name for f in dataclasses.fields(PriceTrustAssessment)}
    assert not {name for name in fields if "score" in name}
    assessment = assess_price_trust(_evidence())
    assert market_headline(assessment) is market_headline(assessment)  # deterministic


# ------------------------------------------------------------------------------------------ sample bound (defect B)


def test_fetch_is_bounded_to_twenty_listings_in_two_batches():
    result, transport, client = _lookup("deep_unbounded")  # the synthetic server has 500 matches and 60 ids to offer
    fetched = [path.rsplit("/", 1)[1].split(",") for path in transport.paths() if "/fetch/" in path]
    assert len(fetched) == 2
    assert all(len(batch) <= 10 for batch in fetched)
    assert sum(len(batch) for batch in fetched) == 20
    assert transport.count("/search/") == 1
    assert client.fetch_requests == 2
    assert result.comparable_count <= 20


def test_a_search_that_fits_one_batch_costs_one_fetch():
    _, transport, _ = _lookup("moderate")  # total 9: nothing more to read
    assert transport.count("/fetch/") == 1


def test_the_client_enforces_the_bound_itself():
    transport = scenario_transport(specs=[[30 + i, "exalted", f"S{i:02d}"] for i in range(60)], total=60)
    client = make_client(transport)
    ids = [f"syn{i:03d}" for i in range(60)]
    rows = client.fetch_progressive(ids, "synthetic-query-0001")
    assert len(rows) <= 20 and transport.count("/fetch/") == 2
    transport2 = scenario_transport(specs=[[30 + i, "exalted", f"S{i:02d}"] for i in range(60)], total=60)
    one = make_client(transport2).fetch_progressive(ids, "synthetic-query-0001", max_fetch_requests=1)
    assert len(one) <= 10 and transport2.count("/fetch/") == 1


def test_cheapest_first_is_stated_as_cost_to_buy_not_worth():
    result, _, _ = _lookup("strong")
    assert result.request.compiled_query.body["sort"] == {"price": "asc"}
    text = f"{result.estimate.disclaimer} {result.estimate.summary}".lower()
    assert "cost to buy" in text
    for forbidden in ("fair value", "true value", "worth it", "is worth", "market value"):
        assert forbidden not in text


# ------------------------------------------------------------------------------------------------ uniques (defect D)

UNIQUE_ITEM = "Rarity: UNIQUE\nSynthetic Crown\nSapphire Ring\nLevelReq: 80\nImplicits: 1\n+30% to Cold Resistance\n+89 to maximum Energy Shield\n"


def test_a_unique_gets_no_base_type_estimate_and_no_request():
    transport = scenario_transport("strong")
    result = make_provider(make_client(transport)).lookup(compiled_request(UNIQUE_ITEM))
    assert transport.requests == []
    assert result.live_search_state is LiveSearchState.LIVE_ITEM_CLASS_UNSUPPORTED
    assert result.estimate.has_currency_estimate is False
    assert result.estimate_state == EstimateState.NEEDS_REFINEMENT.value
    trust = _trust(result)
    assert TrustReason.UNIQUE_NOT_PRICED.value in trust["hard_vetoes"]
    assert trust["display_price_mode"] == DisplayPriceMode.NONE.value
    assert market_headline(_assessment_from(result)) is MarketHeadline.NO_TRUSTWORTHY_ESTIMATE


# ---------------------------------------------------------------------------------- outliers and sellers (section 7)


def _prices(values, sellers=None):
    sellers = sellers or [f"S{i:02d}" for i in range(len(values))]
    return [NormalizedPrice(f"id{i}", float(v), "exalted", s) for i, (v, s) in enumerate(zip(values, sellers))]


def _amounts(rows):
    return sorted(row.amount for row in rows)


def test_iqr_trims_a_lone_absurd_ask():
    kept = OutlierFilter().filter(_prices([30, 31, 32, 32, 33, 34, 34, 35, 36, 36, 37, 38, 500]))
    assert 500.0 not in _amounts(kept) and len(kept) == 12


def test_mad_uses_the_scaled_modified_z_score():
    """Unscaled `3.5 * MAD` trimmed a legitimate 43 from this tight set; the standard 3.5 * 1.4826 * MAD keeps it."""
    kept = OutlierFilter(iqr_multiplier=100.0)._mad_filter(_prices([30, 31, 32, 33, 34, 40, 43]))
    assert 43.0 in _amounts(kept)
    far = OutlierFilter(iqr_multiplier=100.0)._mad_filter(_prices([30, 31, 32, 33, 34, 40, 80]))
    assert 80.0 not in _amounts(far)


def test_mad_zero_fallback_is_relative_not_absolute():
    """When most asks are identical MAD is 0. The old fallback was an absolute 1.0 currency unit, so 0.5 divine against 0.05 divine
    survived; the fallback is now a share of the median, whatever the display currency."""
    prices = _prices([0.05, 0.05, 0.05, 0.05, 0.06, 0.5])
    kept = OutlierFilter()._mad_filter(prices)
    assert 0.5 not in _amounts(kept) and 0.06 in _amounts(kept)


def test_seller_dedupe_runs_before_the_outlier_pass():
    """One account listing many cheap items used to drag the quartiles down and make honest asks look high. After deduping, its cheapest
    listing is judged once, against the other sellers."""
    values = [10] * 5 + [30, 31, 32, 33, 34, 35, 36, 37]
    sellers = ["Hoarder"] * 5 + [f"Other{i}" for i in range(8)]
    kept = OutlierFilter().filter(_prices(values, sellers))
    assert 10.0 not in _amounts(kept), "the hoarder's cheap ask is an outlier among distinct sellers"
    assert _amounts(kept) == [30.0, 31.0, 32.0, 33.0, 34.0, 35.0, 36.0, 37.0]


def test_dedupe_keeps_the_cheapest_listing_per_seller_and_every_anonymous_one():
    rows = [
        NormalizedPrice("a1", 40.0, "exalted", "A"),
        NormalizedPrice("a2", 35.0, "exalted", "A"),
        NormalizedPrice("b1", 36.0, "exalted", "B"),
        NormalizedPrice("n1", 50.0, "exalted", None),
        NormalizedPrice("n2", 51.0, "exalted", None),
    ]
    kept = OutlierFilter().filter(rows)
    assert {row.listing_id for row in kept} == {"a2", "b1", "n1", "n2"}


def test_distinct_sellers_and_concentration_are_measured_before_dedupe():
    from exilelens.price_check.models import ComparableListing

    def listing(i, seller):
        return ComparableListing(listing_id=f"l{i}", item_raw="", price_amount=1.0, price_currency="exalted", source="t", league="L", seller_id=seller)

    stats = seller_stats([listing(i, "A" if i < 6 else f"B{i}") for i in range(10)])
    assert (stats.listing_count, stats.distinct_sellers) == (10, 5) and stats.top_seller_share == pytest.approx(0.6)


def test_concentrated_sample_is_flagged_and_cannot_be_high():
    # 8 other sellers plus one that listed 10 items: nine distinct prices survive dedupe, but more than half the sample is one account.
    specs = [[30 + i, "exalted", f"Other{i}"] for i in range(8)] + [[31 + i * 0.1, "exalted", "Hoarder"] for i in range(10)]
    result, _, _ = _lookup(specs=specs, total=60)
    trust = _trust(result)
    assert TrustReason.SELLER_CONCENTRATED.value in trust["reason_codes"]
    assert result.estimate_state != EstimateState.HIGH_CONFIDENCE.value
    assert result.comparable_count == 9


def test_multimodal_market_is_not_trimmed_into_a_fake_cluster():
    result, _, _ = _lookup("volatile")
    prices = sorted(row.normalized_amount for row in result.estimate.comparables)
    assert prices[0] <= 6 and prices[-1] >= 58, "both clusters survive"
    assert TrustReason.MARKET_MULTIMODAL.value in _trust(result)["hard_vetoes"]
    assert _headline(result) is MarketHeadline.VOLATILE_ESTIMATE


def test_two_lone_spikes_read_as_multimodal_which_is_conservative():
    """Documented limitation of the existing classifier: two extreme asks form a 'second mode' of size 2 (MULTIMODAL_MIN_SUPPORT)."""
    specs = [[30 + i % 8, "exalted", f"S{i:02d}"] for i in range(12)] + [[500, "exalted", "X1"], [900, "exalted", "X2"]]
    result, _, _ = _lookup(specs=specs, total=30)
    assert TrustReason.MARKET_MULTIMODAL.value in _trust(result)["hard_vetoes"]
    assert _headline(result) is MarketHeadline.VOLATILE_ESTIMATE
