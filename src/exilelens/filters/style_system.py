"""Visual system V4 for the native item filter: importance x family x treatment x theme motif, plus explicit beam and sound ladders.

Independent layers (the hierarchy is the same in every theme; a theme changes personality, never importance or visibility):

  IMPORTANCE  how much attention an item deserves (MYTHIC .. LOW)   -> font size, plate alpha, minimap icon size
  FAMILY      what kind of thing it is                                -> hue family and minimap shape
  TREATMENT   how the label is BUILT (the silhouette)                 -> white/red apex, solid bar, enamel, dark plate, outline
  MOTIF       the theme: ground, frame metal, text glow, ash, hero    -> personality; never importance, family identity or visibility
  BEAM / SOUND explicit per-role tables (BEAM_POLICY, SOUND_POLICY)    -> persistent / temporary / none; a small native sound vocabulary

V4 (after in-game feedback on V3: "works, but not epic; families look samey"):
  * the iconic white/red label is the real thing: white plate, VIVID red text, red (MYTHIC) or theme-metal (Divine) frame; it is reserved for
    the apex currency (MYTHIC names and the Divine tier) and nothing else;
  * the silhouette carries the family, not only the hue: premium currency is a solid gold bar with black ink, special drops a solid rose bar,
    build gear and gems are enamel (dark plate, coloured text), regular currency a dark plate in the theme's frame metal, craft / trade outlines;
  * every theme has an opinionated motif (frame metal, text glow, ash, hero palette, hero pillar colour and shape) instead of a tint;
  * MYTHIC and the Divine tier keep a PERSISTENT beam; enhanced currency, specials, uniques and top waystones get a temporary one; nothing
    else beams;
  * sounds form a vocabulary of built-in ids (see SOUND_WORDS), not a volume knob on one id.

Only documented native actions come out of ``native_style``: SetFontSize (<= 45), SetTextColor, SetBorderColor, SetBackgroundColor,
MinimapIcon (size 0-2, documented colours and shapes), PlayEffect (documented colours, optional Temp) and PlayAlertSound (id 1-16, volume
0-300). Visibility is never decided here.
"""
from __future__ import annotations

import colorsys
from dataclasses import dataclass

from exilelens.filters.profiles import BaseTier, FilterThemeName

LEVELS = ("MYTHIC", "HIGH", "VALUABLE", "UTILITY", "LOW")

# level -> label mass. `bg_alpha` / `border_alpha` are native 0-255 alphas. Beams and sounds are NOT level properties any more: a level says
# how big a label is; whether it beams or sounds is a deliberate per-role decision (BEAM_POLICY / SOUND_POLICY below).
LEVEL_POLICY: dict[str, dict] = {
    "MYTHIC":   {"font": 45, "bg_alpha": 255, "border_alpha": 255, "icon_size": 0},
    "HIGH":     {"font": 41, "bg_alpha": 255, "border_alpha": 255, "icon_size": 1},
    "VALUABLE": {"font": 36, "bg_alpha": 248, "border_alpha": 255, "icon_size": 2},
    "UTILITY":  {"font": 30, "bg_alpha": 238, "border_alpha": 240, "icon_size": None},
    "LOW":      {"font": 25, "bg_alpha": 226, "border_alpha": 210, "icon_size": None},
}

# -- beams -------------------------------------------------------------------------------------------------------------------------------
# GGG item-filter reference: `PlayEffect <colour>` is a PERMANENT beam (it stays while the item lies on the ground); `PlayEffect <colour> Temp`
# only appears while the item drops. Persistent beams are reserved for loot that must never be lost in a cluster.
PERSISTENT, TEMP = "persistent", "temp"
BEAM_POLICY: dict[str, str] = {
    "hero": PERSISTENT,              # MYTHIC: the theme's own pillar colour (Grade.hero_effect), exclusive inside the theme
    "currency_premium": PERSISTENT,  # Divine tier: a white pillar for the white label (DIVINE_EFFECT)
    "quest": PERSISTENT,             # safety: a quest item must not be walked past
    "premium_currency": TEMP,        # enhanced (Greater / Perfect) currency
    "special": TEMP,                 # omens, pinnacle keys, map fragments
    "unique": TEMP,                  # the game's unique colour; temporary because most uniques are not chase items
    "waystone_high": TEMP,           # tier 15+ waystones: the endgame engine
}
DIVINE_EFFECT = "White"

# -- sounds ------------------------------------------------------------------------------------------------------------------------------
# A compact vocabulary of BUILT-IN alert ids (PlayAlertSound 1-16, volume 0-300; GGG reference). The id is the WORD (what kind of drop), the
# volume is the EMPHASIS inside a word. The id meanings follow the convention of the most widely used PoE2 community filter (research ID
# 'community filter A', 0.10.4: 6 = apex / S tier, 1 = top currency, 2 = currency, 3 = uniques / exotic / quest, 4 = maps, 5 = high maps), so a player who knows that
# convention recognises the words immediately. The timbre of each id is the game's; it is NOT verified by this project and must be heard.
SOUND_WORDS: dict[str, int] = {"APEX": 6, "PREMIUM": 1, "CURRENCY": 2, "SPECIAL": 3, "ENDGAME": 4, "ENDGAME_HIGH": 5}
SOUND_POLICY: dict[str, tuple[str, int]] = {
    "hero": ("APEX", 300),               # MYTHIC: the loudest event in the filter, and the only one at 300
    "currency_premium": ("APEX", 230),   # Divine tier: same word as MYTHIC (white label <-> sound 6), clearly quieter
    "premium_currency": ("PREMIUM", 210),
    "special": ("SPECIAL", 190),
    "unique": ("SPECIAL", 160),
    "quest": ("SPECIAL", 150),           # safety
    "waystone_high": ("ENDGAME_HIGH", 170),
    "tablet": ("ENDGAME", 120),
    "currency_valuable": ("CURRENCY", 110),   # Chaos / Exalted / Regal / Vaal / Gemcutter's: a soft currency word (profiles may mute it)
}
# Roles whose alert is part of the protective rules and sounds in every profile; the rest follow the profile's play_alert_sounds switch.
ALWAYS_SOUND_ROLES = frozenset(role for role in SOUND_POLICY if role != "currency_valuable")
# Noise floor: Hide rules carry this action so hidden loot makes no drop sound and the alert words stand out. GGG documents the bare flag;
# the `True` form is the one the most widely used live PoE2 community filter (0.10.4) uses on its hide layers, i.e. the form the PoE2 client is known to load.
HIDDEN_DROP_SOUND = "DisableDropSound True"


@dataclass(frozen=True)
class RoleDesign:
    family: str
    level: str                      # default level; build roles override it by tier (see TIER_LEVELS)
    variant: str                    # white_red | solid | enamel | dark | outline
    description: str
    text_family: str | None = None  # outline text borrows this family's colour (frame and plate keep `family`): a rarity identity hint

    @property
    def weight(self) -> str:        # kept for older callers / documentation
        return self.level.lower()

    @property
    def font_size(self) -> int:
        return LEVEL_POLICY[self.level]["font"]


TREATMENTS = {
    "white_red": "the apex label: white plate, vivid red text, red / theme-metal frame (MYTHIC and the Divine tier only)",
    "solid": "a solid colour bar with black ink (premium currency gold, special rose): loud, unmistakably not a dark plate",
    "enamel": "near-black plate with COLOURED text and a coloured frame (build gear, uniques, jewels, waystones, strong craft bases)",
    "dark": "a tinted dark plate with light text, framed in the theme's metal (regular currency and other protected classes)",
    "outline": "near-ground plate with a bright coloured edge (craft / trade substrates, gems, augments, charms, tablets, minor currency)",
    "slate": "a neutral grey stone plate with coloured text and frame: the unrevealed item (unidentified tiers), unlike every dark plate",
}

ROLE_DESIGNS: dict[str, RoleDesign] = {
    # --- currency: an explicit, maintainable loot-importance ladder (names in currency_tiers.py); not a price claim
    "hero": RoleDesign("currency", "MYTHIC", "white_red", "MYTHIC currency: white plate, vivid red text and frame, 45 pt, persistent theme pillar, sound 6 @ 300"),
    "currency_premium": RoleDesign("currency", "HIGH", "white_red", "Divine tier: white plate, red text, theme-metal frame, persistent white pillar, sound 6 @ 230"),
    "premium_currency": RoleDesign("currency", "HIGH", "solid", "Enhanced currency: solid gold bar, black ink, Temp beam, sound 1"),
    "currency_valuable": RoleDesign("currency", "VALUABLE", "dark", "Valuable currency: heavy gold-tinted plate in the theme's frame metal, small icon, soft sound 2"),
    "crafting_currency": RoleDesign("craft", "VALUABLE", "dark", "Named crafting currency: sage plate"),
    "currency": RoleDesign("currency", "UTILITY", "dark", "General currency: 30 pt, silent"),
    "currency_low": RoleDesign("currency", "LOW", "outline", "Shards and scraps: 25 pt outline, quiet"),
    # --- special classes / chase / progression
    "special": RoleDesign("special", "HIGH", "solid", "Omen / key / map fragment: solid rose bar, Temp beam, sound 3"),
    "socketable": RoleDesign("socketable", "UTILITY", "outline", "Augment / rune: teal outline"),
    "unique": RoleDesign("unique", "HIGH", "enamel", "Unique: black plate with the game's unique orange as text and frame (less mass than V3), Temp beam"),
    "quest": RoleDesign("quest", "VALUABLE", "dark", "Quest item: green plate, persistent green beam (safety)"),
    "waystone_high": RoleDesign("endgame", "HIGH", "enamel", "Waystone tier 15+: violet enamel, Temp beam, hexagon, sound 5"),
    "waystone_mid": RoleDesign("endgame", "VALUABLE", "enamel", "Waystone tier 11-14: violet enamel, small hexagon"),
    "waystone": RoleDesign("endgame", "UTILITY", "enamel", "Waystone: violet enamel (every waystone tier shares the look; the tier sets the size)"),
    "tablet": RoleDesign("tablet", "VALUABLE", "outline", "Tablet: lilac outline with a bright edge, small hexagon, no beam, sound 4 (class-wide: no tier to justify HIGH)"),
    "high_unid": RoleDesign("unidentified", "UTILITY", "slate", "High unidentified tier: grey slate plate, rare-item yellow text and frame, quiet: no beam / alert"),
    "jewel": RoleDesign("jewel", "VALUABLE", "enamel", "Jewel: emerald enamel, small icon"),
    "charm": RoleDesign("jewel", "UTILITY", "outline", "Charm: emerald outline, quiet"),
    "gem": RoleDesign("gem", "UTILITY", "outline", "Uncut skill / support / spirit gem: periwinkle outline (build armour is blue ENAMEL)"),
    # --- build-aware (level follows the base tier; opportunities say "inspect me", not "jackpot")
    "build_weapon": RoleDesign("build_weapon", "VALUABLE", "enamel", "Build weapon candidate: cyan enamel"),
    "fallback_weapon": RoleDesign("build_weapon", "LOW", "outline", "Unmapped skill: broad weapon candidate without a build alert"),
    "build_defense": RoleDesign("build_armour", "VALUABLE", "enamel", "Build armour candidate: blue enamel"),
    "build_jewellery": RoleDesign("jewellery", "VALUABLE", "enamel", "Build jewellery candidate: orchid enamel"),
    "build_offhand": RoleDesign("build_weapon", "VALUABLE", "enamel", "Build offhand candidate: cyan enamel"),
    # --- craft / trade heuristics
    "crafting_base": RoleDesign("craft", "UTILITY", "outline", "Quality crafting base: sage outline"),
    "craft_premium": RoleDesign("craft", "VALUABLE", "enamel", "Premium crafting substrate: sage enamel (sage text and frame), small moon icon"),
    "craft_relevant": RoleDesign("craft", "UTILITY", "outline", "Relevant crafting substrate (the Utility Belt reference): sage outline, quiet"),
    "trade_weapon": RoleDesign("trade", "UTILITY", "outline", "Heuristic trade weapon: copper outline (no price claim)"),
    "trade_armour": RoleDesign("trade", "UTILITY", "outline", "Heuristic trade armour: copper outline"),
    "trade_jewellery": RoleDesign("trade", "UTILITY", "outline", "Heuristic trade jewellery: copper outline"),
    "trade_craft": RoleDesign("craft", "LOW", "outline", "Quality trade crafting candidate: quiet"),
    "trade": RoleDesign("trade", "UTILITY", "outline", "Heuristic trade candidate: copper outline"),
    # --- profile system V2: generic equipment (the safety baseline lanes) and the unknown-item catch-all
    "generic": RoleDesign("generic", "UTILITY", "outline", "Generic equipment on a known base: grey outline (QUIET: smaller, no effects)"),
    # a generic RARE that is shown: the same restrained grey outline, text in the unidentified / rare yellow so the item keeps its Rare identity;
    # it never beams, sounds or carries an icon, so BUILD / CRAFT / trade rules stay louder (QUIET is exactly `generic`)
    "generic_rare": RoleDesign("generic", "UTILITY", "outline", "Generic Rare on a known base: grey outline, rare-yellow text, quiet",
                               text_family="unidentified"),
    "unknown": RoleDesign("unknown", "VALUABLE", "outline", "Unclassified item (unknown base / new class): magenta outline, small white square icon, "
                                                             "recognisable, not a jackpot"),
}

# Build roles: the base tier chooses the level.
TIER_LEVELS: dict[str, dict[BaseTier, str]] = {
    "build_weapon": {BaseTier.T1: "VALUABLE", BaseTier.T2: "UTILITY", BaseTier.T3: "UTILITY", BaseTier.T4: "LOW"},
    "build_offhand": {BaseTier.T1: "VALUABLE", BaseTier.T2: "UTILITY", BaseTier.T3: "UTILITY", BaseTier.T4: "LOW"},
    "build_defense": {BaseTier.T1: "VALUABLE", BaseTier.T2: "UTILITY", BaseTier.T3: "UTILITY", BaseTier.T4: "LOW"},
    "build_jewellery": {BaseTier.T1: "VALUABLE", BaseTier.T2: "UTILITY", BaseTier.T3: "UTILITY", BaseTier.T4: "LOW"},
}

# Family anchor: (hue degrees, saturation, lightness) of the vivid accent before the theme. Hues are spread so families stay separable; near
# neighbours additionally differ in treatment (currency dark vs unique enamel, special solid vs jewellery enamel, craft vs jewel).
FAMILY_BASE: dict[str, tuple[float, float, float]] = {
    "currency": (44, .86, .58), "unidentified": (62, .70, .60), "unique": (26, .90, .56), "trade": (2, .50, .60),
    "special": (340, .70, .64), "jewellery": (312, .52, .68), "endgame": (270, .62, .68), "tablet": (292, .44, .76),
    "build_armour": (216, .70, .64), "build_weapon": (188, .78, .54), "socketable": (172, .56, .58), "jewel": (150, .58, .56),
    "quest": (128, .56, .58), "craft": (92, .46, .58), "gem": (236, .48, .72),
    "generic": (205, .16, .66), "unknown": (326, .74, .70),
}

# Native colour names for PlayEffect / MinimapIcon per family (constant across themes for recognition; see _native_colour for the one
# exception: the theme's MYTHIC pillar colour is exclusive inside its theme).
FAMILY_NATIVE_COLOR = {
    "currency": "Yellow", "unique": "Orange", "trade": "Brown", "unidentified": "Yellow", "special": "Pink", "jewellery": "Pink",
    "endgame": "Purple", "tablet": "Purple", "build_armour": "Blue", "build_weapon": "Cyan", "socketable": "Cyan", "jewel": "Green",
    "quest": "Green", "craft": "Green", "gem": "Blue", "generic": "Grey", "unknown": "White",
}
# The replacement when a family colour equals the theme's MYTHIC pillar colour (so the pillar colour means MYTHIC and nothing else).
COLOUR_FALLBACK = {"Yellow": "Orange", "Orange": "Red", "Green": "Cyan", "Red": "Pink", "Cyan": "Blue", "Purple": "Pink", "Pink": "Purple",
                   "Blue": "Cyan"}
# Native minimap shape per family (constant across themes): the shape says WHAT it is, the size says HOW MUCH.
FAMILY_SHAPE = {
    "currency": "Diamond", "unique": "Pentagon", "trade": "Square", "unidentified": "Cross", "special": "Kite", "jewellery": "Circle",
    "endgame": "Hexagon", "tablet": "Hexagon", "build_armour": "Square", "build_weapon": "Triangle", "socketable": "Moon", "jewel": "Raindrop",
    "quest": "UpsideDownHouse", "craft": "Moon", "gem": "Kite", "generic": "Square", "unknown": "Square",
}
DIVINE_ICON_SHAPE = "Diamond"

# The white / red apex: (plate, text, MYTHIC frame) per theme. The text is a VIVID red (V3's 7 : 1 floor drove it to maroon and the label lost
# its iconic read); at 41-45 pt it is large text, so the floor is 5 : 1 (WCAG AA for normal text is 4.5 : 1). Divine uses the same plate washed
# 6 % toward the theme's frame metal, the same red text and the theme metal as its frame.
HERO_RED: dict[FilterThemeName, tuple[str, str, str]] = {
    FilterThemeName.VOID_GOLD: ("#fffaee", "#cf0f1e", "#b00d1a"),          # warm white, crimson, crimson frame (gold on Divine)
    FilterThemeName.BLOOD_SIGIL: ("#fff4f1", "#d2000e", "#80000e"),        # bone white, blood red, black-blood frame
    FilterThemeName.ARCANE_PRISM: ("#f5f8ff", "#c90f3c", "#9b0b2e"),      # pearl, arcane magenta-red, ruby frame (ice on Divine)
    FilterThemeName.VERDANT_RELIC: ("#fbf9ea", "#c80c14", "#951013"),      # parchment, scarlet, dark scarlet frame (jade on Divine)
    FilterThemeName.EMBERFORGE: ("#fff6e6", "#cf1c00", "#a01600"),         # hot white, ember red, forged red frame (ember on Divine)
    FilterThemeName.ABYSSAL_COVENANT: ("#f4f2fb", "#bd0d3c", "#3a0d4e"),  # cold white, occult crimson, black-violet frame
    FilterThemeName.ETERNAL_EMPIRE: ("#fbf6e8", "#bc0a18", "#8a0d17"),     # marble, imperial red, deep red frame (bronze on Divine)
    FilterThemeName.WRAECLAST_ASHES: ("#f1f1ed", "#c0160c", "#2c2a28"),    # ash white, dried-blood red, charcoal frame
}
WHITE_RED_TEXT_FLOOR = 5.0


@dataclass(frozen=True)
class Grade:
    """A theme's MOTIF: it never changes level, family identity or visibility."""
    ground: str          # darkest plate base
    ink: str             # text on solid plates
    bone: str            # light text on dark plates
    cast_hue: float      # hue the palette leans toward
    cast: float          # how far (0-.3)
    sat: float           # saturation multiplier
    light: float         # lightness multiplier
    hero_effect: str     # MYTHIC pillar colour (exclusive inside the theme)
    hero_shape: str      # MYTHIC minimap shape
    motif: str
    tint: float = .30    # how far dark plates lean toward the theme hue
    frame: str = "#c9a24a"   # the theme's METAL: frames of dark plates, Divine's frame, the wash on the Divine plate
    frame_mix: float = .45   # how far dark-plate frames lean toward the metal
    glow: bool = False       # dark-plate text takes the family colour (neon) instead of bone
    ash: float = 0.0         # UTILITY / LOW text and plates lose this share of their saturation; frames keep the family colour
    name: str = ""           # one-word motif name
    field: float = .30       # the theme FIELD: how far near-ground plates (enamel / outline) lean to the theme colour; text and frame keep the family


GRADES: dict[FilterThemeName, Grade] = {
    FilterThemeName.VOID_GOLD: Grade("#09080c", "#120d05", "#fff6dc", 46, .10, 1.00, 1.00, "Yellow", "Star",
                                     "Gilded void: black plates, every frame in hot gold, ivory text, a gold MYTHIC pillar", .22,
                                     frame="#e0aa2a", frame_mix=.60, name="GILDED", field=0.08),
    FilterThemeName.BLOOD_SIGIL: Grade("#1a070c", "#1c0a0f", "#ffe7e2", 352, .18, 1.06, .97, "Red", "Cross",
                                       "Blood seal: wine-black plates, crimson frames, bone text, a red MYTHIC pillar", .30,
                                       frame="#c0172a", frame_mix=.55, name="BLOOD", field=0.62),
    FilterThemeName.ARCANE_PRISM: Grade("#06102a", "#06141f", "#eaffff", 200, .16, 1.12, 1.04, "Cyan", "Kite",
                                        "Arcane prism: deep navy plates, neon family-coloured text, ice frames, a cyan MYTHIC pillar", .40,
                                        frame="#58c8f0", frame_mix=.40, glow=True, name="PRISM", field=0.68),
    FilterThemeName.VERDANT_RELIC: Grade("#07160d", "#0b160a", "#f0ffe0", 118, .16, .94, .99, "Green", "Hexagon",
                                         "Verdant relic: forest-black plates, jade frames, pale sage text, a green MYTHIC pillar", .38,
                                         frame="#5fae6e", frame_mix=.45, name="RELIC", field=0.62),
    FilterThemeName.EMBERFORGE: Grade("#1d0f08", "#1d0e04", "#fff0d8", 24, .18, 1.08, 1.00, "Orange", "Triangle",
                                      "Emberforge: charcoal-brown plates, ember frames, white-hot text, an orange MYTHIC pillar", .32,
                                      frame="#f07818", frame_mix=.55, name="FORGE", field=0.55),
    FilterThemeName.ABYSSAL_COVENANT: Grade("#0a0614", "#140a1f", "#f6e9ff", 276, .20, 1.02, 1.00, "Purple", "Moon",
                                            "Abyssal covenant: near-black indigo plates, violet frames, orchid-white text, a purple pillar", .30,
                                            frame="#9a5cf0", frame_mix=.40, name="OCCULT", field=0.68),
    FilterThemeName.ETERNAL_EMPIRE: Grade("#211b14", "#1a140c", "#fbf1d8", 40, .10, .86, 1.04, "Yellow", "Pentagon",
                                          "Eternal empire: warm marble-bronze plates, bronze frames, ivory text, an imperial gold pillar", .25,
                                          frame="#c49a48", frame_mix=.50, name="IMPERIAL", field=0.48),
    FilterThemeName.WRAECLAST_ASHES: Grade("#15191c", "#0e1316", "#eef3f2", 205, .20, .70, 1.02, "Red", "Circle",
                                           "Wraeclast ashes: slate plates and bone frames; ordinary loot turns to ash, only what matters keeps colour",
                                           .30, frame="#cfc8ba", frame_mix=.50, ash=.55, name="ASH", field=0.45),
}


def _hex(rgb: tuple[int, int, int]) -> str:
    return "#%02x%02x%02x" % rgb


def _rgb(hex_color: str) -> tuple[int, int, int]:
    return tuple(int(hex_color[i:i + 2], 16) for i in (1, 3, 5))


def _from_hls(h: float, l: float, s: float) -> tuple[int, int, int]:
    r, g, b = colorsys.hls_to_rgb((h % 360) / 360.0, max(0.0, min(1.0, l)), max(0.0, min(1.0, s)))
    return round(r * 255), round(g * 255), round(b * 255)


def _to_hls(rgb: tuple[int, int, int]) -> tuple[float, float, float]:
    h, l, s = colorsys.rgb_to_hls(*(c / 255 for c in rgb))
    return h * 360, l, s


def _blend(a: tuple[int, int, int], b: tuple[int, int, int], amount: float) -> tuple[int, int, int]:
    return tuple(round(x * (1 - amount) + y * amount) for x, y in zip(a, b))


def _luminance(rgb: tuple[int, int, int]) -> float:
    def channel(c: int) -> float:
        v = c / 255
        return v / 12.92 if v <= .03928 else ((v + .055) / 1.055) ** 2.4
    r, g, b = (channel(c) for c in rgb)
    return .2126 * r + .7152 * g + .0722 * b


def contrast(a: tuple[int, int, int], b: tuple[int, int, int]) -> float:
    la, lb = sorted((_luminance(a), _luminance(b)), reverse=True)
    return (la + .05) / (lb + .05)


def _ensure_contrast(fg: tuple[int, int, int], bg: tuple[int, int, int], minimum: float) -> tuple[int, int, int]:
    """Push the colour toward white or black (whichever the plate allows) until it reaches the required contrast ratio."""
    target = (255, 255, 255) if _luminance(bg) < .3 else (0, 0, 0)
    colour = fg
    for step in range(1, 41):
        if contrast(colour, bg) >= minimum:
            break
        colour = _blend(fg, target, step / 40)
    return colour


SOLID_LUMINANCE = (.36, .44)   # a solid bar: bright enough for 7 : 1 black ink, below the white-plate luminance (.55) with margin


def _solid_plate(hue: float, sat: float, ink: tuple[int, int, int], minimum: float) -> tuple[int, int, int]:
    """A saturated colour bar that black ink reads on: the darkest lightness that holds the contrast and reaches the luminance window."""
    for step in range(100):
        colour = _from_hls(hue, .30 + .006 * step, sat)
        if contrast(ink, colour) >= minimum and _luminance(colour) >= SOLID_LUMINANCE[0]:
            return colour
    return colour


# Currency on a dark plate reads gold-on-black (its text leans to the family gold), other dark plates keep bone text.
DARK_TEXT_TINT = {"currency": .40}
# The ash motif greys ordinary loot; craft substrates keep their colour so they still read as craft-worthy (FILTER-09).
ASH_EXEMPT = frozenset({"craft"})
# Coloured text on a dark plate: 7 : 1 opaque plus headroom, so it still clears 6.5 : 1 when the plate's alpha lets bright fire through.
TEXT_ON_DARK = 7.8
MAX_HUE_SHIFT = 14.0   # degrees; keeps every family inside its own colour name in every theme


def _accent(family: str, grade: Grade, level: str = "HIGH") -> tuple[int, int, int]:
    hue, sat, light = FAMILY_BASE[family]
    delta = ((grade.cast_hue - hue + 180) % 360) - 180
    shift = max(-MAX_HUE_SHIFT, min(MAX_HUE_SHIFT, delta * grade.cast))     # a theme leans, it never turns gold into green
    saturation = min(.95, sat * grade.sat)
    if level in ("UTILITY", "LOW"):
        saturation *= 1 - (0.0 if family in ASH_EXEMPT else grade.ash)
    return _from_hls(hue + shift, min(.95, light * grade.light), saturation)


def family_accent(theme: FilterThemeName, family: str) -> str:
    return _hex(_accent(family, GRADES[theme]))


def _rgba(rgb: tuple[int, int, int], alpha: int) -> str:
    return " ".join(map(str, (*rgb, alpha)))


# Resolved palette per theme, keyed like the old THEME_FAMILIES (+ ground) for the dashboard badges.
THEME_FAMILIES: dict[FilterThemeName, dict[str, str]] = {
    theme: {**{family: family_accent(theme, family) for family in FAMILY_BASE}, "hero": HERO_RED[theme][1], "ground": grade.ground}
    for theme, grade in GRADES.items()
}


def level_for(role: str, tier: BaseTier | None) -> str:
    table = TIER_LEVELS.get(role)
    if table is not None and tier is not None:
        return table.get(tier, "LOW")
    return ROLE_DESIGNS[role].level


def _native_colour(grade: Grade, family: str) -> str:
    colour = FAMILY_NATIVE_COLOR[family]
    return COLOUR_FALLBACK.get(colour, colour) if colour == grade.hero_effect else colour


def beam_for(theme_name: FilterThemeName, role: str) -> str | None:
    """The PlayEffect value of a role in a theme, or None (no beam)."""
    kind = BEAM_POLICY.get(role)
    if kind is None:
        return None
    grade = GRADES[theme_name]
    if role == "hero":
        colour = grade.hero_effect
    elif role == "currency_premium":
        colour = DIVINE_EFFECT
    else:
        colour = _native_colour(grade, ROLE_DESIGNS[role].family)
    return colour if kind == PERSISTENT else f"{colour} Temp"


def sound_for(role: str) -> tuple[int, int] | None:
    entry = SOUND_POLICY.get(role)
    return None if entry is None else (SOUND_WORDS[entry[0]], entry[1])


def _white_red(theme_name: FilterThemeName, grade: Grade, level: str):
    plate_hex, text_hex, frame_hex = HERO_RED[theme_name]
    plate, text = _rgb(plate_hex), _rgb(text_hex)
    if level == "MYTHIC":
        edge = _rgb(frame_hex)
    else:                                   # the Divine tier: the same icon dressed in the theme's metal
        plate = _blend(plate, _rgb(grade.frame), .06)
        edge = _rgb(grade.frame)
    foreground = _ensure_contrast(text, plate, WHITE_RED_TEXT_FLOOR)
    border = _ensure_contrast(edge, plate, 3.0)
    return plate, foreground, border


# Profile-system states (profile_policy): the V4 treatment of a role under SHOW+ / SHOW / QUIET. HIDE has no style.
QUIET_LEVEL = {"HIGH": "VALUABLE", "VALUABLE": "UTILITY", "UTILITY": "LOW", "LOW": "LOW"}
ATTENTION_STATES = ("SHOW+", "SHOW", "QUIET")


def native_style(theme_name: FilterThemeName, role: str, tier: BaseTier | None = None, state: str = "SHOW+") -> dict[str, str | int]:
    """Resolve one semantic role (+ optional base tier) to documented native actions only.

    ``state``: SHOW+ = the role's full V4 treatment; SHOW = same label, no sound and no beam (the minimap icon stays); QUIET = one V4
    importance level lower and no sound, no beam, no minimap icon. MYTHIC and the white / red roles exist only as SHOW+ (the matrix never
    gives them another state)."""
    if state not in ATTENTION_STATES:
        raise ValueError(f"no style for state {state!r}")
    if role == "generic_rare" and state == "QUIET":
        role = "generic"                                # QUIET generic Rares were already styled (grey) and stay exactly so
    design = ROLE_DESIGNS[role]
    grade = GRADES[theme_name]
    level = level_for(role, tier)
    if state != "SHOW+" and (level == "MYTHIC" or design.variant == "white_red"):
        raise ValueError(f"role {role!r} is always SHOW+")
    if state == "QUIET":
        level = QUIET_LEVEL[level]
    policy = LEVEL_POLICY[level]
    family = design.family
    accent = _accent(family, grade, level)
    # theme mood lives in the plate BASE; the family accent still dominates, so categories stay recognisable
    ground = _blend(_rgb(grade.ground), _from_hls(grade.cast_hue, .14, .55), grade.tint)
    field = _blend(_rgb(grade.ground), _from_hls(grade.cast_hue, .16, .62), grade.field)   # the colour of the screen behind the families
    ink, bone, frame = _rgb(grade.ink), _rgb(grade.bone), _rgb(grade.frame)
    hue, light, sat = _to_hls(accent)
    edge_sat = _to_hls(_accent(family, grade))[2]     # frames keep the family colour even where the ash motif greys the text
    variant = design.variant
    if variant == "white_red":
        background, foreground, border = _white_red(theme_name, grade, level)
    elif variant == "solid":
        # a saturated bar with black ink; kept below the white-plate luminance so it never reads as (or counts as) a white label.
        # A bar is the family's own colour: the theme may lean it by at most 30 % of its shift (a gold bar never turns olive or orange).
        base_hue = FAMILY_BASE[family][0]
        hue = base_hue + (((hue - base_hue + 180) % 360) - 180) * .3
        background = _solid_plate(hue, min(.95, FAMILY_BASE[family][1] * 1.05), ink, 7.0)
        foreground = _ensure_contrast(ink, background, 7.0)
        border = _from_hls(hue, .86, min(.95, sat))
    elif variant == "enamel":
        mass = {"HIGH": .14, "VALUABLE": .11, "UTILITY": .08, "LOW": .06}[level]
        background = _blend(field, accent, mass)
        text_light = {"HIGH": .76, "VALUABLE": .74, "UTILITY": .72, "LOW": .62}[level]
        foreground = _ensure_contrast(_from_hls(hue, text_light, min(.95, sat * 1.1)), background, TEXT_ON_DARK)
        border = _from_hls(hue, {"HIGH": .62, "VALUABLE": .60, "UTILITY": .52, "LOW": .42}[level], min(.95, edge_sat * 1.1))
    elif variant == "slate":
        background = _from_hls(_to_hls(ground)[0], .27, .06)
        foreground = _ensure_contrast(_from_hls(hue, .80, min(.95, sat * 1.1)), background, TEXT_ON_DARK)
        border = _from_hls(hue, .62, min(.95, edge_sat * 1.1))
    elif variant == "outline":
        background = _blend(field, accent, .05)
        border = _from_hls(hue, {"HIGH": .72, "VALUABLE": .66, "UTILITY": .60, "LOW": .46}[level], min(.95, edge_sat * 1.05))
        text_accent = _accent(design.text_family, grade, level) if design.text_family else accent
        foreground = _ensure_contrast(_blend(bone, text_accent, .55), background, TEXT_ON_DARK)
    else:  # dark plate: tinted mass, light text, framed in the theme's metal
        mass = {"HIGH": .50, "VALUABLE": .36, "UTILITY": .09, "LOW": .07}[level]   # V4: utility is near-black, valuable is heavy
        background = _blend(ground, accent, mass)
        while mass > .05 and contrast(bone, background) < 7.5:        # heavy plate, but never so bright that light text loses
            mass -= .02
            background = _blend(ground, accent, mass)
        family_edge = _from_hls(hue, .66 if level in ("HIGH", "VALUABLE") else .54, min(.95, edge_sat * 1.1))
        border = _blend(family_edge, frame, grade.frame_mix)
        text = _from_hls(hue, .80, min(.95, sat * 1.1)) if grade.glow else _blend(bone, accent, DARK_TEXT_TINT.get(family, .16))
        foreground = _ensure_contrast(text, background, TEXT_ON_DARK if grade.glow else 7.0)
    if level == "LOW":
        foreground = _ensure_contrast(_blend(bone, accent, .5), background, 4.5)

    style: dict[str, str | int] = {
        "font_size": policy["font"],
        "text_color": _rgba(foreground, 255),
        "border_color": _rgba(border, policy["border_alpha"]),
        "bg_color": _rgba(background, policy["bg_alpha"]),
        "level": level,
        "family": family,
        "variant": variant,
        "state": state,
    }
    if state == "QUIET":
        return style                                   # no beam, no sound, no minimap icon
    if level == "MYTHIC":
        style["minimap_icon"] = f"0 {grade.hero_effect} {grade.hero_shape}"
    elif role == "currency_premium":
        style["minimap_icon"] = f"0 {DIVINE_EFFECT} {DIVINE_ICON_SHAPE}"
    elif policy["icon_size"] is not None:
        # an ordinary unique at SHOW keeps its plaque and colour but only the smallest native icon (the large one is the jackpot signal)
        size = 2 if (role == "unique" and state == "SHOW") else policy["icon_size"]
        style["minimap_icon"] = f"{size} {_native_colour(grade, family)} {FAMILY_SHAPE[family]}"
    if state == "SHOW":
        return style                                   # label + icon, no alert sound and no beam
    effect = beam_for(theme_name, role)
    if effect is not None:
        style["play_effect"] = effect
    sound = sound_for(role)
    if sound is not None:
        style["sound"] = f"{sound[0]} {sound[1]}"
    return style
