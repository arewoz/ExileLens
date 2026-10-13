"""First-match ground label simulation using the generated filter rules."""
from __future__ import annotations

import shlex
from dataclasses import dataclass
from functools import lru_cache

from exilelens.filters.rules import GeneratedRule
from exilelens.filters.verified_bases import load_base_properties


@dataclass(frozen=True)
class PreviewItem:
    name: str
    category: str
    item_class: str
    base_type: str = ""
    rarity: str = "Normal"
    item_level: int = 82
    area_level: int = 82
    quality: int = 0
    sockets: int = 0
    linked_sockets: int = 0
    unidentified_item_tier: int = 0
    waystone_tier: int = 0
    base_energy_shield: int = 0
    base_armour: int = 0
    base_evasion: int = 0
    corrupted: bool = False
    mirrored: bool = False
    stack_size: int = 1               # label text only: a stack count never takes part in any decision or style
    gem_level: int = 0                # GemLevel of an uncut gem (condition only; the label name is separate)

    @property
    def label(self) -> str:
        """What the game prints on the ground: stacks are prefixed (`20x Chaos Orb`)."""
        return f"{self.stack_size}x {self.name}" if self.stack_size > 1 else self.name


def _load_preview_samples():
    import json
    from pathlib import Path
    data = json.loads((Path(__file__).parent / "data" / "preview_scenes.json").read_text(encoding="utf-8"))
    return {key: tuple(PreviewItem(**item) for item in items) for key, items in data.items()}


_SAMPLES = _load_preview_samples()
PREVIEW_ITEMS = _SAMPLES["PREVIEW_ITEMS"]
SHOWCASE_ITEMS = _SAMPLES["SHOWCASE_ITEMS"]
REAL_GAME_ITEMS = _SAMPLES["REAL_GAME_ITEMS"]
HERO_CLUSTER_ITEMS = _SAMPLES["HERO_CLUSTER_ITEMS"]


@dataclass(frozen=True)
class PreviewDecision:
    hidden: bool
    rule_name: str
    stylesheet: str
    font_size: int = 27
    source: str = "Default"
    effect: str = ""
    importance: str = "LOW"
    native_details: str = "No matching filter rule; game default"
    reason: str = "No matching filter rule"
    minimap_icon: str = ""
    style_role: str = "default"
    border_hex: str = "#777777"
    provenance: str = "No generated-rule evidence"
    # FILTER-08C: compact BUILD / ITEMIZATION / CRAFT / MARKET / CONFIDENCE rows for this item (empty for legacy rules)
    sections: tuple = ()
    detail_lines: tuple = ()
    # profile system V2: the matrix row and the state (SHOW+ / SHOW / QUIET / HIDE / SAFETY) of the rule that decided this item
    row: str = ""
    state: str = ""


def preview_scene_items(preset: str) -> list[PreviewItem]:
    """Curated scene compositions; every item still uses first-match rules."""
    if preset == "Observed Currency":
        # Names visible together in the user's FILTER-08A game capture. This
        # preset changes only the sample scene, never generated filter rules.
        return [
            PreviewItem("Exalted Orb", "Currency", "Stackable Currency"),
            PreviewItem("Armourer's Scrap", "Currency", "Stackable Currency"),
            PreviewItem("Lesser Jeweller's Orb", "Currency", "Stackable Currency"),
        ]
    if preset == "Showcase":
        return list(SHOWCASE_ITEMS)
    if preset == "Real Game Cluster":
        return list(REAL_GAME_ITEMS)
    if preset == "Hero Cluster":
        return list(HERO_CLUSTER_ITEMS)
    items = list(PREVIEW_ITEMS)
    if preset == "Hero Drop":
        return [item for item in items if item.category not in {
            "Magic weapon", "Magic armour", "Low tier jewellery", "Low-priority build base",
        }][:21]
    if preset == "Value Dense":
        return [item for item in items if item.category not in {
            "Magic weapon", "Magic armour", "Low tier jewellery", "Rare boots",
        }]
    if preset == "Mixed Loot":
        return [item for item in items if item.category not in {
            "Magic armour", "Rare boots", "Low tier jewellery", "Trade equipment",
        }]
    return items


def visible_preview_entries(entries: list[tuple[PreviewItem, PreviewDecision]]) -> list[tuple[PreviewItem, PreviewDecision]]:
    """The sole preview displays only labels the generated filter shows."""
    return [(item, decision) for item, decision in entries if not decision.hidden]


_split = lru_cache(maxsize=4096)(lambda line: tuple(shlex.split(line)))


@lru_cache(maxsize=4096)
def _parsed_rule(lines: tuple[str, ...]):
    """Cache syntax by immutable contents, so edited rules cannot reuse a stale decision."""
    stripped = tuple(line.strip() for line in lines)
    action = next((line for line in stripped if line in {"Show", "Hide"}), None)
    conditions = tuple(line for line in stripped if line and not line.startswith(
        ("Show", "Hide", "Set", "Play", "MinimapIcon", "Continue", "DisableDropSound")))
    return action, conditions


def _matches_condition(line: str, item: PreviewItem) -> bool:
    parts = _split(line)
    if not parts:
        return True
    key, values = parts[0], parts[1:]
    if key == "Class":
        return any(value.casefold() in item.item_class.casefold() for value in values)
    if key == "BaseType":
        # one meaning for planner, IR, preview and serializer: exact (`==`) vs the native partial form (see base_match)
        from exilelens.filters.base_match import BaseCondition
        condition = BaseCondition.parse(line)
        return condition is not None and condition.matches(item.base_type or item.name)   # currency / bases without a separate base
    if key == "Rarity":
        return item.rarity.casefold() in (value.casefold() for value in values)
    if key in {"Corrupted", "Mirrored"}:
        return bool(values) and getattr(item, key.lower()) == (values[0].lower() == "true")
    numeric = {
        "ItemLevel": item.item_level, "AreaLevel": item.area_level,
        "Quality": item.quality, "Sockets": item.sockets,
        "LinkedSockets": item.linked_sockets, "UnidentifiedItemTier": item.unidentified_item_tier,
        "WaystoneTier": item.waystone_tier, "GemLevel": item.gem_level, "BaseEnergyShield": item.base_energy_shield,
        "BaseArmour": item.base_armour, "BaseEvasion": item.base_evasion,
    }
    if key in numeric and values:
        try:
            op, target = (values[0], int(values[1])) if values[0] in {">=", "<=", ">", "<", "="} else ("=", int(values[0]))
        except (IndexError, ValueError):
            return False
        actual = numeric[key]
        return {">=": actual >= target, "<=": actual <= target, ">": actual > target,
                "<": actual < target, "=": actual == target}[op]
    return False


def preview_decision(rules: list[GeneratedRule], item: PreviewItem) -> PreviewDecision:
    for rule in rules:
        action, conditions = _parsed_rule(tuple(rule.lines))
        if action is None:
            continue
        if not all(_matches_condition(line, item) for line in conditions):
            continue
        colors: dict[str, tuple[int, ...]] = {}
        font_size = 27
        effect = ""
        minimap_icon = ""
        sound = ""
        for line in rule.lines:
            parts = line.strip().split()
            if parts and parts[0] in {"SetTextColor", "SetBorderColor", "SetBackgroundColor"} and len(parts) >= 4:
                colors[parts[0]] = tuple(int(value) for value in parts[1:])
            elif parts and parts[0] == "SetFontSize" and len(parts) == 2:
                font_size = int(parts[1])
            elif parts and parts[0] == "PlayEffect" and len(parts) >= 2:
                effect = " ".join(parts[1:]) if parts[1] != "None" else ""
            elif parts and parts[0] == "MinimapIcon":
                minimap_icon = " ".join(parts[1:])
            elif parts and parts[0] == "PlayAlertSound":
                sound = " ".join(parts[1:])
        hidden = action == "Hide"
        if hidden:
            style_role = "hidden"
        elif getattr(rule, "role", ""):
            style_role = rule.role                     # profile system V2: the rule names the V4 role that styled it
        elif rule.category == "TRADE_HERO":
            style_role = "hero"
        elif rule.category == "TRADE_SPECIAL":
            style_role = "special"
        elif rule.category == "CURRENCY_TOP":
            style_role = "currency_premium"
        elif rule.category == "CURRENCY_PREMIUM":
            style_role = "premium_currency"
        elif rule.category == "CURRENCY_CRAFT":
            style_role = "crafting_currency"
        elif rule.category == "CURRENCY_VALUABLE":
            style_role = "currency_valuable"
        elif rule.category == "CURRENCY_LOW":
            style_role = "currency_low"
        elif rule.category == "PROTECTIVE":
            style_role = {"Currency": "currency", "Waystones": "waystone", "WaystonesHigh": "waystone_high",
                          "WaystonesMid": "waystone_mid", "Jewels": "jewel", "Charms": "charm",
                          "Uniques": "unique", "Socketables": "socketable",
                          "Tablets": "tablet",
                          "UncutGems": "gem",
                          "QuestItems": "quest", "HighUnidentifiedTier": "high_unid"}.get(rule.name, "currency")
        elif rule.category == "BUILD_WEAPON":
            style_role = ("fallback_weapon" if rule.evidence and
                          rule.evidence.build_relevance.startswith("Generic fallback") else "build_weapon")
        elif rule.category == "BUILD_DEFENSE":
            style_role = "build_defense"
        elif rule.category == "BUILD_JEWELLERY":
            style_role = "build_jewellery"
        elif rule.category == "BUILD_OFFHAND":
            style_role = "build_offhand"
        elif rule.category == "HIGH_VALUE_UNID":
            style_role = "high_unid"
        elif rule.category == "CRAFTING_BASES":
            style_role = "crafting_base"
        elif rule.category == "CRAFT_OPPORTUNITY":
            style_role = "craft_premium" if "_PREMIUM_" in rule.name else "craft_relevant"
        elif rule.category == "TRADE_BASES":
            style_role = ("trade_craft" if rule.name.endswith("_Craft") else
                          "trade_jewellery" if item.item_class in {"Rings", "Amulets", "Belts"} else
                          "trade_armour" if item.item_class in {"Body Armours", "Boots", "Gloves", "Helmets", "Shields"} else
                          "trade_weapon")
        else:
            style_role = "default"
        def css_color(key: str, fallback: str, default_alpha: int = 255) -> str:
            values = colors.get(key)
            if values is None:
                return fallback
            r, g, b = values[:3]
            alpha = values[3] if len(values) == 4 else default_alpha
            return f"rgba({r},{g},{b},{alpha / 255:.3f})"
        foreground = "#777e80" if hidden else css_color("SetTextColor", "#ddd")
        border = "#465052" if hidden else css_color("SetBorderColor", "#777")
        background = "#192124" if hidden else css_color("SetBackgroundColor", "#222", 240)
        source = "Hidden" if hidden else ("Fallback" if rule.evidence and rule.evidence.build_relevance.startswith("Generic fallback") else
                  "Build") if rule.category.startswith("BUILD") else (
            "Crafting" if rule.category in ("CRAFTING_BASES", "CRAFT_OPPORTUNITY") else (
            "Trade" if rule.category.startswith("TRADE") or rule.category in {"CURRENCY_TOP", "CURRENCY_PREMIUM", "CURRENCY_VALUABLE"} else (
                "Hidden" if hidden else "Protected" if rule.category in {"PROTECTIVE", "CURRENCY_CRAFT", "CURRENCY_LOW"} else "Other")))
        if hidden:
            importance = "HIDDEN"
            row = getattr(rule, "row", "")
            reason = (f"Hidden by the strictness policy: {row} is HIDE at this level (no more visible row claims the item)." if row else
                      f"Excluded by {rule.name} after higher-priority show rules did not match.")
        elif rule.category == "TRADE_HERO":
            importance = "HERO"
            reason = "Named exceptional currency from GGG's published PoE2 item list; trade relevance is heuristic."
        elif rule.category == "TRADE_SPECIAL":
            importance = "HIGH"
            reason = "Protected special-drop class; potential trade interest, not a live valuation."
        elif rule.category == "CURRENCY_TOP":
            importance = "HIGH"
            reason = "Top-tier currency on the curated loot-importance ladder (observed in game); not a live price."
        elif rule.category == "CURRENCY_VALUABLE":
            importance = "MEDIUM"
            reason = "Valuable currency on the curated loot-importance ladder (observed in game); not a live price."
        elif rule.category == "CURRENCY_LOW":
            importance = "LOW"
            reason = "Minor currency on the curated loot-importance ladder (observed in game); kept quiet, still shown."
        elif rule.category == "CURRENCY_PREMIUM":
            importance = "HIGH"
            reason = "Named enhanced currency from GGG's item list; prominent by category, with no live price claim."
        elif rule.category == "CURRENCY_CRAFT":
            importance = "MEDIUM"
            reason = "Named crafting currency from GGG's item list; useful category, with no live price claim."
        elif rule.category.startswith("BUILD"):
            importance = "HIGH" if font_size >= 41 else "MEDIUM" if font_size >= 29 else "LOW"
            reason = (rule.evidence.build_relevance if rule.evidence else
                      "Matches a base/slot heuristic; investigate, not a confirmed upgrade.")
        elif rule.category == "TRADE_BASES":
            importance = "HIGH" if font_size >= 41 else "MEDIUM"
            reason = "Build-independent, verified-base trade candidate with required item level or quality; price unverified."
        elif rule.category == "CRAFTING_BASES":
            importance = "MEDIUM"
            reason = "Quality normal base for potential crafting; no market price inferred."
        elif rule.category == "CRAFT_OPPORTUNITY":
            importance = "HIGH" if font_size >= 41 else "MEDIUM" if font_size >= 29 else "LOW"
            reason = (rule.class_reasons[0].text if rule.class_reasons else "Crafting substrate") + \
                "; independent of the build, no market price inferred."
        else:
            importance = "MEDIUM" if font_size >= 29 else "LOW"
            reason = "Protected general category or rare tier under this profile."
        native_parts = [f"font {font_size}"]
        for key, label in (("SetTextColor", "text"), ("SetBorderColor", "border"), ("SetBackgroundColor", "background")):
            if key in colors:
                native_parts.append(f"{label} {' '.join(map(str, colors[key]))}")
        if minimap_icon:
            native_parts.append(f"minimap {minimap_icon}")
        if effect:
            native_parts.append(f"ground effect {effect}")
        if sound:
            native_parts.append(f"sound {sound}")
        style = (f"color: {foreground}; background-color: {background}; border: 1px solid {border}; "
                 "border-radius: 0px; padding: 5px 10px;")
        border_rgb = colors.get("SetBorderColor", (119, 119, 119))
        border_hex = "#" + "".join(f"{component:02x}" for component in border_rgb[:3])
        base = load_base_properties().get(item.base_type or item.name)
        base_detail = ""
        if base:
            defenses = ", ".join(f"{key.replace('_', ' ')} {base[key]}" for key in
                                 ("armour", "evasion", "energy_shield", "ward") if base[key])
            base_detail = (f"; pinned base level {base['required_level']}; "
                           f"implicit {base['implicit'] or 'none'}; intrinsic defence {defenses or 'none'}")
        return PreviewDecision(hidden, rule.name, style, font_size, source, effect,
                               importance, "; ".join(native_parts), reason, minimap_icon,
                               style_role, border_hex,
                               (rule.evidence.explain() if rule.evidence else "No generated-rule evidence")
                               + base_detail,
                               tuple(rule.evidence.sections(item.base_type or None)) if rule.evidence and rule.evidence.coverage else (),
                               tuple(rule.evidence.detail_lines()) if rule.evidence and rule.evidence.coverage else (),
                               getattr(rule, "row", ""), getattr(rule, "state", ""))
    return PreviewDecision(False, "game default", "color: #c7c9c9; background-color: #283032; border: 1px solid #616c70; border-radius: 0px; padding: 5px 10px;")
