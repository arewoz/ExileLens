"""Random preview scenes drawn from a large pool (preview only: nothing here feeds filter generation).

The curated scenes (Showcase, Real Game Cluster, Hero Cluster, ...) are fixed regression references: Reroll only moves their labels. The
"Random Drops" scene instead draws a NEW set of drops for every seed from the whole verified catalog:

  * equipment: every GROUND-VALID base of the pinned PoB2 catalog (native registry: PoB-synthetic / non-ground bases are never drawn), rarity, item level, quality and unidentified tier, each state
    checked with ``legal_corpus.classify_equipment`` (INVALID states are never drawn; AMBIGUOUS ones such as Unique / unidentified tiers are
    allowed because they are real drop states whose details are merely not established in the pinned data);
  * currency: every exact name the repository knows (the currency ladder + the curated scenes), weighted by its ladder tier, random stacks;
  * waystones 1-16, uncut skill / support / spirit gems, omens, fragments, keys, tablets and augments.

The weights are PREVIEW weights chosen so a scene looks like a busy endgame floor; they are documented here and are not drop rates.
"""
from __future__ import annotations

import random
from functools import lru_cache

from exilelens.filters.preview import HERO_CLUSTER_ITEMS, PREVIEW_ITEMS, REAL_GAME_ITEMS, SHOWCASE_ITEMS, PreviewItem

RANDOM_SCENE = "Random Drops"
DROPS_PER_SCENE = 30

KIND_WEIGHTS = {"equipment": 56, "currency": 28, "waystone": 7, "gem": 4, "special": 2.5, "tablet": 1.5, "augment": 1.0}
RARITY_WEIGHTS = {"Normal": 28, "Magic": 44, "Rare": 25, "Unique": 3}
# currency ladder tier -> preview weight (the apex is rare on purpose, but appears often enough to be seen across a few rerolls)
CURRENCY_TIER_WEIGHTS = {"CURRENCY_UTILITY": 40, "CURRENCY_LOW": 22, "CURRENCY_VALUABLE": 20, "CURRENCY_CRAFT": 6, "CURRENCY_ENHANCED": 6,
                         "CURRENCY_PREMIUM": 4, "CURRENCY_HERO": 1.2}
ITEM_LEVELS = (45, 55, 60, 65, 68, 70, 72, 74, 75, 76, 78, 79, 80, 81, 82, 82, 83, 84, 84, 85, 86)
SPECIALS = (("Omen of Chance", "Omen"), ("Idol of Estazunti", "Map Fragments"), ("Map Fragment", "Map Fragments"), ("Pinnacle Key", "Pinnacle Keys"))
GEMS = (("Uncut Skill Gem", "Uncut Skill Gems"), ("Uncut Support Gem", "Uncut Support Gems"), ("Uncut Spirit Gem", "Uncut Spirit Gems"))


def _weighted(rng: random.Random, weights: dict):
    keys = list(weights)
    return rng.choices(keys, weights=[weights[k] for k in keys])[0]


@lru_cache(maxsize=1)
def equipment_pool() -> dict[str, tuple[str, ...]]:
    """native class -> every verified base of that class."""
    from exilelens.filters.verified_bases import load_base_properties, native_class
    by_class: dict[str, list[str]] = {}
    for base in sorted(load_base_properties()):
        cls = native_class(base)
        if cls:
            by_class.setdefault(cls, []).append(base)
    return {cls: tuple(bases) for cls, bases in by_class.items()}


@lru_cache(maxsize=1)
def currency_pool() -> dict[str, tuple[str, ...]]:
    """ladder tier -> every exact currency name the repository knows."""
    from exilelens.filters import currency_tiers
    names = set(currency_tiers.ALL_NAMES) | {"Armourer's Scrap", "Lesser Jeweller's Orb", "Exalted Orb"}
    names |= {i.base_type or i.name for i in (*PREVIEW_ITEMS, *SHOWCASE_ITEMS, *REAL_GAME_ITEMS, *HERO_CLUSTER_ITEMS)
              if i.item_class == "Stackable Currency"}
    # only names the native registry establishes as ground bases: a drop floor never contains an object the game cannot put on the ground
    from exilelens.filters.native_bases import is_ground_base
    by_tier: dict[str, list[str]] = {}
    for name in sorted(names):
        if is_ground_base(name):
            by_tier.setdefault(currency_tiers.tier_of(name), []).append(name)
    return {tier: tuple(v) for tier, v in by_tier.items()}


def pool_size() -> int:
    """How many distinct drop states the generator can produce (equipment states counted per base x rarity x level x quality x tier)."""
    equipment = sum(len(bases) for bases in equipment_pool().values()) * len(RARITY_WEIGHTS) * len(set(ITEM_LEVELS)) * 2 * 6
    return equipment + sum(len(v) for v in currency_pool().values()) + 16 * 3 + len(GEMS) * 20 + len(SPECIALS) + 2


def _equipment(rng: random.Random) -> PreviewItem | None:
    from exilelens.filters.legal_corpus import Legality, classify_equipment
    from exilelens.filters.verified_bases import load_base_properties
    pool = equipment_pool()
    cls = rng.choice(sorted(pool))
    base = rng.choice(pool[cls])
    record = load_base_properties()[base]
    rarity = _weighted(rng, RARITY_WEIGHTS)
    level = max(int(record["required_level"]), rng.choice(ITEM_LEVELS))
    quality = 20 if rarity == "Normal" and rng.random() < .15 else (rng.randint(1, 15) if rng.random() < .1 else 0)
    tier = rng.randint(1, 5) if rarity == "Rare" and rng.random() < .35 else 0
    if classify_equipment(base, rarity, level, quality, tier)[0] == Legality.INVALID:
        return None
    name = f"{base} (Tier {tier})" if tier else base
    return PreviewItem(name, f"Random: {rarity.lower()} {cls.lower()}", cls, base, rarity, item_level=level, area_level=level, quality=quality,
                       unidentified_item_tier=tier, base_energy_shield=record["energy_shield"], base_armour=record["armour"],
                       base_evasion=record["evasion"])


def _currency(rng: random.Random) -> PreviewItem:
    pool = currency_pool()
    tier = _weighted(rng, {t: w for t, w in CURRENCY_TIER_WEIGHTS.items() if t in pool})
    name = rng.choice(pool[tier])
    stack = {"CURRENCY_UTILITY": rng.randint(1, 20), "CURRENCY_LOW": rng.randint(1, 8), "CURRENCY_VALUABLE": rng.randint(1, 12)}.get(
        tier, rng.choice((1, 1, 1, 2, 3)) if tier != "CURRENCY_HERO" else 1)
    from exilelens.filters.native_bases import entry_of
    return PreviewItem(name, f"Random: {tier.lower()}", entry_of(name).native_class, name, stack_size=stack)


def random_scene_items(seed: int, count: int = DROPS_PER_SCENE) -> list[PreviewItem]:
    """A new floor of drops for every seed; the same seed always gives the same floor (so a reflow keeps the scene)."""
    rng = random.Random(seed)
    items: list[PreviewItem] = []
    while len(items) < count:
        kind = _weighted(rng, KIND_WEIGHTS)
        if kind == "equipment":
            item = _equipment(rng)
            if item is None:
                continue
        elif kind == "currency":
            item = _currency(rng)
        elif kind == "waystone":
            tier = rng.choices(range(1, 17), weights=[1, 1, 1, 1, 2, 2, 2, 3, 3, 4, 5, 6, 6, 6, 5, 3])[0]
            item = PreviewItem(f"Waystone (Tier {tier})", "Random: waystone", "Waystones", rarity=_weighted(rng, {"Normal": 3, "Magic": 4, "Rare": 3}),
                               waystone_tier=tier)
        elif kind == "gem":
            name, cls = rng.choice(GEMS)
            level = rng.randint(1, 20)
            item = PreviewItem(f"{name} (Level {level})", "Random: gem", cls, name, item_level=level, gem_level=level)
        elif kind == "special":
            name, cls = rng.choice(SPECIALS)
            item = PreviewItem(name, "Random: special", cls)
        elif kind == "tablet":
            item = PreviewItem("Abyss Precursor Tablet", "Random: tablet", "Tablet")
        else:
            item = PreviewItem("Amanamu's Gaze", "Random: augment", "Augment")
        items.append(item)
    return items
