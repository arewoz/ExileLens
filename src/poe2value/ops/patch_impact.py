"""Classify PoE2 patch notes into subsystem impact. Never rewrites product code."""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterable

from poe2value.ops.models import ImpactLevel
from poe2value.ops.paths import patch_test_map_path, repo_root

CATEGORIES = (
    "items_modifiers",
    "skills_gems",
    "passive_tree",
    "defensive_mechanics",
    "currency_economy",
    "trade_api",
    "item_slots_classes",
    "game_client_input_ui",
    "pob_import",
    "irrelevant",
)

_CATEGORY_KEYWORDS: dict[str, tuple[str, ...]] = {
    "items_modifiers": (
        "affix",
        "modifier",
        "implicit",
        "explicit",
        "item class",
        "base type",
        "unique",
        "rare item",
        "magic item",
        "socket",
        "rune",
        "desecrat",
    ),
    "skills_gems": (
        "skill gem",
        "support gem",
        "spirit gem",
        "damage conversion",
        "ailment",
        "combo",
        "totem",
        "minion",
        "cast on",
        "skill",
        "gem",
    ),
    "passive_tree": (
        "passive tree",
        "passive skill",
        "notable",
        "keystone",
        "atlas tree",
        "weapon set",
        "node id",
    ),
    "defensive_mechanics": (
        "energy shield",
        "armour",
        "evasion",
        "resistance",
        "life",
        "ward",
        "block",
        "deflect",
        "stun",
        "overcapped",
    ),
    "currency_economy": (
        "divine",
        "exalted",
        "chaos orb",
        "currency",
        "exchange",
        "gold",
        "trade currency",
    ),
    "trade_api": (
        "trade site",
        "trade api",
        "pathofexile.com/api",
        "listing",
        "whisper",
        "market",
        "stash tab",
    ),
    "item_slots_classes": (
        "helmet",
        "body armour",
        "gloves",
        "boots",
        "belt",
        "amulet",
        "ring",
        "weapon",
        "offhand",
        "focus",
        "shield",
        "quiver",
        "jewel",
    ),
    "game_client_input_ui": (
        "clipboard",
        "shift+c",
        "hotkey",
        "alt-tab",
        "overlay",
        "client",
        "ui scale",
        "fullscreen",
    ),
    "pob_import": (
        "path of building",
        "pob",
        "import code",
        "passive tree code",
        "character import",
    ),
}

_HIGH = ("removed", "rework", "rewritten", "breaking", "disabled", "no longer", "replaced by")
_MEDIUM = ("changed", "adjusted", "added", "now", "instead", "increased", "reduced", "new gem", "new item")
_LOW = ("tooltip", "visual", "audio", "description", "wording", "art")


@dataclass
class ClassifiedEntry:
    text: str
    categories: list[str]
    impact: str
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class PatchImpactReport:
    game_version: str | None
    previous_verified_version: str | None
    patch_source: str
    entries: list[ClassifiedEntry] = field(default_factory=list)
    selected_tests: list[str] = field(default_factory=list)
    test_results: dict[str, Any] | None = None
    manual_verification_required: list[str] = field(default_factory=list)
    compatibility_decision: str = "UNVERIFIED"
    notes: list[str] = field(default_factory=list)

    @property
    def relevant_entries(self) -> list[ClassifiedEntry]:
        return [entry for entry in self.entries if "irrelevant" not in entry.categories]

    def counts(self) -> dict[str, int]:
        relevant = self.relevant_entries
        return {
            "total_relevant": len(relevant),
            "NO_IMPACT": sum(1 for entry in self.entries if entry.impact == ImpactLevel.NONE.value),
            "LOW": sum(1 for entry in relevant if entry.impact == ImpactLevel.LOW.value),
            "MEDIUM": sum(1 for entry in relevant if entry.impact == ImpactLevel.MEDIUM.value),
            "HIGH": sum(1 for entry in relevant if entry.impact == ImpactLevel.HIGH.value),
        }

    def affected_systems(self) -> list[str]:
        names: list[str] = []
        for entry in self.relevant_entries:
            for category in entry.categories:
                if category != "irrelevant" and category not in names:
                    names.append(category)
        return names

    def to_dict(self) -> dict[str, Any]:
        counts = self.counts()
        return {
            "game_version": self.game_version,
            "previous_verified_version": self.previous_verified_version,
            "patch_source": self.patch_source,
            "total_relevant_entries": counts["total_relevant"],
            "NO_IMPACT": counts["NO_IMPACT"],
            "LOW": counts["LOW"],
            "MEDIUM": counts["MEDIUM"],
            "HIGH": counts["HIGH"],
            "affected_systems": self.affected_systems(),
            "selected_tests": self.selected_tests,
            "test_results": self.test_results,
            "manual_verification_required": self.manual_verification_required,
            "compatibility_decision": self.compatibility_decision,
            "notes": self.notes
            + [
                "Patch-note wording MUST NOT be used to rewrite product behavior. "
                "Detection → analysis → tests first. Code changes require identified impact or failure."
            ],
            "entries": [entry.to_dict() for entry in self.entries],
        }


def parse_notes_text(text: str) -> list[str]:
    entries: list[str] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        line = re.sub(r"^[-*•]\s+", "", line)
        if len(line) >= 8:
            entries.append(line)
    return entries


def classify_entry(text: str) -> ClassifiedEntry:
    lowered = text.lower()
    matched: list[str] = []
    for category, keywords in _CATEGORY_KEYWORDS.items():
        if any(keyword in lowered for keyword in keywords):
            matched.append(category)
    if not matched:
        return ClassifiedEntry(text=text, categories=["irrelevant"], impact=ImpactLevel.NONE.value, reason="no subsystem keywords")
    if any(token in lowered for token in _HIGH):
        impact = ImpactLevel.HIGH.value
        reason = "removal/rework language"
    elif any(token in lowered for token in _MEDIUM):
        impact = ImpactLevel.MEDIUM.value
        reason = "mechanical change language"
    elif any(token in lowered for token in _LOW):
        impact = ImpactLevel.LOW.value
        reason = "presentation/tooltip language"
    else:
        impact = ImpactLevel.LOW.value
        reason = "keyword match without strong change verbs"
    return ClassifiedEntry(text=text, categories=matched, impact=impact, reason=reason)


def load_test_map(root: Path | None = None) -> dict[str, list[str]]:
    path = patch_test_map_path(root or repo_root())
    data = json.loads(path.read_text(encoding="utf-8"))
    return {key: list(value) for key, value in data.items() if isinstance(value, list)}


def select_tests(categories: Iterable[str], root: Path | None = None) -> list[str]:
    mapping = load_test_map(root)
    selected: list[str] = []
    for category in categories:
        for test in mapping.get(category, []):
            if test not in selected:
                selected.append(test)
    return selected


def classify_notes(
    entries: Iterable[str],
    *,
    game_version: str | None,
    previous_verified_version: str | None,
    patch_source: str,
    root: Path | None = None,
) -> PatchImpactReport:
    classified = [classify_entry(entry) for entry in entries]
    report = PatchImpactReport(
        game_version=game_version,
        previous_verified_version=previous_verified_version,
        patch_source=patch_source,
        entries=classified,
    )
    report.selected_tests = select_tests(report.affected_systems(), root)
    if report.counts()["HIGH"]:
        report.manual_verification_required.append("HIGH-impact entries present; in-game capture/eval required")
    if "game_client_input_ui" in report.affected_systems():
        report.manual_verification_required.append("Client/input changes cannot be fully proven offline")
    if not report.relevant_entries:
        report.compatibility_decision = "SUPPORTED"
        report.notes.append("No relevant patch entries classified. Still do not rewrite product code.")
    else:
        report.compatibility_decision = "UNVERIFIED"
        report.notes.append("Compatibility stays UNVERIFIED until selected tests and any manual checks pass.")
    return report
