"""Small strategic Item Check validation suite using only public fixtures."""

from __future__ import annotations

import math
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


MIXED_BUILD = ROOT / "fixtures" / "builds" / "public_corpus" / "core04_mixed_hit_ailment.xml"


def test_mixed_hit_and_ailment_offense_selects_combined_dps(real_pob_engine) -> None:
    """CORE04-MIXED-HIT-AILMENT: a real build where hit AND ignite both matter.

    Witch/Infernalist "Comet" (triggered by Cast on Elemental Ailment): real PoB
    baseline for this fixture splits almost evenly between hit and ignite --
    TotalDPS ~545k, IgniteDPS ~387k, CombinedDPS ~932k (~59%/41% hit/ignite split;
    neither component is negligible, and neither dominates the other the way the
    poison-ailment fixture's ailment dominates its hit). Selecting only TotalDPS
    would understate real offense by ~41%; selecting only IgniteDPS would
    understate it by ~59% and get the direction of "which slot/skill this even
    measures" wrong. `resolve_primary_metric` is expected to land in its
    `ailments[dominant] > total_hit` check as False (ignite does not dominate hit
    here) and fall through to PoB's own already-summed `CombinedDPS`
    (`DamageQuantity.HIT_PLUS_AILMENT`), not either isolated component.

    The candidate is the build's own equipped Focus (offhand, Weapon 2) plus one
    added "60% increased Spell Damage" line -- spell damage scales both the
    Comet hit and the ignite it applies, so it should move TotalDPS, IgniteDPS,
    and CombinedDPS together, proportionally. Verified against a real PoB run
    before writing these assertions (see docs/CORPUS_COVERAGE_METHODOLOGY.md,
    M1.1 mixed hit+ailment slice): +9.69% on all three simultaneously, and
    CombinedDPS equals TotalDPS + IgniteDPS exactly in both baseline and
    candidate (no double counting).
    """
    baseline_item = _equipped_item(MIXED_BUILD, "Weapon 2")
    candidate = baseline_item + "\n60% increased Spell Damage\n"
    result = evaluate_item(candidate, real_pob_engine, build_path=str(MIXED_BUILD))

    assert result["pob_parse"]["item"]["type"] == "Focus"
    assert {row["pob_slot"] for row in result["slot_comparisons"]} == {"Weapon 2"}

    row = result["slot_comparisons"][0]
    assert row["baseline"]["primary_skill"]["skill_name"] == "Comet"
    assert row["candidate"]["primary_skill"]["skill_name"] == "Comet"
    assert row["candidate"]["item_present"] is True

    baseline_metric = row["baseline_primary_metric"]
    assert baseline_metric["pob_field"] == "CombinedDPS"
    assert baseline_metric["selected"] == "PRIMARY_DPS"
    assert baseline_metric["semantic_quantity"] == "HIT_PLUS_AILMENT"

    baseline_metrics = row["evaluation_outcome"]["baseline_metrics"]
    candidate_metrics = row["evaluation_outcome"]["candidate_metrics"]
    assert math.isclose(
        baseline_metrics["TotalDPS"] + baseline_metrics["IgniteDPS"], baseline_metrics["CombinedDPS"], rel_tol=1e-9
    )
    assert math.isclose(
        candidate_metrics["TotalDPS"] + candidate_metrics["IgniteDPS"], candidate_metrics["CombinedDPS"], rel_tol=1e-9
    )
    assert candidate_metrics["TotalDPS"] > baseline_metrics["TotalDPS"]
    assert candidate_metrics["IgniteDPS"] > baseline_metrics["IgniteDPS"]

    outcome = row["evaluation_outcome"]
    offense = outcome["item_impact"]["axes"]["OFFENSE"]
    assert offense["direction"] == "POSITIVE"
    assert offense["support"] == "MEASURED"
    assert 5.0 < offense["magnitude_pct"] < 15.0
    assert outcome["evaluation_quality"] == "FULL"
    assert outcome["verdict"] == "MEANINGFUL_UPGRADE"

    assert row["restore"]["pass"] is True
    assert result["recommendation"]["pob_slot"] == "Weapon 2"


def test_mixed_hit_and_ailment_repeated_evaluation_does_not_leak_state(real_pob_engine) -> None:
    baseline_item = _equipped_item(MIXED_BUILD, "Weapon 2")
    candidate = baseline_item + "\n60% increased Spell Damage\n"

    first = evaluate_item(candidate, real_pob_engine, build_path=str(MIXED_BUILD))
    second = evaluate_item(candidate, real_pob_engine, build_path=str(MIXED_BUILD))

    first_row = first["slot_comparisons"][0]
    second_row = second["slot_comparisons"][0]
    assert first_row["baseline_primary_metric"]["pob_field"] == second_row["baseline_primary_metric"]["pob_field"] == "CombinedDPS"
    assert first_row["evaluation_outcome"]["final_score"] == second_row["evaluation_outcome"]["final_score"]
    assert first_row["evaluation_outcome"]["verdict"] == second_row["evaluation_outcome"]["verdict"]
    assert first_row["restore"]["pass"] is True
    assert second_row["restore"]["pass"] is True


WEAPON_SWAP_BUILD = ROOT / "fixtures" / "builds" / "public_corpus" / "core04_weapon_swap.xml"


def test_weapon_swap_baseline_reflects_the_active_second_set(real_pob_engine) -> None:
    """CORE04-WEAPON-SWAP: identity and baseline correctly reflect the active (second) set.

    This build's saved `<ItemSet useSecondWeaponSet="true">` means its TRUE equipped
    weapons are "Weapon 1 Swap" (a bow, "Brood Stinger, Warmonger Bow") and
    "Weapon 2 Swap" (a quiver) -- the PRIMARY "Weapon 1"/"Weapon 2" slots hold an
    unrelated, materially different loadout (a spear + a normal-rarity shield) that
    the player is not actually using. Poisonburst Arrow is an arrow skill: it can
    only produce real damage with a bow equipped, so a non-zero, sensible offense
    output is itself evidence PoB's own calculation is reading the active (swap) set.

    The explicit wrong-set sentinel: the inactive primary spear (Weapon 1) is cloned
    with a massive "+500% increased Physical Damage" mod and evaluated as a
    candidate. This measures a real PoB run and asserts EXACTLY ZERO offense
    change -- proving the calculation the baseline is built from does NOT depend on
    the primary set's weapon at all, i.e. baseline offense (X) is driven by the
    active swap set, not the inactive primary set (Y).

    `Item Check's own equipment summary for logical "Weapon 1"/"Weapon 2" now
    resolves to the ACTIVE physical slot (bow/quiver), not the primary/inactive one
    (spear/shield) -- see runtime/lua/bridge.lua's `active_weapon_slot` (the P0 fix
    for M1.1's weapon-swap slice). See
    test_weapon_swap_candidate_substitution_resolves_the_active_slot for the
    candidate-substitution half of the same fix.
    """
    loaded = real_pob_engine.load_build(WEAPON_SWAP_BUILD)
    assert loaded["build"]["active_item_set_id"] == 1
    assert loaded["build"]["active_loadout"] == "Default"
    identity = loaded["build"]["main_skill_identity"]
    assert identity["skill_name"] == "Poisonburst Arrow"
    assert identity["damage_owner"] == "PLAYER"

    baseline_metrics = loaded["metrics"]
    assert baseline_metrics["TotalDPS"] > 0
    assert baseline_metrics["PoisonDPS"] > 0
    assert baseline_metrics["CombinedDPS"] > 0

    equipment = {row["slot"]: row for row in loaded["equipment"]}
    # Logical "Weapon 1"/"Weapon 2" now correctly name the ACTIVE (swap) items.
    assert equipment["Weapon 1"]["name"] == "Brood Stinger, Warmonger Bow"
    assert equipment["Weapon 2"]["name"] == "Cadiro's Gambit, Primed Quiver"
    # The physical swap slots read the same content (both keys back the same real
    # equipped items) -- confirms the translation, not a coincidence.
    assert equipment["Weapon 1 Swap"]["name"] == "Brood Stinger, Warmonger Bow"
    assert equipment["Weapon 2 Swap"]["name"] == "Cadiro's Gambit, Primed Quiver"

    inactive_spear = _equipped_item(WEAPON_SWAP_BUILD, "Weapon 1")
    sentinel_candidate = inactive_spear + "\n500% increased Physical Damage\n"
    result = evaluate_item(sentinel_candidate, real_pob_engine, build_path=str(WEAPON_SWAP_BUILD))
    row = result["slot_comparisons"][0]
    outcome = row["evaluation_outcome"]
    # The sentinel: a huge damage buff on the INACTIVE set's weapon, submitted as a
    # candidate for logical "Weapon 1", is now correctly recognized as replacing the
    # build's real active bow with an arrow-incompatible weapon -- PoB's guardrail
    # policy correctly refuses this as NOT_VIABLE (Poisonburst Arrow cannot fire
    # without a bow) rather than silently reporting a neutral/no-op SIDEGRADE.
    assert outcome["item_impact"]["axes"]["OFFENSE"]["support"] == "UNMEASURED"
    assert outcome["evaluation_quality"] == "PARTIAL"
    assert outcome["verdict"] == "NOT_VIABLE"
    assert row["restore"]["pass"] is True

    reloaded = real_pob_engine.load_build(WEAPON_SWAP_BUILD)
    assert reloaded["build"]["active_item_set_id"] == 1
    assert reloaded["build"]["active_loadout"] == "Default"
    assert reloaded["build"]["main_skill_identity"]["skill_name"] == "Poisonburst Arrow"
    reloaded_equipment = {row["slot"]: row for row in reloaded["equipment"]}
    assert reloaded_equipment["Weapon 1"]["name"] == "Brood Stinger, Warmonger Bow"
    assert reloaded_equipment["Weapon 2"]["name"] == "Cadiro's Gambit, Primed Quiver"


def test_weapon_swap_candidate_substitution_resolves_the_active_slot(real_pob_engine) -> None:
    """CORE04-WEAPON-SWAP P0 fix: candidate substitution now targets the active slot.

    Before the fix (see git history / docs/CORE_04_ITEM_CHECK_COVERAGE_MATRIX.md risk
    register), a candidate cloned from this build's TRUE active bow, evaluated
    against logical "Weapon 1", produced EXACTLY ZERO measured offense change -- a
    confident FULL/SIDEGRADE result silently disconnected from the real active
    equipment, because candidate substitution always wrote into the PRIMARY
    "Weapon 1" PoB slot instead of the active "Weapon 1 Swap" slot.

    Root cause and fix: `runtime/lua/bridge.lua` now resolves every read/write of
    logical "Weapon 1"/"Weapon 2" through `active_weapon_slot`, which redirects to
    the " Swap" physical slot exactly when `itemsTab.activeItemSet.useSecondWeaponSet`
    is true -- mirroring PoB's own CalcSetup.lua redirection, so ExileLens never
    needs its own notion of "which weapon set". This test proves the fix end to end
    against real PoB output (+148.88% measured before this assertion was written):
    the candidate reaches the slot that actually drives the calculation, the
    baseline item is the true active bow (not the inactive spear), the primary
    (inactive) set is never mutated, and restore is exact -- including
    `useSecondWeaponSet` itself, which this transaction never touches.
    """
    swap_bow = _equipped_item(WEAPON_SWAP_BUILD, "Weapon 1 Swap")
    candidate = swap_bow + "\n500% increased Physical Damage\n"

    result = evaluate_item(candidate, real_pob_engine, build_path=str(WEAPON_SWAP_BUILD))

    assert {row["pob_slot"] for row in result["slot_comparisons"]} == {"Weapon 1"}
    row = result["slot_comparisons"][0]

    # 1-2: the candidate resolved against the ACTIVE bow baseline, not the inactive spear.
    assert row["baseline_item"]["name"] == "Brood Stinger, Warmonger Bow"
    assert row["baseline_item"]["name"] != "Hunter's Grand Spear of the Mongoose"
    assert row["baseline"]["primary_skill"]["skill_name"] == "Poisonburst Arrow"
    assert row["candidate"]["primary_skill"]["skill_name"] == "Poisonburst Arrow"
    assert row["candidate"]["item_present"] is True

    # 3-5: meaningful, real-PoB-consistent candidate delta and truthful classification.
    outcome = row["evaluation_outcome"]
    offense = outcome["item_impact"]["axes"]["OFFENSE"]
    assert offense["support"] == "MEASURED"
    assert offense["direction"] == "POSITIVE"
    assert offense["magnitude_pct"] > 100.0
    assert outcome["evaluation_quality"] == "FULL"
    assert outcome["verdict"] == "MEANINGFUL_UPGRADE"

    # 6: the inactive primary set was never touched by this transaction.
    reloaded = real_pob_engine.load_build(WEAPON_SWAP_BUILD)
    equipment_after = {e["slot"]: e.get("name") for e in reloaded["equipment"]}
    # The spear/shield are no longer exposed under logical "Weapon 1"/"Weapon 2" (those
    # now correctly mean "active"), but they must still be exactly what they were,
    # untouched, in the raw build XML this fixture never gets rewritten from.
    inactive_spear_raw = _equipped_item(WEAPON_SWAP_BUILD, "Weapon 1")
    inactive_shield_raw = _equipped_item(WEAPON_SWAP_BUILD, "Weapon 2")
    assert "Hunter's Grand Spear of the Mongoose" in inactive_spear_raw
    assert "Exceptional Glowering Crest Shield" in inactive_shield_raw

    # 7-8: restore is exact -- both sets, active-set selection, and skill identity.
    assert row["restore"]["pass"] is True
    assert equipment_after["Weapon 1"] == "Brood Stinger, Warmonger Bow"
    assert equipment_after["Weapon 2"] == "Cadiro's Gambit, Primed Quiver"
    assert reloaded["build"]["active_item_set_id"] == 1
    assert reloaded["build"]["active_loadout"] == "Default"
    assert reloaded["build"]["main_skill_identity"]["skill_name"] == "Poisonburst Arrow"

    # 9: repeated evaluation is stable (no state leak, no cache/fingerprint staleness).
    second = evaluate_item(candidate, real_pob_engine, build_path=str(WEAPON_SWAP_BUILD))
    second_row = second["slot_comparisons"][0]
    assert second_row["baseline_item"]["name"] == "Brood Stinger, Warmonger Bow"
    assert second_row["evaluation_outcome"]["final_score"] == outcome["final_score"]
    assert second_row["evaluation_outcome"]["verdict"] == outcome["verdict"]
    assert second_row["restore"]["pass"] is True


SKILL_NATIVE_DOT_BUILD = ROOT / "fixtures" / "builds" / "public_corpus" / "core04_skill_native_dot.xml"


def test_skill_native_dot_offense_is_selected_and_measured(real_pob_engine) -> None:
    """CORE04-SKILL-NATIVE-DOT: a real build whose offense IS its own DoT, not an ailment.

    Monk/Acolyte of Chayula "Profane Ritual" (triggered by Cast on Minion Death): real
    PoB baseline for this fixture has zero hit DPS and zero named-ailment DPS at all
    (no Ignite/Poison/Bleed field present) -- TotalDPS=0, TotalDot~933, CombinedDPS
    exactly equals TotalDot. This is genuinely different from the two other DoT/
    ailment fixtures already in this corpus: core04_poison_ailment.xml has a real
    ailment (PoisonDPS) dominating a nonzero hit, and core04_mixed_hit_ailment.xml has
    meaningful hit AND ailment together (CombinedDPS = hit + ignite). Here there is no
    ailment field at all -- the skill's own damage-over-time output (PoB's TotalDot)
    IS the offense, full stop.

    `resolve_primary_metric` is expected to select PoB's own `TotalDot` field directly
    (OffenseKind.DOT_DPS, DamageQuantity.SKILL_DOT) -- not fall back to TotalDPS (0,
    would silently report no offense at all), not substitute a named ailment field
    (none exists), and not double-count through CombinedDPS (which must equal TotalDot
    exactly here, not TotalDot plus something else). Note on implementation: for a
    build with zero raw hit DPS, the resolver's "hit" variable falls back to
    `combined` before the dominance check runs, so this case is actually satisfied by
    the earlier "DoT dominates hit" branch rather than the separate "hit <= 0" branch
    later in the function -- both produce the identical TotalDot/SKILL_DOT selection,
    confirmed here against real PoB output rather than assumed from reading the code.

    The candidate is the build's own equipped Sceptre (Weapon 1) cloned with one added
    "100% increased Damage over Time" line -- a generic DoT-scaling modifier that
    should move TotalDot specifically. Verified against a real PoB run before writing
    these assertions (see docs/CORPUS_COVERAGE_METHODOLOGY.md, M1.1 skill-native-DoT
    slice): TotalDot 933.41 -> 1698.50 (+81.97%), CombinedDPS moves identically and
    stays exactly equal to TotalDot throughout (no double counting), FullDotDPS stays
    0 (the AGGREGATE alternative field is correctly not involved), FULL quality,
    MEANINGFUL_UPGRADE verdict.
    """
    baseline_item = _equipped_item(SKILL_NATIVE_DOT_BUILD, "Weapon 1")
    candidate = baseline_item + "\n100% increased Damage over Time\n"
    result = evaluate_item(candidate, real_pob_engine, build_path=str(SKILL_NATIVE_DOT_BUILD))

    # This Sceptre is legally compatible with both Weapon 1 and Weapon 2 (an
    # AMBIGUOUS_WEAPON_LAYOUT case already covered by the one-hand-weapon slice, not
    # this test's concern) -- select the Weapon 1 row explicitly.
    row = next(r for r in result["slot_comparisons"] if r["pob_slot"] == "Weapon 1")
    assert row["baseline"]["primary_skill"]["skill_name"] == "Profane Ritual"
    assert row["candidate"]["primary_skill"]["skill_name"] == "Profane Ritual"
    assert row["candidate"]["item_present"] is True

    baseline_metric = row["baseline_primary_metric"]
    assert baseline_metric["pob_field"] == "TotalDot"
    assert baseline_metric["selected"] == "DOT_DPS"
    assert baseline_metric["semantic_quantity"] == "SKILL_DOT"
    assert baseline_metric["ailment"] == ""

    baseline_metrics = row["evaluation_outcome"]["baseline_metrics"]
    candidate_metrics = row["evaluation_outcome"]["candidate_metrics"]
    assert baseline_metrics["TotalDPS"] == 0
    assert baseline_metrics["TotalDot"] > 0
    assert baseline_metrics["CombinedDPS"] == baseline_metrics["TotalDot"]
    assert baseline_metrics.get("FullDotDPS", 0) == 0
    assert candidate_metrics["TotalDot"] > baseline_metrics["TotalDot"]
    assert candidate_metrics["CombinedDPS"] == candidate_metrics["TotalDot"]
    assert candidate_metrics.get("FullDotDPS", 0) == 0

    outcome = row["evaluation_outcome"]
    offense = outcome["item_impact"]["axes"]["OFFENSE"]
    assert offense["support"] == "MEASURED"
    assert offense["direction"] == "POSITIVE"
    assert offense["magnitude_pct"] > 50.0
    assert outcome["evaluation_quality"] == "FULL"
    assert outcome["verdict"] == "MEANINGFUL_UPGRADE"

    assert row["restore"]["pass"] is True


def test_skill_native_dot_repeated_evaluation_does_not_leak_state(real_pob_engine) -> None:
    baseline_item = _equipped_item(SKILL_NATIVE_DOT_BUILD, "Weapon 1")
    candidate = baseline_item + "\n100% increased Damage over Time\n"

    first = evaluate_item(candidate, real_pob_engine, build_path=str(SKILL_NATIVE_DOT_BUILD))
    second = evaluate_item(candidate, real_pob_engine, build_path=str(SKILL_NATIVE_DOT_BUILD))
    first_row = next(r for r in first["slot_comparisons"] if r["pob_slot"] == "Weapon 1")
    second_row = next(r for r in second["slot_comparisons"] if r["pob_slot"] == "Weapon 1")

    assert first_row["baseline_primary_metric"]["pob_field"] == second_row["baseline_primary_metric"]["pob_field"] == "TotalDot"
    assert first_row["evaluation_outcome"]["final_score"] == second_row["evaluation_outcome"]["final_score"]
    assert first_row["evaluation_outcome"]["verdict"] == second_row["evaluation_outcome"]["verdict"]
    assert first_row["restore"]["pass"] is True
    assert second_row["restore"]["pass"] is True
