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
