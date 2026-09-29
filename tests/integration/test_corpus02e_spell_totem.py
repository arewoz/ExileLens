"""CORPUS-02E: proxy/totem coverage on an authentic Spell Totem build.

Fixture ``corpus02e_spell_totem_titan.xml`` is a public poe.ninja ladder character
(Warrior / Titan, level 100) whose selected socket group is the **Spell Totem** meta
skill: the totem, not the player, casts Grim Pillars. PoB calculates the totem's
per-cast damage and cast rate on the player's main output, so Item Check measures the
candidate with PoB's own numbers. See docs/CORPUS-02E.md.

Every numeric expectation is checked against an independent fresh PoB load of the same
build with the candidate item equipped in its slot -- never against ExileLens's own
scoring. Candidates are hand-written rare amulets in the equipped amulet's own shape.
"""

from __future__ import annotations

import math
import re
from pathlib import Path
from xml.sax.saxutils import escape

import pytest

from exilelens.items.evaluation import evaluate_item

ROOT = Path(__file__).resolve().parents[2]
BUILD = ROOT / "fixtures" / "builds" / "public_corpus" / "corpus02e_spell_totem_titan.xml"
pytestmark = [pytest.mark.integration, pytest.mark.real_pob, pytest.mark.itemcheck]

AMULET = """Rarity: RARE
Test Torc
Absent Amulet
Item Level: 79
LevelReq: 50
Implicits: 4
{{enchant}}Allocates Efficient Inscriptions
-1 Prefix Modifier allowed
-1 Suffix Modifier allowed
Grants Skill: Level 17 Archmage
{mods}"""
BASELINE_MODS = "+64 to maximum Energy Shield\n+5 to Level of all Spell Skills\n+42% to Fire Resistance\n+60 to Spirit"
CANDIDATES = {
    "levels_up": "+64 to maximum Energy Shield\n+7 to Level of all Spell Skills\n+42% to Fire Resistance\n+60 to Spirit",
    "levels_down": "+64 to maximum Energy Shield\n+3 to Level of all Spell Skills\n+42% to Fire Resistance\n+60 to Spirit",
    "es_only": "+164 to maximum Energy Shield\n+5 to Level of all Spell Skills\n+42% to Fire Resistance\n+60 to Spirit",
    "cast_speed": "+64 to maximum Energy Shield\n+5 to Level of all Spell Skills\n+42% to Fire Resistance\n20% increased Cast Speed",
    "tradeoff": "+6 to Level of all Spell Skills\n+10 to maximum Energy Shield\n-20% to Cold Resistance\n+42% to Fire Resistance",
}
FIELDS = ("TotalDPS", "Speed", "EnergyShield", "Life", "TotalEHP", "ColdResist")


def _amulet(name: str) -> str:
    return AMULET.format(mods=CANDIDATES[name])


def _variant(tmp_path: Path, name: str, raw: str) -> Path:
    """The build as the player would save it with ``raw`` equipped as the amulet."""
    text = BUILD.read_text(encoding="utf-8")
    text = text.replace("\t\t<ItemSet ", f'\t\t<Item id="900">\n{escape(raw)}\n\t\t</Item>\n\t\t<ItemSet ', 1)
    text, count = re.subn(r'(<Slot itemId=")\d+(" itemPbURL="" name="Amulet"/>)', r"\g<1>900\g<2>", text)
    assert count == 1
    path = tmp_path / f"{name}.xml"
    path.write_text(text, encoding="utf-8")
    return path


def _fresh(engine, path: Path) -> dict:
    engine.load_build(path)
    return engine.get_metrics()["raw"]


def _row(result: dict, slot: str = "Amulet") -> dict:
    return next(row for row in result["slot_comparisons"] if row["pob_slot"] == slot)


def _close(actual, expected) -> bool:
    return math.isclose(float(actual), float(expected), rel_tol=1e-6, abs_tol=1e-6)


def _assert_matches_fresh_load(engine, tmp_path: Path, name: str, row: dict) -> dict:
    reference = _fresh(engine, _variant(tmp_path, name, _amulet(name)))
    for field in FIELDS:
        assert _close(row["candidate"]["metrics"][field], reference[field]), (name, field)
    return reference


# --------------------------------------------------------------------------- identity and mechanics


def test_spell_totem_group_is_the_selected_player_calculation(real_pob_engine) -> None:
    """The totem's spell is the selected effect; PoB reports it on the player's output."""
    loaded = real_pob_engine.load_build(BUILD)
    identity = loaded["build"]["main_skill_identity"]
    assert identity["skill_name"] == "Grim Pillars" and identity["damage_owner"] == "PLAYER"
    assert identity["index"] == 5 and identity["gems"][0] == "Spell Totem"
    assert identity["calculation_mode"] == "DIRECT"
    effects = {e["name"]: e for e in loaded["build"]["effect_catalog"]["effects"]}
    assert effects["Grim Pillars"]["selected"] is True
    # The meta skill and the second linked spell are calculated but deal no damage of their own.
    assert effects["Spell Totem"]["output"]["TotalDPS"] == 0 and effects["Bitter Dead"]["output"]["TotalDPS"] == 0

    metrics = real_pob_engine.get_metrics()["raw"]
    # PoB: per-cast damage x the totem's cast rate. CombinedDPS is the per-cast damage
    # here, so ExileLens must (and does) score TotalDPS, the actual damage per second.
    assert _close(metrics["TotalDPS"], metrics["CombinedDPS"] * metrics["Speed"])
    assert metrics["TotalDPS"] > 2 * metrics["CombinedDPS"]


# --------------------------------------------------------------------------- FULL verdicts, checked against fresh loads


def test_genuine_offense_upgrade_is_a_full_verdict(real_pob_engine, tmp_path: Path) -> None:
    result = evaluate_item(_amulet("levels_up"), real_pob_engine, build_path=str(BUILD))
    row = _row(result)
    outcome = row["evaluation_outcome"]
    assert result["primary_metric"]["pob_field"] == "TotalDPS"
    assert outcome["evaluation_quality"] == "FULL" and outcome["verdict"] == "MEANINGFUL_UPGRADE"
    reference = _assert_matches_fresh_load(real_pob_engine, tmp_path, "levels_up", row)
    assert reference["TotalDPS"] > row["baseline"]["metrics"]["TotalDPS"]
    assert outcome["item_impact"]["axes"]["OFFENSE"]["direction"] == "POSITIVE"
    assert row["restore"]["pass"] is True


def test_genuine_offense_downgrade_is_a_full_verdict(real_pob_engine, tmp_path: Path) -> None:
    result = evaluate_item(_amulet("levels_down"), real_pob_engine, build_path=str(BUILD))
    row = _row(result)
    outcome = row["evaluation_outcome"]
    assert outcome["evaluation_quality"] == "FULL" and outcome["verdict"] == "MEANINGFUL_DOWNGRADE"
    reference = _assert_matches_fresh_load(real_pob_engine, tmp_path, "levels_down", row)
    assert reference["TotalDPS"] < row["baseline"]["metrics"]["TotalDPS"]
    assert outcome["item_impact"]["axes"]["OFFENSE"]["direction"] == "NEGATIVE"


def test_defense_only_item_improves_the_player_without_inventing_offense(real_pob_engine, tmp_path: Path) -> None:
    result = evaluate_item(_amulet("es_only"), real_pob_engine, build_path=str(BUILD))
    row = _row(result)
    outcome = row["evaluation_outcome"]
    assert outcome["evaluation_quality"] == "FULL" and outcome["verdict"] in {"MINOR_UPGRADE", "MEANINGFUL_UPGRADE"}
    reference = _assert_matches_fresh_load(real_pob_engine, tmp_path, "es_only", row)
    baseline = row["baseline"]["metrics"]
    # PoB: the totem's damage and cast rate are untouched; only the player's ES and EHP move.
    assert _close(reference["TotalDPS"], baseline["TotalDPS"]) and _close(reference["Speed"], baseline["Speed"])
    assert reference["EnergyShield"] > baseline["EnergyShield"] and reference["TotalEHP"] > baseline["TotalEHP"]
    axes = outcome["item_impact"]["axes"]
    assert axes["DEFENSE"]["direction"] == "POSITIVE" and axes["OFFENSE"]["direction"] != "POSITIVE"


def test_player_cast_speed_reaches_the_totems_cast_rate_as_pob_calculates_it(real_pob_engine, tmp_path: Path) -> None:
    result = evaluate_item(_amulet("cast_speed"), real_pob_engine, build_path=str(BUILD))
    row = _row(result)
    assert row["evaluation_outcome"]["evaluation_quality"] == "FULL"
    assert row["evaluation_outcome"]["verdict"] == "MEANINGFUL_UPGRADE"
    reference = _assert_matches_fresh_load(real_pob_engine, tmp_path, "cast_speed", row)
    baseline = row["baseline"]["metrics"]
    # PoB scales the totem's cast rate; per-cast damage is unchanged, so DPS follows Speed exactly.
    assert reference["Speed"] > baseline["Speed"]
    assert _close(reference["TotalDPS"] / baseline["TotalDPS"], reference["Speed"] / baseline["Speed"])


def test_offense_gain_with_a_lost_resistance_cap_is_a_flagged_tradeoff(real_pob_engine, tmp_path: Path) -> None:
    result = evaluate_item(_amulet("tradeoff"), real_pob_engine, build_path=str(BUILD))
    row = _row(result)
    outcome = row["evaluation_outcome"]
    reference = _assert_matches_fresh_load(real_pob_engine, tmp_path, "tradeoff", row)
    baseline = row["baseline"]["metrics"]
    assert reference["TotalDPS"] > baseline["TotalDPS"] * 1.10 and reference["TotalEHP"] < baseline["TotalEHP"]
    assert baseline["ColdResist"] == 75 and reference["ColdResist"] < 75
    assert outcome["evaluation_quality"] == "FULL"
    assert outcome["item_impact"]["pattern"] == "TRADEOFF"
    assert {g["code"] for g in outcome["guardrails_applied"]} == {"RES_CAP_LOST"}
    # A large offense gain does not hide the cap loss: never an upgrade.
    assert outcome["verdict"] == "MINOR_DOWNGRADE"


# --------------------------------------------------------------------------- repeatability and restore


def test_repeated_evaluations_are_identical_and_restore_the_build(real_pob_engine) -> None:
    real_pob_engine.load_build(BUILD)
    original_hash = real_pob_engine.get_metrics()["fingerprint_hash"]
    original_equipment = real_pob_engine.get_equipment()

    first = evaluate_item(_amulet("levels_up"), real_pob_engine, build_path=str(BUILD))
    evaluate_item(_amulet("tradeoff"), real_pob_engine, build_path=str(BUILD))
    second = evaluate_item(_amulet("levels_up"), real_pob_engine, build_path=str(BUILD))

    a, b = _row(first), _row(second)
    assert a["evaluation_outcome"]["evaluation_quality"] == "FULL" and b["evaluation_outcome"]["evaluation_quality"] == "FULL"
    assert a["evaluation_outcome"]["verdict"] == b["evaluation_outcome"]["verdict"]
    assert a["evaluation_outcome"]["final_score"] == b["evaluation_outcome"]["final_score"]
    assert a["candidate"]["metrics"]["TotalDPS"] == b["candidate"]["metrics"]["TotalDPS"]
    assert a["restore"]["pass"] is True and b["restore"]["pass"] is True
    assert real_pob_engine.get_metrics()["fingerprint_hash"] == original_hash
    assert real_pob_engine.get_equipment() == original_equipment
