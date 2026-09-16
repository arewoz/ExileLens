"""Known failure-mode registry and subset selection."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from poe2value.ops.paths import regression_registry_path, repo_root

PATH_HINTS: dict[str, tuple[str, ...]] = {
    "game_client_input_ui": (
        "hotkey",
        "clipboard",
        "overlay",
        "foreground",
        "tray",
        "capture",
        "platform/windows",
    ),
    "item_slots_classes": ("items/", "recognition", "slots", "supported_matrix"),
    "items_modifiers": ("items/", "evaluation", "ranking", "presentation"),
    "skills_gems": ("offense", "gem", "skills"),
    "pob_import": ("build_source", "build_reload", "build_cache", "build_revision", "engine", "worker", "pob/"),
    "trade_api": ("price_check/", "market/", "trade2"),
    "currency_economy": ("currency_fx", "comparable_pricing"),
    "passive_tree": ("tree/",),
    "defensive_mechanics": ("defence", "resist", "evaluation_outcome", "guardrail"),
}


@dataclass(frozen=True)
class RegressionEntry:
    id: str
    title: str
    subsystem: str
    trigger: str
    tests: tuple[str, ...]
    status: str
    severity: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "subsystem": self.subsystem,
            "trigger": self.trigger,
            "tests": list(self.tests),
            "status": self.status,
            "severity": self.severity,
        }


def load_registry(path: Path | None = None) -> list[RegressionEntry]:
    raw = json.loads((path or regression_registry_path(repo_root())).read_text(encoding="utf-8"))
    entries = []
    for item in raw.get("entries") or []:
        entries.append(
            RegressionEntry(
                id=str(item["id"]),
                title=str(item["title"]),
                subsystem=str(item["subsystem"]),
                trigger=str(item.get("trigger") or ""),
                tests=tuple(str(test) for test in item.get("tests") or []),
                status=str(item.get("status") or "unknown"),
                severity=str(item.get("severity") or "P2"),
            )
        )
    return entries


def select_for_subsystems(entries: Iterable[RegressionEntry], subsystems: Iterable[str]) -> list[RegressionEntry]:
    wanted = {item.strip() for item in subsystems if item.strip()}
    if not wanted:
        return list(entries)
    return [entry for entry in entries if entry.subsystem in wanted]


def select_for_changed_paths(entries: Iterable[RegressionEntry], changed_paths: Iterable[str]) -> list[RegressionEntry]:
    paths = [path.replace("\\", "/").lower() for path in changed_paths]
    if not paths:
        return []
    selected: list[RegressionEntry] = []
    for entry in entries:
        hints = PATH_HINTS.get(entry.subsystem, ())
        if any(any(hint in path for hint in hints) for path in paths):
            selected.append(entry)
            continue
        if any(any(test.lower().replace("\\", "/") in path or path.endswith(Path(test).name.lower()) for test in entry.tests) for path in paths):
            selected.append(entry)
    return selected


def paths_for_entries(entries: Iterable[RegressionEntry]) -> list[str]:
    tests: list[str] = []
    for entry in entries:
        for test in entry.tests:
            if test not in tests:
                tests.append(test)
    return tests
