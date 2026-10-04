"""Provider package. The live trade2 providers load on first use (R5-A), so importing the package, or the app with market prices
off, does not import the trade2 client or its transport."""

from __future__ import annotations

from importlib import import_module
from typing import TYPE_CHECKING

from exilelens.price_check.providers.fixture import FixtureComparableProvider
from exilelens.price_check.providers.import_provider import ImportComparableProvider
from exilelens.price_check.providers.observation import ObservationCorpusProvider
from exilelens.price_check.providers.theoretical import TheoreticalValueProvider

if TYPE_CHECKING:
    from exilelens.price_check.providers.cached_live_trade2 import CachedLiveMarketProvider
    from exilelens.price_check.providers.live_trade2 import LiveTrade2Provider, LiveTradeComparableProvider

_LAZY = {
    "CachedLiveMarketProvider": "exilelens.price_check.providers.cached_live_trade2",
    "LiveTrade2Provider": "exilelens.price_check.providers.live_trade2",
    "LiveTradeComparableProvider": "exilelens.price_check.providers.live_trade2",
}


def __getattr__(name: str):
    module = _LAZY.get(name)
    if module is None:
        raise AttributeError(name)
    return getattr(import_module(module), name)


__all__ = [
    "CachedLiveMarketProvider",
    "FixtureComparableProvider",
    "ImportComparableProvider",
    "LiveTrade2Provider",
    "LiveTradeComparableProvider",
    "ObservationCorpusProvider",
    "TheoreticalValueProvider",
]
