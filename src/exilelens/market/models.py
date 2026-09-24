from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


MARKET_CONTRACT_VERSION = 1


class SearchDepth(str, Enum):
    FAST = "FAST"
    BALANCED = "BALANCED"
    DEEP = "DEEP"


DEPTH_EVAL_LIMITS = {
    SearchDepth.FAST: 30,
    SearchDepth.BALANCED: 100,
    SearchDepth.DEEP: 250,
}

DEPTH_PREFILTER_LIMITS = {
    SearchDepth.FAST: 60,
    SearchDepth.BALANCED: 200,
    SearchDepth.DEEP: 500,
}


@dataclass(frozen=True)
class ListingPrice:
    amount: float
    currency: str

    def to_dict(self) -> dict[str, Any]:
        return {"amount": self.amount, "currency": self.currency}

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> ListingPrice | None:
        if not data:
            return None
        return cls(amount=float(data["amount"]), currency=str(data["currency"]))


@dataclass(frozen=True)
class CandidateIdentity:
    listing_id: str
    content_hash: str
    source: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "listing_id": self.listing_id,
            "content_hash": self.content_hash,
            "source": self.source,
        }


@dataclass
class CandidateListing:
    identity: CandidateIdentity
    slot: str
    pob_slot: str
    item_raw: str
    price: ListingPrice | None = None
    label: str | None = None
    trade_url: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "identity": self.identity.to_dict(),
            "slot": self.slot,
            "pob_slot": self.pob_slot,
            "item_raw": self.item_raw,
            "price": self.price.to_dict() if self.price else None,
            "label": self.label,
            "trade_url": self.trade_url,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CandidateListing:
        ident = data.get("identity") or {}
        return cls(
            identity=CandidateIdentity(
                listing_id=str(ident.get("listing_id") or data.get("listing_id") or ident.get("content_hash") or ""),
                content_hash=str(ident.get("content_hash") or data.get("content_hash") or ""),
                source=str(ident.get("source") or data.get("source") or "unknown"),
            ),
            slot=str(data.get("slot") or ""),
            pob_slot=str(data.get("pob_slot") or ""),
            item_raw=str(data.get("item_raw") or ""),
            price=ListingPrice.from_dict(data.get("price")),
            label=data.get("label"),
            trade_url=data.get("trade_url"),
            metadata=dict(data.get("metadata") or {}),
        )


@dataclass(frozen=True)
class CandidateSourceCapabilities:
    live_market: bool = False
    import_supported: bool = True
    fixture: bool = False
    network: bool = False
    trade_site_url_only: bool = True
    label: str = "offline"

    def to_dict(self) -> dict[str, Any]:
        return {
            "live_market": self.live_market,
            "import_supported": self.import_supported,
            "fixture": self.fixture,
            "network": self.network,
            "trade_site_url_only": self.trade_site_url_only,
            "label": self.label,
        }


@dataclass
class MarketSearchRequest:
    slot: str
    profile: str = "BALANCED"
    budget_amount: float | None = None
    budget_currency: str | None = None
    depth: SearchDepth = SearchDepth.BALANCED
    source: str = "fixture"
    fixture_corpus: str | None = None
    import_path: str | None = None
    search_intent: dict[str, Any] | None = None
    baseline_generation: int = 0
    build_revision: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "slot": self.slot,
            "profile": self.profile,
            "budget_amount": self.budget_amount,
            "budget_currency": self.budget_currency,
            "depth": self.depth.value,
            "source": self.source,
            "fixture_corpus": self.fixture_corpus,
            "import_path": self.import_path,
            "search_intent": self.search_intent,
            "baseline_generation": self.baseline_generation,
            "build_revision": self.build_revision,
        }


@dataclass
class MarketQueryPlan:
    contract_version: int = MARKET_CONTRACT_VERSION
    slot: str = ""
    pob_slot: str = ""
    profile: str = "BALANCED"
    budget: ListingPrice | None = None
    depth: str = SearchDepth.BALANCED.value
    max_evaluations: int = 100
    prefilter_limit: int = 200
    intent_summary: dict[str, Any] = field(default_factory=dict)
    filters: list[dict[str, Any]] = field(default_factory=list)
    trade_site_hint: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "contract_version": self.contract_version,
            "kind": "MarketQueryPlan",
            "slot": self.slot,
            "pob_slot": self.pob_slot,
            "profile": self.profile,
            "budget": self.budget.to_dict() if self.budget else None,
            "depth": self.depth,
            "max_evaluations": self.max_evaluations,
            "prefilter_limit": self.prefilter_limit,
            "intent_summary": self.intent_summary,
            "filters": self.filters,
            "trade_site_hint": self.trade_site_hint,
            "network": False,
            "live_market": False,
        }


@dataclass
class CandidateEvaluation:
    listing: CandidateListing
    comparison: dict[str, Any]
    build_value_delta: float
    offense_delta: float
    defense_delta: float
    verdict: str
    power_per_currency: dict[str, Any] | None = None
    restore_pass: bool = True
    cache_hit: bool = False
    status: str = "ok"
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "listing": self.listing.to_dict(),
            "comparison": self.comparison,
            "build_value_delta": self.build_value_delta,
            "offense_delta": self.offense_delta,
            "defense_delta": self.defense_delta,
            "verdict": self.verdict,
            "power_per_currency": self.power_per_currency,
            "restore_pass": self.restore_pass,
            "cache_hit": self.cache_hit,
            "status": self.status,
            "error": self.error,
        }


@dataclass
class MarketCandidateResult:
    evaluation: CandidateEvaluation
    categories: list[str] = field(default_factory=list)
    pareto_rank: int | None = None
    on_frontier: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "evaluation": self.evaluation.to_dict(),
            "categories": self.categories,
            "pareto_rank": self.pareto_rank,
            "on_frontier": self.on_frontier,
        }


@dataclass
class ParetoFrontier:
    candidate_ids: list[str] = field(default_factory=list)
    objectives: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "candidate_ids": self.candidate_ids,
            "objectives": self.objectives,
        }


@dataclass
class MarketSearchProgress:
    phase: str
    message: str
    evaluated: int = 0
    total: int = 0
    prefiltered: int = 0
    sourced: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "phase": self.phase,
            "message": self.message,
            "evaluated": self.evaluated,
            "total": self.total,
            "prefiltered": self.prefiltered,
            "sourced": self.sourced,
        }


@dataclass
class MarketCandidatePool:
    """Phase 5C contract — evaluated candidates for a slot search."""

    slot: str
    pob_slot: str
    profile: str
    candidates: list[MarketCandidateResult] = field(default_factory=list)
    pareto: ParetoFrontier = field(default_factory=ParetoFrontier)
    categories: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "contract_version": MARKET_CONTRACT_VERSION,
            "kind": "MarketCandidatePool",
            "slot": self.slot,
            "pob_slot": self.pob_slot,
            "profile": self.profile,
            "candidates": [row.to_dict() for row in self.candidates],
            "pareto": self.pareto.to_dict(),
            "categories": self.categories,
        }


@dataclass
class MarketSearchResult:
    request: MarketSearchRequest
    query_plan: MarketQueryPlan
    source_capabilities: CandidateSourceCapabilities
    pool: MarketCandidatePool
    progress: MarketSearchProgress
    provider_status: str
    performance: dict[str, Any] = field(default_factory=dict)
    stale: bool = False
    network: bool = False
    live_market: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "contract_version": MARKET_CONTRACT_VERSION,
            "kind": "MarketSearchResult",
            "request": self.request.to_dict(),
            "query_plan": self.query_plan.to_dict(),
            "source_capabilities": self.source_capabilities.to_dict(),
            "pool": self.pool.to_dict(),
            "progress": self.progress.to_dict(),
            "provider_status": self.provider_status,
            "performance": self.performance,
            "stale": self.stale,
            "network": self.network,
            "live_market": self.live_market,
        }
