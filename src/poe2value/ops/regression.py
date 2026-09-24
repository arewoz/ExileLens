"""Known regression registry with fail-closed source evidence validation."""

from __future__ import annotations

import ast
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from poe2value.ops.paths import regression_registry_path, repo_root

REGISTRY_VERSION = 2
REQUIRED_P0_IDS = frozenset({
    "hotkey-shift-c-after-focus", "item-capture-fail", "overlay-missing",
    "overlay-unrecoverable", "stale-pob-build",
})
VALID_SEVERITIES = frozenset({"P0", "P1", "P2"})
VALID_STATUSES = frozenset({"covered", "uncovered", "open", "broken"})

PATH_HINTS: dict[str, tuple[str, ...]] = {
    "game_client_input_ui": ("hotkey", "clipboard", "overlay", "foreground", "tray", "capture", "platform/windows"),
    "item_slots_classes": ("items/", "recognition", "slots", "supported_matrix"),
    "items_modifiers": ("items/", "evaluation", "ranking", "presentation"),
    "skills_gems": ("offense", "gem", "skills"),
    "pob_import": ("build_source", "build_reload", "build_cache", "build_revision", "engine", "worker", "pob/"),
    "trade_api": ("price_check/", "market/", "trade2"),
    "currency_economy": ("currency_fx", "comparable_pricing"),
    "passive_tree": ("tree/",),
    "defensive_mechanics": ("defence", "resist", "evaluation_outcome", "guardrail"),
}


class RegressionRegistryError(ValueError):
    """Registry is missing, malformed, or claims unverifiable coverage."""


@dataclass(frozen=True)
class RegressionEvidence:
    path: str
    nodeid: str

    def to_dict(self) -> dict[str, str]:
        return {"path": self.path, "nodeid": self.nodeid}


@dataclass(frozen=True)
class RegressionEntry:
    id: str
    title: str
    subsystem: str
    trigger: str
    tests: tuple[RegressionEvidence, ...]
    status: str
    severity: str
    coverage_gap: str = ""

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "id": self.id,
            "title": self.title,
            "subsystem": self.subsystem,
            "trigger": self.trigger,
            "tests": [test.to_dict() for test in self.tests],
            "status": self.status,
            "severity": self.severity,
        }
        if self.coverage_gap:
            payload["coverage_gap"] = self.coverage_gap
        return payload


def _test_function_names(path: Path) -> set[str]:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except (OSError, SyntaxError) as exc:
        raise RegressionRegistryError(f"cannot inspect test source {path}: {exc}") from exc
    return {node.name for node in ast.walk(tree) if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))}


def _parse_evidence(raw: Any, *, root: Path, entry_id: str, index: int) -> RegressionEvidence:
    if not isinstance(raw, dict):
        raise RegressionRegistryError(f"{entry_id}.tests[{index}] must be an object with path and nodeid")
    path = raw.get("path")
    nodeid = raw.get("nodeid")
    if not isinstance(path, str) or not path.startswith("tests/") or not path.endswith(".py"):
        raise RegressionRegistryError(f"{entry_id}.tests[{index}].path must be a relative tests/*.py path")
    if Path(path).is_absolute() or ".." in Path(path).parts:
        raise RegressionRegistryError(f"{entry_id}.tests[{index}].path must not escape the checkout")
    if not isinstance(nodeid, str) or nodeid.count("::") != 1:
        raise RegressionRegistryError(f"{entry_id}.tests[{index}].nodeid must be path::test_function")
    node_path, function_name = nodeid.split("::", 1)
    if node_path != path or not function_name.startswith("test_") or "[" in function_name:
        raise RegressionRegistryError(f"{entry_id}.tests[{index}].nodeid must exactly identify an unparameterized test")
    source = root / path
    if not source.is_file():
        raise RegressionRegistryError(f"{entry_id}.tests[{index}] references missing test file: {path}")
    if function_name not in _test_function_names(source):
        raise RegressionRegistryError(f"{entry_id}.tests[{index}] references missing test identity: {nodeid}")
    return RegressionEvidence(path=path, nodeid=nodeid)


def _parse_entry(raw: Any, *, root: Path, index: int) -> RegressionEntry:
    if not isinstance(raw, dict):
        raise RegressionRegistryError(f"entries[{index}] must be an object")
    required_text = ("id", "title", "subsystem", "trigger", "status", "severity")
    missing = [key for key in required_text if not isinstance(raw.get(key), str) or not raw[key].strip()]
    if missing:
        raise RegressionRegistryError(f"entries[{index}] missing required text fields: {', '.join(missing)}")
    entry_id = raw["id"].strip()
    status = raw["status"].strip()
    severity = raw["severity"].strip()
    if severity not in VALID_SEVERITIES:
        raise RegressionRegistryError(f"{entry_id}.severity must be one of {sorted(VALID_SEVERITIES)}")
    if status not in VALID_STATUSES:
        raise RegressionRegistryError(f"{entry_id}.status must be one of {sorted(VALID_STATUSES)}")
    raw_tests = raw.get("tests")
    if not isinstance(raw_tests, list):
        raise RegressionRegistryError(f"{entry_id}.tests must be a list")
    tests = tuple(_parse_evidence(item, root=root, entry_id=entry_id, index=i) for i, item in enumerate(raw_tests))
    if status == "covered" and not tests:
        raise RegressionRegistryError(f"{entry_id} is marked covered but has no verified test evidence")
    coverage_gap = str(raw.get("coverage_gap") or "").strip()
    if status != "covered" and not coverage_gap:
        raise RegressionRegistryError(f"{entry_id} status={status} requires coverage_gap")
    if status == "covered" and coverage_gap:
        raise RegressionRegistryError(f"{entry_id} is covered and must not declare coverage_gap")
    return RegressionEntry(
        id=entry_id,
        title=raw["title"].strip(),
        subsystem=raw["subsystem"].strip(),
        trigger=raw["trigger"].strip(),
        tests=tests,
        status=status,
        severity=severity,
        coverage_gap=coverage_gap,
    )


def load_registry(path: Path | None = None, *, root: Path | None = None) -> list[RegressionEntry]:
    registry_path = path or regression_registry_path(repo_root())
    checkout = root or registry_path.resolve().parents[1]
    try:
        raw = json.loads(registry_path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise RegressionRegistryError(f"regression registry missing: {registry_path}") from exc
    except json.JSONDecodeError as exc:
        raise RegressionRegistryError(f"regression registry is not valid JSON: {exc}") from exc
    if not isinstance(raw, dict):
        raise RegressionRegistryError("regression registry root must be an object")
    if raw.get("version") != REGISTRY_VERSION:
        raise RegressionRegistryError(f"regression registry version must be {REGISTRY_VERSION}")
    raw_entries = raw.get("entries")
    if not isinstance(raw_entries, list) or not raw_entries:
        raise RegressionRegistryError("regression registry entries must be a non-empty list")
    entries = [_parse_entry(item, root=checkout, index=index) for index, item in enumerate(raw_entries)]
    ids = [entry.id for entry in entries]
    duplicates = sorted({entry_id for entry_id in ids if ids.count(entry_id) > 1})
    if duplicates:
        raise RegressionRegistryError("regression registry has duplicate ids: " + ", ".join(duplicates))
    missing_p0 = sorted(REQUIRED_P0_IDS - set(ids))
    if missing_p0:
        raise RegressionRegistryError("regression registry missing required P0 entries: " + ", ".join(missing_p0))
    for entry in entries:
        if entry.id in REQUIRED_P0_IDS and entry.severity != "P0":
            raise RegressionRegistryError(f"required regression {entry.id} must remain severity P0")
    return entries


def mandatory_p0_test_nodeids(entries: Iterable[RegressionEntry]) -> list[str]:
    p0_entries = [entry for entry in entries if entry.severity == "P0"]
    uncovered = [entry.id for entry in p0_entries if entry.status != "covered"]
    if uncovered:
        raise RegressionRegistryError("required P0 regressions are not covered: " + ", ".join(uncovered))
    nodeids = [test.nodeid for entry in p0_entries for test in entry.tests]
    if not nodeids:
        raise RegressionRegistryError("no mandatory P0 regression tests are declared")
    return list(dict.fromkeys(nodeids))


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
        if any(
            any(test.path.lower() in path or path.endswith(Path(test.path).name.lower()) for test in entry.tests)
            for path in paths
        ):
            selected.append(entry)
    return selected


def paths_for_entries(entries: Iterable[RegressionEntry]) -> list[str]:
    nodeids: list[str] = []
    for entry in entries:
        for test in entry.tests:
            if test.nodeid not in nodeids:
                nodeids.append(test.nodeid)
    return nodeids
