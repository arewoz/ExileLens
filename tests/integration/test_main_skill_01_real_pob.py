"""MAIN-SKILL-01: actionable diagnostics when the selected main skill has no offense.

Real-PoB evidence on two different builds whose symptom looks alike ("UNCERTAIN for
every item") but whose causes differ:

* ``corpus02d2_voltaic_barrier.xml`` (the CORPUS-02D2 community build): PoB's saved
  main skill is Virtuous Barrier, a zero-damage reservation buff, in its own socket
  group. Other groups hold skills PoB does calculate (Voltaic Barrier among them).
* ``corpus02b_varashta_djinn.xml`` with the player-cast Command selected: Command and
  the Navira Djinn summon share ONE socket group. PoB calculates Navira's minion damage
  but the selected effect (Command) deals none, and the build has too many damage
  groups for the bounded fallback-component discovery to run at all (a different
  quality reason than the Voltaic case).

Every alternative shown is checked against an independent fresh PoB load with that
skill actually selected. Nothing is ever switched automatically.
"""

from __future__ import annotations

import math
import os
import re
import shutil
from pathlib import Path
from xml.etree import ElementTree

import pytest

from exilelens.items.evaluation import evaluate_item
from exilelens.items.more_info import build_more_info

ROOT = Path(__file__).resolve().parents[2]
CORPUS = ROOT / "fixtures" / "builds" / "public_corpus"
VOLTAIC = CORPUS / "corpus02d2_voltaic_barrier.xml"
DJINN = CORPUS / "corpus02b_varashta_djinn.xml"
POISON = CORPUS / "core04_poison_ailment.xml"
CODE = "MAIN_SKILL_NO_OFFENSE"
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


def _select(build: Path, dest: Path, *, group: int, active_skill: int | None = None) -> Path:
    """What the player does in PoB: choose a main skill and save the build."""
    text = build.read_text(encoding="utf-8")
    text, count = re.subn(r'mainSocketGroup="\d+"', f'mainSocketGroup="{group}"', text, count=1)
    assert count == 1
    if active_skill is not None:
        starts = [match.start() for match in re.finditer(r"<Skill ", text)]
        start = starts[group - 1]
        end = text.index(">", start)
        head, count = re.subn(r'mainActiveSkill="[^"]*"', f'mainActiveSkill="{active_skill}"', text[start:end], count=1)
        assert count == 1
        text = text[:start] + head + text[end:]
    dest.write_text(text, encoding="utf-8")
    return dest


def _row(result: dict, slot: str) -> dict:
    return next(row for row in result["slot_comparisons"] if row["pob_slot"] == slot)


def _codes(row: dict) -> list[str]:
    return [reason["code"] for reason in row["evaluation_outcome"]["evaluation_quality_reasons"]]


def _main_skill_name(engine) -> str:
    info = engine.get_build_info()
    return (info.get("build") or info)["main_skill_identity"]["skill_name"]


def _close(actual: float, expected: float) -> bool:
    return math.isclose(float(actual), float(expected), rel_tol=1e-6, abs_tol=1e-6)


LIFE_RING = _equipped_item(VOLTAIC, "Ring 1") + "\n+300 to maximum Life\n"


def test_as_exported_voltaic_build_gets_an_actionable_diagnostic(real_pob_engine) -> None:
    result = evaluate_item(LIFE_RING, real_pob_engine, build_path=str(VOLTAIC))
    assert {row["pob_slot"] for row in result["slot_comparisons"]} == {"Ring 1", "Ring 2"}

    for slot in ("Ring 1", "Ring 2"):
        row = _row(result, slot)
        outcome = row["evaluation_outcome"]
        diagnostic = outcome["main_skill_diagnostic"]
        # Identified by its real PoB name and calculation context; explained first.
        assert diagnostic["selected"]["name"] == "Virtuous Barrier"
        assert diagnostic["selected"]["skill_id"] == "VirtuousBarrierPlayer"
        assert diagnostic["selected"]["group_index"] == 3
        assert diagnostic["selected"]["context"] == "MAP"
        assert _codes(row)[0] == CODE
        assert "Virtuous Barrier" in outcome["evaluation_quality_reasons"][0]["detail"]
        # Still an honest refusal: never a confident verdict.
        assert outcome["evaluation_quality"] == "PARTIAL"
        assert outcome["verdict"] == "UNCERTAIN"
        # The legitimate defensive measurement survives.
        defense = outcome["item_impact"]["axes"]["DEFENSE"]
        assert defense["support"] == "MEASURED" and defense["direction"] == "POSITIVE"
        assert row["restore"]["pass"] is True

    # A substituted fallback component is still only a component, never the primary verdict.
    assert "OFFENSE_FALLBACK_COMPONENT" in _codes(_row(result, "Ring 1"))
    assert _row(result, "Ring 1")["evaluation_outcome"]["verdict"] == "UNCERTAIN"

    diagnostic = _row(result, "Ring 1")["evaluation_outcome"]["main_skill_diagnostic"]
    names = [alt["name"] for alt in diagnostic["alternatives"]]
    # Exactly the skills PoB calculated offense for, in PoB group order. Mace Strike is
    # absent: PoB calculates zero for it (its two-hand mace is in the inactive weapon set).
    assert names == ["Crossbow Shot", "Permafrost Bolts", "Voltaic Barrier", "Incendiary Shot", "Explosive Shot"]
    assert [alt["group_index"] for alt in diagnostic["alternatives"]] == [1, 8, 9, 11, 12]
    assert "Mace Strike" not in names and "War Banner" not in names
    assert diagnostic["alternatives_status"] == "AVAILABLE"
    assert diagnostic["auto_switched"] is False
    assert result["main_skill_diagnostic"]["selected"]["name"] == "Virtuous Barrier"

    # More Info leads with the section, lists Voltaic Barrier, and points at the recovery path.
    info = build_more_info(result["presentation"], outcome=_row(result, "Ring 1")["evaluation_outcome"])
    assert info["section_ids"][:2] == ["verdict_header", "main_skill"]
    text = "\n".join(next(section for section in info["sections"] if section["id"] == "main_skill")["lines"])
    assert "Selected in Path of Building: Virtuous Barrier (PoB group 3, MAP context)" in text
    assert "Voltaic Barrier" in text and "Reload Build" in text
    assert "Defensive changes below are still measured." in text

    # No automatic switching: PoB's own selection is untouched.
    assert _main_skill_name(real_pob_engine) == "Virtuous Barrier"


def test_listed_alternatives_are_backed_by_fresh_pob_calculations(real_pob_engine, tmp_path) -> None:
    result = evaluate_item(LIFE_RING, real_pob_engine, build_path=str(VOLTAIC))
    alternatives = {alt["name"]: alt for alt in _row(result, "Ring 1")["evaluation_outcome"]["main_skill_diagnostic"]["alternatives"]}
    for name in ("Voltaic Barrier", "Explosive Shot"):
        alt = alternatives[name]
        selected = _select(VOLTAIC, tmp_path / f"{alt['group_index']}.xml", group=alt["group_index"])
        loaded = real_pob_engine.load_build(selected)
        assert loaded["build"]["main_skill_identity"]["skill_name"] == name
        assert _close(loaded["metrics"][alt["field"]], alt["value"]), name


def test_selecting_the_skill_in_pob_and_reloading_gives_full_evaluations(real_pob_engine, tmp_path) -> None:
    """The recovery path end to end on ONE build file: evaluate, edit and save the
    selection (what the player does in PoB), evaluate again -- ExileLens reloads the
    changed file itself."""
    build = tmp_path / "player_build.xml"
    shutil.copyfile(VOLTAIC, build)
    weapon = _equipped_item(VOLTAIC, "Weapon 1") + "\n200% increased Physical Damage\n"

    before = _row(evaluate_item(weapon, real_pob_engine, build_path=str(build)), "Weapon 1")
    assert before["evaluation_outcome"]["verdict"] == "UNCERTAIN"
    assert _codes(before)[0] == CODE

    _select(VOLTAIC, build, group=9)
    os.utime(build, ns=(os.stat(build).st_atime_ns, os.stat(build).st_mtime_ns + 2_000_000_000))

    result = evaluate_item(weapon, real_pob_engine, build_path=str(build))
    after = _row(result, "Weapon 1")
    outcome = after["evaluation_outcome"]
    assert after["baseline_primary_metric"]["skill_name"] == "Voltaic Barrier"
    assert outcome["evaluation_quality"] == "FULL"
    assert outcome["verdict"] == "MEANINGFUL_UPGRADE"
    assert outcome["main_skill_diagnostic"] == {}
    assert CODE not in _codes(after)
    assert result["main_skill_diagnostic"] == {}
    info = build_more_info(result["presentation"], outcome=outcome)
    assert "main_skill" not in info["section_ids"]
    assert after["restore"]["pass"] is True


def test_djinn_command_has_a_different_cause_and_the_group_sibling_is_offered(real_pob_engine, tmp_path) -> None:
    """Command shares a socket group with the Navira Djinn: the report's one-row-per-group
    view would hide Navira, so the selected group's own effects are read too. And, unlike
    the Voltaic build, no fallback component is substituted (OFFENSE_MISSING)."""
    command = _select(DJINN, tmp_path / "command.xml", group=2, active_skill=2)
    candidate = _equipped_item(DJINN, "Ring 1") + "\nMinions deal 30% increased Damage\n"
    result = evaluate_item(candidate, real_pob_engine, build_path=str(command))
    row = _row(result, "Ring 1")
    outcome = row["evaluation_outcome"]
    diagnostic = outcome["main_skill_diagnostic"]

    assert diagnostic["selected"]["name"] == "Command"
    assert diagnostic["selected"]["group_index"] == 2
    assert _codes(row)[0] == CODE
    assert "OFFENSE_MISSING" in _codes(row) and "OFFENSE_FALLBACK_COMPONENT" not in _codes(row)
    assert outcome["verdict"] == "UNCERTAIN"

    by_name = {alt["name"]: alt for alt in diagnostic["alternatives"]}
    navira = by_name["Navira, the Last Mirage"]
    assert navira["same_group"] is True and navira["owner"] == "MINION"
    assert navira["group_index"] == 2 and navira["field"] == "Minion.CombinedDPS"
    assert "Ruzhan, the Blazing Sword" in by_name and by_name["Ruzhan, the Blazing Sword"]["same_group"] is False
    assert "same group" in "\n".join(diagnostic["recovery_steps"])
    assert _main_skill_name(real_pob_engine) == "Command"

    # Recovery: select Navira in the same group (mainActiveSkill 1) and save.
    navira_build = _select(DJINN, tmp_path / "navira.xml", group=2, active_skill=1)
    loaded = real_pob_engine.load_build(navira_build)
    assert loaded["build"]["main_skill_identity"]["skill_name"] == "Navira, the Last Mirage"
    assert _close(loaded["metrics"]["Minion.CombinedDPS"], navira["value"])
    fixed = _row(evaluate_item(candidate, real_pob_engine, build_path=str(navira_build)), "Ring 1")
    assert fixed["evaluation_outcome"]["evaluation_quality"] == "FULL"
    assert fixed["evaluation_outcome"]["main_skill_diagnostic"] == {}
    assert CODE not in _codes(fixed)


def test_builds_with_a_measurable_main_skill_are_unaffected(real_pob_engine) -> None:
    poison = _equipped_item(POISON, "Weapon 1") + "\n200% increased Physical Damage\n"
    result = evaluate_item(poison, real_pob_engine, build_path=str(POISON))
    row = _row(result, "Weapon 1")
    assert row["evaluation_outcome"]["evaluation_quality"] == "FULL"
    assert row["evaluation_outcome"]["main_skill_diagnostic"] == {}
    assert CODE not in _codes(row)
    assert result["main_skill_diagnostic"] == {}
    assert "main_skill" not in build_more_info(result["presentation"], outcome=row["evaluation_outcome"])["section_ids"]

    djinn = _equipped_item(DJINN, "Ring 1") + "\nMinions deal 30% increased Damage\n"
    djinn_result = evaluate_item(djinn, real_pob_engine, build_path=str(DJINN))
    djinn_row = _row(djinn_result, "Ring 1")
    assert djinn_row["evaluation_outcome"]["main_skill_diagnostic"] == {}
    assert CODE not in _codes(djinn_row)
