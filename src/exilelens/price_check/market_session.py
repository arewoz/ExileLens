"""Short-lived store of real live-market listings, reusable across price checks.

MARKET-01B11. One item = one remote search cannot work when the search endpoint allows
5 requests per 10 seconds and penalises overuse by minutes. But a single search already
returns a *market neighbourhood* — ~100 result ids, of which we fetch a sample — and
that neighbourhood can price more than the one item that triggered it.

Everything stored here is real data observed from live trade2 responses. It is not
fixture data and it is not a theoretical model, so an estimate derived from it is a
genuine market estimate — labelled `CACHED LIVE MARKET` and carrying its age, never
passed off as fresh.

Reuse is keyed at several levels (task section 9):

* ``LEVEL 2`` the exact generated query fingerprint
* ``LEVEL 3`` the market neighbourhood — league + category + base + top economic
  feature families, deliberately coarser than an exact roll so a similar item reuses it
* ``LEVEL 4`` every recent observation for the league

Level 1, the exact-item result cache, already exists in ``price_check.cache``.
"""

from __future__ import annotations

import hashlib
import logging
import time
from dataclasses import dataclass, field
from threading import Lock
from typing import Callable, Iterable

from exilelens.price_check.comparable_query import ComparableSearchQuery
from exilelens.price_check.market_drivers import neighbourhood_identity, hypothesis_fingerprint
from exilelens.price_check.models import ComparableListing

logger = logging.getLogger(__name__)

# How long observed listings stay usable. Not market truth — internal constants, exposed
# in diagnostics so the age is always visible.
NEIGHBOURHOOD_TTL_SECONDS = 6 * 60.0
OBSERVATION_TTL_SECONDS = 20 * 60.0
MAX_OBSERVATIONS = 4000

# How many economic feature families define a neighbourhood. Narrow enough to stay
# economically meaningful, coarse enough that a similar item reuses it.
NEIGHBOURHOOD_FEATURE_LIMIT = 3


def neighbourhood_fingerprint(query: ComparableSearchQuery, *, league: str | None) -> str:
    """Coarse market-neighbourhood key from selected MarketPriceDrivers.

    MARKET-02B: keyed off the assisted hypothesis (selected driver families + match
    mode), not the old CRITICAL/HIGH-only subset. Two items with the same selected
    families share a neighbourhood; toggling a driver does not.
    """
    if query.hypothesis is not None:
        from dataclasses import replace

        hypothesis = query.hypothesis
        if league and not hypothesis.league:
            hypothesis = replace(hypothesis, league=league)
        return neighbourhood_identity(hypothesis)
    families: list[str] = []
    for feature in query.identity_features():
        family = str(getattr(feature, "family", "") or "").strip().lower()
        if family and family not in families:
            families.append(family)
    families.sort()
    parts = [
        str(league or "").strip().lower(),
        str(query.base_type or "").strip().lower(),
        str(query.rarity or "").strip().lower(),
        "|".join(families[:NEIGHBOURHOOD_FEATURE_LIMIT]),
    ]
    return hashlib.sha256("::".join(parts).encode("utf-8")).hexdigest()[:32]


def query_fingerprint(query: ComparableSearchQuery, *, league: str | None) -> str:
    """Exact generated-query key (level 2). Includes floors and match mode."""
    if query.hypothesis is not None:
        from dataclasses import replace

        hypothesis = query.hypothesis
        if league and not hypothesis.league:
            hypothesis = replace(hypothesis, league=league)
        return hypothesis_fingerprint(hypothesis)
    mods = sorted(
        f"{getattr(mod, 'family', '')}:{getattr(mod, 'normalized_text', '')}" for mod in query.mods
    )
    parts = [
        str(league or "").strip().lower(),
        str(query.base_type or "").strip().lower(),
        str(query.rarity or "").strip().lower(),
        str(int(query.relaxation_tier)),
        "|".join(mods),
    ]
    return hashlib.sha256("::".join(parts).encode("utf-8")).hexdigest()[:32]


@dataclass(frozen=True)
class MarketObservation:
    """One real listing seen in a live response."""

    listing_id: str
    league: str
    base_type: str
    category: str
    item_raw: str
    price_amount: float | None
    price_currency: str | None
    seller_id: str | None
    observed_at: float
    neighbourhood: str
    source_query: str

    @property
    def priced(self) -> bool:
        return self.price_amount is not None and bool(self.price_currency)

    def to_listing(self) -> ComparableListing:
        return ComparableListing(
            listing_id=self.listing_id,
            item_raw=self.item_raw,
            price_amount=self.price_amount,
            price_currency=self.price_currency,
            source="cached_live_market",
            league=self.league,
            seller_id=self.seller_id,
        )


@dataclass(frozen=True)
class NeighbourhoodLookup:
    """What the store can offer for a target item, without any network request."""

    listings: tuple[ComparableListing, ...]
    neighbourhood: str
    observed_at: float
    age_seconds: float
    matched_level: str
    total_candidates: int

    @property
    def count(self) -> int:
        return len(self.listings)

    def to_dict(self) -> dict[str, object]:
        return {
            "neighbourhood": self.neighbourhood,
            "matched_level": self.matched_level,
            "cached_comparable_count": self.count,
            "total_candidates": self.total_candidates,
            "live_cache_age_seconds": round(self.age_seconds, 1),
        }


@dataclass
class MarketSessionCache:
    """Recent real listings, reusable across items in the same market neighbourhood."""

    clock: Callable[[], float] = time.monotonic
    observation_ttl: float = OBSERVATION_TTL_SECONDS
    neighbourhood_ttl: float = NEIGHBOURHOOD_TTL_SECONDS
    max_observations: int = MAX_OBSERVATIONS
    _observations: dict[str, MarketObservation] = field(default_factory=dict, repr=False)
    _neighbourhood_seen_at: dict[str, float] = field(default_factory=dict, repr=False)
    _query_seen_at: dict[str, float] = field(default_factory=dict, repr=False)
    _lock: Lock = field(default_factory=Lock, repr=False)

    # ------------------------------------------------------------------- ingestion

    def record(
        self,
        listings: Iterable[ComparableListing],
        *,
        league: str | None,
        neighbourhood: str,
        source_query: str,
        category: str = "",
    ) -> int:
        """Store the real listings a live search/fetch returned."""
        now = self.clock()
        added = 0
        with self._lock:
            for listing in listings:
                if not listing.listing_id:
                    continue
                self._observations[listing.listing_id] = MarketObservation(
                    listing_id=listing.listing_id,
                    league=str(listing.league or league or ""),
                    base_type=_base_of(listing.item_raw),
                    category=category,
                    item_raw=listing.item_raw,
                    price_amount=listing.price_amount,
                    price_currency=listing.price_currency,
                    seller_id=getattr(listing, "seller_id", None),
                    observed_at=now,
                    neighbourhood=neighbourhood,
                    source_query=source_query,
                )
                added += 1
            self._neighbourhood_seen_at[neighbourhood] = now
            if source_query:
                self._query_seen_at[source_query] = now
            self._prune_locked(now)
        logger.info(
            "market_session_cache stored listings=%d neighbourhood=%s total=%d",
            added,
            neighbourhood[:12],
            len(self._observations),
        )
        return added

    def _prune_locked(self, now: float) -> None:
        cutoff = now - self.observation_ttl
        stale = [key for key, row in self._observations.items() if row.observed_at < cutoff]
        for key in stale:
            self._observations.pop(key, None)
        if len(self._observations) > self.max_observations:
            ordered = sorted(self._observations.items(), key=lambda kv: kv[1].observed_at)
            for key, _row in ordered[: len(self._observations) - self.max_observations]:
                self._observations.pop(key, None)
        for mapping, ttl in ((self._neighbourhood_seen_at, self.neighbourhood_ttl),
                             (self._query_seen_at, self.neighbourhood_ttl)):
            for key, stamp in list(mapping.items()):
                if now - stamp > ttl:
                    mapping.pop(key, None)

    # --------------------------------------------------------------------- lookup

    def lookup(
        self,
        *,
        league: str | None,
        neighbourhood: str,
        source_query: str = "",
        max_age_seconds: float | None = None,
    ) -> NeighbourhoodLookup | None:
        """Best reusable listings for this neighbourhood, newest first. No network."""
        now = self.clock()
        horizon = self.observation_ttl if max_age_seconds is None else max_age_seconds
        league_key = str(league or "").strip().lower()

        with self._lock:
            self._prune_locked(now)
            rows = [
                row
                for row in self._observations.values()
                if row.neighbourhood == neighbourhood
                and row.priced
                and (now - row.observed_at) <= horizon
                and (not league_key or str(row.league or "").strip().lower() == league_key)
            ]
            total = len(rows)
            level = "neighbourhood"
            if source_query:
                exact = [row for row in rows if row.source_query == source_query]
                if exact:
                    rows = exact
                    level = "query"

        if not rows:
            return None
        newest = max(row.observed_at for row in rows)
        rows.sort(key=lambda row: row.observed_at, reverse=True)
        return NeighbourhoodLookup(
            listings=tuple(row.to_listing() for row in rows),
            neighbourhood=neighbourhood,
            observed_at=newest,
            age_seconds=max(0.0, now - newest),
            matched_level=level,
            total_candidates=total,
        )

    def knows_neighbourhood(self, neighbourhood: str) -> bool:
        with self._lock:
            stamp = self._neighbourhood_seen_at.get(neighbourhood)
        return stamp is not None and (self.clock() - stamp) <= self.neighbourhood_ttl

    def snapshot(self) -> dict[str, object]:
        with self._lock:
            return {
                "observations": len(self._observations),
                "neighbourhoods": len(self._neighbourhood_seen_at),
                "queries": len(self._query_seen_at),
            }

    def clear(self) -> None:
        with self._lock:
            self._observations.clear()
            self._neighbourhood_seen_at.clear()
            self._query_seen_at.clear()


def _base_of(item_raw: str) -> str:
    lines = [line.strip() for line in str(item_raw or "").splitlines() if line.strip()]
    return lines[1] if len(lines) > 1 else ""


_SHARED: MarketSessionCache | None = None
_SHARED_LOCK = Lock()


def shared_market_session() -> MarketSessionCache:
    global _SHARED
    with _SHARED_LOCK:
        if _SHARED is None:
            _SHARED = MarketSessionCache()
        return _SHARED


def reset_shared_market_session() -> None:
    shared_market_session().clear()
