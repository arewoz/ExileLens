"""Profile / strictness policy (FILTER profile system V2).

The approved target matrix (`data/profile_matrix.json`, authored in `artifacts/filter_profile_research/proposed_matrix.json`) is the ONLY place
that says what a strictness level does to an item family. Five levels, four states:

  SHOW+   the family's full Visual V4 attention treatment (sound / beam / minimap icon where V4 policy justifies them)
  SHOW    normal visible label at the family's V4 importance, no sound and no beam (the minimap icon stays)
  QUIET   still visible: one V4 importance level lower, no sound, no beam, no minimap icon
  HIDE    native Hide

Context is automatic: AreaLevel <= CAMPAIGN_MAX_AREA_LEVEL (campaign) behaves like the Relaxed column at every level, so a stricter level never
starves a levelling character; AreaLevel >= 65 (maps) uses the chosen level. There is no separate context setting.

Several rows can describe the same item (a premium craft base that is also a Rare top base): an item takes the MOST VISIBLE state of the rows it
belongs to (`most_visible`). Build Intelligence is a modifier, not a row of the same kind: see `build_modified`.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Iterable

DATA = Path(__file__).with_name("data") / "profile_matrix.json"

LEVELS = ("Relaxed", "Recommended", "Strict", "Very Strict", "Uber Strict")
DEFAULT_LEVEL = "Recommended"
STATES = ("SHOW+", "SHOW", "QUIET", "HIDE")
VISIBILITY_RANK = {"SHOW+": 3, "SHOW": 2, "QUIET": 1, "HIDE": 0}
CAMPAIGN_MAX_AREA_LEVEL = 64
MAPS_MIN_AREA_LEVEL = CAMPAIGN_MAX_AREA_LEVEL + 1

# Saved settings written before this profile model: the renamed or removed names and where they go. Anything unknown falls back to
# DEFAULT_LEVEL (the safe fallback), never raises in the settings path.
MIGRATED_NAMES = {"endgame": "Very Strict"}
ENDGAME_NOTICE = ("The Endgame profile is now Very Strict. Endgame progression (campaign vs maps, waystone relevance, crafting bases) is handled "
                  "automatically by every strictness level.")

# Native context bands for waystone relevance: a waystone of tier T opens an area of level 64 + T, so "tiers below the current area" is
# `AreaLevel - 64 - WaystoneTier`. The filter language cannot compare two item/area values, so each AreaLevel band carries the highest
# WaystoneTier that counts as far below it (lowest area of the band, so a band never calls a waystone far below too early).
WAYSTONE_FAR_BELOW_GAP = 3
WAYSTONE_BANDS: tuple[tuple[int, int | None, int], ...] = (   # (area level from, area level to, highest "far below" waystone tier)
    (65, 67, 0), (68, 70, 1), (71, 73, 4), (74, 76, 7), (77, 79, 10), (80, None, 13),
)


@lru_cache(maxsize=1)
def _data() -> dict:
    return json.loads(DATA.read_text(encoding="utf-8"))


def rows() -> dict[str, dict[str, str]]:
    return _data()["rows"]


def protected_floor() -> tuple[str, ...]:
    return tuple(_data()["protected_floor"])


def normalize_level(name: str | None) -> tuple[str, bool]:
    """(canonical level, migrated). Case-insensitive; removed / unknown names never raise: the result is the documented fallback."""
    if not name:
        return DEFAULT_LEVEL, False
    text = str(getattr(name, "value", name)).strip()
    for level in LEVELS:
        if level.lower() == text.lower() or level.upper().replace(" ", "_") == text.upper():
            return level, False
    migrated = MIGRATED_NAMES.get(text.lower())
    if migrated:
        return migrated, True
    return DEFAULT_LEVEL, True


def state(row: str, level: str) -> str:
    return rows()[row][level]


def campaign_state(row: str) -> str:
    """The state a row takes in the campaign at ANY level: the Relaxed column."""
    return rows()[row][LEVELS[0]]


def most_visible(states: Iterable[str]) -> str:
    return max(states, key=VISIBILITY_RANK.__getitem__)


def least_visible(states: Iterable[str]) -> str:
    return min(states, key=VISIBILITY_RANK.__getitem__)


def build_modified(generic: str, build_row_state: str) -> str:
    """Build Intelligence on build-irrelevant GENERIC equipment: it may quiet at any level, and may hide only where the generic row already
    let go (QUIET or HIDE). It never raises visibility."""
    if VISIBILITY_RANK[generic] <= VISIBILITY_RANK["QUIET"]:
        return least_visible((generic, build_row_state))
    return least_visible((generic, "QUIET" if build_row_state == "HIDE" else build_row_state))


@dataclass(frozen=True)
class ProfilePolicy:
    level: str

    def state(self, row: str) -> str:
        return rows()[row][self.level]

    def campaign(self, row: str) -> str:
        return campaign_state(row)

    def contexts(self, row: str) -> tuple[tuple[str, str | None], ...]:
        """((state, area condition), ...) covering the campaign and maps; a single unconditional entry when both contexts agree."""
        maps, camp = self.state(row), self.campaign(row)
        if maps == camp:
            return ((maps, None),)
        return ((camp, f"AreaLevel <= {CAMPAIGN_MAX_AREA_LEVEL}"), (maps, f"AreaLevel >= {MAPS_MIN_AREA_LEVEL}"))


# -- row definitions: the exact native-observable meaning of every row, used by the generator AND the test oracle ---------------------
ROW_DEFINITIONS: dict[str, str] = {
    "currency_mythic": "currency_tiers CURRENCY_HERO names",
    "currency_premium": "currency_tiers CURRENCY_PREMIUM names (Divine tier)",
    "currency_enhanced": "currency_tiers CURRENCY_ENHANCED names (Greater / Perfect Chaos, Exalted, Regal)",
    "currency_craft": "currency_tiers CURRENCY_CRAFT names (Greater / Perfect Transmutation, Augmentation)",
    "currency_valuable": "currency_tiers CURRENCY_VALUABLE names",
    "currency_utility": "currency_tiers CURRENCY_UTILITY names (evidenced utility currency)",
    "currency_shards_low": "currency_tiers CURRENCY_LOW names (shards, scraps, Scroll of Wisdom)",
    "eq_normal_low": "Normal / Magic, verified equipment base whose global quality tier is not T1 / T2 (non-jewellery)",
    "eq_magic_low": "same set as eq_normal_low",
    "eq_normal_top": "Normal / Magic, verified equipment base with global quality tier T1 / T2 (non-jewellery)",
    "eq_magic_top": "same set as eq_normal_top",
    "eq_rare_low": "Rare, verified non-jewellery base with global tier below T2",
    "eq_rare_top": "Rare, verified non-jewellery base with global tier T1 / T2",
    "eq_rare_top_ilvl82": "eq_rare_top at ItemLevel >= 82",
    "eq_rare_unid_t3_4": "Rare equipment with UnidentifiedItemTier 3 or 4",
    "eq_rare_unid_t5": "Rare equipment with UnidentifiedItemTier 5",
    "build_relevant_base": "a base of the build lane (measured Build Intelligence) at its tier gate, or an opportunity rule base",
    "build_irrelevant_generic_nm": "Normal / Magic generic equipment whose pure defence layer the build MEASURED as no response (modifier)",
    "craft_premium_normal_ilvl82": "Normal base, CraftLevel PREMIUM, ItemLevel >= max(82, its breakpoint)",
    "craft_premium_magic_ilvl82": "Magic base, CraftLevel PREMIUM, ItemLevel >= max(82, its breakpoint)",
    "craft_premium_below_ilvl82": "Normal / Magic base, CraftLevel PREMIUM, breakpoint <= ItemLevel < 82",
    "craft_relevant_normal": "Normal base, CraftLevel RELEVANT, ItemLevel >= its breakpoint",
    "craft_relevant_magic": "Magic base, CraftLevel RELEVANT, ItemLevel >= its breakpoint",
    "craft_low": "Normal / Magic base with CraftLevel LOW",
    "craft_unknown": "Normal / Magic base with CraftLevel UNKNOWN",
    "craft_any_rare": "Rare base with CraftLevel PREMIUM / RELEVANT, ItemLevel >= its breakpoint",
    "jewellery_low_generic": "Normal / Magic ring, amulet or belt whose global tier is not T1",
    "jewellery_premium_base": "Normal / Magic ring, amulet or belt with global tier T1",
    "jewellery_rare": "Rare ring, amulet or belt",
    "gems_uncut_top": "uncut gem with GemLevel >= 19, or the area-appropriate level (GemLevel 14..18 while AreaLevel <= 65 / 69 / 73 / 77 / 79)",
    "gems_uncut_other": "every other uncut skill / support / spirit gem",
    "jewels_rare": "Rare jewel", "jewels_magic": "Normal / Magic jewel",
    "charms_top": "charm with Quality >= 10 or ItemLevel >= 82", "charms_other": "every other charm",
    "flasks_top": "flask with Quality >= 10 or ItemLevel >= 82", "flasks_other": "every other flask",
    "waystones_far_below_area": "waystone more than WAYSTONE_FAR_BELOW_GAP - 1 tiers below the area's tier (WAYSTONE_BANDS), tiers 1-10",
    "waystones_near_area": "waystone tiers 1-10 not far below the area",
    "waystones_t11_14": "WaystoneTier 11-14", "waystones_t15_16": "WaystoneTier >= 15",
    "tablets": "Class Tablet", "special_endgame": "Class Omen / Pinnacle Keys / Map Fragments",
    "augments_top": "Class Augment (no tier evidence in the repository: every augment)", "augments_low": "none (no evidenced low augment names)",
    "uniques_generic": "Rarity Unique on a verified base that is not exceptional",
    "uniques_top": "Rarity Unique that is Corrupted, Mirrored or Quality >= 21",
    "quest_items": "Class Quest Items / Instance Local Items",
    "unknown_new_items": "anything no row above classifies (unknown base, new class, unnamed currency): explicit catch-all",
}

# Rows whose native definition is weaker than the row's name promises; reported, never silently stretched.
KNOWN_GAPS: dict[str, str] = {
    "uniques_top": "Unique names cannot be matched natively and ExileLens has no unique tier list: 'top' is limited to observable exceptional "
                   "states (Corrupted / Mirrored / Quality >= 21). Every other unique is 'generic' of UNKNOWN market value: it is never HIDE for "
                   "the profile alone (Uber Strict = QUIET) until a trusted market signal or a verified static value tier exists "
                   "(see unique_state).",
    "augments_low": "No exact augment (rune / soul core) names are evidenced in the repository, so no augment can be classified low: the row is "
                    "empty and every augment follows augments_top.",
    "currency_utility": "Only names with evidence are listed (observed in game or in the pinned community filter text); unlisted currency falls to "
                        "unknown_new_items (visible) instead of being guessed as utility.",
}


# -- uniques: the contract a future trusted market signal plugs into (NOT wired; no market tier is invented) --------------------------
UNIQUE_SIGNALS = ("TRADE_PREMIUM", "VERIFIED_LOW", "UNKNOWN")


def unique_state(level: str, signal: str | None = None) -> str:
    """State of a Unique at ``level`` given what is KNOWN about its value.

    TRADE_PREMIUM (high-confidence valuable)  -> SHOW+ at every level.
    VERIFIED_LOW  (trusted low value)         -> the only case allowed to follow a stricter policy: the generic row, and HIDE at Uber Strict.
    UNKNOWN / None (today: every ordinary unique) -> the generic row, which is never HIDE: unknown value is never hidden by strictness alone.
    """
    level, _ = normalize_level(level)
    generic = state("uniques_generic", level)
    if signal == "TRADE_PREMIUM":
        return "SHOW+"
    if signal == "VERIFIED_LOW":
        return "HIDE" if level == LEVELS[-1] else generic
    if generic == "HIDE":                         # defence in depth: the matrix itself must never hide an unknown-value unique
        raise ValueError("uniques_generic must not be HIDE for an unknown-value unique")
    return generic
