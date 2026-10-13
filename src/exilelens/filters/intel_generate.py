"""Offline generation entry point for build-aware filters (FILTER-08B).

``generate()`` needs no PoB, no network and no game: a ``BuildNeedsSnapshot`` plus the pinned PoB2 snapshots
are enough, so the same stored measurement always yields the same filter. ``intel=False`` runs the legacy
(FILTER-07) generator on the identical build description, which is what the differential benchmark compares.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, replace
from functools import lru_cache
from datetime import datetime, timezone
from typing import Any

from exilelens.filters import degradation
from exilelens.filters.build_needs import BuildNeedsSnapshot
from exilelens.filters.data_drift import DataIncompatible, DataStatus, check as check_data
from exilelens.filters.intel_resolver import BuildIntelSlotPriorityResolver, IntelContext
from exilelens.filters.priorities import SlotPriorityResolver
from exilelens.filters.profiles import (BuildFingerprint, DefenseLayer, EquippedItemSummary, FilterProfileName,
                                        FilterThemeName, ProductSlot, RepairVectorSummary, get_profile_with_theme)
from exilelens.filters.rules import GeneratedRule, RuleGenerator
from exilelens.filters.serialize import FilterSerializer, create_metadata_from_fingerprint
from exilelens.filters.validation import validate_all
from exilelens.filters.verified_bases import load_base_properties

_EPOCH = datetime(2026, 1, 1, tzinfo=timezone.utc)  # fixed: generation must be deterministic
_SLOT_ALIASES = {slot.value: slot for slot in ProductSlot}


def defence_layer_of(needs: BuildNeedsSnapshot) -> DefenseLayer:
    """Same totals-based classification the legacy extractor uses, from the production fingerprint's observed values."""
    d = needs.observed_defence
    return DefenseLayer.from_totals(d.get("energy_shield", 0.0), d.get("armour", 0.0), d.get("evasion", 0.0), 0.0)


def fingerprint_from_needs(needs: BuildNeedsSnapshot, *, class_name: str = "", ascendancy: str = "") -> BuildFingerprint:
    """Minimal legacy BuildFingerprint reconstructed from a stored snapshot (no engine required)."""
    properties = load_base_properties()
    equipped: dict[ProductSlot, EquippedItemSummary] = {}
    for slot_name, base in needs.equipped.items():
        slot = _SLOT_ALIASES.get(slot_name)
        record = properties.get(base)
        if slot is None or record is None:
            continue
        equipped[slot] = EquippedItemSummary(
            slot=slot, base_type=base, item_class=record["class"], rarity="Rare", item_level=0, quality=0,
            base_armour=float(record["armour"]), base_evasion=float(record["evasion"]),
            base_energy_shield=float(record["energy_shield"]), base_ward=float(record.get("ward", 0)),
            implicit_mods=[], explicit_mods=[])
    return BuildFingerprint(
        build_name=needs.label, class_name=class_name or "Unknown", ascendancy=ascendancy or "Unknown",
        main_skill=needs.skill.name or "Unknown", main_skill_gem=needs.skill.name or "Unknown", equipped=equipped,
        offense_primary_dps=0.0, defense_ehp=0.0, life=0.0, energy_shield=needs.observed_defence.get("energy_shield", 0.0),
        mana=0.0, fire_res=0, cold_res=0, lightning_res=0, chaos_res=0, movement_speed=0.0, resist_caps={},
        blockers=[], repair_vector=RepairVectorSummary(repairs=[]), offense_coverage={}, thresholds=[],
        source_revision="stored needs snapshot", generated_at=_EPOCH, defense_layer=defence_layer_of(needs))


def filter_body_sha256(text: str) -> str:
    """SHA-256 of the RULES only (everything from the table of contents on).

    The header carries the build name, generation time and analysis time, so two dashboards generating the same decisions never
    share a whole-file hash; the body hash does not depend on them and is what a manual game test should compare."""
    marker = text.find("# [[TOC]]")
    body = text[marker:] if marker >= 0 else text
    return hashlib.sha256(body.replace("\r\n", "\n").encode("utf-8")).hexdigest()


def intelligence_header(needs: BuildNeedsSnapshot) -> dict[str, str]:
    """Header fields stating what the decisions rest on, so an installed file is never mistaken for a personalised one."""
    baseline = str((needs.identity or {}).get("baseline_fingerprint") or "")[:8]
    parts = [needs.coverage.value]
    if needs.measured_at:
        parts.append(f"analyzed {needs.measured_at}")
    if baseline:
        parts.append(f"baseline {baseline}")
    notes = "" if needs.coverage.name == "MEASURED" else "; ".join(needs.coverage_reasons)
    return {"intelligence": " · ".join(parts), "intelligence_notes": notes}


def data_header(status: DataStatus) -> str:
    v = status.versions
    detail = f"PoB2 {v.get('pob_version')} {str(v.get('pob_commit'))[:12]} · generator {v.get('generator_schema')}"
    return f"{status.state.value} · {detail}" + (f" · {'; '.join(status.reasons)}" if status.reasons else "")


@dataclass(frozen=True)
class GenerationResult:
    rules: list[GeneratedRule]
    text: str
    valid: bool
    errors: list[str]
    intel: IntelContext | None
    priorities: dict[ProductSlot, Any]
    data_status: DataStatus | None = None
    degradations: tuple = ()          # FILTER-08E: visible, non-blocking fallback states (degradation.Degradation)
    # (rule, base name, reason): declared names the native registry kept out of a grouped rule (never silent; empty in a clean catalog)
    excluded_bases: tuple = ()


@lru_cache(maxsize=1)
def _default_data_status() -> DataStatus:
    return check_data()


def generate(needs: BuildNeedsSnapshot, profile_name: str | FilterProfileName = "Recommended",
             theme: str | FilterThemeName = FilterThemeName.VOID_GOLD, *, intel: bool = True,
             fingerprint: BuildFingerprint | None = None, data_status: DataStatus | None = None,
             optimize: bool = False) -> GenerationResult:
    status = data_status or _default_data_status()
    if status.blocks and intel:
        raise DataIncompatible("Generation blocked: " + status.headline)
    fp = fingerprint or fingerprint_from_needs(needs)
    profile = get_profile_with_theme(profile_name, theme)
    if intel:
        resolver = BuildIntelSlotPriorityResolver(fp, needs, widen=status.widen)
        priorities = resolver.resolve_all()
        generator = RuleGenerator(priorities, profile, fp.main_skill, fp.defense_layer, intel=resolver.intel)
        context = resolver.intel
    else:
        priorities = SlotPriorityResolver(fp).resolve_all()
        generator = RuleGenerator(priorities, profile, fp.main_skill, fp.defense_layer)
        context = None
    rules = generator.generate_all()
    metadata = create_metadata_from_fingerprint(fp, profile)
    if intel:
        metadata = replace(metadata, **intelligence_header(needs), data_state=data_header(status))
    if optimize:
        from exilelens.filters.rule_ir import optimize_rules
        rules = optimize_rules(rules)
    text = FilterSerializer(metadata).serialize(rules)
    validity = validate_all(text)
    degradations = degradation.collect(context.model.check_integrity()) if context is not None else ()
    return GenerationResult(rules, text, validity.passed, list(validity.errors), context, priorities, status, degradations,
                            tuple(generator.excluded_bases))
