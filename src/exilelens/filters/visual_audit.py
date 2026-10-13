"""Perceptual QA for the filter visual system (V3, V4 floors). QA ONLY: nothing here feeds filter generation.

A label's native actions are measured against three representative worlds (dark floor, grey stone, bright fire) with the plaque's own alpha
composited over each, and a deliberately simple attention weight is derived so a scene can be audited for:

  * the importance ladder being monotone (MYTHIC > HIGH > VALUABLE > UTILITY > LOW) in every theme
  * adjacent importance levels being separable even when their hues are close
  * readability of every label on every world, including LOW
  * an attention budget: few dominant labels, very few white plaques

The weight is a QA instrument with documented ingredients (size, plaque / border / text contrast against the world, native effects). It is
not a score the generator may use and it is never written into a filter.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from statistics import mean

from exilelens.filters.style_system import LEVELS, WHITE_RED_TEXT_FLOOR, contrast

WORLDS: dict[str, tuple[int, int, int]] = {
    "dark floor": (22, 20, 18),
    "grey stone": (112, 108, 102),
    "bright fire": (238, 150, 66),
}
MIN_TEXT_CONTRAST = {"MYTHIC": 7.0, "HIGH": 6.0, "VALUABLE": 6.5, "UTILITY": 6.5, "LOW": 4.5}
# V4: the white / red apex is large text (41-45 pt) with a vivid red; its floor is 5 : 1 (WCAG AA normal text is 4.5 : 1).
TREATMENT_TEXT_CONTRAST = {"white_red": WHITE_RED_TEXT_FLOOR}
MIN_LEVEL_RATIO = 1.18          # mean attention of a level over the next lower level
DOMINANT_SHARE = 0.25           # MYTHIC + HIGH labels may be at most this share of a cluster (min. 3 labels)
WHITE_SHARE = 0.15              # white plaques may be at most this share (min. 3 labels)
WHITE_LUMINANCE = 0.55          # a plaque at least this bright counts as a white plaque


@dataclass(frozen=True)
class Native:
    role: str
    level: str
    family: str
    treatment: str
    font: int
    text: tuple[int, int, int, int]
    border: tuple[int, int, int, int]
    background: tuple[int, int, int, int]
    beam: str                    # "" | "temp" | "persistent"
    icon_size: int | None
    sound: str


def _rgba(text: str) -> tuple[int, int, int, int]:
    values = [int(v) for v in text.split()]
    return (values[0], values[1], values[2], values[3] if len(values) > 3 else 255)


def from_style(role: str, style: dict) -> Native:
    effect = str(style.get("play_effect", ""))
    icon = str(style.get("minimap_icon", "")).split()
    return Native(role, str(style["level"]), str(style["family"]), str(style["variant"]), int(style["font_size"]), _rgba(style["text_color"]),
                  _rgba(style["border_color"]), _rgba(style["bg_color"]),
                  "" if not effect else ("temp" if effect.endswith("Temp") else "persistent"),
                  int(icon[0]) if icon else None, str(style.get("sound", "")))


def composite(rgba: tuple[int, int, int, int], world: tuple[int, int, int]) -> tuple[int, int, int]:
    a = rgba[3] / 255
    return tuple(round(c * a + w * (1 - a)) for c, w in zip(rgba[:3], world))


def _luminance(rgb) -> float:
    def channel(c: int) -> float:
        v = c / 255
        return v / 12.92 if v <= .03928 else ((v + .055) / 1.055) ** 2.4
    r, g, b = (channel(c) for c in rgb)
    return .2126 * r + .7152 * g + .0722 * b


def min_text_contrast(native: Native) -> float:
    return TREATMENT_TEXT_CONTRAST.get(native.treatment, MIN_TEXT_CONTRAST[native.level])


@dataclass
class LabelMetrics:
    native: Native
    text_contrast: dict[str, float]
    plaque_vs_world: dict[str, float]
    border_delta: float                 # border / plaque contrast ratio on the darkest world
    background_luminance: float
    attention: float                    # QA weight (see module doc)
    white_plaque: bool
    flags: list[str] = field(default_factory=list)


def measure(native: Native) -> LabelMetrics:
    text_c, plaque_c = {}, {}
    for world, rgb in WORLDS.items():
        plaque = composite(native.background, rgb)
        text_c[world] = round(contrast(composite(native.text, plaque), plaque), 2)
        plaque_c[world] = round(contrast(plaque, rgb), 2)
    dark = composite(native.background, WORLDS["dark floor"])
    border_delta = round(contrast(composite(native.border, dark), dark), 2)
    bg_lum = _luminance(dark)
    size = (native.font / 30.0) ** 2
    ingredients = (0.50 * math.log(1 + (mean(plaque_c.values()) - 1)) + 0.30 * math.log(1 + (mean(text_c.values()) - 1) / 4)
                   + 0.20 * math.log(border_delta))
    effects = {"persistent": 0.45, "temp": 0.20, "": 0.0}[native.beam] + {0: 0.25, 1: 0.12, 2: 0.04, None: 0.0}[native.icon_size]
    attention = round(size * max(ingredients, 0.05) * (1 + effects), 4)
    flags = []
    need = min_text_contrast(native)
    if min(text_c.values()) < need:
        flags.append(f"UNREADABLE: text contrast {min(text_c.values())} < {need}")
    return LabelMetrics(native, text_c, plaque_c, border_delta, round(bg_lum, 3), attention, bg_lum >= WHITE_LUMINANCE and native.background[3] >= 200,
                        flags)


@dataclass
class SceneAudit:
    theme: str
    labels: list[tuple[str, LabelMetrics]]
    by_level: dict[str, float]
    flags: list[str]

    def summary(self) -> dict:
        return {"theme": self.theme, "labels": len(self.labels), "mean_attention_by_level": self.by_level, "flags": self.flags,
                "dominant": sum(m.native.level in ("MYTHIC", "HIGH") for _, m in self.labels),
                "white_plaques": [n for n, m in self.labels if m.white_plaque]}


def audit_scene(theme: str, labels: list[tuple[str, Native]]) -> SceneAudit:
    measured = [(name, measure(native)) for name, native in labels]
    by_level: dict[str, float] = {}
    for level in LEVELS:
        values = [m.attention for _, m in measured if m.native.level == level]
        if values:
            by_level[level] = round(mean(values), 4)
    flags: list[str] = []
    for name, m in measured:
        flags.extend(f"{name}: {f}" for f in m.flags)
    present = [l for l in LEVELS if l in by_level]
    for upper, lower in zip(present, present[1:]):
        if by_level[upper] < by_level[lower] * MIN_LEVEL_RATIO:
            kind = "MYTHIC_WEAKER_THAN_" + lower if upper == "MYTHIC" else f"{upper}_INDISTINGUISHABLE_FROM_{lower}"
            flags.append(f"{kind}: mean attention {by_level[upper]} vs {by_level[lower]} (needs x{MIN_LEVEL_RATIO})")
    if "MYTHIC" in by_level:
        weakest = min(m.attention for _, m in measured if m.native.level == "MYTHIC")
        louder = [n for n, m in measured if m.native.level != "MYTHIC" and m.attention >= weakest]
        if louder:
            flags.append(f"MYTHIC_OUTRANKED: {', '.join(louder[:4])}")
    total = len(measured)
    dominant = sum(m.native.level in ("MYTHIC", "HIGH") for _, m in measured)
    if total >= 6 and dominant > max(3, math.floor(DOMINANT_SHARE * total)):
        flags.append(f"TOO_MANY_DOMINANT: {dominant} of {total} labels are MYTHIC / HIGH")
    white = sum(m.white_plaque for _, m in measured)
    if total >= 6 and white > max(3, math.floor(WHITE_SHARE * total)):
        flags.append(f"TOO_MUCH_WHITE: {white} of {total} labels use a white plaque")
    return SceneAudit(theme, measured, by_level, flags)


_LEVEL_BY_FONT = {45: "MYTHIC", 41: "HIGH", 36: "VALUABLE", 30: "UTILITY", 25: "LOW"}


def _infer_treatment(actions: dict[str, str]) -> str:
    """Rules parsed back from filter TEXT carry no role: a white plate with red text is the white / red treatment (its own floor)."""
    import colorsys
    plate, text = _rgba(actions.get("SetBackgroundColor", "0 0 0 255")), _rgba(actions.get("SetTextColor", "255 255 255 255"))
    hue, _light, sat = colorsys.rgb_to_hls(*(c / 255 for c in text[:3]))
    red = hue * 360 <= 22 or hue * 360 >= 335
    return "white_red" if _luminance(plate[:3]) >= WHITE_LUMINANCE and red and sat >= .5 else "?"


def natives_from_rules(rules, items) -> list[tuple[str, Native]]:
    """The native actions the generated filter gives each visible item (first match), as measurable labels."""
    from exilelens.filters.preview import preview_decision
    from exilelens.filters.style_system import ROLE_DESIGNS
    index = {}
    for rule in rules:
        index.setdefault(rule.name, rule)
    out: list[tuple[str, Native]] = []
    for item in items:
        decision = preview_decision(rules, item)
        if decision.hidden or decision.rule_name == "game default":
            continue
        rule = index.get(decision.rule_name)
        if rule is None:
            continue
        actions: dict[str, str] = {}
        for line in rule.lines:
            parts = line.strip().split(None, 1)
            if len(parts) == 2 and parts[0].startswith(("Set", "Play", "MinimapIcon")):
                actions[parts[0]] = parts[1]
        if "SetFontSize" not in actions or int(actions["SetFontSize"]) not in _LEVEL_BY_FONT:
            continue
        role = decision.style_role
        design = ROLE_DESIGNS.get(role)
        effect = actions.get("PlayEffect", "")
        icon = actions.get("MinimapIcon", "").split()
        treatment = design.variant if design else _infer_treatment(actions)
        out.append((item.label, Native(
            role, _LEVEL_BY_FONT[int(actions["SetFontSize"])], design.family if design else "?", treatment,
            int(actions["SetFontSize"]), _rgba(actions.get("SetTextColor", "255 255 255 255")),
            _rgba(actions.get("SetBorderColor", "255 255 255 255")), _rgba(actions.get("SetBackgroundColor", "0 0 0 255")),
            "" if not effect else ("temp" if effect.endswith("Temp") else "persistent"),
            int(icon[0]) if icon else None, actions.get("PlayAlertSound", ""))))
    return out
