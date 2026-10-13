"""FILTER visual system V3: value hierarchy calibration from real gameplay + the white / red hero.

V4 (test_filter_visual_v4.py) superseded the V3 beam / sound / white-red contrast policy; the assertions that encode it are updated in place and
marked "V4". Every V3 invariant (ladder, budgets, readability, visibility) still holds.

Presentation only: nothing here may change which items are shown or hidden.
Run with:  python -m pytest tests/test_filter_visual_v3.py -m ""
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from exilelens.filters import canonical, currency_tiers
from exilelens.filters.build_needs import BuildNeedsSnapshot
from exilelens.filters.inspector import make_item
from exilelens.filters.intel_generate import generate
from exilelens.filters.preview import REAL_GAME_ITEMS, SHOWCASE_ITEMS, PreviewItem, preview_decision, preview_scene_items
from exilelens.filters.profiles import BaseTier, FilterThemeName
from exilelens.filters.rules import GeneratedRule
from exilelens.filters.style_system import (GRADES, HERO_RED, LEVEL_POLICY, LEVELS, ROLE_DESIGNS, SOUND_POLICY, TIER_LEVELS, _rgb, _to_hls,
                                            contrast, native_style)
from exilelens.filters.validation import validate_all
from exilelens.filters.visual_audit import (MIN_TEXT_CONTRAST, WORLDS, audit_scene, from_style, measure, min_text_contrast,
                                            natives_from_rules)

ROOT = Path(__file__).resolve().parents[1]
THEMES = list(FilterThemeName)


def attention(theme, role, tier=None) -> float:
    return measure(from_style(role, native_style(theme, role, tier))).attention


@pytest.fixture(scope="module")
def needs():
    path = canonical.CANONICAL_NEEDS_DIR / "spark_fixture.json"
    if not path.exists():
        pytest.skip("canonical needs not present")
    return BuildNeedsSnapshot.from_dict(json.loads(path.read_text(encoding="utf-8")))


@pytest.fixture(scope="module")
def generated(needs):
    return {theme: generate(needs, "Recommended", theme, intel=True) for theme in THEMES}


# -- importance vs family -----------------------------------------------------------------------------------------------------------------
def test_importance_decides_size_mass_and_effects_independently_of_family():
    by_level: dict[str, set] = {level: set() for level in LEVELS}
    for theme in THEMES:
        for role, design in ROLE_DESIGNS.items():
            for tier in ([None, BaseTier.T1, BaseTier.T2, BaseTier.T3, BaseTier.T4] if role in TIER_LEVELS else [None]):
                style = native_style(theme, role, tier)
                policy = LEVEL_POLICY[style["level"]]
                assert style["font_size"] == policy["font"], (role, tier)
                assert style["bg_color"].split()[-1] == str(policy["bg_alpha"]) or style["level"] == "MYTHIC", (role, tier)
                by_level[style["level"]].add(design.family)
    assert len(by_level["UTILITY"]) >= 5 and len(by_level["VALUABLE"]) >= 5       # several families share a level, one policy


def test_family_changes_hue_not_importance():
    for theme in THEMES:
        for a, b in (("currency_valuable", "build_weapon"), ("currency", "crafting_base"), ("premium_currency", "unique")):
            sa, sb = native_style(theme, a, BaseTier.T1 if a == "build_weapon" else None), native_style(theme, b, BaseTier.T1 if b == "build_weapon" else None)
            if sa["level"] == sb["level"]:
                assert sa["font_size"] == sb["font_size"]


# -- currency ladder ------------------------------------------------------------------------------------------------------------------------
def test_currency_has_an_explicit_evidenced_ladder():
    keys = [t.key for t in currency_tiers.TIERS]
    assert keys == ["CURRENCY_HERO", "CURRENCY_PREMIUM", "CURRENCY_ENHANCED", "CURRENCY_CRAFT", "CURRENCY_VALUABLE", "CURRENCY_UTILITY",
                    "CURRENCY_LOW"]
    assert all(t.evidence in (currency_tiers.GGG_NOTICE, currency_tiers.OBSERVED) for t in currency_tiers.TIERS)
    assert all(t.evidence_of(n) in (currency_tiers.GGG_NOTICE, currency_tiers.OBSERVED, currency_tiers.COMMUNITY_FILTER)
               for t in currency_tiers.TIERS for n in t.names)
    names = [n for t in currency_tiers.TIERS for n in t.names]
    assert len(names) == len(set(names)), "a currency name belongs to exactly one tier"
    assert currency_tiers.tier_of("Divine Orb") == "CURRENCY_PREMIUM" and currency_tiers.tier_of("Orb of Alchemy") == "CURRENCY_UTILITY"


def test_divine_tier_outranks_ordinary_currency_and_every_ordinary_opportunity():
    for theme in THEMES:
        divine = attention(theme, "currency_premium")
        for role in ("currency_valuable", "currency", "currency_low", "crafting_currency", "craft_relevant", "craft_premium", "high_unid",
                     "jewel", "gem", "trade_weapon", "build_jewellery"):
            assert divine > attention(theme, role) * 1.5, (theme, role)
        for role in ("build_weapon", "build_defense", "build_offhand", "build_jewellery"):
            for tier in (BaseTier.T1, BaseTier.T2, BaseTier.T3):
                assert divine > attention(theme, role, tier) * 1.5, (theme, role, tier)
        assert attention(theme, "hero") > divine > attention(theme, "premium_currency")           # hero > Divine > enhanced currency


def test_ladder_descends_in_every_theme():
    for theme in THEMES:
        ladder = [attention(theme, r) for r in ("hero", "currency_premium", "premium_currency", "currency_valuable", "currency", "currency_low")]
        assert ladder == sorted(ladder, reverse=True) and len(set(ladder)) == len(ladder), (theme, ladder)


def test_build_and_craft_opportunities_say_inspect_me_not_jackpot():
    for role, table in TIER_LEVELS.items():
        assert table[BaseTier.T1] in ("VALUABLE", "UTILITY") and table[BaseTier.T2] in ("UTILITY", "LOW")
    for theme in THEMES:
        for role in ("build_weapon", "build_defense", "build_jewellery", "build_offhand", "craft_premium", "craft_relevant", "high_unid"):
            style = native_style(theme, role, BaseTier.T1 if role.startswith("build") else None)
            assert style["level"] in ("VALUABLE", "UTILITY") and "play_effect" not in style and "sound" not in style
        # the Utility Belt reference (CRAFT_RELEVANT): visible, readable, quiet
        belt = native_style(theme, "craft_relevant")
        assert belt["level"] == "UTILITY" and contrast(_rgb("#" + "".join(f"{int(v):02x}" for v in belt["text_color"].split()[:3])),
                                                       _rgb("#" + "".join(f"{int(v):02x}" for v in belt["bg_color"].split()[:3]))) >= 7.0


# -- stack size ----------------------------------------------------------------------------------------------------------------------------
def test_stack_quantity_never_selects_a_style_or_a_rule(generated):
    rules = generated[FilterThemeName.VOID_GOLD].rules
    base = PreviewItem("Chaos Orb", "t", "Stackable Currency", "Chaos Orb")
    reference = preview_decision(rules, base)
    for stack in (1, 2, 20, 999):
        item = PreviewItem("Chaos Orb", "t", "Stackable Currency", "Chaos Orb", stack_size=stack)
        d = preview_decision(rules, item)
        assert (d.rule_name, d.font_size, d.stylesheet, d.effect, d.minimap_icon) == \
               (reference.rule_name, reference.font_size, reference.stylesheet, reference.effect, reference.minimap_icon)
        assert item.label == (f"{stack}x Chaos Orb" if stack > 1 else "Chaos Orb") and "Chaos Orb" in item.label
    for theme in THEMES:
        assert "StackSize" not in generated[theme].text


# -- the real-game scene ---------------------------------------------------------------------------------------------------------------------
def test_real_game_scene_reads_as_a_hierarchy_in_every_theme(generated):
    for theme in THEMES:
        rules = generated[theme].rules
        decisions = {item.name: preview_decision(rules, item) for item in REAL_GAME_ITEMS}
        assert not any(d.hidden for d in decisions.values())
        sizes = {n: d.font_size for n, d in decisions.items()}
        assert sizes["Hinekora's Lock"] == 45 and sizes["Divine Orb"] == 41
        for name in ("Warlord Cuirass (Tier 3)", "Drakeskin Boots (Tier 3)", "Imperial Greathelm (Tier 2)", "Utility Belt", "Chaos Orb",
                     "Orb of Alchemy", "Regal Shard"):
            assert sizes["Divine Orb"] > sizes[name], (theme, name)
        natives = dict(natives_from_rules(rules, REAL_GAME_ITEMS))
        weight = {name: measure(native).attention for name, native in natives.items()}
        divine = weight["2x Divine Orb"]
        for label in ("Warlord Cuirass (Tier 3)", "Drakeskin Boots (Tier 3)", "Imperial Greathelm (Tier 2)", "Utility Belt", "20x Chaos Orb",
                      "20x Orb of Alchemy", "3x Regal Shard", "Voltaic Staff", "Vitalic Ring", "Uncut Skill Gem (Level 17)"):
            assert divine > weight[label] * 1.5, (theme, label)
        assert weight["Hinekora's Lock"] > divine
        audit = audit_scene(theme.value, list(natives.items()))
        assert audit.flags == [], (theme, audit.flags)


def test_attention_budget_in_dense_clusters(generated):
    for theme in THEMES:
        for scene in ("Real Game Cluster", "Showcase"):
            audit = audit_scene(theme.value, natives_from_rules(generated[theme].rules, preview_scene_items(scene)))
            assert audit.flags == [], (theme, scene, audit.flags)
            summary = audit.summary()
            assert summary["dominant"] <= max(3, int(0.25 * summary["labels"]))
            assert len(summary["white_plaques"]) <= max(3, int(0.15 * summary["labels"]))


def test_the_audit_can_fail():
    """A QA instrument that cannot flag proves nothing: a cluster of ten white heroes must trip the budget and the ladder checks."""
    theme = FilterThemeName.VOID_GOLD
    hero = from_style("hero", native_style(theme, "hero"))
    flooded = audit_scene(theme.value, [(f"hero {i}", hero) for i in range(10)] + [("Orb", from_style("currency", native_style(theme, "currency")))])
    assert any(f.startswith("TOO_MANY_DOMINANT") for f in flooded.flags) and any(f.startswith("TOO_MUCH_WHITE") for f in flooded.flags)
    weak_mythic = from_style("currency", native_style(theme, "currency"))
    from dataclasses import replace
    forged = replace(weak_mythic, level="MYTHIC")
    labels = [("fake mythic", forged), ("valuable", from_style("currency_valuable", native_style(theme, "currency_valuable")))]
    assert any("MYTHIC" in f for f in audit_scene(theme.value, labels).flags)


# -- readability on any ground -----------------------------------------------------------------------------------------------------------------
def test_every_label_is_readable_on_dark_stone_and_fire():
    for theme in THEMES:
        for role in ROLE_DESIGNS:
            for tier in ([BaseTier.T1, BaseTier.T4] if role in TIER_LEVELS else [None]):
                m = measure(from_style(role, native_style(theme, role, tier)))
                need = min_text_contrast(m.native)                       # V4: the white / red apex has its own large-text floor (5 : 1)
                assert need == MIN_TEXT_CONTRAST[m.native.level] or m.native.treatment == "white_red"
                assert min(m.text_contrast.values()) >= need, (theme, role, tier, m.text_contrast)
                assert set(m.text_contrast) == set(WORLDS)


def test_skill_gems_have_an_identity_and_a_readable_plate(generated):
    for theme in THEMES:
        d = preview_decision(generated[theme].rules, make_item("Uncut Skill Gem", rarity="Normal", item_class="Uncut Skill Gems"))
        assert not d.hidden and d.rule_name == "UncutGems" and d.style_role == "gem"
        assert measure(from_style("gem", native_style(theme, "gem"))).native.level == "UTILITY"
    assert LEVEL_POLICY["LOW"]["bg_alpha"] >= 205                                      # LOW stays a plate, not a ghost


# -- themes ------------------------------------------------------------------------------------------------------------------------------------
def test_theme_changes_flavour_never_importance_or_visibility(generated):
    items = list(REAL_GAME_ITEMS) + list(SHOWCASE_ITEMS)
    reference = None
    for theme in THEMES:
        assert generated[theme].valid and validate_all(generated[theme].text).passed
        signature = tuple((preview_decision(generated[theme].rules, i).hidden, preview_decision(generated[theme].rules, i).font_size,
                           preview_decision(generated[theme].rules, i).style_role) for i in items)
        reference = reference or signature
        assert signature == reference, theme
    for role in ("hero", "currency_premium", "premium_currency", "currency_valuable", "currency", "gem"):
        styles = [native_style(t, role) for t in THEMES]
        assert len({s["level"] for s in styles}) == 1 and len({s["font_size"] for s in styles}) == 1
        assert len({s["bg_color"] for s in styles}) >= 6


# -- sound / beam / icon hierarchy ----------------------------------------------------------------------------------------------------------
def test_sound_is_sparing_and_ordered():
    volumes = {}
    for role in ROLE_DESIGNS:
        style = native_style(FilterThemeName.VOID_GOLD, role, BaseTier.T1 if role in TIER_LEVELS else None)
        if "sound" in style:
            volumes[role] = int(style["sound"].split()[1])
    assert volumes["hero"] > volumes["currency_premium"] > volumes["premium_currency"] >= max(
        v for r, v in volumes.items() if r not in ("hero", "currency_premium"))
    # V4: + a soft currency word for valuable currency; build / craft / trade / utility stay silent; sound is per role, not per level
    assert set(volumes) == {"hero", "currency_premium", "premium_currency", "special", "unique", "waystone_high", "tablet", "quest",
                            "currency_valuable"} == set(SOUND_POLICY)
    assert all("sound" not in LEVEL_POLICY[level] for level in LEVELS)


def test_beams_are_rare_and_mean_something():
    beams = {}
    for role in ROLE_DESIGNS:
        style = native_style(FilterThemeName.VOID_GOLD, role, BaseTier.T1 if role in TIER_LEVELS else None)
        if "play_effect" in style:
            beams[role] = style["play_effect"]
    assert set(beams) == {"hero", "currency_premium", "premium_currency", "special", "unique", "quest", "waystone_high"}
    # V4: persistent for MYTHIC, the Divine tier and quest items; everything else that beams is Temp
    assert {r for r, v in beams.items() if not v.endswith("Temp")} == {"hero", "currency_premium", "quest"}


# -- the white / red hero ------------------------------------------------------------------------------------------------------------------
def test_white_red_exists_in_every_theme_and_is_reserved():
    users = {role for role, d in ROLE_DESIGNS.items() if d.variant == "white_red"}
    assert users == {"hero", "currency_premium"}                                           # one MYTHIC and one top-HIGH currency
    assert {ROLE_DESIGNS[r].level for r in users} == {"MYTHIC", "HIGH"}
    assert set(HERO_RED) == set(THEMES)
    assert len(users) / len(ROLE_DESIGNS) < 0.08                                           # a status symbol, not a family colour


def test_white_red_palettes_are_numerically_valid_and_flavoured():
    plaques, texts = set(), set()
    for theme, (plaque, text, border) in HERO_RED.items():
        p, t, b = _rgb(plaque), _rgb(text), _rgb(border)
        assert contrast(t, p) >= 5.0 and contrast(b, p) >= 3.0, theme                                      # V4: vivid red, large text
        hue, light, sat = _to_hls(t)
        assert (hue <= 22 or hue >= 335) and sat >= 0.85 and 0.30 <= light <= 0.48, (theme, hue, sat, light)  # V4: vivid, not maroon
        assert _to_hls(p)[1] >= 0.85, theme                                                                  # a real white plaque
        plaques.add(plaque)
        texts.add(text)
        for level, floor in (("hero", 5.0), ("currency_premium", 5.0)):
            style = native_style(theme, level)
            assert contrast(_rgb("#%02x%02x%02x" % tuple(int(v) for v in style["text_color"].split()[:3])),
                            _rgb("#%02x%02x%02x" % tuple(int(v) for v in style["bg_color"].split()[:3]))) >= floor
    assert len(plaques) == len(texts) == len(THEMES)                                                      # every theme reinterprets it


def test_white_red_outranks_every_ordinary_label_in_every_theme():
    for theme in THEMES:
        ordinary = [r for r, d in ROLE_DESIGNS.items() if d.variant != "white_red"]
        floor = attention(theme, "currency_premium")
        for role in ordinary:
            for tier in ([BaseTier.T1, BaseTier.T2, BaseTier.T3] if role in TIER_LEVELS else [None]):
                assert floor > attention(theme, role, tier), (theme, role, tier)


def test_white_mass_is_controlled(generated):
    for theme in THEMES:
        natives = natives_from_rules(generated[theme].rules, preview_scene_items("Real Game Cluster"))
        white = [n for n, native in natives if measure(native).white_plaque]
        assert set(white) == {"Hinekora's Lock", "2x Divine Orb"}, (theme, white)
        every_role = sum(measure(from_style(r, native_style(theme, r))).white_plaque for r in ROLE_DESIGNS)
        assert every_role == 2                                                          # V4: hero and Divine tier only (enhanced is a gold bar)


# Visibility vs the FILTER-09 filters is no longer an invariant: profile system V2 DEFINES visibility from the approved matrix
# (tests/test_filter_profile_system_v2.py; old-vs-new measurements in artifacts/filter_profile_v2/).
