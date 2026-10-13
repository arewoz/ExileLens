"""FILTER-08C: weapon/slot family coverage, class-name verification and the hardened guards. Offline.

Run with:  python -m pytest tests/test_filter08c_coverage.py -m ""
"""
from __future__ import annotations

import pytest

from exilelens.filters import benchmark08b as bm, benchmark08b_fn as fn, skill_facts
from exilelens.filters.build_needs import BuildNeedsSnapshot
from exilelens.filters.intel_generate import generate
from exilelens.filters.opportunity import ROLE_BY_CLASS, BuildOpportunityModel, EvidenceKind
from exilelens.filters.preview import PreviewItem, preview_decision
from exilelens.filters.priorities import (EXTENDED_OFFHAND_CLASSES, EXTENDED_WEAPON_CLASSES, SLOT_EQUIPMENT_CLASSES)
from exilelens.filters.profiles import FilterProfileName, ProductSlot
from exilelens.filters.validation import validate_all
from exilelens.filters.verified_bases import FILTER_TO_POB_CLASS, load_base_properties, native_class

NEEDS = bm.NEEDS_DIR if hasattr(bm, "NEEDS_DIR") else None

# Native item classes confirmed against PoE2DB's equipment item-class list (https://poe2db.tw/us/Items, 2026-10-02).
POE2DB_EQUIPMENT_CLASSES = {
    "Claws", "Daggers", "Wands", "One Hand Swords", "One Hand Axes", "One Hand Maces", "Sceptres", "Spears", "Flails",
    "Bows", "Staves", "Two Hand Swords", "Two Hand Axes", "Two Hand Maces", "Quarterstaves", "Crossbows", "Traps",
    "Talismans", "Quivers", "Shields", "Bucklers", "Foci", "Gloves", "Boots", "Body Armours", "Helmets", "Amulets", "Rings",
    "Belts", "Jewels",
    "Charms",    # FILTER-08E: listed by PoE2DB (https://poe2db.tw/us/Items, 2026-10-03)
}
WEAPON_FAMILIES = [c for c, role in ROLE_BY_CLASS.items() if role == "weapon"]


def _top_base(filter_class: str) -> str:
    pob = FILTER_TO_POB_CLASS[filter_class]
    rows = sorted(((r["required_level"], n) for n, r in load_base_properties().items()
                   if native_class(n) == filter_class and not n.startswith(("Runeforged ", "Runemastered "))), reverse=True)
    assert rows, (filter_class, pob)
    return rows[0][1]


def _item(base: str, rarity: str = "Magic", level: int = 88) -> PreviewItem:
    r = load_base_properties()[base]
    return PreviewItem(base, "08C", native_class(base), base, rarity, item_level=level,
                       base_energy_shield=r["energy_shield"], base_armour=r["armour"], base_evasion=r["evasion"])


def test_every_native_class_name_is_a_verified_poe2_item_class():
    for name in FILTER_TO_POB_CLASS:
        if name == "Flasks":
            continue  # pre-existing non-equipment class, not part of PoE2DB's equipment list
        assert name in POE2DB_EQUIPMENT_CLASSES, f"{name} is not a documented PoE2 item class"
    for family in (*EXTENDED_WEAPON_CLASSES, *EXTENDED_OFFHAND_CLASSES):
        assert family in FILTER_TO_POB_CLASS and family in ROLE_BY_CLASS


def test_bucklers_are_their_own_native_class_and_the_validator_knows():
    buckler = next(n for n in load_base_properties() if n.endswith("Buckler"))
    shield = next(n for n, r in load_base_properties().items() if r["class"] == "Shield" and "Buckler" not in n)
    assert native_class(buckler) == "Bucklers" and native_class(shield) == "Shields"
    bad = f'Show\n\tClass "Shields"\n\tBaseType "{buckler}"\n'
    assert not validate_all(bad).passed
    good = f'Show\n\tClass "Bucklers"\n\tBaseType "{buckler}"\n'
    assert validate_all(good).passed or not any("native Class" in e for e in validate_all(good).errors)


def _skill_requiring(filter_class: str) -> str:
    candidates = []
    for sid in skill_facts._skills():
        if not sid.endswith("Player"):
            continue
        profile = skill_facts.lookup(skill_id=sid)
        if profile and profile.weapon_classes and filter_class in profile.weapon_classes:
            candidates.append((len(profile.weapon_classes), sid))
    assert candidates, f"no verified PoB2 skill requires {filter_class}"
    return min(candidates)[1]  # the skill ID (names are ambiguous across monster/player variants)


@pytest.mark.parametrize("family", WEAPON_FAMILIES)
def test_each_weapon_family_survives_the_whole_pipeline(family):
    """A verified skill requirement reaches generation: rules exist for the family and its top base is shown everywhere."""
    skill = _skill_requiring(family) if family not in ("Wands", "Sceptres") else None
    if skill is None:
        pytest.skip("wands and sceptres have no weapon-type skill requirement in PoB2 (spell weapons); covered by spell builds")
    needs = BuildNeedsSnapshot.unavailable(f"requires-{family}", "test: no measurement", skill_id=skill)
    classes, reasons, _ = BuildOpportunityModel(needs).weapon_classes(SLOT_EQUIPMENT_CLASSES[ProductSlot.WEAPON_1] + EXTENDED_WEAPON_CLASSES)
    assert family in classes and reasons[0].kind == EvidenceKind.VERIFIED_BASE_FACT
    top = _top_base(family)
    for profile in FilterProfileName:
        generated = generate(needs, profile)
        assert generated.valid, (family, profile, generated.errors[:2])
        rule_bases = {b for r in generated.rules if r.category == "BUILD_WEAPON" for b in r.base_types}
        assert any(native_class(b) == family for b in rule_bases), (family, profile)
        assert not preview_decision(generated.rules, _item(top)).hidden, (family, profile, top)


@pytest.mark.parametrize("family", [*WEAPON_FAMILIES, "Shields", "Bucklers", "Foci", "Quivers"])
def test_no_family_disappears_when_the_build_is_unmeasured(family):
    """Widening, not narrowing: with no measurement every supported family's top base stays visible in the default profile."""
    needs = BuildNeedsSnapshot.unavailable("unknown", "test: unresolved skill")
    generated = generate(needs, "Recommended")
    assert generated.valid
    assert not preview_decision(generated.rules, _item(_top_base(family), level=86)).hidden, family


def test_curated_swords_and_axes_aliases_expand_to_native_classes():
    needs = BuildNeedsSnapshot.unavailable("curated", "test", skill_name="Leap Slam")  # curated map names 'Axes'
    classes, reasons, _ = BuildOpportunityModel(needs).weapon_classes(
        SLOT_EQUIPMENT_CLASSES[ProductSlot.WEAPON_1] + EXTENDED_WEAPON_CLASSES)
    assert reasons  # evidence recorded
    assert all(c in ROLE_BY_CLASS for c in classes)


# --- retired legacy map, offhand families, defence direction ---------------------------------------------------------------------------
from dataclasses import replace  # noqa: E402

from exilelens.filters.build_needs import NeedSignal, Relevance  # noqa: E402
from exilelens.filters.priorities import SKILL_WEAPON_CLASSES  # noqa: E402

SPARK_08B = bm.NEEDS_DIR / "spark_fixture.json" if hasattr(bm, "NEEDS_DIR") else None
_NEEDS_08B = __import__("pathlib").Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "filter_needs" / "filter08b"


def test_curated_skill_map_has_no_dead_entries():
    """Every remaining curated key resolves to a real PoB2 skill; the 76 PoE1-only names were retired (retired_skill_map.json)."""
    dead = [name for name in SKILL_WEAPON_CLASSES if skill_facts.lookup(name=name) is None]
    assert not dead, dead
    retired = __import__("json").loads((__import__("pathlib").Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "filter_retired_skill_map.json").read_text(encoding="utf-8"))["retired"]
    assert len(retired) == 76 and not set(retired) & set(SKILL_WEAPON_CLASSES)


def test_foci_follow_spell_builds_and_quivers_follow_bow_builds():
    snaps = bm.load_snapshots(_NEEDS_08B)
    spell, bow = snaps["spark_fixture"], snaps["core04_bow_quiver"]
    focus, quiver = _top_base("Foci"), _top_base("Quivers")
    for profile in ("Relaxed", "Recommended", "Strict"):
        assert not preview_decision(generate(spell, profile).rules, _item(focus, level=88)).hidden, ("focus", profile)
        assert not preview_decision(generate(bow, profile).rules, _item(quiver, level=88)).hidden, ("quiver", profile)


_with_layers = bm.with_layers


def _hidden_layer_rules(needs) -> set[str]:
    """Defence layers the BUILD modifier acts on (profile system V2): the pure-layer bases carried by build_irrelevant_generic_nm rules.
    At Recommended the modifier changes the top-tier bases (QUIET -> HIDE); low bases are hidden by the generic matrix row anyway."""
    props = load_base_properties()
    layers = set()
    for rule in generate(needs, "Recommended").rules:
        if rule.row == "build_irrelevant_generic_nm":
            for base in rule.base_types:
                layers.update(k for k in ("armour", "evasion", "energy_shield") if props[base].get(k))
    return layers


@pytest.mark.parametrize("responding, expected", [
    (("ES",), {"armour", "evasion"}),
    (("AR",), {"evasion", "energy_shield"}),
    (("EV",), {"armour", "energy_shield"}),
    (("AR", "EV"), {"energy_shield"}),
    (("AR", "ES"), {"evasion"}),
    (("EV", "ES"), {"armour"}),
    (("AR", "EV", "ES"), set()),
])
def test_measured_defence_direction_hides_only_layers_that_do_not_respond(responding, expected):
    needs = bm.load_snapshots(_NEEDS_08B)["spark_fixture"]
    layers = {k: ("STRONG" if k in responding else "NO_RESPONSE") for k in ("AR", "EV", "ES")}
    measured = _with_layers(needs, **layers)
    assert _hidden_layer_rules(measured) == expected


def test_defence_direction_that_is_not_measured_hides_nothing():
    needs = bm.load_snapshots(_NEEDS_08B)["spark_fixture"]
    assert _hidden_layer_rules(needs) == set()                                   # Armour/Evasion never tested
    untested = _with_layers(needs, AR="NOT_ESTABLISHED", EV="NO_RESPONSE", ES="STRONG")
    assert _hidden_layer_rules(untested) == set()                                # one layer untested: unknown direction
    silent = _with_layers(needs, AR="NO_RESPONSE", EV="NO_RESPONSE", ES="NO_RESPONSE")
    assert _hidden_layer_rules(silent) == set()                                  # nothing responds: no evidence of direction
    weak = _with_layers(needs, AR="STRONG", EV="NO_RESPONSE", ES="NO_RESPONSE", EV_confidence="LOW", ES_confidence="LOW")
    assert _hidden_layer_rules(weak) == set()                                    # LOW-confidence silence never hides


def test_measured_layer_hide_hits_only_pure_layers_and_is_justified():
    from exilelens.filters.rules import generic_sets
    needs = _with_layers(bm.load_snapshots(_NEEDS_08B)["spark_fixture"], AR="NO_RESPONSE", EV="NO_RESPONSE", ES="STRONG")
    generated = generate(needs, "Recommended")
    props = load_base_properties()
    top = set(generic_sets().top_eq)
    pure_ev = next(n for n, r in props.items() if n in top and r["class"] == "Body Armour" and r["evasion"] and not r["armour"] and not r["energy_shield"])
    hybrid = next(n for n, r in props.items() if n in top and r["class"] == "Body Armour" and r["evasion"] and r["energy_shield"] and not r["armour"])
    for base, expect_build_hide in ((pure_ev, True), (hybrid, False)):
        item = PreviewItem(base, "t", "Body Armours", base, "Magic", item_level=70, base_energy_shield=props[base]["energy_shield"],
                           base_armour=props[base]["armour"], base_evasion=props[base]["evasion"])
        decision = preview_decision(generated.rules, item)
        # a hybrid is never touched by the build modifier (the generic matrix row still applies to it)
        assert (decision.row == "build_irrelevant_generic_nm") == expect_build_hide, (base, decision.rule_name)
        if expect_build_hide:
            assert decision.hidden and decision.state == "HIDE"
            rule = next(r for r in generated.rules if r.name == decision.rule_name)
            assert rule.justification.startswith("MEASURED BUILD EVIDENCE")
            assert bm.reduction_justification(item, needs, generated, matched_rule=rule.name) == bm.MEASURED_BUILD_EVIDENCE
        else:
            assert not decision.hidden            # QUIET at Recommended: visible, generic top-base row



# --- FILTER-08C measurements (Armour/Evasion tested) -------------------------------------------------------------------------------------
_NEEDS_08C = __import__("pathlib").Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "filter_needs" / "filter08c"


@pytest.fixture(scope="module")
def snaps_08c():
    loaded = bm.load_snapshots(_NEEDS_08C)
    assert len(loaded) >= 20
    return loaded


def test_08c_measurements_cover_defence_and_state_their_limits(snaps_08c):
    spark = snaps_08c["spark_fixture"]
    assert spark.coverage.name == "MEASURED" and spark.signal("ARMOUR").status == "MEASURED" and spark.signal("EVASION").status == "MEASURED"
    minion = snaps_08c["core04_minion_actor"]
    assert minion.coverage.name == "PARTIAL" and any("weapon mapping fallback" in r for r in minion.coverage_reasons)
    assert minion.signal("MINION_DAMAGE") is not None and minion.signal("MINION_SKILL_LEVELS") is not None
    poison = snaps_08c["core04_poison_ailment"]
    assert poison.signal("POISON_DURATION") is not None and poison.skill.weapon_classes == ("Bows",)
    assert all(s.coverage.name in ("MEASURED", "PARTIAL") for s in snaps_08c.values())


def test_every_08c_reduction_versus_legacy_has_one_of_the_four_justifications(snaps_08c):
    items = bm.systematic_items()[::6]
    allowed = {bm.VERIFIED_INCOMPATIBILITY, bm.MEASURED_BUILD_EVIDENCE, bm.EXPLICIT_PROFILE_POLICY, bm.INDEPENDENT_CLUTTER}
    for label in ("spark_fixture", "core04_bow_quiver", "core04_minion_actor", "core04_melee_weapon"):
        needs = snaps_08c[label]
        for profile in bm.PROFILES:
            new_result, old_result = generate(needs, profile), generate(needs, profile, intel=False)
            new, old = bm.evaluate(new_result, items), bm.evaluate(old_result, items)
            for item, a, b in zip(items, old, new):
                if not a.hidden and b.hidden:
                    assert bm.reduction_justification(item, needs, new_result, matched_rule=b.rule) in allowed, (label, profile, item.name)


def test_minion_build_widens_instead_of_narrowing(snaps_08c):
    """A PARTIAL minion build keeps the broad weapon classes: a Sceptre, Wand and Staff top base are all visible."""
    needs = snaps_08c["core04_minion_actor"]
    generated = generate(needs, "Recommended")
    for family in ("Sceptres", "Wands", "Staves"):
        assert not preview_decision(generated.rules, _item(_top_base(family), level=86)).hidden, family
