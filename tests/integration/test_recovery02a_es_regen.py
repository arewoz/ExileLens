"""RECOVERY-02A: a real PoB ES-regeneration effect remains a distinct recovery channel."""

from __future__ import annotations

from pathlib import Path

import pytest

from exilelens.items.evaluation import evaluate_item


ROOT = Path(__file__).resolve().parents[2]
BUILD = ROOT / "fixtures" / "builds" / "public_corpus" / "recovery02a_es_regen_invoker.xml"
CANONICAL_EFFECT = "Regenerate 1% of maximum Energy Shield per second"
pytestmark = [pytest.mark.integration, pytest.mark.real_pob, pytest.mark.itemcheck]


def _boots(engine) -> str:
    equipment = {entry["physical_slot"]: entry.get("raw", "") for entry in engine.get_equipment()["equipment"]}
    return equipment["Boots"]


def _row(result: dict, slot: str) -> dict:
    return next(row for row in result["slot_comparisons"] if row["pob_slot"] == slot)


def test_authentic_invoker_boots_gain_real_es_regeneration_and_restore(real_pob_engine) -> None:
    real_pob_engine.load_build(BUILD)
    baseline = real_pob_engine.get_metrics()
    boots = _boots(real_pob_engine)
    candidate = boots + "\n" + CANONICAL_EFFECT + "\n"

    direct = real_pob_engine.evaluate_item_slots(["Boots"], candidate)
    final = direct["slots"][0]["candidate"]["metrics"]
    # pobb.in recorded 9,365 ES for this export; the pinned local PoB revision recalculates 9,284.
    assert baseline["raw"]["EnergyShield"] > 1
    assert baseline["raw"]["EnergyShieldRegenRecovery"] == 0
    assert final["EnergyShieldRegenRecovery"] > 0
    assert direct["restore"]["pass"] is True
    assert real_pob_engine.get_metrics()["fingerprint_hash"] == baseline["fingerprint_hash"]

    row = _row(evaluate_item(candidate, real_pob_engine, build_path=str(BUILD)), "Boots")
    assert row["evaluation_outcome"]["evaluation_quality"] == "FULL"
    assert row["restore"]["pass"] is True
    impact = row["evaluation_outcome"]["item_impact"]
    recovery = impact["axes"]["RECOVERY"]
    es = next(metric for metric in recovery["metrics"] if metric["key"] == "EnergyShieldRegenRecovery")
    assert es["current"] == 0 and es["candidate"] > 0
    assert es["from_zero"] is True and es["pool_pct"] > 0.5
    assert "Energy Shield Regeneration" in " ".join(impact["reasons"])
    components = row["build_comparison"]["axes"]["RECOVERY"]["components"]
    assert components["life_regen"]["label"] == "Life Regen"
    assert components["energy_shield_regen"]["label"] == "Energy Shield Regen"
