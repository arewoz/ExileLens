"""R1 strongest measured responses: derived from Build Priorities, tested increment always kept, no per-point value."""

from __future__ import annotations

import json

import pytest

from exilelens.analysis.pipeline import analyze_build, rescore_analysis
from exilelens.analysis.priorities import build_priorities
from exilelens.analysis.strongest import (
    COULD_NOT_ESTABLISH,
    MEASURED,
    NO_MEASURABLE_RESPONSE,
    STATUS_LABELS,
    entry_keys,
    format_entry,
    strongest_responses,
)
from tests.test_m5_3_build_priorities import PROBES, _probe, _result
from tests.test_m5_5_remediation import RING, FakeEngine

pytestmark = pytest.mark.itemcheck


def _strongest(probes, **kwargs):
    return strongest_responses(build_priorities(_result(probes, **kwargs)))


def test_offense_ehp_max_hit_and_movement_winners_keep_their_tested_change() -> None:
    top = _strongest(PROBES)
    assert (top["damage"]["tested_change"], top["damage"]["response_percent"]) == ("+1 to Level of all Spell Skills", 8.7)
    assert (top["ehp"]["tested_change"], top["ehp"]["response_percent"]) == ("+50 to maximum Energy Shield", 3.1)
    assert (top["max_hit"]["tested_change"], top["max_hit"]["response_percent"]) == ("+50 to maximum Energy Shield", 2.0)
    assert (top["movement"]["tested_change"], top["movement"]["response_percent"]) == ("10% increased Movement Speed", 10.0)
    assert all(top[key]["status"] == MEASURED and top[key]["tested_change"] for key in entry_keys())
    assert format_entry(top["damage"]) == "+1 to Level of all Spell Skills → Damage +8.7%"
    assert top["basis"] == "Strongest measured response among the tested stat changes."


def test_multi_impact_winner_keeps_every_measured_axis() -> None:
    top = _strongest(PROBES)["multi_impact"]
    assert top["tested_change"] == "+20 to Intelligence" and top["responses"] == {"Damage": 2.1, "ES": 4.3, "Mana": 3.0}
    assert format_entry(top) == "+20 to Intelligence → Damage +2.1% · ES +4.3% · Mana +3.0%"


def test_multi_impact_prefers_breadth_then_catalog_order_and_never_sums_axes() -> None:
    narrow = _probe("STRENGTH", "Strength", "+20 to Strength", 20.0, family="utility", offense=30.0, life=1.5)
    broad = _probe("DEXTERITY", "Dexterity", "+20 to Dexterity", 20.0, family="utility", offense=1.2, life=1.1, mana=1.3)
    second = _probe("INTELLIGENCE", "Intelligence", "+20 to Intelligence", 20.0, family="utility", offense=1.0, es=1.0, mana=1.0)
    top = _strongest([narrow, broad, second])["multi_impact"]
    assert top["label"] == "Dexterity"  # three kinds of effect beats a larger two-kind response; equal breadth keeps catalog order
    assert top["others"] == ["+20 to Strength", "+20 to Intelligence"]


def test_exact_ties_keep_catalog_order_and_near_ties_are_reported_not_decided_by_rounding() -> None:
    exact = [_probe("CAST_SPEED", "Cast Speed", "10% increased Cast Speed", 10.0, offense=6.0),
             _probe("SPELL_DAMAGE", "Spell Damage", "20% increased Spell Damage", 20.0, offense=6.0)]
    assert _strongest(exact)["damage"]["label"] == "Cast Speed"
    assert _strongest(list(reversed(exact)))["damage"]["label"] == "Spell Damage"  # order of the measurement, not of a float
    assert _strongest(exact)["damage"]["tied_with"] == ["20% increased Spell Damage"]
    near = [_probe("CAST_SPEED", "Cast Speed", "10% increased Cast Speed", 10.0, offense=6.101),
            _probe("SPELL_DAMAGE", "Spell Damage", "20% increased Spell Damage", 20.0, offense=6.104)]
    entry = _strongest(near)["damage"]
    assert entry["tied_with"] and "tied_with" not in _strongest(PROBES)["damage"]
    assert _strongest(near) == _strongest(near)


def test_no_measured_signal_is_a_truthful_empty_state() -> None:
    flat = [_probe("CAST_SPEED", "Cast Speed", "10% increased Cast Speed", 10.0, status="NO_SIGNAL")]
    top = _strongest(flat)
    assert all(top[key]["status"] == NO_MEASURABLE_RESPONSE for key in entry_keys())
    assert all("tested_change" not in top[key] and "response_percent" not in top[key] for key in entry_keys())
    assert format_entry(top["damage"]) == "No measurable response"


def test_rejected_and_no_signal_never_win_and_nothing_established_says_so() -> None:
    rejected = [_probe("CAST_SPEED", "Cast Speed", "10% increased Cast Speed", 10.0, status="REJECTED"),
                _probe("LIFE", "Life", "+50 to maximum Life", 50.0, family="defense", status="UNSUPPORTED_PROBE")]
    top = _strongest(rejected)
    assert all(top[key]["status"] == COULD_NOT_ESTABLISH for key in entry_keys())
    assert format_entry(top["ehp"]) == STATUS_LABELS[COULD_NOT_ESTABLISH] == "Could not establish"
    assert all(_strongest([])[key]["status"] == COULD_NOT_ESTABLISH for key in entry_keys())
    mixed = _strongest(PROBES)  # contains a NO_SIGNAL crit probe and an unsupported armour probe
    assert "Crit" not in json.dumps(mixed) and "Armour" not in json.dumps(mixed)


def test_low_confidence_offense_is_flagged_on_the_damage_winner_only() -> None:
    top = _strongest(PROBES, confidence="LOW")
    assert top["damage"]["limited_confidence"] is True and top["damage"]["confidence"] == "LOW"
    assert "limited_confidence" not in top["ehp"] and top["ehp"]["confidence"] == "HIGH"


def test_player_payload_has_no_internal_names_and_no_per_point_value() -> None:
    top = _strongest(PROBES)
    # `identity` is the staleness binding (same as M5.1-M5.3); it is never rendered.
    text = json.dumps({key: value for key, value in top.items() if key != "identity"})
    for internal in ("probe_id", "SPELL_SKILL_LEVELS", "CAST_SPEED", "score", "marginal", "per_unit", "hash1", "profile"):
        assert internal not in text
    assert "not a per-point comparison" in top["caveat"]


def test_profile_independent_and_rebuilt_by_rescore_without_an_engine() -> None:
    flipped = [{**p, "score_delta": 100.0 - i} if p["status"] == "ok" else p for i, p in enumerate(PROBES)]
    assert _strongest(PROBES, profile="BALANCED") == _strongest(flipped, profile="MAPPING")
    result = _result(PROBES)
    result["build_priorities"] = build_priorities(result)
    result["strongest_responses"] = strongest_responses(result["build_priorities"])
    result["slots"] = []
    assert rescore_analysis(result, "MAPPING")["strongest_responses"] == result["strongest_responses"]


def test_analyze_build_attaches_strongest_responses_with_zero_extra_engine_calls() -> None:
    engine = FakeEngine({"Ring 2": RING})
    result = analyze_build(engine, build_path="b.xml", slot_filter="__none__")
    calls = len(engine.evaluations)
    assert result["performance"]["pob_recalcs"] == calls
    again = strongest_responses(result["build_priorities"])
    assert again == result["strongest_responses"] and len(engine.evaluations) == calls
    assert result["strongest_responses"]["identity"] == result["build_priorities"]["identity"]
    assert {result["strongest_responses"][key]["status"] for key in entry_keys()} <= set(STATUS_LABELS)
