"""PERF-01 (real PoB): re-asserting the loadout / item set that is already active is free and changes nothing.

Item Check, the tree snapshot and the baseline capture each re-assert the active loadout and item set before they read.
Each of those was a full PoB recalculation (130-420 ms per call measured). The bridge now skips the activation and the
recalculation when PoB itself reports exactly that identity AND has nothing pending; the settle and the response are never
skipped. These tests pin that the skipped path is indistinguishable from the forced one, and that a real change is still
applied.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from exilelens.items.evaluation import evaluate_item
from tests.integration.test_ammo01_state_matrix import ALT, FIRED_SAVED, LOAD_SAVED, _two_loadout_build

pytestmark = [pytest.mark.integration, pytest.mark.real_pob, pytest.mark.itemcheck]

ROOT = Path(__file__).resolve().parents[2]
CORPUS = ROOT / "fixtures" / "builds" / "public_corpus"
BUILDS = ("core04_melee_weapon", "corpus02e_spell_totem_titan")


def _canonical(value) -> str:
    return json.dumps(value, sort_keys=True, default=str)


def _state(engine) -> dict:
    metrics = engine.get_metrics("MAP")
    info = engine.get_build_info()
    return {
        "fingerprint": metrics.get("fingerprint_hash"),
        "raw": metrics.get("raw"),
        "identity": (info.get("build") or {}).get("main_skill_identity"),
        "active_loadout": (info.get("build") or {}).get("active_loadout"),
        "active_item_set_id": (info.get("build") or {}).get("active_item_set_id"),
    }


def _force(engine, method: str, params: dict) -> dict:
    return engine._call(method, {**params, "force": True})


@pytest.mark.parametrize("build", BUILDS)
def test_reasserting_the_active_identity_is_a_noop_and_matches_the_forced_path(real_pob_engine, build: str) -> None:
    engine = real_pob_engine
    engine.load_build(CORPUS / f"{build}.xml", context="MAP")
    loadout = engine.list_loadouts()["active"]
    item_set = engine.list_item_sets()["active_id"]
    before = _state(engine)

    skipped_loadout = engine.set_active_loadout(loadout)
    skipped_item_set = engine.set_active_item_set(item_set)
    after_skipped = _state(engine)
    forced_loadout = _force(engine, "set_active_loadout", {"name": loadout})
    forced_item_set = _force(engine, "set_active_item_set", {"item_set_id": str(item_set)})
    after_forced = _state(engine)

    assert _canonical(after_skipped) == _canonical(before)
    assert _canonical(after_forced) == _canonical(before)
    # The responses carry the same fingerprint and metrics whichever path produced them.
    assert skipped_loadout["fingerprint"] == forced_loadout["fingerprint"]
    assert _canonical(skipped_loadout["metrics"]) == _canonical(forced_loadout["metrics"])
    assert skipped_item_set["fingerprint"] == forced_item_set["fingerprint"]
    assert _canonical(skipped_item_set["metrics"]) == _canonical(forced_item_set["metrics"])


@pytest.mark.parametrize("build", BUILDS)
def test_item_check_is_identical_with_and_without_the_skipped_recalculation(real_pob_engine, build: str) -> None:
    from xml.etree import ElementTree

    engine = real_pob_engine
    path = CORPUS / f"{build}.xml"
    root = ElementTree.parse(path).getroot()
    items = root.find("Items")
    raw = {i.get("id"): (i.text or "").strip() for i in items.findall("Item")}
    active = items.get("activeItemSet")
    item_set = next(e for e in items.findall("ItemSet") if e.get("id") == active)
    slot = "Amulet" if "Amulet" in {e.get("name") for e in item_set.findall("Slot")} else "Ring 1"
    item_id = next(e.get("itemId") for e in item_set.findall("Slot") if e.get("name") == slot)
    candidate = raw[item_id] + "\n+100 to maximum Life\n"

    def strip_volatile(result: dict) -> dict:
        text = _canonical(result)
        text = re.sub(r'"[a-z_]*(?:_ms|timings?)": (?:\{[^{}]*\}|[-0-9.e]+)', '"x": 0', text)
        return json.loads(text)

    fast_first = evaluate_item(candidate, engine, build_path=str(path), context="MAP")
    fast_second = evaluate_item(candidate, engine, build_path=str(path), context="MAP")

    original = {name: getattr(engine, name) for name in ("set_active_loadout", "set_active_item_set")}
    try:
        engine.set_active_loadout = lambda name: _force(engine, "set_active_loadout", {"name": name})  # type: ignore[method-assign]
        engine.set_active_item_set = lambda item_set_id: _force(engine, "set_active_item_set", {"item_set_id": str(item_set_id)})  # type: ignore[method-assign]
        forced = evaluate_item(candidate, engine, build_path=str(path), context="MAP", loadout=engine.list_loadouts()["active"],
                               item_set=str(engine.list_item_sets()["active_id"]))
    finally:
        for name, method in original.items():
            setattr(engine, name, method)

    fast = evaluate_item(candidate, engine, build_path=str(path), context="MAP", loadout=engine.list_loadouts()["active"],
                         item_set=str(engine.list_item_sets()["active_id"]))
    for left, right in ((fast_first, fast_second), (fast, forced)):
        for row_left, row_right in zip(left["slot_comparisons"], right["slot_comparisons"], strict=True):
            assert _canonical(row_left["baseline"]["metrics"]) == _canonical(row_right["baseline"]["metrics"])
            assert _canonical(row_left["candidate"]["metrics"]) == _canonical(row_right["candidate"]["metrics"])
            assert row_left["evaluation_outcome"]["verdict"] == row_right["evaluation_outcome"]["verdict"]
            assert row_left["evaluation_outcome"]["evaluation_quality"] == row_right["evaluation_outcome"]["evaluation_quality"]
            assert row_left["restore"]["pass"] == row_right["restore"]["pass"]
    assert fast["state_integrity"]["recovery_used"] is False


def test_a_real_loadout_or_item_set_change_is_still_applied(real_pob_engine, tmp_path: Path) -> None:
    """The skip applies to an unchanged identity only: a different loadout is activated, and returning restores state."""
    engine = real_pob_engine
    path = _two_loadout_build(tmp_path, default_saves=FIRED_SAVED, alt_saves=LOAD_SAVED, name="perf01_loadouts.xml")
    engine.load_build(path)
    default_state = _state(engine)
    assert default_state["active_loadout"] == "Default"

    engine.set_active_loadout(ALT)
    alt_state = _state(engine)
    assert alt_state["active_loadout"] == ALT
    assert alt_state["identity"] != default_state["identity"]   # the saved main effect differs between the two sets
    assert engine.list_loadouts()["active"] == ALT

    engine.set_active_item_set("2")
    assert str(engine.list_item_sets()["active_id"]) == "2"
    engine.set_active_item_set("1")
    assert str(engine.list_item_sets()["active_id"]) == "1"

    engine.set_active_loadout("Default")
    assert _canonical(_state(engine)) == _canonical(default_state)
    # And a pending recalculation is never skipped: reasserting after the switch above is a no-op, not a stale read.
    engine.set_active_loadout("Default")
    assert _canonical(_state(engine)) == _canonical(default_state)
