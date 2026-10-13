"""Pinned PoE2 base names and the audit of build-specific priority suggestions."""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path


DATA_FILE = Path(__file__).with_name("data") / "poe2_bases.json"
PROPERTIES_FILE = Path(__file__).with_name("data") / "poe2_base_properties.json"

# Exact currency names published by GGG in The Third Edict item-filter list.
# Currency is intentionally separate from PoB's equipment-base snapshot.
PINNED_SPECIAL_BASES = {
    name: "Stackable Currency" for name in (
        "Hinekora's Lock", "Greater Chaos Orb", "Perfect Chaos Orb",
        "Greater Exalted Orb", "Perfect Exalted Orb", "Greater Regal Orb",
        "Perfect Regal Orb", "Greater Orb of Transmutation",
        "Perfect Orb of Transmutation", "Greater Orb of Augmentation",
        "Perfect Orb of Augmentation",
    )
}

# Names the user's own in-game captures show (see currency_tiers.OBSERVED): exact, class-bound, and never presented as GGG-published.
from exilelens.filters.currency_tiers import OBSERVED_ONLY as _OBSERVED_CURRENCY  # noqa: E402

OBSERVED_SPECIAL_BASES = {name: "Stackable Currency" for name in _OBSERVED_CURRENCY}
# Exact names taken from the most widely used live PoE2 community filter (currency_tiers.COMMUNITY_FILTER): never presented as GGG-published or observed.
from exilelens.filters.currency_tiers import COMMUNITY_ONLY as _COMMUNITY_CURRENCY  # noqa: E402

COMMUNITY_SPECIAL_BASES = {name: "Stackable Currency" for name in _COMMUNITY_CURRENCY}
# Every special (non-equipment) name the repository DECLARES (evidence per name lives in currency_tiers). Declared is not legal: the class
# here is an assumption (`Stackable Currency`); the legal set and the real class come from the native ground-base registry below.
_DECLARED_SPECIAL_BASES = {**PINNED_SPECIAL_BASES, **OBSERVED_SPECIAL_BASES, **COMMUNITY_SPECIAL_BASES}


def raw_special_names() -> frozenset[str]:
    """Declared special names (input of the registry build; NOT the legal set)."""
    return frozenset(_DECLARED_SPECIAL_BASES)


def _legal_special_bases() -> dict[str, str]:
    """Declared special names that the native registry establishes as ground bases, with their REAL native class. An unreadable registry
    yields no legal special name at all (fail closed)."""
    from exilelens.filters import native_bases
    try:
        registry = native_bases.load_registry()
    except (OSError, ValueError, KeyError, TypeError):
        return {}
    return {name: registry[name].native_class for name in sorted(_DECLARED_SPECIAL_BASES)
            if name in registry and registry[name].ground_valid}


# Every special (non-equipment) name a BaseType condition may legally carry, with the class it needs (registry-established only).
SPECIAL_BASES = _legal_special_bases()

# PoB's item types are singular; filter Class conditions use these names.
FILTER_TO_POB_CLASS = {
    "Amulets": "Amulet", "Belts": "Belt", "Body Armours": "Body Armour",
    "Boots": "Boots", "Bows": "Bow", "Crossbows": "Crossbow",
    "Flasks": "Flask", "Foci": "Focus", "Gloves": "Gloves",
    "Helmets": "Helmet", "Jewels": "Jewel", "One Hand Maces": "One Hand Mace",
    "Quarterstaves": "Quarterstaff", "Quivers": "Quiver", "Rings": "Ring",
    "Sceptres": "Sceptre", "Shields": "Shield", "Spears": "Spear",
    "Staves": "Staff", "Talismans": "Talisman", "Two Hand Maces": "Two Hand Mace",
    "Wands": "Wand",
    # FILTER-08C: weapon/offhand families PoB2 carries and PoE2DB lists as item classes
    # (https://poe2db.tw/us/Items, equipment item classes, checked 2026-10-02).
    "Claws": "Claw", "Daggers": "Dagger", "Flails": "Flail", "One Hand Axes": "One Hand Axe",
    "Two Hand Axes": "Two Hand Axe", "One Hand Swords": "One Hand Sword", "Two Hand Swords": "Two Hand Sword",
    "Bucklers": "Shield",
    # FILTER-08E: PoE2DB lists "Charms" and "Traps" as item classes (https://poe2db.tw/us/Items, checked 2026-10-03). They carry no role in
    # build-aware rules; classifying them only makes their native Class verified (valid in the validator, counted as classified).
    "Charms": "Charm", "Traps": "TrapTool",
}


def native_class(base: str) -> str | None:
    """Native filter Class of a verified base. Bucklers are PoB2 'Shield' bases with their own native class."""
    record = load_base_properties().get(base)
    if record is None:
        return None
    if record["class"] == "Shield":
        return "Bucklers" if "Buckler" in base else "Shields"
    return next((native for native, pob in FILTER_TO_POB_CLASS.items() if pob == record["class"]), None)


@lru_cache(maxsize=1)
def load_pob_bases() -> dict[str, str]:
    """POB_INTERNAL_ITEM_BASES: every name in PoB2's `itemBases` (synthetic, non-ground and developer bases included). This is the CALCULATION
    universe; it is never a source of BaseType values. Fail closed if the checked-in source snapshot is unavailable or malformed."""
    data = json.loads(DATA_FILE.read_text(encoding="utf-8"))
    bases = data["bases"]
    if not data.get("pob_commit") or not data.get("pob_version") or len(bases) < 1000:
        raise ValueError("PoE2 base-item snapshot is incomplete")
    if any(not isinstance(name, str) or not isinstance(cls, str) for name, cls in bases.items()):
        raise ValueError("PoE2 base-item snapshot contains invalid entries")
    return bases


@lru_cache(maxsize=1)
def load_pob_base_properties() -> dict[str, dict]:
    """Pinned implicit, progression and intrinsic defence data of the whole PoB2 universe (calculation only)."""
    payload = json.loads(PROPERTIES_FILE.read_text(encoding="utf-8"))
    source = json.loads(DATA_FILE.read_text(encoding="utf-8"))
    records = payload.get("bases", {})
    if payload.get("pob_commit") != source.get("pob_commit") or set(records) != set(source["bases"]):
        raise ValueError("PoB2 base properties do not match the verified base snapshot")
    if any(record.get("class") != source["bases"][name] for name, record in records.items()):
        raise ValueError("PoB2 base properties have a class mismatch")
    return records


def _ground_names() -> frozenset[str]:
    from exilelens.filters import native_bases
    native_bases.load_registry()   # raises on a missing or malformed registry: no registry, no bases
    pinned = json.loads(DATA_FILE.read_text(encoding="utf-8")).get("pob_commit")
    if native_bases.registry_meta().get("pob_commit") != pinned:
        raise ValueError("native ground-base registry was built for another PoB2 commit; rebuild it (scripts/filter_native_registry.py)")
    return native_bases.ground_bases()


@lru_cache(maxsize=1)
def load_verified_bases() -> dict[str, str]:
    """NATIVE_FILTER_GROUND_BASES among the PoB catalog: base name -> PoB class, for names the native registry establishes as ground bases.

    This is the only base universe the filter generator, planner, preview pools and validator may enumerate. PoB-only names are absent."""
    ground = _ground_names()
    return {name: cls for name, cls in load_pob_bases().items() if name in ground}


@lru_cache(maxsize=1)
def load_base_properties() -> dict[str, dict]:
    """Properties of the ground-valid bases (same key set as `load_verified_bases`)."""
    ground = load_verified_bases()
    return {name: record for name, record in load_pob_base_properties().items() if name in ground}


def audit_priorities(priorities: dict) -> tuple[dict, dict]:
    """Keep priority labels only where exact native name and class are verified."""
    bases = load_verified_bases()
    verified = {}
    absent = []
    wrong_class = []
    duplicates = []
    seen = {}
    for filter_class, names in priorities.items():
        expected = FILTER_TO_POB_CLASS.get(filter_class)
        if expected is None:
            raise ValueError(f"No verified class mapping for {filter_class}")
        selected = {}
        for name, tier in names.items():
            previous = seen.setdefault(name, filter_class)
            if previous != filter_class:
                duplicates.append((name, previous, filter_class))
            actual = bases.get(name)
            if actual is None:
                absent.append((filter_class, name))
            elif actual != expected:
                wrong_class.append((filter_class, name, actual))
            else:
                selected[name] = tier
        verified[filter_class] = selected
    report = {"examined": sum(map(len, priorities.values())),
              "verified": sum(map(len, verified.values())),
              "absent": absent, "wrong_class": wrong_class, "duplicate_suggestions": duplicates}
    return verified, report
