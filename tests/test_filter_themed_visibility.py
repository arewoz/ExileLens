"""Themed visibility coverage: every item ExileLens keeps visible matches an explicit ExileLens rule with the V4 text / plaque actions.

Run with:  python -m pytest tests/test_filter_themed_visibility.py -m ""
"""
from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from exilelens.filters import profile_policy as pp
from exilelens.filters import style_coverage as sc
from exilelens.filters.inspector import make_item
from exilelens.filters.intel_generate import generate
from exilelens.filters.preview import PreviewItem, preview_decision
from exilelens.filters.profile_oracle import UNKNOWN_ROW, classify
from exilelens.filters.profiles import FilterThemeName

ROOT = Path(__file__).resolve().parents[1]
LEVELS = pp.LEVELS


def _needs(kind: str):
    from exilelens.filters import profile_report as pr
    return pr.load_builds(ROOT)[kind]


@pytest.fixture(scope="module")
def nb():
    return {lv: generate(_needs("no_build"), lv, "Void Gold", intel=True) for lv in LEVELS}


@pytest.fixture(scope="module")
def built():
    return {lv: generate(_needs("spark"), lv, "Void Gold", intel=True) for lv in LEVELS}


@pytest.fixture(scope="module")
def corpus():
    from exilelens.filters import profile_report as pr
    return pr.corpus(legal=1200, floors=40)


def _decide(result, item):
    return sc.first_match(result.rules, item)


# -- the screenshot class ---------------------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("area", [30, 82])
@pytest.mark.parametrize("level", LEVELS)
def test_screenshot_class_rare_unidentified_t2_gets_an_explicit_themed_rule(nb, built, level, area):
    """Soldier Cuirass-type item: Rare, Body Armours, Unidentified Tier 2, generic (no BUILD / CRAFT / trade reason)."""
    item = replace(make_item("Soldier Cuirass", rarity="Rare", item_level=80, unidentified_tier=2), area_level=area)
    assert item.item_class == "Body Armours" and item.unidentified_item_tier == 2
    for results in (nb, built):
        rule, action = _decide(results[level], item)
        assert rule is not None, "no rule matched: the game would show its own label"
        if action == "Hide":
            continue                                           # an explicit Hide owns the decision
        assert rule.role not in ("", "unknown") and rule.state != "SAFETY"
        assert sc.has_required_style(rule), (level, area, rule.name, sc.styled_actions(rule))
        decision = preview_decision(results[level].rules, item)
        assert decision.rule_name == rule.name and decision.style_role != "default" and "game default" not in decision.native_details


def test_generic_rare_keeps_rare_identity_and_is_quieter_than_opportunities(nb):
    item = replace(make_item("Soldier Cuirass", rarity="Rare", item_level=80), area_level=30)
    rule, _ = _decide(nb["Recommended"], item)
    assert rule.role == "generic_rare" and rule.row == "eq_rare_low" and rule.state == "SHOW"
    lines = {l.split()[0]: l for l in (x.strip() for x in rule.lines) if l.split()[0].startswith(("Set", "Minimap", "Play"))}
    assert "MinimapIcon" not in lines and "PlayEffect" not in lines and "PlayAlertSound" not in lines     # no beam, icon or sound
    assert int(lines["SetFontSize"].split()[1]) <= 30                                                       # UTILITY size, not VALUABLE+


def test_the_root_cause_is_closed_in_the_style_layer():
    """Cause B of the screenshot: a Show rule of role `generic` was emitted without any style action."""
    from exilelens.filters.style_system import native_style
    for theme in FilterThemeName:
        for state in ("SHOW+", "SHOW", "QUIET"):
            for role in ("generic", "generic_rare"):
                style = native_style(theme, role, None, state)
                assert {"font_size", "text_color", "border_color", "bg_color"} <= set(style)
                assert "play_effect" not in style and "sound" not in style
    # QUIET generic Rares were already styled grey and stay byte-identical
    assert (native_style(FilterThemeName.VOID_GOLD, "generic_rare", None, "QUIET")
            == native_style(FilterThemeName.VOID_GOLD, "generic", None, "QUIET"))


# -- contract over the generated filters ------------------------------------------------------------------------------------------------
def test_every_show_rule_carries_the_text_and_plaque_actions(nb, built):
    for results in (nb, built):
        for level, result in results.items():
            for rule in result.rules:
                if any(l.strip() == "Show" for l in rule.lines):
                    assert sc.has_required_style(rule), (level, rule.name, rule.state, rule.role)


def test_show_plus_show_and_quiet_all_have_explicit_style(nb, built):
    seen = set()
    for results in (nb, built):
        for result in results.values():
            for rule in result.rules:
                if any(l.strip() == "Show" for l in rule.lines):
                    seen.add(rule.state)
                    assert sc.has_required_style(rule)
    assert {"SHOW+", "SHOW", "QUIET", "SAFETY"} <= seen


def test_known_visible_items_never_fall_through_across_profiles_and_contexts(nb, built, corpus):
    for results in (nb, built):
        for level in LEVELS:
            for area in (30, 82):
                items = [replace(i, area_level=area) for i in corpus]
                known = [classify(i, level).rows not in ((), (UNKNOWN_ROW,)) for i in items]
                verdicts = sc.evaluate(results[level].rules, items, known)
                bad = [(i.name, v.outcome, v.rule) for i, v in zip(items, verdicts) if sc.is_failure(v.outcome)]
                assert not bad, (level, area, bad[:5])


def test_no_build_is_as_fully_themed_as_a_build(nb, built, corpus):
    for results in (nb, built):
        summary = sc.summarise(corpus, sc.evaluate(results["Recommended"].rules, corpus, [True] * len(corpus)))
        assert summary["unstyled_visible_fallthrough"] == 0


# -- rare equipment ---------------------------------------------------------------------------------------------------------------------
def test_rare_equipment_is_covered_for_every_tier_ilvl_and_profile(nb, built):
    from exilelens.filters.opportunity import ROLE_BY_CLASS
    from exilelens.filters.verified_bases import load_base_properties, native_class
    props = load_base_properties()
    bases = [b for b in sorted(props) if native_class(b) in ROLE_BY_CLASS][::7]
    for results in (nb, built):
        for level in LEVELS:
            for area in (30, 82):
                items = [PreviewItem(b, "audit", native_class(b), b, "Rare", item_level=ilvl, area_level=area, unidentified_item_tier=unid)
                         for b in bases for ilvl in (45, 70, 82) for unid in (0, 1, 2, 3, 4, 5) if ilvl >= int(props[b]["required_level"])]
                verdicts = sc.evaluate(results[level].rules, items, [True] * len(items))
                bad = [(i.name, i.item_level, i.unidentified_item_tier, v.outcome, v.rule) for i, v in zip(items, verdicts)
                       if sc.is_failure(v.outcome)]
                assert not bad, (level, area, bad[:4])


# -- known generic vs unknown ----------------------------------------------------------------------------------------------------------
def test_known_generic_is_distinct_from_unknown_safety(nb):
    trap = PreviewItem("Spike Trap", "t", "Traps", "Spike Trap", "Magic", item_level=60, area_level=82)
    unknown = PreviewItem("Imagined Trap", "t", "Traps", "Imagined Trap", "Magic", item_level=60, area_level=82)
    for level in LEVELS:
        k, _ = _decide(nb[level], trap)
        u, _ = _decide(nb[level], unknown)
        assert k.row == "known_generic_fallback" and k.role == "generic" and k.state == "SHOW" and k.name == "Known_Generic_Traps"
        assert u.row == "unknown_new_items" and u.role == "unknown" and u.state == "SAFETY"
        assert k.evidence.lane == "KNOWN_GENERIC" and u.evidence.lane == "SAFETY"
        assert sc.has_required_style(k) and sc.has_required_style(u)
        assert classify(trap, level).rows == ("known_generic_fallback",) and classify(unknown, level).rows == (UNKNOWN_ROW,)


def test_known_generic_sits_after_every_hide_and_before_the_safety_rule(nb):
    for level in LEVELS:
        rules = nb[level].rules
        index = {r.row: i for i, r in enumerate(rules) if r.row in ("known_generic_fallback", "unknown_new_items")}
        last_hide = max((i for i, r in enumerate(rules) if any(l.strip() == "Hide" for l in r.lines)), default=-1)   # Relaxed hides nothing
        assert last_hide < index["known_generic_fallback"] < index["unknown_new_items"] == len(rules) - 1


def test_unknown_safety_treatment_is_unchanged(nb):
    from exilelens.filters.style_system import native_style
    rule = nb["Recommended"].rules[-1]
    assert rule.role == "unknown" and rule.state == "SAFETY"
    expected = native_style(FilterThemeName.VOID_GOLD, "unknown", None, "SHOW+")
    assert f"SetFontSize {expected['font_size']}" in [l.strip() for l in rule.lines]


# -- themes -----------------------------------------------------------------------------------------------------------------------------
def test_all_eight_themes_style_every_visible_state_and_never_change_visibility(corpus):
    needs = _needs("no_build")
    reference = None
    sample = corpus[::4]
    for theme in FilterThemeName:
        result = generate(needs, "Recommended", theme, intel=True)
        assert result.valid
        for rule in result.rules:
            if any(l.strip() == "Show" for l in rule.lines):
                assert sc.has_required_style(rule), (theme, rule.name)
        bits = []
        for area in (30, 82):
            for item in sample:
                rule, action = _decide(result, replace(item, area_level=area))
                assert rule is not None
                bits.append(action)
        reference = reference or bits
        assert bits == reference, theme


# -- guard rails ------------------------------------------------------------------------------------------------------------------------
def test_qa_fixture_resolves_every_item_to_an_explicit_role(nb, built):
    for results in (nb, built):
        for level in ("Relaxed", "Recommended", "Very Strict"):
            fixture = sc.qa_fixture(results[level].rules)
            labels = {label for label, _ in fixture}
            assert {"generic_rare_body_armour_unid_t2", "quiet_rare_in_maps", "generic_rare_weapon", "unique", "unknown_safety"} <= labels
            for label, item in fixture:
                decision = preview_decision(results[level].rules, item)
                assert "game default" not in decision.native_details and decision.style_role != "default", (level, label)
                if label == "unknown_safety":
                    assert decision.style_role == "unknown"
                elif not decision.hidden:
                    assert decision.style_role != "unknown", (level, label)


def test_visibility_follows_the_matrix_not_the_style_layer(nb):
    """The oracle (matrix-derived, independent of rules) agrees with every generated visible / hidden bit."""
    from exilelens.filters import profile_report as pr
    items = pr.corpus(legal=600, floors=20)
    for level in LEVELS:
        for area in (30, 82):
            for item in (replace(i, area_level=area) for i in items):
                _, action = _decide(nb[level], item)
                assert (action == "Hide") == (classify(item, level).state == "HIDE"), (level, area, item.name)


def test_exact_basetype_and_registry_still_hold(nb):
    from exilelens.filters import native_bases
    for result in nb.values():
        lines = [l.strip() for l in result.text.splitlines() if l.strip().startswith("BaseType")]
        assert lines and all(l.startswith("BaseType ==") for l in lines)
        assert native_bases.base_type_violations(result.text) == []


def test_utility_belt_and_unique_policy_unchanged(nb):
    belt = replace(make_item("Utility Belt", rarity="Rare", item_level=82), area_level=82)
    assert not preview_decision(nb["Recommended"].rules, belt).hidden
    unique = replace(make_item("Utility Belt", rarity="Unique", item_level=82), area_level=82)
    assert not preview_decision(nb["Uber Strict"].rules, unique).hidden          # ordinary uniques are never hidden by strictness


def test_visual_v4_hero_audio_beam_rules_unchanged():
    from exilelens.filters.style_system import BEAM_POLICY, PERSISTENT, SOUND_POLICY, TEMP
    assert {r for r, k in BEAM_POLICY.items() if k == PERSISTENT} == {"hero", "currency_premium", "quest"}
    assert {r for r, k in BEAM_POLICY.items() if k == TEMP} == {"premium_currency", "special", "unique", "waystone_high"}
    assert SOUND_POLICY["hero"] == ("APEX", 300) and "generic" not in SOUND_POLICY and "generic_rare" not in SOUND_POLICY


def test_preview_ir_and_native_first_match_agree_on_rule_and_style(nb, corpus):
    """A preview that shows a themed label where the native filter would fall through is a defect: the matched rule, its role and its
    font must be what the native first-match reads (and the rule IR must see no defect in the same rules)."""
    from exilelens.filters import rule_ir
    for level in ("Relaxed", "Recommended", "Uber Strict"):
        rules = nb[level].rules
        for item in corpus[::6]:
            rule, action = _decide(nb[level], item)
            decision = preview_decision(rules, item)
            assert decision.rule_name == rule.name
            assert decision.hidden == (action == "Hide")
            if not decision.hidden:
                declared = next(int(l.split()[1]) for l in (x.strip() for x in rule.lines) if l.startswith("SetFontSize"))
                assert decision.font_size == declared and decision.style_role == rule.role
        assert rule_ir.analyse(rules).defects() == []
