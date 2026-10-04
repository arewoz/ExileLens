"""R5-B: the MarketEvidence v1 contract, its single conversion layer, and MarketEvidenceService (injected providers/transports only)."""

from __future__ import annotations

import json
import threading
import urllib.parse

import pytest

from exilelens.price_check.market_evidence import (
    BandBasis,
    EvidenceStatus,
    Freshness,
    ListedPrice,
    ListedVsMarket,
    MarketEvidence,
    MarketPrice,
    age_freshness,
    evidence_from_price_result,
    listed_price_from_note,
    listed_vs_market,
    status_evidence,
)
from exilelens.price_check.market_evidence_service import MarketEvidenceService
from exilelens.price_check.market_policy import MarketAccessDecision, MarketAccessState
from exilelens.price_check.price_trust import EstimateState, MarketHeadline
from tests.market_support import (
    FakeClock,
    FakeTransport,
    RING_ITEM,
    compiled_request,
    error_response,
    make_client,
    make_provider,
    scenario_transport,
)

pytestmark = pytest.mark.itemcheck

LEAGUE = "Synthetic League"
ITEM = RING_ITEM.read_text(encoding="utf-8")
AVAILABLE = MarketAccessDecision(MarketAccessState.AVAILABLE, True, "test")


def _result(name=None, **kwargs):
    return make_provider(make_client(scenario_transport(name, **kwargs))).lookup(compiled_request())


def _evidence(name=None, **kwargs) -> MarketEvidence:
    return evidence_from_price_result(_result(name, **kwargs), fetched_at=1234.5)


# ------------------------------------------------------------------------------------------------------- the contract


@pytest.mark.parametrize(
    ("scenario", "status", "headline"),
    [
        ("strong", EvidenceStatus.AVAILABLE, MarketHeadline.STRONG_COMPARABLE_SET),
        ("outliers", EvidenceStatus.AVAILABLE, MarketHeadline.STRONG_COMPARABLE_SET),
        ("sparse", EvidenceStatus.AVAILABLE, MarketHeadline.SPARSE_MARKET),
        ("moderate", EvidenceStatus.AVAILABLE, MarketHeadline.SPARSE_MARKET),
        ("volatile", EvidenceStatus.AVAILABLE, MarketHeadline.NO_TRUSTWORTHY_ESTIMATE),  # see test_volatile_*
        ("unusable", EvidenceStatus.AVAILABLE, MarketHeadline.NO_TRUSTWORTHY_ESTIMATE),
        ("stale", EvidenceStatus.AVAILABLE, MarketHeadline.NO_TRUSTWORTHY_ESTIMATE),
    ],
)
def test_headline_and_status_per_scenario(scenario, status, headline):
    evidence = _evidence(scenario)
    assert evidence.status is status
    if scenario != "volatile":
        assert evidence.headline is headline


def test_strong_evidence_carries_a_price_basis_counts_and_freshness():
    evidence = _evidence("strong")
    assert evidence.estimate_state is EstimateState.HIGH_CONFIDENCE
    assert evidence.price is not None and evidence.price.low <= evidence.price.high
    assert evidence.price.display_currency == "exalted" and evidence.price.point is not None
    assert evidence.band_basis is BandBasis.CHEAPEST_COMPARABLES  # 20 of 64 listings
    assert evidence.comparable_count == 20 and evidence.distinct_sellers == 20
    assert evidence.freshness is Freshness.CURRENT
    assert evidence.fetched_at == 1234.5 and evidence.provider_id == "live_trade2" and evidence.league == LEAGUE
    assert evidence.coverage == ()


def test_a_complete_sample_is_labelled_full_sample():
    specs = [[30 + i, "exalted", f"S{i:02d}"] for i in range(9)]
    assert _evidence(specs=specs, total=9).band_basis is BandBasis.FULL_SAMPLE


@pytest.mark.parametrize("scenario", ["unusable", "concentrated", "stale", "volatile", "partial_fx"])
def test_untrustworthy_evidence_never_exposes_a_price(scenario):
    evidence = _evidence(scenario)
    if evidence.headline in {MarketHeadline.NO_TRUSTWORTHY_ESTIMATE, MarketHeadline.VOLATILE_ESTIMATE}:
        assert evidence.price is None and evidence.band_basis is None


def test_price_is_withheld_whenever_the_headline_is_no_trustworthy_estimate_across_every_scenario():
    from tests.market_support import fixture

    for name in fixture("listing_sets.json")["sets"]:
        evidence = _evidence(name)
        if evidence.headline is MarketHeadline.NO_TRUSTWORTHY_ESTIMATE:
            assert evidence.price is None, name
        if evidence.price is not None:
            assert evidence.headline in {
                MarketHeadline.STRONG_COMPARABLE_SET,
                MarketHeadline.WEAK_COMPARABLE_SET,
                MarketHeadline.SPARSE_MARKET,
            }, name


def test_volatile_evidence_has_no_price():
    evidence = _evidence("volatile")
    assert evidence.price is None
    assert evidence.headline is MarketHeadline.NO_TRUSTWORTHY_ESTIMATE or evidence.headline is MarketHeadline.VOLATILE_ESTIMATE


def test_stale_listings_are_reported_and_withhold_the_price():
    evidence = _evidence("stale")
    assert evidence.price is None and evidence.headline is MarketHeadline.NO_TRUSTWORTHY_ESTIMATE
    assert "PRICE_DATA_STALE" in evidence.reasons and evidence.freshness is Freshness.STALE


def test_zero_results_and_weak_comparables_are_available_but_priceless():
    zero = evidence_from_price_result(
        make_provider(make_client(FakeTransport(lambda r: error_response("empty_search")))).lookup(compiled_request()), fetched_at=1.0
    )
    assert zero.status is EvidenceStatus.AVAILABLE and zero.reason_code == "NO_LISTINGS"
    assert zero.price is None and zero.headline is MarketHeadline.NO_TRUSTWORTHY_ESTIMATE
    weak = _evidence("unusable")
    assert weak.price is None


def test_a_unique_is_unavailable_with_a_stable_reason():
    from tests.test_r5a_market_estimator import UNIQUE_ITEM

    result = make_provider(make_client(scenario_transport("strong"))).lookup(compiled_request(UNIQUE_ITEM))
    evidence = evidence_from_price_result(result)
    assert evidence.status is EvidenceStatus.UNAVAILABLE and evidence.reason_code == "UNIQUE_NOT_PRICED"
    assert evidence.price is None and "base type" in evidence.reason


@pytest.mark.parametrize(
    ("name", "status", "code"),
    [
        ("rate_limited_429", EvidenceStatus.RATE_LIMITED, "RATE_LIMITED"),
        ("server_error_503", EvidenceStatus.UNAVAILABLE, "UNAVAILABLE"),
        ("forbidden_403", EvidenceStatus.UNAVAILABLE, "UNAVAILABLE"),
        ("malformed_json", EvidenceStatus.UNAVAILABLE, "UNAVAILABLE"),
    ],
)
def test_provider_failures_map_to_typed_statuses(name, status, code):
    result = make_provider(make_client(FakeTransport(lambda r, n=name: error_response(n)))).lookup(compiled_request())
    evidence = evidence_from_price_result(result)
    assert (evidence.status, evidence.reason_code) == (status, code)
    assert evidence.price is None and evidence.headline is None and evidence.reason


def test_conversion_never_raises_on_garbage():
    evidence = evidence_from_price_result(object())
    assert evidence.status is EvidenceStatus.UNAVAILABLE


def test_coverage_says_what_the_search_did_not_include():
    result = _result("strong")
    request = result.request
    coverage = request.compiled_query.coverage
    assert list(evidence_from_price_result(result).coverage) == list(coverage.explain())


def test_serialisation_is_deterministic_versioned_and_round_trips():
    for scenario in ("strong", "unusable", "sparse"):
        evidence = _evidence(scenario).with_listed(ListedPrice(35.0, "Exalted"))
        data = evidence.to_dict()
        assert data["contract_version"] == 1
        assert json.dumps(data, sort_keys=True) == json.dumps(_evidence(scenario).with_listed(ListedPrice(35.0, "Exalted")).to_dict(), sort_keys=True)
        assert MarketEvidence.from_dict(json.loads(json.dumps(data))) == evidence
    assert set(data) == {
        "contract_version", "status", "reason_code", "reason", "provider_id", "league", "fetched_at", "freshness", "headline",
        "estimate_state", "reasons", "price", "band_basis", "comparable_count", "distinct_sellers", "coverage", "listed_price",
        "listed_vs_market",
    }
    assert not {key for key in data if "score" in key or "confidence" in key or "percent" in key}


@pytest.mark.parametrize("status", list(EvidenceStatus))
def test_every_status_serialises(status):
    evidence = status_evidence(status, "UNAVAILABLE", league="L")
    assert MarketEvidence.from_dict(evidence.to_dict()) == evidence and evidence.price is None


def test_freshness_ages_with_the_cache():
    assert age_freshness(Freshness.CURRENT, 10) is Freshness.CURRENT
    assert age_freshness(Freshness.CURRENT, 600) is Freshness.RECENT
    assert age_freshness(Freshness.CURRENT, 3000) is Freshness.AGING
    assert age_freshness(Freshness.CURRENT, 9000) is Freshness.STALE
    assert age_freshness(Freshness.STALE, 1) is Freshness.STALE
    assert age_freshness(None, 10) is Freshness.CURRENT


# ------------------------------------------------------------------------------------------------------ listed price


def test_the_existing_note_parser_is_reused():
    assert listed_price_from_note(ITEM + "Note: ~b/o 35 exalted\n") == ListedPrice(35.0, "Exalted", "NOTE")
    assert listed_price_from_note(ITEM) is None
    assert listed_price_from_note("Note: ~price 5 chaos") is None


def _priced(headline=MarketHeadline.STRONG_COMPARABLE_SET, low=30.0, high=36.0, currency="exalted", freshness=Freshness.CURRENT,
            status=EvidenceStatus.AVAILABLE, with_price=True):
    return MarketEvidence(
        status=status, headline=headline, freshness=freshness,
        price=MarketPrice(currency, low, high) if with_price else None,
    )


@pytest.mark.parametrize(
    ("amount", "expected"),
    [(29.9, ListedVsMarket.BELOW), (30.0, ListedVsMarket.WITHIN), (33.0, ListedVsMarket.WITHIN), (36.0, ListedVsMarket.WITHIN),
     (36.1, ListedVsMarket.ABOVE)],
)
def test_listed_vs_market_uses_the_actual_band(amount, expected):
    assert listed_vs_market(_priced(), ListedPrice(amount, "Exalted")) is expected
    assert listed_vs_market(_priced(headline=MarketHeadline.WEAK_COMPARABLE_SET), ListedPrice(amount, "exalted")) is expected


@pytest.mark.parametrize(
    "evidence",
    [
        _priced(headline=MarketHeadline.SPARSE_MARKET),
        _priced(headline=MarketHeadline.VOLATILE_ESTIMATE),
        _priced(headline=MarketHeadline.NO_TRUSTWORTHY_ESTIMATE, with_price=False),
        _priced(freshness=Freshness.STALE),
        _priced(currency="divine"),
        _priced(status=EvidenceStatus.UNAVAILABLE),
    ],
)
def test_listed_vs_market_is_not_comparable_when_the_evidence_cannot_support_it(evidence):
    assert listed_vs_market(evidence, ListedPrice(33.0, "Exalted")) is ListedVsMarket.NOT_COMPARABLE


def test_no_listed_price_means_no_comparison():
    assert listed_vs_market(_priced(), None) is None
    assert _priced().with_listed(None).listed_vs_market is None


# ------------------------------------------------------------------------------------------------------ the service


def _service(transport=None, *, access=AVAILABLE, clock=None, **kwargs):
    transport = transport or scenario_transport("strong")
    mono = clock or FakeClock()
    built = {"n": 0}

    def factory():
        built["n"] += 1
        return make_provider(make_client(transport))

    service = MarketEvidenceService(access_fn=lambda: access, provider_factory=factory, monotonic=mono, wall_clock=lambda: 5000.0, **kwargs)
    return service, transport, built, mono


@pytest.mark.parametrize(
    ("state", "status", "code"),
    [
        (MarketAccessState.DISABLED_BY_USER, EvidenceStatus.DISABLED, "DISABLED_BY_USER"),
        (MarketAccessState.NETWORK_DISABLED, EvidenceStatus.DISABLED, "NETWORK_DISABLED"),
        (MarketAccessState.PROVIDER_NOT_AUTHORIZED, EvidenceStatus.UNAVAILABLE, "PROVIDER_NOT_AUTHORIZED"),
    ],
)
def test_access_denials_short_circuit_before_any_work(state, status, code):
    service, transport, built, _ = _service(access=MarketAccessDecision(state, False, "x"))
    evidence = service.evidence_for(ITEM, league=LEAGUE, listed=ListedPrice(30.0, "Exalted"))
    assert (evidence.status, evidence.reason_code) == (status, code)
    assert built["n"] == 0 and transport.requests == [], "no provider constructed, no request"
    assert evidence.price is None and evidence.listed_price == ListedPrice(30.0, "Exalted") and evidence.listed_vs_market is None


def test_success_through_an_injected_provider():
    service, transport, built, _ = _service()
    evidence = service.evidence_for(ITEM + "Note: ~b/o 35 exalted\n", league=LEAGUE, listed=ListedPrice(35.0, "Exalted"))
    assert evidence.status is EvidenceStatus.AVAILABLE and evidence.headline is MarketHeadline.STRONG_COMPARABLE_SET
    assert evidence.fetched_at == 5000.0 and evidence.listed_vs_market is ListedVsMarket.WITHIN
    assert built["n"] == 1 and transport.count("/search/") == 1


def test_a_missing_league_is_typed():
    service, _, built, _ = _service()
    assert service.evidence_for(ITEM, league="").reason_code == "LEAGUE_REQUIRED" and built["n"] == 0


def test_rate_limited_and_unavailable_are_typed_and_not_cached():
    service, transport, _, _ = _service(FakeTransport(lambda r: error_response("rate_limited_429")))
    assert service.evidence_for(ITEM, league=LEAGUE).status is EvidenceStatus.RATE_LIMITED
    assert service.diagnostics()["cache_entries"] == 0
    service2, _, _, _ = _service(FakeTransport(lambda r: error_response("server_error_503")))
    assert service2.evidence_for(ITEM, league=LEAGUE).status is EvidenceStatus.UNAVAILABLE
    assert service2.diagnostics()["cache_entries"] == 0


def test_a_throwing_provider_is_contained():
    class Boom:
        def lookup(self, request):
            raise RuntimeError("synthetic provider bug SECRET")

    service = MarketEvidenceService(access_fn=lambda: AVAILABLE, provider_factory=Boom)
    evidence = service.evidence_for(ITEM, league=LEAGUE)
    assert evidence.status is EvidenceStatus.UNAVAILABLE and "SECRET" not in json.dumps(evidence.to_dict())


def test_a_throwing_factory_and_an_uncompilable_item_are_contained():
    def bad_factory():
        raise ImportError("synthetic")

    assert MarketEvidenceService(access_fn=lambda: AVAILABLE, provider_factory=bad_factory).evidence_for(ITEM, league=LEAGUE).status is (
        EvidenceStatus.UNAVAILABLE
    )
    service, _, _, _ = _service()
    assert service.evidence_for("not an item", league=LEAGUE).status is EvidenceStatus.UNAVAILABLE


def test_the_service_is_synchronous_and_starts_no_threads_of_its_own():
    seen = []

    class Probe:
        def lookup(self, request):
            seen.append(threading.current_thread())
            return make_provider(make_client(scenario_transport("strong"))).lookup(request)

    MarketEvidenceService(access_fn=lambda: AVAILABLE, provider_factory=Probe).evidence_for(ITEM, league=LEAGUE)
    assert seen == [threading.current_thread()]


def test_a_transport_timeout_is_the_real_boundary_and_is_typed():
    from exilelens.price_check.transport import TransportError

    service, _, _, _ = _service(FakeTransport(lambda r: TransportError("timeout")))
    evidence = service.evidence_for(ITEM, league=LEAGUE)
    assert evidence.status is EvidenceStatus.UNAVAILABLE and evidence.price is None


def test_every_lookup_gets_its_own_provider():
    built = []

    def factory():
        provider = make_provider(make_client(scenario_transport("strong")))
        built.append(provider)
        return provider

    service = MarketEvidenceService(access_fn=lambda: AVAILABLE, provider_factory=factory)
    service.evidence_for(ITEM, league=LEAGUE)
    service.evidence_for(ITEM.replace("40% increased", "20% increased"), league=LEAGUE)
    assert len(built) == 2 and built[0] is not built[1]


# cache: key = (league, compiled-query fingerprint); never the PoB build


def test_cache_hit_miss_and_expiry():
    service, transport, built, clock = _service(ttl_seconds=100.0)
    first = service.evidence_for(ITEM, league=LEAGUE)
    assert service.diagnostics()["provider_lookups"] == 1
    second = service.evidence_for(ITEM, league=LEAGUE)
    assert service.diagnostics()["provider_lookups"] == 1, "hit: the provider is not asked again"
    assert second.fetched_at == first.fetched_at and second.price == first.price
    clock.advance(101.0)
    service.evidence_for(ITEM, league=LEAGUE)
    assert service.diagnostics()["provider_lookups"] == 2, "expired: looked up again"


def test_cached_evidence_ages_its_freshness():
    service, _, _, clock = _service(ttl_seconds=100000.0)
    service.evidence_for(ITEM, league=LEAGUE)
    clock.advance(600.0)
    assert service.evidence_for(ITEM, league=LEAGUE).freshness is Freshness.RECENT
    clock.advance(9000.0)
    assert service.evidence_for(ITEM, league=LEAGUE).freshness is Freshness.STALE


def test_a_league_change_does_not_reuse_evidence():
    service, transport, _, _ = _service()
    service.evidence_for(ITEM, league=LEAGUE)
    before = transport.count("/search/")
    evidence = service.evidence_for(ITEM, league="Other Synthetic League")
    assert transport.count("/search/") == before + 1 and evidence.league == "Other Synthetic League"


def test_a_changed_query_does_not_reuse_evidence():
    service, transport, _, _ = _service()
    service.evidence_for(ITEM, league=LEAGUE)
    before = transport.count("/search/")
    changed = ITEM.replace("40% increased Cast Speed", "20% increased Cast Speed")
    service.evidence_for(changed, league=LEAGUE)
    assert transport.count("/search/") == before + 1


def test_the_listed_note_does_not_change_the_cache_key_but_is_reattached():
    service, transport, _, _ = _service()
    service.evidence_for(ITEM, league=LEAGUE)
    before = transport.count("/search/")
    evidence = service.evidence_for(ITEM, league=LEAGUE, listed=ListedPrice(500.0, "Exalted"))
    assert transport.count("/search/") == before and evidence.listed_vs_market is ListedVsMarket.ABOVE


def test_stale_evidence_stays_priceless_in_the_cache():
    service, _, _, _ = _service(scenario_transport("stale"))
    first = service.evidence_for(ITEM, league=LEAGUE)
    assert first.price is None and service.evidence_for(ITEM, league=LEAGUE).price is None


def test_diagnostics_are_operational_only():
    service, _, _, _ = _service()
    service.evidence_for(ITEM + "Note: ~b/o 33 exalted\n", league=LEAGUE)
    diag = service.diagnostics()
    assert set(diag) == {"access_state", "network_permitted", "cache_entries", "provider_lookups"}
    blob = json.dumps(diag)
    for private in ("Arcane Loop", "syn0", "Seller", "exalted", "query", ITEM[:20]):
        assert private not in blob


def test_the_service_never_enters_pob_or_the_trade2_stack_when_blocked():
    import subprocess
    import sys

    from tests.market_support import ROOT

    code = (
        "import sys\n"
        "from exilelens.price_check.market_evidence_service import MarketEvidenceService\n"
        "from exilelens.price_check.market_policy import resolve_market_access\n"
        "s = MarketEvidenceService(access_fn=lambda: resolve_market_access(enabled=True, consent_version=1))\n"
        "e = s.evidence_for(open(sys.argv[1], encoding='utf-8').read(), league='L')\n"
        "bad = [m for m in sys.modules if m.startswith(('exilelens.engine', 'exilelens.price_check.trade2_client',\n"
        "     'exilelens.price_check.transport', 'exilelens.price_check.providers.live_trade2'))]\n"
        "print(e.status.value, e.reason_code, bad)\n"
    )
    import os

    env = {**os.environ, "PYTHONPATH": str(ROOT / "src")}
    done = subprocess.run([sys.executable, "-c", code, str(RING_ITEM)], cwd=ROOT, env=env, capture_output=True, text=True, timeout=120)
    assert done.returncode == 0, done.stderr
    assert done.stdout.strip() == "UNAVAILABLE PROVIDER_NOT_AUTHORIZED []"
