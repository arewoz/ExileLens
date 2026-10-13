"""Curated loot-importance ladder for currency (FILTER visual system V3).

This is a hand-maintained, explicit table of exact item names. It is NOT a price list and NOT live: it says how much visual attention a
currency name deserves in a dense drop cluster, and it only ever changes styling (every currency was already shown by the protective
`Currency` rule; the tiers sit above it as Show rules). Names come from two kinds of evidence, recorded per name:

  GGG_NOTICE        exact names from GGG's published item-filter notice (also pinned in `verified_bases.PINNED_SPECIAL_BASES`)
  OBSERVED          a name the user's own in-game capture shows (FILTER-08A capture or the FILTER visual V3 gameplay screenshot)
  COMMUNITY_FILTER  an exact `BaseType ==` name in the most widely used live PoE2 community filter (0.10.4, 2026-09-04), used only where the game's own
                    structure (not a price) justifies the tier; a wrong exact name can only fail to match, and the item then still falls
                    through to the protective `Currency` rule (styling-only, never a visibility change)

No other name is invented: to extend a tier, add the exact in-game name with its evidence.
"""
from __future__ import annotations

from dataclasses import dataclass

GGG_NOTICE = "GGG_NOTICE"
OBSERVED = "OBSERVED"
COMMUNITY_FILTER = "COMMUNITY_FILTER"


@dataclass(frozen=True)
class Tier:
    key: str                # CURRENCY_HERO | CURRENCY_PREMIUM | CURRENCY_ENHANCED | CURRENCY_CRAFT | CURRENCY_VALUABLE | CURRENCY_UTILITY | CURRENCY_LOW
    category: str           # GeneratedRule category
    rule_name: str
    role: str               # style role
    priority: int
    names: tuple[str, ...]
    evidence: str
    name_evidence: tuple[tuple[str, str], ...] = ()     # per-name override of `evidence`
    row: str = ""           # profile-matrix row that decides this tier's state at every strictness level

    def evidence_of(self, name: str) -> str:
        return dict(self.name_evidence).get(name, self.evidence)


_UTILITY_COMMUNITY = ("Orb of Transmutation", "Orb of Augmentation", "Blacksmith's Whetstone", "Arcanist's Etcher", "Gnawed Collarbone",
                      "Gnawed Jawbone", "Gnawed Rib", "Preserved Jawbone", "Vaal Siphoner")
# "Alchemy Shard" was in the community filter text but is "Not in game" (PoE2DB acquisition); the native registry marks it STALE_OBSOLETE.
_LOW_COMMUNITY = ("Artificer's Shard", "Transmutation Shard", "Scroll of Wisdom")

TIERS: tuple[Tier, ...] = (
    # MYTHIC (white / red, 45 pt, persistent pillar, sound 6 @ 300). Mirror of Kalandra: the game's rarest currency by design (V4).
    Tier("CURRENCY_HERO", "TRADE_HERO", "Exceptional currency", "hero", 2, ("Hinekora's Lock", "Mirror of Kalandra"), GGG_NOTICE,
         (("Mirror of Kalandra", COMMUNITY_FILTER),), row="currency_mythic"),
    # Divine-tier: above every other currency on the screen. Not a price claim; one name today, extend with evidence.
    Tier("CURRENCY_PREMIUM", "CURRENCY_TOP", "Premium currency (top)", "currency_premium", 6, ("Divine Orb",), OBSERVED, row="currency_premium"),
    Tier("CURRENCY_ENHANCED", "CURRENCY_PREMIUM", "Enhanced currency", "premium_currency", 7,
         ("Greater Chaos Orb", "Perfect Chaos Orb", "Greater Exalted Orb", "Perfect Exalted Orb", "Greater Regal Orb", "Perfect Regal Orb"),
         GGG_NOTICE, row="currency_enhanced"),
    Tier("CURRENCY_CRAFT", "CURRENCY_CRAFT", "Crafting currency", "crafting_currency", 8,
         ("Greater Orb of Transmutation", "Perfect Orb of Transmutation", "Greater Orb of Augmentation", "Perfect Orb of Augmentation"),
         GGG_NOTICE, row="currency_craft"),
    Tier("CURRENCY_VALUABLE", "CURRENCY_VALUABLE", "Valuable currency", "currency_valuable", 9,
         ("Exalted Orb", "Chaos Orb", "Gemcutter's Prism", "Regal Orb", "Vaal Orb"), OBSERVED, row="currency_valuable"),
    # Utility currency: only names WITH evidence. Anything else of class Stackable Currency is unclassified and falls to the explicit
    # unknown-item catch-all (visible), never to a guess. Observed = the user's own captures; community = exact names in the pinned PoE2
    # community filter text (tiers d / e / "supply").
    Tier("CURRENCY_UTILITY", "CURRENCY_UTILITY", "Utility currency", "currency", 10,
         ("Orb of Alchemy", "Artificer's Orb", "Lesser Jeweller's Orb", *_UTILITY_COMMUNITY), OBSERVED,
         tuple((name, COMMUNITY_FILTER) for name in _UTILITY_COMMUNITY), row="currency_utility"),
    Tier("CURRENCY_LOW", "CURRENCY_LOW", "Minor currency", "currency_low", 11,
         ("Regal Shard", "Armourer's Scrap", *_LOW_COMMUNITY), OBSERVED, tuple((name, COMMUNITY_FILTER) for name in _LOW_COMMUNITY),
         row="currency_shards_low"),
)

OBSERVED_ONLY = tuple(name for tier in TIERS for name in tier.names if tier.evidence_of(name) == OBSERVED)
COMMUNITY_ONLY = tuple(name for tier in TIERS for name in tier.names if tier.evidence_of(name) == COMMUNITY_FILTER)
ALL_NAMES = tuple(name for tier in TIERS for name in tier.names)


def tier_of(name: str) -> str:
    for tier in TIERS:
        if name in tier.names:
            return tier.key
    return "CURRENCY_UNCLASSIFIED"
