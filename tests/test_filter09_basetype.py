"""FILTER-09: exact BaseType semantics (base_match contract), the collision corpus and the migration guarantees.

Run with:  python -m pytest tests/test_filter09_basetype.py -m ""
"""
from __future__ import annotations

import shlex
from pathlib import Path

import pytest

from exilelens.filters import base_collisions as col
from exilelens.filters import benchmark08b as bm
from exilelens.filters import rule_ir
from exilelens.filters.base_match import PARTIAL_MARKER, BaseCondition, BaseMatch, base_line, exact, legacy_partial_emission, partial
from exilelens.filters.inspector import make_item
from exilelens.filters.intel_generate import generate
from exilelens.filters.preview import PreviewItem, _matches_condition, preview_decision
from exilelens.filters.rules import GeneratedRule
from exilelens.filters.validation import validate_base_types
from exilelens.filters.verified_bases import load_base_properties, native_class

ROOT = Path(__file__).resolve().parents[1]
NEEDS = ROOT / "tests" / "fixtures" / "filter_needs" / "filter08e"
PROFILES = ("Relaxed", "Recommended", "Strict", "Very Strict", "Uber Strict")


@pytest.fixture(scope="module")
def blood():
    if not NEEDS.exists():
        pytest.skip("canonical needs snapshots not present")
    return bm.load_snapshots(NEEDS)["spark_fixture"]


def native_expectation(operator_exact: bool, names, base: str) -> bool:
    """Written independently of base_match: the filter language's rule, stated again."""
    base, names = base.lower(), [n.lower() for n in names]
    return base in names if operator_exact else any(n in base for n in names)


# -- contract -----------------------------------------------------------------------------------------------------------------------
def test_serialization_round_trips_and_distinguishes_the_two_meanings():
    e, p = exact(["A", "B C"]), partial(["A", "B C"])
    assert e.serialize() == '\tBaseType == "A" "B C"' and p.serialize() == '\tBaseType "A" "B C"'
    assert BaseCondition.parse(e.serialize().strip()) == e and BaseCondition.parse(p.serialize().strip()) == p
    assert p.lines()[0].strip() == PARTIAL_MARKER and len(e.lines()) == 1
    assert BaseCondition.parse("Class \"Rings\"") is None
    with pytest.raises(ValueError):
        BaseCondition.parse('BaseType != "A"')


def test_the_planner_only_emits_exact_identities():
    assert base_line(["Utility Belt"]) == '\tBaseType == "Utility Belt"'
    with legacy_partial_emission():
        assert base_line(["Utility Belt"]) == '\tBaseType "Utility Belt"'      # the reproduction used by the diff report only


# -- collision corpus -----------------------------------------------------------------------------------------------------------------
def test_collision_corpus_is_deterministic_and_real():
    pairs = col.collisions()
    assert len(pairs) >= 783 and pairs == col.collisions()
    kinds = {c.kind for c in pairs}
    assert {"prefix", "suffix"} <= kinds
    prefixes = {c.family for c in pairs if c.kind == "suffix"}
    assert {"Runeforged", "Runemastered"} <= prefixes
    # not only the two special prefixes: `Ring` is inside many other names
    assert any(c.inner == "Ring" and c.outer == "Amethyst Ring" for c in pairs)
    assert len({c.inner for c in pairs if not c.outer.startswith(("Runeforged ", "Runemastered "))}) > 5
    for c in pairs:
        assert c.inner != c.outer and c.inner.casefold() in c.outer.casefold()


def test_every_collision_pair_exact_matches_only_the_intended_base():
    for c in col.collisions():
        e, p = exact([c.inner]), partial([c.inner])
        inner_item, outer_item = PreviewItem(c.inner, "", "", c.inner), PreviewItem(c.outer, "", "", c.outer)
        # the contract agrees with the native language, stated independently
        assert e.matches(c.inner) and not e.matches(c.outer), c
        assert p.matches(c.inner) and p.matches(c.outer), c
        assert native_expectation(True, [c.inner], c.outer) is False
        assert native_expectation(False, [c.inner], c.outer) is True
        # preview consumes the same parsed condition
        assert _matches_condition(e.serialize().strip(), inner_item) and not _matches_condition(e.serialize().strip(), outer_item)
        assert _matches_condition(p.serialize().strip(), inner_item) and _matches_condition(p.serialize().strip(), outer_item)


def test_ir_models_exact_and_partial_differently_and_the_optimiser_never_folds_them_together():
    shows = lambda lines: GeneratedRule("T", "R" + str(len(lines)), ["Show", *lines, "\tSetFontSize 30"], 10, base_types=["Altar Robe"])  # noqa: E731
    exact_rule = shows(['\tBaseType == "Altar Robe"'])
    partial_rule = GeneratedRule("T", "R", ["Show", PARTIAL_MARKER, '\tBaseType "Altar Robe"', "\tSetFontSize 30"], 20,
                                 base_types=["Altar Robe"])
    report = rule_ir.compare([exact_rule], [partial_rule])
    # `Runeforged Altar Robe` is styled by one and left to the game default by the other: the IR sees the difference
    assert report.diffs and report.by_category()["STYLING"] > 0
    rules = [exact_rule, GeneratedRule("T", "R2", ["Show", '\tBaseType == "Aged Cuffs"', "\tSetFontSize 30"], 11, base_types=["Aged Cuffs"])]
    optimised, _ = rule_ir.optimise(rules)
    assert all(any(line.strip().startswith("BaseType ==") for line in r.lines) for r in optimised)


def test_validator_rejects_an_unmarked_partial_list_and_accepts_the_marked_one():
    body = "Show\n\tClass \"Belts\"\n\t{}\n\tSetFontSize 30\n"
    assert validate_base_types(body.format('BaseType == "Utility Belt"')).passed
    bad = validate_base_types(body.format('BaseType "Utility Belt"'))
    assert not bad.passed and any("PARTIAL_BASE_PATTERN" in e for e in bad.errors)
    marked = "Show\n\tClass \"Belts\"\n\t" + PARTIAL_MARKER + "\n\tBaseType \"Utility Belt\"\n\tSetFontSize 30\n"
    assert validate_base_types(marked).passed


# -- generated rules -----------------------------------------------------------------------------------------------------------------
def test_every_generated_base_list_is_exact_and_valid(blood):
    for profile in PROFILES:
        result = generate(blood, profile, intel=True)
        assert result.valid, (profile, result.errors[:2])
        lines = [line.strip() for line in result.text.splitlines() if line.strip().startswith("BaseType")]
        assert lines and all(line.startswith("BaseType ==") for line in lines), profile
        assert PARTIAL_MARKER not in result.text            # nothing in the product is an intentional partial pattern (yet)


def test_exact_rules_never_match_a_longer_catalog_name(blood):
    outers: dict[str, list[str]] = {}
    for c in col.collisions():
        outers.setdefault(c.inner.casefold(), []).append(c.outer)
    checked = 0
    for profile in ("Relaxed", "Recommended", "Endgame"):
        for rule in generate(blood, profile, intel=True).rules:
            for line in rule.lines:
                condition = BaseCondition.parse(line.strip())
                if condition is None:
                    continue
                listed = {n.casefold() for n in condition.names}
                for name in listed:
                    for outer in outers.get(name, ()):
                        if outer.casefold() not in listed:
                            checked += 1
                            assert not _matches_condition(line.strip(), PreviewItem(outer, "", "", outer)), (profile, rule.name, name, outer)
    assert checked > 200


def test_optimised_rules_stay_exact_and_decide_collision_items_identically(blood):
    items = []
    for c in list(col.collisions())[::7]:
        for name in (c.inner, c.outer):
            if native_class(name):
                items += [make_item(name, rarity=r, item_level=82) for r in ("Normal", "Rare")]
    for profile in ("Recommended", "Endgame"):
        rules = generate(blood, profile, intel=True).rules
        optimised, _ = rule_ir.optimise(rules)
        for rule in optimised:
            for line in rule.lines:
                condition = BaseCondition.parse(line.strip())
                assert condition is None or condition.match == BaseMatch.EXACT_BASE, (profile, rule.name)
        for item in items:
            a, b = preview_decision(rules, item), preview_decision(optimised, item)
            assert (a.hidden, a.rule_name) == (b.hidden, b.rule_name) or a.hidden == b.hidden, (profile, item.base_type)


def test_legacy_partial_reproduction_really_inherits_and_the_correction_removes_it(blood):
    """The defect the correction fixes, shown on real data: a variant matched an ordinary base's rule only by substring (its state changed:
    a QUIET generic top base inherited the plain base's SHOW craft row). The exact emission gives every variant its own row."""
    plain = next(c for c in col.collisions() if c.outer.startswith("Runeforged ") and native_class(c.inner) == "Body Armours"
                 and c.outer == f"Runeforged {c.inner}")
    found = 0
    with legacy_partial_emission():
        before = generate(blood, "Recommended", intel=True).rules
    after = generate(blood, "Recommended", intel=True).rules
    by_name = {r.name: r for r in before}
    assert len(by_name) == len(before)                     # rule names are unique
    for c in col.collisions():
        if not c.outer.startswith(("Runeforged ", "Runemastered ")) or not native_class(c.inner):
            continue
        for rarity in ("Normal", "Rare"):
            item = make_item(c.outer, rarity=rarity, item_level=82)
            b, a = preview_decision(before, item), preview_decision(after, item)
            if (b.hidden, b.state) != (a.hidden, a.state):
                # every difference is explained by a listed ordinary name being a substring of the variant
                rule = by_name[b.rule_name]
                names = [n for line in rule.lines for cond in [BaseCondition.parse(line.strip())] if cond for n in cond.names]
                assert c.outer not in names
                assert any(n.casefold() in c.outer.casefold() for n in names), (c.outer, rarity, b.rule_name)
                found += 1
    assert found > 20 and plain


def test_unknown_special_bases_get_no_ordinary_base_craft_rule(blood):
    from exilelens.filters import crafting_intel as ci
    for profile in PROFILES:
        rules = generate(blood, profile, intel=True).rules
        listed = {b for r in rules if r.category == "CRAFT_OPPORTUNITY" and r.name.startswith(("Craft_PREMIUM", "Craft_RELEVANT"))
                  for b in r.base_types}
        assert not [b for b in listed if b.startswith(ci.SPECIAL_PREFIXES)]
        for base in list(load_base_properties())[::9]:
            if base.startswith(ci.SPECIAL_PREFIXES):
                decision = preview_decision(rules, make_item(base, rarity="Normal", item_level=82))
                assert not decision.rule_name.startswith(("Craft_PREMIUM", "Craft_RELEVANT")), (profile, base)


def test_utility_belt_is_still_shown_by_craft_reasoning_not_by_accident(blood):
    """The approved ladder (Normal / Magic at item level 82): visible through Strict, QUIET at Very Strict (Normal only), HIDE at Uber Strict."""
    expected = {"Relaxed": ("SHOW", "SHOW"), "Recommended": ("SHOW", "SHOW"), "Strict": ("SHOW", "QUIET"),
                "Very Strict": ("QUIET", "HIDE"), "Uber Strict": ("HIDE", "HIDE")}
    for profile, (normal, magic) in expected.items():
        rules = generate(blood, profile, intel=True).rules
        by_name = {r.name: r for r in rules}
        for rarity, want in (("Normal", normal), ("Magic", magic)):
            d = preview_decision(rules, make_item("Utility Belt", rarity=rarity, item_level=82))
            assert ("HIDE" if d.hidden else d.state) == want, (profile, rarity, d.rule_name, d.state)
            if want != "HIDE":
                rule = by_name[d.rule_name]
                assert rule.category == "CRAFT_OPPORTUNITY" and rule.name.startswith("Craft_RELEVANT_")
                assert shlex.split(next(l for l in rule.lines if "BaseType" in l))[:2] == ["BaseType", "=="]
                if want == "QUIET":
                    assert d.effect == "" and d.minimap_icon == "" and "sound" not in d.native_details     # QUIET: no attention effects