from __future__ import annotations

import math
from typing import Any


RAW_METRIC_FIELDS = [
    "CombinedDPS",
    "FullDPS",
    "TotalDPS",
    "TotalDot",
    "FullDotDPS",
    "AverageDamage",
    "Speed",
    "HitSpeed",
    "CritChance",
    "TotalEHP",
    "Life",
    "LifeUnreserved",
    "EnergyShield",
    "Mana",
    "ManaUnreserved",
    "Spirit",
    "SpiritUnreserved",
    "FireResist",
    "ColdResist",
    "LightningResist",
    "ChaosResist",
    "FireResistOverCap",
    "ColdResistOverCap",
    "LightningResistOverCap",
    "ChaosResistOverCap",
    "FireResistTotal",
    "ColdResistTotal",
    "LightningResistTotal",
    "ChaosResistTotal",
    "FireResistMax",
    "ColdResistMax",
    "LightningResistMax",
    "ChaosResistMax",
    "MissingFireResist",
    "MissingColdResist",
    "MissingLightningResist",
    "MissingChaosResist",
    "PhysicalMaximumHitTaken",
    "FireMaximumHitTaken",
    "ColdMaximumHitTaken",
    "LightningMaximumHitTaken",
    "ChaosMaximumHitTaken",
    "Armour",
    "Evasion",
    "BlockChance",
    "MovementSpeedMod",
    "ManaPerSecondCost",
    "ManaRegenRecovery",
    "Minion.CombinedDPS",
    "Minion.TotalDPS",
    "Minion.FullDPS",
    "Minion.TotalDot",
    "Minion.FullDotDPS",
    "Minion.AverageDamage",
    "Minion.AverageHit",
    "Minion.Speed",
]

_DIRECTION_EPS = 1e-9

METRIC_CATALOG: dict[str, dict[str, str]] = {
    "primary_offense": {"label": "Damage", "display_format": "large_number", "importance": "critical"},
    "ehp": {"label": "EHP", "display_format": "large_number", "importance": "high"},
    "worst_max_hit": {"label": "Max Hit", "display_format": "large_number", "importance": "high"},
    "physical_max_hit": {"label": "Phys Max Hit", "display_format": "large_number", "importance": "medium"},
    "fire_max_hit": {"label": "Fire Max Hit", "display_format": "large_number", "importance": "medium"},
    "cold_max_hit": {"label": "Cold Max Hit", "display_format": "large_number", "importance": "medium"},
    "lightning_max_hit": {"label": "Lightning Max Hit", "display_format": "large_number", "importance": "medium"},
    "chaos_max_hit": {"label": "Chaos Max Hit", "display_format": "large_number", "importance": "medium"},
    "life": {"label": "Life", "display_format": "large_number", "importance": "medium"},
    "energy_shield": {"label": "Energy Shield", "display_format": "large_number", "importance": "medium"},
    "mana": {"label": "Mana", "display_format": "large_number", "importance": "low"},
    "fire_res": {"label": "Fire Res", "display_format": "resistance", "importance": "high"},
    "cold_res": {"label": "Cold Res", "display_format": "resistance", "importance": "high"},
    "lightning_res": {"label": "Lightning Res", "display_format": "resistance", "importance": "high"},
    "chaos_res": {"label": "Chaos Res", "display_format": "resistance", "importance": "medium"},
    "movement_speed": {"label": "Move Speed", "display_format": "percent_mod", "importance": "medium"},
    "cast_attack_speed": {"label": "Cast/Attack Speed", "display_format": "large_number", "importance": "high"},
    "armour": {"label": "Armour", "display_format": "large_number", "importance": "low"},
    "evasion": {"label": "Evasion", "display_format": "large_number", "importance": "low"},
    "block_chance": {"label": "Block", "display_format": "percent_mod", "importance": "low"},
}


def normalize_metrics(raw: dict[str, Any]) -> dict[str, Any]:
    offense_primary = raw.get("CombinedDPS")
    if offense_primary is None:
        # Legacy normalized primary_dps represents the selected skill only.
        # FullDPS needs explicit group/configuration provenance; AverageDamage
        # may be per hit (showAverage), so neither is a safe generic fallback.
        offense_primary = raw.get("TotalDPS")

    return {
        "offense": {
            "primary_dps": offense_primary,
            "combined_dps": raw.get("CombinedDPS"),
            "full_dps": raw.get("FullDPS"),
            "total_dps": raw.get("TotalDPS"),
            "total_dot": raw.get("TotalDot"),
            "full_dot_dps": raw.get("FullDotDPS"),
            "speed": raw.get("Speed"),
            "hit_speed": raw.get("HitSpeed"),
            "crit_chance": raw.get("CritChance"),
        },
        "defense": {
            "ehp": raw.get("TotalEHP"),
            "life": raw.get("Life"),
            "energy_shield": raw.get("EnergyShield"),
            "armour": raw.get("Armour"),
            "evasion": raw.get("Evasion"),
            "physical_max_hit": raw.get("PhysicalMaximumHitTaken"),
            "fire_max_hit": raw.get("FireMaximumHitTaken"),
            "cold_max_hit": raw.get("ColdMaximumHitTaken"),
            "lightning_max_hit": raw.get("LightningMaximumHitTaken"),
            "chaos_max_hit": raw.get("ChaosMaximumHitTaken"),
            "resists": {
                "fire": raw.get("FireResist"),
                "cold": raw.get("ColdResist"),
                "lightning": raw.get("LightningResist"),
                "chaos": raw.get("ChaosResist"),
            },
            "resist_overcap": {
                "fire": raw.get("FireResistOverCap"),
                "cold": raw.get("ColdResistOverCap"),
                "lightning": raw.get("LightningResistOverCap"),
                "chaos": raw.get("ChaosResistOverCap"),
            },
            "resist_cap": {
                "fire": raw.get("FireResistMax"),
                "cold": raw.get("ColdResistMax"),
                "lightning": raw.get("LightningResistMax"),
                "chaos": raw.get("ChaosResistMax"),
            },
        },
        "resources": {
            "mana": raw.get("Mana"),
            "mana_unreserved": raw.get("ManaUnreserved"),
            "spirit_unreserved": raw.get("SpiritUnreserved"),
            "movement_speed_mod": raw.get("MovementSpeedMod"),
            "mana_per_second_cost": raw.get("ManaPerSecondCost"),
            "mana_regen": raw.get("ManaRegenRecovery"),
        },
    }


def metric_delta(current: dict[str, Any], candidate: dict[str, Any]) -> dict[str, Any]:
    deltas: dict[str, Any] = {}
    for key in ("offense", "defense", "resources"):
        section: dict[str, Any] = {}
        cur = current.get(key, {})
        cand = candidate.get(key, {})
        for metric, cur_val in cur.items():
            if metric in {"resists", "resist_overcap", "resist_cap"}:
                nested = {}
                for nested_key, resist_val in (cur_val or {}).items():
                    cand_val = (cand.get(metric) or {}).get(nested_key)
                    if isinstance(resist_val, (int, float)) and isinstance(cand_val, (int, float)):
                        nested[nested_key] = _delta_pair(resist_val, cand_val)
                if nested:
                    section[metric] = nested
                continue
            cand_val = cand.get(metric)
            if isinstance(cur_val, (int, float)) and isinstance(cand_val, (int, float)):
                section[metric] = _delta_pair(cur_val, cand_val)
        if section:
            deltas[key] = section
    return deltas


def _delta_pair(current: float, candidate: float) -> dict[str, float | None]:
    absolute = candidate - current
    percent = None
    if current not in (0, 0.0):
        percent = (candidate / current - 1.0) * 100.0
    return {
        "current": current,
        "candidate": candidate,
        "absolute_delta": absolute,
        "percent_delta": percent,
        # Backward-compatible aliases for Phase 1 consumers.
        "absolute": absolute,
        "percent": percent,
    }


def _direction(absolute: float) -> str:
    if abs(absolute) < _DIRECTION_EPS:
        return "neutral"
    return "positive" if absolute > 0 else "negative"


def _metric_entry(
    key: str,
    current: float | None,
    candidate: float | None,
    *,
    pob_field: str,
    confidence: str = "high",
    importance: str | None = None,
) -> dict[str, Any]:
    catalog = METRIC_CATALOG.get(key, {"label": key, "display_format": "large_number", "importance": "low"})
    available = current is not None and candidate is not None
    if not available:
        return {
            "key": key,
            "label": catalog["label"],
            "pob_field": pob_field,
            "current": current,
            "candidate": candidate,
            "absolute_delta": None,
            "percent_delta": None,
            "absolute": None,
            "percent": None,
            "direction": "neutral",
            "importance": importance or catalog["importance"],
            "availability": "missing",
            "confidence": "low",
            "display_format": catalog["display_format"],
        }
    pair = _delta_pair(float(current), float(candidate))
    return {
        "key": key,
        "label": catalog["label"],
        "pob_field": pob_field,
        **pair,
        "direction": _direction(float(pair["absolute_delta"] or 0)),
        "importance": importance or catalog["importance"],
        "availability": "available",
        "confidence": confidence,
        "display_format": catalog["display_format"],
    }


def _optional_raw(metrics: dict[str, Any], field: str) -> float | None:
    if field in metrics:
        value = metrics.get(field)
        if value is None or isinstance(value, bool):
            return None
        try:
            number = float(value)
        except (TypeError, ValueError):
            return None
        return number if math.isfinite(number) else None
    offense = metrics.get("offense") or {}
    defense = metrics.get("defense") or {}
    resources = metrics.get("resources") or {}
    mapping = {
        "CombinedDPS": offense["combined_dps"] if "combined_dps" in offense else offense.get("primary_dps"),
        "FullDPS": offense.get("full_dps"),
        "TotalDPS": offense.get("total_dps"),
        "TotalDot": offense.get("total_dot"),
        "FullDotDPS": offense.get("full_dot_dps"),
        "TotalEHP": defense.get("ehp"),
        "Life": defense.get("life"),
        "EnergyShield": defense.get("energy_shield"),
        "Mana": resources.get("mana"),
        "FireResist": (defense.get("resists") or {}).get("fire"),
        "ColdResist": (defense.get("resists") or {}).get("cold"),
        "LightningResist": (defense.get("resists") or {}).get("lightning"),
        "ChaosResist": (defense.get("resists") or {}).get("chaos"),
        "PhysicalMaximumHitTaken": defense.get("physical_max_hit"),
        "FireMaximumHitTaken": defense.get("fire_max_hit"),
        "ColdMaximumHitTaken": defense.get("cold_max_hit"),
        "LightningMaximumHitTaken": defense.get("lightning_max_hit"),
        "ChaosMaximumHitTaken": defense.get("chaos_max_hit"),
        "MovementSpeedMod": resources.get("movement_speed_mod"),
        "Speed": offense.get("speed"),
        "HitSpeed": offense.get("hit_speed"),
        "Armour": defense.get("armour"),
        "Evasion": defense.get("evasion"),
        "BlockChance": defense.get("block_chance") if "block_chance" in defense else None,
    }
    if field not in mapping:
        return None
    value = mapping.get(field)
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _resolve_metric_value(metrics: dict[str, Any], field: str) -> float:
    value = _optional_raw(metrics, field)
    return float(value or 0.0)


def _worst_max_hit(metrics: dict[str, Any]) -> tuple[float | None, str]:
    fields = (
        ("physical_max_hit", "PhysicalMaximumHitTaken"),
        ("fire_max_hit", "FireMaximumHitTaken"),
        ("cold_max_hit", "ColdMaximumHitTaken"),
        ("lightning_max_hit", "LightningMaximumHitTaken"),
        ("chaos_max_hit", "ChaosMaximumHitTaken"),
    )
    worst_value = None
    worst_field = "PhysicalMaximumHitTaken"
    for _key, field in fields:
        value = _optional_raw(metrics, field)
        if value is None:
            continue
        if worst_value is None or value < worst_value:
            worst_value = value
            worst_field = field
    return worst_value, worst_field


def build_metric_profile(
    current: dict[str, Any],
    candidate: dict[str, Any],
    *,
    primary_field: str = "CombinedDPS",
    confidence: str = "high",
) -> dict[str, dict[str, Any]]:
    primary_current = _optional_raw(current, primary_field)
    primary_candidate = _optional_raw(candidate, primary_field)
    worst_current, worst_field = _worst_max_hit(current)
    worst_candidate, _ = _worst_max_hit(candidate)
    profile = {
        "primary_offense": _metric_entry(
            "primary_offense",
            primary_current,
            primary_candidate,
            pob_field=primary_field,
            confidence=confidence,
            importance="critical",
        ),
        "ehp": _metric_entry("ehp", _optional_raw(current, "TotalEHP"), _optional_raw(candidate, "TotalEHP"), pob_field="TotalEHP", confidence=confidence),
        "worst_max_hit": _metric_entry(
            "worst_max_hit",
            worst_current,
            worst_candidate,
            pob_field=worst_field,
            confidence="high" if worst_current is not None else "low",
        ),
        "physical_max_hit": _metric_entry(
            "physical_max_hit",
            _optional_raw(current, "PhysicalMaximumHitTaken"),
            _optional_raw(candidate, "PhysicalMaximumHitTaken"),
            pob_field="PhysicalMaximumHitTaken",
        ),
        "fire_max_hit": _metric_entry(
            "fire_max_hit",
            _optional_raw(current, "FireMaximumHitTaken"),
            _optional_raw(candidate, "FireMaximumHitTaken"),
            pob_field="FireMaximumHitTaken",
        ),
        "cold_max_hit": _metric_entry(
            "cold_max_hit",
            _optional_raw(current, "ColdMaximumHitTaken"),
            _optional_raw(candidate, "ColdMaximumHitTaken"),
            pob_field="ColdMaximumHitTaken",
        ),
        "lightning_max_hit": _metric_entry(
            "lightning_max_hit",
            _optional_raw(current, "LightningMaximumHitTaken"),
            _optional_raw(candidate, "LightningMaximumHitTaken"),
            pob_field="LightningMaximumHitTaken",
        ),
        "chaos_max_hit": _metric_entry(
            "chaos_max_hit",
            _optional_raw(current, "ChaosMaximumHitTaken"),
            _optional_raw(candidate, "ChaosMaximumHitTaken"),
            pob_field="ChaosMaximumHitTaken",
        ),
        "life": _metric_entry("life", _optional_raw(current, "Life"), _optional_raw(candidate, "Life"), pob_field="Life"),
        "energy_shield": _metric_entry(
            "energy_shield",
            _optional_raw(current, "EnergyShield"),
            _optional_raw(candidate, "EnergyShield"),
            pob_field="EnergyShield",
        ),
        "mana": _metric_entry("mana", _optional_raw(current, "Mana"), _optional_raw(candidate, "Mana"), pob_field="Mana"),
        "fire_res": _metric_entry("fire_res", _optional_raw(current, "FireResist"), _optional_raw(candidate, "FireResist"), pob_field="FireResist"),
        "cold_res": _metric_entry("cold_res", _optional_raw(current, "ColdResist"), _optional_raw(candidate, "ColdResist"), pob_field="ColdResist"),
        "lightning_res": _metric_entry(
            "lightning_res",
            _optional_raw(current, "LightningResist"),
            _optional_raw(candidate, "LightningResist"),
            pob_field="LightningResist",
        ),
        "chaos_res": _metric_entry(
            "chaos_res",
            _optional_raw(current, "ChaosResist"),
            _optional_raw(candidate, "ChaosResist"),
            pob_field="ChaosResist",
        ),
        "movement_speed": _metric_entry(
            "movement_speed",
            _optional_raw(current, "MovementSpeedMod"),
            _optional_raw(candidate, "MovementSpeedMod"),
            pob_field="MovementSpeedMod",
        ),
        "cast_attack_speed": _metric_entry(
            "cast_attack_speed",
            _optional_raw(current, "Speed"),
            _optional_raw(candidate, "Speed"),
            pob_field="Speed",
            importance="high",
        ),
        "armour": _metric_entry("armour", _optional_raw(current, "Armour"), _optional_raw(candidate, "Armour"), pob_field="Armour"),
        "evasion": _metric_entry("evasion", _optional_raw(current, "Evasion"), _optional_raw(candidate, "Evasion"), pob_field="Evasion"),
    }
    return profile
