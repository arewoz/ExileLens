"""Small strategic Item Check validation suite using only public fixtures."""

from __future__ import annotations

import re
from pathlib import Path
from xml.etree import ElementTree

import pytest

from poe2value.errors import RestoreFailed
from poe2value.items.evaluation import evaluate_item


ROOT = Path(__file__).resolve().parents[2]
BUILD = ROOT / "fixtures" / "builds" / "core04_player_ring.xml"
ITEMS = ROOT / "fixtures" / "items"
pytestmark = [pytest.mark.integration, pytest.mark.real_pob, pytest.mark.itemcheck]


def _item(name: str) -> str:
    return (ITEMS / name).read_text(encoding="utf-8")


def _slot(engine, item: str, slot: str = "Ring 1", *, build: Path = BUILD) -> dict:
    result = evaluate_item(_item(item), engine, build_path=str(build))
    return next(row for row in result["slot_comparisons"] if row["pob_slot"] == slot)


def _equipped_item(path: Path, slot: str) -> str:
    root = ElementTree.parse(path).getroot()
    items = root.find("Items")
    assert items is not None
    raw = {item.get("id"): (item.text or "").strip() for item in items.findall("Item")}
    active = items.get("activeItemSet")
    item_set = next(entry for entry in items.findall("ItemSet") if entry.get("id") == active)
    item_id = next(entry.get("itemId") for entry in item_set.findall("Slot") if entry.get("name") == slot)
    assert item_id and item_id != "0"
    return raw[item_id]


def test_supported_offense_and_defense_comparisons_are_measured(real_pob_engine) -> None:
    offense = _slot(real_pob_engine, "core04_offense_ring.txt")
    defense = _slot(real_pob_engine, "core04_defense_ring.txt")
    assert offense["evaluation_outcome"]["evaluation_quality"] == "FULL"
    assert offense["evaluation_outcome"]["item_impact"]["axes"]["OFFENSE"]["direction"] == "POSITIVE"
    assert defense["evaluation_outcome"]["item_impact"]["axes"]["DEFENSE"]["direction"] == "POSITIVE"
    assert offense["restore"]["pass"] is True and defense["restore"]["pass"] is True


def test_ring_tradeoff_and_best_slot_remain_semantic(real_pob_engine) -> None:
    result = evaluate_item(_item("core04_tradeoff_ring.txt"), real_pob_engine, build_path=str(BUILD))
    ring_one = next(row for row in result["slot_comparisons"] if row["pob_slot"] == "Ring 1")
    assert {row["pob_slot"] for row in result["slot_comparisons"]} == {"Ring 1", "Ring 2"}
    assert ring_one["evaluation_outcome"]["item_impact"]["pattern"] == "TRADEOFF"
    assert ring_one["evaluation_outcome"]["verdict"] == "SIDEGRADE"
    assert result["recommendation"]["pob_slot"] == result["slot_comparisons"][0]["pob_slot"]
    assert all(row["restore"]["pass"] is True for row in result["slot_comparisons"])


def test_empty_ring_slot_is_explicitly_compared_not_inferred_as_missing(real_pob_engine, tmp_path: Path) -> None:
    original = BUILD.read_text(encoding="utf-8")
    empty, replacements = re.subn(
        r'<Slot name="Ring 2" itemId="\d+" itemPbURL=""/>',
        '<Slot name="Ring 2" itemId="0" itemPbURL=""/>',
        original,
        count=1,
    )
    assert replacements == 1
    build = tmp_path / "core04_empty_ring.xml"
    build.write_text(empty, encoding="utf-8")
    result = evaluate_item(_item("core04_offense_ring.txt"), real_pob_engine, build_path=str(build))
    ring_two = next(row for row in result["slot_comparisons"] if row["pob_slot"] == "Ring 2")
    assert ring_two["baseline_item"]["empty"] is True
    assert ring_two["evaluation_outcome"]["replacing_empty_slot"] is True
    assert ring_two["candidate"]["item_present"] is True
    assert ring_two["restore"]["pass"] is True


def test_bow_quiver_preserves_player_skill_and_restore(real_pob_engine) -> None:
    build = ROOT / "fixtures" / "builds" / "public_corpus" / "core04_bow_quiver.xml"
    quiver = _equipped_item(build, "Weapon 2") + "\n200% increased Damage\n"
    result = evaluate_item(quiver, real_pob_engine, build_path=str(build))
    row = next(comparison for comparison in result["slot_comparisons"] if comparison["pob_slot"] == "Weapon 2")
    assert result["pob_parse"]["item"]["type"] == "Quiver"
    assert row["baseline"]["primary_skill"]["skill_name"] == "Ice Shot"
    assert row["candidate"]["primary_skill"]["skill_name"] == "Ice Shot"
    assert row["candidate"]["item_present"] is True
    assert row["restore"]["pass"] is True


def test_minion_actor_and_stage_context_are_retained(real_pob_engine) -> None:
    minion = ROOT / "fixtures" / "builds" / "public_corpus" / "core04_minion_actor.xml"
    stage = ROOT / "fixtures" / "builds" / "public_corpus" / "core04_stage_context.xml"
    minion_info = real_pob_engine.load_build(minion)["build"]["main_skill_identity"]
    stage_info = real_pob_engine.load_build(stage)["build"]["main_skill_identity"]
    assert minion_info["skill_id"] == "SummonInfernalHoundPlayer"
    assert minion_info["damage_owner"] == "MINION"
    assert stage_info["skill_id"] == "FlameblastPlayer"
    assert stage_info["calculation_mode"] == "CHANNEL_RELEASE"
    assert stage_info["stage_count"] == 1


def test_failed_candidate_restore_is_followed_by_a_clean_valid_evaluation(real_pob_engine) -> None:
    candidate = _item("core04_baseline_ring.txt")
    real_pob_engine.load_build(BUILD)
    with pytest.raises(RestoreFailed):
        real_pob_engine.evaluate_candidate("Ring 1", candidate, test_fault="corrupt_restore")
    recovered = _slot(real_pob_engine, "core04_offense_ring.txt")
    assert real_pob_engine.last_load_reloaded is True
    assert recovered["restore"]["pass"] is True


def test_one_item_check_uses_one_batched_candidate_evaluation(real_pob_engine, monkeypatch) -> None:
    calls: list[tuple[str, ...]] = []
    original = real_pob_engine.evaluate_item_slots

    def counted(slots, *args, **kwargs):
        calls.append(tuple(slots))
        return original(slots, *args, **kwargs)

    monkeypatch.setattr(real_pob_engine, "evaluate_item_slots", counted)
    result = evaluate_item(_item("core04_offense_ring.txt"), real_pob_engine, build_path=str(BUILD))
    assert calls == [("Ring 1", "Ring 2")]
    assert len(result["slot_comparisons"]) == 2


MELEE_BUILD = ROOT / "fixtures" / "builds" / "public_corpus" / "core04_melee_weapon.xml"


def test_melee_two_hand_weapon_upgrade_is_measured_and_restored(real_pob_engine) -> None:
    """CORE04-MELEE-WEAPON: a real two-handed mace replacement on a Sunder build.

    The candidate is the build's own equipped weapon plus one added physical-damage
    modifier (same "clone the equipped item, add one mod" technique as the bow/quiver
    fixture). Expected quality/verdict below is not assumed: it was captured from a
    real PoB run of this exact candidate before this assertion was written (see
    docs/CORPUS_COVERAGE_METHODOLOGY.md, M1.1 melee slice) — a +11%-ish offense-only
    gain with an unchanged defense axis produced FULL quality / MEANINGFUL_UPGRADE.
    """
    baseline_item = _equipped_item(MELEE_BUILD, "Weapon 1")
    candidate = baseline_item + "\n40% increased Physical Damage\n"
    result = evaluate_item(candidate, real_pob_engine, build_path=str(MELEE_BUILD))

    assert result["pob_parse"]["item"]["type"] == "Two Hand Mace"
    assert result["pob_parse"]["item"]["two_hand"] is True
    # A two-handed weapon has exactly one legal slot given this build's empty offhand.
    assert {row["pob_slot"] for row in result["slot_comparisons"]} == {"Weapon 1"}

    row = result["slot_comparisons"][0]
    assert row["baseline"]["primary_skill"]["skill_name"] == "Sunder"
    assert row["candidate"]["primary_skill"]["skill_name"] == "Sunder"
    assert row["candidate"]["item_present"] is True

    outcome = row["evaluation_outcome"]
    assert outcome["evaluation_quality"] == "FULL"
    assert outcome["item_impact"]["axes"]["OFFENSE"]["direction"] == "POSITIVE"
    assert outcome["item_impact"]["axes"]["DEFENSE"]["direction"] == "NEUTRAL"
    assert outcome["verdict"] == "MEANINGFUL_UPGRADE"

    assert row["restore"]["pass"] is True
    assert result["recommendation"]["pob_slot"] == "Weapon 1"


def test_melee_weapon_repeated_evaluation_does_not_leak_state(real_pob_engine) -> None:
    baseline_item = _equipped_item(MELEE_BUILD, "Weapon 1")
    candidate = baseline_item + "\n40% increased Physical Damage\n"

    first = evaluate_item(candidate, real_pob_engine, build_path=str(MELEE_BUILD))
    second = evaluate_item(candidate, real_pob_engine, build_path=str(MELEE_BUILD))

    first_row = first["slot_comparisons"][0]
    second_row = second["slot_comparisons"][0]
    assert first_row["baseline_primary_metric"]["skill_name"] == second_row["baseline_primary_metric"]["skill_name"] == "Sunder"
    assert first_row["evaluation_outcome"]["final_score"] == second_row["evaluation_outcome"]["final_score"]
    assert first_row["evaluation_outcome"]["verdict"] == second_row["evaluation_outcome"]["verdict"]
    assert first_row["restore"]["pass"] is True
    assert second_row["restore"]["pass"] is True


ONEHAND_BUILD = ROOT / "fixtures" / "builds" / "public_corpus" / "core04_onehand_weapon.xml"


def test_onehand_weapon_candidate_is_ambiguous_and_resolved_safely(real_pob_engine) -> None:
    """CORE04-ONEHAND-WEAPON: a one-hand mace candidate is legal in two weapon slots.

    This build (Warrior/Titan, Shield Wall) has a one-hand mace in Weapon 1 and a
    tower shield in Weapon 2. A one-hand mace candidate is reported by PoB as legal
    replacement for BOTH slots: Weapon 1 (a normal weapon swap) and Weapon 2 (which
    would remove the shield and start dual-wielding). PoB itself decides slot
    legality (`IsItemValidForSlot`); ExileLens does not second-guess it, it evaluates
    every legal slot and ranks them under the same guardrail policy as any other
    multi-slot item (e.g. Ring 1/Ring 2).

    Expected result below is not assumed: it was captured from a real PoB run of this
    exact candidate before this assertion was written (see
    docs/CORPUS_COVERAGE_METHODOLOGY.md, M1.1 one-hand-weapon slice). Removing the
    shield to equip the candidate in Weapon 2 breaks the Shield Wall main skill (it
    requires an equipped shield), which the guardrail policy correctly downgrades to
    NOT_VIABLE -- never a confident directional verdict against the wrong slot.
    """
    baseline_item = _equipped_item(ONEHAND_BUILD, "Weapon 1")
    candidate = baseline_item + "\n+300 to maximum Life\n"
    result = evaluate_item(candidate, real_pob_engine, build_path=str(ONEHAND_BUILD))

    assert result["pob_parse"]["weapon_layout"] == "AMBIGUOUS_WEAPON_LAYOUT"
    assert result["pob_parse"]["item"]["type"] == "One Hand Mace"
    assert result["pob_parse"]["item"]["one_hand"] is True
    assert {row["pob_slot"] for row in result["slot_comparisons"]} == {"Weapon 1", "Weapon 2"}

    by_slot = {row["pob_slot"]: row for row in result["slot_comparisons"]}

    weapon_1 = by_slot["Weapon 1"]
    assert weapon_1["baseline"]["primary_skill"]["skill_name"] == "Shield Wall"
    assert weapon_1["candidate"]["primary_skill"]["skill_name"] == "Shield Wall"
    assert weapon_1["candidate"]["item_present"] is True
    outcome_1 = weapon_1["evaluation_outcome"]
    assert outcome_1["evaluation_quality"] == "FULL"
    assert outcome_1["item_impact"]["axes"]["DEFENSE"]["direction"] == "POSITIVE"
    assert outcome_1["verdict"] == "MEANINGFUL_UPGRADE"
    assert weapon_1["restore"]["pass"] is True

    # Weapon 2 would remove the tower shield the main skill depends on: a guardrail
    # forces NOT_VIABLE, never a confident up/downgrade against the unintended slot.
    weapon_2 = by_slot["Weapon 2"]
    outcome_2 = weapon_2["evaluation_outcome"]
    assert outcome_2["verdict"] == "NOT_VIABLE"
    assert "MAIN_SKILL_INVALID" in {g["code"] for g in outcome_2["guardrails_applied"]}
    assert weapon_2["restore"]["pass"] is True

    # The best-slot ranking never surfaces the guardrail-blocked slot as the pick.
    assert result["recommendation"]["pob_slot"] == "Weapon 1"


def test_onehand_weapon_repeated_evaluation_does_not_leak_state(real_pob_engine) -> None:
    baseline_item = _equipped_item(ONEHAND_BUILD, "Weapon 1")
    candidate = baseline_item + "\n+300 to maximum Life\n"

    first = evaluate_item(candidate, real_pob_engine, build_path=str(ONEHAND_BUILD))
    second = evaluate_item(candidate, real_pob_engine, build_path=str(ONEHAND_BUILD))

    for slot in ("Weapon 1", "Weapon 2"):
        first_row = next(row for row in first["slot_comparisons"] if row["pob_slot"] == slot)
        second_row = next(row for row in second["slot_comparisons"] if row["pob_slot"] == slot)
        assert first_row["evaluation_outcome"]["final_score"] == second_row["evaluation_outcome"]["final_score"]
        assert first_row["evaluation_outcome"]["verdict"] == second_row["evaluation_outcome"]["verdict"]
        assert first_row["restore"]["pass"] is True
        assert second_row["restore"]["pass"] is True

    assert first["recommendation"]["pob_slot"] == second["recommendation"]["pob_slot"] == "Weapon 1"


POISON_BUILD = ROOT / "fixtures" / "builds" / "public_corpus" / "core04_poison_ailment.xml"


def test_poison_ailment_dominant_offense_is_selected_and_measured(real_pob_engine) -> None:
    """CORE04-POISON-AILMENT: a real Huntress/Ritualist build whose damage is poison, not hit.

    Poisonburst Arrow's selected stat set ("Poison Burst") reports PoB's own hit DPS
    (TotalDPS) as a small fraction of its poison DPS (real PoB baseline for this
    fixture: TotalDPS ~102k vs PoisonDPS ~794k, i.e. poison is ~89% of CombinedDPS).
    `resolve_primary_metric` is expected to pick the dominant ailment field directly
    (`ailments[dominant] > total_hit`) rather than defaulting to hit DPS or the
    combined figure -- selecting hit DPS here would materially understate the real
    offense change from an item that scales physical (poison-source) damage.

    The candidate is the build's own equipped bow plus "200% increased Physical
    Damage" -- physical damage is poison's source damage, so this should move
    PoisonDPS substantially without touching defense. This was verified against a
    real PoB run before writing these assertions (see
    docs/CORPUS_COVERAGE_METHODOLOGY.md, M1.1 DoT/ailment slice): a candidate with
    "increased Damage with Poison" instead was also tried and produced a
    reproducible ZERO change in PoisonDPS at every magnitude tested (100%/300%) --
    that is a PoB-native calculation characteristic of this specific stat set
    ("Bursting Plague"-detonated poison), not an ExileLens defect: ExileLens only
    reads PoB's own recomputed number, it never derives one, and the "increased
    Physical Damage" candidate below proves the pipeline does correctly recompute
    and thread PoisonDPS end to end.
    """
    baseline_item = _equipped_item(POISON_BUILD, "Weapon 1")
    candidate = baseline_item + "\n200% increased Physical Damage\n"
    result = evaluate_item(candidate, real_pob_engine, build_path=str(POISON_BUILD))

    assert result["pob_parse"]["item"]["type"] == "Bow"
    assert {row["pob_slot"] for row in result["slot_comparisons"]} == {"Weapon 1"}

    row = result["slot_comparisons"][0]
    assert row["baseline"]["primary_skill"]["skill_name"] == "Poisonburst Arrow"
    assert row["candidate"]["primary_skill"]["skill_name"] == "Poisonburst Arrow"
    assert row["candidate"]["item_present"] is True

    baseline_metric = row["baseline_primary_metric"]
    assert baseline_metric["pob_field"] == "PoisonDPS"
    assert baseline_metric["selected"] == "DOT_DPS"
    assert baseline_metric["semantic_quantity"] == "AILMENT_DPS"
    assert baseline_metric["ailment"] == "POISON"

    outcome = row["evaluation_outcome"]
    offense = outcome["item_impact"]["axes"]["OFFENSE"]
    assert offense["direction"] == "POSITIVE"
    assert offense["support"] == "MEASURED"
    assert offense["magnitude_pct"] > 40.0
    # Ailment-dominant offense keeps a truthful, cautious classification: a real,
    # correctly measured and directionally right change still does not earn FULL
    # quality or a confident directional verdict for this mechanic today.
    assert outcome["evaluation_quality"] == "PARTIAL"
    assert outcome["verdict"] == "UNCERTAIN"

    assert row["restore"]["pass"] is True
    assert result["recommendation"]["pob_slot"] == "Weapon 1"


def test_poison_ailment_repeated_evaluation_does_not_leak_state(real_pob_engine) -> None:
    baseline_item = _equipped_item(POISON_BUILD, "Weapon 1")
    candidate = baseline_item + "\n200% increased Physical Damage\n"

    first = evaluate_item(candidate, real_pob_engine, build_path=str(POISON_BUILD))
    second = evaluate_item(candidate, real_pob_engine, build_path=str(POISON_BUILD))

    first_row = first["slot_comparisons"][0]
    second_row = second["slot_comparisons"][0]
    assert first_row["baseline_primary_metric"]["pob_field"] == second_row["baseline_primary_metric"]["pob_field"] == "PoisonDPS"
    assert first_row["evaluation_outcome"]["final_score"] == second_row["evaluation_outcome"]["final_score"]
    assert first_row["evaluation_outcome"]["verdict"] == second_row["evaluation_outcome"]["verdict"]
    assert first_row["restore"]["pass"] is True
    assert second_row["restore"]["pass"] is True
