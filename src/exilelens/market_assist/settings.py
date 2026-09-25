from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class MarketAssistantRuntimeSettings:
    enabled: bool = False
    rapid_capture: bool = True
    suppress_item_popup: bool = True
    overlay_enabled: bool = True
    adaptive_guidance: bool = True
    ideal_target_mode: str = "MANUAL"

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> MarketAssistantRuntimeSettings:
        payload = data or {}
        return cls(
            enabled=bool(payload.get("enabled", False)),
            rapid_capture=bool(payload.get("rapid_capture", True)),
            suppress_item_popup=bool(payload.get("suppress_item_popup", True)),
            overlay_enabled=bool(payload.get("overlay_enabled", True)),
            adaptive_guidance=bool(payload.get("adaptive_guidance", True)),
            ideal_target_mode=str(payload.get("ideal_target_mode") or "MANUAL"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "rapid_capture": self.rapid_capture,
            "suppress_item_popup": self.suppress_item_popup,
            "overlay_enabled": self.overlay_enabled,
            "adaptive_guidance": self.adaptive_guidance,
            "ideal_target_mode": self.ideal_target_mode,
        }

    def session_defaults(self) -> dict[str, Any]:
        return {
            "rapid_capture": self.rapid_capture,
            "suppress_item_popup": self.suppress_item_popup,
            "overlay_enabled": self.overlay_enabled,
            "adaptive_guidance": self.adaptive_guidance,
            "ideal_target_mode": self.ideal_target_mode,
        }
