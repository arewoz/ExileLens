"""Generated legal item corpus (FILTER-08D), independent of every filter visibility decision.

The generator enumerates controlled combinations over VERIFIED base data and states, for each, whether it is LEGAL, INVALID or
AMBIGUOUS / NOT ESTABLISHED. It never imports rules, profiles, tiers, the opportunity model or a preview/simulator, and it carries no
expected Show/Hide: the only expectation it records is ``protected`` — a category-level policy ("these item kinds must never be
hidden") that comes from the item's KIND alone.

Legality facts used (each cites its source):
  * a base cannot drop below its required level  -> item level < required level is INVALID (PoB2 base requirement)
  * item level is 1..100                          -> outside is INVALID
  * equipment quality is 0..20 (Normal/Magic/Rare)-> negative INVALID; 21..30 AMBIGUOUS (needs corruption/special sources)
  * UnidentifiedItemTier exists only for unidentified Rare items, 1..5 -> on Normal/Magic or >5 INVALID; its relation to item level
    is not established in the pinned data -> tier > 0 is AMBIGUOUS
  * Unique rarity needs a real unique item; an arbitrary base + Unique is AMBIGUOUS (kept: protection is rarity-based)
  * waystone tiers 1..16, intrinsic defences always equal the base's verified values
"""
from __future__ import annotations

import random
from collections import Counter
from dataclasses import dataclass
from enum import Enum
from typing import Iterator

from exilelens.filters.preview import PreviewItem
from exilelens.filters.verified_bases import PINNED_SPECIAL_BASES, load_base_properties, native_class

ITEM_LEVELS = (1, 20, 40, 55, 60, 65, 68, 70, 72, 75, 78, 80, 82, 84, 85, 86, 88, 100)
PROTECTED_CLASSES = ("Stackable Currency", "Omen", "Pinnacle Keys", "Map Fragments", "Augment", "Tablet", "Quest Items")


class Legality(str, Enum):
    LEGAL = "LEGAL"
    INVALID = "INVALID"
    AMBIGUOUS = "AMBIGUOUS / NOT ESTABLISHED"


@dataclass(frozen=True)
class CorpusCase:
    id: str
    item: PreviewItem
    legality: Legality
    reason: str
    kind: str                 # equipment | currency | waystone | special | unique
    protected: bool           # by KIND: must never be hidden by any filter


def classify_equipment(base: str, rarity: str, level: int, quality: int, unid_tier: int) -> tuple[Legality, str]:
    """Pure legality rules for one equipment item. No filter logic."""
    record = load_base_properties().get(base)
    if record is None:
        return Legality.INVALID, "base is not in the verified catalog"
    if not 1 <= level <= 100:
        return Legality.INVALID, "item level outside 1..100"
    if level < int(record["required_level"]):
        return Legality.INVALID, f"item level {level} below the base's required level {record['required_level']}"
    if rarity not in ("Normal", "Magic", "Rare", "Unique"):
        return Legality.INVALID, "unknown rarity"
    if quality < 0:
        return Legality.INVALID, "negative quality"
    if unid_tier < 0 or unid_tier > 5:
        return Legality.INVALID, "UnidentifiedItemTier outside 0..5"
    if unid_tier > 0 and rarity != "Rare":
        return Legality.INVALID, "only unidentified Rare items have an UnidentifiedItemTier"
    if rarity == "Unique":
        return Legality.AMBIGUOUS, "a Unique needs a real unique item on this base; protection is rarity-based"
    if quality > 20:
        return Legality.AMBIGUOUS, "quality above 20 needs special sources not established in the pinned data"
    if unid_tier > 0:
        return Legality.AMBIGUOUS, "the relation between UnidentifiedItemTier and item level is not established"
    return Legality.LEGAL, "base, item level, rarity and quality are consistent"


def _equipment(base: str, rarity: str, level: int, quality: int, tier: int) -> CorpusCase:
    record = load_base_properties()[base]
    legality, reason = classify_equipment(base, rarity, level, quality, tier)
    item = PreviewItem(f"{base} [{rarity} i{level} q{quality} u{tier}]", "FILTER-08D generated", native_class(base) or "", base, rarity,
                       item_level=level, quality=quality, unidentified_item_tier=tier, base_energy_shield=record["energy_shield"],
                       base_armour=record["armour"], base_evasion=record["evasion"])
    return CorpusCase(f"eq|{base}|{rarity}|{level}|{quality}|{tier}", item, legality, reason, "unique" if rarity == "Unique" else "equipment",
                      protected=rarity == "Unique")


def equipment_cases(*, include_invalid: bool = True) -> Iterator[CorpusCase]:
    """Every equipment base x rarity x item level x quality x unidentified tier (full enumeration, ~100k cases)."""
    for base in sorted(load_base_properties()):
        if native_class(base) is None:
            continue
        required = int(load_base_properties()[base]["required_level"])
        levels = sorted({lv for lv in ITEM_LEVELS if lv >= required} | {required, max(1, required - 1)})
        for rarity in ("Normal", "Magic", "Rare"):
            for level in levels:
                qualities = (0, 20) if rarity == "Normal" else (0,)
                tiers = (0, 3, 5) if rarity == "Rare" else (0,)
                for quality in qualities:
                    for tier in tiers:
                        case = _equipment(base, rarity, level, quality, tier)
                        if include_invalid or case.legality != Legality.INVALID:
                            yield case
        yield _equipment(base, "Unique", max(required, 70), 0, 0)
        yield _equipment(base, "Normal", 101, 0, 0)                      # INVALID: item level out of range
        yield _equipment(base, "Magic", 82, -1, 0)                       # INVALID: negative quality
        yield _equipment(base, "Magic", max(required, 70), 0, 2)         # INVALID: tier on a Magic item


def special_cases() -> Iterator[CorpusCase]:
    """Protected item kinds. Names come from the pinned GGG currency list or are native class probes."""
    for name in sorted(PINNED_SPECIAL_BASES):
        yield CorpusCase(f"cur|{name}", PreviewItem(name, "FILTER-08D generated", "Stackable Currency", name), Legality.LEGAL,
                         "named currency from the pinned GGG item-filter list", "currency", True)
    for cls, example in (("Stackable Currency", "Exalted Orb"), ("Stackable Currency", "Orb of Transmutation"), ("Omen", "Omen of Chance"),
                         ("Pinnacle Keys", "Pinnacle Key"), ("Map Fragments", "Map Fragment"), ("Augment", "Augment"),
                         ("Tablet", "Abyss Precursor Tablet"), ("Quest Items", "Quest Item")):
        yield CorpusCase(f"special|{cls}|{example}", PreviewItem(example, "FILTER-08D generated", cls), Legality.AMBIGUOUS,
                         "generic class probe, not an observed named item", "special", True)
    for tier in range(0, 18):
        for rarity in ("Normal", "Magic", "Rare"):
            legality = Legality.LEGAL if 1 <= tier <= 16 else Legality.INVALID
            yield CorpusCase(f"waystone|{tier}|{rarity}", PreviewItem(f"Waystone (Tier {tier})", "FILTER-08D generated", "Waystones",
                                                                       rarity=rarity, waystone_tier=tier),
                             legality, "waystone tier 1..16" if legality == Legality.LEGAL else "waystone tier outside 1..16", "waystone",
                             protected=tier >= 15)


def sample(n: int, seed: int = 1, *, legality: tuple[Legality, ...] = (Legality.LEGAL, Legality.AMBIGUOUS)) -> list[CorpusCase]:
    """Deterministic stratified sample: equal share per native class and rarity, plus every special/waystone case."""
    rng = random.Random(seed)
    buckets: dict[tuple[str, str], list[CorpusCase]] = {}
    for case in equipment_cases(include_invalid=False):
        if case.legality in legality:
            buckets.setdefault((case.item.item_class, case.item.rarity), []).append(case)
    specials = [c for c in special_cases() if c.legality in legality or c.legality == Legality.AMBIGUOUS]
    per_bucket = max(1, (n - len(specials)) // max(1, len(buckets)))
    chosen: list[CorpusCase] = []
    for key in sorted(buckets):
        pool = buckets[key]
        chosen.extend(rng.sample(pool, min(per_bucket, len(pool))))
    return chosen + specials


def census() -> dict[str, object]:
    """Counts of the FULL enumeration (this is the corpus size the harness samples from)."""
    by_legality: Counter[str] = Counter()
    by_kind: Counter[str] = Counter()
    by_class: Counter[str] = Counter()
    for case in equipment_cases():
        by_legality[case.legality.value] += 1
        by_kind[case.kind] += 1
        by_class[case.item.item_class] += 1
    specials = list(special_cases())
    for case in specials:
        by_legality[case.legality.value] += 1
        by_kind[case.kind] += 1
    return {"total": sum(by_legality.values()), "by_legality": dict(by_legality), "by_kind": dict(by_kind),
            "equipment_by_native_class": dict(sorted(by_class.items())), "special_and_waystone_cases": len(specials),
            "protected_cases": sum(1 for c in specials if c.protected)}
