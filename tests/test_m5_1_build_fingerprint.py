"""M5.1 Build Fingerprint: a summary contract over existing evidence (no PoB, no probes run)."""

from __future__ import annotations

import pytest

from exilelens.analysis.fingerprint import (
    SCHEMA_VERSION,
    build_fingerprint,
    is_fingerprint_stale,
    profile_independent,
    with_probe_signals,
)
from exilelens.analysis.identity import AnalysisBaseline

pytestmark = pytest.mark.itemcheck

BASE = AnalysisBaseline(
    build_path="b.xml", build_name="Test", loadout="L1", item_set="1", context="MAP",
    profile="BALANCED", generation=3, fingerprint="abc123",
)
SPARK = {"main_skill_identity": {"skill_name": "Spark", "skill_id": "SparkPlayer", "damage_owner": "PLAYER"}}
RAW = {
    "CombinedDPS": 120000.0, "Speed": 4.0, "CritChance": 31.2, "CritMultiplier": 2.4,
    "Life": 1.0, "EnergyShield": 9284.0, "Mana": 500.0, "ManaPerSecondCost": 20.0, "ManaRegenRecovery": 30.0,
    "TotalEHP": 15000.0, "PhysicalMaximumHitTaken": 4000.0, "FireMaximumHitTaken": 9000.0,
    "FireResist": 75.0, "FireResistTotal": 75.0, "ColdResist": 60.0, "ColdResistTotal": 60.0, "MissingColdResist": 15.0,
    "LightningResist": 75.0, "ChaosResist": -20.0, "MissingChaosResist": 95.0, "MovementSpeedMod": 1.3,
    "Str": 100.0, "Dex": 80.0, "Int": 200.0, "ReqStr": 90.0, "ReqDex": 120.0, "ReqInt": 150.0,
}


def _fp(raw=None, info=SPARK, baseline=BASE):
    return build_fingerprint(raw=raw if raw is not None else RAW, baseline=baseline, build_info=info).to_dict()


def test_schema_version_sections_and_identity_binding() -> None:
    fp = _fp()
    assert fp["schema_version"] == SCHEMA_VERSION == 1
    assert {"identity", "offense", "defense", "resources", "requirements", "mobility", "signals", "coverage"} <= set(fp)
    assert fp["identity"] == {
        "baseline_fingerprint": "abc123", "generation": 3, "build_path": "b.xml", "build_name": "Test",
        "loadout": "L1", "item_set": "1", "context": "MAP", "primary_skill": "Spark",
    }


def test_player_offense_provenance_and_crit() -> None:
    off = _fp()["offense"]
    assert off["owner"] == "PLAYER" and off["skill"] == "Spark" and off["metric"] == "CombinedDPS"
    assert off["damage"] == {"value": 120000.0, "evidence": "OBSERVED"}
    assert off["crit"]["present"]["value"] is True and off["crit"]["chance"]["value"] == 31.2
    no_crit = _fp({**RAW, "CritChance": 0.0})["offense"]["crit"]["present"]
    assert no_crit == {"value": False, "evidence": "OBSERVED"}


def test_minion_owner_does_not_borrow_player_crit() -> None:
    info = {"main_skill_identity": {"skill_name": "Raise Zombie", "damage_owner": "MINION"}}
    raw = {**RAW, "Minion.CombinedDPS": 5000.0}
    off = _fp(raw, info)["offense"]
    assert off["owner"] == "MINION" and off["metric"] == "Minion.CombinedDPS"
    assert off["damage"]["value"] == 5000.0
    assert off["crit"]["present"] == {"value": None, "evidence": "UNAVAILABLE"}
    assert "MINION" in off["crit"]["reason_unavailable"]


def test_low_confidence_primary_metric_is_preserved() -> None:
    off = _fp({k: v for k, v in RAW.items() if k != "CombinedDPS"}, {})["offense"]
    assert off["confidence"] == "LOW" and off["damage"]["evidence"] == "UNAVAILABLE"


def test_life_es_and_hybrid_pools() -> None:
    es = _fp()["defense"]
    assert es["energy_shield"]["present"]["value"] is True and es["life"]["present"]["value"] is False
    assert es["pool_share"]["energy_shield"]["value"] == pytest.approx(1.0, abs=1e-3)
    assert es["pool_share"]["energy_shield"]["evidence"] == "DERIVED"
    life = _fp({**RAW, "Life": 5000.0, "EnergyShield": 0.0})["defense"]
    assert life["life"]["present"]["value"] is True and life["energy_shield"]["present"]["value"] is False
    hybrid = _fp({**RAW, "Life": 3000.0, "EnergyShield": 1000.0})["defense"]["pool_share"]
    assert hybrid["life"]["value"] == 0.75 and hybrid["energy_shield"]["value"] == 0.25


def test_resistance_cap_states_come_from_the_existing_audit() -> None:
    res = _fp()["defense"]["resistances"]
    assert res["fire"]["state"]["value"] == "CAPPED" and res["cold"]["state"]["value"] == "BELOW_CAP"
    assert res["cold"]["missing"]["value"] == 15.0 and res["chaos"]["state"]["value"] == "BELOW_CAP"
    assert _fp()["defense"]["worst_max_hit"]["value"]["value"] == 4000.0


def test_resource_pressure_and_separate_recovery() -> None:
    assert _fp()["resources"]["mana"]["sustain"]["value"] == "SUSTAINED"
    pressured = _fp({**RAW, "ManaPerSecondCost": 50.0})["resources"]
    assert pressured["mana"]["sustain"] == {"value": "PRESSURED", "evidence": "DERIVED"}
    assert set(pressured) >= {"life", "energy_shield", "spirit"}  # Life and ES recovery stay separate
    unknown = _fp({k: v for k, v in RAW.items() if k != "ManaRegenRecovery"})["resources"]["mana"]["sustain"]
    assert unknown["evidence"] == "UNAVAILABLE"


def test_attribute_margins_and_deficits() -> None:
    req = _fp()["requirements"]
    assert req["strength"]["margin"] == {"value": 10.0, "evidence": "DERIVED"}
    assert req["strength"]["state"]["value"] == "MET"
    assert req["dexterity"]["margin"]["value"] == -40.0 and req["dexterity"]["state"]["value"] == "DEFICIT"
    missing = _fp({k: v for k, v in RAW.items() if k != "ReqInt"})["requirements"]["intelligence"]
    assert missing["state"]["evidence"] == "UNAVAILABLE"
    assert _fp()["mobility"]["movement_speed_mod"]["value"] == 1.3


def _probe(status, **extra):
    return {
        "probe_id": extra.pop("probe_id", "CAST_SPEED"), "status": status, "family": "offense",
        "magnitude": 10, "unit": "%", "confidence": "HIGH", **extra,
    }


def test_probe_statuses_stay_distinguishable() -> None:
    ok = _probe(
        "ok", offense_percent=6.8, ehp_percent=0.0, score_delta=4.1, marginal_value_per_unit=0.41,
        metric_profile={"worst_max_hit": {"percent_delta": 0.0}}, breakpoints=[{"code": "CAP_REACHED"}],
    )
    probes = [
        ok,
        _probe("NO_SIGNAL", probe_id="LIFE"),
        _probe("UNSUPPORTED_PROBE", probe_id="X"),
        _probe("REJECTED", probe_id="Y"),
        _probe("RESTORE_FAILED", probe_id="Z"),
        {"probe_id": "CAST_SPEED", "status": "ok", "nonlinear_sample": True},
        {"probe_id": "CAST_SPEED", "status": "curve", "samples": []},
    ]
    fp = with_probe_signals(_fp(), probes)
    sig = fp["signals"]
    assert sig["CAST_SPEED"]["status"] == "MEASURED" and sig["CAST_SPEED"]["offense_percent"] == 6.8
    assert sig["CAST_SPEED"]["breakpoints"] == ["CAP_REACHED"]
    assert sig["CAST_SPEED"]["profile_dependent"]["score_delta"] == 4.1
    assert [sig[k]["status"] for k in ("LIFE", "X", "Y", "Z")] == ["NO_SIGNAL", "UNSUPPORTED", "REJECTED", "RESTORE_FAILED"]
    assert "offense_percent" not in sig["Z"]  # a failed probe carries no relevance claim
    assert fp["coverage"]["signals_by_status"]["MEASURED"] == ["CAST_SPEED"] and fp["coverage"]["signals_measured"]


def test_profile_change_leaves_profile_independent_facts_unchanged() -> None:
    probes = [_probe("ok", offense_percent=6.8, ehp_percent=1.0, score_delta=4.1, marginal_value_per_unit=0.4)]
    balanced = with_probe_signals(_fp(), probes)
    rescored = with_probe_signals(balanced, [{**probes[0], "score_delta": 9.9, "marginal_value_per_unit": 0.99}])
    assert rescored["signals"]["CAST_SPEED"]["profile_dependent"]["score_delta"] == 9.9
    assert balanced != rescored and profile_independent(balanced) == profile_independent(rescored)
    assert balanced["offense"] == rescored["offense"] == _fp()["offense"]


def test_fingerprint_is_stale_for_another_baseline() -> None:
    fp = _fp()
    assert not is_fingerprint_stale(fp, BASE)
    for change in ({"fingerprint": "zzz"}, {"generation": 4}, {"loadout": "L2"}, {"item_set": "2"}, {"context": "BOSS"}):
        assert is_fingerprint_stale(fp, AnalysisBaseline(**{**BASE.to_dict(), **change}))
    assert not is_fingerprint_stale(fp, AnalysisBaseline(**{**BASE.to_dict(), "profile": "MAPPING"}))
