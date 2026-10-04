"""CORPUS-02B: verdict-level Item Check coverage for minion and Djinn builds.

Two public-corpus fixtures:

* ``core04_minion_actor.xml`` -- Witch/Infernalist, Summon Infernal Hound. Until
  now it had identity-only coverage.
* ``corpus02b_varashta_djinn.xml`` -- Sorceress/Disciple of Varashta with all three
  ascendancy Djinns (Navira main, Ruzhan, Kelari) plus other minions. A real public
  ladder character, but NOT the build from the community Djinn report (that export
  is unavailable); see docs/CORPUS-02B.md.

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
from exilelens.items.more_info import build_more_info


ROOT = Path(__file__).resolve().parents[2]
CORPUS = ROOT / "fixtures" / "builds" / "public_corpus"
HOUND = CORPUS / "core04_minion_actor.xml"
DJINN = CORPUS / "corpus02b_varashta_djinn.xml"
DEFENSE_RING = ROOT / "fixtures" / "items" / "core04_defense_ring.txt"
MINION_FIELD = "Minion.CombinedDPS"
NAVIRA, RUZHAN, KELARI = "Navira, the Last Mirage", "Ruzhan, the Blazing Sword", "Kelari, the Tainted Sands"
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


def _without(raw: str, pattern: str) -> str:
    kept = [line for line in raw.splitlines() if not re.search(pattern, line)]
    assert len(kept) == len(raw.splitlines()) - 1, pattern
    return "\n".join(kept)


def _variant(build: Path, tmp_path: Path, name: str, *, slots: dict[str, str] | None = None,
             main_group: int | None = None, main_active_skill: int | None = None) -> Path:
    """Write an edited copy of ``build`` (slot items and/or main-skill selection)."""
    text = build.read_text(encoding="utf-8")
    new_items = []
    for index, (slot, raw) in enumerate((slots or {}).items()):
        item_id = str(900 + index)
        new_items.append(f'\t\t<Item id="{item_id}">\n{escape(raw)}\n\t\t</Item>\n')
        text, count = re.subn(
            rf'(<Slot itemId=")\d+(" itemPbURL="" name="{re.escape(slot)}"/>)', rf"\g<1>{item_id}\g<2>", text,
        )
        assert count == 1, slot
    if new_items:
        anchor = re.search(r"\t\t<ItemSet ", text)
        assert anchor is not None
        text = text[:anchor.start()] + "".join(new_items) + text[anchor.start():]
    if main_group is not None:
        text, count = re.subn(r'mainSocketGroup="\d+"', f'mainSocketGroup="{main_group}"', text, count=1)
        assert count == 1
    if main_active_skill is not None:
        starts = [match.start() for match in re.finditer(r"<Skill ", text)]
        start = starts[(main_group or 1) - 1]
        end = text.index(">", start)
        head, count = re.subn(r'mainActiveSkill="[^"]*"', f'mainActiveSkill="{main_active_skill}"', text[start:end], count=1)
        assert count == 1
        text = text[:start] + head + text[end:]
    path = tmp_path / f"{name}.xml"
    path.write_text(text, encoding="utf-8")
    return path


def _fresh(engine, path: Path) -> dict:
    engine.load_build(path)
    return engine.get_metrics()["raw"]


def _row(result: dict, slot: str) -> dict:
    return next(row for row in result["slot_comparisons"] if row["pob_slot"] == slot)


def _axes(row: dict) -> dict[str, str]:
    return {name: axis["direction"] for name, axis in row["evaluation_outcome"]["item_impact"]["axes"].items()}


def _close(actual: float, expected: float) -> bool:
    return math.isclose(float(actual), float(expected), rel_tol=1e-6, abs_tol=1e-6)


def _assert_minion_primary(row: dict, actor_id: str) -> None:
    metric = row["baseline_primary_metric"]
    assert row["primary_metric_field"] == MINION_FIELD
    assert metric["metric_source"] == "MINION"
    assert metric["output_table"] == "mainOutput.Minion"
    assert metric["semantic_quantity"] == "ACTOR_COMBINED_DPS"
    assert row["candidate_primary_metric"]["metric_path"] == metric["metric_path"]
    for phase in ("baseline", "candidate"):
        skill = row[phase]["primary_skill"]
        assert skill["damage_owner"] == "MINION"
        assert skill["actor_id"] == actor_id
    assert row["metric_profile"]["primary_offense"]["delta_kind"] == "MEASURED"
    assert row["offense_coverage"]["state"] == "FULL"


# --------------------------------------------------------------------------- Infernal Hound


def test_minion_damage_ring_is_measured_on_the_minion_actor(real_pob_engine, tmp_path: Path) -> None:
    candidate = _equipped_item(HOUND, "Ring 1") + "\nMinions deal 30% increased Damage\n"
    baseline = _fresh(real_pob_engine, HOUND)
    expected = _fresh(real_pob_engine, _variant(HOUND, tmp_path, "ring", slots={"Ring 1": candidate}))
    # The player deals no damage of their own; only the hound's output can carry this build.
    assert baseline.get("CombinedDPS", 0) == 0
    assert expected[MINION_FIELD] > baseline[MINION_FIELD]

    result = evaluate_item(candidate, real_pob_engine, build_path=str(HOUND))

    row = _row(result, "Ring 1")
    _assert_minion_primary(row, "SummonedHellhound")
    assert _close(row["baseline"]["metrics"][MINION_FIELD], baseline[MINION_FIELD])
    assert _close(row["candidate"]["metrics"][MINION_FIELD], expected[MINION_FIELD])
    outcome = row["evaluation_outcome"]
    assert outcome["evaluation_quality"] == "FULL"
    assert _axes(row) == {"OFFENSE": "POSITIVE", "DEFENSE": "NEUTRAL", "RECOVERY": "NEUTRAL", "UTILITY": "NEUTRAL"}
    assert outcome["verdict"] in {"MINOR_UPGRADE", "MEANINGFUL_UPGRADE", "MAJOR_UPGRADE"}
    assert all(entry["restore"]["pass"] is True for entry in result["slot_comparisons"])


def test_losing_minion_skill_levels_is_a_measured_minion_downgrade(real_pob_engine, tmp_path: Path) -> None:
    candidate = _without(_equipped_item(HOUND, "Amulet"), r"Level of all Minion Skills")
    baseline = _fresh(real_pob_engine, HOUND)
    expected = _fresh(real_pob_engine, _variant(HOUND, tmp_path, "amulet", slots={"Amulet": candidate}))
    assert expected[MINION_FIELD] < 0.7 * baseline[MINION_FIELD]

    result = evaluate_item(candidate, real_pob_engine, build_path=str(HOUND))

    row = _row(result, "Amulet")
    _assert_minion_primary(row, "SummonedHellhound")
    assert row["candidate"]["primary_skill"]["skill_id"] == "SummonInfernalHoundPlayer"
    assert _close(row["candidate"]["metrics"][MINION_FIELD], expected[MINION_FIELD])
    assert row["evaluation_outcome"]["evaluation_quality"] == "FULL"
    assert _axes(row)["OFFENSE"] == "NEGATIVE"
    assert row["evaluation_outcome"]["verdict"] == "MEANINGFUL_DOWNGRADE"
    assert result["presentation"]["verdict"] == "MEANINGFUL_DOWNGRADE"
    assert row["restore"]["pass"] is True


def test_player_defense_ring_is_a_minion_offense_versus_defense_tradeoff(real_pob_engine, tmp_path: Path) -> None:
    candidate = DEFENSE_RING.read_text(encoding="utf-8")
    baseline = _fresh(real_pob_engine, HOUND)
    expected = _fresh(real_pob_engine, _variant(HOUND, tmp_path, "defense_ring", slots={"Ring 1": candidate}))
    assert expected[MINION_FIELD] < baseline[MINION_FIELD]

    result = evaluate_item(candidate, real_pob_engine, build_path=str(HOUND))

    assert {row["pob_slot"] for row in result["slot_comparisons"]} == {"Ring 1", "Ring 2"}
    row = _row(result, "Ring 1")
    _assert_minion_primary(row, "SummonedHellhound")
    assert _close(row["candidate"]["metrics"][MINION_FIELD], expected[MINION_FIELD])
    for entry in result["slot_comparisons"]:
        assert entry["evaluation_outcome"]["evaluation_quality"] == "FULL"
        assert _axes(entry)["OFFENSE"] == "NEGATIVE" and _axes(entry)["DEFENSE"] == "POSITIVE"
        if entry["pob_slot"] == "Ring 2":
            # CORPUS-02G: this ring costs 20 Dexterity (52 -> 32), below the 45 Dexterity PoB reports as
            # required by an equipped item or gem. The requirement guard now reads PoB's real fields.
            assert entry["evaluation_outcome"]["verdict"] == "NOT_VIABLE"
            assert "ATTRIBUTE_REQUIREMENT_LOST" in {g["code"] for g in entry["evaluation_outcome"]["guardrails_applied"]}
        else:
            # SCORING-01b: -10.6% minion offense for +5.3% EHP is a material trade-off with a net score of -6.5. A
            # conflict holds an upgrade back but never softens a downgrade the score reads: MINOR DOWNGRADE.
            outcome = entry["evaluation_outcome"]
            assert outcome["item_impact"]["conflict"]["kind"] == "MATERIAL"
            assert outcome["verdict"] == "MINOR_DOWNGRADE" and outcome["final_score"] == outcome["raw_score"]
            assert "Trade-off: " in outcome["verdict_reason"]
        assert entry["restore"]["pass"] is True


def test_minion_repeated_evaluation_is_deterministic_and_restores(real_pob_engine) -> None:
    real_pob_engine.load_build(HOUND)
    original_hash = real_pob_engine.get_metrics()["fingerprint_hash"]
    original_equipment = real_pob_engine.get_equipment()
    ring = _equipped_item(HOUND, "Ring 1") + "\nMinions deal 30% increased Damage\n"

    first = evaluate_item(ring, real_pob_engine, build_path=str(HOUND))
    evaluate_item(_without(_equipped_item(HOUND, "Amulet"), r"Level of all Minion Skills"),
                  real_pob_engine, build_path=str(HOUND))
    second = evaluate_item(ring, real_pob_engine, build_path=str(HOUND))

    for slot in ("Ring 1", "Ring 2"):
        before, after = _row(first, slot), _row(second, slot)
        assert before["evaluation_outcome"]["evaluation_quality"] == after["evaluation_outcome"]["evaluation_quality"] == "FULL"
        assert before["evaluation_outcome"]["verdict"] == after["evaluation_outcome"]["verdict"]
        assert before["evaluation_outcome"]["final_score"] == after["evaluation_outcome"]["final_score"]
        assert before["candidate"]["metrics"][MINION_FIELD] == after["candidate"]["metrics"][MINION_FIELD]
    assert real_pob_engine.get_metrics()["fingerprint_hash"] == original_hash
    assert real_pob_engine.get_equipment() == original_equipment


# --------------------------------------------------------------------------- Varashta Djinns


def test_djinn_minion_levels_are_measured_and_every_djinn_component_is_reported(
    real_pob_engine, tmp_path: Path,
) -> None:
    """Regression: Ruzhan and Kelari were missing from the advanced damage components.

    PoB's Fire/Sand Djinn summon stat sets carry empty ``baseFlags``, so the bridge's
    cheap native-damage hint skipped their groups and their calculated minion output
    was never requested. Each component value is checked against a cold PoB load with
    that Djinn selected as the main skill.
    """
    candidate = _without(_equipped_item(DJINN, "Amulet"), r"Level of all Minion Skills")
    slots = {"Amulet": candidate}
    expected = {}
    for name, group in ((NAVIRA, 2), (RUZHAN, 1), (KELARI, 3)):
        before = _fresh(real_pob_engine, _variant(DJINN, tmp_path, f"base_{group}", main_group=group))
        after = _fresh(real_pob_engine, _variant(DJINN, tmp_path, f"amulet_{group}", slots=slots, main_group=group))
        assert after[MINION_FIELD] < before[MINION_FIELD]
        expected[name] = (before[MINION_FIELD], after[MINION_FIELD])

    loaded = real_pob_engine.load_build(DJINN)["build"]
    assert {1, 2, 3} <= set(loaded["native_damage_group_indices"])
    result = evaluate_item(candidate, real_pob_engine, build_path=str(DJINN))

    row = _row(result, "Amulet")
    _assert_minion_primary(row, "WaterDjinn")
    assert row["baseline"]["primary_skill"]["skill_id"] == "SummonWaterDjinnPlayer"
    assert _close(row["candidate"]["metrics"][MINION_FIELD], expected[NAVIRA][1])
    assert row["evaluation_outcome"]["evaluation_quality"] == "FULL"
    assert _axes(row)["OFFENSE"] == "NEGATIVE"
    assert row["evaluation_outcome"]["verdict"] == "MEANINGFUL_DOWNGRADE"
    assert row["restore"]["pass"] is True

    components = {entry["name"]: entry for entry in row["native_damage_discovery"]["components"]}
    for name in (RUZHAN, KELARI):
        component = components[name]
        assert component["owner"] == "MINION" and component["field"] == MINION_FIELD
        assert component["status"] == "MEASURED"
        assert _close(component["before"], expected[name][0])
        assert _close(component["after"], expected[name][1])
    # Components are reported side by side; no whole-build damage total is claimed.
    assert row["native_damage_discovery"]["full_build"]["available"] is False
    assert row["native_damage_discovery"]["overall_damage_verdict"] in {"UNCERTAIN", "NOT_DERIVED"}

    section = next(s for s in build_more_info(result["presentation"])["sections"] if s["id"] == "native_components")
    text = "\n".join(section["lines"])
    assert all(name in text for name in (NAVIRA, RUZHAN, KELARI))


def test_djinn_minion_damage_ring_is_a_measured_upgrade_and_restores(real_pob_engine, tmp_path: Path) -> None:
    candidate = _equipped_item(DJINN, "Ring 1") + "\nMinions deal 30% increased Damage\n"
    expected = _fresh(real_pob_engine, _variant(DJINN, tmp_path, "ring", slots={"Ring 1": candidate}))
    real_pob_engine.load_build(DJINN)
    original_hash = real_pob_engine.get_metrics()["fingerprint_hash"]

    first = evaluate_item(candidate, real_pob_engine, build_path=str(DJINN))
    second = evaluate_item(candidate, real_pob_engine, build_path=str(DJINN))

    row = _row(first, "Ring 1")
    _assert_minion_primary(row, "WaterDjinn")
    assert _close(row["candidate"]["metrics"][MINION_FIELD], expected[MINION_FIELD])
    assert row["evaluation_outcome"]["evaluation_quality"] == "FULL"
    assert _axes(row)["OFFENSE"] == "POSITIVE"
    assert row["evaluation_outcome"]["verdict"] in {"MINOR_UPGRADE", "MEANINGFUL_UPGRADE", "MAJOR_UPGRADE"}
    repeat = _row(second, "Ring 1")
    assert repeat["evaluation_outcome"]["verdict"] == row["evaluation_outcome"]["verdict"]
    assert repeat["evaluation_outcome"]["final_score"] == row["evaluation_outcome"]["final_score"]
    assert real_pob_engine.get_metrics()["fingerprint_hash"] == original_hash


def test_djinn_command_as_main_skill_is_truthfully_uncertain(real_pob_engine, tmp_path: Path) -> None:
    """Configuration variant: PoB's main skill set to Navira's player-cast Command effect.

    PoB then calculates no offensive output at all (not for the player, not for the
    Djinn), so there is nothing to measure and every item is PARTIAL/UNCERTAIN. This
    is one plausible way to see "UNCERTAIN for nearly every item" on a Djinn build;
    it is not a reproduction of the community report.
    """
    command = _variant(DJINN, tmp_path, "command", main_group=2, main_active_skill=2)
    identity = real_pob_engine.load_build(command)["build"]["main_skill_identity"]
    assert identity["skill_id"] == "CommandWaterDjinnBubblePlayer"
    assert identity["damage_owner"] == "PLAYER"
    raw = real_pob_engine.get_metrics()["raw"]
    assert not any(value for key, value in raw.items() if key.endswith(("DPS", "Dot")) and isinstance(value, (int, float)))

    candidate = _equipped_item(DJINN, "Ring 1") + "\nMinions deal 30% increased Damage\n"
    result = evaluate_item(candidate, real_pob_engine, build_path=str(command))

    row = _row(result, "Ring 1")
    outcome = row["evaluation_outcome"]
    assert outcome["evaluation_quality"] == "PARTIAL"
    assert "OFFENSE_MISSING" in {reason["code"] for reason in outcome["evaluation_quality_reasons"]}
    assert _axes(row)["OFFENSE"] == "UNKNOWN"
    assert outcome["verdict"] == "UNCERTAIN"
    assert result["presentation"]["verdict"] == "UNCERTAIN"
    assert row["restore"]["pass"] is True
