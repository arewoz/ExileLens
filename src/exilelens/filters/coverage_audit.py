"""Complete item-family audit and modifier-family registry (FILTER-08D). Pure functions over the pinned datasets.

Nothing is invented: classes, tags, handedness, requirements and pools all come from ``poe2_item_catalog.json`` /
``poe2_affix_pools.json`` / ``poe2_skill_facts.json``. The only classification tables here map VERIFIED TAG NAMES to the filter's slot
vocabulary; a base none of whose tags names a slot is reported as unclassified, never guessed.
"""
from __future__ import annotations

import json
from collections import Counter, defaultdict
from functools import lru_cache
from pathlib import Path
from typing import Any, Mapping

from exilelens.filters import affix_pools as pools
from exilelens.filters import skill_facts
from exilelens.filters.data_drift import GENERATOR_SCHEMA
from exilelens.filters.opportunity import ROLE_BY_CLASS
from exilelens.filters.priorities import BASE_TIERS, CATALOG_AUDIT, RETIRED_MISFILED_TIERS, EXTENDED_OFFHAND_CLASSES, EXTENDED_WEAPON_CLASSES, SLOT_EQUIPMENT_CLASSES
from exilelens.filters.verified_bases import FILTER_TO_POB_CLASS, native_class

CATALOG_FILE = Path(__file__).with_name("data") / "poe2_item_catalog.json"

# Native item classes confirmed against PoE2DB's equipment item-class list (https://poe2db.tw/us/Items, checked 2026-10-02).
POE2DB_EQUIPMENT_CLASSES = frozenset({
    "Claws", "Daggers", "Wands", "One Hand Swords", "One Hand Axes", "One Hand Maces", "Sceptres", "Spears", "Flails", "Bows", "Staves",
    "Two Hand Swords", "Two Hand Axes", "Two Hand Maces", "Quarterstaves", "Crossbows", "Traps", "Talismans", "Quivers", "Shields",
    "Bucklers", "Foci", "Gloves", "Boots", "Body Armours", "Helmets", "Amulets", "Rings", "Belts", "Jewels", "Charms"})

# FILTER-08E: every PoB2 class that still has no native filter class carries an explicit, sourced disposition (never silently unclassified).
UNCLASSIFIED_DISPOSITION = {
    "Fishing Rod": ("AMBIGUOUS IN PINNED DATA", "PoB2 carries the class, but the PoE2DB item-class list (checked 2026-10-03) does not list a "
                    "fishing-rod class, so no native Class name can be verified. Not equipment; no build relevance; no rule is generated."),
    "Transcendent Limb": ("AMBIGUOUS IN PINNED DATA", "PoB2 0.23.1 carries 12 Arm/Leg bases (required level 0, implicit-only), but the PoE2DB "
                          "item-class list (checked 2026-10-03) does not list them, so the native Class name cannot be verified. They are a "
                          "class-specific special item, not ground-filter gear; unsupported until a verified class name exists."),
}


# Verified PoB2 tag name -> slot vocabulary. First match wins; a base matching none has NO verified slot.
SLOT_TAGS = (("ring", "RING"), ("amulet", "AMULET"), ("belt", "BELT"), ("helmet", "HELMET"), ("gloves", "GLOVES"), ("boots", "BOOTS"),
             ("body_armour", "BODY_ARMOUR"), ("shield", "OFFHAND"), ("focus", "OFFHAND"), ("quiver", "OFFHAND"), ("weapon", "WEAPON"),
             ("wand", "WEAPON"), ("staff", "WEAPON"), ("sceptre", "WEAPON"), ("trap", "TRAP"), ("jewel", "JEWEL"),
             ("utility_flask", "CHARM"), ("flask", "FLASK"), ("fishing_rod", "FISHING_ROD"))
BUILD_RULE_SLOT_CLASSES = frozenset(ROLE_BY_CLASS) - {"Belts"}      # classes that receive build-aware (BUILD_*) rules
CONDITIONAL_RULE_CLASSES = frozenset({"Belts"})     # FILTER-08E: a Show rule exists only for belts whose verified implicit supports a STRONG/FIX_FIRST need


@lru_cache(maxsize=1)
def catalog() -> dict[str, dict[str, Any]]:
    return json.loads(CATALOG_FILE.read_text(encoding="utf-8"))["bases"]


def slot_of(record: Mapping[str, Any]) -> str | None:
    tags = set(record["tags"])
    return next((slot for tag, slot in SLOT_TAGS if tag in tags), None)


def handedness(record: Mapping[str, Any]) -> str:
    tags = set(record["tags"])
    if "twohand" in tags:
        return "two-handed"
    if "onehand" in tags:
        return "one-handed"
    return "n/a"


def _skills_requiring() -> dict[str, int]:
    counts: Counter[str] = Counter()
    for sid in skill_facts._skills():
        profile = skill_facts.lookup(skill_id=sid)
        if profile and profile.weapon_classes and sid.endswith("Player"):
            counts.update(profile.weapon_classes)
    return dict(counts)


def _handling(native: str | None) -> dict[str, bool]:
    return {
        "build_rules": native in BUILD_RULE_SLOT_CLASSES,
        "global_quality_and_trade_rules": native in ROLE_BY_CLASS,
        "generic_clutter_policy": native in set(BASE_TIERS) | set(EXTENDED_WEAPON_CLASSES) | set(EXTENDED_OFFHAND_CLASSES),
        "curated_tiers": bool(BASE_TIERS.get(native or "")),
    }


def family_matrix() -> dict[str, Any]:
    """Machine-readable matrix: one row per PoB class plus global detections and explicit coverage percentages."""
    records = catalog()
    by_class: dict[str, list[str]] = defaultdict(list)
    for name, record in records.items():
        by_class[record["class"]].append(name)
    skill_counts = _skills_requiring()
    rows = {}
    for pob_class, names in sorted(by_class.items()):
        natives = Counter(native_class(n) for n in names)
        native_names = sorted(k for k in natives if k)
        levels = [records[n]["required_level"] for n in names]
        slots = Counter(slot_of(records[n]) for n in names)
        tag_sets = [set(records[n]["tags"]) for n in names]
        common = sorted(set.intersection(*tag_sets))
        fam_counts: Counter[str] = Counter()
        for n in names:
            fam_counts.update(pools.pools_for(n).keys())
        rows[pob_class] = {
            "bases": len(names), "native_classes": native_names, "unclassified_native": natives.get(None, 0),
            "slots": {str(k): v for k, v in sorted(slots.items(), key=lambda kv: str(kv[0]))},
            "handedness": dict(Counter(handedness(records[n]) for n in names)),
            "weapon_requirement_skills": {c: skill_counts.get(c, 0) for c in native_names if c in skill_counts},
            "intrinsic_defence_archetypes": dict(Counter("".join(t for t, k in (("A", "armour"), ("E", "evasion"), ("S", "energy_shield")) if records[n][k]) or "none" for n in names)),
            "bases_with_implicit": sum(1 for n in names if records[n]["implicit"]),
            "required_level": {"min": min(levels), "max": max(levels)},
            "quality_values": sorted({records[n]["quality"] for n in names}),
            "common_tags": common,
            "modifier_families_rollable": {fam: count for fam, count in sorted(fam_counts.items())},
            "native_class_verified_poe2db": all(k in POE2DB_EQUIPMENT_CLASSES for k in native_names) if native_names else False,
            "filter_handling": {k: _handling(k) for k in native_names},
            "native_observables": ["Class", "BaseType", "ItemLevel", "Rarity", "Quality", "UnidentifiedItemTier"]
                                  + (["BaseArmour", "BaseEvasion", "BaseEnergyShield"] if any(records[n]["armour"] or records[n]["evasion"] or records[n]["energy_shield"] for n in names) else []),
        }
    total = len(records)
    # class-level gap: PoB classes with no native filter Class at all (name-level exclusions are the registry's, reported separately below)
    from exilelens.filters import native_bases as _nb
    unclassified = sorted(n for n in records if _nb.pob_native_class(n, records[n]["class"]) is None)
    outside_ground = Counter(_nb.status_of(n).value for n in records if not _nb.is_ground_base(n))
    no_slot = sorted(n for n in records if slot_of(records[n]) is None)
    in_build = sum(1 for n in records if native_class(n) in BUILD_RULE_SLOT_CLASSES)
    in_global = sum(1 for n in records if native_class(n) in ROLE_BY_CLASS)
    pooled = sum(1 for n in records if pools.pools_for(n))
    verified = sum(1 for n in records if native_class(n) in POE2DB_EQUIPMENT_CLASSES and slot_of(records[n]) is not None)
    fallback_only = sorted({records[n]["class"] for n in records if native_class(n) not in ROLE_BY_CLASS})
    equipment = [n for n in records if native_class(n) in POE2DB_EQUIPMENT_CLASSES]
    detections = {
        "unclassified_bases (no native class)": {"count": len(unclassified), "by_pob_class": dict(Counter(records[n]["class"] for n in unclassified))},
        "pob_bases_outside_native_ground_set (never emitted, by registry status)": dict(sorted(outside_ground.items())),
        "bases_without_verified_slot_tag": {"count": len(no_slot), "by_pob_class": dict(Counter(records[n]["class"] for n in no_slot))},
        "bases_in_multiple_incompatible_classes": [],          # parse_bases fails closed on a conflicting class; the check is structural
        "classes_without_build_rules": sorted(set(FILTER_TO_POB_CLASS) - BUILD_RULE_SLOT_CLASSES - CONDITIONAL_RULE_CLASSES),
        "classes_with_conditional_implicit_rules (FILTER-08E)": sorted(CONDITIONAL_RULE_CLASSES),
        "valid_pob_classes_without_filter_native_class": sorted({records[n]["class"] for n in unclassified}),
        "families_visible_only_through_generic_fallback": fallback_only,
        "legacy_curated_suggestions": {"examined": CATALOG_AUDIT["examined"], "verified_in_data": CATALOG_AUDIT["verified"],
                                       "absent_poe1_leftovers": len(CATALOG_AUDIT["absent"]), "wrong_class": len(CATALOG_AUDIT["wrong_class"])},
        "curated_tier_entries_in_wrong_native_class (active)": [f"{c}:{b}" for c, t in BASE_TIERS.items() for b in t if native_class(b) != c],
        "retired_misfiled_curated_tiers": dict(RETIRED_MISFILED_TIERS),
        "dead_skill_map_entries": [k for k in __import__("exilelens.filters.priorities", fromlist=["x"]).SKILL_WEAPON_CLASSES if skill_facts.lookup(name=k) is None],
    }
    coverage = {
        "bases": total, "equipment_bases (native class verified against PoE2DB)": len(equipment),
        "verified_classification_pct": round(100 * verified / total, 1),
        "itemization_intelligence_pct (global tier + modifier pools)": round(100 * sum(1 for n in records if native_class(n) in ROLE_BY_CLASS and pools.pools_for(n)) / total, 1),
        "build_personalization_pct (BUILD_* rules)": round(100 * in_build / total, 1),
        "fallback_only_pct (no build or global-tier handling)": round(100 * (total - in_global) / total, 1),
        "modifier_pool_available_pct": round(100 * pooled / total, 1),
        "of_equipment_bases": {
            "verified_classification_pct": round(100 * sum(1 for n in equipment if slot_of(records[n])) / len(equipment), 1),
            "build_personalization_pct": round(100 * sum(1 for n in equipment if native_class(n) in BUILD_RULE_SLOT_CLASSES) / len(equipment), 1),
            "fallback_only_pct": round(100 * sum(1 for n in equipment if native_class(n) not in ROLE_BY_CLASS) / len(equipment), 1)},
    }
    return {"generator_schema": GENERATOR_SCHEMA, "classes": rows, "detections": detections, "coverage": coverage}


def family_registry() -> dict[str, Any]:
    """Every stat/modifier family tied to a production probe: who can roll it, from which item level, what excludes it."""
    from exilelens.analysis.catalog import ProbeCatalog
    records = catalog()
    definitions = pools.family_definitions()
    production_global = set(ProbeCatalog().global_ids(minion_owned=True, crit_chance=1.0, ignite_dps=1.0, poison_dps=1.0))
    out: dict[str, Any] = {}
    for family, definition in definitions.items():
        per_class: dict[str, dict[str, Any]] = defaultdict(lambda: {"able": 0, "total": 0, "levels": []})
        able_tags: dict[str, list[set[str]]] = defaultdict(list)
        unable_tags: dict[str, list[set[str]]] = defaultdict(list)
        slots: set[str] = set()
        for name, record in records.items():
            native = native_class(name)
            if native is None or native not in ROLE_BY_CLASS:
                continue
            entry = per_class[native]
            entry["total"] += 1
            pool = pools.pools_for(name).get(family)
            if pool is not None:
                entry["able"] += 1
                entry["levels"].append((pool.first_level, pool.top_level))
                able_tags[native].append(set(record["tags"]))
                slot = slot_of(record)
                if slot:
                    slots.add(slot)
            else:
                unable_tags[native].append(set(record["tags"]))
        classes = {}
        for native, entry in sorted(per_class.items()):
            if not entry["able"]:
                continue
            exclusions = []
            if unable_tags[native]:
                exclusions = sorted(set.intersection(*unable_tags[native]) - set.union(*able_tags[native]))
            classes[native] = {"bases_able": entry["able"], "bases_in_class": entry["total"],
                               "first_item_level": min(a for a, _ in entry["levels"]), "top_tier_item_level": max(b for _, b in entry["levels"]),
                               "universal_in_class": entry["able"] == entry["total"], "excluded_by_tags": exclusions}
        implicit_bases = sorted(n for n in records if family in pools.implicit_families(n))
        universal_everywhere = bool(classes) and all(c["universal_in_class"] for c in classes.values())
        out[family] = {
            "probe_id": definition["probe_id"], "relation": definition["relation"],
            "applies_when": ("always (the measured stat itself)" if definition["relation"] == "DIRECT" else
                             "only for a verified spell of that element / damage mode (PoB2 skill facts)"),
            "slots": sorted(slots), "classes": classes, "bases_with_verified_implicit": len(implicit_bases),
            "native_proxy": ("Class + BaseType + ItemLevel (class-level only: every eligible base can roll it)" if universal_everywhere
                             else "Class + BaseType + ItemLevel (base-specific: some bases of an eligible class cannot roll it)") if classes
                            else "none from pools (implicit-only)" if implicit_bases else "none",
            "modifier_observable_on_unidentified_item": False,
            "production_runs_probe_globally": definition["probe_id"] in production_global,
            "language": "eligible opportunity for this measured stat family; an unidentified item is never said to HAVE the stat"}
    return {"generator_schema": GENERATOR_SCHEMA, "families": out}
