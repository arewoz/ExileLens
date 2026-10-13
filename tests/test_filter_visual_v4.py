"""FILTER visual system V4: theme motifs, the iconic white / red apex, persistent beams for the top, a native sound vocabulary.

Presentation only: nothing here may change which items are shown or hidden, or the exact BaseType contract (FILTER-09).
Run with:  python -m pytest tests/test_filter_visual_v4.py -m ""
"""
from __future__ import annotations

import itertools
import json
import re
from pathlib import Path

import pytest

from exilelens.filters import canonical, currency_tiers, legal_corpus
from exilelens.filters.base_match import BaseCondition, BaseMatch
from exilelens.filters.build_needs import BuildNeedsSnapshot
from exilelens.filters.inspector import make_item
from exilelens.filters.intel_generate import generate
from exilelens.filters.preview import REAL_GAME_ITEMS, SHOWCASE_ITEMS, PreviewItem, preview_decision, preview_scene_items
from exilelens.filters.profiles import BaseTier, FilterThemeName
from exilelens.filters.rule_ir import to_ir
from exilelens.filters.style_system import (ALWAYS_SOUND_ROLES, BEAM_POLICY, DIVINE_EFFECT, GRADES, HERO_RED, HIDDEN_DROP_SOUND, LEVEL_POLICY,
                                            PERSISTENT, ROLE_DESIGNS, SOUND_POLICY, SOUND_WORDS, TEMP, TIER_LEVELS, TREATMENTS,
                                            WHITE_RED_TEXT_FLOOR, _luminance, _rgb, _to_hls, beam_for, contrast, native_style)
from exilelens.filters.validation import validate_all, validate_syntax
from exilelens.filters.verified_bases import COMMUNITY_SPECIAL_BASES, PINNED_SPECIAL_BASES, SPECIAL_BASES
from exilelens.filters.visual_audit import audit_scene, from_style, measure, natives_from_rules
from exilelens.filters.visual_identity import (FAMILY_PROBES, family_separation, policy_matrix, required_axes, separating_axes,
                                               theme_distance)

ROOT = Path(__file__).resolve().parents[1]
THEMES = list(FilterThemeName)
PROFILES = ("Relaxed", "Recommended", "Strict", "Very Strict", "Uber Strict")


def rgb(text: str) -> tuple[int, int, int]:
    return tuple(int(v) for v in text.split()[:3])


def all_styles():
    for theme in THEMES:
        for role in ROLE_DESIGNS:
            for tier in ([BaseTier.T1, BaseTier.T2, BaseTier.T3, BaseTier.T4] if role in TIER_LEVELS else [None]):
                yield theme, role, tier, native_style(theme, role, tier)


@pytest.fixture(scope="module")
def needs():
    path = canonical.CANONICAL_NEEDS_DIR / "spark_fixture.json"
    if not path.exists():
        pytest.skip("canonical needs not present")
    return BuildNeedsSnapshot.from_dict(json.loads(path.read_text(encoding="utf-8")))


@pytest.fixture(scope="module")
def matrix(needs):
    """Every profile x theme filter (40 filters), generated once."""
    return {(profile, theme): generate(needs, profile, theme, intel=True) for profile in PROFILES for theme in THEMES}


@pytest.fixture(scope="module")
def corpus():
    return [c.item for c in legal_corpus.sample(900, 11)] + list(REAL_GAME_ITEMS) + list(SHOWCASE_ITEMS)


def _blocks(text: str) -> list[list[str]]:
    blocks, current = [], None
    for raw in text.splitlines():
        line = raw.strip()
        if line in ("Show", "Hide"):
            current = [line]
            blocks.append(current)
        elif current is not None and raw.startswith("\t"):
            current.append(line)
        elif not line or line.startswith("#"):
            current = None if not line.startswith("#") else current
    return blocks


def _action(block: list[str], keyword: str) -> str | None:
    return next((line.split(None, 1)[1] if " " in line else "" for line in block if line.split(None, 1)[0] == keyword), None)


# == A. theme identity ======================================================================================================================
def test_every_theme_has_its_own_motif():
    motifs = [(g.name, g.frame, g.hero_effect, g.hero_shape) for g in GRADES.values()]
    assert len({m[0] for m in motifs}) == len(THEMES) and all(m[0] for m in motifs)            # a named motif per theme
    assert len({m[1] for m in motifs}) == len(THEMES)                                          # its own frame metal
    assert len({(m[2], m[3]) for m in motifs}) == len(THEMES)                                  # its own MYTHIC pillar + icon pair
    assert len({HERO_RED[t] for t in THEMES}) == len(THEMES)                                   # its own white / red reading
    assert sum(g.glow for g in GRADES.values()) >= 1 and sum(g.ash > 0 for g in GRADES.values()) >= 1   # opinionated axes, not only tints


def test_themes_are_far_apart_not_recolours():
    distances = {(a, b): theme_distance(a, b) for a, b in itertools.combinations(THEMES, 2)}
    # V3 measured min 11.6 / mean 29.1 on the same probes (artifacts/filter_visual_v4/THEME_IDENTITY.md); V4 must be clearly further apart
    assert min(distances.values()) >= 14.0, min(distances.items(), key=lambda kv: kv[1])
    assert sum(distances.values()) / len(distances) >= 31.0


def test_dark_plates_are_framed_in_the_theme_metal():
    for theme, grade in GRADES.items():
        metal = rgb(" ".join(str(int(grade.frame[i:i + 2], 16)) for i in (1, 3, 5)))
        border = rgb(native_style(theme, "currency_valuable")["border_color"])
        family_only = rgb(native_style(FilterThemeName.VOID_GOLD, "currency_valuable")["border_color"])
        # closer to its own metal than an unframed family edge would be (the metal is a visible motif, not a rounding error)
        assert sum((a - b) ** 2 for a, b in zip(border, metal)) < sum((a - b) ** 2 for a, b in zip(family_only, metal)) or theme == FilterThemeName.VOID_GOLD


def test_prism_glows_and_ashes_turn_to_ash():
    glow = native_style(FilterThemeName.ARCANE_PRISM, "currency")
    plain = native_style(FilterThemeName.ETERNAL_EMPIRE, "currency")
    assert _to_hls(rgb(glow["text_color"]))[2] > _to_hls(rgb(plain["text_color"]))[2]     # neon family text vs bone text
    ash = GRADES[FilterThemeName.WRAECLAST_ASHES]
    assert ash.ash > 0
    for role in ("trade_armour", "gem", "charm"):
        grey = native_style(FilterThemeName.WRAECLAST_ASHES, role)
        colour = native_style(FilterThemeName.VERDANT_RELIC, role)
        assert _to_hls(rgb(grey["text_color"]))[2] < _to_hls(rgb(colour["text_color"]))[2], role
    # what matters keeps its colour in the ash theme: VALUABLE+ and the craft lane
    for role, tier in (("build_weapon", BaseTier.T1), ("craft_relevant", None), ("craft_premium", None)):
        assert _to_hls(rgb(native_style(FilterThemeName.WRAECLAST_ASHES, role, tier)["text_color"]))[2] >= .25, role


# == E. family differentiation ==============================================================================================================
def test_families_differ_on_several_axes_in_every_theme():
    for theme in THEMES:
        for pair, axes in family_separation(theme).items():
            assert len(axes) >= required_axes(theme, pair), (theme.value, pair, axes)


def test_separation_counts_real_axes():
    a = native_style(FilterThemeName.VOID_GOLD, "currency")
    assert separating_axes(a, a) == []                                                       # identical labels: nothing separates them
    assert {"treatment", "size", "beam", "sound"} <= set(separating_axes(native_style(FilterThemeName.VOID_GOLD, "hero"), a))


def test_treatments_are_distinct_silhouettes():
    assert set(TREATMENTS) == {d.variant for d in ROLE_DESIGNS.values()}
    for theme in THEMES:
        lum = {}
        for role, design in ROLE_DESIGNS.items():
            lum.setdefault(design.variant, []).append(_luminance(rgb(native_style(theme, role, BaseTier.T1 if role in TIER_LEVELS else None)["bg_color"])))
        assert min(lum["white_red"]) >= .70                                                   # white
        assert .30 <= min(lum["solid"]) and max(lum["solid"]) < .50                           # coloured bar, never "white"
        assert max(lum["slate"]) > max(lum["outline"]) and max(lum["slate"]) < .12            # grey stone, still a dark label
        assert max(lum["enamel"] + lum["outline"] + lum["dark"]) < .12                        # the dark family of plates


def test_enamel_means_coloured_text():
    for theme in THEMES:
        for role in ("build_weapon", "build_defense", "unique", "jewel", "waystone_high", "craft_premium"):
            style = native_style(theme, role, BaseTier.T1 if role in TIER_LEVELS else None)
            if GRADES[theme].ash and style["level"] in ("UTILITY", "LOW"):
                continue
            assert _to_hls(rgb(style["text_color"]))[2] >= .35, (theme, role)


# == B. the iconic white / red label ========================================================================================================
def test_white_red_is_reserved_for_the_apex():
    assert {r for r, d in ROLE_DESIGNS.items() if d.variant == "white_red"} == {"hero", "currency_premium"}
    hero_names = set(currency_tiers.TIERS[0].names) | set(currency_tiers.TIERS[1].names)
    assert hero_names == {"Hinekora's Lock", "Mirror of Kalandra", "Divine Orb"}
    for theme, role, tier, style in all_styles():
        white = _luminance(rgb(style["bg_color"])) >= .55
        assert white == (role in ("hero", "currency_premium")), (theme, role, tier)


def test_white_red_is_vivid_iconic_red():
    for theme in THEMES:
        for role in ("hero", "currency_premium"):
            style = native_style(theme, role)
            text, plate = rgb(style["text_color"]), rgb(style["bg_color"])
            hue, light, sat = _to_hls(text)
            assert (hue <= 22 or hue >= 335) and sat >= .85 and light >= .30, (theme, role, hue, light, sat)   # red, saturated, not maroon
            assert contrast(text, plate) >= WHITE_RED_TEXT_FLOOR and _to_hls(plate)[1] >= .88, (theme, role)
            assert style["font_size"] >= 41                                                   # the 5 : 1 floor is a large-text floor


def test_mythic_and_divine_never_tie():
    for theme in THEMES:
        hero, divine = native_style(theme, "hero"), native_style(theme, "currency_premium")
        assert hero["font_size"] > divine["font_size"]
        assert hero["play_effect"] != divine["play_effect"] and divine["play_effect"] == DIVINE_EFFECT
        assert hero["minimap_icon"] != divine["minimap_icon"]
        assert hero["border_color"] != divine["border_color"]
        assert int(hero["sound"].split()[1]) > int(divine["sound"].split()[1])
        assert measure(from_style("hero", hero)).attention > measure(from_style("currency_premium", divine)).attention


def test_white_red_does_not_spread_in_generated_filters(matrix, corpus):
    for (profile, theme), result in matrix.items():
        white_rules = [block for block in _blocks(result.text) if block[0] == "Show"
                       and _action(block, "SetBackgroundColor") and _luminance(rgb(_action(block, "SetBackgroundColor"))) >= .55]
        assert len(white_rules) == 2, (profile, theme, len(white_rules))
        assert all(_action(b, "SetTextColor") and _to_hls(rgb(_action(b, "SetTextColor")))[2] >= .85 for b in white_rules)
    rules = matrix[("Recommended", FilterThemeName.BLOOD_SIGIL)].rules
    white_items = {name for name, native in natives_from_rules(rules, corpus) if measure(native).white_plaque}
    assert white_items <= {"Hinekora's Lock", "Mirror of Kalandra", "Divine Orb", "2x Divine Orb"}, white_items


def test_white_budget_holds_in_dense_clusters(matrix):
    for theme in THEMES:
        rules = matrix[("Recommended", theme)].rules
        for scene in ("Real Game Cluster", "Showcase"):
            audit = audit_scene(theme.value, natives_from_rules(rules, preview_scene_items(scene)))
            assert audit.flags == [], (theme, scene, audit.flags)
            assert len(audit.summary()["white_plaques"]) <= 3


# == D. beams ===============================================================================================================================
def test_beam_policy_is_explicit():
    assert {r for r, k in BEAM_POLICY.items() if k == PERSISTENT} == {"hero", "currency_premium", "quest"}
    assert {r for r, k in BEAM_POLICY.items() if k == TEMP} == {"premium_currency", "special", "unique", "waystone_high"}
    quiet = {"build_weapon", "build_defense", "build_jewellery", "build_offhand", "fallback_weapon", "craft_premium", "craft_relevant",
             "crafting_base", "trade_weapon", "trade_armour", "trade_jewellery", "trade_craft", "trade", "currency_valuable", "currency",
             "currency_low", "tablet", "gem", "jewel", "charm", "high_unid", "socketable", "waystone_mid", "waystone", "crafting_currency",
             "generic", "generic_rare", "unknown"}
    assert quiet == set(ROLE_DESIGNS) - set(BEAM_POLICY)
    for theme in THEMES:
        for role in quiet:
            assert "play_effect" not in native_style(theme, role, BaseTier.T1 if role in TIER_LEVELS else None), (theme, role)


def test_mythic_pillar_colour_is_exclusive_in_its_theme():
    for theme, grade in GRADES.items():
        assert grade.hero_effect != DIVINE_EFFECT
        assert beam_for(theme, "hero") == grade.hero_effect and "Temp" not in beam_for(theme, "hero")
        others = {beam_for(theme, role).split()[0] for role in BEAM_POLICY if role != "hero"}
        assert grade.hero_effect not in others, (theme, grade.hero_effect, others)
        icons = {native_style(theme, r, BaseTier.T1 if r in TIER_LEVELS else None).get("minimap_icon", "") for r in ROLE_DESIGNS if r != "hero"}
        assert native_style(theme, "hero")["minimap_icon"] not in icons
        assert all(not i.startswith("0 ") for i in icons - {native_style(theme, "currency_premium")["minimap_icon"]})


def test_generated_filters_keep_persistent_beams_for_the_top_only(matrix):
    for (profile, theme), result in matrix.items():
        effects = [(b, _action(b, "PlayEffect")) for b in _blocks(result.text) if _action(b, "PlayEffect")]
        persistent = [e for _, e in effects if not e.endswith("Temp")]
        assert sorted(persistent) == sorted([GRADES[theme].hero_effect, DIVINE_EFFECT, "Green" if GRADES[theme].hero_effect != "Green" else "Cyan"]), \
            (profile, theme, persistent)
        assert all(b[0] == "Show" for b, _ in effects)
        rules = result.rules
        for name in ("Hinekora's Lock", "Mirror of Kalandra", "Divine Orb"):
            d = preview_decision(rules, PreviewItem(name, "t", "Stackable Currency", name))
            assert d.effect and "Temp" not in d.effect, (profile, theme, name)


# == C. sounds ==============================================================================================================================
def test_sound_vocabulary_is_native_and_tiered():
    assert all(1 <= i <= 16 for i in SOUND_WORDS.values()) and len(set(SOUND_WORDS.values())) == len(SOUND_WORDS)
    volumes = {role: volume for role, (_, volume) in SOUND_POLICY.items()}
    assert all(0 <= v <= 300 for v in volumes.values())
    assert [r for r, v in volumes.items() if v == 300] == ["hero"]                            # one sound at full volume: MYTHIC
    order = ["hero", "currency_premium", "premium_currency", "special", "waystone_high", "unique", "quest", "tablet", "currency_valuable"]
    assert [volumes[r] for r in order] == sorted(volumes.values(), reverse=True) and len(set(volumes.values())) == len(volumes)
    apex = {r for r, (word, _) in SOUND_POLICY.items() if word == "APEX"}
    assert apex == {r for r, d in ROLE_DESIGNS.items() if d.variant == "white_red"}             # hear sound 6 -> look for the white label


def test_build_craft_and_utility_are_silent():
    for theme, role, tier, style in all_styles():
        if role.startswith(("build_", "craft_", "trade", "fallback")) or role in ("crafting_base", "high_unid", "gem", "jewel", "charm", "currency",
                                                                                 "currency_low", "socketable", "waystone", "waystone_mid"):
            assert "sound" not in style, (theme, role, tier)


def test_generated_sounds_use_the_vocabulary_and_respect_profiles(matrix):
    for (profile, theme), result in matrix.items():
        sounds = [_action(b, "PlayAlertSound") for b in _blocks(result.text) if _action(b, "PlayAlertSound")]
        assert sounds and all(int(s.split()[0]) in SOUND_WORDS.values() for s in sounds)
        assert sum(s.startswith("6 ") for s in sounds) == 2                                     # MYTHIC and Divine rules only
        assert "PlayAlertSoundPositional" not in result.text and "CustomAlertSound" not in result.text
        valuable = preview_decision(result.rules, PreviewItem("Chaos Orb", "t", "Stackable Currency", "Chaos Orb"))
        # profile system V2: the soft currency word is SHOW+ through Strict and SHOW (silent) from Very Strict
        assert ("sound 2 " in valuable.native_details) == (profile in ("Relaxed", "Recommended", "Strict")), (profile, valuable.native_details)
    assert "currency_valuable" not in ALWAYS_SOUND_ROLES and "hero" in ALWAYS_SOUND_ROLES


def test_alert_density_in_the_real_cluster(matrix):
    rules = matrix[("Recommended", FilterThemeName.VOID_GOLD)].rules
    sounding = [i.label for i in REAL_GAME_ITEMS if "sound " in preview_decision(rules, i).native_details]
    assert len(sounding) <= 7, sounding                                                         # 18 labels, at most 7 make a sound
    assert {"Hinekora's Lock", "2x Divine Orb"} <= set(sounding)


def test_hidden_loot_is_silenced_without_changing_visibility(matrix, corpus):
    for (profile, theme), result in matrix.items():
        for block in _blocks(result.text):
            assert (HIDDEN_DROP_SOUND in block) == (block[0] == "Hide"), (profile, theme, block[:2])
        assert validate_syntax(result.text).passed
    rules = matrix[("Recommended", FilterThemeName.VOID_GOLD)].rules
    from dataclasses import replace
    stripped = [replace(r, lines=[l for l in r.lines if l.strip() != HIDDEN_DROP_SOUND]) for r in rules]
    for item in corpus:
        assert preview_decision(rules, item).hidden == preview_decision(stripped, item).hidden, item.name
    assert all(c.split()[0] != "DisableDropSound" for r in to_ir(rules) for c in r.conditions)


def test_validator_rejects_a_malformed_drop_sound_flag():
    assert validate_syntax("Hide\n\tRarity Normal\n\tDisableDropSound True\n").passed
    assert not validate_syntax("Hide\n\tRarity Normal\n\tDisableDropSound Maybe\n").passed


# == G. FILTER-09 exact BaseType contract ===================================================================================================
def test_exact_basetype_contract_holds_in_every_filter(matrix):
    for (profile, theme), result in matrix.items():
        assert result.valid and validate_all(result.text).passed, (profile, theme)
        for line in result.text.splitlines():
            if line.strip().startswith("BaseType"):
                condition = BaseCondition.parse(line.strip())
                assert condition is not None
                assert condition.match == BaseMatch.EXACT_BASE or "# PARTIAL_BASE_PATTERN" in result.text, (profile, theme, line)


def test_mythic_names_are_exact_and_evidenced(matrix):
    assert "Mirror of Kalandra" in COMMUNITY_SPECIAL_BASES and "Mirror of Kalandra" not in PINNED_SPECIAL_BASES   # never presented as GGG
    assert SPECIAL_BASES["Mirror of Kalandra"] == "Stackable Currency"
    hero = currency_tiers.TIERS[0]
    assert hero.evidence_of("Mirror of Kalandra") == currency_tiers.COMMUNITY_FILTER and hero.evidence_of("Hinekora's Lock") == currency_tiers.GGG_NOTICE
    rules = matrix[("Recommended", FilterThemeName.VOID_GOLD)].rules
    assert preview_decision(rules, PreviewItem("Mirror of Kalandra", "t", "Stackable Currency", "Mirror of Kalandra")).style_role == "hero"
    # exact, never partial: a longer name containing it is NOT the hero (it falls through to ordinary currency, still shown)
    probe = preview_decision(rules, PreviewItem("Mirror of Kalandra Replica", "t", "Stackable Currency", "Mirror of Kalandra Replica"))
    assert probe.style_role != "hero" and not probe.hidden


# == visibility: V4 vs the FILTER-09 filters, and theme invariance ==========================================================================
def test_theme_never_changes_visibility(matrix, corpus):
    for profile in PROFILES:
        reference = None
        for theme in THEMES:
            signature = tuple(preview_decision(matrix[(profile, theme)].rules, i).hidden for i in corpus)
            reference = reference or signature
            assert signature == reference, (profile, theme)


# == F. craft-relevant bases stay visible and craft-worthy ==================================================================================
def test_utility_belt_opportunity_survives_v4(matrix):
    from exilelens.filters import crafting_intel as ci
    assessment = ci.assess("Utility Belt")
    for (profile, theme), result in matrix.items():
        placed = ci.gate_for(assessment, profile)                    # FILTER-09 policy: Very Strict deliberately drops RELEVANT substrates
        for rarity in ("Normal", "Magic"):
            d = preview_decision(result.rules, make_item("Utility Belt", rarity=rarity, item_class="Belts", item_level=82))
            expected = placed is not None and rarity in placed[1] and 82 >= placed[0]
            assert (not d.hidden) == expected, (profile, theme, rarity, d.rule_name)
            if expected:
                assert d.style_role in ("craft_relevant", "craft_premium"), (profile, theme, d.rule_name)
                assert not d.effect and "sound" not in d.native_details
    for theme in THEMES:
        craft = native_style(theme, "craft_relevant")
        assert craft["level"] == "UTILITY" and craft["variant"] == "outline" and craft["family"] == "craft"
        assert measure(from_style("craft_relevant", craft)).attention * 1.5 < measure(from_style("currency_premium", native_style(theme, "currency_premium"))).attention
        assert measure(from_style("craft_relevant", craft)).attention < measure(from_style("premium_currency", native_style(theme, "premium_currency"))).attention
        premium = native_style(theme, "craft_premium")
        assert premium["variant"] == "enamel" and premium["minimap_icon"].endswith("Moon") and "play_effect" not in premium
        assert _luminance(rgb(premium["bg_color"])) < .12                                       # never a gold / white plate: not premium currency


def test_real_cluster_craft_and_unidentified_read_differently(matrix):
    for theme in THEMES:
        rules = matrix[("Recommended", theme)].rules
        natives = dict(natives_from_rules(rules, REAL_GAME_ITEMS))
        belt, unid = natives["Utility Belt"], natives["Warlord Cuirass (Tier 3)"]
        # A build/trade rule may own this tier-3 base before the unidentified row.
        # Its resolved family/palette stays distinct without forcing an alert treatment.
        assert belt.family != unid.family
        assert (belt.text, belt.border, belt.background) != (unid.text, unid.border, unid.background)


# == policy matrix (helper used by the docs / artifacts) ====================================================================================
def test_policy_matrix_matches_the_tables():
    rows = policy_matrix(FilterThemeName.EMBERFORGE)
    assert {r["role"] for r in rows} == set(ROLE_DESIGNS)
    by = {r["role"]: r for r in rows}
    assert by["hero"]["beam"] == "persistent" and by["hero"]["sound"] == "6 300" and by["hero"]["minimap_icon"].startswith("0 Orange")
    assert by["currency_premium"]["beam"] == "persistent" and by["currency_premium"]["beam_colour"] == "White"
    assert by["unique"]["beam_colour"] == "Red"                                                 # Orange is Emberforge's MYTHIC pillar
    assert by["craft_relevant"]["beam"] == "none" and by["craft_relevant"]["sound"] == ""
    assert all(r["font"] == LEVEL_POLICY[r["level"]]["font"] for r in rows)
    assert set(FAMILY_PROBES) >= {"mythic", "divine", "premium_currency", "regular_currency", "build_gear", "craft_base", "trade_base", "unique",
                                  "gem", "tablet", "waystone_high", "waystone_mid", "waystone", "jewel", "charm"}
