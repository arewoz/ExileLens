"""CORPUS-02G: attribute stacking on two authentic public builds.

``corpus02g_strength_oracle_brutus.xml`` (Druid / Oracle, level 99, Chaos Inoculation): dual wielded
Brutus' Lead Sprinkler maces ("5 to 10 Added Attack Fire Damage per 25 Strength") and about
1,900 Strength. ``corpus02g_dex_int_acolyte_hand_of_wisdom.xml`` (Acolyte of Chayula, level 98):
Astramentis and Hand of Wisdom and Action ("1% increased Attack Speed per 20 Dexterity", "Adds
1 to 12 Lightning Damage to Attacks per 20 Intelligence"). See docs/CORPUS-02G.md.

Every numeric expectation is checked against an independent fresh PoB load of the same build
with the candidate equipped in its slot, never against ExileLens's own scoring. Candidates are
the equipped amulet with individual lines changed.
"""

from __future__ import annotations

import math
import re
from pathlib import Path
from xml.sax.saxutils import escape

import pytest

from exilelens.items.evaluation import evaluate_item

ROOT = Path(__file__).resolve().parents[2]
CORPUS = ROOT / "fixtures" / "builds" / "public_corpus"
STRENGTH = CORPUS / "corpus02g_strength_oracle_brutus.xml"
DEX_INT = CORPUS / "corpus02g_dex_int_acolyte_hand_of_wisdom.xml"
pytestmark = [pytest.mark.integration, pytest.mark.real_pob, pytest.mark.itemcheck]

FIELDS = ("TotalDPS", "CombinedDPS", "Speed", "Life", "EnergyShield", "TotalEHP", "Str", "Dex", "Int", "ReqStr")

STR_AMULET = """Rarity: RARE
Morbid Heart
Amber Amulet
Item Level: 82
LevelReq: 65
Implicits: 2
{{enchant}}Allocates Careful Assassin
+21 to Strength
+33 to all Attributes
+86 to maximum Energy Shield
36% increased maximum Energy Shield
{flat}
{inc}
23% increased Global Armour, Evasion and Energy Shield
{extra}"""


def _str_amulet(flat: str = "+44 to Strength", inc: str = "14% increased Strength", extra: str = "", es: str = "") -> str:
    text = STR_AMULET.format(flat=flat, inc=inc, extra=extra)
    if es:
        text = text.replace("+86 to maximum Energy Shield", es)
    return text.rstrip("\n")


STR_CANDIDATES = {
    "str_more": _str_amulet(flat="+84 to Strength"),
    "str_less": _str_amulet(flat="+4 to Strength"),
    "flat_high": _str_amulet(flat="+150 to Strength"),
    "inc_high": _str_amulet(inc="70% increased Strength"),
    "step_below": _str_amulet(flat="+7 to Strength"),
    "step_above": _str_amulet(flat="+10 to Strength"),
    "es_only": _str_amulet(es="+386 to maximum Energy Shield"),
    "tradeoff": _str_amulet(flat="+150 to Strength", extra="-60% to Cold Resistance"),
    "requirement": _str_amulet(flat="-1700 to Strength"),
}

DI_AMULET = """Rarity: UNIQUE
Astramentis
Stellar Amulet
Item Level: 81
LevelReq: 24
Implicits: 2
{{enchant}}Allocates Zarokh's Gift
+8 to all Attributes
{attrs}
-4 Physical Damage taken from Attack Hits
{extra}"""


def _di_amulet(attrs: str = "+123 to all Attributes", extra: str = "") -> str:
    return DI_AMULET.format(attrs=attrs, extra=extra).rstrip("\n")


DI_CANDIDATES = {
    "attrs_more": _di_amulet("+183 to all Attributes"),
    "attrs_less": _di_amulet("+3 to all Attributes"),
    "attrs_less_more_es": _di_amulet("+63 to all Attributes", extra="+150 to maximum Energy Shield"),
    "es_only": _di_amulet(extra="+300 to maximum Energy Shield"),
}


# --------------------------------------------------------------------------- helpers


def _variant(base: Path, tmp_path: Path, name: str, raw: str, slot: str = "Amulet") -> Path:
    """The build as the player would save it with ``raw`` equipped in ``slot``."""
    text = base.read_text(encoding="utf-8")
    text = text.replace("\t\t<ItemSet ", f'\t\t<Item id="900">\n{escape(raw)}\n\t\t</Item>\n\t\t<ItemSet ', 1)
    text, count = re.subn(rf'(<Slot itemId=")\d+(" itemPbURL="" name="{re.escape(slot)}"/>)', r"\g<1>900\g<2>", text)
    assert count == 1, slot
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


def _check(engine, base: Path, tmp_path: Path, name: str, raw: str, row: dict) -> dict:
    reference = _fresh(engine, _variant(base, tmp_path, name, raw))
    for field in FIELDS:
        assert _close(row["candidate"]["metrics"][field], reference[field]), (name, field)
    return reference


def _evaluate(engine, base: Path, tmp_path: Path, name: str, raw: str) -> tuple[dict, dict, dict]:
    result = evaluate_item(raw, engine, build_path=str(base))
    row = _row(result)
    return row, row["evaluation_outcome"], _check(engine, base, tmp_path, name, raw, row)


# --------------------------------------------------------------------------- Strength stacker


def test_strength_build_stacks_strength_through_the_weapons_and_uses_combined_dps(real_pob_engine) -> None:
    loaded = real_pob_engine.load_build(STRENGTH)
    identity = loaded["build"]["main_skill_identity"]
    assert identity["skill_name"] == "Molten Blast" and identity["damage_owner"] == "PLAYER"
    metrics = real_pob_engine.get_metrics()["raw"]
    # PoB's own attribute and requirement outputs are visible to Item Check.
    assert metrics["Str"] > 1500 and metrics["ReqStr"] == 157 and metrics["Str"] > 10 * metrics["ReqStr"]
    assert metrics["Life"] == 1  # Chaos Inoculation: defence is Energy Shield
    equipment = {item["physical_slot"]: item.get("raw", "") for item in real_pob_engine.get_equipment()["equipment"]}
    assert "Added Attack Fire Damage per 25 Strength" in equipment["Weapon 1"]
    assert "Added Attack Fire Damage per 25 Strength" in equipment["Weapon 2"]
    result = evaluate_item(STR_CANDIDATES["str_more"], real_pob_engine, build_path=str(STRENGTH))
    assert result["primary_metric"]["pob_field"] == "CombinedDPS"


def test_more_and_less_strength_move_offense_and_defence_together(real_pob_engine, tmp_path: Path) -> None:
    row, outcome, reference = _evaluate(real_pob_engine, STRENGTH, tmp_path, "str_more", STR_CANDIDATES["str_more"])
    baseline = row["baseline"]["metrics"]
    assert reference["Str"] > baseline["Str"] and reference["CombinedDPS"] > baseline["CombinedDPS"] * 1.05
    assert reference["EnergyShield"] > baseline["EnergyShield"]  # Strength also raises Energy Shield in this build
    assert outcome["evaluation_quality"] == "FULL" and outcome["verdict"] == "MEANINGFUL_UPGRADE"
    assert outcome["item_impact"]["axes"]["OFFENSE"]["direction"] == "POSITIVE"

    row, outcome, reference = _evaluate(real_pob_engine, STRENGTH, tmp_path, "str_less", STR_CANDIDATES["str_less"])
    baseline = row["baseline"]["metrics"]
    assert reference["CombinedDPS"] < baseline["CombinedDPS"] * 0.95
    assert outcome["evaluation_quality"] == "FULL" and outcome["verdict"] == "MEANINGFUL_DOWNGRADE"
    assert outcome["item_impact"]["axes"]["OFFENSE"]["direction"] == "NEGATIVE"


def test_strength_scaling_has_thresholds_and_is_not_a_fixed_rate(real_pob_engine, tmp_path: Path) -> None:
    """Three more Strength across a per-25 boundary is worth several times the neighbouring three."""
    floor = _fresh(real_pob_engine, _variant(STRENGTH, tmp_path, "s4", _str_amulet(flat="+4 to Strength")))["CombinedDPS"]
    below = _fresh(real_pob_engine, _variant(STRENGTH, tmp_path, "s7", _str_amulet(flat="+7 to Strength")))["CombinedDPS"]
    above = _fresh(real_pob_engine, _variant(STRENGTH, tmp_path, "s10", _str_amulet(flat="+10 to Strength")))["CombinedDPS"]
    smooth, step = below - floor, above - below
    assert smooth > 0 and step > 3 * smooth

    # Item Check reports exactly PoB's number for each side of the boundary.
    for name in ("step_below", "step_above"):
        row, outcome, _ = _evaluate(real_pob_engine, STRENGTH, tmp_path, name, STR_CANDIDATES[name])
        assert outcome["evaluation_quality"] == "FULL"


def test_percent_increased_strength_beats_a_larger_flat_bonus(real_pob_engine, tmp_path: Path) -> None:
    """The item with no flat Strength change outscores the one adding +106 more flat Strength."""
    flat_row, flat_outcome, flat_ref = _evaluate(real_pob_engine, STRENGTH, tmp_path, "flat_high", STR_CANDIDATES["flat_high"])
    inc_row, inc_outcome, inc_ref = _evaluate(real_pob_engine, STRENGTH, tmp_path, "inc_high", STR_CANDIDATES["inc_high"])
    assert flat_outcome["evaluation_quality"] == "FULL" and inc_outcome["evaluation_quality"] == "FULL"
    assert inc_ref["Str"] > flat_ref["Str"] > flat_row["baseline"]["metrics"]["Str"]
    assert inc_ref["CombinedDPS"] > flat_ref["CombinedDPS"] * 1.3
    assert inc_outcome["final_score"] > flat_outcome["final_score"]
    assert inc_outcome["verdict"] == "MEANINGFUL_UPGRADE"


def test_defence_only_amulet_leaves_the_strength_stack_untouched(real_pob_engine, tmp_path: Path) -> None:
    row, outcome, reference = _evaluate(real_pob_engine, STRENGTH, tmp_path, "es_only", STR_CANDIDATES["es_only"])
    baseline = row["baseline"]["metrics"]
    assert _close(reference["CombinedDPS"], baseline["CombinedDPS"]) and _close(reference["Str"], baseline["Str"])
    assert reference["EnergyShield"] > baseline["EnergyShield"]
    assert outcome["evaluation_quality"] == "FULL" and outcome["verdict"] in {"MINOR_UPGRADE", "MEANINGFUL_UPGRADE"}
    axes = outcome["item_impact"]["axes"]
    assert axes["DEFENSE"]["direction"] == "POSITIVE" and axes["OFFENSE"]["direction"] != "POSITIVE"


def test_strength_gain_with_a_lost_resistance_cap_is_a_flagged_tradeoff(real_pob_engine, tmp_path: Path) -> None:
    row, outcome, reference = _evaluate(real_pob_engine, STRENGTH, tmp_path, "tradeoff", STR_CANDIDATES["tradeoff"])
    baseline = row["baseline"]["metrics"]
    assert reference["CombinedDPS"] > baseline["CombinedDPS"] * 1.1 and reference["TotalEHP"] < baseline["TotalEHP"]
    assert outcome["evaluation_quality"] == "FULL" and outcome["item_impact"]["pattern"] == "TRADEOFF"
    assert {g["code"] for g in outcome["guardrails_applied"]} == {"RES_CAP_LOST"}
    assert outcome["verdict"] == "MINOR_DOWNGRADE"


def test_dropping_below_an_equipped_requirement_is_not_viable(real_pob_engine, tmp_path: Path) -> None:
    """PoB still applies an item whose requirement is unmet; only the guardrail can catch it."""
    result = evaluate_item(STR_CANDIDATES["requirement"], real_pob_engine, build_path=str(STRENGTH))
    row = _row(result)
    outcome = row["evaluation_outcome"]
    reference = _fresh(real_pob_engine, _variant(STRENGTH, tmp_path, "requirement", STR_CANDIDATES["requirement"]))
    assert reference["Str"] < reference["ReqStr"] == 157
    assert row["candidate"]["metrics"]["Str"] == reference["Str"]
    # The offense and defence deltas are fully measured; the guardrail alone makes the verdict NOT_VIABLE.
    assert outcome["evaluation_quality"] == "FULL"
    assert outcome["verdict"] == "NOT_VIABLE"
    assert "ATTRIBUTE_REQUIREMENT_LOST" in {g["code"] for g in outcome["guardrails_applied"]}


def test_strength_build_repeated_evaluations_restore_the_build(real_pob_engine) -> None:
    real_pob_engine.load_build(STRENGTH)
    original_hash = real_pob_engine.get_metrics()["fingerprint_hash"]
    original_equipment = real_pob_engine.get_equipment()
    first = evaluate_item(STR_CANDIDATES["str_more"], real_pob_engine, build_path=str(STRENGTH))
    evaluate_item(STR_CANDIDATES["requirement"], real_pob_engine, build_path=str(STRENGTH))
    second = evaluate_item(STR_CANDIDATES["str_more"], real_pob_engine, build_path=str(STRENGTH))
    a, b = _row(first), _row(second)
    assert a["evaluation_outcome"]["evaluation_quality"] == b["evaluation_outcome"]["evaluation_quality"] == "FULL"
    assert a["evaluation_outcome"]["final_score"] == b["evaluation_outcome"]["final_score"]
    assert a["restore"]["pass"] is True and b["restore"]["pass"] is True
    assert real_pob_engine.get_metrics()["fingerprint_hash"] == original_hash
    assert real_pob_engine.get_equipment() == original_equipment


# --------------------------------------------------------------------------- Dexterity / Intelligence stacker


def test_dex_int_build_scales_speed_and_added_damage_from_attributes(real_pob_engine) -> None:
    loaded = real_pob_engine.load_build(DEX_INT)
    identity = loaded["build"]["main_skill_identity"]
    assert identity["skill_name"] == "Fragments of the Past" and identity["damage_owner"] == "PLAYER"
    metrics = real_pob_engine.get_metrics()["raw"]
    assert metrics["Dex"] > 400 and metrics["Int"] > 1400 and metrics["ReqDex"] == 147 == metrics["ReqInt"]
    equipment = {item["physical_slot"]: item.get("raw", "") for item in real_pob_engine.get_equipment()["equipment"]}
    assert "1% increased Attack Speed per 20 Dexterity" in equipment["Gloves"]
    assert "Adds 1 to 12 Lightning Damage to Attacks per 20 Intelligence" in equipment["Gloves"]


def test_more_and_fewer_attributes_change_speed_and_damage(real_pob_engine, tmp_path: Path) -> None:
    row, outcome, reference = _evaluate(real_pob_engine, DEX_INT, tmp_path, "attrs_more", DI_CANDIDATES["attrs_more"])
    baseline = row["baseline"]["metrics"]
    assert reference["Dex"] > baseline["Dex"] and reference["Int"] > baseline["Int"]
    assert reference["Speed"] > baseline["Speed"] and reference["TotalDPS"] > baseline["TotalDPS"] * 1.05
    assert outcome["evaluation_quality"] == "FULL" and outcome["verdict"] == "MEANINGFUL_UPGRADE"

    row, outcome, reference = _evaluate(real_pob_engine, DEX_INT, tmp_path, "attrs_less", DI_CANDIDATES["attrs_less"])
    baseline = row["baseline"]["metrics"]
    assert reference["Speed"] < baseline["Speed"] and reference["TotalDPS"] < baseline["TotalDPS"] * 0.95
    assert outcome["evaluation_quality"] == "FULL" and outcome["verdict"] == "MEANINGFUL_DOWNGRADE"


def test_extra_energy_shield_does_not_pay_for_lost_attributes(real_pob_engine, tmp_path: Path) -> None:
    row, outcome, reference = _evaluate(real_pob_engine, DEX_INT, tmp_path, "attrs_less_more_es", DI_CANDIDATES["attrs_less_more_es"])
    baseline = row["baseline"]["metrics"]
    assert reference["EnergyShield"] > baseline["EnergyShield"] and reference["TotalDPS"] < baseline["TotalDPS"]
    assert reference["TotalEHP"] < baseline["TotalEHP"]  # the lost Strength also costs Life
    assert outcome["evaluation_quality"] == "FULL" and outcome["verdict"] == "MEANINGFUL_DOWNGRADE"
    axes = outcome["item_impact"]["axes"]
    assert axes["OFFENSE"]["direction"] == "NEGATIVE" and axes["DEFENSE"]["direction"] == "NEGATIVE"


def test_dex_int_defence_only_amulet_leaves_offense_unchanged(real_pob_engine, tmp_path: Path) -> None:
    row, outcome, reference = _evaluate(real_pob_engine, DEX_INT, tmp_path, "di_es_only", DI_CANDIDATES["es_only"])
    baseline = row["baseline"]["metrics"]
    assert _close(reference["TotalDPS"], baseline["TotalDPS"]) and reference["EnergyShield"] > baseline["EnergyShield"]
    assert outcome["evaluation_quality"] == "FULL"
    assert outcome["item_impact"]["axes"]["OFFENSE"]["direction"] != "POSITIVE"
