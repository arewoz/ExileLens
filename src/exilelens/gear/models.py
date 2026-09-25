from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from exilelens.market.models import CandidateIdentity, CandidateListing, ListingPrice, MarketCandidatePool


GEAR_CONTRACT_VERSION = 1
KEEP_CURRENT_ID = "__KEEP_CURRENT__"


class PoolState(str, Enum):
    READY = "READY"
    MISSING = "MISSING"
    STALE = "STALE"
    INCOMPATIBLE = "INCOMPATIBLE"
    EMPTY = "EMPTY"


class GearSearchPreset(str, Enum):
    FAST = "FAST"
    BALANCED = "BALANCED"
    DEEP = "DEEP"


GEAR_SEARCH_LIMITS = {
    GearSearchPreset.FAST: {"shortlist": 3, "beam_width": 24, "max_evaluations": 60, "exhaustive_threshold": 200},
    GearSearchPreset.BALANCED: {"shortlist": 5, "beam_width": 80, "max_evaluations": 180, "exhaustive_threshold": 400},
    GearSearchPreset.DEEP: {"shortlist": 8, "beam_width": 200, "max_evaluations": 450, "exhaustive_threshold": 500},
}


class PlanConstraint(str, Enum):
    MAIN_SKILL_MUST_REMAIN_VALID = "MAIN_SKILL_MUST_REMAIN_VALID"
    KEEP_ELEMENTAL_RES_CAPS = "KEEP_ELEMENTAL_RES_CAPS"
    EHP_NOT_BELOW_CURRENT = "EHP_NOT_BELOW_CURRENT"
    RESOURCE_STATE_NOT_WORSE = "RESOURCE_STATE_NOT_WORSE"
    MIN_DPS_FLOOR = "MIN_DPS_FLOOR"
    MIN_MAX_HIT_FLOOR = "MIN_MAX_HIT_FLOOR"
    MAX_PURCHASES = "MAX_PURCHASES"


DEFAULT_CONSTRAINTS = (
    PlanConstraint.MAIN_SKILL_MUST_REMAIN_VALID,
    PlanConstraint.KEEP_ELEMENTAL_RES_CAPS,
    PlanConstraint.EHP_NOT_BELOW_CURRENT,
    PlanConstraint.RESOURCE_STATE_NOT_WORSE,
)


@dataclass(frozen=True)
class GearPlanReplacement:
    product_slot: str
    pob_slot: str
    identity: CandidateIdentity | None
    listing: CandidateListing | None
    item_raw: str
    price: ListingPrice | None = None
    keep_current: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "product_slot": self.product_slot,
            "pob_slot": self.pob_slot,
            "identity": self.identity.to_dict() if self.identity else None,
            "listing": self.listing.to_dict() if self.listing else None,
            "item_raw": self.item_raw,
            "price": self.price.to_dict() if self.price else None,
            "keep_current": self.keep_current,
        }


@dataclass(frozen=True)
class GearPlan:
    replacements: tuple[GearPlanReplacement, ...]

    @property
    def canonical_id(self) -> str:
        parts: list[str] = []
        for row in sorted(self.replacements, key=lambda r: r.product_slot):
            if row.keep_current:
                parts.append(f"{row.product_slot}=KEEP")
            else:
                lid = row.identity.listing_id if row.identity else row.item_raw[:32]
                parts.append(f"{row.product_slot}={lid}")
        payload = "|".join(parts)
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]

    @property
    def purchase_count(self) -> int:
        return sum(1 for row in self.replacements if not row.keep_current)

    @property
    def total_price(self) -> float:
        total = 0.0
        for row in self.replacements:
            if row.keep_current or row.price is None:
                continue
            total += float(row.price.amount)
        return total

    def active_replacements(self) -> tuple[GearPlanReplacement, ...]:
        return tuple(row for row in self.replacements if not row.keep_current)

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": "GearPlan",
            "contract_version": GEAR_CONTRACT_VERSION,
            "canonical_id": self.canonical_id,
            "replacements": [row.to_dict() for row in self.replacements],
            "purchase_count": self.purchase_count,
            "total_price": self.total_price,
        }


@dataclass
class SlotPoolEntry:
    product_slot: str
    pob_slot: str
    state: PoolState
    pool: MarketCandidatePool | None = None
    candidate_count: int = 0
    baseline_fingerprint: str = ""
    baseline_generation: int = 0
    profile: str = "BALANCED"
    message: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "product_slot": self.product_slot,
            "pob_slot": self.pob_slot,
            "state": self.state.value,
            "candidate_count": self.candidate_count,
            "baseline_fingerprint": self.baseline_fingerprint,
            "baseline_generation": self.baseline_generation,
            "profile": self.profile,
            "message": self.message,
            "pool": self.pool.to_dict() if self.pool else None,
        }


@dataclass
class GearOptimizationRequest:
    baseline_fingerprint: str
    baseline_generation: int
    pools: dict[str, MarketCandidatePool]
    budget_amount: float
    budget_currency: str
    profile: str = "BALANCED"
    context: str = "MAP"
    constraints: tuple[PlanConstraint, ...] = DEFAULT_CONSTRAINTS
    search_preset: GearSearchPreset = GearSearchPreset.BALANCED
    enabled_slots: tuple[str, ...] = ()
    max_purchases: int | None = None
    min_dps_floor: float | None = None
    min_max_hit_floor: float | None = None
    build_revision: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": "GearOptimizationRequest",
            "contract_version": GEAR_CONTRACT_VERSION,
            "baseline_fingerprint": self.baseline_fingerprint,
            "baseline_generation": self.baseline_generation,
            "pools": {slot: pool.to_dict() for slot, pool in self.pools.items()},
            "budget_amount": self.budget_amount,
            "budget_currency": self.budget_currency,
            "profile": self.profile,
            "context": self.context,
            "constraints": [c.value for c in self.constraints],
            "search_preset": self.search_preset.value,
            "enabled_slots": list(self.enabled_slots),
            "max_purchases": self.max_purchases,
            "min_dps_floor": self.min_dps_floor,
            "min_max_hit_floor": self.min_max_hit_floor,
            "build_revision": self.build_revision,
        }


@dataclass
class GearPlanEvaluation:
    plan: GearPlan
    baseline_metrics: dict[str, Any]
    final_metrics: dict[str, Any]
    baseline_fingerprint: str
    final_fingerprint: str
    comparison: dict[str, Any]
    build_value_delta: float
    offense_delta: float
    defense_delta: float
    verdict: str
    warnings: list[dict[str, Any]] = field(default_factory=list)
    constraint_violations: list[str] = field(default_factory=list)
    restore_pass: bool = True
    cache_hit: bool = False
    status: str = "ok"
    error: str | None = None
    total_price: float = 0.0
    price_currency: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "plan": self.plan.to_dict(),
            "baseline_metrics": self.baseline_metrics,
            "final_metrics": self.final_metrics,
            "baseline_fingerprint": self.baseline_fingerprint,
            "final_fingerprint": self.final_fingerprint,
            "comparison": self.comparison,
            "build_value_delta": self.build_value_delta,
            "offense_delta": self.offense_delta,
            "defense_delta": self.defense_delta,
            "verdict": self.verdict,
            "warnings": self.warnings,
            "constraint_violations": self.constraint_violations,
            "restore_pass": self.restore_pass,
            "cache_hit": self.cache_hit,
            "status": self.status,
            "error": self.error,
            "total_price": self.total_price,
            "price_currency": self.price_currency,
        }


@dataclass
class GearOptimizationProgress:
    phase: str
    message: str
    evaluated: int = 0
    total: int = 0
    candidates_considered: int = 0
    best_build_value: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "phase": self.phase,
            "message": self.message,
            "evaluated": self.evaluated,
            "total": self.total,
            "candidates_considered": self.candidates_considered,
            "best_build_value": self.best_build_value,
        }


@dataclass
class GearOptimizationResult:
    request: GearOptimizationRequest
    label: str
    search_mode: str
    best_plan: GearPlanEvaluation | None
    alternatives: list[GearPlanEvaluation] = field(default_factory=list)
    pareto_frontier: list[str] = field(default_factory=list)
    categories: dict[str, str] = field(default_factory=dict)
    budget_curve: list[dict[str, Any]] = field(default_factory=list)
    best_single_purchase: GearPlanEvaluation | None = None
    opportunity_cost: dict[str, Any] | None = None
    pool_status: list[SlotPoolEntry] = field(default_factory=list)
    progress: GearOptimizationProgress = field(default_factory=lambda: GearOptimizationProgress("init", ""))
    performance: dict[str, Any] = field(default_factory=dict)
    stale: bool = False
    provider_status: str = "BEST FOUND IN AVAILABLE CANDIDATE POOLS"

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": "GearOptimizationResult",
            "contract_version": GEAR_CONTRACT_VERSION,
            "request": self.request.to_dict(),
            "label": self.label,
            "search_mode": self.search_mode,
            "best_plan": self.best_plan.to_dict() if self.best_plan else None,
            "alternatives": [row.to_dict() for row in self.alternatives],
            "pareto_frontier": self.pareto_frontier,
            "categories": self.categories,
            "budget_curve": self.budget_curve,
            "best_single_purchase": self.best_single_purchase.to_dict() if self.best_single_purchase else None,
            "opportunity_cost": self.opportunity_cost,
            "pool_status": [row.to_dict() for row in self.pool_status],
            "progress": self.progress.to_dict(),
            "performance": self.performance,
            "stale": self.stale,
            "provider_status": self.provider_status,
        }


def stable_json(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"))
