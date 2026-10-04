"""R5-A: market networking is off by default, one central policy decides, and the production transport can never reach GGG.

Everything here is offline. `conftest.py` makes any real connection attempt from a `test_r5a_*` module fail the test.
"""

from __future__ import annotations

import types

import pytest

from exilelens.app.settings import AppSettings
from exilelens.price_check import market_policy as mp
from exilelens.price_check.models import LiveSearchState
from exilelens.price_check.trade2_client import Trade2Client, Trade2Error
from exilelens.price_check.transport import AuthorizedTransport, TransportNotPermitted, TransportRequest

from tests.market_support import FakeTransport, compiled_request, make_provider, scenario_transport

pytestmark = pytest.mark.itemcheck


@pytest.fixture(autouse=True)
def _clean_policy_state(monkeypatch):
    from exilelens import security_audit

    for name in ("EXILELENS_AUDIT_VARIANT", "POE2VALUE_LIVE_TRADE2", "POE2VALUE_LIVE_MARKET_MODE", "POE2VALUE_TRADE2_SESSION"):
        monkeypatch.delenv(name, raising=False)
    security_audit.variant.cache_clear()
    mp.register_settings_reader(None)
    yield
    mp.register_settings_reader(None)
    security_audit.variant.cache_clear()


def _no_network_build(monkeypatch):
    from exilelens import security_audit

    monkeypatch.setenv("EXILELENS_AUDIT_VARIANT", "no_network")
    security_audit.variant.cache_clear()


def _opted_in() -> AppSettings:
    settings = AppSettings()
    settings.market_prices_enabled = True
    settings.market_consent_version = mp.MARKET_CONSENT_VERSION
    return settings


# ----------------------------------------------------------------------------------------------- the central decision


def test_market_prices_default_off_with_no_consent():
    settings = AppSettings()
    assert settings.market_prices_enabled is False
    assert settings.market_consent_version == 0
    decision = mp.market_access_for_settings(settings)
    assert decision.state is mp.MarketAccessState.DISABLED_BY_USER
    assert decision.network_permitted is False


def test_enabling_without_recorded_consent_is_still_off():
    settings = AppSettings()
    settings.market_prices_enabled = True
    assert mp.market_access_for_settings(settings).state is mp.MarketAccessState.DISABLED_BY_USER
    settings.market_consent_version = mp.MARKET_CONSENT_VERSION + 1  # consent to a different statement does not count
    assert mp.market_access_for_settings(settings).state is mp.MarketAccessState.DISABLED_BY_USER


def test_opt_in_with_consent_still_resolves_provider_not_authorized_and_permits_no_network():
    decision = mp.market_access_for_settings(_opted_in())
    assert decision.state is mp.MarketAccessState.PROVIDER_NOT_AUTHORIZED
    assert decision.network_permitted is False
    assert mp.LIVE_TRADE2_AUTHORIZED is False
    assert mp.LIVE_TRADE2_AUTHORIZATION == "BLOCKED_PENDING_PROVIDER_AUTHORIZATION"
    assert mp.live_market_mode_for_settings(_opted_in()) == "disabled"


def test_no_network_build_wins_over_every_setting(monkeypatch):
    _no_network_build(monkeypatch)
    decision = mp.market_access_for_settings(_opted_in())
    assert decision.state is mp.MarketAccessState.NETWORK_DISABLED
    assert decision.network_permitted is False
    # ...even for a provider that WERE authorized.
    assert mp.resolve_market_access(enabled=True, consent_version=mp.MARKET_CONSENT_VERSION, provider_authorized=True).state is (
        mp.MarketAccessState.NETWORK_DISABLED
    )


def test_the_only_way_to_available_is_the_authorization_constant():
    """Documents the single switch: with a (hypothetically) authorized provider plus opt-in plus consent, access opens; nothing else opens it."""
    decision = mp.resolve_market_access(enabled=True, consent_version=mp.MARKET_CONSENT_VERSION, provider_authorized=True)
    assert decision.state is mp.MarketAccessState.AVAILABLE and decision.network_permitted is True


def test_environment_variables_can_only_disable(monkeypatch):
    monkeypatch.setenv("POE2VALUE_LIVE_TRADE2", "1")
    monkeypatch.setenv("POE2VALUE_LIVE_MARKET_MODE", "auto")
    assert mp.resolve_live_market_mode(None) == "disabled"
    assert mp.resolve_live_market_mode("disabled") == "disabled"
    assert mp.market_access_for_settings(AppSettings()).network_permitted is False
    assert mp.market_access_for_settings(_opted_in()).network_permitted is False


def test_legacy_live_market_mode_setting_is_ignored():
    from_old_file = AppSettings.from_dict({"live_market_mode": "auto"})
    assert mp.live_market_mode_for_settings(from_old_file) == "disabled"
    assert mp.market_access_for_settings(from_old_file).network_permitted is False
    assert AppSettings().live_market_mode == "disabled"


def test_lookup_status_vocabulary_never_implies_an_estimate():
    statuses = {s.value for s in mp.MarketLookupStatus}
    assert {"DISABLED_BY_USER", "NETWORK_DISABLED", "PROVIDER_NOT_AUTHORIZED", "RATE_LIMITED", "UNAVAILABLE"} <= statuses
    off = mp.market_access_for_settings(AppSettings())
    assert mp.market_lookup_status(None, off) is mp.MarketLookupStatus.DISABLED_BY_USER
    blocked = mp.market_access_for_settings(_opted_in())
    assert mp.market_lookup_status(LiveSearchState.LIVE_PROVIDER_DISABLED, blocked) is mp.MarketLookupStatus.PROVIDER_NOT_AUTHORIZED
    assert mp.market_lookup_status(LiveSearchState.LIVE_SEARCH_RATE_LIMITED, blocked) is mp.MarketLookupStatus.RATE_LIMITED
    assert mp.market_lookup_status(LiveSearchState.LIVE_SEARCH_NETWORK_ERROR, blocked) is mp.MarketLookupStatus.UNAVAILABLE
    assert mp.market_lookup_status(LiveSearchState.LIVE_PROVIDER_ERROR, blocked) is mp.MarketLookupStatus.UNAVAILABLE


# ------------------------------------------------------------------------------------------------ the transport guard


def test_authorized_transport_refuses_before_calling_the_inner_transport():
    inner = FakeTransport(lambda request: pytest.fail("the inner transport must not be reached"))
    guarded = AuthorizedTransport(inner, mp.current_market_access)
    with pytest.raises(TransportNotPermitted) as caught:
        guarded(TransportRequest("GET", "https://example.invalid/synthetic"))
    assert caught.value.kind == "not_permitted"
    assert inner.requests == []


@pytest.mark.parametrize("opted_in", [False, True])
def test_default_client_cannot_reach_the_network_even_when_the_user_opted_in(opted_in):
    if opted_in:
        mp.register_settings_reader(_opted_in)
    client = Trade2Client()  # production default transport: AuthorizedTransport(UrllibTransport())
    with pytest.raises(Trade2Error) as caught:
        client.search("Synthetic League", compiled_request().compiled_query.body)
    assert caught.value.code == "not_permitted"
    with pytest.raises(Trade2Error) as caught:
        client.list_leagues()
    assert caught.value.code == "not_permitted"


def test_provider_with_the_default_client_returns_a_typed_unavailable_result_and_makes_no_request():
    mp.register_settings_reader(_opted_in)
    result = make_provider(Trade2Client()).lookup(compiled_request())
    assert result is not None
    assert result.live_search_state is LiveSearchState.LIVE_PROVIDER_DISABLED
    assert result.estimate.has_currency_estimate is False
    status = mp.market_lookup_status(result.live_search_state, mp.current_market_access())
    assert status is mp.MarketLookupStatus.PROVIDER_NOT_AUTHORIZED


# --------------------------------------------------------------------------------------------- startup league request


def test_league_catalog_default_fetch_is_never_started_when_market_is_off_or_unauthorized():
    from exilelens.price_check.league_catalog import LOOKUP_DISABLED, LeagueCatalog

    catalog = LeagueCatalog()
    for reader in (None, _opted_in):
        mp.register_settings_reader(reader)
        result = catalog.refresh(force=True)
        assert result.status == LOOKUP_DISABLED
        assert result.from_cache is True


def test_league_catalog_injected_fetch_is_the_callers_responsibility():
    from exilelens.price_check.league_catalog import LOOKUP_OK, LeagueCatalog

    calls: list[int] = []

    def fetch():
        calls.append(1)
        return ["Synthetic League"]

    result = LeagueCatalog().refresh(leagues_fn=fetch, force=True)
    assert result.status == LOOKUP_OK and calls == [1]


@pytest.mark.parametrize("settings_factory", [AppSettings, _opted_in])
def test_startup_league_refresh_is_not_initiated(settings_factory):
    from exilelens.app.main import ExileLensApp

    def boom(*args, **kwargs):
        raise AssertionError("startup must not initiate a league request")

    controller = types.SimpleNamespace(settings=settings_factory(), refresh_league_catalog=boom, league_catalog=types.SimpleNamespace(refresh=boom))
    ExileLensApp._refresh_league_catalog_at_startup(types.SimpleNamespace(controller=controller))


def test_startup_league_refresh_is_not_initiated_in_no_network(monkeypatch):
    from exilelens.app.main import ExileLensApp

    _no_network_build(monkeypatch)

    def boom(*args, **kwargs):
        raise AssertionError("startup must not initiate a league request")

    controller = types.SimpleNamespace(settings=_opted_in(), refresh_league_catalog=boom)
    ExileLensApp._refresh_league_catalog_at_startup(types.SimpleNamespace(controller=controller))


# ----------------------------------------------------------------------------------------- no session cookie, identity


def test_no_session_cookie_is_ever_sent_even_if_the_old_environment_variable_is_set(monkeypatch):
    monkeypatch.setenv("POE2VALUE_TRADE2_SESSION", "synthetic-session-value")
    transport = scenario_transport("strong")
    from tests.market_support import make_client

    make_provider(make_client(transport)).lookup(compiled_request())
    assert transport.requests, "the fake transport should have been used"
    for request in transport.requests:
        names = {str(name).lower() for name in request.headers}
        assert "cookie" not in names and "authorization" not in names
        assert "synthetic-session-value" not in " ".join(str(value) for value in request.headers.values())


def test_production_source_has_no_session_cookie_path():
    import inspect

    from exilelens.price_check import trade2_client

    source = inspect.getsource(trade2_client).lower()
    assert "poesessid" not in source
    assert "trade2_session" not in source
    assert '"cookie"' not in source and "'cookie'" not in source


def test_user_agent_is_an_internal_exilelens_string_with_no_contact_or_oauth_claim():
    from exilelens.price_check.trade2_client import USER_AGENT

    assert "ExileLens" in USER_AGENT
    assert "@" not in USER_AGENT
    assert "oauth" not in USER_AGENT.lower() and "client_id" not in USER_AGENT.lower()
