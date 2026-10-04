"""CORPUS-02C: Way of the Stonefist (Monk / Martial Artist) Item Check.

Fixture ``corpus02c_stonefist_martial_artist.xml`` is a real public ladder character
with Way of the Stonefist allocated; its export already carries the equipped gloves
transformed ("Runeforged Fists of Stone"). Ordinary glove candidates are transformed
in memory into the Fists of Stone item the character would equip (``items/stonefist``)
and PoB calculates everything. See docs/CORPUS-02C.md.

Every numeric expectation is checked against an independent cold PoB load of a
*hand-written* reference item (transformed by hand from the game's HandWraps data),
never against ExileLens's own transformation or scoring output.
"""

from __future__ import annotations

import json
import math
import re
from pathlib import Path
from xml.etree import ElementTree
from xml.sax.saxutils import escape

import pytest

from exilelens.items.evaluation import evaluate_item
from exilelens.items.stonefist import transformer_for
from exilelens.items.stonefist_rolls import BEST_ROLLS, WORST_ROLLS


ROOT = Path(__file__).resolve().parents[2]
CORPUS = ROOT / "fixtures" / "builds" / "public_corpus"
BUILD = CORPUS / "corpus02c_stonefist_martial_artist.xml"
STONEFIST = "Way of the Stonefist"
FISTS = "Fists of Stone"
DIRECTIONAL = {
    "MINOR_UPGRADE", "MEANINGFUL_UPGRADE", "MAJOR_UPGRADE",
    "MINOR_DOWNGRADE", "MEANINGFUL_DOWNGRADE", "MAJOR_DOWNGRADE", "STRONG_DOWNGRADE", "SIDEGRADE",
}
pytestmark = [pytest.mark.integration, pytest.mark.real_pob, pytest.mark.itemcheck]

# An ordinary glove whose modifiers all transform into FIXED values (exact).
FIXED_GLOVE = (
    "Rarity: Rare\nTest Grip\nVaal Gloves\nItem Level: 82\n--------\n"
    "+37 to maximum Energy Shield\n+82 to maximum Life\nGain 5 Life per enemy killed"
)
# Hand-transformed from game data: LocalIncreasedEnergyShield5 -> +3 Evasion / +1 ES
# per level; IncreasedLife6 -> 10% less damage taken on Low Life;
# LifeGainedFromEnemyDeath1 -> Recover 1% of maximum Life on Kill; Fists of Stone base.
FIXED_GLOVE_TRANSFORMED = """Rarity: RARE
Test Grip
Fists of Stone
Item Level: 82
Quality: 0
Implicits: 2
Has +3 to Evasion Rating per player level
Has +1 to maximum Energy Shield per player level
Has +3 to Evasion Rating per player level
Has +1 to maximum Energy Shield per player level
10% less damage taken while on Low Life
Recover 1% of maximum Life on Kill"""

# The real Massive Mitts from the Giant's Blood fixture, hand-transformed at the worst
# and best end of every ranged HandWraps modifier (AddedColdDamage6/AddedLightningDamage6
# (15-16)%, Dexterity6 (36-40)%, GlobalMeleeSkillGemLevel2 +1 level (10-12)% quality,
# IncreasedLife9 13% fixed, Strength6 (23-25)%).
_MITTS_HEADER = """Rarity: RARE
Eagle Clutches
Fists of Stone
Item Level: 81
Quality: 20
Sockets: S
Rune: Greater Desert Rune
LevelReq: 80
Implicits: 5
{enchant}{rune}Bonded: +20 to maximum Life
{enchant}{rune}Bonded: +20 to maximum Mana
{enchant}{rune}+18% to Fire Resistance
Has +3 to Evasion Rating per player level
Has +1 to maximum Energy Shield per player level
"""
MITTS_WORST = _MITTS_HEADER + """Attacks Gain 15% of Damage as Extra Cold Damage
Attacks Gain 15% of Damage as Extra Lightning Damage
+36% Surpassing chance to fire an additional Projectile
+1 to Level of all Melee Skills
+10% to Quality of all Skills
13% less damage taken while on Low Life
23% increased Area of Effect for Attacks"""
MITTS_BEST = _MITTS_HEADER + """Attacks Gain 16% of Damage as Extra Cold Damage
Attacks Gain 16% of Damage as Extra Lightning Damage
+40% Surpassing chance to fire an additional Projectile
+1 to Level of all Melee Skills
+12% to Quality of all Skills
13% less damage taken while on Low Life
25% increased Area of Effect for Attacks"""


def _equipped_item(build: Path, slot: str) -> str:
    root = ElementTree.parse(build).getroot()
    items = root.find("Items")
    assert items is not None
    raw = {item.get("id"): (item.text or "").strip() for item in items.findall("Item")}
    active = items.get("activeItemSet")
    item_set = next(entry for entry in items.findall("ItemSet") if entry.get("id") == active)
    item_id = next(entry.get("itemId") for entry in item_set.findall("Slot") if entry.get("name") == slot)
    assert item_id and item_id != "0"
    return raw[item_id]


def _variant(tmp_path: Path, name: str, *, slots: dict[str, str] | None = None, level: int | None = None,
             build: Path = BUILD) -> Path:
    text = build.read_text(encoding="utf-8")
    items = []
    for index, (slot, raw) in enumerate((slots or {}).items()):
        item_id = str(900 + index)
        items.append(f'\t\t<Item id="{item_id}">\n{escape(raw)}\n\t\t</Item>\n')
        text, count = re.subn(
            rf'(<Slot itemId=")\d+(" itemPbURL="" name="{re.escape(slot)}"/>)', rf"\g<1>{item_id}\g<2>", text,
        )
        assert count == 1, slot
    if items:
        anchor = re.search(r"\t\t<ItemSet ", text)
        assert anchor is not None
        text = text[:anchor.start()] + "".join(items) + text[anchor.start():]
    if level is not None:
        text, count = re.subn(r'(<Build [^>]*\blevel=")\d+(")', rf"\g<1>{level}\g<2>", text, count=1)
        assert count == 1
    path = tmp_path / f"{name}.xml"
    path.write_text(text, encoding="utf-8")
    return path


def _fresh(engine, path: Path) -> dict:
    engine.load_build(path)
    return engine.get_metrics()["raw"]


def _row(result: dict, slot: str = "Gloves") -> dict:
    return next(row for row in result["slot_comparisons"] if row["pob_slot"] == slot)


def _close(actual, expected) -> bool:
    return math.isclose(float(actual), float(expected), rel_tol=1e-6, abs_tol=1e-6)


def _assert_same_metrics(measured: dict, reference: dict, fields=("CombinedDPS", "TotalEHP", "Evasion", "EnergyShield", "Life")) -> None:
    for field_name in fields:
        if field_name in reference:
            assert _close(measured[field_name], reference[field_name]), (field_name, measured[field_name], reference[field_name])


# --------------------------------------------------------------------------- detection


def test_stonefist_is_detected_and_the_supported_pob_does_not_model_it(real_pob_engine) -> None:
    """Re-pin tripwire: a PoB revision that parses the passive must be re-validated."""
    build = real_pob_engine.load_build(BUILD)["build"]
    assert (build["class"], build["ascendancy"]) == ("Monk", "Martial Artist")
    assert build["item_base_transforms"] == [{
        "modeled": False, "node": STONEFIST, "node_id": 39595, "slot": "Gloves", "transformed_base": FISTS,
    }]
    equipment = {e["slot"]: e for e in real_pob_engine.get_equipment()["equipment"] if isinstance(e, dict)}
    assert FISTS in equipment["Gloves"]["base_name"]


# --------------------------------------------------------------------------- exact transformations


def test_transformed_glove_comparison_is_measured(real_pob_engine, tmp_path: Path) -> None:
    """Both sides are Fists of Stone: a like-for-like comparison PoB measures."""
    own = _equipped_item(BUILD, "Gloves")
    candidate = "\n".join(line for line in own.splitlines() if "to Critical Hit Chance" not in line)
    assert candidate != own
    baseline = _fresh(real_pob_engine, _variant(tmp_path, "own", slots={"Gloves": own}))
    expected = _fresh(real_pob_engine, _variant(tmp_path, "no_crit", slots={"Gloves": candidate}))
    assert expected["CombinedDPS"] < baseline["CombinedDPS"]

    result = evaluate_item(candidate, real_pob_engine, build_path=str(BUILD))

    row = _row(result)
    assert row["unmodeled_item_transform"] is None
    assert row["item_transform"]["candidate"]["already_transformed"] is True
    _assert_same_metrics(row["candidate"]["metrics"], expected)
    assert row["evaluation_outcome"]["evaluation_quality"] == "FULL"
    assert row["evaluation_outcome"]["verdict"] == "MEANINGFUL_DOWNGRADE"
    assert "stonefist_roll_bounds" not in row
    assert row["restore"]["pass"] is True


def test_fixed_value_ordinary_glove_is_transformed_exactly(real_pob_engine, tmp_path: Path) -> None:
    """Every modifier maps to a fixed transformed value: one exact PoB comparison."""
    reference = _fresh(real_pob_engine, _variant(tmp_path, "fixed_ref", slots={"Gloves": FIXED_GLOVE_TRANSFORMED}))
    untransformed = _fresh(real_pob_engine, _variant(tmp_path, "fixed_raw", slots={"Gloves": FIXED_GLOVE}))
    assert reference["Evasion"] != untransformed["Evasion"]

    result = evaluate_item(FIXED_GLOVE, real_pob_engine, build_path=str(BUILD))

    row = _row(result)
    transform = row["item_transform"]["candidate"]
    assert transform["ok"] is True and transform["bounded"] is False and transform["base_name"] == FISTS
    assert {m["target_id"] for m in transform["mapped"]} == {
        "HandWrapsLocalIncreasedEnergyShield5", "HandWrapsIncreasedLife6", "HandWrapsLifeGainedFromEnemyDeath1",
    }
    _assert_same_metrics(row["candidate"]["metrics"], reference)
    outcome = row["evaluation_outcome"]
    assert outcome["evaluation_quality"] == "FULL" and outcome["verdict"] in DIRECTIONAL
    assert row["unmodeled_item_transform"] is None and "stonefist_roll_bounds" not in row
    assert row["restore"]["pass"] is True


def test_already_transformed_gloves_are_never_transformed_twice(real_pob_engine, tmp_path: Path) -> None:
    """Double-transformation regression (the defect in upstream PR #2350)."""
    own = _equipped_item(BUILD, "Gloves")
    exported = _fresh(real_pob_engine, BUILD)
    real_pob_engine.load_build(BUILD)
    for rule in (WORST_ROLLS, BEST_ROLLS):
        transform = transformer_for(real_pob_engine, rule).transform(real_pob_engine, own)
        assert transform.already_transformed is True and transform.item_raw == own

    result = evaluate_item(own, real_pob_engine, build_path=str(BUILD))

    row = _row(result)
    report = row["item_transform"]
    assert report["candidate"]["already_transformed"] is True
    assert report["baseline"]["already_transformed"] is True
    _assert_same_metrics(row["baseline"]["metrics"], exported)
    _assert_same_metrics(row["candidate"]["metrics"], exported)
    assert row["evaluation_outcome"]["evaluation_quality"] == "FULL"
    assert row["evaluation_outcome"]["verdict"] == "SIDEGRADE"


# --------------------------------------------------------------------------- roll-dependent transformations


def test_ranged_rolls_are_bounded_by_independent_reference_items(real_pob_engine, tmp_path: Path) -> None:
    """Worst/best PoB runs equal hand-transformed worst/best items; a verified range is shown."""
    candidate = _equipped_item(CORPUS / "corpus02_giants_blood_shield.xml", "Gloves")
    worst_ref = _fresh(real_pob_engine, _variant(tmp_path, "worst_ref", slots={"Gloves": MITTS_WORST}))
    best_ref = _fresh(real_pob_engine, _variant(tmp_path, "best_ref", slots={"Gloves": MITTS_BEST}))
    assert worst_ref["CombinedDPS"] < best_ref["CombinedDPS"]
    real_pob_engine.load_build(BUILD)
    for rule, reference in ((WORST_ROLLS, worst_ref), (BEST_ROLLS, best_ref)):
        transform = transformer_for(real_pob_engine, rule).transform(real_pob_engine, candidate)
        assert transform.ok and transform.bounded

    result = evaluate_item(candidate, real_pob_engine, build_path=str(BUILD))

    row = _row(result)
    bounds = row["stonefist_roll_bounds"]
    # worst, middle and best, plus each of the 5 ranged lines alone at its best roll
    assert bounds["alternatives"] == 1 and bounds["single_roll_probes"] == 5 and bounds["verified_configurations"] == 8
    _assert_same_metrics(row["candidate"]["metrics"], worst_ref)
    offense = bounds["ranges"]["primary_offense"]
    assert _close(offense["worst"], worst_ref["CombinedDPS"])
    assert _close(offense["best"], best_ref["CombinedDPS"])
    outcome = row["evaluation_outcome"]
    assert outcome["evaluation_quality"] == "FULL" and outcome["verdict"] in DIRECTIONAL
    assert "STONEFIST_ROLL_DEPENDENT" in {r["code"] for r in outcome["unsupported_or_unmodeled"]}
    assert result["presentation"]["roll_dependent"] is True
    assert "at each measured roll" in result["presentation"]["verdict_explanation"]
    assert row["restore"]["pass"] is True


@pytest.mark.parametrize(
    ("source", "note"),
    [
        (CORPUS / "core04_minion_actor.xml", "Vaal Gloves"),
        (CORPUS / "core04_onehand_weapon.xml", "Runeforged Massive Mitts, two decompositions"),
        (CORPUS / "core04_bow_quiver.xml", "Secured Wraps"),
        (CORPUS / "core04_stage_context.xml", "corrupted Secured Wraps"),
        (CORPUS / "core04_mixed_hit_ailment.xml", "Massive Mitts"),
        (CORPUS / "core04_poison_ailment.xml", "Sirenscale Gloves, separate same-stat lines"),
        (CORPUS / "core04_melee_weapon.xml", "Plate Gauntlets, overlapping Added Physical tiers"),
    ],
    ids=["vaal_gloves", "runeforged_mitts", "secured_wraps", "corrupted_wraps", "massive_mitts",
         "sirenscale_separate_lines", "plate_gauntlets_overlap"],
)
def test_ordinary_real_gloves_receive_verified_verdicts(real_pob_engine, source: Path, note: str) -> None:
    """Before CORPUS-02C these were FULL on the untransformed item (wrong), then UNSUPPORTED."""
    candidate = _equipped_item(source, "Gloves")
    assert FISTS not in candidate
    real_pob_engine.load_build(BUILD)
    original_hash = real_pob_engine.get_metrics()["fingerprint_hash"]

    result = evaluate_item(candidate, real_pob_engine, build_path=str(BUILD))

    row = _row(result)
    transform = row["item_transform"]["candidate"]
    assert transform["ok"] is True and transform["base_name"] in {FISTS, "Runeforged " + FISTS}, note
    if "Runeforged" in note:
        assert transform["base_name"] == "Runeforged " + FISTS
    outcome = row["evaluation_outcome"]
    assert outcome["evaluation_quality"] == "FULL", note
    assert outcome["verdict"] in DIRECTIONAL
    assert row["unmodeled_item_transform"] is None
    bounds = row.get("stonefist_roll_bounds")
    if transform["bounded"] or transform["alternatives"] > 1:
        assert bounds and bounds["verdict"] == outcome["verdict"]
        assert bounds["alternatives"] == transform["alternatives"]
        assert bounds["verified_configurations"] >= (3 if transform["bounded"] else transform["alternatives"])
    if "two decompositions" in note:
        assert transform["alternatives"] == 2
    assert row["restore"]["pass"] is True
    assert real_pob_engine.get_metrics()["fingerprint_hash"] == original_hash


def test_roll_dependent_evaluation_is_deterministic_and_restores(real_pob_engine) -> None:
    candidate = _equipped_item(CORPUS / "core04_onehand_weapon.xml", "Gloves")
    real_pob_engine.load_build(BUILD)
    original_hash = real_pob_engine.get_metrics()["fingerprint_hash"]
    original_equipment = real_pob_engine.get_equipment()

    first = evaluate_item(candidate, real_pob_engine, build_path=str(BUILD))
    evaluate_item(FIXED_GLOVE, real_pob_engine, build_path=str(BUILD))
    second = evaluate_item(candidate, real_pob_engine, build_path=str(BUILD))

    a, b = _row(first), _row(second)
    assert a["evaluation_outcome"]["evaluation_quality"] == b["evaluation_outcome"]["evaluation_quality"] == "FULL"
    assert a["evaluation_outcome"]["verdict"] == b["evaluation_outcome"]["verdict"]
    assert a["evaluation_outcome"]["final_score"] == b["evaluation_outcome"]["final_score"]
    assert a["stonefist_roll_bounds"]["ranges"] == b["stonefist_roll_bounds"]["ranges"]
    assert real_pob_engine.get_metrics()["fingerprint_hash"] == original_hash
    assert real_pob_engine.get_equipment() == original_equipment


# --------------------------------------------------------------------------- baselines and levels


def test_ordinary_equipped_gloves_are_transformed_for_the_baseline(real_pob_engine, tmp_path: Path) -> None:
    """A hand-built PoB with ordinary gloves is measured as the character wears them."""
    hand_built = _variant(tmp_path, "hand_built", slots={"Gloves": FIXED_GLOVE})
    amulet = _equipped_item(BUILD, "Amulet")
    candidate = amulet + "\n+30 to maximum Life\n"
    reference = _fresh(real_pob_engine, _variant(tmp_path, "ref", slots={"Gloves": FIXED_GLOVE_TRANSFORMED}))
    reference_with_candidate = _fresh(
        real_pob_engine, _variant(tmp_path, "ref_amulet", slots={"Gloves": FIXED_GLOVE_TRANSFORMED, "Amulet": candidate}),
    )
    real_pob_engine.load_build(hand_built)
    untouched_hash = real_pob_engine.get_metrics()["fingerprint_hash"]

    result = evaluate_item(candidate, real_pob_engine, build_path=str(hand_built))

    row = _row(result, "Amulet")
    _assert_same_metrics(row["baseline"]["metrics"], reference)
    _assert_same_metrics(row["candidate"]["metrics"], reference_with_candidate)
    assert row["evaluation_outcome"]["evaluation_quality"] == "FULL"
    assert row["restore"]["pass"] is True
    # The user's build (ordinary gloves) is restored exactly, never rewritten.
    assert real_pob_engine.get_metrics()["fingerprint_hash"] == untouched_hash
    assert hand_built.read_text(encoding="utf-8").count("Vaal Gloves") == 1


def test_transformed_defences_follow_the_character_level(real_pob_engine, tmp_path: Path) -> None:
    low_level = _variant(tmp_path, "level70", level=70)
    reference = _fresh(real_pob_engine, _variant(tmp_path, "level70_ref", level=70, slots={"Gloves": FIXED_GLOVE_TRANSFORMED}))
    reference_100 = _fresh(real_pob_engine, _variant(tmp_path, "level100_ref", slots={"Gloves": FIXED_GLOVE_TRANSFORMED}))
    assert reference["Evasion"] < reference_100["Evasion"]

    result = evaluate_item(FIXED_GLOVE, real_pob_engine, build_path=str(low_level))

    row = _row(result)
    _assert_same_metrics(row["candidate"]["metrics"], reference)
    assert row["evaluation_outcome"]["evaluation_quality"] == "FULL"
    assert row["restore"]["pass"] is True


# --------------------------------------------------------------------------- still unsupported (not coverage)


# A unique glove with no real-item evidence (text from PoB's own definition, current variant).
UNVERIFIED_UNIQUE = (
    "Rarity: Unique\nTreefingers\nRiveted Mitts\n--------\n45% increased Armour\n"
    "Adds 8 to 14 Physical Damage to Attacks\n5% reduced Attack Speed\n+18 to Strength\n"
    "25% increased Stun Buildup\nGiant's Blood"
)


@pytest.mark.parametrize(
    ("source", "reason"),
    [
        (UNVERIFIED_UNIQUE, "the unique gloves Treefingers have no verified Way of the Stonefist transformation"),
        (CORPUS / "corpus02b_varashta_djinn.xml", "match no combination"),
    ],
    ids=["unverified_unique_gloves", "unmatched_modifiers"],
)
def test_unresolvable_gloves_stay_unsupported_with_the_precise_reason(real_pob_engine, source, reason: str) -> None:
    candidate = source if isinstance(source, str) else _equipped_item(source, "Gloves")
    result = evaluate_item(candidate, real_pob_engine, build_path=str(BUILD))

    row = _row(result)
    outcome = row["evaluation_outcome"]
    assert outcome["verdict"] == "UNSUPPORTED" and outcome["evaluation_quality"] == "UNSUPPORTED"
    assert [r["code"] for r in outcome["evaluation_quality_reasons"]] == ["ITEM_TRANSFORM_UNMODELED"]
    assert reason in outcome["evaluation_quality_reasons"][0]["detail"]
    assert row["metric_profile"]["primary_offense"]["delta_kind"] == "UNSUPPORTED"
    assert row["restore"]["pass"] is True


def test_non_glove_candidates_on_a_stonefist_build_stay_measured(real_pob_engine, tmp_path: Path) -> None:
    candidate = _equipped_item(BUILD, "Amulet") + "\n+30 to maximum Life\n"
    expected = _fresh(real_pob_engine, _variant(tmp_path, "amulet_life", slots={"Amulet": candidate}))

    result = evaluate_item(candidate, real_pob_engine, build_path=str(BUILD))

    row = _row(result, "Amulet")
    assert row["unmodeled_item_transform"] is None and row.get("item_transform") is None
    assert _close(row["candidate"]["metrics"]["Life"], expected["Life"])
    assert row["evaluation_outcome"]["evaluation_quality"] == "FULL"
    assert row["restore"]["pass"] is True


def test_guaranteed_upgrade_across_every_roll_is_communicated(real_pob_engine, tmp_path: Path) -> None:
    """Hand-built baseline with weak ordinary gloves; a better ordinary glove is an upgrade at every roll."""
    hand_built = _variant(tmp_path, "hand_built", slots={"Gloves": FIXED_GLOVE})
    candidate = FIXED_GLOVE + "\n27% increased Critical Damage Bonus\n15% increased Attack Speed"
    # CriticalMultiplier4 -> +(2.1-2.5)% Critical Hit Chance; IncreasedAttackSpeed4 -> (26-30)% Onslaught.
    base_ref = _fresh(real_pob_engine, _variant(tmp_path, "base", slots={"Gloves": FIXED_GLOVE_TRANSFORMED}))
    worst_ref = _fresh(real_pob_engine, _variant(tmp_path, "worst", slots={"Gloves": FIXED_GLOVE_TRANSFORMED
        + "\n+2.1% to Critical Hit Chance\n26% chance to gain Onslaught for 4 seconds on Hit"}))
    best_ref = _fresh(real_pob_engine, _variant(tmp_path, "best", slots={"Gloves": FIXED_GLOVE_TRANSFORMED
        + "\n+2.5% to Critical Hit Chance\n30% chance to gain Onslaught for 4 seconds on Hit"}))

    result = evaluate_item(candidate, real_pob_engine, build_path=str(hand_built))

    row = _row(result)
    _assert_same_metrics(row["baseline"]["metrics"], base_ref)
    bounds = row["stonefist_roll_bounds"]
    offense = bounds["ranges"]["primary_offense"]
    assert _close(offense["worst"], worst_ref["CombinedDPS"]) and _close(offense["best"], best_ref["CombinedDPS"])
    worst_pct = (worst_ref["CombinedDPS"] / base_ref["CombinedDPS"] - 1) * 100
    best_pct = (best_ref["CombinedDPS"] / base_ref["CombinedDPS"] - 1) * 100
    assert math.isclose(offense["worst_pct"], worst_pct, rel_tol=1e-6) and math.isclose(offense["best_pct"], best_pct, rel_tol=1e-6)
    assert row["evaluation_outcome"]["evaluation_quality"] == "FULL"
    assert row["evaluation_outcome"]["verdict"] in {"MINOR_UPGRADE", "MEANINGFUL_UPGRADE", "MAJOR_UPGRADE"}
    assert bounds["guarantee"] == "an upgrade at each measured roll"
    assert "an upgrade at each measured roll" in result["presentation"]["verdict_explanation"]
    assert row["restore"]["pass"] is True


def test_inexact_equipped_gloves_are_disclosed_on_other_slots(real_pob_engine, tmp_path: Path) -> None:
    """A hand-built PoB with ordinary ranged gloves cannot get an exact baseline: disclosed, not hidden."""
    ranged_gloves = _equipped_item(CORPUS / "corpus02_giants_blood_shield.xml", "Gloves")
    hand_built = _variant(tmp_path, "hand_built_ranged", slots={"Gloves": ranged_gloves})
    candidate = _equipped_item(BUILD, "Amulet") + "\n+30 to maximum Life\n"

    result = evaluate_item(candidate, real_pob_engine, build_path=str(hand_built))

    row = _row(result, "Amulet")
    assert row["item_transform"] is None
    codes = {r["code"] for r in row["evaluation_outcome"]["unsupported_or_unmodeled"]}
    assert "STONEFIST_BASELINE_UNTRANSFORMED" in codes
    # An item's effect can depend on the unknown gloves: never a confident recommendation.
    assert row["evaluation_outcome"]["evaluation_quality"] == "PARTIAL"
    assert row["evaluation_outcome"]["verdict"] == "UNCERTAIN"
    assert row["restore"]["pass"] is True


# --------------------------------------------------------------------------- batched configuration measurement


def _roll_configurations(engine, candidate: str) -> list[str]:
    from exilelens.items.stonefist_integration import safe_transform

    raws = [safe_transform(engine, candidate, bound, 0).item_raw for bound in ("worst", "middle", "best")]
    assert len(set(raws)) == 3
    return raws


def test_batched_configurations_measure_what_separate_transactions_measure(real_pob_engine) -> None:
    """One transaction for every roll configuration: each variant's PoB result is the one
    its own transaction gives, and the build is verifiably restored."""
    real_pob_engine.load_build(BUILD)
    original_hash = real_pob_engine.get_metrics()["fingerprint_hash"]
    raws = _roll_configurations(real_pob_engine, _equipped_item(CORPUS / "core04_minion_actor.xml", "Gloves"))

    batched = real_pob_engine.evaluate_item_variants(["Gloves"], raws)
    assert len(batched) == 3
    for raw, variant in zip(raws, batched):
        assert variant["restore"]["pass"] is True
        single = real_pob_engine.evaluate_item_slots(["Gloves"], raw)
        assert single["restore"]["pass"] is True
        [measured], [reference] = variant["slots"], single["slots"]
        assert measured["candidate"]["item_present"] is True
        assert measured["candidate"]["normalized"] == reference["candidate"]["normalized"]
        assert measured["candidate"]["fingerprint_hash"] == reference["candidate"]["fingerprint_hash"]
        assert variant["baseline"]["fingerprint_hash"] == single["baseline"]["fingerprint_hash"]
    worst, best = (variant["slots"][0]["candidate"]["metrics"] for variant in (batched[0], batched[2]))
    assert float(worst["TotalEHP"]) < float(best["TotalEHP"])
    assert real_pob_engine.get_metrics()["fingerprint_hash"] == original_hash


def test_roll_dependent_candidate_is_measured_in_one_transaction(real_pob_engine, monkeypatch) -> None:
    candidate = _equipped_item(CORPUS / "core04_onehand_weapon.xml", "Gloves")
    real_pob_engine.load_build(BUILD)
    original_hash = real_pob_engine.get_metrics()["fingerprint_hash"]
    calls: list[tuple[str, int]] = []
    singles, variants = real_pob_engine.evaluate_item_slots, real_pob_engine.evaluate_item_variants
    monkeypatch.setattr(real_pob_engine, "evaluate_item_slots",
                        lambda slots, raw, **kw: calls.append(("slots", 1)) or singles(slots, raw, **kw))
    monkeypatch.setattr(real_pob_engine, "evaluate_item_variants",
                        lambda slots, raws, **kw: calls.append(("variants", len(raws))) or variants(slots, raws, **kw))

    result = evaluate_item(candidate, real_pob_engine, build_path=str(BUILD))
    # Two decomposition alternatives x worst/middle/best rolls, one transaction.
    assert calls == [("variants", 6)]
    assert _row(result)["stonefist_roll_bounds"]["verified_configurations"] == 6
    assert real_pob_engine.get_metrics()["fingerprint_hash"] == original_hash


def test_a_failed_batch_restore_invalidates_the_build(real_pob_engine) -> None:
    from exilelens.errors import RestoreFailed

    candidate = _equipped_item(CORPUS / "core04_minion_actor.xml", "Gloves")
    real_pob_engine.load_build(BUILD)
    raws = _roll_configurations(real_pob_engine, candidate)
    with pytest.raises(RestoreFailed):
        real_pob_engine.evaluate_item_variants(["Gloves"], raws, test_fault="corrupt_restore")
    reloads = real_pob_engine.reload_count
    recovered = evaluate_item(candidate, real_pob_engine, build_path=str(BUILD))
    # The corrupted build is re-parsed once before any configuration is measured
    # (`last_load_reloaded` only reflects the last of the configurations' readiness checks).
    assert real_pob_engine.reload_count == reloads + 1
    assert _row(recovered)["restore"]["pass"] is True
    assert "stonefist_roll_bounds" in _row(recovered)


# --------------------------------------------------------------------------- unique gloves (real items)

UNIQUE_EVIDENCE = json.loads((ROOT / "fixtures" / "items" / "stonefist_unique_gloves_poeninja.json").read_text(encoding="utf-8"))["uniques"]
# Modifiers whose line is not part of an item's text (granted skills, markers).
_NOT_IN_ITEM_TEXT = {"UniqueCrushingFearSkill1", "UniqueAtziriHeraldSkill1", "UniqueNothingHappened"}


def _unique_raw(name: str, item: dict) -> str:
    lines = [line for text in item["explicit"] for line in text.split("\n")]
    return "\n".join(["Rarity: Unique", name, item["base"], "--------", *lines])


def _numbers(line: str) -> list[float]:
    return [float(value) for value in re.findall(r"-?\d+(?:\.\d+)?", line)]


def _shape(line: str) -> str:
    return re.sub(r"[+-]?\d+(?:\.\d+)?", "#", line)


def _assert_real_transformed_items_are_bracketed(name: str, worst, best, real_items: list[dict]) -> None:
    """The game's own transformed items: the same transformed modifiers, and every real
    line lies between the transformation's worst and best measured line."""
    ours = {m["target_id"] for m in worst.mapped if m["target_id"]}
    measured = {row["line"] for row in worst.explicit} | {row["line"] for row in best.explicit}
    by_shape: dict[str, list[list[float]]] = {}
    for line in measured:
        by_shape.setdefault(_shape(line), []).append(_numbers(line))
    for real in real_items:
        assert ours == set(real["ids"]) - _NOT_IN_ITEM_TEXT, name
        for text in real["explicit"]:
            for line in text.split("\n"):
                ends = by_shape.get(_shape(line))
                assert ends, (name, line)
                values = _numbers(line)
                for index, value in enumerate(values):
                    column = [end[index] for end in ends]
                    assert min(column) - 1e-9 <= value <= max(column) + 1e-9, (name, line, ends)


@pytest.mark.parametrize("name", [n for n, e in UNIQUE_EVIDENCE.items() if e.get("untransformed")])
def test_unique_gloves_transform_exactly_like_the_games_transformed_items(real_pob_engine, name: str) -> None:
    """A real untransformed unique, transformed here, must equal the real transformed ones
    (same HandWraps modifiers, each real value within the measured roll range)."""
    from exilelens.items.stonefist_integration import safe_transform

    real_pob_engine.load_build(BUILD)
    raw = _unique_raw(name, UNIQUE_EVIDENCE[name]["untransformed"])
    worst, best = safe_transform(real_pob_engine, raw, "worst", 0), safe_transform(real_pob_engine, raw, "best", 0)
    assert worst.ok and best.ok, (worst.unresolved, best.unresolved)
    # Observed: runic ("RunicUnique") gloves become Runeforged Fists of Stone, others Fists of Stone.
    runic = UNIQUE_EVIDENCE[name]["untransformed"]["base"].startswith("Runemastered")
    assert worst.base_name == ("Runeforged " + FISTS if runic else FISTS)
    _assert_real_transformed_items_are_bracketed(name, worst, best, UNIQUE_EVIDENCE[name]["transformed"])


def test_corpus_unique_gloves_receive_a_verified_verdict(real_pob_engine) -> None:
    """The real Aurseize from the CORE-04 weapon-swap build (previously refused as a unique)."""
    from exilelens.items.stonefist_integration import safe_transform

    candidate = _equipped_item(CORPUS / "core04_weapon_swap.xml", "Gloves")
    real_pob_engine.load_build(BUILD)
    original_hash = real_pob_engine.get_metrics()["fingerprint_hash"]
    worst = safe_transform(real_pob_engine, candidate, "worst", 0)
    best = safe_transform(real_pob_engine, candidate, "best", 0)
    _assert_real_transformed_items_are_bracketed("Aurseize", worst, best, UNIQUE_EVIDENCE["Aurseize"]["transformed"])
    # PoB 0.23.1 still has the older "(20-30)% increased Rarity" range; the line is
    # identified by its text and reported, its value is not used.
    assert worst.source_values_outside_pob_data == ["56% increased Rarity of Items found"]

    result = evaluate_item(candidate, real_pob_engine, build_path=str(BUILD))
    row = _row(result)
    outcome = row["evaluation_outcome"]
    assert outcome["evaluation_quality"] == "FULL" and outcome["verdict"] in DIRECTIONAL
    assert row["item_transform"]["candidate"]["ok"] is True
    bounds = row["stonefist_roll_bounds"]
    assert bounds["verified_configurations"] == 3 + bounds["single_roll_probes"] and bounds["single_roll_probes"] == 2
    assert row["restore"]["pass"] is True
    assert real_pob_engine.get_metrics()["fingerprint_hash"] == original_hash


def test_a_unique_whose_pob_results_are_not_ordered_stays_unsupported(real_pob_engine) -> None:
    """Candlemaker: PoB's DPS falls as "Enemies Ignited or Chilled by you have -#% to
    Elemental Resistances" grows, so no verdict holds for every roll."""
    raw = _unique_raw("Candlemaker", UNIQUE_EVIDENCE["Candlemaker"]["untransformed"])
    result = evaluate_item(raw, real_pob_engine, build_path=str(BUILD))
    row = _row(result)
    assert row["evaluation_outcome"]["verdict"] == "UNSUPPORTED"
    assert "not ordered across the roll range (CombinedDPS)" in row["evaluation_outcome"]["evaluation_quality_reasons"][0]["detail"]
    assert row["restore"]["pass"] is True


# --------------------------------------------------------------------------- data and roll probes


def test_every_supported_transformed_modifier_has_its_same_named_source(real_pob_engine) -> None:
    """E.g. HandWrapsEnergyShieldRechargeRate5 <- EnergyShieldRechargeRate5______ (the game
    id's trailing underscores), same affix "of Ardour"."""
    real_pob_engine.load_build(BUILD)
    mods = real_pob_engine._call("get_item_transform_mods", {"prefix": "HandWraps"})["mods"]
    ordinary = [m for m in mods if m["target_table"] == "Item"]
    assert all(m.get("source_id") for m in ordinary)
    assert all(m["affix"] == m["source_affix"] for m in ordinary if m.get("source_table") != "Exclusive")
    recharge = next(m for m in mods if m["target_id"] == "HandWrapsEnergyShieldRechargeRate5")
    assert recharge["source_id"] == "EnergyShieldRechargeRate5______" and recharge["affix"] == "of Ardour"
    unique = [m for m in mods if m["target_table"] == "Exclusive" and m.get("source_id")]
    assert len(unique) >= 170


def test_each_ranged_line_is_probed_alone_for_a_real_glove(real_pob_engine, monkeypatch) -> None:
    """Vaal Gloves with four ranged transformed lines: 3 roll configurations plus one
    probe per line, all in one transaction, all ordered and agreeing."""
    candidate = _equipped_item(CORPUS / "core04_minion_actor.xml", "Gloves")
    calls: list[int] = []
    variants = real_pob_engine.evaluate_item_variants
    monkeypatch.setattr(real_pob_engine, "evaluate_item_variants",
                        lambda slots, raws, **kw: calls.append(len(raws)) or variants(slots, raws, **kw))
    result = evaluate_item(candidate, real_pob_engine, build_path=str(BUILD))
    bounds = _row(result)["stonefist_roll_bounds"]
    assert _row(result)["evaluation_outcome"]["evaluation_quality"] == "FULL"
    assert calls == [7]
    assert bounds["single_roll_probes"] == 4 and bounds["verified_configurations"] == 7
    assert "each ranged modifier alone at its highest roll" in bounds["summary"]

