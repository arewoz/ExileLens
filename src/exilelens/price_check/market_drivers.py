"""MarketPriceDriver + PriceCheckHypothesis — one object powers UI and Trade JSON.

MARKET-02B. Driver selection is a class-specific market prior. It must not use PoB
DPS delta, profile score, or Build Value.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field, replace
from enum import Enum
from typing import Any, Iterable

from exilelens.items.metadata import parse_lightweight_metadata
from exilelens.items.raw_input import RawItemInput
from exilelens.price_check.comparable_features import (
    ComparableFeature,
    build_features,
    parse_feature_from_mod,
    normalize_mod_text,
    strip_mod_markup,
)
from exilelens.price_check.stat_registry import (
    DriverKind,
    FloorKind,
    get_family,
    primary_trade_stat_id,
    trade_stat_ids,
)
from exilelens.price_check.trade2_query_validation import validate_trade2_search_body


class SourceKind(str, Enum):
    EXPLICIT = "EXPLICIT"
    IMPLICIT = "IMPLICIT"
    FRACTURED = "FRACTURED"
    CRAFTED = "CRAFTED"
    DESECRATED = "DESECRATED"
    DERIVED = "DERIVED"


class MatchMode(str, Enum):
    ALL = "ALL"
    COUNT = "COUNT"


class HypothesisSource(str, Enum):
    AUTO_PRIOR = "AUTO_PRIOR"
    USER_REFINED = "USER_REFINED"
    AUTO_RECOVERY = "AUTO_RECOVERY"
    SIGNATURE = "SIGNATURE"


class EstimateState(str, Enum):
    MARKET_ESTIMATE = "MARKET ESTIMATE"
    HIGH_CONFIDENCE = "HIGH CONFIDENCE"
    ASSISTED_ESTIMATE = "ASSISTED ESTIMATE"
    NEEDS_REFINEMENT = "NEEDS REFINEMENT"
    BASE_MARKET_ESTIMATE = "BASE MARKET ESTIMATE"


class SlotFamily(str, Enum):
    JEWELLERY = "jewellery"
    JEWEL = "jewel"
    WEAPON = "weapon"
    ARMOUR = "armour"
    BOOTS = "boots"
    UNIQUE = "unique"
    OTHER = "other"


_RARITY_MAP = {
    "RARE": "rare",
    "UNIQUE": "unique",
    "MAGIC": "magic",
    "NORMAL": "normal",
}

_IMPLICITS_RE = re.compile(r"^Implicits:\s*(\d+)", re.I)
_FRACTURED_RE = re.compile(r"\(fractured\)", re.I)
_CRAFTED_RE = re.compile(r"\(crafted\)", re.I)
_DESECRATED_RE = re.compile(r"\(desecrated\)", re.I)
_ARMOUR_PROP_RE = re.compile(r"^Armour:\s*(\d+)", re.I)
_EVASION_PROP_RE = re.compile(r"^Evasion(?: Rating)?:\s*(\d+)", re.I)
_ES_PROP_RE = re.compile(r"^Energy Shield:\s*(\d+)", re.I)
_PHYS_DMG_RE = re.compile(r"^Physical Damage:\s*(\d+)-(\d+)", re.I)
_APS_RE = re.compile(r"^Attacks per Second:\s*([\d.]+)", re.I)
_ELEM_DMG_RE = re.compile(r"^Elemental Damage:\s*(.+)$", re.I)
_RANGE_RE = re.compile(r"(\d+)-(\d+)")

_ITEM_CLASS_RE = re.compile(r"(?im)^Item Class:\s*(.+)$")
# Word-boundary tokens. Optional trailing "s" is allowed ("boot"→"boots", "ring"→"rings")
# but "ring" must not match "Roaring" or "Ringmail".
_JEWELLERY_TOKENS = ("ring", "amulet", "belt")
_WEAPON_TOKENS = (
    "wand",
    "staff",
    "bow",
    "crossbow",
    "sword",
    "axe",
    "mace",
    "spear",
    "quarterstaff",
    "claw",
    "dagger",
    "sceptre",
    "flail",
)
_BOOT_TOKENS = ("boot", "greave", "sandal", "shoe", "slipper")
_HELMET_TOKENS = ("helmet", "helm", "tiara", "crown", "circlet")
_ARMOUR_TOKENS = (
    "glove",
    "gauntlet",
    "helmet",
    "helm",
    "tiara",
    "crown",
    "circlet",
    "body",
    "raiment",
    "mail",
    "robe",
    "armour",
    "armor",
    "shield",
    "buckler",
    "vestment",
    "cuirass",
)
_JEWEL_BASES = frozenset({"ruby", "emerald", "sapphire", "diamond", "time-lost ruby", "time-lost emerald", "time-lost sapphire"})
_CRIT_CHANCE_FAMILIES = frozenset({"critical_strike_chance", "spell_critical_hit_chance"})

JEWELLERY_PRIMARY = (
    "maximum_life",
    "total_resistance",
    "total_elemental_resistance",
    "cast_speed",
    "lightning_spell_skills",
    "spell_damage",
    "lightning_damage",
    "fire_damage",
    "cold_damage",
    "attack_speed",
    "chaos_resistance",
    "strength",
    "dexterity",
    "intelligence",
    "all_attributes",
    "critical_strike_chance",
)
WEAPON_GLOBAL = (
    "lightning_spell_skills",
    "spell_damage",
    "cast_speed",
    "spell_critical_hit_chance",
    "critical_strike_chance",
    "critical_strike_multiplier",
    "lightning_damage",
    "fire_damage",
    "cold_damage",
    "maximum_life",
)
ARMOUR_PRIMARY = (
    "maximum_life",
    "total_resistance",
    "total_elemental_resistance",
    "movement_speed",
    "maximum_energy_shield",
    "chaos_resistance",
)
BOOTS_PRIMARY = (
    "movement_speed",
    "maximum_life",
    "total_elemental_resistance",
    "total_resistance",
    "maximum_energy_shield",
    "chaos_resistance",
)
_RESISTANCE_FAMILIES = frozenset(
    {"fire_resistance", "cold_resistance", "lightning_resistance", "chaos_resistance", "all_elemental_resistances"}
)
_PSEUDO_RESISTANCE_FAMILIES = frozenset({"total_elemental_resistance", "total_resistance"})
_SOURCE_KIND_RANK = {
    SourceKind.EXPLICIT: 0,
    SourceKind.FRACTURED: 1,
    SourceKind.CRAFTED: 2,
    SourceKind.DERIVED: 3,
    SourceKind.IMPLICIT: 4,
    SourceKind.DESECRATED: 5,
}
JEWEL_USEFUL = frozenset(
    {
        "spell_damage",
        "lightning_damage",
        "fire_damage",
        "cold_damage",
        "physical_damage",
        "cast_speed",
        "attack_speed",
        "maximum_life",
        "fire_resistance",
        "cold_resistance",
        "lightning_resistance",
        "chaos_resistance",
        "all_elemental_resistances",
        "strength",
        "dexterity",
        "intelligence",
        "critical_strike_chance",
        "spell_critical_hit_chance",
        "critical_strike_multiplier",
    }
)
JUNK_FAMILIES = frozenset(
    {
        "light_radius",
        "rarity_of_items_found",
        "mana_regeneration_rate",
        "item_rarity",
    }
)


@dataclass(frozen=True)
class MarketPriceDriver:
    """One driver row. The same object is rendered and turned into Trade JSON."""

    driver_id: str
    family: str
    label: str
    source_mod_text: str
    actual_value: float
    search_min: float
    search_max: float | None
    trade_stat_ids: tuple[str, ...]
    pseudo_id: str | None
    enabled: bool
    driver_kind: DriverKind
    source_kind: SourceKind
    priority: int
    query_group_id: str
    floor_policy: str
    component_families: tuple[str, ...] = ()
    equipment_key: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "driver_id": self.driver_id,
            "family": self.family,
            "label": self.label,
            "source_mod_text": self.source_mod_text,
            "actual_value": self.actual_value,
            "search_min": self.search_min,
            "search_max": self.search_max,
            "trade_stat_ids": list(self.trade_stat_ids),
            "pseudo_id": self.pseudo_id or "",
            "enabled": self.enabled,
            "driver_kind": self.driver_kind.value,
            "source_kind": self.source_kind.value,
            "priority": self.priority,
            "query_group_id": self.query_group_id,
            "floor_policy": self.floor_policy,
            "component_families": list(self.component_families),
            "equipment_key": self.equipment_key or "",
        }

    def overlay_row(self) -> str:
        mark = "x" if self.enabled else " "
        actual = _fmt_num(self.actual_value)
        floor = _fmt_num(self.search_min)
        kind = ""
        if self.driver_kind is DriverKind.PSEUDO:
            kind = "  (pseudo)"
        elif self.driver_kind is DriverKind.EQUIPMENT_FILTER:
            kind = "  (item)"
        return f"[{mark}] {self.label}          min {floor}     ({actual} on item){kind}"

    def with_enabled(self, enabled: bool) -> MarketPriceDriver:
        return replace(self, enabled=bool(enabled))

    def with_search_min(self, search_min: float) -> MarketPriceDriver:
        return replace(self, search_min=float(search_min), floor_policy="user_edited")


@dataclass(frozen=True)
class PriceCheckHypothesis:
    item_raw: str
    base_type: str
    item_class: str
    rarity: str | None
    slot_family: SlotFamily
    selected_drivers: tuple[MarketPriceDriver, ...]
    available_drivers: tuple[MarketPriceDriver, ...]
    ignored_mod_texts: tuple[str, ...]
    match_mode: MatchMode
    count_min: int | None
    search_basis: str
    hypothesis_source: HypothesisSource
    league: str | None = None
    floor_diagnostics: tuple[str, ...] = ()
    selection_origin: str = ""
    signature_id: str = ""

    @property
    def query_fingerprint(self) -> str:
        return hypothesis_fingerprint(self)

    def to_dict(self) -> dict[str, Any]:
        return {
            "base_type": self.base_type,
            "item_class": self.item_class,
            "rarity": self.rarity or "",
            "slot_family": self.slot_family.value,
            "selected_drivers": [row.to_dict() for row in self.selected_drivers],
            "available_drivers": [row.to_dict() for row in self.available_drivers],
            "ignored_mod_texts": list(self.ignored_mod_texts),
            "match_mode": self.match_mode.value,
            "count_min": self.count_min,
            "search_basis": self.search_basis,
            "hypothesis_source": self.hypothesis_source.value,
            "league": self.league or "",
            "query_fingerprint": self.query_fingerprint,
            "floor_diagnostics": list(self.floor_diagnostics),
            "selection_origin": self.selection_origin,
            "signature_id": self.signature_id,
        }

    def diagnostics(self) -> dict[str, Any]:
        body = hypothesis_to_search_body(self)
        validation = validate_trade2_search_body(body)
        return {
            "selected_drivers": [row.to_dict() for row in self.selected_drivers],
            "floors": {row.driver_id: row.search_min for row in self.selected_drivers},
            "trade_stat_ids": {row.driver_id: list(row.trade_stat_ids) for row in self.selected_drivers},
            "match_mode": self.match_mode.value,
            "count_min": self.count_min,
            "query_group_json": (body.get("query") or {}).get("stats") or [],
            "query_fingerprint": self.query_fingerprint,
            "local_validation": validation.to_dict(),
            "floor_diagnostics": list(self.floor_diagnostics),
        }

    def refined(
        self,
        *,
        enabled_ids: Iterable[str] | None = None,
        search_mins: dict[str, float] | None = None,
        match_mode: MatchMode | None = None,
        count_min: int | None = None,
    ) -> PriceCheckHypothesis:
        enabled = {str(value) for value in (enabled_ids or [row.driver_id for row in self.selected_drivers])}
        mins = dict(search_mins or {})
        updated: list[MarketPriceDriver] = []
        for row in self.available_drivers:
            next_row = row.with_enabled(row.driver_id in enabled)
            if row.driver_id in mins:
                next_row = next_row.with_search_min(float(mins[row.driver_id]))
            updated.append(next_row)
        selected = tuple(row for row in updated if row.enabled)
        mode = match_mode if match_mode is not None else self.match_mode
        n = count_min if count_min is not None else self.count_min
        if mode is MatchMode.ALL:
            n = None
        elif mode is MatchMode.COUNT:
            n = max(1, int(n or max(1, len(selected) - 1)))
        return replace(
            self,
            available_drivers=tuple(updated),
            selected_drivers=selected,
            match_mode=mode,
            count_min=n,
            search_basis=_search_basis(self.base_type, selected, mode, n),
            hypothesis_source=HypothesisSource.USER_REFINED,
            selection_origin="USER_REFINED",
            signature_id="",
        )


def hypothesis_with_selection(
    hypothesis: PriceCheckHypothesis,
    selected: Iterable[MarketPriceDriver],
    *,
    match_mode: MatchMode,
    count_min: int | None = None,
    hypothesis_source: HypothesisSource | None = None,
) -> PriceCheckHypothesis:
    """Rebuild a visible hypothesis from a subset of the same driver pool.

    MARKET-02C H2 is a transformation of H1, not a new taxonomy. Floors stay as they
    were on those drivers. Discovery never invents a third search.
    """
    wanted = [row for row in selected]
    wanted_ids = {row.driver_id for row in wanted}
    enabled = tuple(row.with_enabled(row.driver_id in wanted_ids) for row in hypothesis.available_drivers)
    by_id = {row.driver_id: row for row in enabled}
    ordered = tuple(by_id[row.driver_id] for row in wanted if row.driver_id in by_id)
    mode = match_mode
    n = count_min
    if mode is MatchMode.ALL:
        n = None
    elif mode is MatchMode.COUNT:
        n = max(1, int(n or max(1, len(ordered) - 1)))
    return replace(
        hypothesis,
        available_drivers=enabled,
        selected_drivers=ordered,
        match_mode=mode,
        count_min=n,
        search_basis=_search_basis(hypothesis.base_type, ordered, mode, n),
        hypothesis_source=hypothesis_source or hypothesis.hypothesis_source,
        selection_origin=(
            "AUTO_RECOVERY"
            if hypothesis_source is HypothesisSource.AUTO_RECOVERY
            else hypothesis.selection_origin
        ),
        signature_id="" if hypothesis_source is HypothesisSource.AUTO_RECOVERY else hypothesis.signature_id,
    )


def hypothesis_fingerprint(hypothesis: PriceCheckHypothesis) -> str:
    parts = [
        str(hypothesis.league or "").strip().lower(),
        str(hypothesis.item_class or "").strip().lower(),
        str(hypothesis.base_type or "").strip().lower(),
        hypothesis.match_mode.value,
        str(hypothesis.count_min or ""),
    ]
    for row in sorted(hypothesis.selected_drivers, key=lambda item: item.driver_id):
        parts.append(f"{row.driver_id}:{row.search_min:g}:{','.join(row.trade_stat_ids)}")
    return hashlib.sha256("::".join(parts).encode("utf-8")).hexdigest()[:32]


def neighbourhood_identity(hypothesis: PriceCheckHypothesis) -> str:
    families = sorted({row.family for row in hypothesis.selected_drivers})
    parts = [
        str(hypothesis.league or "").strip().lower(),
        str(hypothesis.item_class or "").strip().lower(),
        str(hypothesis.base_type or "").strip().lower(),
        str(hypothesis.rarity or "").strip().lower(),
        hypothesis.match_mode.value,
        str(hypothesis.count_min or ""),
        "|".join(families[:3]),
    ]
    return hashlib.sha256("::".join(parts).encode("utf-8")).hexdigest()[:32]


def canonical_search_min(
    family: str,
    value: float,
    *,
    exact: bool = False,
    floor_kind: FloorKind | None = None,
    affix_range: tuple[float, float] | None = None,
) -> tuple[float, str]:
    """One canonical floor stored on the driver. Visible, editable, reused by the query."""
    amount = float(value)
    if exact:
        return amount, "exact_locked"
    record = get_family(family)
    kind = floor_kind or (record.floor_kind if record else FloorKind.INTEGER_SMALL)
    bounds = affix_range or (record.affix_range if record else None)

    if kind is FloorKind.EXACT:
        return amount, "exact"
    if kind is FloorKind.EQUIPMENT:
        haircut = max(1.0, round(amount * 0.02))
        return max(1.0, round(amount - haircut, 1)), "equipment_1_3pct"
    if kind is FloorKind.PSEUDO:
        haircut = 5.0 if amount >= 20 else 2.0
        return max(1.0, round(amount - haircut, 1)), "pseudo_absolute"
    if kind is FloorKind.FLAT_LARGE:
        delta = max(5.0, amount * 0.10)
        low = bounds[0] if bounds else 0.0
        return max(low, round(amount - delta, 1)), "flat_life_10pct"
    if kind is FloorKind.BOUNDED_PERCENT:
        if bounds and bounds[1] > bounds[0]:
            span = bounds[1] - bounds[0]
            floor = round(amount - 0.15 * span)
            low = bounds[0]
            clamped = max(low, min(amount, float(floor)))
            return clamped, "bounded_pct_of_range"
        fallback = max(1.0, round(amount - 2.0, 1))
        return min(amount, fallback), "fallback_no_range"
    # INTEGER_SMALL
    span = (bounds[1] - bounds[0]) if bounds else 0.0
    delta = 2.0 if span >= 10 else 1.0
    low = bounds[0] if bounds else 0.0
    return max(low, round(amount - delta, 1)), "integer_minus_1_or_2"


def _word_in(blob: str, token: str) -> bool:
    """Token match with word boundaries. 'ring' matches Ruby Ring, not Roaring or Ringmail."""
    if not blob or not token:
        return False
    return re.search(rf"(?<![a-z0-9]){re.escape(token)}s?(?![a-z])", blob) is not None


def _any_token(blob: str, tokens: Iterable[str]) -> bool:
    return any(_word_in(blob, token) for token in tokens)


def parsed_item_class(item_raw: str) -> str:
    match = _ITEM_CLASS_RE.search(str(item_raw or ""))
    return (match.group(1) or "").strip().lower() if match else ""


def _slot_from_blob(blob: str) -> SlotFamily | None:
    text = re.sub(r"\s+", " ", str(blob or "").strip().lower())
    if not text:
        return None
    if _word_in(text, "jewelled") and _any_token(text, ("glove", "gauntlet")):
        return SlotFamily.ARMOUR
    compact = text.strip()
    if compact in _JEWEL_BASES or compact.endswith(" jewel"):
        return SlotFamily.JEWEL
    if _word_in(text, "jewel") and not _any_token(text, ("glove", "gauntlet")):
        return SlotFamily.JEWEL
    if _any_token(text, _JEWELLERY_TOKENS):
        return SlotFamily.JEWELLERY
    if _any_token(text, _BOOT_TOKENS):
        return SlotFamily.BOOTS
    if _any_token(text, _WEAPON_TOKENS):
        return SlotFamily.WEAPON
    if _any_token(text, _ARMOUR_TOKENS):
        return SlotFamily.ARMOUR
    if compact.endswith("mail") or compact.endswith("mails"):
        return SlotFamily.ARMOUR
    return None


def classify_slot(item_raw: str, *, category: str | None = None, rarity: str | None = None, base_type: str | None = None) -> SlotFamily:
    """Slot prior: parsed Item Class > verified base-family tokens > safe token fallback.

    Helmets use SlotFamily.ARMOUR (no separate HELMET enum). Circlet-family maps there.
    """
    if str(rarity or "").upper() == "UNIQUE":
        return SlotFamily.UNIQUE
    item_class = parsed_item_class(item_raw)
    for blob in (
        item_class,
        str(base_type or "").strip().lower(),
        str(category or "").strip().lower(),
    ):
        slot = _slot_from_blob(blob)
        if slot is not None:
            return slot
    header = "\n".join(str(item_raw or "").splitlines()[:6])
    return _slot_from_blob(header) or SlotFamily.OTHER


#: The live game marks provenance with a trailing tag on the mod line itself; the
#: ``Implicits: N`` header only ever appears in hand-written/exported fixtures.
_IMPLICIT_TAG_RE = re.compile(r"\(implicit\)\s*$", re.I)
_RUNE_TAG_RE = re.compile(r"\(rune\)\s*$", re.I)


def _source_kind_from_line(line: str, *, implicit: bool) -> SourceKind:
    if _IMPLICIT_TAG_RE.search(line):
        return SourceKind.IMPLICIT
    if _FRACTURED_RE.search(line):
        return SourceKind.FRACTURED
    if _CRAFTED_RE.search(line):
        return SourceKind.CRAFTED
    if _DESECRATED_RE.search(line):
        return SourceKind.DESECRATED
    if implicit:
        return SourceKind.IMPLICIT
    return SourceKind.EXPLICIT


def tagged_mod_lines(item_raw: str) -> list[tuple[str, SourceKind]]:
    lines = [line.strip() for line in str(item_raw or "").replace("\r\n", "\n").split("\n") if line.strip()]
    implicit_remaining = 0
    seen_implicits_header = False
    tagged: list[tuple[str, SourceKind]] = []
    for line in lines:
        match = _IMPLICITS_RE.match(line)
        if match:
            implicit_remaining = int(match.group(1))
            seen_implicits_header = True
            continue
        if line.startswith(("Rarity:", "Item Class:", "--------", "Requirements:", "LevelReq:", "Quality:", "Sockets:", "Rune:")):
            continue
        feature = parse_feature_from_mod(line)
        looks_mod = feature is not None or line.startswith("+") or "increased" in line.lower() or "reduced" in line.lower()
        if not looks_mod:
            continue
        implicit = seen_implicits_header and implicit_remaining > 0
        tagged.append((line, _source_kind_from_line(line, implicit=implicit)))
        if implicit:
            implicit_remaining -= 1
    return tagged


def _fmt_num(value: float) -> str:
    if float(value).is_integer():
        return str(int(value))
    return f"{value:g}"


def _driver_id(kind: DriverKind, family: str, source: SourceKind) -> str:
    return f"{kind.value}:{family}:{source.value}"


def _queryable(driver: MarketPriceDriver) -> bool:
    if driver.driver_kind is DriverKind.EQUIPMENT_FILTER:
        return bool(driver.equipment_key) and driver.actual_value > 0
    return bool(driver.trade_stat_ids) and driver.actual_value > 0


def _make_stat_driver(
    family: str,
    value: float,
    *,
    source_text: str,
    source_kind: SourceKind,
    enabled: bool,
    priority: int,
    exact: bool = False,
) -> MarketPriceDriver | None:
    record = get_family(family)
    if record is None:
        return None
    if record.driver_kind is DriverKind.EQUIPMENT_FILTER:
        return None
    ids = trade_stat_ids(family) if record.driver_kind is DriverKind.EXACT_STAT else trade_stat_ids(family)
    if family in _CRIT_CHANCE_FAMILIES:
        ids = tuple(stat_id for stat_id in ids if "3556824919" not in stat_id)
    if record.driver_kind is DriverKind.EXACT_STAT and not ids:
        return None
    floor, policy = canonical_search_min(
        family,
        value,
        exact=exact or source_kind is SourceKind.FRACTURED,
        floor_kind=record.floor_kind,
        affix_range=record.affix_range,
    )
    pseudo_id = ids[0] if record.driver_kind is DriverKind.PSEUDO else None
    return MarketPriceDriver(
        driver_id=_driver_id(record.driver_kind, family, source_kind),
        family=family,
        label=record.label,
        source_mod_text=strip_mod_markup(source_text),
        actual_value=float(value),
        search_min=float(floor),
        search_max=None,
        trade_stat_ids=ids,
        pseudo_id=pseudo_id,
        enabled=enabled,
        driver_kind=record.driver_kind,
        source_kind=source_kind,
        priority=priority,
        query_group_id=family,
        floor_policy=policy,
        component_families=record.component_families,
    )


def _make_equipment_driver(
    family: str,
    value: float,
    *,
    source_text: str,
    enabled: bool,
    priority: int,
) -> MarketPriceDriver | None:
    record = get_family(family)
    if record is None or record.driver_kind is not DriverKind.EQUIPMENT_FILTER or not record.equipment_key:
        return None
    floor, policy = canonical_search_min(family, value, floor_kind=FloorKind.EQUIPMENT)
    return MarketPriceDriver(
        driver_id=_driver_id(DriverKind.EQUIPMENT_FILTER, family, SourceKind.DERIVED),
        family=family,
        label=record.label,
        source_mod_text=source_text,
        actual_value=float(value),
        search_min=float(floor),
        search_max=None,
        trade_stat_ids=(),
        pseudo_id=None,
        enabled=enabled,
        driver_kind=DriverKind.EQUIPMENT_FILTER,
        source_kind=SourceKind.DERIVED,
        priority=priority,
        query_group_id=f"equip:{record.equipment_key}",
        floor_policy=policy,
        equipment_key=record.equipment_key,
    )


def _sum_families(features: Iterable[ComparableFeature], families: Iterable[str]) -> float:
    wanted = set(families)
    total = 0.0
    for row in features:
        if row.family in wanted:
            if row.family == "all_elemental_resistances":
                total += 3.0 * float(row.value)
            elif row.family == "all_attributes":
                total += 3.0 * float(row.value)
            else:
                total += float(row.value)
    return total


def _mid(low: float, high: float) -> float:
    return (low + high) / 2.0


def parse_equipment_properties(item_raw: str) -> dict[str, float]:
    props: dict[str, float] = {}
    phys_avg = 0.0
    elem_avg = 0.0
    aps = 0.0
    for line in str(item_raw or "").splitlines():
        stripped = line.strip()
        armour = _ARMOUR_PROP_RE.match(stripped)
        if armour:
            props["equip_ar"] = float(armour.group(1))
            continue
        evasion = _EVASION_PROP_RE.match(stripped)
        if evasion:
            props["equip_ev"] = float(evasion.group(1))
            continue
        shield = _ES_PROP_RE.match(stripped)
        if shield:
            props["equip_es"] = float(shield.group(1))
            continue
        phys = _PHYS_DMG_RE.match(stripped)
        if phys:
            phys_avg = _mid(float(phys.group(1)), float(phys.group(2)))
            continue
        aps_match = _APS_RE.match(stripped)
        if aps_match:
            aps = float(aps_match.group(1))
            continue
        elem = _ELEM_DMG_RE.match(stripped)
        if elem:
            total = 0.0
            for low, high in _RANGE_RE.findall(elem.group(1)):
                total += _mid(float(low), float(high))
            elem_avg = total
    if aps > 0:
        if phys_avg > 0:
            props["equip_pdps"] = round(phys_avg * aps, 1)
        if elem_avg > 0:
            props["equip_edps"] = round(elem_avg * aps, 1)
        total_dps = (phys_avg + elem_avg) * aps
        if total_dps > 0:
            props["equip_dps"] = round(total_dps, 1)
    return props


def extract_all_drivers(item_raw: str, *, category: str | None = None) -> tuple[tuple[MarketPriceDriver, ...], tuple[str, ...], tuple[ComparableFeature, ...]]:
    features = build_features(item_raw, category=category)
    tagged = tagged_mod_lines(item_raw)
    drivers: list[MarketPriceDriver] = []
    seen: set[str] = set()
    parsed_texts = {normalize_mod_text(row.source_text) for row in features}
    ignored: list[str] = []
    for text, kind in tagged:
        cleaned = strip_mod_markup(text)
        feature = parse_feature_from_mod(text, category=category)
        if feature is None:
            ignored.append(cleaned)
            continue
        driver = _make_stat_driver(
            feature.family,
            feature.value,
            source_text=cleaned,
            source_kind=kind,
            enabled=False,
            priority=0,
            exact=kind is SourceKind.FRACTURED,
        )
        if driver is None:
            ignored.append(cleaned)
            continue
        if driver.driver_id in seen:
            continue
        seen.add(driver.driver_id)
        drivers.append(driver)

    # Pseudos: only when the item actually has contributing families.
    ele_total = _sum_families(features, ("fire_resistance", "cold_resistance", "lightning_resistance", "all_elemental_resistances"))
    chaos_total = _sum_families(features, ("chaos_resistance",))
    attr_total = _sum_families(features, ("strength", "dexterity", "intelligence", "all_attributes"))
    life_total = _sum_families(features, ("maximum_life",))
    mana_total = _sum_families(features, ("maximum_mana",))
    es_total = _sum_families(features, ("maximum_energy_shield", "energy_shield"))
    ele_contributors = sum(1 for row in features if row.family in {"fire_resistance", "cold_resistance", "lightning_resistance", "all_elemental_resistances"})
    attr_contributors = sum(1 for row in features if row.family in {"strength", "dexterity", "intelligence", "all_attributes"})

    def add_pseudo(family: str, value: float, components: tuple[str, ...], priority: int) -> None:
        if value <= 0:
            return
        driver = _make_stat_driver(
            family,
            value,
            source_text=f"{family.replace('_', ' ')} from {', '.join(components)}",
            source_kind=SourceKind.DERIVED,
            enabled=False,
            priority=priority,
        )
        if driver is None or driver.driver_id in seen:
            return
        seen.add(driver.driver_id)
        drivers.append(driver)

    if ele_contributors >= 2:
        add_pseudo("total_elemental_resistance", ele_total, ("fire_resistance", "cold_resistance", "lightning_resistance"), 80)
    if ele_contributors + (1 if chaos_total else 0) >= 2 and chaos_total:
        add_pseudo("total_resistance", ele_total + chaos_total, ("elemental", "chaos_resistance"), 85)
    if attr_contributors >= 2:
        add_pseudo("total_attributes", attr_total, ("strength", "dexterity", "intelligence"), 40)
    if life_total > 0:
        add_pseudo("total_life", life_total, ("maximum_life",), 20)
    if mana_total > 0:
        add_pseudo("total_mana", mana_total, ("maximum_mana",), 10)
    if es_total > 0:
        add_pseudo("total_energy_shield", es_total, ("maximum_energy_shield",), 20)

    for family, value in parse_equipment_properties(item_raw).items():
        driver = _make_equipment_driver(
            family,
            value,
            source_text=f"{family} {value:g}",
            enabled=False,
            priority=90,
        )
        if driver is None or driver.driver_id in seen:
            continue
        seen.add(driver.driver_id)
        drivers.append(driver)

    for text, _kind in tagged:
        cleaned = strip_mod_markup(text)
        # Provenance tags never change what a mod does, so compare on the untagged
        # form — otherwise a contributing "(rune)"/"(implicit)" mod is reported as ignored.
        if normalize_mod_text(cleaned) not in parsed_texts and cleaned not in ignored:
            ignored.append(cleaned)
    return tuple(drivers), tuple(dict.fromkeys(ignored)), features


def _driver_preference_key(driver: MarketPriceDriver) -> tuple[int, float, str]:
    """Prefer explicit rare affixes over base implicits; higher roll wins within a tier."""
    return (
        _SOURCE_KIND_RANK.get(driver.source_kind, 9),
        -float(driver.actual_value or 0.0),
        driver.driver_id,
    )


def _best_driver_for_family(drivers: Iterable[MarketPriceDriver], family: str) -> MarketPriceDriver | None:
    candidates = [row for row in drivers if row.family == family and _queryable(row)]
    if not candidates:
        return None
    return min(candidates, key=_driver_preference_key)


def _pick(drivers: Iterable[MarketPriceDriver], families: Iterable[str], *, limit: int) -> list[MarketPriceDriver]:
    wanted = list(families)
    picked: list[MarketPriceDriver] = []
    used_families: set[str] = set()
    for family in wanted:
        row = _best_driver_for_family(drivers, family)
        if row is None or family in used_families:
            continue
        picked.append(row)
        used_families.add(family)
        if len(picked) >= limit:
            break
    return picked


def _resistance_driver_blocked(
    driver: MarketPriceDriver,
    *,
    selected_families: set[str],
    available: Iterable[MarketPriceDriver],
) -> bool:
    """Do not spend a driver slot on base implicit res when explicit or pseudo covers it."""
    if driver.family not in _RESISTANCE_FAMILIES:
        return False
    if driver.source_kind is not SourceKind.IMPLICIT:
        return False
    if driver.family in selected_families:
        return True
    if selected_families & _PSEUDO_RESISTANCE_FAMILIES:
        return True
    if _best_driver_for_family(available, driver.family) is not driver:
        return True
    return False


def driver_floor_invariant_holds(driver: MarketPriceDriver) -> bool:
    """Search floor must not demand a strictly better roll than the represented target."""
    if driver.driver_kind is DriverKind.PSEUDO:
        return True
    if driver.driver_kind is DriverKind.EQUIPMENT_FILTER:
        return float(driver.search_min) <= float(driver.actual_value)
    if driver.floor_policy in {"exact", "exact_locked"}:
        return float(driver.search_min) == float(driver.actual_value)
    return float(driver.search_min) <= float(driver.actual_value)


def assert_driver_floors_valid(drivers: Iterable[MarketPriceDriver]) -> list[str]:
    violations: list[str] = []
    for row in drivers:
        if not driver_floor_invariant_holds(row):
            violations.append(
                f"{row.driver_id}: search_min {row.search_min:g} > actual_value {row.actual_value:g}"
            )
    return violations


def _select_boots_drivers(available: Iterable[MarketPriceDriver]) -> list[MarketPriceDriver]:
    """Boots market identity: MS + life + resistance/defence — not base ES over rare affixes."""
    selected = _pick(available, BOOTS_PRIMARY, limit=3)
    selected_families = {row.family for row in selected}
    if len(selected) < 3 and not (selected_families & _PSEUDO_RESISTANCE_FAMILIES):
        selected.extend(
            _pick(
                available,
                ("fire_resistance", "cold_resistance", "lightning_resistance", "chaos_resistance"),
                limit=3 - len(selected),
            )
        )
        selected_families = {row.family for row in selected}
    if len(selected) < 2:
        local = [
            row
            for row in available
            if row.family in {"equip_ar", "equip_ev", "equip_es"} and _queryable(row)
        ]
        if local:
            selected.append(max(local, key=lambda row: row.actual_value))
    filtered: list[MarketPriceDriver] = []
    seen_families: set[str] = set()
    for row in selected:
        if row.family in seen_families:
            continue
        if _resistance_driver_blocked(row, selected_families=seen_families, available=available):
            continue
        filtered.append(row)
        seen_families.add(row.family)
        if len(filtered) >= 3:
            break
    return filtered[:3]


def _enable(rows: Iterable[MarketPriceDriver], selected: Iterable[MarketPriceDriver]) -> tuple[MarketPriceDriver, ...]:
    enabled_ids = {row.driver_id for row in selected}
    return tuple(row.with_enabled(row.driver_id in enabled_ids) for row in rows)


def auto_select_drivers(
    item_raw: str,
    *,
    category: str | None = None,
    rarity: str | None = None,
    base_type: str | None = None,
) -> tuple[tuple[MarketPriceDriver, ...], MatchMode, int | None, SlotFamily, tuple[str, ...]]:
    slot = classify_slot(item_raw, category=category, rarity=rarity, base_type=base_type)
    available, ignored, _features = extract_all_drivers(item_raw, category=category)
    if slot is SlotFamily.UNIQUE:
        return available, MatchMode.ALL, None, slot, ignored

    selected: list[MarketPriceDriver] = []
    mode = MatchMode.ALL
    count_min: int | None = None

    if slot is SlotFamily.JEWEL:
        useful = [row for row in available if row.family in JEWEL_USEFUL and _queryable(row) and row.driver_kind is DriverKind.EXACT_STAT]
        selected = useful[:6]
        if len(selected) >= 2:
            mode = MatchMode.COUNT
            count_min = min(2, len(selected))
        elif len(selected) == 1:
            mode = MatchMode.ALL
        else:
            selected = []
    elif slot is SlotFamily.JEWELLERY:
        selected.extend(_pick(available, ("maximum_life",), limit=1))
        selected.extend(
            _pick(
                available,
                (
                    "cast_speed",
                    "lightning_spell_skills",
                    "spell_damage",
                    "lightning_damage",
                    "fire_damage",
                    "cold_damage",
                    "attack_speed",
                    "spell_critical_hit_chance",
                    "critical_strike_chance",
                ),
                limit=2,
            )
        )
        selected.extend(
            _pick(
                available,
                ("total_resistance", "total_elemental_resistance", "chaos_resistance"),
                limit=max(0, 3 - len(selected)),
            )
        )
        if len(selected) < 2:
            selected.extend(
                _pick(
                    available,
                    ("fire_resistance", "cold_resistance", "lightning_resistance", "strength", "dexterity", "intelligence", "all_attributes"),
                    limit=max(0, 3 - len(selected)),
                )
            )
        selected = selected[:3]
        if len(selected) >= 3:
            mode = MatchMode.COUNT
            count_min = 2
        elif len(selected) >= 1:
            mode = MatchMode.ALL
    elif slot is SlotFamily.WEAPON:
        local = [row for row in available if row.family in {"equip_dps", "equip_pdps", "equip_edps"} and _queryable(row)]
        if local:
            preferred = next((row for row in local if row.family == "equip_dps"), local[0])
            selected.append(preferred)
        selected.extend(_pick(available, WEAPON_GLOBAL, limit=2 if selected else 3))
        selected = selected[:3]
        mode = MatchMode.ALL
    elif slot is SlotFamily.BOOTS:
        selected = _select_boots_drivers(available)
        mode = MatchMode.ALL
    elif slot is SlotFamily.ARMOUR:
        local = [row for row in available if row.family in {"equip_ar", "equip_ev", "equip_es"} and _queryable(row)]
        if local:
            selected.append(max(local, key=lambda row: row.actual_value))
        selected.extend(_pick(available, ARMOUR_PRIMARY, limit=2 if selected else 3))
        if len(selected) < 2:
            selected.extend(
                _pick(
                    available,
                    ("fire_resistance", "cold_resistance", "lightning_resistance", "chaos_resistance", "armour", "evasion"),
                    limit=2,
                )
            )
        selected = selected[:3]
        mode = MatchMode.ALL
    else:
        selected = _pick(
            available,
            ("maximum_life", "total_elemental_resistance", "cast_speed", "spell_damage"),
            limit=2,
        )

    queryable_selected = [row for row in selected if _queryable(row)]
    deduped: list[MarketPriceDriver] = []
    seen_families: set[str] = set()
    for row in queryable_selected:
        if row.family in seen_families:
            continue
        seen_families.add(row.family)
        deduped.append(row)
    enabled = _enable(available, deduped[:3])
    return enabled, mode, count_min, slot, ignored


def _search_basis(base_type: str, selected: Iterable[MarketPriceDriver], mode: MatchMode, count_min: int | None) -> str:
    labels = [row.label for row in selected]
    if not labels:
        return f"{base_type} · base only" if base_type else "base only"
    joined = " + ".join(labels[:3])
    if mode is MatchMode.COUNT and count_min:
        return f"{base_type}, {count_min} of {len(tuple(selected))} ({joined})"
    return f"{base_type}, {joined}" if base_type else joined


def build_auto_hypothesis(
    item_raw: str,
    *,
    league: str | None = None,
) -> PriceCheckHypothesis:
    raw = RawItemInput.from_text(item_raw)
    meta = parse_lightweight_metadata(raw)
    available, match_mode, count_min, slot, ignored = auto_select_drivers(
        item_raw,
        category=meta.category,
        rarity=meta.rarity,
        base_type=meta.base_type,
    )
    selected = tuple(row for row in available if row.enabled)
    floors = tuple(f"{row.family}:{row.floor_policy}={row.search_min:g}" for row in selected)
    return PriceCheckHypothesis(
        item_raw=item_raw,
        base_type=str(meta.base_type or ""),
        item_class=str(meta.category or meta.base_type or ""),
        rarity=meta.rarity,
        slot_family=slot,
        selected_drivers=selected,
        available_drivers=available,
        ignored_mod_texts=ignored,
        match_mode=match_mode,
        count_min=count_min,
        search_basis=_search_basis(str(meta.base_type or ""), selected, match_mode, count_min),
        hypothesis_source=HypothesisSource.AUTO_PRIOR,
        league=league,
        floor_diagnostics=floors,
        selection_origin="AUTO_PRIOR",
        signature_id="",
    )


def estimate_state_for(hypothesis: PriceCheckHypothesis) -> EstimateState:
    if not hypothesis.selected_drivers:
        return EstimateState.BASE_MARKET_ESTIMATE
    return EstimateState.ASSISTED_ESTIMATE


def _stat_filter(driver: MarketPriceDriver, stat_id: str) -> dict[str, Any]:
    return {
        "id": stat_id,
        "value": {"min": driver.search_min},
        "disabled": False,
    }


def _count_group(filters: list[dict[str, Any]], minimum: int) -> dict[str, Any]:
    return {
        "type": "count",
        "value": {"min": max(1, min(int(minimum), len(filters)))},
        "filters": filters,
    }


def hypothesis_stat_groups(hypothesis: PriceCheckHypothesis) -> list[dict[str, Any]]:
    selected = [row for row in hypothesis.selected_drivers if _queryable(row) and row.driver_kind is not DriverKind.EQUIPMENT_FILTER]
    if not selected:
        return []
    if hypothesis.match_mode is MatchMode.COUNT and len(selected) >= 2:
        filters = []
        for row in selected:
            primary = row.trade_stat_ids[0] if row.trade_stat_ids else primary_trade_stat_id(row.family)
            if not primary:
                continue
            filters.append(_stat_filter(row, primary))
        if not filters:
            return []
        return [_count_group(filters, int(hypothesis.count_min or max(1, len(filters) - 1)))]

    groups: list[dict[str, Any]] = []
    and_filters: list[dict[str, Any]] = []
    for row in selected:
        ids = tuple(row.trade_stat_ids)
        if not ids:
            continue
        if len(ids) == 1:
            and_filters.append(_stat_filter(row, ids[0]))
        else:
            # Alias-OR: COUNT min 1 over prefix variants of the same hash.
            groups.append(_count_group([_stat_filter(row, stat_id) for stat_id in ids], 1))
    if and_filters:
        groups.insert(0, {"type": "and", "filters": and_filters})
    return groups


def hypothesis_equipment_filters(hypothesis: PriceCheckHypothesis) -> dict[str, Any]:
    filters: dict[str, Any] = {}
    for row in hypothesis.selected_drivers:
        if row.driver_kind is DriverKind.EQUIPMENT_FILTER and row.equipment_key:
            filters[row.equipment_key] = {"min": row.search_min}
    return filters


def _category_option(hypothesis: PriceCheckHypothesis) -> str | None:
    blob = f"{hypothesis.item_class} {hypothesis.base_type}".lower()
    if hypothesis.slot_family is SlotFamily.JEWEL:
        return "jewel"
    if _word_in(blob, "ring"):
        return "accessory.ring"
    if _word_in(blob, "amulet"):
        return "accessory.amulet"
    if _word_in(blob, "belt"):
        return "accessory.belt"
    if _word_in(blob, "wand"):
        return "weapon.wand"
    if _word_in(blob, "staff"):
        return "weapon.staff"
    if _word_in(blob, "bow"):
        return "weapon.bow"
    if _any_token(blob, _HELMET_TOKENS):
        return "armour.helmet"
    if _any_token(blob, ("glove", "gauntlet")):
        return "armour.gloves"
    if _any_token(blob, _BOOT_TOKENS) or hypothesis.slot_family is SlotFamily.BOOTS:
        return "armour.boots"
    if hypothesis.slot_family is SlotFamily.ARMOUR:
        return "armour.chest"
    if hypothesis.slot_family is SlotFamily.WEAPON:
        return "weapon.one"
    return None


def hypothesis_to_search_body(hypothesis: PriceCheckHypothesis) -> dict[str, Any]:
    query: dict[str, Any] = {"status": {"option": "available"}}
    rarity = _RARITY_MAP.get(str(hypothesis.rarity or "").upper())
    if hypothesis.slot_family is SlotFamily.JEWEL:
        # Prefer category so other jewel bases can match the useful-mod COUNT.
        type_filters: dict[str, Any] = {"category": {"option": "jewel"}}
        if rarity:
            type_filters["rarity"] = {"option": rarity}
        query["filters"] = {"type_filters": {"filters": type_filters}}
    else:
        if hypothesis.base_type:
            query["type"] = hypothesis.base_type
        if hypothesis.rarity and str(hypothesis.rarity).upper() == "UNIQUE" and hypothesis.item_class:
            # Unique SKU lookup keeps name when the clipboard had one.
            pass
        type_filters = {}
        if rarity:
            type_filters["rarity"] = {"option": rarity}
        equipment = hypothesis_equipment_filters(hypothesis)
        filters: dict[str, Any] = {}
        if type_filters:
            filters["type_filters"] = {"filters": type_filters}
        if equipment:
            filters["equipment_filters"] = {"filters": equipment}
        if filters:
            query["filters"] = filters

    stats = hypothesis_stat_groups(hypothesis)
    if stats:
        query["stats"] = stats
    return {"query": query, "sort": {"price": "asc"}}


def dump_hypothesis_json(hypothesis: PriceCheckHypothesis) -> str:
    return json.dumps(hypothesis_to_search_body(hypothesis), indent=2, sort_keys=True)
