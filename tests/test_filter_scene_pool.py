"""Random preview scene (preview only): a new floor of drops per Reroll, drawn from the whole verified catalog.

Run with:  python -m pytest tests/test_filter_scene_pool.py -m ""
"""
from __future__ import annotations

from collections import Counter

from exilelens.filters.legal_corpus import Legality, classify_equipment
from exilelens.filters.scene_pool import DROPS_PER_SCENE, RANDOM_SCENE, currency_pool, equipment_pool, pool_size, random_scene_items


def test_same_seed_same_floor_new_seed_new_floor():
    assert [i.label for i in random_scene_items(7)] == [i.label for i in random_scene_items(7)]
    a, b = {i.label for i in random_scene_items(7)}, {i.label for i in random_scene_items(8)}
    assert len(random_scene_items(7)) == DROPS_PER_SCENE and len(a & b) < DROPS_PER_SCENE // 2


def test_the_pool_is_large_and_actually_used():
    assert pool_size() > 100_000
    bases, classes, kinds = set(), set(), Counter()
    for seed in range(300):
        for item in random_scene_items(seed):
            kinds[item.category.split(":")[1].split()[0] if ":" in item.category else item.category] += 1
            if item.base_type and item.item_class != "Stackable Currency":
                bases.add(item.base_type)
                classes.add(item.item_class)
    assert len(bases) > 500 and len(classes) >= 0.8 * len(equipment_pool())        # most of the catalog appears within 300 rerolls
    seen = {i.item_class for seed in range(300) for i in random_scene_items(seed)}
    assert {"Stackable Currency", "Waystones", "Uncut Skill Gems", "Omen", "Tablet", "Augment"} <= seen
    names = {i.name for seed in range(300) for i in random_scene_items(seed) if i.item_class == "Stackable Currency"}
    assert {"Divine Orb", "Hinekora's Lock"} <= names and len(names) >= 0.8 * sum(len(v) for v in currency_pool().values())


def test_equipment_states_are_never_invalid():
    for seed in range(200):
        for item in random_scene_items(seed):
            from exilelens.filters.verified_bases import SPECIAL_BASES
            if (item.base_type and item.base_type not in SPECIAL_BASES
                    and item.item_class not in ("Stackable Currency", "Uncut Skill Gems", "Uncut Support Gems", "Uncut Spirit Gems")):
                verdict, reason = classify_equipment(item.base_type, item.rarity, item.item_level, item.quality, item.unidentified_item_tier)
                assert verdict != Legality.INVALID, (item, reason)


def test_the_dashboard_lists_the_random_scene():
    import inspect
    from exilelens.ui import filters_page
    source = inspect.getsource(filters_page)
    assert filters_page.RANDOM_SCENE == RANDOM_SCENE and '"Showcase", RANDOM_SCENE,' in source and "random_scene_items(self._seed)" in source
