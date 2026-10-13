"""Test script for FILTER-01 experimental filter generation."""

import sys
from datetime import datetime
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from exilelens.filters.profiles import (
    FilterProfileName,
    BaseTier,
    DefenseLayer,
    ProductSlot,
    get_profile,
)
from exilelens.filters.priorities import (
    BASE_TIERS,
    SLOT_EQUIPMENT_CLASSES,
    get_weapon_classes_for_skill,
    DEFENSIVE_FLOORS,
)
from exilelens.filters.rules import RuleGenerator
from exilelens.filters.serialize import FilterSerializer, FilterMetadata
from exilelens.filters.validation import validate_all


def test_base_tiers():
    """Test base tier database."""
    print("Testing base tier database...")

    # Check Body Armours
    body_tiers = BASE_TIERS.get("Body Armours", {})
    # FILTER-07 C corrected a PoE1-derived inversion with pinned PoB2 data (FILTER-08C disposition: the old "Silk Robe is
    # T1" expectation is proven obsolete): Silk Robe is a level-22 / 64 ES base, Vile Robe a level-65 / 171 ES base.
    from exilelens.filters.verified_bases import load_base_properties
    props = load_base_properties()
    assert props["Silk Robe"]["required_level"] == 22 and props["Vile Robe"]["required_level"] == 65
    assert body_tiers["Vile Robe"] == BaseTier.T1
    assert body_tiers["Silk Robe"] != BaseTier.T1
    print(f"  Body Armours: {len(body_tiers)} bases")

    # The pinned verified snapshot only retains audited native names.
    assert "Corsair Coat" not in body_tiers

    # Check Rings
    ring_tiers = BASE_TIERS.get("Rings", {})
    assert "Prismatic Ring" in ring_tiers
    assert ring_tiers["Prismatic Ring"] == BaseTier.T1
    print(f"  Rings: {len(ring_tiers)} bases")

    print("  [OK] Base tier database OK")


def test_skill_weapon_mapping():
    """Test skill to weapon class mapping."""
    print("Testing skill weapon mapping...")

    # Spark -> Wands/Sceptres
    spark_weapons = get_weapon_classes_for_skill("Spark")
    assert "Wands" in spark_weapons
    assert "Sceptres" in spark_weapons
    print(f"  Spark: {spark_weapons}")

    # Lightning Arrow -> Bows
    la_weapons = get_weapon_classes_for_skill("Lightning Arrow")
    assert "Bows" in la_weapons
    assert "Quivers" in la_weapons
    print(f"  Lightning Arrow: {la_weapons}")

    # Unknown skill -> defaults
    unknown_weapons = get_weapon_classes_for_skill("UnknownSkill123")
    assert "Wands" in unknown_weapons
    assert "Bows" in unknown_weapons
    print(f"  Unknown: {len(unknown_weapons)} default classes")

    print("  [OK] Skill weapon mapping OK")


def test_defense_layer():
    """Test defense layer inference."""
    print("Testing defense layer inference...")

    # Pure ES
    layer = DefenseLayer.from_totals(es=1000, ar=0, ev=0, ward=0)
    assert layer == DefenseLayer.ENERGY_SHIELD

    # Pure Armour
    layer = DefenseLayer.from_totals(es=0, ar=1000, ev=0, ward=0)
    assert layer == DefenseLayer.ARMOUR

    # Hybrid AR/ES
    layer = DefenseLayer.from_totals(es=500, ar=600, ev=0, ward=0)
    assert layer == DefenseLayer.HYBRID_AR_ES

    # Hybrid EV/ES
    layer = DefenseLayer.from_totals(es=500, ar=0, ev=600, ward=0)
    assert layer == DefenseLayer.HYBRID_EV_ES

    # All three
    layer = DefenseLayer.from_totals(es=400, ar=500, ev=600, ward=0)
    assert layer == DefenseLayer.HYBRID_AR_EV_ES

    # Unknown
    layer = DefenseLayer.from_totals(es=0, ar=0, ev=0, ward=0)
    assert layer == DefenseLayer.UNKNOWN

    print("  [OK] Defense layer inference OK")


def test_profile_presets():
    """Test filter profile presets (profile system V2: one dial, five levels; behaviour lives in the matrix)."""
    print("Testing profile presets...")

    assert [p.value for p in FilterProfileName] == ["Relaxed", "Recommended", "Strict", "Very Strict", "Uber Strict"]
    for name in FilterProfileName:
        assert get_profile(name.value).name == name

    # Case insensitive; the removed Endgame level resolves to Very Strict
    assert get_profile("relaxed").name == FilterProfileName.RELAXED
    assert get_profile("RECOMMENDED").name == FilterProfileName.RECOMMENDED
    assert get_profile("Endgame").name == FilterProfileName.VERY_STRICT

    print("  [OK] Profile presets OK")


def test_rule_generation():
    """Test rule generation with mock data."""
    print("Testing rule generation...")

    # Create mock slot priorities
    from exilelens.filters.profiles import SlotPriority
    from exilelens.filters.priorities import BASE_TIERS

    slot_priorities = {}

    # Weapon slot
    weapon_tiers = BASE_TIERS.get("Wands", {}).copy()
    weapon_tiers.update(BASE_TIERS.get("Sceptres", {}))
    slot_priorities[ProductSlot.WEAPON_1] = SlotPriority(
        slot=ProductSlot.WEAPON_1,
        defense_layer=DefenseLayer.ENERGY_SHIELD,
        base_tiers=weapon_tiers,
        min_item_level=75,
        min_unidentified_tier=2,
        required_sockets=5,
        required_links=5,
        defensive_floors={},
        preferred_implicits=["Spell Damage", "Cast Speed"],
        blocked_bases=frozenset(),
    )

    # Body armour
    body_tiers = BASE_TIERS.get("Body Armours", {})
    slot_priorities[ProductSlot.BODY_ARMOUR] = SlotPriority(
        slot=ProductSlot.BODY_ARMOUR,
        defense_layer=DefenseLayer.ENERGY_SHIELD,
        base_tiers=body_tiers,
        min_item_level=75,
        min_unidentified_tier=2,
        required_sockets=5,
        required_links=5,
        defensive_floors={"BaseEnergyShield": 150},
        preferred_implicits=[],
        blocked_bases=frozenset(),
    )

    # Rings
    ring_tiers = BASE_TIERS.get("Rings", {})
    slot_priorities[ProductSlot.RING_1] = SlotPriority(
        slot=ProductSlot.RING_1,
        defense_layer=DefenseLayer.ENERGY_SHIELD,
        base_tiers=ring_tiers,
        min_item_level=75,
        min_unidentified_tier=2,
        required_sockets=0,
        required_links=0,
        defensive_floors={},
        preferred_implicits=["All Elemental Resistances"],
        blocked_bases=frozenset(),
    )
    slot_priorities[ProductSlot.RING_2] = slot_priorities[ProductSlot.RING_1]

    profile = get_profile("Recommended")

    generator = RuleGenerator(
        slot_priorities=slot_priorities,
        profile=profile,
        main_skill="Spark",
        defense_layer=DefenseLayer.ENERGY_SHIELD,
    )
    rules = generator.generate_all()

    print(f"  Generated {len(rules)} rules")

    # Check categories present
    categories = set(r.category for r in rules)
    # (no build measurement: the weapon lane exists only for a verified skill class; defence / jewellery lanes need a measured build)
    expected_categories = {
        "PROTECTIVE", "TRADE_BASES", "TRADE_SPECIAL", "GENERIC_EQUIPMENT", "CRAFT_OPPORTUNITY", "UNKNOWN_SAFETY",
        "HIDDEN_CLUTTER", "HIGH_VALUE_UNID",
    }
    for cat in expected_categories:
        assert cat in categories, f"Missing category: {cat}"

    print(f"  Categories: {sorted(categories)}")
    print("  [OK] Rule generation OK")

    return rules


def test_serialization(rules=None):
    """Test filter serialization."""
    print("Testing serialization...")

    if rules is None:
        rules = test_rule_generation()
    metadata = FilterMetadata(
        build_name="Test Build",
        class_name="Sorceress",
        ascendancy="Stormweaver",
        main_skill="Spark",
        profile_name="Recommended",
        generated_at=datetime.now(),
        source_revision="test-rev",
    )

    serializer = FilterSerializer(metadata)
    filter_text = serializer.serialize(rules)

    print(f"  Filter size: {len(filter_text)} bytes, {len(filter_text.split(chr(10)))} lines")

    # Validate
    result = validate_all(filter_text)
    if not result.passed:
        print("  Validation errors:")
        for err in result.errors:
            print(f"    ERROR: {err}")
        for warn in result.warnings:
            print(f"    WARNING: {warn}")
        return False

    print("  [OK] Serialization and validation OK")
    return True


def test_determinism(rules=None):
    """Test deterministic output."""
    print("Testing determinism...")

    if rules is None:
        rules = test_rule_generation()
    metadata = FilterMetadata(
        build_name="Test Build",
        class_name="Sorceress",
        ascendancy="Stormweaver",
        main_skill="Spark",
        profile_name="Recommended",
        generated_at=datetime.now(),
        source_revision="test-rev",
    )

    serializer = FilterSerializer(metadata)
    filter_text1 = serializer.serialize(rules)
    filter_text2 = serializer.serialize(rules)

    if filter_text1 != filter_text2:
        print("  FAILED: Output not deterministic")
        return False

    print("  [OK] Determinism OK")
    return True


if __name__ == "__main__":
    from datetime import datetime

    print("=" * 60)
    print("FILTER-01 Experimental Prototype Tests")
    print("=" * 60)

    try:
        test_base_tiers()
        test_skill_weapon_mapping()
        test_defense_layer()
        test_profile_presets()
        rules = test_rule_generation()
        ok1 = test_serialization(rules)
        ok2 = test_determinism(rules)

        if ok1 and ok2:
            print("\n" + "=" * 60)
            print("ALL TESTS PASSED")
            print("=" * 60)
            sys.exit(0)
        else:
            print("\n" + "=" * 60)
            print("SOME TESTS FAILED")
            print("=" * 60)
            sys.exit(1)

    except Exception as e:
        print(f"\nTEST ERROR: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
