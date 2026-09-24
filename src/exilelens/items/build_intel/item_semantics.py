"""Neutral item semantic parser. No market scores. No build scores."""

from __future__ import annotations

import re
from typing import Any

from exilelens.items.build_intel.models import ItemModFact, ItemSemanticModel, ModSource

_SECTION_BREAK = re.compile(r"^-{4,}$")
_NUMBER_RE = re.compile(r"[-+]?\d+(?:\.\d+)?")
_RARITY_RE = re.compile(r"^Rarity:\s*(\w+)", re.I)
_IMPLICITS_RE = re.compile(r"^Implicits:\s*(\d+)", re.I)

_PROPERTY_KEYS = (
    "energy shield",
    "armour",
    "evasion rating",
    "evasion",
    "block chance",
    "physical damage",
    "critical hit chance",
    "attacks per second",
    "reload time",
    "weapon range",
    "quality",
    "spirit",
)

_FAMILY_PATTERNS: list[tuple[str, str, str, tuple[str, ...]]] = [
    # family, group, contribution-ish tag, regex needles (lowercase)
    ("movement_speed", "movement", "mobility", ("increased movement speed", "to movement speed")),
    ("cast_speed", "cast_speed", "damage", ("increased cast speed",)),
    ("attack_speed", "attack_speed", "damage", ("increased attack speed", "increased attack and cast speed")),
    ("crit_chance", "crit", "damage", ("critical hit chance", "critical strike chance")),
    ("crit_multi", "crit", "damage", ("critical hit damage bonus", "critical strike multiplier", "critical damage bonus")),
    ("spell_damage", "spell_damage", "damage", ("increased spell damage",)),
    ("elemental_damage", "spell_damage", "damage", ("increased elemental damage",)),
    ("lightning_damage", "flat_pct_damage", "damage", ("increased lightning damage", "to lightning damage")),
    ("fire_damage", "flat_pct_damage", "damage", ("increased fire damage", "to fire damage")),
    ("cold_damage", "flat_pct_damage", "damage", ("increased cold damage", "to cold damage")),
    ("physical_damage", "flat_pct_damage", "damage", ("increased physical damage", "physical damage")),
    ("accuracy", "accuracy", "damage", ("to accuracy rating", "increased accuracy")),
    ("life", "life", "defence", ("to maximum life",)),
    ("energy_shield", "local_es", "defence", ("to maximum energy shield", "increased energy shield")),
    ("es_recharge", "recovery", "recovery", ("energy shield recharge",)),
    ("life_regen", "recovery", "recovery", ("life regeneration", "life regenerated")),
    ("mana", "mana", "resource", ("to maximum mana",)),
    ("mana_regen", "resource_gen", "resource", ("mana regeneration",)),
    ("spirit", "spirit", "resource", ("to spirit",)),
    ("fire_res", "resistance", "resistance", ("to fire resistance",)),
    ("cold_res", "resistance", "resistance", ("to cold resistance",)),
    ("lightning_res", "resistance", "resistance", ("to lightning resistance",)),
    ("chaos_res", "resistance", "resistance", ("to chaos resistance",)),
    ("all_res", "resistance", "resistance", ("to all elemental resistances",)),
    ("strength", "attributes", "attribute", ("to strength",)),
    ("dexterity", "attributes", "attribute", ("to dexterity",)),
    ("intelligence", "attributes", "attribute", ("to intelligence",)),
    ("all_attributes", "attributes", "attribute", ("to all attributes",)),
    ("armour", "armour", "defence", ("to armour", "increased armour")),
    ("evasion", "evasion", "defence", ("to evasion", "increased evasion")),
    ("block", "block", "defence", ("to block", "block chance")),
    ("skill_gem_levels", "enabler", "enabler", ("to level of all", "to level of")),
    ("leech", "recovery", "recovery", ("leech",)),
]

_ITEM_CLASS_NEEDLES: list[tuple[str, tuple[str, ...]]] = [
    ("BOOTS", ("sandals", "boots", "greaves", "shoes")),
    ("HELMET", ("helm", "helmet", "circlet", "crown", "hood", "mask")),
    ("GLOVES", ("gloves", "gauntlets", "mitts")),
    ("BODY_ARMOUR", ("armour", "robe", "regalia", "vest", "plate", "garb", "coat", "wrap")),
    ("BELT", ("belt", "sash")),
    ("AMULET", ("amulet", "talisman")),
    ("RING", ("ring",)),
    ("JEWEL", ("jewel",)),
    ("OFFHAND", ("focus", "shield", "buckler", "quiver")),
    ("ATTACK_WEAPON", ("bow", "crossbow", "sword", "axe", "mace", "spear", "quarterstaff", "claw", "dagger", "flail")),
    ("CASTER_WEAPON", ("wand", "staff", "sceptre")),
]


def classify_item_class(base_type: str, *, product_slot: str = "", item_type: str = "") -> str:
    blob = f"{base_type} {item_type}".lower()
    slot = (product_slot or "").upper()
    if slot in {"BOOTS", "HELMET", "GLOVES", "BODY_ARMOUR", "BELT", "AMULET"}:
        return slot
    if slot.startswith("RING"):
        return "RING"
    if slot.startswith("WEAPON"):
        for cls, needles in _ITEM_CLASS_NEEDLES:
            if cls in {"ATTACK_WEAPON", "CASTER_WEAPON", "OFFHAND"} and any(n in blob for n in needles):
                return cls
        return "ATTACK_WEAPON"
    if slot.startswith("OFFHAND"):
        return "OFFHAND"
    for cls, needles in _ITEM_CLASS_NEEDLES:
        if any(n in blob for n in needles):
            return cls
    return "UNKNOWN"


def _first_number(text: str) -> float | None:
    match = _NUMBER_RE.search(text.replace("%", ""))
    if not match:
        return None
    try:
        return float(match.group(0))
    except ValueError:
        return None


def classify_family(text: str) -> tuple[str, str, str]:
    lowered = text.lower()
    for family, group, tag, needles in _FAMILY_PATTERNS:
        if any(needle in lowered for needle in needles):
            return family, group, tag
    return "other", "other", "utility"


def _is_property_line(text: str) -> bool:
    lowered = text.lower()
    if ":" not in stripped_colon(lowered):
        return False
    key = lowered.split(":", 1)[0].strip()
    return any(key == needle or key.startswith(needle) for needle in _PROPERTY_KEYS)


def stripped_colon(text: str) -> str:
    return text


def _source_from_prefix(text: str) -> tuple[str, str]:
    raw = text
    source = ModSource.EXPLICIT.value
    if "{enchant}{rune}" in text or text.startswith("{enchant}{rune}"):
        source = ModSource.RUNE.value
        raw = re.sub(r"^\{enchant\}\{rune\}", "", text).strip()
    elif "{enchant}" in text:
        source = ModSource.ENCHANT.value
        raw = re.sub(r"^\{enchant\}", "", text).strip()
    elif text.lower().startswith("rune:"):
        source = ModSource.RUNE.value
    return source, raw


def parse_item_semantics(
    raw_text: str,
    *,
    metadata: dict[str, Any] | None = None,
    product_slot: str = "",
    item_type: str = "",
) -> ItemSemanticModel:
    metadata = metadata or {}
    text = (raw_text or "").replace("\r\n", "\n").replace("\r", "\n")
    lines = [line.strip() for line in text.split("\n") if line.strip()]
    rarity = str(metadata.get("rarity") or "")
    name = str(metadata.get("name") or "")
    base_type = str(metadata.get("base_type") or "")
    implicit_count = 0
    seen_name = bool(name)
    seen_base = bool(base_type)
    current_section: list[str] = []
    sections: list[list[str]] = []
    header_lines: list[str] = []
    body_started = seen_name and seen_base

    for line in lines:
        rarity_match = _RARITY_RE.match(line)
        if rarity_match:
            rarity = rarity_match.group(1).upper()
            continue
        implicits_match = _IMPLICITS_RE.match(line)
        if implicits_match:
            implicit_count = int(implicits_match.group(1))
            continue
        if _SECTION_BREAK.match(line):
            body_started = True
            if current_section:
                sections.append(current_section)
                current_section = []
            continue
        if not body_started:
            if not seen_name:
                name = line
                seen_name = True
                continue
            if not seen_base:
                base_type = line
                seen_base = True
                body_started = True
                continue
            header_lines.append(line)
            continue
        if _is_property_line(line) or line.lower().startswith("sockets:") or line.lower().startswith("levelreq:") or line.lower().startswith("item level:"):
            header_lines.append(line)
            continue
        if line.lower().startswith("rune:") and ":" in line and "{" not in line:
            header_lines.append(line)
            continue
        current_section.append(line)
    if current_section:
        sections.append(current_section)

    properties: list[ItemModFact] = []
    mods: list[ItemModFact] = []
    for line in header_lines:
        if _is_property_line(line) or line.lower().startswith("sockets:") or line.lower().startswith("rune:"):
            family, group, tag = classify_family(line)
            if ":" in line:
                key = line.split(":", 1)[0].strip().lower()
                if "energy shield" in key:
                    family, group, tag = "energy_shield", "base_es", "defence"
                elif "armour" in key:
                    family, group, tag = "armour", "base_armour", "defence"
                elif "evasion" in key:
                    family, group, tag = "evasion", "base_evasion", "defence"
                elif "attacks per second" in key:
                    family, group, tag = "attack_speed", "base_attack", "damage"
                elif "critical" in key:
                    family, group, tag = "crit_chance", "base_crit", "damage"
                elif "physical damage" in key:
                    family, group, tag = "physical_damage", "base_damage", "damage"
            properties.append(
                ItemModFact(
                    family=family,
                    source=ModSource.PROPERTY.value,
                    raw_text=line,
                    raw_value=_first_number(line),
                    base_related=True,
                    group=group,
                    synergy_tags=[tag, "base"],
                )
            )

    implicit_remaining = implicit_count
    for section in sections:
        for line in section:
            if line.lower() in {"corrupted", "unidentified", "mirrored"}:
                continue
            source, raw = _source_from_prefix(line)
            if implicit_remaining > 0 and source == ModSource.EXPLICIT.value:
                source = ModSource.IMPLICIT.value
                implicit_remaining -= 1
            family, group, tag = classify_family(raw)
            mods.append(
                ItemModFact(
                    family=family,
                    source=source,
                    raw_text=raw,
                    raw_value=_first_number(raw),
                    base_related=False,
                    group=group,
                    synergy_tags=[tag],
                )
            )

    item_class = classify_item_class(base_type, product_slot=product_slot, item_type=item_type)
    groups: dict[str, list[str]] = {}
    for fact in [*properties, *mods]:
        groups.setdefault(fact.group, []).append(fact.raw_text)

    return ItemSemanticModel(
        base_type=base_type,
        item_class=item_class,
        rarity=rarity,
        properties=properties,
        mods=mods,
        groups=groups,
    )


def strip_group_lines(raw_text: str, texts: list[str]) -> str:
    """Rebuild clipboard text without the given affix/property lines."""
    drop = {str(item).strip() for item in texts if str(item).strip()}
    if not drop:
        return raw_text
    out: list[str] = []
    for line in (raw_text or "").splitlines():
        stripped = line.strip()
        comparable = re.sub(r"^\{enchant\}\{rune\}", "", stripped).strip()
        comparable = re.sub(r"^\{enchant\}", "", comparable).strip()
        if stripped in drop or comparable in drop:
            continue
        out.append(line)
    return "\n".join(out).rstrip() + "\n"


def group_label(group: str) -> str:
    labels = {
        "movement": "Movement Speed",
        "cast_speed": "Cast Speed",
        "attack_speed": "Attack Speed",
        "crit": "Crit package",
        "spell_damage": "Spell Damage",
        "flat_pct_damage": "Damage",
        "life": "Maximum Life",
        "local_es": "Energy Shield",
        "base_es": "Base Energy Shield",
        "base_armour": "Base Armour",
        "base_evasion": "Base Evasion",
        "base_attack": "Base Attack Speed",
        "base_crit": "Base Crit",
        "base_damage": "Base Damage",
        "resistance": "Resistance",
        "attributes": "Attributes",
        "mana": "Mana",
        "resource_gen": "Resource generation",
        "recovery": "Recovery",
        "enabler": "Skill enabler",
        "other": "Other",
    }
    return labels.get(group, group.replace("_", " ").title())
