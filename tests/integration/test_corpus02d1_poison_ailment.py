"""CORPUS-02D1: poison and damaging-ailment Item Check on real PoB builds.

Fixtures (reused, see docs/CORPUS-02D1.md):

* ``core04_poison_ailment.xml`` -- Huntress/Ritualist, Poisonburst Arrow on its
  "Poison Burst" stat set, which deals no hit damage in game (PoB data stat
  ``display_statset_no_hit_damage``); PoB still reports a fake poison-sizing hit.
* ``core04_weapon_swap.xml`` -- the same skill on the second weapon set, whose
  Ring 1 is Kalandra's Touch (PoB ignores lines added to it).

Edited copies of the poison build cover the stat set that really hits ("Arrow")
and a configured poison-stack count. Every numeric expectation is checked against
an independent cold PoB load of an edited copy of the build, never against
ExileLens's own scoring.
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
BUILD = ROOT / "fixtures" / "builds" / "public_corpus" / "core04_poison_ailment.xml"
WEAPON_SWAP_BUILD = ROOT / "fixtures" / "builds" / "public_corpus" / "core04_weapon_swap.xml"
STAT_SET_LINE = '<StatSetIndex grantedEffect="PoisonBurstArrowPlayer" index="2"/>'
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


def _edit(raw: str, *, remove: tuple[str, ...] = (), add: tuple[str, ...] = ()) -> str:
    lines = raw.splitlines()
    for pattern in remove:
        kept = [line for line in lines if not re.search(pattern, line)]
        assert len(kept) == len(lines) - 1, pattern
        lines = kept
    return "\n".join([*lines, *add]) + "\n"


def _variant(tmp_path: Path, name: str, *, slots: dict[str, str] | None = None, arrow_stat_set: bool = False,
             poison_stacks: int | None = None) -> Path:
    """Write an edited copy of the poison build."""
    text = BUILD.read_text(encoding="utf-8")
    new_items = []
    for index, (slot, raw) in enumerate((slots or {}).items()):
        item_id = str(900 + index)
        new_items.append(f'\t\t<Item id="{item_id}">\n{escape(raw.strip())}\n\t\t</Item>\n')
        text, count = re.subn(
            rf'(<Slot itemId=")\d+(" itemPbURL="" name="{re.escape(slot)}"/>)', rf"\g<1>{item_id}\g<2>", text,
        )
        assert count == 1, slot
    if new_items:
        text = text.replace('\t\t<ItemSet id="1"', "".join(new_items) + '\t\t<ItemSet id="1"', 1)
    if arrow_stat_set:
        assert text.count(STAT_SET_LINE) == 1
        text = text.replace(STAT_SET_LINE, STAT_SET_LINE.replace('index="2"', 'index="1"'))
    if poison_stacks is not None:
        anchor = '\t\t<ConfigSet id="1">\n'
        assert text.count(anchor) == 1
        text = text.replace(anchor, anchor + f'\t\t\t<Input name="multiplierPoisonOnEnemy" number="{poison_stacks}"/>\n')
    path = tmp_path / f"{name}.xml"
    path.write_text(text, encoding="utf-8")
    return path


def _fresh_metrics(engine, tmp_path: Path, name: str, **edits) -> dict:
    engine.load_build(_variant(tmp_path, name, **edits))
    return engine.get_metrics()["raw"]


def _close(actual: float, expected: float) -> bool:
    return math.isclose(float(actual), float(expected), rel_tol=1e-6, abs_tol=1e-6)


def _row(result: dict, slot: str) -> dict:
    return next(row for row in result["slot_comparisons"] if row["pob_slot"] == slot)


def _factor(row: dict, field: str) -> dict:
    return next(entry for entry in row["ailment_breakdown"]["factors"] if entry["field"] == field)


QUIVER = _equipped_item(BUILD, "Weapon 2")
GLOVES = _equipped_item(BUILD, "Gloves")
MAGNITUDE_QUIVER = _edit(QUIVER, add=("40% increased Magnitude of Poison you inflict",))
DURATION_QUIVER = _edit(QUIVER, add=("30% increased Poison Duration",))
STACK_QUIVER = _edit(QUIVER, add=("Targets can be affected by +1 of your Poisons at the same time",))
DURATION_STACK_QUIVER = _edit(QUIVER, add=(
    "30% increased Poison Duration", "Targets can be affected by +1 of your Poisons at the same time",
))
SLOW_GLOVES = _edit(GLOVES, remove=("14% increased Attack Speed",))
TRADEOFF_GLOVES = _edit(GLOVES, remove=("99% increased Energy Shield",), add=("16% increased Attack Speed",))


def test_poison_magnitude_upgrade_is_fully_measured_and_matches_a_fresh_load(real_pob_engine, tmp_path) -> None:
    result = evaluate_item(MAGNITUDE_QUIVER, real_pob_engine, build_path=str(BUILD))
    row = _row(result, "Weapon 2")
    outcome = row["evaluation_outcome"]

    assert row["baseline_primary_metric"]["pob_field"] == "PoisonDPS"
    assert result["offense_coverage"]["state"] == "FULL"
    assert result["offense_coverage"]["dimension_evidence"]["POISON_DURATION"] == "RESPONSIVE"
    assert outcome["evaluation_quality"] == "FULL"
    assert outcome["verdict"] == "MEANINGFUL_UPGRADE"
    assert outcome["item_impact"]["axes"]["OFFENSE"]["magnitude_pct"] == pytest.approx(9.24, abs=0.01)
    assert _factor(row, "PoisonMagnitudeEffect")["percent_delta"] == pytest.approx(9.24, abs=0.01)
    assert row["ailment_breakdown"]["composition"]["status"] == "EXPLAINED"
    assert row["restore"]["pass"] is True

    candidate = row["candidate"]["metrics"]
    fresh = _fresh_metrics(real_pob_engine, tmp_path, "magnitude", slots={"Weapon 2": MAGNITUDE_QUIVER})
    for field in ("PoisonDPS", "CombinedDPS", "TotalDPS", "PoisonMagnitudeEffect", "TotalEHP"):
        assert _close(candidate[field], fresh[field]), field


def test_duration_and_stack_cap_interaction_follows_pob(real_pob_engine, tmp_path) -> None:
    """PoisonStackPotential 0.94 of 4 stacks: more duration is partly capped by the
    stack limit, an extra stack alone changes nothing, and both together scale fully."""
    rows = {
        name: _row(evaluate_item(raw, real_pob_engine, build_path=str(BUILD)), "Weapon 2")
        for name, raw in (("duration", DURATION_QUIVER), ("stack", STACK_QUIVER), ("both", DURATION_STACK_QUIVER))
    }
    duration, stack, both = rows["duration"], rows["stack"], rows["both"]

    assert _factor(duration, "PoisonDuration")["percent_delta"] == pytest.approx(20.0, abs=1e-6)
    assert _factor(duration, "PoisonStackPotential")["after"] > 1.0
    assert duration["evaluation_outcome"]["item_impact"]["axes"]["OFFENSE"]["magnitude_pct"] == pytest.approx(15.59, abs=0.01)
    assert duration["evaluation_outcome"]["verdict"] == "MEANINGFUL_UPGRADE"

    assert _factor(stack, "PoisonStacksMax")["after"] == 5
    assert stack["metric_profile"]["primary_offense"]["delta_kind"] == "MEASURED_ZERO"
    assert stack["evaluation_outcome"]["evaluation_quality"] == "FULL"
    assert stack["evaluation_outcome"]["verdict"] == "SIDEGRADE"

    assert both["evaluation_outcome"]["item_impact"]["axes"]["OFFENSE"]["magnitude_pct"] == pytest.approx(20.0, abs=0.01)
    assert both["evaluation_outcome"]["evaluation_quality"] == "FULL"

    for name, raw in (("duration", DURATION_QUIVER), ("both", DURATION_STACK_QUIVER)):
        fresh = _fresh_metrics(real_pob_engine, tmp_path, name, slots={"Weapon 2": raw})
        assert _close(rows[name]["candidate"]["metrics"]["PoisonDPS"], fresh["PoisonDPS"]), name


def test_attack_speed_downgrade_and_offense_defense_tradeoff(real_pob_engine, tmp_path) -> None:
    slow = _row(evaluate_item(SLOW_GLOVES, real_pob_engine, build_path=str(BUILD)), "Gloves")
    assert slow["evaluation_outcome"]["evaluation_quality"] == "FULL"
    assert slow["evaluation_outcome"]["verdict"] == "MEANINGFUL_DOWNGRADE"
    assert slow["evaluation_outcome"]["item_impact"]["axes"]["OFFENSE"]["magnitude_pct"] == pytest.approx(-11.48, abs=0.01)
    # Fewer hits per second means fewer active poisons: PoB lowers the stack potential.
    assert _factor(slow, "PoisonStackPotential")["percent_delta"] == pytest.approx(-11.48, abs=0.01)

    trade = _row(evaluate_item(TRADEOFF_GLOVES, real_pob_engine, build_path=str(BUILD)), "Gloves")
    outcome = trade["evaluation_outcome"]
    assert outcome["evaluation_quality"] == "FULL"
    assert outcome["verdict"] == "SIDEGRADE"
    assert outcome["verdict_reason"].startswith("Meaningful trade-off")
    assert outcome["item_impact"]["axes"]["OFFENSE"]["direction"] == "POSITIVE"
    assert outcome["item_impact"]["axes"]["DEFENSE"]["direction"] == "NEGATIVE"
    assert outcome["item_impact"]["axes"]["OFFENSE"]["magnitude_pct"] == pytest.approx(10.95, abs=0.01)

    for name, raw, row in (("slow", SLOW_GLOVES, slow), ("trade", TRADEOFF_GLOVES, trade)):
        fresh = _fresh_metrics(real_pob_engine, tmp_path, name, slots={"Gloves": raw})
        for field in ("PoisonDPS", "TotalEHP", "EnergyShield"):
            assert _close(row["candidate"]["metrics"][field], fresh[field]), (name, field)


def test_fake_hit_is_excluded_and_repeated_evaluations_restore_exactly(real_pob_engine) -> None:
    first = evaluate_item(MAGNITUDE_QUIVER, real_pob_engine, build_path=str(BUILD))
    second = evaluate_item(MAGNITUDE_QUIVER, real_pob_engine, build_path=str(BUILD))
    first_row, second_row = _row(first, "Weapon 2"), _row(second, "Weapon 2")

    breakdown = first_row["ailment_breakdown"]
    assert breakdown["hit_damage_real"] is False
    assert breakdown["combined_includes_fake_hit"] is True
    roles = {entry["field"]: entry["role"] for entry in breakdown["components"]}
    assert roles["TotalDPS"] == "EXCLUDED_NO_HIT_DAMAGE"
    assert roles["PoisonDPS"] == "SCORED"
    assert {entry["role"] for entry in breakdown["factors"]} == {"INCORPORATED"}

    assert first_row["evaluation_outcome"]["evaluation_quality"] == "FULL"
    assert second_row["evaluation_outcome"]["evaluation_quality"] == "FULL"
    assert first_row["evaluation_outcome"]["final_score"] == second_row["evaluation_outcome"]["final_score"]
    assert first_row["evaluation_outcome"]["verdict"] == second_row["evaluation_outcome"]["verdict"]
    assert first_row["candidate"]["metrics"]["PoisonDPS"] == second_row["candidate"]["metrics"]["PoisonDPS"]
    assert first_row["restore"]["pass"] is True and second_row["restore"]["pass"] is True

    restored = real_pob_engine.get_metrics()["raw"]
    baseline = first_row["baseline"]["metrics"]
    for field in ("PoisonDPS", "CombinedDPS", "PoisonStackPotential", "PoisonMagnitudeEffect", "TotalEHP"):
        assert restored[field] == baseline[field], field


def test_real_hit_stat_set_scores_pobs_combined_hit_and_poison(real_pob_engine, tmp_path) -> None:
    """The "Arrow" stat set really hits (~19% of CombinedDPS): losing poison chance
    while gaining hit damage is measured on PoB's own hit + poison sum."""
    build = _variant(tmp_path, "arrow", arrow_stat_set=True)
    candidate = _edit(QUIVER, remove=("30% chance to Poison",), add=("60% increased Damage with Bow Skills",))
    row = _row(evaluate_item(candidate, real_pob_engine, build_path=str(build)), "Weapon 2")
    outcome = row["evaluation_outcome"]

    assert row["baseline"]["primary_skill"]["stat_set"] == "Arrow"
    assert row["baseline_primary_metric"]["pob_field"] == "CombinedDPS"
    assert row["baseline_primary_metric"]["semantic_quantity"] == "HIT_PLUS_AILMENT"
    breakdown = row["ailment_breakdown"]
    assert breakdown["hit_damage_real"] is True
    assert breakdown["composition"]["status"] == "EXPLAINED"
    assert breakdown["hit_percent_delta"] == pytest.approx(12.43, abs=0.01)
    assert breakdown["ailment_percent_delta"] == pytest.approx(-42.02, abs=0.01)
    assert _factor(row, "PoisonChancePerHit")["after"] == pytest.approx(44.8)
    assert outcome["evaluation_quality"] == "FULL"
    assert outcome["verdict"] == "MEANINGFUL_DOWNGRADE"
    assert outcome["item_impact"]["axes"]["OFFENSE"]["magnitude_pct"] == pytest.approx(-31.54, abs=0.01)
    assert row["restore"]["pass"] is True

    fresh = _fresh_metrics(real_pob_engine, tmp_path, "arrow_candidate", slots={"Weapon 2": candidate},
                           arrow_stat_set=True)
    for field in ("CombinedDPS", "TotalDPS", "PoisonDPS"):
        assert _close(row["candidate"]["metrics"][field], fresh[field]), field


def test_configured_poison_stack_count_keeps_a_specific_uncertainty(real_pob_engine, tmp_path) -> None:
    """With "# of Poisons on enemy" configured, PoB fixes the active stacks, so
    attack speed and duration no longer move PoisonDPS. That is refused specifically."""
    build = _variant(tmp_path, "configured_stacks", poison_stacks=3)
    result = evaluate_item(SLOW_GLOVES, real_pob_engine, build_path=str(build))
    row = _row(result, "Gloves")
    outcome = row["evaluation_outcome"]

    assert result["offense_coverage"]["dimension_evidence"]["POISON_DURATION"] == "INSENSITIVE"
    assert result["offense_coverage"]["scope_gap"] == "AILMENT_STACK_SCOPE_UNPROVEN"
    assert outcome["evaluation_quality"] == "PARTIAL"
    assert outcome["verdict"] == "UNCERTAIN"
    assert "stack count" in outcome["evaluation_quality_reasons"][0]["detail"]
    assert row["restore"]["pass"] is True


def test_inert_probe_carrier_is_skipped(real_pob_engine) -> None:
    """Kalandra's Touch in Ring 1 ignores added lines; the audit moves to Ring 2."""
    quiver = _equipped_item(WEAPON_SWAP_BUILD, "Weapon 2 Swap")
    result = evaluate_item(quiver + "\n50% increased Attack Speed\n", real_pob_engine,
                           build_path=str(WEAPON_SWAP_BUILD))
    coverage = result["offense_coverage"]
    assert coverage["carrier_slot"] == "Ring 2"
    assert "Inert probe carriers skipped: Ring 1." in coverage["reason"]
    assert coverage["state"] == "FULL"
    assert _row(result, "Weapon 2")["evaluation_outcome"]["evaluation_quality"] == "FULL"
