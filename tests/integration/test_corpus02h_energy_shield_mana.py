"""CORPUS-02H: Energy Shield scaling on an authentic Eldritch Battery build.

``corpus02h_eldritch_battery_shaman.xml`` (Druid / Shaman, level 100): the Eldritch Battery keystone
("Convert 100% of maximum Energy Shield to maximum Mana", "Mana Costs are Doubled") turns every point
of Energy Shield into maximum Mana, and Rathpith Globe scales the main skill (Spark, cast by a Spell
Totem) with maximum Mana ("6% increased Damage per 100 maximum Mana", "+3% Critical Hit Chance per 100
maximum Mana"). PoB therefore reports Energy Shield 0 and calculates Mana, damage and effective HP from
the same pool. See docs/CORPUS-02H.md.

Every numeric expectation is checked against an independent fresh PoB load of the same build with the
candidate equipped in its slot, never against ExileLens's own scoring.
"""

from __future__ import annotations

import math
import re
from pathlib import Path
from xml.sax.saxutils import escape

import pytest

from exilelens.items.evaluation import evaluate_item

ROOT = Path(__file__).resolve().parents[2]
BUILD = ROOT / "fixtures" / "builds" / "public_corpus" / "corpus02h_eldritch_battery_shaman.xml"
pytestmark = [pytest.mark.integration, pytest.mark.real_pob, pytest.mark.itemcheck]

FIELDS = (
    "TotalDPS", "Speed", "Life", "EnergyShield", "Mana", "ManaUnreserved", "ManaPerSecondCost",
    "ManaRegenRecovery", "TotalEHP", "ChaosResist",
)

_HELMET = """Rarity: RARE
Dusk Halo
Ancestral Tiara
Energy Shield: 532
Item Level: 80
Quality: 24
Sockets: S S
Rune: Raven-Touched Shard
Rune: Jiquani's Thesis
LevelReq: 80
Implicits: 3
{{enchant}}{{rune}}+1 to maximum Mana per 2 Item Energy Shield on Equipped Helmet
{{enchant}}{{rune}}Raven-Touched
{{enchant}}Allocates Piercing Shot
{{fractured}}16% increased Rarity of Items found
{inc}
{life}
+32 to Intelligence
{chaos}
{{desecrated}}{flat}
{extra}"""


def _helmet(inc: str = "137% increased Energy Shield", life: str = "+48 to maximum Life",
            chaos: str = "+22% to Chaos Resistance", flat: str = "+72 to maximum Energy Shield", extra: str = "") -> str:
    text = _HELMET.format(inc=inc, life=life, chaos=chaos, flat=flat, extra=extra)
    return "\n".join(line for line in text.split("\n") if line.strip())


_AMULET = """Rarity: RARE
Gale Beads
Gold Amulet
Item Level: 82
LevelReq: 65
Implicits: 2
{{enchant}}Allocates Zarokh's Gift
20% increased Rarity of Items found
{{fractured}}+50 to Spirit
+188 to maximum Mana
5% increased maximum Mana
+4 to Level of all Spell Skills
35% increased Cast Speed
{{desecrated}}16% of Damage is taken from Mana before Life
{extra}"""


def _amulet(extra: str = "") -> str:
    return "\n".join(line for line in _AMULET.format(extra=extra).split("\n") if line.strip())


HELMETS = {
    "es_up": _helmet(flat="+272 to maximum Energy Shield"),
    "es_down": _helmet(flat="+2 to maximum Energy Shield"),
    "inc_es_up": _helmet(inc="237% increased Energy Shield"),
    "mana_direct": _helmet(extra="+1000 to maximum Mana"),
    "life_instead_of_es": _helmet(inc="+300 to maximum Life"),
    "tradeoff": _helmet(flat="+272 to maximum Energy Shield", chaos="-30% to Chaos Resistance"),
}
AMULETS = {"es_flat": _amulet("+200 to maximum Energy Shield"), "mana_flat": _amulet("+1000 to maximum Mana")}


# --------------------------------------------------------------------------- helpers


def _variant(tmp_path: Path, name: str, slot: str, raw: str) -> Path:
    """The build as the player would save it with ``raw`` equipped in ``slot``."""
    text = BUILD.read_text(encoding="utf-8")
    text = text.replace("\t\t<ItemSet ", f'\t\t<Item id="900">\n{escape(raw)}\n\t\t</Item>\n\t\t<ItemSet ', 1)
    text, count = re.subn(rf'(<Slot itemId=")\d+(" itemPbURL="" name="{slot}"/>)', r"\g<1>900\g<2>", text)
    assert count == 1, slot
    path = tmp_path / f"{name}.xml"
    path.write_text(text, encoding="utf-8")
    return path


def _fresh(engine, path: Path) -> dict:
    engine.load_build(path)
    return engine.get_metrics()["raw"]


def _row(result: dict, slot: str) -> dict:
    return next(row for row in result["slot_comparisons"] if row["pob_slot"] == slot)


def _close(actual, expected) -> bool:
    return math.isclose(float(actual), float(expected), rel_tol=1e-6, abs_tol=1e-6)


def _evaluate(engine, tmp_path: Path, name: str, slot: str, raw: str) -> tuple[dict, dict, dict]:
    result = evaluate_item(raw, engine, build_path=str(BUILD))
    row = _row(result, slot)
    reference = _fresh(engine, _variant(tmp_path, name, slot, raw))
    for field in FIELDS:
        assert _close(row["candidate"]["metrics"][field], reference[field]), (name, field)
    return row, row["evaluation_outcome"], reference


# --------------------------------------------------------------------------- what the build measures


def test_energy_shield_is_converted_to_mana_and_mana_scales_the_main_skill(real_pob_engine) -> None:
    loaded = real_pob_engine.load_build(BUILD)
    identity = loaded["build"]["main_skill_identity"]
    assert identity["skill_name"] == "Spark" and identity["damage_owner"] == "PLAYER"
    metrics = real_pob_engine.get_metrics()["raw"]
    assert metrics["EnergyShield"] == 0 and metrics["Mana"] > 10_000  # every point of ES is in the Mana pool
    equipment = {item["physical_slot"]: item.get("raw", "") for item in real_pob_engine.get_equipment()["equipment"]}
    assert "6% increased Damage per 100 maximum Mana" in equipment["Weapon 2"]
    assert "+1 to maximum Mana per 2 Item Energy Shield on Equipped Helmet" in equipment["Helmet"]
    spec = BUILD.read_text(encoding="utf-8").split("<Spec ", 1)[1].split("</Spec>", 1)[0]
    assert "57513" in re.search(r'nodes="([^"]*)"', spec).group(1).split(",")  # Eldritch Battery is allocated

    result = evaluate_item(HELMETS["es_up"], real_pob_engine, build_path=str(BUILD))
    assert result["primary_metric"]["pob_field"] == "TotalDPS"


# --------------------------------------------------------------------------- FULL verdicts against fresh loads


def test_more_energy_shield_raises_mana_damage_and_effective_hp(real_pob_engine, tmp_path: Path) -> None:
    row, outcome, reference = _evaluate(real_pob_engine, tmp_path, "es_up", "Helmet", HELMETS["es_up"])
    baseline = row["baseline"]["metrics"]
    assert reference["EnergyShield"] == 0 == baseline["EnergyShield"]  # the Energy Shield output never moves
    assert reference["Mana"] > baseline["Mana"] * 1.1
    assert reference["TotalDPS"] > baseline["TotalDPS"] * 1.2 and reference["TotalEHP"] > baseline["TotalEHP"]
    assert outcome["evaluation_quality"] == "FULL" and outcome["verdict"] == "MEANINGFUL_UPGRADE"
    axes = outcome["item_impact"]["axes"]
    assert axes["OFFENSE"]["direction"] == "POSITIVE" and axes["DEFENSE"]["direction"] == "POSITIVE"


def test_less_energy_shield_lowers_mana_damage_and_effective_hp(real_pob_engine, tmp_path: Path) -> None:
    row, outcome, reference = _evaluate(real_pob_engine, tmp_path, "es_down", "Helmet", HELMETS["es_down"])
    baseline = row["baseline"]["metrics"]
    assert reference["Mana"] < baseline["Mana"] and reference["TotalDPS"] < baseline["TotalDPS"] * 0.9
    assert reference["TotalEHP"] < baseline["TotalEHP"]
    assert outcome["evaluation_quality"] == "FULL" and outcome["verdict"] == "MEANINGFUL_DOWNGRADE"
    axes = outcome["item_impact"]["axes"]
    assert axes["OFFENSE"]["direction"] == "NEGATIVE" and axes["DEFENSE"]["direction"] == "NEGATIVE"


def test_percent_increased_energy_shield_on_the_armour_reaches_the_mana_pool(real_pob_engine, tmp_path: Path) -> None:
    row, outcome, reference = _evaluate(real_pob_engine, tmp_path, "inc_es_up", "Helmet", HELMETS["inc_es_up"])
    baseline = row["baseline"]["metrics"]
    assert reference["Mana"] > baseline["Mana"] and reference["TotalDPS"] > baseline["TotalDPS"] * 1.05
    assert outcome["evaluation_quality"] == "FULL" and outcome["verdict"] == "MEANINGFUL_UPGRADE"


def test_the_same_flat_energy_shield_is_worth_more_on_the_helmet_than_the_amulet(real_pob_engine, tmp_path: Path) -> None:
    """The helmet's enchant and its increased Energy Shield multiply the flat value; the amulet has neither."""
    helmet_row, helmet_outcome, helmet_ref = _evaluate(real_pob_engine, tmp_path, "h200", "Helmet", _helmet(extra="+200 to maximum Energy Shield"))
    amulet_row, amulet_outcome, amulet_ref = _evaluate(real_pob_engine, tmp_path, "a200", "Amulet", AMULETS["es_flat"])
    baseline = helmet_row["baseline"]["metrics"]
    helmet_mana = helmet_ref["Mana"] - baseline["Mana"]
    amulet_mana = amulet_ref["Mana"] - baseline["Mana"]
    assert amulet_mana > 0 and helmet_mana > 3 * amulet_mana
    assert helmet_outcome["evaluation_quality"] == amulet_outcome["evaluation_quality"] == "FULL"
    assert helmet_outcome["final_score"] > amulet_outcome["final_score"]


def test_direct_mana_and_converted_energy_shield_are_measured_alike(real_pob_engine, tmp_path: Path) -> None:
    """Independent effect: flat Mana needs no conversion; Energy Shield still reads as zero in both."""
    row, outcome, reference = _evaluate(real_pob_engine, tmp_path, "mana_direct", "Helmet", HELMETS["mana_direct"])
    baseline = row["baseline"]["metrics"]
    assert reference["EnergyShield"] == 0 and reference["Mana"] > baseline["Mana"]
    assert reference["TotalDPS"] > baseline["TotalDPS"] * 1.2
    assert outcome["evaluation_quality"] == "FULL" and outcome["verdict"] == "MEANINGFUL_UPGRADE"


def test_energy_shield_gain_that_costs_a_resistance_cap_is_a_flagged_tradeoff(real_pob_engine, tmp_path: Path) -> None:
    row, outcome, reference = _evaluate(real_pob_engine, tmp_path, "tradeoff", "Helmet", HELMETS["tradeoff"])
    baseline = row["baseline"]["metrics"]
    assert reference["TotalDPS"] > baseline["TotalDPS"] * 1.2 and reference["ChaosResist"] < baseline["ChaosResist"]
    assert outcome["evaluation_quality"] == "FULL"
    assert {g["code"] for g in outcome["guardrails_applied"]} == {"RES_CAP_LOST"}
    assert outcome["verdict"] != "MEANINGFUL_UPGRADE"


def test_swapping_energy_shield_for_life_costs_damage_and_effective_hp(real_pob_engine, tmp_path: Path) -> None:
    """Life is not Energy Shield here: the measured offense and effective HP both fall."""
    row, outcome, reference = _evaluate(real_pob_engine, tmp_path, "life", "Helmet", HELMETS["life_instead_of_es"])
    baseline = row["baseline"]["metrics"]
    assert reference["Life"] > baseline["Life"]
    assert reference["TotalDPS"] < baseline["TotalDPS"] * 0.9 and reference["TotalEHP"] < baseline["TotalEHP"]
    assert outcome["evaluation_quality"] == "FULL"
    axes = outcome["item_impact"]["axes"]
    assert axes["OFFENSE"]["direction"] == "NEGATIVE" and axes["DEFENSE"]["direction"] == "NEGATIVE"
    # SCORING-01: the +6.8 life/s recovery gain (0.37% of max Life per second) is measured and visible, but it is
    # not a material opposing effect, so the ordinary score decides: a clear downgrade, not a forced sidegrade.
    assert axes["RECOVERY"]["direction"] == "POSITIVE" and not axes["RECOVERY"]["material_positive"]
    conflict = outcome["item_impact"]["conflict"]
    assert conflict["kind"] == "NONE" and [o["metric"] for o in conflict["negligible_opposition"]] == ["LifeRegenRecovery"]
    assert outcome["verdict"] == "MEANINGFUL_DOWNGRADE" and outcome["final_score"] == outcome["raw_score"]
    assert "too small to offset the larger offense and defense losses" in outcome["verdict_reason"]


def test_repeated_evaluations_are_identical_and_restore_the_build(real_pob_engine) -> None:
    real_pob_engine.load_build(BUILD)
    original_hash = real_pob_engine.get_metrics()["fingerprint_hash"]
    original_equipment = real_pob_engine.get_equipment()
    first = evaluate_item(HELMETS["es_up"], real_pob_engine, build_path=str(BUILD))
    evaluate_item(HELMETS["es_down"], real_pob_engine, build_path=str(BUILD))
    second = evaluate_item(HELMETS["es_up"], real_pob_engine, build_path=str(BUILD))
    a, b = _row(first, "Helmet"), _row(second, "Helmet")
    assert a["evaluation_outcome"]["evaluation_quality"] == b["evaluation_outcome"]["evaluation_quality"] == "FULL"
    assert a["evaluation_outcome"]["final_score"] == b["evaluation_outcome"]["final_score"]
    assert a["candidate"]["metrics"]["TotalDPS"] == b["candidate"]["metrics"]["TotalDPS"]
    assert a["restore"]["pass"] is True and b["restore"]["pass"] is True
    assert real_pob_engine.get_metrics()["fingerprint_hash"] == original_hash
    assert real_pob_engine.get_equipment() == original_equipment
