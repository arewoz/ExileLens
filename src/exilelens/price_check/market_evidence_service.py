"""MarketEvidenceService (R5-B): the only thing Item Check talks to about market prices.

Responsibilities, in order: read the central market-access decision (and stop there when it says no), compile the item's market query
(the existing compiler), look in the evidence cache, make ONE provider lookup when permitted, convert the result with the one
conversion layer, and contain every failure as a typed `MarketEvidence`. It owns no pricing logic: the provider, trust model, rate
policy, FX and league handling are reused. It never touches PoB.

Concurrency model: the service is SYNCHRONOUS and starts no threads. The caller (EvaluationController) owns asynchrony and runs
`evidence_for` inside its own background job. Python cannot cancel a running thread, so the service does not pretend to: staleness is the
caller's decision (identity guards); a superseded job simply finishes and its result is discarded. Every lookup builds its OWN provider from
`provider_factory`, so an old job still executing can never share a provider with a newer one. The shared, already thread-safe pieces (rate
policy/limit state, response caches, in-flight coalescer, FX cache) stay shared through the provider's defaults.

Bounded work (live provider, when one is ever authorized): the transport times out each request after 30 s; one lookup makes at most 1 search
and 2 fetch batches (<= 20 listings) plus one exchange request per distinct non-base currency actually present (cached 15 min); pacing never
sleeps more than 5 s per wait and otherwise returns a typed rate-limited result. The bound is on request count and per-request time, not on
total wall-clock; no wall-clock service timeout exists.

While the live provider is unauthorized the default provider is never constructed (the access decision stops first), so nothing from the
trade2 stack is imported and no request is made. Tests inject `access_fn` and `provider_factory`.
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from typing import Any, Callable

from exilelens.price_check.market_evidence import (
    EvidenceStatus,
    ListedPrice,
    MarketEvidence,
    age_freshness,
    evidence_from_price_result,
    status_evidence,
)
from exilelens.price_check.market_policy import MarketAccessDecision, MarketAccessState, current_market_access

logger = logging.getLogger(__name__)

DEFAULT_EVIDENCE_TTL_SECONDS = 600.0
MAX_CACHE_ENTRIES = 64

_ACCESS_STATUS = {
    MarketAccessState.DISABLED_BY_USER: (EvidenceStatus.DISABLED, "DISABLED_BY_USER"),
    MarketAccessState.NETWORK_DISABLED: (EvidenceStatus.DISABLED, "NETWORK_DISABLED"),
    MarketAccessState.PROVIDER_NOT_AUTHORIZED: (EvidenceStatus.UNAVAILABLE, "PROVIDER_NOT_AUTHORIZED"),
}


@dataclass
class _CacheEntry:
    evidence: MarketEvidence
    stored_at: float


def _default_provider() -> Any:
    from exilelens.price_check.providers.live_trade2 import LiveTradeComparableProvider

    return LiveTradeComparableProvider()


def compile_market_request(item_raw: str, league: str) -> Any:
    """Item text -> CompiledPriceCheckRequest using the existing planner/compiler. Raises on an item that cannot be searched."""
    from exilelens.items.metadata import parse_lightweight_metadata
    from exilelens.items.raw_input import RawItemInput
    from exilelens.price_check.market_plan import compile_plan, plan_for_item
    from exilelens.price_check.models import CompiledPriceCheckRequest, LeagueContext, LeagueStatus

    raw = RawItemInput.from_text(item_raw)
    meta = parse_lightweight_metadata(raw)
    plan = plan_for_item(
        item_raw,
        category=meta.category,
        base_type=meta.base_type,
        rarity=meta.rarity,
        item_level=meta.ilvl,
        quality=meta.quality,
        corrupted=meta.corrupted,
    )
    compiled = compile_plan(plan)
    return CompiledPriceCheckRequest(
        item_raw=item_raw,
        content_hash=raw.content_hash,
        league=LeagueContext(league=league, status=LeagueStatus.KNOWN),
        request_id=0,
        compiled_query=compiled,
        plan=plan,
        generation=0,
    )


class MarketEvidenceService:
    def __init__(
        self,
        *,
        access_fn: Callable[[], MarketAccessDecision] = current_market_access,
        provider_factory: Callable[[], Any] = _default_provider,
        ttl_seconds: float = DEFAULT_EVIDENCE_TTL_SECONDS,
        wall_clock: Callable[[], float] = time.time,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self._access_fn = access_fn
        self._provider_factory = provider_factory
        self._ttl = float(ttl_seconds)
        self._wall = wall_clock
        self._mono = monotonic
        self._cache: dict[tuple[str, str], _CacheEntry] = {}
        self._lock = threading.Lock()
        self._lookups = 0

    # ------------------------------------------------------------------------------------------------------ public

    def evidence_for(self, item_raw: str, *, league: str | None, listed: ListedPrice | None = None) -> MarketEvidence:
        """Never raises. Returns typed evidence for every outcome."""
        try:
            evidence = self._evidence_for(item_raw, str(league or "").strip(), listed)
        except Exception as exc:  # noqa: BLE001 - nothing market-related may reach Item Check
            logger.warning("market evidence contained %s", type(exc).__name__)
            evidence = status_evidence(EvidenceStatus.UNAVAILABLE, "PROVIDER_ERROR", listed=listed)
        return evidence

    def invalidate(self) -> None:
        with self._lock:
            self._cache.clear()

    def diagnostics(self) -> dict[str, Any]:
        """Attempt-level operational state only (no query, listing, seller, price, item text or identity). What the product actually
        ACCEPTED is tracked by the controller after its stale guards, never here: a late, superseded lookup must not look current."""
        decision = self._access_fn()
        return {
            "access_state": decision.state.value,
            "network_permitted": decision.network_permitted,
            "cache_entries": len(self._cache),
            "provider_lookups": self._lookups,
        }

    # ----------------------------------------------------------------------------------------------------- internals

    def _evidence_for(self, item_raw: str, league: str, listed: ListedPrice | None) -> MarketEvidence:
        decision = self._access_fn()
        if not decision.network_permitted:
            status, code = _ACCESS_STATUS.get(decision.state, (EvidenceStatus.UNAVAILABLE, "UNAVAILABLE"))
            return status_evidence(status, code, league=league, listed=listed)
        if not league:
            return status_evidence(EvidenceStatus.UNAVAILABLE, "LEAGUE_REQUIRED", listed=listed)

        request = compile_market_request(item_raw, league)
        key = (league, request.compiled_query.query_fingerprint)
        cached = self._cache_get(key)
        if cached is not None:
            return cached.with_listed(listed) if listed is not None else cached

        result = self._lookup(request)
        evidence = evidence_from_price_result(result, fetched_at=self._wall(), listed=None)
        if evidence.status is EvidenceStatus.AVAILABLE:
            self._cache_put(key, evidence)
        return evidence.with_listed(listed) if listed is not None else evidence

    def _lookup(self, request: Any) -> Any:
        provider = self._provider_factory()  # one provider per lookup: never shared with a superseded, still-running lookup
        with self._lock:
            self._lookups += 1
        result = provider.lookup(request)
        if result is None:
            raise LookupError("provider returned no result")
        return result

    # cache: keyed by (league, compiled-query fingerprint). Never by the PoB build: price estimation does not depend on it.

    def _cache_get(self, key: tuple[str, str]) -> MarketEvidence | None:
        with self._lock:
            entry = self._cache.get(key)
            if entry is None:
                return None
            age = self._mono() - entry.stored_at
            if age > self._ttl:
                del self._cache[key]
                return None
            from dataclasses import replace

            return replace(entry.evidence, freshness=age_freshness(entry.evidence.freshness, age))

    def _cache_put(self, key: tuple[str, str], evidence: MarketEvidence) -> None:
        with self._lock:
            if len(self._cache) >= MAX_CACHE_ENTRIES:
                oldest = min(self._cache, key=lambda k: self._cache[k].stored_at)
                del self._cache[oldest]
            self._cache[key] = _CacheEntry(evidence, self._mono())
