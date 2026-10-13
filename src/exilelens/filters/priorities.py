"""Slot Priority Resolution and Base Tier Database for FILTER-01.

This module contains the static base tier classifications and the logic
to resolve per-slot equipment priorities from a build fingerprint.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, FrozenSet, List, Optional, Set
from collections import defaultdict

from exilelens.filters.profiles import (
    BaseTier,
    DefenseLayer,
    ProductSlot,
    SlotPriority,
    EquippedItemSummary,
    BuildFingerprint,
)
from exilelens.filters.verified_bases import audit_priorities


# ============================================================================
# BASE TIER DATABASE
# ============================================================================
# Tier classifications per equipment class.
# T1 = Best-in-slot / meta endgame bases
# T2 = Strong alternatives
# T3 = Viable budget / leveling bases
# T4 = Niche / early game only
# IGNORE = Never show (vendor trash tier)

def _load_declared_base_tiers():
    import json
    from pathlib import Path
    data = json.loads((Path(__file__).parent / "data" / "base_tiers.json").read_text(encoding="utf-8"))
    return {cls: {base: BaseTier(tier) for base, tier in bases.items()} for cls, bases in data.items()}


LEGACY_BASE_TIERS: Dict[str, Dict[str, BaseTier]] = _load_declared_base_tiers()

# The declared tier table is data; every name/class pair is audited against the native registry.
BASE_TIERS, CATALOG_AUDIT = audit_priorities(LEGACY_BASE_TIERS)
# FILTER-08D: a curated label filed under the wrong NATIVE class (e.g. a buckler under "Shields") would serialise a Class condition
# the game never matches; such entries are retired from the table and reported by the item-family audit.
from exilelens.filters.verified_bases import native_class as _native_class  # noqa: E402

RETIRED_MISFILED_TIERS = {f"{c}:{b}": t.value for c, d in BASE_TIERS.items() for b, t in d.items() if _native_class(b) != c}
BASE_TIERS = {c: {b: t for b, t in d.items() if _native_class(b) == c} for c, d in BASE_TIERS.items()}


# ============================================================================
# SKILL -> WEAPON CLASS MAPPING
# ============================================================================

SKILL_WEAPON_CLASSES: Dict[str, List[str]] = {
    # Bow skills
    "Lightning Arrow": ["Bows", "Quivers"],
    "Tornado Shot": ["Bows", "Quivers"],
    "Rain of Arrows": ["Bows", "Quivers"],
    "Barrage": ["Bows", "Quivers"],
    "Ice Shot": ["Bows", "Quivers"],
    "Toxic Rain": ["Bows", "Quivers"],
    "Siege Ballista": ["Bows", "Quivers"],

    # Crossbow skills (if any distinct)
    "Snipe": ["Crossbows", "Quivers"],

    # Wand skills (spell caster)
    "Spark": ["Wands", "Sceptres", "Staves"],
    "Arc": ["Wands", "Sceptres", "Staves"],
    "Ball Lightning": ["Wands", "Sceptres", "Staves"],
    "Fireball": ["Wands", "Sceptres", "Staves"],
    "Frostbolt": ["Wands", "Sceptres"],
    "Glacial Cascade": ["Wands", "Sceptres"],
    "Sigil of Power": ["Wands", "Sceptres"],
    "Hexblast": ["Wands", "Sceptres"],
    "Incinerate": ["Wands", "Sceptres"],
    "Flameblast": ["Wands", "Sceptres"],
    "Detonate Dead": ["Wands", "Sceptres"],
    "Unearth": ["Wands", "Sceptres"],
    "Volatile Dead": ["Wands", "Sceptres"],
    "Lightning Warp": ["Wands", "Sceptres"],

    # In PoE2: Quarterstaves are Dex/Int martial weapons
    # Melee skills use Quarterstaves and Two Hand Maces
    "Earthquake": ["Quarterstaves", "Two Hand Maces"],
    "Sunder": ["Quarterstaves", "Two Hand Maces"],
    "Shield Charge": ["Quarterstaves", "Two Hand Maces", "Shields"],
    "Leap Slam": ["Quarterstaves", "Two Hand Maces"],

    # Melee attack skills
    "Dual Strike": ["One Hand Maces", "Swords", "Axes"],
    "Earthquake": ["Two Hand Maces", "Quarterstaves"],
    "Sunder": ["Two Hand Maces", "Quarterstaves"],
    "Shield Charge": ["One Hand Maces", "Swords", "Axes", "Shields"],
    "Leap Slam": ["One Hand Maces", "Axes", "Two Hand Maces", "Quarterstaves"],
    "Power Siphon": ["Wands", "Sceptres"],
    "Barrage": ["Bows", "Crossbows"],

    # Minion skills (generic weapon)
    "Raise Zombie": ["Any"],

}

# Default fallback for unknown skills
DEFAULT_WEAPON_CLASSES = [
    "Wands", "Sceptres", "Staves", "Quarterstaves",
    "One Hand Maces", "Two Hand Maces",
    "Bows", "Crossbows", "Spears",
    "Shields", "Foci", "Quivers",
]

# FILTER-08C: weapon families PoB2 data carries that the legacy slot table omitted. Used only by the build-aware
# (intel) path, where they widen the broad fallback and are verified candidates when a skill requires them.
EXTENDED_WEAPON_CLASSES = [
    "Flails", "Talismans", "Claws", "Daggers", "One Hand Axes", "Two Hand Axes",
    "One Hand Swords", "Two Hand Swords",
]
EXTENDED_OFFHAND_CLASSES = ["Bucklers"]


# ============================================================================
# DEFENSE LAYER -> BASE TIER FILTERING
# ============================================================================

# Full equipment class list for completeness
_ALL_EQUIPMENT_CLASSES = [
    "Body Armours", "Helmets", "Gloves", "Boots", "Belts", "Amulets", "Rings",
    "Wands", "Sceptres", "Staves", "Quarterstaves", "One Hand Maces", "Two Hand Maces",
    "Bows", "Crossbows", "Spears", "Shields", "Foci", "Quivers",
    "One Hand Swords", "Two Hand Swords", "Axes", "Daggers", "Claws",
]

# Build full filter for each defense layer
def _build_full_filter(allowed_tiers: Set[BaseTier]) -> Dict[str, Set[BaseTier]]:
    """Build filter dict with all equipment classes for given allowed tiers."""
    return {eq_class: allowed_tiers for eq_class in _ALL_EQUIPMENT_CLASSES}

# Base tier sets per defense philosophy
_TIER_SETS = {
    DefenseLayer.ENERGY_SHIELD: {BaseTier.T1, BaseTier.T2, BaseTier.T3},
    DefenseLayer.ARMOUR: {BaseTier.T1, BaseTier.T2, BaseTier.T3},
    DefenseLayer.EVASION: {BaseTier.T1, BaseTier.T2, BaseTier.T3},
    DefenseLayer.HYBRID_AR_ES: {BaseTier.T1, BaseTier.T2, BaseTier.T3},
    DefenseLayer.HYBRID_EV_ES: {BaseTier.T1, BaseTier.T2, BaseTier.T3},
    DefenseLayer.HYBRID_AR_EV: {BaseTier.T1, BaseTier.T2, BaseTier.T3},
    DefenseLayer.HYBRID_AR_EV_ES: {BaseTier.T1, BaseTier.T2, BaseTier.T3},
    DefenseLayer.WARD: {BaseTier.T1, BaseTier.T2},
    DefenseLayer.UNKNOWN: {BaseTier.T1, BaseTier.T2, BaseTier.T3, BaseTier.T4},
}

# Build the filter dict programmatically
DEFENSE_LAYER_BASE_FILTER: Dict[DefenseLayer, Dict[str, Set[BaseTier]]] = {
    layer: _build_full_filter(tiers) for layer, tiers in _TIER_SETS.items()
}


# ============================================================================
# SLOT -> EQUIPMENT CLASS MAPPING
# ============================================================================

SLOT_EQUIPMENT_CLASSES: Dict[ProductSlot, List[str]] = {
    ProductSlot.HELMET: ["Helmets"],
    ProductSlot.BODY_ARMOUR: ["Body Armours"],
    ProductSlot.GLOVES: ["Gloves"],
    ProductSlot.BOOTS: ["Boots"],
    ProductSlot.BELT: ["Belts"],
    ProductSlot.AMULET: ["Amulets"],
    ProductSlot.RING_1: ["Rings"],
    ProductSlot.RING_2: ["Rings"],
    ProductSlot.WEAPON_1: ["One Hand Maces", "Sceptres", "Wands", "Staves", "Quarterstaves",
                            "Two Hand Maces", "Bows", "Crossbows", "Spears"],
    ProductSlot.WEAPON_2: ["One Hand Maces", "Sceptres", "Wands", "Staves", "Quarterstaves",
                            "Two Hand Maces", "Bows", "Crossbows", "Spears"],
    ProductSlot.OFFHAND_1: ["Shields", "Foci", "Quivers"],
    ProductSlot.OFFHAND_2: ["Shields", "Foci", "Quivers"],
}


# ============================================================================
# DEFENSIVE FLOORS PER SLOT PER DEFENSE LAYER
# ============================================================================

DEFENSIVE_FLOORS: Dict[DefenseLayer, Dict[ProductSlot, Dict[str, float]]] = {
    DefenseLayer.ENERGY_SHIELD: {
        ProductSlot.HELMET: {"BaseEnergyShield": 120},
        ProductSlot.BODY_ARMOUR: {"BaseEnergyShield": 200},
        ProductSlot.GLOVES: {"BaseEnergyShield": 50},
        ProductSlot.BOOTS: {"BaseEnergyShield": 40},
        ProductSlot.OFFHAND_1: {"BaseEnergyShield": 80},
    },
    DefenseLayer.ARMOUR: {
        ProductSlot.HELMET: {"BaseArmour": 300},
        ProductSlot.BODY_ARMOUR: {"BaseArmour": 600},
        ProductSlot.GLOVES: {"BaseArmour": 150},
        ProductSlot.BOOTS: {"BaseArmour": 120},
        ProductSlot.OFFHAND_1: {"BaseArmour": 400},
    },
    DefenseLayer.EVASION: {
        ProductSlot.HELMET: {"BaseEvasion": 300},
        ProductSlot.BODY_ARMOUR: {"BaseEvasion": 600},
        ProductSlot.GLOVES: {"BaseEvasion": 150},
        ProductSlot.BOOTS: {"BaseEvasion": 120},
        ProductSlot.OFFHAND_1: {"BaseEvasion": 400},
    },
    DefenseLayer.HYBRID_AR_ES: {
        ProductSlot.HELMET: {"BaseArmour": 150, "BaseEnergyShield": 80},
        ProductSlot.BODY_ARMOUR: {"BaseArmour": 300, "BaseEnergyShield": 150},
        ProductSlot.GLOVES: {"BaseArmour": 80, "BaseEnergyShield": 40},
        ProductSlot.BOOTS: {"BaseArmour": 60, "BaseEnergyShield": 30},
        ProductSlot.OFFHAND_1: {"BaseArmour": 200, "BaseEnergyShield": 80},
    },
    DefenseLayer.HYBRID_EV_ES: {
        ProductSlot.HELMET: {"BaseEvasion": 150, "BaseEnergyShield": 80},
        ProductSlot.BODY_ARMOUR: {"BaseEvasion": 300, "BaseEnergyShield": 150},
        ProductSlot.GLOVES: {"BaseEvasion": 80, "BaseEnergyShield": 40},
        ProductSlot.BOOTS: {"BaseEvasion": 60, "BaseEnergyShield": 30},
        ProductSlot.OFFHAND_1: {"BaseEvasion": 200, "BaseEnergyShield": 80},
    },
    DefenseLayer.HYBRID_AR_EV: {
        ProductSlot.HELMET: {"BaseArmour": 150, "BaseEvasion": 150},
        ProductSlot.BODY_ARMOUR: {"BaseArmour": 300, "BaseEvasion": 300},
        ProductSlot.GLOVES: {"BaseArmour": 80, "BaseEvasion": 80},
        ProductSlot.BOOTS: {"BaseArmour": 60, "BaseEvasion": 60},
        ProductSlot.OFFHAND_1: {"BaseArmour": 200, "BaseEvasion": 200},
    },
    DefenseLayer.HYBRID_AR_EV_ES: {
        ProductSlot.HELMET: {"BaseArmour": 100, "BaseEvasion": 100, "BaseEnergyShield": 60},
        ProductSlot.BODY_ARMOUR: {"BaseArmour": 200, "BaseEvasion": 200, "BaseEnergyShield": 100},
        ProductSlot.GLOVES: {"BaseArmour": 50, "BaseEvasion": 50, "BaseEnergyShield": 30},
        ProductSlot.BOOTS: {"BaseArmour": 40, "BaseEvasion": 40, "BaseEnergyShield": 20},
        ProductSlot.OFFHAND_1: {"BaseArmour": 150, "BaseEvasion": 150, "BaseEnergyShield": 60},
    },
    DefenseLayer.UNKNOWN: {},
}


# ============================================================================
# PRIORITY RESOLVER
# ============================================================================

class SlotPriorityResolver:
    """Resolves per-slot equipment priorities from build fingerprint."""

    def __init__(self, fingerprint: BuildFingerprint):
        self.fingerprint = fingerprint
        self.defense_layer = fingerprint.defense_layer
        self.main_skill = fingerprint.main_skill
        self.equipped = fingerprint.equipped

    def resolve_all(self) -> Dict[ProductSlot, SlotPriority]:
        """Resolve priorities for all equipment slots."""
        priorities = {}

        for slot in ProductSlot:
            priorities[slot] = self.resolve_slot(slot)

        return priorities

    def resolve_slot(self, slot: ProductSlot) -> SlotPriority:
        """Resolve priority for a single slot."""
        # Get weapon classes for main skill
        weapon_classes = self._get_weapon_classes()

        # Get equipment classes for this slot
        equipment_classes = self._get_equipment_classes(slot, weapon_classes)

        # Resolve base tiers for this slot
        base_tiers = self._resolve_base_tiers(slot, equipment_classes)

        # Get defensive floors
        defensive_floors = DEFENSIVE_FLOORS.get(self.defense_layer, {}).get(slot, {})

        # Get preferred implicits
        preferred_implicits = self._get_preferred_implicits(slot)

        # Get blocked bases (wrong defense layer)
        blocked_bases = self._get_blocked_bases(slot, equipment_classes)

        # Determine socket/link requirements
        required_sockets, required_links = self._get_socket_requirements(slot)

        # Determine min item level and unidentified tier (profile will override)
        min_item_level = 68
        min_unidentified_tier = 2

        return SlotPriority(
            slot=slot,
            defense_layer=self.defense_layer,
            base_tiers=base_tiers,
            min_item_level=min_item_level,
            min_unidentified_tier=min_unidentified_tier,
            required_sockets=required_sockets,
            required_links=required_links,
            defensive_floors=defensive_floors,
            preferred_implicits=preferred_implicits,
            blocked_bases=frozenset(blocked_bases),
        )

    def _get_weapon_classes(self) -> List[str]:
        """Keep the equipped weapon class even when the skill map is incomplete."""
        classes = get_weapon_classes_for_skill(self.main_skill)
        from exilelens.filters.verified_bases import FILTER_TO_POB_CLASS, load_verified_bases
        bases = load_verified_bases()
        for slot in (ProductSlot.WEAPON_1, ProductSlot.WEAPON_2):
            item = self.equipped.get(slot)
            actual = bases.get(item.base_type) if item and item.base_type else None
            for filter_class, pob_class in FILTER_TO_POB_CLASS.items():
                if actual == pob_class and filter_class in SLOT_EQUIPMENT_CLASSES[slot]:
                    classes = [*classes, filter_class]
        return list(dict.fromkeys(classes))

    def _get_equipment_classes(self, slot: ProductSlot, weapon_classes: List[str]) -> List[str]:
        """Get equipment classes for a slot, filtered by weapon classes for weapon slots."""
        base_classes = SLOT_EQUIPMENT_CLASSES.get(slot, [])

        if slot in (ProductSlot.WEAPON_1, ProductSlot.WEAPON_2):
            # Filter weapon classes by skill relevance
            return [wc for wc in base_classes if wc in weapon_classes]

        return base_classes

    def _resolve_base_tiers(self, slot: ProductSlot, equipment_classes: List[str]) -> Dict[str, BaseTier]:
        """Resolve base tiers for a slot across relevant equipment classes."""
        merged = {}

        for eq_class in equipment_classes:
            class_tiers = BASE_TIERS.get(eq_class, {})
            merged.update(class_tiers)

        # Filter by defense layer if hiding irrelevant layers
        allowed_tiers = DEFENSE_LAYER_BASE_FILTER.get(self.defense_layer, {})

        if allowed_tiers:
            filtered = {}
            for eq_class in equipment_classes:
                class_allowed = allowed_tiers.get(eq_class, set())
                class_tiers = BASE_TIERS.get(eq_class, {})
                for base, tier in class_tiers.items():
                    if tier in class_allowed or tier == BaseTier.IGNORE:
                        filtered[base] = tier
            return filtered

        return merged

    def _get_preferred_implicits(self, slot: ProductSlot) -> List[str]:
        """Get preferred implicit mods for a slot based on build needs."""
        implicits = []

        # Resistance needs
        resist_caps = self.fingerprint.resist_caps
        if resist_caps.get("fire") in ("BELOW_CAP", "BELOW_CAP_IMPROVED", "BELOW_CAP_WORSENED"):
            implicits.append("Fire Resistance")
        if resist_caps.get("cold") in ("BELOW_CAP", "BELOW_CAP_IMPROVED", "BELOW_CAP_WORSENED"):
            implicits.append("Cold Resistance")
        if resist_caps.get("lightning") in ("BELOW_CAP", "BELOW_CAP_IMPROVED", "BELOW_CAP_WORSENED"):
            implicits.append("Lightning Resistance")
        if resist_caps.get("chaos") in ("BELOW_CAP", "BELOW_CAP_IMPROVED", "BELOW_CAP_WORSENED"):
            implicits.append("Chaos Resistance")

        # Attribute needs (check thresholds)
        for threshold in self.fingerprint.thresholds:
            if threshold.metric in ("strength", "dexterity", "intelligence") and threshold.severity == "SOFT":
                implicits.append(threshold.metric.capitalize())

        # Slot-specific
        if slot in (ProductSlot.AMULET, ProductSlot.RING_1, ProductSlot.RING_2):
            implicits.extend(["All Attributes", "All Elemental Resistances"])

        if slot in (ProductSlot.WEAPON_1, ProductSlot.WEAPON_2):
            implicits.extend(["Spell Damage", "Attack Speed", "Critical Strike Chance"])

        return list(dict.fromkeys(implicits))  # Dedupe preserving order

    def _get_blocked_bases(self, slot: ProductSlot, equipment_classes: List[str]) -> Set[str]:
        """Get bases that should be explicitly hidden (wrong defense layer)."""
        blocked = set()

        # If we have a clear defense layer, block bases of other layers
        if self.defense_layer != DefenseLayer.UNKNOWN:
            for eq_class in equipment_classes:
                class_tiers = BASE_TIERS.get(eq_class, {})
                for base, tier in class_tiers.items():
                    if tier == BaseTier.IGNORE:
                        blocked.add(base)

        return blocked

    def _get_socket_requirements(self, slot: ProductSlot) -> tuple[int, int]:
        """PoE2 skill links do not justify a gear-socket gate here."""
        return (0, 0)


def get_base_tier(equipment_class: str, base_type: str) -> BaseTier:
    """Look up base tier for a specific equipment class and base type."""
    return BASE_TIERS.get(equipment_class, {}).get(base_type, BaseTier.IGNORE)


def get_all_bases_for_class(equipment_class: str) -> Dict[str, BaseTier]:
    """Get all base types and tiers for an equipment class."""
    return BASE_TIERS.get(equipment_class, {}).copy()


def get_weapon_classes_for_skill(skill: str) -> List[str]:
    """Get relevant weapon classes for a skill."""
    classes = SKILL_WEAPON_CLASSES.get(skill, DEFAULT_WEAPON_CLASSES)
    return list(DEFAULT_WEAPON_CLASSES if classes == ["Any"] else classes)
