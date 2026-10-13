"""FILTER-08B differential and false-negative benchmark library (offline, deterministic).

Everything here runs from stored needs snapshots (``artifacts/filter08b/needs``) and the pinned PoB2 snapshots:
no PoB process, no network, no game. The SAME item corpus is evaluated through every build, so any difference
is attributable to the build evidence and not to the items.
"""
from __future__ import annotations

import json
from collections import Counter, defaultdict
from dataclasses import dataclass
from itertools import combinations
from pathlib import Path
from typing import Iterable, Mapping, Sequence

from exilelens.filters.benchmark_corpus import LOOT_CASES, LootCase
from exilelens.filters.build_needs import BuildNeedsSnapshot, Relevance
from exilelens.filters.intel_generate import GenerationResult, generate
from exilelens.filters.opportunity import ROLE_BY_CLASS
from exilelens.filters.preview import PreviewDecision, PreviewItem, preview_decision
from exilelens.filters.profiles import FilterProfileName
from exilelens.filters.verified_bases import FILTER_TO_POB_CLASS, load_base_properties, native_class

PROFILES = tuple(profile.value for profile in FilterProfileName)
_NATIVE_BY_POB = {pob: native for native, pob in FILTER_TO_POB_CLASS.items()}


# -- snapshots ------------------------------------------------------------------------------------------
def load_snapshots(directory: Path) -> dict[str, BuildNeedsSnapshot]:
    snapshots = {}
    for path in sorted(Path(directory).glob("*.json")):
        if path.name.endswith(".error.json"):
            continue
        snapshots[path.stem] = BuildNeedsSnapshot.from_dict(json.loads(path.read_text(encoding="utf-8")))
    return snapshots


def build_tags(needs: BuildNeedsSnapshot) -> frozenset[str]:
    """Archetype tags used to scope build-specific expectations (never read from the generator)."""
    tags = {f"mode:{needs.skill.mode}"}
    for cls in needs.skill.weapon_classes or ():
        tags.add(f"weapon:{cls}")
    for element in needs.skill.elements:
        tags.add(f"element:{element}")
    return frozenset(tags)


# -- systematic item corpus ---------------------------------------------------------------------------------
_STATES = (
    ("normal-q0-i82", "Normal", 82, 0, 0),
    ("normal-q20-i82", "Normal", 82, 20, 0),
    ("magic-i75", "Magic", 75, 0, 0),
    ("magic-i82", "Magic", 82, 0, 0),
    ("rare-i82-u3", "Rare", 82, 0, 3),
    ("rare-i70-u1", "Rare", 70, 0, 1),
    ("magic-i86", "Magic", 86, 0, 0),          # reaches the Very Strict / Endgame item-level gates
    ("normal-q25-i86", "Normal", 86, 25, 0),
)


def probe_bases(per_class_top: int = 8, per_class_spread: int = 4) -> dict[str, list[str]]:
    """Per supported equipment class: the highest-requirement bases plus an evenly spread mid/low sample."""
    by_class: dict[str, list[tuple[int, str]]] = defaultdict(list)
    for base, record in load_base_properties().items():
        native = native_class(base)
        if native in ROLE_BY_CLASS and not base.startswith(("Runeforged ", "Runemastered ")):
            by_class[native].append((int(record["required_level"]), base))
    chosen: dict[str, list[str]] = {}
    for native, rows in by_class.items():
        rows.sort(key=lambda row: (-row[0], row[1]))
        top = [base for _, base in rows[:per_class_top]]
        rest = rows[per_class_top:]
        step = max(1, len(rest) // per_class_spread) if rest else 1
        spread = [base for _, base in rest[::step][:per_class_spread]]
        chosen[native] = top + spread
    return chosen


def systematic_items() -> list[PreviewItem]:
    properties = load_base_properties()
    items: list[PreviewItem] = []
    for native, bases in sorted(probe_bases().items()):
        for base in bases:
            record = properties[base]
            for state, rarity, level, quality, tier in _STATES:
                items.append(PreviewItem(
                    f"{base} [{state}]", "FILTER-08B systematic", native, base, rarity, item_level=level,
                    quality=quality, unidentified_item_tier=tier, base_energy_shield=record["energy_shield"],
                    base_armour=record["armour"], base_evasion=record["evasion"]))
    return items


# -- evaluation -----------------------------------------------------------------------------------------------
@dataclass(frozen=True)
class Decision:
    hidden: bool
    rule: str
    source: str
    font_size: int
    personalised: bool
    coverage: str
    kinds: tuple[str, ...]
    reason: str
    native_rule: tuple[str, ...]


def _classify(result: GenerationResult, preview: PreviewDecision) -> Decision:
    rule = next((r for r in result.rules if r.name == preview.rule_name), None)
    evidence = rule.evidence if rule else None
    coverage = evidence.coverage if evidence and evidence.coverage else ""
    shifted = bool(rule and any(d.shift != 0 for d in getattr(rule, "decisions", ())))
    verified_class = bool(rule and any(r.kind.name in {"VERIFIED_BASE_FACT", "MEASURED_BUILD_RESPONSE"}
                                       for r in getattr(rule, "class_reasons", ())))
    personalised = bool(rule and rule.category.startswith("BUILD") and not preview.hidden and
                        coverage in ("MEASURED PERSONALIZATION", "PARTIAL PERSONALIZATION") and
                        (shifted or verified_class or rule.name.startswith("Opportunity_")))
    return Decision(preview.hidden, preview.rule_name, preview.source, preview.font_size, personalised, coverage,
                    tuple(evidence.evidence_kinds) if evidence else (), preview.reason,
                    tuple(line.strip() for line in rule.lines) if rule else ())


def evaluate(result: GenerationResult, items: Sequence[PreviewItem]) -> list[Decision]:
    return [_classify(result, preview_decision(result.rules, item)) for item in items]


def evaluate_all(snapshots: Mapping[str, BuildNeedsSnapshot], items: Sequence[PreviewItem],
                 *, intel: bool = True) -> dict[str, dict[str, tuple[GenerationResult, list[Decision]]]]:
    out: dict[str, dict[str, tuple[GenerationResult, list[Decision]]]] = {}
    for label, needs in snapshots.items():
        out[label] = {}
        for profile in PROFILES:
            result = generate(needs, profile, intel=intel)
            out[label][profile] = (result, evaluate(result, items))
    return out


def differential(left: Sequence[Decision], right: Sequence[Decision], items: Sequence[PreviewItem]) -> dict:
    rows = []
    visibility = emphasis = 0
    for index, (a, b) in enumerate(zip(left, right)):
        if a.hidden != b.hidden:
            visibility += 1
        elif (a.rule, a.font_size, a.source) != (b.rule, b.font_size, b.source):
            emphasis += 1
        else:
            continue
        rows.append((index, a, b))
    return {"visibility_changed": visibility, "emphasis_or_rule_changed": emphasis,
            "genuinely_personalised": sum(1 for _, a, b in rows if a.personalised or b.personalised),
            "fallback_only": sum(1 for _, a, b in rows if not (a.personalised or b.personalised)),
            "_rows": rows}


def material_needs_difference(a: BuildNeedsSnapshot, b: BuildNeedsSnapshot) -> list[str]:
    """Why two builds' MEASURED needs differ materially (empty list = not materially different)."""
    reasons = []
    if a.skill.mode != b.skill.mode:
        reasons.append(f"damage mode {a.skill.mode} vs {b.skill.mode}")
    if (a.skill.weapon_classes or ()) != (b.skill.weapon_classes or ()):
        reasons.append("verified weapon requirement differs")
    strong = lambda n: {s.probe_id for s in n.signals if s.relevance_class.rank >= Relevance.STRONG.rank}
    if len(strong(a) ^ strong(b)) >= 2:
        reasons.append(f"strong responses differ: {sorted(strong(a) ^ strong(b))}")
    return reasons


def item_summary(item: PreviewItem) -> dict:
    return {"name": item.name, "base": item.base_type, "class": item.item_class, "rarity": item.rarity,
            "item_level": item.item_level, "quality": item.quality, "unidentified_tier": item.unidentified_item_tier}


def decision_summary(decision: Decision) -> dict:
    return {"hidden": decision.hidden, "rule": decision.rule, "source": decision.source, "font_size": decision.font_size,
            "personalised": decision.personalised, "confidence": decision.coverage, "evidence": list(decision.kinds),
            "reason": decision.reason, "native_rule": list(decision.native_rule[:6])}


# -- justification of visibility reductions (FILTER-08C) -----------------------------------------------------------------------
VERIFIED_INCOMPATIBILITY = "VERIFIED INCOMPATIBILITY"
MEASURED_BUILD_EVIDENCE = "MEASURED BUILD EVIDENCE"
EXPLICIT_PROFILE_POLICY = "EXPLICIT PROFILE POLICY"
INDEPENDENT_CLUTTER = "INDEPENDENTLY JUSTIFIED CLUTTER EXPECTATION"
UNEXPLAINED = "UNEXPLAINED"


def reduction_justification(item: PreviewItem, needs: BuildNeedsSnapshot, result: GenerationResult,
                            *, independent_clutter: bool = False, matched_rule: str = "") -> str:
    """Why an item the legacy generator showed is hidden by the intelligence generator.

    Exactly one of the milestone's four justifications, or UNEXPLAINED (a regression). Weak support never reaches
    the first three: an unmeasured build keeps every legacy-visible item (the extended classes stay visible too)."""
    from exilelens.filters.priorities import EXTENDED_OFFHAND_CLASSES, EXTENDED_WEAPON_CLASSES
    from exilelens.filters.profiles import ProductSlot
    rule = next((r for r in result.rules if r.name == matched_rule), None) if matched_rule else None
    if rule is not None and rule.justification.startswith("MEASURED BUILD EVIDENCE"):
        return MEASURED_BUILD_EVIDENCE               # a measured pure defence layer with no response (build_irrelevant_generic_nm)
    if rule is not None and rule.row and rule.state == "HIDE":
        return EXPLICIT_PROFILE_POLICY               # the approved profile matrix says this row is HIDE at this level
    role = ROLE_BY_CLASS.get(item.item_class)
    weapon = result.priorities.get(ProductSlot.WEAPON_1)
    candidates = {d.filter_class for d in weapon.decisions.values()} if weapon else set()
    if role == "weapon" and item.item_class not in candidates:
        if needs.skill.weapon_classes:
            return VERIFIED_INCOMPATIBILITY          # PoB2: the main skill requires other weapon classes
        if needs.has_measurement:
            return MEASURED_BUILD_EVIDENCE           # no spell-scaling family can be rolled by this class for a measured spell
    if needs.has_measurement and item.item_class in (*EXTENDED_WEAPON_CLASSES, *EXTENDED_OFFHAND_CLASSES):
        return EXPLICIT_PROFILE_POLICY               # uniform Normal/Magic clutter policy, applied once the build is measured
    if independent_clutter:
        return INDEPENDENT_CLUTTER
    return UNEXPLAINED


def with_layers(needs: BuildNeedsSnapshot, **layers: str) -> BuildNeedsSnapshot:
    """CONTROLLED COUNTERFACTUAL: replace the measured relevance of the three defence layers (AR / EV / ES).

    Used to exercise the layer-narrowing logic. It is not a measured build and is never reported as coverage."""
    from dataclasses import replace
    from exilelens.filters.build_needs import NeedSignal
    probes = {"AR": "ARMOUR", "EV": "EVASION", "ES": "ENERGY_SHIELD"}
    kept = tuple(s for s in needs.signals if s.probe_id not in probes.values())
    added = []
    for key, probe in probes.items():
        relevance = layers[key]
        if relevance == "NOT_ESTABLISHED":
            continue
        added.append(NeedSignal(
            probe_id=probe, label=probe.title(), category="defense", status="NO_SIGNAL" if relevance == "NO_RESPONSE" else "MEASURED",
            tested_change=f"+200 {probe} (counterfactual)", responses={"ehp": 3.0 if relevance in ("STRONG", "RESPONSIVE") else 0.0},
            confidence=layers.get(f"{key}_confidence", "HIGH"), relevance=relevance))
    return replace(needs, signals=(*kept, *added))
