from __future__ import annotations

import pytest

from exilelens.items.item_impact import interpret_item_impact


pytestmark = pytest.mark.itemcheck


def _raw(**values: float) -> dict[str, float]:
    return {"CombinedDPS": 100.0, "TotalEHP": 1_000.0, "Life": 1_000.0, "EnergyShield": 5_000.0, **values}


def _impact(before: dict[str, float], after: dict[str, float]):
    return interpret_item_impact({}, {}, before, after).to_dict()["axes"]["RECOVERY"]


def test_life_regen_remains_its_own_recovery_channel() -> None:
    axis = _impact(_raw(LifeRegenRecovery=10.0), _raw(LifeRegenRecovery=20.0))

    life = next(metric for metric in axis["metrics"] if metric["key"] == "LifeRegenRecovery")
    es = next(metric for metric in axis["metrics"] if metric["key"] == "EnergyShieldRegenRecovery")
    assert life["absolute_delta"] == 10.0 and life["pool_pct"] == 1.0
    assert es["support"] == "UNMEASURED"
    assert axis["direction"] == "POSITIVE" and axis["material_positive"] is True


def test_zero_to_positive_es_regen_uses_es_pool_without_inventing_relative_percent() -> None:
    axis = _impact(_raw(EnergyShieldRegenRecovery=0.0), _raw(EnergyShieldRegenRecovery=50.0))

    es = next(metric for metric in axis["metrics"] if metric["key"] == "EnergyShieldRegenRecovery")
    assert es["percent_delta"] is None
    assert es["from_zero"] is True
    assert es["absolute_delta"] == 50.0 and es["pool_pct"] == 1.0
    assert axis["direction"] == "POSITIVE" and axis["material_positive"] is True


def test_opposite_life_and_es_regeneration_deltas_remain_mixed() -> None:
    before = _raw(LifeRegenRecovery=100.0, EnergyShieldRegenRecovery=100.0)
    after = _raw(LifeRegenRecovery=80.0, EnergyShieldRegenRecovery=150.0)

    axis = _impact(before, after)
    assert axis["direction"] == "MIXED"
    assert axis["material_positive"] is True and axis["material_negative"] is True
    assert {metric["key"] for metric in axis["metrics"]} == {
        "LifeRegenRecovery", "EnergyShieldRegenRecovery",
    }
