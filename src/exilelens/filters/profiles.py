"""Filter Profiles and Core Types for FILTER-01."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from enum import Enum
from typing import Any, Dict, FrozenSet, Literal, Set
from datetime import datetime


class BaseTier(str, Enum):
    """Equipment base tier classification."""
    T1 = "T1"           # Best-in-slot / meta bases
    T2 = "T2"           # Strong alternatives
    T3 = "T3"           # Viable budget options
    T4 = "T4"           # Niche / leveling only
    IGNORE = "IGNORE"   # Never show


class DefenseLayer(str, Enum):
    """Primary defense layer classification."""
    ENERGY_SHIELD = "ENERGY_SHIELD"
    ARMOUR = "ARMOUR"
    EVASION = "EVASION"
    WARD = "WARD"
    HYBRID_AR_ES = "HYBRID_AR_ES"
    HYBRID_EV_ES = "HYBRID_EV_ES"
    HYBRID_AR_EV = "HYBRID_AR_EV"
    HYBRID_AR_EV_ES = "HYBRID_AR_EV_ES"
    UNKNOWN = "UNKNOWN"

    @classmethod
    def from_totals(cls, es: float, ar: float, ev: float, ward: float) -> DefenseLayer:
        """Classify observed layers without comparing unlike defence units.

        Armour, evasion and energy shield values have different scales. A small
        secondary equipped layer is enough to make an aggressive pure-layer hide
        unsafe; mixed Ward/other gear is left unknown.
        """
        active = frozenset(name for name, value in (
            ("ES", es), ("AR", ar), ("EV", ev), ("WARD", ward)) if value > 0)
        return {
            frozenset(): cls.UNKNOWN,
            frozenset({"ES"}): cls.ENERGY_SHIELD,
            frozenset({"AR"}): cls.ARMOUR,
            frozenset({"EV"}): cls.EVASION,
            frozenset({"WARD"}): cls.WARD,
            frozenset({"AR", "ES"}): cls.HYBRID_AR_ES,
            frozenset({"EV", "ES"}): cls.HYBRID_EV_ES,
            frozenset({"AR", "EV"}): cls.HYBRID_AR_EV,
            frozenset({"AR", "EV", "ES"}): cls.HYBRID_AR_EV_ES,
        }.get(active, cls.UNKNOWN)


class ProductSlot(str, Enum):
    """Product equipment slots (matches POB2_ENGINE_CONTRACT.md)."""
    HELMET = "HELMET"
    BODY_ARMOUR = "BODY_ARMOUR"
    GLOVES = "GLOVES"
    BOOTS = "BOOTS"
    BELT = "BELT"
    AMULET = "AMULET"
    RING_1 = "RING_1"
    RING_2 = "RING_2"
    WEAPON_1 = "WEAPON_1"
    WEAPON_2 = "WEAPON_2"
    OFFHAND_1 = "OFFHAND_1"
    OFFHAND_2 = "OFFHAND_2"


class FilterProfileName(str, Enum):
    """Filter strictness levels (profile system V2): one dial, Recommended is the default. "Endgame" is no longer a level: it migrates to
    Very Strict (see profile_policy.MIGRATED_NAMES) and endgame behaviour is automatic context."""
    RELAXED = "Relaxed"
    RECOMMENDED = "Recommended"
    STRICT = "Strict"
    VERY_STRICT = "Very Strict"
    UBER_STRICT = "Uber Strict"

    @classmethod
    def _missing_(cls, value):                      # FilterProfileName("Endgame") -> VERY_STRICT; unknown values stay a ValueError
        from exilelens.filters.profile_policy import MIGRATED_NAMES
        text = str(value).strip().lower()
        for member in cls:
            if member.value.lower() == text:
                return member
        target = MIGRATED_NAMES.get(text)
        return cls(target) if target else None


class FilterThemeName(str, Enum):
    """Visual themes for filter item labels."""
    VOID_GOLD = "Void Gold"
    BLOOD_SIGIL = "Blood Sigil"
    ARCANE_PRISM = "Arcane Prism"
    VERDANT_RELIC = "Verdant Relic"
    EMBERFORGE = "Emberforge"
    ABYSSAL_COVENANT = "Abyssal Covenant"
    ETERNAL_EMPIRE = "Eternal Empire"
    WRAECLAST_ASHES = "Wraeclast Ashes"


@dataclass(frozen=True)
class FilterProfile:
    """One strictness level. What it does to each item family is the matrix in profile_policy (the only policy source); a profile carries only
    its name and the visual theme. Visibility never depends on the theme."""
    name: FilterProfileName
    theme: FilterThemeName = FilterThemeName.VOID_GOLD

    @property
    def policy(self):
        from exilelens.filters.profile_policy import ProfilePolicy
        return ProfilePolicy(self.name.value)


@dataclass(frozen=True)
class FilterTheme:
    """Visual theme specification for filter item labels.

    Maps to native PoE2 filter actions: SetTextColor, SetBorderColor,
    SetBackgroundColor, SetFontSize, MinimapIcon, PlayEffect.
    """
    name: FilterThemeName

    # Tier-specific styling (T1 = highest importance)
    tier_styles: Dict[BaseTier, Dict[str, any]]

    # Category-specific overrides
    category_overrides: Dict[str, Dict[str, any]]

    # Global defaults
    default_font_size: int = 30
    default_text_color: str = "255 255 255 255"
    default_border_color: str = "128 128 128 255"
    default_bg_color: str = "20 20 20 240"


# Theme definitions using valid PoE2 filter syntax
THEMES: Dict[FilterThemeName, FilterTheme] = {
    FilterThemeName.VOID_GOLD: FilterTheme(
        name=FilterThemeName.VOID_GOLD,
        tier_styles={
            BaseTier.T1: {
                "font_size": 38,
                "text_color": "255 215 0 255",      # Gold
                "border_color": "255 215 0 255",    # Gold
                "bg_color": "25 15 0 255",          # Dark gold-tinted
                "minimap_icon": "1 Yellow Diamond",
                "play_effect": "Yellow",
            },
            BaseTier.T2: {
                "font_size": 34,
                "text_color": "230 190 60 255",     # Muted gold
                "border_color": "200 160 40 255",
                "bg_color": "20 15 5 255",
                "minimap_icon": "1 Yellow Circle",
                "play_effect": "Yellow Temp",
            },
            BaseTier.T3: {
                "font_size": 30,
                "text_color": "200 170 80 255",
                "border_color": "160 130 40 255",
                "bg_color": "18 14 5 255",
                "minimap_icon": "2 Yellow Circle",
                "play_effect": "None",
            },
            BaseTier.T4: {
                "font_size": 26,
                "text_color": "180 150 70 255",
                "border_color": "120 100 30 255",
                "bg_color": "15 12 5 255",
                "minimap_icon": "None",
                "play_effect": "None",
            },
        },
        category_overrides={
            "currency": {"text_color": "255 255 255 255", "border_color": "255 215 0 255", "bg_color": "30 20 0 255", "font_size": 30},
            "unique": {"text_color": "175 96 37 255", "border_color": "175 96 37 255", "bg_color": "40 20 0 255", "font_size": 35},
            "socketable": {"text_color": "0 255 255 255", "border_color": "0 255 255 255", "bg_color": "0 40 40 255", "font_size": 32, "minimap_icon": "1 Cyan Diamond"},
            "waystone": {"text_color": "255 200 0 255", "border_color": "255 200 0 255", "bg_color": "40 30 0 255", "font_size": 30},
            "quest": {"text_color": "74 230 58 255", "border_color": "74 230 58 255", "bg_color": "0 40 0 255", "font_size": 35},
            "high_unid": {"text_color": "0 240 190 255", "border_color": "0 240 190 255", "bg_color": "0 75 30 255", "font_size": 38, "minimap_icon": "1 Blue Diamond"},
            "crafting_base": {"text_color": "215 228 165 255", "border_color": "125 158 79 255", "bg_color": "25 38 16 255", "font_size": 33},
            "trade": {"text_color": "245 219 150 255", "border_color": "200 157 63 255", "bg_color": "38 28 12 255", "font_size": 34, "minimap_icon": "1 Yellow Hexagon"},
            "special": {"text_color": "255 246 207 255", "border_color": "245 204 80 255", "bg_color": "45 29 5 255", "font_size": 38, "minimap_icon": "0 Yellow Star", "play_effect": "Yellow"},
            "hero": {"text_color": "255 250 225 255", "border_color": "255 214 85 255", "bg_color": "54 37 7 255", "font_size": 45, "minimap_icon": "0 Yellow Star", "play_effect": "Yellow"},
        },
        default_font_size=30,
        default_text_color="200 200 200 255",
        default_border_color="100 100 100 255",
        default_bg_color="25 25 25 255",
    ),
    FilterThemeName.BLOOD_SIGIL: FilterTheme(
        name=FilterThemeName.BLOOD_SIGIL,
        tier_styles={
            BaseTier.T1: {
                "font_size": 38,
                "text_color": "220 20 60 255",      # Crimson
                "border_color": "180 0 40 255",     # Dark crimson
                "bg_color": "40 0 10 255",          # Deep blood
                "minimap_icon": "1 Red Diamond",
                "play_effect": "Red",
            },
            BaseTier.T2: {
                "font_size": 34,
                "text_color": "200 60 80 255",      # Muted crimson
                "border_color": "160 40 60 255",
                "bg_color": "35 5 10 255",
                "minimap_icon": "1 Red Circle",
                "play_effect": "Red Temp",
            },
            BaseTier.T3: {
                "font_size": 30,
                "text_color": "180 80 90 255",
                "border_color": "140 50 60 255",
                "bg_color": "30 5 10 255",
                "minimap_icon": "2 Red Circle",
                "play_effect": "None",
            },
            BaseTier.T4: {
                "font_size": 26,
                "text_color": "160 100 100 255",
                "border_color": "100 40 50 255",
                "bg_color": "25 5 10 255",
                "minimap_icon": "None",
                "play_effect": "None",
            },
        },
        category_overrides={
            "currency": {"text_color": "255 255 255 255", "border_color": "220 20 60 255", "bg_color": "40 0 10 255", "font_size": 30},
            "unique": {"text_color": "180 40 60 255", "border_color": "180 40 60 255", "bg_color": "45 5 15 255", "font_size": 35},
            "socketable": {"text_color": "255 100 100 255", "border_color": "255 100 100 255", "bg_color": "50 10 10 255", "font_size": 32, "minimap_icon": "1 Red Diamond"},
            "waystone": {"text_color": "255 150 50 255", "border_color": "200 100 30 255", "bg_color": "40 15 5 255", "font_size": 30},
            "quest": {"text_color": "100 255 100 255", "border_color": "100 200 100 255", "bg_color": "0 40 0 255", "font_size": 35},
            "high_unid": {"text_color": "255 100 120 255", "border_color": "200 60 80 255", "bg_color": "40 10 15 255", "font_size": 38, "minimap_icon": "1 Red Diamond"},
            "crafting_base": {"text_color": "225 186 157 255", "border_color": "164 99 84 255", "bg_color": "37 19 20 255", "font_size": 33},
            "trade": {"text_color": "255 175 164 255", "border_color": "204 58 77 255", "bg_color": "48 12 21 255", "font_size": 34, "minimap_icon": "1 Red Cross"},
            "special": {"text_color": "255 228 219 255", "border_color": "243 40 75 255", "bg_color": "60 7 20 255", "font_size": 38, "minimap_icon": "0 Red Star", "play_effect": "Red"},
            "hero": {"text_color": "255 242 226 255", "border_color": "255 60 88 255", "bg_color": "75 7 22 255", "font_size": 45, "minimap_icon": "0 Red Star", "play_effect": "Red"},
        },
        default_font_size=30,
        default_text_color="200 180 180 255",
        default_border_color="100 60 60 255",
        default_bg_color="30 5 10 255",
    ),
    FilterThemeName.ARCANE_PRISM: FilterTheme(
        name=FilterThemeName.ARCANE_PRISM,
        tier_styles={
            BaseTier.T1: {
                "font_size": 38,
                "text_color": "100 200 255 255",    # Bright cyan
                "border_color": "0 180 255 255",    # Electric blue
                "bg_color": "0 20 40 255",          # Deep arcane
                "minimap_icon": "1 Blue Diamond",
                "play_effect": "Blue",
            },
            BaseTier.T2: {
                "font_size": 34,
                "text_color": "150 180 255 255",    # Light blue
                "border_color": "80 140 255 255",
                "bg_color": "5 15 35 255",
                "minimap_icon": "1 Blue Circle",
                "play_effect": "Blue Temp",
            },
            BaseTier.T3: {
                "font_size": 30,
                "text_color": "160 170 240 255",
                "border_color": "70 110 220 255",
                "bg_color": "5 10 30 255",
                "minimap_icon": "2 Blue Circle",
                "play_effect": "None",
            },
            BaseTier.T4: {
                "font_size": 26,
                "text_color": "140 150 220 255",
                "border_color": "60 80 180 255",
                "bg_color": "5 8 25 255",
                "minimap_icon": "None",
                "play_effect": "None",
            },
        },
        category_overrides={
            "currency": {"text_color": "255 255 255 255", "border_color": "100 200 255 255", "bg_color": "0 20 40 255", "font_size": 30},
            "unique": {"text_color": "180 100 255 255", "border_color": "180 100 255 255", "bg_color": "25 10 45 255", "font_size": 35},
            "socketable": {"text_color": "0 255 255 255", "border_color": "0 255 255 255", "bg_color": "0 40 40 255", "font_size": 32, "minimap_icon": "1 Cyan Diamond"},
            "waystone": {"text_color": "200 150 255 255", "border_color": "180 100 255 255", "bg_color": "25 10 40 255", "font_size": 30},
            "quest": {"text_color": "100 255 180 255", "border_color": "100 200 150 255", "bg_color": "0 40 20 255", "font_size": 35},
            "high_unid": {"text_color": "100 220 255 255", "border_color": "60 180 255 255", "bg_color": "0 30 50 255", "font_size": 38, "minimap_icon": "1 Blue Diamond"},
            "crafting_base": {"text_color": "187 230 222 255", "border_color": "92 155 173 255", "bg_color": "14 33 41 255", "font_size": 33},
            "trade": {"text_color": "221 206 255 255", "border_color": "129 96 255 255", "bg_color": "24 17 56 255", "font_size": 34, "minimap_icon": "1 Purple Kite"},
            "special": {"text_color": "225 250 255 255", "border_color": "62 219 255 255", "bg_color": "9 32 71 255", "font_size": 38, "minimap_icon": "0 Cyan Star", "play_effect": "Cyan"},
            "hero": {"text_color": "246 254 255 255", "border_color": "75 231 255 255", "bg_color": "17 32 87 255", "font_size": 45, "minimap_icon": "0 Cyan Star", "play_effect": "Cyan"},
        },
        default_font_size=30,
        default_text_color="180 190 220 255",
        default_border_color="60 80 120 255",
        default_bg_color="15 20 35 255",
    ),
    FilterThemeName.VERDANT_RELIC: FilterTheme(
        name=FilterThemeName.VERDANT_RELIC,
        tier_styles={
            BaseTier.T1: {"font_size": 40, "text_color": "234 245 191 255", "border_color": "72 211 128 255", "bg_color": "10 39 27 255", "minimap_icon": "0 Green Pentagon", "play_effect": "Green"},
            BaseTier.T2: {"font_size": 34, "text_color": "177 234 176 255", "border_color": "66 150 100 255", "bg_color": "13 34 25 255", "minimap_icon": "1 Green Triangle", "play_effect": "Green Temp"},
            BaseTier.T3: {"font_size": 29, "text_color": "175 199 156 255", "border_color": "69 113 78 255", "bg_color": "16 29 23 255"},
            BaseTier.T4: {"font_size": 25, "text_color": "155 174 143 255", "border_color": "61 91 70 255", "bg_color": "17 26 21 255"},
        },
        category_overrides={
            "currency": {"font_size": 33, "text_color": "251 237 177 255", "border_color": "174 142 69 255", "bg_color": "39 34 18 255"},
            "special": {"font_size": 38, "text_color": "255 243 196 255", "border_color": "91 222 137 255", "bg_color": "13 55 35 255", "minimap_icon": "0 Green Star", "play_effect": "Green"},
            "hero": {"font_size": 45, "text_color": "255 250 220 255", "border_color": "113 245 150 255", "bg_color": "15 66 38 255", "minimap_icon": "0 Green Star", "play_effect": "Green"},
            "trade": {"font_size": 34, "text_color": "231 226 174 255", "border_color": "135 185 91 255", "bg_color": "26 43 22 255", "minimap_icon": "1 Green Pentagon"},
            "crafting_base": {"font_size": 33, "text_color": "209 226 176 255", "border_color": "107 152 80 255", "bg_color": "24 39 21 255"},
        },
        default_font_size=28, default_text_color="188 205 173 255", default_border_color="71 115 79 255", default_bg_color="16 29 22 255",
    ),
    FilterThemeName.EMBERFORGE: FilterTheme(
        name=FilterThemeName.EMBERFORGE,
        tier_styles={
            BaseTier.T1: {"font_size": 41, "text_color": "255 241 207 255", "border_color": "255 100 42 255", "bg_color": "51 20 14 255", "minimap_icon": "0 Orange Hexagon", "play_effect": "Orange"},
            BaseTier.T2: {"font_size": 34, "text_color": "255 198 143 255", "border_color": "200 94 48 255", "bg_color": "38 22 19 255", "minimap_icon": "1 Orange Square", "play_effect": "Orange Temp"},
            BaseTier.T3: {"font_size": 29, "text_color": "211 177 150 255", "border_color": "142 88 62 255", "bg_color": "30 25 24 255"},
            BaseTier.T4: {"font_size": 25, "text_color": "166 151 141 255", "border_color": "96 76 68 255", "bg_color": "27 25 25 255"},
        },
        category_overrides={
            "currency": {"font_size": 33, "text_color": "255 229 192 255", "border_color": "246 137 59 255", "bg_color": "55 25 13 255"},
            "special": {"font_size": 38, "text_color": "255 248 224 255", "border_color": "255 89 40 255", "bg_color": "70 22 10 255", "minimap_icon": "0 Orange Star", "play_effect": "Orange"},
            "hero": {"font_size": 45, "text_color": "255 251 231 255", "border_color": "255 111 46 255", "bg_color": "80 26 8 255", "minimap_icon": "0 Orange Star", "play_effect": "Orange"},
            "trade": {"font_size": 34, "text_color": "255 197 144 255", "border_color": "220 111 63 255", "bg_color": "48 26 21 255", "minimap_icon": "1 Orange Hexagon"},
            "crafting_base": {"font_size": 33, "text_color": "222 193 159 255", "border_color": "156 116 77 255", "bg_color": "42 29 24 255"},
        },
        default_font_size=28, default_text_color="207 190 177 255", default_border_color="118 80 66 255", default_bg_color="32 25 24 255",
    ),
}


def _new_native_theme(name: FilterThemeName, color: str, shape: str,
                      accent: str, dark: str) -> FilterTheme:
    """Native actions for new themes; label colours resolve in style_system."""
    return FilterTheme(
        name=name,
        tier_styles={
            BaseTier.T1: {"font_size": 40, "text_color": accent,
                          "border_color": accent, "bg_color": dark,
                          "minimap_icon": f"0 {color} {shape}", "play_effect": color},
            BaseTier.T2: {"font_size": 34, "text_color": accent,
                          "border_color": accent, "bg_color": dark,
                          "minimap_icon": f"1 {color} {shape}", "play_effect": f"{color} Temp"},
            BaseTier.T3: {"font_size": 29, "text_color": accent,
                          "border_color": accent, "bg_color": dark},
            BaseTier.T4: {"font_size": 25, "text_color": accent,
                          "border_color": accent, "bg_color": dark},
        },
        category_overrides={
            "hero": {"minimap_icon": f"0 {color} Star", "play_effect": color},
            "special": {"minimap_icon": f"0 {color} {shape}", "play_effect": color},
            "socketable": {"minimap_icon": f"1 {color} Diamond"},
            "trade": {"minimap_icon": f"1 {color} {shape}"},
        },
        default_text_color=accent,
        default_border_color=accent,
        default_bg_color=dark,
    )


THEMES.update({
    FilterThemeName.ABYSSAL_COVENANT: _new_native_theme(
        FilterThemeName.ABYSSAL_COVENANT, "Purple", "Moon",
        "217 179 246 255", "26 13 37 250"),
    FilterThemeName.ETERNAL_EMPIRE: _new_native_theme(
        FilterThemeName.ETERNAL_EMPIRE, "Yellow", "Pentagon",
        "245 226 177 255", "39 31 25 250"),
    FilterThemeName.WRAECLAST_ASHES: _new_native_theme(
        FilterThemeName.WRAECLAST_ASHES, "Grey", "Diamond",
        "213 224 229 255", "22 28 32 250"),
})


def get_theme(name: str | FilterThemeName) -> FilterTheme:
    """Get theme by name (case-insensitive)."""
    if isinstance(name, FilterThemeName):
        key = name
    else:
        try:
            key = FilterThemeName[name.upper().replace(" ", "_")]
        except KeyError:
            for k, v in FilterThemeName.__members__.items():
                if v.value.lower() == name.lower():
                    key = v
                    break
            else:
                raise ValueError(f"Unknown theme: {name}")
    return THEMES[key]


# Profile presets (one per level; the behaviour lives in the matrix)
PROFILES: Dict[FilterProfileName, FilterProfile] = {name: FilterProfile(name=name) for name in FilterProfileName}

PROFILE_INTENT: Dict[FilterProfileName, str] = {
    FilterProfileName.RELAXED: "Broad visibility, with common loot kept quiet.",
    FilterProfileName.RECOMMENDED: "Balanced visibility. Ordinary rares and low waystones stay quiet.",
    FilterProfileName.STRICT: "Less common loot; strong crafting bases stay visible.",
    FilterProfileName.VERY_STRICT: "Top rare bases, with quieter currency and crafting loot.",
    FilterProfileName.UBER_STRICT: "Strong opportunities and protected value, with minimal clutter.",
}


def get_profile(name: str | FilterProfileName) -> FilterProfile:
    """Get a profile by name (case-insensitive). The removed "Endgame" name resolves to Very Strict; any other unknown name is a ValueError
    (use profile_policy.normalize_level for settings, where the safe fallback is Recommended)."""
    if isinstance(name, FilterProfileName):
        return PROFILES[name]
    text = str(name).strip()
    try:
        return PROFILES[FilterProfileName[text.upper().replace(" ", "_")]]
    except KeyError:
        pass
    try:
        return PROFILES[FilterProfileName(text)]
    except ValueError:
        raise ValueError(f"Unknown profile: {name}") from None


def get_profile_with_theme(profile_name: str | FilterProfileName, theme_name: str | FilterThemeName) -> FilterProfile:
    """Get a profile with a specific theme override."""
    profile = get_profile(profile_name)
    theme = get_theme(theme_name)
    # Return a new profile with the theme applied
    return replace(profile, theme=theme.name)


def get_all_themes() -> list[FilterThemeName]:
    """Get all available theme names."""
    return list(FilterThemeName)


@dataclass(frozen=True)
class BuildFingerprint:
    """Complete build fingerprint for filter generation."""
    # Identity
    build_name: str
    class_name: str
    ascendancy: str
    main_skill: str
    main_skill_gem: str

    # Equipment baseline
    equipped: Dict[ProductSlot, 'EquippedItemSummary']

    # Normalized metrics (MAP context)
    offense_primary_dps: float
    defense_ehp: float
    life: float
    energy_shield: float
    mana: float
    fire_res: int
    cold_res: int
    lightning_res: int
    chaos_res: int
    movement_speed: float

    # Resistance analysis
    resist_caps: Dict[str, str]  # element -> CapState value

    # Blocker/repair analysis
    blockers: list['BlockerSummary']
    repair_vector: 'RepairVectorSummary'

    # Offense coverage
    offense_coverage: Dict[str, str]  # dimension -> evidence level

    # Thresholds
    thresholds: list['ThresholdEventSummary']

    # Metadata
    source_revision: str
    generated_at: datetime
    defense_layer: DefenseLayer


@dataclass(frozen=True)
class EquippedItemSummary:
    """Summary of an equipped item for fingerprint."""
    slot: ProductSlot
    base_type: str
    item_class: str
    rarity: str
    item_level: int
    quality: int
    base_armour: float
    base_evasion: float
    base_energy_shield: float
    base_ward: float
    implicit_mods: list[str]
    explicit_mods: list[str]


@dataclass(frozen=True)
class BlockerSummary:
    """Summary of an upgrade blocker."""
    blocker_type: str
    metric: str
    label: str
    severity: str
    repairable: bool
    repair_target: float
    probe_id: str


@dataclass(frozen=True)
class RepairVectorSummary:
    """Summary of repair vector."""
    repairs: list[Dict[str, any]]


@dataclass(frozen=True)
class ThresholdEventSummary:
    """Summary of a threshold event."""
    code: str
    metric: str
    before: float | None
    after: float | None
    threshold: float | None
    direction: str
    severity: str
    is_build_fix: bool
    is_hard_break: bool


@dataclass(frozen=True)
class SlotPriority:
    """Per-slot equipment priority for filter generation."""
    slot: ProductSlot
    defense_layer: DefenseLayer
    base_tiers: Dict[str, BaseTier]  # base_type -> tier
    min_item_level: int
    min_unidentified_tier: int
    required_sockets: int
    required_links: int
    defensive_floors: Dict[str, float]  # e.g., {"BaseEnergyShield": 150}
    preferred_implicits: list[str]
    blocked_bases: frozenset[str]
    # FILTER-08B (empty for the legacy resolver): base quality tiers pin the profile's item-level gate, while
    # `base_tiers` (build tiers) decide inclusion; `decisions` carry per-base provenance for explanations.
    quality_tiers: Dict[str, BaseTier] = field(default_factory=dict)
    decisions: Dict[str, Any] = field(default_factory=dict)
    class_reasons: tuple = ()
    coverage: Any = None


@dataclass(frozen=True)
class RuleTemplate:
    """Template for generating a filter rule."""
    name: str
    category: str  # PROTECTIVE, BUILD_WEAPON, BUILD_DEFENSE, etc.
    condition_lines: list[str]  # Lines like 'Class "Body Armours"'
    action_lines: list[str]     # Lines like 'SetFontSize 34'
    continue_: bool = False
    comment: str = ""

    def render(self, params: Dict[str, any]) -> list[str]:
        """Render rule with parameter substitution."""
        lines = []
        if self.comment:
            lines.append(f"# {self.comment}")

        # Determine block type
        block_type = "Show"
        if "Hide" in self.name or "hide" in self.name.lower():
            block_type = "Hide"
        elif "Minimal" in self.name:
            block_type = "Minimal"

        lines.append(block_type)

        # Substitute conditions
        for cond in self.condition_lines:
            rendered = cond.format(**params)
            lines.append(f"\t{rendered}")

        # Substitute actions
        for action in self.action_lines:
            rendered = action.format(**params)
            lines.append(f"\t{rendered}")

        if self.continue_:
            lines.append("\tContinue")

        lines.append("")  # Blank line after rule
        return lines
