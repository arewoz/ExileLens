"""Independent oracle for the profile matrix: which rows an item belongs to and which state the matrix gives it (profile system V2).

It is derived from `profile_policy.ROW_DEFINITIONS` and the verified catalog, NOT from the generated rules, so a test can ask "does the generated
filter give this item the state the approved matrix says?". The generator and this module are two implementations of the same definitions.

Scope: the general filter (no build). The BUILD lane adds `build_relevant_base` and the build-irrelevant modifier on top of it
(`profile_policy.build_modified`); both are tested separately with a measured build.
"""
from __future__ import annotations

from dataclasses import dataclass

from exilelens.filters import crafting_intel as ci
from exilelens.filters import currency_tiers
from exilelens.filters import profile_policy as pp
from exilelens.filters.preview import PreviewItem

JEWELLERY = frozenset({"Rings", "Amulets", "Belts"})
SPECIAL_CLASSES = frozenset({"Omen", "Pinnacle Keys", "Map Fragments"})
GEM_CLASSES = frozenset({"Uncut Skill Gems", "Uncut Support Gems", "Uncut Spirit Gems"})
TOP_ILVL, TOP_QUALITY = 82, 10
GEM_TOP_LEVEL = 19
GEM_AREA_APPROPRIATE = {14: 65, 15: 69, 16: 73, 17: 77, 18: 79}
EXCEPTIONAL_UNIQUE_QUALITY = 21
UNKNOWN_ROW = "unknown_new_items"
KNOWN_GENERIC_ROW = "known_generic_fallback"     # fixed SHOW for a verified base of a class without a matrix row (rules.KNOWN_GENERIC_ROW)


@dataclass(frozen=True)
class Classification:
    rows: tuple[str, ...]            # every matrix row the item belongs to (UNKNOWN_ROW alone when none does)
    state: str                       # the most visible state among them at the requested level and context
    campaign: bool


def _currency_row(name: str) -> str | None:
    for tier in currency_tiers.TIERS:
        if name in tier.names:
            return tier.row
    return None


def _tier_sets():
    from exilelens.filters.rules import generic_sets
    return generic_sets()


def waystone_rows(tier: int, area_level: int) -> list[str]:
    rows = []
    far_max = 0
    for lo, hi, gap in pp.WAYSTONE_BANDS:
        if area_level >= lo and (hi is None or area_level <= hi):
            far_max = gap
            break
    rows.append("waystones_far_below_area" if tier <= far_max else "waystones_near_area")
    if 11 <= tier <= 14:
        rows.append("waystones_t11_14")
    if tier >= 15:
        rows.append("waystones_t15_16")
    return rows


def rows_of(item: PreviewItem) -> list[str]:
    """Matrix rows of one item (general filter). Empty = unclassified."""
    from exilelens.filters.opportunity import ROLE_BY_CLASS
    from exilelens.filters.verified_bases import native_class
    cls = item.item_class
    base = item.base_type or item.name
    rarity = item.rarity
    rows: list[str] = []
    from exilelens.filters.verified_bases import SPECIAL_BASES
    # a declared currency-ladder name is currency under its REAL native class (the native registry: Vaal Siphoner is `Incubators`)
    if cls == "Stackable Currency" or (cls and SPECIAL_BASES.get(base) == cls and _currency_row(base)):
        row = _currency_row(base)
        return [row] if row else []
    if cls in SPECIAL_CLASSES:
        return ["special_endgame"]
    if cls == "Augment":
        return ["augments_top"]
    if cls == "Tablet":
        return ["tablets"]
    if cls in ("Quest Items", "Instance Local Items"):
        return ["quest_items"]
    if cls == "Waystones":
        return waystone_rows(item.waystone_tier, item.area_level) if item.waystone_tier >= 1 else []
    if cls in GEM_CLASSES:
        level = item.gem_level
        top = level >= GEM_TOP_LEVEL or (level in GEM_AREA_APPROPRIATE and item.area_level <= GEM_AREA_APPROPRIATE[level])
        return ["gems_uncut_top" if top else "gems_uncut_other"]
    if rarity == "Unique":
        exceptional = item.corrupted or item.mirrored or item.quality >= EXCEPTIONAL_UNIQUE_QUALITY
        if exceptional:
            rows.append("uniques_top")
        elif native_class(base):
            rows.append("uniques_generic")
    if cls == "Jewels":
        if rarity == "Rare":
            rows.append("jewels_rare")
        elif rarity in ("Normal", "Magic"):
            rows.append("jewels_magic")
        return rows
    if cls in ("Charms", "Flasks"):
        prefix = "charms" if cls == "Charms" else "flasks"
        top = item.quality >= TOP_QUALITY or item.item_level >= TOP_ILVL
        rows.append(f"{prefix}_top" if top else f"{prefix}_other")
        return rows
    native = native_class(base)
    if native in ROLE_BY_CLASS and rarity in ("Normal", "Magic", "Rare"):
        sets = _tier_sets()
        jewellery = native in JEWELLERY
        if jewellery:
            if rarity == "Rare":
                rows.append("jewellery_rare")
            else:
                rows.append("jewellery_premium_base" if base in sets.top_jw else "jewellery_low_generic")
        else:
            top = base in sets.top_eq
            if rarity == "Rare":
                rows.append("eq_rare_top" if top else "eq_rare_low")
                if top and item.item_level >= TOP_ILVL:
                    rows.append("eq_rare_top_ilvl82")
            else:
                rows.append("eq_normal_top" if top else "eq_normal_low")
        if rarity == "Rare" and item.unidentified_item_tier >= 5:
            rows.append("eq_rare_unid_t5")
        elif rarity == "Rare" and 3 <= item.unidentified_item_tier <= 4:
            rows.append("eq_rare_unid_t3_4")
        if not (item.corrupted or item.mirrored):
            craft = ci.craft_row(ci.assess(base), rarity, item.item_level)
            if craft:
                rows.append(craft)
        elif ci.assess(base).level in (ci.CraftLevel.LOW, ci.CraftLevel.UNKNOWN):
            craft = ci.craft_row(ci.assess(base), rarity, item.item_level)
            if craft:
                rows.append(craft)
    return rows


def classify(item: PreviewItem, level: str) -> Classification:
    rows = rows_of(item)
    campaign = item.area_level <= pp.CAMPAIGN_MAX_AREA_LEVEL
    if not rows:
        from exilelens.filters.verified_bases import native_class
        # KNOWN_GENERIC: a verified base in its own native class that no matrix row owns is known, not unknown: a fixed SHOW
        base = item.base_type or item.name
        if native_class(base) and native_class(base) == item.item_class:
            return Classification((KNOWN_GENERIC_ROW,), "SHOW", campaign)
        return Classification((UNKNOWN_ROW,), "SHOW+", campaign)
    pick = pp.campaign_state if campaign else (lambda row: pp.state(row, level))
    # a waystone row is already area-relative: in the campaign its Relaxed column applies like every other row
    return Classification(tuple(rows), pp.most_visible(pick(row) for row in rows), campaign)


def expected_state(item: PreviewItem, level: str) -> str:
    return classify(item, level).state


def matrix_hides(item: PreviewItem, level: str) -> bool:
    """True when the APPROVED matrix gives this item the state HIDE at ``level`` (a hide of a 'protected' kind is then policy, not an error)."""
    return classify(item, level).state == "HIDE"
