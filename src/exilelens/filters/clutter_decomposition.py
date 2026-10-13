"""Decomposition of the extra ground labels the Build Intelligence filter shows (FILTER-08D). Measurement only: no threshold is tuned.

"Newly visible" = an item the build-aware filter shows that the legacy build-independent generator hides. Each such item is assigned
to exactly one cause, taken from the generated rule that shows it and the opportunity decision for that base:

  MEASURED_STRONG        promoted by a STRONG / FIX_FIRST measured stat family (production measurement + verified pool)
  MEASURED_WEAK          promoted/kept by a RESPONSIVE or MARGINAL measured family
  AFFIX_POOL_OPPORTUNITY shown because the base can roll a measured family (verified pool) without a measured promotion of the base
  VERIFIED_COMPATIBILITY shown because verified data says the base class can serve the skill / equipped class
  VERIFIED_BASE_QUALITY  a build slot rule that keeps a base on its verified drop-level band (build-independent base quality)
  EQUIPPED_BASE          the build already wears this base (observed gear), so its class/tier is kept visible
  CRAFTING               a quality-normal crafting base rule
  CRAFT_OPPORTUNITY      the FILTER-09 CRAFT lane: a verified crafting substrate (build-independent)
  HEURISTIC_TRADE        a build-independent trade candidate rule (price unverified)
  CONSERVATIVE_SAFETY    a protective rule (currency, uniques, waystones ...), or widening because evidence is missing/incomplete
  FALLBACK_NOISE         build rule that rests only on a generic fallback (no measured or verified claim about this build)
  OTHER                  anything else (reported so nothing hides in a residual)

Recall side: items the legacy filter shows and the build-aware filter hides are counted per justification category.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from typing import Sequence

from exilelens.filters import benchmark08b as bm
from exilelens.filters.build_needs import BuildNeedsSnapshot
from exilelens.filters.intel_generate import generate
from exilelens.filters.opportunity import EvidenceKind
from exilelens.filters.preview import PreviewItem, preview_decision

CATEGORIES = ("MEASURED_STRONG", "MEASURED_WEAK", "AFFIX_POOL_OPPORTUNITY", "VERIFIED_COMPATIBILITY", "VERIFIED_BASE_QUALITY", "EQUIPPED_BASE", "CRAFTING", "CRAFT_OPPORTUNITY", "HEURISTIC_TRADE",
              "CONSERVATIVE_SAFETY", "FALLBACK_NOISE", "OTHER")


@dataclass(frozen=True)
class Visible:
    base: str
    item_class: str
    rarity: str
    slot: str
    category: str
    rule: str


def classify(rule, item: PreviewItem, *, widened: bool) -> tuple[str, str]:
    """(category, slot) of the rule that newly shows ``item``."""
    slot = rule.slot.value if getattr(rule, "slot", None) else ""
    if rule.category in ("PROTECTIVE", "TRADE_HERO", "TRADE_SPECIAL") or rule.category.startswith("CURRENCY_"):
        return "CONSERVATIVE_SAFETY", slot
    if rule.category == "CRAFTING_BASES":
        return "CRAFTING", slot
    if rule.category == "CRAFT_OPPORTUNITY":
        return "CRAFT_OPPORTUNITY", slot
    if rule.category == "TRADE_BASES":
        return "HEURISTIC_TRADE", slot
    if not rule.category.startswith("BUILD"):
        return "OTHER", slot
    decision = next((d for d in (rule.decisions or ()) if d.base == (item.base_type or item.name)), None)
    reasons = {r.kind for r in (rule.class_reasons or ())}
    if decision is not None:
        kinds = {r.kind for r in decision.reasons}
        if decision.shift > 0 and decision.relevance is not None:
            return ("MEASURED_STRONG" if decision.relevance.rank >= 4 else "MEASURED_WEAK"), slot
        if EvidenceKind.AFFIX_POOL_OPPORTUNITY in kinds:
            return "AFFIX_POOL_OPPORTUNITY", slot
    if widened:
        return "CONSERVATIVE_SAFETY", slot
    if decision is not None and str(getattr(decision, "quality_source", "")).startswith("equipped"):
        return "EQUIPPED_BASE", slot
    if decision is not None and str(getattr(decision, "quality_source", "")).startswith("verified") and             EvidenceKind.MEASURED_BUILD_RESPONSE not in reasons:
        return "VERIFIED_BASE_QUALITY", slot
    if EvidenceKind.MEASURED_BUILD_RESPONSE in reasons:
        return "MEASURED_WEAK", slot
    if EvidenceKind.VERIFIED_BASE_FACT in reasons:
        return "VERIFIED_COMPATIBILITY", slot
    evidence = rule.evidence.build_relevance if rule.evidence else ""
    if evidence.startswith("Generic fallback") or EvidenceKind.CONSERVATIVE_FALLBACK in reasons:
        return "FALLBACK_NOISE", slot
    return "OTHER", slot


def decompose(needs: BuildNeedsSnapshot, profile: str, items: Sequence[PreviewItem]) -> dict[str, object]:
    new = generate(needs, profile)
    old = generate(needs, profile, intel=False)
    widened = not needs.evidence_complete
    visible: list[Visible] = []
    reductions: Counter[str] = Counter()
    for item in items:
        a, b = preview_decision(new.rules, item), preview_decision(old.rules, item)
        if not a.hidden and b.hidden:
            rule = next(r for r in new.rules if r.name == a.rule_name)
            category, slot = classify(rule, item, widened=widened)
            visible.append(Visible(item.base_type or item.name, item.item_class, item.rarity, slot, category, a.rule_name))
        elif a.hidden and not b.hidden:
            reductions[bm.reduction_justification(item, needs, new, matched_rule=a.rule_name)] += 1
    return {"newly_visible": visible, "reductions": dict(reductions), "legacy_shown": sum(not preview_decision(old.rules, i).hidden for i in items),
            "intel_shown": sum(not preview_decision(new.rules, i).hidden for i in items), "items": len(items)}


def aggregate(rows: Sequence[Visible]) -> dict[str, dict[str, int]]:
    out: dict[str, dict[str, int]] = {"by_category": Counter(), "by_slot": Counter(), "by_class": Counter(), "by_rarity": Counter()}
    for row in rows:
        out["by_category"][row.category] += 1
        out["by_slot"][row.slot or "(none)"] += 1
        out["by_class"][row.item_class] += 1
        out["by_rarity"][row.rarity] += 1
    return {k: dict(v.most_common()) for k, v in out.items()}


def archetype_of(needs: BuildNeedsSnapshot) -> str:
    tags = bm.build_tags(needs)
    for key in ("mode:MINION", "mode:SPELL", "mode:ATTACK"):
        if key in tags:
            return key.split(":")[1].lower()
    return "unresolved"


def uniform_items(level: int, rarity: str) -> list[PreviewItem]:
    """Every verified equipment base that can drop at ``level`` (uniform weight: no drop-weight data exists in the pinned snapshots)."""
    from exilelens.filters.opportunity import ROLE_BY_CLASS
    from exilelens.filters.verified_bases import load_base_properties, native_class
    items = []
    for base, record in load_base_properties().items():
        native = native_class(base)
        if native in ROLE_BY_CLASS and not base.startswith(("Runeforged ", "Runemastered ")) and record["required_level"] <= level:
            items.append(PreviewItem(base, "clutter", native, base, rarity, item_level=level, base_energy_shield=record["energy_shield"],
                                     base_armour=record["armour"], base_evasion=record["evasion"]))
    return items
