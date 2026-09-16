"""ITEM CHECK PRO settings — scoped to item check module."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any


class UpgradePotentialMode(str, Enum):
    OFF = "OFF"
    AUTO = "AUTO"
    AUTO_DEEP = "AUTO_DEEP"
    # Legacy values accepted during migration only.
    MANUAL = "MANUAL"
    AUTO_NEAR_MISS = "AUTO_NEAR_MISS"


def normalize_upgrade_mode(value: str | None) -> str:
    raw = str(value or "").upper()
    if raw in {UpgradePotentialMode.OFF.value, UpgradePotentialMode.AUTO.value, UpgradePotentialMode.AUTO_DEEP.value}:
        return raw
    if raw == "MANUAL":
        return UpgradePotentialMode.OFF.value
    if raw in {"AUTO_NEAR_MISS", "AUTO_SMART"}:
        return UpgradePotentialMode.AUTO_DEEP.value
    return UpgradePotentialMode.AUTO.value


def migrate_upgrade_potential_setting(data: dict[str, Any] | None) -> tuple[str, bool]:
    data = data or {}
    raw = data.get("upgrade_potential")
    explicit = bool(data.get("upgrade_potential_explicit")) or "upgrade_potential" in data
    if raw is None:
        return UpgradePotentialMode.AUTO.value, False
    raw = str(raw).upper()
    if raw == "MANUAL":
        if explicit:
            return UpgradePotentialMode.OFF.value, True
        return UpgradePotentialMode.AUTO.value, False
    if raw == "AUTO_NEAR_MISS":
        return UpgradePotentialMode.AUTO_DEEP.value, explicit
    return normalize_upgrade_mode(raw), explicit


@dataclass
class ItemCheckProSettings:
    decision_intelligence: bool = True
    best_replacement_slot: bool = True
    multi_profile: bool = True
    history_enabled: bool = True
    history_size: int = 50
    loot_review_enabled: bool = False
    upgrade_potential: str = UpgradePotentialMode.AUTO.value
    upgrade_potential_explicit: bool = False
    recommendation_style: str = "BALANCED"
    popup_density: str = "COMPACT"

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> ItemCheckProSettings:
        data = data or {}
        upgrade_mode, explicit = migrate_upgrade_potential_setting(data)
        return cls(
            decision_intelligence=bool(data.get("decision_intelligence", True)),
            best_replacement_slot=bool(data.get("best_replacement_slot", True)),
            multi_profile=bool(data.get("multi_profile", True)),
            history_enabled=bool(data.get("history_enabled", True)),
            history_size=int(data.get("history_size", 50)),
            loot_review_enabled=bool(data.get("loot_review_enabled", False)),
            upgrade_potential=normalize_upgrade_mode(upgrade_mode),
            upgrade_potential_explicit=explicit,
            recommendation_style=str(data.get("recommendation_style") or "BALANCED"),
            popup_density=str(data.get("popup_density") or "COMPACT"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "decision_intelligence": self.decision_intelligence,
            "best_replacement_slot": self.best_replacement_slot,
            "multi_profile": self.multi_profile,
            "history_enabled": self.history_enabled,
            "history_size": self.history_size,
            "loot_review_enabled": self.loot_review_enabled,
            "upgrade_potential": self.upgrade_potential,
            "upgrade_potential_explicit": self.upgrade_potential_explicit,
            "recommendation_style": self.recommendation_style,
            "popup_density": self.popup_density,
        }

    def clamp_history_size(self) -> int:
        if self.history_size <= 20:
            return 20
        if self.history_size <= 50:
            return 50
        return 100

    def upgrade_path_enabled(self) -> bool:
        return normalize_upgrade_mode(self.upgrade_potential) != UpgradePotentialMode.OFF.value

    def upgrade_path_deep(self) -> bool:
        return normalize_upgrade_mode(self.upgrade_potential) == UpgradePotentialMode.AUTO_DEEP.value
