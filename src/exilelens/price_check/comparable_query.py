from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from exilelens.price_check.market_plan import CompiledTradeQuery

import re
from dataclasses import dataclass
from enum import Enum

from exilelens.items.metadata import parse_lightweight_metadata
from exilelens.items.raw_input import RawItemInput
from exilelens.price_check.comparable_features import (
    ComparableFeature,
    FAMILY_MATCH_THRESHOLD,
    ModImportance,
    best_feature_score,
    build_features,
    parse_feature_from_mod,
)
from exilelens.price_check.feature_fallback import (
    EconomicIdentity,
    IdentitySource,
    select_economic_identity,
)
from exilelens.price_check.market_drivers import PriceCheckHypothesis, build_auto_hypothesis

_MOD_LINE_RE = re.compile(
    r"^(\+?\d+%?|\d+%)\s+(.+)$|^(Gain|Adds|Grants|Regenerate)\s+.+$|^.+(increased|reduced|to)\s+.+$",
    re.I,
)


class RelaxationTier(int, Enum):
    STRICT = 0
    RELAXED_MODS = 1
    PSEUDO_EQUIV = 2
    DROP_LOWEST_HIGH = 3
    BASE_AND_RARITY = 4
    BASE_ONLY = 5
    ULTRA_LOOSE = 6


@dataclass(frozen=True)
class ModSignature:
    text: str
    normalized: str
    importance: ModImportance
    pseudo: str | None = None
    feature: ComparableFeature | None = None

    def to_dict(self) -> dict[str, str]:
        return {
            "text": self.text,
            "normalized": self.normalized,
            "importance": self.importance.value,
            "pseudo": self.pseudo or "",
        }


@dataclass(frozen=True)
class ComparableSearchQuery:
    base_type: str
    rarity: str | None
    item_name: str | None
    mods: tuple[ModSignature, ...] = ()
    features: tuple[ComparableFeature, ...] = ()
    relaxation_tier: RelaxationTier = RelaxationTier.STRICT
    league: str | None = None
    item_raw: str = ""
    hypothesis: PriceCheckHypothesis | None = None
    compiled_query: CompiledTradeQuery | None = None

    def to_dict(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "base_type": self.base_type,
            "rarity": self.rarity,
            "item_name": self.item_name,
            "mods": [row.to_dict() for row in self.mods],
            "features": [row.to_dict() for row in self.features],
            "relaxation_tier": int(self.relaxation_tier),
            "league": self.league,
        }
        if self.hypothesis is not None:
            payload["hypothesis"] = self.hypothesis.to_dict()
        return payload

    @property
    def economic_identity(self) -> EconomicIdentity:
        """The features this query searches on, and where they came from.

        MARKET-02B: when a MarketPriceDriver hypothesis is attached, that set is the
        identity. Empty selected drivers remain BASE_ONLY (B13 honesty).
        """
        if self.compiled_query is not None:
            material = any(not row.omitted_from_query for row in self.compiled_query.coverage.entries
                           if row.economic_role.value in {"ANCHOR", "FLEXIBLE"})
            return EconomicIdentity(features=(), source=IdentitySource.PRIMARY if material else IdentitySource.BASE_ONLY,
                                    reason="compiled Trade search")
        if self.hypothesis is not None:
            selected = self.hypothesis.selected_drivers
            if not selected:
                return EconomicIdentity(
                    features=(),
                    source=IdentitySource.BASE_ONLY,
                    reason="no market-relevant affix to search on",
                )
            families = {row.family for row in selected}
            features = tuple(
                row
                for row in self.features
                if row.family in families or (row.pseudo_family or "") in families
            )
            return EconomicIdentity(
                features=features or tuple(self.features[: len(selected)]),
                source=IdentitySource.PRIMARY,
                reason=f"{len(selected)} assisted market driver{'s' if len(selected) != 1 else ''}",
            )
        return select_economic_identity(self.features)

    @property
    def is_base_only(self) -> bool:
        """No affix could carry the query — the estimate is a base-type price."""
        return self.economic_identity.is_base_only

    def identity_features(self) -> tuple[ComparableFeature, ...]:
        return self.economic_identity.features

    def matched_summary(self, limit: int = 3) -> str:
        """The economic features the query actually matched on, for the overlay."""
        if self.compiled_query is not None:
            return self.compiled_query.summary
        if self.hypothesis is not None:
            labels: list[str] = []
            for driver in self.hypothesis.selected_drivers:
                label = driver.label
                if label and label not in labels:
                    labels.append(label)
            return " + ".join(labels[:limit])
        labels: list[str] = []
        for feature in self.identity_features():
            label = str(feature.pseudo_family or feature.family or "").replace("_", " ").strip()
            if label and label not in labels:
                labels.append(label)
        return " + ".join(labels[:limit])

    @property
    def search_basis(self) -> str:
        if self.compiled_query is not None:
            return self.compiled_query.summary

        if self.hypothesis is not None:
            return self.hypothesis.search_basis

        identity = self.economic_identity
        if identity.is_base_only:
            # MARKET-01B13: say it in the words §10 asks for, so a base estimate cannot
            # be mistaken for a valuation of the item's mods.
            basis = f"{self.base_type} · base only" if self.base_type else "base only"
            if self.relaxation_tier > RelaxationTier.STRICT:
                basis = f"{basis}, tier {int(self.relaxation_tier)}"
            return basis

        parts = [self.base_type] if self.base_type else []
        for feature in identity.features:
            label = str(feature.pseudo_family or feature.family).replace("_", " ")
            parts.append(f"{feature.value:g} {label}")
        if not parts and self.mods:
            for mod in self.mods:
                if mod.importance in {ModImportance.CRITICAL, ModImportance.HIGH}:
                    parts.append(mod.pseudo or mod.text)
        if self.relaxation_tier > RelaxationTier.STRICT:
            parts.append(f"tier {int(self.relaxation_tier)}")
        return ", ".join(parts)


def _normalize_mod_text(line: str) -> str:
    cleaned = re.sub(r"\d+", "#", line.lower().strip())
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned


def _pseudo_mod(feature: ComparableFeature | None) -> str | None:
    if feature is None:
        return None
    if feature.family == "cast_speed":
        return "Cast Speed"
    if feature.family == "lightning_damage":
        return "Lightning Damage"
    if feature.pseudo_family:
        return feature.pseudo_family.replace("_", " ").title()
    return feature.family.replace("_", " ").title()


def _extract_mod_lines(item_raw: str) -> list[str]:
    lines = [line.strip() for line in item_raw.replace("\r\n", "\n").split("\n") if line.strip()]
    mods: list[str] = []
    for line in lines:
        if line.startswith(
            ("Rarity:", "Item Class:", "--------", "Requirements:", "LevelReq:", "Implicits:", "Quality:")
        ):
            continue
        if line == "__UNNAMED__":
            continue
        if _MOD_LINE_RE.match(line) or line.startswith("+") or "increased" in line.lower():
            mods.append(line)
    return mods


def build_mod_signatures(item_raw: str, *, category: str | None = None) -> tuple[ModSignature, ...]:
    features = build_features(item_raw, category=category)
    signatures: list[ModSignature] = []
    for line in _extract_mod_lines(item_raw):
        feature = parse_feature_from_mod(line, category=category)
        signatures.append(
            ModSignature(
                text=line,
                normalized=_normalize_mod_text(line),
                importance=feature.importance if feature else ModImportance.LOW,
                pseudo=_pseudo_mod(feature),
                feature=feature,
            )
        )
    if signatures and not features:
        return tuple(signatures)
    if features and len(signatures) != len(features):
        return tuple(
            ModSignature(
                text=feature.source_text,
                normalized=_normalize_mod_text(feature.source_text),
                importance=feature.importance,
                pseudo=_pseudo_mod(feature),
                feature=feature,
            )
            for feature in features
        )
    return tuple(signatures)


def build_search_query(
    item_raw: str,
    *,
    relaxation_tier: RelaxationTier = RelaxationTier.STRICT,
    league: str | None = None,
    hypothesis: PriceCheckHypothesis | None = None,
) -> ComparableSearchQuery:
    raw = RawItemInput.from_text(item_raw)
    meta = parse_lightweight_metadata(raw)
    features = build_features(item_raw, category=meta.category)
    resolved = hypothesis if hypothesis is not None else build_auto_hypothesis(item_raw, league=league)
    return ComparableSearchQuery(
        base_type=str(meta.base_type or ""),
        rarity=meta.rarity,
        item_name=meta.name,
        mods=build_mod_signatures(item_raw, category=meta.category),
        features=features,
        relaxation_tier=relaxation_tier,
        league=league,
        item_raw=item_raw,
        hypothesis=resolved,
    )
    raw = RawItemInput.from_text(item_raw)
    meta = parse_lightweight_metadata(raw)
    features = build_features(item_raw, category=meta.category)
    hypothesis = build_auto_hypothesis(item_raw, league=league)
    return ComparableSearchQuery(
        base_type=str(meta.base_type or ""),
        rarity=meta.rarity,
        item_name=meta.name,
        mods=build_mod_signatures(item_raw, category=meta.category),
        features=features,
        relaxation_tier=relaxation_tier,
        league=league,
        item_raw=item_raw,
        hypothesis=hypothesis,
    )


def with_relaxation(query: ComparableSearchQuery, tier: RelaxationTier) -> ComparableSearchQuery:
    return ComparableSearchQuery(
        base_type=query.base_type,
        rarity=query.rarity,
        item_name=query.item_name,
        mods=query.mods,
        features=query.features,
        relaxation_tier=tier,
        league=query.league,
        item_raw=query.item_raw,
        hypothesis=query.hypothesis,
        compiled_query=query.compiled_query,
    )


def required_important_matches(tier: RelaxationTier, important_count: int) -> int:
    if important_count <= 0:
        return 0
    if tier >= RelaxationTier.BASE_AND_RARITY:
        return 0
    if tier == RelaxationTier.STRICT:
        return important_count if important_count <= 2 else max(1, important_count - 1)
    if tier == RelaxationTier.RELAXED_MODS:
        return max(1, int(important_count * 0.6))
    if tier in {RelaxationTier.PSEUDO_EQUIV, RelaxationTier.DROP_LOWEST_HIGH}:
        return max(1, int(important_count * 0.5))
    return 1


def listing_similarity_score(item_raw: str, query: ComparableSearchQuery) -> float:
    listing_features = build_features(item_raw, category=query.base_type)
    # MARKET-01B13: score against the features the query actually searched on. For an
    # item with high-importance mods this is the same set as before; for a fallback item
    # it is the difference between real precision and "everything matches perfectly".
    important = query.identity_features()
    if not important:
        return 1.0

    scores = [best_feature_score(row, listing_features) for row in important]
    avg = sum(scores) / len(scores)
    missing_penalty = sum(0.08 for score in scores if score < 0.25)
    listing_medium = sum(1 for row in listing_features if row.importance == ModImportance.MEDIUM)
    bonus = min(0.05, 0.01 * listing_medium)
    return max(0.0, min(1.0, avg - missing_penalty + bonus))


def _legacy_mod_match_score(query_mod: ModSignature, listing_mods: tuple[ModSignature, ...]) -> float:
    if query_mod.feature is not None:
        listing_features = tuple(row.feature for row in listing_mods if row.feature is not None)
        if listing_features:
            return best_feature_score(query_mod.feature, listing_features)
    for listing_mod in listing_mods:
        if query_mod.normalized == listing_mod.normalized:
            return 1.0
        if query_mod.pseudo and query_mod.pseudo == listing_mod.pseudo:
            return FAMILY_MATCH_THRESHOLD
    return 0.0


def listing_matches_query(item_raw: str, query: ComparableSearchQuery) -> bool:
    raw = RawItemInput.from_text(item_raw)
    meta = parse_lightweight_metadata(raw)
    if query.base_type and str(meta.base_type or "").lower() != query.base_type.lower():
        return False

    tier = query.relaxation_tier
    if tier >= RelaxationTier.ULTRA_LOOSE:
        return bool(query.base_type)

    if tier >= RelaxationTier.BASE_ONLY:
        return bool(query.base_type)

    if tier >= RelaxationTier.BASE_AND_RARITY:
        if query.rarity and str(meta.rarity or "").upper() != query.rarity.upper():
            return False
        return True

    score = listing_similarity_score(item_raw, query)
    important = query.identity_features()
    if not important:
        return True
    required = required_important_matches(tier, len(important))
    if required <= 0:
        return score >= FAMILY_MATCH_THRESHOLD * 0.5
    matched = sum(
        1
        for row in important
        if best_feature_score(row, build_features(item_raw, category=meta.category)) >= FAMILY_MATCH_THRESHOLD
    )
    return matched >= required and score >= (FAMILY_MATCH_THRESHOLD * required / len(important))
