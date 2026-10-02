"""M5.1 Build Fingerprint: what the loaded build *is* and what it responds to.

Not an identity hash. `identity.baseline_fingerprint` is the existing PoB state hash (cache / staleness
binding); everything else is a structured, evidence-labelled summary assembled from data ExileLens already
has, with ZERO additional PoB recalculations:

* the baseline raw PoB metrics, build info and `PrimaryMetricSelection`,
* the existing `BuildStateAudit` (resistance caps, worst max hit, resource pressure),
* optionally the existing `ProbeEngine` global probes (`with_probe_signals`), normalised, never re-run.

Evidence vocabulary (every leaf is `{"value", "evidence"}`):
  OBSERVED     read directly from loaded PoB output
  DERIVED      plain arithmetic on observed values (a margin, a pool share)
  MEASURED     result of an existing controlled probe
  UNAVAILABLE  PoB did not report it / does not apply to this offense owner
(INFERRED is reserved; this module draws no judgement-based conclusions.)

Profile independent by construction: nothing here reads a value profile. Probe score deltas, which depend
on the scoring profile, live only under each signal's `profile_dependent` key.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field
from typing import Any, Mapping

from exilelens.analysis.audit import BuildStateAudit, build_state_audit
from exilelens.analysis.identity import AnalysisBaseline, is_stale
from exilelens.items.primary_metric import DamageOwner, PrimaryMetricSelection, resolve_primary_metric

SCHEMA_VERSION = 1

OBSERVED = "OBSERVED"
DERIVED = "DERIVED"
MEASURED = "MEASURED"
UNAVAILABLE = "UNAVAILABLE"

# Existing ProbeEngine statuses -> signal status. They stay distinguishable on purpose:
# NO_SIGNAL (probe ran, nothing moved), REJECTED / UNSUPPORTED / RESTORE_FAILED / INVALID (no valid measurement).
_PROBE_STATUS = {
    "ok": MEASURED,
    "NO_SIGNAL": "NO_SIGNAL",
    "REJECTED": "REJECTED",
    "UNSUPPORTED_PROBE": "UNSUPPORTED",
    "RESTORE_FAILED": "RESTORE_FAILED",
    "INVALID_PROBE": "INVALID",
}


def _num(raw: Mapping[str, Any], key: str) -> float | None:
    value = raw.get(key)
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _leaf(value: Any, evidence: str = OBSERVED) -> dict[str, Any]:
    if value is None:
        return {"value": None, "evidence": UNAVAILABLE}
    return {"value": value, "evidence": evidence}


def _obs(raw: Mapping[str, Any], key: str) -> dict[str, Any]:
    return _leaf(_num(raw, key))


def _present(raw: Mapping[str, Any], key: str) -> dict[str, Any]:
    value = _num(raw, key)
    return _leaf(None if value is None else value > 0, OBSERVED)


@dataclass
class BuildFingerprint:
    identity: dict[str, Any]
    offense: dict[str, Any]
    defense: dict[str, Any]
    resources: dict[str, Any]
    requirements: dict[str, Any]
    mobility: dict[str, Any]
    signals: dict[str, Any] = field(default_factory=dict)
    coverage: dict[str, Any] = field(default_factory=dict)
    schema_version: int = SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ----------------------------------------------------------------------- sections


def _identity(baseline: AnalysisBaseline | Mapping[str, Any], primary: PrimaryMetricSelection) -> dict[str, Any]:
    data = baseline.to_dict() if isinstance(baseline, AnalysisBaseline) else dict(baseline)
    return {
        "baseline_fingerprint": str(data.get("fingerprint") or ""),  # identity hash: binding only, not intelligence
        "generation": int(data.get("generation") or 0),
        "build_path": str(data.get("build_path") or ""),
        "build_name": str(data.get("build_name") or ""),
        "loadout": str(data.get("loadout") or ""),
        "item_set": str(data.get("item_set") or ""),
        "context": str(data.get("context") or ""),
        "primary_skill": primary.skill.name or None,
    }


def _offense(raw: Mapping[str, Any], primary: PrimaryMetricSelection, audit: BuildStateAudit) -> dict[str, Any]:
    owner = primary.damage_owner
    value = _num(raw, primary.pob_field)
    player_owned = owner == DamageOwner.PLAYER
    reason = None if player_owned else f"offense owner is {owner.value}; PoB crit output describes the player's skill"
    crit_chance = _num(raw, "CritChance") if player_owned else None
    return {
        "owner": owner.value,
        "skill": primary.skill.name or None,
        "skill_id": primary.skill.skill_id or None,
        "metric": primary.pob_field,
        "scope": primary.metric_scope.value,
        "quantity": primary.semantic_quantity.value,
        "kind": primary.selected.value,
        "provenance": primary.provenance.value,
        "ailment": primary.ailment or None,
        "full_dps_status": primary.full_dps_status,
        "confidence": primary.confidence.value.upper(),
        "damage": _leaf(value if audit.offense.get("availability") == "available" else None),
        "speed": _obs(raw, "Speed") if player_owned else _leaf(None),
        "crit": {
            "chance": _leaf(crit_chance),
            "multiplier": _leaf(_num(raw, "CritMultiplier") if player_owned else None),
            "present": _leaf(None if crit_chance is None else crit_chance > 0),
            "reason_unavailable": reason,
        },
        "dot_present": _present(raw, "TotalDot") if player_owned else _leaf(None),
    }


def _defense(raw: Mapping[str, Any], audit: BuildStateAudit) -> dict[str, Any]:
    life, es = _num(raw, "Life"), _num(raw, "EnergyShield")
    pool = (life or 0.0) + (es or 0.0) if life is not None or es is not None else None
    shares = None
    if pool:
        shares = {
            "life": _leaf(round((life or 0.0) / pool, 4), DERIVED),
            "energy_shield": _leaf(round((es or 0.0) / pool, 4), DERIVED),
        }
    resistances = {
        element: {
            "current": _leaf(cap.current),
            "cap": _leaf(cap.cap),
            "missing": _leaf(cap.missing, OBSERVED if cap.missing is not None else DERIVED),
            "overcap": _leaf(cap.overcap),
            "state": _leaf(None if cap.state == "UNKNOWN" else cap.state, DERIVED),
        }
        for element, cap in audit.resistances.items()
    }
    return {
        "life": {"value": _leaf(life), "present": _leaf(None if life is None else life > 1)},
        "energy_shield": {"value": _leaf(es), "present": _leaf(None if es is None else es > 0)},
        "pool_share": shares,
        "armour": _obs(raw, "Armour"),
        "evasion": _obs(raw, "Evasion"),
        "block_chance": _obs(raw, "BlockChance"),
        "total_ehp": _obs(raw, "TotalEHP"),
        "worst_max_hit": {
            "value": _leaf(audit.defense.get("worst_max_hit")),
            "pob_field": audit.defense.get("worst_max_hit_field"),
        },
        "resistances": resistances,
    }


def _resources(raw: Mapping[str, Any], audit: BuildStateAudit) -> dict[str, Any]:
    cost, regen = _num(raw, "ManaPerSecondCost"), _num(raw, "ManaRegenRecovery")
    leech = _num(raw, "ManaLeechGainRate")
    if cost is None or regen is None:
        sustain = _leaf(None)
        deficit = _leaf(None)
    else:
        # PoB's per-second cost assumes uninterrupted use at full speed; recovery here is passive regeneration plus
        # PoB's own leech / on-hit gain when it reports one. Leech-free fields stay UNAVAILABLE rather than assumed 0.
        recovery = regen + (leech or 0.0)
        gap = cost - recovery
        sustain = _leaf("PRESSURED" if gap > 0.05 else "SUSTAINED", DERIVED)
        deficit = _leaf(round(max(0.0, gap), 2), DERIVED)
    return {
        "mana": {
            "pool": _obs(raw, "Mana"), "unreserved": _obs(raw, "ManaUnreserved"), "cost_per_use": _obs(raw, "ManaCost"),
            "cost_per_second": _obs(raw, "ManaPerSecondCost"), "regen_per_second": _obs(raw, "ManaRegenRecovery"),
            "leech_gain_per_second": _obs(raw, "ManaLeechGainRate"),
            "continuous_use_deficit_per_second": deficit, "sustain": sustain,
        },
        "life": {"cost_per_second": _obs(raw, "LifePerSecondCost"), "regen_per_second": _obs(raw, "LifeRegenRecovery")},
        "energy_shield": {"regen_per_second": _obs(raw, "EnergyShieldRegenRecovery"), "cost_per_second": _obs(raw, "ESPerSecondCost")},
        "spirit": {"pool": _obs(raw, "Spirit"), "unreserved": _obs(raw, "SpiritUnreserved")},
    }


def _requirements(raw: Mapping[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for name, attr, req in (("strength", "Str", "ReqStr"), ("dexterity", "Dex", "ReqDex"), ("intelligence", "Int", "ReqInt")):
        have, need = _num(raw, attr), _num(raw, req)
        margin = None if have is None or need is None else have - need
        out[name] = {
            "value": _leaf(have),
            # PoB's ReqX is the highest requirement among equipped items and gems, not a sum.
            "highest_requirement": _leaf(need),
            "margin": _leaf(margin, DERIVED),
            "state": _leaf(None if margin is None else ("DEFICIT" if margin < 0 else "MET"), DERIVED),
        }
    return out


# ----------------------------------------------------------------------- coverage


def _walk_leaves(node: Any, path: str = ""):
    if isinstance(node, dict):
        if set(node) >= {"value", "evidence"} and len(node) == 2:
            yield path, node
            return
        for key, value in node.items():
            yield from _walk_leaves(value, f"{path}.{key}" if path else str(key))


def _coverage(sections: Mapping[str, Any], offense_confidence: str, signals: Mapping[str, Any]) -> dict[str, Any]:
    observed: list[str] = []
    unavailable: list[str] = []
    for name, section in sections.items():
        for path, leaf in _walk_leaves(section, name):
            (unavailable if leaf["evidence"] == UNAVAILABLE else observed).append(path)
    by_status: dict[str, list[str]] = {}
    for probe_id, signal in signals.items():
        by_status.setdefault(str(signal.get("status")), []).append(probe_id)
    return {
        "observed": observed,
        "unavailable": unavailable,
        # Not reported by this fingerprint at all (deliberately not guessed).
        "not_modelled": ["attack_cast_orientation", "triggered_mechanics", "minion_defences", "es_recharge", "leech", "recoup"],
        "offense_confidence": offense_confidence,
        "signals_by_status": by_status,
        "signals_measured": bool(by_status.get(MEASURED)),
    }


# ----------------------------------------------------------------------- public API


def build_fingerprint(
    *,
    raw: Mapping[str, Any],
    baseline: AnalysisBaseline | Mapping[str, Any],
    build_info: Mapping[str, Any] | None = None,
    primary: PrimaryMetricSelection | None = None,
    audit: BuildStateAudit | None = None,
) -> BuildFingerprint:
    """Base fingerprint from already loaded data. No PoB calls, no file or network access."""
    raw = dict(raw or {})
    primary = primary or resolve_primary_metric(dict(build_info or {}), raw)
    audit = audit or build_state_audit(raw, primary_field=primary.pob_field, primary_confidence=primary.confidence.value)
    sections = {
        "offense": _offense(raw, primary, audit),
        "defense": _defense(raw, audit),
        "resources": _resources(raw, audit),
        "requirements": _requirements(raw),
        "mobility": {"movement_speed_mod": _obs(raw, "MovementSpeedMod")},
    }
    return BuildFingerprint(
        identity=_identity(baseline, primary),
        **sections,
        coverage=_coverage(sections, sections["offense"]["confidence"], {}),
    )


def normalize_probe_signal(probe: Mapping[str, Any]) -> dict[str, Any]:
    """One existing ProbeEngine result -> one signal. Raw dimensions first; profile-dependent score kept apart."""
    status = _PROBE_STATUS.get(str(probe.get("status")), "UNKNOWN")
    signal: dict[str, Any] = {
        "status": status,
        "family": probe.get("family"),
        "magnitude": probe.get("magnitude"),
        "unit": probe.get("unit"),
        "confidence": probe.get("confidence"),
    }
    if status == MEASURED:
        profile_metrics = probe.get("metric_profile") or {}

        def pct(key: str) -> float | None:
            value = (profile_metrics.get(key) or {}).get("percent_delta")
            return None if value is None else round(float(value), 3)

        signal.update(
            {
                "offense_percent": probe.get("offense_percent"),
                "ehp_percent": probe.get("ehp_percent"),
                "max_hit_percent": pct("worst_max_hit"),
                "breakpoints": [b.get("code") for b in probe.get("breakpoints") or [] if isinstance(b, dict)],
                "cache_hit": bool(probe.get("cache_hit")),
                "profile_dependent": {
                    "score_delta": probe.get("score_delta"),
                    "marginal_value_per_unit": probe.get("marginal_value_per_unit"),
                },
            }
        )
    return signal


def with_probe_signals(fingerprint: Mapping[str, Any], probes: list[Mapping[str, Any]]) -> dict[str, Any]:
    """Enrich a serialized fingerprint with existing global probe results (no probe is run here).

    Only each probe's default-magnitude result is used; nonlinear samples, exact breakpoint probes and curve rows
    are existing analysis detail and stay in the analysis result.
    """
    updated = {key: value for key, value in fingerprint.items()}
    signals: dict[str, Any] = {}
    for probe in probes or []:
        probe_id = probe.get("probe_id")
        if not probe_id or probe.get("status") == "curve" or probe.get("nonlinear_sample") or probe.get("breakpoint_exact"):
            continue
        signals.setdefault(str(probe_id), normalize_probe_signal(probe))
    updated["signals"] = signals
    coverage = dict(fingerprint.get("coverage") or {})
    by_status: dict[str, list[str]] = {}
    for probe_id, signal in signals.items():
        by_status.setdefault(signal["status"], []).append(probe_id)
    coverage["signals_by_status"] = by_status
    coverage["signals_measured"] = bool(by_status.get(MEASURED))
    updated["coverage"] = coverage
    return updated


def profile_independent(fingerprint: Mapping[str, Any]) -> dict[str, Any]:
    """The fingerprint without any scoring-profile-dependent value (for equality checks)."""
    result = {key: value for key, value in fingerprint.items()}
    result["signals"] = {
        probe_id: {k: v for k, v in signal.items() if k != "profile_dependent"}
        for probe_id, signal in (fingerprint.get("signals") or {}).items()
    }
    return result


def is_fingerprint_stale(fingerprint: Mapping[str, Any], current: AnalysisBaseline) -> bool:
    """True when the fingerprint was built for another baseline (hash, generation, loadout, item set, context, build)."""
    identity = fingerprint.get("identity") or {}
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
