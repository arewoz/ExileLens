"""R5-A: provider/transport failures are typed results (never exceptions), and the rate policy is deterministic.

Synthetic HTTP outcomes come from fixtures/market/errors.json and rate_headers.json (invented numbers), an injected clock drives
every window, and no sleep is real.
"""

from __future__ import annotations

import urllib.parse
from types import SimpleNamespace

import pytest

from exilelens.price_check import rate_limit
from exilelens.price_check.models import LiveSearchState
from exilelens.price_check.rate_policy import EXCHANGE, FETCH, SEARCH, TradePolicyRegistry
from exilelens.price_check.trade2_client import Trade2Error
from exilelens.price_check.transport import TransportError
from tests.market_support import (
    FakeClock,
    FakeTransport,
    compiled_request,
    error_response,
    fixture,
    make_client,
    make_provider,
    scenario_transport,
)

pytestmark = pytest.mark.itemcheck


@pytest.fixture
def clock():
    fake = FakeClock()
    slept: list[float] = []
    rate_limit.set_monotonic_clock(fake)
    rate_limit.set_sleep(slept.append)
    yield fake
    rate_limit.reset_monotonic_clock()


def _search_then(fetch_outcome):
    base = scenario_transport("strong")

    def handler(request):
        if "/fetch/" in urllib.parse.urlparse(request.url).path:
            return fetch_outcome
        return base.handler(request)

    return FakeTransport(handler)


def _lookup_with(transport):
    client = make_client(transport)
    return make_provider(client).lookup(compiled_request()), client


# ------------------------------------------------------------------------------------ provider failures are typed results


@pytest.mark.parametrize(
    ("name", "state"),
    [
        ("bad_request_400", LiveSearchState.LIVE_SEARCH_BAD_REQUEST),
        ("unauthorized_401", LiveSearchState.LIVE_SEARCH_AUTH_REQUIRED),
        ("forbidden_403", LiveSearchState.LIVE_SEARCH_FORBIDDEN),
        ("rate_limited_429", LiveSearchState.LIVE_SEARCH_RATE_LIMITED),
        ("server_error_503", LiveSearchState.LIVE_SEARCH_NETWORK_ERROR),
        ("malformed_json", LiveSearchState.LIVE_SEARCH_PARSE_ERROR),
        ("non_object_json", LiveSearchState.LIVE_SEARCH_PARSE_ERROR),
        ("missing_query_id", LiveSearchState.LIVE_SEARCH_PARSE_ERROR),
        ("empty_search", LiveSearchState.LIVE_SEARCH_OK_ZERO_RESULTS),
    ],
)
def test_search_failures_are_typed_and_carry_no_estimate(name, state):
    result, _ = _lookup_with(FakeTransport(lambda request, n=name: error_response(n)))
    assert result.live_search_state is state
    assert result.estimate.has_currency_estimate is False
    assert result.estimate.currency_bands == ()


@pytest.mark.parametrize(
    ("outcome", "state"),
    [
        (TransportError("timeout"), LiveSearchState.LIVE_SEARCH_NETWORK_ERROR),
        (TransportError("network"), LiveSearchState.LIVE_SEARCH_NETWORK_ERROR),
    ],
)
def test_transport_errors_are_typed(outcome, state):
    result, _ = _lookup_with(FakeTransport(lambda request, o=outcome: o))
    assert result.live_search_state is state and result.estimate.has_currency_estimate is False


@pytest.mark.parametrize(
    ("name", "state"),
    [
        ("fetch_missing_fields", LiveSearchState.LIVE_FETCH_NO_PRICES),
        ("fetch_result_not_list", LiveSearchState.LIVE_SEARCH_PARSE_ERROR),
        ("server_error_503", LiveSearchState.LIVE_SEARCH_NETWORK_ERROR),
        ("rate_limited_429", LiveSearchState.LIVE_SEARCH_RATE_LIMITED),
        ("malformed_json", LiveSearchState.LIVE_SEARCH_PARSE_ERROR),
    ],
)
def test_fetch_failures_are_typed(name, state):
    result, _ = _lookup_with(_search_then(error_response(name)))
    assert result.live_search_state is state
    assert result.estimate.has_currency_estimate is False


def test_fetch_timeout_is_typed():
    result, _ = _lookup_with(_search_then(TransportError("timeout")))
    assert result.live_search_state is LiveSearchState.LIVE_SEARCH_NETWORK_ERROR


# ------------------------------------------------------------------------------------- exception containment (defect E)


def test_an_unexpected_transport_exception_is_contained():
    result, _ = _lookup_with(FakeTransport(lambda request: RuntimeError("synthetic transport bug")))
    assert result.live_search_state is LiveSearchState.LIVE_PROVIDER_ERROR
    assert result.estimate.has_currency_estimate is False
    assert "synthetic transport bug" not in (result.message or "")  # exception text is never surfaced


def test_an_invalid_compiled_body_is_a_typed_bad_request_not_an_exception(monkeypatch):
    from exilelens.price_check import trade2_query_validation

    monkeypatch.setattr(
        trade2_query_validation,
        "validate_trade2_search_body",
        lambda body: SimpleNamespace(ok=False, fatal="synthetic: body cannot be repaired", body=body, repairs=()),
    )
    transport = scenario_transport("strong")
    result = make_provider(make_client(transport)).lookup(compiled_request())
    assert result.live_search_state is LiveSearchState.LIVE_SEARCH_BAD_REQUEST
    assert transport.requests == []


def test_an_estimator_exception_is_contained(monkeypatch):
    from exilelens.price_check.providers import live_trade2

    def boom(*args, **kwargs):
        raise ValueError("synthetic estimator bug")

    monkeypatch.setattr(live_trade2, "build_band_estimate", boom)
    result, _ = _lookup_with(scenario_transport("strong"))
    assert result.live_search_state is LiveSearchState.LIVE_PROVIDER_ERROR


def test_an_fx_exception_is_contained(monkeypatch):
    from exilelens.price_check.currency_fx import CurrencyFxTable

    def boom(self, *args, **kwargs):
        raise RuntimeError("synthetic fx bug")

    monkeypatch.setattr(CurrencyFxTable, "convert", boom)
    specs = [[30 + i, "exalted" if i % 2 else "divine", f"S{i:02d}"] for i in range(12)]
    result, _ = _lookup_with(scenario_transport(specs=specs, total=40))
    assert result.live_search_state is LiveSearchState.LIVE_PROVIDER_ERROR


def test_the_service_contains_a_raising_provider():
    from exilelens.price_check.service import PriceCheckService

    class Raising:
        provider_id = "live_trade2"

        def lookup(self, request):
            raise RuntimeError("synthetic provider bug")

    service = PriceCheckService(providers=[Raising()], live_market_mode="auto", strict_live=True)
    result = service.check(compiled_request())
    assert result.live_search_state is LiveSearchState.LIVE_PROVIDER_ERROR
    assert result.estimate.has_currency_estimate is False
    lenient = PriceCheckService(providers=[Raising()], live_market_mode="auto", strict_live=False)
    assert lenient.check(compiled_request()) is not None  # never raises, whatever the fallback decides


# ---------------------------------------------------------------------------------------- rate policy (synthetic headers)


def _registry(clock) -> TradePolicyRegistry:
    return TradePolicyRegistry(clock)


def test_dynamic_headers_replace_the_cold_start_fallback(clock):
    registry = _registry(clock)
    cold = registry.policy(SEARCH).rules
    assert cold, "a cold-start fallback exists but is only a floor"
    registry.update_from_headers(SEARCH, fixture("rate_headers.json")["learned_search"], http_status=200)
    learned = registry.policy(SEARCH)
    assert {(r.max_hits, r.period_seconds, r.penalty_seconds) for r in learned.rules} == {(4, 8, 20), (10, 30, 120), (2, 5, 30)}
    assert learned.server_policy == "synthetic-search"
    assert learned.rules != cold


def test_the_learned_window_paces_requests_and_releases_on_time(clock):
    registry = _registry(clock)
    registry.update_from_headers(SEARCH, {"X-Rate-Limit-Policy": "p", "X-Rate-Limit-Rules": "Ip", "X-Rate-Limit-Ip": "3:10:60"}, http_status=200)
    # 3 hits/10s keeps one slot in reserve: two requests go out, the third waits for the window to free a slot.
    assert registry.seconds_until_safe(SEARCH) == 0.0
    registry.record_request(SEARCH)
    registry.record_request(SEARCH)
    wait = registry.seconds_until_safe(SEARCH)
    assert 9.0 < wait <= 10.5
    clock.advance(9.9)  # the window is 10s; the extra margin in `wait` is conservatism, not part of the window
    assert registry.seconds_until_safe(SEARCH) > 0.0
    clock.advance(0.2)
    assert registry.seconds_until_safe(SEARCH) == 0.0


def test_retry_after_on_a_429_sets_a_penalty_that_expires(clock):
    registry = _registry(clock)
    registry.update_from_headers(SEARCH, error_response("rate_limited_429").headers, http_status=429, retry_after=37.0)
    assert registry.seconds_until_safe(SEARCH) == pytest.approx(37.0)
    clock.advance(36.0)
    assert registry.seconds_until_safe(SEARCH) == pytest.approx(1.0)
    clock.advance(1.5)
    assert registry.seconds_until_safe(SEARCH) == 0.0


def test_an_active_penalty_in_the_rule_state_wins(clock):
    registry = _registry(clock)
    registry.update_from_headers(SEARCH, fixture("rate_headers.json")["penalty_active"], http_status=200)
    assert registry.seconds_until_safe(SEARCH) == pytest.approx(45.0)
    clock.advance(45.1)
    assert registry.seconds_until_safe(SEARCH) == 0.0


def test_endpoints_are_independent(clock):
    registry = _registry(clock)
    registry.update_from_headers(SEARCH, error_response("rate_limited_429").headers, http_status=429, retry_after=37.0)
    assert registry.seconds_until_safe(SEARCH) > 0.0
    assert registry.seconds_until_safe(FETCH) == 0.0 and registry.seconds_until_safe(EXCHANGE) == 0.0


def test_a_429_stops_further_requests_until_the_penalty_expires(clock):
    transport = FakeTransport(lambda request: error_response("rate_limited_429"))
    client = make_client(transport, clock=clock)
    provider = make_provider(client)
    first = provider.lookup(compiled_request())
    assert first.live_search_state is LiveSearchState.LIVE_SEARCH_RATE_LIMITED
    sent = len(transport.requests)
    assert sent == 1 and client.rate_limit_state.is_limited()
    # While limited, lookups answer from local state and send nothing.
    for _ in range(3):
        again = provider.lookup(compiled_request())
        assert again.live_search_state is LiveSearchState.LIVE_SEARCH_RATE_LIMITED
    assert len(transport.requests) == sent
    clock.advance(40.0)
    assert not client.rate_limit_state.is_limited()
    transport.handler = scenario_transport("strong").handler
    ok = provider.lookup(compiled_request())
    assert ok.live_search_state is LiveSearchState.LIVE_SEARCH_OK_RESULTS
    assert len(transport.requests) > sent


def test_pacing_error_is_raised_before_any_request_when_the_policy_says_wait(clock):
    transport = scenario_transport("strong")
    client = make_client(transport, clock=clock)
    client.policy_registry.update_from_headers(SEARCH, error_response("rate_limited_429").headers, http_status=429, retry_after=37.0)
    with pytest.raises(Trade2Error) as caught:
        client.search("Synthetic League", compiled_request().compiled_query.body)
    assert caught.value.code == "rate_limit_pacing" and caught.value.retry_after == pytest.approx(37.0)
    assert transport.requests == []
