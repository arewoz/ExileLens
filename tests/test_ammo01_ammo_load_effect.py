"""AMMO-01 — a crossbow ammo "Load" effect is never a confident damage measure (no PoB engine).

Real-PoB counterpart: tests/integration/test_ammo01_permafrost_bolts_weapon.py.
"""

from __future__ import annotations

import pytest

from exilelens.items.diagnostics import build_item_diagnostics
from exilelens.items.primary_metric import OffenseKind, PrimaryMetricConfidence, resolve_primary_metric

pytestmark = pytest.mark.itemcheck

# The tester's measured baseline for "Load Permafrost Bolts": weapon-blind, speed = 1 / 0.8 s cast time.
LOAD_METRICS = {
    "CombinedDPS": 332.5892380189, "TotalDPS": 216.18, "AverageDamage": 172.944, "Speed": 1.25,
    "TotalDot": 0.0, "FullDPS": 0.0, "IgniteDPS": 116.4092380189, "PoisonDPS": 0.0, "BleedDPS": 0.0,
}


def _build_info(**identity_overrides) -> dict:
    identity = {
        "skill_name": "Load Permafrost Bolts", "skill_id": "PermafrostBoltsAmmoPlayer", "index": 8,
        "stat_set": "Ammunition", "stat_set_key": "PermafrostBoltsAmmoPlayer:sole-set", "stat_set_count": 1,
        "stat_set_resolved": True, "damage_owner": "PLAYER", "output_table": "mainOutput",
        "calculation_mode": "DIRECT", "ammo_load_effect": True,
    }
    identity.update(identity_overrides)
    return {"main_skill_identity": identity, "main_socket_group": 8}


def test_unredirected_ammo_load_effect_is_unresolved_not_a_measured_offense() -> None:
    selection = resolve_primary_metric(_build_info(), LOAD_METRICS)
    assert selection.selected == OffenseKind.UNRESOLVED
    assert selection.confidence == PrimaryMetricConfidence.LOW
    assert "deals no damage" in selection.reason
    payload = selection.to_dict()
    assert payload["primary_skill"]["ammo_load_effect"] is True


def test_the_guard_is_specific_to_the_ammo_load_effect() -> None:
    """The same weapon-blind figures on an ordinary effect keep resolving to the normal PoB output."""
    selection = resolve_primary_metric(_build_info(ammo_load_effect=False), LOAD_METRICS)
    assert selection.selected != OffenseKind.UNRESOLVED
    assert selection.confidence == PrimaryMetricConfidence.HIGH


def test_a_redirected_effect_is_measured_normally_and_the_redirect_is_disclosed() -> None:
    redirect = {
        "reason": "AMMO_LOAD_DEALS_NO_DAMAGE",
        "from_skill_id": "PermafrostBoltsAmmoPlayer", "from_skill_name": "Load Permafrost Bolts",
        "from_stat_set": "Ammunition", "to_skill_id": "PermafrostBoltsPlayer",
        "to_skill_name": "Permafrost Bolts", "to_stat_set": "Projectile",
    }
    info = _build_info(
        skill_name="Permafrost Bolts", skill_id="PermafrostBoltsPlayer", stat_set="Projectile",
        stat_set_key="PermafrostBoltsPlayer:sole-set", ammo_load_effect=False, effect_redirect=redirect,
    )
    selection = resolve_primary_metric(info, {**LOAD_METRICS, "CombinedDPS": 2833.4251323497, "TotalDPS": 1841.6457457494, "AverageDamage": 1397.6424146733, "IgniteDPS": 0.0806})
    assert selection.selected != OffenseKind.UNRESOLVED
    assert selection.to_dict()["primary_skill"]["effect_redirect"] == redirect


def _recommendation(baseline_text: str, candidate_text: str) -> dict:
    return {
        "pob_slot": "Weapon 1",
        "baseline": {"equipment": {"Weapon 1": baseline_text}},
        "candidate": {"equipment": {"Weapon 1": candidate_text}, "item_present": True},
        "baseline_item": {"name": "Blight Core, Bleak Crossbow", "item_id": "4"},
        "candidate_item": {"name": "Spirit Core"},
    }


def test_diagnostics_prove_which_item_each_calculation_held_in_the_replacement_slot() -> None:
    diagnostics = build_item_diagnostics({"recommendation": _recommendation("Blight Core\nBleak Crossbow", "Spirit Core\nStout Crossbow")}, {})
    state = diagnostics["build"]["replacement_slot_state"]
    assert state["slot"] == "Weapon 1"
    assert state["baseline_in_calc"]["name"] == "Blight Core, Bleak Crossbow"
    assert state["baseline_in_calc"]["item_id"] == "4"
    assert state["candidate_in_calc"]["name"] == "Spirit Core"
    assert state["candidate_item_active_in_calc"] is True
    # Privacy: hashes and names only, never item text.
    assert "Stout Crossbow" not in str(state)


def test_diagnostics_flag_a_candidate_that_never_replaced_the_equipped_item() -> None:
    same = "Spirit Core\nStout Crossbow"
    state = build_item_diagnostics({"recommendation": _recommendation(same, same)}, {})["build"]["replacement_slot_state"]
    assert state["candidate_item_active_in_calc"] is False
