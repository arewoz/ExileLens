"""Cached list of currently active PoE2 trade leagues.

MARKET-01B10. The league selector and the resolver both need to know which leagues
exist, but `/api/trade2/data/leagues` is rate limited like every other trade2 endpoint —
and a 429 there must never turn into a dead end for a user who already has a league.

So the list is cached (in settings, therefore across restarts) and refreshed only when
stale. A failed refresh falls back to the cache and reports why it failed; it never
clears what is already known.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Callable, Iterable

logger = logging.getLogger(__name__)

DEFAULT_CACHE_TTL_SECONDS = 6 * 60 * 60  # leagues change on GGG's schedule, not ours

# Permanent leagues always exist. They are offered as choices, but the resolver never
# selects one on the user's behalf.
PERMANENT_LEAGUES: tuple[str, ...] = ("Standard", "Hardcore")


# Plain string constants: these travel into log payloads and presentation models, so
# they stay serialisable without any enum handling.
LOOKUP_OK = "OK"
LOOKUP_RATE_LIMITED = "LEAGUE_LOOKUP_RATE_LIMITED"
LOOKUP_FAILED = "LEAGUE_LOOKUP_FAILED"
LOOKUP_EMPTY = "NO_ACTIVE_LEAGUES"
LOOKUP_CACHED = "CACHED"
LOOKUP_SKIPPED = "SKIPPED_FRESH"


@dataclass(frozen=True)
class LeagueListResult:
    leagues: tuple[str, ...]
    status: str
    from_cache: bool
    error: str | None = None

    @property
    def ok(self) -> bool:
        return bool(self.leagues)


@dataclass
class LeagueCatalog:
    """Reads and refreshes the active league list, backed by a persistent cache."""

    leagues: list[str] = field(default_factory=list)
    fetched_at: float = 0.0
    ttl_seconds: float = DEFAULT_CACHE_TTL_SECONDS
    clock: Callable[[], float] = time.time

    @classmethod
    def from_settings(cls, settings, *, ttl_seconds: float = DEFAULT_CACHE_TTL_SECONDS) -> LeagueCatalog:
        return cls(
            leagues=[str(row) for row in (getattr(settings, "market_league_cache", None) or [])],
            fetched_at=float(getattr(settings, "market_league_cache_at", 0.0) or 0.0),
            ttl_seconds=ttl_seconds,
        )

    def write_to_settings(self, settings) -> None:
        settings.market_league_cache = list(self.leagues)
        settings.market_league_cache_at = float(self.fetched_at)

    @property
    def is_stale(self) -> bool:
        if not self.leagues:
            return True
        return (self.clock() - self.fetched_at) > self.ttl_seconds

    def cached(self) -> LeagueListResult:
        return LeagueListResult(tuple(self.leagues), LOOKUP_CACHED, from_cache=True)

    def refresh(
        self,
        *,
        leagues_fn: Callable[[], Iterable[str]] | None = None,
        force: bool = False,
    ) -> LeagueListResult:
        """Fetch the league list when stale. Never clears the cache on failure."""
        if not force and not self.is_stale:
            return LeagueListResult(tuple(self.leagues), LOOKUP_SKIPPED, from_cache=True)

        fetch = leagues_fn or _default_leagues_fn
        try:
            fetched = [str(row).strip() for row in fetch() if str(row).strip()]
        except Exception as exc:  # noqa: BLE001 - every failure falls back to cache
            status = LOOKUP_RATE_LIMITED if _looks_rate_limited(exc) else LOOKUP_FAILED
            logger.warning(
                "price_check_league_catalog refresh failed status=%s error=%s: %s cached=%d",
                status,
                type(exc).__name__,
                exc,
                len(self.leagues),
            )
            return LeagueListResult(tuple(self.leagues), status, from_cache=True, error=str(exc))

        if not fetched:
            logger.warning("price_check_league_catalog refresh returned no leagues; keeping cache")
            return LeagueListResult(tuple(self.leagues), LOOKUP_EMPTY, from_cache=True)

        self.leagues = fetched
        self.fetched_at = self.clock()
        logger.info("price_check_league_catalog refreshed count=%d", len(fetched))
        return LeagueListResult(tuple(self.leagues), LOOKUP_OK, from_cache=False)

    def selectable_leagues(self) -> tuple[str, ...]:
        """Leagues to offer in the picker: live list first, permanents always present."""
        ordered: list[str] = []
        for name in list(self.leagues) + list(PERMANENT_LEAGUES):
            if name and name not in ordered:
                ordered.append(name)
        return tuple(ordered)

    def knows(self, league: str) -> bool:
        cleaned = str(league or "").strip().lower()
        if not cleaned:
            return False
        return any(cleaned == str(row).strip().lower() for row in self.selectable_leagues())

    def canonicalize(self, league: str) -> str | None:
        cleaned = str(league or "").strip()
        if not cleaned:
            return None
        for row in self.selectable_leagues():
            if row.strip().lower() == cleaned.lower():
                return row
        return None

    def challenge_leagues(self) -> tuple[str, ...]:
        """Non-permanent softcore leagues — the ones a normal character plays in."""
        found: list[str] = []
        for league_id in self.leagues:
            lowered = league_id.lower()
            if lowered in {"standard", "hardcore"}:
                continue
            if lowered.startswith("hc "):
                continue
            found.append(league_id)
        return tuple(found)

    def active_league(self) -> str | None:
        """The single current challenge league, or None when that is not unambiguous.

        MARKET-01B10: PoE2 can run more than one challenge league at a time (the live
        list carried both `Forbidden Rites` and `Runes of Aldur`). Picking the first is
        a guess that would silently price against the wrong market, so ambiguity is
        reported rather than resolved — the user is asked instead.
        """
        challenge = self.challenge_leagues()
        if len(challenge) == 1:
            return challenge[0]
        return None

    def is_ambiguous(self) -> bool:
        return len(self.challenge_leagues()) > 1


def _default_leagues_fn() -> list[str]:
    from exilelens.price_check.trade2_client import Trade2Client

    return Trade2Client().list_leagues()


def _looks_rate_limited(exc: BaseException) -> bool:
    status = getattr(exc, "http_status", None)
    if status == 429:
        return True
    code = str(getattr(exc, "code", "") or "").lower()
    if "rate" in code and "limit" in code:
        return True
    return "rate limited" in str(exc).lower()
