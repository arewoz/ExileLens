"""FILTER-08B false-negative corpus: independently annotated, build-scoped expectations.

Expectations are authored from loot/crafting reasoning about the ITEM and what the build measurably needs
(tags such as ``mode:SPELL`` or ``fix:CHAOS_RES`` come from the stored measurement), never from the generator's
rules or its output. Each case says which builds it applies to; bases are chosen by a verified-data rule
(e.g. "highest required level wand"), not by looking at a decision.

Outcome classes for a hidden item:
  CONFIRMED ERROR       a protected item or an item whose independent annotation is "protect"
  POTENTIAL MISS        an annotated opportunity/trade/build-opportunity item
  ACCEPTABLE HIDE       annotated clutter
  UNKNOWN               annotated uncertain: evidence is insufficient either way
"""
from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from typing import Mapping, Sequence

from exilelens.filters.benchmark08b import PROFILES, build_tags, decision_summary, evaluate, item_summary
from exilelens.filters.benchmark_corpus import LOOT_CASES
from exilelens.filters.build_needs import BuildNeedsSnapshot, Relevance
from exilelens.filters.intel_generate import defence_layer_of, generate
from exilelens.filters.preview import PreviewItem
from exilelens.filters.verified_bases import FILTER_TO_POB_CLASS, load_base_properties, native_class

AGGRESSIVE = ("Very Strict", "Endgame")
_NATIVE = {pob: native for native, pob in FILTER_TO_POB_CLASS.items()}


@dataclass(frozen=True)
class FnCase:
    id: str
    item: PreviewItem
    expectation: str          # protect | opportunity | trade | clutter | uncertain
    rationale: str
    scope: tuple[str, ...]    # build tags that must ALL be present; () = every build
    area: str                 # which risk this case challenges


def extended_tags(needs: BuildNeedsSnapshot) -> frozenset[str]:
    tags = set(build_tags(needs))
    tags.add(f"layer:{defence_layer_of(needs).value}")
    for signal in needs.signals:
        if signal.relevance == Relevance.FIX_FIRST.value:
            tags.add(f"fix:{signal.probe_id}")
        if signal.relevance in (Relevance.STRONG.value, Relevance.FIX_FIRST.value):
            tags.add(f"strong:{signal.probe_id}")
    return frozenset(tags)


@lru_cache(maxsize=None)
def top_base(pob_class: str, archetype: str | None = None, rank: int = 0) -> str:
    """Highest-required-level base of a class (optionally of one intrinsic-defence archetype), by verified data."""
    def arch(record: Mapping) -> str:
        return "".join(tag for tag, key in (("A", "armour"), ("E", "evasion"), ("S", "energy_shield")) if record.get(key))
    rows = sorted(((int(r["required_level"]), name) for name, r in load_base_properties().items()
                   if r["class"] == pob_class and not name.startswith(("Runeforged ", "Runemastered "))
                   and (archetype is None or arch(r) == archetype)), key=lambda row: (-row[0], row[1]))
    return rows[rank][1]


def _item(base: str, rarity: str, level: int, *, quality: int = 0, tier: int = 0) -> PreviewItem:
    record = load_base_properties()[base]
    return PreviewItem(f"{base} ({rarity} i{level}{f' q{quality}' if quality else ''}{f' u{tier}' if tier else ''})",
                       "FILTER-08B false-negative probe", native_class(base), base, rarity, item_level=level,
                       quality=quality, unidentified_item_tier=tier, base_energy_shield=record["energy_shield"],
                       base_armour=record["armour"], base_evasion=record["evasion"])


def _case(case_id: str, base: str, rarity: str, level: int, expectation: str, rationale: str, *,
          scope: tuple[str, ...] = (), area: str, quality: int = 0, tier: int = 0) -> FnCase:
    return FnCase(case_id, _item(base, rarity, level, quality=quality, tier=tier), expectation, rationale, scope, area)


def fn_cases() -> tuple[FnCase, ...]:
    wand, staff = top_base("Wand"), top_base("Staff")
    focus = top_base("Focus", "S")
    bow, quiver = top_base("Bow"), top_base("Quiver")
    mace2, mace1 = top_base("Two Hand Mace"), top_base("One Hand Mace")
    robe_es, plate_ar, coat_ev = top_base("Body Armour", "S"), top_base("Body Armour", "A"), top_base("Body Armour", "E")
    hybrid_ar_es, hybrid_ev_es = top_base("Body Armour", "AS"), top_base("Body Armour", "ES")
    ring, amulet = top_base("Ring"), top_base("Amulet")
    spell, bows, maces = ("mode:SPELL",), ("weapon:Bows",), ("weapon:One Hand Maces",)
    return (
        # --- high-response build opportunities: top bases that can roll the top tier of a measured stat ---------------
        _case("spell-wand-top-magic-82", wand, "Magic", 82, "opportunity",
              "Top-level wand base for a spell build: a magic item has open modifier slots on the base that can roll the top spell-level tier.",
              scope=spell, area="high-response build opportunity"),
        _case("spell-staff-top-magic-82", staff, "Magic", 82, "opportunity",
              "Top-level staff base for a spell build: same reasoning as the wand.", scope=spell, area="high-response build opportunity"),
        _case("spell-staff-top-normal-q20", staff, "Normal", 82, "opportunity",
              "Normal quality-20 top staff is a crafting base for a spell build.", scope=spell, quality=20, area="valuable crafting base"),
        _case("spell-focus-top-magic-82", focus, "Magic", 82, "opportunity",
              "Top-level ES focus for a spell build: offhand that can roll spell skill levels and cast speed.",
              scope=spell, area="offhand opportunity"),
        _case("bow-top-magic-82", bow, "Magic", 82, "opportunity",
              "Top-level bow for a bow attack skill: magic base that can roll the top projectile/attack tiers.",
              scope=bows, area="high-response build opportunity"),
        _case("bow-top-normal-q20", bow, "Normal", 82, "opportunity",
              "Normal quality-20 top bow is a crafting base for a bow build.", scope=bows, quality=20, area="valuable crafting base"),
        _case("bow-quiver-top-magic-82", quiver, "Magic", 82, "opportunity",
              "Top-level quiver for a bow attack skill (offhand opportunity).", scope=bows, area="offhand opportunity"),
        _case("mace-top-two-hand-magic-82", mace2, "Magic", 82, "opportunity",
              "Top-level two-hand mace for a mace attack skill: magic base that can roll attack-scaling tiers.",
              scope=maces, area="high-response build opportunity"),
        _case("mace-top-one-hand-magic-82", mace1, "Magic", 82, "opportunity",
              "Top-level one-hand mace for a mace attack skill.", scope=maces, area="high-response build opportunity"),
        # --- fix-first needs with a verified base fact -----------------------------------------------------------------------
        _case("fixfirst-chaos-ring-amethyst", "Amethyst Ring", "Magic", 70, "opportunity",
              "The Amethyst Ring implicit grants chaos resistance (verified); a chaos-resistance cap deficit is a hard need.",
              scope=("fix:CHAOS_RES",), area="fix-first implicit"),
        _case("fixfirst-chaos-body-devout", "Devout Garb", "Magic", 82, "opportunity",
              "Devout Garb carries a chaos-resistance implicit (verified) for a build below the chaos cap.",
              scope=("fix:CHAOS_RES",), area="fix-first implicit"),
        # --- hybrid / archetype crafting bases (hybrid-defence safety) ------------------------------------------------------------
        _case("craft-top-es-body-q20", robe_es, "Normal", 82, "opportunity",
              "Normal quality-20 top ES body armour is a crafting base for a build whose ES responds.",
              scope=("strong:ENERGY_SHIELD",), quality=20, area="valuable crafting base"),
        _case("craft-top-ar-es-body-q20", hybrid_ar_es, "Normal", 82, "opportunity",
              "Normal quality-20 top armour/ES hybrid is a crafting base for a build whose ES responds (hybrid-defence safety).",
              scope=("strong:ENERGY_SHIELD",), quality=20, area="hybrid-defence base"),
        _case("craft-top-ev-es-body-q20", hybrid_ev_es, "Normal", 82, "opportunity",
              "Normal quality-20 top evasion/ES hybrid is a crafting base for a build whose ES responds (hybrid-defence safety).",
              scope=("strong:ENERGY_SHIELD",), quality=20, area="hybrid-defence base"),
        _case("craft-top-ar-body-q20-any", plate_ar, "Normal", 82, "uncertain",
              "Quality armour base is a crafting candidate for armour builds; for other builds its use is unknown.", area="hybrid-defence base"),
        _case("craft-top-ev-body-q20-any", coat_ev, "Normal", 82, "uncertain",
              "Quality evasion base is a crafting candidate for evasion builds; for other builds its use is unknown.", area="hybrid-defence base"),
        # --- jewellery ------------------------------------------------------------------------------------------------------------
        _case("jewel-ring-top-rare-86", ring, "Rare", 86, "trade",
              "High-item-level rare ring: possible trade/crafting value, price unknown.", area="jewellery"),
        _case("jewel-amulet-top-rare-86", amulet, "Rare", 86, "trade",
              "High-item-level rare amulet: possible trade/crafting value, price unknown.", area="jewellery"),
        _case("jewel-amulet-top-magic-82", amulet, "Magic", 82, "uncertain",
              "Magic amulet value depends on unseen modifiers.", area="jewellery"),
        # --- unidentified rares and aggressive boundaries ---------------------------------------------------------------------------
        _case("unid-t5-body-i86", robe_es, "Rare", 86, "opportunity",
              "Highest-tier unidentified rare armour at the endgame item level.", tier=5, area="unidentified rare"),
        _case("unid-t5-ring-i86", ring, "Rare", 86, "opportunity",
              "Highest-tier unidentified rare jewellery at the endgame item level.", tier=5, area="unidentified rare"),
        _case("unid-t4-wand-i84", wand, "Rare", 84, "opportunity",
              "High-tier unidentified rare wand just below the strictest item-level gates.", tier=4, area="aggressive-profile boundary"),
        _case("boundary-staff-magic-84", staff, "Magic", 84, "uncertain",
              "Magic top staff exactly between the Strict and Very Strict item-level gates.", scope=spell, area="aggressive-profile boundary"),
        # --- clutter ------------------------------------------------------------------------------------------------------------------
        _case("clutter-low-magic-wand", "Bone Wand", "Magic", 60, "clutter",
              "Lowest-level magic wand at an endgame area level has no special trait.", area="clutter"),
        _case("clutter-low-normal-bow", "Crude Bow", "Normal", 50, "clutter",
              "Lowest-level unquality normal bow has no special trait.", area="clutter"),
        _case("clutter-low-normal-ring", "Iron Ring", "Normal", 50, "clutter",
              "Lowest-level unquality normal ring has no special trait.", area="clutter"),
        # --- unsupported mechanics ----------------------------------------------------------------------------------------------------
        _case("unsupported-quiver-spell-magic", quiver, "Magic", 82, "uncertain",
              "A quiver serves bow users; its value to a spell build is unknown.", scope=spell, area="unsupported mechanic"),
    )


def build_matrix(snapshots: Mapping[str, BuildNeedsSnapshot], extra: Mapping[str, BuildNeedsSnapshot] | None = None
                 ) -> dict[str, BuildNeedsSnapshot]:
    merged = dict(snapshots)
    merged.update(extra or {})
    return merged


def _outcome(expectation: str, hidden: bool) -> str:
    if not hidden:
        return "VISIBLE"
    return {"protect": "CONFIRMED ERROR", "opportunity": "POTENTIAL MISS", "trade": "POTENTIAL MISS",
            "clutter": "ACCEPTABLE HIDE", "uncertain": "UNKNOWN / INSUFFICIENT EVIDENCE"}[expectation]


def evaluate_corpus(needs: BuildNeedsSnapshot, *, intel: bool = True) -> dict:
    """Run FILTER-07 cases plus the 08B build-scoped cases through every profile for ONE build."""
    tags = extended_tags(needs)
    scoped = [case for case in fn_cases() if all(tag in tags for tag in case.scope)]
    legacy_cases = [(case.id, case.item, case.expectation, "filter07") for case in LOOT_CASES]
    new_cases = [(case.id, case.item, case.expectation, case.area) for case in scoped]
    rows = legacy_cases + new_cases
    result: dict = {"profiles": {}}
    for profile in PROFILES:
        generated = generate(needs, profile, intel=intel)
        decisions = evaluate(generated, [item for _, item, _, _ in rows])
        counts: dict[str, int] = {}
        misses = []
        for (case_id, item, expectation, area), decision in zip(rows, decisions):
            outcome = _outcome(expectation, decision.hidden)
            if outcome == "CONFIRMED ERROR":
                from exilelens.filters.profile_oracle import matrix_hides
                if matrix_hides(item, profile):
                    outcome = "MATRIX HIDE"       # the approved profile matrix says HIDE for this row at this level: policy, not an error
            counts[outcome] = counts.get(outcome, 0) + 1
            if outcome in ("CONFIRMED ERROR", "POTENTIAL MISS"):
                misses.append({"case": case_id, "area": area, "outcome": outcome, "item": item_summary(item),
                               "decision": decision_summary(decision)})
            elif expectation == "clutter" and not decision.hidden:
                counts["CLUTTER VISIBLE"] = counts.get("CLUTTER VISIBLE", 0) + 1
        result["profiles"][profile] = {"valid": generated.valid, "counts": dict(sorted(counts.items())), "misses": misses}
    result["cases"] = {"filter07": len(legacy_cases), "filter08b_scoped": len(new_cases)}
    return result
