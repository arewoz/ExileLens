"""Independent opportunity benchmark (FILTER-09): which Normal / Magic bases a player would want to see on the ground.

HONEST LABEL: every expectation here is AUTHORED. Nothing is read from generator output or from `crafting_intel`. Three sources:

  AUTHOR DOMAIN JUDGEMENT   hand-picked jewellery / belt bases, judged from the verified implicit text and from how PoE2 players use the base
  STRUCTURAL                armour / weapon / focus / shield bases classified by their verified drop level among class + defence-archetype
                            peers only (top band = a standard crafting / trade base; far below the top with no implicit = obsolete)
  NATURAL GAMEPLAY          a base the user actually saw on the ground in a real PoE2 session and judged worth a label

Expectations are conditional on an item level (82 unless stated). SHOULD_SHOW is a statement about Recommended behaviour at endgame
item levels; stricter profiles may legitimately show less (their policy is measured separately as PROFILE AGGRESSION).
The benchmark has no MARKET lane: no live price is available, so TRADE is NOT MEASURED, never inferred.
"""
from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache

SHOULD_SHOW, MAY_HIDE, SHOULD_HIDE = "SHOULD_SHOW", "MAY_HIDE", "SHOULD_HIDE"


@dataclass(frozen=True)
class OpportunityCase:
    id: str
    base: str
    rarity: str
    item_level: int
    expectation: str
    lane: str          # CRAFT for every case here: BUILD is measured per build, PROTECTED by the safety suites
    source: str
    rationale: str


# -- AUTHOR DOMAIN JUDGEMENT -----------------------------------------------------------------------------------------------------------
_JEWELLERY = (
    # (base, expectation, rationale)
    ("Utility Belt", SHOULD_SHOW, "natural gameplay: instant flask recovery plus charm slots; the user judged it worth a label"),
    ("Fine Belt", SHOULD_SHOW, "top drop level belt; passive flask charge generation is a broadly useful implicit"),
    ("Heavy Belt", SHOULD_SHOW, "stun threshold implicit is useful to almost every build; common crafting base"),
    ("Mail Belt", MAY_HIDE, "reduced flask charges used is useful but modest"),
    ("Plate Belt", MAY_HIDE, "flat armour implicit; only matters for armour builds"),
    ("Double Belt", MAY_HIDE, "charm charges gained: minor"),
    ("Rawhide Belt", SHOULD_HIDE, "level 0 base with a flask-recovery implicit; no reason to stop for the base"),
    ("Linen Belt", SHOULD_HIDE, "level 0 base with a flask-recovery implicit; no reason to stop for the base"),
    ("Vitalic Ring", SHOULD_SHOW, "percentage maximum life implicit"),
    ("Biostatic Ring", SHOULD_SHOW, "+1% to all maximum resistances implicit: top drop level"),
    ("Prismatic Ring", SHOULD_SHOW, "resistance to every element implicit"),
    ("Mnemonic Ring", MAY_HIDE, "percentage maximum mana: strong for some builds, irrelevant for most"),
    ("Penumbra Ring", SHOULD_SHOW, "changes the prefix/suffix budget by two: a crafting tool in itself"),
    ("Tenebrous Ring", SHOULD_SHOW, "changes the prefix/suffix budget by two: a crafting tool in itself"),
    ("Dusk Ring", MAY_HIDE, "one-slot prefix/suffix swap: situational"),
    ("Gloam Ring", MAY_HIDE, "one-slot prefix/suffix swap: situational"),
    ("Sapphire Ring", MAY_HIDE, "single resistance implicit: ordinary"),
    ("Ruby Ring", MAY_HIDE, "single resistance implicit: ordinary"),
    ("Topaz Ring", MAY_HIDE, "single resistance implicit: ordinary"),
    ("Two-Stone Ring", MAY_HIDE, "two resistances: useful, modest"),
    ("Golden Hoop", MAY_HIDE, "all attributes implicit: modest"),
    ("Ring", SHOULD_HIDE, "no implicit, level 0"),
    ("Iron Ring", SHOULD_HIDE, "tiny added physical damage, level 0"),
    ("Abyssal Signet", SHOULD_HIDE, "special mechanic, level 0"),
    ("Solar Amulet", SHOULD_SHOW, "flat Spirit implicit: the scarcest budget in PoE2"),
    ("Pearlescent Amulet", SHOULD_SHOW, "resistance to every element implicit"),
    ("Penumbra Amulet", SHOULD_SHOW, "changes the prefix/suffix budget by two: a crafting tool in itself"),
    ("Tenebrous Amulet", SHOULD_SHOW, "changes the prefix/suffix budget by two: a crafting tool in itself"),
    ("Stellar Amulet", MAY_HIDE, "all attributes implicit: modest"),
    ("Bloodstone Amulet", MAY_HIDE, "flat life implicit at level 18: ordinary"),
    ("Lunar Amulet", MAY_HIDE, "flat energy shield implicit at level 14: ordinary"),
    ("Twisted Amulet", SHOULD_HIDE, "removes a modifier slot"),
    ("Distorted Amulet", SHOULD_HIDE, "removes a modifier slot"),
)


def _author_cases() -> list[OpportunityCase]:
    out = []
    for base, expectation, why in _JEWELLERY:
        for rarity in ("Normal", "Magic"):
            out.append(OpportunityCase(f"AUTH-{base.replace(' ', '_')}-{rarity}", base, rarity, 82, expectation, "CRAFT",
                                       "NATURAL GAMEPLAY" if base == "Utility Belt" else "AUTHOR DOMAIN JUDGEMENT", why))
    return out


# -- STRUCTURAL ------------------------------------------------------------------------------------------------------------------------
_SPECIAL_MECHANIC_PREFIXES = ("Runeforged ", "Runemastered ")     # restated here on purpose: no import from the code under test
_STRUCTURAL_CLASSES = ("Body Armours", "Helmets", "Gloves", "Boots", "Shields", "Foci", "Quivers", "Bows", "Crossbows", "Spears",
                       "Quarterstaves", "Two Hand Maces", "One Hand Maces", "Wands", "Sceptres", "Staves")


def _structural_cases() -> list[OpportunityCase]:
    from exilelens.filters.verified_bases import load_base_properties, native_class
    props = load_base_properties()
    peers: dict[tuple, int] = {}
    arch = lambda r: "".join(k for k, f in (("A", "armour"), ("E", "evasion"), ("S", "energy_shield")) if r.get(f))  # noqa: E731
    for base, rec in props.items():
        key = (rec["class"], arch(rec))
        peers[key] = max(peers.get(key, 0), int(rec["required_level"]))
    out = []
    for base, rec in sorted(props.items()):
        cls = native_class(base)
        if cls not in _STRUCTURAL_CLASSES or base.startswith(_SPECIAL_MECHANIC_PREFIXES):
            continue
        gap = peers[(rec["class"], arch(rec))] - int(rec["required_level"])
        has_implicit = bool(str(rec.get("implicit", "")).strip())
        if gap <= 4:
            expectation, why = SHOULD_SHOW, f"top drop level of its class and defence archetype (gap {gap})"
        elif gap >= 30 and not has_implicit:
            expectation, why = SHOULD_HIDE, f"obsolete: {gap} levels below the top of its peers and no implicit"
        else:
            expectation, why = MAY_HIDE, f"mid drop level (gap {gap}): a base, not an opportunity"
        for rarity in ("Normal", "Magic"):
            out.append(OpportunityCase(f"STRUCT-{base.replace(' ', '_')}-{rarity}", base, rarity, 82, expectation, "CRAFT",
                                       "STRUCTURAL", why))
    return out


@lru_cache(maxsize=1)
def cases() -> tuple[OpportunityCase, ...]:
    return tuple(_author_cases() + _structural_cases())


# -- evaluation (against generated rules; this module never imports the CRAFT lane) -----------------------------------------------------
def evaluate(result_rules, *, ilvl_override: int | None = None) -> dict:
    """Visibility of every case under one generated rule set. Returns counts per expectation and the list of misses / clutter."""
    from exilelens.filters.inspector import make_item
    from exilelens.filters.preview import preview_decision
    rows = {"SHOULD_SHOW": [0, 0], "MAY_HIDE": [0, 0], "SHOULD_HIDE": [0, 0]}      # [visible, total]
    misses, clutter = [], []
    by_source: dict[str, dict[str, list[int]]] = {}
    for case in cases():
        item = make_item(case.base, rarity=case.rarity, item_level=ilvl_override or case.item_level)
        decision = preview_decision(result_rules, item)
        visible = not decision.hidden
        rows[case.expectation][1] += 1
        rows[case.expectation][0] += visible
        src = by_source.setdefault(case.source, {k: [0, 0] for k in rows})
        src[case.expectation][1] += 1
        src[case.expectation][0] += visible
        if case.expectation == SHOULD_SHOW and not visible:
            misses.append({"id": case.id, "base": case.base, "rarity": case.rarity, "rule": decision.rule_name, "why": case.rationale})
        if case.expectation == SHOULD_HIDE and visible:
            clutter.append({"id": case.id, "base": case.base, "rarity": case.rarity, "rule": decision.rule_name, "why": case.rationale})
    show_total = rows["SHOULD_SHOW"][1] or 1
    hide_total = rows["SHOULD_HIDE"][1] or 1
    return {
        "generic_opportunity_miss": round(1 - rows["SHOULD_SHOW"][0] / show_total, 4),
        "craft_recall": round(rows["SHOULD_SHOW"][0] / show_total, 4),
        "clutter_rate": round(rows["SHOULD_HIDE"][0] / hide_total, 4),
        "may_hide_visible_rate": round(rows["MAY_HIDE"][0] / (rows["MAY_HIDE"][1] or 1), 4),
        "counts": {k: {"visible": v[0], "total": v[1]} for k, v in rows.items()},
        "by_source": {s: {k: {"visible": v[0], "total": v[1]} for k, v in d.items()} for s, d in by_source.items()},
        "misses": misses, "clutter": clutter,
    }
