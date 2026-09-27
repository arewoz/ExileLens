"""CORPUS-02C: Way of the Stonefist (Monk / Martial Artist) Item Check truthfulness.

Fixture ``corpus02c_stonefist_martial_artist.xml`` is a real public ladder character
with Way of the Stonefist allocated. Its export already contains the equipped gloves
in their transformed form ("Runeforged Fists of Stone" with transformed modifiers),
which the supported PoB parses. The supported PoB does not apply the transformation
itself, so an ordinary glove candidate would be compared untransformed against the
transformed baseline. See docs/CORPUS-02C.md.

Every numeric expectation is checked against an independent cold PoB load of an
edited copy of the fixture, never against ExileLens's own scoring output.
"""

from __future__ import annotations

import math
import re
from pathlib import Path
from xml.etree import ElementTree
from xml.sax.saxutils import escape

import pytest

from exilelens.items.evaluation import evaluate_item


ROOT = Path(__file__).resolve().parents[2]
CORPUS = ROOT / "fixtures" / "builds" / "public_corpus"
BUILD = CORPUS / "corpus02c_stonefist_martial_artist.xml"
STONEFIST = "Way of the Stonefist"
FISTS = "Fists of Stone"
pytestmark = [pytest.mark.integration, pytest.mark.real_pob, pytest.mark.itemcheck]


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


def _fresh_metrics(engine, tmp_path: Path, name: str, slot: str, raw: str) -> dict:
    text = BUILD.read_text(encoding="utf-8")
    text, count = re.subn(
        rf'(<Slot itemId=")\d+(" itemPbURL="" name="{re.escape(slot)}"/>)', r"\g<1>900\g<2>", text,
    )
    assert count == 1
    anchor = re.search(r"\t\t<ItemSet ", text)
    assert anchor is not None
    text = text[:anchor.start()] + f'\t\t<Item id="900">\n{escape(raw)}\n\t\t</Item>\n' + text[anchor.start():]
    path = tmp_path / f"{name}.xml"
    path.write_text(text, encoding="utf-8")
    engine.load_build(path)
    return engine.get_metrics()["raw"]


def _row(result: dict, slot: str) -> dict:
    return next(row for row in result["slot_comparisons"] if row["pob_slot"] == slot)


def _close(actual: float, expected: float) -> bool:
    return math.isclose(float(actual), float(expected), rel_tol=1e-6, abs_tol=1e-6)


def _own_gloves() -> str:
    return _equipped_item(BUILD, "Gloves")


def test_stonefist_is_detected_and_the_supported_pob_does_not_model_it(real_pob_engine) -> None:
    """Re-pin tripwire: a PoB revision that parses the passive must be re-validated."""
    build = real_pob_engine.load_build(BUILD)["build"]
    assert (build["class"], build["ascendancy"]) == ("Monk", "Martial Artist")
    assert build["item_base_transforms"] == [{
        "modeled": False, "node": STONEFIST, "node_id": 39595, "slot": "Gloves", "transformed_base": FISTS,
    }]
    equipment = {e["slot"]: e for e in real_pob_engine.get_equipment()["equipment"] if isinstance(e, dict)}
    assert FISTS in equipment["Gloves"]["base_name"]


def test_transformed_glove_comparison_is_measured(real_pob_engine, tmp_path: Path) -> None:
    """Both sides are Fists of Stone: a like-for-like comparison PoB measures."""
    candidate = "\n".join(line for line in _own_gloves().splitlines() if "to Critical Hit Chance" not in line)
    assert candidate != _own_gloves()
    baseline = _fresh_metrics(real_pob_engine, tmp_path, "own", "Gloves", _own_gloves())
    expected = _fresh_metrics(real_pob_engine, tmp_path, "no_crit", "Gloves", candidate)
    assert expected["CombinedDPS"] < baseline["CombinedDPS"]

    result = evaluate_item(candidate, real_pob_engine, build_path=str(BUILD))

    row = _row(result, "Gloves")
    assert row["unmodeled_item_transform"] is None
    assert _close(row["baseline"]["metrics"]["CombinedDPS"], baseline["CombinedDPS"])
    assert _close(row["candidate"]["metrics"]["CombinedDPS"], expected["CombinedDPS"])
    outcome = row["evaluation_outcome"]
    assert outcome["evaluation_quality"] == "FULL"
    assert outcome["item_impact"]["axes"]["OFFENSE"]["direction"] == "NEGATIVE"
    assert outcome["verdict"] == "MEANINGFUL_DOWNGRADE"
    assert row["restore"]["pass"] is True


@pytest.mark.parametrize(
    "source",
    [CORPUS / "core04_minion_actor.xml", CORPUS / "core04_melee_weapon.xml"],
    ids=["vaal_gloves", "plate_gauntlets"],
)
def test_ordinary_glove_candidate_is_unsupported_not_confident(real_pob_engine, source: Path) -> None:
    """An ordinary glove would be transformed in game; PoB compares it untransformed.

    Before CORPUS-02C these candidates were FULL / MEANINGFUL_DOWNGRADE (e.g. -34%
    damage, -30% EHP) purely because the transformation was missing.
    """
    candidate = _equipped_item(source, "Gloves")
    assert FISTS not in candidate
    real_pob_engine.load_build(BUILD)
    original_hash = real_pob_engine.get_metrics()["fingerprint_hash"]

    result = evaluate_item(candidate, real_pob_engine, build_path=str(BUILD))

    row = _row(result, "Gloves")
    outcome = row["evaluation_outcome"]
    assert outcome["verdict"] == "UNSUPPORTED"
    assert result["presentation"]["verdict"] == "UNSUPPORTED"
    assert outcome["evaluation_quality"] == "UNSUPPORTED"
    assert [reason["code"] for reason in outcome["evaluation_quality_reasons"]] == ["ITEM_TRANSFORM_UNMODELED"]
    transform = row.get("unmodeled_item_transform") or {}
    assert transform.get("code") == "ITEM_TRANSFORM_UNMODELED" and transform.get("node") == STONEFIST
    assert FISTS in transform["baseline_base"] and FISTS not in transform["candidate_base"]
    # No damage number is claimed for the untransformed item.
    assert row["metric_profile"]["primary_offense"]["delta_kind"] == "UNSUPPORTED"
    assert outcome["item_impact"]["axes"]["OFFENSE"]["direction"] == "UNKNOWN"
    assert outcome["damage_claim"]["relative_status"] != "AVAILABLE"
    assert row["restore"]["pass"] is True
    assert real_pob_engine.get_metrics()["fingerprint_hash"] == original_hash


def test_non_glove_candidates_on_a_stonefist_build_stay_measured(real_pob_engine, tmp_path: Path) -> None:
    candidate = _equipped_item(BUILD, "Amulet") + "\n+30 to maximum Life\n"
    baseline = _fresh_metrics(real_pob_engine, tmp_path, "amulet_own", "Amulet", _equipped_item(BUILD, "Amulet"))
    expected = _fresh_metrics(real_pob_engine, tmp_path, "amulet_life", "Amulet", candidate)
    assert expected["Life"] > baseline["Life"]

    result = evaluate_item(candidate, real_pob_engine, build_path=str(BUILD))

    row = _row(result, "Amulet")
    assert row["unmodeled_item_transform"] is None
    assert _close(row["candidate"]["metrics"]["Life"], expected["Life"])
    outcome = row["evaluation_outcome"]
    assert outcome["evaluation_quality"] == "FULL"
    assert outcome["verdict"] not in {"UNSUPPORTED", "UNCERTAIN", "NOT_EVALUATED"}
    assert row["restore"]["pass"] is True
