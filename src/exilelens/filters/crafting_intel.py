"""Crafting Base Intelligence (FILTER-09): how good a base is as a crafting substrate, independent of the current build.

Everything is derived from the version-pinned PoB2 data (catalog: implicit, required level, intrinsic defence, weapon base stats, quality
capability; affix pools: modifier families and their tier levels). The result is an explicit class with reasons, never a numeric score:

  PREMIUM   a strong independent reason to inspect the base as a substrate
  RELEVANT  a meaningful substrate for a generic crafting goal
  LOW       no compelling evidence
  UNKNOWN   the data cannot say (special mechanics, no pool data) — callers must stay conservative

Item-level breakpoints come from the base's own affix pool: the item level at which 60 % / 85 % / 95 % of its families' tiers are
unlocked (meaningful / high / premium). Nothing here knows about the build, the profile or the market.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from functools import lru_cache

from exilelens.filters import affix_pools as pools
from exilelens.filters.verified_bases import load_base_properties, native_class

CATALOG_FILE = None  # populated lazily from coverage_audit (single reader of the pinned item catalog)


class CraftLevel(str, Enum):
    PREMIUM = "PREMIUM"
    RELEVANT = "RELEVANT"
    LOW = "LOW"
    UNKNOWN = "UNKNOWN"

    @property
    def rank(self) -> int:
        return {"PREMIUM": 3, "RELEVANT": 2, "LOW": 1, "UNKNOWN": 0}[self.value]


# -- implicit classification (explicit, reviewable policy over verified implicit text) ---------------------------------------------------
# value: PREMIUM_IMPLICIT (broadly desirable on any build), RELEVANT_IMPLICIT (generic utility / defence), SPECIFIC (one archetype),
#        FLEX (changes how many prefixes/suffixes can roll: a crafting tool), NICHE (situational or restrictive), BASELINE (shared by the class)
IMPLICIT_RULES: tuple[tuple[str, str, str], ...] = (
    (r"[+]\d[^\n]* Prefix Modifiers? allowed|[+]\d[^\n]* Suffix Modifiers? allowed", "FLEX", "changes the prefix/suffix budget (crafting flexibility)"),
    (r"-\d+ Prefix Modifiers? allowed|-\d+ Suffix Modifiers? allowed", "NICHE", "removes modifier slots (restrictive)"),
    (r"all Maximum (Elemental )?Resistances", "PREMIUM_IMPLICIT", "raises maximum resistances"),
    (r"all Elemental Resistances", "PREMIUM_IMPLICIT", "resistance to every element"),
    (r"increased maximum (Life|Mana)", "PREMIUM_IMPLICIT", "percentage maximum life / mana"),
    (r"Cold and Lightning Resistances|Fire and Cold Resistances|Fire and Lightning Resistances", "RELEVANT_IMPLICIT", "two resistances"),
    (r"to all Attributes", "RELEVANT_IMPLICIT", "all attributes"),
    (r"to Spirit", "PREMIUM_IMPLICIT", "spirit (the contested PoE2 budget; a flat implicit is rare)"),
    (r"to maximum (Life|Energy Shield|Mana)", "RELEVANT_IMPLICIT", "flat life / energy shield / mana"),
    (r"to (Strength|Dexterity|Intelligence)\b", "RELEVANT_IMPLICIT", "attribute"),
    (r"% to (Fire|Cold|Lightning|Chaos) Resistance", "RELEVANT_IMPLICIT", "single resistance"),
    (r"Movement Speed", "RELEVANT_IMPLICIT", "movement speed"),
    (r"Stun Threshold|Ailment Threshold", "RELEVANT_IMPLICIT", "threshold"),
    (r"Regenerat|Regeneration", "RELEVANT_IMPLICIT", "regeneration"),
    (r"Flask Recovery|Recovery from Flasks|Flask Charges|Flasks gain|Charm Charges|Charm Effect|Charges used", "RELEVANT_IMPLICIT", "flask / charm utility"),
    (r"to Armour|to Evasion|increased Armour|increased Evasion|Energy Shield Recharge", "RELEVANT_IMPLICIT", "defence"),
    (r"Has \(?\d[^\n]*Charm Slot", "BASELINE", "charm slots (every belt has them)"),
    (r"Rarity of Items found|Maximum Quality|Grants Skill|as though it was|Skill Slot|Abyssal Wasting", "NICHE", "situational identity"),
    (r"Damage|Cast Speed|Attack Speed|Critical|Accuracy|Projectile|Minions?|Area of Effect|Chain|Pierce|Bolt|Sockets", "SPECIFIC", "one archetype"),
)
_COMPILED = tuple((re.compile(pattern, re.I), kind, why) for pattern, kind, why in IMPLICIT_RULES)

_GROUP = (  # modifier family -> archetype breadth group
    (re.compile(r"^(SPELL|CAST)"), "spell"), (re.compile(r"^(ATTACK|PROJECTILE)"), "attack"), (re.compile(r"^MINION"), "minion"),
    (re.compile(r"^LIFE$"), "life"), (re.compile(r"^ENERGY_SHIELD$"), "energy_shield"), (re.compile(r"^(ARMOUR|EVASION)$"), "physical_defence"),
    (re.compile(r"_RES$"), "resistance"), (re.compile(r"^(STRENGTH|DEXTERITY|INTELLIGENCE)$"), "attribute"),
    (re.compile(r"^(MANA|MOVEMENT_SPEED)$"), "utility"), (re.compile(r"^(POISON|IGNITE)"), "ailment"), (re.compile(r"^CRIT"), "crit"),
)
SPECIAL_PREFIXES = ("Runeforged ", "Runemastered ")


@dataclass(frozen=True)
class ImplicitFacts:
    kinds: tuple[str, ...]
    value: str                       # PREMIUM_IMPLICIT | RELEVANT_IMPLICIT | FLEX | SPECIFIC | NICHE | BASELINE | NONE
    reasons: tuple[str, ...]


@dataclass(frozen=True)
class CraftAssessment:
    base: str
    native_class: str
    level: CraftLevel
    reasons: tuple[str, ...]
    band: str | None                 # verified drop-level band T1 / T2
    implicit: ImplicitFacts
    intrinsic: str                   # HIGH | NORMAL | N/A
    breadth: int                     # archetype groups the pool serves
    groups: tuple[str, ...]
    breakpoints: dict[str, int]      # meaningful / high / premium item level from the base's own pool ({} without pool data)
    quality_capable: bool
    confidence: str                  # VERIFIED (pool + catalog) | PARTIAL (catalog only) | NONE
    required_level: int = 0

    def native_proxy(self) -> tuple[str, ...]:
        return ("Class", "BaseType", "ItemLevel", "Rarity")


def classify_implicit(text: str) -> ImplicitFacts:
    kinds: list[str] = []
    reasons: list[str] = []
    for line in (ln.strip() for ln in text.replace("\\n", "\n").split("\n") if ln.strip()):
        for pattern, kind, why in _COMPILED:
            if pattern.search(line):
                kinds.append(kind)
                reasons.append(f"{why}: {line[:70]}")
                break
    order = ("FLEX", "PREMIUM_IMPLICIT", "RELEVANT_IMPLICIT", "SPECIFIC", "NICHE", "BASELINE")
    value = next((k for k in order if k in kinds), "NONE")
    return ImplicitFacts(tuple(kinds), value, tuple(reasons))


@lru_cache(maxsize=1)
def _catalog() -> dict:
    from exilelens.filters import coverage_audit
    return coverage_audit.catalog()


def _archetype(record) -> str:
    return "".join(k for k, f in (("A", "armour"), ("E", "evasion"), ("S", "energy_shield")) if record.get(f))


@lru_cache(maxsize=None)
def _intrinsic_cutoffs() -> dict[tuple[str, str], float]:
    """Per (class, archetype) the 85th percentile of intrinsic strength among eligible peers (None-free; verified numbers only)."""
    groups: dict[tuple[str, str], list[float]] = {}
    for base, rec in load_base_properties().items():
        if base.startswith(SPECIAL_PREFIXES):
            continue
        value = _intrinsic_value(base, rec)
        if value is not None:
            groups.setdefault((rec["class"], _archetype(rec)), []).append(value)
    cutoffs = {}
    for key, values in groups.items():
        values.sort()
        cutoffs[key] = values[min(len(values) - 1, int(len(values) * 0.85))] if len(values) >= 6 else float("inf")
    return cutoffs


def _intrinsic_value(base: str, rec) -> float | None:
    defence = rec["armour"] + rec["evasion"] + rec["energy_shield"]
    if defence:
        return float(defence)
    weapon = _catalog().get(base, {}).get("weapon") or {}
    if weapon.get("AttackRateBase"):
        mean = lambda a, b: (weapon.get(a, 0) + weapon.get(b, 0)) / 2
        damage = mean("PhysicalMin", "PhysicalMax") + mean("FireMin", "FireMax") + mean("ColdMin", "ColdMax") \
            + mean("LightningMin", "LightningMax") + mean("ChaosMin", "ChaosMax")
        return damage * weapon["AttackRateBase"]
    return None


def breakpoints(base: str) -> dict[str, int]:
    ps = pools.pools_for(base)
    if not ps:
        return {}
    # Bases with the same eligible tier levels share the same thresholds.
    # Return a fresh mapping because CraftAssessment exposes it to callers.
    return dict(_breakpoint_levels(tuple(p.levels for p in ps.values())))


@lru_cache(maxsize=512)
def _breakpoint_levels(levels: tuple[tuple[int, ...], ...]) -> tuple[tuple[str, int], ...]:
    from bisect import bisect_right

    def reached(level: int, target: float) -> bool:
        # Keep the original summation order and weighting of each stat family.
        return sum(bisect_right(tiers, level) / len(tiers) for tiers in levels) / len(levels) >= target

    out: dict[str, int] = {}
    for name, target in (("meaningful", .60), ("high", .85), ("premium", .95)):
        if not reached(100, target):
            continue
        low, high = 1, 100
        while low < high:
            middle = (low + high) // 2
            if reached(middle, target):
                high = middle
            else:
                low = middle + 1
        out[name] = low
    return tuple(out.items())


def archetype_groups(base: str) -> tuple[str, ...]:
    found = set()
    for family in pools.pools_for(base):
        for pattern, group in _GROUP:
            if pattern.search(family):
                found.add(group)
                break
    return tuple(sorted(found))


@lru_cache(maxsize=None)
def assess(base: str) -> CraftAssessment:
    from exilelens.filters.opportunity import ROLE_BY_CLASS, level_band
    props = load_base_properties()
    record = props.get(base)
    cls = native_class(base) or ""
    if record is None or not cls:
        return CraftAssessment(base, cls, CraftLevel.UNKNOWN, ("base is not in the verified catalog",), None,
                               ImplicitFacts((), "NONE", ()), "N/A", 0, (), {}, False, "NONE")
    catalog = _catalog().get(base, {})
    implicit = classify_implicit(record.get("implicit", ""))
    band = level_band(base)
    band_name = band.value if band is not None else None
    groups = archetype_groups(base)
    bps = breakpoints(base)
    quality_capable = bool(catalog.get("quality", 0))
    value = _intrinsic_value(base, record)
    cutoff = _intrinsic_cutoffs().get((record["class"], _archetype(record)), float("inf"))
    intrinsic = "N/A" if value is None else "HIGH" if value >= cutoff else "NORMAL"
    confidence = "VERIFIED" if bps else "PARTIAL"
    reasons: list[str] = []
    if band_name:
        reasons.append(f"verified drop-level band {band_name} among {record['class']} peers (required level {record['required_level']})")
    reasons.extend(implicit.reasons[:2])
    if intrinsic == "HIGH":
        reasons.append("intrinsic strength in the top 15 % of its peers")
    if groups:
        reasons.append(f"pool serves {len(groups)} archetype groups ({', '.join(groups)})")

    if base.startswith(SPECIAL_PREFIXES):
        level = CraftLevel.UNKNOWN
        reasons = ["special-mechanic base: crafting value not evaluated (shown only by the generic rules)"]
    elif not bps and implicit.value == "NONE" and not band_name:
        level = CraftLevel.UNKNOWN
        reasons = ["no pool data and no classifiable implicit"]
    else:
        generic = implicit.value in ("PREMIUM_IMPLICIT", "RELEVANT_IMPLICIT")
        # Jewellery carries no base defence, so its drop-level band says little: affix tiers depend on the ITEM level, not the base's.
        # A generally desirable implicit is therefore enough on a ring / amulet / belt; for other classes it also needs a top band.
        jewellery = record["class"] in ("Ring", "Amulet", "Belt")
        if (band_name == "T1" and (generic or intrinsic == "HIGH")) or                 (implicit.value == "PREMIUM_IMPLICIT" and (band_name in ("T1", "T2") or jewellery)):
            level = CraftLevel.PREMIUM
        elif (band_name in ("T1", "T2") and (generic or intrinsic == "HIGH")) or implicit.value in ("PREMIUM_IMPLICIT", "FLEX") \
                or (band_name == "T1" and intrinsic == "N/A" and record["class"] in ("Staff", "Wand", "Sceptre", "Focus")):
            level = CraftLevel.RELEVANT
        elif band_name == "T1" and cls in ROLE_BY_CLASS and not any("removes modifier slots" in r for r in implicit.reasons):
            # The top drop-level band of an equipment class is the end of its base progression (highest base stats, highest item-level
            # requirement). Without a generic implicit or a top intrinsic it is a RELEVANT substrate, not a PREMIUM one.
            level = CraftLevel.RELEVANT
            reasons.append("top drop-level band of its class: end of the base progression")
        else:
            level = CraftLevel.LOW
            if not reasons:
                reasons.append("no top band, no generic implicit, no intrinsic strength")
    return CraftAssessment(base, cls, level, tuple(reasons), band_name, implicit, intrinsic, len(groups), groups, bps, quality_capable,
                           confidence, int(record["required_level"]))


# Item-level gate ladder (rounded DOWN so a rule never starts later than the base's own breakpoint).
LADDER = (1, 40, 50, 55, 60, 65, 70, 75, 80, 82)


def quantise_down(level: int) -> int:
    return max(rung for rung in LADDER if rung <= max(1, level))


# -- CRAFT ladder (profile system V2) ---------------------------------------------------------------------------------------------------
# One policy for every strictness level: WHERE a substrate starts to count (its item-level breakpoint) never moves; what a level does with it is
# the matrix row (profile_policy). PREMIUM counts from the "meaningful" breakpoint (60 % of its affix tiers unlocked), RELEVANT from "high" (85 %).
CRAFT_BREAKPOINT = {"PREMIUM": "meaningful", "RELEVANT": "high"}
WIDENED_BREAKPOINT = {"PREMIUM": "meaningful", "RELEVANT": "meaningful"}   # data drift: pinned breakpoints may be stale, so only ever show more
PREMIUM_ILVL = 82                                                          # the matrix splits CRAFT_PREMIUM Normal / Magic at this item level


def breakpoint_gate(assessment: CraftAssessment, *, widened: bool = False) -> int | None:
    """Item level from which this base counts as a craft substrate (None: LOW / UNKNOWN bases, or no breakpoint data)."""
    if assessment.level not in (CraftLevel.PREMIUM, CraftLevel.RELEVANT) or not assessment.breakpoints:
        return None
    point = (WIDENED_BREAKPOINT if widened else CRAFT_BREAKPOINT)[assessment.level.value]
    level = assessment.breakpoints.get(point)
    if level is None:
        return None
    return max(quantise_down(level), max(1, assessment.required_level))


def craft_row(assessment: CraftAssessment, rarity: str, item_level: int, *, widened: bool = False) -> str | None:
    """The matrix row an item of this base / rarity / item level belongs to in the CRAFT lane (None: not a CRAFT lane member)."""
    if rarity not in ("Normal", "Magic", "Rare"):
        return None
    if assessment.level == CraftLevel.LOW:
        return "craft_low" if rarity in ("Normal", "Magic") else None
    if assessment.level == CraftLevel.UNKNOWN:
        return "craft_unknown" if rarity in ("Normal", "Magic") else None
    gate = breakpoint_gate(assessment, widened=widened)
    if gate is None or item_level < gate:
        return None
    if rarity == "Rare":
        return "craft_any_rare"
    if assessment.level == CraftLevel.RELEVANT:
        return "craft_relevant_normal" if rarity == "Normal" else "craft_relevant_magic"
    if item_level < PREMIUM_ILVL:
        return "craft_premium_below_ilvl82"
    return "craft_premium_normal_ilvl82" if rarity == "Normal" else "craft_premium_magic_ilvl82"


def craft_state(assessment: CraftAssessment, rarity: str, item_level: int, profile: str, *, widened: bool = False,
                campaign: bool = False) -> str | None:
    """The state the matrix gives this item through the CRAFT lane at ``profile`` (None when the lane does not claim it)."""
    from exilelens.filters import profile_policy as pp
    row = craft_row(assessment, rarity, item_level, widened=widened)
    if row is None:
        return None
    return pp.campaign_state(row) if campaign else pp.state(row, profile)


def gate_for(assessment: CraftAssessment, profile: str, *, widened: bool = False) -> tuple[int, tuple[str, ...]] | None:
    """(item-level gate, rarities) from which this base is VISIBLE (any state but HIDE) through the CRAFT lane at ``profile``, or None."""
    from exilelens.filters import profile_policy as pp
    gate = breakpoint_gate(assessment, widened=widened)
    if gate is None:
        return None
    probes = {"Normal": (max(gate, PREMIUM_ILVL), "Normal"), "Magic": (max(gate, PREMIUM_ILVL), "Magic")}
    rarities = []
    for rarity, (level, _name) in probes.items():
        row = craft_row(assessment, rarity, level, widened=widened)
        if row is not None and pp.state(row, profile) != "HIDE":
            rarities.append(rarity)
    if assessment.level == CraftLevel.PREMIUM and assessment.breakpoints and gate < PREMIUM_ILVL:
        below = craft_row(assessment, "Normal", gate, widened=widened)
        if below and pp.state(below, profile) != "HIDE" and "Normal" not in rarities:
            rarities.append("Normal")
    return (gate, tuple(rarities)) if rarities else None


def policy_note(profile: str) -> str:
    """One sentence for explanations: what the matrix does with CRAFT substrates at this level."""
    from exilelens.filters import profile_policy as pp
    parts = [f"{label} {pp.state(row, profile)}" for label, row in (
        ("PREMIUM Normal >= 82", "craft_premium_normal_ilvl82"), ("PREMIUM Magic >= 82", "craft_premium_magic_ilvl82"),
        ("RELEVANT Normal", "craft_relevant_normal"), ("RELEVANT Magic", "craft_relevant_magic"))]
    return f"{profile}: " + ", ".join(parts)
