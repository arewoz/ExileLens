"""TRUST-01A: candidate-own equipability proven against real PoB.

Uses the authentic level-98 Acolyte public build (low Strength). The candidates are the equipped
amulet with a higher LevelReq, and a Strength body armour whose own requirement the character cannot meet.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from exilelens.items.evaluation import evaluate_item

ROOT = Path(__file__).resolve().parents[2]
BUILD = ROOT / "fixtures" / "builds" / "public_corpus" / "corpus02g_dex_int_acolyte_hand_of_wisdom.xml"
pytestmark = [pytest.mark.integration, pytest.mark.real_pob, pytest.mark.itemcheck]

AMULET = """Rarity: RARE
Morbid Heart
Amber Amulet
Item Level: 82
LevelReq: {level}
Implicits: 1
+21 to Strength
+500 to maximum Energy Shield"""

PLATE = """Rarity: RARE
Doom Shell
Glorious Plate
Item Level: 82
Implicits: 0
400% increased Attribute Requirements
+400 to maximum Energy Shield
+300 to maximum Life"""


def _row(result: dict, slot: str) -> dict:
    return next(row for row in result["slot_comparisons"] if row["pob_slot"] == slot)


def test_item_requirement_and_character_level_come_from_pob(real_pob_engine) -> None:
    real_pob_engine.load_build(BUILD)
    parsed = real_pob_engine.parse_item(PLATE)
    # 121 * (1 + 400%): PoB applies the item's own local requirement mod.
    assert parsed["item"]["req_str"] == 605
    assert parsed["item"]["req_dex"] == 0 and parsed["item"]["req_int"] == 0
    assert parsed["item"]["level_req"] >= 65
    metrics = real_pob_engine.get_metrics()["raw"]
    assert metrics["CharacterLevel"] == 98


def test_level_requirement_one_above_character_is_not_viable(real_pob_engine) -> None:
    ok = _row(evaluate_item(AMULET.format(level=98), real_pob_engine, build_path=str(BUILD)), "Amulet")
    assert ok["equipability"]["status"] != "NOT_EQUIPPABLE"
    assert "EQUIP_REQUIREMENT_NOT_MET" not in {g["code"] for g in ok["evaluation_outcome"]["guardrails_applied"]}

    row = _row(evaluate_item(AMULET.format(level=99), real_pob_engine, build_path=str(BUILD)), "Amulet")
    outcome = row["evaluation_outcome"]
    assert outcome["verdict"] == "NOT_VIABLE"
    assert row["equipability"]["blocking_reasons"] == ["Requires level 99 · Character is level 98"]
    assert [g["code"] for g in outcome["guardrails_applied"]] == ["EQUIP_REQUIREMENT_NOT_MET"]


def test_strength_requirement_above_character_is_not_viable_despite_big_gain(real_pob_engine) -> None:
    result = evaluate_item(PLATE, real_pob_engine, build_path=str(BUILD))
    row = _row(result, "Body Armour")
    strength = next(c for c in row["equipability"]["checks"] if c["kind"] == "strength")
    assert strength["status"] == "FAIL" and strength["required"] == 605 and strength["available"] < 605
    outcome = row["evaluation_outcome"]
    assert outcome["verdict"] == "NOT_VIABLE"
    assert outcome["guardrails_applied"][0]["reason"] == f"Requires 605 Strength · Character has {int(strength['available'])}"
