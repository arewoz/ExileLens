"""Test support: a production-shaped analysis built with the REAL M5.2/M5.3 functions (no reimplementation)."""
from __future__ import annotations


def make_probe(probe_id, label, line, magnitude, *, family="offense", status="ok", **axes):
    mapping = {"offense": "primary_offense", "ehp": "ehp", "max_hit": "worst_max_hit", "es": "energy_shield",
               "life": "life", "mana": "mana", "movement": "movement_speed"}
    probe = {"probe_id": probe_id, "status": status, "family": family, "display_name": label, "magnitude": magnitude,
             "unit": "percent", "line": line, "confidence": "HIGH"}
    if status == "ok":
        probe["metric_profile"] = {mapping[k]: {"availability": "available", "absolute_delta": v, "percent_delta": v}
                                   for k, v in axes.items()}
        probe.update(score_delta=1.0, marginal_value_per_unit=0.1, breakpoints=[], warnings=[])
    return probe


def synthetic_analysis(*, generation: int = 1, build_path: str = "b.xml"):
    """A production-shaped analysis built with the real M5.2/M5.3 functions (no reimplementation)."""
    from exilelens.analysis.priorities import build_priorities
    from exilelens.analysis.sensitivity import build_sensitivity
    result = {
        "baseline": {"build_path": build_path, "build_name": "T", "loadout": "L", "item_set": "1", "context": "MAP",
                     "profile": "BALANCED", "generation": generation, "fingerprint": "h"},
        "audit": {"primary_field": "CombinedDPS", "primary_confidence": "high"},
        "build_fingerprint": {"offense": {"owner": "PLAYER", "skill": "Spark", "skill_id": "SparkPlayer",
                                          "metric": "CombinedDPS", "confidence": "HIGH"},
                              "defense": {"armour": {"value": 100.0}, "evasion": {"value": 0.0},
                                          "energy_shield": {"value": {"value": 900.0}}}},
        "global_probes": [
            make_probe("SPELL_SKILL_LEVELS", "Spell Skill Levels", "+1 to Level of all Spell Skills", 1.0, offense=11.0),
            make_probe("CAST_SPEED", "Cast Speed", "10% increased Cast Speed", 10.0, offense=4.0),
            make_probe("SPELL_DAMAGE", "Spell Damage", "20% increased Spell Damage", 20.0, offense=3.0),
            make_probe("ENERGY_SHIELD", "Energy Shield", "+50 to maximum Energy Shield", 50.0, family="defense", ehp=3.0, es=5.0),
            make_probe("LIFE", "Life", "+50 to maximum Life", 50.0, family="defense", ehp=2.0, life=2.0),
            make_probe("MOVEMENT_SPEED", "Movement Speed", "10% increased Movement Speed", 10.0, family="utility", movement=7.0),
            make_probe("ATTACK_SPEED", "Attack Speed", "10% increased Attack Speed", 10.0, status="no_signal"),
        ],
        "needs": [],
    }
    for probe in result["global_probes"]:
        if probe["status"] != "ok":
            probe["status"] = "ok"
            probe["metric_profile"] = {"primary_offense": {"availability": "available", "absolute_delta": 0.0, "percent_delta": 0.0}}
            probe.update(score_delta=0.0, marginal_value_per_unit=0.0, breakpoints=[], warnings=[])
    result["build_sensitivity"] = build_sensitivity(result)
    result["build_priorities"] = build_priorities(result)
    return result
