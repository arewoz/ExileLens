"""MARKET-02D — persistent market hypothesis signatures.

A signature remembers hypothesis *shape* (families, match mode, floor policy),
not a stale price. Listing caches stay separate and still expire on their TTL.
"""

from __future__ import annotations

import hashlib
import logging
import time
from dataclasses import dataclass, replace
from enum import Enum
from typing import Any, Iterable

from poe2value.items.raw_input import RawItemInput
from poe2value.price_check.hypothesis_discovery import (
    FinalHypothesis,
    HypothesisStability,
)
from poe2value.price_check.market_drivers import (
    ARMOUR_PRIMARY,
    JEWEL_USEFUL,
    JEWELLERY_PRIMARY,
    JUNK_FAMILIES,
    MatchMode,
    MarketPriceDriver,
    PriceCheckHypothesis,
    SlotFamily,
    WEAPON_GLOBAL,
    HypothesisSource,
    build_auto_hypothesis,
    hypothesis_with_selection,
)
from poe2value.price_check.models import LeagueStatus, LiveSearchState, PriceCheckRequest, PriceCheckResult
from poe2value.price_check.stat_registry import STAT_REGISTRY_VERSION, get_family
from poe2value.price_check.trade2_query_validation import validate_trade2_search_body
from poe2value.price_check.trade2_query import build_trade2_search_body
from poe2value.price_check.comparable_query import build_search_query

logger = logging.getLogger(__name__)

SIGNATURE_SCHEMA_VERSION = 1
# Bumped whenever driver extraction/selection semantics change, so signatures
# learned under the old vocabulary are discarded instead of pinning a stale
# market identity. "02f2b-2": boots life/res ranking + provenance-tag parsing.
QUERY_VOCABULARY_VERSION = "02f2b-2"

# Age is in days: signatures encode driver structure, not live price.
SIGNATURE_FRESH_DAYS = 14.0
SIGNATURE_AGING_DAYS = 45.0
SIGNATURE_STALE_DAYS = 90.0

PROVISIONAL_DISTINCT_ITEMS = 2
MATURE_DISTINCT_ITEMS = 3
USER_REFINED_WEIGHT = 0.4
AUTO_H1_WEIGHT = 1.0
H2_RECOVERY_WEIGHT = 1.25
CONTRADICTION_DEGRADE_AT = 2

CASTER_FAMILIES = frozenset(
    {
        "cast_speed",
        "spell_damage",
        "lightning_spell_skills",
        "lightning_damage",
        "fire_damage",
        "cold_damage",
        "spell_critical_hit_chance",
    }
)
LIFE_RES_FAMILIES = frozenset(
    {
        "maximum_life",
        "chaos_resistance",
        "total_resistance",
        "total_elemental_resistance",
        "fire_resistance",
        "cold_resistance",
        "lightning_resistance",
    }
)


class SignatureMaturity(str, Enum):
    CANDIDATE = "CANDIDATE"
    PROVISIONAL = "PROVISIONAL"
    MATURE = "MATURE"
    DEGRADED = "DEGRADED"


class SignatureEvidenceSource(str, Enum):
    AUTO_H1_SUCCESS = "AUTO_H1_SUCCESS"
    AUTO_H2_RECOVERY = "AUTO_H2_RECOVERY"
    USER_REFINED_SUCCESS = "USER_REFINED_SUCCESS"


class SignatureAgeBand(str, Enum):
    FRESH = "fresh"
    AGING = "aging"
    STALE = "stale"


@dataclass
class SignatureMetrics:
    signature_lookup: int = 0
    signature_found: int = 0
    signature_applied: int = 0
    evidence_added: int = 0
    contradiction_added: int = 0
    signature_degraded: int = 0
    discovery_avoided: int = 0
    searches_saved_estimate: int = 0

    def snapshot(self) -> dict[str, int]:
        return {
            "signature_lookup": self.signature_lookup,
            "signature_found": self.signature_found,
            "signature_applied": self.signature_applied,
            "evidence_added": self.evidence_added,
            "contradiction_added": self.contradiction_added,
            "signature_degraded": self.signature_degraded,
            "discovery_avoided": self.discovery_avoided,
            "searches_saved_estimate": self.searches_saved_estimate,
        }


@dataclass(frozen=True)
class SignatureIdentity:
    league: str
    item_class: str
    base_family: str
    driver_family_set: tuple[str, ...]
    slot_family: str

    @property
    def signature_id(self) -> str:
        parts = [
            self.league.strip().lower(),
            self.slot_family.strip().lower(),
            self.item_class.strip().lower(),
            self.base_family.strip().lower(),
            "|".join(self.driver_family_set),
        ]
        return hashlib.sha256("::".join(parts).encode("utf-8")).hexdigest()[:24]


@dataclass
class MarketSignature:
    """Persistent hypothesis shape. Never a price table."""

    signature_id: str
    league: str
    item_class: str
    base_family: str
    driver_family_set: tuple[str, ...]
    preferred_selected_families: tuple[str, ...]
    preferred_selected_driver_ids: tuple[str, ...]
    preferred_match_mode: str
    preferred_count_min: int | None
    floor_strategy: tuple[str, ...]
    evidence_count: int = 0
    successful_use_count: int = 0
    failure_count: int = 0
    recovery_count: int = 0
    price_sample_count: int = 0
    median_similarity: float | None = None
    median_dispersion: float | None = None
    first_observed_at: float = 0.0
    last_observed_at: float = 0.0
    maturity: SignatureMaturity = SignatureMaturity.CANDIDATE
    source: SignatureEvidenceSource = SignatureEvidenceSource.AUTO_H1_SUCCESS
    schema_version: int = SIGNATURE_SCHEMA_VERSION
    vocabulary_version: str = QUERY_VOCABULARY_VERSION
    registry_version: str = STAT_REGISTRY_VERSION
    independent_item_fingerprints: tuple[str, ...] = ()
    independent_weight: float = 0.0
    self_confirmation_count: int = 0
    contradiction_count: int = 0
    slot_family: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "signature_id": self.signature_id,
            "league": self.league,
            "item_class": self.item_class,
            "base_family": self.base_family,
            "slot_family": self.slot_family,
            "driver_family_set": list(self.driver_family_set),
            "preferred_selected_families": list(self.preferred_selected_families),
            "preferred_selected_driver_ids": list(self.preferred_selected_driver_ids),
            "preferred_match_mode": self.preferred_match_mode,
            "preferred_count_min": self.preferred_count_min,
            "floor_strategy": list(self.floor_strategy),
            "evidence_count": self.evidence_count,
            "successful_use_count": self.successful_use_count,
            "failure_count": self.failure_count,
            "recovery_count": self.recovery_count,
            "price_sample_count": self.price_sample_count,
            "median_similarity": self.median_similarity,
            "median_dispersion": self.median_dispersion,
            "first_observed_at": self.first_observed_at,
            "last_observed_at": self.last_observed_at,
            "maturity": self.maturity.value,
            "source": self.source.value,
            "schema_version": self.schema_version,
            "vocabulary_version": self.vocabulary_version,
            "registry_version": self.registry_version,
            "independent_item_fingerprints": list(self.independent_item_fingerprints),
            "independent_weight": self.independent_weight,
            "self_confirmation_count": self.self_confirmation_count,
            "contradiction_count": self.contradiction_count,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> MarketSignature:
        return cls(
            signature_id=str(payload.get("signature_id") or ""),
            league=str(payload.get("league") or ""),
            item_class=str(payload.get("item_class") or ""),
            base_family=str(payload.get("base_family") or ""),
            slot_family=str(payload.get("slot_family") or ""),
            driver_family_set=tuple(str(value) for value in (payload.get("driver_family_set") or ())),
            preferred_selected_families=tuple(
                str(value) for value in (payload.get("preferred_selected_families") or ())
            ),
            preferred_selected_driver_ids=tuple(
                str(value) for value in (payload.get("preferred_selected_driver_ids") or ())
            ),
            preferred_match_mode=str(payload.get("preferred_match_mode") or MatchMode.ALL.value),
            preferred_count_min=payload.get("preferred_count_min"),
            floor_strategy=tuple(str(value) for value in (payload.get("floor_strategy") or ())),
            evidence_count=int(payload.get("evidence_count") or 0),
            successful_use_count=int(payload.get("successful_use_count") or 0),
            failure_count=int(payload.get("failure_count") or 0),
            recovery_count=int(payload.get("recovery_count") or 0),
            price_sample_count=int(payload.get("price_sample_count") or 0),
            median_similarity=payload.get("median_similarity"),
            median_dispersion=payload.get("median_dispersion"),
            first_observed_at=float(payload.get("first_observed_at") or 0.0),
            last_observed_at=float(payload.get("last_observed_at") or 0.0),
            maturity=_maturity(payload.get("maturity")),
            source=_source(payload.get("source")),
            schema_version=int(payload.get("schema_version") or 0),
            vocabulary_version=str(payload.get("vocabulary_version") or ""),
            registry_version=str(payload.get("registry_version") or ""),
            independent_item_fingerprints=tuple(
                str(value) for value in (payload.get("independent_item_fingerprints") or ())
            ),
            independent_weight=float(payload.get("independent_weight") or 0.0),
            self_confirmation_count=int(payload.get("self_confirmation_count") or 0),
            contradiction_count=int(payload.get("contradiction_count") or 0),
        )


def _maturity(raw: Any) -> SignatureMaturity:
    try:
        return SignatureMaturity(str(raw or SignatureMaturity.CANDIDATE.value))
    except ValueError:
        return SignatureMaturity.DEGRADED


def _source(raw: Any) -> SignatureEvidenceSource:
    try:
        return SignatureEvidenceSource(str(raw or SignatureEvidenceSource.AUTO_H1_SUCCESS.value))
    except ValueError:
        return SignatureEvidenceSource.AUTO_H1_SUCCESS


def _class_vocabulary(slot: SlotFamily) -> frozenset[str]:
    if slot is SlotFamily.JEWELLERY:
        return frozenset(JEWELLERY_PRIMARY)
    if slot is SlotFamily.WEAPON:
        return frozenset(("equip_dps", "equip_pdps", "equip_edps") + WEAPON_GLOBAL)
    if slot is SlotFamily.BOOTS:
        return frozenset(("equip_ar", "equip_ev", "equip_es", "movement_speed") + ARMOUR_PRIMARY)
    if slot is SlotFamily.ARMOUR:
        return frozenset(("equip_ar", "equip_ev", "equip_es") + ARMOUR_PRIMARY)
    if slot is SlotFamily.JEWEL:
        return JEWEL_USEFUL
    return frozenset(JEWELLERY_PRIMARY)


def market_relevant_families(hypothesis: PriceCheckHypothesis) -> tuple[str, ...]:
    vocab = _class_vocabulary(hypothesis.slot_family)
    families: list[str] = []
    for row in hypothesis.available_drivers:
        if row.family in JUNK_FAMILIES:
            continue
        if row.family not in vocab:
            continue
        if not row.trade_stat_ids and not row.equipment_key:
            continue
        if row.family not in families:
            families.append(row.family)
    return tuple(sorted(families))


def derive_base_family(hypothesis: PriceCheckHypothesis) -> str:
    present = set(market_relevant_families(hypothesis))
    slot = hypothesis.slot_family
    if slot is SlotFamily.JEWEL:
        return "jewel"
    if slot is SlotFamily.WEAPON:
        if present & CASTER_FAMILIES:
            return "caster_weapon"
        if present & {"equip_dps", "equip_pdps", "equip_edps"}:
            return "physical_weapon"
        return "weapon"
    if slot in {SlotFamily.ARMOUR, SlotFamily.BOOTS}:
        if "equip_ev" in present:
            return "evasion_armour"
        if "equip_es" in present:
            return "energy_shield_armour"
        if "equip_ar" in present:
            return "armour_armour"
        if "movement_speed" in present:
            return "boots"
        return "armour"
    if slot is SlotFamily.JEWELLERY:
        if present & CASTER_FAMILIES:
            return "caster_jewellery"
        if present & LIFE_RES_FAMILIES:
            return "life_res_jewellery"
        if present & {"strength", "dexterity", "intelligence", "all_attributes"}:
            return "attribute_jewellery"
        return "jewellery"
    return "other"


def derive_signature_identity(hypothesis: PriceCheckHypothesis) -> SignatureIdentity | None:
    league = str(hypothesis.league or "").strip()
    if not league:
        return None
    if hypothesis.slot_family in {SlotFamily.UNIQUE, SlotFamily.OTHER}:
        return None
    families = market_relevant_families(hypothesis)
    if not families:
        return None
    item_class = str(hypothesis.item_class or hypothesis.slot_family.value)
    return SignatureIdentity(
        league=league,
        item_class=item_class,
        base_family=derive_base_family(hypothesis),
        driver_family_set=families,
        slot_family=hypothesis.slot_family.value,
    )


def signature_age_band(signature: MarketSignature, *, now: float | None = None) -> SignatureAgeBand:
    stamp = float(signature.last_observed_at or 0.0)
    if stamp <= 0:
        return SignatureAgeBand.STALE
    age_days = max(0.0, (float(now if now is not None else time.time()) - stamp) / 86400.0)
    if age_days <= SIGNATURE_FRESH_DAYS:
        return SignatureAgeBand.FRESH
    if age_days <= SIGNATURE_AGING_DAYS:
        return SignatureAgeBand.AGING
    return SignatureAgeBand.STALE


def signature_compatible_with_auto(signature: MarketSignature, *, now: float | None = None) -> bool:
    if signature.maturity is not SignatureMaturity.MATURE:
        return False
    if signature.schema_version != SIGNATURE_SCHEMA_VERSION:
        return False
    if signature.vocabulary_version != QUERY_VOCABULARY_VERSION:
        return False
    if signature.registry_version != STAT_REGISTRY_VERSION:
        return False
    if signature_age_band(signature, now=now) is SignatureAgeBand.STALE:
        return False
    if not signature.preferred_selected_families:
        return False
    return True


def _compatible_match(preferred_mode: str, preferred_count_min: int | None, selected_n: int) -> tuple[MatchMode, int | None]:
    if preferred_mode == MatchMode.COUNT.value:
        if selected_n < 2:
            return MatchMode.ALL, None
        minimum = int(preferred_count_min or max(1, selected_n - 1))
        if minimum < 1 or minimum >= selected_n:
            return MatchMode.ALL, None
        return MatchMode.COUNT, minimum
    return MatchMode.ALL, None


def _drivers_for_families(
    hypothesis: PriceCheckHypothesis,
    families: Iterable[str],
) -> tuple[MarketPriceDriver, ...]:
    by_family: dict[str, MarketPriceDriver] = {}
    for row in hypothesis.available_drivers:
        if row.family in by_family:
            continue
        by_family[row.family] = row
    picked: list[MarketPriceDriver] = []
    for family in families:
        row = by_family.get(family)
        if row is None:
            continue
        if family in JUNK_FAMILIES:
            continue
        if get_family(family) is None and not row.equipment_key:
            continue
        picked.append(row)
    return tuple(picked)


def apply_mature_signature(
    hypothesis: PriceCheckHypothesis,
    signature: MarketSignature,
    *,
    now: float | None = None,
) -> PriceCheckHypothesis | None:
    if not signature_compatible_with_auto(signature, now=now):
        return None
    present = set(market_relevant_families(hypothesis))
    preferred = [family for family in signature.preferred_selected_families if family in present]
    if not preferred:
        return None
    selected = _drivers_for_families(hypothesis, preferred)
    if not selected:
        return None
    auto_selected = [row for row in hypothesis.selected_drivers]
    if len(selected) < 1 and auto_selected:
        selected = tuple(auto_selected[:1])
    mode, count_min = _compatible_match(signature.preferred_match_mode, signature.preferred_count_min, len(selected))
    applied = hypothesis_with_selection(
        hypothesis,
        selected,
        match_mode=mode,
        count_min=count_min,
        hypothesis_source=HypothesisSource.SIGNATURE,
    )
    return replace(
        applied,
        selection_origin="SIGNATURE",
        signature_id=signature.signature_id,
    )


def influence_provisional_ranking(
    hypothesis: PriceCheckHypothesis,
    signature: MarketSignature,
) -> PriceCheckHypothesis:
    """PROVISIONAL may reorder AUTO drivers. It must not drop core AUTO safeguards."""
    if signature.maturity is not SignatureMaturity.PROVISIONAL:
        return hypothesis
    preferred = list(signature.preferred_selected_families)
    selected = list(hypothesis.selected_drivers)
    if not selected or not preferred:
        return hypothesis
    ranked = sorted(
        selected,
        key=lambda row: (preferred.index(row.family) if row.family in preferred else 80, row.family),
    )
    if [row.driver_id for row in ranked] == [row.driver_id for row in selected]:
        return hypothesis
    return hypothesis_with_selection(
        hypothesis,
        ranked,
        match_mode=hypothesis.match_mode,
        count_min=hypothesis.count_min,
        hypothesis_source=hypothesis.hypothesis_source,
    )


def build_assisted_hypothesis(
    item_raw: str,
    *,
    league: str | None = None,
    store: Any | None = None,
    now: float | None = None,
) -> PriceCheckHypothesis:
    prior = build_auto_hypothesis(item_raw, league=league)
    prior = replace(prior, selection_origin="AUTO_PRIOR", signature_id="")
    if store is None:
        from poe2value.price_check.signature_store import shared_signature_store

        store = shared_signature_store()
    identity = derive_signature_identity(prior)
    store.metrics.signature_lookup += 1
    if identity is None:
        return prior
    signature = store.get(identity.signature_id)
    if signature is None:
        return prior
    store.metrics.signature_found += 1
    if signature_compatible_with_auto(signature, now=now):
        applied = apply_mature_signature(prior, signature, now=now)
        if applied is not None:
            store.metrics.signature_applied += 1
            return applied
    if signature.maturity is SignatureMaturity.PROVISIONAL:
        return influence_provisional_ranking(prior, signature)
    return prior


def _shape_key(hypothesis: PriceCheckHypothesis) -> tuple[tuple[str, ...], str, int | None]:
    families = tuple(row.family for row in hypothesis.selected_drivers)
    mode = hypothesis.match_mode.value
    return families, mode, hypothesis.count_min if mode == MatchMode.COUNT.value else None


def _floor_strategy(hypothesis: PriceCheckHypothesis) -> tuple[str, ...]:
    return tuple(f"{row.family}:{row.floor_policy}" for row in hypothesis.selected_drivers)


def _should_skip_training(result: PriceCheckResult, request: PriceCheckRequest) -> str | None:
    if request.league.status is LeagueStatus.UNKNOWN or not str(request.league.league or "").strip():
        return "league_unknown"
    live = result.live_search_state
    if live in {
        LiveSearchState.LIVE_SEARCH_BAD_REQUEST,
        LiveSearchState.LIVE_SEARCH_RATE_LIMITED,
        LiveSearchState.LIVE_SEARCH_NETWORK_ERROR,
        LiveSearchState.LIVE_SEARCH_AUTH_REQUIRED,
        LiveSearchState.LIVE_SEARCH_FORBIDDEN,
        LiveSearchState.LEAGUE_REQUIRED,
    }:
        return live.value if live is not None else "live_failure"
    http_status = getattr(result.diagnostics, "http_status", None) if result.diagnostics else None
    if http_status in {400, 429}:
        return f"http_{http_status}"
    if result.pending_hypothesis is not None:
        return "queued"
    hypothesis = result.hypothesis
    if hypothesis is None:
        return "missing_hypothesis"
    if hypothesis.slot_family in {SlotFamily.UNIQUE, SlotFamily.OTHER}:
        return "unsupported_class"
    body = build_trade2_search_body(build_search_query(request.item_raw, league=request.league.league, hypothesis=hypothesis))
    validation = validate_trade2_search_body(body)
    if not validation.ok:
        return "invalid_query"
    if validation.repaired:
        return "query_repair"
    for row in hypothesis.selected_drivers:
        if not row.trade_stat_ids and not row.equipment_key:
            return "missing_stat_ids"
        if row.trade_stat_ids and get_family(row.family) is None and not row.equipment_key:
            return "invalid_stat"
    return None


def qualify_training_event(
    result: PriceCheckResult,
    request: PriceCheckRequest,
) -> tuple[SignatureEvidenceSource, PriceCheckHypothesis, bool] | None:
    """Return (source, hypothesis_to_learn, independent) or None."""
    reason = _should_skip_training(result, request)
    if reason:
        logger.debug("signature train skipped: %s", reason)
        return None
    discovery = result.discovery if isinstance(result.discovery, dict) else {}
    winner = str((discovery.get("final") or {}).get("final_hypothesis") or result.estimate_state)
    stability = str(result.stability or "")
    if stability == HypothesisStability.SENSITIVE.value:
        return None
    if winner in {FinalHypothesis.NEEDS_REFINEMENT.value, "NEEDS REFINEMENT"}:
        return None
    if winner in {FinalHypothesis.BASE_ONLY.value, "BASE MARKET ESTIMATE"} or result.estimate_state == "BASE MARKET ESTIMATE":
        return None
    h1 = discovery.get("h1") if isinstance(discovery.get("h1"), dict) else None
    h2 = discovery.get("h2") if isinstance(discovery.get("h2"), dict) else None
    if winner == FinalHypothesis.H2_RECOVERY.value:
        learned = result.hypothesis
        if learned is None:
            return None
        if h2 and not h2.get("usable"):
            return None
        accepted = int((h2 or {}).get("accepted_count") or result.comparable_count or 0)
        if accepted < 3 or not result.estimate.has_currency_estimate:
            return None
        return SignatureEvidenceSource.AUTO_H2_RECOVERY, learned, True
    if winner != FinalHypothesis.H1.value and result.auto_adjusted:
        return None
    learned = result.hypothesis
    if learned is None:
        return None
    if h1 is not None and not h1.get("usable") and not result.estimate.has_currency_estimate:
        return None
    accepted = int((h1 or {}).get("accepted_count") or result.comparable_count or 0)
    if accepted < 3 or not result.estimate.has_currency_estimate:
        return None
    source_value = learned.hypothesis_source
    if source_value is HypothesisSource.USER_REFINED:
        return SignatureEvidenceSource.USER_REFINED_SUCCESS, learned, True
    if source_value is HypothesisSource.SIGNATURE:
        return SignatureEvidenceSource.AUTO_H1_SUCCESS, learned, False
    if source_value is HypothesisSource.AUTO_PRIOR:
        return SignatureEvidenceSource.AUTO_H1_SUCCESS, learned, True
    return None


def _refresh_maturity(signature: MarketSignature, *, now: float | None = None) -> MarketSignature:
    distinct = len(signature.independent_item_fingerprints)
    stale = signature_age_band(signature, now=now) is SignatureAgeBand.STALE
    versions_ok = (
        signature.schema_version == SIGNATURE_SCHEMA_VERSION
        and signature.vocabulary_version == QUERY_VOCABULARY_VERSION
        and signature.registry_version == STAT_REGISTRY_VERSION
    )
    if not versions_ok:
        return replace(signature, maturity=SignatureMaturity.DEGRADED)
    if signature.contradiction_count >= CONTRADICTION_DEGRADE_AT:
        return replace(signature, maturity=SignatureMaturity.DEGRADED)
    if stale and signature.maturity is SignatureMaturity.MATURE:
        return replace(signature, maturity=SignatureMaturity.DEGRADED)
    if signature.maturity is SignatureMaturity.DEGRADED:
        if (
            signature.contradiction_count == 0
            and distinct >= PROVISIONAL_DISTINCT_ITEMS
            and signature.independent_weight >= PROVISIONAL_DISTINCT_ITEMS
            and not stale
        ):
            if distinct >= MATURE_DISTINCT_ITEMS and signature.independent_weight >= MATURE_DISTINCT_ITEMS:
                return replace(signature, maturity=SignatureMaturity.MATURE)
            return replace(signature, maturity=SignatureMaturity.PROVISIONAL)
        return signature
    if (
        distinct >= MATURE_DISTINCT_ITEMS
        and signature.independent_weight >= MATURE_DISTINCT_ITEMS
        and signature.contradiction_count == 0
        and not stale
    ):
        return replace(signature, maturity=SignatureMaturity.MATURE)
    if distinct >= PROVISIONAL_DISTINCT_ITEMS and signature.independent_weight >= PROVISIONAL_DISTINCT_ITEMS:
        return replace(signature, maturity=SignatureMaturity.PROVISIONAL)
    return replace(signature, maturity=SignatureMaturity.CANDIDATE)


def record_signature_evidence(
    store: Any,
    *,
    request: PriceCheckRequest,
    result: PriceCheckResult,
    now: float | None = None,
    synthetic: bool = False,
) -> MarketSignature | None:
    if store is None:
        return None
    if synthetic and getattr(store, "blocks_synthetic_persist", lambda: False)():
        return None
    qualified = qualify_training_event(result, request)
    if qualified is None:
        return None
    source, learned, independent = qualified
    identity = derive_signature_identity(learned)
    if identity is None:
        identity = derive_signature_identity(
            result.original_hypothesis or learned
        )
    if identity is None:
        return None
    item_fp = request.content_hash or RawItemInput.from_text(request.item_raw).content_hash
    stamp = float(now if now is not None else time.time())
    existing = store.get(identity.signature_id)
    shape = _shape_key(learned)
    weight = {
        SignatureEvidenceSource.AUTO_H2_RECOVERY: H2_RECOVERY_WEIGHT,
        SignatureEvidenceSource.USER_REFINED_SUCCESS: USER_REFINED_WEIGHT,
        SignatureEvidenceSource.AUTO_H1_SUCCESS: AUTO_H1_WEIGHT,
    }[source]
    if existing is None:
        if not independent:
            return None
        signature = MarketSignature(
            signature_id=identity.signature_id,
            league=identity.league,
            item_class=identity.item_class,
            base_family=identity.base_family,
            slot_family=identity.slot_family,
            driver_family_set=identity.driver_family_set,
            preferred_selected_families=shape[0],
            preferred_selected_driver_ids=tuple(row.driver_id for row in learned.selected_drivers),
            preferred_match_mode=shape[1],
            preferred_count_min=shape[2],
            floor_strategy=_floor_strategy(learned),
            evidence_count=1,
            successful_use_count=1,
            recovery_count=1 if source is SignatureEvidenceSource.AUTO_H2_RECOVERY else 0,
            price_sample_count=int(result.comparable_count or 0),
            first_observed_at=stamp,
            last_observed_at=stamp,
            maturity=SignatureMaturity.CANDIDATE,
            source=source,
            independent_item_fingerprints=(item_fp,),
            independent_weight=weight,
        )
        store.put(signature, synthetic=synthetic)
        store.metrics.evidence_added += 1
        return signature

    seen = set(existing.independent_item_fingerprints)
    existing_shape = (
        existing.preferred_selected_families,
        existing.preferred_match_mode,
        existing.preferred_count_min if existing.preferred_match_mode == MatchMode.COUNT.value else None,
    )
    contradicts = existing_shape != shape
    if item_fp in seen and not contradicts:
        return existing
    if not independent:
        updated = replace(
            existing,
            successful_use_count=existing.successful_use_count + 1,
            self_confirmation_count=existing.self_confirmation_count + 1,
            last_observed_at=stamp,
        )
        store.put(updated, synthetic=synthetic)
        return updated

    if contradicts:
        updated = replace(
            existing,
            contradiction_count=existing.contradiction_count + 1,
            failure_count=existing.failure_count + 1,
            last_observed_at=stamp,
        )
        store.metrics.contradiction_added += 1
        refreshed = _refresh_maturity(updated, now=stamp)
        if refreshed.maturity is SignatureMaturity.DEGRADED and existing.maturity is not SignatureMaturity.DEGRADED:
            store.metrics.signature_degraded += 1
        store.put(refreshed, synthetic=synthetic)
        return refreshed

    fingerprints = existing.independent_item_fingerprints + (item_fp,)
    updated = replace(
        existing,
        evidence_count=existing.evidence_count + 1,
        successful_use_count=existing.successful_use_count + 1,
        recovery_count=existing.recovery_count + (1 if source is SignatureEvidenceSource.AUTO_H2_RECOVERY else 0),
        price_sample_count=existing.price_sample_count + int(result.comparable_count or 0),
        last_observed_at=stamp,
        independent_item_fingerprints=fingerprints,
        independent_weight=existing.independent_weight + weight,
        source=source if source is SignatureEvidenceSource.AUTO_H2_RECOVERY else existing.source,
        contradiction_count=0 if existing.maturity is SignatureMaturity.DEGRADED else existing.contradiction_count,
    )
    if existing.maturity is SignatureMaturity.DEGRADED:
        updated = replace(updated, contradiction_count=0)
    refreshed = _refresh_maturity(updated, now=stamp)
    store.metrics.evidence_added += 1
    store.put(refreshed, synthetic=synthetic)
    return refreshed


def annotate_discovery_payload(
    payload: dict[str, Any] | None,
    *,
    hypothesis: PriceCheckHypothesis | None,
    store: Any | None,
    discovery_avoided: bool = False,
) -> dict[str, Any]:
    data = dict(payload or {})
    signature_applied = bool(hypothesis is not None and hypothesis.hypothesis_source is HypothesisSource.SIGNATURE)
    maturity = ""
    coverage = 0.0
    if store is not None and hypothesis is not None and hypothesis.signature_id:
        found = store.get(hypothesis.signature_id)
        if found is not None:
            maturity = found.maturity.value
            present = set(market_relevant_families(hypothesis))
            preferred = set(found.preferred_selected_families)
            coverage = (len(preferred & present) / len(preferred)) if preferred else 0.0
    metrics = store.metrics.snapshot() if store is not None else {}
    data["signature"] = {
        "applied": signature_applied,
        "maturity": maturity,
        "driver_coverage": coverage,
        "origin": hypothesis.selection_origin if hypothesis is not None else "",
        "signature_id": hypothesis.signature_id if hypothesis is not None else "",
        "discovery_avoided": discovery_avoided,
        "metrics": metrics,
    }
    return data
