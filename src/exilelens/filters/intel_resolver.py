"""Build-aware slot resolution (FILTER-08B): production Build Intelligence -> filter slot priorities.

``IntelContext`` is the single object handed to the rule generator. It never reaches PoB or the network:
everything is derived from a ``BuildNeedsSnapshot`` (stored or freshly projected from a production analysis)
plus the pinned PoB2 base/affix snapshots.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from functools import cached_property

from exilelens.filters.build_needs import BuildNeedsSnapshot
from exilelens.filters.opportunity import (ROLE_BY_CLASS, BuildOpportunityModel, EvidenceKind,
                                           global_quality_tier)
from exilelens.filters.priorities import (EXTENDED_OFFHAND_CLASSES, EXTENDED_WEAPON_CLASSES, SLOT_EQUIPMENT_CLASSES,
                                           SlotPriorityResolver)
from exilelens.filters.profiles import BaseTier, BuildFingerprint, ProductSlot, SlotPriority
from exilelens.filters.verified_bases import load_base_properties, native_class

_WEAPON_SLOTS = (ProductSlot.WEAPON_1, ProductSlot.WEAPON_2)
_OFFHAND_SLOTS = (ProductSlot.OFFHAND_1, ProductSlot.OFFHAND_2)


@dataclass(frozen=True)
class IntelContext:
    needs: BuildNeedsSnapshot
    widen: bool = False      # set by data-drift handling: nothing may narrow on the strength of possibly stale data

    @cached_property
    def model(self) -> BuildOpportunityModel:
        return BuildOpportunityModel(self.needs, widen=self.widen)

    @cached_property
    def global_tiers(self) -> dict[str, dict[str, BaseTier]]:
        """Build-independent base quality for every supported class (trade and crafting rules)."""
        tiers: dict[str, dict[str, BaseTier]] = {}
        for base in load_base_properties():
            native = native_class(base)
            if native is None or native not in ROLE_BY_CLASS:
                continue
            tier, _ = global_quality_tier(base, native, self.model.equipped_bases)
            if tier != BaseTier.IGNORE:
                tiers.setdefault(native, {})[base] = tier
        return tiers


def with_equipped(needs: BuildNeedsSnapshot, fingerprint: BuildFingerprint) -> BuildNeedsSnapshot:
    """Fill observed gear from the FILTER fingerprint when the snapshot did not carry it."""
    if needs.equipped:
        return needs
    equipped = {slot.value: item.base_type for slot, item in fingerprint.equipped.items() if item.base_type}
    return replace(needs, equipped=equipped)


class BuildIntelSlotPriorityResolver(SlotPriorityResolver):
    """SlotPriorityResolver whose classes and tiers come from measured/verified evidence first."""

    def __init__(self, fingerprint: BuildFingerprint, needs: BuildNeedsSnapshot, *, widen: bool = False):
        super().__init__(fingerprint)
        self.intel = IntelContext(with_equipped(needs, fingerprint), widen=widen)
        self._weapon_cache: dict[ProductSlot, tuple] = {}

    def _classes(self, slot: ProductSlot) -> tuple[list[str], tuple, object]:
        model = self.intel.model
        supported = SLOT_EQUIPMENT_CLASSES.get(slot, [])
        if slot in _WEAPON_SLOTS:
            supported = [*supported, *[c for c in EXTENDED_WEAPON_CLASSES if c not in supported]]
            classes, reasons, coverage = model.weapon_classes(supported)
            return [c for c in classes if c in supported], tuple(reasons), coverage
        if slot in _OFFHAND_SLOTS:
            supported = [*supported, *[c for c in EXTENDED_OFFHAND_CLASSES if c not in supported]]
            classes, reasons = model.offhand_classes(supported)
            return classes, tuple(reasons), None
        return list(supported), (), None

    def resolve_slot(self, slot: ProductSlot) -> SlotPriority:
        base = super().resolve_slot(slot)
        classes, reasons, coverage = self._classes(slot)
        decisions = self.intel.model.resolve_classes(classes)
        base_tiers: dict[str, BaseTier] = {}
        quality: dict[str, BaseTier] = {}
        for name, decision in decisions.items():
            tier = decision.build_tier
            # (FILTER-08C) The legacy "known defence layer drops T4 bases" filter is retired from this path: it keyed off a
            # layer inferred from gear totals (almost always a hybrid) and silently narrowed even weapon classes.
            if tier == BaseTier.IGNORE:
                continue
            base_tiers[name] = tier
            quality[name] = decision.gate_tier
        return replace(base, base_tiers=base_tiers, quality_tiers=quality,
                       decisions={n: decisions[n] for n in base_tiers}, class_reasons=reasons, coverage=coverage)
