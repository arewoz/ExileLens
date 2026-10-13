"""Economy / market boundary for filter generation (FILTER-08B).

This milestone builds NO pricing. It fixes the seam where a later R5 Market Intelligence layer can plug in:

* provenance stays LIVE / CACHED / HEURISTIC / UNKNOWN (production ``PriceSourceKind`` maps onto them below);
* a provider is consulted at GENERATION time only, so the generated filter and generation itself never depend on
  the network and never carry a fake price;
* asking prices are never evidence of completed sales: a provider that only has listings must return
  ``MarketLevel.HEURISTIC`` or ``UNKNOWN``, not a sale claim.
"""
from __future__ import annotations

from typing import Protocol

from exilelens.filters.decision import MarketContext, MarketLevel

# production exilelens.price_check.models.PriceSourceKind value -> filter provenance level
PRICE_SOURCE_TO_LEVEL = {
    "LIVE_MARKET": MarketLevel.LIVE,
    "CACHED_LIVE_MARKET": MarketLevel.CACHED,
    "HISTORICAL_MARKET": MarketLevel.CACHED,       # an observation that is no longer live: cached, never live
    "OBSERVATION_CORPUS": MarketLevel.HEURISTIC,
    "MODEL_THEORETICAL": MarketLevel.HEURISTIC,
    "UNKNOWN": MarketLevel.UNKNOWN,
}


class MarketProvider(Protocol):
    """Generation-time source of category/base market context. Must be deterministic for one cached snapshot."""

    def category_context(self, item_class: str, base_type: str | None, league: str) -> MarketContext: ...


class HeuristicMarketProvider:
    """Default: pinned category/base heuristics only (what FILTER-07/08B ship). No league, no price, no network."""

    def category_context(self, item_class: str, base_type: str | None, league: str) -> MarketContext:
        return MarketContext()


def level_for_price_source(kind: str) -> MarketLevel:
    return PRICE_SOURCE_TO_LEVEL.get(str(kind), MarketLevel.UNKNOWN)


# ---- FILTER-08D: the contract between a market provider and the opportunity graph ----------------------------------------------------
# Market information is OPTIONAL context with provenance. It carries no price and no sale claim, nothing in generation requires it, and
# a failing or absent provider degrades to UNKNOWN — never to an error and never to a visibility change.
from datetime import datetime, timezone
from typing import Iterable, Mapping

from exilelens.filters.opportunity_graph import MarketSignal

MARKET_LEVELS = ("LIVE", "CACHED", "HEURISTIC", "UNKNOWN")


class MarketContractError(ValueError):
    pass


def validate_signal(signal: MarketSignal, *, now: datetime | None = None) -> MarketSignal:
    """LIVE/CACHED need a source and a timezone-aware, non-future observation time; HEURISTIC/UNKNOWN need nothing."""
    if signal.level not in MARKET_LEVELS:
        raise MarketContractError(f"unknown market level {signal.level!r}")
    if signal.level in ("LIVE", "CACHED"):
        if not signal.source or not signal.observed_at:
            raise MarketContractError(f"{signal.level} market data needs a source and an observation time")
        try:
            observed = datetime.fromisoformat(signal.observed_at.replace("Z", "+00:00"))
        except ValueError as exc:
            raise MarketContractError(f"unparseable observation time {signal.observed_at!r}") from exc
        if observed.tzinfo is None:
            raise MarketContractError("market observation time must include a timezone")
        if observed > (now or datetime.now(timezone.utc)):
            raise MarketContractError("market observation time cannot be in the future")
    return signal


def signals_from(provider: MarketProvider | None, bases: Iterable[tuple[str, str]], league: str = "unverified",
                 *, now: datetime | None = None) -> Mapping[str, MarketSignal]:
    """Resolve (item_class, base) pairs into graph market signals. Deterministic for a cached provider; never raises, never uses the
    network by itself: an absent provider, a raising provider or an invalid answer yields UNKNOWN for that base."""
    out: dict[str, MarketSignal] = {}
    for item_class, base in bases:
        if provider is None:
            out[base] = MarketSignal("UNKNOWN", "no provider", "")
            continue
        try:
            context = provider.category_context(item_class, base, league)
            observed = context.observed_at.isoformat() if context.observed_at else ""
            out[base] = validate_signal(MarketSignal(context.level.value, context.source, observed), now=now)
        except Exception as exc:                                    # noqa: BLE001 - degrade, record why
            out[base] = MarketSignal("UNKNOWN", f"provider failed: {type(exc).__name__}", "")
    return out
