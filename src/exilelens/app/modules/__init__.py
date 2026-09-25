"""Static product capability gates."""

from exilelens.app.modules.registry import (
    FeatureModule,
    PARKED_MODULES,
    SUPPORTED_MODULES,
    is_enabled,
    is_module_parked,
    parking_enforced,
)

__all__ = [
    "FeatureModule",
    "PARKED_MODULES",
    "SUPPORTED_MODULES",
    "is_enabled",
    "is_module_parked",
    "parking_enforced",
]
