"""Canonical Trade2 stat registry for MARKET-02B.

MARKET-02A found collisions in the hand-written `_FAMILY_STAT_IDS` map (lightning
res sharing fire's id, strength sharing intelligence, dex/evasion missing from the
catalog). This module is the source of truth: one canonical family → verified Trade2
hashes → prefixed ids. Two different families must not resolve to the same hash
unless the collision is explicit and intentional.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Iterable


class FloorKind(str, Enum):
    INTEGER_SMALL = "integer_small"
    FLAT_LARGE = "flat_large"
    BOUNDED_PERCENT = "bounded_percent"
    PSEUDO = "pseudo"
    EQUIPMENT = "equipment"
    EXACT = "exact"


class DriverKind(str, Enum):
    EXACT_STAT = "EXACT_STAT"
    PSEUDO = "PSEUDO"
    EQUIPMENT_FILTER = "EQUIPMENT_FILTER"


# Prefixes that can carry the same numeric hash for one economic stat.
# Never emit a prefix that is absent from `/api/trade2/data/stats` for that hash —
# Trade2 HTTP 400s on unknown `implicit.stat_*` / `crafted.stat_*` ids.
ALIAS_PREFIXES: tuple[str, ...] = (
    "explicit",
    "implicit",
    "fractured",
    "crafted",
    "desecrated",
)

# Catalog-verified prefixes per numeric hash (Forbidden Rites, 2026-09-08).
_HASH_PREFIXES: dict[str, tuple[str, ...]] = {
    "2891184298": ("explicit", "implicit", "fractured", "crafted", "desecrated"),
    "681332047": ("explicit", "implicit", "fractured", "crafted", "desecrated"),
    "2672805335": ("explicit",),
    "2231156303": ("explicit", "implicit", "fractured", "crafted", "desecrated"),
    "3962278098": ("explicit", "fractured", "crafted", "desecrated"),
    "3291658075": ("explicit", "fractured", "crafted", "desecrated"),
    "1509134228": ("explicit", "fractured", "crafted", "desecrated"),
    "2974417149": ("explicit", "fractured", "crafted", "desecrated"),
    "1545858329": ("explicit", "fractured", "desecrated"),
    "3299347043": ("explicit", "implicit", "fractured", "crafted", "desecrated"),
    "1050105434": ("explicit", "implicit", "fractured", "crafted", "desecrated"),
    "3489782002": ("explicit", "implicit", "fractured", "desecrated"),
    "4015621042": ("explicit", "fractured", "crafted", "desecrated"),
    "3372524247": ("explicit", "implicit", "fractured", "crafted", "desecrated"),
    "4220027924": ("explicit", "implicit", "fractured", "crafted", "desecrated"),
    "1671376347": ("explicit", "implicit", "fractured", "crafted", "desecrated"),
    "2923486259": ("explicit", "implicit", "fractured", "crafted", "desecrated"),
    "2901986750": ("explicit", "implicit", "fractured", "desecrated"),
    "587431675": ("explicit", "fractured", "desecrated"),
    "737908626": ("explicit", "fractured", "crafted", "desecrated"),
    "3556824919": ("explicit", "fractured", "crafted", "desecrated"),
    "4080418644": ("explicit", "implicit", "fractured", "crafted", "desecrated"),
    "3261801346": ("explicit", "implicit", "fractured", "crafted", "desecrated"),
    "328541901": ("explicit", "implicit", "fractured", "crafted", "desecrated"),
    "809229260": ("explicit", "implicit", "fractured", "desecrated"),
    "2144192055": ("explicit", "fractured", "desecrated"),
    "2250533757": ("explicit", "implicit", "fractured", "crafted", "desecrated"),
    "1379411836": ("explicit", "implicit", "fractured", "desecrated"),
    # MARKET-03, verified against the live catalog snapshot on 2026-09-09. Prefixes are
    # the intersection of what the catalog publishes for the hash and what this registry
    # is willing to emit -- the catalog also carries `rune.` and `enchant.` forms for
    # several of these, which are deliberately not sent.
    "124131830": ("explicit", "fractured", "crafted", "desecrated"),
    "818778753": ("explicit", "fractured", "desecrated"),
    "2653955271": ("explicit", "fractured", "desecrated"),
    "3417711605": ("explicit", "fractured", "desecrated"),
    "2101383955": ("explicit", "fractured", "crafted"),
    "3278136794": ("explicit", "fractured", "crafted", "desecrated"),
    "3015669065": ("explicit", "fractured", "crafted", "desecrated"),
    "2505884597": ("explicit", "fractured", "crafted", "desecrated"),
    "3398787959": ("explicit", "fractured", "crafted", "desecrated"),
    "3981240776": ("explicit", "implicit", "fractured", "crafted", "desecrated"),
    "2704225257": ("explicit", "fractured", "desecrated"),
}

# Trade2 equipment_filters keys — not pseudo stats.
EQUIPMENT_FILTER_KEYS = frozenset({"dps", "pdps", "edps", "aps", "crit", "ar", "ev", "es", "ward", "block"})


@dataclass(frozen=True)
class StatFamilyRecord:
    family: str
    label: str
    hashes: tuple[str, ...]
    floor_kind: FloorKind
    driver_kind: DriverKind = DriverKind.EXACT_STAT
    affix_range: tuple[float, float] | None = None
    component_families: tuple[str, ...] = ()
    equipment_key: str | None = None
    aliases: tuple[str, ...] = ()
    verified: bool = True


def _explicit(*hashes: str) -> tuple[str, ...]:
    return tuple(hashes)


# Snapshot of the catalog-backed family map. Signatures store this so a later
# registry rewrite cannot keep applying stale Trade ids as AUTO authority.
STAT_REGISTRY_VERSION = "2026-09-09-fr"

# Verified against live `/api/trade2/data/stats` during MARKET-02A plus ids that
# already produced HTTP 200 on the B7–B13 path. Hashes are the numeric `stat_*`
# fragment; prefixes are applied at query time.
_FAMILIES: tuple[StatFamilyRecord, ...] = (
    StatFamilyRecord(
        "cast_speed",
        "Cast Speed",
        _explicit("2891184298"),
        FloorKind.BOUNDED_PERCENT,
        affix_range=(10.0, 35.0),
        aliases=("cast speed",),
    ),
    StatFamilyRecord(
        "attack_speed",
        "Attack Speed",
        _explicit("681332047"),
        FloorKind.BOUNDED_PERCENT,
        affix_range=(5.0, 25.0),
        aliases=("attack speed",),
    ),
    StatFamilyRecord(
        "attack_cast_speed",
        "Attack and Cast Speed",
        _explicit("2672805335"),
        FloorKind.BOUNDED_PERCENT,
        affix_range=(5.0, 20.0),
        aliases=("attack and cast speed",),
    ),
    StatFamilyRecord(
        "lightning_damage",
        "Lightning Damage",
        _explicit("2231156303"),
        FloorKind.BOUNDED_PERCENT,
        affix_range=(10.0, 50.0),
        aliases=("lightning damage",),
    ),
    StatFamilyRecord(
        "fire_damage",
        "Fire Damage",
        _explicit("3962278098"),
        FloorKind.BOUNDED_PERCENT,
        affix_range=(10.0, 50.0),
        aliases=("fire damage",),
    ),
    StatFamilyRecord(
        "cold_damage",
        "Cold Damage",
        _explicit("3291658075"),
        FloorKind.BOUNDED_PERCENT,
        affix_range=(10.0, 50.0),
        aliases=("cold damage",),
    ),
    StatFamilyRecord(
        "physical_damage",
        "Physical Damage",
        _explicit("1509134228"),
        FloorKind.BOUNDED_PERCENT,
        affix_range=(10.0, 50.0),
        aliases=("physical damage",),
    ),
    StatFamilyRecord(
        "spell_damage",
        "Spell Damage",
        _explicit("2974417149"),
        FloorKind.BOUNDED_PERCENT,
        affix_range=(10.0, 80.0),
        aliases=("spell damage",),
    ),
    StatFamilyRecord(
        "lightning_spell_skills",
        "Lightning Spell Skills",
        _explicit("1545858329"),
        FloorKind.INTEGER_SMALL,
        affix_range=(1.0, 4.0),
        aliases=("level of all lightning spell skills",),
    ),
    StatFamilyRecord(
        "maximum_life",
        "Maximum Life",
        _explicit("3299347043"),
        FloorKind.FLAT_LARGE,
        affix_range=(20.0, 120.0),
        aliases=("life", "maximum life"),
    ),
    StatFamilyRecord(
        "maximum_mana",
        "Maximum Mana",
        _explicit("1050105434"),
        FloorKind.FLAT_LARGE,
        affix_range=(50.0, 180.0),
        aliases=("mana", "maximum mana"),
    ),
    StatFamilyRecord(
        "maximum_energy_shield",
        "Maximum Energy Shield",
        _explicit("3489782002"),
        FloorKind.FLAT_LARGE,
        affix_range=(20.0, 120.0),
        aliases=("energy shield", "maximum energy shield"),
    ),
    StatFamilyRecord(
        "energy_shield",
        "Energy Shield",
        _explicit("4015621042"),
        FloorKind.BOUNDED_PERCENT,
        affix_range=(20.0, 120.0),
        aliases=("energy shield (local)",),
    ),
    # MARKET-02A: fire was already correct; lightning must NOT share this hash.
    StatFamilyRecord(
        "fire_resistance",
        "Fire Resistance",
        _explicit("3372524247"),
        FloorKind.INTEGER_SMALL,
        affix_range=(15.0, 45.0),
        aliases=("fire resistance",),
    ),
    StatFamilyRecord(
        "cold_resistance",
        "Cold Resistance",
        _explicit("4220027924"),
        FloorKind.INTEGER_SMALL,
        affix_range=(15.0, 45.0),
        aliases=("cold resistance",),
    ),
    StatFamilyRecord(
        "lightning_resistance",
        "Lightning Resistance",
        _explicit("1671376347"),
        FloorKind.INTEGER_SMALL,
        affix_range=(15.0, 45.0),
        aliases=("lightning resistance",),
    ),
    StatFamilyRecord(
        "chaos_resistance",
        "Chaos Resistance",
        _explicit("2923486259"),
        FloorKind.INTEGER_SMALL,
        affix_range=(10.0, 35.0),
        aliases=("chaos resistance",),
    ),
    StatFamilyRecord(
        "all_elemental_resistances",
        "All Elemental Resistances",
        _explicit("2901986750"),
        FloorKind.INTEGER_SMALL,
        affix_range=(5.0, 20.0),
        aliases=("all elemental resistances",),
    ),
    StatFamilyRecord(
        "critical_strike_chance",
        "Critical Hit Chance",
        _explicit("587431675"),
        FloorKind.BOUNDED_PERCENT,
        affix_range=(10.0, 50.0),
        aliases=("critical strike chance", "critical hit chance"),
    ),
    StatFamilyRecord(
        "spell_critical_hit_chance",
        "Critical Hit Chance for Spells",
        _explicit("737908626"),
        FloorKind.BOUNDED_PERCENT,
        affix_range=(10.0, 50.0),
        aliases=("critical hit chance for spells", "critical strike chance for spells"),
    ),
    StatFamilyRecord(
        "critical_strike_multiplier",
        "Critical Damage Bonus",
        _explicit("3556824919"),
        FloorKind.BOUNDED_PERCENT,
        affix_range=(10.0, 40.0),
        aliases=("critical strike multiplier", "critical damage bonus"),
    ),
    StatFamilyRecord(
        "strength",
        "Strength",
        _explicit("4080418644"),
        FloorKind.INTEGER_SMALL,
        affix_range=(5.0, 55.0),
        aliases=("strength",),
    ),
    StatFamilyRecord(
        "dexterity",
        "Dexterity",
        _explicit("3261801346"),
        FloorKind.INTEGER_SMALL,
        affix_range=(5.0, 55.0),
        aliases=("dexterity",),
    ),
    StatFamilyRecord(
        "intelligence",
        "Intelligence",
        _explicit("328541901"),
        FloorKind.INTEGER_SMALL,
        affix_range=(5.0, 55.0),
        aliases=("intelligence",),
    ),
    StatFamilyRecord(
        "armour",
        "Armour",
        _explicit("809229260"),
        FloorKind.FLAT_LARGE,
        affix_range=(20.0, 400.0),
        aliases=("armour",),
    ),
    StatFamilyRecord(
        "evasion",
        "Evasion",
        _explicit("2144192055"),
        FloorKind.FLAT_LARGE,
        affix_range=(20.0, 400.0),
        aliases=("evasion", "evasion rating"),
    ),
    StatFamilyRecord(
        "movement_speed",
        "Movement Speed",
        _explicit("2250533757"),
        FloorKind.BOUNDED_PERCENT,
        affix_range=(10.0, 35.0),
        aliases=("movement speed",),
    ),
    StatFamilyRecord(
        "all_attributes",
        "All Attributes",
        _explicit("1379411836"),
        FloorKind.INTEGER_SMALL,
        affix_range=(5.0, 30.0),
        aliases=("all attributes",),
    ),
    # First-class pseudos from the live 36-id catalog. Not equipment DPS.
    StatFamilyRecord(
        "total_elemental_resistance",
        "Total Elemental Resistance",
        ("pseudo_total_elemental_resistance",),
        FloorKind.PSEUDO,
        driver_kind=DriverKind.PSEUDO,
        component_families=("fire_resistance", "cold_resistance", "lightning_resistance", "all_elemental_resistances"),
        aliases=("total elemental resistance",),
    ),
    StatFamilyRecord(
        "total_resistance",
        "Total Resistance",
        ("pseudo_total_resistance",),
        FloorKind.PSEUDO,
        driver_kind=DriverKind.PSEUDO,
        component_families=(
            "fire_resistance",
            "cold_resistance",
            "lightning_resistance",
            "chaos_resistance",
            "all_elemental_resistances",
        ),
        aliases=("total resistance",),
    ),
    StatFamilyRecord(
        "total_attributes",
        "Total Attributes",
        ("pseudo_total_attributes",),
        FloorKind.PSEUDO,
        driver_kind=DriverKind.PSEUDO,
        component_families=("strength", "dexterity", "intelligence", "all_attributes"),
        aliases=("total attributes",),
    ),
    StatFamilyRecord(
        "total_life",
        "Total Life",
        ("pseudo_total_life",),
        FloorKind.PSEUDO,
        driver_kind=DriverKind.PSEUDO,
        component_families=("maximum_life",),
        aliases=("total life",),
    ),
    StatFamilyRecord(
        "total_mana",
        "Total Mana",
        ("pseudo_total_mana",),
        FloorKind.PSEUDO,
        driver_kind=DriverKind.PSEUDO,
        component_families=("maximum_mana",),
        aliases=("total mana",),
    ),
    StatFamilyRecord(
        "total_energy_shield",
        "Total Energy Shield",
        ("pseudo_total_energy_shield",),
        FloorKind.PSEUDO,
        driver_kind=DriverKind.PSEUDO,
        component_families=("maximum_energy_shield", "energy_shield"),
        aliases=("total energy shield",),
    ),
    StatFamilyRecord(
        "pseudo_movement_speed",
        "Movement Speed (total)",
        ("pseudo_increased_movement_speed",),
        FloorKind.PSEUDO,
        driver_kind=DriverKind.PSEUDO,
        component_families=("movement_speed",),
        aliases=("increased movement speed",),
    ),
    # Equipment filters — never emitted as fake stat ids.
    StatFamilyRecord(
        "equip_dps",
        "Damage per Second",
        (),
        FloorKind.EQUIPMENT,
        driver_kind=DriverKind.EQUIPMENT_FILTER,
        equipment_key="dps",
        aliases=("dps",),
    ),
    StatFamilyRecord(
        "equip_pdps",
        "Physical DPS",
        (),
        FloorKind.EQUIPMENT,
        driver_kind=DriverKind.EQUIPMENT_FILTER,
        equipment_key="pdps",
        aliases=("physical dps", "pdps"),
    ),
    StatFamilyRecord(
        "equip_edps",
        "Elemental DPS",
        (),
        FloorKind.EQUIPMENT,
        driver_kind=DriverKind.EQUIPMENT_FILTER,
        equipment_key="edps",
        aliases=("elemental dps", "edps"),
    ),
    StatFamilyRecord(
        "equip_ar",
        "Armour (item)",
        (),
        FloorKind.EQUIPMENT,
        driver_kind=DriverKind.EQUIPMENT_FILTER,
        equipment_key="ar",
        aliases=("armour rating",),
    ),
    StatFamilyRecord(
        "equip_ev",
        "Evasion (item)",
        (),
        FloorKind.EQUIPMENT,
        driver_kind=DriverKind.EQUIPMENT_FILTER,
        equipment_key="ev",
        aliases=("evasion rating (item)",),
    ),
    StatFamilyRecord(
        "equip_es",
        "Energy Shield (item)",
        (),
        FloorKind.EQUIPMENT,
        driver_kind=DriverKind.EQUIPMENT_FILTER,
        equipment_key="es",
        aliases=("energy shield (item)",),
    ),
    # --- MARKET-03 registry-coverage closure -------------------------------------
    # Every hash below was read from one authorised catalog fetch on 2026-09-09 and is
    # matched on the catalog's exact label, never on a similar one. The snapshot that
    # verified them lives in fixtures/market/trade2_stat_catalog.json so the regressions
    # stay offline.
    StatFamilyRecord(
        "all_spell_skills",
        "Level of all Spell Skills",
        _explicit("124131830"),
        FloorKind.EXACT,
        aliases=("level of all spell skills", "level_of_all_spell_skills"),
    ),
    StatFamilyRecord(
        "spirit",
        "Spirit",
        # Two distinct catalog hashes carry the plain "# to Spirit" label. Both are
        # legitimate, so both are emitted as an alias-OR rather than one being picked.
        _explicit("3981240776", "2704225257"),
        FloorKind.FLAT_LARGE,
        aliases=("to spirit",),
    ),
    StatFamilyRecord(
        "lightning_penetration",
        "Lightning Penetration",
        _explicit("818778753"),
        FloorKind.INTEGER_SMALL,
    ),
    StatFamilyRecord(
        "fire_penetration",
        "Fire Penetration",
        _explicit("2653955271"),
        FloorKind.INTEGER_SMALL,
    ),
    StatFamilyRecord(
        "cold_penetration",
        "Cold Penetration",
        _explicit("3417711605"),
        FloorKind.INTEGER_SMALL,
    ),
    StatFamilyRecord(
        "elemental_penetration",
        "Elemental Penetration",
        _explicit("2101383955"),
        FloorKind.INTEGER_SMALL,
    ),
    StatFamilyRecord(
        "gain_extra_lightning",
        "Gain as Extra Lightning Damage",
        _explicit("3278136794"),
        FloorKind.INTEGER_SMALL,
    ),
    StatFamilyRecord(
        "gain_extra_fire",
        "Gain as Extra Fire Damage",
        _explicit("3015669065"),
        FloorKind.INTEGER_SMALL,
    ),
    StatFamilyRecord(
        "gain_extra_cold",
        "Gain as Extra Cold Damage",
        _explicit("2505884597"),
        FloorKind.INTEGER_SMALL,
    ),
    StatFamilyRecord(
        "gain_extra_chaos",
        "Gain as Extra Chaos Damage",
        _explicit("3398787959"),
        FloorKind.INTEGER_SMALL,
    ),
)
_BY_FAMILY: dict[str, StatFamilyRecord] = {row.family: row for row in _FAMILIES}
_BY_ALIAS: dict[str, str] = {}
for _row in _FAMILIES:
    _BY_ALIAS[_row.family] = _row.family
    _BY_ALIAS[_row.label.lower()] = _row.family
    for _alias in _row.aliases:
        _BY_ALIAS[_alias.lower()] = _row.family


def all_families() -> tuple[StatFamilyRecord, ...]:
    return _FAMILIES


def get_family(family: str) -> StatFamilyRecord | None:
    key = str(family or "").strip()
    if not key:
        return None
    if key in _BY_FAMILY:
        return _BY_FAMILY[key]
    mapped = _BY_ALIAS.get(key.lower())
    return _BY_FAMILY.get(mapped or "")


def canonical_family_name(label: str) -> str | None:
    cleaned = " ".join(str(label or "").lower().split())
    if not cleaned:
        return None
    if cleaned in _BY_FAMILY:
        return cleaned
    return _BY_ALIAS.get(cleaned) or _BY_ALIAS.get(cleaned.replace(" ", "_"))


def _format_id(record: StatFamilyRecord, hash_value: str, prefix: str) -> str:
    if record.driver_kind is DriverKind.PSEUDO:
        if hash_value.startswith("pseudo_"):
            return f"pseudo.{hash_value}"
        return f"pseudo.{hash_value}"
    return f"{prefix}.stat_{hash_value}"


def is_catalog_invalid_stat_id(stat_id: str) -> bool:
    """True when this prefixed id is known-absent from the Trade2 catalog.

    Unknown hashes are not claimed invalid — we only refuse prefixes we have
    audited for hashes this registry owns.
    """
    cleaned = str(stat_id or "").strip()
    if not cleaned or cleaned.startswith("pseudo."):
        return False
    if ".stat_" not in cleaned:
        return False
    prefix, _, rest = cleaned.partition(".")
    hash_value = rest.replace("stat_", "")
    allowed = _HASH_PREFIXES.get(hash_value)
    if allowed is None:
        return False
    return prefix not in allowed


def prefixes_for_hash(hash_value: str) -> tuple[str, ...]:
    """Catalog-verified prefixes for a numeric Trade2 hash. Explicit-only if unknown."""
    return _HASH_PREFIXES.get(str(hash_value), ("explicit",))


def trade_stat_ids(family: str, *, prefixes: Iterable[str] | None = None) -> tuple[str, ...]:
    """Prefixed Trade2 ids for a family. Pseudos are a single catalog id.

    Alias-OR only uses prefixes that exist on the live Trade2 catalog for that hash.
    """
    record = get_family(family)
    if record is None or record.driver_kind is DriverKind.EQUIPMENT_FILTER:
        return ()
    if record.driver_kind is DriverKind.PSEUDO:
        return tuple(_format_id(record, hash_value, "pseudo") for hash_value in record.hashes)
    ids: list[str] = []
    for hash_value in record.hashes:
        allowed = prefixes_for_hash(hash_value)
        used = tuple(prefix for prefix in (prefixes or allowed) if prefix in allowed)
        if not used:
            used = ("explicit",) if "explicit" in allowed else allowed[:1]
        for prefix in used:
            ids.append(_format_id(record, hash_value, prefix))
    return tuple(ids)


def verified_trade_stat_ids() -> frozenset[str]:
    """Every prefixed id this registry is willing to send."""
    ids: set[str] = set()
    for record in _FAMILIES:
        ids.update(trade_stat_ids(record.family))
    return frozenset(ids)


def primary_trade_stat_id(family: str) -> str | None:
    record = get_family(family)
    if record is None:
        return None
    if record.driver_kind is DriverKind.EQUIPMENT_FILTER:
        return None
    ids = trade_stat_ids(family, prefixes=("explicit",) if record.driver_kind is DriverKind.EXACT_STAT else ("pseudo",))
    if record.driver_kind is DriverKind.PSEUDO:
        ids = trade_stat_ids(family)
    return ids[0] if ids else None


def hash_for_family(family: str) -> str | None:
    record = get_family(family)
    if record is None or not record.hashes:
        return None
    return record.hashes[0]


def collision_report(*, ignore_intentional: Iterable[str] = ()) -> list[str]:
    """Families that accidentally share a Trade2 hash.

    Pseudos and equipment filters are excluded. Intentional multi-family aliases
    can be listed in `ignore_intentional` as `family_a|family_b`.
    """
    ignore = {tuple(sorted(key.split("|"))) for key in ignore_intentional}
    hash_owners: dict[str, list[str]] = {}
    for record in _FAMILIES:
        if record.driver_kind is not DriverKind.EXACT_STAT:
            continue
        for hash_value in record.hashes:
            hash_owners.setdefault(hash_value, []).append(record.family)
    problems: list[str] = []
    for hash_value, families in hash_owners.items():
        unique = sorted(set(families))
        if len(unique) < 2:
            continue
        pair_key = tuple(unique[:2])
        if pair_key in ignore or tuple(unique) in ignore:
            continue
        problems.append(f"hash {hash_value} shared by {', '.join(unique)}")
    return problems


REQUIRED_DISTINCT_GROUPS: tuple[tuple[str, ...], ...] = (
    ("fire_resistance", "cold_resistance", "lightning_resistance", "chaos_resistance"),
    ("strength", "dexterity", "intelligence"),
    ("maximum_life", "cast_speed", "attack_speed"),
)


def assert_required_families_distinct() -> None:
    problems = collision_report()
    if problems:
        raise AssertionError("stat registry collisions: " + "; ".join(problems))
    for group in REQUIRED_DISTINCT_GROUPS:
        hashes = [hash_for_family(name) for name in group]
        if any(value is None for value in hashes):
            missing = [name for name, value in zip(group, hashes) if value is None]
            raise AssertionError(f"missing registry hashes: {missing}")
        if len(set(hashes)) != len(hashes):
            raise AssertionError(f"group {group} is not distinct: {hashes}")
