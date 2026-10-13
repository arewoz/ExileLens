"""Focused checks for the experimental preview and safe test installation."""
from __future__ import annotations

from exilelens.filters.install import (TEST_FILTER_FILENAME, get_filter_path, get_installed_filter_info,
                                       install_test_filter, install_batch_filters)
from exilelens.filters.validation import validate_all, validate_base_types
from exilelens.filters.profiles import BaseTier, DefenseLayer, FilterProfileName, FilterThemeName, ProductSlot, SlotPriority, get_profile_with_theme
from exilelens.filters.rules import RuleGenerator
from exilelens.filters.priorities import BASE_TIERS, CATALOG_AUDIT
from exilelens.filters.verified_bases import FILTER_TO_POB_CLASS, load_verified_bases, load_base_properties
from pathlib import Path
import hashlib
import pytest
from exilelens.filters.preview import PREVIEW_ITEMS, PreviewItem, preview_decision, preview_scene_items, visible_preview_entries
from exilelens.filters.rules import GeneratedRule
from exilelens.filters.style_system import ROLE_DESIGNS, native_style


def test_preview_uses_first_generated_rule_and_its_colors():
    rules = [
        GeneratedRule("HIDE", "low ring", ["Hide", 'BaseType "Amber Ring"'], 1),
        GeneratedRule("SHOW", "currency", ["Show", 'Class "Currency"',
                                       "SetTextColor 250 210 30 255"], 2),
    ]
    hidden = preview_decision(rules, PreviewItem("Amber Ring", "Jewellery", "Rings", "Amber Ring"))
    shown = preview_decision(rules, PreviewItem("Exalted Orb", "Currency", "Currency"))
    assert hidden.hidden and hidden.rule_name == "low ring"
    assert not shown.hidden and "rgba(250,210,30,1.000)" in shown.stylesheet


def test_install_preserves_unrelated_test_file(tmp_path):
    destination = tmp_path / TEST_FILTER_FILENAME
    destination.write_text("personal filter", encoding="utf-8")
    content = "# ExileLens Build-Aware Loot Filter\n" + "# heading\n" * 10 + "Show\n\tClass \"Currency\"\n"
    result = install_test_filter(content, tmp_path, "Recommended", "Void Gold")
    assert not result.success
    assert destination.read_text(encoding="utf-8") == "personal filter"


def test_install_replaces_own_file_and_verifies(tmp_path):
    content = "# ExileLens Build-Aware Loot Filter\n" + "# heading\n" * 10 + "Show\n\tClass \"Currency\"\n"
    first = install_test_filter(content, tmp_path, "Recommended", "Void Gold")
    second = install_test_filter(content + "# updated\n", tmp_path, "Recommended", "Blood Sigil")
    assert first.success and first.verified and second.success and second.verified
    assert second.destination.read_bytes() == (content + "# updated\n").encode("utf-8")


def test_installed_filter_info_reports_file_hash(tmp_path):
    content = ('# ExileLens Build-Aware Loot Filter\n'
               '# Profile: Very Strict\n# Theme: Blood Sigil\n'
               'Show\n\tClass "Stackable Currency"\n')
    path = tmp_path / TEST_FILTER_FILENAME
    path.write_bytes(content.encode("utf-8"))
    info = get_installed_filter_info(tmp_path)
    assert info is not None
    assert info["profile"] == "Very Strict" and info["theme"] == "Blood Sigil"
    assert info["sha256"] == hashlib.sha256(path.read_bytes()).hexdigest()


def test_observed_currency_scene_follows_the_currency_ladder():
    """Profile system V2: observed currency is classified by the V4 ladder (one rule per tier), not by one generic Currency rule."""
    items = preview_scene_items("Observed Currency")
    assert [item.name for item in items] == [
        "Exalted Orb", "Armourer's Scrap", "Lesser Jeweller's Orb"]
    rules = _sample_rules(FilterProfileName.RECOMMENDED, FilterThemeName.BLOOD_SIGIL)
    decisions = {item.name: preview_decision(rules, item) for item in items}
    assert not any(decision.hidden for decision in decisions.values())
    assert {name: d.style_role for name, d in decisions.items()} == {
        "Exalted Orb": "currency_valuable", "Armourer's Scrap": "currency_low", "Lesser Jeweller's Orb": "currency"}
    assert [decisions[n].font_size for n in ("Exalted Orb", "Lesser Jeweller's Orb", "Armourer's Scrap")] == [36, 30, 25]


@pytest.mark.parametrize("name", ["Terror Staff", "Primordial Staff", "Imperial Staff"])
def test_reported_staff_names_are_rejected(name):
    result = validate_base_types(f'Show\n\tClass "Staves"\n\tBaseType "Ashen Staff" "{name}"\n')
    assert not result.passed
    assert any(name in error for error in result.errors)
    assert name not in BASE_TIERS["Staves"]


def test_previous_classifications_are_audited_and_excluded():
    wrong = CATALOG_AUDIT["wrong_class"]
    assert ("Crossbows", "Composite Bow", "Bow") in wrong
    assert ("Foci", "Ochre Sceptre", "Sceptre") in wrong
    assert ("Two Hand Maces", "Morning Star", "One Hand Mace") in wrong
    assert "Composite Bow" not in BASE_TIERS["Crossbows"]
    assert "Ochre Sceptre" not in BASE_TIERS["Foci"]


def test_unknown_inside_multi_base_rule_and_class_mismatch():
    text = 'Show\n\tClass "Staves"\n\tBaseType "Ashen Staff" "Unknown Staff" "Voltaic Staff"\n'
    assert any("Unknown Staff" in error for error in validate_all(text).errors)
    mismatch = 'Show\n\tClass "Crossbows"\n\tBaseType "Composite Bow"\n'
    assert any("incompatible" in error for error in validate_all(mismatch).errors)
    malformed = 'Show\n\tBaseType "Ashen Staff" unquoted\n'
    assert any("malformed" in error for error in validate_all(malformed).errors)


def test_every_emitted_base_in_saved_matrix_is_verified():
    from exilelens.filters.intel_generate import generate
    from exilelens.filters.build_needs import BuildNeedsSnapshot
    from exilelens.filters.profiles import FilterProfileName, FilterThemeName
    verified = load_verified_bases()
    for profile in FilterProfileName:
        for theme in FilterThemeName:
            content = generate(BuildNeedsSnapshot.unavailable("General", "fixture"), profile, theme).text
            result = validate_all(content)
            assert result.passed, (profile, theme, result.errors)
            assert "Primordial Staff" not in content
    assert all(FILTER_TO_POB_CLASS[cls] == verified[name]
               for cls, names in BASE_TIERS.items() for name in names)


def test_validation_failure_preserves_installed_filter(tmp_path):
    destination = tmp_path / TEST_FILTER_FILENAME
    original = '# ExileLens Build-Aware Loot Filter\nShow\n\tClass "Currency"\n'
    destination.write_text(original, encoding="utf-8")
    invalid = '# ExileLens Build-Aware Loot Filter\n' + '# heading\n' * 10 + 'Show\n\tBaseType "Ashen Staff" "Terror Staff"\n'
    result = install_test_filter(invalid, tmp_path, "Recommended", "Void Gold")
    assert not result.success and "Terror Staff" in result.error_message
    assert destination.read_text(encoding="utf-8") == original


def test_batch_validation_is_atomic_before_install(tmp_path):
    good = '# ExileLens Build-Aware Loot Filter\n' + '# heading\n' * 10 + 'Show\n\tClass "Currency"\n'
    bad = good + 'Show\n\tBaseType "Primordial Staff"\n'
    result = install_batch_filters([(good, "Relaxed", "Void Gold"),
                                    (bad, "Recommended", "Void Gold")], tmp_path)
    assert not result.all_successful and result.successful == 0
    assert not list(tmp_path.glob("*.filter"))
    assert "Primordial Staff" in result.results[0].error_message


def test_native_action_error_blocks_install_and_preserves_existing_file(tmp_path):
    from exilelens.filters.intel_generate import generate
    from exilelens.filters.build_needs import BuildNeedsSnapshot
    original = generate(BuildNeedsSnapshot.unavailable("General", "fixture"), "Very Strict", "Emberforge").text
    first = install_test_filter(original, tmp_path, "Endgame", "Emberforge")
    assert first.success and first.verified
    corrupt = original.replace("PlayEffect Orange", "PlayEffect Gold", 1)
    rejected = install_test_filter(corrupt, tmp_path, "Endgame", "Emberforge")
    assert not rejected.success and "PlayEffect" in rejected.error_message
    assert get_filter_path(tmp_path, "Very Strict").read_text(encoding="utf-8") == original


def test_missing_snapshot_fails_closed(monkeypatch):
    from exilelens.filters import validation
    def unavailable():
        raise FileNotFoundError("snapshot missing")
    monkeypatch.setattr(validation, "load_verified_bases", unavailable)
    result = validation.validate_all('Show\n\tBaseType "Ashen Staff"\n')
    assert not result.passed
    assert "snapshot missing" in result.errors[0]


@pytest.mark.parametrize("line", [
    "PlayEffect Gold", "PlayEffect Red Lasting", "MinimapIcon 1 Gold Diamond",
    "MinimapIcon 0 Red Octagon", "PlayAlertSound 17 100", "SetFontSize 46",
    "SetTextColor 1 2", "SetBorderColor 1 2 3 4 5",
    "SetBackgroundColor 1 x 3", 'Class "Not A PoE2 Class"',
    "TotallyUnknown 1", "ItemLevel >= abc",
])
def test_serialized_output_rejects_invalid_native_directive(line):
    result = validate_all(f"Show\n\t{line}\n")
    assert not result.passed, line


def _sample_rules(profile_name, theme_name):
    staff = SlotPriority(
        slot=ProductSlot.WEAPON_1, defense_layer=DefenseLayer.ENERGY_SHIELD,
        base_tiers={"Ashen Staff": BaseTier.T1}, min_item_level=75,
        min_unidentified_tier=2, required_sockets=0, required_links=0,
        defensive_floors={}, preferred_implicits=[], blocked_bases=frozenset(),
    )
    profile = get_profile_with_theme(profile_name, theme_name)
    return RuleGenerator({ProductSlot.WEAPON_1: staff}, profile, "Spark", DefenseLayer.ENERGY_SHIELD).generate_all()


def test_five_profiles_change_build_trade_and_waystone_visibility():
    assert [p.value for p in FilterProfileName] == ["Relaxed", "Recommended", "Strict", "Very Strict", "Uber Strict"]
    build = PreviewItem("Ashen Staff", "Build", "Staves", "Ashen Staff", "Rare", item_level=83)
    trade = PreviewItem("Galvanic Wand", "Trade", "Wands", "Galvanic Wand", "Rare", item_level=80)
    waystone = PreviewItem("Tier 8 Waystone", "Waystone", "Waystones", waystone_tier=8)
    relaxed = _sample_rules(FilterProfileName.RELAXED, FilterThemeName.VOID_GOLD)
    uber = _sample_rules(FilterProfileName.UBER_STRICT, FilterThemeName.VOID_GOLD)
    assert preview_decision(relaxed, build).source == "Build"
    assert not preview_decision(uber, build).hidden            # build ADDS: the build lane keeps it visible (QUIET) even at Uber Strict
    assert preview_decision(uber, build).state == "QUIET"
    assert preview_decision(relaxed, trade).source == "Trade"
    assert preview_decision(uber, trade).hidden                # a generic top-base Rare below item level 82 is HIDE at Uber Strict
    assert not preview_decision(uber, PreviewItem("Galvanic Wand", "Trade", "Wands", "Galvanic Wand", "Rare", item_level=84)).hidden
    assert not preview_decision(relaxed, waystone).hidden
    assert preview_decision(uber, waystone).hidden             # a far-below waystone is HIDE at Uber Strict (area level 82, tier 8)
    signatures = [tuple((rule.name, tuple(rule.lines[:5])) for rule in _sample_rules(name, FilterThemeName.VOID_GOLD)) for name in FilterProfileName]
    assert len(set(signatures)) == 5
    waystone_counts = []
    for name in FilterProfileName:
        rules = _sample_rules(name, FilterThemeName.VOID_GOLD)
        waystone_counts.append(sum(not preview_decision(
            rules, PreviewItem(f"Waystone {tier}", "Waystone", "Waystones", waystone_tier=tier)
        ).hidden for tier in range(1, 16)))
    assert waystone_counts == [15, 15, 15, 5, 5]               # area level 82: tiers 1-13 are far below it; T11+ are protected by their rows


def test_rare_unknowns_are_not_hidden_by_build_irrelevance():
    rules = _sample_rules(FilterProfileName.UBER_STRICT, FilterThemeName.VOID_GOLD)
    for rarity in ("Rare", "Unique"):
        item = PreviewItem("Unknown Mace", "Unknown", "One Hand Maces", "Unknown Mace",
                           rarity, item_level=65, base_armour=0)
        decision = preview_decision(rules, item)
        assert not decision.hidden and decision.state == "SAFETY"       # a base the snapshot does not know: the explicit catch-all
    assert all("Sockets >=" not in "\n".join(rule.lines) and
               "LinkedSockets >=" not in "\n".join(rule.lines)
               for rule in rules if rule.category == "BUILD_WEAPON")


def test_rule_evidence_keeps_decision_dimensions_separate():
    from exilelens.filters.decision import MarketContext, MarketLevel
    rules = _sample_rules(FilterProfileName.RECOMMENDED, FilterThemeName.VOID_GOLD)
    assert all(rule.evidence and rule.evidence.native_conditions for rule in rules)
    trade = next(rule for rule in rules if rule.category == "TRADE_BASES")
    assert "HEURISTIC" in trade.evidence.market_opportunity
    assert "confirmed" in trade.evidence.market_opportunity
    build = next(rule for rule in rules if rule.category == "BUILD_WEAPON")
    assert "Spark" in build.evidence.build_relevance
    assert build.evidence.market_opportunity == "not evaluated"
    assert MarketContext().level == MarketLevel.HEURISTIC
    with pytest.raises(ValueError):
        MarketContext(level=MarketLevel.LIVE, source="listing asks")


def test_unmapped_skill_has_no_weapon_candidate_lane():
    """Profile system V2: without verified weapon-class evidence there is no BUILD rule at all (the broad fallback lane is retired); the
    general filter decides the item."""
    priority = SlotPriority(
        slot=ProductSlot.WEAPON_1, defense_layer=DefenseLayer.UNKNOWN,
        base_tiers={"Ashen Staff": BaseTier.T1}, min_item_level=75,
        min_unidentified_tier=2, required_sockets=0, required_links=0,
        defensive_floors={}, preferred_implicits=[], blocked_bases=frozenset())
    profile = get_profile_with_theme(FilterProfileName.RECOMMENDED, FilterThemeName.VOID_GOLD)
    rules = RuleGenerator({ProductSlot.WEAPON_1: priority}, profile,
                          "Summon Infernal Hound", DefenseLayer.UNKNOWN).generate_all()
    assert not [r for r in rules if r.category.startswith("BUILD")]
    decision = preview_decision(rules, PreviewItem("Ashen Staff", "Weapon", "Staves",
                                                   "Ashen Staff", "Rare", item_level=89))
    assert decision.source != "Build" and decision.style_role != "fallback_weapon"
    assert decision.effect == "" and decision.minimap_icon == "" and "sound" not in decision.native_details


def test_mixed_defence_units_do_not_trigger_pure_layer_hides():
    assert DefenseLayer.from_totals(es=1000, ar=1, ev=0, ward=0) == DefenseLayer.HYBRID_AR_ES


def test_pinned_base_properties_explain_implicit_and_impossible_floor_is_removed():
    bases = load_base_properties()
    # the PoB2 universe is 1769 names; only the native ground-valid subset (1749) is the filter's universe (see test_filter_native_basetype)
    from exilelens.filters.verified_bases import load_pob_bases
    assert len(load_pob_bases()) == 1769
    assert len(bases) == len(load_verified_bases()) == 1749
    assert "Firebolt" in bases["Ashen Staff"]["implicit"]
    assert bases["Vile Robe"]["energy_shield"] == 171
    rules = _sample_rules(FilterProfileName.RECOMMENDED, FilterThemeName.VOID_GOLD)
    assert "Firebolt" in preview_decision(rules, PREVIEW_ITEMS[13]).provenance
    assert all(not line.strip().startswith("BaseEnergyShield >=")
               for rule in rules if rule.category == "BUILD_DEFENSE" for line in rule.lines)


def test_verified_high_es_robe_is_a_top_base_and_survives_where_the_matrix_keeps_it():
    from exilelens.filters.priorities import BASE_TIERS

    assert BASE_TIERS["Body Armours"]["Vile Robe"] == BaseTier.T1
    assert BASE_TIERS["Body Armours"]["Silk Robe"] == BaseTier.T4
    robe = PreviewItem("Vile Robe", "Crafting", "Body Armours", "Vile Robe", "Rare", quality=20, item_level=86, base_energy_shield=171)
    for profile in (FilterProfileName.RECOMMENDED, FilterProfileName.STRICT, FilterProfileName.VERY_STRICT, FilterProfileName.UBER_STRICT):
        rules = _sample_rules(profile, FilterThemeName.VOID_GOLD)
        assert not preview_decision(rules, robe).hidden, profile        # a Rare top base at item level 86 stays (QUIET at Uber Strict)


def test_craft_policy_is_one_ladder_with_matrix_states():
    """Profile system V2: there is no Endgame crafting policy; one CRAFT ladder, and the matrix gives the state per level."""
    from exilelens.filters import crafting_intel as ci
    candidate = PreviewItem("Permafrost Staff", "Crafting", "Staves", "Permafrost Staff", rarity="Normal", item_level=86, quality=20)
    states = {}
    for profile in FilterProfileName:
        rules = _sample_rules(profile, FilterThemeName.VOID_GOLD)
        decision = preview_decision(rules, candidate)
        states[profile.value] = "HIDE" if decision.hidden else decision.state
    assessment = ci.assess("Permafrost Staff")
    assert assessment.level in (ci.CraftLevel.PREMIUM, ci.CraftLevel.RELEVANT, ci.CraftLevel.LOW)
    order = {"SHOW+": 3, "SHOW": 2, "QUIET": 1, "HIDE": 0, "SAFETY": 3}
    ranks = [order[states[p.value]] for p in FilterProfileName]
    assert ranks == sorted(ranks, reverse=True), states                 # visibility never increases with strictness


def test_eight_themes_update_real_preview_decision():
    assert len(FilterThemeName) == 8
    item = PreviewItem("Ashen Staff", "Build", "Staves", "Ashen Staff", "Rare", item_level=89)
    decisions = [preview_decision(_sample_rules(FilterProfileName.RECOMMENDED, theme), item) for theme in FilterThemeName]
    assert all(not decision.hidden and decision.source == "Build" for decision in decisions)
    assert len({decision.stylesheet for decision in decisions}) == 8


def test_category_first_native_styles_have_distinct_background_weight():
    for theme in FilterThemeName:
        hero = native_style(theme, "hero")
        premium = native_style(theme, "premium_currency")
        currency = native_style(theme, "currency")
        build = native_style(theme, "build_weapon", BaseTier.T1)
        armour = native_style(theme, "build_defense", BaseTier.T1)
        jewel = native_style(theme, "build_jewellery", BaseTier.T1)
        craft = native_style(theme, "crafting_base")
        assert hero["font_size"] > premium["font_size"] > currency["font_size"]
        assert hero["bg_color"].endswith(" 255") and premium["bg_color"].endswith(" 255")
        from exilelens.filters.style_system import LEVEL_POLICY
        assert craft["bg_color"].endswith(f" {LEVEL_POLICY['UTILITY']['bg_alpha']}")   # crafting base: UTILITY level
        assert len({build["bg_color"], armour["bg_color"], jewel["bg_color"],
                    currency["bg_color"], craft["bg_color"]}) == 5
    assert len({native_style(theme, "hero")["bg_color"] for theme in FilterThemeName}) == 8


def test_complete_profile_theme_matrix_is_native_and_visibility_invariant():
    matrix = {}
    for profile in FilterProfileName:
        for theme in FilterThemeName:
            rules = _sample_rules(profile, theme)
            from exilelens.filters.serialize import FilterSerializer, FilterMetadata
            from datetime import datetime
            output = FilterSerializer(FilterMetadata("fixture", "Witch", "Blood Mage", "Spark",
                                                     profile.value, datetime(2026, 9, 27), "qa",
                                                     theme_name=theme.value)).serialize(rules)
            assert validate_all(output).passed, (profile, theme)
            matrix[(profile, theme)] = tuple(preview_decision(rules, item).hidden for item in PREVIEW_ITEMS)
    assert len(matrix) == 40
    for profile in FilterProfileName:
        assert len({matrix[(profile, theme)] for theme in FilterThemeName}) == 1
    assert {"hero", "premium_currency", "crafting_currency", "trade_jewellery", "waystone"} <= ROLE_DESIGNS.keys()


def test_currency_and_equipment_roles_follow_first_matching_export_rule():
    rules = _sample_rules(FilterProfileName.RECOMMENDED, FilterThemeName.VOID_GOLD)
    hero, basic_exalted, basic_transmute, enhanced = [preview_decision(rules, item) for item in PREVIEW_ITEMS[:4]]
    assert hero.style_role == "hero" and hero.importance == "HERO"
    assert basic_exalted.style_role == "currency_valuable"  # a ladder tier by name: no live-value claim
    assert basic_transmute.style_role == "currency"
    assert enhanced.style_role == "premium_currency"
    enhanced_craft = preview_decision(rules, PREVIEW_ITEMS[4])
    assert enhanced_craft.style_role == "crafting_currency"
    assert len({x.stylesheet for x in (hero, basic_exalted, enhanced_craft, enhanced)}) == 4
    staff = next(item for item in PREVIEW_ITEMS if item.name == "Ashen Staff")
    tablet = next(item for item in PREVIEW_ITEMS if item.item_class == "Tablet")
    augment = next(item for item in PREVIEW_ITEMS if item.item_class == "Augment")
    assert preview_decision(rules, staff).style_role == "build_weapon"
    assert preview_decision(rules, tablet).style_role == "tablet"
    assert preview_decision(rules, augment).style_role == "socketable"
    assert not validate_all('Show\n\tClass "Socketable"\n').passed


@pytest.mark.parametrize("theme", list(FilterThemeName))
def test_theme_rules_emit_one_native_action_per_style_property(theme):
    rules = _sample_rules(FilterProfileName.RECOMMENDED, theme)
    for rule in rules:
        for action in ("SetFontSize", "SetTextColor", "SetBorderColor",
                       "SetBackgroundColor", "MinimapIcon", "PlayEffect"):
            assert sum(line.strip().startswith(action + " ") for line in rule.lines) <= 1, rule.name


def test_hero_and_unified_visibility_are_rule_driven():
    rules = _sample_rules(FilterProfileName.RECOMMENDED, FilterThemeName.VOID_GOLD)
    hero = preview_decision(rules, PREVIEW_ITEMS[0])
    assert hero.importance == "HERO" and hero.source == "Trade"
    assert hero.minimap_icon == "0 Yellow Star" and hero.effect == "Yellow"
    assert "font 45" in hero.native_details and "rgba(" in hero.stylesheet
    entries = [(item, preview_decision(rules, item)) for item in PREVIEW_ITEMS]
    assert 20 <= len(entries) <= 30
    hidden_count = sum(decision.hidden for _, decision in entries)
    assert hidden_count > 0
    assert len(visible_preview_entries(entries)) == len(entries) - hidden_count


def test_pinned_special_name_needs_its_documented_class():
    assert validate_all('Show\n\tClass "Stackable Currency"\n\tBaseType == "Hinekora\'s Lock"\n').passed
    assert not validate_all('Show\n\tClass "Rings"\n\tBaseType == "Hinekora\'s Lock"\n').passed
    # the bare form is a substring match in the native language: refused unless explicitly marked as a partial pattern
    assert not validate_all('Show\n\tClass "Stackable Currency"\n\tBaseType "Hinekora\'s Lock"\n').passed


def test_ground_preview_content_width_and_nonoverlap(monkeypatch):
    from PySide6.QtWidgets import QApplication
    from exilelens.ui.filters_page import LootGroundScene, _ground_label, _ground_layout, _ground_positions
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance() or QApplication([])
    scene = LootGroundScene()
    rules = _sample_rules(FilterProfileName.RECOMMENDED, FilterThemeName.VOID_GOLD)
    decision = preview_decision(rules, PREVIEW_ITEMS[0])
    assert decision.font_size == 45
    for name in ("Orb", "Treasurer's Irradiated Tablet of Strongboxes",
                 "Doom Grasp Apex Precursor Tablet of the Forgotten Empire and Beyond"):
        label = _ground_label(scene, PreviewItem(name, "Tablet", "Tablet"), decision)
        assert label.width() >= label.fontMetrics().horizontalAdvance(name) + 20
        assert label.height() >= label.fontMetrics().height() + 10
        assert "..." not in label.text()
        assert label.font().capitalization() == label.font().Capitalization.SmallCaps
        assert label.font().letterSpacing() > 1
    sizes = [(120, 30)] * 25
    assert _ground_positions(10, sizes, 900, 1000) != _ground_positions(11, sizes, 900, 1000)
    positions = _ground_positions(10, sizes, 900, 1000, ["HIGH"] * 5 + ["MEDIUM"] * 10 + ["LOW"] * 10)
    assert len(positions) == 25
    assert 5 < len({y for _, y in positions}) < 25  # Staggered cluster, not uniform rows.
    _, needed_height = _ground_layout(10, sizes, 900)
    assert max(y + 30 for _, y in positions) < needed_height
    for i, (x, y) in enumerate(positions):
        assert 0 <= x and x + sizes[i][0] <= 900 and 0 <= y and y + sizes[i][1] <= 1000
        for xx, yy in positions[i + 1:]:
            assert x + 120 <= xx or xx + 120 <= x or y + 30 <= yy or yy + 30 <= y
    scene.close()


def test_ground_layout_accommodates_long_labels_without_clipping():
    from exilelens.ui.filters_page import _ground_layout

    sizes = [(795, 54), (410, 40), (380, 35), (210, 31), (690, 50)]
    positions, height = _ground_layout(42, sizes, 900)
    for i, ((x, y), (width, item_height)) in enumerate(zip(positions, sizes)):
        assert 0 <= x and x + width <= 900
        assert 0 <= y and y + item_height < height
        for (xx, yy), (other_width, other_height) in zip(positions[i + 1:], sizes[i + 1:]):
            assert x + width <= xx or xx + other_width <= x or y + item_height <= yy or yy + other_height <= y


def test_ground_layout_uses_available_width_without_fixed_three_item_rows():
    from exilelens.ui.filters_page import _ground_layout

    sizes = [(120, 34)] * 10
    wide_positions, wide_height = _ground_layout(7, sizes, 900)
    narrow_positions, narrow_height = _ground_layout(7, sizes, 560)
    assert len({y for _, y in wide_positions}) > 2
    assert all(x + 120 <= 900 for x, _ in wide_positions)
    assert all(x + 120 <= 560 for x, _ in narrow_positions)
    assert wide_height < narrow_height


def test_dashboard_preview_controls_change_rendered_labels(monkeypatch, tmp_path):
    from datetime import datetime
    from types import SimpleNamespace
    from PySide6.QtCore import QObject, Signal
    from PySide6.QtWidgets import QApplication, QLabel
    from exilelens.ui.filters_page import FiltersPage

    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance() or QApplication([])

    class Controller(QObject):
        build_changed = Signal()
        engine_ready = Signal()
        engine_failed = Signal(str)

        def __init__(self):
            super().__init__()
            self.engine = None
            self.build_info = SimpleNamespace(is_ready=False, state=SimpleNamespace(value="not_loaded"),
                                              error_message="", path="", name="")

    page = FiltersPage(Controller(), SimpleNamespace())
    # FILTER-08C: the dashboard no longer injects legacy slot priorities; it builds from a needs snapshot. An unmeasured
    # Spark build exercises the conservative-fallback path of the same intelligence pipeline.
    from exilelens.filters.build_needs import BuildNeedsSnapshot
    from exilelens.filters.intel_generate import fingerprint_from_needs
    page._fingerprint = fingerprint_from_needs(
        BuildNeedsSnapshot.unavailable("Preview fixture", "preview test", skill_name="Spark",
                                       equipped={"WEAPON_1": "Ashen Staff"}),
        class_name="Witch", ascendancy="Blood Mage")
    page._config_changed()

    def label_count():
        return sum(isinstance(child, QLabel) for child in page._scene.children())

    page._render_preview()
    shown = label_count()
    assert page._scene_preset.currentText() == "Mixed Loot"   # the default scene shows every level and family
    assert shown < len(preview_scene_items("Mixed Loot"))
    assert page._scene.minimumWidth() < 900
    page._filter_dir = tmp_path
    page._update_installed()
    assert "awaits installation" in page._hashes.text()
    result = install_test_filter(page._filter_text, tmp_path, "Recommended", "Void Gold")
    assert result.success and result.verified
    page._update_installed()
    assert "matches the installed file" in page._hashes.text()
    assert "In-game refresh: unconfirmed" in page._hashes.text()
    page._scene_preset.setCurrentText("Clutter Stress Test")
    assert label_count() <= len(PREVIEW_ITEMS)
    void_text = page._filter_text
    page._theme.setCurrentIndex(page._theme.findText("Emberforge"))
    assert page._filter_text != void_text and "Theme: Emberforge" in page._filter_text
    assert "Installed file is Recommended / Void Gold" in page._sync_notice.text()
    assert "awaits installation" in page._hashes.text()
    recommended_count = label_count()
    page._profile.setCurrentIndex(page._profile.findText("Uber Strict"))
    assert "Profile: Uber Strict" in page._filter_text
    assert label_count() < recommended_count
    page.close()
