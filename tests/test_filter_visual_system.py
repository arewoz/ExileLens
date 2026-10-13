"""Visual system: five importance levels, family treatments and theme grades (native actions only).

Run with:  python -m pytest tests/test_filter_visual_system.py -m ""
"""
from __future__ import annotations

import itertools
import json
from pathlib import Path

import pytest

from exilelens.filters import canonical
from exilelens.filters.build_needs import BuildNeedsSnapshot
from exilelens.filters.intel_generate import generate
from exilelens.filters.preview import SHOWCASE_ITEMS, preview_decision, preview_scene_items
from exilelens.filters.profiles import BaseTier, FilterThemeName
from exilelens.filters.style_system import (FAMILY_BASE, GRADES, LEVEL_POLICY, LEVELS, ROLE_DESIGNS, TIER_LEVELS, _accent, _to_hls, contrast,
                                            native_style)
from exilelens.filters.validation import validate_all

THEMES = list(FilterThemeName)


def rgb(color: str) -> tuple[int, int, int]:
    return tuple(int(v) for v in color.split()[:3])


def all_styles():
    for theme in THEMES:
        for role in ROLE_DESIGNS:
            for tier in ([None, *BaseTier] if role in TIER_LEVELS else [None]):
                if tier == BaseTier.IGNORE:
                    continue
                yield theme, role, tier, native_style(theme, role, tier)


def test_five_levels_have_a_strictly_descending_font_ladder_within_native_limits():
    sizes = [LEVEL_POLICY[level]["font"] for level in LEVELS]
    assert sizes == sorted(sizes, reverse=True) and len(set(sizes)) == 5 and max(sizes) <= 45 and min(sizes) >= 18
    for theme in THEMES:
        assert native_style(theme, "hero")["level"] == "MYTHIC"
        assert native_style(theme, "hero")["font_size"] > native_style(theme, "premium_currency")["font_size"] \
            > native_style(theme, "crafting_currency")["font_size"] > native_style(theme, "currency")["font_size"] \
            > native_style(theme, "trade_craft")["font_size"]


def test_every_label_stays_legible():
    worst = min(contrast(rgb(s["text_color"]), rgb(s["bg_color"])) for _t, _r, _ti, s in all_styles())
    assert worst >= 4.5
    for theme, role, tier, style in all_styles():
        if style["level"] == "LOW":
            continue
        # V4: the white / red apex uses a VIVID red on white at 41-45 pt (large text): 5 : 1; every other label 7 : 1
        floor = 5.0 if style["variant"] == "white_red" else 7.0
        assert contrast(rgb(style["text_color"]), rgb(style["bg_color"])) >= floor, (theme, role, tier)


def test_level_controls_beam_icon_and_sound_policy():
    # V4: the level decides the icon size; beams and sounds are explicit per-role tables (style_system.BEAM_POLICY / SOUND_POLICY)
    from exilelens.filters.style_system import BEAM_POLICY, PERSISTENT, SOUND_POLICY
    for theme, role, tier, style in all_styles():
        level = style["level"]
        beam = style.get("play_effect", "")
        if level == "MYTHIC":
            assert beam and "Temp" not in beam and style["minimap_icon"].startswith("0 ") and style["sound"].endswith(" 300")
        elif level == "HIGH":
            assert style["minimap_icon"].startswith("1 ") or role == "currency_premium"
        elif level in ("UTILITY", "LOW"):
            assert "minimap_icon" not in style and "sound" not in style
        assert bool(beam) == (role in BEAM_POLICY) and ("sound" in style) == (role in SOUND_POLICY), (theme, role)
        if beam:
            assert ("Temp" not in beam) == (BEAM_POLICY[role] == PERSISTENT), (theme, role, beam)
    mythic_roles = {role for _t, role, _ti, s in all_styles() if s["level"] == "MYTHIC"}
    assert mythic_roles == {"hero"}


def test_hero_is_the_brightest_block_and_outshines_every_other_currency():
    from exilelens.filters.visual_audit import from_style, measure
    for theme in THEMES:
        hero = native_style(theme, "hero")
        assert hero["bg_color"].endswith(" 255") and hero["border_color"].endswith(" 255") and hero["variant"] == "white_red"
        for role in ("currency_premium", "premium_currency", "currency_valuable", "currency", "currency_low"):
            other = native_style(theme, role)
            assert sum(rgb(hero["bg_color"])) >= sum(rgb(other["bg_color"])) - 6, (theme, role)     # no brighter plaque than the hero
            assert measure(from_style("hero", hero)).attention > measure(from_style(role, other)).attention, (theme, role)
        for role in ("unique", "special", "waystone_high", "build_weapon", "currency", "trade", "jewel"):
            other = native_style(theme, role, BaseTier.T1 if role == "build_weapon" else None)
            assert sum(rgb(hero["bg_color"])) > sum(rgb(other["bg_color"])) + 120, (theme, role)


def test_families_stay_separable_in_every_theme():
    variants: dict[str, set[str]] = {}
    for role, design in ROLE_DESIGNS.items():
        variants.setdefault(design.family, set()).add(design.variant)
    neutral = {"generic"}            # profile system V2: the grey generic label has no hue identity; it is separated by CHROMA, asserted below
    for theme, grade in GRADES.items():
        hues = {family: _to_hls(_accent(family, grade))[0] for family in FAMILY_BASE}
        assert all(_to_hls(_accent(family, grade))[2] <= .25 for family in neutral), theme
        assert all(_to_hls(_accent(family, grade))[2] >= .28 for family in FAMILY_BASE if family not in neutral), theme
        for a, b in itertools.combinations([f for f in FAMILY_BASE if f not in neutral], 2):
            distance = abs(hues[a] - hues[b])
            distance = min(distance, 360 - distance)
            assert distance >= 11 and (distance >= 18 or variants[a] != variants[b]), (theme, a, b, distance)


def test_themes_change_mood_not_hierarchy():
    for role, tier in (("hero", None), ("unique", None), ("build_weapon", BaseTier.T1), ("currency", None), ("trade", None)):
        styles = [native_style(theme, role, tier) for theme in THEMES]
        assert len({s["level"] for s in styles}) == 1 and len({s["font_size"] for s in styles}) == 1
        assert len({s["bg_color"] for s in styles}) == len(THEMES)           # but every theme looks different
    signatures = {(g.hero_effect, g.hero_shape) for g in GRADES.values()}
    assert len(signatures) >= 6                                                # near-unique hero signatures


def test_build_tiers_descend_in_attention():
    for role, table in TIER_LEVELS.items():
        sizes = [native_style(FilterThemeName.VOID_GOLD, role, tier)["font_size"] for tier in (BaseTier.T1, BaseTier.T2, BaseTier.T3, BaseTier.T4)]
        assert sizes == sorted(sizes, reverse=True) and sizes[0] > sizes[-1]


@pytest.fixture(scope="module")
def needs():
    path = canonical.CANONICAL_NEEDS_DIR / "spark_fixture.json"
    if not path.exists():
        pytest.skip("canonical needs not present")
    return BuildNeedsSnapshot.from_dict(json.loads(path.read_text(encoding="utf-8")))


def test_generated_filters_are_native_valid_and_visibility_is_theme_invariant(needs):
    items = list(preview_scene_items("Showcase"))
    assert items == list(SHOWCASE_ITEMS)
    for profile in ("Recommended", "Endgame"):
        shown = set()
        for theme in THEMES:
            result = generate(needs, profile, theme)
            assert result.valid and validate_all(result.text).passed, (profile, theme)
            shown.add(tuple(preview_decision(result.rules, item).hidden for item in items))
        assert len(shown) == 1


def test_showcase_exposes_every_level_and_family(needs):
    result = generate(needs, "Recommended")
    decisions = {item.name + "/" + item.category: preview_decision(result.rules, item) for item in SHOWCASE_ITEMS}
    visible = [d for d in decisions.values() if not d.hidden]
    sizes = {d.font_size for d in visible}
    assert len(sizes) >= 5 and max(sizes) == 45
    roles = {d.style_role for d in visible}
    assert {"hero", "currency_premium", "premium_currency", "currency_valuable", "currency", "currency_low", "special", "waystone_high",
            "waystone_mid", "waystone", "unique", "jewel", "charm", "gem", "tablet", "build_weapon", "craft_relevant", "craft_premium"} <= roles
    assert sum(1 for d in decisions.values() if d.hidden) >= 2                 # the scene also shows what is filtered out
