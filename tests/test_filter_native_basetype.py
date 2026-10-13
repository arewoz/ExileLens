"""Native BaseType validity: PoB2's `itemBases` universe is not the set of names a native filter may carry.

Run with:  python -m pytest tests/test_filter_native_basetype.py -m ""
"""
from __future__ import annotations

import json
import random
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

from exilelens.filters import native_bases as nb
from exilelens.filters import native_preflight as pf
from exilelens.filters.intel_generate import generate
from exilelens.filters.rules import GeneratedRule
from exilelens.filters.serialize import FilterMetadata, FilterSerializer
from exilelens.filters.validation import validate_all, validate_base_types
from exilelens.filters.verified_bases import (SPECIAL_BASES, load_base_properties, load_pob_bases, load_verified_bases, native_class)

ROOT = Path(__file__).resolve().parents[1]
SYNTHETIC = ("Energy Blade One Handed", "Energy Blade Two Handed")
PROFILES = ("Relaxed", "Recommended", "Strict", "Very Strict", "Uber Strict")


def _no_build():
    from exilelens.filters.build_needs import BuildNeedsSnapshot
    return BuildNeedsSnapshot.unavailable("No build", "no build connected")


def _serializer() -> FilterSerializer:
    return FilterSerializer(FilterMetadata("t", "c", "a", "s", "p", datetime(2026, 1, 1, tzinfo=timezone.utc), "r"))


def _rule(lines, name="Build_Test_Rule") -> GeneratedRule:
    return GeneratedRule(category="TEST", name=name, lines=lines, priority=1)


def _base_types(text: str) -> set[str]:
    return {n for line in text.splitlines() if line.strip().startswith("BaseType") for n in re.findall(r'"([^"]+)"', line)}


# -- the two universes ---------------------------------------------------------------------------------------------------------------
def test_pob_universe_is_larger_than_the_native_ground_universe():
    pob, ground = set(load_pob_bases()), set(load_verified_bases())
    assert len(pob) == 1769 and ground < pob
    assert set(load_base_properties()) == ground
    assert ground == {b for b in pob if nb.is_ground_base(b)}


@pytest.mark.parametrize("name", SYNTHETIC)
def test_energy_blade_synthetics_are_pob_only(name):
    assert name in load_pob_bases()                       # PoB calculates with it ...
    entry = nb.entry_of(name)
    assert entry.status is nb.Status.POB_SYNTHETIC and entry.real_name == "Energy Blade"
    assert not nb.is_ground_base(name)                    # ... but it is not a native ground base
    assert name not in load_verified_bases() and name not in load_base_properties() and native_class(name) is None


def test_every_pob_name_is_classified_and_nothing_unknown_is_valid():
    registry = nb.load_registry()
    assert set(load_pob_bases()) <= set(registry)
    statuses = {registry[n].status for n in load_pob_bases()}
    assert nb.Status.AMBIGUOUS not in statuses and nb.Status.UNKNOWN not in statuses     # nothing left unsettled in the pinned catalog
    for entry in registry.values():
        assert entry.ground_valid == (entry.status is nb.Status.GROUND_FILTER_VALID)
        if entry.ground_valid:
            assert entry.native_class and entry.source != "none" and entry.confidence in ("high", "medium")
    assert nb.status_of("Definitely Not A Base") is nb.Status.UNKNOWN and not nb.is_ground_base("Definitely Not A Base")


def test_suspicious_families_are_classified_explicitly():
    for name in ("Calm Leg", "Sprinters Leg", "Caster Arm", "Fishing Rod", "Keyblade", "Ethereal Blade"):
        assert nb.status_of(name) is nb.Status.NON_GROUND_GAME_OBJECT, name
    for name in ("Shrine Sceptre (Purity of Cold)", "Shrine Sceptre (Purity of Fire)", "Shrine Sceptre (Purity of Lighting)"):
        assert nb.status_of(name) is nb.Status.POB_SYNTHETIC and nb.entry_of(name).real_name == "Shrine Sceptre"
    assert nb.is_ground_base("Shrine Sceptre")                                  # the real base is untouched
    assert nb.status_of("Alchemy Shard") is nb.Status.STALE_OBSOLETE
    # Runeforged / Runemastered variants are real game bases (PoE2DB lists them), not synthetic
    rune = [n for n in load_pob_bases() if n.startswith(("Runeforged ", "Runemastered "))]
    assert len(rune) > 700 and all(nb.is_ground_base(n) for n in rune)
    # the demigods / time-lost bases exist for uniques only: valid names, scope recorded, never silently 'any'
    assert nb.entry_of("Golden Mantle").scope == "unique_only" and nb.entry_of("Time-Lost Ruby").scope == "unique_only"
    assert nb.entry_of("Golden Blade").scope == "any"        # the same name is also an ordinary sellable base: both variants share it
    assert nb.entry_of("Utility Belt").scope == "any" and nb.entry_of("Utility Belt").native_class == "Belts"


def test_pob_alone_never_establishes_validity():
    # a base PoB knows (class + tags) but with no game evidence is UNKNOWN, never valid
    entry = nb.classify_pob_base("Imaginary Blade", "One Hand Sword", ["default", "sword"], None)
    assert entry["status"] == "UNKNOWN"
    # an Energy-Blade-like name stays synthetic even if a (wrong) game record were attached
    assert nb.classify_pob_base("Energy Blade One Handed", "One Hand Sword", [], None)["status"] == "POB_SYNTHETIC"
    # not_for_sale without an explanation is AMBIGUOUS, not valid
    ev = {"page": "present", "class": "Daggers", "listed": True, "tags": ["not_for_sale", "dagger"], "drop_level": 1}
    assert nb.classify_pob_base("Mystery Dagger", "Dagger", ["not_for_sale"], ev)["status"] == "AMBIGUOUS"
    # a real, sellable, listed base is valid
    ev = {"class": "Daggers", "listed": True, "tags": ["dagger"], "drop_level": 1}
    assert nb.classify_pob_base("Glass Shank", "Dagger", [], ev)["status"] == "GROUND_FILTER_VALID"
    # listed under another class than PoB says -> ambiguous
    ev = {"class": "Wands", "listed": True, "tags": [], "drop_level": 1}
    assert nb.classify_pob_base("Glass Shank", "Dagger", [], ev)["status"] == "AMBIGUOUS"


def test_committed_registry_equals_a_rebuild_of_the_committed_evidence():
    result = subprocess.run([sys.executable, str(ROOT / "scripts" / "filter_native_registry.py"), "check"], capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr


# -- fail-closed serialization ---------------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("name", [*SYNTHETIC, "Totally Made Up Base"])
def test_serializer_blocks_a_base_that_is_not_a_native_ground_base(name):
    rule = _rule(["Show", '\tClass "One Hand Swords"', f'\tBaseType == "{name}"', "\tSetFontSize 30"])
    with pytest.raises(nb.NativeBaseTypeBlocked) as caught:
        _serializer().serialize([rule])
    message = str(caught.value)
    assert "FILTER GENERATION BLOCKED" in message and name in message and "Build_Test_Rule" in message
    assert caught.value.violations[0]["name"] == name


def test_unknown_base_cannot_serialize_even_inside_a_valid_group():
    rule = _rule(["Show", '\tBaseType == "Vile Robe" "Utility Belt" "Not A Real Base"'])
    with pytest.raises(nb.NativeBaseTypeBlocked) as caught:
        _serializer().serialize([rule])
    assert [v["name"] for v in caught.value.violations] == ["Not A Real Base"]


def test_valid_real_bases_still_serialize_exactly():
    rule = _rule(["Show", '\tClass "Belts"', '\tBaseType == "Utility Belt"', "\tSetFontSize 30"])
    text = _serializer().serialize([rule])
    assert '\tBaseType == "Utility Belt"' in text
    assert validate_all(text).passed


def test_validator_rejects_and_explains_the_synthetic_base():
    text = 'Show\n\tClass "One Hand Swords"\n\tBaseType == "Energy Blade One Handed"\n\tSetFontSize 30\n'
    result = validate_base_types(text)
    assert not result.passed and "POB_SYNTHETIC" in " ".join(result.errors)


# -- grouped rules ---------------------------------------------------------------------------------------------------------------------
def test_grouped_list_partitions_valid_from_provably_absent():
    valid, excluded = nb.partition_for_emission(["Vile Robe", "Energy Blade One Handed", "Utility Belt", "Keyblade"])
    assert valid == ["Vile Robe", "Utility Belt"]
    assert [n for n, _ in excluded] == ["Energy Blade One Handed", "Keyblade"]
    assert all("POB_SYNTHETIC" in r or "NON_GROUND" in r for _, r in excluded)


def test_grouped_list_with_an_unestablished_name_blocks_instead_of_dropping():
    with pytest.raises(nb.NativeBaseTypeBlocked):
        nb.partition_for_emission(["Vile Robe", "Not A Real Base"])
    with pytest.raises(nb.NativeBaseTypeBlocked):            # nothing valid left: the rule would change meaning entirely
        nb.partition_for_emission(["Energy Blade One Handed"])


def test_class_binding_of_a_partition():
    valid, rejected = nb.partition_base_types(["Utility Belt", "Vile Robe"], native_class="Belts")
    assert valid == ["Utility Belt"] and rejected[0][0] == "Vile Robe"


# -- generation ------------------------------------------------------------------------------------------------------------------------
@pytest.fixture(scope="module")
def generated():
    needs = _no_build()
    return {level: generate(needs, level, "Void Gold", intel=True) for level in PROFILES}


def test_generated_filters_never_emit_a_synthetic_or_non_ground_base(generated):
    for level, result in generated.items():
        assert result.valid, result.errors
        emitted = _base_types(result.text)
        for name in (*SYNTHETIC, "Keyblade", "Ethereal Blade", "Fishing Rod", "Alchemy Shard",
                     "Shrine Sceptre (Purity of Fire)", "Calm Leg"):
            assert name not in emitted, (level, name)
        assert emitted <= nb.ground_bases(), (level, sorted(emitted - nb.ground_bases())[:5])
        assert nb.base_type_violations(result.text) == []
        assert result.excluded_bases == ()


def test_exact_basetype_semantics_remain(generated):
    for result in generated.values():
        lines = [l.strip() for l in result.text.splitlines() if l.strip().startswith("BaseType")]
        assert lines and all(l.startswith("BaseType ==") for l in lines)
        assert "PARTIAL_BASE_PATTERN" not in result.text


def test_uniques_rule_lists_real_bases_only(generated):
    text = generated["Recommended"].text
    uniques = next(l for l in text.split("# Uniques [campaign]")[1].splitlines() if l.strip().startswith("BaseType"))
    names = set(re.findall(r'"([^"]+)"', uniques))
    assert "Utility Belt" in names and "Shrine Sceptre" in names and not names & set(SYNTHETIC)
    assert names == {b for b in load_base_properties() if native_class(b)}


def test_utility_belt_and_real_bases_keep_their_visibility(generated):
    from exilelens.filters.inspector import make_item
    from exilelens.filters.preview import preview_decision
    rules = generated["Recommended"].rules
    belt = preview_decision(rules, make_item("Utility Belt", rarity="Rare", item_level=82))
    assert not belt.hidden
    assert preview_decision(rules, make_item("Utility Belt", rarity="Normal", item_level=10)) is not None


def test_currency_class_comes_from_the_registry_not_an_assumption(generated):
    text = generated["Recommended"].text
    assert "Alchemy Shard" not in text
    # a name whose real class is not Stackable Currency has its own rule, so its Class condition can actually match it
    assert nb.entry_of("Vaal Siphoner").native_class == "Incubators" and SPECIAL_BASES["Vaal Siphoner"] == "Incubators"
    block = text.split('Class "Incubators"')[1].split("Show")[0]
    assert 'BaseType == "Vaal Siphoner"' in block
    stackable = [l for l in text.splitlines() if l.strip().startswith("BaseType") and "Vaal Siphoner" in l]
    assert len(stackable) == 1
    assert SPECIAL_BASES["Chaos Orb"] == "Stackable Currency" and "Alchemy Shard" not in SPECIAL_BASES


def test_craft_lane_uses_only_ground_bases(generated):
    rows = [r for r in generated["Recommended"].rules if r.row.startswith("craft")]
    assert rows
    for rule in rows:
        assert set(rule.base_types) <= nb.ground_bases()
        for line in rule.lines:
            if line.strip().startswith("BaseType"):
                assert set(re.findall(r'"([^"]+)"', line)) <= nb.ground_bases()
    from exilelens.filters import crafting_intel as ci
    assert ci.assess("Utility Belt") is not None


def test_profile_visibility_is_unchanged_for_real_bases():
    """The ground boundary removes only names no item can carry: for every real base the generated decision is what the profile matrix says."""
    from exilelens.filters.inspector import make_item
    from exilelens.filters.preview import preview_decision
    needs = _no_build()
    sample = [b for b in sorted(load_base_properties()) if native_class(b)][::97]
    for level in ("Relaxed", "Very Strict"):
        rules = generate(needs, level, "Void Gold", intel=True).rules
        for base in sample:
            item = make_item(base, rarity="Rare", item_level=70)
            decision = preview_decision(rules, item)
            assert decision is not None and decision.state in ("SHOW+", "SHOW", "QUIET", "HIDE", "SAFETY"), (level, base)


# -- Random Drops ----------------------------------------------------------------------------------------------------------------------
def test_random_drops_never_draw_synthetic_or_non_ground_objects():
    from exilelens.filters import scene_pool
    pool_bases = {b for bases in scene_pool.equipment_pool().values() for b in bases}
    assert pool_bases <= nb.ground_bases() and not pool_bases & set(SYNTHETIC)
    assert {n for names in scene_pool.currency_pool().values() for n in names} <= nb.ground_bases()
    drawn = set()
    for seed in range(250):
        for item in scene_pool.random_scene_items(seed):
            drawn.add(item.base_type or item.name)
    assert not drawn & {*SYNTHETIC, "Keyblade", "Ethereal Blade", "Fishing Rod", "Alchemy Shard", "Calm Leg"}
    stack = {i.base_type: i.item_class for seed in range(60) for i in scene_pool.random_scene_items(seed) if i.base_type == "Vaal Siphoner"}
    assert set(stack.values()) <= {"Incubators"}


# -- preflight -------------------------------------------------------------------------------------------------------------------------
def test_preflight_union_is_fully_established():
    needs = _no_build()
    jobs = [pf.collect_job(("no_build", needs, level, theme)) for level in ("Relaxed", "Uber Strict") for theme in ("Void Gold", "Blood Sigil")]
    report = pf.evaluate(jobs)
    assert report["combinations"] == 4 and report["ambiguous"] == 0 and report["unknown"] == 0 and report["rejected_synthetic"] == 0
    assert report["all_emitted_ground_valid"] and report["unique_emitted_base_types"] == report["verified_valid"] > 1700


def test_preflight_detects_a_contaminated_rule(monkeypatch):
    """The preflight itself must not be vacuous: feed it a result containing the original failure."""
    bad = {"build": "x", "level": "Recommended", "theme": "Void Gold", "valid": True, "errors": [], "excluded": [],
           "names": {"Energy Blade One Handed": [["row", "Uniques"]]}, "violations": []}
    report = pf.evaluate([bad])
    assert not report["all_emitted_ground_valid"] and report["rejected_synthetic"] == 1
    assert report["rejected"]["Energy Blade One Handed"]["status"] == "POB_SYNTHETIC"
