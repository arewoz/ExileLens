"""Independent evidence lanes and the opportunity taxonomy (FILTER-09).

An item is looked at through five lanes that never merge into one score:

  BUILD      measured relevance to the current build (production Build Intelligence through the opportunity model)
  CRAFT      quality as a crafting substrate (verified catalog + affix pools; independent of the build)
  TRADE      general opportunity: heuristic category evidence, or LIVE / CACHED market evidence when a signal is supplied
  PROTECTED  categories that stay visible whatever the build says
  FALLBACK   conservative behaviour when evidence is missing

Every lane verdict carries its reason, evidence source, confidence, the native-observable proxy a rule can test, the profile policy that
applied and its provenance. ``decide`` combines verdicts with an explicit, deterministic precedence and keeps WHICH lane caused visibility.

Precedence (the first that applies is the CAUSE; agreeing lanes are listed as supporting):
  1. PROTECTED                                              -> shows
  2. BUILD tier rules (FILTER-08 machinery, first in the generated filter) -> shows, build style
  3. CRAFT lane: CRAFT_PREMIUM / CRAFT_RELEVANT inside the profile's gate and rarities -> shows, craft style
  4. TRADE_PREMIUM (needs LIVE / CACHED market evidence); TRADE_POTENTIAL (heuristic) never shows an item by itself
  5. CONSERVATIVE_VISIBLE / UNKNOWN keep the pre-existing behaviour: never newly hidden, never newly widened
  6. the profile's generic rows (matrix states for Normal / Magic / Rare equipment) apply to what no lane claims
A broad Hide can no longer shadow a lane because the lane rules sit above it. Several lanes agreeing raise `emphasis_bonus` by one: it is
reference information for explanations; the generated style does not change and visibility never depends on it.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from exilelens.filters import crafting_intel as ci
from exilelens.filters.preview import PreviewItem


class Lane(str, Enum):
    BUILD = "BUILD"
    CRAFT = "CRAFT"
    TRADE = "TRADE"
    PROTECTED = "PROTECTED"
    FALLBACK = "FALLBACK"


class Opportunity(str, Enum):
    BUILD_STRONG = "BUILD_STRONG"
    BUILD_RELEVANT = "BUILD_RELEVANT"
    BUILD_LOW = "BUILD_LOW"
    CRAFT_PREMIUM = "CRAFT_PREMIUM"
    CRAFT_RELEVANT = "CRAFT_RELEVANT"
    CRAFT_LOW = "CRAFT_LOW"
    TRADE_PREMIUM = "TRADE_PREMIUM"
    TRADE_POTENTIAL = "TRADE_POTENTIAL"
    TRADE_LOW = "TRADE_LOW"
    GENERAL_PROTECTED = "GENERAL_PROTECTED"
    CONSERVATIVE_VISIBLE = "CONSERVATIVE_VISIBLE"
    LOW_VALUE = "LOW_VALUE"
    UNKNOWN = "UNKNOWN"


class Precision(str, Enum):
    PREMIUM = "PREMIUM"            # a strong independent reason to inspect
    STRONG = "STRONG"              # a meaningful opportunity
    CONDITIONAL = "CONDITIONAL"    # useful for a specific archetype or crafting goal
    CONSERVATIVE = "CONSERVATIVE"  # shown because hiding is unsafe
    LOW = "LOW"                    # no compelling evidence
    UNKNOWN = "UNKNOWN"


PRECISION = {
    Opportunity.CRAFT_PREMIUM: Precision.PREMIUM, Opportunity.TRADE_PREMIUM: Precision.PREMIUM, Opportunity.GENERAL_PROTECTED: Precision.PREMIUM,
    Opportunity.BUILD_STRONG: Precision.STRONG,
    Opportunity.BUILD_RELEVANT: Precision.CONDITIONAL, Opportunity.CRAFT_RELEVANT: Precision.CONDITIONAL,
    Opportunity.TRADE_POTENTIAL: Precision.CONDITIONAL,
    Opportunity.CONSERVATIVE_VISIBLE: Precision.CONSERVATIVE,
    Opportunity.BUILD_LOW: Precision.LOW, Opportunity.CRAFT_LOW: Precision.LOW, Opportunity.TRADE_LOW: Precision.LOW,
    Opportunity.LOW_VALUE: Precision.LOW, Opportunity.UNKNOWN: Precision.UNKNOWN,
}


@dataclass(frozen=True)
class LaneVerdict:
    lane: Lane
    level: Opportunity
    reason: str
    source: str                        # where the evidence comes from
    confidence: str                    # VERIFIED | MEASURED | HEURISTIC | PARTIAL | NONE
    proxy: tuple[str, ...] = ()        # native conditions a rule can test for this verdict
    policy: str = ""                   # the profile policy applied
    provenance: tuple[str, ...] = ()

    @property
    def precision(self) -> Precision:
        return PRECISION[self.level]


@dataclass(frozen=True)
class Decision:
    visible: bool
    cause: Lane | None
    why: str
    verdicts: tuple[LaneVerdict, ...]
    supporting: tuple[Lane, ...] = ()
    emphasis_bonus: int = 0
    gate: int | None = None

    def verdict(self, lane: Lane) -> LaneVerdict | None:
        return next((v for v in self.verdicts if v.lane == lane), None)


# -- lanes -------------------------------------------------------------------------------------------------------------------------------
def craft_lane(base: str, profile: str, item_level: int, rarity: str) -> LaneVerdict:
    a = ci.assess(base)
    note = ci.policy_note(profile)
    proxy = a.native_proxy()
    source = "pinned PoB2 catalog + affix pools"
    if a.level == ci.CraftLevel.UNKNOWN:
        return LaneVerdict(Lane.CRAFT, Opportunity.UNKNOWN, "; ".join(a.reasons), source, "NONE", proxy, note, a.reasons)
    level = {ci.CraftLevel.PREMIUM: Opportunity.CRAFT_PREMIUM, ci.CraftLevel.RELEVANT: Opportunity.CRAFT_RELEVANT,
             ci.CraftLevel.LOW: Opportunity.CRAFT_LOW}[a.level]
    reason = "; ".join(a.reasons[:3]) or "no craft evidence"
    if a.breakpoints:
        reason += f"; item-level breakpoints {a.breakpoints['meaningful']} / {a.breakpoints['high']} / {a.breakpoints['premium']}"
    return LaneVerdict(Lane.CRAFT, level, reason, source, a.confidence, proxy, note, a.reasons)


def trade_lane(base: str, market=None) -> LaneVerdict:
    """TRADE_PREMIUM needs LIVE or CACHED market evidence. Without it the best a base can be is a heuristic TRADE_POTENTIAL."""
    if market is not None and getattr(market, "level", "UNKNOWN") in ("LIVE", "CACHED"):
        return LaneVerdict(Lane.TRADE, Opportunity.TRADE_PREMIUM, f"market signal {market.level} from {market.source}", market.source,
                           market.level, ("BaseType", "ItemLevel"), "market evidence supplied at generation time",
                           (getattr(market, "observed_at", ""),))
    from exilelens.filters.opportunity import global_quality_tier
    from exilelens.filters.profiles import BaseTier
    from exilelens.filters.verified_bases import native_class
    cls = native_class(base)
    if not cls:
        return LaneVerdict(Lane.TRADE, Opportunity.UNKNOWN, "base not in the verified catalog", "none", "NONE")
    tier, source = global_quality_tier(base, cls)
    if tier in (BaseTier.T1, BaseTier.T2):
        return LaneVerdict(Lane.TRADE, Opportunity.TRADE_POTENTIAL,
                           f"top verified drop-level band ({tier.value}); heuristic only, no live price used", source, "HEURISTIC",
                           ("Class", "BaseType", "ItemLevel", "Rarity"), "heuristic category/base rule", (source,))
    return LaneVerdict(Lane.TRADE, Opportunity.TRADE_LOW, "no top-band evidence", source, "HEURISTIC", (), "", (source,))


def build_lane(model, base: str, native: str) -> LaneVerdict:
    """BUILD verdict from the opportunity model (None model, a class without a role or no measurement = UNKNOWN)."""
    from exilelens.filters.build_needs import Relevance
    from exilelens.filters.opportunity import ROLE_BY_CLASS
    if model is None or not model.needs.has_measurement or native not in ROLE_BY_CLASS:
        return LaneVerdict(Lane.BUILD, Opportunity.UNKNOWN, "no Build Intelligence measurement for this base", "none", "NONE")
    decision = model.decide(base, native)
    specific = [h for h in decision.hits if not h.universal]
    best = max((h.relevance.rank for h in specific), default=-1)
    if decision.shift > 0 or best >= Relevance.STRONG.rank:
        level, reason = Opportunity.BUILD_STRONG, "base can roll a stat family the build responds to strongly"
    elif specific and best >= Relevance.RESPONSIVE.rank:
        level, reason = Opportunity.BUILD_RELEVANT, "base can roll a stat family the build responds to"
    else:
        level, reason = Opportunity.BUILD_LOW, "no base-specific measured stat family supports it"
    return LaneVerdict(Lane.BUILD, level, reason, "production Build Intelligence",
                       "MEASURED" if model.needs.evidence_complete else "PARTIAL", ("Class", "BaseType", "ItemLevel"),
                       "build tier rules", tuple(h.family for h in specific[:4]))


PROTECTED_CLASSES = frozenset({"Stackable Currency", "Omen", "Pinnacle Keys", "Map Fragments", "Augment", "Tablet", "Quest Items", "Waystones"})


def protected_lane(item: PreviewItem) -> LaneVerdict | None:
    if item.rarity == "Unique":
        return LaneVerdict(Lane.PROTECTED, Opportunity.GENERAL_PROTECTED, "unique rarity is protected", "protective rules", "VERIFIED",
                           ("Rarity",), "protected category")
    if item.item_class in PROTECTED_CLASSES:
        return LaneVerdict(Lane.PROTECTED, Opportunity.GENERAL_PROTECTED, f"{item.item_class} is a protected class", "protective rules",
                           "VERIFIED", ("Class",), "protected category")
    if item.item_class in ("Jewels", "Charms", "Flasks"):
        return LaneVerdict(Lane.PROTECTED, Opportunity.CONSERVATIVE_VISIBLE,
                           f"{item.item_class}: the pinned data cannot rank bases within this class, and no rule hides it", "pinned catalog",
                           "PARTIAL", ("Class",), "conservative protection")
    return None


# -- combination -------------------------------------------------------------------------------------------------------------------------
def decide(item: PreviewItem, profile: str, *, model=None, market=None, build_shown: bool = False, widen: bool = False) -> Decision:
    """Deterministic, explainable lane attribution for one item under one profile.

    ``visible`` means "a lane shows it". It is deliberately not "the filter shows it": the profile's generic rules (a Hide, or the game
    default for an unlabelled item) decide everything no lane claims, and Rare items are never hidden by them. Scope: items without
    quality (quality-gated crafting rules belong to the older CRAFTING_BASES layer).

    BUILD visibility is owned by the FILTER-08 tier machinery (build tier x profile tiers x item-level gate, per resolved slot class),
    which this function does not re-derive: pass ``build_shown=True`` when a BUILD rule shows the item (the inspector does, from the
    generated rules). The BUILD verdict is still reported as a reason lane either way. ``widen`` mirrors data drift (one policy step wider).
    """
    from exilelens.filters.verified_bases import native_class
    base = item.base_type or item.name
    native = native_class(base) or item.item_class
    effective = profile                                 # one craft policy at every level: widening changes the breakpoint, not the level
    verdicts: list[LaneVerdict] = []
    protected = protected_lane(item)
    if protected is not None:
        verdicts.append(protected)
    if native_class(base):
        verdicts.append(build_lane(model, base, native))
        verdicts.append(craft_lane(base, effective, item.item_level, item.rarity))
        verdicts.append(trade_lane(base, market))
    if model is None or not model.needs.evidence_complete:
        verdicts.append(LaneVerdict(Lane.FALLBACK, Opportunity.CONSERVATIVE_VISIBLE, "Build Intelligence missing or incomplete: build evidence "
                                    "never hides a base", "evidence completeness", "PARTIAL", (), "widen, never narrow"))
    by_lane = {v.lane: v for v in verdicts}
    if protected is not None and protected.level == Opportunity.GENERAL_PROTECTED:
        return Decision(True, Lane.PROTECTED, protected.reason, tuple(verdicts))

    craft, build, trade = by_lane.get(Lane.CRAFT), by_lane.get(Lane.BUILD), by_lane.get(Lane.TRADE)
    gate = None
    craft_shows = False
    craft_state = None
    if craft is not None and craft.level in (Opportunity.CRAFT_PREMIUM, Opportunity.CRAFT_RELEVANT):
        assessment = ci.assess(base)
        gate = ci.breakpoint_gate(assessment, widened=widen)
        campaign = item.area_level <= 64
        craft_state = ci.craft_state(assessment, item.rarity, item.item_level, effective, widened=widen, campaign=campaign)
        craft_shows = craft_state is not None and craft_state != "HIDE" and not item.corrupted and not item.mirrored
    trade_shows = trade is not None and trade.level == Opportunity.TRADE_PREMIUM

    # precedence: BUILD tier rules (they come first in the generated filter) > CRAFT lane > TRADE (market evidence only)
    if build_shown:
        cause, why = Lane.BUILD, f"{build.level.value if build else 'BUILD'}: a BUILD tier rule shows it"
    elif craft_shows:
        cause, why = Lane.CRAFT, f"{craft.level.value}: {craft.reason}"
    elif trade_shows:
        cause, why = Lane.TRADE, f"TRADE_PREMIUM: {trade.reason}"
    else:
        cause, why = None, ""
    if cause is not None:
        agreeing = {Lane.BUILD: build_shown, Lane.CRAFT: craft_shows, Lane.TRADE: trade_shows}
        support = tuple(lane for lane in (Lane.BUILD, Lane.CRAFT, Lane.TRADE) if lane != cause and agreeing[lane])
        return Decision(True, cause, why, tuple(verdicts), support, 1 if support else 0, gate)
    if protected is not None:      # jewels, charms, flasks: no generated rule hides them
        return Decision(True, Lane.PROTECTED, protected.reason, tuple(verdicts))
    if item.rarity not in ("Normal", "Magic"):
        return Decision(False, None, f"no lane changes a {item.rarity} item: the profile shows it by default", tuple(verdicts))
    if craft is not None and craft.level == Opportunity.UNKNOWN:
        return Decision(False, None, "craft value unknown (special-mechanic or no pool data): the profile's generic rules apply, nothing is "
                        "widened", tuple(verdicts))
    if craft is not None and craft.level in (Opportunity.CRAFT_PREMIUM, Opportunity.CRAFT_RELEVANT):
        if gate is None:
            why = f"{craft.level.value}, but the pinned data has no item-level breakpoint for it ({ci.policy_note(effective)})"
        elif craft_state is None:
            why = f"{craft.level.value} counts from item level {gate}; this {item.rarity} i{item.item_level} item is below it"
        else:
            why = f"{craft.level.value}: the {effective} profile gives this {item.rarity} i{item.item_level} item the state {craft_state}"
        return Decision(False, None, why, tuple(verdicts), gate=gate)
    return Decision(False, None, "no lane shows it: low craft, build and trade evidence; the profile's generic rules apply",
                    tuple(verdicts), gate=gate)
