from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

import logging

from exilelens.price_check.league_catalog import (
    LOOKUP_EMPTY,
    LOOKUP_FAILED,
    LOOKUP_RATE_LIMITED,
    LeagueCatalog,
)
from exilelens.price_check.models import LeagueContext, LeagueStatus

logger = logging.getLogger(__name__)

# Resolution sources, in the order the product prefers them.
SOURCE_PINNED = "pinned"
SOURCE_CHARACTER = "character"
SOURCE_BUILD = "build"
SOURCE_SAVED = "saved"
SOURCE_LIVE_LIST = "trade2_active_league"
SOURCE_UNKNOWN = "unknown"

# Why automatic resolution could not produce a league.
BUILD_LEAGUE_MISSING = "BUILD_LEAGUE_MISSING"
SAVED_LEAGUE_MISSING = "SAVED_LEAGUE_MISSING"
LEAGUE_LOOKUP_RATE_LIMITED = LOOKUP_RATE_LIMITED
LEAGUE_LOOKUP_FAILED = LOOKUP_FAILED
NO_ACTIVE_LEAGUES = LOOKUP_EMPTY
AMBIGUOUS_LEAGUE = "AMBIGUOUS_LEAGUE"
SAVED_LEAGUE_STALE = "SAVED_LEAGUE_STALE"

MODE_AUTO = "AUTO"
MODE_PINNED = "PINNED"


@dataclass(frozen=True)
class LeagueResolution:
    context: LeagueContext
    source: str
    needs_confirmation: bool = False
    failure_code: str | None = None
    stale_league: str | None = None

    @property
    def resolved(self) -> bool:
        return self.context.status == LeagueStatus.KNOWN and bool(self.context.league)

    def to_dict(self) -> dict[str, Any]:
        return {
            "league": self.context.league,
            "status": self.context.status.value,
            "source": self.source,
            "needs_confirmation": self.needs_confirmation,
            "failure_code": self.failure_code,
            "stale_league": self.stale_league,
        }


def _known(league: str, source: str, **kwargs: Any) -> LeagueResolution:
    return LeagueResolution(
        context=LeagueContext(league=league, status=LeagueStatus.KNOWN),
        source=source,
        **kwargs,
    )


def _unresolved(failure_code: str, *, stale_league: str | None = None) -> LeagueResolution:
    return LeagueResolution(
        context=LeagueContext(league=None, status=LeagueStatus.UNKNOWN),
        source=SOURCE_UNKNOWN,
        needs_confirmation=True,
        failure_code=failure_code,
        stale_league=stale_league,
    )


def resolve_market_league(
    *,
    settings_league: str | None = None,
    settings_mode: str | None = None,
    character_league: str | None = None,
    build_league: str | None = None,
    catalog: LeagueCatalog | None = None,
    leagues_fn: Callable[[], list[str]] | None = None,
    allow_network: bool = True,
) -> LeagueResolution:
    """Resolve the league for a live market search.

    Priority (MARKET-01B10):

    1. an explicit PINNED user choice, which wins outright until the user changes it
    2. the current character league, then the build league, when known
    3. the user's last confirmed league
    4. the live active-league list
    5. otherwise unresolved, so the caller can ask the user once

    A permanent league is never selected on the user's behalf; `Standard` only ever
    becomes the league because the user picked it.
    """
    mode = str(settings_mode or MODE_AUTO).strip().upper()
    saved = str(settings_league or "").strip()
    catalog = catalog if catalog is not None else LeagueCatalog()

    if mode == MODE_PINNED:
        if not saved:
            return _unresolved(SAVED_LEAGUE_MISSING)
        stale = _stale_reason(saved, catalog)
        if stale is not None:
            logger.info(
                "price_check_league pinned league is no longer available league=%s", saved
            )
            return _unresolved(SAVED_LEAGUE_STALE, stale_league=saved)
        canonical = catalog.canonicalize(saved) or saved
        logger.info("price_check_league resolved source=%s league=%s", SOURCE_PINNED, canonical)
        return _known(canonical, SOURCE_PINNED)

    for candidate, source in ((character_league, SOURCE_CHARACTER), (build_league, SOURCE_BUILD)):
        cleaned = str(candidate or "").strip()
        if cleaned:
            logger.info("price_check_league resolved source=%s league=%s", source, cleaned)
            return _known(catalog.canonicalize(cleaned) or cleaned, source)

    if saved:
        stale = _stale_reason(saved, catalog)
        if stale is not None:
            logger.info(
                "price_check_league saved league is no longer available league=%s", saved
            )
            return _unresolved(SAVED_LEAGUE_STALE, stale_league=saved)
        canonical = catalog.canonicalize(saved) or saved
        logger.info("price_check_league resolved source=%s league=%s", SOURCE_SAVED, canonical)
        return _known(canonical, SOURCE_SAVED)

    # Nothing saved. Consult the league list — cached first, network only if allowed.
    refresh = catalog.refresh(leagues_fn=leagues_fn) if allow_network else catalog.cached()
    active = catalog.active_league()
    if active:
        logger.info(
            "price_check_league resolved source=%s league=%s needs_confirmation=true",
            SOURCE_LIVE_LIST,
            active,
        )
        return _known(active, SOURCE_LIVE_LIST, needs_confirmation=True)

    if catalog.is_ambiguous():
        # More than one challenge league is running; choosing for the user would price
        # against the wrong market.
        logger.info(
            "price_check_league ambiguous challenge leagues=%s",
            list(catalog.challenge_leagues()),
        )
        return _unresolved(AMBIGUOUS_LEAGUE)

    failure = refresh.status if refresh.status in {
        LEAGUE_LOOKUP_RATE_LIMITED,
        LEAGUE_LOOKUP_FAILED,
    } else (NO_ACTIVE_LEAGUES if catalog.leagues else SAVED_LEAGUE_MISSING)
    logger.info(
        "price_check_league unresolved failure_code=%s cached_leagues=%d",
        failure,
        len(catalog.leagues),
    )
    return _unresolved(failure)


def _stale_reason(league: str, catalog: LeagueCatalog) -> str | None:
    """A saved league is stale only when we have a list and it is not in it.

    With no cached list — first run, or the lookup has never succeeded — the saved
    league is trusted rather than second-guessed, so a rate-limited lookup can never
    invalidate a league the user already confirmed.
    """
    if not catalog.leagues:
        return None
    if catalog.knows(league):
        return None
    return SAVED_LEAGUE_STALE


def describe_resolution(resolution: LeagueResolution, *, mode: str, saved: str | None) -> dict[str, Any]:
    """Diagnostic payload for the runtime log (MARKET-01B10 section 13)."""
    return {
        "league_mode": str(mode or MODE_AUTO).upper(),
        "saved_league": str(saved or "") or None,
        "resolved_league": resolution.context.league,
        "resolution_source": resolution.source,
        "needs_confirmation": resolution.needs_confirmation,
        "failure_code": resolution.failure_code,
    }
