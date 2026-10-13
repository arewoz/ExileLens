"""FILTER-08D: rule IR, static analysis, exact equivalence, verified optimisation and the profile contract.

Run with:  python -m pytest tests/test_filter08d_rules.py -m ""
"""
from __future__ import annotations

from pathlib import Path

import pytest

from exilelens.filters import benchmark08b as bm, legal_corpus as lc, profile_contract as pc, rule_ir as ri
from exilelens.filters.intel_generate import generate
from exilelens.filters.preview import PreviewItem, preview_decision
from exilelens.filters.rules import GeneratedRule

ROOT = Path(__file__).resolve().parents[1]
NEEDS = ROOT / "tests" / "fixtures" / "filter_needs" / "filter08e"


def rule(name, category, action, *conditions, style=("SetFontSize 30",), base_types=()):
    lines = [action, *conditions, *style]
    return GeneratedRule(category=category, name=name, lines=lines, priority=1, base_types=list(base_types))


@pytest.fixture(scope="module")
def snapshots():
    if not NEEDS.exists():
        pytest.skip("08C needs snapshots not present")
    return bm.load_snapshots(NEEDS)


# -- analysis on synthetic rules -------------------------------------------------------------------------------------------------------
def kinds(rules):
    return {(f.kind, f.rule) for f in ri.analyse(rules).findings}


def test_detects_shadowed_duplicate_and_partial():
    rules = [rule("wide", "BUILD_DEFENSE", "Show", 'Class "Boots"', "Rarity Rare"),
             rule("dup", "BUILD_DEFENSE", "Show", 'Class "Boots"', "Rarity Rare"),
             rule("inside", "BUILD_DEFENSE", "Show", 'Class "Boots"', "Rarity Rare", "ItemLevel >= 80", style=("SetFontSize 40",)),
             rule("partial", "BUILD_DEFENSE", "Show", 'Class "Boots"', style=("SetFontSize 50",))]
    found = kinds(rules)
    assert ("DUPLICATE", "dup") in found
    assert ("SHADOWED", "inside") in found
    assert ("PARTIALLY_SHADOWED", "partial") in found
    assert not any(kind == "SHADOWED" and name == "wide" for kind, name in found)


def test_detects_dead_and_contradictory():
    rules = [rule("unknown key", "BUILD_WEAPON", "Show", "Nonsense 3"),
             rule("contradiction", "BUILD_WEAPON", "Show", 'Class "Wands"', "ItemLevel >= 90", "ItemLevel <= 10")]
    found = kinds(rules)
    assert ("DEAD", "unknown key") in found
    assert ("CONTRADICTORY", "contradiction") in found


def test_protective_rule_hidden_by_earlier_hide_is_a_defect():
    rules = [rule("hide wands", "HIDE", "Hide", 'Class "Stackable Currency"'),
             rule("Currency", "PROTECTIVE", "Show", 'Class "Stackable Currency"')]
    report = ri.analyse(rules)
    assert {f.kind for f in report.defects()} >= {"PROTECTIVE_SHADOWED_BY_HIDE", "PROTECTIVE_NEVER_MATCHES"}


def test_hide_rule_pre_empting_a_show_rule_is_reported():
    rules = [rule("hide magic", "HIDE", "Hide", 'Class "Boots"', "Rarity Magic"), rule("show boots", "BUILD_DEFENSE", "Show", 'Class "Boots"')]
    report = ri.analyse(rules)
    assert ("SHOW_PREEMPTED_BY_HIDE", "show boots") in {(f.kind, f.rule) for f in report.findings}
    assert report.hide_rules and report.hide_rules[0]["bases_hidden"] > 10


def test_hide_of_all_rarities_is_too_broad():
    report = ri.analyse([rule("hide boots", "HIDE", "Hide", 'Class "Boots"')])
    assert "HIDE_TOO_BROAD" in {f.kind for f in report.findings}


def test_redundant_rule_is_found():
    rules = [rule("specific", "BUILD_DEFENSE", "Show", 'Class "Boots"', "Rarity Rare"), rule("general", "BUILD_DEFENSE", "Show", 'Class "Boots"')]
    assert ("REDUNDANT", "specific") in kinds(rules)


def test_ir_matches_the_simulator_on_first_match():
    rules = [rule("a", "BUILD_DEFENSE", "Show", 'Class "Boots"', "ItemLevel >= 80"), rule("b", "HIDE", "Hide", 'Class "Boots"')]
    items = [PreviewItem("Plated Greaves", "", "Boots", "Plated Greaves", "Magic", item_level=lv) for lv in (60, 79, 80, 81, 100)]
    decisions = [preview_decision(rules, item).hidden for item in items]
    assert decisions == [True, True, False, False, False]
    optimised, report = ri.optimise(rules)
    assert report.verified and [preview_decision(optimised, item).hidden for item in items] == decisions


# -- comparison ------------------------------------------------------------------------------------------------------------------------
def test_compare_categories():
    base = [rule("r", "BUILD_DEFENSE", "Show", 'Class "Boots"')]
    assert ri.compare(base, [rule("r", "BUILD_DEFENSE", "Show", 'Class "Boots"')]).summary()["strictly_identical"]
    visibility = ri.compare(base, [rule("r", "BUILD_DEFENSE", "Hide", 'Class "Boots"')])
    assert visibility.by_category()["VISIBILITY"] > 0 and not visibility.equivalent()
    styling = ri.compare(base, [rule("r", "BUILD_DEFENSE", "Show", 'Class "Boots"', style=("SetFontSize 44",))])
    assert styling.by_category()["STYLING"] > 0 and styling.by_category()["VISIBILITY"] == 0
    renamed = ri.compare(base, [rule("other", "BUILD_DEFENSE", "Show", 'Class "Boots"')])
    assert renamed.equivalent() and not renamed.equivalent(strict=True) and renamed.by_category()["MATCHED_RULE"] > 0


def test_compare_reports_a_concrete_example():
    diff = ri.compare([rule("r", "BUILD_DEFENSE", "Show", 'Class "Boots"')],
                      [rule("r", "BUILD_DEFENSE", "Hide", 'Class "Boots"', "ItemLevel >= 84")]).diffs[0]
    assert diff.category == "VISIBILITY" and diff.b_hidden and not diff.a_hidden
    assert diff.example.item_class == "Boots" and diff.example.item_level >= 84


# -- optimiser -------------------------------------------------------------------------------------------------------------------------
def test_optimiser_removes_only_unreachable_rules():
    rules = [rule("a", "BUILD_DEFENSE", "Show", 'Class "Boots"'), rule("a2", "BUILD_DEFENSE", "Show", 'Class "Boots"'),
             rule("never", "BUILD_DEFENSE", "Show", 'Class "Boots"', "Rarity Rare", style=("SetFontSize 50",)),
             rule("other", "BUILD_WEAPON", "Show", 'Class "Wands"')]
    optimised, report = ri.optimise(rules)
    assert [r.name for r in optimised] == ["a", "other"]
    assert report.verified and (report.removed_duplicate, report.removed_shadowed) == (1, 1)
    assert ri.compare(rules, optimised).equivalent(strict=True)


def test_optimiser_merges_base_type_lists_only_when_order_cannot_matter():
    from exilelens.filters.verified_bases import load_base_properties, native_class
    a, b, c = [x for x in sorted(load_base_properties()) if native_class(x) == "Boots"][:3]
    one = rule("Trade", "TRADE_BASES", "Show", 'Class "Boots"', f'BaseType "{a}" "{b}"', base_types=[a, b])
    two = rule("Trade", "TRADE_BASES", "Show", 'Class "Boots"', f'BaseType "{c}"', base_types=[c])
    merged, report = ri.optimise([one, two])
    assert report.merged == 1 and len(merged) == 1 and set(merged[0].base_types) == {a, b, c}
    assert 'BaseType "{}" "{}" "{}"'.format(a, b, c) in " ".join(merged[0].lines)
    blocker = rule("Block", "HIDE", "Hide", f'BaseType "{c}"', base_types=[c])
    kept, report2 = ri.optimise([one, blocker, two])
    assert report2.merged == 0 and report2.removed_shadowed == 1       # `two` is fully pre-empted by the blocker instead
    assert [r.name for r in kept] == ["Trade", "Block"]


def test_optimiser_returns_the_original_if_it_cannot_prove_equivalence(monkeypatch):
    rules = [rule("a", "BUILD_DEFENSE", "Show", 'Class "Boots"'), rule("a2", "BUILD_DEFENSE", "Show", 'Class "Boots"')]

    def failing(*args, **kwargs):
        report = ri.EquivalenceReport([], 0, 0.0)
        report.diffs.append(ri.Diff("VISIBILITY", "a", "b", False, True, 1, 1, PreviewItem("x", "", "Boots")))
        return report

    monkeypatch.setattr(ri, "compare", failing)
    result, report = ri.optimise(rules)
    assert result == rules and not report.verified


# -- real filters ----------------------------------------------------------------------------------------------------------------------
def test_real_filters_have_no_rule_defects(snapshots):
    for name in list(snapshots)[:4]:
        for profile in bm.PROFILES:
            report = ri.analyse(generate(snapshots[name], profile).rules)
            assert report.defects() == [], (name, profile, report.defects()[:2])


def test_optimised_real_filter_is_exactly_equivalent_and_smaller(snapshots):
    needs = snapshots[next(iter(snapshots))]
    plain = generate(needs, "Recommended")
    optimised = generate(needs, "Recommended", optimize=True)
    assert optimised.valid and len(optimised.rules) < len(plain.rules) and len(optimised.text) < len(plain.text)
    assert ri.compare(plain.rules, optimised.rules).equivalent(strict=True)
    items = [c.item for c in lc.sample(800, 5)]
    assert ri.compare_on_items(plain.rules, optimised.rules, items)["diffs"] == {}


def test_profile_chain_is_monotonic_on_real_builds(snapshots):
    for name in list(snapshots)[:3]:
        found, narrowed = pc.inversions(name, snapshots[name])
        assert [i for i in found if not i.documented] == [], found[:2]
        assert narrowed                                    # the stricter profiles really do narrow something


def test_profile_inversion_is_detected():
    rules = {"Relaxed": [rule("r", "BUILD_DEFENSE", "Hide", 'Class "Boots"')], "Recommended": [rule("r", "BUILD_DEFENSE", "Show", 'Class "Boots"')],
             "Strict": [rule("r", "BUILD_DEFENSE", "Show", 'Class "Boots"')], "Very Strict": [rule("r", "BUILD_DEFENSE", "Show", 'Class "Boots"')],
             "Uber Strict": [rule("r", "BUILD_DEFENSE", "Show", 'Class "Boots"')]}
    found, _ = pc.inversions("synthetic", None, rules=rules)               # type: ignore[arg-type]
    assert found and found[0].looser == "Relaxed"
