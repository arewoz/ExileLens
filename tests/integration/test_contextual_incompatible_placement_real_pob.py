"""FIX-02 real-PoB gate: cross-base weapon placements fail clean, never corrupt.

Root cause (proven on `core04_weapon_swap`, active set 2 / bow+quiver vs
spear+shield): PoB's own `IsItemValidForSlot` accepts any one/two-hand
weapon in `Weapon 1`, but placing a conflicting base type deselects the
paired same-set offhand as a side effect (2H-bow vs shield, spear vs
quiver). Reverting only the requested physical slot cannot undo that, so
the old code surfaced it at final verification as RESTORE_FAILED and
poisoned the worker. The transaction now verifies every non-target
physical slot before and after the candidate frame and reverts all slots;
a disturbed pairing aborts to UNAVAILABLE/NOT_VALID_IN_CONTEXT with the
disturbed slots named, restore verified, worker healthy. A genuine
restore failure still raises RESTORE_FAILED (see the corrupt-restore test
in `test_weapon_set_component_contexts.py`).
"""

from __future__ import annotations

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
WEAPON_SWAP = ROOT / "fixtures" / "builds" / "public_corpus" / "core04_weapon_swap.xml"
pytestmark = [pytest.mark.integration, pytest.mark.real_pob, pytest.mark.itemcheck]


def _fresh_refs(engine):
    loaded = engine.load_build(WEAPON_SWAP)
    count = int((loaded.get("build") or {}).get("skill_group_count") or 0)
    refs = {}
    for index in range(1, count + 1):
        catalog = engine.list_calculable_effects(indices=[index])
        for row in catalog.get("effects") or []:
            refs[row["reference"]["effect_id"]] = row["reference"]
    physical = engine.get_weapon_set_context()["physical_weapons"]
    return refs, physical


def test_compatible_same_base_replacements_still_measure(real_pob_engine) -> None:
    refs, physical = _fresh_refs(real_pob_engine)
    bow = physical["Weapon 1 Swap"] + "\n500% increased Physical Damage\n"
    spear = physical["Weapon 1"] + "\n500% increased Physical Damage\n"

    primary = real_pob_engine.evaluate_effect_candidate(
        refs["EscapeShotPlayer"], weapon_set=2, physical_slot="Weapon 1 Swap", item_raw=bow
    )
    assert primary["status"] == "MEASURED"
    assert primary["restore"]["pass"] is True
    assert "disturbed_slots" not in primary

    alternate = real_pob_engine.evaluate_effect_candidate(
        refs["SpearThrowPlayer"], weapon_set=1, physical_slot="Weapon 1", item_raw=spear
    )
    assert alternate["status"] == "MEASURED"
    assert alternate["restore"]["pass"] is True
    assert "disturbed_slots" not in alternate


def test_cross_base_offhand_disturbance_is_unavailable_not_corrupt(real_pob_engine) -> None:
    refs, physical = _fresh_refs(real_pob_engine)
    before = real_pob_engine.get_metrics()["fingerprint_hash"]
    spear = physical["Weapon 1"] + "\n500% increased Physical Damage\n"

    result = real_pob_engine.evaluate_effect_candidate(
        refs["EscapeShotPlayer"], weapon_set=2, physical_slot="Weapon 1 Swap", item_raw=spear
    )
    assert result["status"] == "UNAVAILABLE"
    assert result["reason"] == "NOT_VALID_IN_CONTEXT"
    assert result["disturbed_slots"] == ["Weapon 2 Swap"]
    assert result["restore"]["pass"] is True
    assert "output" not in (result.get("candidate") or {})
    assert real_pob_engine.get_metrics()["fingerprint_hash"] == before

    # Worker stays healthy: the very next transaction measures normally.
    bow = physical["Weapon 1 Swap"] + "\n500% increased Physical Damage\n"
    followup = real_pob_engine.evaluate_effect_candidate(
        refs["EscapeShotPlayer"], weapon_set=2, physical_slot="Weapon 1 Swap", item_raw=bow
    )
    assert followup["status"] == "MEASURED"
    assert followup["restore"]["pass"] is True


def test_cross_base_primary_disturbance_is_unavailable_not_corrupt(real_pob_engine) -> None:
    refs, physical = _fresh_refs(real_pob_engine)
    before = real_pob_engine.get_metrics()["fingerprint_hash"]
    bow = physical["Weapon 1 Swap"] + "\n500% increased Physical Damage\n"

    result = real_pob_engine.evaluate_effect_candidate(
        refs["SpearThrowPlayer"], weapon_set=1, physical_slot="Weapon 1", item_raw=bow
    )
    assert result["status"] == "UNAVAILABLE"
    assert result["reason"] == "NOT_VALID_IN_CONTEXT"
    assert result["disturbed_slots"] == ["Weapon 2"]
    assert result["restore"]["pass"] is True
    assert real_pob_engine.get_metrics()["fingerprint_hash"] == before
    assert real_pob_engine.get_weapon_set_context()["weapon_set"] == 2
