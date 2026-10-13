"""Independent FILTER-07 item expectations for a simulated ground-loot benchmark.

Base names and intrinsic defences come from the pinned PoB2 0.23.1 snapshot;
special currency names come from the GGG item-filter notice. Rarity/level/
quality combinations are controlled test cases, not observed drops or prices.
"""
from __future__ import annotations

from dataclasses import dataclass

from exilelens.filters.preview import PREVIEW_ITEMS, PreviewItem
from exilelens.filters.verified_bases import FILTER_TO_POB_CLASS, load_base_properties


@dataclass(frozen=True)
class LootCase:
    id: str
    item: PreviewItem
    expectation: str  # protect, opportunity, trade, clutter, uncertain
    rationale: str
    source: str


# This independent review annotates the 29 pre-existing preview items. The
# expectation is authored by loot category/item potential, never read from rules.
_PREVIEW_EXPECTATIONS = (
    ("protect", "Exceptional named currency; hiding risks a costly miss."),
    ("protect", "Currency is generally worth inspecting; exact price unknown."),
    ("protect", "Basic crafting currency should stay accessible."),
    ("protect", "Named enhanced currency; no live value asserted."),
    ("protect", "Named crafting currency; no live value asserted."),
    ("protect", "Named enhanced currency; no live value asserted."),
    ("protect", "Omen is a special reward class with uncertain individual value."),
    ("protect", "Map fragment is a protected progression/special class."),
    ("protect", "Augment is a protected socketable class."),
    ("protect", "Tablet is an endgame progression class."),
    ("protect", "Tier 15 waystone is relevant to endgame progression."),
    ("uncertain", "Tier 8 waystone is useful to some characters but profile-dependent."),
    ("opportunity", "High-tier unidentified rare can contain unknown valuable modifiers."),
    ("opportunity", "High-level rare staff is an inspectable crafting/build candidate; implicit fit uncertain."),
    ("opportunity", "Quality staff has crafting utility without a claimed price."),
    ("trade", "High-item-level rare verified wand is a possible trade base, not a sale."),
    ("uncertain", "Magic wand may be useful if its unidentified or known modifiers fit."),
    ("uncertain", "Midlevel magic wand has unknown rolls and limited base evidence."),
    ("opportunity", "High-item-level rare ES robe can contain unknown useful modifiers."),
    ("trade", "High-item-level rare robe is a possible trade base without a price."),
    ("uncertain", "Rare boots have unknown modifiers; visibility is prudent."),
    ("clutter", "Ordinary magic armour with no stated quality or rare modifiers."),
    ("trade", "High-item-level rare ring has possible trade/crafting utility."),
    ("trade", "High-item-level rare ring has possible trade/crafting utility."),
    ("uncertain", "Rare belt rolls are unknown; do not call it worthless."),
    ("clutter", "Low-item-level magic greaves have no stated quality or special trait."),
    ("uncertain", "Magic amulet value depends on unseen modifiers."),
    ("opportunity", "Quality normal ES robe is a crafting candidate."),
    ("clutter", "Low-item-level ordinary ring with no quality or special trait."),
)
assert len(_PREVIEW_EXPECTATIONS) == len(PREVIEW_ITEMS)


def _gear(case_id: str, base: str, rarity: str, *, level: int = 82, quality: int = 0,
          tier: int = 0, expectation: str, rationale: str) -> LootCase:
    properties = load_base_properties()[base]  # fail closed on an unknown name
    pob_class = properties["class"]
    item_class = next((native for native, pob in FILTER_TO_POB_CLASS.items() if pob == pob_class), None)
    if item_class is None:
        raise ValueError(f"No verified native class mapping for {base}: {pob_class}")
    item = PreviewItem(base, "FILTER-07 controlled equipment", item_class, base,
                       rarity, item_level=level, quality=quality,
                       unidentified_item_tier=tier,
                       base_energy_shield=properties["energy_shield"],
                       base_armour=properties["armour"],
                       base_evasion=properties["evasion"])
    return LootCase(case_id, item, expectation, rationale,
                    "pinned PoB2 0.23.1 base; rarity/level/quality simulated")


def _special(case_id: str, name: str, item_class: str, *, expectation: str,
             rationale: str, tier: int = 0) -> LootCase:
    return LootCase(case_id, PreviewItem(name, "FILTER-07 controlled special", item_class,
                                        name if item_class == "Stackable Currency" else "",
                                        waystone_tier=tier), expectation, rationale,
                    "GGG named currency or native class; controlled simulated drop")


def _load_cases():
    import json
    from pathlib import Path
    data = json.loads((Path(__file__).parent / "data" / "benchmark_loot.json").read_text(encoding="utf-8"))
    return tuple(LootCase(**{**row, "item": PreviewItem(**row["item"])}) for row in data)


LOOT_CASES: tuple[LootCase, ...] = _load_cases()
