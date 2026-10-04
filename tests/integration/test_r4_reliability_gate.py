"""R4 1.0 reliability gate: real-PoB evidence for what the existing corpus did not establish.

The R4 audit swept every gear slot across five public-corpus builds and found no defect; what it found missing was a
committed regression proving it. Belt had no real-PoB verdict test at all, Helmet and Body Armour appeared only inside
an ES-mana case and a requirement guardrail. This file holds that single sweep so a slot that silently evaluates the
wrong slot, loses its candidate, or fails to restore is caught on the real engine.

Only gaps the audit proved are added here; jewel and stat-stacker evidence lives beside the fixtures it extends
(test_jewel_real_pob.py, test_corpus02_giants_blood_shield.py) so each regression has exactly one layer.
"""

from __future__ import annotations

from pathlib import Path
from xml.etree import ElementTree

import pytest

from exilelens.items.evaluation import evaluate_item

ROOT = Path(__file__).resolve().parents[2]
BUILD = ROOT / "fixtures" / "builds" / "public_corpus" / "core04_melee_weapon.xml"
pytestmark = [pytest.mark.integration, pytest.mark.real_pob, pytest.mark.itemcheck]

GEAR_SLOTS = ("Helmet", "Body Armour", "Gloves", "Boots", "Belt", "Amulet", "Ring 1", "Ring 2")
UPGRADES = {"MINOR_UPGRADE", "MEANINGFUL_UPGRADE", "MAJOR_UPGRADE"}


def _equipped_item(path: Path, slot: str) -> str:
    root = ElementTree.parse(path).getroot()
    items = root.find("Items")
    assert items is not None
    raw = {item.get("id"): (item.text or "").strip() for item in items.findall("Item")}
    active = items.get("activeItemSet")
    item_set = next(entry for entry in items.findall("ItemSet") if entry.get("id") == active)
    item_id = next(entry.get("itemId") for entry in item_set.findall("Slot") if entry.get("name") == slot)
    assert item_id and item_id != "0", slot
    return raw[item_id]


@pytest.mark.parametrize("slot", GEAR_SLOTS)
def test_every_gear_slot_is_measured_in_its_own_slot_and_restored(real_pob_engine, slot: str) -> None:
    """The equipped item plus one Life line, in each slot: resolved to that slot, FULL, a measured defence gain, restored."""
    equipped = _equipped_item(BUILD, slot)
    candidate = equipped + "\n+100 to maximum Life\n"

    result = evaluate_item(candidate, real_pob_engine, build_path=str(BUILD))

    rows = {row["pob_slot"]: row for row in result["slot_comparisons"]}
    # Rings are legal in both ring slots and are both evaluated; every other slot resolves to exactly itself.
    assert set(rows) == ({"Ring 1", "Ring 2"} if slot.startswith("Ring") else {slot})
    row = rows[slot]
    assert row["baseline_item"]["empty"] is False
    assert row["candidate"]["item_present"] is True
    outcome = row["evaluation_outcome"]
    assert outcome["evaluation_quality"] == "FULL"
    assert outcome["item_impact"]["axes"]["DEFENSE"]["direction"] == "POSITIVE"
    assert outcome["verdict"] in UPGRADES
    assert all(entry["restore"]["pass"] is True for entry in result["slot_comparisons"])
