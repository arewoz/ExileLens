"""Inspectable generation-time evidence; no runtime game or market access."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum


class MarketLevel(str, Enum):
    LIVE = "LIVE MARKET"
    CACHED = "CACHED MARKET"
    HEURISTIC = "HEURISTIC"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class MarketContext:
    level: MarketLevel = MarketLevel.HEURISTIC
    source: str = "pinned item category/base heuristics"
    league: str = "unverified"
    observed_at: datetime | None = None

    def __post_init__(self) -> None:
        if self.level not in (MarketLevel.HEURISTIC, MarketLevel.UNKNOWN):
            if not self.source or self.league == "unverified" or self.observed_at is None:
                raise ValueError("Measured market context needs source, league and observation time")
            if self.observed_at.tzinfo is None:
                raise ValueError("Market observation time must include a timezone")
            if self.observed_at > datetime.now(timezone.utc):
                raise ValueError("Market observation time cannot be in the future")

    @property
    def description(self) -> str:
        if self.level == MarketLevel.UNKNOWN:
            return "UNKNOWN · no market information; nothing inferred"
        if self.level == MarketLevel.HEURISTIC:
            return "HEURISTIC · no current league price or confirmed sale"
        return f"{self.level.value} · {self.source} · {self.league} · {self.observed_at.isoformat()}"


@dataclass(frozen=True)
class DecisionEvidence:
    build_relevance: str
    item_potential: str
    crafting_potential: str
    market_opportunity: str
    general_importance: str
    unknowns: str
    native_conditions: tuple[str, ...]
    # FILTER-08B: why this rule exists. Empty for legacy rules; explain() is then byte-identical to before.
    confidence: str = ""
    evidence_kinds: tuple[str, ...] = ()
    coverage: str = ""
    details: tuple[str, ...] = ()
    decisions: tuple = ()
    market_context: str = ""
    lane: str = ""                    # FILTER-09: the opportunity lane that produced this rule (CRAFT), empty otherwise

    def explain(self) -> str:
        text = (f"Build: {self.build_relevance}; Base: {self.item_potential}; "
                f"Craft: {self.crafting_potential}; Market: {self.market_opportunity}; "
                f"Protection: {self.general_importance}; Unknown: {self.unknowns}")
        if self.coverage:
            text += f"; Confidence: {self.coverage}; Evidence: {', '.join(self.evidence_kinds) or 'none'}"
        return text

    def sections(self, base: str | None = None) -> list[tuple[str, str]]:
        """Compact provenance for one item: BUILD / ITEMIZATION / CRAFT / MARKET / CONFIDENCE.

        ``base`` selects that base's own decision (rules never mix promoted and unpromoted bases, but a rule can still list
        many). Legacy rules (no decisions) report their category-level text unchanged."""
        if self.lane == "CRAFT" and base:
            from exilelens.filters import crafting_intel as ci
            a = ci.assess(base)
            craft = f"{a.level.value} substrate · " + "; ".join(a.reasons[:3])
            if a.breakpoints:
                craft += (f" · item-level breakpoints {a.breakpoints.get('meaningful')}/{a.breakpoints.get('high')}/"
                          f"{a.breakpoints.get('premium')} (60/85/95 % of its affix tiers unlocked)")
            return [("BUILD", self.build_relevance), ("ITEMIZATION", self.item_potential), ("CRAFT", craft + " (build-independent)"),
                    ("MARKET", self.market_context or self.market_opportunity),
                    ("CONFIDENCE", f"{a.confidence} — shown for its crafting value, not as a build upgrade")]
        decision = next((d for d in self.decisions if d.base == base), None) if base else None
        if decision is None and self.decisions and base is None:
            decision = self.decisions[0]
        if decision is not None:
            from exilelens.filters.opportunity import EvidenceKind
            specific = next((r.text for r in decision.reasons if not r.text.startswith("Base quality") and
                             r.kind in (EvidenceKind.AFFIX_POOL_OPPORTUNITY, EvidenceKind.VERIFIED_BASE_FACT)), "")
            quality = next((r.text for r in decision.reasons if r.text.startswith("Base quality")), "")
            itemization = specific or quality
            craft = (f"{decision.crafting.level.title()} potential"
                     + (f" · top affix tiers unlock at item level {decision.crafting.unlock_item_level}"
                        if decision.crafting.unlock_item_level else "") + " (build-independent)")
        else:
            itemization, craft = self.item_potential, self.crafting_potential
        rows = [("BUILD", self.build_relevance), ("ITEMIZATION", itemization), ("CRAFT", craft),
                ("MARKET", self.market_context or self.market_opportunity)]
        if self.coverage:
            rows.append(("CONFIDENCE", f"{self.coverage} — exact unidentified affixes are unknown"))
        return rows

    def detail_lines(self) -> list[str]:
        """Secondary (hover) reasons: the evidence rows behind the compact view."""
        return list(self.details)


def _intel_evidence(rule) -> dict:
    """Relevance/provenance text derived from the rule's per-base decisions (build-aware rules only)."""
    from exilelens.filters.build_needs import Coverage
    from exilelens.filters.opportunity import EvidenceKind

    decisions = tuple(getattr(rule, "decisions", ()) or ())
    class_reasons = tuple(getattr(rule, "class_reasons", ()) or ())
    shifted = [d for d in decisions if d.shift != 0]
    kinds: list[str] = []
    details: list[str] = []
    for reason in class_reasons[:2]:
        kinds.append(reason.kind.value)
        details.append(reason.text)
    if shifted:
        sample = shifted[0]
        promoted = sum(d.shift > 0 for d in shifted)
        demoted = sum(d.shift < 0 for d in shifted)
        for reason in sample.reasons:
            if reason.kind in (EvidenceKind.MEASURED_BUILD_RESPONSE, EvidenceKind.AFFIX_POOL_OPPORTUNITY,
                               EvidenceKind.VERIFIED_BASE_FACT) and not reason.text.startswith("Base quality"):
                kinds.append(reason.kind.value)
                details.append(reason.text)
        details.append(f"{promoted} base(s) promoted, {demoted} demoted in this rule; example {sample.base}")
        coverage = sample.coverage
    elif decisions:
        coverage = Coverage.FALLBACK if all(d.coverage == Coverage.FALLBACK for d in decisions) else Coverage.PARTIAL
        kinds.append(EvidenceKind.CONSERVATIVE_FALLBACK.value)
    else:
        coverage = getattr(rule, "coverage", None) or Coverage.FALLBACK
    if class_reasons and getattr(rule, "coverage", None) is not None and not shifted:
        coverage = rule.coverage
    measured = bool(shifted) or any(r.kind == EvidenceKind.MEASURED_BUILD_RESPONSE for r in class_reasons)
    return {"coverage": coverage, "kinds": tuple(dict.fromkeys(kinds)), "details": tuple(dict.fromkeys(details)), "measured": measured}


def evidence_for_rule(rule, market: MarketContext, *, skill: str,
                      skill_mapped: bool = False) -> DecisionEvidence:
    """Describe each independent dimension without assigning an invented score."""
    category = rule.category
    conditions = tuple(line.strip() for line in rule.lines
                       if line.strip() and line.strip() not in {"Show", "Hide"}
                       and not line.lstrip().startswith(("Set", "Play", "MinimapIcon", "Continue", "DisableDropSound")))
    protected = category in {"PROTECTIVE", "TRADE_HERO", "TRADE_SPECIAL"} or category.startswith("CURRENCY_")
    build = category.startswith("BUILD")
    trade = category in {"TRADE_BASES", "TRADE_HERO", "TRADE_SPECIAL", "CURRENCY_TOP", "CURRENCY_PREMIUM", "CURRENCY_VALUABLE"}
    craft = category == "CRAFTING_BASES" or rule.name.endswith("_Craft") or category == "CURRENCY_CRAFT"
    hidden = any(line.strip() == "Hide" for line in rule.lines)
    if category == "UNKNOWN_SAFETY":
        return DecisionEvidence(
            build_relevance="not evaluated: the item is not classified by any row",
            item_potential="unknown to the pinned snapshot (new base / new class / unnamed currency)",
            crafting_potential="not evaluated", market_opportunity=market.description,
            general_importance="SAFETY: unclassified items stay visible, never silently hidden",
            unknowns="everything: the pinned data does not know this item",
            native_conditions=conditions or ("(no condition: every item no earlier rule decided)",), confidence="UNKNOWN",
            evidence_kinds=("UNKNOWN / SAFETY",), coverage="SAFETY catch-all",
            details=("explicit catch-all after every Hide: a patch can add bases the snapshot does not list",),
            market_context=market.description, lane="SAFETY")
    if getattr(rule, "row", "") == "known_generic_fallback":
        return DecisionEvidence(
            build_relevance="not evaluated: no build claim for this class",
            item_potential="known base of the pinned catalog; its class has no profile-matrix row and no specialised rule",
            crafting_potential="not evaluated", market_opportunity=market.description,
            general_importance="KNOWN_GENERIC: a known item shown with the restrained generic treatment (never the unknown treatment)",
            unknowns="market value, rolled modifiers",
            native_conditions=conditions, confidence="VERIFIED",
            evidence_kinds=("known generic fallback",), coverage="KNOWN_GENERIC fallback",
            details=("a verified base of a class without a matrix row: visible, themed, not 'unknown'",),
            market_context=market.description, lane="KNOWN_GENERIC")
    if category == "CRAFT_OPPORTUNITY":
        reasons = tuple(getattr(rule, "class_reasons", ()) or ())
        return DecisionEvidence(
            build_relevance="not a build claim: the CRAFT lane is independent of the current build (the BUILD lane judges this base separately)",
            item_potential="pinned PoB2 catalog: implicit, drop level, intrinsic strength; affix pools for item-level breakpoints",
            crafting_potential=(reasons[0].text if reasons else "crafting substrate (build-independent)"),
            market_opportunity=market.description,
            general_importance="none",
            unknowns="rolled modifiers (Normal/Magic base shown as a substrate), market price, whether the build can use the result",
            native_conditions=conditions, confidence="VERIFIED",
            evidence_kinds=("crafting opportunity",), coverage="CRAFT lane", details=tuple(r.text for r in reasons[:2]),
            market_context=market.description, lane="CRAFT")
    intel = None
    if build and (getattr(rule, "decisions", ()) or getattr(rule, "class_reasons", ())):
        intel = _intel_evidence(rule)
    if intel is not None:
        from exilelens.filters.build_needs import Coverage
        measured = intel["measured"]
        if category in {"BUILD_WEAPON", "BUILD_OFFHAND"}:
            if skill_mapped:
                relevance = ("Relevant base for a stat family your build responds to (measured); exact unidentified "
                             "modifiers are unknown" if measured else
                             f"{skill} class evidence is verified, but no measured base-specific advantage")
            else:
                relevance = (f"Generic fallback for unsupported or unmapped skill {skill}; equipped class may be "
                             "retained, skill benefit unverified")
        elif measured:
            relevance = ("Relevant base for a stat family your build responds to (measured); unidentified modifiers "
                         "are not observable")
        else:
            relevance = ("Observed defence layer and shared base-tier heuristic; item upgrade unverified"
                         if category == "BUILD_DEFENSE" else
                         "Shared jewellery base-tier heuristic; build-specific modifier benefit unverified")
    elif category in {"BUILD_WEAPON", "BUILD_OFFHAND"}:
        relevance = (f"{skill} weapon-class mapping and shared base-tier heuristic; skill benefit and modifier upgrade unverified"
                     if skill_mapped else
                     f"Generic fallback for unsupported or unmapped skill {skill}; equipped class may be retained, skill benefit unverified")
    elif build:
        relevance = ("Observed defence layer and shared base-tier heuristic; item upgrade unverified"
                     if category == "BUILD_DEFENSE" else
                     "Shared jewellery base-tier heuristic; build-specific modifier benefit unverified")
    else:
        relevance = "not evaluated by this rule"
    return DecisionEvidence(
        build_relevance=relevance,
        item_potential=("pinned PoB2 base and native level/defence conditions" if rule.base_types else
                        "native class/category conditions only"),
        crafting_potential=("normal-quality or named crafting category heuristic" if craft else "not evaluated"),
        market_opportunity=(market.description if trade else "not evaluated"),
        general_importance=("protected category" if protected else "none"),
        unknowns=("unseen rare modifiers, exact rolls, unique effects and transaction prices" if not hidden else
                  "hidden low-rarity candidate; valuable unknowns protected by prior rules"),
        native_conditions=conditions,
        **({"confidence": intel["coverage"].value, "coverage": intel["coverage"].value,
            "evidence_kinds": intel["kinds"], "details": intel["details"],
            "decisions": tuple(getattr(rule, "decisions", ()) or ()), "market_context": market.description}
           if intel is not None else {}),
    )
