"""M5.2 Build Sensitivity Profile: how the loaded build responded to controlled PoB probes.

Pure normalisation of results the existing `ProbeEngine` already produced (`analyze_build()["global_probes"]`).
No probe is run, no PoB call is made, no probe magnitude or catalog entry is added.

Measured response (what PoB reported for one controlled increment) is kept strictly apart from profile-dependent
preference scoring (`profile_dependent`). There is deliberately NO universal scalar: offense %, EHP %, max hit %,
resistance breakpoints and movement are different axes, and a probe increment (+10% Cast Speed, +50 Life) is a local
intervention, not an economic equivalent of any other.
"""

from __future__ import annotations

import math
from typing import Any, Mapping

from exilelens.analysis.catalog import ProbeCatalog
from exilelens.analysis.fingerprint import MEASURED, _PROBE_STATUS
from exilelens.analysis.identity import AnalysisBaseline, is_stale

SCHEMA_VERSION = 1

# metric_profile key -> response axis name. percent is reported where PoB has a meaningful ratio.
_PERCENT_AXES = {
    "primary_offense": "offense",
    "ehp": "ehp",
    "worst_max_hit": "max_hit",
    "life": "life",
    "energy_shield": "energy_shield",
    "mana": "mana",
    "armour": "armour",
    "evasion": "evasion",
    "movement_speed": "movement",
    "cast_attack_speed": "speed",
}
_ABSOLUTE_AXES = {"fire_res": "fire_res", "cold_res": "cold_res", "lightning_res": "lightning_res", "chaos_res": "chaos_res"}
# Not present in the existing metric_profile, so not captured here (never recomputed or faked).
AXES_NOT_CAPTURED = ("life_regen", "energy_shield_regen", "mana_sustain_numbers")

_CONFIDENCE_ORDER = ("UNSUPPORTED", "LOW", "MEDIUM", "HIGH")


def _confidence(value: Any) -> str:
    text = str(value or "").upper()
    return text if text in _CONFIDENCE_ORDER else "LOW"


def _min_confidence(*values: str) -> str:
    return min(values, key=_CONFIDENCE_ORDER.index)


def _finite(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _response(probe: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    """Measured response vector from the probe's existing metric_profile. Unavailable axes are omitted, never 0."""
    profile = probe.get("metric_profile") or {}
    response: dict[str, dict[str, Any]] = {}
    for key, axis in {**_PERCENT_AXES, **_ABSOLUTE_AXES}.items():
        entry = profile.get(key)
        if not isinstance(entry, Mapping) or entry.get("availability") != "available":
            continue
        row: dict[str, Any] = {"absolute": _finite(entry.get("absolute_delta")), "evidence": MEASURED}
        if key in _PERCENT_AXES:
            row["percent"] = _finite(entry.get("percent_delta"))
        response[axis] = row
    warnings = {w.get("code") for w in probe.get("warnings") or [] if isinstance(w, Mapping)}
    if warnings & {"RESOURCE_FAILURE", "RESOURCE_SUSTAIN_LOST"}:
        response["resource_failure"] = {"evidence": MEASURED, "absolute": None}
    return response


def _per_unit(response: Mapping[str, Any], magnitude: float | None) -> dict[str, Any] | None:
    """Plain arithmetic (response / probe magnitude). DERIVED, for the same stat only, never for cross-stat ranking."""
    if not magnitude:
        return None
    out: dict[str, Any] = {"evidence": "DERIVED"}
    for axis in ("offense", "ehp", "max_hit"):
        value = (response.get(axis) or {}).get("percent")
        if value is not None:
            out[f"{axis}_percent_per_unit"] = round(float(value) / float(magnitude), 5)
    return out if len(out) > 1 else None


def _breakpoints(probe: Mapping[str, Any], exact: list[Mapping[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for event in probe.get("breakpoints") or []:
        if isinstance(event, Mapping):
            rows.append({"kind": "RESISTANCE_CAP", "event": event.get("code"), "element": event.get("element")})
    for item in exact:
        increment = _finite(item.get("CAP_REACHED_AT"))
        if increment is not None:
            probe_id = str(item.get("probe_id") or "")
            rows.append(
                {
                    "kind": "RESISTANCE_CAP",
                    "element": probe_id.replace("_RES", "").lower() or None,
                    "required_increment": increment,
                    "status": _PROBE_STATUS.get(str(item.get("status")), "UNKNOWN"),
                    "response_at_breakpoint": {
                        "offense_percent": item.get("offense_percent"),
                        "ehp_percent": item.get("ehp_percent"),
                    },
                }
            )
    return rows


def _native_sample(probe: Mapping[str, Any]) -> dict[str, Any]:
    status = _PROBE_STATUS.get(str(probe.get("status")), "UNKNOWN")
    sample: dict[str, Any] = {"magnitude": probe.get("magnitude"), "status": status}
    if status == MEASURED:
        sample.update(
            {
                "offense_percent": probe.get("offense_percent"),
                "ehp_percent": probe.get("ehp_percent"),
                "profile_dependent": {"score_delta": probe.get("score_delta")},
            }
        )
    return sample


def _offense_context(result: Mapping[str, Any]) -> dict[str, Any]:
    fingerprint_offense = (result.get("build_fingerprint") or {}).get("offense") or {}
    audit = result.get("audit") or {}
    return {
        "owner": fingerprint_offense.get("owner"),
        "metric": fingerprint_offense.get("metric") or audit.get("primary_field"),
        "scope": fingerprint_offense.get("scope"),
        "provenance": fingerprint_offense.get("provenance"),
        "confidence": str(fingerprint_offense.get("confidence") or audit.get("primary_confidence") or "low").upper(),
    }


def build_sensitivity(result: Mapping[str, Any]) -> dict[str, Any]:
    """Build the profile from one existing `analyze_build()` result. Zero PoB recalculations."""
    baseline = dict(result.get("baseline") or {})
    probes = [p for p in result.get("global_probes") or [] if isinstance(p, Mapping) and p.get("probe_id")]
    offense = _offense_context(result)
    offense_low = offense["confidence"] == "LOW"
    catalog = ProbeCatalog()

    by_id: dict[str, dict[str, Any]] = {}
    for probe in probes:
        entry = by_id.setdefault(str(probe["probe_id"]), {"default": None, "exact": [], "curve": None, "samples": []})
        if probe.get("status") == "curve":
            entry["curve"] = probe
        elif probe.get("breakpoint_exact"):
            entry["exact"].append(probe)
        elif probe.get("nonlinear_sample"):
            entry["samples"].append(probe)
        elif entry["default"] is None:
            entry["default"] = probe

    signals: list[dict[str, Any]] = []
    for probe_id, entry in by_id.items():
        main = entry["default"] or (entry["exact"][0] if entry["exact"] else None)
        if main is None:
            continue
        status = _PROBE_STATUS.get(str(main.get("status")), "UNKNOWN")
        magnitude = _finite(main.get("magnitude"))
        definition = catalog.get(probe_id)
        measured_or_flat = status in {MEASURED, "NO_SIGNAL"}
        signal: dict[str, Any] = {
            "probe_id": probe_id,
            "family": main.get("family") or (definition.family if definition else None),  # the intervention, not the response
            "label": main.get("display_name") or (definition.label if definition else probe_id),
            "probe": {"magnitude": magnitude, "unit": main.get("unit") or (definition.unit if definition else None), "line": main.get("line")},
            "status": status,
            # True only when the experiment was established (PoB applied the probe). NO_SIGNAL then means "applied, no
            # measured response"; REJECTED/UNSUPPORTED/RESTORE_FAILED/INVALID mean "not established".
            "applied": measured_or_flat,
            "confidence": "UNSUPPORTED" if status != MEASURED else _confidence(main.get("confidence")),
        }
        if status == "NO_SIGNAL" and (main.get("family") or (definition.family if definition else None)) == "resistance":
            own = ((main.get("metric_profile") or {}).get(probe_id.lower()) or {})
            if own.get("availability") == "available":
                # The resistance this probe raises did not move: it is pinned (e.g. overridden by an equipped item).
                signal["own_resistance_delta"] = _finite(own.get("absolute_delta"))
        if status == MEASURED:
            response = _response(main)
            signal["response"] = response
            if "offense" in response:
                # Confidence follows the evidence of each axis: a low-confidence offense metric limits the offense axis
                # only; independent defensive axes keep the probe's own confidence.
                axis_confidence = _min_confidence(signal["confidence"], "LOW") if offense_low else signal["confidence"]
                signal["response"]["offense"]["confidence"] = axis_confidence
            per_unit = _per_unit(response, magnitude)
            if per_unit:
                signal["response_per_unit"] = per_unit
            samples = [main, *entry["samples"]]
            signal["samples"] = sorted((_native_sample(s) for s in samples), key=lambda s: s.get("magnitude") or 0)
            curve = entry["curve"]
            signal["profile_dependent"] = {
                "score_delta": main.get("score_delta"),
                "marginal_value_per_unit": main.get("marginal_value_per_unit"),
                # Existing ProbeEngine classification; it is derived from score_delta, hence profile-dependent.
                "linearity": str(curve.get("linearity") or "unknown").upper() if curve else "UNKNOWN",
            }
        signal["breakpoints"] = _breakpoints(main, entry["exact"])
        signals.append(signal)

    counts: dict[str, int] = {}
    for signal in signals:
        counts[signal["status"]] = counts.get(signal["status"], 0) + 1
    catalog_ids = [d.probe_id for d in catalog.all()]
    return {
        "schema_version": SCHEMA_VERSION,
        "identity": {
            "baseline_fingerprint": str(baseline.get("fingerprint") or ""),
            "generation": int(baseline.get("generation") or 0),
            "build_path": str(baseline.get("build_path") or ""),
            "build_name": str(baseline.get("build_name") or ""),
            "loadout": str(baseline.get("loadout") or ""),
            "item_set": str(baseline.get("item_set") or ""),
            "context": str(baseline.get("context") or ""),
        },
        "offense_context": offense,
        "profile": str(baseline.get("profile") or ""),
        "signals": signals,
        "coverage": {
            "counts": {k: counts.get(k, 0) for k in ("MEASURED", "NO_SIGNAL", "REJECTED", "UNSUPPORTED", "RESTORE_FAILED", "INVALID")},
            "not_measured": [s["probe_id"] for s in signals if s["status"] != MEASURED],
            "not_run": [pid for pid in catalog_ids if pid not in {s["probe_id"] for s in signals}],
            "axes_not_captured": list(AXES_NOT_CAPTURED),
            "offense_confidence": offense["confidence"],
        },
    }


def profile_independent_sensitivity(profile: Mapping[str, Any]) -> dict[str, Any]:
    """The profile without any scoring-profile-dependent field (measured responses untouched)."""
    out = {key: value for key, value in profile.items() if key != "profile"}
    signals = []
    for signal in profile.get("signals") or []:
        clean = {k: v for k, v in signal.items() if k != "profile_dependent"}
        if "samples" in clean:
            clean["samples"] = [{k: v for k, v in s.items() if k != "profile_dependent"} for s in clean["samples"]]
        signals.append(clean)
    out["signals"] = signals
    return out


def is_sensitivity_stale(profile: Mapping[str, Any], current: AnalysisBaseline) -> bool:
    """Same binding as the Build Fingerprint; a value-profile-only change is never stale."""
    identity = profile.get("identity") or {}
    previous = AnalysisBaseline(
        build_path=str(identity.get("build_path") or ""),
        build_name=str(identity.get("build_name") or ""),
        loadout=str(identity.get("loadout") or ""),
        item_set=str(identity.get("item_set") or ""),
        context=str(identity.get("context") or ""),
        profile=current.profile,
        generation=int(identity.get("generation") or 0),
        fingerprint=str(identity.get("baseline_fingerprint") or ""),
    )
    return is_stale(previous, current)
