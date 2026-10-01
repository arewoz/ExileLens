"""M5.5: regressions for the M5.4 findings (false NO_SIGNAL, mana noise, global probe families, axis confidence, pinned resistance)."""

from __future__ import annotations

import re

import pytest

from exilelens.analysis.catalog import ProbeCatalog
from exilelens.analysis.fingerprint import build_fingerprint
from exilelens.analysis.identity import AnalysisBaseline
from exilelens.analysis.pipeline import (
    PROBE_NOT_APPLIED,
    _validated_carrier,
    analyze_build,
    item_applies_probe_mods,
    not_applied_probe,
)
from exilelens.analysis.priorities import build_priorities
from exilelens.analysis.probes import ProbeEngine
from exilelens.analysis.sensitivity import build_sensitivity

pytestmark = pytest.mark.itemcheck

BASE_RAW = {
    "CombinedDPS": 1000.0, "TotalDPS": 1000.0, "Speed": 2.0, "CritChance": 30.0, "CritMultiplier": 2.0,
    "Life": 1000.0, "EnergyShield": 500.0, "Mana": 500.0, "ManaUnreserved": 500.0, "ManaCost": 40.0,
    "ManaPerSecondCost": 80.0, "ManaRegenRecovery": 10.0, "TotalEHP": 5000.0, "PhysicalMaximumHitTaken": 3000.0,
    "FireResist": 75.0, "ColdResist": 75.0, "LightningResist": 75.0, "ChaosResist": 75.0, "MovementSpeedMod": 1.0,
    "Str": 100.0, "Dex": 100.0, "Int": 100.0, "ReqStr": 0.0, "ReqDex": 0.0, "ReqInt": 0.0,
}
_POOLS = {"Life": "Life", "Energy Shield": "EnergyShield", "Mana": "Mana"}


class FakeEngine:
    """Applies `+N to maximum <pool>` lines unless the item is one PoB rewrites (Kalandra's Touch)."""

    def __init__(self, equipment: dict[str, str]) -> None:
        self.equipment = equipment
        self.evaluations: list[str] = []

    def load_build(self, *a, **k):
        return {"fingerprint_hash": "fp"}

    def get_metrics(self, context=None):
        return {"fingerprint_hash": "fp", "raw": dict(BASE_RAW)}

    def get_equipment(self):
        return {"equipment": [{"slot": s, "equipped": True, "raw": r, "name": s, "base_name": "B"} for s, r in self.equipment.items()]}

    def get_build_info(self):
        return {"name": "fake", "main_skill_identity": {"skill_name": "Fake Skill", "damage_owner": "PLAYER"}}

    def evaluate_candidate(self, slot, raw, context=None):
        self.evaluations.append(slot)
        after = dict(BASE_RAW)
        if "Kalandra" not in self.equipment[slot]:
            for amount, pool in re.findall(r"\+(\d+) to maximum ([A-Za-z ]+)", raw):
                if pool.strip() in _POOLS:
                    after[_POOLS[pool.strip()]] += float(amount)
        return {
            "baseline": {"metrics": dict(BASE_RAW), "fingerprint_hash": "fp"},
            "candidate": {"metrics": after},
            "restored": {"fingerprint_hash": "fp"},
            "restore": {"pass": True},
        }


RING = "Rarity: RARE\nSome Ring\nRuby Ring\n"
KALANDRA = "Rarity: UNIQUE\nKalandra's Touch\nRing\nReflects opposite Ring\n"


def test_carrier_that_ignores_appended_mods_is_detected_by_capability_not_by_name() -> None:
    engine = FakeEngine({"Ring 1": KALANDRA, "Ring 2": RING})
    assert item_applies_probe_mods(engine, "Ring 1", KALANDRA, context="MAP") is False
    assert item_applies_probe_mods(engine, "Ring 2", RING, context="MAP") is True


def test_first_inert_carrier_is_skipped_and_the_next_valid_one_is_used() -> None:
    engine = FakeEngine({"Ring 1": KALANDRA, "Ring 2": RING})
    probes = ProbeEngine(engine)
    carrier, had = _validated_carrier(engine, {"Ring 1": {"equipped": True, "raw": KALANDRA}, "Ring 2": {"equipped": True, "raw": RING}}, context="MAP", probes=probes)
    assert carrier == ("Ring 2", RING) and had is True and probes.pob_recalcs == 2


def test_global_stage_measures_on_the_valid_carrier_and_reports_applied_probes() -> None:
    engine = FakeEngine({"Ring 1": KALANDRA, "Ring 2": RING})
    result = analyze_build(engine, build_path="b.xml", slot_filter="__none__")
    statuses = {p["probe_id"]: p["status"] for p in result["global_probes"] if not p.get("nonlinear_sample") and not p.get("breakpoint_exact")}
    assert statuses["LIFE"] == "ok" and statuses["ENERGY_SHIELD"] == "ok" and statuses["MANA"] == "ok"
    assert set(engine.evaluations) == {"Ring 1", "Ring 2"}  # Ring 1 only for the canary
    sig = {s["probe_id"]: s for s in result["build_sensitivity"]["signals"]}
    assert sig["LIFE"]["applied"] is True and sig["CAST_SPEED"]["status"] == "NO_SIGNAL" and sig["CAST_SPEED"]["applied"] is True


def test_no_carrier_accepts_mods_so_every_probe_is_not_established_never_no_signal() -> None:
    engine = FakeEngine({"Ring 1": KALANDRA})
    result = analyze_build(engine, build_path="b.xml", slot_filter="__none__")
    probes = result["global_probes"]
    assert probes and all(p["status"] == "REJECTED" and p["error"] == PROBE_NOT_APPLIED for p in probes)
    sens = result["build_sensitivity"]
    assert all(s["status"] == "REJECTED" and s["applied"] is False for s in sens["signals"])
    assert sens["coverage"]["counts"]["NO_SIGNAL"] == 0 and sens["coverage"]["counts"]["REJECTED"] == len(sens["signals"])
    pri = result["build_priorities"]
    assert pri["coverage"]["no_signal"] == [] and len(pri["coverage"]["not_established"]) == len(sens["signals"])
    assert any(s["reason"] == "carrier_ignores_probe_mods" for s in result["skipped"])


def test_slot_stage_does_not_report_no_signal_for_an_item_that_ignores_mods() -> None:
    engine = FakeEngine({"Ring 1": KALANDRA, "Ring 2": RING})
    result = analyze_build(engine, build_path="b.xml", slot_filter="Ring 1")
    rows = next(s for s in result["slots"] if s["pob_slot"] == "Ring 1")["probes"]
    # Global results are reused where they exist (measured on the valid carrier); anything newly run is not established.
    assert all(r["status"] != "NO_SIGNAL" or r.get("measured_on") for r in rows)


def test_global_probe_set_covers_attack_attribute_and_gates_the_rest_on_observed_facts() -> None:
    catalog = ProbeCatalog()
    base = catalog.global_ids()
    assert {"ATTACK_DAMAGE", "ATTACK_SPEED", "PROJECTILE_SKILL_LEVELS", "STRENGTH", "DEXTERITY", "INTELLIGENCE", "CAST_SPEED"} <= set(base)
    assert not {"CRIT_CHANCE", "MINION_DAMAGE", "IGNITE_MAGNITUDE", "POISON_MAGNITUDE"} & set(base)
    full = catalog.global_ids(minion_owned=True, crit_chance=30.0, ignite_dps=5.0, poison_dps=5.0)
    assert {"CRIT_CHANCE", "CRIT_MULTIPLIER", "MINION_DAMAGE", "MINION_SKILL_LEVELS", "IGNITE_MAGNITUDE", "POISON_DURATION"} <= set(full)
    assert len(full) == len(set(full)) and catalog.global_ids(crit_chance=0.0) == base


def _probe(probe_id, family, **axes):
    mapping = {"offense": "primary_offense", "ehp": "ehp", "max_hit": "worst_max_hit", "es": "energy_shield", "mana": "mana", "res": probe_id.lower()}
    profile = {mapping[k]: {"availability": "available", "absolute_delta": v, "percent_delta": v} for k, v in axes.items()}
    return {"probe_id": probe_id, "status": "ok" if any(axes.values()) else "NO_SIGNAL", "family": family, "display_name": probe_id,
            "magnitude": 20.0, "unit": "flat", "line": f"+20 {probe_id}", "confidence": "HIGH", "metric_profile": profile,
            "score_delta": 1.0, "marginal_value_per_unit": 0.05, "breakpoints": [], "warnings": []}


def _result(probes, *, confidence="HIGH", needs=(), resources=None, requirements=None):
    result = {
        "baseline": {"build_path": "b", "build_name": "n", "loadout": "", "item_set": "", "context": "MAP", "profile": "BALANCED", "generation": 1, "fingerprint": "h"},
        "audit": {"primary_field": "CombinedDPS", "primary_confidence": confidence.lower()},
        "build_fingerprint": {"offense": {"owner": "PLAYER", "metric": "CombinedDPS", "scope": "PRIMARY_SKILL", "provenance": "P", "confidence": confidence},
                              "resources": {"mana": resources or {}}, "requirements": requirements or {}},
        "global_probes": probes, "needs": list(needs),
    }
    result["build_sensitivity"] = build_sensitivity(result)
    return result


def test_attribute_probe_gives_a_multi_axis_row_when_it_moves_different_kinds_of_effect() -> None:
    intel = _probe("INTELLIGENCE", "utility", offense=2.1, es=4.3, mana=3.0)
    attack = _probe("ATTACK_SPEED", "offense", offense=6.0)
    pri = build_priorities(_result([intel, attack]))
    assert [r["label"] for r in pri["multi_axis"]] == ["INTELLIGENCE"]
    assert [r["label"] for r in pri["offense"]] == ["ATTACK_SPEED", "INTELLIGENCE"]


def test_defence_confidence_does_not_inherit_low_offense_confidence() -> None:
    barrier = _probe("LIFE", "defense", ehp=2.2, max_hit=2.0, offense=0.0)
    barrier["metric_profile"]["energy_shield"] = {"availability": "available", "absolute_delta": 0.0, "percent_delta": 0.0}
    pri = build_priorities(_result([barrier], confidence="LOW"))
    assert pri["offense_limited_confidence"] is True
    assert [r["confidence"] for r in pri["ehp"]] == ["HIGH"] and [r["confidence"] for r in pri["max_hit"]] == ["HIGH"]
    sig = build_sensitivity(_result([barrier], confidence="LOW"))["signals"][0]
    assert sig["confidence"] == "HIGH" and sig["response"]["offense"]["confidence"] == "LOW"


def test_offense_rows_stay_limited_confidence_when_offense_is_low_confidence() -> None:
    pri = build_priorities(_result([_probe("CAST_SPEED", "offense", offense=6.0)], confidence="LOW"))
    assert [r["confidence"] for r in pri["offense"]] == ["LOW"]


def test_pinned_resistance_is_not_listed_as_an_actionable_fix_but_a_real_deficit_is() -> None:
    fire = _probe("FIRE_RES", "resistance", res=0.0)  # applied, own resistance did not move
    cold = _probe("COLD_RES", "resistance", res=20.0, ehp=3.0)
    cold["breakpoints"] = []
    needs = [{"code": "RES_CAP_MISSING", "severity": "critical", "metric": "fire_res", "deficit": 75.0},
             {"code": "RES_CAP_MISSING", "severity": "critical", "metric": "cold_res", "deficit": 20.0}]
    pri = build_priorities(_result([fire, cold], needs=needs))
    assert [r["title"] for r in pri["fix_first"]] == ["Cold Resistance"]
    assert pri["coverage"]["resistance_pinned"] == ["fire"]
    capped = build_priorities(_result([_probe("FIRE_RES", "resistance", res=0.0)]))  # no deficit: capped, not pinned
    assert capped["coverage"]["resistance_pinned"] == []
    # a probe that was never applied is not evidence of a pinned resistance
    rejected = {**not_applied_probe(ProbeCatalog().get("FIRE_RES"))}
    pri2 = build_priorities(_result([rejected], needs=needs[:1]))
    assert [r["title"] for r in pri2["fix_first"]] == ["Fire Resistance"] and pri2["coverage"]["resistance_pinned"] == []


def _mana(raw_overrides):
    raw = {**BASE_RAW, **raw_overrides}
    fp = build_fingerprint(raw=raw, baseline=AnalysisBaseline("b", "n", "", "", "MAP", "BALANCED", 1, "h"), build_info={"main_skill_identity": {"skill_name": "S"}}).to_dict()
    return fp["resources"]["mana"]


def test_mana_sustain_noise_is_context_not_fix_first_but_a_pool_below_one_use_is() -> None:
    # M5.4 false positive: huge per-second cost against passive regen, pool far larger than one use.
    noisy = _mana({"ManaPerSecondCost": 15332.0, "ManaRegenRecovery": 2029.0, "ManaCost": 2746.0, "ManaUnreserved": 13316.0})
    need = {"code": "RESOURCE_PRESSURE", "severity": "medium", "metric": "mana", "deficit": 13303.0}
    pri = build_priorities(_result([], needs=[need], resources=noisy))
    assert pri["fix_first"] == []
    assert pri["resource_context"]["mana"]["seconds_to_empty_unreserved_pool"] == 1.0
    # genuine: the pool cannot pay for one use
    genuine = _mana({"ManaUnreserved": 30.0, "ManaCost": 60.0})
    rows = build_priorities(_result([], resources=genuine))["fix_first"]
    assert [(r["title"], r["severity"]) for r in rows] == [("Mana pool", "critical")]
    # stable build: leech/regen cover the cost, and a build with no mana cost has nothing to report
    stable = _mana({"ManaPerSecondCost": 100.0, "ManaRegenRecovery": 40.0, "ManaLeechGainRate": 70.0})
    assert stable["sustain"]["value"] == "SUSTAINED" and stable["continuous_use_deficit_per_second"]["value"] == 0.0
    assert build_priorities(_result([], resources=stable))["resource_context"] == {}
    free = _mana({"ManaPerSecondCost": 0.0, "ManaCost": 0.0})
    assert build_priorities(_result([], resources=free))["fix_first"] == []
