"""Central market-access policy (R5-A).

ONE authoritative answer to "may ExileLens make a market network request right now?". Nothing else decides this: the startup
league fetch, the provider chain, the trade2 transport and the diagnostics all ask `resolve_market_access`.

Order of precedence (first match wins):
  1. NETWORK_DISABLED         audit/no_network build: no market traffic regardless of any setting.
  2. DISABLED_BY_USER         market prices are OFF by default and need an explicit opt-in WITH recorded consent.
  3. PROVIDER_NOT_AUTHORIZED  the only live provider is the undocumented trade2 website API. GGG's developer documentation supports
                              only the resources in its API Reference / Data Exports, so live trade2 stays production-disabled
                              until GGG explicitly documents or authorizes the access (`LIVE_TRADE2_AUTHORIZED`).
  4. AVAILABLE
So with the current constant, `network_permitted` is False for every setting combination and no market request is ever initiated.
The environment variables can only DISABLE; nothing in the environment can enable market networking.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable, Literal

LiveMarketMode = Literal["auto", "disabled"]

_LIVE_CHAIN_PROVIDER_IDS = frozenset({"live_trade2", "cached_live_trade2"})

# Policy state of the live trade2 provider. Flip only when GGG explicitly documents/authorizes this access; see
# docs/R5-MARKET-INTELLIGENCE-PLAN.md. The required User-Agent/identification format is likewise unresolved.
LIVE_TRADE2_AUTHORIZATION = "BLOCKED_PENDING_PROVIDER_AUTHORIZATION"
LIVE_TRADE2_AUTHORIZED = False

# Bumped when the data statement the user consents to changes.
MARKET_CONSENT_VERSION = 1


class MarketAccessState(str, Enum):
    DISABLED_BY_USER = "DISABLED_BY_USER"
    NETWORK_DISABLED = "NETWORK_DISABLED"
    PROVIDER_NOT_AUTHORIZED = "PROVIDER_NOT_AUTHORIZED"
    AVAILABLE = "AVAILABLE"


class MarketLookupStatus(str, Enum):
    """What the product can say about a market lookup. Access states plus the two runtime outcomes; never carries an estimate."""

    DISABLED_BY_USER = "DISABLED_BY_USER"
    NETWORK_DISABLED = "NETWORK_DISABLED"
    PROVIDER_NOT_AUTHORIZED = "PROVIDER_NOT_AUTHORIZED"
    RATE_LIMITED = "RATE_LIMITED"
    UNAVAILABLE = "UNAVAILABLE"
    AVAILABLE = "AVAILABLE"


@dataclass(frozen=True)
class MarketAccessDecision:
    state: MarketAccessState
    network_permitted: bool
    reason: str

    @property
    def status(self) -> MarketLookupStatus:
        return MarketLookupStatus(self.state.value)


_REASONS = {
    MarketAccessState.NETWORK_DISABLED: "Network access is disabled in this build.",
    MarketAccessState.DISABLED_BY_USER: "Market prices are off.",
    MarketAccessState.PROVIDER_NOT_AUTHORIZED: "The market provider is not available: it has not been authorized.",
    MarketAccessState.AVAILABLE: "Market access is available.",
}


def resolve_market_access(
    *,
    enabled: bool = False,
    consent_version: int = 0,
    provider_authorized: bool | None = None,
) -> MarketAccessDecision:
    """The single decision. Pure apart from the audit-variant read."""
    from exilelens.security_audit import network_disabled

    authorized = LIVE_TRADE2_AUTHORIZED if provider_authorized is None else bool(provider_authorized)
    if network_disabled():
        state = MarketAccessState.NETWORK_DISABLED
    elif not enabled or int(consent_version or 0) != MARKET_CONSENT_VERSION:
        state = MarketAccessState.DISABLED_BY_USER
    elif not authorized:
        state = MarketAccessState.PROVIDER_NOT_AUTHORIZED
    else:
        state = MarketAccessState.AVAILABLE
    return MarketAccessDecision(state, state is MarketAccessState.AVAILABLE, _REASONS[state])


def market_access_for_settings(settings: Any) -> MarketAccessDecision:
    return resolve_market_access(
        enabled=bool(getattr(settings, "market_prices_enabled", False)),
        consent_version=int(getattr(settings, "market_consent_version", 0) or 0),
    )


def live_market_mode_for_settings(settings: Any) -> LiveMarketMode:
    """The legacy `live_market_mode` string the provider chain still takes, derived from central access (never from the old setting)."""
    return "auto" if market_access_for_settings(settings).network_permitted else "disabled"


_settings_reader: Callable[[], Any] | None = None


def register_settings_reader(reader: Callable[[], Any] | None) -> None:
    """The app registers how to read current settings so the production transport can re-check access on every request."""
    global _settings_reader
    _settings_reader = reader


def current_market_access() -> MarketAccessDecision:
    reader = _settings_reader
    return market_access_for_settings(reader() if reader is not None else None)


def _env_flag(name: str) -> str:
    return os.environ.get(name, "").strip().lower()


def _is_pytest_runtime() -> bool:
    return bool(os.environ.get("PYTEST_CURRENT_TEST"))


def resolve_live_market_mode(settings_mode: str | None = None) -> LiveMarketMode:
    """Legacy mode resolver. FAIL-CLOSED: only an explicit "auto" (derived from central access by `live_market_mode_for_settings`)
    enables it, and the environment can only disable."""
    from exilelens.security_audit import network_disabled

    if network_disabled():
        return "disabled"
    env = _env_flag("POE2VALUE_LIVE_TRADE2")
    if env in {"0", "false", "no", "disabled", "off"}:
        return "disabled"
    env_mode = _env_flag("POE2VALUE_LIVE_MARKET_MODE")
    if env_mode in {"disabled", "off", "0"}:
        return "disabled"
    mode = str(settings_mode or "disabled").strip().lower()
    return "auto" if mode == "auto" else "disabled"


def is_live_market_enabled(settings_mode: str | None = None) -> bool:
    return resolve_live_market_mode(settings_mode) == "auto"


def resolve_strict_live(settings_strict: bool | None = None) -> bool:
    """Strict live is ON by default for owner/dev/frozen builds; tests opt out via pytest or env."""
    env = _env_flag("POE2VALUE_LIVE_TRADE2_STRICT")
    if env in {"0", "false", "no", "off"}:
        return False
    if env in {"1", "true", "yes"}:
        return True
    if settings_strict is not None:
        return bool(settings_strict)
    if _is_pytest_runtime():
        return False
    return True


def is_live_chain_provider(provider_id: str) -> bool:
    return provider_id in _LIVE_CHAIN_PROVIDER_IDS


def market_lookup_status(state: Any, access: MarketAccessDecision | None = None) -> MarketLookupStatus:
    """Map a lookup outcome (`LiveSearchState`, or None for "nothing attempted") to the status the product may state.

    Never produces or implies an estimate: it only says why there is none (or that the lookup itself worked)."""
    from exilelens.price_check.models import LiveSearchState

    decision = access if access is not None else current_market_access()
    if state is None:
        return decision.status
    if state is LiveSearchState.LIVE_PROVIDER_DISABLED:
        return decision.status if decision.state is not MarketAccessState.AVAILABLE else MarketLookupStatus.UNAVAILABLE
    if state is LiveSearchState.LIVE_SEARCH_RATE_LIMITED:
        return MarketLookupStatus.RATE_LIMITED
    if state in {LiveSearchState.LIVE_SEARCH_OK_RESULTS, LiveSearchState.LIVE_SEARCH_OK_ZERO_RESULTS, LiveSearchState.LIVE_COMPARABLES_TOO_WEAK,
                 LiveSearchState.LIVE_ITEM_CLASS_UNSUPPORTED}:
        return MarketLookupStatus.AVAILABLE
    return MarketLookupStatus.UNAVAILABLE
