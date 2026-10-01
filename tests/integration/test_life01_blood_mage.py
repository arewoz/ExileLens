"""LIFE-01: authentic current-Life offensive scaling through PoB2 Gore Spike."""

from pathlib import Path
from xml.etree import ElementTree

import pytest

from exilelens.items.evaluation import evaluate_item


ROOT = Path(__file__).resolve().parents[2]
BUILD = ROOT / "fixtures" / "builds" / "public_corpus" / "life01_blood_mage_ember_fusillade.xml"

pytestmark = [pytest.mark.integration, pytest.mark.real_pob, pytest.mark.itemcheck]


LIFE_ONLY_ORIGINAL_SIN = """Rarity: UNIQUE
Original Sin
Amethyst Ring
Item Level: 82
LevelReq: 20
+13% to Chaos Resistance
+21% to Chaos Resistance
100% of Elemental Damage Converted to Chaos Damage
+100 to maximum Life"""


def test_life01_gore_spike_life_increases_authoritative_player_offense(real_pob_engine) -> None:
    """The retained public Blood Mage export proves a Life-only item delta moves DPS."""
    root = ElementTree.parse(BUILD).getroot()
    build = root.find("Build")
    spec = root.find(".//Tree/Spec")
    assert build is not None and build.get("ascendClassName") == "Blood Mage"
    assert spec is not None and "52703" in (spec.get("nodes") or "").split(",")  # Gore Spike in TreeData/0_4.

    result = evaluate_item(LIFE_ONLY_ORIGINAL_SIN, real_pob_engine, build_path=str(BUILD))
    row = next(row for row in result["slot_comparisons"] if row["pob_slot"] == "Ring 2")
    baseline = row["baseline"]["metrics"]
    candidate = row["candidate"]["metrics"]
    outcome = row["evaluation_outcome"]

    assert result["build"]["main_skill_identity"]["skill_name"] == "Ember Fusillade"
    assert baseline["Life"] < candidate["Life"]
    assert baseline["LifeUnreserved"] < candidate["LifeUnreserved"]
    assert baseline["CritMultiplier"] < candidate["CritMultiplier"]
    assert baseline["CombinedDPS"] < candidate["CombinedDPS"]
    assert baseline["TotalEHP"] < candidate["TotalEHP"]
    assert outcome["evaluation_quality"] == "FULL"
    assert outcome["item_impact"]["axes"]["OFFENSE"]["direction"] == "POSITIVE"
    assert row["restore"]["pass"] is True
