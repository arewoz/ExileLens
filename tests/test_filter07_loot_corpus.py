"""Source and expensive-miss checks for independent FILTER-07 cases."""
from __future__ import annotations

from exilelens.filters.benchmark_corpus import LOOT_CASES
from exilelens.filters.preview import preview_decision
from exilelens.filters.profiles import DefenseLayer, FilterProfileName, FilterThemeName, get_profile_with_theme
from exilelens.filters.profile_oracle import matrix_hides
from exilelens.filters.rules import RuleGenerator
from exilelens.filters.verified_bases import FILTER_TO_POB_CLASS, PINNED_SPECIAL_BASES, load_verified_bases


def test_corpus_sources_are_versioned_and_expectations_are_explicit():
    assert len(LOOT_CASES) >= 70
    assert len({case.id for case in LOOT_CASES}) == len(LOOT_CASES)
    assert {case.expectation for case in LOOT_CASES} == {
        "protect", "opportunity", "trade", "clutter", "uncertain"}
    bases = load_verified_bases()
    for case in LOOT_CASES:
        assert case.rationale and case.source
        item = case.item
        if item.item_class in FILTER_TO_POB_CLASS:
            assert bases.get(item.base_type) == FILTER_TO_POB_CLASS[item.item_class]
        if item.item_class == "Stackable Currency" and item.base_type:
            assert item.base_type in PINNED_SPECIAL_BASES


def test_protected_cases_remain_visible_in_every_profile():
    protected = [case for case in LOOT_CASES if case.expectation == "protect"]
    assert len(protected) >= 15
    for profile_name in FilterProfileName:
        profile = get_profile_with_theme(profile_name, FilterThemeName.VOID_GOLD)
        rules = RuleGenerator({}, profile, "Unknown", DefenseLayer.UNKNOWN).generate_all()
        # profile system V2: a "protected" KIND may be hidden only where the approved matrix says HIDE for its row (utility currency and
        # generic uniques at Uber Strict); everything else stays visible at every level
        assert not [case.id for case in protected
                    if preview_decision(rules, case.item).hidden and not matrix_hides(case.item, profile_name.value)]
