"""Validation for FILTER-01 generated filters.

Static validation of syntax, precedence, and profile hierarchy.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import List, Dict, Set, Tuple, Optional
from collections import defaultdict


from exilelens.filters.base_match import PARTIAL_MARKER
from exilelens.filters.verified_bases import FILTER_TO_POB_CLASS, SPECIAL_BASES as PINNED_SPECIAL_BASES, load_verified_bases, native_class


def _quoted_values(params: str) -> list[str] | None:
    """Return every exact quoted token, rejecting any hidden unquoted content."""
    if not re.fullmatch(r'\s*(?:==\s*)?(?:"[^"\n]+"\s*)+', params):
        return None
    return re.findall(r'"([^"\n]+)"', params)


def validate_base_types(filter_text: str) -> ValidationResult:
    """Check each serialized BaseType and its rule's Class against pinned PoB2 data."""
    result = ValidationResult(passed=True, errors=[], warnings=[])
    try:
        bases = load_verified_bases()
    except (OSError, ValueError, KeyError, TypeError) as exc:
        result.add_error(f"PoE2 base-item data unavailable: {exc}")
        return result

    rule_lines: list[tuple[int, str]] = []

    def check_rule() -> None:
        classes = []
        base_lines = []
        for number, content in rule_lines:
            keyword, _, params = content.partition(" ")
            if keyword == "Class":
                parsed = _quoted_values(params)
                if parsed is None:
                    result.add_error(f"Line {number}: malformed Class condition")
                else:
                    classes.extend(parsed)
            elif keyword == "BaseType":
                parsed = _quoted_values(params)
                if parsed is None:
                    result.add_error(f"Line {number}: malformed BaseType condition")
                else:
                    base_lines.append((number, parsed))
                    # a list of base identities must say EXACT (`==`): the bare form is a substring match in the native language
                    if not params.lstrip().startswith("==") and not any(c == "#MARK" for _, c in rule_lines):
                        result.add_error(f"Line {number}: partial BaseType match without an explicit PARTIAL_BASE_PATTERN marker "
                                         f"(use BaseType == for base identities)")
        expected = set()
        for cls in classes:
            mapped = FILTER_TO_POB_CLASS.get(cls)
            if mapped is None:
                if base_lines and cls not in PINNED_SPECIAL_BASES.values():
                    result.add_error(f"Class '{cls}' has no verified PoE2 equipment mapping")
            else:
                expected.add(mapped)
        for number, names in base_lines:
            if len(names) != len(set(names)):
                result.add_error(f"Line {number}: duplicate BaseType within rule")
            for name in names:
                actual = bases.get(name)
                if actual is None:
                    special_class = PINNED_SPECIAL_BASES.get(name)
                    if special_class is None:
                        from exilelens.filters.native_bases import rejection_reason
                        result.add_error(f"Line {number}: BaseType '{name}' absent from pinned PoE2 data "
                                         f"(not a native ground base - {rejection_reason(name)})")
                    elif special_class not in classes:
                        result.add_error(f"Line {number}: BaseType '{name}' requires Class '{special_class}'")
                elif expected and actual not in expected:
                    result.add_error(f"Line {number}: BaseType '{name}' is {actual}, incompatible with Class {classes}")
                elif expected and native_class(name) not in classes:
                    # Same PoB class, different native class (shield vs buckler): the filter would never match it.
                    result.add_error(f"Line {number}: BaseType '{name}' has native Class '{native_class(name)}', not {classes}")

    for number, line in enumerate(filter_text.splitlines(), 1):
        content = line.strip()
        if content in BLOCK_TYPES:
            check_rule()
            rule_lines = []
        elif content == PARTIAL_MARKER:
            rule_lines.append((number, "#MARK"))
        elif content and not content.startswith("#"):
            rule_lines.append((number, content))
    check_rule()
    return result


# Compatibility for callers of the old function; this now uses PoE2 data.
validate_base_types_against_repoe = validate_base_types


@dataclass
class ValidationResult:
    """Result of a validation check."""
    passed: bool
    errors: List[str]
    warnings: List[str]

    def __bool__(self) -> bool:
        return self.passed

    def add_error(self, msg: str) -> None:
        self.errors.append(msg)
        self.passed = False

    def add_warning(self, msg: str) -> None:
        self.warnings.append(msg)


# Valid PoE2 filter keywords (from official documentation)
VALID_CONDITIONS = {
    "Rarity", "Class", "BaseType", "ItemLevel", "AreaLevel", "DropLevel",
    "Quality", "Sockets", "LinkedSockets", "SocketGroup", "GemLevel",
    "GemQualityType", "AlternateQuality", "AlwaysShow", "AnyEnchantment",
    "ArchnemesisMod", "BaseArmour", "BaseEvasion", "BaseEnergyShield", "BaseWard",
    "BaseDefencePercentile", "BlightedMap", "Corrupted", "CorruptedMods",
    "ElderItem", "ElderMap", "EnchantmentPassiveNode", "EnchantmentPassiveNum",
    "Exceptional", "Foulborn", "FracturedItem", "HasCruciblePassiveTree",
    "HasEaterOfWorldsImplicit", "HasEnchantment", "HasExplicitMod", "HasImplicitMod",
    "HasInfluence", "HasSearingExarchImplicit", "HasVaalUniqueMod", "Height",
    "Identified", "Imbued", "IsVaalUnique", "MapTier", "MemoryStrands",
    "MirageMap", "Mirrored", "Scourged", "ShapedMap", "ShaperItem", "StackSize",
    "SynthesisedItem", "TransfiguredGem", "TwiceCorrupted", "UnidentifiedItemTier",
    "Vestigial", "WaystoneTier", "Width",
}

VALID_ACTIONS = {
    "SetFontSize", "SetTextColor", "SetBorderColor", "SetBackgroundColor",
    "PlayAlertSound", "PlayAlertSoundPositional", "CustomAlertSound",
    "CustomAlertSoundOptional", "DisableDropSound", "EnableDropSound",
    "DisableDropSoundIfAlertSound", "EnableDropSoundIfAlertSound",
    "MinimapIcon", "PlayEffect", "Continue",
}

VALID_RARITIES = {"Normal", "Magic", "Rare", "Unique"}
VALID_CLASSES = set(FILTER_TO_POB_CLASS) | {
    "Currency", "Stackable Currency", "Augment", "Tablet", "Quest Items",
    "Instance Local Items", "Waystone", "Waystones", "Omen",
    "Map Fragments", "Pinnacle Keys", "Skill Gems", "Support Gems",
    "Uncut Skill Gems", "Uncut Support Gems", "Uncut Spirit Gems",
    # real class of a declared utility name (`Vaal Siphoner`, PoE2DB class listing "Incubators"); see native_bases / the registry
    "Incubators",
}

# Exact action enum values from GGG's item-filter reference (checked 2026-09-26).
EFFECT_COLORS = {"Red", "Green", "Blue", "Brown", "White", "Yellow", "Cyan", "Grey", "Orange", "Pink", "Purple"}
ICON_SHAPES = {"Circle", "Diamond", "Hexagon", "Square", "Star", "Triangle", "Cross", "Moon", "Raindrop", "Kite", "Pentagon", "UpsideDownHouse"}
EMITTED_NUMERIC_CONDITIONS = {"ItemLevel", "AreaLevel", "Quality", "Sockets", "LinkedSockets", "UnidentifiedItemTier", "WaystoneTier", "GemLevel", "BaseArmour", "BaseEvasion", "BaseEnergyShield"}
EMITTED_BOOLEAN_CONDITIONS = {"Corrupted", "Mirrored"}

BLOCK_TYPES = {"Show", "Hide", "Minimal", "Import"}


def validate_syntax(filter_text: str) -> ValidationResult:
    """Fail closed on every non-comment line in serialized output."""
    result = ValidationResult(passed=True, errors=[], warnings=[])
    in_block = False
    for line_num, line in enumerate(filter_text.splitlines(), 1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped in {"Show", "Hide"}:
            in_block = True
            continue
        if not in_block:
            result.add_error(f"Line {line_num}: directive outside Show/Hide block: {stripped[:60]}")
            continue
        keyword, _, params = stripped.partition(" ")
        if keyword in {"SetFontSize", "SetTextColor", "SetBorderColor", "SetBackgroundColor", "PlayAlertSound", "MinimapIcon", "PlayEffect"}:
            _validate_action(keyword, params, line_num, result)
        elif keyword == "DisableDropSound":
            # documented flag; `True` is the form the most widely used live PoE2 community filter uses (style_system.HIDDEN_DROP_SOUND)
            if params.strip() not in {"", "True"}:
                result.add_error(f"Line {line_num}: invalid DisableDropSound value '{params}'")
        elif keyword in {"Class", "BaseType", "Rarity"} | EMITTED_NUMERIC_CONDITIONS | EMITTED_BOOLEAN_CONDITIONS:
            _validate_condition(keyword, params, line_num, result)
        else:
            result.add_error(f"Line {line_num}: unverified directive '{keyword}'")
    if not in_block:
        result.add_error("Filter has no Show/Hide blocks")
    return result


def _validate_action(keyword: str, params: str, line_num: int, result: ValidationResult) -> None:
    """Validate action parameters."""
    if keyword == "SetFontSize":
        try:
            size = int(params.strip())
            if not 1 <= size <= 45:
                result.add_error(f"Line {line_num}: SetFontSize must be 1-45, got {size}")
        except ValueError:
            result.add_error(f"Line {line_num}: SetFontSize requires numeric parameter")

    elif keyword in ("SetTextColor", "SetBorderColor", "SetBackgroundColor"):
        parts = params.strip().split()
        if len(parts) not in (3, 4):
            result.add_error(f"Line {line_num}: {keyword} requires 3 or 4 RGB(A) values")
        else:
            for p in parts:
                try:
                    val = int(p)
                    if not 0 <= val <= 255:
                        result.add_error(f"Line {line_num}: {keyword} values must be 0-255")
                except ValueError:
                    result.add_error(f"Line {line_num}: {keyword} requires numeric values")

    elif keyword in ("PlayAlertSound", "PlayAlertSoundPositional"):
        parts = params.strip().split()
        if len(parts) < 1 or len(parts) > 2:
            result.add_error(f"Line {line_num}: {keyword} requires sound ID (1-16) and optional volume (0-300)")
        else:
            try:
                sound_id = int(parts[0])
                if not 1 <= sound_id <= 16:
                    result.add_error(f"Line {line_num}: Sound ID must be 1-16")
                if len(parts) == 2:
                    volume = int(parts[1])
                    if not 0 <= volume <= 300:
                        result.add_error(f"Line {line_num}: Volume must be 0-300")
            except ValueError:
                result.add_error(f"Line {line_num}: {keyword} requires numeric parameters")

    elif keyword == "MinimapIcon":
        parts = params.strip().split()
        if parts == ["-1"]:
            return
        if len(parts) != 3:
            result.add_error(f"Line {line_num}: MinimapIcon requires size, color, shape")
        else:
            try:
                size = int(parts[0])
                if not 0 <= size <= 2:
                    result.add_error(f"Line {line_num}: MinimapIcon size must be 0-2")
            except ValueError:
                result.add_error(f"Line {line_num}: MinimapIcon size must be numeric")
            if parts[1] not in EFFECT_COLORS:
                result.add_error(f"Line {line_num}: invalid MinimapIcon color '{parts[1]}'")
            if parts[2] not in ICON_SHAPES:
                result.add_error(f"Line {line_num}: invalid MinimapIcon shape '{parts[2]}'")

    elif keyword == "PlayEffect":
        parts = params.strip().split()
        if parts != ["None"] and not (len(parts) in (1, 2) and parts[0] in EFFECT_COLORS and (len(parts) == 1 or parts[1] == "Temp")):
            result.add_error(f"Line {line_num}: invalid PlayEffect value '{params}'")


def _validate_condition(keyword: str, params: str, line_num: int, result: ValidationResult) -> None:
    """Validate every condition form used by this generator."""
    if keyword in {"Class", "BaseType"}:
        values = _quoted_values(params)
        if values is None:
            result.add_error(f"Line {line_num}: malformed {keyword} condition")
        elif keyword == "Class":
            for value in values:
                if value not in VALID_CLASSES:
                    result.add_error(f"Line {line_num}: unverified PoE2 Class '{value}'")
    elif keyword == "Rarity":
        values = params.split()
        if not values or any(value not in VALID_RARITIES for value in values):
            result.add_error(f"Line {line_num}: invalid Rarity values '{params}'")
    elif keyword in EMITTED_NUMERIC_CONDITIONS:
        if not re.fullmatch(r'\s*(?:>=|<=|=|>|<)\s*\d+\s*', params):
            result.add_error(f"Line {line_num}: invalid {keyword} numeric condition '{params}'")
    elif keyword in EMITTED_BOOLEAN_CONDITIONS:
        if params.strip() not in {"True", "False"}:
            result.add_error(f"Line {line_num}: invalid {keyword} boolean '{params}'")


def validate_precedence(filter_text: str) -> ValidationResult:
    """Validate rule precedence (Show before Hide for same items)."""
    result = ValidationResult(passed=True, errors=[], warnings=[])

    # Parse all rules with their base types
    show_rules = []  # (line_num, base_types)
    hide_rules = []  # (line_num, base_types)

    lines = filter_text.split("\n")
    in_block = False
    block_type = None
    current_base_types = []
    line_num = 0

    for line_num, line in enumerate(lines, 1):
        stripped = line.strip()

        if not stripped or stripped.startswith("#"):
            continue

        if stripped in BLOCK_TYPES:
            # Save previous block
            if in_block and current_base_types:
                if block_type == "Show":
                    show_rules.append((line_num, current_base_types.copy()))
                elif block_type == "Hide":
                    hide_rules.append((line_num, current_base_types.copy()))

            in_block = True
            block_type = stripped
            current_base_types = []
            continue

        if stripped.startswith("\tBaseType"):
            # Extract base types
            base_types = _extract_base_types(stripped)
            current_base_types.extend(base_types)

    # Don't forget last block
    if in_block and current_base_types:
        if block_type == "Show":
            show_rules.append((line_num, current_base_types.copy()))
        elif block_type == "Hide":
            hide_rules.append((line_num, current_base_types.copy()))

    # Check precedence: for each base type in both Show and Hide, Show must come first
    show_by_base = defaultdict(list)
    for line_num, bases in show_rules:
        for base in bases:
            show_by_base[base].append(line_num)

    for hide_line, bases in hide_rules:
        for base in bases:
            if base in show_by_base:
                show_lines = show_by_base[base]
                if all(sl > hide_line for sl in show_lines):
                    result.add_error(
                        f"Precedence violation: BaseType '{base}' hidden at line {hide_line} "
                        f"but shown at line(s) {show_lines} (Hide before Show)"
                    )

    return result


def _extract_base_types(line: str) -> List[str]:
    """Extract base type names from a BaseType condition line."""
    # Format: BaseType "Type1" "Type2" ...
    matches = re.findall(r'"([^"]+)"', line)
    return matches


def validate_profile_hierarchy(
    relaxed_text: str,
    recommended_text: str,
    strict_text: str,
) -> ValidationResult:
    """Validate Relaxed ��� Recommended ��� Strict hierarchy."""
    result = ValidationResult(passed=True, errors=[], warnings=[])

    # Parse shown base types from each filter
    relaxed_shows = _parse_show_bases(relaxed_text)
    recommended_shows = _parse_show_bases(recommended_text)
    strict_shows = _parse_show_bases(strict_text)

    # Check Strict ��� Recommended
    for base in strict_shows:
        if base not in recommended_shows:
            result.add_error(f"Profile hierarchy: '{base}' shown in Strict but hidden in Recommended")

    # Check Recommended ��� Relaxed
    for base in recommended_shows:
        if base not in relaxed_shows:
            result.add_error(f"Profile hierarchy: '{base}' shown in Recommended but hidden in Relaxed")

    # Check Strict hides are also hidden in Recommended (or shown)
    strict_hides = _parse_hide_bases(strict_text)
    recommended_hides = _parse_hide_bases(recommended_text)

    for base in strict_hides:
        if base in recommended_shows:
            result.add_warning(f"Profile hierarchy: '{base}' hidden in Strict but shown in Recommended")

    return result


def _parse_show_bases(filter_text: str) -> Set[str]:
    """Parse all base types from Show blocks."""
    bases = set()
    lines = filter_text.split("\n")
    in_show = False

    for line in lines:
        stripped = line.strip()
        if stripped == "Show":
            in_show = True
        elif stripped in ("Hide", "Minimal", "Import"):
            in_show = False
        elif in_show and stripped.startswith("\tBaseType"):
            bases.update(_extract_base_types(stripped))

    return bases


def _parse_hide_bases(filter_text: str) -> Set[str]:
    """Parse all base types from Hide blocks."""
    bases = set()
    lines = filter_text.split("\n")
    in_hide = False

    for line in lines:
        stripped = line.strip()
        if stripped == "Hide":
            in_hide = True
        elif stripped in ("Show", "Minimal", "Import"):
            in_hide = False
        elif in_hide and stripped.startswith("\tBaseType"):
            bases.update(_extract_base_types(stripped))

    return bases


def validate_determinism(
    filter_text1: str,
    filter_text2: str,
) -> ValidationResult:
    """Validate two filter outputs are identical."""
    result = ValidationResult(passed=True, errors=[], warnings=[])

    if filter_text1 != filter_text2:
        result.add_error("Filters are not byte-identical")
        # Find first difference
        for i, (c1, c2) in enumerate(zip(filter_text1, filter_text2)):
            if c1 != c2:
                result.add_error(f"First difference at char {i}: '{c1}' vs '{c2}'")
                break
        if len(filter_text1) != len(filter_text2):
            result.add_error(f"Length mismatch: {len(filter_text1)} vs {len(filter_text2)}")

    return result


def validate_all(filter_text: str) -> ValidationResult:
    """Run all static validations."""
    result = validate_syntax(filter_text)

    precedence_result = validate_precedence(filter_text)
    result.errors.extend(precedence_result.errors)
    result.warnings.extend(precedence_result.warnings)
    if not precedence_result.passed:
        result.passed = False

    base_type_result = validate_base_types_against_repoe(filter_text)
    result.errors.extend(base_type_result.errors)
    result.warnings.extend(base_type_result.warnings)
    if not base_type_result.passed:
        result.passed = False

    return result
