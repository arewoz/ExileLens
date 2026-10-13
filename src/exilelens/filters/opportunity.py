"""Item / base opportunity model for build-aware filter generation (FILTER-08B).

Three dimensions are kept apart on purpose and never collapsed into one score:

* BASE QUALITY        build-independent: verified drop-level band of the base inside its class (curated
                      labels only as a fallback where no verified level exists).
* BUILD RELEVANCE     how the measured build needs (``BuildNeedsSnapshot``) meet what this base can
                      provide: affix-pool eligibility, verified implicits, intrinsic defence.
* CRAFTING POTENTIAL  build-independent: how deep a base's best modifier tiers go and at which item level.

A theoretically strong base for one build therefore never becomes a globally high-tier base: the global
(quality) tier is identical for every build; only the BUILD tier moves, by at most one step, and only on
positive evidence. Demotion requires measured NO_RESPONSE with HIGH/MEDIUM confidence; absence of evidence
never demotes (weak build support widens the filter, it does not narrow it).

Every decision carries ``Reason`` rows whose ``EvidenceKind`` says WHY it exists, so a fallback is never
presented as measured personalisation.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from enum import Enum
from functools import cached_property, lru_cache
from typing import Iterable, Mapping

from exilelens.filters import affix_pools as pools
from exilelens.filters.build_needs import BuildNeedsSnapshot, Coverage, Relevance
from exilelens.filters.priorities import (BASE_TIERS, SLOT_EQUIPMENT_CLASSES, DEFAULT_WEAPON_CLASSES, EXTENDED_OFFHAND_CLASSES,
                                           EXTENDED_WEAPON_CLASSES, SKILL_WEAPON_CLASSES)
from exilelens.filters.profiles import BaseTier, ProductSlot
from exilelens.filters.verified_bases import FILTER_TO_POB_CLASS, load_base_properties, native_class

_TIERS = (BaseTier.T1, BaseTier.T2, BaseTier.T3, BaseTier.T4)
# Drop-level bands relative to the highest verified required level of the class (and, for armour and
# shields, of the defence archetype). Only the TOP two bands are derived: lower tiers stay curated so a
# profile's clutter control is not undone by promoting every mid-level base.
_LEVEL_BANDS = ((4, BaseTier.T1), (14, BaseTier.T2))

ROLE_BY_CLASS = {
    "Wands": "weapon", "Sceptres": "weapon", "Staves": "weapon", "Quarterstaves": "weapon",
    "One Hand Maces": "weapon", "Two Hand Maces": "weapon", "Bows": "weapon", "Crossbows": "weapon",
    "Spears": "weapon", "Shields": "offhand", "Foci": "offhand", "Quivers": "offhand",
    **{name: "weapon" for name in EXTENDED_WEAPON_CLASSES},
    **{name: "offhand" for name in EXTENDED_OFFHAND_CLASSES},
    "Body Armours": "armour", "Helmets": "armour", "Gloves": "armour", "Boots": "armour",
    "Rings": "jewellery", "Amulets": "jewellery", "Belts": "jewellery",
}
# Which kinds of tested intervention can make a base of this role relevant.
ROLE_CATEGORIES = {
    "weapon": frozenset({"offense"}),
    "offhand": frozenset({"offense", "defense"}),
    "armour": frozenset({"defense", "resistance", "utility"}),
    "jewellery": frozenset({"offense", "defense", "resistance", "utility"}),
}
_LAYER_PROBE = {"armour": "ARMOUR", "evasion": "EVASION", "energy_shield": "ENERGY_SHIELD"}
_SPELL_WEAPON_FAMILIES = frozenset({"SPELL_SKILL_LEVELS", "CAST_SPEED", "SPELL_DAMAGE", "CRIT_CHANCE_SPELL", "CRIT_MULTIPLIER_SPELL"})
_RELIABLE = frozenset({"HIGH", "MEDIUM"})
_MAINTENANCE_PROBES = frozenset({"FIRE_RES", "COLD_RES", "LIGHTNING_RES", "CHAOS_RES", "STRENGTH", "DEXTERITY", "INTELLIGENCE"})


class EvidenceKind(str, Enum):
    MEASURED_BUILD_RESPONSE = "measured build response"
    VERIFIED_BASE_FACT = "verified base/item fact"
    AFFIX_POOL_OPPORTUNITY = "affix-pool opportunity"
    CRAFTING_OPPORTUNITY = "crafting opportunity"
    MARKET_HEURISTIC = "market heuristic"
    GENERIC_PROTECTION = "generic protection"
    CONSERVATIVE_FALLBACK = "conservative fallback"
    UNSUPPORTED = "unsupported / uncertain"


@dataclass(frozen=True)
class Reason:
    kind: EvidenceKind
    text: str


@dataclass(frozen=True)
class FamilyHit:
    family: str
    probe_id: str
    relevance: Relevance
    source: str                   # POOL | IMPLICIT | INTRINSIC
    first_level: int | None = None
    top_level: int | None = None
    universal: bool = False       # every base of the class can roll it: carries no base-specific information
    basis: str = ""               # the measurement behind the relevance class


@dataclass(frozen=True)
class CraftingPotential:
    level: str                    # HIGH | MEDIUM | LOW
    unlock_item_level: int | None
    basis: str


@dataclass(frozen=True)
class BaseDecision:
    base: str
    filter_class: str
    role: str
    quality_tier: BaseTier
    quality_source: str
    build_tier: BaseTier
    relevance: Relevance | None   # None = no evidence either way
    shift: int
    hits: tuple[FamilyHit, ...]
    reasons: tuple[Reason, ...]
    crafting: CraftingPotential
    coverage: Coverage
    global_tier: BaseTier = BaseTier.IGNORE   # build-independent quality, identical for every build
    gate_tier: BaseTier = BaseTier.IGNORE     # tier whose profile item-level gate applies (never stricter than legacy)
    unlock_level: int | None = None           # item level where the top tier of a strongly responded stat unlocks

    @property
    def personalised(self) -> bool:
        """True only when measured/verified build evidence changed THIS base's build tier or candidacy."""
        return self.coverage in (Coverage.MEASURED, Coverage.PARTIAL) and self.shift != 0


_CURATED_ALIASES = {"Swords": ["One Hand Swords", "Two Hand Swords"], "Axes": ["One Hand Axes", "Two Hand Axes"]}


def _expand_curated(classes):
    """The curated skill map names whole families ('Swords', 'Axes'); expand them to the native classes."""
    if not classes:
        return classes
    out = []
    for name in classes:
        out.extend(_CURATED_ALIASES.get(name, [name]))
    return out


# -- base quality ---------------------------------------------------------------------------------
def _tier_index(tier: BaseTier) -> int:
    return _TIERS.index(tier)


def shift_tier(tier: BaseTier, delta: int) -> BaseTier:
    if tier not in _TIERS or delta == 0:
        return tier
    # delta > 0 promotes (towards T1); delta < 0 demotes (towards T4). Never leaves T1..T4.
    return _TIERS[max(0, min(len(_TIERS) - 1, _tier_index(tier) - delta))]


def _archetype(record: Mapping) -> str:
    return "".join(tag for tag, key in (("A", "armour"), ("E", "evasion"), ("S", "energy_shield")) if record.get(key))


@lru_cache(maxsize=None)
def _peer_max_required_level(pob_class: str, archetype: str) -> int:
    levels = [r["required_level"] for r in load_base_properties().values()
              if r["class"] == pob_class and _archetype(r) == archetype]
    return max(levels) if levels else 0


def _disputed(base: str, curated: BaseTier) -> bool:
    """A curated T1/T2 label on a base more than 30 levels below the top of its peers (e.g. a level-0 ring labelled T1)."""
    record = load_base_properties().get(base)
    if not record or curated not in (BaseTier.T1, BaseTier.T2):
        return False
    return _peer_max_required_level(record["class"], _archetype(record)) - int(record["required_level"]) > 30


def level_band(base: str) -> BaseTier | None:
    """T1/T2 from the verified drop-level band among peers (same class and defence archetype).

    None when the base has no verified level or is not in a top band; lower tiers are never derived."""
    record = load_base_properties().get(base)
    if not record:
        return None
    gap = _peer_max_required_level(record["class"], _archetype(record)) - int(record["required_level"])
    for limit, tier in _LEVEL_BANDS:
        if gap <= limit:
            return tier
    return None


def global_quality_tier(base: str, filter_class: str, equipped: Iterable[str] = ()) -> tuple[BaseTier, str]:
    """Build-independent base quality: the better of the curated label and the verified top level band.

    Identical for every build; used by generic trade and crafting rules."""
    curated = BASE_TIERS.get(filter_class, {}).get(base)
    derived = level_band(base)
    if curated == BaseTier.IGNORE:
        return BaseTier.IGNORE, "curated exclusion"
    if derived is not None and (curated is None or _tier_index(derived) <= _tier_index(curated)):
        tier, source = derived, "verified drop-level band"
    elif curated is not None:
        tier, source = curated, "curated fallback"
        if _disputed(base, curated):
            # Verified drop level contradicts the curated label. Visibility is retained (no accepted justification exists to
            # reduce it) but the provenance says so; it never outranks a verified band.
            source = "curated fallback (contradicted by verified drop level)"
    else:
        return BaseTier.IGNORE, "outside verified top level bands"
    if base in set(equipped) and _tier_index(tier) > _tier_index(BaseTier.T2):
        return BaseTier.T2, "equipped base (observed gear)"
    return tier, source


def crafting_potential(base: str, tier: BaseTier) -> CraftingPotential:
    """How deep the base's best tiers go; independent of any build."""
    top_levels = [pool.top_level for pool in pools.pools_for(base).values()]
    unlock = max(top_levels) if top_levels else None
    level = {BaseTier.T1: "HIGH", BaseTier.T2: "MEDIUM"}.get(tier, "LOW")
    return CraftingPotential(level, unlock, "verified drop-level band and pinned affix-tier levels")


@lru_cache(maxsize=None)
def _shared_layers(pob_class: str) -> frozenset[str]:
    """Intrinsic defence layers every base of the class has (e.g. all foci): no base-specific information."""
    records = [r for r in load_base_properties().values() if r["class"] == pob_class]
    return frozenset(key for key in _LAYER_PROBE if records and all(r.get(key) for r in records))


# -- build-aware model -----------------------------------------------------------------------------
class BuildOpportunityModel:
    """Evaluates verified bases against one ``BuildNeedsSnapshot``. Pure and offline."""

    def __init__(self, needs: BuildNeedsSnapshot, *, widen: bool = False):
        self.needs = needs
        self.widen = widen   # data drift: no demotion, no narrowing, verified bands everywhere
        # Degraded knowledge: a measurement exists but is not complete. Measured evidence may then promote but never narrow.
        self.incomplete = needs.has_measurement and not needs.evidence_complete
        self.equipped_bases = tuple(base for base in needs.equipped.values() if base)
        # FILTER-08E: why the model fell back, by code (see degradation.py). Recording only; it never changes a decision.
        self.diagnostics: dict[str, set[str]] = defaultdict(set)
        if not self.equipped_bases:
            self.diagnostics["NO_OBSERVED_GEAR"]

    def check_integrity(self) -> dict[str, set[str]]:
        """Data-integrity diagnostics, evaluated through the same lookups the model uses (so a failing lookup is seen here too)."""
        from exilelens.filters.verified_bases import load_verified_bases
        props = load_base_properties()
        missing = [base for base in load_verified_bases() if base not in props]
        if missing:
            self.diagnostics["BASE_METADATA_MISSING"].update(missing)
        unmapped = [base for base in props if native_class(base) in ROLE_BY_CLASS and not pools.pools_for(base)]
        if unmapped:
            self.diagnostics["FAMILY_MAPPING_MISSING"].update(unmapped)
        return self.diagnostics

    @cached_property
    def weapon_basis_evidenced(self) -> bool:
        """True when the build's weapon classes come from verified/measured evidence (not a curated or broad fallback)."""
        supported = list(SLOT_EQUIPMENT_CLASSES[ProductSlot.WEAPON_1]) + list(EXTENDED_WEAPON_CLASSES)
        return self.weapon_classes(supported)[2] in (Coverage.MEASURED, Coverage.PARTIAL)

    @property
    def bow_context(self) -> bool:
        skill = self.needs.skill
        if skill.weapon_classes and "Bows" in skill.weapon_classes:
            return True
        props = load_base_properties()
        return any(props.get(base, {}).get("class") == "Bow" for base in self.equipped_bases)

    # ---- applicability of a pool family to THIS build -------------------------------------------
    def applicable(self, family: str) -> bool:
        definition = pools.family_definitions()[family]
        if definition["relation"] == "DIRECT":
            return True
        skill = self.needs.skill
        if "@" in family:
            return skill.mode == "SPELL" and family.split("@", 1)[1] in skill.elements
        if family.endswith("_SPELL"):
            return skill.mode == "SPELL"
        if family.endswith("_ATTACK"):
            return skill.mode == "ATTACK"
        return False

    def _hit(self, family: str, source: str, pool: pools.FamilyPool | None, universal: bool,
             role: str) -> FamilyHit | None:
        probe = pools.family_probe(family)
        signal = self.needs.signal(probe)
        if signal is None or signal.category not in ROLE_CATEGORIES[role] or not self.applicable(family):
            return None
        if probe in _MAINTENANCE_PROBES and signal.relevance_class != Relevance.FIX_FIRST:
            # Resistances and attributes are maintenance stats: they identify a need only when a hard deficit exists.
            return None
        return FamilyHit(family, probe, signal.relevance_class, source,
                         pool.first_level if pool else None, pool.top_level if pool else None,
                         universal, signal.basis())

    def hits(self, base: str, role: str) -> tuple[FamilyHit, ...]:
        record = load_base_properties().get(base)
        if not record:
            return ()
        if record["class"] == "Quiver" and not self.bow_context:
            # A quiver serves bow users; without a verified/equipped bow no build evidence applies to it.
            return ()
        universal = pools.universal_families(record["class"])
        found: list[FamilyHit] = []
        for family, pool in pools.pools_for(base).items():
            hit = self._hit(family, "POOL", pool, family in universal, role)
            if hit:
                found.append(hit)
        for family in pools.implicit_families(base):
            hit = self._hit(family, "IMPLICIT", None, False, role)
            if hit:
                found.append(hit)
        if role in ("armour", "offhand"):
            shared = _shared_layers(record["class"])
            for key, probe in _LAYER_PROBE.items():
                if record.get(key):
                    signal = self.needs.signal(probe)
                    if signal is not None:
                        found.append(FamilyHit(probe, probe, signal.relevance_class, "INTRINSIC", None, None,
                                               key in shared, signal.basis()))
        return tuple(found)

    # ---- the decision table -----------------------------------------------------------------------
    def _shift(self, hits: tuple[FamilyHit, ...]) -> tuple[int, Relevance | None, list[FamilyHit]]:
        """+1 promote / 0 keep / -1 demote from BASE-SPECIFIC hits only (universal pool families carry no
        per-base information). Returns the evidence that justified a non-zero shift."""
        specific = [h for h in hits if not h.universal]
        if not specific:
            return 0, None, []
        if self.widen or self.incomplete:
            best = max(specific, key=lambda h: h.relevance.rank)
            if best.relevance.rank >= Relevance.STRONG.rank:
                return 1, best.relevance, [h for h in specific if h.relevance.rank >= Relevance.STRONG.rank]
            return 0, best.relevance, []
        best = max(specific, key=lambda h: h.relevance.rank)
        if best.relevance.rank >= Relevance.STRONG.rank:
            return 1, best.relevance, [h for h in specific if h.relevance.rank >= Relevance.STRONG.rank]
        if all(h.relevance == Relevance.NO_RESPONSE for h in specific):
            confident = all((self.needs.signal(h.probe_id).confidence in _RELIABLE) for h in specific
                            if self.needs.signal(h.probe_id))
            # Offense metric confidence LOW never demotes: weak support must widen, not narrow.
            offense_weak = self.needs.offense_limited_confidence and any(
                (self.needs.signal(h.probe_id).category == "offense") for h in specific if self.needs.signal(h.probe_id))
            if confident and not offense_weak:
                return -1, Relevance.NO_RESPONSE, specific
        return 0, best.relevance, []

    def decide(self, base: str, filter_class: str) -> BaseDecision:
        role = ROLE_BY_CLASS[filter_class]
        global_tier, global_source = global_quality_tier(base, filter_class, self.equipped_bases)
        hits = self.hits(base, role)
        quality, source = self._build_input_quality(base, filter_class, role, hits, global_tier, global_source)
        delta, relevance, cause = self._shift(hits)
        build_tier = shift_tier(quality, delta) if quality != BaseTier.IGNORE else quality
        reasons = [Reason(EvidenceKind.VERIFIED_BASE_FACT if source.startswith(("verified", "equipped")) else
                          EvidenceKind.CONSERVATIVE_FALLBACK,
                          f"Base quality {quality.value}: {source}")]
        if delta and cause:
            top = cause[0]
            kind = EvidenceKind.MEASURED_BUILD_RESPONSE
            verb = "promoted" if delta > 0 else "demoted"
            where = {"POOL": "affix pool", "IMPLICIT": "base implicit", "INTRINSIC": "intrinsic defence"}[top.source]
            reasons.append(Reason(kind, f"{verb} one step: {where} ({top.family.replace('_', ' ').title()}) — {top.basis}"))
            if top.source == "POOL":
                reasons.append(Reason(EvidenceKind.AFFIX_POOL_OPPORTUNITY,
                                      f"Base can roll {top.family.replace('_', ' ').lower()} from item level {top.first_level}"
                                      f" (top tier {top.top_level}); unidentified rolls are not observable"))
            elif top.source == "IMPLICIT":
                reasons.append(Reason(EvidenceKind.VERIFIED_BASE_FACT, "Base implicit grants this stat (always present)"))
        elif hits and relevance is not None:
            reasons.append(Reason(EvidenceKind.AFFIX_POOL_OPPORTUNITY,
                                  f"Class-level opportunity only ({relevance.value.lower()}); no base-specific advantage"))
        else:
            reasons.append(Reason(EvidenceKind.CONSERVATIVE_FALLBACK, "No base-specific build evidence; base quality tier kept"))
        coverage = self._coverage(delta, hits)
        curated = BASE_TIERS.get(filter_class, {}).get(base)
        gate_tier = quality
        if curated not in (None, BaseTier.IGNORE) and quality != BaseTier.IGNORE and                 _tier_index(curated) > _tier_index(quality):
            # The profile gate rises with tier (T1 82 > T2 75): a derived upgrade must never raise the gate the curated
            # label already had, or items the legacy filter showed would disappear.
            gate_tier = curated
        return BaseDecision(base, filter_class, role, quality, source, build_tier, relevance, delta, hits,
                            tuple(reasons), crafting_potential(base, global_tier), coverage, global_tier, gate_tier,
                            self._unlock_level(role, hits))

    def _unlock_level(self, role: str, hits: tuple[FamilyHit, ...]) -> int | None:
        """Lowest item level at which this base can roll the TOP tier of a stat the build responds to strongly.

        Weapons/offhands count class-wide offense families (the verified class is the evidence); armour and jewellery
        need base-specific hits. A pool opportunity only: unidentified modifiers stay unobservable."""
        levels = []
        for hit in hits:
            if hit.source != "POOL" or not hit.top_level or hit.relevance.rank < Relevance.STRONG.rank:
                continue
            signal = self.needs.signal(hit.probe_id)
            category = signal.category if signal else ""
            if (role in ("weapon", "offhand") and category == "offense") or not hit.universal:
                levels.append(hit.top_level)
        return min(levels) if levels else None

    def _build_input_quality(self, base: str, filter_class: str, role: str, hits: tuple[FamilyHit, ...],
                             global_tier: BaseTier, global_source: str) -> tuple[BaseTier, str]:
        """The verified top-band upgrade reaches BUILD rules only with evidence that this base is useful to the
        build (or when there is no measurement at all: weak support widens). Otherwise the curated label stands."""
        curated = BASE_TIERS.get(filter_class, {}).get(base)
        derived = level_band(base)
        if derived is None or global_source != "verified drop-level band":
            return global_tier, global_source
        if self.widen or self.incomplete:
            return global_tier, global_source + (" (data drift: widened)" if self.widen else " (incomplete evidence: widened)")
        if not self.needs.has_measurement:
            return global_tier, global_source + " (no build measurement: widened)"
        if not pools.pools_for(base):
            # Every real base has modifier pools. None here means the itemization data is missing for it, which is not evidence that
            # the base is useless to the build: the verified band stands (a lost input widens, it never hides).
            self.diagnostics["FAMILY_MAPPING_MISSING"].add(base)
            return global_tier, global_source + " (itemization data unavailable for this base: widened)"
        if role in ("weapon", "offhand") and not self.weapon_basis_evidenced:
            # The build's weapon classes rest on a fallback (e.g. a minion skill): nothing says a class is irrelevant, so the
            # verified top bands apply to every candidate class, exactly as for an unmeasured build.
            return global_tier, global_source + " (weapon classes unevidenced: widened)"
        def counts(hit: FamilyHit) -> bool:
            # Armour and jewellery need STRONG evidence: a merely responsive stat (e.g. a movement-speed implicit that
            # every build responds to) must not lift a whole class of top bases.
            floor = Relevance.RESPONSIVE if role in ("weapon", "offhand") else Relevance.STRONG
            if hit.relevance.rank < floor.rank:
                return False
            if role == "weapon":
                return True
            category = self.needs.signal(hit.probe_id).category if self.needs.signal(hit.probe_id) else ""
            # Universal pool families describe the whole class, not this base: only offense-scaling ones identify a
            # caster/attacker offhand (focus); defence and jewellery evidence must be base-specific.
            return (role == "offhand" and category == "offense") or not hit.universal
        if any(counts(h) for h in hits):
            return global_tier, global_source
        if curated is not None and curated != BaseTier.IGNORE:
            return curated, "curated fallback (top level band not evidenced for this build)"
        return BaseTier.IGNORE, "top level band not evidenced for this build"

    def _coverage(self, delta: int, hits: tuple[FamilyHit, ...]) -> Coverage:
        if not self.needs.has_measurement:
            return Coverage.FALLBACK
        if delta != 0:
            return Coverage.MEASURED if not self.needs.offense_limited_confidence else Coverage.PARTIAL
        return Coverage.PARTIAL if any(not h.universal for h in hits) else Coverage.FALLBACK

    # ---- candidate classes ------------------------------------------------------------------------
    def weapon_classes(self, supported: Iterable[str]) -> tuple[list[str], list[Reason], Coverage]:
        """Which weapon classes the build can use, by evidence precedence. See module docstring."""
        supported = list(supported)
        skill = self.needs.skill
        reasons: list[Reason] = []
        equipped = self._equipped_classes(supported)
        if self.widen:
            reasons.append(Reason(EvidenceKind.CONSERVATIVE_FALLBACK, "Data drift: weapon classes widened to every supported class"))
            return list(dict.fromkeys([*DEFAULT_WEAPON_CLASSES, *EXTENDED_WEAPON_CLASSES, *equipped])), reasons, Coverage.FALLBACK
        verified = skill.weapon_classes
        if not verified and skill.mode == "ATTACK":
            self.diagnostics["WEAPON_REQUIREMENT_UNKNOWN"].add(skill.name or "unknown skill")
        if skill.mode == "UNKNOWN" and skill.name:
            meta = bool({"Meta", "Triggers"} & set(skill.types))
            self.diagnostics["SKILL_UNRESOLVED"].add(skill.name + (" (trigger/meta: triggered skills not resolved)" if meta else ""))
        if verified:
            usable = [cls for cls in verified if cls in supported]
            if usable:
                reasons.append(Reason(EvidenceKind.VERIFIED_BASE_FACT,
                                      f"PoB2 requires {', '.join(usable)} for {skill.name}"))
                return list(dict.fromkeys([*usable, *equipped])), reasons, (
                    Coverage.MEASURED if self.needs.has_measurement else Coverage.PARTIAL)
            reasons.append(Reason(EvidenceKind.UNSUPPORTED,
                                  f"{skill.name} requires {', '.join(verified)}: not covered by supported weapon classes"))
            return list(dict.fromkeys([*DEFAULT_WEAPON_CLASSES, *EXTENDED_WEAPON_CLASSES, *equipped])), reasons, Coverage.UNSUPPORTED
        # Observed gear unknown: the guarantee that the class the player wields stays visible cannot be given, so evidence-derived and
        # curated class lists (both narrower than the generic fallback) are skipped and the generic fallback applies. A verified weapon
        # requirement, handled above, is independent of gear and still applies.
        gear_known = bool(self.equipped_bases)
        measured = self.needs.has_measurement and gear_known
        if skill.mode in ("SPELL", "MINION") and measured:
            # Complete evidence: a class counts when the build measurably responds to spell stats. Incomplete evidence: the verified
            # fact that a class CAN roll them is kept, but with no claim about this build, so the result only ever adds to the curated map.
            spell_relevant = self.incomplete or any(self.needs.relevance(pools.family_probe(f)).rank >= Relevance.RESPONSIVE.rank
                                                    for f in _SPELL_WEAPON_FAMILIES if skill.mode == "SPELL")
            derived = ([cls for cls in supported if ROLE_BY_CLASS.get(cls) == "weapon" and
                        self._class_rolls(cls, _SPELL_WEAPON_FAMILIES)] if skill.mode == "SPELL" and spell_relevant else [])
            # No weapon class rolling spell stats cannot be true of the real game: it means the modifier data is missing, so the
            # derivation is not evidence. Fall through to the curated / generic (widening) branches instead of narrowing.
            if not derived and skill.mode == "SPELL" and spell_relevant:
                self.diagnostics["FAMILY_MAPPING_MISSING"].add("weapon classes (no class rolls spell stats)")
            curated = [c for c in _expand_curated(SKILL_WEAPON_CLASSES.get(skill.name)) or [] if c in supported]
            # Incomplete evidence only ever ADDS the verified classes to a curated map; with no curated map the generic fallback (every
            # class) is already wider than any derivation, so it applies.
            if derived and (curated or not self.incomplete):
                classes = list(dict.fromkeys([*derived, *curated, *equipped]))
                reasons.append(Reason(EvidenceKind.MEASURED_BUILD_RESPONSE if not self.incomplete else EvidenceKind.VERIFIED_BASE_FACT,
                                      f"{skill.name} is a spell (PoB2) and responds to spell-scaling stats; weapon classes that can "
                                      f"roll them: {', '.join(derived) or 'none'}" if not self.incomplete else
                                      f"{skill.name} is a spell (PoB2); weapon classes that can roll spell-scaling stats: "
                                      f"{', '.join(derived) or 'none'} (evidence incomplete: no build-specific claim)"))
                if curated:
                    reasons.append(Reason(EvidenceKind.CONSERVATIVE_FALLBACK,
                                          f"Curated skill map keeps {', '.join(c for c in curated if c not in derived) or 'no extra class'}"))
                return classes, reasons, Coverage.MEASURED if not self.incomplete else Coverage.PARTIAL
        curated = _expand_curated(SKILL_WEAPON_CLASSES.get(skill.name))
        if gear_known and curated and curated != ["Any"]:
            classes = [c for c in curated if c in supported]
            reasons.append(Reason(EvidenceKind.CONSERVATIVE_FALLBACK,
                                  f"Curated skill→weapon map for {skill.name}; benefit not verified"))
            return list(dict.fromkeys([*classes, *equipped])), reasons, Coverage.FALLBACK
        reasons.append(Reason(EvidenceKind.CONSERVATIVE_FALLBACK,
                              f"Generic fallback for unsupported or unmapped skill {skill.name or 'unknown'}"))
        return list(dict.fromkeys([*DEFAULT_WEAPON_CLASSES, *EXTENDED_WEAPON_CLASSES, *equipped])), reasons, (
            Coverage.UNSUPPORTED if not skill.name else Coverage.FALLBACK)

    def _equipped_classes(self, supported: list[str]) -> list[str]:
        classes = []
        for base in self.equipped_bases:
            native = native_class(base)
            if native in supported and ROLE_BY_CLASS.get(native) == "weapon":
                classes.append(native)
        return classes

    @staticmethod
    def _class_rolls(filter_class: str, families: frozenset[str]) -> bool:
        pob_class = FILTER_TO_POB_CLASS[filter_class]
        return bool(pools.class_families(pob_class) & families)

    def offhand_classes(self, supported: Iterable[str]) -> tuple[list[str], list[Reason]]:
        supported = list(supported)
        skill = self.needs.skill
        reasons: list[Reason] = []
        classes = list(supported)
        if skill.weapon_classes and "Bows" in skill.weapon_classes and "Quivers" in supported and \
                all(c in ("Bows", "Crossbows") for c in skill.weapon_classes):
            reasons.append(Reason(EvidenceKind.VERIFIED_BASE_FACT, f"PoB2 requires a bow for {skill.name}: quivers apply"))
        elif "Quivers" in classes and skill.weapon_classes and "Bows" not in skill.weapon_classes:
            classes.remove("Quivers")
            reasons.append(Reason(EvidenceKind.VERIFIED_BASE_FACT,
                                  f"{skill.name} does not use a bow, so quivers are not applicable"))
        return classes, reasons

    # ---- slot resolution ----------------------------------------------------------------------------
    def resolve_classes(self, filter_classes: Iterable[str]) -> dict[str, BaseDecision]:
        decisions: dict[str, BaseDecision] = {}
        wanted = {name for name in filter_classes if name in ROLE_BY_CLASS and name in FILTER_TO_POB_CLASS}
        for base in load_base_properties():
            native = native_class(base)
            if native in wanted:
                decisions[base] = self.decide(base, native)
        return decisions
