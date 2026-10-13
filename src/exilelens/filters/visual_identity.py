"""Visual system V4 QA helpers: family separation, theme identity and the sound / beam matrix. QA ONLY: nothing here feeds generation.

* ``separating_axes`` counts the independent visual axes on which two resolved labels differ (treatment / silhouette, text hue, text chroma,
  plate, frame, size, minimap shape, beam, sound word). "Stronger family differentiation" is asserted as a minimum number of axes per pair.
* ``theme_distance`` is the mean RGB distance between two themes over a fixed set of probe roles (how different two themes LOOK).
* ``policy_matrix`` is the per-role beam / sound / icon / treatment table the documentation and the artifacts are generated from.
"""
from __future__ import annotations

import itertools
import math

from exilelens.filters.profiles import BaseTier, FilterThemeName
from exilelens.filters.style_system import (ALWAYS_SOUND_ROLES, BEAM_POLICY, GRADES, ROLE_DESIGNS, SOUND_POLICY, TIER_LEVELS, _to_hls,
                                            native_style)

# One representative role (and tier) per family the V4 brief names.
FAMILY_PROBES: dict[str, tuple[str, BaseTier | None]] = {
    "mythic": ("hero", None), "divine": ("currency_premium", None), "premium_currency": ("premium_currency", None),
    "regular_currency": ("currency_valuable", None), "utility_currency": ("currency", None), "special": ("special", None),
    "build_gear": ("build_weapon", BaseTier.T1), "build_armour": ("build_defense", BaseTier.T1), "craft_base": ("craft_relevant", None),
    "craft_premium": ("craft_premium", None), "trade_base": ("trade_armour", None), "unique": ("unique", None), "gem": ("gem", None),
    "tablet": ("tablet", None), "waystone_high": ("waystone_high", None), "waystone_mid": ("waystone_mid", None),
    "waystone": ("waystone", None), "jewel": ("jewel", None), "charm": ("charm", None), "unidentified": ("high_unid", None),
}
# Probe families that the ash motif deliberately greys (their text); in an ash theme a pair of them may share everything but the frame.
ASHED = frozenset({"trade_base", "gem", "charm", "utility_currency", "unidentified", "waystone"})


def _rgb(text: str) -> tuple[int, int, int]:
    return tuple(int(v) for v in text.split()[:3])


def _hue_gap(a: float, b: float) -> float:
    d = abs(a - b)
    return min(d, 360 - d)


def separating_axes(a: dict, b: dict) -> list[str]:
    out: list[str] = []
    if a["variant"] != b["variant"]:
        out.append("treatment")
    ta, tb = _to_hls(_rgb(a["text_color"])), _to_hls(_rgb(b["text_color"]))
    if _hue_gap(ta[0], tb[0]) >= 25 and min(ta[2], tb[2]) >= .15:
        out.append("text hue")
    if max(ta[2], tb[2]) >= .25 and min(ta[2], tb[2]) < .15:            # one clearly coloured, one near-grey
        out.append("text chroma")
    pa, pb = _to_hls(_rgb(a["bg_color"])), _to_hls(_rgb(b["bg_color"]))
    if abs(pa[1] - pb[1]) >= .08 or (_hue_gap(pa[0], pb[0]) >= 25 and min(pa[2], pb[2]) >= .2 and min(pa[1], pb[1]) >= .08):
        out.append("plate")
    ba, bb = _to_hls(_rgb(a["border_color"])), _to_hls(_rgb(b["border_color"]))
    if (_hue_gap(ba[0], bb[0]) >= 25 and min(ba[2], bb[2]) >= .25) or abs(ba[1] - bb[1]) >= .2:
        out.append("frame")
    if a["level"] != b["level"]:
        out.append("size")
    if str(a.get("minimap_icon", "")).split()[2:] != str(b.get("minimap_icon", "")).split()[2:]:
        out.append("icon")
    ea, eb = str(a.get("play_effect", "")), str(b.get("play_effect", ""))
    if bool(ea) != bool(eb) or ("Temp" in ea) != ("Temp" in eb):
        out.append("beam")
    if str(a.get("sound", "")).split()[:1] != str(b.get("sound", "")).split()[:1]:
        out.append("sound")
    return out


def family_separation(theme: FilterThemeName) -> dict[tuple[str, str], list[str]]:
    styles = {name: native_style(theme, role, tier) for name, (role, tier) in FAMILY_PROBES.items()}
    return {(x, y): separating_axes(styles[x], styles[y]) for x, y in itertools.combinations(FAMILY_PROBES, 2)}


# Probes of ONE user-facing family (the brief names "build gear bases" once): they share the enamel look on purpose.
SAME_FAMILY = frozenset({frozenset({"build_gear", "build_armour"})})


def required_axes(theme: FilterThemeName, pair: tuple[str, str]) -> int:
    """Two axes for every pair; one (the frame) for two ordinary families in a theme whose motif greys ordinary loot; none inside one family."""
    if frozenset(pair) in SAME_FAMILY:
        return 0
    return 1 if GRADES[theme].ash > 0 and set(pair) <= ASHED else 2


def theme_distance(a: FilterThemeName, b: FilterThemeName) -> float:
    total, count = 0.0, 0
    for role, tier in FAMILY_PROBES.values():
        sa, sb = native_style(a, role, tier), native_style(b, role, tier)
        for key in ("text_color", "border_color", "bg_color"):
            total += math.dist(_rgb(sa[key]), _rgb(sb[key]))
            count += 1
    return total / count


def policy_matrix(theme: FilterThemeName) -> list[dict]:
    """Per role: level, treatment, font, beam, minimap icon, sound (id / volume / word) and whether the profile can mute it."""
    rows = []
    for role, design in ROLE_DESIGNS.items():
        tier = BaseTier.T1 if role in TIER_LEVELS else None
        style = native_style(theme, role, tier)
        effect = str(style.get("play_effect", ""))
        sound = str(style.get("sound", ""))
        rows.append({
            "role": role, "family": design.family, "level": style["level"], "treatment": design.variant, "font": style["font_size"],
            "beam": "none" if not effect else ("temporary" if effect.endswith("Temp") else "persistent"),
            "beam_colour": effect.split()[0] if effect else "", "minimap_icon": str(style.get("minimap_icon", "")),
            "sound": sound, "sound_word": SOUND_POLICY[role][0] if role in SOUND_POLICY else "",
            "sound_in_every_profile": role in ALWAYS_SOUND_ROLES, "beam_policy": BEAM_POLICY.get(role, "none"),
        })
    return rows
