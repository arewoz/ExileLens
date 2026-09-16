"""Turn raw user feedback into a structured triage record. Does not patch code."""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Any

from poe2value.ops.regression import RegressionEntry, load_registry

_SUBSYSTEM_HINTS: dict[str, tuple[str, ...]] = {
    "game_client_input_ui": ("shift+c", "hotkey", "alt-tab", "overlay", "clipboard", "tray", "focus"),
    "item_slots_classes": ("helmet", "ring", "amulet", "boots", "gloves", "weapon", "capture", "tooltip"),
    "pob_import": ("stale", "reload", "build xml", "path of building", "wrong build"),
    "trade_api": ("price", "market", "comparables", "trade", "listing"),
    "currency_economy": ("divine", "exalted", "chaos", "fx", "currency"),
    "skills_gems": ("gem", "dps", "skill", "unsupported"),
    "defensive_mechanics": ("resist", "energy shield", "life", "armour", "evasion"),
    "passive_tree": ("passive", "tree", "notable", "keystone"),
}


@dataclass
class BugTriage:
    user_report: str
    expected: str
    actual: str
    environment: str
    reproduction_steps: list[str]
    likely_subsystem: str
    severity: str
    known_regression: str
    test_to_add: str
    root_cause: str
    fix: str
    verification: str
    matched_registry_ids: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def format_text(self) -> str:
        steps = "\n".join(f"  {index}. {step}" for index, step in enumerate(self.reproduction_steps, 1)) or "  (unknown)"
        return "\n".join(
            [
                f"USER REPORT: {self.user_report.strip()}",
                f"EXPECTED: {self.expected}",
                f"ACTUAL: {self.actual}",
                f"ENVIRONMENT: {self.environment}",
                "REPRODUCTION STEPS:",
                steps,
                f"LIKELY SUBSYSTEM: {self.likely_subsystem}",
                f"SEVERITY: {self.severity}",
                f"KNOWN REGRESSION?: {self.known_regression}",
                f"TEST TO ADD: {self.test_to_add}",
                f"ROOT CAUSE: {self.root_cause}",
                f"FIX: {self.fix}",
                f"VERIFICATION: {self.verification}",
            ]
        )


def infer_subsystem(text: str) -> str:
    lowered = text.lower()
    best = "unknown"
    hits = 0
    for subsystem, hints in _SUBSYSTEM_HINTS.items():
        score = sum(1 for hint in hints if hint in lowered)
        if score > hits:
            hits = score
            best = subsystem
    return best


def infer_severity(text: str) -> str:
    lowered = text.lower()
    if any(token in lowered for token in ("crash", "can't close", "cannot close", "data loss", "won't capture")):
        return "P0"
    if any(token in lowered for token in ("wrong", "stale", "broken", "always", "never")):
        return "P1"
    return "P2"


def match_registry(text: str, entries: list[RegressionEntry] | None = None) -> list[RegressionEntry]:
    lowered = text.lower()
    matched = []
    for entry in entries or load_registry():
        haystack = f"{entry.title} {entry.trigger}".lower()
        tokens = [token for token in re.findall(r"[a-z0-9+]+", haystack) if len(token) > 3]
        if sum(1 for token in tokens if token in lowered) >= 2:
            matched.append(entry)
    return matched


def triage_text(text: str, *, environment: str = "unspecified") -> BugTriage:
    matched = match_registry(text)
    subsystem = infer_subsystem(text)
    if matched:
        subsystem = matched[0].subsystem
    expected = "Behavior matches the documented/tested path for this subsystem"
    actual = text.strip().splitlines()[0][:240] if text.strip() else "unspecified"
    known = ", ".join(entry.id for entry in matched) if matched else "no"
    test = matched[0].tests[0] if matched and matched[0].tests else "Add a failing regression test before any patch"
    return BugTriage(
        user_report=text.strip(),
        expected=expected,
        actual=actual,
        environment=environment,
        reproduction_steps=["Reproduce locally with the same build XML and item text if provided"],
        likely_subsystem=subsystem,
        severity=infer_severity(text),
        known_regression=known,
        test_to_add=test,
        root_cause="unknown until reproduced",
        fix="Do not patch until reproduced or shown to be unreproducible. Then add a failing test.",
        verification="Focused test + regression-audit subset + python -m poe2value ops smoke",
        matched_registry_ids=[entry.id for entry in matched],
    )
